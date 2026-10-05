# T5 result: RK result client against the AGX inference node

Date: 2026-10-05, 23:11 to 23:16 BST. Host: agx02. Node version: `72fe859-dirty`.

**ALL DATA IN THIS TEST IS SIMULATED (R13).** The input is the RK3588 simulator (`tools.rk_sim`, road video files, `source = replay`). Each result has `simulated = true` and envelope flag bit0 (`source_is_replay`) set. No live camera was used.

R8: this report contains no control values. The trajectory point values are not printed.

## 1. Result summary

| Check | Requirement | Measured | Result |
|---|---|---|---|
| Client run, 120 s, `127.0.0.1` | exit code 0, all checks pass | exit code 0, 6 checks PASS | PASS |
| Client run, 10 s, `100.64.0.20` (tailscale) | node binds on all interfaces | exit code 0, 546 results, 10 status messages | PASS |
| Rejects (envelope, CRC, schema hash, decode) | 0 | 0 results, 0 status | PASS |
| Duplicate results | 0 | 0 (client), 0 (recorder) | PASS |
| Stale rule during a 3 s simulator pause | no result for a frame older than 0.5 s | 0 such results. Last result 0.124 s after the pause start. | PASS |
| Status rate | 1 Hz | 120 messages in 120 s, interval mean 1.000 s, min 0.935 s, max 1.064 s | PASS |
| Section 6 fields | all present | all present (see Section 6). `trackId` is always 0: no model gives tracks. | PASS (track: not available) |

## 2. Set-up

Start the services (no change to `config/`; `svc.sh` gives the extra arguments to the program):

```
cd /home/tonyho/driveragent-agx
tools/svc.sh start sim --sessions road
tools/svc.sh start infer
```

Output:

```
Running as unit: agx-sim.service
Running as unit: agx-infer.service
```

Check after 40 s (`tools/svc.sh status`, `tools/svc.sh logs infer 200 | grep -iE "error|warn|fail|traceback"`, `python -m tools.model_ctl list`):

```
  agx-dashboard.service loaded active running driveragent-agx dashboard (transient user unit, night run)
  agx-infer.service     loaded active running driveragent-agx infer (transient user unit, night run)
  agx-sim.service       loaded active running driveragent-agx sim (transient user unit, night run)
2026-10-05T23:11:04+0100 agx02 python[2009184]: kj/filesystem-disk-unix.c++:1734: warning: PWD environment variable doesn't match current directory; pwd = /home/tonyho
NAME                         STATE    EN  CAMERAS           FPS  P50 ms  RESULTS  ERROR/REASON
driverguard_yolopx           RUNNING  y   0,1,2,3,4,5      45.8    61.2     1718
driverguard_dtcp             RUNNING  y   0                10.0    31.1      374
system1                      OFF      n   0,1,2,3,4,5       0.0       -        0  Not a TensorRT model: ...
sparsedrive_convnext_orin    OFF      n   0,1,2,3,4,5       0.0       -        0  Backbone engine only; ...
```

The only log line with "warn" is the pycapnp `PWD` warning. It has no effect. The infer log has no error. The infer log shows `schema hash AgxPerceptionResult = 0xafcaff02 (OK ...)`, `AgxInferStatus = 0x9086fa18 (OK ...)`, `results PUB bound tcp://0.0.0.0:5560`, `status PUB bound tcp://0.0.0.0:5561`.

Simulator (from `tools/svc.sh logs sim`): 6 cameras, H.265 passthrough of the road session `8003-20251109_105508...`, 30 fps each, file size 1280x720 for all cameras. cam4 and cam5 are almost black (known, see `config/sim.yaml`).

## 3. Commands

The orchestration script is `t5_t6_helpers/t5_run.sh`. It runs these steps:

1. Start a recorder (`t5_t6_helpers/rec_results.py`, 124 s). It writes the times of each result and the camera states of each status to `t5_recorder.csv`. It is only for the stale-rule analysis. It does not check the envelope.
2. Start the client (T5 command):
   ```
   PYTHONPATH=/home/tonyho/driveragent-agx .venv/bin/python -m tools.rk_result_client --host 127.0.0.1 --seconds 120 \
       --json /home/tonyho/driveragent-agx/docs/test_results/t5_client.json > docs/test_results/t5_client.log 2>&1
   ```
3. At client start + 60.008 s: `systemctl --user kill -s SIGSTOP agx-sim; sleep 3; systemctl --user kill -s SIGCONT agx-sim`.
4. Read the model counters (`python -m tools.model_ctl --json list`) before and after.

Events (`t5_events.txt`):

```
before: 23:12:17.465 driverguard_yolopx:total=3144,dropped_stale=0,dropped_old=0 driverguard_dtcp:total=689,dropped_stale=0,dropped_old=0
client start 1791238338.586832710
SIGSTOP 1791238398.594460420
SIGCONT 1791238401.612831583
client exit code 0
after: 23:14:21.775 driverguard_yolopx:total=8461,dropped_stale=0,dropped_old=0 driverguard_dtcp:total=1903,dropped_stale=0,dropped_old=0
```

Tailscale run:

```
PYTHONPATH=/home/tonyho/driveragent-agx .venv/bin/python -m tools.rk_result_client --host 100.64.0.20 --seconds 10 \
    --json docs/test_results/t5_client_tailscale.json > docs/test_results/t5_client_tailscale.log 2>&1
```

## 4. Client output, 120 s on 127.0.0.1 (SIMULATED)

`t5_client.log` (complete):

```
rk_result_client: tcp://127.0.0.1:5560 (results) tcp://127.0.0.1:5561 (status), schema hash AgxPerceptionResult 0xafcaff02, AgxInferStatus 0x9086fa18, host local=True, 120.0 s

=== rk_result_client summary: host 127.0.0.1 (local=True), 120.0 s, crc crc32c package (checked against the reference) ===
messages {'result_frames': 6298, 'result_ok': 6298, 'status_frames': 120, 'status_ok': 120}  flags {'result_bit0_source_is_replay': 6298, 'result_bit1_time_uncertain': 6298, 'result_bit2_degraded': 0}  envelope seq lost {'result': 0, 'status': 0}
model                    cam  count     Hz   sim     agx_ms p50/p95/p99/max    e2e_recv_ms p50/p95/p99/max     capture_ms p50/p95/p99/max
driverguard_dtcp           0   1171    9.8  1171      56.5/95.0/119.1/146.5          57.9/96.4/120.4/148.3          58.6/97.2/120.9/150.0
driverguard_yolopx         0    855    7.1   855     94.3/129.4/148.1/164.8         97.1/134.2/150.4/168.3         97.9/134.9/151.4/168.8
driverguard_yolopx         1    855    7.1   855     81.0/108.0/123.1/146.8         82.8/110.3/124.7/148.7         83.7/111.4/125.4/149.5
driverguard_yolopx         2    855    7.1   855     85.0/113.7/130.9/161.8         86.9/115.9/132.2/164.7         87.6/116.9/133.1/166.5
driverguard_yolopx         3    854    7.1   854     82.7/115.6/137.9/157.2         84.4/117.3/139.9/158.2         85.2/118.6/140.5/158.6
driverguard_yolopx         4    854    7.1   854     75.3/104.2/121.4/158.7         76.9/105.8/122.5/160.5         77.1/106.2/122.8/160.9
driverguard_yolopx         5    854    7.1   854      70.5/93.0/109.4/128.5          72.2/95.0/113.0/130.0          72.4/95.3/113.4/130.3
status: 120 messages, interval mean 1.000 s, max 1.064 s
status last: node RUNNING SIMULATED, 6 cameras, 4 models, subscribers 2, rate 51.6 Hz
rejects {'result': {}, 'status': {}}  duplicates 0  restarts 0  out_of_order 0
cameras seen [0, 1, 2, 3, 4, 5]  expected []  missing []
latency validity: e2e_recv_ms valid (client and AGX on one clock)
client processing ms p50/p99/max: 0.34/0.80/1.78
check results_received: PASS
check expected_cameras: PASS
check no_rejects: PASS
check no_duplicates: PASS
check frame_seq_increases: PASS
check status_received: PASS
exit code 0
json: /home/tonyho/driveragent-agx/docs/test_results/t5_client.json
```

### 4.1 Latency per (model, camera), ms, SIMULATED

Definitions (client README): `agx_ms` = `tAgxResultNs - tAgxRecvNs` (AGX clock only). `e2e_recv_ms` = client receive time - `tAgxRecvNs` (frame received at the AGX -> result received at the client). `capture_ms` = client receive time - `tCaptureNs` (sender clock).

| Model | Cam | Count | Rate Hz | agx_ms p50 / p95 / p99 / max | e2e_recv_ms p50 / p95 / p99 / max | capture_ms p50 / p95 / p99 / max |
|---|---:|---:|---:|---|---|---|
| driverguard_dtcp | 0 | 1171 | 9.8 | 56.5 / 95.0 / 119.1 / 146.5 | 57.9 / 96.4 / 120.4 / 148.3 | 58.6 / 97.2 / 120.9 / 150.0 |
| driverguard_yolopx | 0 | 855 | 7.1 | 94.3 / 129.4 / 148.1 / 164.8 | 97.1 / 134.2 / 150.4 / 168.3 | 97.9 / 134.9 / 151.4 / 168.8 |
| driverguard_yolopx | 1 | 855 | 7.1 | 81.0 / 108.0 / 123.1 / 146.8 | 82.8 / 110.3 / 124.7 / 148.7 | 83.7 / 111.4 / 125.4 / 149.5 |
| driverguard_yolopx | 2 | 855 | 7.1 | 85.0 / 113.7 / 130.9 / 161.8 | 86.9 / 115.9 / 132.2 / 164.7 | 87.6 / 116.9 / 133.1 / 166.5 |
| driverguard_yolopx | 3 | 854 | 7.1 | 82.7 / 115.6 / 137.9 / 157.2 | 84.4 / 117.3 / 139.9 / 158.2 | 85.2 / 118.6 / 140.5 / 158.6 |
| driverguard_yolopx | 4 | 854 | 7.1 | 75.3 / 104.2 / 121.4 / 158.7 | 76.9 / 105.8 / 122.5 / 160.5 | 77.1 / 106.2 / 122.8 / 160.9 |
| driverguard_yolopx | 5 | 854 | 7.1 | 70.5 / 93.0 / 109.4 / 128.5 | 72.2 / 95.0 / 113.0 / 130.0 | 72.4 / 95.3 / 113.4 / 130.3 |

Clock validity:

- `agx_ms`: valid (one clock, the AGX clock).
- `e2e_recv_ms`: valid in this test, because the client ran on the AGX (one clock). On the RK3588 it is not valid until PTP or a measured offset exists (envelope bit1 `time_uncertain` is set on all 6298 results).
- `capture_ms`: valid in this test only, because the simulator ran on the AGX and uses the same CLOCK_REALTIME. With a real RK3588 sender, it mixes two clocks.
- The rates include the 3 s pause (no results for 3 s). Thus the 120 s mean rate is lower than the running rate (dtcp: 9.8 Hz here, 10.0 Hz in the 10 s tailscale run).

## 5. Stale rule during the simulator pause (SIMULATED)

Rule (docs/RK_AGX_INTERFACE.md 4.6): no new frame for 500 ms -> no result for that camera. Never send a result two times.

Data: recorder file `t5_recorder.csv`, analysis script `t5_t6_helpers/t5_analyse.py`, output `t5_stale_pause.txt`. Times are relative to SIGSTOP (client start + 60.008 s). SIGCONT is at +3.018 s.

```
recorder: 6516 results, 124 status
recorder duplicates (model,cam,frameSeq seen twice): 0
all results: max (tAgxResultNs - tAgxReadyNs) = 147.3 ms; max (t_client - tAgxRecvNs) = 168.1 ms
pause: SIGSTOP at +0.000 s, SIGCONT at +3.018 s
driverguard_dtcp   cam0  last: client +0.040 s, frame recv -0.014 s, seq 4025, frame age at result 35.8 ms | results in pause window 1 | first after: client +3.168 s seq 4026 (seq jump 1), frame recv +3.020 s
driverguard_yolopx cam0  last: client +0.089 s, frame recv -0.014 s, seq 4025, frame age at result 82.4 ms | results in pause window 1 | first after: client +3.298 s seq 4030 (seq jump 5), frame recv +3.152 s
driverguard_yolopx cam1  last: client +0.092 s, frame recv -0.014 s, seq 4025, frame age at result 91.0 ms | results in pause window 1 | first after: client +3.325 s seq 4033 (seq jump 8), frame recv +3.252 s
driverguard_yolopx cam2  last: client +0.117 s, frame recv -0.015 s, seq 4025, frame age at result 115.6 ms | results in pause window 2 | first after: client +3.181 s seq 4026 (seq jump 1), frame recv +3.020 s
driverguard_yolopx cam3  last: client +0.124 s, frame recv -0.017 s, seq 4025, frame age at result 131.5 ms | results in pause window 2 | first after: client +3.382 s seq 4033 (seq jump 8), frame recv +3.253 s
driverguard_yolopx cam4  last: client +0.041 s, frame recv -0.015 s, seq 4025, frame age at result 44.6 ms | results in pause window 1 | first after: client +3.177 s seq 4026 (seq jump 1), frame recv +3.017 s
driverguard_yolopx cam5  last: client +0.052 s, frame recv -0.017 s, seq 4025, frame age at result 55.7 ms | results in pause window 1 | first after: client +3.269 s seq 4030 (seq jump 5), frame recv +3.151 s
results received between SIGSTOP and SIGCONT: 9; of these, frame received at the AGX > 500 ms before: 0
  latest result in the window: 124.0 ms after SIGSTOP; max e2e_recv in window 141.4 ms
status messages from SIGSTOP-1 s to SIGCONT+2 s (camera state:frameAgeMs):
  -0.708 s node RUNNING | 0:SIMULATED:1 1:SIMULATED:5 2:SIMULATED:19 3:SIMULATED:13 4:SIMULATED:24 5:SIMULATED:33 | ...
  +0.226 s node RUNNING | 0:SIMULATED:201 1:SIMULATED:207 2:SIMULATED:209 3:SIMULATED:220 4:SIMULATED:219 5:SIMULATED:222 | ...
  +1.225 s node RUNNING | 0:NO SIGNAL:1202 1:NO SIGNAL:1208 2:NO SIGNAL:1210 3:NO SIGNAL:1221 4:NO SIGNAL:1220 5:NO SIGNAL:1222 | ...
  +2.226 s node RUNNING | 0:NO SIGNAL:2202 1:NO SIGNAL:2208 2:NO SIGNAL:2210 3:NO SIGNAL:2221 4:NO SIGNAL:2220 5:NO SIGNAL:2223 | ...
  +3.240 s node RUNNING | 0:SIMULATED:14 1:SIMULATED:16 2:SIMULATED:11 3:SIMULATED:10 4:SIMULATED:23 5:SIMULATED:31 | ...
  +4.264 s node RUNNING | 0:SIMULATED:5 1:SIMULATED:46 2:SIMULATED:9 3:SIMULATED:20 4:SIMULATED:25 5:SIMULATED:21 | ...
```

Observation:

1. The last frame before the pause arrived at the AGX 14 to 17 ms before SIGSTOP (frameSeq 4025 on all cameras).
2. 9 results arrived after SIGSTOP. All 9 are for frames that arrived before SIGSTOP. The last one arrived 124 ms after SIGSTOP. The maximum `e2e_recv_ms` of these 9 results is 141.4 ms. No result is for a frame older than 0.5 s.
3. From +0.124 s to +3.168 s, no result arrived (3.04 s with no result).
4. After SIGCONT, the first result of each stream is for a new frame (frame received at +3.017 s or later). frameSeq goes up by 1 to 8. No frameSeq repeats. The client counts: duplicates 0, out_of_order 0, restarts 0.
5. The AGX counters `results_dropped_stale` and `results_dropped_old` stay 0 (before and after). Thus no worker started a frame older than 0.5 s (the frame store gives only frames younger than `stale_s`).
6. Status: at +1.225 s all six cameras are NO SIGNAL (frame age 1202 to 1222 ms). At +3.240 s all six are SIMULATED again. The 1 Hz status did not sample the STALE time (0.5 s to 1.0 s), thus STALE is not in this record.
7. Over all 6516 recorded results, the maximum frame age at result (`tAgxResultNs - tAgxReadyNs`) is 147.3 ms.

Ingest losses: at the end of the run, the status shows `lost_frames 5` on each camera (`t5_client.json`, last status). `/api/cameras` after the run shows `ring_overruns 5` on cam0 to cam4 and 4 on cam5, and `decoder_errors 0`. The value before the run was not read. Possible cause: the burst when the simulator continued after SIGCONT. This cause is NOT verified.

## 6. Section 6 field checklist

Data: `t5_fields.txt` (one result of each model, decoded after `dabus_envelope.unpack` of the RK reference module; one status; mask counts in 5 s). Script: `t5_t6_helpers/t5_fields.py`, `t5_t6_helpers/masks.py`. SIMULATED data.

```
=== SIMULATED result (source=replay, simulated=True) envelope: {'src_board': 1, 'type_id': 5560, 'flags': 3, 'schema_hash': '0xafcaff02', 'seq': 13689, 't_ptp_ns': 1791238522849969882}
schemaVersion=1 model=driverguard_dtcp modelVersion=dtcp_v1_fp16.engine:1071ea90213eddc2 camId=0
frameSeq=7661 tCaptureNs=1791238522779421973 tAgxRecvNs=1791238522779772935 tAgxReadyNs=1791238522813478859 tAgxResultNs=1791238522849969882
frameWidth x frameHeight = 1280 x 720
detections: 0
trajectory: points=4 inputsValid=False
  frame='DTCP ego frame: x = lateral, right positive (m); y = forward (m); origin = ego at frame time (model convention)'
  note='display only, not for control; assumed inputs: ego speed 0 m/s (no CarState on the AGX), command STRAIGHT, target (0, 20) m'
masks:
timing ms: queue=4.4 pre=21.5 infer=10.4 post=0.1 total=36.5
=== SIMULATED result (source=replay, simulated=True) envelope: {'src_board': 1, 'type_id': 5560, 'flags': 3, 'schema_hash': '0xafcaff02', 'seq': 13690, 't_ptp_ns': 1791238522866800173}
schemaVersion=1 model=driverguard_yolopx modelVersion=yolopx_v2_fp16.engine:3412bafa057a3a76 camId=2
frameSeq=7660 tCaptureNs=1791238522747452519 tAgxRecvNs=1791238522747906899 tAgxReadyNs=1791238522777679648 tAgxResultNs=1791238522866800173
frameWidth x frameHeight = 1280 x 720
detections: 7
  classId=2 className=car score=0.777 box=(1140.8,536.8,1197.2,588.2) trackId=0
  classId=4 className=truck score=0.556 box=(1082.7,504.8,1133.3,568.2) trackId=0
  classId=3 className=bus score=0.532 box=(722.6,446.2,967.4,587.8) trackId=0
trajectory: points=0 inputsValid=False
  frame=''
  note='no trajectory from this model'
masks:
timing ms: queue=40.0 pre=22.5 infer=25.0 post=1.5 total=89.1
=== status: schemaVersion=1 host=agx02 version=72fe859-dirty nodeState=RUNNING simulated=True sourceMode=sim uptimeS=259 resultsPort=5560 subscribers=1 rateHz=53.8
  cameras: 0/front:SIMULATED:31.0fps 1/right:SIMULATED:30.0fps 2/left:SIMULATED:30.0fps 3/right-back:SIMULATED:30.0fps 4/left-back:SIMULATED:30.0fps 5/back:SIMULATED:30.0fps
  models: driverguard_yolopx:RUNNING driverguard_dtcp:RUNNING system1:OFF sparsedrive_convnext_orin:OFF
  temps: cpu-thermal=62.6C gpu-thermal=57.2C soc0-thermal=59.0C soc1-thermal=58.6C soc2-thermal=59.1C tj-thermal=62.6C
  errors: []
=== masks per (model, cam) in 5 s (SIMULATED data) ===
('driverguard_dtcp', 0, 'results') 51
('driverguard_yolopx', 0, 'drivable_area') 31
('driverguard_yolopx', 0, 'lane_line') 31
('driverguard_yolopx', 0, 'results') 31
('driverguard_yolopx', 1, 'results') 31
...
{'drivable_area': '1280x720 enc=rle-u16le-count-u8-value-rowmajor 3054 B', 'lane_line': '1280x720 enc=rle-u16le-count-u8-value-rowmajor 4674 B'}
```

| Section 6 field | Field in the message | Seen value (SIMULATED) | Result |
|---|---|---|---|
| Schema version | `schemaVersion`; envelope `schema_hash` | 1; `0xafcaff02` (result), `0x9086fa18` (status, checked by the client on 120 messages) | Present |
| Model name | `model`, `modelVersion` | `driverguard_dtcp` / `dtcp_v1_fp16.engine:1071ea90213eddc2`; `driverguard_yolopx` / `yolopx_v2_fp16.engine:3412bafa057a3a76` | Present |
| Camera number | `camId` | 0 to 5 (client: cameras seen [0, 1, 2, 3, 4, 5]) | Present |
| Frame identity (replaces the RTP timestamp, interface doc 4.5) | `frameSeq` + `tCaptureNs` (FrameLink header) | `frameSeq=7661`, `tCaptureNs=1791238522779421973` | Present |
| AGX receive time | `tAgxRecvNs` (+ `tAgxReadyNs`) | `1791238522779772935` (+ ready `...813478859`) | Present |
| AGX result time | `tAgxResultNs` (= envelope `t_ptp_ns`) | `1791238522849969882` = envelope `t_ptp_ns` | Present |
| Detections: class / score / box / track | `classId`, `className`, `score`, `x1..y2` (pixels of `frameWidth` x `frameHeight`), `trackId` | `car 0.777 (1140.8,536.8,1197.2,588.2) trackId=0` | Present. `trackId` = 0 = no track: no model gives tracks. |
| Other outputs: trajectory with named frame | `trajectory.frame`, `points`, `inputsValid`, `note` | dtcp: 4 points, frame named in full, `inputsValid=False`, note "display only, not for control" | Present |
| Other outputs: masks | `masks[].name/width/height/encoding/data` | yolopx cam0: `drivable_area` and `lane_line`, 1280x720, RLE. Only cam0 (`masks_cameras: [0]` in `config/models.yaml`). | Present |
| Other outputs: timing | `timing.queueMs/preMs/inferMs/postMs/totalMs` | dtcp total 36.5 ms; yolopx total 89.1 ms | Present |
| Simulated label (R13) | `simulated`, `source`; envelope bit0 | `True`, `replay`; bit0 on 6298 of 6298 results | Present |
| Status once each second | `AgxInferStatus` on 5561 | 120 messages in 120 s, mean interval 1.000 s, max 1.064 s, min 0.935 s | Present |

## 7. Bind on all interfaces (tailscale address)

`t5_client_tailscale.log` (SIMULATED):

```
rk_result_client: tcp://100.64.0.20:5560 (results) tcp://100.64.0.20:5561 (status), schema hash AgxPerceptionResult 0xafcaff02, AgxInferStatus 0x9086fa18, host local=True, 10.0 s
messages {'result_frames': 546, 'result_ok': 546, 'status_frames': 10, 'status_ok': 10}  flags {'result_bit0_source_is_replay': 546, 'result_bit1_time_uncertain': 546, 'result_bit2_degraded': 0}  envelope seq lost {'result': 0, 'status': 0}
driverguard_dtcp           0    100   10.0   100      57.1/95.0/135.3/135.5          58.5/96.3/137.2/137.6          59.1/96.9/137.7/138.2
driverguard_yolopx         0     74    7.4    74     89.5/129.0/148.1/148.1         92.7/132.7/150.0/150.0         94.5/133.4/150.7/150.7
...
status: 10 messages, interval mean 0.999 s, max 1.022 s
rejects {'result': {}, 'status': {}}  duplicates 0  restarts 0  out_of_order 0
cameras seen [0, 1, 2, 3, 4, 5]  expected []  missing []
exit code 0
```

Sockets (`ss -ltnp`): `0.0.0.0:5560` and `0.0.0.0:5561` (results, status), `127.0.0.1:5562` and `127.0.0.1:5563` (internal, admin). `100.64.0.20/32` is on `tailscale0`.

Limit: the client ran on the AGX. The kernel sends traffic to a local address over the loopback path. This test shows that the sockets accept a connection to the tailscale address. It does not test the tailscale network between two hosts.

## 8. Files

| File | Content |
|---|---|
| `t5_client.log`, `t5_client.json` | T5 client run, 120 s |
| `t5_client_tailscale.log`, `t5_client_tailscale.json` | client run, 10 s, `--host 100.64.0.20` |
| `t5_events.txt` | SIGSTOP / SIGCONT times, model counters before and after |
| `t5_recorder.csv` | times of each result and status during the T5 run (recorder) |
| `t5_stale_pause.txt` | stale-rule analysis output |
| `t5_fields.txt` | Section 6 field values (one message of each type) |
| `t5_t6_helpers/` | helper scripts (`t5_run.sh`, `rec_results.py`, `t5_analyse.py`, `t5_fields.py`, `masks.py`). They ran from the session scratchpad directory. |
