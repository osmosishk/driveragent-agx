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
# Legacy reference copies of the old DriverGuard code in this project (infer/models/legacy/driverguard/).
# They contain old control code: they must never run. A process matches when one of these files is
# run as a script (absolute path, or relative to the process cwd) or as a module (python -m).
LEGACY_DIR = "legacy/driverguard"
LEGACY_SCRIPTS = ("runner.py", "run_driverguard.py", "camera_reader.py")
LEGACY_MODULES = tuple("infer.models.legacy.driverguard." + n[:-3] for n in LEGACY_SCRIPTS)
_CWD_NEEDED = ("start.py",) + LEGACY_SCRIPTS


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
    for a in cmdline:
        if a in LEGACY_MODULES:
            return a
        if os.path.basename(a) in LEGACY_SCRIPTS:
            full = os.path.normpath(a if os.path.isabs(a) else os.path.join(cwd or "", a))
            if os.path.dirname(full).endswith(LEGACY_DIR):
                return LEGACY_DIR + "/" + os.path.basename(a)
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
            if any(os.path.basename(a) in _CWD_NEEDED for a in cmd):
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
