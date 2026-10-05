"""Link to the RK3588: ping RTT / loss and a clock offset estimate (no change on the RK needed).

clock_offset_ms = RK clock - AGX clock (positive: RK is ahead).
Methods:
  http_date  - HTTP "Date" header of a port on the RK. Resolution 1 s, so the value is coarse
               (uncertainty 500 ms + rtt/2).
  clockdiff  - iputils clockdiff (ICMP timestamps), only if it runs without root.
  none       - no method.
"""
from __future__ import annotations

import collections
import http.client
import logging
import re
import shutil
import socket
import subprocess
import threading
import time
from email.utils import parsedate_to_datetime

log = logging.getLogger("dashboard.link")

NO_METHOD = "n/a (no method; RK gives no time service)"


class LinkMonitor:
    def __init__(self, cfg: dict):
        self.rk_ip = cfg["rk_ip"]
        lc = cfg["link"]
        self.interval = float(lc.get("ping_interval_s", 2))
        self.window = float(lc.get("loss_window_s", 60))
        self.clock_method = lc.get("clock_method", "auto")
        self.clock_port = lc.get("clock_http_port")
        self.clock_ports_auto = list(lc.get("clock_http_ports_auto") or [])
        self.clock_interval = float(lc.get("clock_interval_s", 30))
        self._lock = threading.Lock()
        self._pings: collections.deque = collections.deque(maxlen=int(3600 / self.interval) + 5)
        self._last_rtt: float | None = None
        self._last_ping_t: float | None = None
        self._last_ping_err: str | None = "not measured yet"
        self._clock = {"clock_offset_ms": None, "clock_method": "none",
                       "clock_uncertainty_ms": None, "clock_note": "not measured yet", "clock_t": None}
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._ping_loop, name="link-ping", daemon=True).start()
        threading.Thread(target=self._clock_loop, name="link-clock", daemon=True).start()

    def stop(self):
        self._stop.set()

    # ---- ping
    def _ping_once(self) -> tuple[float | None, str | None]:
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "1", "-n", self.rk_ip],
                               capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError) as e:
            return None, f"ping failed: {e}"
        m = re.search(r"time[=<]([\d.]+)\s*ms", r.stdout)
        if r.returncode == 0 and m:
            return float(m.group(1)), None
        return None, "no reply"

    def _ping_loop(self):
        while not self._stop.is_set():
            t0 = time.monotonic()
            rtt, err = self._ping_once()
            now = time.time()
            with self._lock:
                self._pings.append((now, rtt))
                self._last_rtt = rtt
                self._last_ping_t = now
                self._last_ping_err = err
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - t0)))

    # ---- clock
    def _http_date(self, port: int) -> tuple[float, float] | None:
        """Return (offset_ms, uncertainty_ms) or None when no HTTP answer with a Date header."""
        conn = http.client.HTTPConnection(self.rk_ip, port, timeout=1.5)
        try:
            t0 = time.time()
            conn.request("HEAD", "/")
            resp = conn.getresponse()
            t1 = time.time()
            date = resp.getheader("Date")
        except (OSError, http.client.HTTPException):
            return None
        finally:
            conn.close()
        if not date:
            return None
        try:
            rk = parsedate_to_datetime(date).timestamp()
        except (TypeError, ValueError):
            return None
        # Date is truncated to whole seconds: the true RK time is in [rk, rk+1)
        offset = (rk + 0.5) - (t0 + t1) / 2
        unc = 500.0 + (t1 - t0) * 1000 / 2
        return offset * 1000, unc

    def _clockdiff(self) -> tuple[float, float] | str:
        exe = shutil.which("clockdiff")
        if not exe:
            return "clockdiff not installed"
        try:
            r = subprocess.run([exe, "-o", self.rk_ip], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            return f"clockdiff failed: {e}"
        out = r.stdout + r.stderr
        # e.g. "host=1.2.3.4 rtt=1(0)ms/0ms delta=-3ms/-3ms Mon ..."
        m = re.search(r"rtt=(\d+)\((\d+)\)ms/(\d+)ms\s+delta=(-?\d+)ms", out)
        if r.returncode != 0 or not m:
            return f"clockdiff gave no result (rc {r.returncode}; root may be needed)"
        rtt = float(m.group(1))
        return float(m.group(4)), max(1.0, rtt / 2)

    def _measure_clock(self) -> dict:
        method = self.clock_method
        notes = []
        res = {"clock_offset_ms": None, "clock_method": "none", "clock_uncertainty_ms": None,
               "clock_note": NO_METHOD, "clock_t": time.time()}
        if method == "none":
            res["clock_note"] = "n/a (clock_method is none)"
            return res
        if method in ("auto", "http_date"):
            ports = [self.clock_port] if self.clock_port else (self.clock_ports_auto if method == "auto" else [])
            for p in ports:
                r = self._http_date(int(p))
                if r:
                    res.update(clock_offset_ms=round(r[0], 1), clock_method=f"http_date:{p}",
                               clock_uncertainty_ms=round(r[1], 1),
                               clock_note="coarse ±0.5 s (HTTP Date header has 1 s resolution)")
                    return res
            notes.append("no HTTP Date on ports " + ",".join(str(p) for p in ports) if ports
                         else "no clock_http_port set")
        if method in ("auto", "clockdiff"):
            r = self._clockdiff()
            if isinstance(r, tuple):
                res.update(clock_offset_ms=round(r[0], 1), clock_method="clockdiff",
                           clock_uncertainty_ms=round(r[1], 1), clock_note="ICMP timestamp (clockdiff)")
                return res
            notes.append(r)
        res["clock_note"] = NO_METHOD + ("; " + "; ".join(notes) if notes else "")
        return res

    def _clock_loop(self):
        while not self._stop.is_set():
            try:
                c = self._measure_clock()
            except Exception as e:  # never let the thread die
                log.exception("clock measure failed")
                c = {"clock_offset_ms": None, "clock_method": "none", "clock_uncertainty_ms": None,
                     "clock_note": f"n/a (error: {e})", "clock_t": time.time()}
            with self._lock:
                self._clock = c
            self._stop.wait(self.clock_interval)

    # ---- read
    def summary(self) -> dict:
        now = time.time()
        with self._lock:
            recent = [r for (t, r) in self._pings if now - t <= self.window]
            loss = round(100.0 * sum(1 for r in recent if r is None) / len(recent), 1) if recent else None
            out = {
                "rk_ip": self.rk_ip,
                "ping_ms": self._last_rtt,
                "ping_t": self._last_ping_t,
                "ping_error": self._last_ping_err,
                "loss_pct": loss,
                "loss_window_s": self.window,
                "loss_samples": len(recent),
            }
            out.update(self._clock)
        return out

    def ping_history(self, since_s: float = 3600) -> dict:
        now = time.time()
        with self._lock:
            pts = [(round(t, 1), r) for (t, r) in self._pings if now - t <= since_s]
        return {"t": [p[0] for p in pts], "rtt_ms": [p[1] for p in pts]}
