"""Client for the agx-infer status PUB socket (contract agx-infer-status/1).

Multipart [topic, payload]:
  b"status"      JSON status, 1 Hz
  b"snap.<cam>"  JPEG snapshot (cam 0..5), 1 Hz per camera; the newest per camera is kept.
Staleness: no status for `stale_s` (3 s) -> state "NO DATA".
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


class InferStatusClient:
    def __init__(self, endpoint: str, stale_s: float = 3.0):
        self.endpoint = endpoint
        self.stale_s = float(stale_s)
        self._lock = threading.Lock()
        self._status: dict | None = None
        self._status_rx: float | None = None  # local receive time (time.time())
        self._snaps: dict[int, tuple[bytes, float]] = {}
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
                self._status_rx = now
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
                self._snaps[cam] = (payload, now)

    # ---- read
    def current(self) -> tuple[dict | None, str, str | None, float | None]:
        """(status or None when stale, state, reason, age_s)."""
        with self._lock:
            st, rx = self._status, self._status_rx
        if st is None or rx is None:
            return None, "NO DATA", f"{NOT_RUNNING} (no status received on {self.endpoint})", None
        age = time.time() - rx
        if age > self.stale_s:
            return None, "NO DATA", f"{NOT_RUNNING} (no status for {age:.0f} s)", round(age, 1)
        node = st.get("node") or {}
        return st, str(node.get("state") or "UNKNOWN"), None, round(age, 2)

    @staticmethod
    def _is_sim(x) -> bool:
        return isinstance(x, dict) and x.get("simulated") is True

    def summary(self) -> dict:
        """Health-level infer part. infer is None (+ reason) when agx-infer is not running."""
        st, state, reason, age = self.current()
        if st is None:
            return {"infer": None, "infer_state": state, "infer_reason": reason, "infer_age_s": age}
        node = st.get("node") or {}
        cams = [c for c in st.get("cameras") or [] if isinstance(c, dict)]
        models = [m for m in st.get("models") or [] if isinstance(m, dict)]
        cam_states: dict[str, int] = {}
        for c in cams:
            cam_states[str(c.get("state"))] = cam_states.get(str(c.get("state")), 0) + 1
        mod_states: dict[str, int] = {}
        for m in models:
            mod_states[str(m.get("state"))] = mod_states.get(str(m.get("state")), 0) + 1
        cams_sim = any(self._is_sim(c) for c in cams)
        node_sim = self._is_sim(node)
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
                             "simulated": self._is_sim(c)} for c in cams],
            },
            "models_summary": {
                "total": len(models), "states": mod_states,
                "simulated": bool(node_sim or any(self._is_sim(m) for m in models)),
                "per_model": [{"name": m.get("name"), "state": m.get("state"), "fps": m.get("fps"),
                               "lat_total_p50_ms": ((m.get("lat_ms") or {}).get("total") or {}).get("p50"),
                               "error": m.get("error"),
                               "simulated": bool(node_sim or self._is_sim(m))} for m in models],
            },
            "errors": list(node.get("errors") or []),
        }
        return {"infer": infer, "infer_state": state, "infer_reason": None, "infer_age_s": age}

    def link_part(self) -> dict:
        st, state, reason, _ = self.current()
        if st is None:
            na = f"n/a ({NOT_RUNNING})"
            return {"time_since_last_frame_ms": None, "results_rate_hz": None, "subscribers": None,
                    "infer_na": na}
        pub = st.get("publish") or {}
        lk = st.get("link") or {}
        return {"time_since_last_frame_ms": lk.get("time_since_last_frame_ms"),
                "last_frame_t": lk.get("last_frame_t"),
                "results_rate_hz": pub.get("results_rate_hz"),
                "subscribers": pub.get("subscribers"),
                "infer_na": None}

    def part(self, key: str) -> dict:
        st, state, reason, age = self.current()
        if st is None:
            return {"available": False, "reason": reason or NOT_RUNNING, "state": state}
        return {"available": True, "state": state, "age_s": age, "t": st.get("t"),
                "simulated": bool(self._is_sim(st.get("node"))), key: st.get(key) or []}

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
        for c in st.get("cameras") or []:
            if isinstance(c, dict) and c.get("cam") is not None and isinstance(c.get("fps"), (int, float)):
                pre = "sim_fps" if (node_sim or self._is_sim(c)) else "fps"
                try:
                    out[f"{pre}.cam{int(c['cam'])}"] = float(c["fps"])
                except (TypeError, ValueError):
                    pass
        for m in st.get("models") or []:
            if not isinstance(m, dict) or not m.get("name"):
                continue
            p50 = ((m.get("lat_ms") or {}).get("total") or {}).get("p50")
            if isinstance(p50, (int, float)):
                pre = "sim_lat_p50." if (node_sim or self._is_sim(m)) else "lat_p50."
                out[pre + re.sub(r"[^A-Za-z0-9_.-]", "_", str(m["name"]))[:48]] = float(p50)
        return out

    def snapshot(self, cam: int) -> tuple[bytes, float] | None:
        with self._lock:
            return self._snaps.get(cam)

    def debug(self) -> dict:
        return {"endpoint": self.endpoint, "bad_messages": self._bad, "last_error": self._last_err}
