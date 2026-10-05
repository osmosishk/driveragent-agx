# Morning report: AGX inference node and dashboard (agx02)

Night run 2026-10-05 21:01:45 to 2026-10-06 06:01:45 (BST). Repository: `~/driveragent-agx` (git, local only).
Agent: Claude (coordinator) with sub-agents. Language: ASD-STE100 Simplified Technical English.

**Read this first**
- All camera input tonight is SIMULATED. The RK3588 does not send camera frames yet. The simulator
  replays old recordings on this AGX. Every result carries the SIMULATED label (envelope flag bit 0,
  field `simulated`, dashboard label).
- The node runs now: `agx-infer`, `agx-dashboard` and the simulator `agx-sim` are transient systemd
  USER units. They do not start at boot. They stop if the last session of `tonyho` ends.
- The night agent deleted, moved or overwrote no file that existed before the run. It stopped or disabled
  no service or container. It installed nothing outside the project venv, with one exception (6.2, R4).
  Tool caches outside the project changed automatically (6.2).

## 1. Summary

| Task | State | Proof (command and real output, or file) |
|---|---|---|
| T0 Audit and cleanup proposal | DONE (audit without root) | `docs/AGX_AUDIT.md`; `docs/CLEANUP_PROPOSAL.md` (106 rows, 18 SAVE FIRST rows on top). `pytest tests/test_t0_docs.py` -> `3 passed`. sudo needs a password, so the audit is partial for root-only data (B1). |
| T1 Project and interface | DONE | `docs/MODELS.md` (5 engine files, I/O read from the real files with `python -m tools.inspect_engines`), `docs/RK_AGX_INTERFACE.md`, `proto/agx_infer.capnp` v1. `pytest tests/test_t1_models_doc.py` -> passed. RK repo read at `rk-v0.4.0` (tag object `f3d9d191...`, commit `258cf592...` checked). |
| T2 Dashboard v1 (A, D, E, F) | DONE | `docs/test_results/T2_RESULT.txt`: no password -> 401, wrong password -> 401, `/api/health` real values, page 200, values change each second, 4 SSE events in 3.5 s. |
| T3 Camera input | DONE | `docs/test_results/T3_RESULT.md`: six H.265 streams for 300 s, each 30.0 fps, 0 lost packets, 0 lost frames. NV12 at RK sizes 60 s: <= 0.11 % lost frames. |
| T4 Inference | DONE | `docs/test_results/T4_RESULT.md`: 5 min, six streams, `driverguard_yolopx` 46.9 results/s, `driverguard_dtcp` 10.0/s. Images: `docs/test_results/t4_viewer/`, check: `docs/test_results/T4_VISUAL_CHECK.md`. |
| T5 Results for the RK3588 | DONE | `docs/test_results/T5_RESULT.md`: `python -m tools.rk_result_client --seconds 120` -> 6298 results, six cameras, 0 rejects, 0 duplicates, exit 0. |
| T6 Dashboard v2 (B, C, rest of D) | DONE | `docs/test_results/T6_RESULT.md`: sim stopped -> six tiles NO SIGNAL 1.30-1.32 s after the last frame; restart -> SIMULATED after 1.44 s; one model stopped -> the other continued. |
| T7 Real RK3588 | PARTIAL | No test with real cameras: the RK3588 does not send FrameLink yet (B3). `docs/RK_TASKS.md` (K1-K9) and `tools/framelink_ref/` (C++ sender reference, golden vectors 3/3 ok) are ready. Unit files are in `systemd/` but NOT installed (no sudo, B2). Services run as transient user units, not enabled at boot. `docs/test_results/T7_RESULT.md`. |
| T8 Soak and report | DONE | Section 4.4 (30 min) and section 4.5 (night run). `docs/test_results/t8/`. |

Full test suite after the review fixes: `130 passed in 112.98s` (`docs/test_results/full_suite_after_fixes.txt`).
One test is flaky under heavy load (section 7).

Commits (`git log --oneline`): T0 `fed4a62`, T1 `8d7ba3b`, T2 `c8677bf`, T3 `72fe859`, T4 `74b2af3`,
T5 `05d1e66`, T6 `0c51645`, T7 `9c28a6a`, T8 tools `21139c7`, review fixes `2448a33`, then the T8 commits.

## 2. How to open the dashboard

- On the LAN: `http://10.0.0.130:8700/`. Over tailscale: `http://100.64.0.20:8700/`. On the AGX: `http://127.0.0.1:8700/`.
- User and password: in `~/driveragent-agx/.env` (`AGX_DASH_USER`, `AGX_DASH_PASSWORD`, mode 600, not in git).
- The page uses plain HTTP. The password goes in clear text on the LAN. Use tailscale (encrypted)
  until TLS is set (owner decision, section 6).
- Only these source networks can connect: 127.0.0.0/8, 10.0.0.0/24, 10.42.0.0/30, 100.64.0.0/10.
- API: `/api/health` (summary for the RK3588), `/api/models`, `/api/cameras`, `/api/link`,
  `/api/services`, `/api/history`, `/api/stream`.

## 3. What is real and what is simulated

| Item | Real or simulated |
|---|---|
| Camera frames (all six) | SIMULATED. `tools/rk_sim` replays old recordings from `~/driveragent/logger/video` (read-only): road sessions 8003-20251109 (cam4 and cam5 are black in these recordings) and bench sessions 8003-20260510. FrameLink source byte = REPLAY. |
| Detections, masks, trajectories, fps, latency | Real TensorRT computation on the real engines, but on SIMULATED input. Labelled SIMULATED. |
| DTCP trajectory | Model output with ASSUMED inputs: ego speed 0 m/s (no CarState on the AGX), command STRAIGHT, target (0, 20) m (old defaults). `inputsValid=false`. Display only. Throttle, steer and brake are not published (R8). |
| AGX health (CPU, GPU, RAM, temperatures, power, fan, disk, network) | REAL. Power = sum of the INA3221 rails (this board has no VDD_IN rail). |
| RK3588 ping | REAL (100.64.0.180 over the tailscale DERP relay, about 10-12 ms). |
| Clock offset AGX <-> RK3588 | NOT AVAILABLE (no read-only method, B5). |
| GPU memory per model | ESTIMATE (engine file + activation + I/O). |
| Services, units, Docker | REAL. |

## 4. Measured numbers

All camera data below is SIMULATED input. Times are AGX clock only.

### 4.1 Camera input (T3, ingest only, 300 s, six H.265 streams 1280x720)

| Camera | fps avg / min | kbit/s | lost packets | lost frames | decode p50 / p95 ms | max frame age ms |
|---|---|---|---|---|---|---|
| cam0 front | 30.0 / 29 | 5031 | 0 | 0 | 15.2 / 22.4 | 46 |
| cam1 | 30.0 / 29 | 5031 | 0 | 0 | 10.8 / 15.9 | 50 |
| cam2 | 30.0 / 30 | 5042 | 0 | 0 | 8.4 / 9.3 | 27 |
| cam3 | 29.95 / 14 | 5032 | 0 | 0 | 19.0 / 23.4 | 54 |
| cam4 | 29.95 / 15 | 5029 | 0 | 0 | 20.3 / 24.0 | 57 |
| cam5 | 29.94 / 15 | 5032 | 0 | 0 | 14.9 / 22.9 | 64 |

NV12 at the RK design sizes (cam0 1280x720, cam1-5 704x396, 806 Mbit/s on loopback): ingest only
<= 0.11 % lost frames (T3); with the models running cam0 lost 0.59 % and cam1-5 <= 0.08 %
(`docs/test_results/nv12/NV12_MODEL_TEST.md`).

### 4.2 Models (T4, 5 min, six H.265 road streams)

| Model | Cameras | Results/s | Latency total p50 / p95 / p99 ms | pre / infer / post p50 ms | GPU memory (estimate) |
|---|---|---|---|---|---|
| driverguard_yolopx | 0-5 | 46.9 total (about 7.8 per camera) | 59.5 / 87.4 / 103.1 | 15.0 / 21.7 / 1.3 | 164 MB |
| driverguard_dtcp | 0 | 10.0 | 33.0 / 69.4 / 76.9 | 15.2 / 8.6 / 0.2 | 67 MB |
| system1 | - | OFF | - | - | - |
| sparsedrive_convnext_orin | - | OFF | - | - | - |

"total" = frame ready in the AGX store -> result complete (includes queue time).

### 4.3 End to end (T5, 120 s): frame received at the AGX -> result received by the client

| Model | Camera | Rate Hz | p50 / p95 / p99 / max ms |
|---|---|---|---|
| driverguard_dtcp | 0 | 9.8 | 57.9 / 96.4 / 120.4 / 148.3 |
| driverguard_yolopx | 0 | 7.1 | 97.1 / 134.2 / 150.4 / 168.3 |
| driverguard_yolopx | 1 | 7.1 | 82.8 / 110.3 / 124.7 / 148.7 |
| driverguard_yolopx | 2 | 7.1 | 86.9 / 115.9 / 132.2 / 164.7 |
| driverguard_yolopx | 3 | 7.1 | 84.4 / 117.3 / 139.9 / 158.2 |
| driverguard_yolopx | 4 | 7.1 | 76.9 / 105.8 / 122.5 / 160.5 |
| driverguard_yolopx | 5 | 7.1 | 72.2 / 95.0 / 113.0 / 130.0 |

The client ran on the AGX (one clock). On the RK3588 this number needs PTP (B5).

### 4.4 Soak test (T8, 30 min, 2026-10-06 00:08:47 to 00:39:27)

Full chain: `agx-sim --sessions road` (six H.265 streams, SIMULATED) -> `agx-infer` -> results 5560 ->
`tools.rk_result_client` (1800 s) + dashboard. Data: `docs/test_results/t8/` (`soak_sysmon.jsonl`
1 s samples, `soak_status.jsonl` 1 Hz, `soak_client.json`). Report: `docs/test_results/t8/T8_SOAK_30MIN.md`
(`python -m tools.soak_report ...`).

Client (`agx-log-soak-client.out`): 95893 results, 1800 status messages (interval mean 1.000 s,
max 1.071 s), rejects 0, duplicates 0, out of order 0, all six cameras, all checks PASS, exit code 0.

| Camera | fps mean / min / max | lost frames | lost packets | ring overruns | state |
|---|---|---|---|---|---|
| cam0-cam5 | 29.9-30.1 / 28-29 / 31-32 | 0 | 0 | 0 | SIMULATED in 1801 of 1801 samples |

| Model | Results/s mean / min / max | total latency p50 / p95 / p99 ms | Results in 30 min | State |
|---|---|---|---|---|
| driverguard_yolopx | 43.3 / 36.6 / 51.2 (about 7.2 per camera) | 62.7 / 96.8 / 119.9 | 77895 | RUNNING 1801/1801 |
| driverguard_dtcp | 10.0 / 9.8 / 10.0 | 39.2 / 75.7 / 104.0 | 18000 | RUNNING 1801/1801 |

Frame received at the AGX -> result received by the client (p50 / p99 ms): YOLOPX cam0 90.1 / 157.1,
cam1 82.2 / 130.0, cam2 85.4 / 141.2, cam3 80.9 / 130.5, cam4 90.6 / 140.9, cam5 72.8 / 121.6;
DTCP cam0 52.2 / 120.8.

| System | mean | max | start (first 60 s) | end (last 60 s) |
|---|---|---|---|---|
| CPU total % (12 cores) | 32.0 | 40.4 | 32.4 | 31.5 |
| GPU load % | 59.3 | 99.9 | 53.4 | 54.6 |
| RAM used MB (of 62841) | 9993 | 10118 | 9970 | 9962 |
| Power, sum of rails W | 26.80 | 35.65 | 27.34 | 26.90 |
| Temperature cpu / gpu / tj C | 65.1 / 60.4 / 65.0 | 67.2 / 62.4 / 67.2 | 65.6 / 61.0 / 65.6 | 65.0 / 60.3 / 65.0 |

| Process | RSS start MB | RSS end MB | slope (least squares) | CPU % of one core mean |
|---|---|---|---|---|
| agx-infer (infer.main) | 1633.9 | 1637.1 | +2.7 MB/h | 279 |
| agx-sim (tools.rk_sim) | 76.8 | 83.3 | +8.1 MB/h | 15 |
| agx-dashboard (dashboard.main) | 57.7 | 61.6 | +8.4 MB/h (the 1 h in-memory history fills) | 4 |

Errors: node errors none; journal warnings and errors of agx-infer, agx-sim, agx-dashboard in the window: 0;
service restarts: 0. System RAM slope over the 30 min: -46 MB/h (no leak visible at system level).

### 4.5 Night run (T8, from 00:08 to 05:20)

The night loggers (`agx-log-night-sysmon`, 10 s samples; `agx-log-night-status`, every 10th status)
write `docs/test_results/t8/night_sysmon.jsonl` and `night_status.jsonl` until 05:20. The agent fills
this section at the end of the night. If it still has no numbers, run:
`PYTHONPATH=. .venv/bin/python -m tools.soak_report --sysmon docs/test_results/t8/night_sysmon.jsonl --status docs/test_results/t8/night_status.jsonl`

## 5. Old services or containers stopped

None. The old DriverAgent stack did not run tonight (no process, no systemd unit exists for it).
The Docker container `driveragent-valhalla` (port 8002) still runs; it does not conflict with this node.
Nothing needs to be started again.

## 6. Blockers and owner decisions

### 6.1 Decisions (recommendation first)

| # | Decision | Recommendation / facts |
|---|---|---|
| D1 | Enable the two services at boot | First install the system units: `bash ~/driveragent-agx/systemd/install_units.sh` (run as tonyho; it asks for the sudo password; it does not enable at boot). Then, if approved: `sudo systemctl enable agx-infer.service agx-dashboard.service`. No system unit exists for the simulator. |
| D2 | Cleanup proposal | `docs/CLEANUP_PROPOSAL.md`: approve row by row. Do the 18 SAVE FIRST rows first (unpushed commits in `~/driveragent`, local changes, this new repo without remote). 535 GiB of recordings are on disk twice (mp4 + tar.bz2). |
| D3 | Time synchronisation RK3588 <-> AGX | PTP with the AGX as grandmaster (RK kick-off M3), or at least chrony on both boards. Until then all cross-board times are uncertain (flag bit 1 on every message). The AGX clock is about 31-41 ms ahead of public NTP (timesyncd). |
| D4 | Git remote for `~/driveragent-agx` | Add a remote and push (rule R10: not done tonight). |
| D5 | Link C | 10.42.0.1/30 on the AGX, MTU 9000. The AGX has ONE Ethernet port (`eno1`, now the LAN uplink 10.0.0.130/24). Link C on `eno1` removes the LAN uplink: choose a second NIC or another plan (RK_TASKS O7). Also set `net.core.rmem_max` to 8 MiB (like the RK). |
| D6 | FrameLink payload for six cameras | RK design: raw NV12 (841 Mb/s at MTU 9000, near the 1 GbE limit). Night-task default: H.265 (about 5 Mbit/s per camera). The AGX accepts both (fmt 1 and fmt 2). Recommendation: NV12 for cam0, H.265 for cam1-5 on 1 GbE. |
| D7 | Result channels in driveragent-proto | Add `AgxPerceptionResult` (5560) and `AgxInferStatus` (5561) to the shared proto; decide on the pending 8014/8010/5612 channels (`docs/RK_AGX_INTERFACE.md` section 9). |
| D8 | YOLOPX on cam1-5 | The old stack used cam0 only. Side and rear views give some false boxes (0.38-0.40). The RK `camera_map.ini` says unlabelled cameras are not model inputs. Decide: cam0 only, or all six. |
| D9 | DTCP | It needs real ego speed and a route command from the RK side. Decide: keep it (display only) or switch it off. |
| D10 | Dashboard exposure | Plain HTTP on all interfaces with Basic auth. Options: TLS (`tls_certfile`/`tls_keyfile` in `config/dashboard.yaml`) or bind to loopback + tailscale only. |
| D11 | User lingering | `loginctl enable-linger tonyho` keeps the user units after logout, or use the system units (D1). |
| D12 | Full audit | Run `sudo bash ~/agx_audit.sh` once for the root-only data. |

### 6.2 Rule exceptions and side effects (reported honestly)

- R4: at 21:25-21:26 a sub-agent installed `esprima` and `quickjs` with pip into the session
  scratchpad (outside `.venv`). Corrected: `quickjs` is now in `.venv`; the scratchpad copy is deleted.
- R11: the T1 probe sent SNTP time requests to public NTP servers (pool.ntp.org, time.google.com,
  time.cloudflare.com, 83.217.166.45). No local data was sent. Downloads: RK repo (git clone),
  pip packages, uPlot (cdn.jsdelivr.net).
- R1 (automatic tool side effects outside the project): pip download cache `~/.cache/pip`; GStreamer
  rewrote its own plugin cache `~/.cache/gstreamer-1.0/registry.aarch64.bin`; pytest wrote bytecode
  into `~/.local/lib/python3.10/site-packages/anyio/__pycache__` and `/tmp/pytest-of-tonyho` (both
  removed at the end of the run); git read commands touched the directory time of `~/driveragent/.git`
  (no file changed).

## 7. Known defects and risks

| # | Item |
|---|---|
| K1 | YOLOPX gives about 7.5-7.8 results/s per camera (six cameras), not 30. Cause: CPU preprocessing of the old code (letterbox + float normalise, about 15 ms) and the shared GPU. |
| K2 | False boxes on side/rear views (score 0.38-0.40, threshold 0.30 of the old code). |
| K3 | NV12 cam0 (1280x720 raw) loses 0.59 % of frames when the models run (socket buffer 208 KB, B4). |
| K4 | At node start each camera loses about 5 frames (shared-memory ring overruns while the engines load). |
| K5 | The simulator grows in memory in NV12 mode (548 -> 700 MB in 5 min). It is a test tool. |
| K6 | One unit test is flaky under heavy load (`tests/test_rk_sim.py::test_missing_file_falls_back_to_pattern`: strict zero-loss UDP check). |
| K7 | Transient user units stop at reboot and when the last `tonyho` session ends. The journal is volatile (`/var/log/journal` does not exist). |
| K8 | ZMQ 5560/5561 listen on all interfaces with no authentication (perception data only; size limit set). In rk mode set `rk_allowed_sources` to the RK address. |
| K9 | The dashboard page was not opened in a real browser (no Chromium run: it writes in the user's snap folder). The page logic was tested in QuickJS; the NO SIGNAL page bound (<= 1.75 s) is calculated. |
| K10 | The venv uses packages from `~/.local` (anyio, numpy, pyzmq, pycapnp, pycuda). A cleanup of `~/.local` breaks the services (`requirements-venv.txt`). |
| K11 | System 1 (PyTorch only) and SparseDrive (wrong engine output) are OFF. `docs/MODELS.md` section 7. |
| K12 | Ping in dashboard part D goes over tailscale DERP, not over a direct link. Clock offset: n/a. |
| K13 | An orphan process from an earlier Claude Code task runs since 2026-09-25 (PID 86637, "python3 -", 13 MiB). Not touched. |

## 8. Next steps

**AGX agent**
1. Move YOLOPX preprocessing to the GPU (parity check against the old code with a tolerance) to reach more results per camera.
2. After D5: switch `config/sources.yaml` to `mode: rk`, set `rk_allowed_sources`, test with the real FrameLink sender (RK_TASKS K1 test 2).
3. Bind 5560/5561 to the link address; add ZAP or CURVE if needed. TLS for the dashboard (D10).
4. After D7: publish the agreed proto structs; optionally BoardHelloAgx (5612) and a SUB for CameraHealth (5572).
5. Rebuild the SparseDrive ConvNeXt backbone with a correct workspace size and an FP32 check (`docs/MODELS.md`); consider System 1 in TensorRT.
6. Fix the simulator NV12 memory growth; make the flaky test tolerant to OS-level UDP loss.

**RK3588 agent** (`docs/RK_TASKS.md`)
K1 FrameLink TX in rk-camd (use `tools/framelink_ref/`), K2 optional H.265 payload, K3 Link C,
K4 result subscriber (`tools/rk_result_client` as the example), K5 overlay on the camera tiles,
K6 AGX status on the RK dashboard, K7 time sync, K8 confirm the AGX proposals, K9 CameraHealth to the AGX.
