# DriverGuard (YOLOPX + DTCP): research report

Everything below comes from files I read tonight, plus the TensorRT 10.3.0 output from loading each engine in a separate process. I ran nothing from DriverAgent. My own scripts are in `/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad/driverguard/` (`insp.py`, `parity.py`) and all of them have exited.

## Key findings

- **Camera colour bug (checked with my own GStreamer test, not on the live stream).** The camera publishes RGBA. OpenCV 4.10 hands those bytes over unchanged in R,G,B,A order. `runner/camera_reader.py:86-88` then runs `cv2.COLOR_BGRA2BGR`, so the frame it calls "BGR" is actually **RGB**. As a result:
  - YOLOPX is fed BGR when it expects RGB (`preprocess.py:65` flips the channels again).
  - DTCP is also fed BGR (`runner.py:86` does `BGR2RGB` on data that is already RGB).
  - Test: `videotestsrc` with a pure-red RGBA frame, `caps format=RGBA` into appsink. `cap.read()` gave `[255,0,0,255]`, and after `BGRA2BGR` the pixel was `[255,0,0]`. Pure red in BGR would be `[0,0,255]`.
  - Effect on the 3 sample frames: drivable-area agreement with the reference drops from 0.9996–0.99999 to 0.919–0.988, each frame loses one box, and DTCP's 4th waypoint moves 0.3–0.5 m further forward.
  - **A new node reading RGBA shm through OpenCV must use `cv2.COLOR_RGBA2BGR`.**
- **The real engines do not match the docs.** Both engines take **FP32** input (I/O tensors are FP32; the FP16 is only inside the engine), and YOLOPX input is **384×640**. `docs/YOLOPX_deployment.md:49` (640×640) and `:231` (cast to float16) are out of date.
- **The DTCP route command and target are fixed.** The supervisor starts `run.py` with no arguments (`start.py:105`), so the command is always 2=STRAIGHT and the target always (0, 20) m (`run.py:39-45`). `runner.py` never subscribes to `RouteGuidance`, so `RouteGuidance.dtcpCommand` (`message.capnp:209`) is not used.
- **Two different frame conventions:**
  - `DriverGuardResult.trajectory`: x = lateral (right +), y = forward (`message.capnp:322`).
  - `RouteGuidance`: x = forward, y = left (`message.capnp:196`, `:211`).
- **The DTCP planner does not use YOLOPX features.** Both models take the raw frame separately and share no weights (`docs/jetson_deployment_workplan.md:333`).
- **The repo at `/home/tonyho/model/yolopx/YOLOPX` is the old 1-class version and does not match the engine.** Its `lib/models/YOLOP.py` has `YOLOXHead [1]`, `self.nc = 1` and numeric class names (seen with `diff`: lines 41, 126, 159). The 10-class code the engine was built from is `/home/tonyho/model/jetson_bundle/source/yolopx/lib`.
- **No Jetson latency was ever recorded in the docs.** The hand-off log says "Nothing executed on Jetson yet" (`docs/jetson_deployment_workplan.md:361`). The numbers in section 6 are from my own run tonight.

---

## 1. Engine files

`/home/tonyho/model/driverguard/engines/` contains only symlinks:
- `dtcp_v1_fp16.engine` → `/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine`
- `yolopx_v2_fp16.engine` → `/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine`

The paths are referenced at `run.py:21-22`.

| Engine (real file) | Size (bytes) | mtime | sha256[:16] |
|---|---|---|---|
| `/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine` | 70643388 | 2026-05-11 16:22:53 +0100 | `3412bafa057a3a76` |
| `/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine` | 55987852 | 2026-05-11 16:24:03 +0100 | `1071ea90213eddc2` |

Source ONNX files:
- `onnx/yolopx_v2.onnx`: 131936832 B, sha `3a49f4ebe346bea4`
- `onnx/dtcp_v1.onnx`: 97041687 B, sha `794373ce8d25aaf9`

The build commands are in `README.md:64-74` (`trtexec --fp16 --shapes=image:1x3x384x640` and `--shapes=image:1x3x256x928,state:1x9,target_point:1x2`).

TensorRT 10.3.0 output, exact. stderr was empty: no version-mismatch error and no warnings.

```
##### /home/tonyho/model/driverguard/engines/dtcp_v1_fp16.engine
TRT 10.3.0
LOAD OK
num_io 7 profiles 1
INPUT image (1, 3, 256, 928) FLOAT Row major linear FP32 format (kLINEAR)
INPUT state (1, 9) FLOAT Row major linear FP32 format (kLINEAR)
INPUT target_point (1, 2) FLOAT Row major linear FP32 format (kLINEAR)
OUTPUT pred_wp (1, 4, 2) FLOAT Row major linear FP32 format (kLINEAR)
OUTPUT mu (1, 2) FLOAT Row major linear FP32 format (kLINEAR)
OUTPUT sigma (1, 2) FLOAT Row major linear FP32 format (kLINEAR)
OUTPUT pred_speed (1, 1) FLOAT Row major linear FP32 format (kLINEAR)
device_memory 11403264
exit=0
##### /home/tonyho/model/driverguard/engines/yolopx_v2_fp16.engine
TRT 10.3.0
LOAD OK
num_io 4 profiles 1
INPUT image (1, 3, 384, 640) FLOAT Row major linear FP32 format (kLINEAR)
OUTPUT det (1, 5040, 15) FLOAT Row major linear FP32 format (kLINEAR)
OUTPUT da_seg (1, 2, 384, 640) FLOAT Row major linear FP32 format (kLINEAR)
OUTPUT ll_seg (1, 2, 384, 640) FLOAT Row major linear FP32 format (kLINEAR)
device_memory 43450368
exit=0
```

## 2. How the engines are loaded

The CUDA library is **pycuda**: `trt_runner.py:17-19` (`import tensorrt`, `pycuda.driver`, `pycuda.autoinit`). torch and cuda-python are not used anywhere under `driverguard/` (grep found nothing).

Class `TRTRunner`, `/home/tonyho/model/jetson_bundle/jetson_runtime/trt_runner.py`:
- `trt.Logger(WARNING)` (:22) → `trt.Runtime(...).deserialize_cuda_engine(bytes)` (:29-32) → `create_execution_context()` (:35).
- For each I/O tensor:
  - `get_tensor_name/mode/shape/dtype` (:42-46); any dynamic dim is replaced by 1 (:48).
  - Inputs get `set_input_shape` (:51).
  - Host buffer is a plain `np.empty`, **not pinned** (:54); device buffer is `cuda.mem_alloc` (:55).
  - `context.set_tensor_address` (:59).
- `cuda.Stream()` (:61).
- `infer()`:
  - casts each input to the engine dtype (:69) and checks shape (:70-71);
  - `memcpy_htod_async` (:73), `execute_async_v3(stream.handle)` (:75), `memcpy_dtoh_async` (:82), `stream.synchronize()` (:83);
  - returns copies (:85).

Plugins: no `init_libnvinfer_plugins` call in `trt_runner.py`. My parity script loaded both engines without initialising plugins, so neither engine needs one.

The runner creates one TRTRunner per engine at `runner.py:112-113`, both in the same process and thread.

## 3. Camera and preprocessing

**Source**
- Front camera `/tmp/cam0` (`run.py:37`, `README.md:4`).
- Producer: `visionipc/camtest.cpp:250-259` reads v4l2 UYVY 1920×1080@30, `nvvidconv` scales it to **RGBA 1280×720@30**, then `shmsink socket-path=/tmp/cam0`. Constants at `camtest.cpp:31-32`.
- Reader pipeline (`runner/camera_reader.py:17-24`): `shmsrc socket-path=/tmp/cam0 is-live=true do-timestamp=true ! video/x-raw,format=RGBA,width=1280,height=720,framerate=30/1 ! queue max-size-buffers=2 leaky=downstream ! appsink sync=false max-buffers=1 drop=true`, opened with `cv2.VideoCapture(..., CAP_GSTREAMER)` (:41-42).
- 4-channel to 3-channel at :86-88 (`COLOR_BGRA2BGR`). This is the colour bug above.
- Frames that are not 720×1280 are resized with INTER_LINEAR (`runner.py:163-165`).
- `/tmp/cam0` does not exist on this machine tonight, so I could not read the live stream.

**YOLOPX preprocessing** (`jetson_runtime/preprocess.py:36-71`; matches upstream `letterbox_for_img` in `source/yolopx/lib/utils/augmentations.py:216-250` and `DemoDataset.py:92-101`):
1. Letterbox to (H, W) = (384, 640) (:55). `r = min(384/h0, 640/w0)`. For 1280×720, r = 0.5 → 640×360.
2. Resize with **`cv2.INTER_AREA`** (:45), as upstream does (`augmentations.py:245`).
3. Pad top/bottom/left/right using `round(d ± 0.1)` (:46-49). For 1280×720 that is 12 px top and 12 px bottom, 0 left and right. Pad value is **(114,114,114)**, `BORDER_CONSTANT` (:36, :50-51).
4. Flip BGR→RGB with `[..., ::-1]` (:65).
5. `/255` (:66), then ImageNet mean `[0.485,0.456,0.406]`, std `[0.229,0.224,0.225]` (:13-14, :67).
6. NCHW `(1,3,384,640)`, **float32** (:68-69).

My run confirmed `pad=(0.0, 12.0)`.

**DTCP preprocessing** (`preprocess.py:22-33`):
1. Input is RGB uint8 (`runner.py:86`).
2. **Stretch, not letterbox**, to 928×256 with `cv2.INTER_LINEAR` (:28-29).
3. `/255`, ImageNet mean/std (:30-31).
4. NCHW `(1,3,256,928)`, float32 (:32-33).

The PC reference resizes with **PIL `Image.BILINEAR`** instead (`source/dtcp/dtcp_infer.py:141-143`), so the numbers differ slightly. I did not measure the difference.

## 4. YOLOPX outputs and postprocessing

**`det` (1, 5040, 15)**
- Already decoded inside the graph: `decode_in_inference = True` (`source/yolopx/lib/models/YOLOX_Head_scales_noshare.py:36`, :180-181).
- Columns:

| Columns | Content |
|---|---|
| 0-3 | `[cx, cy, w, h]` in **640×384 input pixels**: xy = (raw + grid) × stride, wh = exp(raw) × stride (:198-199) |
| 4 | objectness, already sigmoided (:167) |
| 5-14 | 10 class scores, sigmoid (independent, not softmax) (:167) |

- Strides 8/16/32 (:22), anchor-free: 80×48 + 40×24 + 20×12 = 5040.
- Real engine ranges I measured: obj 0.0005–0.74, cls 0–0.91.

**Class names (10).** Order: `['person','rider','car','bus','truck','bike','motor','traffic light','traffic sign','train']`. Defined in:
- `/home/tonyho/model/jetson_bundle/jetson_runtime/yolopx_postprocess.py:14-15` (the runtime copy);
- `source/yolopx/lib/models/YOLOP.py:159-160` (nc=10 at :41 and :126);
- `docs/YOLOPX_deployment.md:51`;
- the UI copy at `ui/newwidgets/main_camera.py:398-399`.

The reference npz `class_names` matches.

**NMS** (`nms_yolopx`, `yolopx_postprocess.py:53-86`), called with `conf_thres=0.30, iou_thres=0.45` (`runner.py:78`):
1. Keep rows with obj > 0.30.
2. Class score = obj × cls (:71).
3. xywh → xyxy (:72).
4. Take the **best class only** (:74-75) and require score > 0.30.
5. Class-offset greedy NMS, offset `cls*4096` (:82-83), `max_det=300` (:54, :84).
6. Output `(N,6)`: x1, y1, x2, y2, conf, cls.

This differs from upstream, which uses `multi_label` because nc > 1 (`source/yolopx/lib/core/general.py:115`, :148-150).

Parity on the 3 samples: box counts are equal on every frame, and 33/34 boxes match at IoU > 0.95 with the same class.

**Mapping boxes back to source pixels** (`scale_coords`, `yolopx_postprocess.py:89-102`):
- gain = min(384/720, 640/1280) = 0.5; pad_w = 0, pad_h = 12.
- x and y minus pad, then divided by gain, clipped to [0,1280] × [0,720].
- Floats are not rounded (upstream rounds, `tools/demo.py:153`).

On the wire: x1, y1, x2, y2 and conf as float, `classId = int(cls) & 0xFF` (`runner.py:198-206`).

**Drivable area and lane line**
- `da_seg` and `ll_seg` are `(1,2,384,640)`. They are **sigmoid outputs** (`seg_head` in `source/yolopx/lib/models/common.py:2151-2165`; `YOLOP.py:59`, :94), not logits, even though the runtime calls them logits. Measured `da_seg` range 0.43–1.0.
- `segmasks_from_logits` (`yolopx_postprocess.py:105-127`):
  1. Strip the padding rows (`pad_h:384-pad_h`) and columns (:118).
  2. Take ch1 − ch0 and `cv2.resize` it bilinearly to 1280×720 (:120-121).
  3. Threshold `> 0`, equivalent to argmax (:122).
  4. `da = (da - ll) == 1`, so lane pixels are removed from the drivable area (:126). This matches `tools/demo.py:128-142`.
- Encoding (`runner/mask_codec.py:17-41`):
  - row-major RLE records of `uint16 LE count` + `uint8 value (0/1)`, runs split at 65535;
  - published as `daMaskRle` / `llMaskRle` with `maskWidth=1280`, `maskHeight=720` (`runner.py:190-191`, :221-224);
  - schema at `message.capnp:310-338`;
  - UI decoder: `ui/newwidgets/mask_codec.py:13-30`.

## 5. DTCP planner

**Inputs** (`runner.py:63-69`, :86-90; same as `dtcp_infer.py:145-152`):

| Tensor | Shape | Content |
|---|---|---|
| `image` | (1,3,256,928) | the full camera frame, independent of YOLOPX |
| `state` | (1,9) fp32 | `[speed_mps/12, target_lat_right_m, target_fwd_m, one_hot(command, 6)]` |
| `target_point` | (1,2) | the same target again; fed to the GRU at each step (`source/dtcp/model.py:157`) |

- Speed: CarState `speedKph/3.6` from `tcp://127.0.0.1:5592`, 0 if no CarState arrives (`runner/ego_state.py:16`, :49-51).
- Command: CLI, default 2 (`run.py:39`). Mapping is 0=LEFT, 1=RIGHT, 2=STRAIGHT, 3=LANE_FOLLOW, 4=CHANGE_L, 5=CHANGE_R.
- Target: CLI, default (0, 20) m (`run.py:42`). Training used the next route waypoint at ≥30 m ahead (`docs/DTCP_deployment.md:84`).

**Outputs**
- `pred_wp (1,4,2)`:
  - built by cumulative GRU steps, `x = dx + x` (`model.py:156-164`);
  - ego frame, metres, **col0 = lateral right-positive, col1 = forward**;
  - times t+0.5, 1.0, 1.5, 2.0 s (`docs/DTCP_deployment.md:87-100`);
  - z implicitly 0.
- `mu`, `sigma` (1,2): Softplus Beta α and β over (acc, steer) (`model.py:110-111`).
- `pred_speed` (1,1): multiplied by 12 to give m/s (`runner.py:94`).

**Postprocess** (`beta_mode.py:34-42`):
- mode = (α−1)/(α+β−2), then ×2−1, clipped to [−1,1];
- throttle = max(acc, 0), brake = max(−acc, 0), steer as is.
- The PC `_get_action_beta` (`model.py:236-254`) also handles the α ≤ 1 and β ≤ 1 cases; `beta_mode.py` does not.

**Publishing**
- `trajectory` as `Point2D{x=lat_right, y=fwd}` × 4, plus throttle, steer, brake, `predSpeedMps`, `egoSpeedMps`, `command`, `inferenceMs`, `finite` (`runner.py:184-226`; `message.capnp:319-331`).
- Address: ZMQ `tcp://*:8014` (`run.py:32`).
- UI subscriber: `data_bus.py:37`, :664-718.
- Overlay:
  - masks are drawn as contours scaled from 1280×720 (`main_camera.py:413-464`), and boxes the same way (:466-487);
  - the waypoints use a "virtual perspective", not real projection (:489-519);
  - on the BEV the conversion is (fwd, left = −lat) (:583).

## 6. Rate and latency

- Target **10 Hz** (`run.py:30`), paced by sleep (`runner.py:142`, :252-254). Camera is 30 fps.
- `inferenceMs` covers only `_run_one_frame`: preprocessing, both TRT runs and postprocessing. It excludes camera read and RLE encoding (`runner.py:169-182`).
- Numbers in the docs are PC figures or estimates only:
  - RTX 4090: ~3.5 ms inference + 1.5 ms NMS (`docs/YOLOPX_deployment.md:72`);
  - Orin AGX estimates of 150–250 FPS FP16 (:239-242) and the ≥10 FPS target (`workplan.md:34`) are not measurements.
- **My measurement tonight** (`parity.py`): median of 50 iterations after 10 warm-up runs, 1280×720 frame, includes host↔device copies, power mode not checked.

| Stage | ms |
|---|---|
| YOLOPX preprocessing | 8.13 |
| YOLOPX TRT | 27.8 |
| NMS | 0.79 |
| Segmentation postprocess | 2.18 |
| DTCP preprocessing | 7.74 |
| DTCP TRT | 6.78 |
| **Total** | **54.67** |

At 54.67 ms the serial pipeline tops out around 18 Hz.

## 7. Files a new inference node must copy

| Absolute path | Functions / items |
|---|---|
| `/home/tonyho/model/jetson_bundle/jetson_runtime/preprocess.py` | `IMAGENET_MEAN/STD`, `_imagenet_normalize`, `_letterbox`, `preprocess_yolopx`, `preprocess_dtcp` |
| `/home/tonyho/model/jetson_bundle/jetson_runtime/yolopx_postprocess.py` | `CLASS_NAMES`, `_xywh_to_xyxy`, `_nms`, `nms_yolopx`, `scale_coords`, `segmasks_from_logits` |
| `/home/tonyho/model/jetson_bundle/jetson_runtime/beta_mode.py` | `beta_mode_action` |
| `/home/tonyho/model/jetson_bundle/jetson_runtime/trt_runner.py` | `TRTRunner` (pycuda, TRT 10 tensor API) |
| `/home/tonyho/model/driverguard/runner/runner.py` | `_build_state_vec`, `_run_one_frame` (thresholds 0.30/0.45, `pred_speed*12`), field mapping in `main()` :184-226 |
| `/home/tonyho/model/driverguard/runner/mask_codec.py` | `encode_rle`, `decode_rle` |
| `/home/tonyho/model/driverguard/runner/camera_reader.py` | `_build_pipeline`, `FrontCameraReader` (change :88 to `COLOR_RGBA2BGR`) |
| `/home/tonyho/model/driverguard/runner/ego_state.py` | `SpeedProvider` |
| `/home/tonyho/driveragent/message/message.capnp` | `Point2D` (:218-221), `DriverGuardDetection`, `DriverGuardResult` (:310-338) |
| `/home/tonyho/model/jetson_bundle/jetson_runtime/viz_helpers.py` (optional) | `project_wp_to_image`, `blend_seg_masks`, `draw_box`, `CLASS_COLORS_BGR` |

Parity fixtures:
- `/home/tonyho/model/jetson_bundle/samples/cam_front/*.jpg`
- `/home/tonyho/model/jetson_bundle/samples/scene_manifest_subset.json`
- `/home/tonyho/model/jetson_bundle/samples/reference_yolopx/e036014a715945aa965f4ec24e8639c9_yolopx.npz` (34 frames, keys `fNNNN_boxes/da/ll` at 900×1600; the 3 jpgs correspond to f0000–f0002)

On those 3 frames my engine run gives da agreement ≥ 0.9996 and ll agreement ≥ 0.9999 against the reference.

Not found:
- The `.claude/` notes under `/home/tonyho/model/jetson_bundle/.claude` are an empty directory.
- `/tmp/cam0` does not exist on this machine tonight.