"""System monitor: one JSON line per sample.

  python -m tools.sysmon --seconds N --out file.jsonl [--interval 1]

Each line: t (unix s), cpu_pct (total), cpu_pct_per_core, gpu_load_pct (sysfs load / 10),
ram_used_mb / ram_total_mb, swap_used_mb / swap_total_mb, temps_c {zone: deg C} (unreadable zones are
skipped), power_w {rail: W} from the INA3221 monitors + power_total_w (sum of the rails), and procs
{"infer.main"|"tools.rk_sim"|"dashboard.main": [{pid, rss_mb, cpu_pct}]}.
Read-only: it only reads /proc and /sys.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import psutil

GPU_LOAD = "/sys/devices/platform/bus@0/17000000.gpu/load"
PROC_KEYS = ("infer.main", "tools.rk_sim", "dashboard.main")


def _read(path: str):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, TypeError):   # TypeError: EAGAIN on some Jetson zones gives read() None
        return None


def gpu_load_pct():
    v = _read(GPU_LOAD)
    try:
        return int(v) / 10.0
    except (TypeError, ValueError):
        return None


def temps_c() -> dict:
    out = {}
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        name, v = _read(os.path.join(z, "type")), _read(os.path.join(z, "temp"))
        try:
            out[name or os.path.basename(z)] = int(v) / 1000.0
        except (TypeError, ValueError):
            continue
    return out


def power_w() -> dict:
    """INA3221 rails: in<N>_input (mV) x curr<N>_input (mA)."""
    out = {}
    for hw in sorted(glob.glob("/sys/bus/i2c/drivers/ina3221/*/hwmon/hwmon*")):
        for lab in sorted(glob.glob(os.path.join(hw, "in*_label"))):
            n = os.path.basename(lab)[2:-6]
            name = _read(lab)
            mv, ma = _read(os.path.join(hw, f"in{n}_input")), _read(os.path.join(hw, f"curr{n}_input"))
            try:
                out[name] = round(int(mv) * int(ma) / 1e6, 3)
            except (TypeError, ValueError):
                continue
    return out


class ProcTracker:
    def __init__(self):
        self._p: dict[int, psutil.Process] = {}

    def sample(self) -> dict:
        out = {k: [] for k in PROC_KEYS}
        seen = set()
        for p in psutil.process_iter(["pid", "cmdline"]):
            argv = p.info.get("cmdline") or []
            cmd = " ".join(argv)
            key = next((k for k in PROC_KEYS if k in cmd), None)
            # only the Python process itself (not a "timeout ..." or shell wrapper)
            if key is None or "tools.sysmon" in cmd or not argv or "python" not in os.path.basename(argv[0]):
                continue
            pid = p.info["pid"]
            seen.add(pid)
            proc = self._p.get(pid)
            if proc is None:
                proc = self._p[pid] = p
                try:
                    proc.cpu_percent(None)   # first call starts the measurement
                except psutil.Error:
                    continue
                cpu = None
            else:
                try:
                    cpu = proc.cpu_percent(None)
                except psutil.Error:
                    continue
            try:
                rss = proc.memory_info().rss / 1e6
            except psutil.Error:
                continue
            out[key].append({"pid": pid, "rss_mb": round(rss, 1), "cpu_pct": cpu})
        for pid in list(self._p):
            if pid not in seen:
                del self._p[pid]
        return out


def sample(pt: ProcTracker) -> dict:
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    per = psutil.cpu_percent(None, percpu=True)
    pw = power_w()
    return {
        "t": round(time.time(), 3),
        "cpu_pct": round(sum(per) / len(per), 1) if per else None,
        "cpu_pct_per_core": per,
        "gpu_load_pct": gpu_load_pct(),
        "ram_used_mb": round((vm.total - vm.available) / 1e6, 1), "ram_total_mb": round(vm.total / 1e6, 1),
        "swap_used_mb": round(sw.used / 1e6, 1), "swap_total_mb": round(sw.total / 1e6, 1),
        "temps_c": temps_c(),
        "power_w": pw, "power_total_w": round(sum(pw.values()), 3) if pw else None,
        "procs": pt.sample(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="system monitor -> JSON lines")
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args(argv)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    pt = ProcTracker()
    psutil.cpu_percent(None, percpu=True)
    pt.sample()
    n_total = max(1, int(round(a.seconds / a.interval)))
    n = 0
    with open(a.out, "w") as f:
        nxt = time.monotonic() + a.interval
        while n < n_total:
            d = nxt - time.monotonic()
            if d > 0:
                time.sleep(d)
            f.write(json.dumps(sample(pt)) + "\n")
            f.flush()
            n += 1
            nxt += a.interval
    print(f"wrote {n} samples to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
