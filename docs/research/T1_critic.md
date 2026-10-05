# Completeness critic: gaps in the model reports and what I found

All checks were read-only. My scripts are in `/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad/critic/` (`magic.py`, `eng.py`, `ep_eng.py`, `ep_eng2.py`), and every one has exited.

**The main fixes MODELS.md needs:**
- Add a 6th engine: the one hidden inside the `.ep` file. Its tensors are named `x` and `output0..3`, not `images`/`feat_*`.
- The original YOLOPX (epoch-195) detects 1 class, not BDD classes.
- The old stack launches `tools/demotext.py`, not `demotext2.py`.
- Add the SparseDrive class lists, quoted from code.
- System 1's correct crop is "drop the top 140 rows, keep 140:396", with a 0.55 scale on 1280×720.

## G1. Engine inventory: is it complete? Mostly closed; one hidden engine found

I scanned every file of 200 KB or more on `/` (excluding /proc, /sys, /dev, /run, /snap) for the TensorRT plan header `ftrt` at byte 0. The engine header was checked with xxd on `dtcp_v1_fp16.engine`. Exactly 5 raw plan files exist, the same 5 the reports list:
- `/home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt`
- `/home/tonyho/model/sparsedrive/run/convnext_backbone_fp16.trt`
- `/home/tonyho/model/sparsedrive/run/resnet_backbone_fp16_orin.trt`
- `/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine`
- `/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine`

**One part is NOT closed:** `/data` is `drwx------ root` and could not be read without sudo. Engines stored there are unknown. `/media/tonyho` and `/mnt` are empty, and the only other filesystem is `/boot/efi`.

**New: a 6th engine sits inside `/home/tonyho/model/sparsedrive/run/convnext_backbone_trt.ep`.** It is stored base64-encoded, starting at byte 121 of the inner `archive/data.pkl` of zip entry `convnext_backbone_trt/data/constants/model.pt`. It is the only engine in there (1 occurrence).
- Decoded size is 65,931,356 B, which equals the size declared in its header.
- It deserializes on TRT 10.3.0 with the same "across different models of devices" warning as the SparseDrive engines.
- 228 layers. Exact I/O:

```
INPUT  x       (6, 3, 450, 800)   FLOAT kLINEAR
OUTPUT output0 (6, 256, 112, 200) FLOAT kLINEAR
OUTPUT output1 (6, 256, 56, 100)  FLOAT kLINEAR
OUTPUT output2 (6, 256, 28, 50)   FLOAT kLINEAR
OUTPUT output3 (6, 256, 14, 25)   FLOAT kLINEAR
```

The other-models report gave shapes for this file only from `model.json`. The real tensor names are `x` and `output0..3`, so it cannot be used with the SparseDrive wrapper, which hard-codes `images` and `feat_0..3` (`/home/tonyho/model/sparsedrive/run/hybrid_inference.py:123`, `:137`).

No code under `/home/tonyho/model/sparsedrive` loads a `.ep` file. I grepped `*.py` and `*.sh` for `torch.export.load`, `torch_tensorrt` and `.ep`, and the only hits are the optional install step in `install.sh:157-167`. **How it is loaded: NOT FOUND.**

## G2. Re-reading I/O from the 5 raw engines: confirmed, no contradictions

My own `eng.py` output matches the driverguard and other-models reports exactly for names, shapes, FLOAT/kLINEAR format, 1 profile, layer counts and device memory:

| Engine | Layers | Device memory | Plan warning |
|---|---|---|---|
| convnext_backbone_fp16_orin.trt | 415 | 383,846,400 | yes |
| convnext_backbone_fp16.trt | 318 | 487,065,600 | yes |
| resnet_backbone_fp16_orin.trt | 81 | 237,619,200 | yes |
| dtcp_v1_fp16.engine | 77 | 11,403,264 | no |
| yolopx_v2_fp16.engine | 397 | 43,450,368 | no |

The system1 report listed the ResNet engine as "not read". The other-models report and my run both cover it:
- input `images (6,3,450,800)`
- outputs `feat_0 (6,256,113,200)`, `feat_1 (6,256,57,100)`, `feat_2 (6,256,29,50)`, `feat_3 (6,256,15,25)`

## G3. How the SparseDrive engines are loaded: closed

The other-models report never said which CUDA library is used. It is **torch CUDA, not pycuda**, in class `TensorRTBackbone`, `/home/tonyho/model/sparsedrive/run/hybrid_inference.py`:
- comment "NO pycuda, use PyTorch CUDA context" at :31
- `trt.Logger(WARNING)` at :72, then `deserialize_cuda_engine` at :75-77, then `create_execution_context` at :79
- one `torch.empty` buffer per I/O tensor, with dtype from `DTYPE_MAP` at :58-61, bound with `set_tensor_address(name, buf.data_ptr())` at :87-102
- `execute_async_v3(stream_handle=torch.cuda.current_stream().cuda_stream)` and `synchronize` at :130-132
- returns clones of `feat_0..feat_3` at :135-138
- used only if the engine file exists and TRT imports (:272-274); otherwise the PyTorch backbone is used (:277-280)
- default engine is `--engine convnext_backbone_fp16.trt` (`/home/tonyho/model/sparsedrive/run/camera_integration.py:662`); for `hybrid_inference.py` run directly it is `backbone.trt` (`:654`)

## G4. SparseDrive class names: closed, quoted from code

`/home/tonyho/model/sparsedrive/run/hybrid_inference.py:491-494`:
```
DET_CLASS_NAMES = ['car','truck','construction_vehicle','bus','trailer','barrier','motorcycle','bicycle','pedestrian','traffic_cone']
```
`/home/tonyho/model/sparsedrive/run/hybrid_inference.py:496-498`:
```
MAP_CLASS_NAMES = ['lane_divider','road_boundary','pedestrian_crossing']
```

The same lists are in `/home/tonyho/model/sparsedrive/models/sparsedrive_model.py:43-49`, and they match the capnp comment the old-stack report cited.

Detection postprocessing (`hybrid_inference.py:512-559`):
- score = sigmoid(class).max × mean(sigmoid(quality)), threshold 0.3 (:520-530)
- there is no NMS; results are sorted by score (:556)

Map postprocessing: `max_scores > threshold` (:569-572).

## G5. SparseDrive preprocessing: closed, plus a pitfall

The camera path does **not** use `HybridSparseDrive.preprocess`:
1. `camera_integration.py:171-173` converts with `cv2.COLOR_RGBA2RGB`. This is correct, given that OpenCV returns RGBA unchanged, as both the driverguard and system1 reports measured.
2. `preprocess_frames` (`camera_integration.py:308-324`) does `cv2.resize` to (800, 450) with the default INTER_LINEAR, then `/255`, then HWC→CHW. The result is float32 in [0,1].
3. That goes straight to `model.inference` (`:614-617`; signature at `hybrid_inference.py:363-374`).

**Pitfall:** `hybrid_inference.py:331-360` `preprocess()` assumes BGR uint8 and does `COLOR_BGR2RGB` (:349). Feeding it the RGB frames from the camera path would swap R and B. The other-models report cites :331-360 as if it were in the live path; it is not.

**Camera order:** `run/calibration.json` slots are CAM_FRONT, FRONT_RIGHT, FRONT_LEFT, BACK, BACK_LEFT, BACK_RIGHT (lines 4, 10, 16, 22, 28, 34). Socket `/tmp/cam{i}` goes into slot i (`camera_integration.py:83-85`, `:164`). With the vehicle order 0 front, 1 right, 2 left, 3 right-back, 4 left-back, 5 back, SparseDrive has the same slot 3/5 swap as System 1 (B5). The other-models report missed this.

## G6. Original YOLOPX (epoch-195): wrong script cited and wrong class info; closed

**Contradiction between reports.** The old-stack report says the supervisor launches `tools/demotext.py`. The other-models report documented `tools/demotext2.py`. The real launcher is `exec "$PY" tools/demotext.py ...` (`/home/tonyho/driveragent/startmodel.sh:60-66`). `demotext.py` (1192 lines) differs from `demotext2.py` (990 lines), mostly in added cleanup code. The facts MODELS.md needs come from `demotext.py`:
- `gst-launch` RGBA shmsrc → nvvidconv → videoconvert → `jpegenc quality=70` → multifilesink (`tools/demotext.py:184-193`)
- `cv2.imread` (:980)
- `cv2.resize` to net 640×320 (defaults at :694-705, resize at :996)
- `COLOR_BGR2RGB` (:997)
- ToTensor + ImageNet Normalize (:45-53)
- `.half()` (:806)
- `non_max_suppression(conf, iou, agnostic=False)` (:1011-1017)
- PUB default `tcp://*:8002` (:738)
- startmodel defaults are conf 0.3 and iou 0.45 (`startmodel.sh:13-14`)

**Class names (missing from the other-models report).** The repo model has 1 class:
- `[-1, YOLOXHead, [1]]` (`/home/tonyho/model/yolopx/YOLOPX/lib/models/YOLOP.py:41`)
- `self.nc = 1` (`:126`)
- `self.names = [str(i) for i in range(self.nc)]` → `['0']` (`:159`)
- `demotext.py:809` takes names from the model.

The weights confirm it: in `epoch-195.pth`, `model.2.cls_preds.{0,1,2}.weight` have shape (1,192,1,1). This is the real file, read with torch.load on CPU. So the "BDD100K" model detects a single class, not the 10 BDD classes. This agrees with the driverguard report's note that the repo is the 1-class version.

## G7. DriverGuard: verified, plus one citation fix

- **Class list:** verified at `/home/tonyho/model/jetson_bundle/jetson_runtime/yolopx_postprocess.py:14-15` and `/home/tonyho/model/jetson_bundle/source/yolopx/lib/models/YOLOP.py:159-160`.
- **Colour bug line:** verified, `/home/tonyho/model/driverguard/runner/camera_reader.py:88` `cv2.COLOR_BGRA2BGR`.
- **Pipeline line numbers:** the shmsrc caps are at `camera_reader.py:19-20`, inside the driverguard report's `:17-24`. The old-stack citation `:13-20` is slightly off. No contradiction in substance.
- **DTCP command mapping:** the driverguard report gave no path for it. Citations:
  - `/home/tonyho/driveragent/message/message.capnp:328`
  - `/home/tonyho/model/driverguard/run.py:40-41`
  - `/home/tonyho/model/jetson_bundle/source/dtcp/dtcp_infer.py:56-57` (`CMD_NAMES = {0:"LEFT",1:"RIGHT",2:"STRAIGHT",3:"LANE_FOLLOW",4:"CHANGE_LEFT",5:"CHANGE_RIGHT"}`)
- **DTCP resize (OpenCV vs PIL):** the driverguard report did not measure the numeric difference. Still open, but minor.

## G8. System 1 crop direction (B2) and resize (B1): mostly closed

The full `system1_deploy.pth['preprocessing']` (real file, read on CPU) is:
```
{'mean':[0.485,0.456,0.406],'std':[0.229,0.224,0.225],'resize':0.44,'crop':'top','final_size':[256,704],'raw_size':[900,1600]}
```
`model_info.input_shape` is `[1,6,3,256,704]`.

The system1 report left out `raw_size [900,1600]`. The 0.44 scale is defined for nuScenes 1600×900 input: that gives 704×396, and cropping to 256 removes 140 rows.

The sibling code uses the identical config (`STORED_W_V3, STORED_H_V3 = 1600, 900`, `VAL_RESIZE_V3 = 0.44`, `FINAL 704×256`), and its "top-crop" means `crop_h = new_h - FINAL_H`, i.e. it keeps the **bottom** 256 rows:
- `/home/tonyho/model/stage2/training_convnext/evaluate.py:51-55`, `:116-142`
- the same in `/home/tonyho/model/stage2/training_convnext/evaluate.py:81-85` and `train.py:336-337`

The runner and the reference do the opposite:
- `runner/runner.py:131-143` uses `raw_size` overridden to (720,1280) at `:217`, so 0.44 gives 316×563, then crops `[0:256, 0:704]`, which keeps the top rows and stays 563 wide.
- `run_system1.py:91-93` also uses `crop_y = 0`.

Because 1280×720 has the same aspect ratio as 1600×900, the faithful equivalent for the live cameras is: scale 0.55 → 704×396, keep rows 140:396, crop_x = 0. **Remaining gap:** System 1's own training code is still NOT FOUND, so the crop direction is strongly supported by the sibling code but not proven.

## G9. Gaps I could not close

- **`/data`:** permission denied without sudo, so its contents are unknown.
- **Cause of the "across different models of devices" warning** on the 3 SparseDrive engines and the `.ep` engine: not determined. The DriverGuard engines show no warning.
- **System 1 heading convention and the sign of lateral x:** no training code on disk (as the system1 report says).
- **Live camera streams:** `/tmp/cam0..5` do not exist tonight, so no live check was possible. The RGBA byte order rests on the reports' own GStreamer `videotestsrc` tests.