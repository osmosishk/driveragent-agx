"""Status publisher.

Every period_s (1.0 s):
  1. Calculate the node state (infer.status.NodeState.evaluate) from ModelManager.status() and the
     camera states.
  2. Publish AgxInferStatus (schema v2) with the dabus envelope (type_id 5561, src_board 1) as ONE
     ZMQ frame on PUB tcp://<host>:5561.
  3. Publish the internal JSON status (dashboard contract agx-infer-status/1) on the internal PUB
     (127.0.0.1:5562), topic b"status".
Schema v2 data (owner Section 4.7), the same in the capnp status and (new keys) in the JSON:
  catalog / control_mode / change_in_progress  <model_store>/_state/catalog.json (written by the controller in
                       agx-dashboard at each scan and at the start and end of each change; read again only when its
                       mtime changes). A missing or bad file: empty catalog, no change, control mode from
                       config/control.yaml (controller.control.read_control_mode).
  active_set           the manager instances in state RUNNING / LOADING / LOADED (name, version, cameras)
  last_good_set        <model_store>/_state/last_good.json (controller.runtime.read_set)
  cameras[].name / role_confirmed / info_source   infer/rkinfo.py apply_names (DA01 RkCameraInfo, rk mode only)
  models[].version     the store version ("" = a config/models.yaml entry)
"""
from __future__ import annotations

import glob
import json
import logging
import math
import os
import threading
import time

import zmq

from common import envelope as env
from infer import rkinfo as rki
from infer.publish import schema as sch
from infer.publish.internal import PUB_MAX_IN_BYTES, RateLimitedLog

log = logging.getLogger("infer.status")

SCHEMA_JSON = "agx-infer-status/1"
GPU_MEM_NOTE = "estimate: engine file + activation + I/O"
_LAT_KEYS = ("pre", "infer", "post", "total")
_PCT_KEYS = ("p50", "p95", "p99")
ACTIVE_STATES = ("RUNNING", "LOADING", "LOADED")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_CONTROL = os.path.join(ROOT, "config", "control.yaml")
CATALOG_FILE = "catalog.json"
_CAT_KEYS = ("name", "version", "type", "state", "reason")
CATALOG_MAX = 200            # catalog entries in one status (the store has about 5 now); keeps one capnp segment
REASON_MAX = 300             # characters of a catalog reason in the status (the full text is on the dashboard API)
TEXT_MAX = 1000
CATALOG_FRESH_S = 30.0       # agx-dashboard writes catalog.json every 10 s: an older one gives no change in progress


def _text(v, limit: int = TEXT_MAX) -> str:
    """capnp Text: never None, always valid UTF-8 (a file name can hold a surrogate escape), at most limit characters."""
    s = "" if v is None else str(v)
    return s.encode("utf-8", "replace").decode("utf-8")[:limit]


def _control_mode_of(path) -> str:
    from controller.control import read_control_mode
    try:
        return read_control_mode(path)[0]
    except Exception:  # noqa: BLE001 - fail safe: an unreadable file shows vehicle, as the controller does
        return "vehicle"


def _set_items(items) -> list[dict]:
    """[{name, version, cameras}] with str / str / [int 0..255]; bad items are left out."""
    out = []
    for i in items or []:
        if not isinstance(i, dict) or not i.get("name"):
            continue
        cams = []
        for c in i.get("cameras") or []:
            try:
                cams.append(int(c) & 0xFF)
            except (TypeError, ValueError):
                continue
        out.append({"name": _text(i.get("name")), "version": _text(i.get("version")), "cameras": sorted(set(cams))})
    return out


class _MtimeFile:
    """A file that is parsed again only when its mtime (or size) changes. parse(path) -> value; a missing file or a
    parse error gives the default."""

    def __init__(self, parse, default):
        self.parse = parse
        self.default = default
        self._key = None
        self._val = default
        self.error: str | None = None

    def get(self, path) -> object:
        if path is None:
            return self.default
        try:
            st = os.stat(path)
        except OSError:
            self._key, self._val, self.error = None, self.default, None
            return self.default
        key = (str(path), st.st_mtime_ns, st.st_size)
        if key != self._key:
            try:
                self._val, self.error = self.parse(path), None
            except Exception as e:  # noqa: BLE001
                self._val, self.error = self.default, f"{path}: {type(e).__name__}: {e}"
            self._key = key
        return self._val


def parse_catalog(path) -> dict | None:
    """catalog.json -> {"entries": [...], "control_mode", "change_in_progress", "t"} or None (bad file)."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
        return None
    entries = [{k: _text(e.get(k), REASON_MAX if k == "reason" else 200) for k in _CAT_KEYS}
               for e in d["entries"][:CATALOG_MAX] if isinstance(e, dict)]
    mode = d.get("control_mode")
    return {"entries": entries, "control_mode": mode if isinstance(mode, str) and mode else None,
            "change_in_progress": _text(d.get("change_in_progress")), "t": d.get("t")}


def read_temps() -> list[tuple[str, float]]:
    """(zone type, deg C) of every readable /sys/class/thermal zone. Unreadable zones are skipped
    (on Jetson some zones give EAGAIN when the unit is powered down)."""
    out = []
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            with open(os.path.join(z, "type")) as f:
                name = f.read().strip()
            with open(os.path.join(z, "temp")) as f:
                v = int(f.read().strip())
        except (OSError, ValueError, TypeError):   # TypeError: EAGAIN gives read() None
            continue
        if -40000 < v < 150000:
            out.append((name, v / 1000.0))
    return out


def _num(v, default=None):
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _finite(o):
    """Replace NaN / inf with None (browsers cannot parse NaN in JSON)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


def normalize_model_status(m: dict) -> dict:
    """One ModelManager.status() entry -> the dashboard contract keys (missing keys get null / [])."""
    lat_in = m.get("lat_ms") or {}
    lat = {}
    for k in _LAT_KEYS:
        src = lat_in.get(k) or {}
        lat[k] = {p: _num(src.get(p)) for p in _PCT_KEYS}
    return {
        "name": m.get("name"),
        "version": str(m.get("version") or ""),           # "" for a legacy config/models.yaml entry
        "instance": m.get("instance") or m.get("name"),   # <name>@<version>, or the name (legacy)
        "engine": m.get("engine"),
        "engine_version": m.get("engine_version"),
        "state": m.get("state") or "OFF",
        "error": m.get("error"),
        "reason": m.get("reason"),
        "enabled": bool(m.get("enabled", False)),
        "cameras": [int(c) for c in (m.get("cameras") or [])],
        "fps": _num(m.get("fps"), 0.0),
        "lat_ms": lat,
        "gpu_mem_mb": _num(m.get("gpu_mem_mb")),
        "gpu_mem_note": m.get("gpu_mem_note") or GPU_MEM_NOTE,
        "trt_match": m.get("trt_match"),
        "trt_build_device": m.get("trt_build_device"),
        "trt_device_warning": m.get("trt_device_warning"),
        "trt_version": m.get("trt_version"),
        "load_warnings": list(m.get("load_warnings") or []),
        "inputs": list(m.get("inputs") or []),
        "outputs": list(m.get("outputs") or []),
        "results_total": int(m.get("results_total") or 0),
    }


class StatusPublisher:
    def __init__(self, node, ingest, manager, results_pub, internal_pub, host: str = "0.0.0.0",
                 port: int = 5561, period_s: float = 1.0, proto_path: str | None = None,
                 ctx: zmq.Context | None = None, model_store: str | None = None,
                 control_file: str | None = DEFAULT_CONTROL, rkinfo=None):
        """model_store: the controller store root (None = no store: empty catalog and last good set);
        control_file: config/control.yaml; rkinfo: infer.rkinfo.RkInfoReceiver or None."""
        self.node = node
        self.ingest = ingest
        self.manager = manager
        self.results_pub = results_pub
        self.internal = internal_pub
        self.port = port
        self.period_s = float(period_s)
        self.schema = sch.load(proto_path)
        self.hash = self.schema.hash["AgxInferStatus"]
        self.endpoint = f"tcp://{host}:{port}"
        self._ctx = ctx or zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUB)
        self._sock.setsockopt(zmq.SNDHWM, 20)
        self._sock.setsockopt(zmq.LINGER, 0)
        # A PUB socket receives only subscriptions: a larger inbound message closes that peer.
        self._sock.setsockopt(zmq.MAXMSGSIZE, PUB_MAX_IN_BYTES)
        # Bind address from config/infer.yaml (now 0.0.0.0: the RK3588 connects over the link).
        # The owner can later bind only the link address (100.64.0.20 now, 10.42.0.1 on Link C).
        self._sock.bind(self.endpoint)
        self._rlog = RateLimitedLog(log)
        self._seq = env.Sequencer()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._prev_state = None
        self._seen_model_err: dict[str, str] = {}
        self._seen_cam_err: dict[int, str] = {}
        self.sent = 0
        self.last_json: dict | None = None
        self.rkinfo = rkinfo
        self.control_file = control_file
        self.store = None
        if model_store:
            from controller.store import Store
            self.store = Store(model_store)
        self._catalog = _MtimeFile(parse_catalog, None)
        self._control_mode = _MtimeFile(_control_mode_of, "bench")       # no file = bench (rule M7 default)
        self._last_good = _MtimeFile(self._parse_last_good, [])
        log.info("status PUB bound %s (schema hash 0x%08x)", self.endpoint, self.hash)

    # ---- collect ---------------------------------------------------------------------------------
    def _models(self) -> list[dict]:
        if self.manager is None:
            return []
        try:
            return [normalize_model_status(m) for m in self.manager.status()]
        except Exception as e:  # noqa: BLE001
            self.node.add_error(f"ModelManager.status() failed: {e}")
            log.exception("ModelManager.status() failed")
            return []

    def _cameras(self) -> list[dict]:
        if self.ingest is None:
            return []
        cams = self.ingest.metrics_snapshot()
        store = self.ingest.store
        for c in cams:
            cam = int(c.get("cam"))
            c["state"] = store.state(cam)
            f = store.newest(cam)
            c["last_frame_t"] = (f.t_ready_ns / 1e9) if f is not None else c.get("last_frame_t")
        # DA01 is the only source of the names: only its cameras (rk mode) take the RK names and roles
        info = None
        if self.rkinfo is not None and getattr(self.ingest, "mode", "") == "rk":
            try:
                info = self.rkinfo.fresh()
            except Exception:  # noqa: BLE001
                log.exception("RkCameraInfo read failed")
        return rki.apply_names(cams, info)

    # ---- model control (schema v2) ---------------------------------------------------------------
    def _parse_last_good(self, _path) -> list[dict]:
        from controller import runtime
        d = runtime.read_set(self.store, runtime.LAST_GOOD)
        return _set_items(d["set"]) if d else []

    def control(self, models: list[dict]) -> dict:
        """{catalog, active_set, control_mode, last_good_set, change_in_progress} (JSON keys)."""
        cat = None
        last_good: list = []
        if self.store is not None:
            cat = self._catalog.get(self.store.state / CATALOG_FILE)
            if self._catalog.error:
                self._rlog.warning("catalog", "catalog snapshot not used: %s", self._catalog.error)
            from controller import runtime
            last_good = self._last_good.get(self.store.state / runtime.LAST_GOOD)
        # The control mode always comes from config/control.yaml (the file the controller obeys), parsed when it
        # changes. The change in progress comes from the controller snapshot only while it is fresh: a stopped
        # agx-dashboard must not leave an old change in the status (review N4).
        mode = self._control_mode.get(self.control_file) if self.control_file else "bench"
        t = (cat or {}).get("t")
        age = time.time() - t if isinstance(t, (int, float)) else None
        fresh = age is not None and age <= CATALOG_FRESH_S
        if cat is not None and not fresh:
            self._rlog.warning("catalog_age", "catalog snapshot is %s s old: no change in progress is shown "
                               "(does agx-dashboard run?)", "?" if age is None else round(age))
        active = _set_items([m for m in models if m.get("state") in ACTIVE_STATES])
        return {"catalog": [dict(e) for e in (cat or {}).get("entries", [])],
                "catalog_age_s": None if age is None else round(age, 1),
                "active_set": active,
                "control_mode": _text(mode, 16),
                "last_good_set": [dict(i, cameras=list(i["cameras"])) for i in last_good],
                "change_in_progress": _text((cat or {}).get("change_in_progress"), 200) if fresh else ""}

    def _collect_errors(self, models: list[dict], cams: list[dict]) -> None:
        for m in models:
            name = str(m.get("instance") or m.get("name"))
            err = m.get("error") or ""
            if err and self._seen_model_err.get(name) != err:
                self.node.add_error(f"model {name}: {err}")
            self._seen_model_err[name] = err
        for c in cams:
            cam = int(c.get("cam"))
            err = c.get("last_error") or ""
            if err and self._seen_cam_err.get(cam) != err:
                self.node.add_error(f"cam{cam}: {err}")
            self._seen_cam_err[cam] = err
        st = self.node.state
        if st != self._prev_state:
            if st in ("DEGRADED", "ERROR"):
                self.node.add_error(f"node {st}: " + "; ".join(self.node.reasons))
            log.info("node state %s -> %s %s", self._prev_state, st, self.node.reasons)
            self._prev_state = st

    def _simulated(self, cams: list[dict]) -> bool:
        mode = getattr(self.ingest, "mode", "sim")
        return mode != "rk" or any(c.get("simulated") and c.get("frame_age_ms") is not None
                                   for c in cams)

    # ---- build -----------------------------------------------------------------------------------
    def build_json(self, models: list[dict], cams: list[dict], now: float | None = None,
                   control: dict | None = None) -> dict:
        now = time.time() if now is None else now
        control = self.control(models) if control is None else control
        pub = self.results_pub.stats() if self.results_pub is not None else {}
        last_ts = [c["last_frame_t"] for c in cams if c.get("last_frame_t")]
        last = max(last_ts) if last_ts else None
        return {
            "schema": SCHEMA_JSON,
            "t": now,
            "node": {"state": self.node.state, "uptime_s": round(self.node.uptime_s(), 1),
                     "pid": self.node.pid, "version": self.node.version,
                     "simulated": self._simulated(cams), "errors": self.node.errors()},
            "cameras": cams,
            "models": models,
            "publish": {"results_port": pub.get("results_port", None),
                        "status_port": self.port,
                        "results_rate_hz": pub.get("results_rate_hz", 0.0),
                        "subscribers": pub.get("subscribers", 0),
                        "results_total": pub.get("results_total", 0),
                        "last_result_t": pub.get("last_result_t")},
            "link": {"last_frame_t": last,
                     "time_since_last_frame_ms": round((now - last) * 1000.0, 1) if last else None},
            **control,
            "rk_info": self.rkinfo.stats() if self.rkinfo is not None else None,
        }

    def build_capnp(self, models: list[dict], cams: list[dict], t_ns: int, control: dict | None = None) -> bytes:
        control = self.control(models) if control is None else control
        _mb, s = sch.new_builder(self.schema.mod.AgxInferStatus, 65536)
        s.schemaVersion = self.schema.version
        s.hostname = self.node.hostname
        s.version = self.node.version
        s.nodeState = self.node.state
        s.simulated = self._simulated(cams)
        s.uptimeS = int(self.node.uptime_s()) & 0xFFFFFFFF
        s.tStatusNs = t_ns
        s.sourceMode = str(getattr(self.ingest, "mode", "") or "")
        lc = s.init("cameras", len(cams))
        for i, c in enumerate(cams):
            o = lc[i]
            o.camId = int(c.get("cam", i)) & 0xFF
            o.role = _text(c.get("role"), 200)
            o.state = _text(c.get("state") or "NO SIGNAL", 32)
            o.simulated = bool(c.get("simulated"))
            o.fps = _num(c.get("fps"), 0.0)
            age = _num(c.get("frame_age_ms"))
            o.frameAgeMs = float("nan") if age is None else age
            o.lostFrames = int(c.get("lost_frames") or 0)
            o.lostPackets = int(c.get("lost_packets") or 0)
            o.lastFrameSeq = int(c.get("last_seq") or 0) & 0xFFFFFFFF
            o.name = _text(c.get("name"))
            o.roleConfirmed = bool(c.get("role_confirmed"))
            o.infoSource = _text(c.get("info_source")) or "config"
        lm = s.init("models", len(models))
        for i, m in enumerate(models):
            o = lm[i]
            o.name = _text(m.get("name"), 200)
            o.state = _text(m.get("state"), 32)
            o.error = _text(m.get("error"))
            cl = o.init("cameras", len(m["cameras"]))
            for j, c in enumerate(m["cameras"]):
                cl[j] = c & 0xFF
            o.fps = _num(m.get("fps"), 0.0)
            tot = m["lat_ms"]["total"]
            o.latencyP50Ms = _num(tot.get("p50"), float("nan"))
            o.latencyP95Ms = _num(tot.get("p95"), float("nan"))
            o.latencyP99Ms = _num(tot.get("p99"), float("nan"))
            o.version = _text(m.get("version"))
        temps = read_temps()
        lt = s.init("temps", len(temps))
        for i, (zone, c) in enumerate(temps):
            lt[i].zone = _text(zone, 64)
            lt[i].celsius = c
        errs = self.node.errors()[:20]
        le = s.init("errors", len(errs))
        for i, e in enumerate(errs):
            le[i] = _text(e)
        pub = self.results_pub.stats() if self.results_pub is not None else {}
        s.resultsPort = int(pub.get("results_port") or 0) & 0xFFFF
        s.resultSubscribers = min(0xFFFF, int(pub.get("subscribers") or 0))
        s.resultsRateHz = float(pub.get("results_rate_hz") or 0.0)
        # schema v2: model control. A bad value here must never stop the status (review N4): log it, send the rest.
        try:
            cat = control["catalog"][:CATALOG_MAX]
            lc = s.init("catalog", len(cat))
            for i, e in enumerate(cat):
                for k in _CAT_KEYS:
                    setattr(lc[i], k, _text(e.get(k), REASON_MAX if k == "reason" else 200))
            for field, key in (("activeSet", "active_set"), ("lastGoodSet", "last_good_set")):
                items = control[key]
                la = s.init(field, len(items))
                for i, a in enumerate(items):
                    la[i].name = _text(a["name"], 200)
                    la[i].version = _text(a["version"], 64)
                    la[i].cameras = [int(c) & 0xFF for c in a["cameras"]]
            s.controlMode = _text(control["control_mode"], 16)
            s.changeInProgress = _text(control["change_in_progress"], 200)
        except Exception as e:  # noqa: BLE001
            self._rlog.warning("v2", "model control part of the status not complete: %s: %s", type(e).__name__, e)
        return s.to_bytes()

    # ---- run -------------------------------------------------------------------------------------
    def tick(self) -> dict:
        models = self._models()
        cams = self._cameras()
        self.node.evaluate(models, {int(c["cam"]): c["state"] for c in cams})
        self._collect_errors(models, cams)
        t_ns = time.time_ns()
        control = self.control(models)
        payload = self.build_capnp(models, cams, t_ns, control)
        flags = env.FLAG_TIME_UNCERTAIN
        if self._simulated(cams):
            flags |= env.FLAG_SOURCE_IS_REPLAY
        if self.node.state == "DEGRADED":
            flags |= env.FLAG_DEGRADED
        msg = env.pack(sch.TYPE_STATUS, flags, self.hash, self._seq.next(sch.TYPE_STATUS), t_ns,
                       payload, src_board=env.SRC_AGX)
        try:
            self._sock.send(msg, zmq.NOBLOCK)
        except zmq.ZMQError as e:
            self._rlog.warning("send", "status send failed: %s", e)
        js = self.build_json(models, cams, t_ns / 1e9, control)
        if self.internal is not None:
            self.internal.send(b"status", json.dumps(_finite(js), default=str,
                                                     allow_nan=False).encode("utf-8"))
        self.sent += 1
        self.last_json = js
        return js

    def _run(self) -> None:
        nxt = time.monotonic()
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                log.exception("status tick failed")
                self.node.add_error(f"status tick failed: {e}")
            nxt += self.period_s
            d = nxt - time.monotonic()
            if d < 0:
                nxt = time.monotonic()
                d = 0
            self._stop.wait(d)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="status-pub", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._sock.close(0)
