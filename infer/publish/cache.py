"""Recent results per (model, cam), for the snapshots and the admin socket. Thread-safe."""
from __future__ import annotations

import threading
from collections import deque


class ResultCache:
    def __init__(self, keep: int = 16):
        self.keep = keep
        self._d: dict[tuple[str, int], deque] = {}
        self._lock = threading.Lock()

    def add(self, r: dict) -> None:
        """r: a canonical result dict (infer.publish.results.normalize_result)."""
        key = (r["model"], int(r["cam"]))
        with self._lock:
            q = self._d.get(key)
            if q is None:
                q = self._d[key] = deque(maxlen=self.keep)
            q.append(r)

    def newest(self, model: str, cam: int) -> dict | None:
        with self._lock:
            q = self._d.get((model, cam))
            return q[-1] if q else None

    def for_frame(self, cam: int, frame_seq: int, exact: bool = False,
                  t_ready_ns: int | None = None, max_age_s: float = 1.0) -> list[dict]:
        """Newest result of each model for this camera with result.frame_seq <= frame_seq
        (exact=True: == frame_seq). With t_ready_ns: skip results whose frame is more than
        max_age_s older than that frame (no old result on a new picture)."""
        out = []
        with self._lock:
            items = [(k, list(q)) for k, q in self._d.items() if k[1] == cam]
        for (_model, _cam), rs in sorted(items):
            for r in reversed(rs):
                if t_ready_ns is not None and r["t_ready_ns"] \
                        and t_ready_ns - r["t_ready_ns"] > max_age_s * 1e9:
                    break
                if (r["frame_seq"] == frame_seq) if exact else (r["frame_seq"] <= frame_seq):
                    out.append(r)
                    break
        return out
