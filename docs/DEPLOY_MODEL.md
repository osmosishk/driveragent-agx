# Deploy a model version to AGX02

This document tells you how to put a new model version into the model store of AGX02. The store is
`~/agx-models` on AGX02. It is not in git.

A deploy only adds a version to the store. A deploy does not build an engine. A deploy does not activate the model.
You build and activate the version after the deploy, with the API (`docs/MODEL_CONTROL_API.md`) or the dashboards.

To add a model of a new type (a type without an adapter), read `docs/ADD_MODEL_TYPE.md` first.

## 1. The tools

| Tool | Where | What it does |
|---|---|---|
| `tools/deploy_model.sh <package dir>` | AGX02 or a workstation | Copies the package to AGX02 (from a workstation) and runs the deploy of `tools/model_store_cli.py`. |
| `python -m tools.model_store_cli validate <package dir>` | AGX02 | Checks a package. It changes nothing. |
| `python -m tools.model_store_cli deploy <package dir>` | AGX02 | Checks the package and puts it into the store. |

Run the Python tool from the repository folder:

```bash
cd ~/driveragent-agx
.venv/bin/python -m tools.model_store_cli validate ~/model-packages/driverguard_yolopx-2
```

Options:

| Option | Tool | Default | Meaning |
|---|---|---|---|
| `--store DIR` | both | `~/agx-models` | The model store. It must exist. |
| `--user U` | both | `$USER` (the script adds `@<hostname>`) | The person in the audit line. |
| `--host H` | `deploy_model.sh` | `$AGX_HOST`, else none | The ssh host of the AGX (for example `agx02`). |
| `--repo DIR` | `deploy_model.sh` | `~/driveragent-agx` | The repository folder on the AGX. |
| `--local` / `--remote` | `deploy_model.sh` | by host | `--local` runs the deploy on this computer. `--remote` copies to `--host`. Without a host (no `--host`, no `AGX_HOST`), the script uses `--local`. |
| `--staged DIR` | `model_store_cli deploy` | - | Deploys a package that is already in `<store>/_incoming/`. `deploy_model.sh` uses it. |

Exit codes: `0` = valid or deployed. `1` = a problem: the tool writes each problem in a `PROBLEM:` line.
`2` = a wrong command line (`model_store_cli` only).

## 2. The package layout

A package is one folder. Give it any name. Example:

```text
driverguard_yolopx-2/
  manifest.yaml     the description of the version (Section 3)
  model.onnx        the files of the manifest (any names; sub-folders are permitted)
```

After the deploy, the store has the same files in `<store>/<name>/<version>/`:

```text
~/agx-models/driverguard_yolopx/2/
  manifest.yaml
  model.onnx
  driverguard_yolopx_2_fp16.engine   added by the build on this AGX (controller/builder.py)
  build.json, build.log              added by the build
```

## 3. The manifest fields

The schema is in [`controller/manifest.py`](../controller/manifest.py). The function `validate()` in that file is the
reference. Write the manifest in YAML.

| Field | Needed | Value |
|---|---|---|
| `schema` | yes | `agx-model-manifest/1` |
| `name` | yes | 1 to 48 characters `a-z`, `0-9`, `_`. Do not start with `_` (the store uses `_` folders). |
| `version` | yes | A quoted string of 1 to 32 characters `A-Z`, `a-z`, `0-9`, `.`, `_`, `-`. Write `"2"`, not `2`. |
| `type` | yes | Selects the adapter (`TYPES` in `controller/manifest.py`: `yolopx`, `dtcp`). A type without an adapter gives the state NO ADAPTER. |
| `description` | yes | Text. |
| `files` | yes | A list of `{role, path, sha256}`. `role` is `engine`, `onnx`, `weights` or `other`. Not more than one `engine` and one `onnx`. `path` is relative to the package folder. `sha256` is 64 lower-case hexadecimal characters. The list can be empty. |
| `input.tensors` | yes (1) | A list of `{name, shape, dtype}`. `shape` is a list of integers. |
| `input.size`, `input.colour_order`, `input.normalisation` | no | Information for persons (the adapter does the preprocessing). |
| `outputs.tensors` | yes (1) | A list of `{name, shape, dtype}`. |
| `outputs.kinds` | yes | A list of `boxes`, `drivable_area`, `lane_lines`, `trajectory`, `other`. |
| `precision` | yes | `fp16`, `fp32`, `int8` or `mixed`. |
| `cameras.permitted` | yes | A list of camera ids `0` to `5`. |
| `cameras.default` | yes | A list. Each id must be in `cameras.permitted`. |
| `adapter.class_names` | no | The class names of the boxes. |
| `adapter.score_limit` | no | `0` to `1`. The adapter gets it as `conf_thres`. |
| `adapter.options` | no | Other adapter parameters (for example `iou_thres`, `max_det`, `masks_cameras`). |
| `runtime.workers` | no | `1` to `4` (default `1`). |
| `runtime.max_fps_per_camera` | no | More than `0` and not more than `30` (default `30`). |
| `build.shapes` | no | The `trtexec --shapes` value, for example `image:1x3x384x640`. Use it for an ONNX file with a dynamic batch. |
| `build.precision` | no | The precision of the build (default: `precision`). |
| `date` | yes | `YYYY-MM-DD`. |
| `notes` | no | Text. |

(1) Needed when the type has an adapter.

## 4. The rules

1. Each file of the manifest must have a relative path in the package folder. The tool refuses an absolute path, a
   path that starts with `~`, and a path with `..`.
2. Each file of the manifest must be in the package. Its sha256 must agree with the manifest. The tool calculates the
   sha256 two times: in the package, and again in the copy in the store.
3. The package must not contain symbolic links. Put the real files into the package.
4. The package must not contain `build.json` or `build.log`. The build on this AGX writes these files.
5. A version is never overwritten and never deleted (owner rule M2). When `<store>/<name>/<version>` exists, the tool
   refuses the deploy. Give the package a new version.
6. The tool refuses a package that gets the state FAILED in the catalog (for example: no engine file and no ONNX
   file). Such a version cannot be removed from the store again.
7. After the deploy, the files in the store are read-only (`r--r--r--`). The version folder stays writable for the
   build.

## 5. What the deploy does

`model_store_cli deploy <package dir>` does these steps:

1. It checks the package (Section 4). It checks the manifest for the folder `<store>/<name>/<version>`.
2. It refuses the deploy when `<store>/<name>/<version>` exists.
3. It copies the package to `<store>/_incoming/<name>-<version>-<random>/`.
4. It calculates the sha256 of each file in the copy again.
5. It makes the files read-only.
6. It renames the copy to `<store>/<name>/<version>` (one `os.rename`: the catalog never sees half a version).
7. It writes one line in `<store>/_state/audit.jsonl`: source `command-line`, action `deploy`, result `ok`,
   `refused` or `failed`, and the reason. `GET /api/models/events` shows this line.
8. It writes the expected state and the next step.

Only one deploy runs at a time in a store (a lock on `<store>/_incoming/.deploy.lock`).

`tools/deploy_model.sh` on a workstation does these steps:

1. It refuses a package with a symbolic link.
2. It stops when `<store>/<name>/<version>` exists on the host (before the copy).
3. It copies the package with `scp -r` to `<host>:<store>/_incoming/<name>-<version>-<random>/`.
4. It runs `model_store_cli deploy --staged <that folder>` on the host with ssh.

When the deploy of a staged package is refused, the package stays in `_incoming` for inspection. The tool writes the
`rm -r` command that removes it.

The states after the deploy:

| The package has | State in the catalog | Next step |
|---|---|---|
| An ONNX file, no engine | NEEDS BUILD | Build the engine. Then the checks run. |
| An engine file | REGISTERED | The checks run. Then the state is READY or FAILED. |
| A type without an adapter | NO ADAPTER | Add an adapter (`docs/ADD_MODEL_TYPE.md`). |

## 6. Full example: YOLOPX as driverguard_yolopx version "2"

This example makes a second version of YOLOPX from the same ONNX file. Version `1` uses the old engine in
`/home/tonyho/model`. Version `2` gets its own engine, built on this AGX.

### 6.1 Make the package (on AGX02)

```bash
mkdir -p ~/model-packages/driverguard_yolopx-2
cd ~/model-packages/driverguard_yolopx-2
cp /home/tonyho/model/jetson_bundle/onnx/yolopx_v2.onnx model.onnx
cp ~/agx-models/driverguard_yolopx/1/manifest.yaml manifest.yaml
sha256sum model.onnx
```

The output of `sha256sum`:

```text
3a49f4ebe346bea4e54d30a01b727c8fd27bfd3ef3486f39ba2698679683b232  model.onnx
```

Do not change the files in `/home/tonyho/model`. The commands above only read them.

### 6.2 Edit manifest.yaml

Make two changes in `manifest.yaml`:

1. Change `version: '1'` to `version: '2'`.
2. Replace the `files` list with only `model.onnx` (a relative path) and its sha256.

Keep all other fields (`input`, `outputs`, `adapter`, `cameras`, `runtime`, `build`, ...). The full manifest:

```yaml
# Model store manifest. Schema: controller/manifest.py.
schema: agx-model-manifest/1
name: driverguard_yolopx
version: '2'
type: yolopx
description: 'DriverGuard YOLOPX v2: object boxes (10 classes), drivable area and lane line masks from one camera image.'
files:
- role: onnx
  path: model.onnx
  sha256: 3a49f4ebe346bea4e54d30a01b727c8fd27bfd3ef3486f39ba2698679683b232
input:
  tensors:
  - name: image
    shape: [1, 3, 384, 640]
    dtype: FLOAT
  size:
    width: 640
    height: 384
  colour_order: RGB
  normalisation:
    source_frame: BGR uint8
    resize: 'letterbox: r = min(384/h, 640/w), resize to round(w*r) x round(h*r) with cv2.INTER_AREA (skipped when the size
      does not change), pad centred with (114, 114, 114) BORDER_CONSTANT'
    colour: BGR -> RGB ([..., ::-1]) after the letterbox
    scale: divide by 255
    mean: [0.485, 0.456, 0.406]
    std: [0.229, 0.224, 0.225]
    layout: NCHW float32
precision: fp16
cameras:
  permitted: [0, 1, 2, 3, 4, 5]
  default: [0, 1, 2, 3, 4, 5]
adapter:
  class_names:
  - person
  - rider
  - car
  - bus
  - truck
  - bike
  - motor
  - traffic light
  - traffic sign
  - train
  score_limit: 0.3
  options:
    iou_thres: 0.45
    max_det: 300
    masks_cameras: [0]
outputs:
  tensors:
  - name: det
    shape: [1, 5040, 15]
    dtype: FLOAT
  - name: da_seg
    shape: [1, 2, 384, 640]
    dtype: FLOAT
  - name: ll_seg
    shape: [1, 2, 384, 640]
    dtype: FLOAT
  kinds:
  - boxes
  - drivable_area
  - lane_lines
runtime:
  workers: 2
  max_fps_per_camera: 30
build:
  shapes: image:1x3x384x640
  precision: fp16
date: '2026-05-11'
notes: 'I/O tensors are FP32, FP16 only inside the engine. Parity with the PC reference: 33 of 34 boxes match at IoU > 0.95,
  masks agree >= 0.9996 (docs/MODELS.md 3.8). The old stack ran it on cam0 only: detection quality on side and rear views
  is not validated. Masks are made for cam0 only (masks_cameras). The ONNX has a dynamic batch: build with the fixed shape.'
```

### 6.3 Check the package

```bash
cd ~/driveragent-agx
.venv/bin/python -m tools.model_store_cli validate ~/model-packages/driverguard_yolopx-2
```

Expected output:

```text
VALID: driverguard_yolopx@2 -> /home/tonyho/agx-models/driverguard_yolopx/2
Expected state after deploy: NEEDS BUILD (no engine yet: build one from the ONNX file on this AGX)
```

### 6.4 Deploy the package

On AGX02:

```bash
cd ~/driveragent-agx
tools/deploy_model.sh ~/model-packages/driverguard_yolopx-2
```

From a workstation (with an ssh connection to `agx02` and a copy of this repository): make the same package on the
workstation, then run:

```bash
tools/deploy_model.sh ./driverguard_yolopx-2 --host agx02
```

Expected output (on AGX02; `<random>` is 8 hexadecimal characters):

```text
deploy_model: local deploy into ~/agx-models
copy /home/tonyho/model-packages/driverguard_yolopx-2 -> /home/tonyho/agx-models/_incoming/driverguard_yolopx-2-<random>
DEPLOYED driverguard_yolopx@2 -> /home/tonyho/agx-models/driverguard_yolopx/2
Expected state in the catalog: NEEDS BUILD (no engine yet: build one from the ONNX file on this AGX)
Next step: build the engine on this AGX (build action of driverguard_yolopx@2: docs/MODEL_CONTROL_API.md or the dashboards), then wait for READY and activate it.
```

When you do the deploy a second time, the tool refuses it:

```text
PROBLEM: /home/tonyho/agx-models/driverguard_yolopx/2 exists: a version is never overwritten (owner rule M2). Give the package a new version
REFUSED: nothing was changed in the store.
```

### 6.5 Build, check and activate

The deploy is complete. The catalog (`GET /api/models/catalog`, the AGX dashboard, the DA01 rk console) shows
`driverguard_yolopx@2` with the state NEEDS BUILD.

1. Start the build of `driverguard_yolopx@2`: the build action (`POST /api/models/driverguard_yolopx/2/build`,
   `docs/MODEL_CONTROL_API.md` Section 3) or the build button of a dashboard. The state is BUILDING.
   A build uses the GPU for some minutes: the active models give fewer results per second during the build.
2. After the build, the controller runs the checks. The state is REGISTERED, then READY (or FAILED with a reason).
3. Activate the version: the activate action (`POST /api/models/driverguard_yolopx/2/activate`,
   `docs/MODEL_CONTROL_API.md` Section 3) or the activate button of a dashboard. The state is ACTIVE.

## 7. If a deploy is refused

| Message | Cause | Do this |
|---|---|---|
| `sha256 does not agree` | The file is not the file of the manifest. | Calculate the sha256 again (`sha256sum`) and write it in the manifest. |
| `the path must be relative` / `no '..'` | The path is absolute or goes out of the package. | Put the file into the package. Write the path relative to the package folder. |
| `the file does not exist in the package` | A file of the manifest is missing. | Copy the file into the package. |
| `exists: a version is never overwritten` | The version is in the store. | Give the package a new version. |
| `would show this version as FAILED` | No engine file and no ONNX file. | Add the ONNX file or the engine file to the package and the manifest. |
| `the store ... does not exist` | A wrong `--store`. | Give the correct store folder. |
| `version must be a quoted string` | `version: 2` in the YAML. | Write `version: "2"`. |
