"""Client for the agx-infer status PUB socket (contract agx-infer-status/1).

Multipart [topic, payload]:
  b"status"      JSON status, 1 Hz
  b"snap.<cam>"  JPEG snapshot (cam 0..5), 1 Hz per camera; the newest per camera is kept.
Staleness: no status for `stale_s` (3 s) -> state "NO DATA".
Ages and the status interval use time.monotonic() (a clock step does not change them); the
time.time() receive time is only sent to the page (status_rx_t).
Every field of the status can be missing or have a wrong type: the readers use _d() / _num().
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

log = logging.getLogger("dashboard.infer")

SCHEMA = "agx-infer-status/1"
MAX_STATUS_BYTES = 1 << 20
MAX_SNAP_BYTES = 4 << 20
MAX_MSG_BYTES = 8 << 20  # zmq drops (disconnects) any larger message part before it is buffered
MAX_CAMS = 6
NOT_RUNNING = "agx-infer not running"
SIM = "SIMULATED"


def _d(x) -> dict:
    """x when it is a dict, else {} (a status field with a wrong type does not break a reader)."""
    return x if isinstance(x, dict) else {}


def _l(x) -> list:
    return x if isinstance(x, list) else []


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def cam_simulated(c: dict, node_sim: bool) -> bool:
    """A camera is simulated when its own flag says so. The node flag is used only when the camera
    has no flag (agx-infer sets node.simulated when ONE camera is simulated: mixed mode)."""
    if isinstance(c.get("simulated"), bool):
        return c["simulated"]
    return node_sim


class InferStatusClient:
    def __init__(self, endpoint: str, stale_s: float = 3.0):
        self.endpoint = endpoint
        self.stale_s = float(stale_s)
        self._lock = threading.Lock()
        self._status: dict | None = None
        self._status_rx: float | None = None  # local receive time (time.time()), for the page
        self._status_rx_mono: float | None = None  # local receive time (time.monotonic()), for ages
        self.period_s = 1.0  # measured status interval (EMA of the receive intervals)
        self._gaps_skipped = 0
        self.seq = 0  # +1 for each accepted status (the SSE stream sends an event at once)
        self._snaps: dict[int, tuple[bytes, float, float]] = {}  # cam -> (jpeg, time(), monotonic())
        self._bad = 0
        self._last_err: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="infer-sub", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        try:
            import zmq
        except ImportError as e:
            self._last_err = f"pyzmq missing: {e}"
            log.error(self._last_err)
            return
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVHWM, 50)
        sock.setsockopt(zmq.MAXMSGSIZE, MAX_MSG_BYTES)
        sock.setsockopt(zmq.SUBSCRIBE, b"status")
        sock.setsockopt(zmq.SUBSCRIBE, b"snap.")
        sock.connect(self.endpoint)
        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)
        try:
            while not self._stop.is_set():
                if not dict(poller.poll(500)):
                    continue
                while True:
                    try:
                        parts = sock.recv_multipart(zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    self._handle(parts)
        except Exception as e:
            self._last_err = f"SUB loop error: {e}"
            log.exception("infer SUB loop failed")
        finally:
            sock.close(0)

    def _handle(self, parts: list[bytes]):
        if len(parts) != 2:
            self._bad += 1
            return
        topic, payload = parts
        now = time.time()
        mono = time.monotonic()
        if topic == b"status":
            if len(payload) > MAX_STATUS_BYTES:
                self._bad += 1
                return
            try:
                st = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self._bad += 1
                self._last_err = "status payload is not valid JSON"
                return
            if not isinstance(st, dict) or st.get("schema") != SCHEMA:
                self._bad += 1
                self._last_err = f"unknown schema {st.get('schema') if isinstance(st, dict) else None!r}"
                return
            with self._lock:
                self._status = st
                if self._status_rx_mono is not None:
                    dt = mono - self._status_rx_mono
                    # a gap (agx-infer paused, restarted) is not a new status rate: skip gaps longer than
                    # 2 x the period, but accept them after 3 in a row (the rate really changed)
                    if 0.02 < dt < 5.0 and (dt <= 2.0 * self.period_s or self._gaps_skipped >= 3):
                        self.period_s = 0.8 * self.period_s + 0.2 * dt
                        self._gaps_skipped = 0
                    elif dt >= 0.02:
                        self._gaps_skipped += 1
                self._status_rx = now
                self._status_rx_mono = mono
                self.seq += 1
        elif topic.startswith(b"snap."):
            try:
                cam = int(topic[5:].decode("ascii"))
            except ValueError:
                self._bad += 1
                return
            if not (0 <= cam < MAX_CAMS) or len(payload) > MAX_SNAP_BYTES or not payload.startswith(b"\xff\xd8"):
                self._bad += 1
                return
            with self._lock:
                self._snaps[cam] = (payload, now, mono)

    # ---- read
    def current(self) -> tuple[dict | None, str, str | None, float | None]:
        """(status or None when stale, state, reason, age_s)."""
        with self._lock:
            st, rx = self._status, self._status_rx_mono
        if st is None or rx is None:
            return None, "NO DATA", f"{NOT_RUNNING} (no status received on {self.endpoint})", None
        age = time.monotonic() - rx
        if age > self.stale_s:
            return None, "NO DATA", f"{NOT_RUNNING} (no status for {age:.0f} s)", round(age, 1)
        node = _d(st.get("node"))
        return st, str(node.get("state") or "UNKNOWN"), None, round(age, 2)

    def status_age_s(self) -> float | None:
        """Seconds since the newest status was received (monotonic clock)."""
        with self._lock:
            rx = self._status_rx_mono
        return None if rx is None else time.monotonic() - rx

    @staticmethod
    def _is_sim(x) -> bool:
        return isinstance(x, dict) and x.get("simulated") is True

    def summary(self) -> dict:
        """Health-level infer part. infer is None (+ reason) when agx-infer is not running."""
        st, state, reason, age = self.current()
        if st is None:
            return {"infer": None, "infer_state": state, "infer_reason": reason, "infer_age_s": age}
        node = _d(st.get("node"))
        cams = [c for c in _l(st.get("cameras")) if isinstance(c, dict)]
        models = [m for m in _l(st.get("models")) if isinstance(m, dict)]
        cam_states: dict[str, int] = {}
        for c in cams:
            cam_states[str(c.get("state"))] = cam_states.get(str(c.get("state")), 0) + 1
        mod_states: dict[str, int] = {}
        for m in models:
            mod_states[str(m.get("state"))] = mod_states.get(str(m.get("state")), 0) + 1
        node_sim = self._is_sim(node)
        cams_sim = any(cam_simulated(c, node_sim) for c in cams)
        infer = {
            "state": state,
            "simulated": bool(node_sim or cams_sim or any(self._is_sim(m) for m in models)),
            "node_simulated": node_sim,
            "version": node.get("version"),
            "uptime_s": node.get("uptime_s"),
            "pid": node.get("pid"),
            "age_s": age,
            "cameras_summary": {
                "total": len(cams), "states": cam_states, "simulated": cams_sim,
                "per_cam": [{"cam": c.get("cam"), "role": c.get("role"), "state": c.get("state"),
                             "fps": c.get("fps"), "frame_age_ms": c.get("frame_age_ms"),
                             "simulated": cam_simulated(c, node_sim)} for c in cams],
            },
            "models_summary": {
                "total": len(models), "states": mod_states,
                "simulated": bool(node_sim or any(self._is_sim(m) for m in models)),
                "per_model": [{"name": m.get("name"), "state": m.get("state"), "fps": m.get("fps"),
                               "lat_total_p50_ms": _num(_d(_d(m.get("lat_ms")).get("total")).get("p50")),
                               "error": m.get("error"),
                               "simulated": bool(node_sim or self._is_sim(m))} for m in models],
            },
            "errors": [str(e) for e in _l(node.get("errors"))],
        }
        return {"infer": infer, "infer_state": state, "infer_reason": None, "infer_age_s": age}

    def raw(self) -> tuple[dict | None, float | None]:
        """Newest status and its local receive time, also when it is stale."""
        with self._lock:
            return self._status, self._status_rx

    @staticmethod
    def newest_frame_t(st: dict) -> float | None:
        """Newest last_frame_t over the cameras (falls back to link.last_frame_t)."""
        ts = []
        for c in _l(st.get("cameras")):
            if isinstance(c, dict) and _num(c.get("last_frame_t")) is not None:
                ts.append(float(c["last_frame_t"]))
        lk = _num(_d(st.get("link")).get("last_frame_t"))
        if not ts and lk is not None:
            ts.append(lk)
        return max(ts) if ts else None

    def link_part(self, hold_s: float = 1.3, now: float | None = None) -> dict:
        """RK3588 link values from agx-infer, calculated NOW with the camera rule (infer_views):
        newest frame f (minimum frame age over the cameras), status time S, now N.
          N - f < hold_s : the value is S - f (frame age when agx-infer made the status). Newer frames
                           are possible but not known yet, so N - f is not a measured age.
          else           : the value is N - f (no newer frame is known; an upper limit).
        R13: the values carry simulated + label "SIMULATED" when the agx-infer source is simulated."""
        st, state, reason, _ = self.current()
        if st is None:
            na = f"n/a ({NOT_RUNNING})"
            return {"time_since_last_frame_ms": None, "time_since_last_frame_basis": None, "last_frame_t": None,
                    "results_rate_hz": None, "subscribers": None, "results_total": None, "last_result_t": None,
                    "infer_na": na, "simulated": False, "label": None}
        now = time.time() if now is None else now
        pub = _d(st.get("publish"))
        last = self.newest_frame_t(st)
        status_t = _num(st.get("t"))
        val = basis = None
        if last is not None:
            upper = max(0.0, now - last)
            if upper < hold_s and status_t is not None and status_t <= now + 1.0:
                val, basis = max(0.0, status_t - last), "agx-infer status (newer frames are possible)"
            else:
                val, basis = upper, "now - newest frame (upper limit)"
        node_sim = self._is_sim(st.get("node"))
        sim = bool(node_sim or any(isinstance(c, dict) and cam_simulated(c, node_sim)
                                   for c in _l(st.get("cameras"))))
        return {"time_since_last_frame_ms": round(val * 1000.0, 1) if val is not None else None,
                "time_since_last_frame_basis": basis,
                "last_frame_t": last,
                "results_rate_hz": _num(pub.get("results_rate_hz")),
                "subscribers": pub.get("subscribers") if isinstance(pub.get("subscribers"), int) else None,
                "results_total": pub.get("results_total") if isinstance(pub.get("results_total"), int) else None,
                "last_result_t": _num(pub.get("last_result_t")),
                "infer_na": None,
                "simulated": sim,
                "label": SIM if sim else None}

    def part(self, key: str) -> dict:
        st, state, reason, age = self.current()
        if st is None:
            return {"available": False, "reason": reason or NOT_RUNNING, "state": state}
        return {"available": True, "state": state, "age_s": age, "t": st.get("t"),
                "simulated": bool(self._is_sim(st.get("node"))), key: _l(st.get(key))}

    def metrics(self) -> dict:
        """History metrics: fps per camera, latency p50 per model (only when fresh).

        R13: values from a simulated source (node, camera or model simulated=true) are stored
        under a "sim_" prefix (sim_fps.camN, sim_lat_p50.<model>) so that they never mix with
        real data in the history; the page labels them SIMULATED.
        """
        st, _, _, _ = self.current()
        out: dict[str, float | None] = {}
        if st is None:
            return out
        node_sim = self._is_sim(st.get("node"))
        for c in _l(st.get("cameras")):
            if isinstance(c, dict) and c.get("cam") is not None and _num(c.get("fps")) is not None:
                pre = "sim_fps" if cam_simulated(c, node_sim) else "fps"
                try:
                    out[f"{pre}.cam{int(c['cam'])}"] = float(c["fps"])
                except (TypeError, ValueError):
                    pass
        for m in _l(st.get("models")):
            if not isinstance(m, dict) or not m.get("name"):
                continue
            p50 = _num(_d(_d(m.get("lat_ms")).get("total")).get("p50"))
            if p50 is not None:
                pre = "sim_lat_p50." if (node_sim or self._is_sim(m)) else "lat_p50."
                out[pre + re.sub(r"[^A-Za-z0-9_.-]", "_", str(m["name"]))[:48]] = float(p50)
        return out

    def snapshot(self, cam: int) -> tuple[bytes, float] | None:
        """(jpeg, receive time as time.time()) or None."""
        with self._lock:
            s = self._snaps.get(cam)
        return (s[0], s[1]) if s else None

    def snapshot_age_s(self, cam: int) -> float | None:
        """Seconds since the newest snapshot of this camera was received (monotonic clock)."""
        with self._lock:
            s = self._snaps.get(cam)
        return None if s is None else time.monotonic() - s[2]

    def debug(self) -> dict:
        return {"endpoint": self.endpoint, "bad_messages": self._bad, "last_error": self._last_err}
