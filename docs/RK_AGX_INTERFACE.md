# RK3588 <-> AGX inference node: interface

| Item | Value |
|---|---|
| Document | `docs/RK_AGX_INTERFACE.md` |
| Date | 2026-10-05 (night run) |
| AGX side | agx02, this repository (`/home/tonyho/driveragent-agx`) |
| RK side | RK3588 board DA01 (`rk3588-da01`), repository `driveragent-hmi`, tag `rk-v0.4.0` (HEAD `258cf5922278e9e530d71277c2e94b7be5aaef3e`, `rk/proto` HEAD `6874e6127ba1b457f4ae110abfa4780c94cce044`) |
| RK repository copy | `/home/tonyho/driveragent-agx/ref/driveragent-hmi` (read-only). RK paths below are relative to its root. |
| Status | Proposal from the AGX side. The RK agent and the owner must confirm the items marked "AGX proposal". |

## 0. Rule and source labels

Owner rule: "If the RK3588 repository already defines a format, a port or a message, use it. Do not make a second design. Where it defines nothing, use the defaults in Section 6."

Every item in this document has one of these source labels:

| Label | Meaning |
|---|---|
| **RK repo (path:line)** | The RK repository defines the item. The AGX uses it unchanged. |
| **Night-task Section 6 default** | The RK repository defines nothing. The AGX uses the night-task default. |
| **AGX proposal (RK repo defines nothing)** | The RK repository and Section 6 define nothing. The AGX proposes a value. The RK agent must confirm it. |
| **Probe** / **Check** | A read-only measurement on 2026-10-05 (`docs/research/T1_rk-probe.md`) or a read-only check for this document. |

Directions in this document: "RK -> AGX" = the RK sends, the AGX receives. "AGX -> RK" = the AGX sends, the RK receives.

## 1. Summary

| # | Item | Decision | Source |
|---|---|---|---|
| 1 | Video transport | FrameLink over UDP. Camera N goes to UDP port 6000+N. | RK repo (`RK3588_AGENT_KICKOFF.md:86`, `:135`) |
| 2 | Video frame header | 40 bytes, little-endian, fields as the kick-off defines them | RK repo (`RK3588_AGENT_KICKOFF.md:86`) |
| 3 | FrameLink magic, version value, fmt codes, source codes 2/3, CRC coverage, fragment header layout | Values in Section 3 | AGX proposal (RK repo defines nothing; `T1_rk-repo.md` section 3) |
| 4 | FrameLink health byte | rk-camd LinkState codes | Codes: RK repo (`rk/camd/src/protocol.h:121`; `rk/proto/schema/message.capnp:34-39`). Use in the FrameLink byte: AGX proposal (the kick-off defines no codes). |
| 5 | Section 6 video (H.265 RTP/UDP 5600-5605) | NOT used. The RK repo defines the transport. | RK repo overrides Section 6 |
| 6 | Frame identity | (camId, FrameLink `seq`, `t_capture_ptp_ns`) | RK repo header fields (`RK3588_AGENT_KICKOFF.md:86`); replaces the Section 6 RTP timestamp |
| 7 | Results | ZMQ PUB, TCP 5560, dabus envelope + Cap'n Proto `AgxPerceptionResult` v1 | Port: Night-task Section 6 default. Envelope: RK repo (`rk/proto/envelope/SPEC.md`). Struct: AGX proposal. |
| 8 | Status | ZMQ PUB, TCP 5561, 1 Hz, `AgxInferStatus` v1. HTTP GET `/api/health` on port 8700. | Night-task Section 6 default |
| 9 | Socket direction | The AGX binds. The RK connects. | RK repo (`rk/proto/bus_registry.yaml:3`) |
| 10 | Stale rule | No new frame for 500 ms: no result for that camera, camera state STALE. Never re-send an old result. | Night-task Section 6 default |
| 11 | Time | No PTP. CLOCK_REALTIME from NTP on both boards. Envelope bit1 `time_uncertain` is always set. | No PTP: RK repo (`rk/docs/STATUS.md:44-47`). Rule for RK messages: RK repo (`rk/proto/envelope/SPEC.md:16`; `RK3588_AGENT_KICKOFF.md:101`). Same rule on AGX messages: AGX proposal. |
| 12 | Network | Link C (10.42.0.1/30 <-> 10.42.0.2/30) is NOT configured. No network change tonight (R5). | RK repo (`RK3588_AGENT_KICKOFF.md:139`); Probe |
| 13 | Dashboard | TCP 8700 | Night-task Section 6 default |
| 14 | RK registry channels 8014, 8010, 5612, 5607, 5592, 5588 | NOT served by this node tonight | RK repo (`rk/proto/bus_registry.yaml:33-45`) |

## 2. Network and ports

### 2.1 Link C (planned, not configured)

| Item | Value | Source |
|---|---|---|
| Link C | Point-to-point 1 GbE. AGX `eno1` 10.42.0.1/30. RK `eth0` 10.42.0.2/30. | RK repo (`RK3588_AGENT_KICKOFF.md:139`, `:100`) |
| Link C MTU | 9000 target, 1500 fallback | RK repo (`RK3588_AGENT_KICKOFF.md:139`) |
| RK interface | `eth0` (GMAC0, the only PHC `/dev/ptp0`). MTU range 46-9000, now 1500. Jumbo frames unverified. | RK repo (`rk/docs/BRINGUP_REPORT.md:592-595`, `:1627`) |
| Traffic classes | Planned `mqprio` TC0 = PTP + ZMQ + heartbeat, TC1 = FrameLink. Not possible on the RK kernel (`CONFIG_NET_SCHED` not set). Interim: userspace pacing + `SO_PRIORITY`. | RK repo (`RK3588_AGENT_KICKOFF.md:139`; `rk/docs/BRINGUP_REPORT.md:1590`) |
| RK `agx_host` | `"10.42.0.1"` | RK repo (`rk/config/rk.toml:152`; `rk/boards/rk3588-da01/board.toml:23-24`) |
| Link C state, AGX | NOT configured. `ip addr` has no 10.42.0.x address. `ip route get 10.42.0.2` goes `via 10.0.0.1 dev eno1` (internet gateway). | Probe (`T1_rk-probe.md` section 6) |
| Link C state, RK | NOT configured. "A fixed 10.42.0.2/30 on the board is a proposed change, not made". | RK repo (`rk/docs/RECOVERY.md:28`; `rk/docs/STATUS.md:45-47`) |
| Network changes tonight | None (rule R5) | Night-task rule R5 |

### 2.2 Path until Link C exists

| Item | Value | Source |
|---|---|---|
| AGX `eno1` | 10.0.0.130/24, 2500 Mb/s full duplex | Probe (`T1_rk-probe.md` section 2) |
| RK DA01 path | tailscale only, through DERP relay `lhr`. No direct path. RTT about 12.6 ms. | Probe (`T1_rk-probe.md` section 1) |
| tailscale addresses | AGX 100.64.0.20, RK 100.64.0.180 | Probe |
| tailscale0 MTU | 1280 | Probe |
| Results/status bind | `tcp://0.0.0.0:5560` and `tcp://0.0.0.0:5561` (all interfaces) | AGX proposal (RK repo defines nothing for this case) |
| Test path for the RK | `tcp://100.64.0.20:5560` and `tcp://100.64.0.20:5561` over tailscale | AGX proposal |
| FrameLink receive, mode `rk` | UDP `0.0.0.0:6000-6005` | AGX proposal; check `config/sources.yaml:15-17` |
| FrameLink receive, mode `sim` | UDP `127.0.0.1:6000-6005` (loopback only) | Check `config/sources.yaml:15-17` |

Note (AGX proposal): FrameLink at full rate does not fit the tailscale path (DERP relay, MTU 1280). For tests on this path, use the H.265 payload (fmt 2) or one camera.

### 2.3 Socket buffers

| Item | Value | Source |
|---|---|---|
| RK setting | `net.core.rmem_max = 8388608`, `net.core.wmem_max = 8388608` | RK repo (`rk/ops/etc/sysctl-driveragent.conf:7-9`) |
| AGX now | `net.core.rmem_max = 212992` B. No root, no change tonight. The receiver asks for the maximum (`rcvbuf_bytes: 0`). | Check `config/sources.yaml:23-25` |
| Owner decision | Set 8 MiB on the AGX, as the RK does | AGX proposal |

### 2.4 Ports of the AGX node

| Port | Proto | Direction | Bind | Use | Source |
|---|---|---|---|---|---|
| 6000-6005 | UDP | RK -> AGX | `0.0.0.0` (mode rk), `127.0.0.1` (mode sim) | FrameLink, camera N on 6000+N | RK repo (`RK3588_AGENT_KICKOFF.md:86`, `:135`) |
| 5560 | TCP | AGX -> RK | `0.0.0.0` | ZMQ PUB `AgxPerceptionResult` | Night-task Section 6 default |
| 5561 | TCP | AGX -> RK | `0.0.0.0` | ZMQ PUB `AgxInferStatus`, 1 Hz | Night-task Section 6 default |
| 5562 | TCP | local | `127.0.0.1` | Internal JSON status + JPEG snapshots for the dashboard | AGX proposal; check `config/dashboard.yaml:28` |
| 5563 | TCP | local | `127.0.0.1` | Local admin socket: model stop/start for tests. Not reachable from the network. The dashboard stays read-only. | AGX proposal |
| 8700 | TCP | any -> AGX | `0.0.0.0` | Dashboard, HTTP GET `/api/health`. If 8700 is in use, the next free port (8701, ...). | Night-task Section 6/7 default; check `config/dashboard.yaml:2-4` |

Collisions:

| Check | Result | Source |
|---|---|---|
| Running services on 5560-5563, 6000-6005, 8700 | None | Check `docs/audit/agx_audit_agx02_20261005_210334/raw/Listening_ports.txt` |
| Old stack (not running) | Used TCP 5600, 5601, 5610 on 0.0.0.0, and 8010, 8011, 8014 (8014 bound as `tcp://*:8014` by the old driverguard model) | `docs/research/T1_old-stack.md` section 6 |
| Rule | Do not run the old stack together with this node. | AGX proposal |

## 3. Video: FrameLink (RK -> AGX)

### 3.1 State

| Item | Value | Source |
|---|---|---|
| Transport | FrameLink, UDP, camera N -> port 6000+N | RK repo (`RK3588_AGENT_KICKOFF.md:86`, `:135`) |
| FrameLink TX on the RK | NOT implemented at rk-v0.4.0: "FrameLink TX deferred by Tony until after the HMI" | RK repo (`rk/docs/STATUS.md:291`) |
| Other video sender on the RK | None (no RTP, RTSP or GStreamer sender) | `T1_rk-repo.md` section 3 |
| Section 6 H.265 RTP/UDP 5600-5605 | NOT used. The RK repo defines the transport. | Owner rule |
| AGX receiver | Implemented: `common/framelink.py`, `infer/ingest/framelink_rx.py`. Tested: `tests/test_framelink.py`. | Check |

### 3.2 Frame header (40 bytes, little-endian)

Python layout: `struct.Struct("<IBBBBIQHHHHB3sII")` (`common/framelink.py:29`). Field order and sizes: RK repo (`RK3588_AGENT_KICKOFF.md:86`).

| Offset | Size | Field | Value | Source |
|---:|---:|---|---|---|
| 0 | 4 | `magic` | `0x4B4E4C46` (bytes on the wire `46 4C 4E 4B` = "FLNK") | Field: RK repo (`RK3588_AGENT_KICKOFF.md:86`). Value: AGX proposal (RK repo defines nothing) (`common/framelink.py:27`) |
| 4 | 1 | `ver` | `1` | Field: RK repo. Value: AGX proposal (`common/framelink.py:28`) |
| 5 | 1 | `cam` | 0..5 | RK repo |
| 6 | 1 | `fmt` | See 3.3 | Field: RK repo. Codes: AGX proposal |
| 7 | 1 | `health` | See 3.4 | Field: RK repo. Codes: RK repo (LinkState). Use of LinkState here: AGX proposal |
| 8 | 4 | `seq` | Frame sequence number per camera, wraps at 2^32. See 3.8. | RK repo |
| 12 | 8 | `t_capture_ptp_ns` | Capture time, ns. See 3.8 and Section 6. | RK repo |
| 20 | 2 | `w` | Frame width, pixels | RK repo |
| 22 | 2 | `h` | Frame height, pixels | RK repo |
| 24 | 2 | `stride` | Row stride, bytes (NV12: `stride = width`, `rk/camd/src/rga_scaler.cpp:35-43`). 0 for H.265. | RK repo; 0 for H.265 = AGX proposal |
| 26 | 2 | `exposure_us` | 0 = unknown | Field: RK repo. "0 = unknown": AGX proposal, the same rule as CameraHealth.exposureUs (`rk/proto/schema/message.capnp:27`) |
| 28 | 1 | `source` | See 3.5 | RK repo (1 = LIVE). Other codes: AGX proposal |
| 29 | 3 | `reserved` | 0 | Field: RK repo. Value 0: AGX proposal (`common/framelink.py:82`) |
| 32 | 4 | `payload_crc32c` | CRC-32C over the payload bytes (bytes 40..end) | Field: RK repo. Coverage: AGX proposal (`common/framelink.py:79`) |
| 36 | 4 | `header_crc32c` | CRC-32C over header bytes 0..35. These bytes include `payload_crc32c`: compute the payload CRC first. | Field: RK repo. Coverage: AGX proposal (`common/framelink.py:80-83`) |
| 40 | n | payload | NV12 or H.265 access unit | Field: RK repo. NV12: RK repo (`RK3588_AGENT_KICKOFF.md:85`). H.265: AGX proposal |

CRC-32C = Castagnoli, the same function as the dabus envelope: reflected polynomial `0x82F63B78`, init `0xFFFFFFFF`, final xor `0xFFFFFFFF`, check value `crc32c(b"123456789") == 0xE3069283` (RK repo `rk/proto/envelope/dabus_envelope.py:42-59`, `:158`). The use for FrameLink is an AGX proposal.

Receiver checks, in this order (AGX code):
1. Length >= 40, magic, version, header CRC (`common/framelink.py:90-100`).
2. `cam` agrees with the UDP port (`infer/ingest/framelink_rx.py:336-339`).
3. A frame with the same `seq` as the last frame is a duplicate. The receiver drops it and does not count it (`infer/ingest/framelink_rx.py:342-345`).
4. Payload CRC (`infer/ingest/framelink_rx.py:352-359`).

The receiver drops a frame that fails check 1, 2 or 4 and counts it in `bad_frames` (`infer/ingest/framelink_rx.py:328-359`).

### 3.3 `fmt` codes

| Code | Name | Payload | Source |
|---:|---|---|---|
| 1 | NV12 | Y plane (`stride * h`), then interleaved UV plane (`stride * h / 2`). Size = 1.5 x `stride * h`. | Code: AGX proposal (`common/framelink.py:33`). Layout: RK repo (`rk/camd/src/rga_scaler.cpp:35-43`) |
| 2 | H.265 | One H.265 access unit, Annex-B byte stream. VPS/SPS/PPS come before each IDR. Optional payload to save bandwidth. | AGX proposal (`common/framelink.py:34`). Codec: Night-task Section 6 default, carried inside FrameLink. |

H.265 receiver rule (AGX proposal): after a lost frame, the receiver drops frames until the next random access picture (`h265_resync_on_loss: true`, `config/sources.yaml:45`). At start, this picture must come with VPS/SPS/PPS. After a loss, an IDR or CRA picture is sufficient when the parameter sets were received before (`infer/ingest/framelink_rx.py:54-61`). No B-frames (Night-task Section 6 default).

### 3.4 `health` codes (rk-camd LinkState)

| Code | Name | Source |
|---:|---|---|
| 0 | NotStarted | RK repo (`rk/camd/src/protocol.h:121`; `rk/proto/schema/message.capnp:34-39` CameraHealth.LinkState `notStarted @0`) |
| 1 | Starting | RK repo |
| 2 | Live | RK repo |
| 3 | Stalled | RK repo |
| 4 | NoSignal | RK repo |

Use of LinkState in the FrameLink `health` byte: AGX proposal (the kick-off defines no codes).

### 3.5 `source` codes

| Code | Name | AGX treatment | Source |
|---:|---|---|---|
| 1 | LIVE | Live only in AGX mode `rk` | RK repo (`RK3588_AGENT_KICKOFF.md:86`) |
| 2 | REPLAY | Simulated | AGX proposal (`common/framelink.py:38`) |
| 3 | TEST_PATTERN | Simulated | AGX proposal (`common/framelink.py:39`) |
| other | unknown | Simulated | AGX proposal (`infer/ingest/framelink_rx.py:85-91`) |

### 3.6 Fragment header (16 bytes, little-endian)

The kick-off says only "16 B fragment header" (`RK3588_AGENT_KICKOFF.md:86`; `rk/docs/BRINGUP_REPORT.md:783`). The layout is an AGX proposal (RK repo defines nothing). Python layout: `struct.Struct("<HBBIHHI")` (`common/framelink.py:49`).

| Offset | Size | Field | Value |
|---:|---:|---|---|
| 0 | 2 | `magic` | `0x4C46` (bytes on the wire `46 4C` = "FL") (`common/framelink.py:47`) |
| 2 | 1 | `ver` | `1` (`common/framelink.py:48`) |
| 3 | 1 | `cam` | 0..5 |
| 4 | 4 | `seq` | Frame `seq` (same value as the frame header) |
| 8 | 2 | `idx` | Fragment index, 0..count-1 |
| 10 | 2 | `count` | Number of fragments of this frame (max 65535, `common/framelink.py:110-112`) |
| 12 | 4 | `offset` | Byte offset of this chunk in (40-byte frame header + payload) |
| 16 | n | chunk | Data |

Each fragment is one UDP datagram (RK repo, `rk/docs/BRINGUP_REPORT.md:783`). The fragment header has no CRC. The frame header CRCs protect the reassembled frame. The receiver drops a datagram with a bad fragment header (magic, version, `count` = 0, `idx` >= `count`, or `offset` + chunk > max frame). It counts the datagram in `bad` (`common/framelink.py:172-182`). The receiver does not check the fragment `cam` byte.

### 3.7 Fragment size and receiver behaviour

| Item | Value | Source |
|---|---|---|
| Chunk at MTU 9000 | 8896 B | RK repo (`RK3588_AGENT_KICKOFF.md:86`); AGX `common/framelink.py:52` |
| Chunk at MTU 1500 | 1456 B (UDP payload 1472 B). The kick-off value 1472 B + 16 B overflows MTU 1500. | RK repo (`rk/docs/BRINGUP_REPORT.md:1593`, gap row `:1631`). Not agreed yet: open question `:1711`. AGX uses it (`common/framelink.py:53`) |
| Chunk size on the receiver | Any size. The receiver uses `offset`. | AGX proposal (`common/framelink.py:176-204`) |
| Max frame | 2 MiB in the receive processes (4 MiB in the thread-mode reassembler) | AGX proposal (`max_frame_bytes` in `config/sources.yaml`; `common/framelink.py` Reassembler default) |
| Frames in flight per camera | 4 | AGX proposal (`common/framelink.py:148`) |
| Partial frame timeout | 200 ms, then the frame is abandoned | AGX proposal (`common/framelink.py:149`, `:205-208`; `reassembly_timeout_s: 0.2`, `config/sources.yaml:42`) |
| Newest frame wins | A complete frame abandons all older partial frames of that camera | AGX proposal (`common/framelink.py:212-215`) |
| Duplicates | Dropped | AGX proposal (`common/framelink.py:197-198`) |

### 3.8 Frame sizes, colour and identity

| Item | Value | Source |
|---|---|---|
| Camera input on the RK | UYVY 1920x1080, 30 fps | RK repo (`rk/config/rk.toml:44-48`) |
| cam0 FrameLink size | 1280x720 NV12 | RK repo (`rk/config/rk.toml:62-65`; `RK3588_AGENT_KICKOFF.md:85`) |
| cam1-5 FrameLink size | 704x396 NV12 | RK repo (`rk/config/rk.toml:67-90`; `RK3588_AGENT_KICKOFF.md:85`) |
| Section 6 size (1280x720 30 fps for all) | Not used for cam1-5. The RK repo defines the sizes. | Owner rule |
| Scaling | Full-frame RGA resize, no crop: `srect{0,0,s.w,s.h}` -> `drect{0,0,d.w,d.h}`. 1920x1080 -> 1280x720 is exactly /1.5. | RK repo (`rk/camd/src/rga_scaler.cpp:89-90`) |
| Colour | NV12, BT.601, limited range. Declared by the RK, UNVERIFIED. The AGX does the single YUV->RGB conversion. | RK repo (`rk/config/rk.toml:50-57`) |
| cam1-5 on demand | cam0 always on. cam1-5 off by default, on when a surround model is selected. | RK repo (`RK3588_AGENT_KICKOFF.md:86`; `rk/config/rk.toml:60-61`) |
| Frame identity | (camId, FrameLink `seq`, `t_capture_ptp_ns`). Replaces the Section 6 "camera number + 90 kHz RTP timestamp". | RK repo header fields (`RK3588_AGENT_KICKOFF.md:86`) |
| `seq` meaning | The RK must define `seq` so that the RK can map a result to the RAW frame that it displays: use the rk-camd `frame_no`, or keep a map to the capture time. The HMI shows RK RAW frames, not FrameLink frames. | AGX proposal; facts: RK repo (`rk/camd/src/protocol.h:99-109`; `T1_rk-repo.md` section 7 item 4) |
| `t_capture_ptp_ns` clock before PTP | The RK repo does not say. The rk-camd capture time is CLOCK_MONOTONIC. AGX proposal: CLOCK_REALTIME at capture, as the envelope rule for `t_ptp_ns`. | RK repo (`rk/camd/src/protocol.h:99-109`; `rk/proto/envelope/SPEC.md:16`); AGX proposal |

### 3.9 Bandwidth

| Case | Rate | Source |
|---|---|---|
| NV12, 6 cameras, MTU 9000 | 841.4 Mb/s (84.1 % of 1 GbE) | RK repo (`rk/docs/BRINGUP_REPORT.md:782-800`) |
| NV12, cam0 only, MTU 9000 | 334.9 Mb/s | RK repo (`rk/docs/BRINGUP_REPORT.md:782-800`) |
| NV12, 6 cameras, MTU 1500, 1456 B chunk | 880.7 Mb/s (88.1 % of 1 GbE) | RK repo (`rk/docs/BRINGUP_REPORT.md:1593`) |
| H.265, per camera, 1280x720 30 fps | About 5 Mb/s (old logger recordings: hevc Main, about 5.01 Mb/s) | `docs/research/T1_old-stack.md` (recordings table) |
| AGX `eno1` link speed | 2500 Mb/s | Probe |

### 3.10 Timeouts in the RK kick-off

The kick-off lists "Timeouts the AGX applies to you", for example "FrameLink 150 ms or seq gap >= 3 -> camera INVALID" (RK repo, `RK3588_AGENT_KICKOFF.md:141`). These are rules of the AGX supervisor. This node is not the supervisor. It does not apply them (AGX proposal). It uses the Section 6 stale rule (Section 4.6).

## 4. Results: `AgxPerceptionResult` (AGX -> RK)

### 4.1 Channel

| Item | Value | Source |
|---|---|---|
| Socket | ZMQ PUB, AGX binds `tcp://0.0.0.0:5560`, the RK connects (SUB) | Port: Night-task Section 6 default (the RK registry has no generic perception channel). Direction: RK repo (`rk/proto/bus_registry.yaml:3`) |
| ZMQ frame | One ZMQ frame = 32-byte dabus envelope + Cap'n Proto payload. No topic frame. | RK repo (`rk/proto/envelope/SPEC.md:3-5`) |
| Payload encoding | Cap'n Proto, unpacked, single segment, standard flat array with segment table (Python `to_bytes()`) | RK repo (`rk/proto/envelope/SPEC.md:3-5`; `rk/hmi/driveragent_hmi/bus.py:183`) |
| Message rate | One message per (model, camera, frame) | Night-task Section 6 default |
| Schema file | `/home/tonyho/driveragent-agx/proto/agx_infer.capnp`, file id `0xd30f559909e364de`, schema version 1 | AGX proposal |

### 4.2 Envelope (32 bytes, little-endian)

Layout: RK repo (`rk/proto/envelope/SPEC.md:9-19`). Python: `struct.Struct("<HBBHHIIQI")` + CRC u32 (`rk/proto/envelope/dabus_envelope.py:37`). AGX code: `common/envelope.py`, `common/dabus_envelope.py`. `common/dabus_envelope.py` is identical to the RK reference (Check: `diff` gives no difference).

| Offset | Size | Field | Value for 5560 | Source |
|---:|---:|---|---|---|
| 0 | 2 | magic | `0xDA5E` (wire `5e da`) | RK repo (`SPEC.md:9`) |
| 2 | 1 | ver | `1` | RK repo (`SPEC.md:10`) |
| 3 | 1 | src_board | `1` = AGX | RK repo (`SPEC.md:11`) |
| 4 | 2 | type_id | `5560` (= port) | RK repo rule (`rk/proto/bus_registry.yaml:2`); value: Section 6 port |
| 6 | 2 | flags | bit0 `source_is_replay` (AGX sets it for every simulated source, Section 7). bit1 `time_uncertain`: ALWAYS set (no PTP). bit2 `degraded`: node state DEGRADED. Other bits 0. | Bits: RK repo (`SPEC.md:13`). Use: AGX proposal. The RK HMI does not check flags on receive (`T1_rk-repo.md` section 2.2). |
| 8 | 4 | schema_hash | `0xafcaff02` (`AgxPerceptionResult` v1) | Rule: RK repo (`SPEC.md:14`, `:24-27`). Value: Check (see below) |
| 12 | 4 | seq | Counter per (src_board, type_id), wraps at 2^32 | RK repo (`SPEC.md:15`); AGX `common/envelope.py:66-75` |
| 16 | 8 | t_ptp_ns | `tAgxResultNs` (AGX CLOCK_REALTIME) | Field: RK repo (`SPEC.md:16`). Value: AGX proposal |
| 24 | 4 | len | Payload length | RK repo (`SPEC.md:17`) |
| 28 | 4 | crc32c | CRC-32C over bytes 0..27, then the payload | RK repo (`SPEC.md:18`) |
| 32 | len | payload | Cap'n Proto `AgxPerceptionResult` | RK repo |

Schema hash check (run for this document): `cd /home/tonyho/driveragent-agx && PYTHONPATH=. .venv/bin/python -c "from common import dabus_envelope as d; t=open('proto/agx_infer.capnp').read(); print('%08x %08x' % (d.schema_hash(t,'AgxPerceptionResult'), d.schema_hash(t,'AgxInferStatus')))"` prints `afcaff02 9086fa18`. `AgxPerceptionResult` = `0xafcaff02`. `AgxInferStatus` = `0x9086fa18`. The code uses the RK reference canonical text rule (`rk/proto/envelope/SPEC.md:24-27`; `dabus_envelope.py:69-97`).

Receiver rule in the RK repo: drop a frame with a wrong magic, version, length or CRC. Treat a different schema_hash for the type_id as a schema mismatch and do not decode it (`rk/proto/envelope/SPEC.md:21-22`). The RK HMI also drops a message with a wrong `src_board` or `type_id` (`rk/hmi/driveragent_hmi/bus.py:146-170`).

### 4.3 Schema (verbatim copy of `proto/agx_infer.capnp`)

```capnp
@0xd30f559909e364de;
# driveragent-agx: AGX inference node -> RK3588. Schema version 1 (2026-10-05, night run).
#
# Transport (RK repo design, rk-v0.4.0 kick-off section 4 + driveragent-proto):
#   ZMQ PUB on the AGX (the AGX binds, the RK connects). One ZMQ frame = 32-byte dabus envelope
#   (src_board 1 = AGX, type_id = port, schema_hash = FNV-1a of the canonical struct text) + one
#   unpacked single-segment Cap'n Proto message of a struct below.
#   Envelope flags: bit0 source_is_replay = the frame came from the simulator or a file (R13),
#                   bit1 time_uncertain = always set (no PTP between the boards yet),
#                   bit2 degraded = node state DEGRADED.
# Channels (night-task Section 6 defaults; the RK registry defines no generic result/status channel):
#   5560 AgxPerceptionResult  one message per (model, camera, frame) result
#   5561 AgxInferStatus       1 Hz
# Rules: additive only (new fields take the next ordinal). Any change of a struct changes its
# schema hash: bump schemaVersion and tell the RK side.
# Times: *Ns fields are CLOCK_REALTIME nanoseconds unless the comment says otherwise.

const schemaVersion :UInt16 = 1;

struct AgxPerceptionResult {
  schemaVersion @0 :UInt16;       # = 1
  model @1 :Text;                 # model name from config/models.yaml, e.g. "driverguard_yolopx"
  modelVersion @2 :Text;          # engine file name + ":" + sha256[:16] of the engine file
  camId @3 :UInt8;                # 0..5 (FrameLink cam = UDP port 6000 + camId)
  frameSeq @4 :UInt32;            # FrameLink header seq of the frame that was used
  tCaptureNs @5 :UInt64;          # FrameLink header t_capture_ptp_ns of that frame (sender clock)
  tAgxRecvNs @6 :UInt64;          # AGX: last fragment of the frame received
  tAgxReadyNs @7 :UInt64;         # AGX: frame decoded and ready (NV12: = tAgxRecvNs)
  tAgxResultNs @8 :UInt64;        # AGX: result complete, just before publish
  frameWidth @9 :UInt16;          # pixel space of every box and mask below = the FrameLink frame size
  frameHeight @10 :UInt16;        # (cam0 1280x720 in the RK design: x1.5 gives capture pixels 1920x1080)
  simulated @11 :Bool;            # true: the frame is NOT from a live camera (simulator / file)
  source @12 :Text;               # "live" | "replay" | "test-pattern" | "file"
  detections @13 :List(Detection);
  trajectory @14 :Trajectory;     # points is empty when the model gives no trajectory
  masks @15 :List(Mask);          # empty when the model gives no mask (or masks are off for this camera)
  timing @16 :Timing;

  struct Detection {
    classId @0 :UInt16;           # index into the model's class list (docs/MODELS.md)
    className @1 :Text;
    score @2 :Float32;            # 0..1
    x1 @3 :Float32;               # box, pixels of frameWidth x frameHeight, x right, y down
    y1 @4 :Float32;
    x2 @5 :Float32;
    y2 @6 :Float32;
    trackId @7 :UInt32;           # 0 = no track (no model gives tracks tonight)
  }

  struct Trajectory {
    frame @0 :Text;               # coordinate frame, named in full (axes, units, origin)
    points @1 :List(Point);
    inputsValid @2 :Bool;         # false: some model inputs were not real (for example ego speed unknown)
    note @3 :Text;                # which inputs were assumed, and "display only, not for control"
    struct Point {
      x @0 :Float32;
      y @1 :Float32;
      tS @2 :Float32;             # time after the frame, seconds
    }
  }

  struct Mask {
    name @0 :Text;                # "drivable_area" | "lane_line"
    width @1 :UInt16;             # mask size (= frameWidth x frameHeight for DriverGuard)
    height @2 :UInt16;
    encoding @3 :Text;            # "rle-u16le-count-u8-value-rowmajor" (old DriverGuard mask_codec)
    data @4 :Data;
  }

  struct Timing {
    queueMs @0 :Float32;          # frame ready -> processing start
    preMs @1 :Float32;
    inferMs @2 :Float32;          # TensorRT enqueue -> outputs on the host
    postMs @3 :Float32;
    totalMs @4 :Float32;          # frame ready -> result complete
  }
}

struct AgxInferStatus {
  schemaVersion @0 :UInt16;       # = 1
  hostname @1 :Text;
  version @2 :Text;               # git describe of driveragent-agx
  nodeState @3 :Text;             # "STARTING" | "RUNNING" | "DEGRADED" | "ERROR"
  simulated @4 :Bool;             # true when any camera input is simulated
  uptimeS @5 :UInt32;
  tStatusNs @6 :UInt64;
  sourceMode @7 :Text;            # config/sources.yaml mode: "rk" | "sim" | "file"
  cameras @8 :List(Camera);
  models @9 :List(Model);
  temps @10 :List(Temp);
  errors @11 :List(Text);         # newest first, at most 20
  resultsPort @12 :UInt16;        # 5560
  resultSubscribers @13 :UInt16;  # TCP peers connected to the results socket
  resultsRateHz @14 :Float32;     # results published per second (all models, all cameras)

  struct Camera {
    camId @0 :UInt8;
    role @1 :Text;
    state @2 :Text;               # "OK" | "SIMULATED" | "STALE" | "NO SIGNAL"
    simulated @3 :Bool;
    fps @4 :Float32;
    frameAgeMs @5 :Float32;       # NaN = never a frame
    lostFrames @6 :UInt64;
    lostPackets @7 :UInt64;
    lastFrameSeq @8 :UInt32;
  }

  struct Model {
    name @0 :Text;
    state @1 :Text;               # "RUNNING" | "LOADED" | "OFF" | "FAILED"
    error @2 :Text;               # "" = none
    cameras @3 :List(UInt8);
    fps @4 :Float32;              # results per second, all cameras of the model
    latencyP50Ms @5 :Float32;     # totalMs percentiles over the last 60 s
    latencyP95Ms @6 :Float32;
    latencyP99Ms @7 :Float32;
  }

  struct Temp {
    zone @0 :Text;
    celsius @1 :Float32;
  }
}
```

### 4.4 Box pixel space

| Item | Value | Source |
|---|---|---|
| Pixel space | The FrameLink frame of that result: `frameWidth` x `frameHeight` | AGX proposal (`proto/agx_infer.capnp:30-31`, `:43`) |
| Axes | x to the right, y down, origin at the top-left pixel corner of the frame | AGX proposal (`proto/agx_infer.capnp:43`) |
| Box | `x1, y1` = top-left, `x2, y2` = bottom-right, Float32 pixels | AGX proposal |
| cam0 to capture pixels | Multiply by 1.5: 1280x720 -> 1920x1080 | RK repo (full-frame resize, `rk/camd/src/rga_scaler.cpp:89-90`) |
| cam1-5 to capture pixels | Multiply by 1920 / `frameWidth` and 1080 / `frameHeight` (704x396 -> 1920x1080) | RK repo (same resize rule) |
| RK precedent | The maintenance overlay draws in capture pixels (1920x1080) and scales to the tile | RK repo (`rk/hmi/driveragent_hmi/screens/maintenance.py:396`, `:460-473`, `:485`) |
| Section 6 rule ("pixels of the 1280x720 source frame") | Kept for cam0. For cam1-5 the FrameLink frame is 704x396. | Night-task Section 6 default + RK repo sizes |
| Masks | `width` x `height` in the same pixel space (= `frameWidth` x `frameHeight` for DriverGuard) | AGX proposal (`proto/agx_infer.capnp:62-68`) |
| Trajectory | Its own coordinate frame, named in full in `Trajectory.frame`. "display only, not for control". | Night-task Section 6 default; AGX proposal (`proto/agx_infer.capnp:50-60`) |
| RK vehicle frame | x forward, y left, z up, origin rear-axle centre on the ground | RK repo (`rk/hmi/driveragent_hmi/screens/world.py:6-7`; `rk/config/cameras.toml:11-15`) |

### 4.5 Field sources (Section 6 list)

| Section 6 field | `AgxPerceptionResult` field | Source |
|---|---|---|
| schema version | `schemaVersion` = 1 | Night-task Section 6 default |
| model name | `model`, `modelVersion` | Night-task Section 6 default; `modelVersion` = AGX proposal |
| camera number | `camId` | Night-task Section 6 default |
| RTP timestamp | Replaced by `frameSeq` + `tCaptureNs` (FrameLink identity) | RK repo (`RK3588_AGENT_KICKOFF.md:86`) |
| AGX receive time | `tAgxRecvNs` (and `tAgxReadyNs`) | Night-task Section 6 default |
| AGX result time | `tAgxResultNs` | Night-task Section 6 default |
| detections (class, score, box, track) | `detections` (`classId`, `className`, `score`, `x1..y2`, `trackId`; 0 = no track) | Night-task Section 6 default |
| other outputs in their own structure | `trajectory` (with `frame`), `masks`, `timing` | Night-task Section 6 default |
| simulated flag | `simulated`, `source` | Night-task rule R13 |

### 4.6 Stale rule and no re-send

| Rule | Source |
|---|---|
| No new frame for a camera for 500 ms: publish no result for that camera. | Night-task Section 6 default (`config/sources.yaml:19-20`, `stale_s: 0.5`; `infer/ingest/frame_store.py:10`) |
| That camera's state is STALE in `AgxInferStatus.Camera.state`. | Night-task Section 6 default |
| No frame for 1 s: state NO SIGNAL. | AGX proposal (`config/sources.yaml:21`, `no_signal_s: 1.0`) |
| Never re-send an old result. Each result belongs to exactly one frame. | Night-task Section 6 default |

## 5. Status (AGX -> RK)

### 5.1 ZMQ status

| Item | Value | Source |
|---|---|---|
| Socket | ZMQ PUB, AGX binds `tcp://0.0.0.0:5561`, the RK connects | Night-task Section 6 default; direction: RK repo (`rk/proto/bus_registry.yaml:3`) |
| Rate | 1 Hz | Night-task Section 6 default |
| Payload | Cap'n Proto `AgxInferStatus` v1 (Section 4.3) | AGX proposal |
| Envelope | As 4.2, with type_id `5561`, schema_hash `0x9086fa18` | RK repo (envelope layout); type_id: Section 6 port; hash: Check |
| Envelope t_ptp_ns | `tStatusNs` | AGX proposal |
| Content | Node state, models, fps per camera, temperatures, errors | Night-task Section 6 default |

### 5.2 HTTP `/api/health`

| Item | Value | Source |
|---|---|---|
| URL | HTTP GET `http://<agx>:8700/api/health` | Night-task Section 6/7 default; check `dashboard/app.py` route `/api/health` |
| Auth | HTTP Basic auth, realm `agx02-dashboard` | AGX proposal; check `dashboard/auth.py:17` |
| Allowed sources | Private addresses only: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10 (tailscale), 169.254.0.0/16, ::1, fc00::/7, fe80::/10 | AGX proposal; check `config/dashboard.yaml:7-16` |
| Methods | GET only (POST gives 405) | Check `tests/test_dashboard.py:170` |
| RK client | None. The RK repo has no HTTP client for this. The RK reads nothing from the AGX over HTTP. | RK repo (`T1_rk-repo.md` section 4; the only HTTP use is the rk-updater download, `rk/updater/rk_updater.py:53-54`, `:126`) |

## 6. Time

| Item | Value | Source |
|---|---|---|
| PTP | None. RK milestone M3 is deferred. Planned: AGX grandmaster on `eno1`. | RK repo (`RK3588_AGENT_KICKOFF.md:100`; `rk/docs/STATUS.md:44-47`) |
| Clock on both boards | CLOCK_REALTIME from NTP | RK repo (`rk/docs/BRINGUP_REPORT.md:1561`: RK timesyncd to ntp.ubuntu.com; the probe could not check this); Probe (AGX) |
| AGX clock | systemd-timesyncd. About 31-41 ms ahead of public NTP servers (uncertainty about +/-8 ms). timesyncd jitter 47.8 ms. | Probe (`T1_rk-probe.md` section 3) |
| RK clock offset | NOT MEASURABLE read-only: no HTTP, no NTP answer on udp/123, `clockdiff` not installed | Probe |
| Envelope `time_uncertain` | Bit1 always set on every AGX message | Rule for RK messages: RK repo (`rk/proto/envelope/SPEC.md:16`; `RK3588_AGENT_KICKOFF.md:101`). Same rule on AGX messages: AGX proposal |
| Latency inside the AGX | Uses only AGX clock values (`tAgxRecvNs`, `tAgxReadyNs`, `tAgxResultNs`, `timing`) | AGX proposal |
| `tCaptureNs` | Sender clock. Do not subtract it from AGX times until PTP or a measured offset exists. | AGX proposal (`proto/agx_infer.capnp:26`) |
| Owner decision | PTP (AGX grandmaster, kick-off M3), or at least chrony on both boards | AGX proposal |

## 7. SIMULATED frames (rule R13)

A frame is simulated when one of these is true:
- The FrameLink `source` byte is not 1 (LIVE).
- The AGX source mode is not `rk` (`config/sources.yaml:3-9`: `sim` or `file`).

Source: Night-task rule R13; implemented in `infer/ingest/framelink_rx.py:7-9`, `:85-91`.

| Output | Marking | Source |
|---|---|---|
| `AgxPerceptionResult` | `simulated = true`, `source` = "replay", "test-pattern", "file" (or "live" only when live) | AGX proposal (`proto/agx_infer.capnp:32-33`) |
| Envelope | Flags bit0 (`source_is_replay`) set | RK repo bit (`rk/proto/envelope/SPEC.md:13`); use: AGX proposal |
| `AgxInferStatus` | `simulated = true` when any camera input is simulated; camera state "SIMULATED" | AGX proposal (`proto/agx_infer.capnp:84`, `:99-100`) |
| Dashboard | Label SIMULATED | Night-task rule R13 |

## 8. Camera roles

| camId | Role | Status | Source |
|---:|---|---|---|
| 0 | front | CONFIRMED (`gmsl_des29_linkA`, 120 deg rectilinear). The old stack agrees. | RK repo (`rk/boards/rk3588-da01/vehicle/camera_map.ini:13`, `:284-287`); `T1_old-stack.md` |
| 1 | RK: `unknown`. Old logger: right | UNCONFIRMED on the RK | RK repo (`camera_map.ini:289-312`: role `unknown`, `gmsl_section` `unassigned`); old stack `logger/encoder_265.py:60-67` |
| 2 | RK: `unknown`. Old logger: left | UNCONFIRMED | same |
| 3 | RK: `unknown`. Old logger: right-back | UNCONFIRMED | same |
| 4 | RK: `unknown`. Old logger: left-back | UNCONFIRMED | same |
| 5 | RK: `unknown`. Old logger: back | UNCONFIRMED | same |

The old UI uses other labels (0 Front, 1 Left Front, 2 Left Rear, 3 Rear, 4 Right Rear, 5 Right Front; old `ui/newwidgets/main_camera.py:19`). The AGX node uses `camId` only. The `role` text in `AgxInferStatus.Camera` is information only.

## 9. RK registry channels and this node

### 9.1 AGX -> RK channels NOT served tonight

| Channel | Port | Struct | RK registry status | Reason | Source |
|---|---:|---|---|---|---|
| driver_guard | 8014 | DriverGuardResult | pending, no struct in driveragent-proto | No struct to fill. Results go on 5560. | RK repo (`rk/proto/bus_registry.yaml:44-45`) |
| bev_frame | 8010 | BevFrame | pending, no struct | No struct to fill | RK repo (`bus_registry.yaml:42-43`) |
| board_hello_agx | 5612 | BoardHelloAgx | pending, no struct | No struct to fill | RK repo (`bus_registry.yaml:40-41`) |
| autopilot_state | 5607 | AutopilotState | pending | Supervisor function. Not on the inference node in the new split. | RK repo (`bus_registry.yaml:38-39`) |
| car_state | 5592 | CarState | pending | CAN function. Not on the inference node. | RK repo (`bus_registry.yaml:36-37`) |
| gps | 5588 | GpsLocationData | proposed | GNSS function. Not on the inference node. | RK repo (`bus_registry.yaml:33-35`) |

The old AGX `DriverGuardResult` (`/home/tonyho/driveragent/message/message.capnp:319-338`) carries `throttle`, `steer` and `brake`. It is NOT used. Rule R8: the node publishes perception results only.

Effect on the RK HMI today: the HMI opens no socket for a channel without a struct in its schema (`rk/hmi/driveragent_hmi/bus.py:103-104`). It also does not subscribe to 5560 or 5561. The "NO PERCEPTION" chip stays on (`rk/hmi/driveragent_hmi/views.py:151`).

Owner decision (recommendation first):
- **(a) Recommended:** add `AgxPerceptionResult` and `AgxInferStatus` to driveragent-proto as channels `agx_perception` 5560 and `agx_infer_status` 5561 (status `proposed`). Decide if 8014 and 8010 stay in the registry.
- **(b)** Or define `DriverGuardResult` for 8014 from the fields of `AgxPerceptionResult`.

### 9.2 RK -> AGX channels NOT received tonight

| Channel | Port | Struct | Source |
|---|---:|---|---|
| camera_health | 5572 | CameraHealth | RK repo (`bus_registry.yaml:15-16`) |
| hmi_heartbeat | 5595 | HmiHeartbeat | RK repo (`:17-18`) |
| hmi_request | 5604 | HmiRequest | RK repo (`:19-20`) |
| engage_request | 5608 | EngageRequest | RK repo (`:21-22`) |
| disengage_request | 5609 | DisengageRequest | RK repo (`:23-24`) |
| board_hello_rk | 5611 | BoardHelloRk | RK repo (`:25-26`) |
| segment_event | 5613 | SegmentEvent | RK repo (`:27-28`) |
| recorder_status | 5614 | RecorderStatus | RK repo (`:29-30`) |

Reason: no Link C, and inference does not need them. Possible next step: bind SUB on 5572 and use CameraHealth to cross-check the camera state (AGX proposal).

## 10. Probe results (T1.4)

Read-only probe from agx02 to RK DA01 (100.64.0.180), 2026-10-05 21:10-21:14 BST. Source: `docs/research/T1_rk-probe.md`.

| Item | Result |
|---|---|
| Ping (20 packets) | 0 % loss, rtt min/avg/max = 9.649 / 12.556 / 30.931 ms |
| Path | tailscale via DERP relay `lhr`. "direct connection not established". RK publishes no endpoints. |
| RK LAN addresses in RK docs (10.0.0.208, .209) | No answer, ARP INCOMPLETE |
| Open TCP ports (1-10000) | 22 (OpenSSH 8.9p1), 111 (rpcbind), 4000 (NoMachine), 5555 (adbd, root) |
| DriverAgent ports (5572, 5588-5614, 6000-6005, 8010, 8014, ...) | All closed. No ZMQ, RTSP or HTTP service. |
| Traffic from the RK to the AGX | None. Tailscale peer counters +0 B in 15 s. No inbound socket. |
| Traffic from the AGX to the RK | Probe traffic only: ping, TCP connect + close, 3 NTP requests to udp/123. No data sent to any open port. |
| Clock offset AGX vs RK | NOT MEASURABLE read-only |
| AGX clock vs public NTP | About 31-41 ms ahead |
| AGX `eno1` | 10.0.0.130/24, 2500 Mb/s full duplex |
| RK config | Every endpoint points to `agx_host = "10.42.0.1"` (unreachable today) |

## 11. Owner decisions

| # | Decision | Recommendation | Reference |
|---|---|---|---|
| O1 | Registry channels for AGX results and status | (a) Add `agx_perception` 5560 and `agx_infer_status` 5561 to driveragent-proto. Decide on 8014/8010. | Section 9.1 |
| O2 | Link C setup (10.42.0.1/30 <-> 10.42.0.2/30, MTU 9000) | Configure on both sides after the night run (not tonight, R5) | Section 2.1 |
| O3 | AGX `net.core.rmem_max` | 8 MiB, as `rk/ops/etc/sysctl-driveragent.conf:7-9` | Section 2.3 |
| O4 | Time sync | PTP (AGX grandmaster, kick-off M3), or at least chrony on both boards | Section 6 |
| O5 | FrameLink proposals (magic, version, fmt, health use, source codes, CRC coverage, fragment header) | Accept the values in Section 3 | Section 3 |
| O6 | cam1-5 roles | Confirm in `camera_map.ini` | Section 8 |

## 12. What the RK agent must build

The full task list goes in `docs/RK_TASKS.md` (written later, task T7). Summary:

| # | Task | Section |
|---|---|---|
| K1 | Implement FrameLink TX in rk-camd: 40-byte header, 16-byte fragment header, UDP to 6000+camId, as in Section 3. | 3 |
| K2 | Fill `seq` so that a result maps to the RAW frame on the HMI (rk-camd `frame_no` or a map to the capture time). | 3.8 |
| K3 | Fill `t_capture_ptp_ns` (CLOCK_REALTIME until PTP; AGX proposal) and `source` = 1 only for live cameras. | 3.8, 6, 7 |
| K4 | Confirm or change the AGX proposals in Section 3 (magic, version, fmt, health use, source, CRC coverage, fragment layout). | 3 |
| K5 | Add `AgxPerceptionResult` and `AgxInferStatus` to driveragent-proto (if the owner chooses O1 (a)), regenerate, bump the submodule. | 9.1 |
| K6 | Connect ZMQ SUB to 5560 and 5561. Check src_board 1, type_id, schema_hash, CRC. | 4, 5 |
| K7 | Draw boxes on camera tiles: scale from `frameWidth` x `frameHeight` to capture pixels (cam0 x 1.5). Show SIMULATED when `simulated` is true. | 4.4, 7 |
| K8 | Do not draw a result for a camera when no result arrives. Do not hold an old result. | 4.6 |
| K9 | Configure Link C `eth0` 10.42.0.2/30, MTU 9000, after the owner decision. | 2.1 |

## 13. References

| File | Use |
|---|---|
| `/home/tonyho/driveragent-agx/proto/agx_infer.capnp` | Result and status schema |
| `/home/tonyho/driveragent-agx/common/framelink.py` | FrameLink pack, unpack, fragment, reassemble |
| `/home/tonyho/driveragent-agx/common/envelope.py`, `common/dabus_envelope.py` | dabus envelope |
| `/home/tonyho/driveragent-agx/tests/test_framelink.py`, `tests/test_envelope.py` | Tests |
| `/home/tonyho/driveragent-agx/config/sources.yaml` | Source mode, bind address, stale times |
| `/home/tonyho/driveragent-agx/config/dashboard.yaml` | Dashboard port, allowed addresses |
| `/home/tonyho/driveragent-agx/docs/research/T1_rk-repo.md` | RK repository facts |
| `/home/tonyho/driveragent-agx/docs/research/T1_rk-probe.md` | Probe results |
| `/home/tonyho/driveragent-agx/docs/research/T1_old-stack.md` | Old stack ports, camera roles, recordings |
| `/home/tonyho/driveragent-agx/docs/research/T1_driverguard.md` | Old DriverGuardResult |
