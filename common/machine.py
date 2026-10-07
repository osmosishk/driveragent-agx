"""Values of this machine that are not in the code: the node name and the protected folders.

node_name: config key node_name (config/dashboard.yaml); null or missing = the short host name.
protected_dirs: config key protected_dirs (config/dashboard.yaml and config/infer.yaml): folders that no part of
this software writes (for example the old engines). Missing or null = no protected folder.
"""
from __future__ import annotations

import os
import socket


def short_hostname() -> str:
    """The host name without the domain part ("agx" when the host name is not known)."""
    try:
        name = socket.gethostname().split(".")[0].strip()
    except OSError:
        name = ""
    return name or "agx"


def node_name(cfg: dict | None) -> str:
    """config node_name, else the short host name."""
    v = (cfg or {}).get("node_name")
    return str(v).strip() if v is not None and str(v).strip() else short_hostname()


def protected_dirs(dirs) -> list[str]:
    """Real absolute paths of the protected folders (~ is expanded). None, "" or a bad type = []."""
    if not dirs:
        return []
    if isinstance(dirs, (str, os.PathLike)):
        dirs = [dirs]
    out = []
    for d in dirs:
        if d is None or not str(d).strip():
            continue
        p = os.path.realpath(os.path.expanduser(str(d)))
        if p not in out:
            out.append(p)
    return out


def inside_protected(path, dirs) -> str | None:
    """The protected folder that contains path (or is path), else None. Real paths: a symbolic link into a
    protected folder is inside it. "/a/model" does not contain "/a/models"."""
    p = os.path.realpath(os.path.expanduser(str(path)))
    for d in protected_dirs(dirs):
        if p == d or p.startswith(d.rstrip(os.sep) + os.sep):
            return d
    return None
