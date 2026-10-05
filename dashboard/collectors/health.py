"""AGX health from /proc and /sys (no root, no jtop daemon needed). Sampled every 1 s.

Power rails (INA3221, verified on agx02 2026-10-05 against `tegrastats --interval 1000`):
  in<N>_input is mV, curr<N>_input is mA, so W = mV * mA / 1e6.
  1-0040 ch1 VDD_GPU_SOC 19864 mV * 180 mA = 3.58 W  <-> tegrastats VDD_GPU_SOC 3575 mW (match)
  1-0040 ch2 VDD_CPU_CV, ch3 VIN_SYS_5V0, 1-0041 ch2 VDDQ_VDD2_1V8AO.
  This board has NO VDD_IN rail (tegrastats shows only VDD_GPU_SOC, VDD_CPU_CV, VIN_SYS_5V0).
  So power.total_w = sum of all labelled rails (same as jtop "tot"), listed in power.total_rails.
  It is NOT the board input power, and it includes VDDQ_VDD2_1V8AO, which tegrastats does not
  show (so it is ~0.6 W above the tegrastats 3-rail sum). total_source says this.
  If a VDD_IN rail shows up (other carrier boards), it is used as the total instead.
  in4..in6 are shunt voltages and in7 is "sum of shunt voltages": not rails, ignored.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("dashboard.health")

GPU_LOAD = "/sys/devices/platform/bus@0/17000000.gpu/load"
GPU_FREQ = "/sys/devices/platform/bus@0/17000000.gpu/devfreq/17000000.gpu/cur_freq"
INA_GLOBS = ["/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*",
             "/sys/bus/i2c/drivers/ina3221/1-0041/hwmon/hwmon*"]
REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "vfat", "exfat", "f2fs", "ntfs", "ntfs3", "fuseblk"}


def _read_err(path: str) -> tuple[str | None, str | None]:
    # binary read: some sysfs files (powered-off thermal zones) give EAGAIN, which breaks
    # the text-mode decoder with a TypeError instead of an OSError
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            chunks = []
            while True:
                b = os.read(fd, 65536)
                if not b or len(chunks) > 16:
                    break
                chunks.append(b)
            data = b"".join(chunks)
        finally:
            os.close(fd)
        return data.decode("utf-8", "replace").strip(), None
    except OSError as e:
        return None, (e.strerror or str(e))
    except (TypeError, ValueError) as e:
        return None, str(e)


def _read(path: str) -> str | None:
    return _read_err(path)[0]


def level_of(value: float | None, lim: dict) -> str:
    if value is None:
        return "n/a"
    if value >= lim["crit"]:
        return "crit"
    if value >= lim["warn"]:
        return "warn"
    return "ok"


LEVEL_RANK = {"ok": 0, "warn": 1, "crit": 2}


def worst(levels) -> str:
    """Worst of the measured levels; "n/a" when no level is measured (n/a is not ok)."""
    ranks = [LEVEL_RANK[lv] for lv in levels if lv in LEVEL_RANK]
    if not ranks:
        return "n/a"
    return ["ok", "warn", "crit"][max(ranks)]


class HealthCollector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.limits = cfg["limits"]
        self.ncpu = os.cpu_count() or 1
        self.hostname = socket.gethostname()
        self._prev_stat: dict[int, tuple[int, int]] = {}
        self._prev_net: dict[str, tuple[float, int, int]] = {}
        self._nvp: dict = {"mode": None, "id": None, "error": "not read yet"}
        self._nvp_t = 0.0
        self._addrs: dict[str, list[str]] = {}
        self._addrs_t = 0.0
        self._lock = threading.Lock()
        self._snap: dict | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listeners = []  # callables(snapshot) called after each sample
        self._fan_pwm = self._find_hwmon_file(["pwmfan", "pwm-fan"], "pwm1")
        self._fan_rpm = self._find_rpm()

    # ---- lifecycle
    def start(self):
        self.sample()  # prime deltas
        self._thread = threading.Thread(target=self._run, name="health", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def add_listener(self, fn):
        self._listeners.append(fn)

    def latest(self) -> dict | None:
        with self._lock:
            return self._snap

    def _run(self):
        nxt = time.monotonic()
        while not self._stop.is_set():
            nxt += 1.0
            if self._stop.wait(max(0.0, nxt - time.monotonic())):
                break
            try:
                snap = self.sample()
                for fn in self._listeners:
                    try:
                        fn(snap)
                    except Exception:
                        log.exception("health listener failed")
            except Exception:
                log.exception("health sample failed")
            if nxt < time.monotonic() - 1.0:
                nxt = time.monotonic()  # fell behind: do not burst

    # ---- sample
    def sample(self) -> dict:
        errors: list[str] = []
        now = time.time()
        snap = {
            "hostname": self.hostname,
            "t": now,
            "time_iso": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
            "uptime_s": self._uptime(errors),
            "nvpmodel": self._nvpmodel(now),
            "cpu": self._cpu(errors),
            "gpu": self._gpu(errors),
        }
        snap["ram"], snap["swap"] = self._mem(errors)
        snap["temps"] = self._temps(errors)
        snap["power"] = self._power(errors)
        snap["fan"] = self._fan(errors)
        snap["disk"] = self._disk(errors)
        snap["net"] = self._net(errors, now)
        snap["errors"] = errors
        with self._lock:
            self._snap = snap
        return snap

    def _uptime(self, errors):
        v = _read("/proc/uptime")
        if v is None:
            errors.append("uptime: /proc/uptime not readable")
            return None
        return round(float(v.split()[0]), 1)

    def _nvpmodel(self, now):
        if now - self._nvp_t >= self.cfg.get("nvpmodel_interval_s", 30):
            self._nvp_t = now
            try:
                r = subprocess.run(["nvpmodel", "-q"], capture_output=True, text=True, timeout=5)
                mode, mid = None, None
                for line in r.stdout.splitlines():
                    m = re.match(r"NV Power Mode:\s*(.+)", line.strip())
                    if m:
                        mode = m.group(1).strip()
                    elif line.strip().isdigit():
                        mid = int(line.strip())
                if mode:
                    self._nvp = {"mode": mode, "id": mid, "error": None}
                else:
                    self._nvp = {"mode": None, "id": None,
                                 "error": f"nvpmodel -q gave no mode (rc {r.returncode})"}
            except (OSError, subprocess.SubprocessError) as e:
                self._nvp = {"mode": None, "id": None, "error": f"nvpmodel -q failed: {e}"}
        return dict(self._nvp)

    def _cpu(self, errors):
        per = [None] * self.ncpu
        freq = [None] * self.ncpu
        per_na: dict[str, str] = {}
        freq_na: dict[str, str] = {}
        seen: set[int] = set()
        txt = _read("/proc/stat")
        if txt is None:
            errors.append("cpu: /proc/stat not readable")
        else:
            for line in txt.splitlines():
                m = re.match(r"cpu(\d+)\s+(.*)", line)
                if not m:
                    continue
                i = int(m.group(1))
                vals = [int(x) for x in m.group(2).split()]
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                total = sum(vals[:8])
                seen.add(i)
                prev = self._prev_stat.get(i)
                self._prev_stat[i] = (total, idle)
                if prev is None and i < self.ncpu:
                    per_na[str(i)] = "first sample: no delta yet"
                if prev and i < self.ncpu:
                    dt = total - prev[0]
                    di = idle - prev[1]
                    per[i] = round(max(0.0, min(100.0, 100.0 * (dt - di) / dt)), 1) if dt > 0 else 0.0
        for i in range(self.ncpu):
            if txt is not None and i not in seen:
                per_na[str(i)] = "core offline (not in /proc/stat)"
            elif txt is None:
                per_na[str(i)] = "/proc/stat not readable"
            f, e = _read_err(f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq")
            if f and f.isdigit():
                freq[i] = int(f) // 1000  # kHz -> MHz, floor (same as tegrastats)
            else:
                freq_na[str(i)] = f"scaling_cur_freq not readable ({e or 'no number'})"
        vals = [v for v in per if v is not None]
        out = {
            "load_pct_avg": round(sum(vals) / len(vals), 1) if vals else None,
            "per_core": per,
            "freq_mhz": freq,
            "online": len(seen) if txt is not None else None,
        }
        if per_na:
            out["per_core_na"] = per_na
        if freq_na:
            out["freq_na"] = freq_na
        if not vals:
            out["load_na"] = "no core load value yet" if per_na else "n/a"
        return out

    def _gpu(self, errors):
        out = {"load_pct": None, "freq_mhz": None}
        v, e = _read_err(GPU_LOAD)
        if v is not None and v.lstrip("-").isdigit():
            out["load_pct"] = round(int(v) / 10.0, 1)
        else:
            errors.append(f"gpu load: {GPU_LOAD} not readable ({e})")
        if out["load_pct"] is None:
            out["load_na"] = f"{GPU_LOAD} not readable ({e or 'no number'})"
        f, fe = _read_err(GPU_FREQ)
        if f and f.isdigit():
            out["freq_mhz"] = int(f) // 1_000_000  # Hz -> MHz, floor
        else:
            out["freq_na"] = f"{GPU_FREQ} not readable ({fe or 'no number'})"
        return out

    def _mem(self, errors):
        txt = _read("/proc/meminfo")
        info = {}
        if txt is None:
            errors.append("ram: /proc/meminfo not readable")
        else:
            for line in txt.splitlines():
                k, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    info[k] = int(parts[0])  # kB
        lim = self.limits["ram_pct"]
        if "MemTotal" in info and "MemAvailable" in info:
            tot = info["MemTotal"] / 1024
            used = (info["MemTotal"] - info["MemAvailable"]) / 1024
            pct = round(100.0 * used / tot, 1) if tot else None
            ram = {"total_mb": round(tot), "used_mb": round(used),
                   "available_mb": round(info["MemAvailable"] / 1024), "pct": pct,
                   "level": level_of(pct, lim), "used_def": "MemTotal - MemAvailable (/proc/meminfo)",
                   "note": "On Jetson, the GPU and the CPU use the same RAM"}
        else:
            ram = {"total_mb": None, "used_mb": None, "pct": None, "level": "n/a",
                   "na": "/proc/meminfo not readable" if txt is None
                   else "MemTotal or MemAvailable missing in /proc/meminfo"}
        if "SwapTotal" in info and "SwapFree" in info:
            st = info["SwapTotal"] / 1024
            su = (info["SwapTotal"] - info["SwapFree"]) / 1024
            swap = {"total_mb": round(st), "used_mb": round(su),
                    "pct": round(100.0 * su / st, 1) if st else 0.0}
        else:
            swap = {"total_mb": None, "used_mb": None, "pct": None,
                    "na": "/proc/meminfo not readable" if txt is None
                    else "SwapTotal or SwapFree missing in /proc/meminfo"}
        return ram, swap

    def _temps(self, errors):
        zones: dict = {}
        na: dict = {}
        for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*"),
                        key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
            name = _read(os.path.join(z, "type")) or os.path.basename(z)
            v, e = _read_err(os.path.join(z, "temp"))
            if v is not None and v.lstrip("-").isdigit():
                c = int(v) / 1000.0
                # -256 C / very low values mean "sensor off"
                if c > -40:
                    zones[name] = round(c, 1)
                    continue
                e = "sensor gives invalid value"
            zones[name] = None
            na[name] = f"not readable: {e}"
        valid = {k: v for k, v in zones.items() if v is not None}
        if not valid:
            errors.append("temps: no thermal zone readable")
        max_zone = max(valid, key=valid.get) if valid else None
        max_c = valid[max_zone] if max_zone else None
        return {"max_c": max_c, "max_zone": max_zone,
                "level": level_of(max_c, self.limits["temp_c"]), "zones": zones, "na": na}

    def _power(self, errors):
        rails = {}
        for g in INA_GLOBS:
            for d in glob.glob(g):
                for lab in glob.glob(os.path.join(d, "in*_label")):
                    n = re.search(r"in(\d+)_label", lab).group(1)
                    name = _read(lab)
                    if not name or name.lower().startswith("sum of"):
                        continue
                    mv = _read(os.path.join(d, f"in{n}_input"))
                    ma = _read(os.path.join(d, f"curr{n}_input"))
                    if mv and ma and mv.lstrip("-").isdigit() and ma.lstrip("-").isdigit():
                        rails[name] = {"v": round(int(mv) / 1000, 3), "a": round(int(ma) / 1000, 3),
                                       "w": round(int(mv) * int(ma) / 1e6, 2)}
                    else:
                        rails[name] = {"v": None, "a": None, "w": None,
                                       "na": f"in{n}_input or curr{n}_input not readable"}
        valid = {k: r["w"] for k, r in rails.items() if r["w"] is not None}
        if "VDD_IN" in valid:
            total, used, src = valid["VDD_IN"], ["VDD_IN"], "VDD_IN rail (board input)"
        elif valid:
            used = sorted(valid)
            total = round(sum(valid.values()), 2)
            src = ("sum of " + "+".join(used) + " (no VDD_IN rail on this board; this is not the "
                   "board input power; tegrastats does not show VDDQ_VDD2_1V8AO)")
        else:
            total, used, src = None, [], "n/a (no INA3221 rail readable)"
            errors.append("power: no INA3221 rail readable")
        return {"total_w": total, "total_source": src, "total_rails": used, "rails": rails}

    @staticmethod
    def _find_hwmon_file(names, fname):
        for h in glob.glob("/sys/class/hwmon/hwmon*"):
            n = _read(os.path.join(h, "name")) or ""
            if n in names or "fan" in n:
                p = os.path.join(h, fname)
                if os.path.exists(p):
                    return p
        return None

    @staticmethod
    def _find_rpm():
        for p in sorted(glob.glob("/sys/class/hwmon/hwmon*/rpm") + glob.glob("/sys/class/hwmon/hwmon*/fan*_input")):
            return p
        return None

    def _fan(self, errors):
        out = {"pwm_pct": None, "pwm_raw": None, "rpm": None}
        if self._fan_pwm:
            v, e = _read_err(self._fan_pwm)
            if v and v.isdigit():
                out["pwm_raw"] = int(v)
                out["pwm_pct"] = round(int(v) * 100 / 255, 1)
            else:
                out["pwm_na"] = f"{self._fan_pwm} not readable ({e or 'no number'})"
        else:
            out["pwm_na"] = "no pwmfan hwmon found"
        if self._fan_rpm:
            v, e = _read_err(self._fan_rpm)
            if v and v.lstrip("-").isdigit():
                out["rpm"] = int(v)
            else:
                out["rpm_na"] = f"{self._fan_rpm} not readable ({e or 'no number'})"
        else:
            out["rpm_na"] = "no tach (rpm) hwmon found"
        return out

    def _disk(self, errors):
        out, seen = [], set()
        txt = _read("/proc/mounts") or ""
        for line in txt.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            dev, mnt, fs = parts[0], parts[1].replace("\\040", " "), parts[2]
            if fs not in REAL_FS or dev in seen:
                continue
            seen.add(dev)
            try:
                st = os.statvfs(mnt)
            except OSError as e:
                errors.append(f"disk {mnt}: {e.strerror}")
                continue
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
            # same formula as df: used / (used + avail)
            pct = round(100.0 * used / (used + free), 1) if (used + free) else None
            # *_gb are SI (10^9 bytes); *_gib are binary (2^30 bytes, the unit of `df -h`)
            gib = float(1 << 30)
            out.append({"mount": mnt, "dev": dev, "fs": fs,
                        "total_gb": round(total / 1e9, 2), "used_gb": round(used / 1e9, 2),
                        "free_gb": round(free / 1e9, 2),
                        "total_gib": round(total / gib, 2), "used_gib": round(used / gib, 2),
                        "free_gib": round(free / gib, 2), "pct": pct,
                        "level": level_of(pct, self.limits["disk_pct"])})
        return out

    def _ipv4_addrs(self, now):
        if now - self._addrs_t < 10 and self._addrs:
            return self._addrs
        self._addrs_t = now
        try:
            r = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=3)
            data = json.loads(r.stdout or "[]")
            self._addrs = {d["ifname"]: [f'{a["local"]}/{a["prefixlen"]}' for a in d.get("addr_info", [])
                                         if a.get("family") == "inet"] for d in data}
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            self._addrs = {}
        return self._addrs

    def _net(self, errors, now):
        counters = {}
        txt = _read("/proc/net/dev") or ""
        for line in txt.splitlines()[2:]:
            name, _, rest = line.partition(":")
            vals = rest.split()
            if len(vals) >= 9:
                counters[name.strip()] = (int(vals[0]), int(vals[8]))
        addrs = self._ipv4_addrs(now)
        out = []
        for path in sorted(glob.glob("/sys/class/net/*")):
            ifn = os.path.basename(path)
            if ifn == "lo" or ifn.startswith("veth"):
                continue
            state = _read(os.path.join(path, "operstate")) or "unknown"
            sp, spe = _read_err(os.path.join(path, "speed"))
            speed = int(sp) if sp and sp.lstrip("-").isdigit() and int(sp) > 0 else None
            speed_na = None
            if speed is None:
                if spe:
                    speed_na = f"not readable ({spe}; link down or virtual interface)"
                else:
                    speed_na = f"not reported by driver (value {sp!r})"
            rx_bps = tx_bps = None
            rate_na = None
            if ifn in counters:
                rx, tx = counters[ifn]
                prev = self._prev_net.get(ifn)
                self._prev_net[ifn] = (now, rx, tx)
                if prev and now > prev[0]:
                    dt = now - prev[0]
                    rx_bps = round(max(0, rx - prev[1]) / dt)
                    tx_bps = round(max(0, tx - prev[2]) / dt)
                else:
                    rate_na = "first sample: no delta yet"
            else:
                rate_na = "interface not in /proc/net/dev"
            # rx_bps / tx_bps are BYTES per second (field names fixed by the agx-health/1 schema)
            d = {"if": ifn, "state": state, "speed_mbps": speed, "rx_bps": rx_bps,
                 "tx_bps": tx_bps, "rate_unit": "bytes/s", "addrs": addrs.get(ifn, [])}
            if speed_na:
                d["speed_na"] = speed_na
            if rate_na:
                d["rate_na"] = rate_na
            out.append(d)
        return out
