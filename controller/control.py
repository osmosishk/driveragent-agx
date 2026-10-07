"""Model controller (runs in the agx-dashboard process; docs/MODEL_CONTROL_API.md). Pure Python: no TensorRT import.

Read part: the catalog (controller/catalog.py), the control state and the events. The checks run in child processes,
one at a time (controller/checks.py). Each scan writes <store>/_state/catalog.json: agx-infer reads it for the status
message to DA01.

control_mode comes from config/control.yaml. Only the owner changes that file; no API changes it.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import yaml

from controller import catalog
from controller.store import Store, read_json, write_json

log = logging.getLogger("controller")
MODES = ("bench", "vehicle")
SCAN_PERIOD_S = 10.0
EVENTS = "events.jsonl"


def read_control_mode(path) -> tuple[str, str | None]:
    """(mode, problem). No file: bench (the default). A bad file or value: vehicle (refuse changes) + the problem."""
    try:
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return "bench", f"{path} does not exist: default bench"
    except (OSError, yaml.YAMLError) as e:
        return "vehicle", f"{path} cannot be read ({e}): changes are refused"
    mode = d.get("control_mode") if isinstance(d, dict) else None
    if mode not in MODES:
        return "vehicle", f"control_mode {mode!r} in {path} is not bench or vehicle: changes are refused"
    return mode, None


class Controller:
    def __init__(self, store_root: str, repo_root: str, control_file: str, infer_client=None, check_runner=None):
        self.store = Store(store_root)
        self.repo_root = str(repo_root)
        self.control_file = str(control_file)
        self.infer = infer_client
        self.checks = check_runner
        self.jobs: dict = {}            # key -> job dict (builds, N3)
        self.change = None              # the change in progress (N3), else None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_rows: list = []
        self._last_scan_t: float | None = None

    # ---- life cycle
    def start(self):
        start = getattr(self.checks, "start", None)   # a CheckRunner starts its thread when it is made
        if callable(start):
            start()
        self._thread = threading.Thread(target=self._loop, name="model-controller", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self.checks is not None:
            self.checks.stop()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.scan()
            except Exception:  # the dashboard must keep running
                log.exception("model controller scan failed")
            self._stop.wait(SCAN_PERIOD_S)

    # ---- data
    def live_models(self) -> list[dict]:
        if self.infer is None:
            return []
        st = self.infer.current()[0]
        return list((st or {}).get("models") or [])

    def rows(self) -> list[dict]:
        return catalog.build(self.store, self.checks, self.live_models(), self.jobs)

    def scan(self) -> list[dict]:
        """Queue the checks that are needed, and write the catalog snapshot for agx-infer."""
        rows = self.rows()
        if self.checks is not None:
            for r in rows:
                if r["state"] in ("REGISTERED", "ACTIVE") and r.get("check") is None and r.get("engine"):
                    m = self.store.get(r["name"], r["version"])
                    if m is not None and not m.errors:
                        self.checks.request(m)
        mode, _ = read_control_mode(self.control_file)
        if self.store.exists():
            try:
                write_json(self.store.state / "catalog.json", catalog.snapshot(rows, mode))
            except OSError as e:
                log.warning("cannot write the catalog snapshot: %s", e)
        self._last_rows, self._last_scan_t = rows, time.time()
        return rows

    def control_mode(self) -> tuple[str, str | None]:
        return read_control_mode(self.control_file)

    def active_set(self) -> list[dict]:
        """The models that run now in agx-infer (from its status): name, version, cameras."""
        out = []
        for r in self.rows():
            if r["state"] == "ACTIVE":
                out.append({"name": r["name"], "version": r["version"], "cameras": (r.get("live") or {}).get("cameras")})
        return out

    # ---- API documents
    def catalog_doc(self) -> dict:
        mode, problem = self.control_mode()
        rows = self.rows()
        counts = {s: sum(1 for r in rows if r["state"] == s) for s in catalog.STATES}
        return {"t": time.time(), "store": str(self.store.root), "store_exists": self.store.exists(),
                "control_mode": mode, "control_problem": problem, "change_in_progress": self.change,
                "check_running": self.checks.busy() if self.checks else None,
                "check_queued": self.checks.pending() if self.checks else [],
                "counts": counts, "entries": rows}

    def control_doc(self) -> dict:
        mode, problem = self.control_mode()
        last_good = read_json(self.store.state / "last_good.json")
        return {"t": time.time(), "control_mode": mode, "control_problem": problem,
                "control_file": self.control_file, "change_in_progress": self.change,
                "active_set": self.active_set(), "last_good_set": last_good,
                "check_running": self.checks.busy() if self.checks else None}

    def events_doc(self, limit: int = 100) -> dict:
        path = self.store.state / EVENTS
        lines = []
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()[-max(1, min(int(limit), 1000)):]
        except OSError:
            pass
        import json
        ev = []
        for ln in reversed(lines):
            try:
                ev.append(json.loads(ln))
            except ValueError:
                continue
        return {"t": time.time(), "events": ev, "file": str(path)}


def from_config(cfg: dict, project_root: Path, infer_client=None) -> Controller:
    """Build the controller of the dashboard from config/dashboard.yaml."""
    import sys

    from controller.checks import CheckRunner
    store_root = os.path.expanduser(cfg.get("model_store") or "~/agx-models")
    cf = Path(cfg.get("control_config") or "config/control.yaml")
    control_file = cf if cf.is_absolute() else project_root / cf
    runner = CheckRunner(store_root, str(project_root), sys.executable,
                         timeout_s=float(cfg.get("model_check_timeout_s", 180)))
    return Controller(store_root, str(project_root), str(control_file), infer_client, runner)
