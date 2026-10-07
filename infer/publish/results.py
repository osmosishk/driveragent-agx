"""Results publisher: ZMQ PUB on tcp://<host>:5560, one ZMQ frame per result =
32-byte dabus envelope + unpacked single-segment Cap'n Proto AgxPerceptionResult (schema v1).

Result dict (from the ModelManager on_result callback). Snake-case names of the capnp fields:
  model, model_version, cam, frame_seq, t_capture_ns, t_recv_ns, t_ready_ns, t_result_ns,
  frame_width, frame_height, simulated, source,
  detections: [{class_id, class_name, score, x1, y1, x2, y2, track_id}]
  trajectory: None | {frame, points: [{x, y, t_s}] or [(x, y, t_s)], inputs_valid, note}
  masks:      [{name, width, height, encoding, data(bytes)}]
  timing:     {queue_ms, pre_ms, infer_ms, post_ms, total_ms}
  instance:   "<name>@<version>" of a model store instance, or the model name of a legacy entry (default:
              model). Not on the wire: the duplicate check and the result cache use (instance, cam), so two
              versions of one model name can run at the same time. On the wire: model + modelVersion
              ("<version>:<engine sha256 16 hex>" for a store instance).
Some other names are also accepted (normalize_result). Other keys are ignored: the capnp struct has
no field for control values (rule R8: throttle, steer, brake, mu, sigma, pred_speed are never sent).

Envelope: type_id 5560, src_board 1 (AGX), seq = per-type counter, t_ptp_ns = t_result_ns,
flags = bit0 if simulated (R13) | bit1 always (no PTP) | bit2 if the node is DEGRADED.
Thread-safe: publish() only puts the packed message in a queue; one sender thread owns the socket.
"""
from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections import deque

import zmq
from zmq.utils.monitor import recv_monitor_message

from common import envelope as env
from infer.publish import schema as sch
from infer.publish.internal import PUB_MAX_IN_BYTES, RateLimitedLog

log = logging.getLogger("infer.results")

_ALIASES = {
    "cam": ("cam", "cam_id", "camId"),
    "frame_seq": ("frame_seq", "seq", "frameSeq"),
    "frame_width": ("frame_width", "frame_w", "width", "frameWidth"),
    "frame_height": ("frame_height", "frame_h", "height", "frameHeight"),
    "model_version": ("model_version", "modelVersion", "engine_version"),
    "t_capture_ns": ("t_capture_ns", "tCaptureNs"),
    "t_recv_ns": ("t_recv_ns", "t_agx_recv_ns", "tAgxRecvNs"),
    "t_ready_ns": ("t_ready_ns", "t_agx_ready_ns", "tAgxReadyNs"),
    "t_result_ns": ("t_result_ns", "t_agx_result_ns", "tAgxResultNs"),
}
U64 = (1 << 64) - 1


def _get(d: dict, key: str, default=None):
    for k in _ALIASES.get(key, (key,)):
        if k in d and d[k] is not None:
            return d[k]
    return default


def _f(v, default=0.0) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _norm_det(d) -> dict:
    if isinstance(d, (list, tuple)):  # (x1, y1, x2, y2, conf, cls[, name])
        out = {"x1": d[0], "y1": d[1], "x2": d[2], "y2": d[3], "score": d[4], "class_id": int(d[5])}
        out["class_name"] = d[6] if len(d) > 6 else ""
        out["track_id"] = 0
        return out
    box = d.get("box") or d.get("xyxy")
    x1, y1, x2, y2 = box if box is not None else (d.get("x1"), d.get("y1"), d.get("x2"), d.get("y2"))
    return {"class_id": int(d.get("class_id", d.get("cls", 0)) or 0),
            "class_name": str(d.get("class_name", d.get("name", "")) or ""),
            "score": _f(d.get("score", d.get("conf", 0.0))),
            "x1": _f(x1), "y1": _f(y1), "x2": _f(x2), "y2": _f(y2),
            "track_id": int(d.get("track_id", 0) or 0)}


def _norm_traj(t):
    if not t:
        return None
    pts = []
    for p in t.get("points") or []:
        if isinstance(p, dict):
            pts.append({"x": _f(p.get("x")), "y": _f(p.get("y")), "t_s": _f(p.get("t_s", p.get("tS", 0.0)))})
        else:
            pts.append({"x": _f(p[0]), "y": _f(p[1]), "t_s": _f(p[2]) if len(p) > 2 else 0.0})
    return {"frame": str(t.get("frame", "") or ""), "points": pts,
            "inputs_valid": bool(t.get("inputs_valid", t.get("inputsValid", False))),
            "note": str(t.get("note", "") or "")}


def _norm_mask(m) -> dict:
    data = m.get("data", b"")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        data = bytes(data)
    return {"name": str(m.get("name", "")), "width": int(m.get("width", 0)),
            "height": int(m.get("height", 0)),
            "encoding": str(m.get("encoding", "rle-u16le-count-u8-value-rowmajor")),
            "data": bytes(data)}


def normalize_result(r: dict) -> dict:
    """Return a new dict with the canonical keys (see module doc). R13: simulated is true when the
    result says so OR the source is not "live"."""
    source = str(r.get("source", "") or "")
    sim = bool(r.get("simulated", True)) or source != "live"
    timing = r.get("timing") or {}
    t_res = _get(r, "t_result_ns")
    model = str(r.get("model", "") or "")
    return {
        "model": model,
        "instance": str(r.get("instance") or model),
        "model_version": str(_get(r, "model_version", "") or ""),
        "cam": int(_get(r, "cam", 0)),
        "frame_seq": int(_get(r, "frame_seq", 0)) & 0xFFFFFFFF,
        "t_capture_ns": int(_get(r, "t_capture_ns", 0)) & U64,
        "t_recv_ns": int(_get(r, "t_recv_ns", 0)) & U64,
        "t_ready_ns": int(_get(r, "t_ready_ns", 0)) & U64,
        "t_result_ns": int(t_res if t_res else time.time_ns()) & U64,
        "frame_width": int(_get(r, "frame_width", 0)),
        "frame_height": int(_get(r, "frame_height", 0)),
        "simulated": sim,
        "source": source or "unknown",
        "detections": [_norm_det(d) for d in (r.get("detections") or [])],
        "trajectory": _norm_traj(r.get("trajectory")),
        "masks": [_norm_mask(m) for m in (r.get("masks") or [])],
        "timing": {k: _f(timing.get(k, timing.get(k.replace("_ms", "Ms").replace("_m", "M"), 0.0)))
                   for k in ("queue_ms", "pre_ms", "infer_ms", "post_ms", "total_ms")},
    }


def build_result_payload(schema: sch.Schema, r: dict) -> bytes:
    """Canonical result dict -> single-segment capnp bytes."""
    est = 4096 + 64 * len(r["detections"]) + sum(len(m["data"]) + 128 for m in r["masks"]) \
        + 32 * len((r["trajectory"] or {}).get("points", []))
    _mb, m = sch.new_builder(schema.mod.AgxPerceptionResult, est)
    m.schemaVersion = schema.version
    m.model = r["model"]
    m.modelVersion = r["model_version"]
    m.camId = r["cam"] & 0xFF
    m.frameSeq = r["frame_seq"]
    m.tCaptureNs = r["t_capture_ns"]
    m.tAgxRecvNs = r["t_recv_ns"]
    m.tAgxReadyNs = r["t_ready_ns"]
    m.tAgxResultNs = r["t_result_ns"]
    m.frameWidth = r["frame_width"] & 0xFFFF
    m.frameHeight = r["frame_height"] & 0xFFFF
    m.simulated = r["simulated"]
    m.source = r["source"]
    dets = m.init("detections", len(r["detections"]))
    for i, d in enumerate(r["detections"]):
        o = dets[i]
        o.classId = d["class_id"] & 0xFFFF
        o.className = d["class_name"]
        o.score = d["score"]
        o.x1, o.y1, o.x2, o.y2 = d["x1"], d["y1"], d["x2"], d["y2"]
        o.trackId = d["track_id"] & 0xFFFFFFFF
    t = m.init("trajectory")
    tr = r["trajectory"]
    if tr is None:
        t.frame = ""
        t.init("points", 0)
        t.inputsValid = False
        t.note = "no trajectory from this model"
    else:
        t.frame = tr["frame"]
        pts = t.init("points", len(tr["points"]))
        for i, p in enumerate(tr["points"]):
            pts[i].x, pts[i].y, pts[i].tS = p["x"], p["y"], p["t_s"]
        t.inputsValid = tr["inputs_valid"]
        t.note = tr["note"]
    ms = m.init("masks", len(r["masks"]))
    for i, mk in enumerate(r["masks"]):
        o = ms[i]
        o.name = mk["name"]
        o.width = mk["width"] & 0xFFFF
        o.height = mk["height"] & 0xFFFF
        o.encoding = mk["encoding"]
        o.data = mk["data"]
    tm = m.init("timing")
    tm.queueMs = r["timing"]["queue_ms"]
    tm.preMs = r["timing"]["pre_ms"]
    tm.inferMs = r["timing"]["infer_ms"]
    tm.postMs = r["timing"]["post_ms"]
    tm.totalMs = r["timing"]["total_ms"]
    return m.to_bytes()


class ResultPublisher:
    def __init__(self, host: str = "0.0.0.0", port: int = 5560, proto_path: str | None = None,
                 degraded_fn=None, sndhwm: int = 100, queue_max: int = 1000,
                 rate_window_s: float = 5.0, ctx: zmq.Context | None = None):
        self.endpoint = f"tcp://{host}:{port}"
        self.port = port
        self.schema = sch.load(proto_path)
        self.hash = self.schema.hash["AgxPerceptionResult"]
        self.degraded_fn = degraded_fn or (lambda: False)
        self._ctx = ctx or zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUB)
        self._sock.setsockopt(zmq.SNDHWM, sndhwm)
        self._sock.setsockopt(zmq.LINGER, 0)
        # A PUB socket receives only subscriptions: a larger inbound message closes that peer.
        self._sock.setsockopt(zmq.MAXMSGSIZE, PUB_MAX_IN_BYTES)
        # Bind address from config/infer.yaml (now 0.0.0.0: the RK3588 connects over the link).
        # The owner can later bind only the link address (100.64.0.20 now, 10.42.0.1 on Link C).
        self._mon = self._sock.get_monitor_socket(zmq.EVENT_ACCEPTED | zmq.EVENT_DISCONNECTED)
        self._sock.bind(self.endpoint)
        self._seq = env.Sequencer()
        self._q: queue.Queue = queue.Queue(maxsize=queue_max)
        self._lock = threading.Lock()          # counters
        self._build_lock = threading.Lock()    # sequencer + duplicate check
        self._times = deque()
        self.rate_window_s = rate_window_s
        self.results_total = 0
        self.dropped_queue = 0
        self.dropped_duplicate = 0
        self.errors = 0
        self.subscribers = 0
        self.last_result_t: float | None = None
        self.multi_segment = 0
        self._last_id: dict[tuple, tuple] = {}
        self._rlog = RateLimitedLog(log)   # repeated errors: 1 line per 10 s per kind
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="results-pub", daemon=True)
        self._thread.start()
        log.info("results PUB bound %s (schema hash 0x%08x)", self.endpoint, self.hash)

    # ---- producer side (any thread) --------------------------------------------------------------
    def _build(self, result: dict) -> tuple[bytes, int, dict]:
        """result -> (capnp payload, envelope flags, canonical result). No envelope seq yet."""
        r = normalize_result(result)
        payload = build_result_payload(self.schema, r)
        if sch.segment_count(payload) != 1:
            self.multi_segment += 1
        flags = env.FLAG_TIME_UNCERTAIN
        if r["simulated"]:
            flags |= env.FLAG_SOURCE_IS_REPLAY
        if self.degraded_fn():
            flags |= env.FLAG_DEGRADED
        return payload, flags, r

    def make_message(self, result: dict) -> tuple[bytes, dict]:
        payload, flags, r = self._build(result)
        with self._build_lock:
            seq = self._seq.next(sch.TYPE_RESULT)
            msg = env.pack(sch.TYPE_RESULT, flags, self.hash, seq, r["t_result_ns"], payload,
                           src_board=env.SRC_AGX)
        return msg, r

    def publish(self, result: dict) -> dict | None:
        """Queue one result. Returns the canonical result dict, or None when it is dropped
        (duplicate, queue full, error, closed).
        The envelope seq is taken and the message is queued in one critical section: the seq on
        the wire always goes up by 1, also with many worker threads, and a message dropped because
        the queue is full uses no seq."""
        if self._stop.is_set():
            return None
        key = (str(result.get("instance") or result.get("model", "")), int(_get(result, "cam", 0)))
        ident = (int(_get(result, "frame_seq", 0)), int(_get(result, "t_capture_ns", 0)))
        with self._build_lock:
            if self._last_id.get(key) == ident:   # never re-send an old result (per model instance + camera)
                self.dropped_duplicate += 1
                return None
            self._last_id[key] = ident
        try:
            payload, flags, r = self._build(result)
        except Exception:  # noqa: BLE001
            self.errors += 1
            self._rlog.error("build", "cannot build result message", exc_info=True)
            return None
        with self._build_lock:
            if self._stop.is_set():
                return None
            if self._q.full():
                with self._lock:
                    self.dropped_queue += 1
                return None
            try:
                seq = self._seq.next(sch.TYPE_RESULT)
                msg = env.pack(sch.TYPE_RESULT, flags, self.hash, seq, r["t_result_ns"], payload,
                               src_board=env.SRC_AGX)
            except Exception:  # noqa: BLE001
                self.errors += 1
                self._rlog.error("pack", "cannot pack result message", exc_info=True)
                return None
            try:
                self._q.put_nowait(msg)   # only full at close (the None stop marker)
            except queue.Full:
                with self._lock:
                    self.dropped_queue += 1
                return None
        return r

    # ---- sender thread ---------------------------------------------------------------------------
    def _drain_monitor(self) -> None:
        while True:
            try:
                ev = recv_monitor_message(self._mon, zmq.NOBLOCK)
            except zmq.Again:
                return
            except zmq.ZMQError:
                return
            e = ev.get("event")
            with self._lock:
                if e == zmq.EVENT_ACCEPTED:
                    self.subscribers += 1
                elif e == zmq.EVENT_DISCONNECTED:
                    self.subscribers = max(0, self.subscribers - 1)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._drain_monitor()
            try:
                msg = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if msg is None:
                break
            try:
                self._sock.send(msg, zmq.NOBLOCK, copy=len(msg) < 65536)
            except zmq.Again:
                with self._lock:
                    self.dropped_queue += 1
                continue
            except zmq.ZMQError as e:
                self.errors += 1
                self._rlog.error("send", "results send failed: %s", e)
                continue
            now = time.monotonic()
            with self._lock:
                self.results_total += 1
                self.last_result_t = time.time()
                self._times.append(now)
        self._drain_monitor()

    # ---- stats -----------------------------------------------------------------------------------
    def rate_hz(self) -> float:
        now = time.monotonic()
        with self._lock:
            while self._times and now - self._times[0] > self.rate_window_s:
                self._times.popleft()
            return round(len(self._times) / self.rate_window_s, 2)

    def stats(self) -> dict:
        rate = self.rate_hz()
        with self._lock:
            return {"results_port": self.port, "results_rate_hz": rate,
                    "subscribers": self.subscribers, "results_total": self.results_total,
                    "last_result_t": self.last_result_t, "dropped_queue": self.dropped_queue,
                    "dropped_duplicate": self.dropped_duplicate, "errors": self.errors}

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=2.0)
        try:
            self._sock.disable_monitor()
        except zmq.ZMQError:
            pass
        self._mon.close(0)
        self._sock.close(0)
        log.info("results PUB closed (%d results sent)", self.results_total)
