"""Store version -> agx-infer runtime config of one model instance, and the active-set files. Pure Python.

An instance is keyed "<name>@<version>" (controller.manifest.key). agx-infer (infer/main.py) uses runtime_cfg() for
the last good set at start; the controller uses it for the admin command "add".

Active-set files in <store>/_state/ (written by the controller, read by agx-infer at start):
  active.json      the set that runs now
  last_good.json   the last set that gave valid results (rollback target; agx-infer loads it after a restart)
  format: {"t": <unix s>, "set": [{"name", "version", "cameras": [..]}], "source", "user", "reason"}
"""
from __future__ import annotations

import time

from controller import manifest as mf
from controller.store import Store, read_json, write_json

ACTIVE = "active.json"
LAST_GOOD = "last_good.json"


class NotRunnable(ValueError):
    """A version that cannot run (no adapter, no engine, bad cameras): the text is the reason in plain words."""


def runtime_cfg(store: Store, m: mf.Manifest, cameras=None) -> dict:
    """The ModelManager entry of this version on these cameras (default: the manifest default cameras)."""
    if m.errors:
        raise NotRunnable(f"{m.key}: manifest error: {'; '.join(m.errors[:3])}")
    if m.adapter is None:
        raise NotRunnable(f"{m.key}: no adapter for type {m.type!r}")
    eng = store.engine(m)
    if eng is None:
        raise NotRunnable(f"{m.key}: no engine (build it first)")
    permitted, default = m.cameras()
    cams = [int(c) for c in (default if cameras is None else cameras)]
    if not cams:
        raise NotRunnable(f"{m.key}: no camera selected")
    bad = [c for c in cams if c not in permitted]
    if bad:
        raise NotRunnable(f"{m.key}: camera(s) {bad} not permitted (permitted: {permitted})")
    rt = m.runtime()
    return {"name": m.name, "version": m.version, "group": m.type, "enabled": True, "engine": eng["path"],
            "onnx": None,          # no automatic rebuild in agx-infer: builds are controller jobs (docs/MODEL_CONTROL_API.md)
            "adapter": m.adapter, "cameras": sorted(set(cams)), "workers": rt["workers"],
            "max_fps_per_camera": rt["max_fps_per_camera"], "options": m.adapter_options()}


def read_set(store: Store, which: str = LAST_GOOD) -> dict | None:
    d = read_json(store.state / which)
    if not isinstance(d, dict) or not isinstance(d.get("set"), list):
        return None
    return d


def write_set(store: Store, which: str, items: list[dict], source: str, user: str, reason: str) -> dict:
    d = {"t": time.time(), "set": [{"name": i["name"], "version": str(i["version"]),
                                    "cameras": sorted(int(c) for c in i.get("cameras") or [])} for i in items],
         "source": source, "user": user, "reason": reason}
    write_json(store.state / which, d)
    return d


def configs_for_set(store: Store, items: list[dict]) -> tuple[list[dict], list[str]]:
    """(runtime configs, problems) for a stored set; a version that cannot run is left out with its reason."""
    cfgs, problems = [], []
    for i in items:
        m = store.get(str(i.get("name")), str(i.get("version")))
        if m is None:
            problems.append(f"{i.get('name')}@{i.get('version')}: not in the store")
            continue
        try:
            cfgs.append(runtime_cfg(store, m, i.get("cameras")))
        except NotRunnable as e:
            problems.append(str(e))
    return cfgs, problems
