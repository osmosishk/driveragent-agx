# Other models on disk (everything except DriverGuard and System 1)

Jetson AGX Orin 64GB (`/proc/device-tree/model`), L4T R36.4.7, TRT 10.3.0, power mode MAXN (`nvpmodel -q`). Everything here was checked read-only. My own snippets live only in `/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad/other-models/`. I did not launch any DriverAgent or SparseDrive script.

## Summary

- **SparseDrive is not usable.** All 3 TensorRT engines load, but the two ConvNeXt engines give the wrong numbers.
  - Their features differ from their source ONNX run in ONNX Runtime: cosine 0.12 and 0.39.
  - The ResNet engine is numerically correct (cosine 1.00000 against its ONNX), but `best.pth` has no ResNet weights. Its feature shapes (113×200 etc.) also differ from what the ConvNeXt-trained head expects.
  - The `.ep` exported program outputs 100% NaN.
- **The head is PyTorch only.** It runs on the slow grid_sample fallback because the custom CUDA op is missing here. The guide measured 1.25–1.7 s per frame.
- **Camera calibration is a placeholder** (identity extrinsics).
- **stage2 cannot load at all.** Both `.pth` files are truncated zip archives.
- **The original YOLOPX (epoch-195) is a working PyTorch-only pipeline**, superseded by the DriverGuard `yolopx_v2` engine.

## 1. Inventory: every engine, plan and .ep file on disk

Search: `find / -xdev \( -iname '*.engine' -o -iname '*.trt' -o -iname '*.plan' -o -iname '*.onnx' \)`, plus symlinks and a separate scan for `.pth/.pt/.ep`. No `.plan` files exist. The only symlinks are `/home/tonyho/model/driverguard/engines/*.engine`, which point to `jetson_bundle/engines/`.

| Path | Size (bytes) | Date | sha256[:16] | Loads on TRT 10.3? |
|---|---|---|---|---|
| /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16.trt | 63,330,348 | 2026-04-02 08:21 | 653ec9617d4d6613 | OK, with warning ¹ |
| /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt | 63,276,916 | 2026-04-03 21:10 | 3d0ece003f5e61a4 | OK, with warning ¹ |
| /home/tonyho/model/sparsedrive/run/resnet_backbone_fp16_orin.trt | 54,297,884 | 2026-04-03 18:19 | d90f93dc43c1d62d | OK, with warning ¹ |
| /home/tonyho/model/sparsedrive/run/convnext_backbone_trt.ep (torch_tensorrt ExportedProgram, not a raw plan) | 87,918,879 | 2026-04-02 | e28b0f0ae8612ebc | Loads with `torch.export.load` + torch_tensorrt 2.8.0, with the same warning. **Output is 100% NaN.** |
| /home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine (DriverGuard, for completeness) | 55,987,852 | 2026-05-11 16:24 | 1071ea90213eddc2 | OK, no warning |
| /home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine (DriverGuard, for completeness) | 70,643,388 | 2026-05-11 16:22 | 3412bafa057a3a76 | OK, no warning |

¹ Exact stderr: `[TRT] [W] Using an engine plan file across different models of devices is not recommended and is likely to affect performance or even cause errors.`
- `trt_build.log:90` shows builds on this run on the same GPU (UUID `GPU-2e73499a-2d3d-5ef5-b705-2cfeb9b34079`).
- MODE_50W and MAXN both use `TPC_PG_MASK 0` (`/etc/nvpmodel.conf`).
- The cause of the warning is NOT determined.

### Engine I/O

All tensors are FLOAT, kLINEAR, 1 optimization profile, static shapes.

| Engine | INPUT | OUTPUTs | Device memory | Layers |
|---|---|---|---|---|
| convnext_backbone_fp16.trt | `images (6,3,450,800)` | `feat_0 (6,256,112,200)`, `feat_1 (6,256,56,100)`, `feat_2 (6,256,28,50)`, `feat_3 (6,256,14,25)` | 487,065,600 | 318 |
| convnext_backbone_fp16_orin.trt | same | same | 383,846,400 | 415 |
| resnet_backbone_fp16_orin.trt | `images (6,3,450,800)` | `feat_0 (6,256,113,200)`, `feat_1 (6,256,57,100)`, `feat_2 (6,256,29,50)`, `feat_3 (6,256,15,25)` | 237,619,200 | 81 |
| convnext_backbone_trt.ep | `x (6,3,450,800)` | 4 tensors with the same shapes as the ConvNeXt engines, strides channels-last (from the `models/model.json` archive entry); torch 2.8.0 | – | – |
| dtcp_v1_fp16.engine | `image (1,3,256,928)`, `state (1,9)`, `target_point (1,2)` | `pred_wp (1,4,2)`, `mu (1,2)`, `sigma (1,2)`, `pred_speed (1,1)` | 11,403,264 | 77 |
| yolopx_v2_fp16.engine | `image (1,3,384,640)` | `det (1,5040,15)`, `da_seg (1,2,384,640)`, `ll_seg (1,2,384,640)` | 43,450,368 | 397 |

### Numeric check (my own snippets, MAXN)

Method:
- Fixed random input in [0,1], shape (6,3,450,800).
- PyTorch reference: `SparseDriveConvNeXtBackbone` with `best.pth` `backbone_state_dict`. Result: "All keys matched".
- Source ONNX run on ONNX Runtime CPU.
- The runner was validated on the ResNet engine as a control.

| Engine | Cosine vs its ONNX (ORT) | Cosine vs `best.pth` PyTorch | TRT latency (6 cams) |
|---|---|---|---|
| resnet_backbone_fp16_orin.trt | **1.00000** (maxabs 0.14) vs `backbone_450x800.onnx` | n/a (shapes differ, no ResNet weights) | 35.6 ms |
| convnext_backbone_fp16.trt | 0.121 vs `convnext_nchw_backbone.onnx` | 0.13 / 0.23 / 0.25 / 0.19 (feat_0..3) | 125 ms |
| convnext_backbone_fp16_orin.trt | 0.390 vs `convnext_backbone_nchw_orin.onnx` | 0.04 / 0.04 / 0.07 / −0.001 | 112 ms |
| convnext_backbone_trt.ep | – | NaN everywhere (also on all-zero input) | – |

- The two ConvNeXt engines are therefore numerically broken. My guess, not verified, is FP16 overflow in the LayerNorm or GRN (`ReduceL2`) blocks.
- The ResNet engine is correct but has no matching head weights.
- Older docs claim 5–8 ms for the backbone (`convnext_jetson_deploy.md:24-27`). This disagrees with my measurements and with `OPTIMIZATION_GUIDE.md:7`, which measured 136 ms.

## 2. ONNX files

Read with `onnx.load(load_external_data=False)`.

| Path | sha256[:16] | Opset / producer | Inputs → Outputs | Notes |
|---|---|---|---|---|
| sparsedrive/run/backbone_450x800.onnx (107.6 MB) | 210e678b7377dd98 | 18 / pytorch 2.11.0.dev | `images (6,3,450,800)` → `feat_0..3` (113×200, 57×100, 29×50, 15×25) | ResNet+FPN; first nodes `Sub mean`, `Div std` (ImageNet) |
| sparsedrive/run/convnext_nchw_backbone.onnx (122.5 MB) | bbcd6bda9ea3771c | 17 / pytorch 2.8.0 | `images (6,3,450,800)` → 112×200, 56×100, 28×50, 14×25 | **Weights match `best.pth`** (stem diff 0.0). ORT vs PyTorch maxabs ≤0.066. Normalization is in the graph. This is the source named in `install.sh:173-174` and `package.sh:46`. |
| sparsedrive/run/convnext_backbone_450x800.onnx (123.5 MB) | 3d360066cad53080 | 18 / pytorch 2.11.0.dev | same shapes | Weights match `best.pth`. Native LayerNorm and Transpose. The trtexec build failed (`trt_build.log:6271`). |
| sparsedrive/run/convnext_backbone_nchw_ln.onnx (123.5 MB) | 06fffce03a502be3 | 18 / pytorch 2.11.0.dev | same | Weights match `best.pth` |
| sparsedrive/run/convnext_backbone_nchw_orin.onnx (123.7 MB) | 4b5cf16e9c9cf639 | 18 / pytorch 2.11.0.dev | same | **Weights do NOT match `best.pth`** (stem maxabs 0.0276; ORT output cosine ≈0 vs reference). It came from a different checkpoint, which I did not find on disk. |
| system1/backbone_nchw.onnx | a31813fca8a29d1f | 18 | `images (num_cams,3,256,704)` → 4 feats | System 1, out of scope |
| jetson_bundle/onnx/dtcp_v1.onnx, yolopx_v2.onnx | 794373ce8d25aaf9, 3a49f4ebe346bea4 | 13 | dynamic batch | DriverGuard, out of scope |
| /usr/src/tensorrt/data/mnist/mnist.onnx, ResNet50.onnx; /usr/src/jetson_multimedia_api/data/Model/resnet10/resnet10_dynamic_batch.onnx | 2f06e72de813a863, 78eecdb9354e7136, 48c26511600dd95a | 8 / 9 / 9 | 1×1×28×28→10; 1×3×224×224→1000; −1×3×368×640→cov/bbox | NVIDIA SDK samples; ignore |

## 3. Root cause of the "ConvNeXt cannot build on Orin" claim

- The docs say TRT 10.3 cannot implement `ForeignNode[node_permute...node_permute_1]` (`EXPORT_INSTRUCTIONS_FOR_5090.md:5-17`, `OPTIMIZATION_GUIDE.md:89-93`).
- The log shows the build ran with a tiny workspace. `trt_build.log:1` used `--memPoolSize=workspace:2048MiB`, which trtexec parsed as `workspace: 0.00195312 MiB` (`trt_build.log:7`).
- The tactics were then skipped with `Exceeded mem budget of 2432. Need 77952000` just before `Error Code 10 ... Could not find any implementation`.
- So the likely real cause is the workspace unit (`MiB` was not understood), not a kernel limitation. Not re-tested.

## 4. Per-model findings

### A. SparseDrive (`/home/tonyho/model/sparsedrive`)

**What it is**
- Full SparseDrive: ConvNeXt V2-Tiny + FPN backbone, then det/map/motion head.
- Outputs: 10 nuScenes detection classes, 3 map classes, ego plan of 6 steps (`OPTIMIZATION_GUIDE.md:34-57`; `run/hybrid_inference.py:491-498`).
- Only the backbone exists in TRT. The head is always PyTorch (`run/hybrid_inference.py:285-310`) with FP16 autocast (`run/hybrid_inference.py:312-315`, `:422-424`).

**Checkpoint**
- `checkpoints/best.pth` (447,399,433 B, sha 71eb970aece969d3) loads.
- Keys: `epoch=5`, `backbone_type='convnext_v2'`, `convnext_size='tiny'`, `backbone_state_dict` (214 keys, **0 `resnet.*` keys**), `head_state_dict` (1008 keys).
- Anchors are non-zero in the checkpoint: det (900,11), map (100,40), motion (10,6,12,2), plan (3,6,6,2).
- The kmeans `.npy` files the code looks for (`models/sparsedrive_head.py:263-267`, `:596-609`) exist nowhere on disk. The checkpoint anchors override them, so this is not blocking.

**Cameras**
- 6 surround cameras: CAM_FRONT, FRONT_RIGHT, FRONT_LEFT, BACK, BACK_LEFT, BACK_RIGHT (`run/calibration.json:4-36`).
- Read from GStreamer `shmsrc` sockets `/tmp/cam0..5`, RGBA 1280×720 at 30 fps (`run/camera_integration.py:5`, `:47-51`, `:83-93`).

**Input and preprocessing**
- Resize to 800×450, then /255, HWC→CHW, giving (6,3,450,800) float32 in [0,1] (`run/camera_integration.py:308-324`; `run/hybrid_inference.py:331-360`).
- ImageNet mean/std normalization is inside the engine/ONNX: the first nodes are `Sub mean`, `Div std`. The values in `run/hybrid_inference.py:320-321` are never used.
- The head also needs a (6,4,4) `projection_mat` and `image_wh` (`run/camera_integration.py:263-285`).
- **`run/calibration.json` holds placeholders:** every camera has identity extrinsics and the same intrinsics (`run/calibration.json:5-6`). `OPTIMIZATION_GUIDE.md:176-181` documents the resulting garbage, about 57 false detections per frame.

**Postprocess**
- Exists in Python: `_postprocess_det/_map/_motion` (`run/hybrid_inference.py:512-642`).
- Publishes capnp `SparseDriveResult` (`/home/tonyho/driveragent/message/message.capnp:261-279`) on tcp 8012 (`run/camera_integration.py:686`, `:733`; `driveragent/message/service_list.yaml:44`).
- It depends on the old DriverAgent tree: `sys.path.insert(0,'/home/tonyho/driveragent')` (`run/camera_integration.py:38-40`, `:581`).
- **Safety note:** on startup it runs `lsof -ti:<port> | xargs -r kill -9` (`run/camera_integration.py:723-727`). Do not reuse this as is.

**Custom CUDA op**
- `models/deformable_agg.py:48-79` imports `../projects/mmdet3d_plugin/ops`. `sparsedrive/projects` does not exist, so it falls back to grid_sample (`HAS_CUDA_KERNEL=False`).

**Performance (from the docs, not re-measured)**
- Head 1253–1720 ms, total 1540–2058 ms, about 0.5–0.7 FPS (`OPTIMIZATION_GUIDE.md:7-12`).
- `model.half()` crashed (`OPTIMIZATION_GUIDE.md:18`).

**Dependencies (import check with /usr/bin/python3)**
- Present: timm 1.0.26, zmq 27.1.0, capnp 2.2.0, torch_tensorrt 2.8.0, onnxruntime 1.23.2, pycuda.
- Missing: mmcv, mmdet, mmdet3d. Not needed by `hybrid_inference.py`.

**Doc inconsistency**
- `convnext_jetson_deploy.md:45` lists ConvNeXt outputs as 113×200 and similar. The actual ConvNeXt ONNX and engines give 112×200 and similar. 113×200 is the ResNet shape.

**Complete runnable pipeline on this machine: NO.**
- Code, checkpoint and postprocess exist, but the ConvNeXt engines give wrong features and the `.ep` gives NaN.
- The only correct engine (ResNet) has no matching head weights.
- Calibration is a placeholder.
- Pure PyTorch fallback (`--engine none`) would probably run, but at about 0.5 FPS.

**PyTorch only:** the whole head (det, map, motion, instance bank, deformable aggregation) and the fallback backbone.

### B. stage2 (`/home/tonyho/model/stage2`)

**What it is**
- Stage-2 SparseDrive ConvNeXt V2-T, a single det+map+motion model (`DEPLOY_STAGE2.md:1-5`).
- Recorded results: mAP 0.3116, NDS 0.4631 (`checkpoints/stage2_convnext_v2_lr4/eval_results_temporal.json:2-3`).

**Input**
- 6 cameras, (1,6,3,256,704). The preprocessing resizes, top-crops to 256×704, and ImageNet-normalizes (`training_convnext/evaluate.py:48-51`, `:63-102`; `DEPLOY_STAGE2.md:213-215`).
- This does not match the 450×800 SparseDrive engines.

**Checkpoints: BROKEN**
- `best.pth`: 326,680,576 B, sha 190bf6b2fb61e959.
- `latest.pth`: 320,233,472 B, sha 245691dfcc7126a4.
- Both start with `PK` but have no zip central directory. Exact errors:
  - torch: `RuntimeError: PytorchStreamReader failed reading zip archive: failed finding central directory`
  - zipfile: `BadZipFile File is not a zip file`
- Both sizes are exact multiples of 4096, which suggests a truncated copy.
- The doc expects 427 MB (`DEPLOY_STAGE2.md:21`).

**Other problems**
- No TRT or ONNX artifact ("No TRT engine. Pure PyTorch path", `DEPLOY_STAGE2.md:208-210`). No camera pipeline (`DEPLOY_STAGE2.md:213-215`).
- The CUDA op exists only as x86_64 `.so` builds: `projects/mmdet3d_plugin/ops/deformable_aggregation_ext.cpython-311-x86_64-linux-gnu.so` and `...-38-x86_64...so`. These cannot load on aarch64. The source is there (`ops/src/*.cu`, `ops/setup.py`), but rebuilding is not allowed tonight.
- Wrong directory layout:
  - `run_stage2.py:25` sets `PROJECT_ROOT = Path(__file__).parent.parent`, which resolves to `/home/tonyho/model`, because the script expects to live in `deploy/`.
  - So `training_convnext/evaluate.py` (`run_stage2.py:34-38`) resolves to `/home/tonyho/model/training_convnext`, which does not exist.
  - The default checkpoint path (`run_stage2.py:137`) does not resolve either.
- `models/*.py` are byte-identical to `sparsedrive/models/*.py` (checked with cmp).

**Runnable: NO.** The checkpoint cannot load, and the paths and CUDA op are wrong. PyTorch only.

### C. `/home/tonyho/model/models` and `/home/tonyho/model/models_convnext`

- These are not models, only Python source with no weights.
- `models/*.py` is byte-identical to `sparsedrive/models` and `stage2/models`. Only `__init__.py` differs: it exists here (`models/__init__.py:1-3`) and is missing in sparsedrive.
- `models_convnext/backbone.py` is identical to the SparseDrive and stage2 copies.
- `models_convnext` is used by System 1 (`/home/tonyho/model/system1/system1_model.py:19-21`).
- Not a `models.yaml` entry. Treat it as a System 1 dependency and do not delete it.

### D. YOLOPX original (`/home/tonyho/model/yolopx`)

**What it is**
- The upstream YOLOPX repo (`git remote` = `https://github.com/jiaoZ7688/YOLOPX.git`, HEAD 35627f6), trained on BDD100K (`lib/config/default.py:62`, `:67`).
- Full multitask model: detection + drivable area + lane line.
- Weights: `YOLOPX/weights/epoch-195.pth` (396,551,195 B, 2025-05-29, sha 52e989dc3d15c9e4). Keys are `epoch=195`, `state_dict` (914), `optimizer`.
- No ONNX or engine of these weights exists. The DriverGuard `yolopx_v2` engine comes from different weights (`jetson_bundle/weights/yolopx_v2_epoch30.pth`).

**Camera**
- Single camera: `/tmp/cam0` shmsrc RGBA 1280×720 (`tools/demotext2.py:536-559`).
- Frames go through gst-launch, then JPEG files on disk, then `cv2.imread` (`tools/demotext2.py:55-73`, `:792-804`).

**Input and preprocessing**
- Plain resize to 640×320 (`--net-width/height`, `tools/demotext2.py:560-571`), BGR→RGB, ToTensor, ImageNet normalize (`tools/demotext2.py:42-50`, `:808-810`).
- FP16 PyTorch (`tools/demotext2.py:664-673`, `:813`).

**Postprocess**
- NMS (conf 0.3, IoU 0.45), seg masks upsampled to the original size, contour extraction (`tools/demotext2.py:819-840`).
- Publishes capnp `SelfDrivingPrediction` on `tcp://*:8002`, gated by `SelfDrivingStatus` on 5595 (`tools/demotext2.py:602-617`, `:635-660`).

**Environment**
- `yolopx/venv`: Python 3.10.12, torch 2.8.0 (CUDA True), cv2 4.12.0.

**Runnable: YES, PyTorch only** (not executed tonight, per the safety rules). It needs the old DriverAgent camera shm and capnp schema. Disk-to-JPEG input and no TRT make it slower than, and redundant with, the DriverGuard `yolopx_v2` engine.

## 5. Recommendation for `config/models.yaml`

`/home/tonyho/driveragent-agx/config/models.yaml` does not exist yet.

| id | enabled | Reason |
|---|---|---|
| `sparsedrive_convnext` (`convnext_backbone_fp16.trt` or `_fp16_orin.trt` + PyTorch head + `best.pth`) | **no** (listed) | Backbone engines give wrong output (cos 0.12–0.39 vs ONNX). The `_orin` ONNX/engine also has weights that differ from `best.pth`. Head is PyTorch only on the grid_sample fallback, about 0.5–0.7 FPS. Calibration is a placeholder. Needs 6 surround cameras. |
| `sparsedrive_resnet` (`resnet_backbone_fp16_orin.trt`) | **no** | Engine is correct (cos 1.0, 35.6 ms), but `best.pth` has 0 ResNet backbone keys and the 113-row feature shapes do not match the ConvNeXt-trained head. No compatible head weights on disk. |
| `sparsedrive_convnext_ep` (`convnext_backbone_trt.ep`) | **no** | Output is all NaN. |
| `stage2` | **no** | Both checkpoints are truncated and cannot load. No TRT. CUDA op is x86_64 only. The script's path layout is wrong. Input is 256×704, unlike the SparseDrive engines. |
| `yolopx_v1_bdd` (epoch-195, PyTorch, venv) | **no** (listed as legacy) | Complete but PyTorch only, single front camera, JPEG round-trip input. Superseded by DriverGuard `yolopx_v2_fp16.engine`. |
| `models/`, `models_convnext/` | not a model entry | Shared source code. `models_convnext` is imported by System 1. |
| NVIDIA samples (mnist, ResNet50, resnet10) | not listed | SDK samples. |

**Possible next step, for a later session and not done tonight:** rebuild the ConvNeXt backbone from `sparsedrive/run/convnext_nchw_backbone.onnx`. It is the only verified ONNX: it matches `best.pth` exactly. Use a correctly specified workspace (for example `--memPoolSize=workspace:8192M`) and keep LayerNorm/GRN in FP32 (or try an FP32 build), then check cosine against PyTorch. Even then, SparseDrive stays OFF until the head runs faster and real calibration exists.

Files in my scratchpad folder: `eng.py`, `onnxinfo.py`, `ckpt.py`, `ref.py`, `ref.pt`, `cmp.py`, `cmp2.py`, `ort.py`, `ort_*.npy`, `first.py`.