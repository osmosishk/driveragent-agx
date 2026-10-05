"""Status publisher.

Every period_s (1.0 s):
  1. Calculate the node state (infer.status.NodeState.evaluate) from ModelManager.status() and the
     camera states.
  2. Publish AgxInferStatus (schema v1) with the dabus envelope (type_id 5561, src_board 1) as ONE
     ZMQ frame on PUB tcp://<host>:5561.
  3. Publish the internal JSON status (dashboard contract agx-infer-status/1) on the internal PUB
     (127.0.0.1:5562), topic b"status".
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
from infer.publish import schema as sch

log = logging.getLogger("infer.status")

SCHEMA_JSON = "agx-infer-status/1"
GPU_MEM_NOTE = "estimate: engine file + activation + I/O"
_LAT_KEYS = ("pre", "infer", "post", "total")
_PCT_KEYS = ("p50", "p95", "p99")


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
        "trt_version": m.get("trt_version"),
        "load_warnings": list(m.get("load_warnings") or []),
        "inputs": list(m.get("inputs") or []),
        "outputs": list(m.get("outputs") or []),
        "results_total": int(m.get("results_total") or 0),
    }


class StatusPublisher:
    def __init__(self, node, ingest, manager, results_pub, internal_pub, host: str = "0.0.0.0",
                 port: int = 5561, period_s: float = 1.0, proto_path: str | None = None,
                 ctx: zmq.Context | None = None):
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
        self._sock.bind(self.endpoint)
        self._seq = env.Sequencer()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._prev_state = None
        self._seen_model_err: dict[str, str] = {}
        self._seen_cam_err: dict[int, str] = {}
        self.sent = 0
        self.last_json: dict | None = None
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
        return cams

    def _collect_errors(self, models: list[dict], cams: list[dict]) -> None:
        for m in models:
            name = str(m.get("name"))
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
    def build_json(self, models: list[dict], cams: list[dict], now: float | None = None) -> dict:
        now = time.time() if now is None else now
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
        }

    def build_capnp(self, models: list[dict], cams: list[dict], t_ns: int) -> bytes:
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
            o.role = str(c.get("role") or "")
            o.state = str(c.get("state") or "NO SIGNAL")
            o.simulated = bool(c.get("simulated"))
            o.fps = _num(c.get("fps"), 0.0)
            age = _num(c.get("frame_age_ms"))
            o.frameAgeMs = float("nan") if age is None else age
            o.lostFrames = int(c.get("lost_frames") or 0)
            o.lostPackets = int(c.get("lost_packets") or 0)
            o.lastFrameSeq = int(c.get("last_seq") or 0) & 0xFFFFFFFF
        lm = s.init("models", len(models))
        for i, m in enumerate(models):
            o = lm[i]
            o.name = str(m.get("name") or "")
            o.state = str(m.get("state") or "")
            o.error = str(m.get("error") or "")
            cl = o.init("cameras", len(m["cameras"]))
            for j, c in enumerate(m["cameras"]):
                cl[j] = c & 0xFF
            o.fps = _num(m.get("fps"), 0.0)
            tot = m["lat_ms"]["total"]
            o.latencyP50Ms = _num(tot.get("p50"), float("nan"))
            o.latencyP95Ms = _num(tot.get("p95"), float("nan"))
            o.latencyP99Ms = _num(tot.get("p99"), float("nan"))
        temps = read_temps()
        lt = s.init("temps", len(temps))
        for i, (zone, c) in enumerate(temps):
            lt[i].zone = zone
            lt[i].celsius = c
        errs = self.node.errors()[:20]
        le = s.init("errors", len(errs))
        for i, e in enumerate(errs):
            le[i] = e
        pub = self.results_pub.stats() if self.results_pub is not None else {}
        s.resultsPort = int(pub.get("results_port") or 0) & 0xFFFF
        s.resultSubscribers = min(0xFFFF, int(pub.get("subscribers") or 0))
        s.resultsRateHz = float(pub.get("results_rate_hz") or 0.0)
        return s.to_bytes()

    # ---- run -------------------------------------------------------------------------------------
    def tick(self) -> dict:
        models = self._models()
        cams = self._cameras()
        self.node.evaluate(models, {int(c["cam"]): c["state"] for c in cams})
        self._collect_errors(models, cams)
        t_ns = time.time_ns()
        payload = self.build_capnp(models, cams, t_ns)
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
            log.warning("status send failed: %s", e)
        js = self.build_json(models, cams, t_ns / 1e9)
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
