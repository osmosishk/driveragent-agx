"""Measure the IDR interval of recorded H.265 files (count the AUs between IDR NAL types 19/20).

Usage: python -m tools.rk_sim.idr FILE.mp4 [FILE.mp4 ...]
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from tools.rk_sim.pipelines import Source, file_h265_passthrough

IDR_TYPES = (19, 20)   # IDR_W_RADL, IDR_N_LP
CRA_TYPE = 21


def nal_types(au: bytes) -> list[int]:
    """NAL unit types of one Annex-B access unit."""
    out = []
    i = 0
    while True:
        j = au.find(b"\x00\x00\x01", i)
        if j < 0 or j + 3 >= len(au):
            return out
        out.append((au[j + 3] >> 1) & 0x3F)
        i = j + 3


@dataclass
class IdrInfo:
    path: str
    aus: int
    idr_at: list[int]
    gaps: list[int]
    fps: float
    max_au: int
    mean_au: float
    vps_sps_pps_on_every_idr: bool

    @property
    def interval_aus(self) -> int:
        return max(self.gaps) if self.gaps else self.aus

    @property
    def interval_s(self) -> float:
        return self.interval_aus / self.fps if self.fps else 0.0

    def line(self) -> str:
        g = sorted(set(self.gaps))
        return (f"IDR interval {self.interval_aus} AU = {self.interval_s:.2f} s "
                f"(gaps {g}, {len(self.idr_at)} IDR in {self.aus} AU, fps {self.fps:.2f}, "
                f"AU max {self.max_au} B mean {self.mean_au:.0f} B, "
                f"VPS/SPS/PPS before every IDR: {'yes' if self.vps_sps_pps_on_every_idr else 'no'})")


def measure(path: str, max_aus: int = 0, timeout_s: float = 30.0) -> IdrInfo:
    src = Source(file_h265_passthrough(path), "h265")
    src.play()
    n, idr, sizes, ptss, params_ok = 0, [], [], [], True
    t_end = time.monotonic() + timeout_s
    try:
        while time.monotonic() < t_end and (not max_aus or n < max_aus):
            o = src.pull(1.0)
            if o is None:
                if src.eos() or src.poll_bus():
                    break
                continue
            t = nal_types(o.data)
            if any(x in IDR_TYPES for x in t):
                idr.append(n)
                if not {32, 33, 34} <= set(t):
                    params_ok = False
            sizes.append(len(o.data))
            if o.pts >= 0:
                ptss.append(o.pts)
            n += 1
    finally:
        src.stop()
    if src.error:
        raise RuntimeError(f"{path}: {src.error}")
    fps = 0.0
    if len(ptss) > 1 and ptss[-1] > ptss[0]:
        fps = (len(ptss) - 1) * 1e9 / (ptss[-1] - ptss[0])
    gaps = [b - a for a, b in zip(idr, idr[1:])]
    return IdrInfo(path, n, idr, gaps, fps, max(sizes) if sizes else 0,
                   sum(sizes) / len(sizes) if sizes else 0.0, params_ok)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for p in argv:
        print(f"{p}: {measure(p).line()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
