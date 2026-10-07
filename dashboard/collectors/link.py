"""Link to the RK3588: ping RTT / loss and a clock offset estimate (no change on the RK needed).

Target: a paired board from data/paired_boards.json (the ONE source of the board addresses on AGX02; config key
paired_boards_file; written by the pairing code). The board with the newest last_seen_t (else paired_t), and its
last_seen_addr (else its first address). The file is read again when it changes (checked before each ping); a new
target clears the ping history. No file / no board: no ping ("no paired board"). The old config key rk_ip is not
used any more. summary() keeps the old key rk_ip (= the address in use) and adds board_id / board_name / boards.

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
import ipaddress
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from email.utils import parsedate_to_datetime

log = logging.getLogger("dashboard.link")

NO_METHOD = "n/a (no method; RK gives no time service)"
NO_BOARD = "no paired board (pair a board on this page)"
DEFAULT_PAIRED_FILE = "data/paired_boards.json"


def _valid_addr(a) -> str | None:
    try:
        return str(ipaddress.ip_address(str(a).strip()))
    except ValueError:
        return None


def ping_targets(data: dict) -> list[dict]:
    """paired_boards.json data -> [{board_id, board_name, address, last_seen_t}], newest last_seen first (a board
    without last_seen_t uses paired_t). address = last_seen_addr when valid, else the first valid address."""
    out = []
    for b in data.get("boards") or []:
        if not isinstance(b, dict):
            continue
        addrs = [a for a in (_valid_addr(x) for x in (b.get("addresses") or [])) if a]
        addr = _valid_addr(b.get("last_seen_addr") or "") or (addrs[0] if addrs else None)
        if not addr:
            continue
        t = b.get("last_seen_t") if isinstance(b.get("last_seen_t"), (int, float)) else b.get("paired_t")
        out.append({"board_id": str(b.get("id") or ""), "board_name": str(b.get("name") or b.get("id") or ""),
                    "address": addr, "last_seen_t": t if isinstance(t, (int, float)) else None})
    out.sort(key=lambda x: -(x["last_seen_t"] or 0.0))
    return out


class LinkMonitor:
    def __init__(self, cfg: dict):
        p = cfg.get("paired_boards_file") or DEFAULT_PAIRED_FILE
        if not os.path.isabs(p):
            from dashboard.config import resolve_path
            p = str(resolve_path(p))
        self.paired_file = p
        self._pkey = None
        self.boards: list[dict] = []
        self.board: dict | None = None
        self.rk_ip: str | None = None           # the address in use (old key name kept)
        self.paired_error: str | None = None
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
        self._refresh_lock = threading.Lock()
        self.refresh_target()

    # ---- target
    def refresh_target(self) -> bool:
        """Read paired_boards.json again when it changed. Returns True when the target address changed."""
        with self._refresh_lock:
            return self._refresh_target()

    def _refresh_target(self) -> bool:
        try:
            st = os.stat(self.paired_file)
            key = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            key = None
        if key == self._pkey and self._pkey is not None:
            return False
        self._pkey = key
        boards = []
        err = None
        if key is not None:
            # the same reader as the Paired boards table and agx-infer (common.pairing_store): the same boards
            from common.pairing_store import read_boards_file
            d, prob = read_boards_file(self.paired_file)
            if prob:
                err = f"{os.path.basename(self.paired_file)}: {prob}".replace(self.paired_file,
                                                                             os.path.basename(self.paired_file))
                with self._lock:
                    self.paired_error = err
                log.warning("paired boards file not read (the last target stays): %s", err)
                return False
            boards = ping_targets(d)
        new = boards[0] if boards else None
        old_ip = self.rk_ip
        with self._lock:
            self.boards = boards
            self.board = new
            self.rk_ip = new["address"] if new else None
            self.paired_error = err
            changed = self.rk_ip != old_ip
            if changed or new is None:
                self._pings.clear()
                self._last_rtt = None
                self._last_ping_t = None
                self._last_ping_err = "not measured yet" if new else NO_BOARD
                self._clock = {"clock_offset_ms": None, "clock_method": "none", "clock_uncertainty_ms": None,
                               "clock_note": "not measured yet" if new else "n/a (" + NO_BOARD + ")",
                               "clock_t": None}
        if changed:
            log.info("link monitor target: %s", f"{new['board_name']} {new['address']}" if new else NO_BOARD)
        return changed

    def start(self):
        threading.Thread(target=self._ping_loop, name="link-ping", daemon=True).start()
        threading.Thread(target=self._clock_loop, name="link-clock", daemon=True).start()

    def stop(self):
        self._stop.set()

    # ---- ping
    def _ping_once(self) -> tuple[float | None, str | None]:
        ip = self.rk_ip
        if not ip:
            return None, NO_BOARD
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "1", "-n", ip],
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
            try:
                self.refresh_target()
                ip = self.rk_ip
                rtt, err = self._ping_once()
            except Exception as e:  # noqa: BLE001 - never let the thread die
                log.exception("ping failed")
                ip, rtt, err = self.rk_ip, None, f"ping failed: {e}"
            now = time.time()
            with self._lock:
                if ip and ip == self.rk_ip:      # no sample for "no board", nor for an old target
                    self._pings.append((now, rtt))
                    self._last_rtt = rtt
                    self._last_ping_t = now
                self._last_ping_err = err
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - t0)))

    # ---- clock
    def _http_date(self, port: int) -> tuple[float, float] | None:
        """Return (offset_ms, uncertainty_ms) or None when no HTTP answer with a Date header."""
        if not self.rk_ip:
            return None
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
        if not self.rk_ip:
            return NO_BOARD
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
        self.refresh_target()
        if not self.rk_ip:
            res["clock_note"] = "n/a (" + NO_BOARD + ")"
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
            b = self.board or {}
            out = {
                "rk_ip": self.rk_ip,
                "board_id": b.get("board_id"),
                "board_name": b.get("board_name"),
                "target_from": os.path.basename(self.paired_file) + " (board with the newest last_seen)",
                "boards": [dict(x) for x in self.boards],
                "paired_error": self.paired_error,
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
