# T4 result: AGX inference node, 5-minute test with real driving recordings

Date: 2026-10-05, 23:01:29 to 23:07:26 (local time). Board: Jetson AGX Orin, 12 CPU cores, 64 GB RAM.

All data in this test is SIMULATED. The simulator replays old recordings. Every result has
`simulated=true` and envelope flag bit0 (rule R13).

## 1. Commands

All commands use `PYTHONPATH=/home/tonyho/driveragent-agx` in `/home/tonyho/driveragent-agx`.

```
# unit tests (before and after the test run)
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_t4_fixes.py tests/test_adapters_parity.py tests/test_manager.py tests/test_publish.py

# simulator pace check (15 s, test ports 16300-16305, no receiver)
.venv/bin/python -m tools.rk_sim --config tests/out/sim_driving.yaml --base-port 16300 --seconds 15 --status-interval 5

# T4 test (production ports 5560-5563, UDP 6000-6005)
.venv/bin/python -m tools.rk_sim --config tests/out/sim_driving.yaml          > tests/out/t4_sim.log   (23:01:27)
.venv/bin/python -m infer.main --config config/infer.yaml                     > tests/out/t4_node.log  (23:01:29)
.venv/bin/python -m tools.sysmon --seconds 330 --out tests/out/t4_sysmon.jsonl                         (23:01:29)
# wait 30 s, then record the internal status (SUB 127.0.0.1:5562, topic "status") for 300 s
.venv/bin/python <scratchpad>/t4/rec_status.py tests/out/t4_status.jsonl 300                          (23:02:04-23:07:04)
.venv/bin/python -m tools.result_viewer --seconds 10 --out tests/out/t4_viewer                         (23:07:04)
# stop: SIGTERM to the node, then to the simulator (sysmon had stopped after 330 s)
```

Simulator configuration: `tests/out/sim_driving.yaml`. It is a copy of `config/sim.yaml` with these
files for each camera (H.265 passthrough, three files in a loop):

| Cam | Role | Files (sessions 8003-20251109_090744, _090844, _090944) |
|---|---|---|
| 0 | front | front/cam0_20251109_090744.mp4, front/cam0_20251109_090844.mp4, front/cam0_20251109_090944.mp4 |
| 1 | right | right/cam1_..._090744, _090844, _090944 |
| 2 | left | left/cam2_..._090744, _090844, _090944 |
| 3 | right-back | right-back/cam3_..._090744, _090844, cam3_20251109_090945.mp4 |
| 4 | left-back | left-back/cam4_..._090744, _090844, cam4_20251109_090945.mp4 |
| 5 | back | back/cam5_..._090744, _090844, cam5_20251109_090945.mp4 |

Note: in session 090944 the files of cam3, cam4 and cam5 have the name suffix `_090945`.

Frame rate: the 2025 files show `r_frame_rate=3000/1` (ffprobe), but `avg_frame_rate` is about 30
(for example 21576/719) and the packet durations vary (for example 0.134667 s, 0.013667 s). The
simulator paces each frame from its buffer duration. It sent 30 fps on all cameras. Simulator
printout: `cam0 cam0_20251109_090744.mp4: IDR interval 256 AU = 8.53 s (... fps 30.01 ...)` and
`final: cam0 30.0 fps(avg) ... sent 10768 err 0/0 late 0` (same for cam1-cam5). The 20260510
sessions were not necessary.

## 2. Models

Time window: 300 status records, node uptime 35.1 s to 334.1 s. Node state: RUNNING in all 300
records. Errors list: empty.

| Model | State | Cameras | FPS avg | FPS min | FPS max | Results in window | GPU memory (estimate) | Engine |
|---|---|---|---|---|---|---|---|---|
| driverguard_yolopx | RUNNING (300/300) | 0, 1, 2, 3, 4, 5 | 46.9 | 39.4 | 56.0 | 13991 (46.8/s) | 163.9 MB | yolopx_v2_fp16.engine:3412bafa057a3a76, trt_match true |
| driverguard_dtcp | RUNNING (300/300) | 0 | 10.0 | 10.0 | 10.0 | 2990 (10.0/s) | 67.0 MB | dtcp_v1_fp16.engine:1071ea90213eddc2, trt_match true |
| system1 | OFF (300/300) | - | 0.0 | 0.0 | 0.0 | 0 | - | engine null (reason in models.yaml) |
| sparsedrive_convnext_orin | OFF (300/300) | - | 0.0 | 0.0 | 0.0 | 0 | - | engine null (reason in models.yaml) |

FPS of YOLOPX is the sum of the six cameras. The viewer counted 78-79 YOLOPX results per camera in
10 s, thus about 7.8 results/s per camera. The limit `max_fps_per_camera: 30` is not reached: the
two YOLOPX workers are almost always busy (see section 7).

GPU memory is the node estimate: engine file + activation + I/O. It is not a measured value.

Latency in ms (p50 / p95 / p99). "Last" = the last status record (60 s window).
"Average" = the mean of the 300 per-second values.

| Model | Stage | Last p50 / p95 / p99 | Average p50 / p95 / p99 |
|---|---|---|---|
| driverguard_yolopx | pre | 15.2 / 27.6 / 43.1 | 15.0 / 25.7 / 36.3 |
| driverguard_yolopx | infer | 21.7 / 30.4 / 42.2 | 21.7 / 30.0 / 36.0 |
| driverguard_yolopx | post | 1.1 / 18.3 / 26.8 | 1.3 / 16.2 / 23.6 |
| driverguard_yolopx | total | 59.5 / 90.7 / 110.3 | 59.5 / 87.4 / 103.1 |
| driverguard_dtcp | pre | 15.4 / 26.2 / 35.6 | 15.2 / 23.3 / 28.7 |
| driverguard_dtcp | infer | 8.8 / 15.0 / 21.5 | 8.6 / 13.3 / 16.6 |
| driverguard_dtcp | post | 0.2 / 0.2 / 0.5 | 0.2 / 0.2 / 0.3 |
| driverguard_dtcp | total | 33.7 / 72.8 / 81.6 | 33.0 / 69.4 / 76.9 |

"total" starts when the frame is ready in the store (it includes the queue time). The p95/p99 of
"post" for YOLOPX is probably caused by the cam0 frames: only cam0 makes the drivable-area and
lane masks (RLE encoding). I did not measure post time per camera.

Publisher (5560): rate avg 56.9/s (min 49.2, max 66.0), results_total 1927 -> 18909 in the window.
At stop: `results PUB closed (20056 results sent)`.

## 3. Cameras

| Cam | Role | Size | FPS avg / min / max | State | Frames in window | lost_frames | ring_overruns | decoder_errors | seq_resets | decode_ms p50 / p95 (last) |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | front | 1280x720 | 30.1 / 29.0 / 31.0 | SIMULATED 300/300 | 8971 | 5 -> 5 | 5 | 0 | 0 | 16.1 / 23.2 |
| 1 | right | 1280x720 | 30.0 / 29.0 / 31.0 | SIMULATED 300/300 | 8969 | 5 -> 5 | 5 | 0 | 0 | 11.5 / 22.8 |
| 2 | left | 1280x720 | 30.0 / 29.0 / 31.0 | SIMULATED 300/300 | 8970 | 5 -> 5 | 5 | 0 | 0 | 21.0 / 25.6 |
| 3 | right-back | 1280x720 | 30.0 / 29.0 / 31.0 | SIMULATED 300/300 | 8970 | 5 -> 5 | 5 | 0 | 0 | 20.1 / 25.4 |
| 4 | left-back | 1280x720 | 29.9 / 29.0 / 31.0 | SIMULATED 300/300 | 8970 | 5 -> 5 | 5 | 0 | 0 | 15.4 / 24.1 |
| 5 | back | 1280x720 | 29.9 / 29.0 / 31.0 | SIMULATED 300/300 | 8970 | 0 -> 0 | 5 | 0 | 0 | 12.0 / 22.2 |

"5 -> 5": value at the first and at the last record. All losses and ring overruns occurred before the
window (during the start, while the engines loaded). No frame was lost in the 300 s window.
Largest `time_since_last_frame_ms` in the window: 41.3 ms.

## 4. System (tools.sysmon, 1 s samples)

The values are for the 295 samples in the status window (sysmon stopped 4.5 s before the last status
record). CPU % is the mean of all 12 cores (100 % = all cores busy).

| Item | Value |
|---|---|
| CPU total | avg 31.9 %, max 42.5 % (min 28.5 %) |
| infer.main process | avg 280.8 %, max 301.4 % of one core; RSS 1565.0 MB -> 1574.3 MB (+9.3 MB in 300 s) |
| tools.rk_sim process | avg 15.0 % of one core, RSS 79.9 MB |
| GPU load | avg 67.6 %, max 99.9 % (median 75.2 %; 6 samples read 0.0) |
| RAM used | 9293 MB at window start, 9232 MB at window end (whole run: 8735 MB before the node loaded, 9232 MB at the end; total 65894 MB). Swap 0 MB. |
| Temperatures max | cpu 64.6 C, gpu 59.7 C, soc0 59.6 C, soc1 59.0 C, soc2 60.0 C, tj 64.6 C |
| Power (sum of INA3221 rails) | avg 27.73 W, max 36.84 W |
| Power per rail (avg / max) | VDD_GPU_SOC 14.33 / 19.86 W, VDD_CPU_CV 3.12 / 6.36 W, VIN_SYS_5V0 7.72 / 8.49 W, VDDQ_VDD2_1V8AO 2.56 / 3.02 W |

A dashboard process (`dashboard.main`, not started by T4) also ran during the test.

## 5. Viewer (tools.result_viewer, 10 s, after the status recording)

```
SUB tcp://127.0.0.1:5560 for 10 s (expected schema hash 0xafcaff02)
messages: {'messages': 575, 'ok': 575}
flags set (count): {'bit0 source_is_replay': 575, 'bit1 time_uncertain': 575, 'bit2 degraded': 0}
results per (model, cam) kept: {'driverguard_dtcp/cam0': 105, 'driverguard_yolopx/cam0': 79, 'driverguard_yolopx/cam1': 79, 'driverguard_yolopx/cam2': 78, 'driverguard_yolopx/cam3': 78, 'driverguard_yolopx/cam4': 78, 'driverguard_yolopx/cam5': 78}
CAM FRAME SEQ DETS SIM   CLASSES / MODELS / NOTE
  0     10523    6 True  car x6 | driverguard_dtcp@10523, driverguard_yolopx@10523 |
  1     10523    5 True  car x5 | driverguard_yolopx@10523 |
  2     10524    4 True  car x4 | driverguard_yolopx@10524 |
  3     10524    1 True  car x1 | driverguard_yolopx@10524 |
  4     10537    0 True  - | driverguard_yolopx@10537 | frame 10522 gone (frame not in recent ring);
  5     10537    0 True  - | driverguard_yolopx@10537 |
wrote 6 camera pictures + all.jpg to /home/tonyho/driveragent-agx/tests/out/t4_viewer
```

Pictures: `tests/out/t4_viewer/cam0.jpg` to `cam5.jpg` and `all.jpg`. Every picture has the red
"SIMULATED" label.

| Cam | What the picture shows |
|---|---|
| 0 front | A two-lane urban road, overcast autumn day, tower blocks on the left. A queue of cars is far ahead. The 6 "car" boxes (scores 0.38-0.50) are on these cars: correct. The green drivable-area contour covers the road surface in front of the car. The red lane-line contours are on the left edge line and on the dashed centre line: correct. The yellow DTCP trajectory goes straight up from the bottom centre (points 2, 3, 4 visible), with the text "virtual perspective, not calibrated; inputs assumed". The DTCP inputs are assumed values (speed 0 m/s, command STRAIGHT, target (0, 20) m), so the trajectory has no real meaning. |
| 1 right | Road on the left, buildings, trees and a fence. 4 small boxes are on cars on the road at the left side: correct. WRONG BOX: one large "car 0.38" box covers the right half of the picture (fence, trees, and the car's own A-pillar and dashboard). No car is in that box. |
| 2 left | Tower block, fence and a road on the right side. 4 small "car" boxes are on cars on the road at the right edge: correct. No wrong box is visible. A soft toy on the dashboard and window reflections have no box. |
| 3 right-back | View through the rear window (fish-eye): the road behind the car, lamp posts, buildings. WRONG BOX: one "car 0.40" box covers the jacket of a person inside the car and part of a building. No car is in that box. |
| 4 left-back | Black picture (real data: this camera is almost black in these sessions). 0 detections: correct. |
| 5 back | Black picture (real data). 0 detections: correct. |

All the detections are class "car". The wrong boxes have low scores (0.38-0.40), near the 0.30
threshold, and they are on large dark or uniform areas near the picture edge (car interior).

## 6. Defects fixed (from the integration and review reports)

| # | Defect (source) | Fix | Evidence |
|---|---|---|---|
| 1 | Old-stream result can be sent after a sender restart; then the camera loses results until the new seq passes the old seq (robustness 1, MEDIUM) | `infer/runner.py`: each camera has an epoch that goes up on each source restart. `FrameScheduler.claim_epoch()` returns the epoch with the frame. `mark_emitted(cam, seq, epoch)` refuses a result of an older epoch. `claim()` stays for compatibility. | `test_scheduler_restart_race_old_stream_result_refused`: the reviewer scenario (seq 9000 claimed, restart, seq 1 sent) now refuses seq 9000 and sends seq 2-7. |
| 2 | Clean SIGTERM stop shows node state ERROR and adds an error entry (robustness 2) | `infer/status.py`: `NodeState.evaluate()` keeps the last state while `stopping` is true. | `test_nodestate_keeps_state_while_stopping`. T4 run: the log has no state change at stop; last state RUNNING, errors list empty. |
| 3 | SIGTERM during start is not acted on until all engines are loaded (robustness 3) | `infer/main.py`: `Node.start(should_stop)`; `main()` gives `stop_ev.is_set`. `infer/models/manager.py`: `ModelManager.start(should_stop)` loads no more models and starts no workers after the stop request. | SIGTERM 1.0 s after launch: process gone after 1.29 s (`stop requested during start: models not started`). SIGTERM 2.6 s after launch (YOLOPX load): gone after 2.20 s (`model driverguard_yolopx loaded, workers not started`, `model driverguard_dtcp and the next models are not loaded`). Before the fix: 4.93 s. `test_manager_start_should_stop_loads_nothing`. |
| 4 | Stale rule checked only at claim, not when the result is sent (robustness 4) | `infer/runner.py`: `_process` drops the result when `frame.age_s() >= store.stale_s` (0.5 s) and counts it in `results_dropped_stale` (also in the manager status extra fields). | `test_worker_drops_result_of_stale_frame`. |
| 5 | Results envelope seq can go out of order or skip a number with many worker threads (protocol 1) | `infer/publish/results.py`: `publish()` takes the seq, packs and queues the message in one critical section. A message dropped because the queue is full uses no seq. | `test_results_seq_in_order_many_threads`: 4 threads x 400 results, 0 reversals, 0 gaps. T4 viewer: 575/575 messages OK. |
| 6 | Snapshot of a camera with no signal looks like a live picture (protocol 2) | `infer/draw.py`: for state STALE or NO SIGNAL the snapshot is dark, has no results, and has the text "NO SIGNAL" / "STALE" and "last frame N s ago". The topic, size (320 px) and rate do not change. | `test_snapshot_no_signal_is_marked`. |
| 7 | DTCP `inputsValid` can be true when `ego_speed_mps` is set in the config (parity 1, low) | `infer/models/adapters/dtcp_v1.py`: `inputs_valid` is always False (command and target are always assumed). The note still says "fixed value from config". | `test_dtcp_inputs_valid_false_with_config_speed`. |

Unit tests after the fixes (all T4 tests, run again after the T4 run):

```
$ PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_t4_fixes.py tests/test_adapters_parity.py tests/test_manager.py tests/test_publish.py
.....................                                                    [100%]
21 passed in 15.38s
```

## 7. Known limits

1. YOLOPX throughput: 46.9 results/s for 6 cameras (about 7.8/s per camera), not 30/s per camera.
   The 2 workers are almost always busy: 46.9/s x about 38 ms (pre + infer + post p50) = about
   1.8 of 2 workers. Infer p50 is 21.7 ms, higher than the 17.3 ms measured alone; the probable
   cause is that DTCP and the 6 H.265 decoders share the GPU (not measured). On the bench
   recordings (integration smoke) the rate was 60.4/s. More workers or a lower per-camera rate
   for cams 1-5 can change this; this was not tested.
2. The internal JSON keeps only the dashboard contract keys. Per-camera model rates (`cam_fps`),
   `queue_ms`, `results_dropped_old` and `results_dropped_stale` are not in it. The admin socket
   (5563, "models") gives the full manager status.
3. GPU memory per model is an estimate (engine file + activation + I/O), not a measured value.
   The Orin has shared memory: the node used about 500 MB of system RAM more than before it
   started (8735 MB -> 9232 MB).
4. The H.265 passthrough sends 1280x720 on all six cameras, not 704x396 on cams 1-5 (RK design
   size). Boxes use the frame size, so the boxes are correct.
5. DTCP: speed 0 m/s, command STRAIGHT and target (0, 20) m are assumed values. The trajectory is
   for display only. Its drawing is a virtual perspective, not a calibrated projection. Rule R8:
   the node does not publish throttle, steer, brake, mu, sigma or pred_speed.
6. YOLOPX gives low-score false positives (0.38-0.40) on large areas of the car interior (cam1,
   cam3). The thresholds are the old DriverGuard values (0.30 / 0.45); they were not changed.
7. A single engine load cannot be stopped while it runs. SIGTERM during the YOLOPX load waits for
   that load (about 3 s with a warm disk cache).
8. `ModelManager.stop()` (not `close()`) is used at node stop; the process exit releases the GPU
   memory.
9. Ingest (owner T3, not changed by T4):
   - Each camera had `ring_overruns` 5 and `lost_frames` 5 (cam5: 0) during the start only. The
     values did not change in the 300 s window.
   - When two senders use the same port, only `seq_resets` and `new_streams` go up;
     `source_mismatch` and `foreign_frames` stay 0.
   - "Opening in BLOCKING MODE" prints 6 times on stdout at start and at stop.
10. Time: the AGX has no PTP. Every message has flag bit1 (time uncertain).

## 8. Stop and clean-up

- Node: SIGTERM at 23:07:25.313. Log: `node stopped in 0.60 s`. Process gone after 1.42 s. No
  state change to ERROR at stop.
- Simulator: SIGTERM, process gone after 0.11 s. Sysmon stopped by itself (`wrote 330 samples`).
- After the stop: no `tools.rk_sim`, `infer.main`, `tools.sysmon` or `tools.result_viewer` process
  is left. TCP 5560-5563, UDP 6000-6005, 15590 and 16300-16305 are free.

## 9. Files

- `tests/out/sim_driving.yaml` (simulator configuration)
- `tests/out/t4_status.jsonl` (300 status records), `tests/out/t4_sysmon.jsonl` (330 samples)
- `tests/out/t4_node.log`, `tests/out/t4_sim.log`
- `tests/out/t4_viewer/` (cam0.jpg to cam5.jpg, all.jpg)
- `tests/test_t4_fixes.py` (8 new tests)
- Changed code: `infer/runner.py`, `infer/main.py`, `infer/status.py`, `infer/draw.py`,
  `infer/publish/results.py`, `infer/models/manager.py`, `infer/models/adapters/dtcp_v1.py`
