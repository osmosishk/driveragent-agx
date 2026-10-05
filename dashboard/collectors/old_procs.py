"""Running processes of the OLD DriverAgent stack (read-only, psutil). Nothing is stopped.

No systemd unit exists for the old stack: it starts by hand (~/s.sh -> start.py).
"""
from __future__ import annotations

import os
import time

OLD_ROOT = "/home/tonyho/driveragent"
# a process matches when its command line contains one of these texts
PATTERNS = ("camtest", "ui.ui", "control.py", "control-ami", "carstate.readami", "logger.encoder_265",
            "model/driverguard/run.py", "model/system1/run.py")
NOTE = "No systemd unit exists for the old DriverAgent stack; it starts by hand (~/s.sh)."


def _in_old_root(p: str) -> bool:
    # "/home/tonyho/driveragent-agx" is NOT the old root
    return p == OLD_ROOT or p.startswith(OLD_ROOT + "/")


def match(cmdline: list[str], cwd: str | None) -> str | None:
    """Return the matched pattern or None."""
    joined = " ".join(cmdline)
    for a in cmdline:
        if os.path.basename(a) == "start.py":
            full = a if os.path.isabs(a) else os.path.join(cwd or "", a)
            if _in_old_root(os.path.normpath(full)):
                return "start.py"
    for p in PATTERNS:
        if p in joined:
            return p
    return None


def find_old_processes() -> dict:
    t = time.time()
    try:
        import psutil
    except ImportError as e:
        return {"t": t, "processes": [], "error": f"psutil missing: {e}", "note": NOTE}
    me = os.getpid()
    out = []
    for pr in psutil.process_iter(["pid", "cmdline", "username", "create_time"]):
        try:
            info = pr.info
            if info["pid"] == me or not info.get("cmdline"):
                continue
            cmd = [str(x) for x in info["cmdline"]]
            cwd = None
            if any(os.path.basename(a) == "start.py" for a in cmd):
                try:
                    cwd = pr.cwd()
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    cwd = None
            m = match(cmd, cwd)
            if m is None:
                continue
            out.append({"pid": info["pid"], "user": info.get("username"), "match": m,
                        "cmdline": " ".join(cmd)[:300],
                        "started": info.get("create_time")})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    out.sort(key=lambda x: x["pid"])
    return {"t": t, "processes": out, "error": None, "note": NOTE}
