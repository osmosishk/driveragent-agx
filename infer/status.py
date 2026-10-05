"""Node state of the AGX inference node.

States:
  STARTING  until ingest and the models are started
  RUNNING   normal
  DEGRADED  an enabled model is FAILED, or a camera is NO SIGNAL for more than no_signal_degraded_s
            (10 s) while other cameras run
  ERROR     no enabled model runs
Errors: newest first, at most 20, each "<UTC time> <text>". The same text is not added again while
it is the newest error.
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from collections import deque

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAX_ERRORS = 20


def git_version(path: str = ROOT) -> str:
    """git describe --always --dirty (read-only git command). "unknown" when git fails."""
    try:
        out = subprocess.run(["git", "-C", path, "describe", "--always", "--dirty"],
                             capture_output=True, text=True, timeout=5)
        v = out.stdout.strip()
        return v or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class NodeState:
    def __init__(self, version: str | None = None, no_signal_degraded_s: float = 10.0):
        self.t_start_mono = time.monotonic()
        self.t_start = time.time()
        self.pid = os.getpid()
        self.hostname = socket.gethostname()
        self.version = version if version is not None else git_version()
        self.no_signal_degraded_s = float(no_signal_degraded_s)
        self.started = False
        self.stopping = False
        self._state = "STARTING"
        self._reasons: list[str] = []
        self._errors: deque = deque(maxlen=MAX_ERRORS)
        self._last_err_text = None
        self._no_signal_since: dict[int, float] = {}
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    @property
    def reasons(self) -> list[str]:
        return list(self._reasons)

    def degraded(self) -> bool:
        return self._state == "DEGRADED"

    def uptime_s(self) -> float:
        return time.monotonic() - self.t_start_mono

    def add_error(self, text: str) -> None:
        text = str(text)[:500]
        with self._lock:
            if text == self._last_err_text:
                return
            self._last_err_text = text
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._errors.appendleft(f"{ts} {text}")

    def errors(self) -> list[str]:
        with self._lock:
            return list(self._errors)

    def evaluate(self, models: list[dict], cam_states: dict[int, str],
                 now_mono: float | None = None) -> str:
        """Calculate the node state from ModelManager.status() and the camera states."""
        now = time.monotonic() if now_mono is None else now_mono
        if self.stopping:
            # clean stop: the models and ingest stop before the status publisher. Keep the last
            # state, so a normal stop does not show ERROR or add an error entry.
            return self._state
        for cam, st in cam_states.items():
            if st == "NO SIGNAL":
                self._no_signal_since.setdefault(cam, now)
            else:
                self._no_signal_since.pop(cam, None)
        if not self.started:
            self._state, self._reasons = "STARTING", ["starting"]
            return self._state
        enabled = [m for m in models if m.get("enabled")]
        running = [m for m in enabled if m.get("state") == "RUNNING"]
        reasons = []
        if not running:
            self._state = "ERROR"
            self._reasons = ["no enabled model runs" if enabled else "no model is enabled"]
            return self._state
        for m in enabled:
            if m.get("state") == "FAILED":
                reasons.append(f"model {m.get('name')} FAILED: {m.get('error') or ''}".strip())
        others_run = any(st in ("OK", "SIMULATED") for st in cam_states.values())
        if others_run:
            for cam, t0 in sorted(self._no_signal_since.items()):
                if now - t0 > self.no_signal_degraded_s:
                    reasons.append(f"cam{cam} NO SIGNAL for {now - t0:.0f} s")
        self._state = "DEGRADED" if reasons else "RUNNING"
        self._reasons = reasons
        return self._state
