# T6 result: dashboard camera states, model stop/start, service endpoints

Date: 2026-10-05, 23:16 to 23:18 BST. Host: agx02. Dashboard: `http://127.0.0.1:8700` (HTTP Basic auth; the scripts read the user and password from `.env` and do not print them).

**ALL CAMERA DATA IN THIS TEST IS SIMULATED (R13).** Input: `tools.rk_sim --sessions road` (`source = replay`). The dashboard shows the label SIMULATED.

R8: this report contains no control values.

## 1. Result summary

| Test | Requirement | Measured | Result |
|---|---|---|---|
| a. NO SIGNAL after `svc.sh stop sim` | all six cameras NO SIGNAL less than 2 s after the stop | all six NO SIGNAL at 1.322 s after T0 (first poll with the change; the poll before was about 0.1 s earlier). 1.300 to 1.316 s after the last frame. | PASS |
| a. Page-side bound (`tiles.js`, 250 ms) | less than 2 s | at most 1.55 s after the last frame with the measured `hold_s` 1.3 s; at most 1.75 s with `hold_cap_s` 1.5 s (calculation, Section 3.3) | PASS (calculated, not measured in a browser) |
| b. SIMULATED again after `svc.sh start sim` | six cameras SIMULATED again | all six SIMULATED at 1.439 s after T1. First frames in the store at 1.295 to 1.322 s after T1. | PASS |
| c. Stop `driverguard_dtcp` for 15 s | dtcp OFF; yolopx RUNNING, fps > 0, `results_total` increases | dtcp OFF from 1.02 s to 14.14 s, `results_total` stays 3399; yolopx RUNNING, fps 40.8 to 49.8, `results_total` 15008 -> 15581 | PASS |
| c. Start `driverguard_dtcp` | RUNNING again | RUNNING, fps 10.0 at 1.03 s after the start command | PASS |
| d. `/api/health`, `/api/link`, `/api/services` | HTTP 200, units active | HTTP 200 for all; `agx-dashboard`, `agx-infer`, `agx-sim` active (running) | PASS |
| d. Last 100 log lines endpoint | works | `/api/services/logs?unit=agx-infer` HTTP 200, 87 lines; `unit=agx-dashboard` HTTP 200, 29 lines. The journal has only 87 / 29 lines for these units (`journalctl ... -n 100` gives the same counts). `agx-sim` is not in the allowed list (`config/dashboard.yaml` `log_units`). | PASS (agx-sim logs: not available by design) |

## 2. Commands

Helper scripts are in `t5_t6_helpers/`. They ran from the session scratchpad directory. `dash.py` does the HTTP GET with Basic auth from `.env`.

```
cd /home/tonyho/driveragent-agx
.venv/bin/python t6_ab.py  > docs/test_results/t6_nosignal.txt      # a + b
.venv/bin/python t6_c.py   > docs/test_results/t6_model_stop.txt    # c
.venv/bin/python t6_d.py   > docs/test_results/t6_endpoints.txt     # d
```

`t6_ab.py` does these steps:

1. Read `/api/cameras`.
2. T0 = `time.time()`. Run `tools/svc.sh stop sim`.
3. Poll `/api/cameras` each 100 ms for 5 s. Record the time of each state change.
4. T1 = `time.time()`. Run `tools/svc.sh start sim --sessions road` (same arguments as at the start of T5).
5. Poll `/api/cameras` each 100 ms until all six cameras are SIMULATED (maximum 15 s).

`t6_c.py` runs `python -m tools.model_ctl stop driverguard_dtcp`, polls `/api/models` each 1 s for 15 s, runs `python -m tools.model_ctl start driverguard_dtcp`, polls each 0.5 s until dtcp is RUNNING with fps > 0, then runs `python -m tools.model_ctl list`.

## 3. a. NO SIGNAL (SIMULATED)

### 3.1 Output (`t6_nosignal.txt`, part a)

```
before stop: cam0:SIMULATED cam1:SIMULATED cam2:SIMULATED cam3:SIMULATED cam4:SIMULATED cam5:SIMULATED hold_s=1.3 hold_cap_s=1.5 stale_s=0.5 no_signal_s=1.0
T0 = 1791238581.382 (before 'svc.sh stop sim'); stop command returned after 0.113 s, rc 0
state changes (time after T0):
+0.120 s cam0 None -> SIMULATED (last_frame_t 1791238580.8093624, frame_age_ms 4.3, server_t 1791238581.499, status_t 1791238580.8523)
...
+1.322 s cam0 SIMULATED -> NO SIGNAL (last_frame_t 1791238581.3962097, frame_age_ms 402.5, server_t 1791238582.701, status_t 1791238581.822501)
+1.322 s cam1 SIMULATED -> NO SIGNAL (last_frame_t 1791238581.3979115, frame_age_ms 404.9, server_t 1791238582.701, status_t 1791238581.822501)
+1.322 s cam2 SIMULATED -> NO SIGNAL (last_frame_t 1791238581.4013839, frame_age_ms 405.6, server_t 1791238582.701, status_t 1791238581.822501)
+1.322 s cam3 SIMULATED -> NO SIGNAL (last_frame_t 1791238581.4040723, frame_age_ms 407.0, server_t 1791238582.701, status_t 1791238581.822501)
+1.322 s cam4 SIMULATED -> NO SIGNAL (last_frame_t 1791238581.3875108, frame_age_ms 427.4, server_t 1791238582.701, status_t 1791238581.822501)
+1.322 s cam5 SIMULATED -> NO SIGNAL (last_frame_t 1791238581.3898997, frame_age_ms 428.7, server_t 1791238582.701, status_t 1791238581.822501)
a. NO SIGNAL table: cam | time after T0 (s) | last_frame_t after T0 (s) | NO SIGNAL after last_frame_t (s)
   cam0 | 1.322 | +0.014 | 1.308
   cam1 | 1.322 | +0.016 | 1.306
   cam2 | 1.322 | +0.019 | 1.302
   cam3 | 1.322 | +0.022 | 1.300
   cam4 | 1.322 | +0.005 | 1.316
   cam5 | 1.322 | +0.008 | 1.314
max time after T0: 1.322 s, all six: True
```

### 3.2 Timings

| Camera | Last frame (`last_frame_t`) after T0, s | NO SIGNAL seen after T0, s | NO SIGNAL after the last frame, s | Requirement < 2 s after the stop |
|---|---:|---:|---:|---|
| cam0 | +0.014 | 1.322 | 1.308 | PASS |
| cam1 | +0.016 | 1.322 | 1.306 | PASS |
| cam2 | +0.019 | 1.322 | 1.302 | PASS |
| cam3 | +0.022 | 1.322 | 1.300 | PASS |
| cam4 | +0.005 | 1.322 | 1.316 | PASS |
| cam5 | +0.008 | 1.322 | 1.314 | PASS |

Notes:

- The poll interval is 100 ms. Thus the change occurred between the poll before (about +1.22 s) and +1.322 s.
- The last frames arrived 5 to 22 ms after T0, because the `svc.sh stop sim` command took 0.113 s.
- The cameras went from SIMULATED directly to NO SIGNAL. They did not show STALE. Reason: the last status before the change (`status_t` 1791238581.8225) had a frame age of about 0.42 s (less than `stale_s` 0.5 s). The rule then waits for `upper >= max(stale_s, hold_s)` = 1.3 s, and at 1.3 s the rule `upper >= max(no_signal_s, hold_s)` = 1.3 s is also true.
- The NO SIGNAL time (about 1.3 s after the last frame) is equal to `hold_s` (status period 0.996 s + jitter, 1.296 s).

### 3.3 Page-side bound (`dashboard/static/tiles.js`, `dashboard/static/app.js`)

- `app.js:535`: `setInterval(evalTiles, 250)`. The page applies `tileState()` each 250 ms, also between two SSE events.
- `app.js:284`: `nowS = Date.now() / 1000 + serverOffset`. `app.js:269`: `serverOffset = doc.server_t - Date.now() / 1000` at each received document.
- `tiles.js:33,37`: `hold = min(doc.hold_s, doc.hold_cap_s)`. NO SIGNAL when `known >= no_signal_s` or `upper >= max(no_signal_s, hold)`, with `upper = nowS - cam.last_frame_t`.
- `dashboard/infer_views.py:38`: `hold_cap_s = no_signal_s + 0.5` = 1.5 s. The server rule `camera_state()` is the same as `tileState()`.

Bound: the page shows NO SIGNAL at most `max(no_signal_s, min(hold_s, hold_cap_s)) + 0.25 s` after the last frame:

| Case | Calculation | Bound after the last frame | Bound after T0 (last frame at most +0.022 s) |
|---|---|---:|---:|
| Measured `hold_s` = 1.3 s | max(1.0, 1.3) + 0.25 | 1.55 s | 1.57 s |
| Worst case `hold_s` = cap 1.5 s | max(1.0, 1.5) + 0.25 | 1.75 s | 1.77 s |

Both are less than 2 s. Limit: `serverOffset` includes the delivery time of the SSE event, which makes the page clock late by that time. On a LAN this is a few ms. This bound is calculated from the code. No browser measurement was made in this test.

## 4. b. SIMULATED again (SIMULATED)

Output (`t6_nosignal.txt`, part b):

```
T1 = 1791238586.503 (before 'svc.sh start sim --sessions road'); start command returned after 0.033 s, rc 0  Running as unit: agx-sim.service
state changes (time after T1):
+0.038 s cam0 None -> NO SIGNAL (last_frame_t 1791238581.3962097, frame_age_ms 4403.2, server_t 1791238586.539, status_t 1791238585.8228343)
...
+1.439 s cam0 NO SIGNAL -> SIMULATED (last_frame_t 1791238587.8128643, frame_age_ms 12.7, server_t 1791238587.941, status_t 1791238587.849104)
...
b. SIMULATED again table: cam | time after T1 (s) | last_frame_t after T1 (s)
   cam0 | 1.439 | +1.310
   cam1 | 1.439 | +1.295
   cam2 | 1.439 | +1.304
   cam3 | 1.439 | +1.318
   cam4 | 1.439 | +1.322
   cam5 | 1.439 | +1.319
max time after T1: 1.439 s, all six: True
```

| Camera | Newest frame in the store at the change (`last_frame_t`) after T1, s | SIMULATED seen after T1, s |
|---|---:|---:|
| cam0 | +1.310 | 1.439 |
| cam1 | +1.295 | 1.439 |
| cam2 | +1.304 | 1.439 |
| cam3 | +1.318 | 1.439 |
| cam4 | +1.322 | 1.439 |
| cam5 | +1.319 | 1.439 |

Notes:

- The state changed with the first status after the new frames (`status_t` = T1 + 1.346 s).
- The simulator log shows `23:16:26 first frame of all cameras after 0.03 s` (time after its pipeline start). Thus most of the 1.3 s is the start of the simulator process. The log has 1 s resolution, thus the parts were not measured separately.
- No wait for a random-access picture was seen. The simulator starts each file at its first access unit (IDR with VPS/SPS/PPS). The ingest counter `waiting_idr` did not change: cam0 was 20 at 23:15:57 (before the stop) and 20 after the start. The road files have one IDR every 256 AU (8.53 s). A receiver that starts in the middle of such a file must wait up to 8.53 s. That case was not part of this test.

## 5. c. Stop and start one model (SIMULATED input)

Output (`t6_model_stop.txt`, complete):

```
before:   0.01 s | dtcp RUNNING  fps  10.0 results_total   3389 | yolopx RUNNING  fps  44.6 results_total  14908
$ python -m tools.model_ctl stop driverguard_dtcp  (rc 0)
{
  "ok": true,
  "cmd": "stop",
  "model": "driverguard_dtcp",
  "result": {
    "ok": true,
    "state": "OFF"
  }
}
  0.01 s | dtcp RUNNING  fps  10.0 results_total   3399 | yolopx RUNNING  fps  45.4 results_total  14959
  1.02 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  45.2 results_total  15008
  2.03 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  45.0 results_total  15051
  3.03 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  46.6 results_total  15096
  4.04 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  49.8 results_total  15157
  5.05 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  48.6 results_total  15202
  6.06 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  46.6 results_total  15241
  7.07 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  46.4 results_total  15283
  8.08 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  45.8 results_total  15325
  9.09 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  42.0 results_total  15368
 10.10 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  40.8 results_total  15406
 11.11 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  41.8 results_total  15450
 12.12 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  41.4 results_total  15490
 13.13 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  41.8 results_total  15534
 14.14 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  42.6 results_total  15581
check while stopped: PASS
$ python -m tools.model_ctl start driverguard_dtcp  (rc 0)
{
  "ok": true,
  "cmd": "start",
  "model": "driverguard_dtcp",
  "result": {
    "ok": true,
    "state": "RUNNING",
    "error": null
  }
}
  0.01 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  44.4 results_total  15629
  0.52 s | dtcp OFF      fps   0.0 results_total   3399 | yolopx RUNNING  fps  44.4 results_total  15629
  1.03 s | dtcp RUNNING  fps  10.0 results_total   3406 | yolopx RUNNING  fps  46.4 results_total  15682
  1.54 s | dtcp RUNNING  fps  10.0 results_total   3406 | yolopx RUNNING  fps  46.4 results_total  15682
  2.05 s | dtcp RUNNING  fps  10.6 results_total   3417 | yolopx RUNNING  fps  48.8 results_total  15734
  2.56 s | dtcp RUNNING  fps  10.6 results_total   3417 | yolopx RUNNING  fps  48.8 results_total  15734
  3.07 s | dtcp RUNNING  fps  10.4 results_total   3427 | yolopx RUNNING  fps  49.6 results_total  15783
dtcp RUNNING with fps > 0 again after 1.03 s
$ python -m tools.model_ctl list  (rc 0)
NAME                         STATE    EN  CAMERAS           FPS  P50 ms  RESULTS  ERROR/REASON
driverguard_yolopx           RUNNING  y   0,1,2,3,4,5      49.0    62.0    15800
driverguard_dtcp             RUNNING  y   0                10.1    44.2     3431
system1                      OFF      n   0,1,2,3,4,5       0.0       -        0  Not a TensorRT model: ...
sparsedrive_convnext_orin    OFF      n   0,1,2,3,4,5       0.0       -        0  Backbone engine only; ...
```

Notes:

- `/api/models` shows the change with the next status (about 1 s). The admin reply is at once (`"state": "OFF"`, `"state": "RUNNING"`).
- The script checks the conditions from 2 s after the stop command: dtcp OFF, dtcp `results_total` does not change, yolopx RUNNING with fps > 0, yolopx `results_total` increases at each 1 s poll. Result: `check while stopped: PASS`.
- The infer log shows `admin start driverguard_dtcp -> {'ok': True, 'state': 'RUNNING', 'error': None}` (from `/api/services/logs?unit=agx-infer`, Section 6).

## 6. d. Health, link, services and logs endpoints (SIMULATED)

Output (`t6_endpoints.txt`, complete):

```
time 2026-10-05 23:17:43
=== GET /api/health -> HTTP 200, 7097 B ===
{"schema": "agx-health/1", "hostname": "agx02", "time_iso": "2026-10-05T22:17:43.049+00:00", "age_s": 0.6, "stale": false, "node_state": "OK", "node_state_reasons": [], "infer_state": "RUNNING", "infer_reason": null, "simulated": true, "errors": []}
infer: {"state": "RUNNING", "simulated": true, "version": "72fe859-dirty", "uptime_s": 398.2, "age_s": 0.78}
infer.cameras_summary.states: {"SIMULATED": 6}
gpu: {"load_pct": 0.6, "freq_mhz": 612} | temps.max_c: 63.1 cpu-thermal | ram pct: 14.0
=== GET /api/link -> HTTP 200, 19396 B ===
{"rk_ip": "100.64.0.180", "ping_ms": 11.2, "ping_t": 1791238662.2340322, "ping_error": null, "loss_pct": 0.0, "loss_window_s": 60.0, "loss_samples": 30, "clock_offset_ms": null, "clock_method": "none", "clock_uncertainty_ms": null, "clock_note": "n/a (no method; RK gives no time service); no HTTP Date on ports 80,8080,8000; clockdiff not installed", "clock_t": 1791238656.6672616, "time_since_last_frame_ms": 8.3, "time_since_last_frame_basis": "agx-infer status (newer frames are possible)", "last_frame_t": 1791238662.8424845, "results_rate_hz": 55.6, "subscribers": 0, "results_total": 20698, "last_result_t": 1791238662.90883, "infer_na": null, "simulated": true, "label": "SIMULATED"}
ping_history: 2 entries
=== GET /api/services -> HTTP 200, 5262 B ===
summary: {"t": 1791238659.2082746, "user": {"agx-dashboard": "active (running)", "agx-infer": "active (running)", "agx-sim": "active (running)"}, "system": {"agx-dashboard": "not installed", "agx-infer": "not installed", "agx-sim": "not installed"}, "old_units": {"total": 14, "active": 13, "failed": 0}, "docker": {"available": true, "total": 1, "running": 1, "error": null}, "old_processes": 0}
  user unit agx-dashboard.service    active/running  pid 1976454  restarts 0  started Mon 2026-10-05 22:43:03 BST
  user unit agx-infer.service        active/running  pid 2009184  restarts 0  started Mon 2026-10-05 23:11:04 BST
  user unit agx-sim.service          active/running  pid 2014499  restarts 0  started Mon 2026-10-05 23:16:26 BST
=== GET /api/services/logs?unit=not-a-unit -> HTTP 400, 68 B ===
{"error": "unit not allowed", "allowed": ["agx-infer", "agx-dashboard"]}
=== GET /api/services/logs?unit=agx-infer -> HTTP 200, 10396 B ===
   keys ['unit', 'rc', 'lines', 'error', 't']; lines: 87
   | 2026-10-05T23:17:12+0100 agx02 python[2009184]: 2026-10-05 23:17:12,111 INFO agx.infer.manager: model driverguard_dtcp RUNNING (1 workers, cams [0])
   | 2026-10-05T23:17:12+0100 agx02 python[2009184]: 2026-10-05 23:17:12,111 INFO infer.admin: admin start driverguard_dtcp -> {'ok': True, 'state': 'RUNNING', 'error': None}
=== GET /api/services/logs?unit=agx-dashboard -> HTTP 200, 3663 B ===
   keys ['unit', 'rc', 'lines', 'error', 't']; lines: 29
   | 2026-10-05T22:43:05+0100 agx02 python[1976454]: 2026-10-05 22:43:05,847 INFO dashboard.engines: engine inspected /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt load OK (0.3 s)
   | 2026-10-05T22:43:06+0100 agx02 python[1976454]: 2026-10-05 22:43:06,181 INFO dashboard.engines: engine inspected /home/tonyho/model/sparsedrive/run/resnet_backbone_fp16_orin.trt load OK (0.3 s)
```

Log line count check (same journal query as `dashboard/collectors/services.py:221`):

```
$ journalctl --user-unit agx-infer -n 100 --no-pager -o short-iso | wc -l
87
$ journalctl --user-unit agx-dashboard -n 100 --no-pager -o short-iso | wc -l
29
```

Notes:

- The endpoint gives the last 100 lines (`lines=100`). The journal of these units has fewer lines, thus the endpoint gives all of them (87 and 29).
- `/api/link`: `subscribers 0` at this time (no client was connected to 5560). `clock_offset_ms null`: there is no clock method to the RK3588 (known, interface doc Section 6).
- `/api/health` `gpu.load_pct 0.6` is one sample. Other samples in this session were 98.8 %.
- The `system` units are "not installed" (transient user units, no sudo; known).

## 7. Service state at the end

The services stay on for the coordinator. Check at 23:21:15 (`tools/svc.sh status`, `systemctl --user show ...`, `python -m tools.model_ctl list`):

| Unit | State | MainPID | NRestarts | Started with |
|---|---|---:|---:|---|
| agx-sim | active (running) | 2014499 | 0 | `tools/svc.sh start sim --sessions road` (23:16:26) |
| agx-infer | active (running) | 2009184 | 0 | `tools/svc.sh start infer` (23:11:04) |
| agx-dashboard | active (running) | 1976454 | 0 | not changed by this task (22:43:03) |

Models: `driverguard_yolopx` RUNNING (44.0 fps, cams 0-5), `driverguard_dtcp` RUNNING (10.0 fps, cam 0). No helper process of this task runs.

## 8. Files

| File | Content |
|---|---|
| `t6_nosignal.txt` | a + b output (full state-change log) |
| `t6_model_stop.txt` | c output |
| `t6_endpoints.txt` | d output |
| `t5_t6_helpers/dash.py`, `t6_ab.py`, `t6_c.py`, `t6_d.py` | helper scripts |
