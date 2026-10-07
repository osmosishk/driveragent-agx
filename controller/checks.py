"""Model check queue: runs tools/model_check.py as a child process, ONE check at a time.

The GPU is shared with the live agx-infer, so only one check runs at any time (one background thread).
A result is stored as JSON in <store>/_state/checks/<name>@<version>.json with a "fingerprint": sha256 of the
manifest.yaml bytes + the size and mtime_ns of every file of the manifest. result(key) returns None (stale)
when the fingerprint no longer matches, so a changed file needs a new check.

No TensorRT, CUDA or torch import here (the dashboard imports this module).
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from collections import deque

from controller import manifest as mf

CHECK_PREFIX = "CHECK:"
STDERR_TAIL = 300


def fingerprint(folder: str) -> str:
    """sha256 of the manifest.yaml bytes + (path, size, mtime_ns) of every file of the manifest."""
    h = hashlib.sha256()
    try:
        with open(os.path.join(folder, mf.MANIFEST), "rb") as f:
            h.update(f.read())
    except OSError:
        h.update(b"<no manifest>")
    for f in mf.load(folder).files():
        try:
            st = os.stat(f["path"])
            h.update(f"\n{f['path']}\0{st.st_size}\0{st.st_mtime_ns}".encode())
        except OSError:
            h.update(f"\n{f['path']}\0<missing>".encode())
    return h.hexdigest()


def _write_json_atomic(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _failed(key: str, reason: str) -> dict:
    return {"ok": False, "reason": reason, "checks": [], "key": key, "t": time.time()}


class CheckRunner:
    """One background thread that runs the queued checks one after the other."""

    def __init__(self, store_root: str, repo_root: str, python_exe: str, timeout_s: float = 180,
                 frame: str | None = None, on_result=None):
        self.store_root = os.path.abspath(store_root)
        self.repo_root = os.path.abspath(repo_root)
        self.python_exe = python_exe
        self.timeout_s = timeout_s
        self.frame = frame                  # test frame for the inference check (None = the tool's default)
        self.on_result = on_result          # optional callback(key, result) after a check is stored
        self.dir = os.path.join(self.store_root, "_state", "checks")
        self._cv = threading.Condition()
        self._queue: deque = deque()        # (key, folder)
        self._busy: str | None = None
        self._proc: subprocess.Popen | None = None
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="model-checks", daemon=True)
        self._thread.start()

    # -- public API ------------------------------------------------------------------------------------------
    def request(self, manifest: mf.Manifest) -> bool:
        """Queue a check of this model version. False when it is already queued or running now."""
        k = manifest.key
        with self._cv:
            if self._stop or k == self._busy or any(q[0] == k for q in self._queue):
                return False
            self._queue.append((k, manifest.folder))
            self._cv.notify_all()
            return True

    def result(self, key: str) -> dict | None:
        """The stored result of `key`, or None when there is none or it is stale (a file changed)."""
        try:
            with open(self._path(key), encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(r, dict):
            return None
        if r.get("fingerprint") != fingerprint(r.get("folder") or self._folder_of(key)):
            return None
        return r

    def busy(self) -> str | None:
        """The key that is checked now, or None."""
        with self._cv:
            return self._busy

    def pending(self) -> list[str]:
        """The queued keys (not yet started), in order."""
        with self._cv:
            return [q[0] for q in self._queue]

    def wait_idle(self, timeout: float) -> bool:
        """Wait until no check is queued or running. True when idle."""
        end = time.monotonic() + timeout
        with self._cv:
            while self._queue or self._busy:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cv.wait(left)
            return True

    def stop(self, timeout: float = 5.0) -> None:
        """End the thread. A running check is killed and gives no result; the queue is dropped."""
        with self._cv:
            self._stop = True
            self._queue.clear()
            proc = self._proc
            self._cv.notify_all()
        if proc is not None:
            self._kill(proc)
        self._thread.join(timeout)

    # -- internals -------------------------------------------------------------------------------------------
    def _path(self, key: str) -> str:
        if "/" in key or key.startswith("."):
            raise ValueError(f"bad key {key!r}")
        return os.path.join(self.dir, f"{key}.json")

    def _folder_of(self, key: str) -> str:
        name, _, version = key.partition("@")
        return os.path.join(self.store_root, name, version)

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)     # the whole process group (start_new_session=True)
        except (ProcessLookupError, PermissionError):
            pass

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                key, folder = self._queue.popleft()
                self._busy = key
            try:
                res = self._check(key, folder)
                if res is not None:
                    _write_json_atomic(self._path(key), res)
                    if self.on_result is not None:
                        self.on_result(key, res)
            except Exception as e:  # noqa: BLE001 - the thread must keep running
                try:
                    res = dict(_failed(key, f"the check could not be run: {type(e).__name__}: {e}"),
                               folder=folder, fingerprint=fingerprint(folder))
                    _write_json_atomic(self._path(key), res)
                except Exception:  # noqa: BLE001
                    pass
            finally:
                with self._cv:
                    self._busy = None
                    self._proc = None
                    self._cv.notify_all()

    def _check(self, key: str, folder: str) -> dict | None:
        """Run the child for one folder. None when stop() interrupted it."""
        fp = fingerprint(folder)    # taken BEFORE the check: a change during the check makes the result stale
        cmd = [self.python_exe, "-m", "tools.model_check", folder, "--json"]
        if self.frame:
            cmd += ["--frame", self.frame]
        env = dict(os.environ, PYTHONPATH=self.repo_root, PYTHONDONTWRITEBYTECODE="1")
        t0 = time.monotonic()
        with self._cv:
            if self._stop:
                return None
            proc = subprocess.Popen(cmd, cwd=self.repo_root, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    start_new_session=True)
            self._proc = proc
        try:
            out, err = proc.communicate(timeout=self.timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            self._kill(proc)
            out, err = proc.communicate()
            timed_out = True
        if self._stop:
            return None
        dur = round(time.monotonic() - t0, 3)
        if timed_out:
            res = _failed(key, f"check did not finish in {self.timeout_s:g} s")
        else:
            lines = [ln for ln in (out or "").splitlines() if ln.startswith(CHECK_PREFIX)]
            res = None
            if lines:
                try:
                    res = json.loads(lines[-1][len(CHECK_PREFIX):])
                except ValueError:
                    res = None
            if not isinstance(res, dict):
                tail = (err or "").strip()[-STDERR_TAIL:]
                res = _failed(key, tail or f"the check gave no result (exit code {proc.returncode})")
        res.setdefault("duration_s", dur)
        res.update(key=key, folder=folder, fingerprint=fp, exit_code=proc.returncode)
        return res
