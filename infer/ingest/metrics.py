"""Per-camera ingest metrics. Thread-safe: receive threads and GStreamer threads write, the
dashboard / probe reads snapshot().

Loss counters (FrameLink):
  lost_fragments   fragments that did not arrive in frames that started but did not complete
                   (Reassembler.lost_fragments)
  abandoned_frames frames that started but did not complete (Reassembler.abandoned)
  lost_frames      frames that did not get to the store: FrameLink seq gaps between frames that came
                   out of the reassembler (this includes the abandoned frames, the frames with a bad
                   header and the frames of which no fragment arrived) + frames with a bad payload CRC
  missing_frames   lost_frames - abandoned_frames - bad_frames - ring_overruns (min 0): frames
                   of which no fragment arrived
  ring_overruns    frames lost in this AGX: the main process read a ring slot too late
  lost_packets     lost_fragments + missing_frames * (mean fragments per frame): an ESTIMATE of the
                   lost UDP datagrams
Other counters (not losses):
  late_datagrams   duplicate or late fragments of a frame that was already complete (dropped)
  start_partial    the receiver started in the middle of a frame; that first frame is dropped
                   (not counted in abandoned_frames / lost_fragments)
  new_streams      the reassembler saw a sender restart (seq jump back, or data after a quiet socket)
  seq_resets       the frame seq went back (sender restart); the H.265 gate waits for a new IDR
  foreign_frames   frames with the header of another camera on this port (dropped)
  rx_restarts      the receive process ended and was started again
  internal_errors  exceptions in the frame handling (the frame is dropped, the camera continues)
"""
from __future__ import annotations

import threading
import time
from collections import deque


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


class CameraMetrics:
    def __init__(self, cam: int, role: str = "", port: int | None = None, mode: str = "sim",
                 store=None, expect_simulated: bool = True):
        self.cam = cam
        self.role = role
        self.port = port
        self.mode = mode
        self.store = store
        self.expect_simulated = expect_simulated
        self._lock = threading.Lock()
        self._t_start = time.monotonic()
        # datagram / byte flow: (t_mono, bytes) per flush (the receiver flushes about every 20 ms)
        self._rx = deque(maxlen=4096)
        self.datagrams = 0
        self.rx_bytes = 0
        self._t_last_rx = None
        # frames into the store
        self._frame_t = deque(maxlen=2048)
        self.frames_total = 0
        self._decode_ms = deque(maxlen=300)
        self._lat_ms = deque(maxlen=300)        # t_ready - t_capture (sender clock, see Frame)
        self.fmt = None
        self.width = None
        self.height = None
        self.last_seq = None
        self.last_frame_t = None
        self.source = None
        self.health = None
        self.frags_per_frame = deque(maxlen=300)
        # counters set by the receiver / file source
        self.c = dict(lost_fragments=0, abandoned_frames=0, lost_frames=0, bad_datagrams=0,
                      bad_frames=0, waiting_idr=0, decoder_errors=0, decoder_drops=0,
                      seq_resets=0, source_mismatch=0, file_loops=0, rcvbuf=None,
                      ring_overruns=0, late_datagrams=0, new_streams=0, foreign_frames=0,
                      rx_restarts=0, internal_errors=0, start_partial=0)
        self.last_error = ""

    # ---- writers ---------------------------------------------------------------------------------
    def add_rx(self, nbytes: int, ndgrams: int, t_mono: float | None = None) -> None:
        t = time.monotonic() if t_mono is None else t_mono
        with self._lock:
            self._rx.append((t, nbytes))
            self.datagrams += ndgrams
            self.rx_bytes += nbytes
            self._t_last_rx = t

    def set_counters(self, **kw) -> None:
        with self._lock:
            self.c.update(kw)

    def add_counter(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.c[name] = (self.c.get(name) or 0) + n

    def set_error(self, text: str) -> None:
        with self._lock:
            self.last_error = text

    def on_frame(self, f, nfrags: int | None = None) -> None:
        """Call after store.put(f)."""
        t = f.t_ready_mono
        with self._lock:
            self._frame_t.append(t)
            self.frames_total += 1
            self.fmt = f.fmt
            self.width, self.height = f.width, f.height
            self.last_seq = f.seq
            self.last_frame_t = f.t_ready_ns / 1e9
            self.source = f.source
            if f.decode_ms:
                self._decode_ms.append(f.decode_ms)
            self._lat_ms.append((f.t_ready_ns - f.t_capture_ns) / 1e6)
            if nfrags:
                self.frags_per_frame.append(nfrags)

    # ---- reader ----------------------------------------------------------------------------------
    def snapshot(self, now_mono: float | None = None) -> dict:
        now = time.monotonic() if now_mono is None else now_mono
        with self._lock:
            n1 = sum(1 for t in self._frame_t if now - t < 1.0)
            n5 = sum(1 for t in self._frame_t if now - t < 5.0)
            win5 = min(5.0, max(1e-3, now - self._t_start))
            b1 = sum(b for (t, b) in self._rx if now - t < 1.0)
            dms = sorted(self._decode_ms)
            lat = sorted(self._lat_ms)
            fpf = (sum(self.frags_per_frame) / len(self.frags_per_frame)) if self.frags_per_frame else 0.0
            c = dict(self.c)
            missing = max(0, c["lost_frames"] - c["abandoned_frames"] - c["bad_frames"]
                          - c["ring_overruns"])
            receiving = (self._t_last_rx is not None and now - self._t_last_rx < 1.0) or n1 > 0
            snap = {
                "cam": self.cam, "role": self.role, "port": self.port, "mode": self.mode,
                "receiving": receiving,
                "fmt": self.fmt, "width": self.width, "height": self.height,
                "source": self.source, "sender_health": self.health,
                "fps": float(n1), "fps_5s": round(n5 / win5, 2),
                "bitrate_kbps": round(b1 * 8 / 1000.0, 1),
                "datagrams": self.datagrams, "rx_bytes": self.rx_bytes,
                "frames": self.frames_total,
                "lost_fragments": c["lost_fragments"],
                "lost_frames": c["lost_frames"],
                "abandoned_frames": c["abandoned_frames"],
                "missing_frames": missing,
                "lost_packets": int(round(c["lost_fragments"] + missing * fpf)),
                "bad": c["bad_datagrams"] + c["bad_frames"],
                "bad_datagrams": c["bad_datagrams"], "bad_frames": c["bad_frames"],
                "waiting_idr": c["waiting_idr"],
                "decoder_errors": c["decoder_errors"], "decoder_drops": c["decoder_drops"],
                "seq_resets": c["seq_resets"], "source_mismatch": c["source_mismatch"],
                "file_loops": c["file_loops"], "rcvbuf": c["rcvbuf"],
                "ring_overruns": c["ring_overruns"],
                "late_datagrams": c["late_datagrams"], "new_streams": c["new_streams"],
                "foreign_frames": c["foreign_frames"], "rx_restarts": c["rx_restarts"],
                "internal_errors": c["internal_errors"], "start_partial": c["start_partial"],
                "decode_ms": {"p50": _pct(dms, 0.5), "p95": _pct(dms, 0.95),
                              "max": dms[-1] if dms else None, "n": len(dms)},
                "capture_to_ready_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95)},
                "last_seq": self.last_seq, "last_frame_t": self.last_frame_t,
                "last_error": self.last_error,
            }
        # store reads take the store lock: do them outside our lock
        state = "NO SIGNAL"
        age_ms = None
        simulated = self.expect_simulated
        if self.store is not None:
            state = self.store.state(self.cam, now)
            f = self.store.newest(self.cam)
            if f is not None:
                age_ms = round(f.age_s(now) * 1000.0, 1)
                simulated = f.simulated
        snap["state"] = state
        snap["frame_age_ms"] = age_ms
        snap["simulated"] = simulated
        return snap
