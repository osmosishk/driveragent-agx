"""Register the four models of config/models.yaml as the first model store entries (version "1").

  python -m tools.register_existing_models --root OLD_MODEL_DIR [--store ~/agx-models] [--force] [--dry-run]

Writes MODEL_STORE/<name>/1/manifest.yaml (schema agx-model-manifest/1, controller/manifest.py) for
driverguard_yolopx, driverguard_dtcp, system1 and sparsedrive_convnext_orin. --root is the old model folder (on
AGX02: /home/tonyho/model); the files are below it (jetson_bundle/, sparsedrive/run/, system1/). The old files stay
at their place: the manifests name them by absolute path and this tool only reads them (sha256).
Facts (tensors, preprocessing, dates, notes) come from docs/MODELS.md, config/models.yaml and
infer/models/legacy/driverguard/preprocess.py; the engine I/O was checked with tools.inspect_engines.

An existing manifest is not overwritten without --force. --dry-run computes and checks everything but writes
nothing. Exit 0 when every model is written (or would be written); 1 when a file is missing or a manifest is
not valid; 2 when an existing manifest was kept (no --force).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import sys

import yaml

from controller import manifest as mf

VERSION = "1"
BLOCK = 1 << 20  # sha256 read size: 1 MiB

# folders below --root (the old model folder)
JB = "jetson_bundle"
SD = "sparsedrive/run"
S1 = "system1"

# Legacy YOLOPX class list (infer/models/legacy/driverguard/yolopx_postprocess.py:14, docs/MODELS.md 3.6).
YOLOPX_CLASSES = ["person", "rider", "car", "bus", "truck", "bike", "motor", "traffic light", "traffic sign",
                  "train"]
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


def _t(name: str, shape: list[int], dtype: str = "FLOAT") -> dict:
    return {"name": name, "shape": shape, "dtype": dtype}


def _mtime_date(path: str) -> str:
    """Local date (YYYY-MM-DD) of the file's modification time."""
    return datetime.date.fromtimestamp(os.stat(path).st_mtime).isoformat()


def specs(root: str) -> list[dict]:
    """Manifest dicts without sha256 values. A "date" of None is filled from the first file's mtime.
    root: the old model folder; the file paths are absolute paths below it."""
    out = _specs()
    for spec in out:
        for f in spec["files"]:
            f["path"] = os.path.join(os.path.abspath(os.path.expanduser(root)), f["path"])
    return out


def _specs() -> list[dict]:
    """The specs with file paths relative to the old model folder."""
    return [
        {
            "name": "driverguard_yolopx",
            "type": "yolopx",
            "description": "DriverGuard YOLOPX v2: object boxes (10 classes), drivable area and lane line masks "
                           "from one camera image.",
            "files": [{"role": "engine", "path": f"{JB}/engines/yolopx_v2_fp16.engine"},
                      {"role": "onnx", "path": f"{JB}/onnx/yolopx_v2.onnx"}],
            "input": {
                "tensors": [_t("image", [1, 3, 384, 640])],
                "size": {"width": 640, "height": 384},
                "colour_order": "RGB",
                # preprocess_yolopx (preprocess.py:36-71): letterbox on the BGR frame, then flip to RGB.
                "normalisation": {
                    "source_frame": "BGR uint8",
                    "resize": "letterbox: r = min(384/h, 640/w), resize to round(w*r) x round(h*r) with "
                              "cv2.INTER_AREA (skipped when the size does not change), pad centred with "
                              "(114, 114, 114) BORDER_CONSTANT",
                    "colour": "BGR -> RGB ([..., ::-1]) after the letterbox",
                    "scale": "divide by 255",
                    "mean": IMAGENET_MEAN,
                    "std": IMAGENET_STD,
                    "layout": "NCHW float32",
                },
            },
            "precision": "fp16",
            "cameras": {"permitted": [0, 1, 2, 3, 4, 5], "default": [0, 1, 2, 3, 4, 5]},
            "adapter": {"class_names": YOLOPX_CLASSES, "score_limit": 0.30,
                        "options": {"iou_thres": 0.45, "max_det": 300, "masks_cameras": [0]}},
            "outputs": {"tensors": [_t("det", [1, 5040, 15]), _t("da_seg", [1, 2, 384, 640]),
                                    _t("ll_seg", [1, 2, 384, 640])],
                        "kinds": ["boxes", "drivable_area", "lane_lines"]},
            "runtime": {"workers": 2, "max_fps_per_camera": 30},
            "build": {"shapes": "image:1x3x384x640", "precision": "fp16"},
            "date": "2026-05-11",
            "notes": "I/O tensors are FP32, FP16 only inside the engine. Parity with the PC reference: 33 of 34 "
                     "boxes match at IoU > 0.95, masks agree >= 0.9996 (docs/MODELS.md 3.8). The old stack ran it "
                     "on cam0 only: detection quality on side and rear views is not validated. Masks are made "
                     "for cam0 only (masks_cameras). The ONNX has a dynamic batch: build with the fixed shape.",
        },
        {
            "name": "driverguard_dtcp",
            "type": "dtcp",
            "description": "DriverGuard DTCP v1: 4 waypoints (0.5 s to 2.0 s, metres, ego frame) from the front "
                           "camera. Display only.",
            "files": [{"role": "engine", "path": f"{JB}/engines/dtcp_v1_fp16.engine"},
                      {"role": "onnx", "path": f"{JB}/onnx/dtcp_v1.onnx"}],
            "input": {
                "tensors": [_t("image", [1, 3, 256, 928]), _t("state", [1, 9]), _t("target_point", [1, 2])],
                "size": {"width": 928, "height": 256},
                "colour_order": "RGB",
                # preprocess_dtcp (preprocess.py:22-33): the caller converts BGR -> RGB first.
                "normalisation": {
                    "source_frame": "RGB uint8 (BGR frame converted to RGB before)",
                    "resize": "stretch (no letterbox) to 928x256 with cv2.INTER_LINEAR",
                    "scale": "divide by 255",
                    "mean": IMAGENET_MEAN,
                    "std": IMAGENET_STD,
                    "layout": "NCHW float32",
                },
            },
            "precision": "fp16",
            "cameras": {"permitted": [0], "default": [0]},
            "adapter": {"options": {"command": 2, "target": [0.0, 20.0], "ego_speed_mps": None}},
            "outputs": {"tensors": [_t("pred_wp", [1, 4, 2]), _t("mu", [1, 2]), _t("sigma", [1, 2]),
                                    _t("pred_speed", [1, 1])],
                        "kinds": ["trajectory"]},
            "runtime": {"workers": 1, "max_fps_per_camera": 10},
            "build": {"shapes": "image:1x3x256x928,state:1x9,target_point:1x2", "precision": "fp16"},
            "date": "2026-05-11",
            "notes": "The adapter publishes pred_wp only; mu, sigma and pred_speed are not published (rule R8). "
                     "Ego speed and route are not on the AGX: speed 0 m/s, command 2 (STRAIGHT) and target "
                     "(0, 20) m are assumed and inputsValid = false (docs/MODELS.md 4.4).",
        },
        {
            "name": "system1",
            "type": "system1",
            "description": "PyTorch only, not a TensorRT model. Not a TensorRT model: PyTorch only "
                           "(system1_deploy.pth), about 200 ms per inference; known defects B1-B5 in the old "
                           "runner. See docs/MODELS.md.",
            "files": [{"role": "weights", "path": f"{S1}/system1_deploy.pth"}],
            "input": {"size": {"width": 704, "height": 256}},
            "precision": "fp32",
            "cameras": {"permitted": [0, 1, 2, 3, 4, 5], "default": [0]},
            "outputs": {"kinds": ["trajectory"]},
            "date": None,
            "notes": "Trajectory scorer: ConvNeXt V2-Tiny + FPN backbone, FactorizedScorer head (v9e, epoch 12). "
                     "Input [1,6,3,256,704] (6 cameras), output 6 points at 0.5 s steps (docs/MODELS.md 7.1). "
                     "The old runner used bf16 autocast. No adapter for this type in this version.",
        },
        {
            "name": "sparsedrive_convnext_orin",
            "type": "sparsedrive_backbone",
            "description": "SparseDrive ConvNeXt V2-Tiny + FPN backbone engine for 6 surround cameras. Backbone "
                           "only: the det/map/motion head is not part of it.",
            "files": [{"role": "engine", "path": f"{SD}/convnext_backbone_fp16_orin.trt"},
                      {"role": "onnx", "path": f"{SD}/convnext_backbone_nchw_orin.onnx"}],
            "input": {"tensors": [_t("images", [6, 3, 450, 800])], "size": {"width": 800, "height": 450}},
            "precision": "fp16",
            "cameras": {"permitted": [0, 1, 2, 3, 4, 5], "default": [0, 1, 2, 3, 4, 5]},
            "outputs": {"tensors": [_t("feat_0", [6, 256, 112, 200]), _t("feat_1", [6, 256, 56, 100]),
                                    _t("feat_2", [6, 256, 28, 50]), _t("feat_3", [6, 256, 14, 25])],
                        "kinds": ["other"]},
            "date": None,
            "notes": "The engine output is wrong: cosine 0.39 against its ONNX (docs/MODELS.md section 7.2). The "
                     "head is PyTorch only. The ONNX (convnext_backbone_nchw_orin.onnx) has weights that do not "
                     "match best.pth. Calibration is a placeholder. No adapter for this type in this version.",
        },
    ]


def sha256_file(path: str) -> str:
    """sha256 of a file, read in 1 MiB blocks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def build(spec: dict) -> dict:
    """Full manifest dict (with schema, version, sha256 and date) from a spec. Raises OSError on a missing file."""
    files = [{"role": f["role"], "path": f["path"], "sha256": sha256_file(f["path"])} for f in spec["files"]]
    out = {"schema": mf.SCHEMA, "name": spec["name"], "version": VERSION}
    for k, v in spec.items():
        if k in ("name", "files"):
            continue
        out[k] = v
        if k == "description":
            out["files"] = files
    if not out.get("date"):
        out["date"] = _mtime_date(spec["files"][0]["path"])
    return out


class _Dumper(yaml.SafeDumper):
    """Block style, but short lists of plain values (shapes, cameras, mean) on one line."""


def _list(dumper: yaml.SafeDumper, data: list):
    flow = bool(data) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_Dumper.add_representer(list, _list)


def dump(d: dict) -> str:
    head = "# Model store manifest, written by tools/register_existing_models.py. Schema: controller/manifest.py.\n"
    return head + yaml.dump(d, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)


def register(store: str, spec: dict, force: bool, dry_run: bool) -> tuple[int, str]:
    """(exit code, one line) for one model."""
    folder = os.path.join(store, spec["name"], VERSION)
    path = os.path.join(folder, mf.MANIFEST)
    label = mf.key(spec["name"], VERSION)
    existed = os.path.exists(path)
    if existed and not force:
        return 2, f"{label}: KEPT {path} exists (use --force to overwrite)"
    try:
        d = build(spec)
    except OSError as e:
        return 1, f"{label}: ERROR file cannot be read: {e}"
    errs = mf.validate(yaml.safe_load(dump(d)), folder)
    if errs:
        return 1, f"{label}: ERROR manifest not valid: {'; '.join(errs)}"
    shas = " ".join(f"{f['role']}={f['sha256'][:16]}" for f in d["files"])
    if dry_run:
        return 0, f"{label}: DRY-RUN would write {path} ({len(d['files'])} files: {shas})"
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(dump(d))
    os.replace(tmp, path)
    m = mf.load(folder)
    if m.errors:
        return 1, f"{label}: ERROR written but load() reports: {'; '.join(m.errors)}"
    return 0, f"{label}: {'OVERWRITTEN' if existed else 'WRITTEN'} {path} ({len(d['files'])} files: {shas})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True,
                    help="the old model folder with jetson_bundle/, sparsedrive/run/ and system1/ "
                         "(for example /home/<user>/model)")
    ap.add_argument("--store", default="~/agx-models", help="model store folder (default ~/agx-models)")
    ap.add_argument("--force", action="store_true", help="overwrite existing manifests")
    ap.add_argument("--dry-run", action="store_true", help="check and print, write nothing")
    a = ap.parse_args(argv)
    store = os.path.abspath(os.path.expanduser(a.store))
    rc = 0
    for spec in specs(a.root):
        code, line = register(store, spec, a.force, a.dry_run)
        print(line, flush=True)
        rc = max(rc, code)
    return rc


if __name__ == "__main__":
    sys.exit(main())
