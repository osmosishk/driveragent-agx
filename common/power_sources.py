"""Power sources of AGX02 (plug-in parts of the power log, interface: common/powerlog.py PowerSource).

jetson_rails: the on-board INA3221 sensors of the Jetson AGX Orin module, read from sysfs (no tegrastats process).
On AGX02 the rails are VDD_GPU_SOC, VDD_CPU_CV, VIN_SYS_5V0 (1-0040) and VDDQ_VDD2_1V8AO (1-0041). There is no
VDD_IN rail, so the supply input of the carrier board is NOT measured: the total is the sum of the module rails and
reads less than a meter at the supply input (the owner can set a correction factor on the pages). The same rail
values are in tegrastats (tegrastats shows 3 of the 4 rails).
"""
from __future__ import annotations

import glob
import os
import time

from common.powerlog import NO_SENSOR, SENSOR, PowerSource, Reading

INA_GLOBS = ("/sys/bus/i2c/drivers/ina3221/*/hwmon/hwmon*",)


def _read_int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


class JetsonRails(PowerSource):
    """Each rail: W = mV * mA / 1e6 from in<N>_input and curr<N>_input; total = the sum of the rails (not VDD_IN:
    the module has none). Channel list found once (labels do not change while the machine runs)."""
    name = "jetson_rails"

    def __init__(self, part: str = "agx02", globs: tuple[str, ...] = INA_GLOBS) -> None:
        self.part, self.globs = part, globs
        self.channels: list[tuple[str, str, str]] = []      # (rail name, in path, curr path)
        self.found = False

    def _find(self) -> None:
        self.channels = []
        for g in self.globs:
            for d in sorted(glob.glob(g)):
                for lab in sorted(glob.glob(os.path.join(d, "in*_label"))):
                    try:
                        with open(lab) as f:
                            name = f.read().strip()
                    except OSError:
                        continue
                    n = os.path.basename(lab)[2:-6]
                    if not name or name.lower().startswith("sum of"):
                        continue
                    vin, cur = os.path.join(d, f"in{n}_input"), os.path.join(d, f"curr{n}_input")
                    if os.path.exists(vin) and os.path.exists(cur):
                        self.channels.append((name, vin, cur))
        self.found = True

    def what(self) -> str:
        names = ", ".join(c[0] for c in self.channels)
        return (f"sum of the module rails {names} (INA3221); the supply input is not measured" if self.channels
                else "no INA3221 rail found")

    def read(self, now: float | None = None) -> list[Reading]:
        now = time.time() if now is None else now
        if not self.found:
            self._find()
        rails: dict[str, float] = {}
        for name, vin, cur in self.channels:
            mv, ma = _read_int(vin), _read_int(cur)
            if mv is not None and ma is not None:
                rails[name] = mv * ma / 1e6
        if not rails:
            return [Reading(self.part, None, NO_SENSOR, now, self.name, self.what())]
        if len(rails) < len(self.channels):         # a rail did not read: the sum would be too low
            return [Reading(self.part, None, NO_SENSOR, now, self.name,
                            f"{len(self.channels) - len(rails)} rail(s) did not read", rails)]
        return [Reading(self.part, sum(rails.values()), SENSOR, now, self.name, self.what(), rails)]

    def probe(self) -> dict:
        if not self.found:
            self._find()
        return {"source": self.name, "part": self.part, "used": bool(self.channels),
                "rails": [{"name": n, "in": v, "curr": c} for n, v, c in self.channels],
                "note": "INA3221 module rails; no VDD_IN rail, so the supply input is not measured"}
