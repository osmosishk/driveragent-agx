"""Model controller (runs in the agx-dashboard process; docs/MODEL_CONTROL_API.md). Pure Python: no TensorRT import.

Read part: the catalog (controller/catalog.py), the control state and the events (the audit log).
Write part (owner Section 4.4 and rules M3-M7):
  build       ONNX -> engine on this AGX (controller/builder.py), a background child process
  activate    model, version, cameras: agx-infer adds the instance at runtime (admin socket), then the WATCHDOG waits
              for a valid result; no valid result in 20 s, or the instance fails, or agx-infer stops -> the controller
              removes it, puts the last good set back and marks the version FAILED with the reason (M6)
  deactivate  agx-infer removes the instance
  rollback    put the last good set back
- control_mode (config/control.yaml) vehicle -> every write request is refused with the reason (M7).
- Only one change at a time (a build is a change): a second request gets 409 with the reason (M4).
- Every request is written to <store>/_state/audit.jsonl with source and user (M3).
- active.json and last_good.json (controller/runtime.py) are written only after a change that gave valid results:
  agx-infer loads last_good.json after a restart.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path

import yaml

from common.machine import inside_protected
from common.machine import protected_dirs as protected_dirs_of
from controller import audit, catalog
from controller import manifest as mf
from controller.admin_client import AdminClient
from controller.builder import DEFAULT_TRTEXEC
from controller.builder import WARNING as BUILD_WARNING
from controller.builder import BuildJob
from controller.runtime import ACTIVE, LAST_GOOD, NotRunnable, read_set, runtime_cfg, write_set
from controller.store import Store, read_json, write_json

log = logging.getLogger("controller")
MODES = ("bench", "vehicle")
ACTIONS = ("build", "activate", "deactivate", "rollback")
SCAN_PERIOD_S = 10.0
WATCHDOG_S = 20.0              # owner rule M6
REMOVE_WAIT_S = 10.0
GPU_MARGIN_MB = 1024.0
FAILURES = "failures.json"


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


def mem_available_mb() -> float | None:
    """MemAvailable (Jetson: the GPU uses the same RAM)."""
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) / 1024.0
    except (OSError, ValueError):
        pass
    return None


def _hms(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


class Controller:
    def __init__(self, store_root: str, repo_root: str, control_file: str, infer_client=None, check_runner=None,
                 admin: AdminClient | None = None, trtexec: str = DEFAULT_TRTEXEC, watchdog_s: float = WATCHDOG_S,
                 protected_dirs=()):
        self.protected_dirs = protected_dirs_of(protected_dirs)   # never written (config protected_dirs)
        bad = inside_protected(store_root, self.protected_dirs)
        if bad:
            raise ValueError(f"the model store {store_root} is inside the protected folder {bad} "
                             "(config protected_dirs): choose another model_store")
        self.store = Store(store_root)
        self.repo_root = str(repo_root)
        self.control_file = str(control_file)
        self.infer = infer_client
        self.checks = check_runner
        self.admin = admin or AdminClient()
        self.trtexec = trtexec
        self.watchdog_s = float(watchdog_s)
        self.jobs: dict = {}            # key -> BuildJob (running or the last one)
        self.change: dict | None = None
        self.last_change: dict | None = None
        self.failures: dict = read_json(self.store.state / FAILURES, {}) or {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- life cycle
    def start(self):
        start = getattr(self.checks, "start", None)   # a CheckRunner starts its thread when it is made
        if callable(start):
            start()
        self._thread = threading.Thread(target=self._loop, name="model-controller", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        for j in list(self.jobs.values()):
            if j.state in ("queued", "running"):
                j.cancel()
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

    # ---- read side
    def live_models(self) -> list[dict]:
        if self.infer is None:
            return []
        st = self.infer.current()[0]
        return list((st or {}).get("models") or [])

    def _jobs(self) -> dict:
        return {k: j.job() for k, j in self.jobs.items()}

    def rows(self) -> list[dict]:
        return catalog.build(self.store, self.checks, self.live_models(), self._jobs(), self.failures)

    def row(self, key: str) -> dict | None:
        return next((r for r in self.rows() if r["key"] == key), None)

    def building(self) -> bool:
        return any(j.state in ("queued", "running") for j in self.jobs.values())

    def _build_change(self) -> bool:
        """A build change runs now (also before its job exists): no check may start on the GPU."""
        c = self.change
        return c is not None and c.get("action") == "build"

    def scan(self) -> list[dict]:
        """Queue the checks that are needed (not during a build), and write the catalog snapshot for agx-infer."""
        rows = self.rows()
        if self.checks is not None and not self.building() and not self._build_change():
            for r in rows:
                if r["state"] in ("REGISTERED", "ACTIVE") and r.get("check") is None and r.get("engine"):
                    m = self.store.get(r["name"], r["version"])
                    if m is not None and not m.errors:
                        self.checks.request(m)
        mode, _ = read_control_mode(self.control_file)
        if self.store.exists():
            try:
                write_json(self.store.state / "catalog.json", catalog.snapshot(rows, mode, self.change))
            except OSError as e:
                log.warning("cannot write the catalog snapshot: %s", e)
        return rows

    def control_mode(self) -> tuple[str, str | None]:
        return read_control_mode(self.control_file)

    def active_set(self, rows=None) -> list[dict]:
        """The models that run now in agx-infer: name, version, cameras."""
        return [{"name": r["name"], "version": r["version"], "cameras": (r.get("live") or {}).get("cameras")}
                for r in (rows if rows is not None else self.rows()) if r["state"] == "ACTIVE"]

    def catalog_doc(self) -> dict:
        mode, problem = self.control_mode()
        rows = self.rows()
        return {"t": time.time(), "store": str(self.store.root), "store_exists": self.store.exists(),
                "control_mode": mode, "control_problem": problem, "change_in_progress": self.change,
                "last_change": self.last_change, "build_warning": BUILD_WARNING,
                "check_running": self.checks.busy() if self.checks else None,
                "check_queued": self.checks.pending() if self.checks else [],
                "counts": {s: sum(1 for r in rows if r["state"] == s) for s in catalog.STATES}, "entries": rows}

    def control_doc(self) -> dict:
        mode, problem = self.control_mode()
        return {"t": time.time(), "control_mode": mode, "control_problem": problem,
                "control_file": self.control_file, "change_in_progress": self.change, "last_change": self.last_change,
                "active_set": self.active_set(), "last_good_set": read_set(self.store, LAST_GOOD),
                "check_running": self.checks.busy() if self.checks else None}

    def events_doc(self, limit: int = 100) -> dict:
        return {"t": time.time(), "events": audit.read(self.store.state, limit),
                "file": str(self.store.state / audit.FILE)}

    # ---- write side
    def request(self, action: str, name: str | None = None, version: str | None = None, params: dict | None = None,
                source: str = "command-line", user: str = "?") -> tuple[int, dict]:
        """Validate and start one change. (HTTP status, document). 202 = started; 4xx = refused with a reason."""
        params = dict(params or {})
        key = mf.key(name, version) if name is not None else None
        extra = {k: params[k] for k in ("cameras",) if k in params}

        def refuse(code: int, reason: str):
            audit.append(self.store.state, source, user, action, name, version, "refused", reason, **extra)
            return code, {"ok": False, "action": action, "model": key, "reason": reason}

        if action not in ACTIONS:
            return refuse(400, f"unknown action {action!r} (actions: {', '.join(ACTIONS)})")
        mode, problem = self.control_mode()
        if mode != "bench":
            return refuse(409, f"control mode is {mode}: build, activate, deactivate and rollback are refused"
                               + (f" ({problem})" if problem else "") + ". Only the owner changes config/control.yaml.")
        with self._lock:
            c = self.change
            if c is not None:
                return refuse(409, f"another change runs now: {c['action']} {c.get('model') or ''} since "
                                   f"{_hms(c['t'])} ({c['source']}, {c['user']}). Only one change at a time.")
            plan, reason, code = self._validate(action, name, version, params)
            if reason:
                return refuse(code, reason)
            change = {"id": uuid.uuid4().hex[:8], "action": action, "model": key, "t": time.time(),
                      "source": source, "user": audit.clean(user), "params": extra}
            self.change = change
        audit.append(self.store.state, source, user, action, name, version, "started", None, change_id=change["id"],
                     **extra)
        try:   # agx-infer shows the change in its status to DA01 at once (not only at the next scan)
            self.scan()
        except Exception:
            log.exception("scan at change start failed")
        threading.Thread(target=self._run, args=(change, plan), name=f"change-{action}", daemon=True).start()
        doc = {"ok": True, "accepted": True, "change": change}
        if action == "build":
            doc["warning"] = BUILD_WARNING
        return 202, doc

    def _validate(self, action, name, version, params) -> tuple[dict, str | None, int]:
        """(plan, refusal reason, HTTP code). Called with the lock held."""
        if action == "rollback":
            target = read_set(self.store, LAST_GOOD)
            if not target or not target["set"]:
                return {}, "no last good set is stored yet", 409
            now = {(a["name"], a["version"], tuple(a["cameras"] or [])) for a in self.active_set()}
            want = {(a["name"], a["version"], tuple(a["cameras"])) for a in target["set"]}
            if now == want:
                return {}, "the active set is already the last good set", 409
            return {"target": target}, None, 0
        m = self.store.get(name or "", version or "")
        if m is None:
            return {}, f"no model {name}@{version} in the store", 404
        r = self.row(m.key)
        st = r["state"] if r else "?"
        if action == "build":
            if st == "BUILDING" or self.building():
                return {}, "a build runs now: only one build at a time", 409
            onnx = m.file("onnx")
            if st != "NEEDS BUILD" and not (st == "FAILED" and onnx and os.path.isfile(onnx["path"])
                                             and self.store.engine(m) is None):
                return {}, f"{m.key} is {st}: only a model in state NEEDS BUILD can be built", 409
            return {"m": m}, None, 0
        if action == "deactivate":
            if st != "ACTIVE":
                return {}, f"{m.key} is not active (state {st})", 409
            return {"m": m}, None, 0
        # activate
        if st == "ACTIVE":
            return {}, (f"{m.key} is already active on cameras {(r.get('live') or {}).get('cameras')}: "
                        "deactivate it first to change its cameras"), 409
        if st in ("NO ADAPTER", "NEEDS BUILD", "BUILDING", "REGISTERED"):
            return {}, f"{m.key} is {st}: {r.get('reason') or 'it cannot be activated now'}", 409
        chk = self.checks.result(m.key) if self.checks else None
        if not chk:
            return {}, f"{m.key}: the checks are not done yet (owner rule M5)", 409
        if not chk.get("ok"):
            return {}, f"{m.key}: the checks failed: {chk.get('reason')} (owner rule M5)", 409
        if st == "FAILED" and m.key not in self.failures:   # a watchdog failure can be tried again; others cannot
            return {}, f"{m.key} is FAILED: {r.get('reason')}", 409
        cams = params.get("cameras")
        if cams is not None and (not isinstance(cams, list) or not all(isinstance(c, int) for c in cams)):
            return {}, "cameras must be a list of camera numbers", 400
        try:
            cfg = runtime_cfg(self.store, m, cams)
        except NotRunnable as e:
            return {}, str(e), 409
        need, free = chk.get("gpu_need_mb"), mem_available_mb()
        if need is not None and free is not None and float(need) + GPU_MARGIN_MB > free:
            return {}, (f"not enough free memory for {m.key}: it needs {float(need):.0f} MB + {GPU_MARGIN_MB:.0f} MB "
                        f"margin, {free:.0f} MB are free"), 409
        return {"m": m, "cfg": cfg}, None, 0

    def _run(self, change: dict, plan: dict):
        action, key = change["action"], change["model"]
        name, _, version = (key or "").partition("@")
        try:
            result, reason = getattr(self, "_do_" + action)(change, plan)
        except Exception as e:  # every failure is a reason in plain words
            log.exception("change %s failed", change)
            result, reason = "failed", f"internal error: {e}"
        audit.append(self.store.state, change["source"], change["user"], action, name or None, version or None,
                     result, reason, change_id=change["id"], **change.get("params", {}))
        with self._lock:
            self.last_change = dict(change, result=result, reason=reason, ended=time.time())
            self.change = None
        try:
            self.scan()
        except Exception:
            log.exception("scan after change failed")

    # ---- agx-infer instances
    def _instances(self) -> tuple[dict | None, str | None]:
        lst, err = self.admin.instances()
        if lst is None:
            return None, err
        return {str(i.get("instance") or i.get("name")): i for i in lst}, None

    def _wait_valid(self, key: str, deadline: float) -> str | None:
        """None when the instance gave a valid result before the deadline, else the reason."""
        while time.monotonic() < deadline:
            inst, err = self._instances()
            if inst is None:
                return f"agx-infer does not answer ({err})"
            i = inst.get(key)
            if i is None:
                return "the instance is gone from agx-infer"
            if i.get("state") == "FAILED":
                return f"failed in agx-infer: {i.get('error') or 'no error text'}"
            if i.get("state") == "RUNNING" and int(i.get("results_total") or 0) > 0:
                return None
            time.sleep(0.5)
        return f"no valid result in {self.watchdog_s:.0f} s"

    def _wait_gone(self, key: str) -> bool:
        deadline = time.monotonic() + REMOVE_WAIT_S
        while time.monotonic() < deadline:
            inst, _ = self._instances()
            if inst is not None and key not in inst:
                return True
            time.sleep(0.3)
        return False

    def _running_set(self) -> list[dict]:
        inst, _ = self._instances()
        out = []
        for k, i in (inst or {}).items():
            if i.get("state") in ("RUNNING", "LOADING", "LOADED") and i.get("version"):
                out.append({"name": i["name"], "version": str(i["version"]), "cameras": list(i.get("cameras") or [])})
        return out

    def _save_sets(self, change: dict, reason: str, good: bool = True):
        cur = self._running_set()
        write_set(self.store, ACTIVE, cur, change["source"], change["user"], reason)
        if good:
            write_set(self.store, LAST_GOOD, cur, change["source"], change["user"], reason)

    def _set_failure(self, key: str, reason: str | None):
        if reason is None:
            self.failures.pop(key, None)
        else:
            self.failures[key] = {"reason": reason, "t": time.time()}
        write_json(self.store.state / FAILURES, self.failures)

    def _restore(self, target: dict) -> list[str]:
        """Make the running instances equal to the target set. [] = done, else the problems."""
        problems = []
        want = {mf.key(i["name"], i["version"]): sorted(i.get("cameras") or []) for i in target["set"]}
        inst, err = self._instances()
        if inst is None:
            return [f"agx-infer does not answer ({err})"]
        for k, i in inst.items():
            if i.get("version") and (k not in want or sorted(i.get("cameras") or []) != want[k]):
                ok, msg = self.admin.remove(k)
                if not ok or not self._wait_gone(k):
                    problems.append(f"remove {k}: {msg or 'still there'}")
        for k, cams in want.items():
            inst, _ = self._instances()
            if inst is not None and k in inst:
                continue
            name, _, version = k.partition("@")
            m = self.store.get(name, version)
            if m is None:
                problems.append(f"{k}: not in the store")
                continue
            try:
                cfg = runtime_cfg(self.store, m, cams)
            except NotRunnable as e:
                problems.append(str(e))
                continue
            ok, msg = self.admin.add(cfg)
            if not ok:
                problems.append(f"add {k}: {msg}")
                continue
            why = self._wait_valid(k, time.monotonic() + self.watchdog_s)
            if why:
                problems.append(f"{k}: {why}")
        return problems

    def _do_activate(self, change: dict, plan: dict) -> tuple[str, str | None]:
        m, cfg = plan["m"], plan["cfg"]
        deadline = time.monotonic() + self.watchdog_s
        ok, msg = self.admin.add(cfg)
        why = None if ok else f"agx-infer refused the instance: {msg}"
        if why is None:
            why = self._wait_valid(m.key, deadline)
        if why is None:
            self._set_failure(m.key, None)
            self._save_sets(change, f"activate {m.key} on cameras {cfg['cameras']}")
            return "ok", f"{m.key} gives valid results on cameras {cfg['cameras']}"
        # owner rule M6: stop it, put the last good set back, FAILED with the reason
        self.admin.remove(m.key)
        self._wait_gone(m.key)
        target = read_set(self.store, LAST_GOOD)
        problems = self._restore(target) if target else ["no last good set is stored"]
        self._set_failure(m.key, why)
        back = "the last good set runs again" if not problems else "the last good set is NOT fully back: " + "; ".join(problems)
        return "failed", f"{why}: the controller stopped {m.key}; {back}"

    def _do_deactivate(self, change: dict, plan: dict) -> tuple[str, str | None]:
        m = plan["m"]
        ok, msg = self.admin.remove(m.key)
        if not ok:
            return "failed", f"agx-infer did not remove {m.key}: {msg}"
        if not self._wait_gone(m.key):
            return "failed", f"{m.key} is still in agx-infer after {REMOVE_WAIT_S:.0f} s"
        self._save_sets(change, f"deactivate {m.key}")
        return "ok", f"{m.key} stopped"

    def _do_rollback(self, change: dict, plan: dict) -> tuple[str, str | None]:
        problems = self._restore(plan["target"])
        if problems:
            self._save_sets(change, "rollback (not complete)", good=False)
            return "failed", "the last good set is not fully back: " + "; ".join(problems)
        self._save_sets(change, "rollback to the last good set", good=False)
        return "ok", "the last good set runs again"

    def _do_build(self, change: dict, plan: dict) -> tuple[str, str | None]:
        m = plan["m"]
        job = BuildJob(m, self.trtexec, protected_dirs=self.protected_dirs)
        self.jobs[m.key] = job
        job.start()
        job._thread.join()
        if job.state != "done":
            return "failed", f"build failed: {job.error}"
        try:  # the old check result does not know the new engine
            os.unlink(self.store.state / "checks" / f"{m.key}.json")
        except OSError:
            pass
        if self.checks is not None:
            self.checks.request(self.store.get(m.name, m.version))
        return "ok", f"engine built in {job.job()['elapsed_s']:.0f} s: {os.path.basename(job.out)} (checks queued)"


def from_config(cfg: dict, project_root: Path, infer_client=None) -> Controller:
    """Build the controller of the dashboard from config/dashboard.yaml."""
    import sys

    from controller.checks import CheckRunner
    store_root = os.path.expanduser(cfg.get("model_store") or "~/agx-models")
    cf = Path(cfg.get("control_config") or "config/control.yaml")
    control_file = cf if cf.is_absolute() else project_root / cf
    # the test frame of the configured store (<model_store>/_testframes/front_1280x720.jpg, tools/model_check.py)
    runner = CheckRunner(store_root, str(project_root), sys.executable,
                         timeout_s=float(cfg.get("model_check_timeout_s", 180)),
                         frame=os.path.join(store_root, "_testframes", "front_1280x720.jpg"))
    from dashboard.config import infer_admin_endpoint
    # the config value, else tcp://127.0.0.1:<ports.admin of infer_config> (5563 when not given)
    admin = AdminClient(infer_admin_endpoint(cfg))
    return Controller(store_root, str(project_root), str(control_file), infer_client, runner, admin,
                      cfg.get("trtexec") or DEFAULT_TRTEXEC, protected_dirs=cfg.get("protected_dirs") or [])
