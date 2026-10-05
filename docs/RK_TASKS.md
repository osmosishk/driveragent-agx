# RK3588 tasks: six camera streams to the AGX, AGX results on the RK HMI

| Item | Value |
|---|---|
| Document | `docs/RK_TASKS.md` (task T7) |
| Date | 2026-10-05 (night run) |
| For | The RK3588 agent (repository `driveragent-hmi`, tag `rk-v0.4.0`, board DA01 `rk3588-da01`) |
| From | The AGX side (agx02, `/home/tonyho/driveragent-agx`) |
| Interface | `docs/RK_AGX_INTERFACE.md` (sections 2-12). This file gives the work. That file gives the contract. |
| RK paths | Relative to the RK repository root (read-only copy: `/home/tonyho/driveragent-agx/ref/driveragent-hmi`) |
| AGX paths | Relative to `/home/tonyho/driveragent-agx` |
| Task names | K1..K9 = tasks. O1..O8 = owner decisions. "R" + number (for example R5, R13) = an owner night rule. This file uses no R number as a task name. |
| Status | Proposal. The owner and the RK agent must accept each item marked "AGX proposal". |

## 0. Reason for this task list (T7.1 check)

Result of the T7.1 check: **the RK3588 does NOT give the six streams in a form that the AGX can pull without a change on the board.**

| # | Fact | Source |
|---|---|---|
| 1 | FrameLink TX is not implemented at rk-v0.4.0: "FrameLink TX deferred by Tony until after the HMI". | `rk/docs/STATUS.md:291` |
| 2 | No other video sender exists on the RK (no RTP, RTSP or GStreamer sender). The recorder writes H.265 to local disk only. | `docs/research/T1_rk-repo.md` section 3 |
| 3 | The board config sends every socket to `agx_host = "10.42.0.1"`. This is Link C. Link C is not configured on the AGX or on the RK. | `rk/config/rk.toml:152`; `rk/boards/rk3588-da01/board.toml:23-24`; `rk/docs/RECOVERY.md:28`; `docs/research/T1_rk-probe.md` section 6 |
| 4 | Over tailscale, the board answers only on TCP 22, 111, 4000 and 5555. All DriverAgent ports (5572, 5588-5614, 6000-6005, 8010, 8014) are closed. The board sends no traffic to the AGX. | `docs/research/T1_rk-probe.md` sections 4 and 6 |
| 5 | The night rules allow no change on the board and no network change. | Night rules (R5: `docs/RK_AGX_INTERFACE.md:59`) |

Thus the AGX cannot get live video tonight. The RK agent must do the tasks below. The owner must make the decisions in Section 3.

## 1. Task summary

| Task | Title | Owner decision | Can start before Link C |
|---|---|---|---|
| K1 | FrameLink TX in rk-camd (C++17), NV12 | O5, O6 | Yes (loopback on the RK). Full test needs K3. |
| K2 | (Optional) H.265 payload, fmt 2 | O8 | Yes (loopback). Full test needs K3. |
| K3 | Link C: addresses, MTU 9000, socket buffers | O2, O3, O7 | No (needs the cable and sudo on both boards) |
| K4 | Result and status subscriber on the RK (driveragent-proto, rk.toml, bus.py) | O1 | Yes (over tailscale, results only) |
| K5 | Overlay on the camera tiles | O1 | Yes (with SIMULATED results). Live frame match needs K1 + K3. |
| K6 | AGX status on the RK dashboard | O1 | Yes (over tailscale) |
| K7 | Time: PTP or chrony | O4 | chrony: yes. PTP: needs K3. |
| K8 | Confirm or change the FrameLink proposals | O5 | Yes (do it first) |
| K9 | (Later) CameraHealth 5572 to the AGX | - | Agree the date only |

## 2. Order and dependencies

### 2.1 Order

| Step | Task | Do this | Needs |
|---:|---|---|---|
| 1 | K8 | Confirm the FrameLink bytes. If you change a value, tell the AGX side before you write code. | - |
| 2 | K1 | Write the sender. Test it with the golden vectors and on loopback (127.0.0.1) on the RK. | K8 |
| 3 | K4 | Add the two structs and channels. Test against the AGX over tailscale `tcp://100.64.0.20:5560` and `:5561`. | O1 |
| 4 | K6 | Show the AGX status chip. Test over tailscale. | K4 |
| 5 | K5 | Draw the overlay. Test with the AGX in sim mode (results are SIMULATED). | K4 |
| 6 | K3 | Connect Link C. Configure both ends. | O2, O3, O7 |
| 7 | K1 | Run the full six-camera test over Link C. | K1, K3, O6 |
| 8 | K5 | Test the live frame match over Link C. | K1, K3, K5 |
| 9 | K7 | Start chrony now. Start PTP after K3. | O4, K3 |
| 10 | K2 | Only if the owner selects H.265 (O8). | K1, K3, O8 |
| 11 | K9 | Agree the date with the AGX side. | K3 |

### 2.2 What works before Link C exists

| Path | Use | Do not use for | Source |
|---|---|---|---|
| Loopback 127.0.0.1 on the RK | K1 and K2 sender tests with a local receiver (K1 test 2a) | - | - |
| tailscale `tcp://100.64.0.20:5560` and `tcp://100.64.0.20:5561` | K4, K5 (SIMULATED results), K6 | Video. The path goes through the DERP relay `lhr` (RTT about 12.6 ms) and tailscale0 has MTU 1280. NV12 needs 335 Mb/s for cam0 alone. | `docs/research/T1_rk-probe.md` section 1, 2; `docs/RK_AGX_INTERFACE.md:74`; `rk/docs/BRINGUP_REPORT.md:782-800` |
| tailscale `http://100.64.0.20:8700/api/health` | K6 HTTP test | - | `config/dashboard.yaml` keys `port`, `allow_cidrs` (100.64.0.0/10 allowed) |

Before the tailscale test, check the tailscale mode on the RK: `ip -br addr show tailscale0`. Pass: the interface exists and has `100.64.0.180`. The RK repo says that tailscaled on da02 uses userspace networking (`rk/docs/RECOVERY.md:26`). In that mode, `tailscale0` does not exist, and a local connect to `100.64.0.20` does not go through tailscale. Then the tailscale test is not possible without a SOCKS5 proxy. Tell the owner.

To use tailscale for K4-K6, set `[hmi.bus] agx_host = "100.64.0.20"` in the board override (`rk/boards/rk3588-da01/board.toml:23-24`) for the test only. This is a change on the board. Do not do it tonight (R5). Get the owner's OK first. Set it back to `"10.42.0.1"` after the test.

## 3. Owner decisions

O1-O6 are in `docs/RK_AGX_INTERFACE.md:557-564`. O7 and O8 are new in this file.

| # | Decision | AGX recommendation | Tasks |
|---|---|---|---|
| O1 | Registry channels for AGX results and status | Add `agx_perception` 5560 and `agx_infer_status` 5561 to driveragent-proto, status `proposed` | K4, K5, K6 |
| O2 | Link C setup (10.42.0.1/30 <-> 10.42.0.2/30, MTU 9000) | Configure after the night run | K3 |
| O3 | AGX `net.core.rmem_max` | 8388608, as `rk/ops/etc/sysctl-driveragent.conf:7-9` | K3 |
| O4 | Time sync | PTP (kick-off M3, AGX grandmaster), or at least chrony on both boards | K7 |
| O5 | FrameLink proposals | Accept the values in `docs/RK_AGX_INTERFACE.md` section 3 | K1, K8 |
| O6 | cam1-5 roles | Confirm them in `camera_map.ini`. Today cam1-5 are `unknown` / `unassigned` / `UNCONFIRMED` (`rk/boards/rk3588-da01/vehicle/camera_map.ini:289-312`). | K1 |
| O7 (new) | AGX Ethernet port for Link C | The AGX has one Ethernet interface, `eno1`. It carries the LAN uplink 10.0.0.130/24 at MTU 1500 today (Check: `ip -br addr`, `/sys/class/net/eno1/mtu`). The kick-off puts Link C on `eno1` (`RK3588_AGENT_KICKOFF.md:100`). The other AGX network interfaces are Wi-Fi `wlP1p1s0` (DOWN), `tailscale0`, `docker0`, `l4tbr0`, `usb0`, `usb1`, `can0`, `can1` (Check: `ls /sys/class/net`). The owner must select: a second Ethernet NIC on the AGX for Link C, or move the AGX uplink off `eno1` (for example to Wi-Fi). | K3 |
| O8 (new) | FrameLink payload: NV12 (fmt 1) or H.265 (fmt 2) | NV12 first (the RK design). H.265 only if NV12 loss stays above 0.1 % after K3 or if the link is needed for other traffic. | K2 |

## 4. What the AGX provides tonight

All AGX commands start in `/home/tonyho/driveragent-agx`.

| Item | State / value | Command or file |
|---|---|---|
| Inference node `agx-infer` | Running. `agx-infer`, `agx-dashboard` and `agx-sim` run as transient systemd user units (`agx-dashboard` started 22:43, `agx-infer` 23:11, `agx-sim` 23:16 on 2026-10-05; `tools/svc.sh status`). These units stop when the last session of `tonyho` ends (Linger=no) and at reboot. The input is SIMULATED (mode `sim`). | Start: `tools/svc.sh start infer`. Start in rk mode: `tools/svc.sh start infer --mode rk` (`tools/svc.sh` usage comment, `exec_of()`, `start` case; `infer/main.py` `main()` option `--mode`). Stop: `tools/svc.sh stop infer`. Logs: `tools/svc.sh logs infer`. |
| Source mode | `mode: sim` (`config/sources.yaml` key `mode`) | Switch to rk: (a) set `mode: rk` in `config/sources.yaml` (key `mode`), or (b) set `AGX_INGEST_MODE=rk` (`infer/ingest/ingest.py` `Ingest.__init__()`), or (c) pass `--mode rk` (`infer/main.py` `main()` option `--mode`). |
| FrameLink receive | UDP 6000-6005. Bind 127.0.0.1 in sim mode, 0.0.0.0 in rk mode. | `config/sources.yaml` key `bind_host` |
| Results | ZMQ PUB `tcp://0.0.0.0:5560`, `AgxPerceptionResult` v1 | `config/infer.yaml` keys `ports.results`, `bind.results` |
| Status | ZMQ PUB `tcp://0.0.0.0:5561`, `AgxInferStatus` v1, 1 Hz | `config/infer.yaml` keys `ports.status`, `bind.status`, `status_period_s` |
| Dashboard | Running. TCP 8700 (next free port if busy; see `data/dashboard_port`). HTTP Basic auth. `GET /api/health`. | `config/dashboard.yaml` keys `port`, `port_file`, `bind`; `dashboard/app.py` `create_app()` route `/api/health` |
| Schema | `proto/agx_infer.capnp`. Hashes: `AgxPerceptionResult` = `0xafcaff02`, `AgxInferStatus` = `0x9086fa18` (computed again for this file). | `docs/RK_AGX_INTERFACE.md:267` |
| Stale rule | No frame for 0.5 s: STALE, no result. No frame for 1.0 s: NO SIGNAL. | `config/sources.yaml` keys `stale_s`, `no_signal_s` |
| Socket receive buffer | `net.core.rmem_max` = 212992 B (Check). `rcvbuf_bytes: 0` = use the maximum. | `config/sources.yaml` key `rcvbuf_bytes` |
| Max FrameLink frame | 2097152 B | `config/sources.yaml` key `max_frame_bytes` |
| Link C | Not configured. No 10.42.0.x address. `eno1` MTU 1500. | Check; `docs/research/T1_rk-probe.md` section 6 |
| Ingest probe | Prints camera state, fps, loss; writes JSON | `infer/ingest/probe.py`. Stop `agx-infer` first: both bind UDP 6000-6005. |
| C++ sender reference | `tools/framelink_ref/` (`framelink.h`, `test_framelink.cpp`, `golden_vectors.txt`, `README.md`). Built and run on the AGX for this file: `3 vectors, 0 failed`. | `tools/framelink_ref/README.md` |
| Python sender reference | `tools/rk_sim/` (pacing in `tools/rk_sim/sender.py` class `FrameLinkSender`) | `.venv/bin/python -m tools.rk_sim --config config/sim.yaml --fmt nv12 --host <ip>` |
| Example subscriber | `tools/rk_result_client/` (`__main__.py`, `README.md`). It checks every envelope and decodes every message. Exit code 0 = all checks pass, 1 = a check failed, 2 = setup error (`tools/rk_result_client/__main__.py` module docstring). | `.venv/bin/python -m tools.rk_result_client --host <agx> --seconds 60 --expect-cams 0,1,2,3,4,5 --json <file>` |
| Measured receive (T3) | H.265, 6 cameras, 300 s: 30.0 fps, 0 lost frames. NV12 at RK sizes, 806 Mb/s, 60 s: 0 to 2 lost frames of about 1830 per camera (0.11 % or less), UDP RcvbufErrors +58, with rmem_max 212992 B. | `docs/test_results/T3_RESULT.md:5-6`, `:100-114` |

---

## K1. FrameLink TX in rk-camd (C++17), NV12

### Goal

rk-camd sends the SCALED NV12 frames of cam0..cam5 to the AGX with FrameLink over UDP. The AGX ingest shows six cameras in state OK, labelled live.

### Where in the RK repo

| Path | Change |
|---|---|
| `rk/camd/src/framelink_tx.h`, `rk/camd/src/framelink_tx.cpp` (new) | Packer, fragmenter, paced UDP sender, counters. Use `tools/framelink_ref/framelink.h` (copy it, or produce the same bytes). |
| `rk/camd/src/camera.cpp:192-217` (`Camera::handle_frame`, SCALED branch) | Give each SCALED frame (after `server_.publish`, `:214`) to the sender of that camera. |
| `rk/camd/src/config.h`, `rk/camd/src/config.cpp` | Read the new table `[camd.framelink]`. |
| `rk/config/rk.toml` (after `[camd.zmq]`, `:39-42`) | Add `[camd.framelink]` (see spec). |
| `rk/camd/CMakeLists.txt:40-41`, `rk/camd/build.sh` | Add `framelink_tx.cpp` to `rk-camd`. Add the golden-vector test to `camd-tests` (`CMakeLists.txt:56-62`). `camd-tests` links only `camd_core` (`:37`, `:57`). Thus put the packer (no sockets) in `camd_core`, or compile it into `camd-tests` too. Copy `golden_vectors.txt` to `rk/camd/tests/` (the test gets that folder as its argument, `:62`). |
| `rk/camd/tests/test_main.cpp` | New test: the rk-camd packer reproduces `golden_vectors.txt`. |
| `rk/docs/STATUS.md` | Write the plan first (kick-off rule, `RK3588_AGENT_KICKOFF.md:145`). |

### Exact spec

Frame header (40 bytes, little-endian) and fragment header (16 bytes): `docs/RK_AGX_INTERFACE.md` sections 3.2 and 3.6. Reference code: `tools/framelink_ref/framelink.h` `pack_frame()`, `fragments()`, `crc32c()`. AGX receiver: `common/framelink.py` `pack_frame()`, `unpack_frame()`, `fragments()`.

Header fields:

| Field | Value | Source |
|---|---|---|
| `magic` | `0x4B4E4C46` (wire `46 4C 4E 4B`) | AGX proposal (`common/framelink.py` `MAGIC`); confirm in K8 |
| `ver` | 1 | AGX proposal (`common/framelink.py` `VERSION`) |
| `cam` | camN from `camera_map.ini`, 0..5. Never send a stream with cam_id 255 (`--bench`, unlabelled; `rk/camd/src/protocol.h:33`). | RK repo |
| `fmt` | 1 = NV12 | AGX proposal (`common/framelink.py` `FMT_NV12`) |
| `health` | rk-camd LinkState of the camera at send time: 0 NotStarted, 1 Starting, 2 Live, 3 Stalled, 4 NoSignal. Value from `Camera::state_` (`rk/camd/src/camera.h:106`). | Codes: `rk/camd/src/protocol.h:121`. Use: AGX proposal |
| `seq` | Low 32 bits of the rk-camd `frame_no` of the SCALED stream (`rk/camd/src/camera.cpp:211`). It increases by 1 for each SCALED frame. | AGX proposal (`docs/RK_AGX_INTERFACE.md:220`) |
| `t_capture_ptp_ns` | CLOCK_REALTIME at capture, until PTP: `t_capture_ns` (V4L2 timestamp, CLOCK_MONOTONIC, `rk/camd/src/protocol.h:105`) + (CLOCK_REALTIME - CLOCK_MONOTONIC), sampled when you send. rk-recorder uses the same method (`rk/recorder/src/main.cpp:449`). After M3 (PTP), use the same formula: phc2sys then disciplines CLOCK_REALTIME. | AGX proposal (`docs/RK_AGX_INTERFACE.md:221`) |
| `w`, `h` | Width and height of the SCALED layout. cam0 1280 x 720. cam1-5 704 x 396. | `rk/config/rk.toml:62-90` |
| `stride` | Luma row bytes of the SCALED layout (= width) | `rk/camd/src/rga_scaler.cpp:35-43` |
| `exposure_us` | 0 (unknown) | Same rule as `CameraHealth.exposureUs` (`rk/proto/schema/message.capnp:27`) |
| `source` | 1 = LIVE only for a frame from a real camera with a CONFIRMED camN. 2 = REPLAY. 3 = TEST_PATTERN. | 1: `RK3588_AGENT_KICKOFF.md:86`. 2, 3: AGX proposal (`common/framelink.py` `SOURCE_LIVE`, `SOURCE_REPLAY`, `SOURCE_TEST_PATTERN`) |
| `reserved` | 0, 0, 0 | AGX proposal |
| `payload_crc32c` | CRC-32C over the payload (bytes 40..end). Compute it first. | AGX proposal (`common/framelink.py` `pack_frame()`) |
| `header_crc32c` | CRC-32C over header bytes 0..35. These bytes include `payload_crc32c`. | AGX proposal (`common/framelink.py` `pack_frame()`) |

CRC-32C: Castagnoli, reflected polynomial `0x82F63B78`, init `0xFFFFFFFF`, final xor `0xFFFFFFFF`. Check value: `crc32c("123456789") = 0xE3069283`. This is the dabus envelope CRC (`rk/proto/envelope/dabus_envelope.py:42-59`, `:158`). Use the ARMv8 CRC32C instructions. A table CRC is also correct.

Payload (NV12): Y plane (`stride * h` bytes), then the interleaved CbCr plane (`stride * h / 2` bytes) (`rk/camd/src/rga_scaler.cpp:35-43`). Do not convert colour. The AGX does the single YUV->RGB conversion (BT.601 limited, `rk/config/rk.toml:50-57`).

Sizes and datagrams:

| Item | cam0 1280 x 720 | cam1-5 704 x 396 | Source |
|---|---|---|---|
| Payload | 1382400 B | 418176 B | 1.5 x stride x h |
| Frame (header + payload) | 1382440 B | 418216 B | - |
| Datagrams at MTU 9000 (chunk 8896 B, UDP payload 8912 B) | 156 | 48 | `RK3588_AGENT_KICKOFF.md:86`; `docs/test_results/T3_RESULT.md:102` |
| Datagrams at MTU 1500 (chunk 1456 B, UDP payload 1472 B) | 950 | 288 | `rk/docs/BRINGUP_REPORT.md:1593` |
| Rate at MTU 9000 | 334.9 Mb/s | 6 cameras: 841.4 Mb/s | `rk/docs/BRINGUP_REPORT.md:782-800` |

Transport:

| Item | Value | Source |
|---|---|---|
| Destination | UDP `<agx_host>:6000+cam`. `agx_host` = 10.42.0.1 (Link C). | `RK3588_AGENT_KICKOFF.md:86`, `:135`; `rk/config/rk.toml:152` |
| Fragment | 16-byte fragment header + chunk. One fragment = one UDP datagram. `offset` = byte offset of the chunk in (header + payload). | `docs/RK_AGX_INTERFACE.md` 3.6; `rk/docs/BRINGUP_REPORT.md:783` |
| Chunk | 8896 B at MTU 9000. 1456 B at MTU 1500. Set DF (no IP fragmentation). | `common/framelink.py` `FRAG_PAYLOAD_JUMBO`, `FRAG_PAYLOAD_1500` |
| Send buffer | `SO_SNDBUF` 4 MiB (RK `wmem_max` = 8 MiB) | `tools/rk_sim/sender.py` `FrameLinkSender.__init__()` argument `sndbuf`; `rk/ops/etc/sysctl-driveragent.conf:9` |
| Priority | Set `SO_PRIORITY` below PTP and ZMQ. `mqprio` is not possible on the RK kernel. | `rk/docs/BRINGUP_REPORT.md:1590` |

Pacing (required; the AGX socket buffer is 212992 B until O3, `docs/test_results/T3_RESULT.md:165`):

| Rule | Value | Source |
|---|---|---|
| Spread | Send the datagrams of one frame over at most 60 % of the frame interval (cam0 at 30 fps: 20 ms). | `tools/rk_sim/sender.py` `FrameLinkSender.__init__()` (`pace_fraction` 0.6) |
| Gap | gap = span / n. span = min(0.6 x interval, n x 150 us). | `tools/rk_sim/sender.py` `FrameLinkSender.__init__()` argument `gap_s`, `FrameLinkSender.send()` |
| No catch-up burst | Each datagram is due one gap after the previous one. When the thread is late, send at most 4 datagrams back-to-back. Then apply the gap again. | `tools/rk_sim/sender.py` `FrameLinkSender` docstring, `FrameLinkSender.send()` |
| Batching | `sendmmsg` is permitted with at most 4 datagrams per call. | AGX proposal (same limit as `max_burst`, `tools/rk_sim/sender.py` `FrameLinkSender.__init__()` argument `max_burst`) |
| Reason | A late Python sender sent up to 156 x 8912 B = 1.39 MB at once. The AGX lost 1-10 % of cam0 frames. With this rule the loss went to 0.11 % or less. | `docs/test_results/T3_RESULT.md:6`, `:146` |

Sender threads and buffers (AGX proposal; the RK agent selects the details):

| Rule | Reason |
|---|---|
| Use one send thread per camera. Do not send in the capture thread. | rk-camd rule: "Capture never waits for a consumer" (`rk/camd/src/protocol.h:23-24`). M1 RGA path p99 <= 4 ms (`RK3588_AGENT_KICKOFF.md:90`). |
| Copy the NV12 bytes out of the SCALED buffer, or hold the buffer until the last datagram is sent. Do not let RGA rewrite a buffer that you send. | Ownership rule (`rk/camd/src/protocol.h:20-24`). |
| The SCALED heap is cached (`/dev/dma_heap/system`). Call `DMA_BUF_IOCTL_SYNC` (start, read) before the CPU reads the buffer and (end) after. | `rk/config/rk.toml:15` |
| When a new frame arrives while the previous frame is still sending: finish the previous frame. Then send only the newest waiting frame. Count each frame that you do not send (`skipped`). | The AGX keeps the newest frame (`common/framelink.py` `Reassembler.push()`). The AGX counts a seq gap as lost frames (`infer/ingest/framelink_rx.py` `FrameLinkReceiver._on_complete()`). |
| A seq that goes back, or jumps forward by more than 100000, starts a new stream on the AGX. Restart seq only when rk-camd restarts. | `infer/ingest/framelink_rx.py` `FrameLinkReceiver._on_complete()` |

Demand-driven cameras: cam0 always sends. cam1-5 send only when they have a SCALED stream (`scaled = true`, `rk/config/rk.toml:59-61`). Today the switch is static. The runtime switch (HmiRequest `selectModel`, `rk/proto/schema/message.capnp:79-92`) is not implemented. rk-camd uses a camera only when its role and link are CONFIRMED (`rk/docs/STATUS.md:100-102`). Today cam1-5 are UNCONFIRMED (O6). Thus:

| Phase | cam1-5 frames |
|---|---|
| Before O6 | The sender makes synthetic 704 x 396 NV12 frames with `source = 3` (TEST_PATTERN) and sends them to ports 6001-6005. Do not send the unlabelled `--bench` streams (cam_id 255). |
| After O6 | Set `scaled = true` for cam1-5 in the board override. Send the SCALED frames with `source = 1` (LIVE). |

New config table (AGX proposal):

```toml
[camd.framelink]
enable = true
host = "10.42.0.1"        # AGX Link C address (same value as [hmi.bus] agx_host)
base_port = 6000          # camN -> base_port + N
chunk = 8896              # 8896 at MTU 9000, 1456 at MTU 1500
pace_fraction = 0.6
gap_us = 150
max_burst = 4
sndbuf = 4194304
```

Sender counters (per camera; log one line every 5 s, for example `framelink_tx cam=0 frames=... datagrams=... bytes=... errors=... skipped=... max_burst=... spread_p99_ms=...`):

| Counter | Meaning |
|---|---|
| `frames` | Frames sent |
| `datagrams`, `bytes` | Datagrams and bytes sent without error |
| `errors` | Failed `sendto`/`sendmmsg` calls |
| `skipped` | SCALED frames not sent (sender busy) |
| `max_burst` | Longest run of datagrams sent less than gap/4 apart (as `max_burst_seen`, `tools/rk_sim/sender.py` `FrameLinkSender.send()`, `Stats.max_burst_seen`) |
| `spread_p99_ms` | p99 of the time from the first to the last datagram of a frame |

### Test

Test 1, golden vectors (on the RK):

```
cd <copy of /home/tonyho/driveragent-agx/tools/framelink_ref>
g++ -std=c++17 -Wall -Wextra -Werror -O2 -o /tmp/test_framelink test_framelink.cpp
/tmp/test_framelink golden_vectors.txt
```

Pass: the last line is `3 vectors, 0 failed`, exit code 0. The new `camd-tests` case (rk-camd packer against the same file) also passes: `ctest` or `build/camd-tests rk/camd/tests` exit code 0.

Test 2a, loopback on the RK (before Link C):

1. Set `[camd.framelink] host = "127.0.0.1"`.
2. Copy `common/__init__.py`, `common/framelink.py`, `common/envelope.py` and `common/dabus_envelope.py` from the AGX into a folder `common/` on the RK.
3. Install the Python package `crc32c` (the AGX uses version 2.9). Without it the CRC is about 1000 times slower (`common/envelope.py` `crc32c()`, `CRC_IMPL`).
4. Run one receiver per camera for 60 s, in the folder that contains `common/` (example for cam0: `python3 fl_rx.py 0 60`):

```python
# fl_rx.py <cam> <seconds>: loopback receiver for the K1 test (uses the AGX receiver code).
import socket, sys, time
from common import framelink as fl
cam, secs = int(sys.argv[1]), float(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
s.bind(("127.0.0.1", 6000 + cam)); s.settimeout(0.5)
r, frames, bad, lost, last, h = fl.Reassembler(cam), 0, 0, 0, None, None
t_end = time.monotonic() + secs
while time.monotonic() < t_end:
    try:
        f = r.push(s.recv(65536))
    except socket.timeout:
        continue
    if f is None:
        continue
    try:
        h, _ = fl.unpack_frame(f)
    except fl.FrameError:
        bad += 1
        continue
    if last is not None:
        lost += (h.seq - last - 1) & 0xFFFFFFFF
    last, frames = h.seq, frames + 1
size, src = (f"{h.width}x{h.height}", h.source) if h else ("-", "-")
print(f"cam{cam} frames {frames} fps {frames / secs:.2f} bad {bad} lost {lost} "
      f"frag_bad {r.bad} abandoned {r.abandoned} size {size} source {src}")
```

Pass (each camera): fps >= 29.5, bad 0, frag_bad 0, lost <= 0.1 % of frames, size 1280x720 (cam0) or 704x396 (cam1-5). Source: cam0 1. cam1-5: 3 before O6, 1 after O6.

Test 2b, AGX ingest over Link C (after K3; on the AGX):

```
cd /home/tonyho/driveragent-agx
tools/svc.sh stop infer          # the probe binds UDP 6000-6005 itself
AGX_INGEST_MODE=rk PYTHONPATH=. .venv/bin/python -m infer.ingest.probe --config config/sources.yaml \
    --seconds 60 --json tests/out/k1_rk_nv12_60s.json
PYTHONPATH=. .venv/bin/python - <<'EOF'
import json
d = json.load(open("tests/out/k1_rk_nv12_60s.json"))
TP = {1, 2, 3, 4, 5}   # cameras sent as TEST_PATTERN (before O6). After O6: TP = set()
for c in d["cameras"]:
    n = c["frames"] + c["lost_frames"]
    tp = c["cam"] in TP
    label_ok = ((c["state_end"] == "SIMULATED" and c["simulated"] and c["source"] == "test-pattern")
                if tp else (c["state_end"] == "OK" and "SIMULATED" not in c["states_seen_s"]
                            and not c["simulated"] and c["source"] == "live"))
    ok = (label_ok and c["fmt"] == "nv12" and c["fps"]["avg"] >= 29.5
          and c["bad"] == 0 and c["lost_frames"] <= 0.001 * n)
    print(c["cam"], "PASS" if ok else "FAIL", c["state_end"], c["source"], c["fps"]["avg"],
          c["bad"], c["lost_frames"], n)
EOF
```

Pass (each of the six cameras): fmt `nv12`, fps avg >= 29.5, bad 0, lost frames <= 0.1 %. Label: a LIVE camera has state OK (never SIMULATED), `simulated` false, source `live`. A TEST_PATTERN camera (cam1-5 before O6) has state SIMULATED, `simulated` true, source `test-pattern` (`infer/ingest/frame_store.py` `FrameStore.state()`; `common/framelink.py` `SOURCE_NAMES`). The probe prints `ingest mode rk bind 0.0.0.0` on its first line (`infer/ingest/probe.py` `main()`). Note: T3 measured up to 0.11 % NV12 loss with rmem_max 212992 B. Do K3 (8 MiB) before this test.

Test 3, sender counters (on the RK, same 60 s):

```
journalctl -u rk-camd --since "-70 s" | grep framelink_tx
```

Pass (each camera): `errors` 0. `skipped` <= 0.1 % of frames. `max_burst` <= 5 (4 catch-up datagrams + the due datagram; the AGX test measured "max back-to-back after the stall 4, max_burst_seen 5", `docs/test_results/T3_RESULT.md:137`). `spread_p99_ms` <= 25 (cam0) and <= 12 (cam1-5). The nominal span is 20 ms (cam0) and 7.2 ms (cam1-5). The AGX Python sender measured 24.2 ms and 7.3-10.2 ms (`docs/test_results/T3_RESULT.md:102`). The spread must stay below the frame interval (33.3 ms). RK `frames` minus AGX stored frames <= 0.1 %.

### Depends on

| Item | Why |
|---|---|
| K8 / O5 | The bytes on the wire |
| K3 / O2, O3, O7 | Test 2b and test 3 need Link C. Test 1 and test 2a do not. |
| O6 | cam1-5 need a CONFIRMED camN (`rk/docs/STATUS.md:100-102`). Until then, test cam1-5 with `source = 3` (TEST_PATTERN) frames from the same sender. The AGX labels them SIMULATED. |

---

## K2. (Optional, O8) H.265 payload, fmt 2

### Goal

Six cameras fit easily in 1 GbE. Each camera sends one H.265 access unit per FrameLink frame (about 4-5 Mb/s per camera instead of 100-335 Mb/s).

### Where in the RK repo

| Path | Use |
|---|---|
| `rk/recorder/src/encoder.cpp:55-79` | MPP H.265 encoder setup to copy: VBR, `rc:gop`, `MPP_ENC_HEADER_MODE_EACH_IDR` (VPS/SPS/PPS in every key frame, `:78`). |
| `rk/config/rk.toml:108-109` | Recorder: `bitrate_kbps = 4000`, `gop = 30` (1080p, 1 key frame per second) |
| `rk/camd/src/framelink_tx.cpp` (K1) | Same packer and sender, `fmt = 2` |

The recorder encodes only while it records (start and stop from HmiRequest, `RK3588_AGENT_KICKOFF.md:96`). Thus FrameLink fmt 2 needs its own encoder instance per camera.

### Exact spec

| Item | Value | Source |
|---|---|---|
| Payload | One H.265 access unit per FrameLink frame, Annex-B byte stream (start codes `00 00 01` / `00 00 00 01`) | AGX proposal (`common/framelink.py` `FMT_H265`; `docs/RK_AGX_INTERFACE.md:153`) |
| Parameter sets | VPS, SPS and PPS before each IDR (same AU) | `infer/ingest/framelink_rx.py` class `IdrGate` |
| Random access | An IDR or CRA at least every 1 s (30 frames). The AGX recordings use IDR every 256 frames and CRA every 30 frames. The recorder setting `gop = 30` meets the rule. | `infer/ingest/framelink_rx.py` class `IdrGate`; `docs/test_results/T3_RESULT.md:44`; `rk/config/rk.toml:109` |
| B-frames | None | Night-task Section 6 default (`docs/RK_AGX_INTERFACE.md:155`) |
| Header `fmt` | 2 | AGX proposal |
| Header `w`, `h` | The encoded picture size | RK repo field |
| Header `stride` | 0 | AGX proposal |
| `seq`, `t_capture_ptp_ns`, `source`, `health` | As K1. One seq per encoded frame, no gaps. | K1 |
| Max AU | 2097152 B | `config/sources.yaml` key `max_frame_bytes` |
| Pacing | As K1. A small AU goes out in 1-2 datagrams. | `tools/rk_sim/sender.py` `FrameLinkSender.send()` |

Picture size options:

| Option | Encoder input | `frameWidth` x `frameHeight` in results | K5 scale |
|---|---|---|---|
| (a) Recommended | SCALED NV12 (cam0 1280x720, cam1-5 704x396), MPP input `MPP_FMT_YUV420SP` | Same as K1 | As K5 |
| (b) | RAW UYVY 1920x1080, as rk-recorder (`rk/recorder/src/encoder.cpp:57`), about 4 Mb/s | 1920 x 1080 | 1.0 |

The AGX accepts any size from the header and from the decoded picture (`infer/ingest/framelink_rx.py` `FrameLinkReceiver._nv12()`, `FrameLinkReceiver._on_decoded()`). Option (b) changes `frameWidth` and `frameHeight` of every result to 1920 x 1080. The AGX has measured decode time only for 1280x720 (p50 8-20 ms with six streams, `docs/test_results/T3_RESULT.md:164`). 1080p decode is not measured. The RK VPU load for six extra encoders is not measured.

### Test

On the AGX (after K3), with `--json tests/out/k2_rk_h265_60s.json` and the same probe command as K1 test 2b:

| Check (per camera, probe JSON) | Pass |
|---|---|
| `fmt` | `h265` |
| `decode_ms_last300.p50` | < 25 ms |
| `waiting_idr` | <= 30 (one key-frame interval) at start; +30 at most per loss |
| `fps.avg` | >= 29.5 |
| `lost_frames` | <= 0.1 % |
| `bitrate_kbps.avg` | Between `rc:bps_min` and `rc:bps_max` of the encoder (target / 2 to target x 1.5; recorder target 4000 kbit/s gives 2000-6000, `rk/recorder/src/encoder.cpp:65-67`, `rk/config/rk.toml:108`) |
| `state_end`, `source` | `OK`, `live` |

On the RK: K1 test 3 counters, `errors` 0.

### Depends on

O8, K1, K3.

---

## K3. Link C (owner decision O2)

### Goal

A direct 1 GbE link between the boards with MTU 9000, and receive buffers large enough for NV12 bursts.

### Where

| Side | Path | Change |
|---|---|---|
| RK | systemd-networkd config for `eth0` (owner script, sudo) | 10.42.0.2/30, MTU 9000. `eth0` = GMAC0, the only PHC `/dev/ptp0`. MTU range 46-9000, now 1500. Jumbo frames unverified. (`rk/docs/BRINGUP_REPORT.md:592-595`, `:1627`) |
| RK | `rk/docs/RECOVERY.md:28` | Update: "A fixed 10.42.0.2/30 on the board" is then made. |
| RK | `rk/ops/etc/sysctl-driveragent.conf:7-9` | Already `net.core.rmem_max = wmem_max = 8388608`. No change. |
| AGX (owner, sudo) | Link C NIC (O7) | 10.42.0.1/30, MTU 9000 |
| AGX (owner, sudo) | `/etc/sysctl.d/` | `net.core.rmem_max = 8388608` (O3) |
| AGX (AGX agent) | `config/sources.yaml` key `rcvbuf_bytes` | `rcvbuf_bytes: 8388608` (0 already means "the maximum"; the explicit value documents it) |

### Exact spec

| Item | Value | Source |
|---|---|---|
| AGX address | 10.42.0.1/30 on the Link C NIC (kick-off: `eno1`, see O7) | `RK3588_AGENT_KICKOFF.md:100`, `:139` |
| RK address | 10.42.0.2/30 on `eth0` | Same |
| MTU | 9000 target. 1500 fallback (then chunk 1456 B, K1). | `RK3588_AGENT_KICKOFF.md:139` |
| WAN | Never on Link C | `RK3588_AGENT_KICKOFF.md:117` |
| AGX ports open to 10.42.0.2 | UDP 6000-6005, TCP 5560, 5561, 8700 | `docs/RK_AGX_INTERFACE.md` 2.4 |
| AGX `rmem_max` | 8388608 B. The kernel doubles a request, so `SO_RCVBUF` reads back 16777216. | AGX proposal (O3) |

### Test

| # | Where | Command | Pass |
|---|---|---|---|
| 1 | RK | `ping -M do -s 8972 -c 100 10.42.0.1` | 100 received, 0 % loss (8972 + 28 = 9000 B, no fragmentation) |
| 2 | RK | `ping -M do -s 1472 -c 100 10.42.0.1` (MTU 1500 fallback only) | 0 % loss |
| 3 | AGX | `cat /proc/sys/net/core/rmem_max` | `8388608` |
| 4 | AGX | Start `agx-infer` in rk mode, then `ss -ulpn | grep -E ':600[0-5]'` | Six sockets on `0.0.0.0:6000-6005` |
| 5 | AGX | K1 test 2b JSON, field `rcvbuf` | 16777216 for each camera |

iperf3 is not required.

### Depends on

O2, O3, O7. The physical cable. sudo on both boards (owner).

---

## K4. Result and status subscriber on the RK

### Goal

The RK HMI receives `AgxPerceptionResult` (5560) and `AgxInferStatus` (5561), checks them like every other channel, and rejects nothing.

### Where in the RK repo

| Path | Change |
|---|---|
| `rk/proto/schema/message.capnp` | Add `struct AgxPerceptionResult` and `struct AgxInferStatus`. Copy the text from `/home/tonyho/driveragent-agx/proto/agx_infer.capnp` (`docs/RK_AGX_INTERFACE.md` 4.3). Do not copy the file id `@0xd30f559909e364de`. Do not copy `const schemaVersion` (or rename it, for example `agxInferSchemaVersion`). Both are outside the structs: they do not change the hashes. |
| `rk/proto/bus_registry.yaml:32-49` | Add two AGX -> RK channels (below). Bump `version: 1` to `version: 2` (`:11`). |
| `rk/proto/CHANGELOG.md` | Add an entry. |
| `rk/proto/generated/` | Run `python3 codegen/generate.py`. Commit `generated/` (`rk/proto/README.md:28`). |
| `rk` (submodule pointer) | Bump the `rk/proto` submodule in the RK repo (`rk/proto/README.md:23-24`). |
| `rk/config/rk.toml` (after `:200`) | Add `[hmi.channels.agx_perception]` and `[hmi.channels.agx_infer_status]` (below). |
| `rk/hmi/driveragent_hmi/bus.py:107-112`, `:134-144` | See "bus.py change" below. |
| `rk/hmi/driveragent_hmi/views.py:151` | `perception` = fresh `agx_perception` (also). |

Registry entries:

```yaml
  - {name: agx_perception, type_id: 5560, struct: AgxPerceptionResult, from: agx, to: rk,
     publisher: agx inference node, rate: per (model, camera, frame), max_age_ms: 300, status: proposed}
  - {name: agx_infer_status, type_id: 5561, struct: AgxInferStatus, from: agx, to: rk,
     publisher: agx inference node, rate: 1 Hz, max_age_ms: 3000, status: proposed}
```

The nested structs (`Detection`, `Trajectory`, `Trajectory.Point`, `Mask`, `Timing`, `Camera`, `Model`, `Temp`) are not top-level. `generate.py` does not require them in `nested:` (`rk/proto/codegen/generate.py:32-40`, `:64-67`). You can list them for clarity with the parent name, as `RecorderStatus.StreamStat` (`rk/proto/bus_registry.yaml:52`), for example `AgxPerceptionResult.Detection`.

rk.toml entries:

```toml
[hmi.channels.agx_perception]
port = 5560
struct = "AgxPerceptionResult"
max_age_ms = 300

[hmi.channels.agx_infer_status]
port = 5561
struct = "AgxInferStatus"
max_age_ms = 3000
```

### Exact spec

| Item | Value | Source |
|---|---|---|
| Socket | ZMQ SUB, `connect` to `tcp://<agx_host>:5560` and `:5561`, `SUBSCRIBE ""`. The AGX binds. | `rk/hmi/driveragent_hmi/bus.py:107-112`; `rk/proto/bus_registry.yaml:3` |
| ZMQ frame | One frame = 32-byte dabus envelope + unpacked single-segment Cap'n Proto message. No topic frame. | `rk/proto/envelope/SPEC.md:3-5` |
| Envelope checks | magic `0xDA5E`, ver 1, len, CRC-32C; `src_board` = 1 (AGX); `type_id` = 5560 / 5561; `schema_hash` = `0xafcaff02` / `0x9086fa18` | `rk/hmi/driveragent_hmi/bus.py:146-170`; `docs/RK_AGX_INTERFACE.md` 4.2, 5.1 |
| Envelope flags | bit0 `source_is_replay` = simulated input. bit1 `time_uncertain` = always set. bit2 `degraded` = node DEGRADED. | `infer/publish/results.py` `ResultPublisher._build()` |
| Result rate | Up to about 190 messages/s: yolopx on 6 cameras at max 30 fps, dtcp on cam0 at max 10 fps | `config/models.yaml` models `driverguard_yolopx` and `driverguard_dtcp`, keys `cameras`, `max_fps_per_camera` |
| Status rate | 1 Hz | `config/infer.yaml` key `status_period_s` |

bus.py change (required for 5560):

| Today | Problem for 5560 | Change |
|---|---|---|
| `poll()` keeps only the newest valid message of a channel (`bus.py:134-144`, `:168-170`). | Results of different (model, camId) arrive on one channel. The newest one hides the others. | For `agx_perception`, keep the newest result per (model, camId). Give each decoded message to the overlay store (K5). |
| `RCVHWM 16` (`bus.py:109`); `poll()` reads at most 32 messages per channel per frame (`:134`). | At 190 messages/s, 16 messages are about 84 ms. A slow HMI frame drops results. | For `agx_perception`: `RCVHWM` 256 and read up to 256 messages per frame. |

Schema hash rule. The envelope `schema_hash` is FNV-1a 32 of the canonical struct text (`rk/proto/envelope/SPEC.md:24-27`; `rk/proto/envelope/dabus_envelope.py:69-97`):

1. Take the text from `struct <Name> {` to its matching `}` (nested structs included).
2. Remove `#` comments. Strip each line. Drop empty lines. Join with `\n`.
3. Hash = FNV-1a 32 of that text.

Consequences:

| Change when you copy | Hash |
|---|---|
| Comments, indentation, empty lines, other structs in the file, file id, `const` lines | Same |
| The text `struct AgxPerceptionResult` (or `struct AgxInferStatus`) in a comment above the struct | Different. The search finds the first match in the raw text, comments included (`rk/proto/envelope/dabus_envelope.py:72`). Check: such a comment gives `0x396bd5b0`. |
| Any other character inside the struct (a field, an ordinal, a type, a name, one extra space between tokens) | Different. Check: one extra space after `x1` in `x1 @3 :Float32;` gives `0xe21f0e26` instead of `0xafcaff02`. |

The AGX computes the hash at runtime from its file `proto/agx_infer.capnp` (`config/infer.yaml` key `proto`; `infer/publish/schema.py` `Schema.__init__()`). Thus the copy in `message.capnp` must keep the struct text exactly. After a later change on the AGX (additive only, `proto/agx_infer.capnp` header comment "Rules"), both files change together.

Hash check on the RK:

```
python3 rk/proto/envelope/dabus_envelope.py --schema-hash rk/proto/schema/message.capnp AgxPerceptionResult   # afcaff02
python3 rk/proto/envelope/dabus_envelope.py --schema-hash rk/proto/schema/message.capnp AgxInferStatus        # 9086fa18
python3 rk/proto/codegen/generate.py --check                                                                  # generated/ up to date
```

### Test

| # | Where | Command | Pass |
|---|---|---|---|
| 1 | RK | The three hash commands above | `afcaff02`, `9086fa18`, `generated/ up to date` (exit code 0, `rk/proto/codegen/generate.py:104-109`) |
| 2 | RK (tailscale before K3, Link C after) | `python -m tools.rk_result_client --host <agx> --seconds 60` (`<agx>` = `100.64.0.20` over tailscale, `10.42.0.1` over Link C). On the RK, run a copy: `tools/rk_result_client/__main__.py` with `--schema` (the schema file) and `--envelope-dir` (folder with `dabus_envelope.py`) (`tools/rk_result_client/__main__.py` module docstring). Add `--expect-cams 0,1,2,3,4,5 --json k4.json`. | Exit code 0. `rejects_total` 0. `duplicates` 0. `out_of_order` 0. `cams_seen` = 0..5. `status.count` >= 55 (1 Hz for 60 s). |
| 3 | RK | Run rk-hmi for 60 s against the running AGX. Log `received` and `rejected` of `agx_perception` and `agx_infer_status` every 10 s (new log line, K4). | `rejected` = 0 for both channels (`rk/hmi/driveragent_hmi/bus.py:56`). No `bus_reject` log line for them. `received` > 0. |

AGX side for the test: `tools/svc.sh start infer` (sim mode is sufficient).

### Depends on

O1. The AGX node running. For the tailscale test: owner OK for the temporary `agx_host` change (Section 2.2).

---

## K5. Overlay on the camera tiles

### Goal

The HMI draws the AGX results on the camera tiles: boxes, labels, cam0 masks, and the trajectory as "display only". The HMI never shows an old result.

### Where in the RK repo

| Path | Change |
|---|---|
| `rk/hmi/driveragent_hmi/screens/cameras.py:67-74`, `:238-245`, `:280-292` | Pass an `overlay` callback to `W.tile()`. Replace the chip "NO PERCEPTION · overlay needs the AGX" when results are fresh. |
| `rk/hmi/driveragent_hmi/widgets.py:173-208` | `tile_video()` computes the video rectangle (`dst`, crop `sx, sy, sw, sh`). Give these values to the overlay callback. |
| `rk/hmi-video/hmi_video.h:28-42`, `rk/hmi-video/hmi_video.cpp:59`, `:444`, `:484-505`, `rk/hmi/driveragent_hmi/hmi_video.py:10-26`, `:30-44`, `:89` | Add `shown_capture_ns` (CLOCK_MONOTONIC capture time of the displayed RAW frame; it exists as `s.shown_capture_ns`) to `hv_cam_info`, to the ctypes `_CamInfo` and to `CamInfo`. Add it as the last field in both structs: the ctypes field order must match the C struct. |
| `rk/hmi/driveragent_hmi/screens/world.py:59` | Optional: trajectory on the World screen |
| New module, for example `rk/hmi/driveragent_hmi/overlay.py` | Result store per (model, camId), RLE decode, scale, freshness |

### Exact spec

Pixel space of a result: `frameWidth` x `frameHeight` (the FrameLink frame), x right, y down, origin at the top-left corner (`proto/agx_infer.capnp` `AgxPerceptionResult.frameWidth`, `frameHeight`, `Detection.x1`). The RK resizes the full frame with no crop (`rk/camd/src/rga_scaler.cpp:89-90`). The HMI shows the full RAW frame (1920 x 1080) in a 1280 x 720 texture (`rk/hmi/driveragent_hmi/app.py:175`).

Scale (use the capture size from `cameras.toml` `image_width`, `image_height`, as `rk/hmi/driveragent_hmi/screens/maintenance.py:396`, `:460-473`):

| Step | Formula | cam0 (1280x720) | cam1-5 (704x396) |
|---|---|---|---|
| 1. To capture pixels | `X = x * 1920 / frameWidth`, `Y = y * 1080 / frameHeight` | x 1.5 | x 1920/704 = x 1080/396 = x 2.7273 |
| 2. To texture pixels | `Xt = X * tex_w / 1920`, `Yt = Y * tex_h / 1080` (tex 1280 x 720) | - | - |
| 3a. Tile, `fit` (default, `rk/config/hmi.toml:14`) | `Xs = dst.x + Xt * dst.w / tex_w`, `Ys = dst.y + Yt * dst.h / tex_h` | - | - |
| 3b. Tile, `fill` | `Xs = dst.x + (Xt - sx) * dst.w / sw`, `Ys = dst.y + (Yt - sy) * dst.h / sh`. Clip to the tile. | - | - |
| 3c. `mirrored` | `Xs = dst.x + dst.w - (Xs - dst.x)` | - | - |

Steps 1 and 2 together: `Xt = x * tex_w / frameWidth`, `Yt = y * tex_h / frameHeight`. The capture size cancels, because RGA and the HMI both use the full frame with no crop.

Always use `frameWidth` and `frameHeight` of each result. Do not hard-code 1280 or 704 (K2 option (b) sends 1920 x 1080).

Draw:

| Output | Rule | Source |
|---|---|---|
| Boxes | `x1, y1` top-left, `x2, y2` bottom-right, Float32 pixels | `proto/agx_infer.capnp` `AgxPerceptionResult.Detection` (`x1`, `y1`, `x2`, `y2`) |
| Label | `className` + `score` (2 decimals), for example `car 0.87` | `proto/agx_infer.capnp` `AgxPerceptionResult.Detection` (`className`, `score`) |
| Masks | Only `drivable_area` and `lane_line`. Only cam0 has masks (`masks_cameras: [0]`). | `config/models.yaml` key `masks_cameras` |
| Mask format | `encoding` = `rle-u16le-count-u8-value-rowmajor`: records of 3 bytes = run length (u16 little-endian) + value (u8, 0 or 1). Row-major over `width` x `height`. A run longer than 65535 is split. Use the mask fields `width` x `height`. For DriverGuard they are `frameWidth` x `frameHeight`. Scale the mask like the boxes. | `infer/models/legacy/driverguard/mask_codec.py` `_MAX_RUN`, `encode_rle()`, `decode_rle()`; `proto/agx_infer.capnp` struct `AgxPerceptionResult.Mask`; `infer/models/adapters/yolopx_v2.py` `YolopxV2Adapter.postprocess()` |
| Trajectory | Draw only with the text "DISPLAY ONLY". When `inputsValid` = false, show "inputs not valid" and the `note` text. The AGX always sends false: the command and the target are assumed values, and the AGX has no ego speed. | `proto/agx_infer.capnp` struct `AgxPerceptionResult.Trajectory`; `config/models.yaml` model `driverguard_dtcp` keys `command`, `target`, `ego_speed_mps`; `infer/models/adapters/dtcp_v1.py` `DtcpV1Adapter.__init__()` (`inputs_valid`) |
| Trajectory frame | Metres in the DTCP ego frame: "x = lateral, right positive (m); y = forward (m); origin = ego at frame time". This is not the RK vehicle frame (x forward, y left, origin rear axle). Do not draw it on a camera tile without a camera projection. Prefer the World screen. | `infer/models/adapters/dtcp_v1.py` `TRAJ_FRAME`; `rk/hmi/driveragent_hmi/screens/world.py:6-7` |
| SIMULATED | When `simulated` = true (or envelope flag bit0): show "SIMULATED" in a warning colour on the tile. | `proto/agx_infer.capnp` `AgxPerceptionResult.simulated`, `AgxPerceptionResult.source`; R13 |

Freshness (per (model, camId)):

| # | Rule |
|---|---|
| 1 | Age = RK monotonic now - RK receive time (`t_rx`, `bus.py:169`). Do not use `tCaptureNs` or AGX times for age (no common clock, K7). |
| 2 | Draw a result only when its age <= 300 ms (`max_age_ms` of `agx_perception`). |
| 3 | Live (`simulated` = false): draw a result only in one of two cases. (a) It matches the shown frame ("Frame match" below). (b) Its `frameSeq` is newer (mod 2^32) than the last drawn result of that (model, camId). |
| 4 | Never draw a result that is older than the last drawn result. Never hold a result after 300 ms. Remove it. |
| 5 | Simulated (`simulated` = true): the frame is not an RK frame. Use rules 1, 2 and 4 only. Show SIMULATED. |
| 6 | The AGX publishes nothing for a camera without frames for 500 ms (`config/sources.yaml` key `stale_s`). Thus the overlay of that camera goes away by rule 2. |

Frame match ("belongs to the shown frame"). The SCALED frame and the RAW frame of one capture have the same `t_capture_ns` and `v4l2_sequence` (`rk/camd/src/camera.cpp:185-188`, `:207`). Their `frame_no` counters are different (`:211`, `:230`). Rule (AGX proposal): convert `tCaptureNs` (RK CLOCK_REALTIME, K1) to CLOCK_MONOTONIC with the RK offset (CLOCK_REALTIME - CLOCK_MONOTONIC, sampled now). The result belongs to the shown frame when the difference to `shown_capture_ns` is <= 10 ms (less than half of the 33.3 ms frame interval). Exact alternative: rk-camd adds the SCALED `frame_no` to the RAW FRAME message (local protocol change, `rk/camd/src/protocol.h:99-110`).

Performance: the HMI exit criterion is >= 60 FPS p99 (`RK3588_AGENT_KICKOFF.md:110`). Decode a mask once per new result. Do not decode in the render loop for each frame.

Latency display (optional): RK now (CLOCK_REALTIME) - `tCaptureNs` is valid on the RK in live mode: both values come from the RK clock.

### Test

| # | Setup | Action | Pass |
|---|---|---|---|
| 1 | AGX: `tools/svc.sh start infer` (sim mode). RK: K4 done. | Look at each camera tile for 60 s. | Boxes show on 6 of 6 tiles (yolopx runs on cam0-5, `config/models.yaml` model `driverguard_yolopx` key `cameras`). "SIMULATED" shows on 6 of 6 tiles. |
| 2 | Same | AGX: `tools/svc.sh stop infer`. RK: log the time of the last result and the time the overlay goes off (for example `overlay_off cam=0 age_ms=...`). | The overlay goes off within 300 ms after the last result (+ one render frame). No old box stays. |
| 3 | After K1 + K3, AGX in rk mode | Wave a hand in front of cam0. | Box follows the hand. No "SIMULATED" label. More than 95 % of drawn results meet frame-match rule 3 (log the count). |
| 4 | Any | HMI frame rate with 6 tiles + overlay | >= 60 FPS p99 (>= 30 accepted) |

### Depends on

K4 (O1). For test 3: K1, K3, O6.

---

## K6. AGX status on the RK dashboard

### Goal

The RK HMI shows the AGX inference node state. The chip goes stale when the AGX stops.

### Where in the RK repo

| Path | Change |
|---|---|
| `rk/hmi/driveragent_hmi/views.py:118-123`, `:144` | Add a chip from `agx_infer_status` (for example label "INFER"), or feed the "AGX" chip from it while `board_hello_agx` has no struct. |
| `rk/hmi/driveragent_hmi/screens/settings.py:50-51` | Optional: show the models, fps and temperatures of `AgxInferStatus`. |
| `/etc/driveragent/` (owner) | Only for the HTTP option: the credential file |

### Exact spec

Preferred: ZMQ 5561 (K4 channel `agx_infer_status`, same envelope rules, `max_age_ms` 3000).

Use the first row that matches (top to bottom).

| Chip value | Colour | Condition |
|---|---|---|
| "—" | grey | No `AgxInferStatus` for 3 s |
| `ERROR` | red | `nodeState` = "ERROR" |
| `SIM` | amber | `simulated` = true (`proto/agx_infer.capnp` `AgxInferStatus.simulated`). In sim and file mode it is always true (`infer/publish/status.py` `StatusPublisher._simulated()`). |
| `DEGRADED`, `STARTING` | amber | `nodeState` |
| `RUNNING` | green | `nodeState` = "RUNNING" and `simulated` = false |

Fields: `proto/agx_infer.capnp` struct `AgxInferStatus` (`nodeState`, `simulated`, `sourceMode`, `cameras[].state`, `models[].state`, `temps`, `errors`).

Optional: HTTP `GET http://<agx>:8700/api/health` (`dashboard/app.py` `create_app()` route `/api/health`).

| Item | Value | Source |
|---|---|---|
| Auth | HTTP Basic, realm `agx02-dashboard` | `dashboard/auth.py` `REALM` |
| User | `AGX_DASH_USER` (default `agx`) from the AGX `.env` | `dashboard/app.py` `create_app()` (`AGX_DASH_USER`) |
| Password | `AGX_DASH_PASSWORD` from the AGX `.env`. The owner gives it to the RK. | `dashboard/app.py` `create_app()` (`AGX_DASH_PASSWORD`) |
| Storage on the RK | `/etc/driveragent/agx-dashboard.netrc`, mode 600, owner = the HMI user. Never in git. | `RK3588_AGENT_KICKOFF.md:117` (credentials from `/etc/driveragent/` only) |
| Allowed sources | Private ranges incl. 10.0.0.0/8 and 100.64.0.0/10 | `config/dashboard.yaml` key `allow_cidrs` |
| Rate | At most 1 request per second | AGX proposal |
| Methods | GET only | `docs/RK_AGX_INTERFACE.md:457` |

The HTTP password crosses the link in plain text (`config/dashboard.yaml` comment above `tls_certfile`). Use ZMQ 5561 for the chip.

### Test

| # | Where | Command / action | Pass |
|---|---|---|---|
| 1 | AGX, then RK | AGX: `tools/svc.sh stop infer`. RK: watch the chip. | Chip goes grey "—" within 3 s (+ one render frame). |
| 2 | AGX, then RK | AGX: `tools/svc.sh start infer`. Find the log line `status PUB bound` (`tools/svc.sh logs infer`; `infer/publish/status.py` `StatusPublisher.__init__()`). | Chip shows `SIM` (sim mode) within 3 s after that log line. |
| 3 | RK | `curl -s -o /dev/null -w '%{http_code}\n' http://<agx>:8700/api/health` | `401` |
| 4 | RK | `curl -s --netrc-file /etc/driveragent/agx-dashboard.netrc -o /dev/null -w '%{http_code}\n' http://<agx>:8700/api/health` | `200` |
| 5 | RK | `stat -c '%a %U' /etc/driveragent/agx-dashboard.netrc`; `git -C <rk repo> grep -n AGX_DASH` | `600 <hmi user>`; no password in git |

### Depends on

K4 (O1). HTTP option: credentials from the owner.

---

## K7. Time (owner decision O4)

### Goal

Both boards use one time base. Until then, no side compares AGX times with RK times.

### Where

| Side | Path / tool | Note |
|---|---|---|
| RK | `ptp4l` on `eth0` (HW timestamps), `phc2sys` to CLOCK_REALTIME, `ptp-check` tool (M3) | `RK3588_AGENT_KICKOFF.md:99-102` |
| RK | `systemd-timesyncd` (now synchronised to ntp.ubuntu.com). It fights `phc2sys`: disable it with PTP. | `rk/docs/BRINGUP_REPORT.md:1561` |
| AGX (owner) | PTP grandmaster on the Link C NIC. The AGX has `/dev/ptp0`. `ptp4l` and `chronyc` are not installed (Check). Today: `systemd-timesyncd`, about 31-41 ms ahead of public NTP. | `docs/research/T1_rk-probe.md:73-88` |

### Exact spec

| Item | Rule | Source |
|---|---|---|
| Until PTP or chrony | Both sides set envelope flag bit1 `time_uncertain` on every message | `rk/proto/envelope/SPEC.md:16`; `RK3588_AGENT_KICKOFF.md:101`; `infer/publish/results.py` `ResultPublisher._build()` |
| Until PTP or chrony | The RK must not subtract AGX times (`tAgxRecvNs`, `tAgxReadyNs`, `tAgxResultNs`, envelope `t_ptp_ns`) from RK times. | `docs/RK_AGX_INTERFACE.md:469-470` |
| Valid without sync | AGX-internal latency: `timing.*` and `tAgxResultNs - tAgxRecvNs`. RK-internal: RK now - `tCaptureNs` (both RK clock). | `proto/agx_infer.capnp` struct `AgxPerceptionResult.Timing` |
| PTP target | Offset <= 10 us p99 over 24 h | `RK3588_AGENT_KICKOFF.md:102` |
| chrony target | Both boards synchronised, offset <= 1 ms each | AGX proposal |
| After sync | Holdover > 60 s: set `time_uncertain` again | `RK3588_AGENT_KICKOFF.md:101` |

### Test

| Case | Where | Command | Pass |
|---|---|---|---|
| PTP | RK | `ptp-check` (M3 tool) over 24 h | offset p99 <= 10 us |
| chrony | RK and AGX | `chronyc tracking` | `Leap status : Normal`, `System time` offset <= 1 ms on both |
| Flag | RK | `python -m tools.rk_result_client --host <agx> --seconds 60 --json k7.json` | Before sync: `envelope_flags.result_bit1_time_uncertain` = `messages.result_ok` (`tools/rk_result_client/__main__.py` `Client.handle_result()`). The RK HMI shows no cross-board latency. |

### Depends on

O4. PTP needs K3.

---

## K8. Confirm or change the FrameLink proposals (O5)

### Goal

Both sides use the same bytes. The RK repository defines these items nowhere (`docs/research/T1_rk-repo.md` section 3).

### Where

`docs/RK_AGX_INTERFACE.md` section 3. AGX code: `common/framelink.py`. Reference: `tools/framelink_ref/framelink.h`, `tools/framelink_ref/golden_vectors.txt`. AGX check: `tests/test_framelink_golden.py`.

### Exact spec (items to confirm)

| # | Item | AGX proposal | AGX file |
|---|---|---|---|
| 1 | Frame magic | `0x4B4E4C46` ("FLNK") | `common/framelink.py` `MAGIC`; `framelink.h` `kMagic` |
| 2 | Frame version | 1 | `common/framelink.py` `VERSION`; `framelink.h` `kVersion` |
| 3 | `fmt` codes | 1 = NV12, 2 = H.265 (Annex-B AU) | `common/framelink.py` `FMT_NV12`, `FMT_H265`; `framelink.h` `enum Fmt` |
| 4 | `source` codes | 1 = LIVE (RK), 2 = REPLAY, 3 = TEST_PATTERN; other = simulated | `common/framelink.py` `SOURCE_LIVE`, `SOURCE_REPLAY`, `SOURCE_TEST_PATTERN`; `infer/ingest/framelink_rx.py` `source_label()` |
| 5 | `health` byte | rk-camd LinkState 0..4 | `common/framelink.py` `HEALTH_NOT_STARTED` .. `HEALTH_NO_SIGNAL`; `framelink.h` `enum Health` |
| 6 | CRC | CRC-32C. `payload_crc32c` over the payload. `header_crc32c` over bytes 0..35 (includes `payload_crc32c`). | `common/framelink.py` `pack_frame()`; `framelink.h` `pack_frame()` |
| 7 | Fragment header | 16 B: magic u16 `0x4C46` ("FL"), ver u8 1, cam u8, seq u32, idx u16, count u16, offset u32 | `common/framelink.py` `FRAG_MAGIC`, `FRAG_VERSION`, `FRAG`, `FRAG_LEN`; `framelink.h` `kFragMagic`, `kFragVersion`, `fragments()` |
| 8 | Chunk at MTU 1500 | 1456 B (open RK question 15, `rk/docs/BRINGUP_REPORT.md:1711`) | `common/framelink.py` `FRAG_PAYLOAD_1500` |
| 9 | `stride` for H.265 | 0 | `framelink.h` `Header::stride` |
| 10 | `exposure_us` | 0 = unknown | `framelink.h` `Header::exposure_us` |
| 11 | `seq` and `t_capture_ptp_ns` meaning | K1 table | `docs/RK_AGX_INTERFACE.md:220-221` |

Change rule: if the RK changes any value, both sides change together:

1. The RK agent writes the change in `rk/docs/STATUS.md` and tells the AGX side.
2. The AGX side changes `common/framelink.py` and `tools/framelink_ref/framelink.h`.
3. The AGX side writes `tools/framelink_ref/golden_vectors.txt` again (written by `common/framelink.py`, `golden_vectors.txt` header comment).
4. Both sides run their tests again.

### Test

| Where | Command | Pass |
|---|---|---|
| RK | K1 test 1 | `3 vectors, 0 failed` |
| AGX | `PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_framelink_golden.py tests/test_framelink.py` | Exit code 0, 0 failed |

### Depends on

O5. Do K8 before K1.

---

## K9. (Later) CameraHealth 5572 to the AGX

### Goal

The AGX uses rk-camd `CameraHealth` to cross-check the camera state.

### State

| Side | State | Source |
|---|---|---|
| RK | Implemented. rk-camd PUB connects to `tcp://10.42.0.1:5572`, 1 Hz per camera, `max_age_ms` 2500. | `rk/config/rk.toml:42`; `rk/proto/bus_registry.yaml:15-16`; `rk/camd/src/health_pub.cpp` |
| AGX | Does not bind SUB 5572 yet. | `docs/RK_AGX_INTERFACE.md:522-535` |

### Exact spec

No RK code change. Agree with the AGX side:

| Item | To agree |
|---|---|
| Date | When the AGX binds SUB `tcp://<Link C>:5572` (AGX proposal: after K3) |
| Use | AGX cross-check only: `linkState` vs the FrameLink `health` byte; `fps`; `seqGaps`; `drops` |
| Rule | The inference node does not apply the supervisor timeouts (`RK3588_AGENT_KICKOFF.md:141`; `docs/RK_AGX_INTERFACE.md:235`) |

### Test (later, on the AGX)

A SUB on 5572 receives 6 messages per second (one per camera), `rejected` 0, `schema_hash` `0xdea3299f` (`rk/proto/generated/python/bus_registry.py`; `docs/research/T1_rk-repo.md:286`).

### Depends on

K3 and an AGX-side task.

---

## 5. References

| File | Use |
|---|---|
| `docs/RK_AGX_INTERFACE.md` | Interface contract (sections 2-12) |
| `tools/framelink_ref/framelink.h`, `test_framelink.cpp`, `golden_vectors.txt`, `README.md` | C++ sender reference and test vectors |
| `common/framelink.py` | AGX FrameLink codec and reassembler |
| `tools/rk_sim/sender.py` | Python sender with the pacing rules |
| `infer/ingest/framelink_rx.py`, `infer/ingest/probe.py`, `config/sources.yaml` | AGX receiver, probe, source mode |
| `proto/agx_infer.capnp` | Result and status schema |
| `common/dabus_envelope.py` | dabus envelope (identical to the RK reference) |
| `tools/rk_result_client/` | Example subscriber |
| `docs/research/T1_rk-repo.md`, `docs/research/T1_rk-probe.md` | RK repository facts, probe results |
| `docs/test_results/T3_RESULT.md` | Measured AGX receive numbers |
