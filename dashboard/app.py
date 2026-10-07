"""FastAPI app factory for the agx02 dashboard. Read routes, the model controller (dashboard/control_api.py) and the
pairing of RK boards (dashboard/pairing_api.py, docs/PAIRING_API.md) are the only write routes."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from common.env import PROJECT_ROOT, get, load_env
from common.pairing_store import PairingStore
from dashboard import control_api, pairing_api, power_api
from dashboard.auth import GuardMiddleware, LoginFails
from dashboard.collectors.engines import EngineScanner
from dashboard.collectors.health import HealthCollector, worst
from dashboard.collectors.infer_status import InferStatusClient
from dashboard.collectors.link import LinkMonitor
from dashboard.collectors.services import ServicesCollector
from dashboard.config import resolve_path
from dashboard.history import History
from dashboard.infer_views import InferViews
from dashboard.mqtt_pub import start_mqtt
from dashboard.power_log import PowerLogger

log = logging.getLogger("dashboard.app")

STATIC_DIR = Path(__file__).resolve().parent / "static"
HEALTH_SCHEMA = "agx-health/1"
METRIC_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
INFER_TO_LEVEL = {"RUNNING": "ok", "STARTING": "warn", "DEGRADED": "warn", "ERROR": "crit"}
HEALTH_STALE_S = 3.0  # a health sample older than this is not "current"
STREAM_PERIOD_S = 1.0  # SSE: one event each second, and one event at once for each new agx-infer status
STREAM_POLL_S = 0.05   # SSE: how often the stream looks for a new agx-infer status
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def label_simulated(doc, label: str = "SIMULATED"):
    """R13: each dict (at any depth) with "simulated": true gets "label": "SIMULATED" when its label
    is missing or empty. Changes doc in place and returns it."""
    if isinstance(doc, dict):
        if doc.get("simulated") is True and not doc.get("label"):
            doc["label"] = label
        for v in doc.values():
            label_simulated(v, label)
    elif isinstance(doc, list):
        for v in doc:
            label_simulated(v, label)
    return doc


class SecurityHeaders:
    """Pure ASGI: add security headers to every HTTP response (does not buffer SSE)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def _send(msg):
            if msg["type"] == "http.response.start":
                h = list(msg.get("headers") or [])
                h += [(b"content-security-policy", CSP.encode()),
                      (b"x-content-type-options", b"nosniff"),
                      (b"referrer-policy", b"no-referrer"),
                      (b"x-frame-options", b"DENY")]
                msg = dict(msg, headers=h)
            await send(msg)
        return await self.app(scope, receive, _send)


class Hub:
    """Holds the collectors and builds the API documents."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.health = HealthCollector(cfg)
        self.link = LinkMonitor(cfg)
        self.services = ServicesCollector(cfg)
        self.infer = InferStatusClient(cfg["infer_status_endpoint"], cfg.get("infer_stale_s", 3))
        h = cfg["history"]
        self.history = History(resolve_path(h["db"]), h["max_mb"], h["memory_s"], h["db_step_s"],
                               h["db_keep_s"], h["cleanup_interval_s"])
        ec = cfg.get("engines") or {}
        scan_dirs = ec.get("scan_dirs")
        if scan_dirs is None:
            from tools.inspect_engines import DEFAULT_SCAN
            scan_dirs = list(DEFAULT_SCAN)
        self.views = InferViews(self.infer, None, resolve_path(cfg.get("models_config")),
                                resolve_path(cfg.get("sources_config")), cfg.get("infer_stale_s", 3),
                                cfg.get("camera_status_jitter_s", 0.3))
        self.engines = EngineScanner(resolve_path(ec.get("cache") or "data/engines_cache.json"),
                                     [str(resolve_path(d)) for d in scan_dirs], self.views.config_engines,
                                     ec.get("scan_interval_s", 1800), ec.get("inspect_timeout_s", 120))
        self.views.scanner = self.engines
        self.health.add_listener(self._on_sample)
        self.pairing = None          # create_app sets it (the power log reads the link state of the paired board)
        self.power = PowerLogger(cfg, self)   # opens data/power.sqlite in start(), not here
        self.mqtt = None
        self.controller = None
        self.controller_error = None
        if cfg.get("model_control", True):
            try:  # the model controller (controller/): the dashboard must start also when it cannot
                from controller.control import from_config
                self.controller = from_config(cfg, PROJECT_ROOT, self.infer)
            except Exception as e:
                log.exception("model controller not started")
                self.controller_error = f"model controller not started: {e}"

    def _on_sample(self, s: dict):
        m = {
            "gpu_load_pct": s["gpu"]["load_pct"],
            "ram_used_pct": s["ram"]["pct"],
            "temp_max_c": s["temps"]["max_c"],
            "power_total_w": s["power"]["total_w"],
            "cpu_load_avg_pct": s["cpu"]["load_pct_avg"],
        }
        try:
            m.update(self.infer.metrics())
        except Exception:  # a bad agx-infer status must not stop the health history
            log.exception("infer metrics failed")
        self.history.add(s["t"], m)

    def start(self, env: dict):
        self.history.start()
        self.infer.start()
        self.health.start()
        self.link.start()
        self.services.start()
        self.engines.start()
        if self.controller is not None:
            try:
                self.controller.start()
            except Exception as e:  # the dashboard must keep running
                log.exception("model controller start failed")
                self.controller_error = f"model controller start failed: {e}"
        try:
            self.power.start()
        except Exception as e:  # the dashboard must keep running without the power log
            log.exception("power log start failed")
            self.power.error = f"power log start failed: {e}"
        self.mqtt = start_mqtt(env, self.health_doc, self.cfg.get("mqtt_interval_s", 5))

    def stop(self):
        for c in (self.mqtt, self.controller, self.health, self.power, self.link, self.services, self.engines,
                  self.infer, self.history):
            if c is not None:
                try:
                    c.stop()
                except Exception:
                    log.exception("stop failed")

    def link_doc(self) -> dict:
        d = self.link.summary()
        d.update(self.infer.link_part(hold_s=self.views.hold_s()))
        return d

    def infer_doc(self, inf: dict, now: float) -> dict | None:
        if inf["infer"] is None:
            return None
        try:
            return dict(inf["infer"], **self.views.health_infer_extra(now))
        except Exception as e:  # keep /api/health and the SSE stream alive
            log.exception("infer summary failed")
            return dict(inf["infer"], extra_error=f"infer summary failed: {e}")

    def health_doc(self) -> dict:
        s = self.health.latest() or self.health.sample()
        inf = self.infer.summary()
        now = time.time()
        age = round(now - s["t"], 1)
        stale = age > HEALTH_STALE_S
        levels = [s["temps"]["level"], s["ram"]["level"]] + [d["level"] for d in s["disk"]]
        reasons = []
        if s["temps"]["level"] == "n/a":
            reasons.append("temperature n/a (no thermal zone readable)")
        if s["ram"]["level"] == "n/a":
            reasons.append("RAM n/a (" + str(s["ram"].get("na") or "not readable") + ")")
        if s["temps"]["level"] in ("warn", "crit"):
            reasons.append(f"temperature {s['temps']['max_c']} C ({s['temps']['max_zone']})")
        if s["ram"]["level"] in ("warn", "crit"):
            reasons.append(f"RAM {s['ram']['pct']} %")
        for d in s["disk"]:
            if d["level"] in ("warn", "crit"):
                reasons.append(f"disk {d['mount']} {d['pct']} %")
        node_source = "local limits"
        if inf["infer"] is not None:
            il = INFER_TO_LEVEL.get(inf["infer_state"], "warn")
            levels.append(il)
            node_source = "local limits + agx-infer"
            if il != "ok":
                reasons.append(f"agx-infer {inf['infer_state']}")
        real = [lv for lv in levels if lv in ("ok", "warn", "crit")]
        if stale:
            node_state = "UNKNOWN"
            reasons.insert(0, f"health sample stale ({age} s old): values are not current")
        elif not real:
            node_state = "UNKNOWN"
            reasons.insert(0, "no measured input (temperature, RAM, disk and agx-infer are n/a)")
        else:
            node_state = worst(real).upper()
        doc = {
            "schema": HEALTH_SCHEMA,
            "hostname": s["hostname"],
            "time": round(s["t"], 3),
            "time_iso": s["time_iso"],
            "age_s": age,
            "stale": stale,
            "uptime_s": s["uptime_s"],
            "node_state": node_state,
            "node_state_source": node_source,
            "node_state_reasons": reasons,
            "nvpmodel": s["nvpmodel"],
            "cpu": s["cpu"],
            "gpu": s["gpu"],
            "ram": s["ram"],
            "swap": s["swap"],
            "temps": s["temps"],
            "power": s["power"],
            "fan": s["fan"],
            "disk": s["disk"],
            "net": s["net"],
            "link": self.link_doc(),
            "infer": self.infer_doc(inf, now),
            "infer_state": inf["infer_state"],
            "infer_reason": inf["infer_reason"],
            "simulated": bool(inf["infer"] and inf["infer"]["simulated"]),
            "label": "SIMULATED" if (inf["infer"] and inf["infer"]["simulated"]) else None,
            "limits": self.cfg["limits"],
            "errors": list(s["errors"]),
        }
        if stale:
            doc["errors"].append(f"health sample stale: last good sample {age} s old")
        if self.history.db_error:
            doc["errors"].append(self.history.db_error)
        return label_simulated(doc)  # R13 safety net: no simulated object without its label


def create_app(cfg: dict, env: dict | None = None, start_collectors: bool = True,
               migrate: bool | None = None) -> FastAPI:
    """migrate (default: start_collectors, i.e. a real start): the one-time pairing migration of the old control
    token file (docs/PAIRING_API.md). Tests that do not test it give start_collectors=False and touch no file."""
    if env is None:
        env = load_env(resolve_path(cfg.get("env_file", ".env")))
    user = get(env, "AGX_DASH_USER", "agx")
    password = get(env, "AGX_DASH_PASSWORD")
    if not password:
        raise RuntimeError("AGX_DASH_PASSWORD is not set in .env: refuse to start without a password")

    hub = Hub(cfg)

    @asynccontextmanager
    async def lifespan(app):
        if start_collectors:
            hub.start(env)
        yield
        hub.stop()

    app = FastAPI(title="agx02 dashboard", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.hub = hub
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def nocache(data, status=200):
        return JSONResponse(data, status_code=status, headers={"cache-control": "no-store"})

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"cache-control": "no-cache"})

    @app.get("/api/health")
    def api_health():
        return nocache(hub.health_doc())

    @app.get("/api/link")
    def api_link():
        d = hub.link_doc()
        d["ping_history"] = hub.link.ping_history(3600)
        return nocache(d)

    @app.get("/api/services")
    def api_services():
        d = hub.services.snapshot()
        d["summary"] = hub.services.summary()
        return nocache(d)

    @app.get("/api/services/logs")
    def api_logs(unit: str = Query(...)):
        if unit not in hub.services.log_units:
            return nocache({"error": "unit not allowed", "allowed": hub.services.log_units}, 400)
        return nocache(hub.services.logs(unit, 100))

    @app.get("/api/models")
    def api_models():
        return nocache(hub.views.models_doc())

    @app.get("/api/cameras")
    def api_cameras():
        return nocache(hub.views.cameras_doc())

    @app.get("/api/cameras/{cam}/snapshot.jpg")
    def api_snapshot(cam: int):
        if not 0 <= cam <= 5:
            return nocache({"error": "camera index must be 0..5"}, 404)
        st, state, reason, _ = hub.infer.current()
        if st is None:
            return nocache({"error": f"no snapshot for camera {cam}", "reason": reason}, 404)
        snap = hub.infer.snapshot(cam)
        if snap is None:
            return nocache({"error": f"no snapshot for camera {cam}",
                            "reason": "agx-infer sent no snapshot for this camera"}, 404)
        data, _t = snap
        sage = hub.infer.snapshot_age_s(cam) or 0.0
        if sage > hub.infer.stale_s:
            return nocache({"error": f"no snapshot for camera {cam}",
                            "reason": f"last snapshot is {sage:.0f} s old "
                                      f"(limit {hub.infer.stale_s:.0f} s)"}, 404)
        return Response(data, media_type="image/jpeg",
                        headers={"cache-control": "no-store", "x-snapshot-age-s": f"{sage:.1f}"})

    @app.get("/api/history")
    def api_history(range: str = Query("1h"), metrics: str | None = Query(None)):
        rs = {"1h": 3600, "24h": 86400}.get(range)
        if rs is None:
            return nocache({"error": "range must be 1h or 24h"}, 400)
        names = None
        if metrics:
            names = [m for m in metrics.split(",") if m][:50]
            if not all(METRIC_RE.match(m) for m in names):
                return nocache({"error": "bad metric name"}, 400)
        d = hub.history.query(rs, names)
        d["available"] = hub.history.names()
        return nocache(d)

    @app.get("/api/stream")
    async def api_stream(request: Request):
        # One event each second, and one event AT ONCE when a new agx-infer status arrives: the page
        # then knows each new last_frame_t without delay, so its 250 ms tile check does not show a
        # false STALE / NO SIGNAL for a status that the server has but the page does not have yet.
        async def gen():
            yield "retry: 3000\n\n"
            n = 0
            while True:
                if await request.is_disconnected():
                    break
                seq = hub.infer.seq
                t_sent = time.monotonic()
                try:
                    doc = await asyncio.to_thread(
                        lambda: {"health": hub.health_doc(), "services": hub.services.summary(),
                                 "cameras": hub.views.cameras_doc(), "server_t": time.time()})
                    n += 1
                    yield f"id: {n}\ndata: {json.dumps(doc, separators=(',', ':'))}\n\n"
                except Exception:  # keep the stream alive; details only in the server log
                    log.exception("stream build failed")
                    yield 'event: fail\ndata: {"error":"stream build failed"}\n\n'
                while time.monotonic() - t_sent < STREAM_PERIOD_S and hub.infer.seq == seq:
                    await asyncio.sleep(STREAM_POLL_S)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"cache-control": "no-store", "x-accel-buffering": "no"})

    control_api.register(app, hub)

    # pairing: the paired boards store (the board tokens of /api/models/*), the one-time migration, the routes
    pairing = PairingStore(resolve_path(cfg.get("paired_boards_file") or "data/paired_boards.json"),
                           resolve_path(cfg.get("link_settings_file") or "data/link_settings.json"))
    fails = LoginFails()   # shared: a wrong pairing code counts as a failed login of the address
    app.state.pairing = pairing
    hub.pairing = pairing
    pairing_api.register(app, hub, pairing, fails, cfg)
    power_api.register(app, hub)
    if start_collectors if migrate is None else migrate:
        pairing_api.migrate_at_start(pairing, cfg, app.state.pair_audit)

    allow = cfg.get("allow_cidrs")
    # add_middleware puts the newest one outside: SecurityHeaders is outermost, so the
    # 401/403 replies of GuardMiddleware also get the security headers.
    app.add_middleware(GuardMiddleware, user=user, password=password, allow_cidrs=allow,
                       pairing=pairing, fails=fails, audit=app.state.pair_audit,
                       vehicle=app.state.pair_vehicle_refusal)
    app.add_middleware(SecurityHeaders)
    return app
