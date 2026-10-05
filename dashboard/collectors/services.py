"""systemd units (user + system), docker containers and journal tails. Read-only.

All subprocess calls use a fixed argv list (no shell). Unit names for logs come from a whitelist.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time

from dashboard.collectors.old_procs import NOTE as OLD_NOTE, find_old_processes

log = logging.getLogger("dashboard.services")

AGX_PROPS = "Id,LoadState,ActiveState,SubState,MainPID,ExecMainStartTimestamp,NRestarts,MemoryCurrent"
OLD_PROPS = "Id,LoadState,ActiveState,SubState,UnitFileState,MainPID,MemoryCurrent"
# no leading "-": a unit name must never be read as a command-line option
UNIT_RE = re.compile(r"^[A-Za-z0-9@_.\\:][A-Za-z0-9@_.\-\\:]*$")


def _run(argv: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def parse_show(text: str) -> list[dict]:
    """Parse `systemctl show A B ...` output: blocks separated by blank lines."""
    blocks, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        k, _, v = line.partition("=")
        cur[k] = v
    if cur:
        blocks.append(cur)
    return blocks


def _clean(d: dict, installed_word: str) -> dict:
    out = {"id": d.get("Id")}
    load = d.get("LoadState")
    out["load_state"] = load
    out["active_state"] = d.get("ActiveState")
    out["sub_state"] = d.get("SubState")
    if "UnitFileState" in d:
        out["unit_file_state"] = d.get("UnitFileState") or None
    pid = d.get("MainPID")
    out["main_pid"] = int(pid) if pid and pid.isdigit() and int(pid) > 0 else None
    mem = d.get("MemoryCurrent")
    out["memory_mb"] = (round(int(mem) / 1048576, 1)
                        if mem and mem.isdigit() and int(mem) < (1 << 62) else None)
    if "NRestarts" in d:
        nr = d.get("NRestarts")
        out["n_restarts"] = int(nr) if nr and nr.isdigit() else None
    if "ExecMainStartTimestamp" in d:
        ts = d.get("ExecMainStartTimestamp")
        out["started"] = ts if ts and ts != "n/a" else None
    if load == "not-found":
        out["state"] = installed_word
    else:
        out["state"] = f"{out['active_state']} ({out['sub_state']})"
    return out


class ServicesCollector:
    def __init__(self, cfg: dict):
        sc = cfg["services"]
        self.agx_units = [u for u in sc["agx_units"] if UNIT_RE.match(u)]
        self.log_units = [u for u in sc["log_units"] if UNIT_RE.match(u)]
        self.old_units = [u for u in cfg.get("old_units", []) if UNIT_RE.match(str(u))]
        self.docker_enabled = bool(cfg.get("docker", True))
        self.unit_refresh = float(sc.get("unit_refresh_s", 5))
        self.docker_refresh = float(sc.get("docker_refresh_s", 10))
        self.inspect_cache_s = float(sc.get("docker_inspect_cache_s", 30))
        self._lock = threading.Lock()
        self._units: dict = {"user": [], "system": [], "old": [], "t": None, "errors": []}
        self._docker: dict = {"available": self.docker_enabled, "containers": [], "t": None,
                              "error": None if self.docker_enabled else "docker disabled in config"}
        self._inspect: dict[str, dict] = {}
        self._inspect_t = 0.0
        self._old_procs: dict = {"t": None, "processes": [], "error": "not measured yet", "note": OLD_NOTE}
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, name="services", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        last_docker = 0.0
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self._refresh_units()
            except Exception:
                log.exception("unit refresh failed")
            try:
                op = find_old_processes()
            except Exception as e:  # noqa: BLE001
                log.exception("old process scan failed")
                op = {"t": time.time(), "processes": [], "error": f"old process scan failed: {e}",
                      "note": OLD_NOTE}
            with self._lock:
                self._old_procs = op
            if self.docker_enabled and time.monotonic() - last_docker >= self.docker_refresh:
                last_docker = time.monotonic()
                try:
                    self._refresh_docker()
                except Exception:
                    log.exception("docker refresh failed")
            self._stop.wait(max(0.5, self.unit_refresh - (time.monotonic() - t0)))

    def _show(self, user: bool, units: list[str], props: str, missing_word: str, errors: list):
        if not units:
            return []
        argv = ["systemctl"] + (["--user"] if user else []) + ["show", "-p", props, "--"] + units
        rc, out, err = _run(argv)
        blocks = parse_show(out)
        if len(blocks) != len(units):
            errors.append(f"systemctl {'--user ' if user else ''}show: rc {rc} {err.strip()[:200]}")
        res = []
        for i, u in enumerate(units):
            b = blocks[i] if i < len(blocks) else {"Id": u, "LoadState": "n/a"}
            c = _clean(b, missing_word)
            c["name"] = u
            res.append(c)
        return res

    def _refresh_units(self):
        errors: list[str] = []
        user = self._show(True, self.agx_units, AGX_PROPS, "not loaded (no user unit)", errors)
        system = self._show(False, self.agx_units, AGX_PROPS, "not installed", errors)
        old = self._show(False, self.old_units, OLD_PROPS, "not installed", errors)
        with self._lock:
            self._units = {"user": user, "system": system, "old": old, "t": time.time(), "errors": errors}

    def _refresh_docker(self):
        rc, out, err = _run(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], timeout=8)
        if rc != 0:
            with self._lock:
                self._docker = {"available": False, "containers": [], "t": time.time(),
                                "error": f"docker ps failed: {err.strip()[:200] or rc}"}
            return
        rows = []
        for line in out.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        ids = [r.get("ID") for r in rows if r.get("ID")]
        if ids and (time.monotonic() - self._inspect_t >= self.inspect_cache_s
                    or any(i not in self._inspect for i in ids)):
            self._inspect_t = time.monotonic()
            rc2, out2, _ = _run(["docker", "inspect"] + ids, timeout=10)
            info = {}
            if rc2 == 0:
                try:
                    for d in json.loads(out2):
                        hc = d.get("HostConfig") or {}
                        st = d.get("State") or {}
                        info[d.get("Id", "")] = {
                            "restart_policy": (hc.get("RestartPolicy") or {}).get("Name") or "no",
                            "restart_count": d.get("RestartCount"),
                            "started_at": st.get("StartedAt"),
                            "health": (st.get("Health") or {}).get("Status"),
                        }
                except ValueError:
                    pass
            self._inspect = info
        conts = []
        for r in rows:
            cid = r.get("ID", "")
            ins = self._inspect.get(cid, {})
            conts.append({
                "id": cid[:12], "name": r.get("Names"), "image": r.get("Image"),
                "state": r.get("State"), "status": r.get("Status"), "ports": r.get("Ports"),
                "restart_policy": ins.get("restart_policy"), "restart_count": ins.get("restart_count"),
                "started_at": ins.get("started_at"), "health": ins.get("health"),
            })
        with self._lock:
            self._docker = {"available": True, "containers": conts, "t": time.time(), "error": None}

    # ---- read
    def snapshot(self) -> dict:
        with self._lock:
            return {"units": self._units, "docker": self._docker, "old_processes": self._old_procs}

    def summary(self) -> dict:
        s = self.snapshot()
        u, d = s["units"], s["docker"]

        def short(lst):
            return {x["name"]: x["state"] for x in lst}
        old = u.get("old", [])
        return {
            "t": u.get("t"),
            "user": short(u.get("user", [])),
            "system": short(u.get("system", [])),
            "old_units": {"total": len(old),
                          "active": sum(1 for x in old if x.get("active_state") == "active"),
                          "failed": sum(1 for x in old if x.get("active_state") == "failed")},
            "docker": {"available": d.get("available"), "total": len(d.get("containers", [])),
                       "running": sum(1 for c in d.get("containers", []) if c.get("state") == "running"),
                       "error": d.get("error")},
            "old_processes": len(s["old_processes"].get("processes") or []),
        }

    def logs(self, unit: str, lines: int = 100) -> dict:
        if unit not in self.log_units:
            raise ValueError("unit not allowed")
        rc, out, err = _run(["journalctl", f"--user-unit={unit}", "-n", str(int(lines)),
                             "--no-pager", "-o", "short-iso"], timeout=8)
        ls = out.splitlines()
        if ls and ls[0].strip() == "-- No entries --":
            ls = []
        return {"unit": unit, "rc": rc, "lines": ls[-lines:],
                "error": (err.strip()[:300] or None) if rc != 0 else None, "t": time.time()}
