"""Audit log of the model controller (owner rule M3). Pure Python.

Each action that changes a model state is one JSON line in <store>/_state/audit.jsonl:
  {"t", "time", "source", "user", "action", "model", "version", "result", "reason", ...extra}
  source  agx-dashboard | rk-console | command-line | controller (automatic: watchdog, start-up)
  result  ok | started | refused | failed
GET /api/models/events serves this file, newest first.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

FILE = "audit.jsonl"
SOURCES = ("agx-dashboard", "rk-console", "command-line", "controller")
RESULTS = ("ok", "started", "refused", "failed")
_lock = threading.Lock()


def clean(text, n: int = 64) -> str:
    """A short single-line text (no control characters) for a log field."""
    return "".join(ch if ch.isprintable() else "?" for ch in str(text or ""))[:n]


def append(state_dir, source: str, user: str, action: str, name: str | None, version: str | None, result: str,
           reason: str | None = None, **extra) -> dict:
    """Write one audit line and return it. Never raises for a full disk: the error goes into the returned dict."""
    rec = {"t": round(time.time(), 3), "time": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
           "source": source if source in SOURCES else clean(source, 32), "user": clean(user),
           "action": clean(action, 32), "model": name, "version": version,
           "result": result if result in RESULTS else clean(result, 16), "reason": reason}
    rec.update(extra)
    path = Path(state_dir) / FILE
    line = json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        rec["audit_write_error"] = str(e)
    return rec


def read(state_dir, limit: int = 100) -> list[dict]:
    """The newest `limit` lines, newest first."""
    try:
        with open(Path(state_dir) / FILE, encoding="utf-8") as f:
            lines = f.readlines()[-max(1, min(int(limit), 5000)):]
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out
