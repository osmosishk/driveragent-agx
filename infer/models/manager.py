"""ModelManager: loads the model instances, runs their workers, reports their status.

Model instances: an entry is keyed "<name>@<version>" (controller.manifest.key) when its config has a version
(model store, controller/runtime.py runtime_cfg), else by its name (a legacy config/models.yaml entry). Instances
can be added and removed at runtime with add_model() / remove_model() (admin socket "add" / "remove"); two versions
of one model name can run at the same time. models and order are changed only under ModelManager._lock.

Model states (dashboard contract):
  OFF      enabled: false in the config (the "reason" is kept), or stopped with stop_model()
  LOADED   engine loaded and warmed up, workers not running
  RUNNING  workers running
  FAILED   load or worker error ("error" = the real error text, "error_t" = unix time)
  LOADING  (transient) engine load or engine rebuild with trtexec in progress

Isolation: an exception in the load or in a worker of one model sets only that model FAILED.
The other models continue.

Automatic restart: a model that is FAILED because of worker errors is started again with
start_model() after a backoff: restart_backoff_s (30 s), then 60 s, 120 s ... up to
restart_backoff_max_s (600 s). The counter "auto_restarts" is in the status. A model that ran for
restart_backoff_max_s or more before it failed starts again with the first backoff. A load error
(no engine) is NOT restarted. A model stopped with stop_model() or ModelManager.stop() is NOT
restarted.

Engine rule: the configured engine is never written. When it does not load and an ONNX file exists,
a new engine is built with trtexec into engines_dir (<name>_fp16.engine) and that engine is loaded.
engines_dir must not be inside a protected folder (config/infer.yaml protected_dirs, for example the old engines).
"""
from __future__ import annotations

import gc
import logging
import os
import subprocess
import threading
import time
import traceback

from common.machine import inside_protected
from infer.models.adapters import get_adapter_class
from infer.runner import FrameScheduler, ModelMetrics, ModelWorker

log = logging.getLogger("agx.infer.manager")

PROJECT_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_ENGINES_DIR = os.path.join(PROJECT_DIR, "engines")
TRTEXEC = "/usr/src/tensorrt/bin/trtexec"
GPU_MEM_NOTE = "estimate: engine file + activation + I/O"

OFF, LOADED, RUNNING, FAILED, LOADING = "OFF", "LOADED", "RUNNING", "FAILED", "LOADING"


def _trt_version() -> str | None:
    try:
        import tensorrt as trt
        return trt.__version__
    except Exception:
        return None


def onnx_input_names(onnx_path: str) -> list[tuple[str, list]]:
    """[(name, dims)] of the graph inputs (initializers excluded). dims: int or str (dynamic)."""
    import onnx
    m = onnx.load(onnx_path, load_external_data=False)
    inits = {i.name for i in m.graph.initializer}
    out = []
    for i in m.graph.input:
        if i.name in inits:
            continue
        dims = [d.dim_value if d.dim_value > 0 else (d.dim_param or "?") for d in i.type.tensor_type.shape.dim]
        out.append((i.name, dims))
    return out


def trtexec_shapes(onnx_path: str, known: dict) -> str | None:
    """--shapes value from the ONNX input names and the engine shapes of the adapter
    (docs/MODELS.md). None when every input is static and not in `known`."""
    parts = []
    for name, dims in onnx_input_names(onnx_path):
        if name in known:
            shape = known[name]
        elif all(isinstance(d, int) for d in dims):
            continue
        else:
            raise ValueError(f"ONNX input {name!r} has dynamic dims {dims} and no known engine shape")
        parts.append(f"{name}:{'x'.join(str(int(d)) for d in shape)}")
    return ",".join(parts) if parts else None


class ModelEntry:
    """Runtime state of one model. Fields are changed under self.lock."""

    def __init__(self, cfg: dict, manager: "ModelManager"):
        self.cfg = dict(cfg)
        self.manager = manager
        self.name = str(cfg.get("name"))
        self.version = str(cfg.get("version") or "")      # "" for a legacy config/models.yaml entry
        self.key = f"{self.name}@{self.version}" if self.version else self.name
        self.group = cfg.get("group")
        self.enabled = bool(cfg.get("enabled", False))
        self.engine_path = cfg.get("engine")
        self.onnx_path = cfg.get("onnx")
        self.adapter_name = cfg.get("adapter")
        self.cameras = [int(c) for c in (cfg.get("cameras") or [])]
        self.workers_n = max(1, int(cfg.get("workers", 1) or 1))
        self.max_fps = cfg.get("max_fps_per_camera")
        self.reason = cfg.get("reason")
        self.state = OFF if not self.enabled else LOADING
        self.error: str | None = None
        self.error_t: float | None = None
        self.engine = None
        self.engine_source: str | None = None    # "config" | "rebuilt"
        self.adapter = None
        self.slots: list = []
        self.workers: list[ModelWorker] = []
        self.stop_event = threading.Event()
        self.scheduler = FrameScheduler(self.cameras, self.max_fps)
        self.metrics = ModelMetrics()
        self.lock = threading.RLock()
        self.build_proc: subprocess.Popen | None = None
        self.build_thread: threading.Thread | None = None
        self.cancel_build = threading.Event()
        self.load_thread: threading.Thread | None = None   # background load of an instance added at runtime
        self.removed = False                               # remove_model() runs or ran: never start again
        # automatic restart after worker errors (see the module doc)
        self.auto_restarts = 0
        self.restart_due: float | None = None      # time.monotonic() of the next attempt
        self.restart_backoff: float = float(manager.restart_backoff_s)

    # called from worker threads
    def report_error(self, text: str, fatal: bool = False) -> None:
        n = self.metrics.add_error(text)
        if fatal or n >= self.manager.fail_after_errors:
            self.fail(f"worker: {text}" + ("" if fatal else f" ({n} errors in sequence)"),
                      restart=True)

    def fail(self, text: str, restart: bool = False) -> None:
        """-> FAILED. restart=True (worker errors only): schedule an automatic restart."""
        delay = None
        with self.lock:
            if restart and self.state != RUNNING:
                # a second worker of the same model, or the model was stopped meanwhile
                if self.state == FAILED:
                    return
                restart = False
            self.state = FAILED
            self.error = text
            self.error_t = time.time()
            self.stop_event.set()
            if restart and self.enabled and self.manager.auto_restart_allowed():
                mgr = self.manager
                ran = self.metrics.running_since
                if ran is not None and time.monotonic() - ran >= mgr.restart_backoff_max_s:
                    self.restart_backoff = float(mgr.restart_backoff_s)   # it ran well: reset
                delay = self.restart_backoff
                self.restart_due = time.monotonic() + delay
                self.restart_backoff = min(float(mgr.restart_backoff_max_s), delay * 2.0)
            else:
                self.restart_due = None
        log.error("model %s FAILED: %s", self.key, text)
        if delay is not None:
            log.warning("model %s: automatic restart in %.1f s (restarts so far: %d)",
                        self.key, delay, self.auto_restarts)
            self.manager._ensure_supervisor()


class ModelManager:
    def __init__(self, models_cfg, store, on_result, engines_dir: str = DEFAULT_ENGINES_DIR,
                 trtexec: str = TRTEXEC, build_timeout_s: float = 3600.0, fail_after_errors: int = 3,
                 warmup: bool = True, restart_backoff_s: float = 30.0,
                 restart_backoff_max_s: float = 600.0, protected_dirs=()):
        if isinstance(models_cfg, dict):
            models_cfg = models_cfg.get("models") or []
        self.store = store
        self.on_result = on_result
        self.engines_dir = os.path.realpath(engines_dir)
        root = inside_protected(self.engines_dir, protected_dirs)   # config/infer.yaml protected_dirs
        if root:
            raise ValueError(f"engines_dir {engines_dir} is under the read-only folder {root}")
        self.trtexec = trtexec
        self.build_timeout_s = float(build_timeout_s)
        self.fail_after_errors = max(1, int(fail_after_errors))
        self.warmup = warmup
        self.restart_backoff_s = max(0.01, float(restart_backoff_s))
        self.restart_backoff_max_s = max(self.restart_backoff_s, float(restart_backoff_max_s))
        self._sup_stop = threading.Event()        # set by stop(): no automatic restart
        self._sup_thread: threading.Thread | None = None
        self._sup_lock = threading.Lock()
        self._lock = threading.Lock()              # every change of models / order
        self._stopping = threading.Event()        # set by stop(): add_model() is refused
        self.models: dict[str, ModelEntry] = {}   # key -> entry
        self.order: list[str] = []                # keys
        for i, c in enumerate(models_cfg):
            e = ModelEntry(c or {}, self)
            if not c or not c.get("name"):
                e.name = e.key = f"model{i}"
                e.fail("config: model has no name")
            elif e.key in self.models:
                if e.version:
                    e.key = f"{e.key}#{i}"
                else:
                    e.name = e.key = f"{e.name}#{i}"
                e.fail("config: duplicate model instance" if e.version else "config: duplicate model name")
            self.models[e.key] = e
            self.order.append(e.key)
        self._started = False

    def _entries(self) -> list[ModelEntry]:
        """The entries in order (a copy: safe while instances are added or removed)."""
        with self._lock:
            return [self.models[k] for k in self.order if k in self.models]

    def _resolve(self, ref: str) -> tuple[ModelEntry | None, str | None]:
        """Entry of an instance key, or of a model name with exactly one instance. -> (entry, error)."""
        with self._lock:
            e = self.models.get(ref)
            if e is not None:
                return e, None
            hits = [m for m in self.models.values() if m.name == ref]
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"no model {ref!r}"
        return None, (f"model name {ref!r} has {len(hits)} instances ({', '.join(m.key for m in hits)}): "
                      f"give the instance key <name>@<version>")

    # -- public API ---------------------------------------------------------------------------------
    def start(self, should_stop=None) -> None:
        """Load every enabled model and start its workers. A model that needs an engine rebuild is
        built in a background thread (state LOADING); the other models start at once.
        should_stop: optional function; when it returns True (for example SIGTERM during the start),
        the models that are not loaded yet are not loaded and no more workers start."""
        self._started = True
        self._stopping.clear()
        self._sup_stop.clear()
        for e in self._entries():
            if not e.enabled or e.state == FAILED or e.removed or e.load_thread is not None:
                continue
            if should_stop is not None and should_stop():
                log.info("stop requested: model %s and the next models are not loaded", e.key)
                break
            self._load_and_run(e, should_stop)

    def stop(self) -> None:
        """Stop all workers and engine builds. Engines stay loaded. No automatic restart after it.
        add_model() is refused after it."""
        self._stopping.set()
        self._sup_stop.set()
        entries = self._entries()
        for e in entries:
            with e.lock:
                e.restart_due = None
        t = self._sup_thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=10)
        for e in entries:   # a background load sees _stopping and starts no workers
            self._join_load(e, 30.0)
        for e in entries:
            self._cancel_build(e)
            self._stop_workers(e)
            with e.lock:
                if e.state in (RUNNING, LOADING):
                    e.state = LOADED if e.engine is not None else OFF
        for e in entries:
            t = e.build_thread
            if t is not None:
                t.join(timeout=10)

    def close(self) -> None:
        """stop() and release the engines (GPU memory)."""
        self.stop()
        for e in self._entries():
            self._free(e)
        try:
            import torch
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        except Exception:
            pass

    # -- instances added / removed at runtime ---------------------------------------------------------
    def add_model(self, cfg: dict) -> tuple[bool, str]:
        """Add one instance (controller.runtime.runtime_cfg() format) and load + start it in a background
        thread (LOADING -> RUNNING, or FAILED with the error). Returns at once: (True, key) or (False, error)."""
        if not isinstance(cfg, dict) or not cfg.get("name"):
            return False, "the model config needs a name"
        version = str(cfg.get("version") or "")
        if not version:
            return False, f"the model config of {cfg.get('name')} needs a version (instance = <name>@<version>)"
        if not cfg.get("adapter") or cfg.get("adapter") == "none" or not (cfg.get("engine") or cfg.get("onnx")):
            return False, f"{cfg.get('name')}@{version}: no adapter or no engine: it cannot run"
        if not cfg.get("cameras"):
            return False, f"{cfg.get('name')}@{version}: no camera"
        cfg = dict(cfg, enabled=True)
        with self._lock:
            if self._stopping.is_set():
                return False, "the model manager is stopping"
            e = ModelEntry(cfg, self)
            if e.key in self.models:
                return False, f"model instance {e.key} exists already"
            e.state = LOADING
            t = threading.Thread(target=self._load_added, args=(e,), name=f"load-{e.key}", daemon=True)
            e.load_thread = t
            self.models[e.key] = e
            self.order.append(e.key)
        t.start()
        log.info("model %s added (cams %s, engine %s): loading", e.key, e.cameras, e.engine_path)
        return True, e.key

    def _load_added(self, e: ModelEntry) -> None:
        self._load_and_run(e, should_stop=lambda: self._stopping.is_set() or e.removed)

    def remove_model(self, key: str) -> tuple[bool, str]:
        """Stop the workers of one instance, cancel its build, free its slots / adapter / engine and delete it."""
        with self._lock:
            e = self.models.get(key)
            if e is None:
                return False, f"no model instance {key}"
            if e.removed:
                return False, f"model instance {key} is being removed"
            e.removed = True
        with e.lock:   # first: no automatic restart
            e.enabled = False
            e.restart_due = None
        self._cancel_build(e)
        self._join_load(e, 60.0)
        self._stop_workers(e)
        with e.lock:
            e.state = OFF
            e.reason = "removed"
        self._free(e)
        with self._lock:
            self.models.pop(key, None)
            if key in self.order:
                self.order.remove(key)
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
        log.info("model %s removed", key)
        return True, f"model instance {key} removed"

    def _join_load(self, e: ModelEntry, timeout: float) -> None:
        t = e.load_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=timeout)
            if t.is_alive():
                log.error("model %s: engine load did not end in %.0f s", e.key, timeout)

    def _free(self, e: ModelEntry) -> None:
        """Release the slots, the adapter and the engine of one entry (the workers are stopped)."""
        with e.lock:
            eng = e.engine
            e.slots, e.adapter, e.engine = [], None, None
        if eng is not None and not any(w.is_alive() for w in e.workers):
            try:
                eng.slots.clear()   # slot <-> engine references: free the GPU buffers now, not at a later GC
            except AttributeError:
                pass
            del eng
            gc.collect()

    def stop_model(self, name: str) -> dict:
        """-> OFF. Workers stop, the engine stays loaded. name: an instance key, or a model name with one
        instance."""
        e, err = self._resolve(name)
        if e is None:
            return {"ok": False, "error": err}
        with e.lock:   # first: no automatic restart of a model the operator stops
            e.enabled = False
            e.restart_due = None
        self._cancel_build(e)
        self._stop_workers(e)
        with e.lock:
            e.state = OFF
            e.enabled = False
            e.reason = "stopped by operator (engine stays loaded)" if e.engine is not None \
                else "stopped by operator"
        log.info("model %s stopped", e.key)
        return {"ok": True, "state": OFF}

    def start_model(self, name: str) -> dict:
        """-> RUNNING (or LOADING while an engine rebuild runs). Loads the engine when needed. name: an
        instance key, or a model name with one instance."""
        e, err = self._resolve(name)
        if e is None:
            return {"ok": False, "error": err}
        with e.lock:
            if e.removed:
                return {"ok": False, "state": e.state, "error": "the instance is being removed"}
            if e.state == RUNNING:
                return {"ok": True, "state": RUNNING}
            if e.state == LOADING and e.build_thread is not None and e.build_thread.is_alive():
                return {"ok": False, "state": LOADING, "error": "engine build is running"}
            if e.state == LOADING and e.load_thread is not None and e.load_thread.is_alive():
                return {"ok": True, "state": LOADING, "error": None}
            if not e.adapter_name or e.adapter_name == "none" or (not e.engine_path and not e.onnx_path):
                return {"ok": False, "state": e.state,
                        "error": "model has no adapter or no engine: it cannot run"}
            e.enabled = True
            e.restart_due = None   # a manual start replaces a pending automatic restart
        self._load_and_run(e)
        with e.lock:
            return {"ok": e.state in (RUNNING, LOADING), "state": e.state, "error": e.error}

    @property
    def results_total(self) -> int:
        return sum(e.metrics.results_total for e in self._entries())

    @property
    def last_result_t(self) -> float | None:
        ts = [e.metrics.last_result_t for e in self._entries() if e.metrics.last_result_t]
        return max(ts) if ts else None

    def status(self) -> list[dict]:
        """Status of every instance, in order. Safe while instances are added or removed."""
        return [self._status_one(e) for e in self._entries()]

    # -- automatic restart ----------------------------------------------------------------------------
    def auto_restart_allowed(self) -> bool:
        return not self._sup_stop.is_set()

    def _ensure_supervisor(self) -> None:
        with self._sup_lock:
            if self._sup_stop.is_set():
                return
            if self._sup_thread is not None and self._sup_thread.is_alive():
                return
            self._sup_thread = threading.Thread(target=self._supervise, name="model-supervisor",
                                                daemon=True)
            self._sup_thread.start()

    def _supervise(self) -> None:
        """Start FAILED models again when their restart time is reached."""
        tick = min(1.0, self.restart_backoff_s / 4.0)
        while not self._sup_stop.wait(tick):
            now = time.monotonic()
            for e in self._entries():
                with e.lock:
                    due = e.restart_due
                    if due is None or now < due:
                        continue
                    e.restart_due = None
                    if e.state != FAILED or not e.enabled or e.removed or self._sup_stop.is_set():
                        continue
                    if e.engine is None:   # only worker failures (engine loaded) are restarted
                        continue
                    e.auto_restarts += 1
                    n = e.auto_restarts
                    log.warning("model %s: automatic restart %d (after FAILED: %s)", e.key, n, e.error)
                    try:
                        # under e.lock: stop_model() cannot run between the check and the start
                        res = self.start_model(e.key)
                    except Exception as ex:  # noqa: BLE001
                        res = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
                    if not res.get("ok"):
                        delay = e.restart_backoff
                        e.restart_due = time.monotonic() + delay
                        e.restart_backoff = min(self.restart_backoff_max_s, delay * 2.0)
                        log.warning("model %s: automatic restart %d failed (%s); next try in %.1f s",
                                    e.key, n, res.get("error"), delay)
                    else:
                        log.warning("model %s: automatic restart %d -> %s", e.key, n, res.get("state"))

    # -- loading ------------------------------------------------------------------------------------
    def _load_and_run(self, e: ModelEntry, should_stop=None) -> None:
        with e.lock:
            if e.engine is not None:
                self._start_workers(e)
                return
            e.state, e.error, e.error_t = LOADING, None, None
        try:
            cls = get_adapter_class(e.adapter_name)
            eng, errors = self._try_engines(e)
            if eng is None:
                if e.onnx_path and os.path.isfile(e.onnx_path):
                    e.cancel_build.clear()
                    with e.lock:
                        e.reason = f"engine rebuild from ONNX with trtexec; load errors: {'; '.join(errors)}"
                    t = threading.Thread(target=self._build_then_run, args=(e, cls, errors),
                                         name=f"build-{e.key}", daemon=True)
                    e.build_thread = t
                    t.start()
                    return
                onnx_txt = f"ONNX file not found: {e.onnx_path}" if e.onnx_path else "no ONNX file configured"
                raise RuntimeError(f"{'; '.join(errors)}; {onnx_txt}: no rebuild possible")
            self._finish_load(e, cls, eng)
            if e.removed:   # removed while the engine loaded: free it again
                self._free(e)
                return
            if should_stop is not None and should_stop():
                log.info("stop requested: model %s loaded, workers not started", e.key)
                return
            self._start_workers(e)
        except Exception as ex:
            log.debug("%s", traceback.format_exc())
            e.fail(f"load: {type(ex).__name__}: {ex}")

    def _rebuilt_path(self, e: ModelEntry) -> str:
        base = f"{e.name}_{e.version}" if e.version else e.name
        p = os.path.join(self.engines_dir, f"{base}_fp16.engine")
        if e.engine_path and os.path.realpath(e.engine_path) == os.path.realpath(p):
            p = os.path.join(self.engines_dir, f"{base}_fp16_rebuilt.engine")
        return p

    def _try_engines(self, e: ModelEntry):
        """Configured engine first, then an engine rebuilt earlier. -> (TrtEngine | None, errors)."""
        from infer.models.trt_engine import TrtEngine
        errors = []
        if e.engine_path:
            try:
                eng = TrtEngine(e.engine_path)
                e.engine_source = "config"
                return eng, errors
            except Exception as ex:
                errors.append(f"engine {e.engine_path}: {type(ex).__name__}: {ex}")
        else:
            errors.append("no engine configured")
        rebuilt = self._rebuilt_path(e)
        if os.path.isfile(rebuilt):
            try:
                eng = TrtEngine(rebuilt)
                e.engine_source = "rebuilt"
                return eng, errors
            except Exception as ex:
                errors.append(f"rebuilt engine {rebuilt}: {type(ex).__name__}: {ex}")
        return None, errors

    def _finish_load(self, e: ModelEntry, cls, eng) -> None:
        adapter = cls(e.cfg, eng)
        slots = [eng.new_slot() for _ in range(e.workers_n)]
        if self.warmup:
            for s in slots:
                s.infer(adapter.dummy_inputs())
        with e.lock:
            e.engine, e.adapter, e.slots = eng, adapter, slots
            e.state = LOADED
            if e.enabled and e.engine_source == "rebuilt":
                e.reason = f"running a rebuilt engine: {eng.path}"
        log.info("model %s loaded: %s (%s)", e.key, eng.version_tag, e.engine_source)

    def build_command(self, e: ModelEntry, out_path: str, cls) -> list[str]:
        cmd = [self.trtexec, f"--onnx={e.onnx_path}", f"--saveEngine={out_path}", "--fp16"]
        shapes = e.cfg.get("build_shapes") or trtexec_shapes(e.onnx_path, cls.ENGINE_INPUT_SHAPES)
        if shapes:
            cmd.append(f"--shapes={shapes}")
        return cmd

    def _build_then_run(self, e: ModelEntry, cls, errors: list) -> None:
        try:
            os.makedirs(self.engines_dir, exist_ok=True)
            final = self._rebuilt_path(e)
            tmp = final + ".partial"
            for p in (final, tmp):  # safety: never write outside engines_dir or onto the old engine
                if os.path.dirname(os.path.realpath(p)) != self.engines_dir:
                    raise RuntimeError(f"refused: {p} is not in {self.engines_dir}")
                if e.engine_path and os.path.realpath(p) == os.path.realpath(e.engine_path):
                    raise RuntimeError(f"refused: {p} is the configured engine")
            cmd = self.build_command(e, tmp, cls)
            log_path = final + ".build.log"
            log.warning("model %s: building engine: %s", e.key, " ".join(cmd))
            t0 = time.monotonic()
            with open(log_path, "w") as lf:
                lf.write(" ".join(cmd) + "\n")
                lf.flush()
                proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                e.build_proc = proc
                while proc.poll() is None:
                    if e.cancel_build.is_set() or time.monotonic() - t0 > self.build_timeout_s:
                        proc.terminate()
                        try:
                            proc.wait(10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                        break
                    time.sleep(0.2)
            e.build_proc = None
            if e.cancel_build.is_set():
                if os.path.exists(tmp):
                    os.remove(tmp)
                log.warning("model %s: engine build cancelled", e.key)
                return
            if proc.returncode != 0 or not os.path.isfile(tmp):
                tail = ""
                try:
                    with open(log_path) as lf:
                        tail = " | ".join(lf.read().strip().splitlines()[-5:])
                except OSError:
                    pass
                why = "timeout" if time.monotonic() - t0 > self.build_timeout_s else f"exit {proc.returncode}"
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise RuntimeError(f"trtexec failed ({why}, log {log_path}): {tail}")
            os.replace(tmp, final)
            log.warning("model %s: engine built in %.0f s: %s", e.key, time.monotonic() - t0, final)
            from infer.models.trt_engine import TrtEngine
            eng = TrtEngine(final)
            e.engine_source = "rebuilt"
            self._finish_load(e, cls, eng)
            with e.lock:
                if e.enabled and not e.cancel_build.is_set():
                    self._start_workers(e)
        except Exception as ex:
            log.debug("%s", traceback.format_exc())
            e.fail(f"load: {'; '.join(errors)}; rebuild: {type(ex).__name__}: {ex}")

    def _cancel_build(self, e: ModelEntry) -> None:
        e.cancel_build.set()
        t = e.build_thread
        if t is not None and t.is_alive() and threading.current_thread() is not t:
            t.join(timeout=15)

    # -- workers ------------------------------------------------------------------------------------
    def _start_workers(self, e: ModelEntry) -> None:
        with e.lock:
            if e.state == RUNNING or e.engine is None or e.removed:
                return
            self._join_workers(e)
            e.stop_event = threading.Event()
            e.metrics.running_since = time.monotonic()
            e.metrics.consecutive_errors = 0
            e.error, e.error_t = None, None
            e.workers = [ModelWorker(e, i, e.slots[i], self.store, self.on_result)
                         for i in range(e.workers_n)]
            e.state = RUNNING
            if e.engine_source != "rebuilt":
                e.reason = e.cfg.get("reason") if not e.cfg.get("enabled", False) else None
            for w in e.workers:
                w.start()
        log.info("model %s RUNNING (%d workers, cams %s)", e.key, e.workers_n, e.cameras)

    def _stop_workers(self, e: ModelEntry) -> None:
        e.stop_event.set()
        self._join_workers(e)

    def _join_workers(self, e: ModelEntry) -> None:
        for w in e.workers:
            if w is not threading.current_thread():
                w.join(timeout=5)
                if w.is_alive():
                    log.error("model %s: worker %s did not stop in 5 s", e.key, w.name)
        e.workers = [w for w in e.workers if w.is_alive()]

    # -- status -------------------------------------------------------------------------------------
    def _status_one(self, e: ModelEntry) -> dict:
        with e.lock:
            eng = e.engine
            m = e.metrics
            lat = m.latency()
            d = {
                "name": e.name,
                "version": e.version,          # "" for a legacy config/models.yaml entry
                "instance": e.key,             # <name>@<version>, or the name for a legacy entry
                "engine": eng.path if eng is not None else e.engine_path,
                "engine_version": eng.version_tag if eng is not None else None,
                "state": e.state,
                "error": e.error,
                "reason": e.reason,
                "enabled": bool(e.enabled),
                "cameras": list(e.cameras),
                "fps": m.fps() if e.state == RUNNING else 0.0,
                "lat_ms": {k: lat[k] for k in ("pre", "infer", "post", "total")},
                "gpu_mem_mb": round(eng.gpu_bytes_estimate() / 2 ** 20, 1) if eng is not None else None,
                "gpu_mem_note": GPU_MEM_NOTE,
                "trt_match": eng.trt_match if eng is not None else None,
                "trt_build_device": eng.trt_build_device if eng is not None else None,
                "trt_device_warning": eng.trt_device_warning if eng is not None else None,  # information only
                "trt_version": eng.trt_version if eng is not None else _trt_version(),
                "load_warnings": list(eng.load_warnings) if eng is not None else [],
                "inputs": [{"name": t.name, "shape": list(t.shape), "dtype": t.dtype} for t in eng.inputs()]
                if eng is not None else [],
                "outputs": [{"name": t.name, "shape": list(t.shape), "dtype": t.dtype} for t in eng.outputs()]
                if eng is not None else [],
                "results_total": m.results_total,
                "auto_restarts": e.auto_restarts,
                "restart_in_s": (round(max(0.0, e.restart_due - time.monotonic()), 1)
                                 if e.restart_due is not None else None),
                # extra fields (not in the dashboard contract; the dashboard ignores them)
                "group": e.group,
                "adapter": e.adapter_name,
                "engine_source": e.engine_source,
                "workers": e.workers_n,
                "max_fps_per_camera": e.max_fps,
                "error_t": e.error_t,
                "errors_total": m.errors_total,
                "results_dropped_old": m.results_dropped_old,
                "results_dropped_stale": m.results_dropped_stale,
                "on_result_errors": m.on_result_errors,
                "last_error": m.last_error,
                "last_error_t": m.last_error_t,
                "last_result_t": m.last_result_t,
                "cam_fps": m.cam_fps() if e.state == RUNNING else {},
                "queue_ms": lat["queue"],
            }
        return d
