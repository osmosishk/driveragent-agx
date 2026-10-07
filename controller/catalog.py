"""Catalog: the state of each model version in the store, with a reason in plain words. Pure Python.

States (owner Section 4.3):
  REGISTERED   the manifest is valid; the checks are not done yet (queued or running)
  NEEDS BUILD  no engine yet, an ONNX file is there: build it on this AGX
  BUILDING     a build job runs now
  READY        all checks passed: it can be activated
  ACTIVE       it runs now in agx-infer
  FAILED       always with a reason (bad manifest, missing file, failed check, failed in agx-infer, ...)
  NO ADAPTER   its type has no adapter in this version: it cannot be activated
"""
from __future__ import annotations

import os
import time

from controller import manifest as mf

STATES = ("REGISTERED", "NEEDS BUILD", "BUILDING", "READY", "ACTIVE", "FAILED", "NO ADAPTER")
LIVE_ACTIVE = {"RUNNING": None, "LOADED": "loaded, workers starting", "LOADING": "loading the engine"}


def _real(p) -> str | None:
    try:
        return os.path.realpath(p) if p else None
    except (OSError, ValueError):
        return None


def live_index(live_models) -> tuple[dict, dict]:
    """(by instance key, by (name, engine realpath)) of the agx-infer status models."""
    by_key, by_engine = {}, {}
    for lm in live_models or []:
        if not isinstance(lm, dict) or not lm.get("name"):
            continue
        if lm.get("version"):
            by_key[mf.key(lm["name"], str(lm["version"]))] = lm
        eng = _real(lm.get("engine"))
        if eng:
            by_engine[(lm["name"], eng)] = lm
    return by_key, by_engine


def _live_part(lm: dict | None) -> dict | None:
    if not lm or lm.get("state") == "OFF":   # listed by agx-infer, but not loaded and not running
        return None
    lat = (lm.get("lat_ms") or {}).get("total") or {}
    return {"state": lm.get("state"), "error": lm.get("error"), "cameras": lm.get("cameras") or [],
            "fps": lm.get("fps"), "latency_ms": {k: lat.get(k) for k in ("p50", "p95", "p99")},
            "results_total": lm.get("results_total"), "gpu_mem_mb": lm.get("gpu_mem_mb"),
            "engine_version": lm.get("engine_version"), "trt_match": lm.get("trt_match"),
            "trt_device_warning": lm.get("trt_device_warning")}


def _check_part(c: dict | None) -> dict | None:
    if not c:
        return None
    keep = ("ok", "reason", "t", "duration_s", "trt_version", "trt_match", "trt_build_device", "trt_device_warning",
            "gpu_need_mb", "gpu_free_mb", "inference_ms", "result_summary", "engine_sha256")
    d = {k: c.get(k) for k in keep}
    d["checks"] = [{"name": x.get("name"), "ok": x.get("ok"), "detail": x.get("detail")} for x in c.get("checks") or []]
    return d


def entry(m: mf.Manifest, store, check: dict | None, lm: dict | None, job: dict | None, check_state: str | None) -> dict:
    """One catalog row. check_state: None | "queued" | "running"."""
    e = {"key": m.key, "name": m.name, "version": m.version, "type": m.type or None, "folder": m.folder,
         "manifest_errors": list(m.errors)}
    if not m.errors:
        e.update(m.summary())
    e["check"] = _check_part(check)
    e["live"] = _live_part(lm)
    e["job"] = job
    eng = store.engine(m) if not m.errors else None
    e["engine"] = None if eng is None else {"path": eng["path"], "built": eng["built"],
                                             "exists": os.path.isfile(eng["path"])}
    for f in e.get("files") or []:
        f["exists"] = os.path.isfile(f["path"])

    def put(state: str, reason: str | None):
        e["state"], e["reason"] = state, reason
        return e

    if m.errors:
        return put("FAILED", "manifest error: " + "; ".join(m.errors[:3]))
    if m.adapter is None:
        notes = " ".join(str(m.data.get("notes") or "").split())
        no_files = m.file("engine") is None and m.file("onnx") is None
        return put("NO ADAPTER", f"no adapter for type {m.type!r} in this version "
                                 f"(types with an adapter: {', '.join(sorted(mf.TYPES))})"
                                 + (". It has no engine file and no ONNX file" if no_files else "")
                                 + (f". Notes: {notes[:240]}" if notes else ""))
    if lm is not None:
        st = str(lm.get("state") or "")
        if st in LIVE_ACTIVE:
            return put("ACTIVE", LIVE_ACTIVE[st])
        if st == "FAILED":
            return put("FAILED", "failed in agx-infer: " + str(lm.get("error") or "no error text"))
    if job and job.get("kind") == "build" and job.get("state") in ("queued", "running"):
        return put("BUILDING", f"build {job.get('state')}: {job.get('progress') or ''}".rstrip(": "))
    onnx = m.file("onnx")
    onnx_ok = onnx is not None and os.path.isfile(onnx["path"])
    if eng is None:
        if job and job.get("kind") == "build" and job.get("state") == "failed":
            return put("FAILED", "build failed: " + str(job.get("error") or "see the build log"))
        if onnx_ok:
            return put("NEEDS BUILD", "no engine yet: build one from the ONNX file on this AGX")
        return put("FAILED", "no engine file and no ONNX file")
    if not os.path.isfile(eng["path"]):
        if onnx_ok:
            return put("NEEDS BUILD", f"the engine file is missing ({eng['path']}): build one from the ONNX file")
        return put("FAILED", f"the engine file is missing: {eng['path']}")
    if check is None:
        return put("REGISTERED", {"running": "checks running now", "queued": "checks queued"}.get(
            check_state or "", "checks not done yet"))
    if check.get("ok"):
        return put("READY", None)
    return put("FAILED", "check failed: " + str(check.get("reason") or "no reason given"))


def build(store, checks, live_models, jobs: dict | None = None) -> list[dict]:
    """All catalog rows. checks: a CheckRunner (result(key), busy(), pending()) or None."""
    by_key, by_engine = live_index(live_models)
    busy = checks.busy() if checks else None
    pending = set(checks.pending()) if checks else set()
    rows = []
    for m in store.entries():
        lm = by_key.get(m.key)
        if lm is None and not m.errors:
            eng = store.engine(m)
            if eng is not None:
                cand = by_engine.get((m.name, _real(eng["path"])))
                if cand is not None and not cand.get("version"):  # an agx-infer that does not send versions yet
                    lm = cand
        cs = "running" if busy == m.key else ("queued" if m.key in pending else None)
        rows.append(entry(m, store, checks.result(m.key) if checks else None, lm, (jobs or {}).get(m.key), cs))
    return rows


def snapshot(rows: list[dict], control_mode: str) -> dict:
    """The short catalog for agx-infer (status to DA01): name, version, type, state, reason."""
    return {"t": time.time(), "control_mode": control_mode,
            "entries": [{k: r.get(k) for k in ("name", "version", "type", "state", "reason")} for r in rows]}
