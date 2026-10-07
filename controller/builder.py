"""Build job: ONNX -> TensorRT engine on this AGX with trtexec, as a background child process. Pure Python.

Output in the version folder: <name>_<version>_<precision>.engine (written as .partial, renamed when trtexec is done),
build.log and build.json ({state: running|done|failed, engine, engine_sha256, command, started, ended, duration_s,
error}). The old engines and the protected folders (config protected_dirs, common/machine.py) are never written.
Only one build at a time (the controller holds the change slot during a build: owner rules M4 and 4.4).
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time

from common.machine import inside_protected
from controller import manifest as mf
from controller.store import BUILD_INFO, sha256_file, write_json

DEFAULT_TRTEXEC = "/usr/src/tensorrt/bin/trtexec"
WARNING = ("A build uses the GPU and the CPU for some minutes: during the build the active models give fewer results "
           "per second and a longer latency.")


def engine_name(m: mf.Manifest) -> str:
    prec = str((m.data.get("build") or {}).get("precision") or m.data.get("precision") or "fp16")
    return f"{m.name}_{m.version}_{prec}.engine"


def build_command(trtexec: str, onnx: str, out_partial: str, m: mf.Manifest) -> list[str]:
    b = m.data.get("build") or {}
    prec = str(b.get("precision") or m.data.get("precision") or "fp16")
    cmd = ["nice", "-n", "10", trtexec, f"--onnx={onnx}", f"--saveEngine={out_partial}"]
    if prec == "fp16":
        cmd.append("--fp16")
    elif prec == "int8":
        cmd.append("--int8")
    if b.get("shapes"):
        cmd.append(f"--shapes={b['shapes']}")
    if b.get("workspace_mb"):
        cmd.append(f"--memPoolSize=workspace:{int(b['workspace_mb'])}M")
    return cmd


class BuildJob:
    """One build. start() runs it in a thread; job() is the dict for the API. done_cb(job) is called at the end."""

    def __init__(self, m: mf.Manifest, trtexec: str = DEFAULT_TRTEXEC, timeout_s: float = 3600.0, done_cb=None,
                 protected_dirs=()):
        self.m = m
        self.trtexec = trtexec
        self.timeout_s = float(timeout_s)
        self.done_cb = done_cb
        self.folder = m.folder
        if inside_protected(self.folder, protected_dirs):
            raise ValueError(f"refuse to build into {self.folder}: it is inside the protected folder "
                             f"{inside_protected(self.folder, protected_dirs)} (config protected_dirs)")
        self.out = os.path.join(self.folder, engine_name(m))
        self.partial = self.out + ".partial"
        self.log_path = os.path.join(self.folder, "build.log")
        self.state = "queued"
        self.started = None
        self.ended = None
        self.error = None
        self.engine_sha256 = None
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"build-{m.key}", daemon=True)

    def start(self):
        self._thread.start()

    def cancel(self):
        self._cancel.set()

    def job(self) -> dict:
        el = (self.ended or time.time()) - self.started if self.started else 0.0
        return {"kind": "build", "key": self.m.key, "state": self.state, "started": self.started, "ended": self.ended,
                "elapsed_s": round(el, 1), "progress": self.progress(), "log": self.log_path, "engine": self.out,
                "engine_sha256": self.engine_sha256, "error": self.error, "warning": WARNING}

    def progress(self) -> str:
        """The last useful line of the trtexec log (trtexec has no percent value)."""
        try:
            with open(self.log_path, "rb") as f:
                f.seek(max(0, os.path.getsize(self.log_path) - 4096))
                lines = [ln.strip() for ln in f.read().decode("utf-8", "replace").splitlines() if ln.strip()]
        except OSError:
            return ""
        return lines[-1][-160:] if lines else ""

    def _info(self, **kw):
        d = {"state": self.state, "engine": os.path.basename(self.out), "engine_sha256": self.engine_sha256,
             "command": " ".join(build_command(self.trtexec, "<onnx>", "<out>", self.m)), "started": self.started,
             "ended": self.ended, "duration_s": round((self.ended or time.time()) - (self.started or time.time()), 1),
             "log": "build.log", "error": self.error}
        d.update(kw)
        write_json(os.path.join(self.folder, BUILD_INFO), d)

    def _run(self):
        self.state, self.started = "running", time.time()
        try:
            onnx = self.m.file("onnx")
            if onnx is None or not os.path.isfile(onnx["path"]):
                raise RuntimeError("no ONNX file in the manifest, or the file is missing")
            if sha256_file(onnx["path"]) != onnx["sha256"]:
                raise RuntimeError(f"the sha256 of {onnx['path']} does not agree with the manifest")
            self._info()
            cmd = build_command(self.trtexec, onnx["path"], self.partial, self.m)
            with open(self.log_path, "wb") as log:
                log.write(("$ " + " ".join(cmd) + "\n").encode())
                log.flush()
                self._proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=self.folder,
                                              start_new_session=True)
                t0 = time.monotonic()
                while self._proc.poll() is None:
                    if self._cancel.is_set() or time.monotonic() - t0 > self.timeout_s:
                        os.killpg(self._proc.pid, signal.SIGKILL)
                        self._proc.wait()
                        raise RuntimeError("build cancelled" if self._cancel.is_set()
                                           else f"build did not finish in {self.timeout_s:.0f} s")
                    time.sleep(0.5)
            if self._proc.returncode != 0:
                raise RuntimeError(f"trtexec exit code {self._proc.returncode}: {self.progress()}")
            if not os.path.isfile(self.partial) or os.path.getsize(self.partial) == 0:
                raise RuntimeError("trtexec wrote no engine file")
            os.replace(self.partial, self.out)
            self.engine_sha256 = sha256_file(self.out)
            self.state, self.ended = "done", time.time()
            self._info()
        except Exception as e:  # every failure becomes a reason in plain words
            self.state, self.ended, self.error = "failed", time.time(), str(e)
            try:
                if os.path.exists(self.partial):
                    os.unlink(self.partial)   # a half engine of THIS build (never an old engine)
                self._info()
            except OSError:
                pass
        finally:
            if self.done_cb is not None:
                try:
                    self.done_cb(self)
                except Exception:
                    pass
