"""TensorRT engine facts for the models part (size, date, sha256[:16], TensorRT load, I/O).

Source: tools/inspect_engines.py (inspect(path), scan(dirs)). Each engine is read in its own
subprocess (about 0.5 s each). A background thread scans at start and every interval_s (30 min).

Cache (JSON file, default data/engines_cache.json):
  {"version": 2, "t": <unix s>, "entries": {"<realpath>|<size>|<mtime_ns>": {<inspect() result>}}}
Only engines with a new key (new file, other size or other mtime) are inspected again.
Version 2 (2026-10-07): new trt_match rule and the fields trt_build_device / trt_device_warning
(common/trt_compat.py). A version 1 cache is ignored, so every engine is inspected again with the new rule.
Each entry has the boot_id of its inspection. The TensorRT device warning depends on the boot (total memory),
so an entry of an other boot is inspected again at the next scan (one time in each boot).
An inspection that FAILED (timeout, GPU memory full while agx-infer runs, ...) is not kept as final:
the next periodic scan (start + every interval_s) inspects that engine again.
The engines of config/models.yaml are always inspected, also when they are outside the scan dirs.
facts_note() / found_notes() compare the CURRENT size + mtime of the file with the cached key: a
changed (or new) file gives no facts but the note "inspection pending", and starts a scan at once
(at most one each RESCAN_MIN_S).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("dashboard.engines")

CACHE_VERSION = 2
RESCAN_MIN_S = 30.0
PENDING = "file changed or new: inspection pending"
BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"


def current_boot_id() -> str | None:
    """Linux boot ID, or None when it cannot be read."""
    try:
        with open(BOOT_ID_PATH, encoding="ascii") as f:
            return f.read().strip() or None
    except OSError:
        return None


def file_key(path: str) -> tuple[str, str] | None:
    """(realpath, cache key) or None when the file does not exist."""
    real = os.path.realpath(path)
    try:
        st = os.stat(real)
    except OSError:
        return None
    return real, f"{real}|{st.st_size}|{st.st_mtime_ns}"


class EngineScanner:
    def __init__(self, cache_path: Path, scan_dirs: list[str], config_engines_fn, interval_s: float = 1800,
                 inspect_timeout_s: float = 120.0):
        self.cache_path = Path(cache_path)
        self.scan_dirs = list(scan_dirs)
        self.config_engines_fn = config_engines_fn  # () -> list of engine paths from models.yaml
        self.interval_s = float(interval_s)
        self.inspect_timeout_s = float(inspect_timeout_s)
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}   # key -> info
        self._by_real: dict[str, dict] = {}   # realpath -> info (current files only)
        self._key_by_real: dict[str, str] = {}  # realpath -> cache key of that info
        self._found: list[str] = []           # realpaths found by the last scan
        self._t: float | None = None
        self._error: str | None = None
        self._running = False
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._last_wake_req = 0.0
        self._thread: threading.Thread | None = None
        self._load_cache()

    # ---- cache file
    def _load_cache(self):
        try:
            d = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            self._error = f"cannot read engine cache {self.cache_path}: {e}"
            log.warning(self._error)
            return
        if not isinstance(d, dict) or d.get("version") != CACHE_VERSION or not isinstance(d.get("entries"), dict):
            self._error = f"engine cache {self.cache_path} has an unknown format: ignored"
            return
        ents = {k: v for k, v in d["entries"].items() if isinstance(v, dict)}
        with self._lock:
            self._entries = ents
            self._t = d.get("t")
            # until the first scan: use the cached entries whose file did not change
            for k, v in ents.items():
                real = k.split("|", 1)[0]
                fk = file_key(real)
                if fk and fk[1] == k:
                    self._by_real[real] = v
                    self._key_by_real[real] = k
            self._found = sorted(self._by_real)

    def _save_cache(self):
        with self._lock:
            doc = {"version": CACHE_VERSION, "t": self._t, "entries": dict(self._entries)}
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_name(self.cache_path.name + ".tmp")
            tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError as e:
            with self._lock:
                self._error = f"cannot write engine cache {self.cache_path}: {e}"
            log.warning("cannot write engine cache: %s", e)

    # ---- scan
    def scan_once(self, retry_failed: bool = True) -> None:
        """retry_failed: inspect again the engines whose cached inspection FAILED (periodic scans)."""
        from tools.inspect_engines import inspect, scan

        boot = current_boot_id()
        with self._lock:
            self._running = True
        errors = []
        try:
            try:
                found = scan([d for d in self.scan_dirs if os.path.isdir(d)])
            except OSError as e:
                found = []
                errors.append(f"scan failed: {e}")
            missing_dirs = [d for d in self.scan_dirs if not os.path.isdir(d)]
            if missing_dirs:
                errors.append("scan directory not found: " + ", ".join(missing_dirs))
            paths = list(found)
            try:
                paths += [p for p in self.config_engines_fn() if p]
            except Exception as e:  # noqa: BLE001
                errors.append(f"cannot read engine paths of the model config: {e}")
            new_entries: dict[str, dict] = {}
            by_real: dict[str, dict] = {}
            key_by_real: dict[str, str] = {}
            with self._lock:
                old = dict(self._entries)
            for p in paths:
                fk = file_key(p)
                if fk is None:
                    continue
                real, key = fk
                if real in by_real:
                    continue
                info = old.get(key)
                if info is not None and retry_failed and info.get("load") != "OK":
                    info = None  # a failed inspection can be temporary: try again
                if info is not None and info.get("boot_id") != boot:
                    info = None  # the TensorRT device warning depends on the boot: inspect again in this boot
                if info is None:
                    t0 = time.monotonic()
                    try:
                        info = inspect(real, timeout=self.inspect_timeout_s)
                    except Exception as e:  # noqa: BLE001
                        info = {"path": real, "realpath": real, "load": "FAILED", "trt_match": False,
                                "trt_build_device": None, "trt_device_warning": None,
                                "error": f"inspect failed: {e}"}
                    info["inspect_s"] = round(time.monotonic() - t0, 2)
                    info["inspected_t"] = time.time()
                    info["boot_id"] = boot
                    log.info("engine inspected %s load %s (%.1f s)", real, info.get("load"), info["inspect_s"])
                new_entries[key] = info
                by_real[real] = info
                key_by_real[real] = key
            with self._lock:
                self._entries = new_entries
                self._by_real = by_real
                self._key_by_real = key_by_real
                self._found = sorted({os.path.realpath(p) for p in found})
                self._t = time.time()
                self._error = "; ".join(errors) or None
            self._save_cache()
        finally:
            with self._lock:
                self._running = False

    def _loop(self):
        periodic = True
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.scan_once(retry_failed=periodic)
            except Exception as e:  # noqa: BLE001 - never let the thread die
                log.exception("engine scan failed")
                with self._lock:
                    self._error = f"engine scan failed: {e}"
            # wake up at the interval (periodic scan) or when a changed file was seen (wake scan)
            periodic = not self._wake.wait(self.interval_s)
            if self._stop.is_set():
                break

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="engine-scan", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _request_scan(self):
        now = time.monotonic()
        with self._lock:
            if self._running or now - self._last_wake_req < RESCAN_MIN_S:
                return
            self._last_wake_req = now
        self._wake.set()

    # ---- read
    def _current(self, real: str) -> tuple[dict | None, str | None]:
        """(facts, note) for one realpath; facts only when the file did not change since inspection."""
        fk = file_key(real)
        with self._lock:
            info = self._by_real.get(real)
            key = self._key_by_real.get(real)
        if fk is None:
            return None, "file not found"
        if info is None or key != fk[1]:
            self._request_scan()
            return None, PENDING
        return info, None

    def facts_note(self, path: str | None) -> tuple[dict | None, str | None]:
        if not path:
            return None, None
        return self._current(os.path.realpath(path))

    def facts(self, path: str | None) -> dict | None:
        return self.facts_note(path)[0]

    def found_notes(self) -> list[tuple[str, dict | None, str | None]]:
        """[(realpath, facts or None, note)] for the engine files of the last scan."""
        with self._lock:
            reals = list(self._found)
        out = []
        for r in reals:
            f, note = self._current(r)
            if note == "file not found":
                continue  # removed since the scan
            out.append((r, f, note))
        return out

    def found(self) -> list[dict]:
        return [f for _, f, _ in self.found_notes() if f is not None]

    def status(self) -> dict:
        with self._lock:
            return {"t": self._t, "count": len(self._found), "error": self._error, "running": self._running,
                    "dirs": list(self.scan_dirs), "interval_s": self.interval_s,
                    "cache": str(self.cache_path)}
