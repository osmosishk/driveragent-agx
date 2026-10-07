"""Model store (MODEL_STORE, default ~/agx-models; not in git). Pure Python.

  <name>/<version>/manifest.yaml       the package description (controller/manifest.py)
  <name>/<version>/model.onnx          optional
  <name>/<version>/<name>_<version>_fp16.engine + build.json    an engine built on this AGX (controller/builder.py)
  _state/                              controller state: active.json, last_good.json, audit.jsonl, events.jsonl,
                                       catalog.json, checks/, jobs/
  _testframes/                         stored camera frames for the inference check
Folder names that start with "_" or "." are not models.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from controller import manifest as mf

DEFAULT_ROOT = "~/agx-models"
BUILD_INFO = "build.json"


def write_json(path, obj) -> None:
    """Atomic write (tmp file + os.replace) of a JSON document."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Store:
    def __init__(self, root: str | None = None):
        self.root = Path(os.path.expanduser(root or DEFAULT_ROOT))

    @property
    def state(self) -> Path:
        return self.root / "_state"

    def exists(self) -> bool:
        return self.root.is_dir()

    def version_dir(self, name: str, version: str) -> Path:
        return self.root / name / version

    def entries(self) -> list[mf.Manifest]:
        """Every <name>/<version> folder, sorted. A folder with a bad or missing manifest gives errors, not an exception."""
        out = []
        if not self.root.is_dir():
            return out
        for nd in sorted(self.root.iterdir()):
            if not nd.is_dir() or nd.name.startswith(("_", ".")):
                continue
            for vd in sorted(nd.iterdir()):
                if vd.is_dir() and not vd.name.startswith(("_", ".")):
                    out.append(mf.load(str(vd)))
        return out

    def get(self, name: str, version: str) -> mf.Manifest | None:
        if not (mf.NAME_RE.match(name or "") and mf.VERSION_RE.match(version or "")):
            return None
        vd = self.version_dir(name, version)
        return mf.load(str(vd)) if vd.is_dir() else None

    def build_info(self, m: mf.Manifest) -> dict | None:
        """build.json of an engine built on this AGX, or None."""
        return read_json(os.path.join(m.folder, BUILD_INFO))

    def engine(self, m: mf.Manifest) -> dict | None:
        """The engine of this version: the manifest engine file, else a finished build. {role, path, sha256, built}."""
        f = m.file("engine")
        if f is not None:
            return dict(f, built=False)
        b = self.build_info(m)
        if b and b.get("state") == "done" and b.get("engine"):
            p = b["engine"] if os.path.isabs(b["engine"]) else os.path.join(m.folder, b["engine"])
            return {"role": "engine", "path": p, "sha256": str(b.get("engine_sha256") or ""), "built": True}
        return None
