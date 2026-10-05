"""Model adapters (preprocessing + postprocessing plug-ins). config/models.yaml field `adapter`
names a module here; the module exports ADAPTER_CLASS."""
from __future__ import annotations

import importlib
import re


def get_adapter_class(name):
    if not name or name == "none":
        raise ValueError("model has no adapter (adapter: none)")
    if not re.fullmatch(r"[a-z0-9_]+", str(name)):
        raise ValueError(f"bad adapter name {name!r}")
    mod = importlib.import_module(f"infer.models.adapters.{name}")
    cls = getattr(mod, "ADAPTER_CLASS", None)
    if cls is None:
        raise ValueError(f"adapter module {name!r} has no ADAPTER_CLASS")
    return cls
