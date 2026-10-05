# System 1: research report

Everything below was checked read-only. I ran only my own short scripts, from `/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad/system1/` (`inspect_pkg.py`, `onnx_io.py`, `onnx_head.py`, `onnx_mean.py`, `cmpw.py`, `eng_io.py`, `bench.py`, `vocab.py`, `cvtest.py`). They ran with `PYTHONDONTWRITEBYTECODE=1` and `TMPDIR` set to the scratchpad, and all exited. Right now System 1 is not running, nothing listens on :8011, and the camera sockets `/tmp/cam0..5` do not exist.

## Bugs found (details in the sections below)
- **B1, image width:** the live runner feeds 256×563 images, not 256×704.
  - The resize scale comes from the checkpoint, 0.44 (`runner/runner.py:133`). The runner forces `raw_size=(720,1280)` (`runner/runner.py:217`), so the image becomes 563×316, and cropping to `[0:256, 0:704]` (`runner/runner.py:142-143`) leaves it 563 wide.
  - Measured: `_gpu_preprocess` returns `(1, 6, 3, 256, 563)`.
  - The calibration code assumes a different scale, `max(704/1280, 256/720)=0.55`, and an image size of 704×256 (`runner/calibration.py:143-149`, `runner/calibration.py:205`). So the projection matrices and `image_wh` do not match the real image.
- **B2, crop direction (inferred):** `run_system1.py:91-93`, `runner/runner.py:143` and `DEPLOY_INSTRUCTIONS.md:378` keep rows 0:256, the top of the image (sky). The checkpoint only says `'crop': 'top'` (from `system1_deploy.pth['preprocessing']`). In the sibling ConvNeXt training code, "top-crop" means *remove* the top and keep the bottom: `crop_h = new_h - FINAL_H` (`/home/tonyho/model/stage2/training_convnext/train.py:336-337`, and `:332` "Bottom-anchored crop"). System 1's own training code is NOT FOUND on disk, so this is not proven.
- **B3, output axes:**
  - The trajectory's `x,y` are copied straight from the vocabulary. Channel 1 is forward and channel 0 is lateral, with forward heading ≈ +π/2 (the nuScenes LiDAR-frame convention). Measured from the vocabulary files (`vocab.py` above).
  - The schema comment (`message/message.capnp:288`) and the docs (`DEPLOY_INSTRUCTIONS.md:366-371`) say x = forward.
  - The UI (`ui/newwidgets/data_bus.py:637-655`) swaps the axes, which is right. But it also treats the points as per-step deltas and sums them, which is wrong: the points are absolute positions (proof in section 4).
- **B4, calibration:**
  - The JSON files for cam2..cam5 do not exist, so those cameras get an identity placeholder matrix (`runner/calibration.py:189-200`).
  - cam1's JSON has `yaw 0.0` and `"calibrated": false` (`/home/tonyho/driveragent/calibration/camera_1_calibration.json`).
  - Lens distortion is ignored, although k1 = -0.44 for cam0.
- **B5, camera order:**
  - The vehicle order is cam0 front, 1 right, 2 left, 3 right-back, 4 left-back, 5 back (`/home/tonyho/driveragent/calibration/doc/skill.md:8-13`).
  - The nuScenes order is FRONT, FRONT_RIGHT, FRONT_LEFT, BACK, BACK_LEFT, BACK_RIGHT (`/home/tonyho/model/stage2/training_convnext/visualize.py:59-60`).
  - The runner stacks cam0..5 in index order (`runner/camera_reader.py:334-359`), so slots 3 and 5 are swapped compared with nuScenes.

## 1. Is it TensorRT?
**No. System 1 runs fully in PyTorch.** No System 1 engine exists anywhere on disk, and no code builds one.
- **Code:** a grep for `engine|.trt|.plan|build_serialized_network|torch2trt|tensorrt|onnx` over `/home/tonyho/model/system1` hits only the documentation strings.
  - `infer.py:9,37-38,58-61` has a `--trt_engine` argument that is never used: `main()` only loads the scorer package and prints instructions (`infer.py:33-62`).
  - `DEPLOY_INSTRUCTIONS.md:402-436` labels the TRT route "Optional, Later". It says "TRT 10.3 on sm_87 cannot compile the ConvNeXt ONNX pattern" (`:408`), and that the ONNX file's GroupNorm substitution "is NOT numerically exact (cosine similarity ~0.95-0.97)" (`:404`).
  - The suggested command `trtexec ... --saveEngine=backbone_fp16.trt` (`:432-435`, `infer.py:59-61`) was never run: no `backbone_fp16.trt` exists.
- **Disk search:** `find / -xdev` for `*.trt *.engine *.plan *backbone*fp16* *system1*`, plus `~/.cache` and `/tmp`, found no System 1 engine. `~/.cache/torch` holds only one NVRTC kernel cache, and there are no `/tmp/system1_vocab_*` folders. Engines that do exist belong to other models:
  - `/home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt` and `convnext_backbone_fp16.trt`. I read both real files. Each loaded OK with the warning `[TRT] [W] Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.` I/O for both:
    - `INPUT images (6, 3, 450, 800) FLOAT`
    - outputs `feat_0 (6,256,112,200)`, `feat_1 (6,256,56,100)`, `feat_2 (6,256,28,50)`, `feat_3 (6,256,14,25)`, all FLOAT and kLINEAR
    - 1 profile; device_memory 383846400 for `_orin`, 487065600 for the other
    - **The 450×800 input size does not match System 1's 256×704.** They are SparseDrive engines.
  - `/home/tonyho/model/sparsedrive/run/resnet_backbone_fp16_orin.trt` (not read)
  - `jetson_bundle/engines/{dtcp_v1,yolopx_v2}_fp16.engine`, `driverguard/engines/{dtcp_v1,yolopx_v2}_fp16.engine` (not System 1, not read)
- **ONNX I/O, read from the real file** `/home/tonyho/model/system1/backbone_nchw.onnx` with `load_external_data=False`:
  - IR 10, opset 18, producer pytorch `2.11.0.dev20260206+cu128`.
  - `INPUT images ['num_cams', 3, 256, 704] FLOAT`
  - `OUTPUT feat_0 ['num_cams',256,64,176]`, `feat_1 [..,32,88]`, `feat_2 [..,16,44]`, `feat_3 [..,8,22]`, all FLOAT.
  - 464 nodes; external data file `backbone_nchw.onnx.data`.
  - LayerNorm was replaced by GroupNorm (22 `InstanceNormalization` nodes).
  - **The graph normalizes internally:** its first nodes are `Sub(images, backbone.mean)` → `Div(.., backbone.std)`, with mean [0.485,0.456,0.406] and std [0.229,0.224,0.225]. An ONNX/TRT backbone therefore expects **un-normalized RGB in [0,1]**. The PyTorch runner is different: it normalizes before the backbone.
  - All 134 named ONNX weights are bit-identical to `system1_deploy.pth` backbone weights (the MLP weights are reshaped to 1×1 convs). So the ONNX is the v9e backbone, apart from the inexact normalization.
  - Never built into an engine.

## 2. PyTorch vs TensorRT
- **The live path is all PyTorch:** `run.py` → `runner/runner.py:179-181` → `run_system1.load_model` (`run_system1.py:34-72`).
  - It builds `System1Model` (backbone `SparseDriveConvNeXtBackbone` from timm `convnextv2_tiny` + FPN, then `FactorizedScorer`) from `system1_deploy.pth`.
  - The package contains `model_state_dict` (454 keys, fp32), `config`, `vocabulary`, `model_info` (v9e, epoch 12) and `preprocessing`. Params: 47,579,199.
- **Precision:** autocast bf16 by default (`run.py:100-102`, `run_system1.py:103-127`). The note at `run_system1.py:149` says fp16 gives NaN in the heading head. `DeformableFeatureAggregation.forward` always runs in fp32 (`scorer/deformable_agg.py:110`).
- **Custom CUDA op:** `ops/deformable_aggregation_ext*.so` loads with torch 2.8.0 (measured: `DAF` available, `use_deformable_func=True`). It is imported as `system1.ops...` (`scorer/deformable_agg.py:17-28`, `scorer/decoder_layer.py:16-23`). If `/home/tonyho/model` is not on `sys.path`, it silently falls back to `grid_sample`.
- **`system1_scorer.pth`:** scorer weights only (240 keys, vocabulary, config, model_info "Frozen-body heading-only training on v9b base"). It is used only by the stub `infer.py:17-28` and not by the runner.
- **TensorRT:** none.

## 3. Inputs and preprocessing
- **Cameras:** 6 GStreamer `shmsrc` sockets `/tmp/cam0..cam5`, RGBA 1280×720 at 30/1 (`runner/camera_reader.py:253-278`).
  - Read through OpenCV in a background thread that keeps only the latest frame (`runner/runner.py:82-115`).
  - A failed camera reuses its last frame or zeros (`runner/camera_reader.py:345-356`).
  - Color conversion: `cv2.COLOR_RGBA2RGB` (`runner/camera_reader.py:340-341`). I measured that OpenCV 4.10 returns RGBA bytes unchanged, so the result is RGB.
- **The exact live preprocessing** (`runner/runner.py:122-145`, all on the GPU):
  1. uint8 `[6,H,W,3]` → `permute(0,3,1,2)` → float `/255`
  2. `F.interpolate(bilinear, align_corners=False, antialias=False)` to `(int(720*0.44), int(1280*0.44)) = (316, 563)`
  3. crop `[0:256, crop_x:crop_x+704]` with `crop_x = max(0,(563-704)//2) = 0`, giving **256×563** (B1)
  4. `(x-mean)/std` with ImageNet values
  5. `unsqueeze(0)` → `[1,6,3,256,563]` fp32 NCHW
  - The backbone also normalizes on its own, but only when the input lies in [-0.1, 1.1] with max > 0.5 (`/home/tonyho/model/models_convnext/backbone.py:207-210`).
  - The reference `run_system1.preprocess_images` uses torchvision `resize(antialias=True)` (`run_system1.py:75-100`), which differs from the runner's step 2.
  - The intended size is `[1,6,3,256,704]` (`config.py:16`, `model_info.input_shape`).
- **Projection matrices:** `[1,6,4,4]` from ego frame to post-crop pixels, built from `driveragent/calibration/cam{i}.yaml` and `camera_{i}_calibration.json` (`runner/calibration.py:114-209`).
  - Intrinsics are scaled 1920×1080 → 1280×720 → ×0.55.
  - Euler order `Rz@Ry@Rx`; frame swap from body to optical (`:89-111`).
  - `image_wh = [704,256]` for every camera (`:205`).
- **Ego state** `[1,8]` (`runner/ego_state.py:498-514`): `[v, 0, ax, 0, 0, v, cmd0, cmd1]`.
  - v = `CarState.speedKph/3.6`; ax is a finite difference of speed (`:473-485`).
  - Command is always straight `(0,0)` (`runner/runner.py:251`); the encoding is `[1,0]` = left, `[0,1]` = right (`ego_state.py:431-433`).
  - No route input.
- **`scene_ctx=None`:** no agents or map are given (`runner/runner.py:257`). The optional inputs are described at `DEPLOY_INSTRUCTIONS.md:356-360`.
- **Vocabulary**, packed in the .pth and bit-identical to `vocabulary/*.npy`:
  - paths `(1024,30,3)`, velocities `(256,6)`, trajectories `(1024,256,6,3)` plus mask
  - written to temp files at load time (`run_system1.py:44-56`)
  - the comment at `scorer/vocabulary.py:11` wrongly says 40 path points

## 4. Outputs and postprocessing
- **Selection:** the scorer works coarse to fine: 1024→128→20 paths and 256→64→20 velocities (`config.py:38-39`), giving 400 candidate trajectories. Each is scored with 8 metric heads, combined as `σ(coll)·σ(drivable)·σ(dir)·σ(tl) · (5σ(ttc)+5σ(prog)+2σ(lane)+2σ(comfort))`. The argmax is chosen (`scorer/decoder_layer.py:349-367`).
  - Its heading channel is then replaced by `heading_head` (`scorer/decoder_layer.py:369-375`).
  - The output is `trajectory [B,6,3]`. Scores and metric logits are **not returned**; `agent_features` and `map_features` are None (`system1_model.py:281-293`).
- **Timing and positions:** 6 points at 0.5 s steps (0.5 to 3.0 s), in metres (`config.py:32-34`, `DEPLOY_INSTRUCTIONS.md:366-368`).
  - The `x,y` values are **absolute cumulative positions**, not deltas. Measured: `traj[0,0] y = 2.112, 2.287, 2.474, 2.994, 3.183, 3.364` equals `cumsum(vel[0]*0.5)`.
  - Channel 1 is forward: 80% of final points have |ch1| > |ch0|, mean ch1 = +2.38.
  - Vocabulary heading ≈ `atan2(dy,dx)`, so forward ≈ π/2. The sign of lateral x (presumably +x = right, as in nuScenes LiDAR) is not verifiable on disk.
- **Heading convention unresolved:** the docs claim 0 = forward (`DEPLOY_INSTRUCTIONS.md:371`, `message.capnp:289`). The training targets for `heading_head` are NOT FOUND (no training code on disk). With dummy zero images, the regressed headings were within ±0.38 rad.
- **Runner postprocessing:** `.float().cpu()` (`run_system1.py:136`), a finiteness check (`runner/runner.py:270`), then `{"x":ch0,"y":ch1}` + `headings` (`runner/runner.py:148-158`). The `System1Result` message is published with `cmd=0` (`runner/runner.py:274-283`).
- **Schema:** `message/message.capnp:285-294` (timestamp, frame, trajectory `List(Point2D)`, headings, egoSpeedKph, cmd, inferenceMs, finite).
- **UI consumer:** `ui/newwidgets/data_bus.py:631-661` swaps the axes and sums the points (B3). The overlays are `ui/newwidgets/main_camera.py:225-227,291-345` (front camera, extended to 40 m) and `:642-675` (BEV).

## 5. Rate and latency
- **Target rate:** 5 Hz by default (`run.py:86-87`). The loop sleeps only for whatever is left of the period (`runner/runner.py:219,305-307`). `inferenceMs` measures the model only, without preprocessing (`runner/runner.py:253-268`).
- **Documented estimates:** FP32 ~150-250 ms, FP16 ~60-120 ms, TRT backbone ~30-50 ms (`DEPLOY_INSTRUCTIONS.md:394-398`).
- **Measured tonight** (MAXN, GPU at 1.3 GHz, dummy input, 15 runs):

| Width | bf16 | fp32 |
|---|---|---|
| 704 | 213 ms (p50 212.6) | 259 ms |
| 563 (the actual runner shape) | 192 ms | 225 ms |

- **So the 5 Hz target is not reached:** at most about 4.7-5.2 Hz from inference alone.

## 6. Running without the old stack, and what a new node needs
- **Inputs it consumes:**
  - `/tmp/cam0..5` shmsrc (from the old camera producer)
  - `CarState` at `tcp://127.0.0.1:5592` (`runner/ego_state.py:28`); if missing it logs a warning and uses zeros
  - `SelfDrivingStatus` at :5595, only with `--gated` (`runner/runner.py:47-79,203-206`)
  - calibration files in `/home/tonyho/driveragent/calibration` (`runner/calibration.py:33`)
  - imports `message.capnp_pubsub` and the schema from `/home/tonyho/driveragent` (`run.py:80,110`; `runner/runner.py:16`)
- **Outputs:**
  - binds a PUB socket on `tcp://*:8011` (`runner/runner.py:209-210`; `message/service_list.yaml:43`)
  - optional heartbeat to `DaemonStatus` (connects to `:5570`, `message/capnp_pubsub.py:74`)
- **Launch:** `start.py:103` `MODEL_REGISTRY["system1"]`. `--no-cameras` gives an offline run on zero images (`run.py:103-104`).
- **The model itself only needs:** 6 RGB frames, 6 projection matrices, and an 8-dim ego vector.
- **Requirements for a new node:**
  - torch with CUDA (2.8.0 works), timm (1.0.26 present), torchvision and PIL (imported by `models/backbone.py:19,23`), numpy
  - the prebuilt aarch64 cp310 deformable-aggregation extension, or a rebuild from `ops/src` + `ops/setup.py`
  - pyzmq and pycapnp only for the bus
- **Measured GPU memory:** about 216 MB for weights. Peak allocation is 1.12 GB in bf16, with 1.74 GB reserved by the PyTorch caching allocator, plus the CUDA context. A budget of about 2-2.5 GB of unified memory is reasonable.

## 7. Files to copy to reproduce pre/post-processing exactly
- **Model code:**
  - `/home/tonyho/model/system1/{run_system1.py, config.py, system1_model.py}`
  - `/home/tonyho/model/system1/scorer/{__init__,scorer_head,decoder_layer,deformable_agg,keypoints_generator,embedders,vocabulary,losses}.py` (`losses` is imported by `decoder_layer.py:14`)
  - `/home/tonyho/model/system1/ops/{__init__.py, deformable_aggregation.py, *.so, setup.py, src/*}`
  - `/home/tonyho/model/models_convnext/backbone.py` (found through the path `../models_convnext`, `system1_model.py:202-205`)
  - `/home/tonyho/model/models/backbone.py`, for FPN (`models_convnext/backbone.py:33-38`). `models/fpn.py` is not imported, despite `DEPLOY_INSTRUCTIONS.md:52`.
- **Weights:** `/home/tonyho/model/system1/system1_deploy.pth` (it contains the vocabulary and the preprocessing config).
- **Runner (pre/post):** `/home/tonyho/model/system1/runner/{runner.py, camera_reader.py, calibration.py, ego_state.py}`, `/home/tonyho/model/system1/run.py`
- **Calibration data:** `/home/tonyho/driveragent/calibration/{cam0..5.yaml, camera_0_calibration.json, camera_1_calibration.json}`
- **Interface:** `/home/tonyho/driveragent/message/message.capnp` (`System1Result`, `Point2D`:218), `message/capnp_pubsub.py`
- **Consumer side, if its interpretation must match:** `/home/tonyho/driveragent/ui/newwidgets/data_bus.py:631-661`, `ui/newwidgets/cam_projection.py`
- **Optional TRT route:** `backbone_nchw.onnx` + `backbone_nchw.onnx.data` (input must be [0,1] RGB; GroupNorm makes it inexact)