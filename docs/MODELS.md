# Models on the AGX

| Item | Value |
|---|---|
| Date | 2026-10-05 |
| Machine | agx02. `/proc/device-tree/model`: "NVIDIA Jetson AGX Orin Developer Kit". RAM: MemTotal 64,349,240 kB. L4T R36.4.7. Power mode MAXN (`nvpmodel -q`). |
| TensorRT | 10.3.0 |
| CUDA | 12.6 (`/usr/local/cuda` -> `/usr/local/cuda-12.6`, version 12.6.11) |
| Python env | `/home/tonyho/driveragent-agx/.venv` (tensorrt 10.3.0, cv2 4.10.0, numpy 1.26.4: read-only check tonight) |
| Sources | `docs/research/T1_*.md`, `docs/research/engines_io.txt`, `proto/agx_infer.capnp`, `common/framelink.py`, read-only checks named below |

All facts come from the research files or from read-only checks. Code facts have `path:line` references.

Short paths have these roots:

| Short path (section) | Root |
|---|---|
| `preprocess.py`, `yolopx_postprocess.py`, `trt_runner.py`, `beta_mode.py` | `/home/tonyho/model/jetson_bundle/jetson_runtime/` |
| `README.md`, `docs/YOLOPX_deployment.md`, `docs/DTCP_deployment.md`, `docs/jetson_deployment_workplan.md`, `source/...` | `/home/tonyho/model/jetson_bundle/` |
| `runner.py`, `camera_reader.py`, `mask_codec.py`, `runner/ego_state.py` | `/home/tonyho/model/driverguard/runner/` (`runner/ego_state.py`: `/home/tonyho/model/driverguard/`) |
| `run.py` (sections 3, 4) | `/home/tonyho/model/driverguard/` |
| `start.py`, `startmodel.sh`, `message.capnp`, `visionipc/...`, `ui/...`, `main_camera.py`, `logger/...`, `calibration/...` | `/home/tonyho/driveragent/` (`main_camera.py`: `ui/newwidgets/`; `message.capnp`: `message/`) |
| `rk/...`, `rk.toml`, `camera_map.ini` | `/home/tonyho/driveragent-agx/ref/driveragent-hmi/` (`rk.toml`: `rk/config/`; `camera_map.ini`: `rk/boards/rk3588-da01/vehicle/`) |
| `run.py`, `run_system1.py`, `runner/runner.py`, `DEPLOY_INSTRUCTIONS.md` (section 7.1) | `/home/tonyho/model/system1/` |
| `run/...`, `OPTIMIZATION_GUIDE.md`, `install.sh` (section 7.2, 7.5) | `/home/tonyho/model/sparsedrive/` |
| `DEPLOY_STAGE2.md`, `run_stage2.py` (section 7.3) | `/home/tonyho/model/stage2/` |
| `lib/...` (section 7.4) | `/home/tonyho/model/yolopx/YOLOPX/` |

## 1. Test evidence (T1): engine I/O read from the real files

Test command (run from `/home/tonyho/driveragent-agx`):

```
PYTHONPATH=. .venv/bin/python -m tools.inspect_engines --scan /home/tonyho/model
```

The tool deserializes each engine in its own subprocess (`tools/inspect_engines.py:1-7`). It scans the `--scan` folders (here `/home/tonyho/model`) for `.engine`, `.trt` and `.plan` files. It has no default folder.

Real output, copied verbatim from `docs/research/engines_io.txt`:

```
##### /home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine
size 55987852 B  mtime 2026-05-11 16:24:03  sha256[:16] 1071ea90213eddc2
TensorRT 10.3.0  load OK  match True
layers 77  profiles 1  device_memory 11403264 B
  INPUT  image          (1, 3, 256, 928)       FLOAT
  INPUT  state          (1, 9)                 FLOAT
  INPUT  target_point   (1, 2)                 FLOAT
  OUTPUT pred_wp        (1, 4, 2)              FLOAT
  OUTPUT mu             (1, 2)                 FLOAT
  OUTPUT sigma          (1, 2)                 FLOAT
  OUTPUT pred_speed     (1, 1)                 FLOAT
##### /home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine
size 70643388 B  mtime 2026-05-11 16:22:53  sha256[:16] 3412bafa057a3a76
TensorRT 10.3.0  load OK  match True
layers 397  profiles 1  device_memory 43450368 B
  INPUT  image          (1, 3, 384, 640)       FLOAT
  OUTPUT det            (1, 5040, 15)          FLOAT
  OUTPUT da_seg         (1, 2, 384, 640)       FLOAT
  OUTPUT ll_seg         (1, 2, 384, 640)       FLOAT
##### /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16.trt
size 63330348 B  mtime 2026-04-02 08:21:20  sha256[:16] 653ec9617d4d6613
TensorRT 10.3.0  load OK  match False
  message: WARNING: Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.
layers 318  profiles 1  device_memory 487065600 B
  INPUT  images         (6, 3, 450, 800)       FLOAT
  OUTPUT feat_0         (6, 256, 112, 200)     FLOAT
  OUTPUT feat_1         (6, 256, 56, 100)      FLOAT
  OUTPUT feat_2         (6, 256, 28, 50)       FLOAT
  OUTPUT feat_3         (6, 256, 14, 25)       FLOAT
##### /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt
size 63276916 B  mtime 2026-04-03 21:10:53  sha256[:16] 3d0ece003f5e61a4
TensorRT 10.3.0  load OK  match False
  message: WARNING: Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.
layers 415  profiles 1  device_memory 383846400 B
  INPUT  images         (6, 3, 450, 800)       FLOAT
  OUTPUT feat_0         (6, 256, 112, 200)     FLOAT
  OUTPUT feat_1         (6, 256, 56, 100)      FLOAT
  OUTPUT feat_2         (6, 256, 28, 50)       FLOAT
  OUTPUT feat_3         (6, 256, 14, 25)       FLOAT
##### /home/tonyho/model/sparsedrive/run/resnet_backbone_fp16_orin.trt
size 54297884 B  mtime 2026-04-03 18:19:35  sha256[:16] d90f93dc43c1d62d
TensorRT 10.3.0  load OK  match False
  message: WARNING: Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.
layers 81  profiles 1  device_memory 237619200 B
  INPUT  images         (6, 3, 450, 800)       FLOAT
  OUTPUT feat_0         (6, 256, 113, 200)     FLOAT
  OUTPUT feat_1         (6, 256, 57, 100)      FLOAT
  OUTPUT feat_2         (6, 256, 29, 50)       FLOAT
  OUTPUT feat_3         (6, 256, 15, 25)       FLOAT
```

Since 2026-10-07 the rule for `match` is different (owner decision, `common/trt_compat.py`): `match True` when
the engine loads with the installed TensorRT AND its build device is an Orin GPU. TensorRT loads an engine that
was built without hardware compatibility only on a GPU with the same compute capability as the build GPU, so such
an engine that loads on this Orin was built on an Orin GPU (sm87). The TensorRT device warning is information only
(field `trt_device_warning`). Real output of the same command on 2026-10-07 (load lines only):

```
##### /home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine
TensorRT 10.3.0  load OK  match True  build device Orin GPU (sm87)
  device warning (information only): WARNING: Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.
##### /home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine
TensorRT 10.3.0  load OK  match True  build device Orin GPU (sm87)
  device warning (information only): WARNING: Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.
##### /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16.trt
TensorRT 10.3.0  load OK  match True  build device Orin GPU (sm87)
  device warning (information only): WARNING: Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.
##### /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt
TensorRT 10.3.0  load OK  match True  build device Orin GPU (sm87)
  device warning (information only): WARNING: Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.
##### /home/tonyho/model/sparsedrive/run/resnet_backbone_fp16_orin.trt
TensorRT 10.3.0  load OK  match True  build device Orin GPU (sm87)
  device warning (information only): WARNING: Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.
```

Notes:
- Exactly 5 raw plan files exist on `/`. The critic scanned every file of 200 KB or more for the plan header (T1_critic.md, G1).
- `/home/tonyho/model/driverguard/engines/` holds only 2 symlinks to the `jetson_bundle/engines/` files (T1_driverguard.md, section 1). The tool lists each real file once.
- A 6th engine is embedded in `/home/tonyho/model/sparsedrive/run/convnext_backbone_trt.ep`. It is not a plan file, so the tool does not list it. See section 7.5.
- `/data` is `drwx------ root`. The research could not read it without sudo. Engines there are unknown.
- The "different models of devices" warning (2026-10-07 check; strong evidence, not a proof, because TensorRT
  is closed source): a plan stores the total memory of its build device (plan bytes 265-272: 64,349,240 kB for
  the two DriverGuard plans, 64,349,236 kB for the three SparseDrive plans). TensorRT writes the warning when the
  total memory of the current boot is different. MemTotal changes at each boot (64,349,240 kB in the boot of
  2026-09-25, 64,349,244 kB since the boot of 2026-10-06). It is not a defect (owner decision 2026-10-07): the
  warning is information only and does not change `match`. A reboot or a rebuild does not reliably remove it.

## 2. Summary

### 2.1 Models in `config/models.yaml`

Source: `config/models.yaml:17-61`. Decisions: `docs/NIGHT_LOG.md` 21:26.

| Model (config name) | Engine file | Size (B) | sha256[:16] | Loads on TRT 10.3.0 | Runnable pipeline | Cameras | Proposed state | Reason |
|---|---|---|---|---|---|---|---|---|
| `driverguard_yolopx` | `/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine` | 70,643,388 | `3412bafa057a3a76` | Yes. match True (built on an Orin GPU). Device warning since the 2026-10-06 boot: information only. | Yes | Detections: cam0-cam5. Masks: cam0 only. | **enabled** | Correct output (parity with reference, section 3.8). Old stack ran it on cam0 only. Detection quality on side and rear views is NOT validated. |
| `driverguard_dtcp` | `/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine` | 55,987,852 | `1071ea90213eddc2` | Yes. match True (built on an Orin GPU). Device warning since the 2026-10-06 boot: information only. | Yes, with assumed inputs | cam0 only | **enabled** | Waypoints for display only. Ego speed and route are not available: `inputsValid = false` (section 4). |
| `system1` | none (no engine exists) | – | – | No engine | No (PyTorch only) | cam0-cam5 | **disabled** (state `OFF`) | Not a TensorRT model. About 192-213 ms per inference. Bugs B1-B5 in the old runner (section 7.1). |
| `sparsedrive_convnext_orin` | `/home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt` | 63,276,916 | `3d0ece003f5e61a4` | Loads. match True (built on an Orin GPU). Device warning: information only. | No | cam0-cam5 | **disabled** | Wrong features (cosine 0.39 against its ONNX). Head is PyTorch only (0.5-0.7 FPS). Calibration is a placeholder (section 7.2). |

### 2.2 Engines on disk that are NOT in the config

The dashboard lists these separately.

| Engine | Size (B) | sha256[:16] | Loads on TRT 10.3.0 | Why not in config |
|---|---|---|---|---|
| `/home/tonyho/model/sparsedrive/run/convnext_backbone_fp16.trt` | 63,330,348 | `653ec9617d4d6613` | Loads. match True (built on an Orin GPU). Device warning: information only. | Wrong features: cosine 0.121 against `convnext_nchw_backbone.onnx`. |
| `/home/tonyho/model/sparsedrive/run/resnet_backbone_fp16_orin.trt` | 54,297,884 | `d90f93dc43c1d62d` | Loads. match True (built on an Orin GPU). Device warning: information only. | Correct (cosine 1.00000 against its ONNX). No head weights for it: `best.pth` has 0 `resnet.*` keys. |
| Engine embedded in `/home/tonyho/model/sparsedrive/run/convnext_backbone_trt.ep` | 65,931,356 (decoded) | `.ep` file: `e28b0f0ae8612ebc` | Deserializes with the device warning (critic check) | Not a plan file. Output is 100% NaN. |

### 2.3 Other weights: not models for this node

| Item | Path | State | Reason |
|---|---|---|---|
| stage2 | `/home/tonyho/model/stage2/checkpoints/stage2_convnext_v2_lr4/best.pth`, `latest.pth` | not listed | Both checkpoints are truncated zip files. They do not load. No TRT, no ONNX. |
| YOLOPX v1 (epoch-195) | `/home/tonyho/model/yolopx/YOLOPX/weights/epoch-195.pth` | not listed | PyTorch only. 1 class. Superseded by `yolopx_v2_fp16.engine`. |

Listed for completeness. Details are in section 7.

## 3. `driverguard_yolopx`

### 3.1 Engine I/O

| Dir | Name | Shape | Type | Content |
|---|---|---|---|---|
| INPUT | `image` | (1, 3, 384, 640) | FLOAT (FP32, kLINEAR) | Letterboxed RGB, ImageNet-normalized, NCHW |
| OUTPUT | `det` | (1, 5040, 15) | FLOAT | Decoded boxes (section 3.5) |
| OUTPUT | `da_seg` | (1, 2, 384, 640) | FLOAT | Drivable area, 2 channels, sigmoid output |
| OUTPUT | `ll_seg` | (1, 2, 384, 640) | FLOAT | Lane line, 2 channels, sigmoid output |

- 397 layers. 1 profile. Device memory 43,450,368 B.
- The I/O tensors are FP32. FP16 is only inside the engine.
- The engine needs no plugin library. The research loaded it without `init_libnvinfer_plugins`.
- Source ONNX: `/home/tonyho/model/jetson_bundle/onnx/yolopx_v2.onnx` (sha256[:16] `3a49f4ebe346bea4`). Build command: `README.md:64-74` in `jetson_bundle` (`trtexec --fp16 --shapes=image:1x3x384x640`).
- Weights: `jetson_bundle/weights/yolopx_v2_epoch30.pth`. Model code: `/home/tonyho/model/jetson_bundle/source/yolopx/lib` (10 classes).
- `docs/YOLOPX_deployment.md:49` (640x640) and `:231` (cast to float16) in `jetson_bundle` are out of date. Do not use them.

### 3.2 How the old code loads it

Class `TRTRunner`, `/home/tonyho/model/jetson_bundle/jetson_runtime/trt_runner.py` (copy: `infer/models/legacy/driverguard/trt_runner.py`). CUDA library: pycuda (`:17-19`).

| Step | Code | Line |
|---|---|---|
| 1 | `trt.Logger(WARNING)` | `:22` |
| 2 | `trt.Runtime(...).deserialize_cuda_engine(bytes)` | `:29-32` |
| 3 | `create_execution_context()` | `:35` |
| 4 | For each tensor: `get_tensor_name/mode/shape/dtype` | `:42-46` |
| 5 | Dynamic dims set to 1. Inputs get `set_input_shape`. | `:48`, `:51` |
| 6 | Host buffer `np.empty` (NOT pinned). Device buffer `cuda.mem_alloc`. | `:54`, `:55` |
| 7 | `context.set_tensor_address` | `:59` |
| 8 | `cuda.Stream()` | `:61` |
| 9 | `infer()`: cast to engine dtype, check shape | `:69`, `:70-71` |
| 10 | `memcpy_htod_async`, `execute_async_v3(stream.handle)`, `memcpy_dtoh_async`, `stream.synchronize()` | `:73`, `:75`, `:82`, `:83` |
| 11 | Return copies | `:85` |

The old runner makes one `TRTRunner` per engine, in one process and one thread (`/home/tonyho/model/driverguard/runner/runner.py:112-113`).

### 3.3 Input source and cameras

| Item | Old stack | New node |
|---|---|---|
| Source | GStreamer shm `/tmp/cam0`, RGBA 1280x720 at 30 fps (`visionipc/camtest.cpp:250-259`) | FrameLink, NV12 (`common/framelink.py:33`) |
| Frame size | 1280x720. The old runner resized other sizes to 1280x720 with `INTER_LINEAR` (`runner.py:163-165`). | cam0 1280x720. cam1-cam5 704x396 (`common/framelink.py:33`). |
| Cameras | cam0 only (`run.py:37`) | Detections cam0-cam5. Masks cam0 only. |
| Colour conversion | `COLOR_BGRA2BGR` on RGBA: BUG (`camera_reader.py:88`) | `cv2.COLOR_YUV2BGR_NV12`: true BGR (section 5) |

### 3.4 Preprocessing (`preprocess_yolopx`, `preprocess.py:36-71`)

Do these steps in this order:

1. Get a BGR uint8 frame (H x W x 3).
2. Calculate `r = min(384/h0, 640/w0)` (`:40`).
3. Calculate the new size `nh = int(round(h0*r))`, `nw = int(round(w0*r))` (`:41`).
4. Resize to (nw, nh) with `cv2.INTER_AREA` (`:45`). Skip this step when the size does not change (`:44`).
5. Calculate `dw = (640-nw)/2` and `dh = (384-nh)/2` (`:42-43`).
6. Pad with `top = round(dh-0.1)`, `bottom = round(dh+0.1)`, `left = round(dw-0.1)`, `right = round(dw+0.1)` (`:46-49`).
7. Use pad value (114, 114, 114) and `BORDER_CONSTANT` (`:36`, `:50-51`).
8. Flip BGR to RGB with `[..., ::-1]` (`:65`).
9. Divide by 255 (`:66`).
10. Subtract ImageNet mean `[0.485, 0.456, 0.406]`. Divide by std `[0.229, 0.224, 0.225]` (`:13-14`, `:67`).
11. Transpose to NCHW (1, 3, 384, 640), float32, contiguous (`:68-69`).

Values for the two FrameLink frame sizes (calculated from the code above):

| Frame | r | Resized | dh | Pad top / bottom / left / right |
|---|---|---|---|---|
| 1280x720 (cam0) | 0.5 | 640x360 | 12 | 12 / 12 / 0 / 0 (the research confirmed `pad=(0.0, 12.0)`) |
| 704x396 (cam1-cam5) | 0.9091 | 640x360 | 12 | 12 / 12 / 0 / 0 |

### 3.5 Postprocessing

**`det` columns** (decoded inside the graph; `source/yolopx/lib/models/YOLOX_Head_scales_noshare.py:36`, `:167`, `:198-199`):

| Columns | Content |
|---|---|
| 0-3 | `cx, cy, w, h` in 640x384 input pixels |
| 4 | Objectness, already sigmoid |
| 5-14 | 10 class scores, sigmoid (independent, not softmax) |

5040 rows = 80x48 + 40x24 + 20x12 (strides 8, 16, 32 at `:22`; anchor-free).

**Boxes** (`nms_yolopx`, `yolopx_postprocess.py:53-86`). The old runner calls it with `conf_thres=0.30, iou_thres=0.45` (`runner.py:78`).

1. Keep rows with objectness > 0.30 (`:65-66`).
2. Multiply the class scores by objectness: score = obj x cls (`:71`).
3. Convert xywh to xyxy (`:72`).
4. Take the best class only (argmax) (`:74-75`).
5. Keep rows with score > 0.30 (`:76-77`).
6. Do greedy NMS with IoU 0.45. Add the offset `cls * 4096` so that classes do not suppress each other (`:82-83`).
7. Keep at most 300 boxes (`max_det=300`, `:54`, `:84`).
8. Output (N, 6): `x1, y1, x2, y2, conf, cls` in 640x384 space (`:85-86`).

Note: upstream YOLOPX uses `multi_label` when nc > 1 (`source/yolopx/lib/core/general.py:115`, `:148-150`). The runtime copy does not. The new node keeps the runtime behaviour.

**Map boxes to the frame** (`scale_coords`, `yolopx_postprocess.py:89-102`):

1. `gain = min(384/out_h, 640/out_w)` (`:93`).
2. `pad_w = (640 - out_w*gain)/2`, `pad_h = (384 - out_h*gain)/2` (`:94-95`).
3. Subtract the pad from x and y (`:97-98`).
4. Divide by gain (`:99`).
5. Clip to [0, out_w] and [0, out_h] (`:100-101`).
6. Do not round. Upstream rounds (`/home/tonyho/model/yolopx/YOLOPX/tools/demo.py:153`).

In the new schema, boxes are in `frameWidth x frameHeight` pixels, the FrameLink frame size (`proto/agx_infer.capnp:30-31`, `:43-46`).

**Masks** (`segmasks_from_logits`, `yolopx_postprocess.py:105-127`). cam0 only.

1. `da_seg` and `ll_seg` are sigmoid outputs, not logits (`source/yolopx/lib/models/common.py:2151-2165`). Measured `da_seg` range: 0.43-1.0.
2. Remove the pad rows and columns: `[pad_h:384-pad_h, pad_w:640-pad_w]` (`:118`).
3. Calculate channel 1 minus channel 0 (`:120`).
4. Resize bilinearly (`INTER_LINEAR`) to the frame size (`:121`).
5. Threshold `> 0` (same as argmax) (`:122`).
6. Remove lane pixels from the drivable area: `da = (da - ll) == 1` (`:126`).

**Mask encoding** (`mask_codec.py:17-41`, `encode_rle`):
- Row-major run-length records.
- Each record: `uint16` little-endian count, then `uint8` value (0 or 1).
- Runs longer than 65535 are split (`_MAX_RUN = 65535`, `mask_codec.py:14`; `:34-37`).
- New schema: `Mask.encoding = "rle-u16le-count-u8-value-rowmajor"`, `Mask.name = "drivable_area" | "lane_line"` (`proto/agx_infer.capnp:62-67`).
- Old schema for reference: `daMaskRle` / `llMaskRle`, `maskWidth=1280`, `maskHeight=720` (`runner.py:190-191`, `:221-224`; `message.capnp:310-338`).

### 3.6 Class names

Exact list, in index order (`classId` = index):

| classId | className | UI colour, RGB (`main_camera.py:400-411`) |
|---|---|---|
| 0 | `person` | (64, 64, 255) |
| 1 | `rider` | (0, 128, 255) |
| 2 | `car` | (64, 255, 64) |
| 3 | `bus` | (255, 200, 64) |
| 4 | `truck` | (255, 0, 200) |
| 5 | `bike` | (255, 255, 0) |
| 6 | `motor` | (0, 255, 255) |
| 7 | `traffic light` | (128, 0, 255) |
| 8 | `traffic sign` | (128, 255, 128) |
| 9 | `train` | (200, 200, 200) |

Sources of the class list:
- `/home/tonyho/model/jetson_bundle/jetson_runtime/yolopx_postprocess.py:14-15`: `CLASS_NAMES = ['person', 'rider', 'car', 'bus', 'truck', 'bike', 'motor', 'traffic light', 'traffic sign', 'train']`
- `/home/tonyho/model/jetson_bundle/source/yolopx/lib/models/YOLOP.py:159-160` (nc=10 at `:41`, `:126`)
- Old UI: `/home/tonyho/driveragent/ui/newwidgets/main_camera.py:398-399` (`_DG_CLASS_NAMES`)

Other old UI colours (`main_camera.py:434-464`):
- Drivable area: green contour, RGBA (60, 220, 80, 200), 3 px.
- Lane line: red contour, RGBA (240, 70, 70, 230), 4 px.
- Box: 2 px outline in the class colour. Label `"{name} {conf:.2f}"`, black text on a tag of the class colour (`:466-487`).

### 3.7 Rate and latency

- Old rate: 10 Hz target (`run.py:30`), paced by sleep (`runner.py:142`, `:252-254`). Camera: 30 fps.
- Old `inferenceMs` covers preprocessing, both TRT runs and postprocessing. It excludes camera read and RLE encoding (`runner.py:169-182`).

Latency measured by the T1 research run (pycuda, non-pinned copies; T4 measures again). Median of 50 runs after 10 warm-up runs. Frame 1280x720. Host-device copies included. The power mode was not checked during this run (T1_driverguard.md, section 6).

| Stage | ms |
|---|---|
| YOLOPX preprocessing | 8.13 |
| YOLOPX TRT | 27.8 |
| NMS | 0.79 |
| Segmentation postprocess | 2.18 |

### 3.8 Parity evidence

Research run on 3 sample frames (`/home/tonyho/model/jetson_bundle/samples/cam_front/*.jpg`) against the reference `reference_yolopx/e036014a715945aa965f4ec24e8639c9_yolopx.npz`:
- Box counts equal on every frame. 33 of 34 boxes match at IoU > 0.95 with the same class.
- Drivable-area agreement >= 0.9996. Lane-line agreement >= 0.9999.

## 4. `driverguard_dtcp`

### 4.1 Engine I/O

| Dir | Name | Shape | Type | Content |
|---|---|---|---|---|
| INPUT | `image` | (1, 3, 256, 928) | FLOAT | Stretched RGB, ImageNet-normalized, NCHW |
| INPUT | `state` | (1, 9) | FLOAT | `[speed_mps/12, target_lat_right_m, target_fwd_m, one_hot(command, 6)]` |
| INPUT | `target_point` | (1, 2) | FLOAT | Same target again (GRU input at each step; `source/dtcp/model.py:157`) |
| OUTPUT | `pred_wp` | (1, 4, 2) | FLOAT | 4 waypoints, metres |
| OUTPUT | `mu` | (1, 2) | FLOAT | Softplus Beta alpha over (acc, steer) (`source/dtcp/model.py:110-111`) |
| OUTPUT | `sigma` | (1, 2) | FLOAT | Softplus Beta beta over (acc, steer) (`source/dtcp/model.py:110-111`) |
| OUTPUT | `pred_speed` | (1, 1) | FLOAT | x12 = m/s (`runner.py:94`) |

- 77 layers. 1 profile. Device memory 11,403,264 B. No plugin library.
- Source ONNX: `/home/tonyho/model/jetson_bundle/onnx/dtcp_v1.onnx` (sha256[:16] `794373ce8d25aaf9`). Build: `README.md:64-74` (`--shapes=image:1x3x256x928,state:1x9,target_point:1x2`).
- DTCP does not use YOLOPX features. The two models share no weights (`docs/jetson_deployment_workplan.md:333`).

### 4.2 How the old code loads it

The same `TRTRunner` as section 3.2 (`trt_runner.py`, pycuda). Second instance at `runner.py:112-113`.

### 4.3 Input source and camera

- cam0 only. Frame 1280x720 (FrameLink NV12, converted to BGR, section 5).
- The old code fed BGR data that was really RGB (camera bug), then did `BGR2RGB` (`runner.py:86`). The new node gives true BGR, then converts to RGB once.

### 4.4 Inputs that the AGX does not have

| Input | Old source | New node value | Note |
|---|---|---|---|
| Ego speed | CarState `speedKph/3.6` from `tcp://127.0.0.1:5592`. 0 when CarState is missing (`runner/ego_state.py:16`, `:49-51`). | 0 m/s | No CarState on the AGX in the new split. `inputsValid = false`. |
| Route command | CLI `--command`, default 2 (`run.py:39-41`). The supervisor starts `run.py` with no arguments (`start.py:105`). | 2 = STRAIGHT (fixed) | Old default. `RouteGuidance.dtcpCommand` was never used. |
| Target point | CLI `--target`, default (0, 20) m (`run.py:42-45`) | (0, 20) m (fixed): lat_right 0, fwd 20 | Old default. Training used the next route waypoint >= 30 m ahead (`docs/DTCP_deployment.md:84`). |

Command mapping: 0=LEFT, 1=RIGHT, 2=STRAIGHT, 3=LANE_FOLLOW, 4=CHANGE_LEFT, 5=CHANGE_RIGHT (`source/dtcp/dtcp_infer.py:56-57`; `message.capnp:328`; `run.py:40-41`).

With these values, `state = [0, 0, 20, 0, 0, 1, 0, 0, 0]` and `target_point = [0, 20]` (from the formula in section 4.1).

### 4.5 Preprocessing (`preprocess_dtcp`, `preprocess.py:22-33`)

1. Convert BGR to RGB (old code: `runner.py:86`). Input to the function is RGB uint8.
2. Stretch (NOT letterbox) to 928x256 with `cv2.INTER_LINEAR` (`:28-29`).
3. Divide by 255 (`:30`).
4. Subtract ImageNet mean, divide by std (`:31`).
5. Transpose to NCHW (1, 3, 256, 928), float32, contiguous (`:32-33`).

Note: the PC reference resizes with PIL `Image.BILINEAR` (`source/dtcp/dtcp_infer.py:141-143`). The difference was not measured.

### 4.6 Postprocessing and what the node publishes

`pred_wp` (1, 4, 2):
- Ego frame, metres. Built by cumulative GRU steps (`source/dtcp/model.py:156-164`).

| Column | Meaning |
|---|---|
| col0 | Lateral, right positive |
| col1 | Forward |

| Row | t (s) |
|---|---|
| 0 | 0.5 |
| 1 | 1.0 |
| 2 | 1.5 |
| 3 | 2.0 |

Source: `docs/DTCP_deployment.md:87-100`. z is 0.

Published in `AgxPerceptionResult.trajectory` (`proto/agx_infer.capnp:50-60`):
- `points`: the 4 waypoints, with `x` = col0, `y` = col1, `tS` = 0.5 / 1.0 / 1.5 / 2.0. This is the same axis order as the old `DriverGuardResult.trajectory` (`message.capnp:322`).
- `frame`: names the axes in full (x lateral right +, y forward, metres).
- `inputsValid = false`.
- `note`: names the assumed inputs (speed 0 m/s, command STRAIGHT, target (0, 20) m) and says "display only, not for control".

NOT published (rule R8: this node publishes perception results only):
- throttle, steer, brake (from `beta_mode.py:34-42`)
- `mu`, `sigma`
- `pred_speed`

`beta_mode.py` is copied for reference only.

Caution: the old `RouteGuidance` uses a different frame (x forward, y left; `message.capnp:196`, `:211`). Do not mix the two.

### 4.7 Rate and latency

- Old rate: 10 Hz, same loop as YOLOPX (`run.py:30`).

Measured by the T1 research run (pycuda, non-pinned copies; T4 measures again):

| Stage | ms |
|---|---|
| DTCP preprocessing | 7.74 |
| DTCP TRT | 6.78 |
| Total, YOLOPX + DTCP, serial | 54.67 (about 18 Hz maximum) |

## 5. Colour decision

| Item | Fact | Source |
|---|---|---|
| Old camera producer | Publishes RGBA 1280x720 | `visionipc/camtest.cpp:250-259` |
| Old reader | Runs `cv2.COLOR_BGRA2BGR` on RGBA bytes | `/home/tonyho/model/driverguard/runner/camera_reader.py:88` |
| Result | The "BGR" frame is really RGB. R and B are swapped for both old models. | Research GStreamer test: pure red RGBA gave `[255,0,0]` after `BGRA2BGR` |
| Effect | Drivable-area agreement 0.919-0.988 with the swap. 0.9996-0.99999 without. One box lost per frame. DTCP 4th waypoint 0.3-0.5 m further forward. | T1_driverguard.md, Key findings |

Decision:
- The new node gets NV12 from FrameLink (`common/framelink.py:33`).
- The node converts with OpenCV `cv2.COLOR_YUV2BGR_NV12`.
- The RK declared encoding is BT.601, limited range (`rk/config/rk.toml:50-57`). The RK marks it UNVERIFIED until the camera datasheet confirms it. The RK side does no YUV to RGB conversion.
- Read-only check tonight (`.venv`, OpenCV 4.10.0): Y=16 gives BGR (0,0,0). Y=235 gives (255,255,255). BT.601 red (Y=81, U=90, V=240) gives BGR (0,0,254). So `COLOR_YUV2BGR_NV12` is BT.601 limited range.
- `preprocess_yolopx` therefore gets true BGR, as its code expects (`preprocess.py:65`).
- The new node does NOT copy the old reader bug.
- The old live models ran with swapped R/B. Results from the new node can differ from old recordings.

## 6. Camera numbering

| Source | cam0 | cam1 | cam2 | cam3 | cam4 | cam5 |
|---|---|---|---|---|---|---|
| Old logger, replay, docs (`logger/encoder_265.py:60-67`, `calibration/doc/skill.md:8-13`) | front | right | left | right-back | left-back | back |
| Old UI (`ui/newwidgets/main_camera.py:19`) | Front | Left Front | Left Rear | Rear | Right Rear | Right Front |
| RK `camera_map.ini` (`rk/boards/rk3588-da01/vehicle/camera_map.ini:284-287`, `:289-312`; RK tag `rk-v0.4.0`) | FRONT, `gmsl_des29_linkA`, CONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED |

- cam0 = front in every source.
- The old logger and the old UI conflict for cam1-cam5.
- The RK map has only cam0 CONFIRMED.
- Open point: `camera_map.ini:14-15` says the unlabelled cameras are "never used as model inputs". The coordinator decision runs `driverguard_yolopx` detections on cam1-cam5. Tell the RK side.
- Do not use side or rear roles for any decision until the RK map confirms them.
- Old UI drew DriverGuard overlays only on cam0 (`main_camera.py:225-232`).

## 7. Models that are OFF

### 7.1 `system1` (state OFF)

| Item | Fact |
|---|---|
| What it is | Trajectory scorer. ConvNeXt V2-Tiny + FPN backbone, `FactorizedScorer` head. Weights `/home/tonyho/model/system1/system1_deploy.pth` (v9e, epoch 12). 6 cameras, input [1,6,3,256,704]. Output 6 points at 0.5 s steps. |
| Runtime | PyTorch only, bf16 autocast (default `--precision bf16`, `run.py:42-44`; autocast in `run_system1.py:103-127`). No engine exists on disk. No code builds one. |
| Latency (research, MAXN) | 213 ms at width 704, 192 ms at width 563 (bf16). Old target 5 Hz is not reached. |
| ONNX | `/home/tonyho/model/system1/backbone_nchw.onnx` (sha256[:16] `a31813fca8a29d1f`). Backbone only. GroupNorm replaces LayerNorm, not exact (cosine about 0.95-0.97; `DEPLOY_INSTRUCTIONS.md:404`). |
| Bugs in old runner | B1: image is 256x563, not 256x704 (`runner/runner.py:133`, `:217`, `:142-143`). B2: crop keeps the top rows; probably wrong. The probable equivalent for 1280x720 is scale 0.55, keep rows 140:396 (from sibling stage2 code; not proven, the System 1 training code is not on disk). B3: output axes: channel 1 is forward; UI sums absolute points as deltas. B4: calibration missing for cam2-cam5, cam1 not calibrated. B5: slots 3 and 5 swapped against nuScenes order. |
| Why OFF | Not a TensorRT model. Too slow. Bugs B1-B5. |
| Not built tonight | An engine of the backbone alone does not make System 1 run. The head stays PyTorch. |
| To enable | Fix B1-B5. Get the training code to prove the crop and heading convention. Real calibration for 6 cameras. Port the head or accept PyTorch latency. CarState input. |

### 7.2 SparseDrive (`sparsedrive_convnext_orin`, disabled)

| Item | Fact |
|---|---|
| What it is | ConvNeXt V2-Tiny + FPN backbone, det/map/motion head. 6 surround cameras, input (6,3,450,800). Checkpoint `/home/tonyho/model/sparsedrive/checkpoints/best.pth`. |
| Classes | `DET_CLASS_NAMES = ['car','truck','construction_vehicle','bus','trailer','barrier','motorcycle','bicycle','pedestrian','traffic_cone']`, `MAP_CLASS_NAMES = ['lane_divider','road_boundary','pedestrian_crossing']` (`run/hybrid_inference.py:491-498`) |
| Engine | `convnext_backbone_fp16_orin.trt` loads with the device warning. Cosine 0.390 against `convnext_backbone_nchw_orin.onnx`. That ONNX has weights that do NOT match `best.pth`. TRT latency 112 ms (6 cameras). |
| Old loader | torch CUDA, not pycuda: class `TensorRTBackbone`, `run/hybrid_inference.py:50-138` (logger `:72`, deserialize `:75-77`) |
| Head | PyTorch only, grid_sample fallback (custom CUDA op missing). 1253-1720 ms, about 0.5-0.7 FPS (`OPTIMIZATION_GUIDE.md:7-12`). |
| Calibration | Placeholder: identity extrinsics for every camera (`run/calibration.json:5-6`). |
| Why OFF | Wrong features, slow head, no calibration. |
| To enable | Rebuild the backbone from `run/convnext_nchw_backbone.onnx` (the only ONNX that matches `best.pth`) with a correct workspace (for example `--memPoolSize=workspace:8192M`) and LayerNorm/GRN in FP32. Check cosine against PyTorch. Make the head fast. Get real calibration. Fix the camera slot order (slots 3/5). |

Other SparseDrive engines (not in config):
- `convnext_backbone_fp16.trt`: cosine 0.121 against `convnext_nchw_backbone.onnx`, 125 ms. Wrong output.
- `resnet_backbone_fp16_orin.trt`: cosine 1.00000, 35.6 ms. Feature shapes 113x200 etc. do not fit the ConvNeXt head. No ResNet weights in `best.pth`.

### 7.3 stage2

- Stage-2 SparseDrive ConvNeXt V2-T, det + map + motion (`DEPLOY_STAGE2.md:1-5`). Input (1,6,3,256,704).
- `best.pth` (326,680,576 B, sha256[:16] `190bf6b2fb61e959`) and `latest.pth` (320,233,472 B, `245691dfcc7126a4`) are truncated. Error: `PytorchStreamReader failed reading zip archive: failed finding central directory`.
- No TRT, no ONNX. CUDA op is x86_64 only. Script paths are wrong (`run_stage2.py:25`).
- To enable: a complete checkpoint copy (doc expects 427 MB), an aarch64 op build, an engine. Not a model for this node.

### 7.4 YOLOPX v1 (epoch-195)

- Upstream YOLOPX repo `/home/tonyho/model/yolopx/YOLOPX` (HEAD 35627f6). Weights `weights/epoch-195.pth` (sha256[:16] `52e989dc3d15c9e4`).
- 1 class only: `[-1, YOLOXHead, [1]]` (`lib/models/YOLOP.py:41`), `self.nc = 1` (`:126`), names `['0']` (`:159`). Weights confirm: `cls_preds` shape (1,192,1,1).
- PyTorch FP16. Old launcher: `tools/demotext.py` (`/home/tonyho/driveragent/startmodel.sh:60-66`). JPEG round trip through disk.
- Superseded by `yolopx_v2_fp16.engine` (10 classes). Not a model for this node.

### 7.5 Engine hidden in `convnext_backbone_trt.ep`

- File: `/home/tonyho/model/sparsedrive/run/convnext_backbone_trt.ep` (87,918,879 B, sha256[:16] `e28b0f0ae8612ebc`). torch_tensorrt ExportedProgram, not a plan file.
- The engine is base64 inside zip entry `convnext_backbone_trt/data/constants/model.pt`. Decoded size 65,931,356 B. 228 layers.
- I/O: `INPUT x (6,3,450,800)`; `OUTPUT output0 (6,256,112,200)`, `output1 (6,256,56,100)`, `output2 (6,256,28,50)`, `output3 (6,256,14,25)`. All FLOAT.
- Output is 100% NaN (also on all-zero input).
- No code loads a `.ep` file. The only related code is the optional `torch_tensorrt` install step, `install.sh:157-167`. It does not name the `.ep` file.
- To enable: not possible. Rebuild instead (section 7.2).

## 8. Files copied

The new node uses copies of the old DriverGuard code. The copies are unchanged (sha256 equal to the source).

| Copy | Use |
|---|---|
| `infer/models/legacy/driverguard/preprocess.py` | Library |
| `infer/models/legacy/driverguard/yolopx_postprocess.py` | Library |
| `infer/models/legacy/driverguard/mask_codec.py` | Library |
| `infer/models/legacy/driverguard/beta_mode.py` | Library, reference only (no control output) |
| `infer/models/legacy/driverguard/viz_helpers.py` | Reference only |
| `infer/models/legacy/driverguard/trt_runner.py` | Reference only |
| `infer/models/legacy/driverguard/runner.py` | Reference only (needs the old repo to import) |
| `infer/models/legacy/driverguard/camera_reader.py` | Reference only (contains the colour bug) |
| `infer/models/legacy/driverguard/run_driverguard.py` | Reference only |
| `infer/models/legacy/message_old_agx.capnp` | Reference only |

Import check (`PYTHONPATH=/home/tonyho/driveragent-agx`, `.venv/bin/python`, old repo NOT on the path):

| Module | Result |
|---|---|
| `infer.models.legacy.driverguard.preprocess` | OK |
| `infer.models.legacy.driverguard.yolopx_postprocess` | OK |
| `infer.models.legacy.driverguard.beta_mode` | OK |
| `infer.models.legacy.driverguard.mask_codec` | OK |
| `infer.models.legacy.driverguard.viz_helpers` | OK |
| `infer.models.legacy.driverguard.trt_runner` | OK (imports pycuda; creates a CUDA context) |
| `infer.models.legacy.driverguard.camera_reader` | OK |
| `infer.models.legacy.driverguard.runner` | FAILS: `ModuleNotFoundError: No module named 'message'` (needs `/home/tonyho/driveragent`). Reference only. |

Source paths, sha256 and git versions: see `docs/COPIED_FILES.md`.
