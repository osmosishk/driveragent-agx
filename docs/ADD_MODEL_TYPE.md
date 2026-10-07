# Add a model type (a new adapter)

The manifest field `type` selects the adapter of a model (`TYPES` in `controller/manifest.py`). An adapter does the
preprocessing (camera frame to engine inputs) and the postprocessing (engine outputs to the result). A version with a
type that has no adapter gets the state NO ADAPTER. It cannot be activated.

This document tells you how to add an adapter. To deploy a version of a type that has an adapter, read
`docs/DEPLOY_MODEL.md`.

Read these files first:

| File | Content |
|---|---|
| `infer/models/adapters/base.py` | The base class `Adapter`, the result schema, `nv12_to_bgr`, `nv12_to_rgb`, `MASK_ENCODING`. |
| `infer/models/adapters/yolopx_v2.py` | An adapter with boxes and two masks. |
| `infer/models/adapters/dtcp_v1.py` | An adapter with a trajectory and constant extra inputs (state vector). |
| `proto/agx_infer.capnp` | `AgxPerceptionResult`: the message that DA01 gets. |
| `controller/manifest.py` | `TYPES`, `OUTPUT_KINDS` and the manifest checks. |
| `tools/model_check.py` | The checks that a version must pass before it is READY. |

## 1. Write the adapter module

Make the file `infer/models/adapters/<module>.py`. Use a lower-case module name with a version number, for example
`segnet_v1.py`. `get_adapter_class()` (`infer/models/adapters/__init__.py`) accepts only `a-z`, `0-9` and `_`.

The module must have:

| Name | Content |
|---|---|
| `ADAPTER_CLASS` | The adapter class (a subclass of `Adapter`). |
| `NAME` (class attribute) | The module name, for example `"segnet_v1"`. |
| `ENGINE_INPUT_SHAPES` (class attribute) | `{input name: shape}` of the engine inputs, for example `{"image": (1, 3, 384, 640)}`. The base class compares it with the engine (a dynamic dimension `-1` counts as `1`). |
| `ENGINE_OUTPUTS` (class attribute) | The names of the engine outputs that the adapter reads. The base class refuses an engine without one of these outputs. The runner gives `postprocess` ONLY these outputs (`infer/runner.py` `adapter_outputs`). |
| `preprocess(self, frame)` | Returns `(inputs, ctx)`: `inputs` is `{input name: numpy array}` in the engine shape, `ctx` is a dict for `postprocess`. |
| `postprocess(self, outputs, frame, ctx)` | Returns the result dict (Section 2). |

The frame (`infer/ingest/frame_store.Frame`) has `cam`, `seq`, `width`, `height` and `nv12` (NV12, BT.601 limited
range, shape `height * 3 / 2` x `width`). Use `nv12_to_bgr(frame)` or `nv12_to_rgb(frame)` of `base.py` to get an
image. The adapter gets its options in `self.options`: the manifest `adapter.options`, plus `conf_thres` (from
`adapter.score_limit`) and `class_names` (from `adapter.class_names`).

Rules for the adapter:

1. Keep no state from one frame to the next frame. All worker threads of a model use one adapter object.
2. Do not write to shared arrays in `preprocess` or `postprocess`. Make constant inputs one time in `__init__`
   (see `dtcp_v1.py` `_state`).
3. Raise `ValueError` with a clear text for a bad option in `__init__` and for a bad output in `postprocess`.
4. Do not import TensorRT in the adapter. The engine is given to `__init__`.

Example skeleton:

```python
"""SEGNET v1 adapter (my_segnet): drivable-area mask from one camera image."""
from __future__ import annotations

import cv2
import numpy as np

from infer.models.adapters.base import MASK_ENCODING, Adapter, nv12_to_rgb
from infer.models.legacy.driverguard.mask_codec import encode_rle


class SegnetV1Adapter(Adapter):
    NAME = "segnet_v1"
    ENGINE_INPUT_SHAPES = {"image": (1, 3, 384, 640)}
    ENGINE_OUTPUTS = ("seg",)

    def preprocess(self, frame) -> tuple[dict, dict]:
        rgb = cv2.resize(nv12_to_rgb(frame), (640, 384), interpolation=cv2.INTER_AREA)
        x = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        return {"image": np.ascontiguousarray(x)}, {}

    def postprocess(self, outputs: dict, frame, ctx: dict) -> dict:
        w, h = int(frame.width), int(frame.height)
        m = (outputs["seg"][0].argmax(0) == 1).astype(np.uint8)
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
        return {"detections": [], "trajectory": None,
                "masks": [{"name": "drivable_area", "width": w, "height": h, "encoding": MASK_ENCODING,
                           "data": encode_rle(m)}]}


ADAPTER_CLASS = SegnetV1Adapter
```

## 2. The result schema

`postprocess` returns one dict with the three keys. Use `Adapter.empty_result()` when there is no result.

```text
{"detections": [{"class_id": int, "class_name": str, "score": float 0..1,
                 "x1": float, "y1": float, "x2": float, "y2": float, "track_id": int (0 = no track)}],
 "trajectory": None | {"frame": str, "points": [(x, y, t_s)], "inputs_valid": bool, "note": str},
 "masks": [{"name": str, "width": int, "height": int, "encoding": str, "data": bytes}]}
```

- Box pixels are in the frame size: `frame.width` x `frame.height`, x to the right, y down.
- `trajectory.frame` names the coordinate frame in full (axes, units, origin). `t_s` is the time after the frame in
  seconds. Set `inputs_valid` to `False` when a model input was not real (for example an assumed speed). Put the
  assumed inputs and the words "display only, not for control" into `note`.
- A mask is `width` x `height` values 0 or 1, row by row. Encode it with `encode_rle` of
  `infer/models/legacy/driverguard/mask_codec.py`. Its encoding is `MASK_ENCODING`
  (`"rle-u16le-count-u8-value-rowmajor"`). Make the mask in the frame size.
- These fields go into `AgxPerceptionResult` of `proto/agx_infer.capnp` (`detections`, `trajectory`, `masks`).
  Other keys are not sent.

## 3. Output kinds and result fields

The manifest field `outputs.kinds` tells the persons and the dashboards what the model gives. Use these values
(`OUTPUT_KINDS` in `controller/manifest.py`):

| Kind | Result field | Notes |
|---|---|---|
| `boxes` | `detections` | One entry per box. |
| `drivable_area` | `masks`, `name: "drivable_area"` | |
| `lane_lines` | `masks`, `name: "lane_line"` | The kind is plural. The mask name is singular. |
| `trajectory` | `trajectory` | `points` in the frame named by `trajectory.frame`. |
| `other` | none | The result schema has no field for it. DA01 gets nothing. |

## 4. Rule R8: no control values

An adapter never returns control values: no `throttle`, `steer`, `brake`, `mu`, `sigma`, `pred_speed`. The results
are for display only.

- Put only the outputs that you need for perception or display into `ENGINE_OUTPUTS`. The runner gives the adapter
  only these outputs. Example: `dtcp_v1.py` lists only `pred_wp`; `mu`, `sigma` and `pred_speed` never reach
  `postprocess`.
- Do not calculate a control value from an output.
- The capnp message has no field for control values. Do not add one.

## 5. Add the type

1. Add the type to `TYPES` in `controller/manifest.py`: `TYPES = {"yolopx": "yolopx_v2", "dtcp": "dtcp_v1",
   "segnet": "segnet_v1"}` (type: adapter module name).
2. `tools/model_check.py` `frame_camera()` uses camera 0 for `yolopx` and the first default camera for all other
   types. Change it only when the new type needs a different test camera.
3. Restart agx-dashboard (the controller and the checks use `TYPES`) and agx-infer (it imports the adapter). Only the
   owner or the main deploy does these restarts.
4. Deploy a version of the new type (`docs/DEPLOY_MODEL.md`). Its state goes from NO ADAPTER to NEEDS BUILD or
   REGISTERED.

A version that was deployed before the type had an adapter needs no new deploy: the catalog reads `TYPES` again.

## 6. Tests to add

| Test | File | What it shows |
|---|---|---|
| Adapter parity | `tests/test_adapters_parity.py` (add a test) | `preprocess` gives the same inputs as the reference code of the model (max abs difference < 1e-6). `postprocess` gives the same boxes, masks or points as the reference code on the same engine outputs. Use a stored sample image and, if there is one, a reference output file. |
| R8 | the parity test | The result has no control value keys (`FORBIDDEN` in `tests/test_adapters_parity.py`). |
| Model check on a real engine | `tests/test_model_check.py` (add a test like `test_real_dtcp_check`) | `tools/model_check.py` on a version folder with the real engine passes all checks: `sha256`, `engine_load`, `io_match`, `adapter`, `gpu_memory`, `inference`. Skip the test when the engine file does not exist. |
| Manifest | `tests/test_model_store.py` | The new type is in `TYPES` and a manifest of the type gives no errors. |

Run the tests on AGX02 (the GPU tests need the engine):

```bash
cd ~/driveragent-agx
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_adapters_parity.py tests/test_model_check.py tests/test_model_store.py
```

## 7. What DA01 draws

The DA01 HMI draws the AGX results on the camera views when the setting "Show AGX results" is on (off by default;
`rk/hmi/driveragent_hmi/agx_overlay.py` in the DA01 repository). It draws:

| Result | Drawing |
|---|---|
| `detections` | A box in the colour of `class_id` (10 colours, `class_id` modulo 10) and the label `class_name score` (labels only on large views). |
| `masks` named `drivable_area` | A green transparent area. |
| `masks` named `lane_line` | A red transparent area. |
| `trajectory` | A yellow line with points, and the text "DISPLAY ONLY", plus "inputs assumed" when `inputs_valid` is false (only on large views). |

- DA01 draws only the two mask names above, and only with the encoding `rle-u16le-count-u8-value-rowmajor`. It
  ignores other masks.
- DA01 draws the trajectory with a fixed virtual perspective, not a calibrated projection. It reads `x` as lateral
  (metres, right is positive) and `y` as forward (metres), as `dtcp_v1.py` gives them. A point with less than 0.2 m
  forward is not drawn. Give a trajectory in this frame, or DA01 draws it at a wrong place.
- A result of a simulated frame gets the text "SIMULATED".
- A new kind of drawing needs a change on DA01 (`agx_overlay.py`) and, for a new result field, an additive change of
  `proto/agx_infer.capnp` (new field with the next ordinal, new `schemaVersion`, tell the RK side).
