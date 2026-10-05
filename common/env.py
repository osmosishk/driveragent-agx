"""Load KEY=VALUE settings from the project .env file.

Values are never printed or logged by this module. Callers must not log them either.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def _strip_quotes(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def load_env(path: str | os.PathLike | None = None) -> dict[str, str]:
    """Return a dict of the KEY=VALUE lines. Comments (#) and blank lines are ignored.

    A missing file gives an empty dict. Process environment variables are NOT merged here;
    use get() for "env file, then process environment" lookup.
    """
    p = Path(path) if path else DEFAULT_ENV_PATH
    out: dict[str, str] = {}
    try:
        text = p.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        out[key] = _strip_quotes(val.strip())
    return out


def get(env: dict[str, str], key: str, default: str = "") -> str:
    """Value from the .env dict; if empty there, from the process environment; else default."""
    v = env.get(key, "")
    if v == "":
        v = os.environ.get(key, "")
    return v if v != "" else default


def truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")
