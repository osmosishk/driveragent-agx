"""Model manifest: MODEL_STORE/<name>/<version>/manifest.yaml (docs/DEPLOY_MODEL.md). Pure Python.

  schema       agx-model-manifest/1
  name         [a-z0-9][a-z0-9_]{0,47} (a leading "_" is reserved for store folders)
  version      [A-Za-z0-9._-]{1,32} (a string: write "1", not 1)
  type         selects the adapter (TYPES). An unknown type gives the state NO ADAPTER.
  description  text
  files        list of {role: engine|onnx|weights|other, path, sha256}. A relative path is relative to the version
               folder. An absolute path (for example an old engine) is used read-only at that place.
  input        {tensors: [{name, shape, dtype}], size: {width, height}, colour_order, normalisation}
  precision    fp16 | fp32 | int8 | mixed
  cameras      {permitted: [cam ids 0..5], default: [subset of permitted]}
  adapter      {class_names: [..], score_limit: 0..1, options: {..}} (adapter parameters)
  outputs      {tensors: [{name, shape, dtype}], kinds: [boxes|drivable_area|lane_lines|trajectory|other]}
  runtime      {workers: 1..4, max_fps_per_camera: 1..30} (optional)
  build        {shapes: "image:1x3x384x640,...", precision: fp16} (optional: used to build an engine from ONNX)
  date         YYYY-MM-DD
  notes        text (optional)

load() never raises for a bad manifest: it returns a Manifest with a list of errors in plain words.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import yaml

SCHEMA = "agx-model-manifest/1"
# type -> adapter module in infer/models/adapters (docs/ADD_MODEL_TYPE.md)
TYPES = {"yolopx": "yolopx_v2", "dtcp": "dtcp_v1"}
FILE_ROLES = ("engine", "onnx", "weights", "other")
OUTPUT_KINDS = ("boxes", "drivable_area", "lane_lines", "trajectory", "other")
PRECISIONS = ("fp16", "fp32", "int8", "mixed")
CAMERAS = range(6)
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,47}$")      # a leading "_" is reserved (_state, _testframes)
VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MANIFEST = "manifest.yaml"


def key(name: str, version: str) -> str:
    """The id of one model version (also the id of a running instance in agx-infer)."""
    return f"{name}@{version}"


@dataclass
class Manifest:
    folder: str
    data: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return str(self.data.get("name") or os.path.basename(os.path.dirname(self.folder)))

    @property
    def version(self) -> str:
        return str(self.data.get("version") or os.path.basename(self.folder))

    @property
    def key(self) -> str:
        return key(self.name, self.version)

    @property
    def type(self) -> str:
        return str(self.data.get("type") or "")

    @property
    def adapter(self) -> str | None:
        """Adapter module name, or None when this type has no adapter."""
        return TYPES.get(self.type)

    def files(self) -> list[dict]:
        """[{role, path (absolute), sha256}] of the manifest."""
        out = []
        for f in self.data.get("files") or []:
            if isinstance(f, dict) and f.get("path"):
                p = str(f["path"])
                out.append({"role": str(f.get("role") or "other"),
                            "path": p if os.path.isabs(p) else os.path.normpath(os.path.join(self.folder, p)),
                            "sha256": str(f.get("sha256") or "").lower()})
        return out

    def file(self, role: str) -> dict | None:
        return next((f for f in self.files() if f["role"] == role), None)

    def cameras(self) -> tuple[list[int], list[int]]:
        c = self.data.get("cameras") or {}
        return [int(x) for x in c.get("permitted") or []], [int(x) for x in c.get("default") or []]

    def output_kinds(self) -> list[str]:
        return [str(k) for k in (self.data.get("outputs") or {}).get("kinds") or []]

    def tensors(self, part: str) -> list[dict]:
        """part = "input" | "outputs": [{name, shape, dtype}]."""
        return [t for t in (self.data.get(part) or {}).get("tensors") or [] if isinstance(t, dict)]

    def runtime(self) -> dict:
        r = self.data.get("runtime") or {}
        return {"workers": int(r.get("workers", 1)), "max_fps_per_camera": float(r.get("max_fps_per_camera", 30))}

    def adapter_options(self) -> dict:
        """Options for the adapter: adapter.options + score_limit (conf_thres) + class_names."""
        a = self.data.get("adapter") or {}
        opts = dict(a.get("options") or {})
        if a.get("score_limit") is not None:
            opts["conf_thres"] = float(a["score_limit"])
        if a.get("class_names"):
            opts["class_names"] = [str(c) for c in a["class_names"]]
        return opts

    def summary(self) -> dict:
        d = self.data
        permitted, default = self.cameras()
        return {"name": self.name, "version": self.version, "type": self.type,
                "description": d.get("description"), "precision": d.get("precision"), "date": d.get("date"),
                "notes": d.get("notes"), "cameras_permitted": permitted, "cameras_default": default,
                "output_kinds": self.output_kinds(), "adapter": self.adapter,
                "input": {k: v for k, v in (d.get("input") or {}).items() if k != "tensors"},
                "input_tensors": self.tensors("input"), "output_tensors": self.tensors("outputs"),
                "files": self.files(), "runtime": self.runtime() if not self.errors else None}


def _tensor_errors(part: str, tensors) -> list[str]:
    errs = []
    if not isinstance(tensors, list) or not tensors:
        return [f"{part}.tensors: a list with at least one tensor is needed"]
    for i, t in enumerate(tensors):
        if not isinstance(t, dict) or not t.get("name"):
            errs.append(f"{part}.tensors[{i}]: a name is needed")
            continue
        shape = t.get("shape")
        if not isinstance(shape, list) or not shape or not all(isinstance(s, int) for s in shape):
            errs.append(f"{part}.tensors[{i}] {t['name']}: shape must be a list of integers")
    return errs


def validate(d, folder: str) -> list[str]:
    """Plain-words errors of a manifest dict ([] = valid)."""
    if not isinstance(d, dict):
        return ["the manifest is not a YAML mapping"]
    errs = []
    if d.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA!r} (found {d.get('schema')!r})")
    name, version = str(d.get("name") or ""), d.get("version")
    if not NAME_RE.match(name):
        errs.append("name must be 1-48 characters a-z, 0-9 or _, and must not start with _")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        errs.append("version must be a quoted string of 1-32 characters A-Z, a-z, 0-9, '.', '_' or '-'")
    parts = os.path.normpath(folder).split(os.sep)
    if len(parts) >= 2 and name and isinstance(version, str) and (parts[-2], parts[-1]) != (name, version):
        errs.append(f"the folder must be <store>/{name}/{version} (it is .../{parts[-2]}/{parts[-1]})")
    if not d.get("type") or not isinstance(d.get("type"), str):
        errs.append("type is needed (for example yolopx or dtcp)")
    if not d.get("description"):
        errs.append("description is needed")
    files = d.get("files")
    if not isinstance(files, list):
        errs.append("files must be a list (it can be empty)")
        files = []
    for i, f in enumerate(files):
        if not isinstance(f, dict) or not f.get("path"):
            errs.append(f"files[{i}]: path is needed")
            continue
        if f.get("role") not in FILE_ROLES:
            errs.append(f"files[{i}]: role must be one of {', '.join(FILE_ROLES)}")
        if not SHA_RE.match(str(f.get("sha256") or "").lower()):
            errs.append(f"files[{i}] {f['path']}: sha256 must be 64 hexadecimal characters")
    roles = [f.get("role") for f in files if isinstance(f, dict)]
    for r in ("engine", "onnx"):
        if roles.count(r) > 1:
            errs.append(f"files: more than one {r} file")
    if d.get("type") in TYPES:  # the checks need tensors only for a type with an adapter
        errs += _tensor_errors("input", (d.get("input") or {}).get("tensors"))
        errs += _tensor_errors("outputs", (d.get("outputs") or {}).get("tensors"))
    kinds = (d.get("outputs") or {}).get("kinds")
    if not isinstance(kinds, list) or not kinds or any(k not in OUTPUT_KINDS for k in kinds):
        errs.append(f"outputs.kinds must be a list of {', '.join(OUTPUT_KINDS)}")
    if d.get("precision") not in PRECISIONS:
        errs.append(f"precision must be one of {', '.join(PRECISIONS)}")
    cams = d.get("cameras") or {}
    permitted, default = cams.get("permitted"), cams.get("default")
    if not isinstance(permitted, list) or not permitted or any(c not in CAMERAS for c in permitted):
        errs.append("cameras.permitted must be a list of camera ids 0..5")
    elif not isinstance(default, list) or any(c not in permitted for c in default):
        errs.append("cameras.default must be a list that is part of cameras.permitted")
    ad = d.get("adapter") or {}
    if not isinstance(ad, dict):
        errs.append("adapter must be a mapping")
    elif ad.get("score_limit") is not None and not 0 <= float(ad["score_limit"]) <= 1:
        errs.append("adapter.score_limit must be 0..1")
    rt = d.get("runtime") or {}
    if not 1 <= int(rt.get("workers", 1)) <= 4:
        errs.append("runtime.workers must be 1..4")
    if not 0 < float(rt.get("max_fps_per_camera", 30)) <= 30:
        errs.append("runtime.max_fps_per_camera must be more than 0 and at most 30")
    if not DATE_RE.match(str(d.get("date") or "")):
        errs.append("date must be YYYY-MM-DD")
    return errs


def load(folder: str) -> Manifest:
    """Read <folder>/manifest.yaml. Content errors are in Manifest.errors (no exception)."""
    folder = os.path.abspath(folder)
    path = os.path.join(folder, MANIFEST)
    try:
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f)
    except FileNotFoundError:
        return Manifest(folder, {}, [f"no {MANIFEST} in {folder}"])
    except (OSError, yaml.YAMLError) as e:
        return Manifest(folder, {}, [f"{MANIFEST} cannot be read: {e}"])
    m = Manifest(folder, d if isinstance(d, dict) else {})
    m.errors = validate(d, folder)
    return m
