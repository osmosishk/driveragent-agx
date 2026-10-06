# AGX link report: RK3588 DA01 and AGX02

| Item | Value |
|---|---|
| Task | "ONE-AGENT TASK: connect RK3588 DA01 and AGX02" (owner Tony) |
| Start | 2026-10-07 03:04:18 CST on DA01 = 2026-10-06 20:04:18 BST on AGX02 = 19:04:18 UTC |
| Time limit | 8 h (until 11:04 CST) |
| DA01 | rk3588-da01, repository driveragent-hmi in /home/tonyho/driveragent (this file), detached HEAD at rk-v0.5.1 |
| AGX02 | agx02 (10.0.0.130), repository ~/driveragent-agx, branch main |
| Agent | Claude (coding agent on DA01) with sub-agents on DA01, and the AGX02 agent "development" (the owner allowed its use during the run) |
| Language | ASD-STE100 Simplified Technical English |

Times in this report are CST (UTC+8, DA01 clock) unless the text says BST (UTC+1, AGX02 clock). The two clocks agreed
with UTC to 1 s during the run (both NTP).

## 1. Summary

| Task | State | Proof (section of this report, files, commits) |
|---|---|---|
| J0 Read and measure | DONE | 2.2 differences (34, verified; `docs/agx_link/j0_differences.md`); 2.3 R4 proof, YOLOPX time budget and bottleneck (2 worker threads), frame-to-result; 2.4 cameras + D1 baseline (`docs/agx_link/data/`); 2.5 link. Commit e5c0462 |
| J1 AGX02 listens for the real board | DONE (rule A4: 1 pre-existing test failure, owner decision) | 3: `mode: rk`, 0.0.0.0:6000-6005, DA01 addresses only; six cameras NO SIGNAL, none SIMULATED (checked from DA01). AGX commit 78d05dc |
| J2 One camera, end to end | DONE | 4: second encoder (recorder not usable); AGX cam0 30 fps, 0 lost, decode 8.5 ms; `docs/agx_link/j2_cam0.jpg` = the real front camera; 16158 results, 2 stale (start), all others in the frame table. Commit a254710 |
| J3 All online cameras | DONE | 5: six cameras, 0 lost on the AGX; per-camera table; result quality per view (dark bench, no road objects; fisheye separately); real vs simulator table. Commit a254710 |
| J4 Sender as a part of the system | DONE (system-unit install = owner step, rule B6) | 6: `[agx_link]` default OFF, DA01 ON (audited); unit + service switch in the repo; D2 test: DA01 at baseline during a 2 min AGX outage, link back in 3.9-4.0 s without action on DA01. Commit 48c305e |
| J5 Result subscriber and dashboard | DONE (live rk-console restart = owner step, rule B6) | 7: envelope/schema checks, capture-to-result on the RK clock, stale rule, panel "AGX link" (API output with real data). Commit 859b0f9 |
| J6 Results on the HMI | DONE | 8: setting "Show AGX results" default OFF; 6 screenshots with the setting ON; geometry matches the AGX pictures; dark bench, so only false low-score boxes. Commit 756c842 |
| J7 Long run and report | DONE | 9: 30 min, 92909 results, 0 stale, 0 rejected, 0 restarts, all cameras OK; this report (copied to AGX02 docs/) |

Main facts:
- DA01 sends all six online cameras (cam0 front 1280x720 at 30 fps; cam1-cam5 704x396 at 15 fps; H.265 from a second
  MPP encoder per camera) to AGX02. AGX02 runs DriverGuard YOLOPX (about 7 results/s per camera) and DTCP (10/s,
  cam0) on the real frames and sends the results back.
- Capture-to-result on the DA01 clock (no clock sync needed): YOLOPX p50 about 85-118 ms, p95 about 130-155 ms.
- Capture, HMI and recording keep their D1 baseline numbers (one exception: the recorder's worst-second encode
  time is about 10 ms higher while it records; no frame is lost).
- If AGX02 stops, DA01 runs as before; the link comes back by itself.
- Owner steps: install the rk-agxlink system unit, restart rk-console for the panel, chrony, install the AGX services
  at boot, camera roles O6 (section 12).

## 2. J0: read and measure

### 2.1 Set-up facts

- The task text gives `AGX_SSH = tonyho@<AGX02 address>`. The address is a placeholder. `~/.ssh/config` on DA01 (written
  2026-10-07 03:02) has `Host agx02` -> `10.0.0.130`, user `tonyho`, key `~/.ssh/id_agx02`. I used this entry.
  First test: `ssh -o BatchMode=yes agx02 hostname` -> `agx02`, exit 0. No password prompt.
- The RK repository on DA01 is the LIVE install: `/opt/driveragent/current -> /home/tonyho/driveragent`. The running
  units execute this tree. Thus I never rebuilt a running binary in place, and I wrote each changed file atomically.
- DA01 sudo: a password is necessary for all commands except `systemctl start|stop lightdm`, the one 5-unit restart
  line (rk-logger, rk-camd, rk-recorder, rk-hmi, rk-hello) and `systemctl restart rk-gnss rk-mapgen`. Thus I could not
  install a new system unit, run `daemon-reload`, or restart rk-console or rk-media (owner approval, rule B6).
- `Linger=no` for tonyho on both machines. User units stop when the last session of tonyho ends.
- At my start, `agx-sim` did NOT run on AGX02. AGX02 had an orderly shutdown at 10:12 BST and a boot at 12:12:20 BST
  (cause not known; REQ-001 of the AGX02 agent). The AGX02 agent started `agx-dashboard` and `agx-infer --mode rk` at
  19:47:34 BST. I started `agx-sim --sessions road` at 20:09:03 BST, only for the J0.2 measurements. J1 stopped it at
  20:47:17 BST.

### 2.2 J0.1: AGX documents and the FrameLink design

Method: a workflow with two readers (AGX documents + AGX code; RK design + RK code at rk-v0.5.1), one comparer and two
adversarial verifiers. The verifiers opened every cited file on both machines.

Result: 34 differences. 21 are confirmed, 13 are corrected in detail, 0 are refuted. The verifiers found 18 more
items. Full list with sources: `docs/agx_link/j0_differences.md`.

No difference makes the interface unusable. Thus I changed no interface item (rule I1). The differences that change
the work:

| ID | Difference | What I did |
|---|---|---|
| D1, D29 | The AGX documents describe Link C (10.42.0.1/30) or tailscale. The real path today is the office LAN: DA01 eth0 10.0.0.208 + 10.0.0.209, AGX02 eno1 10.0.0.130, both 1 Gb/s, MTU 1500. | Use the LAN. The AGX binds 0.0.0.0, so no format change. |
| D2 | `agx_host` default is 10.42.0.1. DA01 has `agx_host = "10.0.0.130"` in `/etc/driveragent/board.toml` (set by daconfig, 2026-10-06 17:32:27 UTC). rk-camd CameraHealth still goes to 10.42.0.1:5572. | The sender uses `[agx_link] host = ""` = `[hmi.bus] agx_host`. CameraHealth is out of scope. |
| D3 | Chunk at MTU 1500: kick-off 1472 B (overflows), RK BRINGUP and AGX 1456 B. | Chunk 1456 B. |
| D4 | RK_TASKS asks for DF; no AGX sender sets it. | The sender sets IP_PMTUDISC_DO (DF). |
| D10 | Document: the receiver does not check the fragment `cam` byte. Code (process mode): it does. | The sender fills the byte. |
| D11, D14 | fmt 2 rules: one Annex-B AU per frame, VPS/SPS/PPS with each IDR, IDR at least each 30 frames, no B-frames; size option (a) = SCALED 1280x720 / 704x396. | Followed. |
| D12, D13 | `seq` source and the capture clock are AGX proposals with options. | `seq` = per camera AU counter; DA01 keeps the table seq -> capture time; `t_capture_ptp_ns` = CLOCK_REALTIME at capture (CLOCK_MONOTONIC capture time + offset). |
| D15, D26 | LIVE (source 1) only for a CONFIRMED camN (RK_TASKS K1). On DA01 only cam0 has a CONFIRMED role. | Decision: all six frames are real camera frames, so they go as LIVE (a test-pattern label would be false, rule B4). The roles of cam1-cam5 stay "role unconfirmed" on both sides (section 3). Owner decision O6. |
| D25 | AGX role names come from the old stack (right, left, ...). | J1: new key `role_rk` (rk mode only). |
| D27 | Since rk-v0.4.0 the HMI can turn (0/90/180/270) and mirror each camera. | J6 uses the same video geometry function. |
| D30 | AGX `rmem_max` 212992 B, RK 8 MiB. | H.265 needs little buffer. Owner decision O3 stays open. |
| D31 | rk-media is a second video sender on DA01 (H.264 of the HMI screen, on demand). | Measured together in D1 (it was off). |

### 2.3 J0.2: open questions (AGX02, before the simulator stopped)

#### a. Rule exception R4 of last night

- Packages: `esprima 4.0.1` and `quickjs 1.19.4`. The night T2 builder sub-agent installed them with pip at 21:25:56
  and 21:26:41 BST on 2026-10-05.
- Where: the night session scratchpad `/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad/pylib/`
  (outside `.venv`; not system Python, not `~/.local`).
- Correction (night): `quickjs 1.19.4` installed in `.venv` (dist-info mtime 2026-10-05 23:45:21). esprima is in no
  environment. The scratchpad copy was deleted (NIGHT_LOG 23:58). Now no esprima/quickjs file exists in `/tmp`.
- Proof that no system or `~/.local` package changed:
  - `find ~/.local/lib/python3.10/site-packages /usr/lib/python3/dist-packages /usr/local/lib/python3.10/dist-packages
    /usr/lib/python3.10/dist-packages -maxdepth 1 ( -name "*.dist-info" -o -name "*.egg-info" ) -newermt "2026-10-05 21:00"`
    -> no output.
  - Package count: 86 + 102 + 4 + 3 = 195 = the night audit baseline of 21:03:38 (before 21:25). The audit Python block,
    run again now, gives an identical output (tensorrt 10.3.0, pycuda 2022.2.2, torch 2.8.0, numpy 1.26.4, pyzmq 27.1.0,
    pycapnp 2.2.0, ...).
  - `pip list` (system: 108, user: 86): no esprima, no quickjs. `.venv`: `quickjs==1.19.4`.
  - `/var/log/dpkg.log`: no install/upgrade/remove since 2026-08-04.
  - The only change under these folders since 21:00: 5 `anyio/__pycache__` directories at 2026-10-06 05:21:09 (the night
    agent deleted its own pytest `.pyc` files there).
  - Limit: the baseline holds versions of 12 named packages and the count, not a full `pip freeze`.

#### b. YOLOPX time budget (simulator input, 2026-10-06 20:27:10-20:29:10 BST, 120 s)

Command (AGX02): `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python tests/out/j0/j0_measure.py --seconds 120
--warmup 3 --tag j0 --infer-pid 13353 --sim-pid 18035 --dash-pid 13344` (SUB to 5560, 5561, 5562; GPU and CPU
samplers; tegrastats). 6180 results, 0 rejects, 0 duplicates.

| YOLOPX, ms, mean / p50 / p95 / p99 | queueMs | preMs | inferMs | postMs | totalMs |
|---|---|---|---|---|---|
| all six cameras (4980 results) | 19.2 / 18.9 / 37.4 / 45.9 | 18.1 / 17.6 / 31.3 / 48.5 | 23.8 / 23.3 / 33.1 / 43.9 | 5.3 / 1.5 / 25.4 / 34.0 | 66.5 / 64.6 / 100.7 / 126.5 |
| cam0 (masks) | 17.9 / 17.9 / 34.0 / 39.0 | 16.0 / 14.9 / 23.0 / 44.6 | 23.2 / 22.2 / 33.3 / 43.4 | 22.2 / 19.5 / 35.3 / 75.8 | 79.5 / 76.2 / 121.8 / 144.4 |

- Rate now: 6.92 results/s per camera (41.50/s for six cameras). The night T4 had 7.8/s, the T8 night run 7.2/s.
- Engine: `yolopx_v2_fp16.engine` (sha256[:16] 3412bafa057a3a76), batch 1, built with `trtexec --fp16` (FP16
  kernels allowed, not INT8; I/O tensors FP32), input 1 x 3 x 384 x 640 (letterbox 1280x720 -> 640x360 + 12 px pad),
  outputs det [1, 5040, 15], da_seg and ll_seg [1, 2, 384, 640]. 2 workers = 2 execution contexts + 2 CUDA streams on
  one engine. DTCP: batch 1, 1 x 3 x 256 x 928, 1 worker, 10 results/s by configuration (`max_fps_per_camera: 10`).
- GPU load: mean 62.1 % (sysfs, 1 Hz), tegrastats GR3D 63.9 %, clock mean 777 MHz of 1300.5 MHz. A second check at
  10 Hz gave 58.3 % (a 1 Hz sample at one phase has a large error).
- CPU: 29.3 % of 12 cores; agx-infer 2.87 cores.
- **Bottleneck: the 2 YOLOPX worker threads.** Each worker does preprocess (CPU), a blocking TensorRT call (batch 1)
  and postprocess (CPU) in series. Both workers are busy 95.9 % of the time (97.8-97.9 % occupancy in two windows).
  One result holds a worker for 47.2 ms (infer 50 %, pre 38 %, post 11 %). The GPU is at about 60 % and the GPU clock
  stays low (612-816 MHz for 86 % of the time), so the GPU is not the limit. `queueMs` is the age of the newest frame
  when a worker takes it; there is no backlog (the store keeps only the newest frame).
- Independent check (second agent, 60 s, `tools.rk_result_client`): same rates (6.98/s per camera) and latencies
  within a few ms. It found three more facts: (1) agx-infer stalls 20-100 ms after each wall-clock second (probably a
  1 Hz task; not examined further); (2) the first agent's "41.5 = 2 / 48.2 ms" is true by construction, the
  independent proof is the occupancy; (3) since the AGX02 cold start TensorRT reports "Using an engine plan file across
  different models of devices" (`trt_match False`) for both engines. This can explain the lower rate; not proved.
- Not optimised (task rule).

#### c. Frame-to-result time (simulator; the simulator, agx-infer and the subscriber are on AGX02: one clock)

c1 = subscriber receive time - tCaptureNs. tCaptureNs is the moment the simulator takes the AU from the recording
(`tools/rk_sim/sim.py:149`), not a camera exposure.

| model | cam0 | cam1 | cam2 | cam3 | cam4 | cam5 |
|---|---|---|---|---|---|---|
| YOLOPX p50 / p95 / p99 ms | 97.3 / 143.7 / 164.8 | 80.4 / 113.8 / 133.0 | 89.9 / 121.7 / 144.1 | 95.1 / 127.1 / 148.0 | 80.6 / 111.4 / 138.3 | 68.0 / 100.5 / 121.2 |
| DTCP p50 / p95 / p99 ms | 64.0 / 97.7 / 129.1 | - | - | - | - | - |

Mean split of c1 (YOLOPX, all cameras): receive 0.6 + decode 18.1 + queue 19.2 + pre 18.1 + infer 23.8 + post 5.3 +
other 0.2 + publish 1.9 = 87.1 ms.

Rule notes from the J0.2 agents (reported, rules B5/A2): one agent ran `sudo -n true` once on AGX02 at about 20:13 BST
(sudo asked for a password and did nothing; it can leave an auth-failure log line). One test tegrastats ran 130 s too
long (the wrong PID was stopped first; then it was stopped by its PID).

### 2.4 J0.3: DA01 cameras and the D1 baseline

Cameras (rk-camd health, 03:13): all six LIVE at 30 fps.

| FrameLink cam (this work) | rk-camd section | Connector | Lens | camera_map role |
|---|---|---|---|---|
| 0 | gmsl_des29_linkA | CAM1 | 120 deg | front, CONFIRMED |
| 1 | gmsl_des29_linkB | CAM2 | 190 deg fisheye | unconfirmed (physical identity CONFIRMED) |
| 2 | gmsl_des6b_linkA | CAM3 | 120 deg | unconfirmed |
| 3 | gmsl_des6b_linkB | CAM4 | 120 deg | unconfirmed |
| 4 | gmsl_des6b_linkC | CAM5 | 120 deg | unconfirmed |
| 5 | gmsl_des6b_linkD | CAM6 | 120 deg | unconfirmed |

gmsl_des29_linkC and linkD have no camera. Only cam0 has a SCALED (RGA NV12) stream.

D1 baseline (tool `rk/agxlink/tools/d1_measure.py`, 120 s windows, read-only; JSON kept in the run scratch folder):

| Item | Idle (03:17:46-03:19:46) | Recording ON (03:20:39-03:22:40) |
|---|---|---|
| Capture, 6 cameras | 30.0 fps each, 0 seq gaps, consumer_drops +1..+4 | 30.0 fps each, 0 seq gaps, consumer_drops +1..+2 |
| HMI (cameras screen, 6 views at 1280x720) | fps_mean 20.66 (min 20.4), frame p50 50.0 ms, p99 max 83.4 ms | fps_mean 20.68 (min 20.2), p50 50.0 ms, p99 max 66.8 ms |
| Recording | off | 6 streams 30.2 fps, ~4820 kbit/s, encode p99 max 6.3-15.7 ms, drop 0 |
| Encoder load (rkvenc IRQ/s) | 0 | 120 + 60 = 180/s (6 x 30 fps) |
| System CPU busy | 19.5 % (max 1 s 31.1 %) | 21.2 % (max 1 s 34.1 %) |
| rk-recorder / rk-hmi / rk-camd CPU (% of one core) | 18.9 / 13.3 / 1.1 | 35.7 / 13.7 / 1.1 |
| MemAvailable | 5967 of 7923 MB | 5941 of 7923 MB |
| Temperature max | 39.8 C | 39.8 C |

Notes:
- The HMI runs at about 20.7 fps on the six-camera screen. This is the baseline (the kick-off target is >= 60 fps).
- CPU0 is about 95 % busy all the time. The cause is the DisplayPort IRQ thread `irq/66-fde50000.dp` (SCHED_FIFO 50).
  All IRQs (eth0 included) go to CPU0. This is a pre-existing condition, not caused by this work.
- `/proc/mpp_service/load` needs `load_interval` (root). Thus "encoder load" = rkvenc interrupts per second + the
  encode time per frame of each encoder.
- DA01 has no board power sensor (only the USB-C PD source of the display). Power on DA01 is not measurable.
- The recording test wrote `/mnt/nvme/driveragent/20261006T192027Z` (3 segments x 6 cameras, about 360 MB). Started and
  stopped with `rk/recorder/tools/rec_ctl.py` (the same path as the HMI Record button).

### 2.5 J0.4: link

| Check | Result |
|---|---|
| `ping -c 20 -i 0.2 10.0.0.130` (DA01 -> AGX02) | 20/20, rtt min/avg/max 0.262/0.797/1.060 ms |
| `ping -M do -s 1472` / `-s 1473` | 0 % loss / "message too long": path MTU 1500 |
| `ping -c 20 -i 0.2 10.0.0.209` (AGX02 -> DA01) | 20/20, rtt 0.752/0.828/1.117 ms; 10.0.0.208 also answers |
| DA01 eth0 | 1000 Mb/s full duplex, MTU 1500 (max 9000); addresses 10.0.0.208 (metric 100) and 10.0.0.209 (DHCP, metric 1024); source toward AGX02 = 10.0.0.208 |
| AGX02 eno1 | 1000 Mb/s full duplex (the night documents say 2500), MTU 1500; rmem_max = wmem_max = 212992 |

The task text says "one local network without a router". The boards are on one /24 with a direct L2 path. The
network also has a gateway (10.0.0.1) and global IPv6 addresses. I did not change the network (rule B1).

## 3. J1: AGX02 listens for the real board

Done by the AGX02 agent "development" on my request (REQ-003), checked by me from DA01. AGX commit `78d05dc`.

- `tools/svc.sh stop sim` (20:47:17 BST). `config/sources.yaml`: `mode: rk`; `rk_allowed_sources: ["10.0.0.208",
  "10.0.0.209"]` (DA01 eth0 has both; the kernel uses 10.0.0.208 toward AGX02); new key `role_rk` per camera (rk mode
  only): cam0 `front`, cam1 `fisheye-190 CAM2 (role unconfirmed)`, cam2-cam5 `CAM3`..`CAM6 (role unconfirmed)`. The key
  `role` stays the camera of the old recordings for sim/file mode. Code: `infer/ingest/ingest.py` and
  `dashboard/infer_views.py roles()` use `role_rk` in rk mode (2 lines). Tests: 2 new, 1 changed.
- `agx-infer` restarted without `--mode` (20:53:06 BST). `ss -ulpn`: six sockets `0.0.0.0:6000-6005`. Log:
  `rk mode: accept FrameLink datagrams only from 10.0.0.208, 10.0.0.209`.
- Test J1.3, from DA01 at 04:00:06 (ZMQ SUB 10.0.0.130:5561, envelope + capnp decode):
  `env_ok=True flags=0x2 node=RUNNING mode=rk simulated=False`, cams `cam0:NO SIGNAL:front ... cam5:NO SIGNAL:CAM6 (role
  unconfirmed)`. No camera SIMULATED. Result: DONE.
- Rule A4: the full AGX suite gives `1 failed, 135 passed`. The failed test is
  `tests/test_manager.py::test_failed_model_is_isolated_and_stop_start` (`assert trt_match is True`). It fails in the
  same way on the old commit `45840a1` (checked in a temporary worktree inside `tests/out`, removed). Cause: since the
  AGX02 cold start, TensorRT writes "Using an engine plan file across different models of devices" for both engines
  (`trt_match False`; the night run had True). Owner decision (section 12). After all AGX changes of this run
  (HEAD f1927d9, 06:40): `1 failed, 135 passed in 111.14s` - the same single test (log
  `~/driveragent-agx/tests/out/da01/j7_full_suite.log`); nothing written outside the repo.
- Rule A1: the suite wrote into a fixed `/tmp/claude-1000/.../scratchpad` path. Corrected in AGX commit `50be769`
  (pytest base temp). The GStreamer plugin cache `~/.cache/gstreamer-1.0/registry.aarch64.bin` was rewritten 3 times
  by GStreamer itself (automatic cache).

## 4. J2: one camera end to end (front camera)

### 4.1 Encoder decision (J2.2)

The recording encoder (rk-recorder) is not usable for the link:
- It encodes only while it records (`rk/recorder/src/main.cpp` `offer()`; no autostart; idle on DA01 at the start).
  The link would stop when the driver stops recording.
- It encodes RAW 1920x1080. The interface size for cam0 is 1280x720 (fmt 2 option (a)); 1080p decode on the AGX is
  not measured.
- A tap needs a change in rk-recorder and a restart; a link fault could then touch the recordings.

Thus: a second encoder in a new process, `rk-agxlink-tx` (`rk/agxlink/tx`). cam0 uses rk-camd's existing SCALED
NV12 1280x720 stream (DMA-BUF import, no copy). MPP H.265, CBR 3000 kbit/s, GOP 30 (one IDR with VPS/SPS/PPS per
second), no B-frames, no re-encode, synchronous encode (one frame in flight), BT.601 limited VUI. Encode time per
frame: p99 2.0-3.2 ms. FrameLink as RK_AGX_INTERFACE.md section 3 (40-byte header, 16-byte fragments, chunk 1456,
DF set), paced UDP to 10.0.0.130:6000.

### 4.2 Frame table (J2.3)

The sender sends one FRAME notice per access unit to the daemon `rk_agxlink.py` (AF_UNIX datagram): FrameLink cam, seq,
capture time (CLOCK_MONOTONIC of the V4L2 buffer, and CLOCK_REALTIME = the FrameLink `t_capture_ptp_ns`), send time,
rk-camd frame_no and V4L2 sequence. The daemon keeps the last 900 entries per camera. A result is fresh only if its
(camId, frameSeq) is in this table and capture-to-result (DA01 CLOCK_MONOTONIC) is 300 ms or less.

### 4.3 Tests (J2.4, J2.5), 04:17:42-04:24:28

AGX02 (`tools/result_jpeg.py` by the AGX02 agent, REQ-002; internal status 5562; 120 s window 20:19-20:21 BST):

| Item | Value |
|---|---|
| cam0 state / source | OK / live (not SIMULATED), H.265 1280x720 |
| fps | 30.0 (3570 frames in 119 s) |
| lost packets / lost frames / bad / ring overruns / decoder errors / waiting for IDR | 0 / 0 / 0 / 0 / 0 / 0 |
| decode time p50 / p95 / max | 8.5 / 11.8 / 18.9 ms |
| frame age p50 | 7.2 ms |
| YOLOPX (only cam0 sent) | 30.0 results/s, total latency p50 / p95 / p99 77.9 / 84.6 / 91.2 ms |
| DTCP | 10.0 results/s |

Picture `docs/agx_link/j2_cam0.jpg`: frame 1032, "source live (LIVE)", YOLOPX and DTCP results of the same frame
(exact frameSeq match). It is the real DA01 front camera: a 1-s grab on DA01 (`rk/camd/build/camd-consumer --socket
/run/rk-camd/frames.sock --duration 1 --dump ...`, cam0 SCALED NV12) shows the same scene and framing
(`docs/agx_link/j2_da01_cam0_reference.jpg`). The scene is a dark indoor bench with no road objects. The one box
("traffic light 0.31") sits on a small bright point and is a false positive; the drivable-area contour on a box is
false. The DTCP trajectory is drawn with "display only, not for control".

DA01 (daemon result log, 405.5 s): 16158 results, 16156 fresh, 2 stale (the first two results, seq 0, 327 and 347 ms,
while the AGX decoder started), 0 identities not in the table, 0 rejects, 0 tCaptureNs mismatches.
Capture-to-result (DA01 clock only): YOLOPX 29.85/s p50 / p95 / p99 115.8 / 125.9 / 136.7 ms; DTCP 10.0/s
87.1 / 94.6 / 96.2 ms. Result: DONE.

Added load (J2.2, D1 windows with the sender for cam0): sender 1.3-1.6 % of one core (RSS 4.8 MB), daemon 4.0-4.4 %
(RSS 30.6 MB), one more encoder at 30 frames/s (rkvenc IRQ +30/s), eth0 +3.1 Mbit/s. System CPU 19.6 % (baseline 19.5);
HMI 20.83 fps (baseline 20.66); capture 30.0 fps, 0 gaps. With recording: recorder 30.15 fps, 0 drops; encode p99 max
5.2-20.4 ms (baseline 6.3-15.7).

## 5. J3: all online cameras

All six cameras are online, so all six go out: cam0 as above; cam1..cam5 = connectors CAM2..CAM6 in this order
(`[agx_link] slots` in `/etc/driveragent/board.toml`), from the RAW streams: RGA3 copy UYVY 1920x1080 -> NV12 704x396
in own DMA buffers (the RAW buffer goes back right after the copy; never more than one per camera), H.265 CBR
1200 kbit/s.

### 5.1 First run (all six at 30 fps) and the D1 effect

AGX02, 120 s: all six OK, 30 fps, 0 lost frames, 0 lost packets, 0 ring overruns, 0 decoder drops, 0 IDR waits;
decode p50 cam0 10.3 ms, cam1-5 4.1-6.7 ms; frame age p50 6-33 ms; YOLOPX 38.6 results/s in total, DTCP 10/s.

DA01 D1 with recording ON: capture 30 fps, 0 gaps, lend_skips 0; HMI 21.50 fps; recording 30.13 fps, 0 drops. But two
values got worse: rk-camd's own cam0 RGA job p99 max 10.1 ms (baseline 3.6 ms; my RAW copies shared the RGA3 cores and
all cameras deliver at the same FSYNC instant), and the recorder's worst-second encode p99 32.8-56.2 ms (baseline
6.3-15.7 ms; 360 encodes/s on the shared VPU).

### 5.2 Mitigation (in the commit)

- `side_fps_max = 15`: cam1-5 at 15 fps (the AGX takes about 7 frames/s per camera). The GOP follows the sent rate
  (one IDR per second, RK_TASKS K2).
- `rga_core = 2`: the RAW copies on RGA3 core 1; rk-camd asks for any core and gets core 0 (IRQ count: core 0 30/s =
  rk-camd, core 1 75/s = sender).

D1 with recording ON after the mitigation (04:40:03-04:42:03): rk-camd cam0 RGA p99 max 4.4 ms (baseline 3.6);
recorder 30.19 fps, 0 drops, queue depth max 1, worst-second encode p99 11.1-25.7 ms (baseline 6.3-15.7: still about
+10 ms in the worst second, no effect on the recording); HMI 21.27 fps (min 20.6); capture 30 fps, 0 gaps, lend_skips 0,
no_free 0; system CPU 23.3 % (baseline 21.2); sender 4.7 %, daemon 5.5 % of one core; temperature max 40.7 C (baseline
39.8 C).

### 5.3 Per camera (mitigated configuration)

| cam | view | sent fps | AGX fps / lost packets / lost frames | AGX decode p50 ms | YOLOPX results/s | capture-to-result p50 / p95 / p99 ms |
|---|---|---|---|---|---|---|
| 0 | front 120 deg (1280x720) | 30 | 30.0 / 0 / 0 | 8.4 | 6.81 (+ DTCP 10.0) | 113.9 / 141.4 / 158.9 (DTCP 77.5 / 109.1 / 122.3) |
| 1 | fisheye 190 deg, CAM2 (704x396) | 15 | 15.0 / 0 / 0 | 4.6 | 6.81 | 111.5 / 145.5 / 169.4 |
| 2 | 120 deg, CAM3 | 15 | 15.0 / 0 / 0 | 6.6 | 6.81 | 118.3 / 155.0 / 171.0 |
| 3 | 120 deg, CAM4 | 15 | 15.0 / 0 / 0 | 6.5 | 6.81 | 122.9 / 159.0 / 175.2 |
| 4 | 120 deg, CAM5 | 15 | 15.0 / 0 / 0 | 6.6 | 6.82 | 121.7 / 156.5 / 173.5 |
| 5 | 120 deg, CAM6 | 15 | 15.0 / 0 / 0 | 6.6 | 6.81 | 124.6 / 161.4 / 175.0 |

(Capture-to-result: daemon result log, last 100 s at 04:4x; AGX values: internal status at the same time.)

Result quality per view (`docs/agx_link/j3_cam0..5.jpg`, montage `docs/agx_link/j3_montage.jpg`; all "source live",
exact frame match): the cameras look at a dark indoor bench at night, so there are no road objects. cam0: no box, a
false drivable-area contour on a box. cam1 (fisheye): the round wide view of a lit wall; no box (YOLOPX was trained on
120-degree road views; a fisheye view of a road was not available tonight). cam2, cam3: almost black; no box. cam4:
dark shapes; no box. cam5: one false "person 0.36" box on a dark box. All false boxes have a score of 0.31-0.36, near
the 0.30 threshold. A real quality check needs road scenes (owner).

### 5.4 Real numbers compared with the simulator (J3.3)

| Item | Night T3/T4/T5 (sim, 6 x 1280x720 H.265) | J0.2 today (sim) | Real DA01 (J3, mitigated) |
|---|---|---|---|
| fps per camera at the AGX | 30.0 | 30 | cam0 30, cam1-5 15 (by design) |
| lost packets / lost frames | 0 / 0 | 0 / 0 | 0 / 0 |
| decode p50 ms | 8.4-20.3 | 11.9-23.8 (mean recv->ready) | cam0 8.4, cam1-5 4.6-6.6 (704x396) |
| YOLOPX results/s, all cameras | 46.9 (T4) | 41.5 | about 41 (6.81 per camera) |
| YOLOPX total latency p50 / p95 / p99 ms (AGX clock) | 59.5 / 87.4 / 103.1 | 64.6 / 100.7 / 126.5 | 66.6 / 93.3 / 108.8 (first J3 window) |
| DTCP results/s | 10.0 | 10.0 | 10.0 |
| frame-to-result p50 ms | T5 (recv->client): 72-97 | 68-97 (one clock, sim send -> client) | 112-125 (one clock, CAMERA capture -> DA01 result receive) |
| GPU load | 67.6 % (T4) | 62.1 % | 72.5 % (first J3 window) |

The real capture-to-result includes what the simulator does not have: camera exposure to the V4L2 buffer, rk-camd,
the RK encoder, the network both ways, and the daemon checks (about 25-40 ms more).

## 6. J4: the sender as a part of the system

### 6.1 Configuration (J4.1)

`rk/config/rk.toml` `[agx_link]` (repo default **OFF**): `enabled = false`, `host = ""` (= `[hmi.bus] agx_host`),
`base_port = 6000`, `results_port = 5560`, `status_port = 5561`, `slots = []` (cam0 only), `fps_max = 30`,
`side_fps_max = 15`, `rga_core = 2`, `unconfirmed_live = true`, `cam0_kbps = 3000`, `side_kbps = 1200`,
`side_width/height = 704/396`, `gop = 30`, `chunk = 1456`, pacing keys, `stale_ms = 300`, `notify_socket`,
`status_file`, `hmi_endpoint`. Checked with rk-camd's C++ parser (`load_rk_toml OK`, `load_camd_config OK`) before
each write.

DA01 per-board setting (the audited path, `/etc/driveragent/board.toml`):
`rk/ops/daconfig set board agx_link.enabled=true agx_link.slots=["gmsl_des29_linkB","gmsl_des6b_linkA","gmsl_des6b_linkB","gmsl_des6b_linkC","gmsl_des6b_linkD"]`
-> audit entry 2026-10-06T20:37:58Z, backup `history/board.toml.20261006T203758Z.daea22d5d67c`. I added string-array
support to daconfig for this (`test_daconfig: 65 checks passed`). The AGX address comes from the existing
`agx_host = "10.0.0.130"` (set by the owner's session today).

### 6.2 Start and stop like the other parts (J4.2)

- In the repo: `rk/ops/systemd/rk-agxlink.service` (same form as rk-media/rk-console: `User=@USER@`, Type=notify,
  WatchdogSec=10, Restart=on-failure, RestartPreventExitStatus=78 = disabled), `rk/ops/user/rk-agxlink.service`,
  `rk/ops/services.py` (OPTIONAL: `rk-agxlink` <- `[agx_link] enabled`; `services.py table` -> `rk-agxlink on
  agx_link.enabled = true`), `update.sh`/`bootstrap-rk.sh` build and test `rk/agxlink` like the other C++ parts
  (`test_install: 50 checks passed`).
- Not installed: `sudo rk/ops/install.sh` needs the owner's password (rule B6). Tonight rk-agxlink runs as the
  transient user unit `rk-agxlink-bench` (`rk/agxlink/run_user.sh start`), with the same command line and unit
  properties. Limit: `Linger=no`, so it stops when the last session of tonyho ends, and it does not start at boot.
- Owner commands (section 12): `rk/agxlink/run_user.sh stop && sudo rk/ops/install.sh && sudo systemctl start
  rk-agxlink`.

### 6.3 Rule D2 test (J4.3)

Recording ON. `agx-infer` stopped at 05:44:56.3 for 120 s (`tools/svc.sh stop infer`), started at 05:46:57.6.

DA01 during the 150 s window around the outage (D1 tool, `docs/agx_link/data/`):

| Item | During the AGX outage | Baseline (recording ON) |
|---|---|---|
| Capture | 30.0 fps all cameras, 0 seq gaps, lend_skips 0, consumer_drops +0..+1 | 30.0 fps, 0 gaps |
| HMI | fps_mean 21.22 (min 20.7), frame p99 max 66.9 ms | 20.68 (min 20.2), 66.8 ms |
| Recording | 6 x 30.21 fps, ~4820 kbit/s, 0 drops, queue depth max 1, encode p99 max 13.0-19.8 ms | 30.2 fps, 0 drops, 6.3-15.7 ms |
| System CPU | 22.2 % | 21.2 % |
| rk-agxlink (daemon + sender) | 10.1 % of one core, RSS 38.5 MB | - |

The link state on DA01 went DOWN 3.5 s after the stop ("no AgxInferStatus for 3.5 s"). The sender kept running (no
block, no restart).

Recovery, exact measurement on the DA01 clock (`recovery.py`: ZMQ SUB to the AGX status and to the fresh-result feed),
second run with a full 120 s outage (stop 05:54:50, start 05:56:51):
```
GO at 1791323812.220 (start command returned)
first AgxInferStatus +0.649 s
first fresh result cam1 driverguard_yolopx seq 13215 c2r 133.9 ms +3.896 s
first fresh result cam0 driverguard_yolopx seq 26432 c2r 130.6 ms +3.905 s
first fresh result cam2 driverguard_yolopx seq 13217 c2r 67.9 ms +3.924 s
first fresh result cam3 driverguard_yolopx seq 13217 c2r 92.3 ms +3.949 s
first fresh result cam4 driverguard_yolopx seq 13217 c2r 103.0 ms +3.959 s
first fresh result cam5 driverguard_yolopx seq 13217 c2r 170.3 ms +4.026 s
messages before GO (must be 0 while the AGX is off): 0
```
Streams and results are back in 3.9-4.0 s on all six cameras, without any action on DA01. Most of this time is the AGX
engine load (status PUB bound +1.0 s, models RUNNING +4.3 s after the start command in the AGX log). A 30 s outage gave
the same result (+3.94 to +4.07 s). Result: J4.3 DONE.

## 7. J5: results and status on DA01, dashboard

- J5.1: `rk/agxlink/rk_agxlink.py` subscribes to tcp://10.0.0.130:5560 and :5561. Every message passes the dabus
  envelope checks (magic, version, length, CRC-32C, src_board 1, type_id = port, schema hash 0xafcaff02 /
  0x9086fa18 computed from `rk/agxlink/schema/agx_infer.capnp`, a byte-identical copy of AGX_REPO/proto, sha256
  75a6e87c...). Decode with pycapnp. In 30 min of operation: 0 rejects.
- J5.2: capture-to-result = DA01 CLOCK_MONOTONIC at receive - capture time from the frame table (no cross-board clock).
  Per camera in section 5.3 and section 9.
- J5.3: stale = not in the frame table, or capture-to-result > 300 ms. Stale results are counted (late / unknown_id)
  and are not given to the HMI. J2: 2 stale of 16158 (the first two results). J3: 1 of 238078.
- J5.4: rk_console panel "AGX link" (`rk/console/rkconsole/agxlink.py`, `ui/src/pages/AgxLink.jsx`, GET
  `/api/v1/agx_link`). Console suite: `185 passed, 8 skipped`. The live rk-console must be restarted to load it
  (sudo with password, owner) after `rk/console/build.sh` (ui/dist). Check on a second instance (127.0.0.1:8702,
  scratch UI build, the real status file, 05:57):
  ```
  link UP green ok host 10.0.0.130 sender {'running': True, 'restarts': 0, 'camd_connected': True}
  cam0 front        sent=True tx_fps=30.0 rps={'driverguard_dtcp': 10.0, 'driverguard_yolopx': 7.2} c2r p50/p95=83.4/125.7 stale=0
  cam1 fisheye-190  sent=True tx_fps=15.0 rps={'driverguard_yolopx': 7.4} c2r p50/p95=111.7/143.9 stale=0
  cam2 video11      sent=True tx_fps=15.0 rps={'driverguard_yolopx': 7.2} c2r p50/p95=118.3/149.5 stale=0
  cam3 video12      sent=True tx_fps=15.0 rps={'driverguard_yolopx': 7.2} c2r p50/p95=118.0/152.5 stale=0
  cam4 video13      sent=True tx_fps=15.0 rps={'driverguard_yolopx': 7.4} c2r p50/p95=111.6/144.3 stale=0
  cam5 video14      sent=True tx_fps=15.0 rps={'driverguard_yolopx': 7.4} c2r p50/p95=115.7/147.4 stale=0
  agx RUNNING rk simulated False [('driverguard_yolopx', 'RUNNING', 44.0, 77.5, 112.1), ('driverguard_dtcp', 'RUNNING', 10.0, 40.7, 49.1)] [('cpu-thermal', 66.3), ('gpu-thermal', 62.2), ('soc0-thermal', 63.0)] errors []
  results {'received': 26678, 'rejected': 0, 'reject_reasons': {}, 'fresh_total': 26678, 'stale_total': 0, 'forwarded_to_hmi': 26678}
  ```
  Not checked: the page in a browser (no browser on DA01); the API and the page bundle are served.

## 8. J6: results on the HMI

- Setting "Show AGX results" = the Cameras screen hero toggle ("AGX results: ON/OFF"), saved in the HMI state file,
  default OFF. The HMI reads only the FRESH results that rk-agxlink forwards (never stale ones).
- Drawn on the correct camera view (hero, grid, filmstrip), with the same geometry as the video (fit/fill, mirror,
  turn): boxes and class names with score; the schema has masks and a trajectory, so the drivable-area and lane-line
  masks and the DTCP trajectory are drawn too (trajectory with "DISPLAY ONLY · virtual perspective, not calibrated ·
  inputs assumed"). No new result of a camera for 500 ms: its drawing goes away (unit-tested).
- Test (06:03:45-06:04:17): display taken over (lightdm start/stop), HMI run with the setting ON, a tap on each
  filmstrip thumbnail and a screenshot of each hero view (`docs/agx_link/j6_hmi_hero0..5.jpg`, montage
  `j6_hmi_montage.jpg`); kiosk restored with the 5-unit restart. 1530 results drawn, 0 draw errors, 19.5-20.1 fps.
  - cam0 front: no object in view; the drivable-area mask is drawn on the box at the left, the same place as the AGX's
    own picture of that camera (J2); the DTCP trajectory with the "DISPLAY ONLY" text.
  - fisheye-190, video11, video12, video13: no detection in these frames.
  - video14 (cam5): two low-score "person" boxes on the dark equipment area, the same place where the AGX's own
    cam5 picture (J3) put its "person 0.36" box. The geometry agrees; the detections are false (no person there).
  - Thus: the boxes are drawn on what the model detected, at the right place; on this dark bench there is no real
    object to show a correct detection.
- First run of this test found a crash (pyray `update_texture` needs a `void *`): fixed before the live HMI got the
  code; drawing errors now never stop the HMI. Live HMI after the restart (setting OFF): 20.4-20.6 fps (baseline 20.66).

## 9. J7: 30-minute run (06:06:14-06:36:19)

Full chain: DA01 rk-agxlink-bench (sender + daemon), all six cameras, AGX02 agx-infer (rk mode), results to the DA01
daemon and the HMI feed; HMI setting OFF (the delivered state); recording OFF. Start window 06:06:15-06:08:15, end
window 06:34:14-06:36:14 (DA01 D1 tool and the AGX measurement script, 120 s each); DA01 link status every 10 s
(180 samples). Data: `docs/agx_link/data/j7_*`.

| Item | Start | End |
|---|---|---|
| Link state (180 samples) | UP | UP (180 of 180) |
| Results (30 min) | - | 92909 received (51.9/s), 92909 fresh, 0 stale, 0 rejected, 92909 to the HMI feed |
| Restarts | - | DA01: sender 0, rk-agxlink-bench 0, rk-camd/rk-hmi 0; AGX02: agx-infer 0 (agx-dashboard 1 planned restart for REQ-005) |
| DA01 capture | 30.0 fps, 0 seq gaps | 30.0 fps, 0 seq gaps |
| DA01 HMI | 20.80 fps (min 20.5) | 20.90 fps (min 20.7) |
| DA01 system CPU | 20.8 % | 19.7 % |
| DA01 rk-agxlink CPU / RSS | 13.8 % of one core / 40.5 MB | 13.0 % / 41.0 MB |
| DA01 MemAvailable | 5966 MB | 6079 MB |
| DA01 temperature (max) | 40.7 C | 39.8 C |
| DA01 power | not measurable (no board sensor) | - |
| DA01 eth0 transmit | 9.58 Mbit/s | 9.55 Mbit/s |
| AGX cameras (120 s) | all OK 120/120; 30 / 15 fps; lost packets +0, lost frames +0 | the same |
| AGX YOLOPX results/s; total latency p50/p95/p99 (AGX clock) | 43.1; 77.4/113.1/126.7 ms | 41.2; 78.2/113.6/132.0 ms |
| AGX DTCP | 10.0/s | 10.0/s |
| AGX GPU load (sysfs 1 Hz / tegrastats GR3D) | 73.5 % / 58.2 % | 67.3 % / 56.1 % |
| AGX CPU (12 cores) | 27.1 % | 25.3 % |
| AGX temperature cpu / gpu / tj | 70.8 / 66.5 / 70.8 C | 71.4 / 67.0 / 71.6 C |
| AGX power (rails) VDD_GPU_SOC + VDD_CPU_CV + VIN_SYS_5V0 | 13.26 + 2.07 + 7.59 = 22.9 W | 12.66 + 1.67 + 7.51 = 21.8 W |
| AGX agx-infer RSS | 1426.2 MB | 1427.9 MB |
| AGX MemAvailable | 59147 MB | 59152 MB |

Capture-to-result per camera (DA01 clock, mean of the 60-s p50 / p95 values over the 30 min): cam0 84.2 / 131.4 ms
(YOLOPX and DTCP together), cam1 111.8 / 148.2, cam2 112.8 / 146.7, cam3 114.9 / 150.1, cam4 116.2 / 151.4,
cam5 113.8 / 147.6 ms. Results/s per camera about 7.0 (YOLOPX) + 10.0 DTCP on cam0.

Observation: rk-camd's cam0 RGA p99 per second was 1.7-2.1 ms in almost all seconds (26 min between the windows: p50
1.84 ms, p95 2.14 ms), with rare single seconds up to 28.5 ms (end window: one 4.9 ms and one 12.3 ms second). A
26-minute baseline without the link was not measured, so I cannot say if these single spikes are new.

## 10. Interface changes (rule I1)

None. Both sides use RK_AGX_INTERFACE.md as written (FrameLink header and fragments, fmt 2 H.265, ports, envelope,
schema v1, hashes). Choices inside the interface (no document change needed):
- `seq` = one counter per FrameLink camera and encoded access unit (a dropped AU keeps its number, so the AGX sees the
  gap); the RK keeps the table seq -> capture time (section 3.8 of the interface allows this).
- cam0 1280x720 from the rk-camd SCALED stream; cam1..cam5 704x396; cam1-5 at 15 fps (`side_fps_max`; the interface
  gives no rate); an IDR with VPS/SPS/PPS at least once per second at the sent rate.
- Source byte 1 (LIVE) also for the role-unconfirmed cameras cam1..cam5 (`unconfirmed_live = true`). RK_TASKS.md K1
  (an AGX proposal, not part of the interface) asks for LIVE only with a CONFIRMED camN. The frames are real camera
  frames; a non-live label would be a false label (rule B4). The roles show as "role unconfirmed" on both sides.
  Owner decision O6 (section 12).

## 11. Defects corrected

| Machine | Defect | Correction | Proof |
|---|---|---|---|
| AGX02 | The rk-mode camera roles came from the old recordings (cam1 "right" = in fact the DA01 fisheye) | `role_rk` labels (78d05dc) | J1.3 status output |
| AGX02 | `rk_allowed_sources` empty: any LAN host could send FrameLink | DA01 addresses only (78d05dc) | agx-infer log line |
| AGX02 | `tests/test_manager.py` wrote into a fixed `/tmp/claude-1000/...` path (rule A1) | pytest base temp (50be769) | suite run, `find /tmp -newer` |
| AGX02 | Dashboard "RK link" pinged DA01 over tailscale (rk_ip 100.64.0.180), not the LAN link | rk_ip 10.0.0.208 (f1927d9, REQ-005) | `/api/link`: rk_ip 10.0.0.208, ping 0.77-0.91 ms, loss 0 %; dashboard tests 46 passed |
| DA01 | (new code) RGA jobs of the sender delayed rk-camd's cam0 RGA job; 360 encodes/s on the shared VPU | RGA core 1 for the sender, cam1-5 at 15 fps | section 5.2 |
| DA01 | (new code) GOP longer than 1 s at 15 fps | GOP limited to the sent rate | review fix, probe |
| DA01 | (new code) HMI crash in the mask texture update | `void *` cast; overlay errors never stop the HMI | J6 test |
| DA01 | (new code) bootstrap ran the sender tests without the vectors file (blocked updates) | argument added | ops review |

Found, NOT corrected (outside the task or not allowed):
- DA01: the DisplayPort IRQ thread `irq/66-fde50000.dp` (SCHED_FIFO 50) holds CPU0 at about 95 % all the time; all
  IRQs go to CPU0. This can explain the HMI rate of about 20.7 fps (target 60).
- AGX02: since the cold start, TensorRT warns "engine plan file across different models of devices" (`trt_match
  False`) for both engines; 1 test fails; YOLOPX is slower than last night (6.9-7.4 vs 7.8 per camera).
- AGX02: `AgxInferStatus.Camera.frameAgeMs` can be negative (min -5.9 ms; `infer/ingest/metrics.py:117` reads `now`
  before the store read).
- AGX02: agx-infer stalls 20-100 ms after each wall-clock second (probably a 1 Hz task).
- AGX02: `capture_to_ready_ms` in the internal status subtracts the DA01 capture time from the AGX clock; with real
  RK frames this is a cross-clock value (about 93 ms, of which about 80 ms is the clock offset).

## 12. Blockers and decisions for the owner

Blockers (steps that need the owner's password or decision; not done, rule B6):
1. Install rk-agxlink as a system unit on DA01: `rk/agxlink/run_user.sh stop; sudo /home/tonyho/driveragent/rk/ops/install.sh; sudo systemctl start rk-agxlink`.
   Tonight it runs as the transient user unit `rk-agxlink-bench` (stops at logout, no start at boot).
2. Show the "AGX link" panel in the live rk_console: `/home/tonyho/driveragent/rk/console/build.sh; sudo systemctl restart rk-console`.
3. Optional: add `rk-agxlink.service` to the NOPASSWD restart rule and to `rk/updater/rk_updater.py` units (then the
   release health check can include it).
4. AGX02 `trt_match False` (see 11): reboot AGX02 and check `python -m tools.inspect_engines`, or rebuild the two
   engines on this AGX, or accept and relax the test.

Decisions (my recommendation first):
| # | Decision | Recommendation | Reason |
|---|---|---|---|
| 1 | Clock synchronisation with chrony (RK + AGX), later PTP | Yes: chrony on both, the AGX as the server for the RK; PTP after Link C | The two clocks differ (about 80 ms seen in `capture_to_ready_ms`); without sync no cross-board time is valid, only RK-clock capture-to-result (as here) |
| 2 | Sender ON by default | Repo default stays OFF (`[agx_link] enabled = false`); ON per board in `/etc/driveragent/board.toml` (DA01 is ON now) | A board without an AGX must not send |
| 3 | Install the AGX services at boot | Yes: `bash ~/driveragent-agx/systemd/install_units.sh` (asks for sudo), then `sudo systemctl enable agx-infer.service agx-dashboard.service`; or at least `loginctl enable-linger tonyho` | Today a reboot of AGX02 (as at 10:12 BST) stops the link until somebody starts the services |
| 4 | Install rk-agxlink as a system unit on DA01 | Yes (blocker 1) | Same reason on the RK side |
| 5 | Camera roles cam1-cam5 (O6) and the LIVE label | Confirm the roles in camera_map.ini; until then keep `unconfirmed_live = true` (real frames) or set it to false (the AGX shows them SIMULATED) | B4 vs the K1 proposal |
| 6 | cam1-5 frame rate | Keep `side_fps_max = 15` | Recorder encode time and rk-camd RGA stay near baseline; YOLOPX takes about 7 frames/s per camera |
| 7 | YOLOPX on side/fisheye cameras | Decide with road data | False boxes at score 0.31-0.36 on the bench; no road scene tonight |
| 8 | AGX `rmem_max` 8 MiB (O3), Link C (O2) | Later | H.265 needs little buffer; NV12 would need it |
| 9 | Keep the DA01 commits | Make a branch or tag at the last commit (I made none: rule B3) | The commits sit on a detached HEAD at rk-v0.5.1; `rk/ops/update.sh` moves HEAD to a release tag |

## 13. Rule notes

- B3: DA01 commits are on the detached HEAD at rk-v0.5.1 (no branch made). AGX commits on `main` (repo-local git
  identity "AGX night agent"). No push.
- B6: the owner allowed the AGX02 agent "development" during the run; it did the AGX work of J1 and the J2.4 picture
  tool on written requests (`~/driveragent-agx/tests/out/da01/REQ-001..005.md` and results).
- A2: one J0 sub-agent ran `sudo -n true` on AGX02 at about 20:13 BST (password required, nothing ran).
- A1: GStreamer rewrote its own plugin cache `~/.cache/gstreamer-1.0/registry.aarch64.bin` at agx-infer starts and
  test runs (automatic). The old suite wrote test files into `/tmp/claude-1000/...` (fixed in 50be769).
- D1 test recordings on DA01 (rec_ctl.py start/stop): `/mnt/nvme/driveragent/20261006T192027Z`, `20261006T202135Z`,
  `20261006T202804Z`, `20261006T203950Z` (457-458 MB each) and `20261006T214434Z` (560 MB, the D2 test).
  Delete them if not needed.
- The simulator: `agx-sim` was not running at my start; I started it for J0.2 only (20:09:03-20:47:17 BST).

## 14. The link left in operation, and how to put the simulator back

State at the end: DA01 sends all six cameras (rk-agxlink-bench, `[agx_link] enabled = true`); AGX02 `agx-infer` in
`mode: rk`, `agx-sim` stopped.

Simulator back (AGX02):
```
cd ~/driveragent-agx
tools/svc.sh stop infer
sed -i 's/^mode: rk/mode: sim/' config/sources.yaml     # or: tools/svc.sh start infer --mode sim (one time)
tools/svc.sh start infer
tools/svc.sh start sim --sessions road
```
In sim mode the receiver binds 127.0.0.1, so DA01 frames do not arrive (and must not: stop the DA01 sender with
`rk/agxlink/run_user.sh stop` to save the LAN). Back to the real board: `tools/svc.sh stop sim`, set `mode: rk`,
`tools/svc.sh restart infer`, `rk/agxlink/run_user.sh start` on DA01.
