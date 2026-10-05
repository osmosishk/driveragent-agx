"""Newest-frame store, one slot per camera, shared by ingest (writer) and model workers (readers).

Only the newest frame of each camera is kept (older frames are dropped, never queued).
Frame identity = (cam, seq, t_capture_ns) from the FrameLink header; results carry it so the RK3588
can put a result on the same frame.

Camera state rules (night-task Section 6 + T6):
  OK         a new frame arrived less than STALE_S ago (source LIVE)
  SIMULATED  same as OK, but the source is the simulator / a file (R13 label)
  STALE      no new frame for >= STALE_S (0.5 s): models publish no result for this camera
  NO SIGNAL  no new frame for >= NO_SIGNAL_S (1.0 s), or never a frame
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

STALE_S = 0.5
NO_SIGNAL_S = 1.0


@dataclass
class Frame:
    cam: int
    seq: int
    t_capture_ns: int          # sender clock (FrameLink t_capture_ptp_ns); CLOCK_REALTIME until PTP
    t_recv_ns: int             # AGX CLOCK_REALTIME: last fragment of the frame received
    t_ready_ns: int            # AGX CLOCK_REALTIME: frame decoded and in the store (NV12: = t_recv_ns)
    width: int
    height: int
    fmt: str                   # wire format: "nv12" | "h265"
    source: str                # "live" | "replay" | "test-pattern" | "file"
    nv12: np.ndarray           # (height*3/2, width) uint8, tightly packed NV12 (BT.601 limited)
    decode_ms: float = 0.0
    t_ready_mono: float = field(default_factory=time.monotonic)

    @property
    def simulated(self) -> bool:
        return self.source != "live"

    def age_s(self, now_mono: float | None = None) -> float:
        return (time.monotonic() if now_mono is None else now_mono) - self.t_ready_mono


class FrameStore:
    def __init__(self, cams=range(6), stale_s: float = STALE_S, no_signal_s: float = NO_SIGNAL_S,
                 keep_recent: int = 8):
        self.cams = list(cams)
        self.stale_s = stale_s
        self.no_signal_s = no_signal_s
        self._newest: dict[int, Frame | None] = {c: None for c in self.cams}
        # a few recent frames per camera, so a viewer can fetch the exact frame of a result
        self._recent: dict[int, deque] = {c: deque(maxlen=keep_recent) for c in self.cams}
        self._cv = threading.Condition()
        self._version = 0

    def put(self, f: Frame) -> None:
        with self._cv:
            self._newest[f.cam] = f
            self._recent[f.cam].append(f)
            self._version += 1
            self._cv.notify_all()

    def newest(self, cam: int) -> Frame | None:
        with self._cv:
            return self._newest.get(cam)

    def find(self, cam: int, seq: int) -> Frame | None:
        with self._cv:
            for f in reversed(self._recent.get(cam, ())):
                if f.seq == seq:
                    return f
        return None

    def wait_new(self, cams, last_seq: dict[int, int], timeout: float) -> list[Frame]:
        """Return the newest frames of `cams` whose seq differs from last_seq[cam] and that are not
        stale. Blocks up to `timeout` s when there is none."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                now = time.monotonic()
                out = []
                for c in cams:
                    f = self._newest.get(c)
                    if f is not None and f.seq != last_seq.get(c) and now - f.t_ready_mono < self.stale_s:
                        out.append(f)
                if out:
                    return out
                rest = deadline - now
                if rest <= 0:
                    return []
                self._cv.wait(rest)

    def state(self, cam: int, now_mono: float | None = None) -> str:
        f = self.newest(cam)
        if f is None:
            return "NO SIGNAL"
        age = f.age_s(now_mono)
        if age >= self.no_signal_s:
            return "NO SIGNAL"
        if age >= self.stale_s:
            return "STALE"
        return "SIMULATED" if f.simulated else "OK"
