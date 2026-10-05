# RK3588 repo interface facts for the AGX inference node (driveragent-hmi, tag rk-v0.4.0)

Repo: `/home/tonyho/driveragent-agx/ref/driveragent-hmi`. I confirmed the versions read-only: `git rev-parse HEAD` = 258cf5922278e9e530d71277c2e94b7be5aaef3e, `git describe` = rk-v0.4.0, and `rk/proto` HEAD = 6874e6127ba1b457f4ae110abfa4780c94cce044. Paths below are relative to the repo root. I also ran these read-only checks with `-B`, so no bytecode was written:
- `dabus_envelope.py --check golden_vectors.txt` → `ok: 4 vectors`
- `codegen/generate.py --check` → `generated/ up to date (3 files)`
- `--schema-hash schema/message.capnp CameraHealth` → `dea3299f`, the same value as `generated/schema_hashes.txt`.

**Short answer:** the RK draws nothing from AGX perception yet. No overlay or box drawing exists, BevFrame and DriverGuardResult have no struct, and no struct carries detections. FrameLink TX is not implemented, and no video sender of any kind exists in `rk/`.

---

## 1. Bus contract (`rk/proto`)

### 1.1 `bus_registry.yaml` (version 1, `rk/proto/bus_registry.yaml:11`)

General rules:
- **Transport:** "ZMQ PUB/SUB over Link C; the AGX binds every TCP socket, the RK connects" (`:3`).
- **type_id:** "The envelope's type_id is the channel's type_id (provisionally the ZMQ port)" (`:2`).
- **Status meanings:** agreed / proposed / pending (`:5-7`). "schema_hash is generated (generated/), never written here" (`:8`).
- **Command-path rule** (`:9-10`): no RK→AGX message sets speed, steer, gear or "enabled". ENGAGE and DISENGAGE are requests.

| name | type_id (port) | struct | dir | publisher | rate | max_age_ms | status | line |
|---|---|---|---|---|---|---|---|---|
| camera_health | 5572 | CameraHealth | rk→agx | rk-camd | 1 Hz per camera | 2500 | proposed | :15-16 |
| hmi_heartbeat | 5595 | HmiHeartbeat | rk→agx | rk-hmi | 10 Hz (render loop) | 300 | proposed | :17-18 |
| hmi_request | 5604 | HmiRequest | rk→agx | rk-hmi | on event; local_copy rk-recorder (ipc recorder-cmd) | – | proposed | :19-20 |
| engage_request | 5608 | EngageRequest | rk→agx | rk-hmi | on event (hold ≥ 1 s while ARMED) | – | proposed | :21-22 |
| disengage_request | 5609 | DisengageRequest | rk→agx | rk-hmi | every tap | – | proposed | :23-24 |
| board_hello_rk | 5611 | BoardHelloRk | rk→agx | rk-hello | 1 Hz | 3000 | proposed | :25-26 |
| segment_event | 5613 | SegmentEvent | rk→agx | rk-recorder | per closed segment file | – | proposed | :27-28 |
| recorder_status | 5614 | RecorderStatus | rk→agx | rk-recorder | 1 Hz; local_copy rk-hmi (ipc recorder-status) | 2000 | proposed | :29-30 |
| gps | 5588 | GpsLocationData | agx→rk | agx | – | 2000 | proposed; local_copy rk-gnss (src_board RK, ipc only) | :33-35 |
| car_state | 5592 | CarState | agx→rk | agx | – | 500 | **pending** | :36-37 |
| autopilot_state | 5607 | AutopilotState | agx→rk | agx supervisor | – | 500 | **pending** | :38-39 |
| board_hello_agx | 5612 | BoardHelloAgx | agx→rk | agx | – | 3000 | **pending** | :40-41 |
| bev_frame | 8010 | BevFrame | agx→rk | agx perception | – | 300 | **pending** | :42-43 |
| driver_guard | 8014 | DriverGuardResult | agx→rk | agx | – | 300 | **pending** | :44-45 |
| arbiter_state | 0 | ArbiterState | mcu via agx→rk | undefined | – | 500 | pending ("port and publisher not defined yet") | :46-47 |
| ptp_status | 0 | PtpStatus | rk→rk | ptp-check (M3) | – | 2000 | pending, local | :48-49 |

`nested: [StateEcho, RecorderStatus.StreamStat]` (`:52`).

Note: **no detection, box, model-overlay or trajectory channel exists in the registry.** The kickoff lists further AGX→RK channels that are not in the registry: CarDataMessage 5593, RouteStatus 5603, RouteGuidance 5605, WaypointCommand 5606, System1Result 8011, ComparisonMetrics 8015, LogEvent/Dtc 5710 (`RK3588_AGENT_KICKOFF.md:137`). RouteRequest 5602 RK→AGX is also missing (`:135`).

### 1.2 `schema/message.capnp`

- **File id:** `@0xc0d51b59f02ee024;` (`rk/proto/schema/message.capnp:1`)
- **Namespace:** `using Cxx = import "/capnp/c++.capnp"; $Cxx.namespace("rkmsg");` (`:14-15`). Python loaders therefore need the capnp include dir: they call `capnp.load(..., imports=["/usr/include"])` (`rk/hmi/driveragent_hmi/bus.py:92`).
- **Header text** (`:7-11`): the AGX-published structs (AutopilotState, CarState, ArbiterState, GpsLocationData, BoardHelloAgx, BevFrame, DriverGuardResult, PtpStatus) "are merged in here from the AGX repo's message.capnp by the AGX side's first PR; that PR also settles the C++ namespace (rkmsg today) and the file id."
- **Rules** (`:3-4`): additive only, and "ANY change to a struct changes its hash and needs both sides".
- **Structs present:** CameraHealth, StateEcho, HmiHeartbeat, EngageRequest, DisengageRequest, HmiRequest, BoardHelloRk, RecorderStatus (nested StreamStat), SegmentEvent, GpsLocationData. No AGX perception struct is present.

Verbatim (`rk/proto/schema/message.capnp:17-192`):

```capnp
# RK -> AGX, ZMQ 5572 (AGX binds, RK connects), 1 Hz per camera. The AGX marks a camera INVALID
# after 2.5 s without one.
struct CameraHealth {
  camId @0 :UInt8;                # 0..5 from camera_map.ini; 255 = unlabelled (bench, never used by the AGX)
  gmslSection @1 :Text;           # camera_map.ini link section, e.g. "gmsl_des29_linkA"
  linkState @2 :LinkState;
  frames @3 :UInt64;              # frames captured since rk-camd start
  seqGaps @4 :UInt64;             # frames lost in the driver (V4L2 sequence gaps)
  drops @5 :UInt64;               # frames captured but not delivered (no free buffer, RGA error, lend skip)
  lastCaptureMonoNs @6 :UInt64;   # V4L2 timestamp of the last frame, CLOCK_MONOTONIC (not yet PTP)
  exposureUs @7 :UInt32;          # 0 = unknown (vendor rkmodule UAPI not available on the board)
  fps @8 :Float32;                # over the last health period
  stalls @9 :UInt32;
  restarts @10 :UInt32;
  scaledP99Us @11 :UInt32;        # RGA (dequeue -> scaled frame ready) p99 over the period; 0 = no SCALED stream
  timestampSource @12 :Text;      # V4L2 flags, e.g. "MONOTONIC/EOF"

  enum LinkState {
    notStarted @0;
    starting @1;
    live @2;
    stalled @3;
    noSignal @4;
  }
}

# ---- HMI (M4), PROPOSED 2026-09-29; RK -> AGX, AGX binds, RK connects. None of these carries a speed,
# steer, gear or "enabled" field: they are telemetry and requests only (kick-off hard rule 2).

# What the HMI is currently showing of AutopilotState, echoed so the AGX can check the driver sees the
# current state.
struct StateEcho {
  valid @0 :Bool;                 # false: no fresh AutopilotState on screen (shown as "—")
  sourceSeq @1 :UInt32;           # envelope seq of the AutopilotState being displayed
  ageMs @2 :UInt32;               # its age when this frame was rendered
  degLevel @3 :UInt8;             # degradation level shown, 0 = none
  state @4 :Text;                 # state label shown
}

# 5595, 10 Hz, generated inside the HMI render loop (no thread): if the loop stalls, heartbeats stop.
struct HmiHeartbeat {
  renderFrame @0 :UInt64;         # frames rendered since HMI start
  lastInputMs @1 :UInt32;         # ms since the last touch/click (saturating; 0xFFFFFFFF = never)
  displayedStateEcho @2 :StateEcho;
  screen @3 :Text;                # screen on display, e.g. "cameras", "world"
}

# 5608. Sent only after ENGAGE was held >= 1 s while a fresh ArbiterState reported ARMED; one per hold.
struct EngageRequest {
  nonce @0 :UInt64;               # fresh random value per hold
  holdMs @1 :UInt32;
  arbiterSeq @2 :UInt32;          # envelope seq of the ArbiterState (ARMED) the button was enabled by
  displayedStateEcho @3 :StateEcho;
}

# 5609. Sent on every tap of DISENGAGE, in any state; never gated.
struct DisengageRequest {
  nonce @0 :UInt64;
  tapSeq @1 :UInt32;              # taps since HMI start
  displayedStateEcho @2 :StateEcho;
}

# 5604. Record, model selection, maintenance and camera restart requests.
struct HmiRequest {
  nonce @0 :UInt64;
  kind @1 :Kind;
  arg @2 :Text;                   # e.g. model name for selectModel
  enum Kind {
    startRecord @0;
    stopRecord @1;
    selectModel @2;
    restartCameras @3;
    maintenanceEnter @4;
    maintenanceExit @5;
    clearDtc @6;
  }
}

# 5611, RK -> AGX (AGX binds, RK connects), 1 Hz, from rk-hello. The AGX declares RK_LOST after 3 s
# without one, and can refuse ENGAGE when calibrationSha256 differs from its copy of cameras.toml.
struct BoardHelloRk {
  gitSha @0 :Text;                # same as version (kept for compatibility); "+dirty" = local changes
  registryHash @1 :Text;          # SHA-256 over the message schema file(s) the RK uses (hello.registry)
  calibrationSha256 @2 :Text;     # SHA-256 of the exact bytes of cameras.toml, re-read every message
  calibrationRevision @3 :UInt32; # cameras.toml `revision`
  kernel @4 :Text;                # uname -r
  uptimeS @5 :UInt32;
  socTempC @6 :Float32;           # NaN = unknown
  powerW @7 :Float32;             # NaN = unknown (no board power sensor read yet)
  bootId @8 :Text;                # /proc/sys/kernel/random/boot_id
  ssdTempC @9 :Float32;           # NVMe composite temperature; NaN = no NVMe (eMMC storage until it arrives)
  storageRoot @10 :Text;          # recorder storage root
  storageFreeBytes @11 :UInt64;   # free space on the storage root's filesystem
  recorderAlive @12 :Bool;        # a RecorderStatus arrived within 3 s
  recording @13 :Bool;            # from RecorderStatus (false when not alive)
  recorderSessionId @14 :Text;
  recorderLastError @15 :Text;
  # Identity (2026-10-01, PROPOSED): /etc/driveragent/board.toml [board]; vehicle calibration hashes.
  boardId @16 :Text;              # e.g. "ami-01"; "" = not set
  role @17 :Text;                 # "dev" | "customer"
  vehicleId @18 :Text;            # the vehicle this board is fitted to; "" = not set
  version @19 :Text;              # release ("rk-v0.3.0") or dev describe ("v0.2.1+3.g7caed93c0a1b+dirty")
  cameraMapSha256 @20 :Text;      # SHA-256 of vehicle/camera_map.ini (cam0 identity); "" = unreadable
  canConfigSha256 @21 :Text;      # SHA-256 of vehicle/can.toml; "" = none
}

# 5614, RK -> AGX (AGX binds, RK connects) and on rk-recorder's local ipc socket for the HMI, 1 Hz.
struct RecorderStatus {
  recording @0 :Bool;
  elapsedS @1 :UInt32;            # since the current recording started; 0 when not recording
  sessionId @2 :Text;             # "YYYYMMDDTHHMMSSZ" of the recording start, "" when none
  segmentSeq @3 :UInt32;          # segment set being written (0-based within the session)
  bytesWritten @4 :UInt64;        # this session
  usedBytes @5 :UInt64;           # all recordings under the storage root
  quotaBytes @6 :UInt64;
  freeBytes @7 :UInt64;           # free space on the storage filesystem
  streams @8 :List(StreamStat);
  lastError @9 :Text;             # "" = none
  storageRoot @10 :Text;

  struct StreamStat {
    camId @0 :UInt8;              # 255 = no camN role (bench)
    gmslSection @1 :Text;
    fps @2 :Float32;              # frames encoded per second over the last period
    kbps @3 :UInt32;              # encoded bitrate over the last period
    framesEncoded @4 :UInt64;     # this session
    dropped @5 :UInt64;           # this session: frames not encoded (queue full, encoder error)
    encodeP99Us @6 :UInt32;       # put_frame -> packet, last period
  }
}

# 5613, RK -> AGX (AGX binds, RK connects), one per camera file when a segment is closed.
struct SegmentEvent {
  sessionId @0 :Text;
  segmentSeq @1 :UInt32;
  camId @2 :UInt8;                # 255 = no camN role (bench)
  gmslSection @3 :Text;
  path @4 :Text;                  # relative to the storage root
  startCaptureNs @5 :UInt64;      # first frame, CLOCK_MONOTONIC (V4L2 timestamp)
  endCaptureNs @6 :UInt64;        # last frame
  startRealtimeNs @7 :UInt64;     # CLOCK_REALTIME of the first frame (mapped at capture), not PTP
  frames @8 :UInt32;
  bytes @9 :UInt64;
  sha256 @10 :Text;               # of the closed file
  reason @11 :Text;               # "roll" | "stop" | "error"
}

# GNSS fix. AGX -> RK on 5588 (the supervisor's position, when Link C is up) and, with envelope src_board = RK and
# source = rk, the RK's own USB GNSS receiver as a LOCAL display copy (rk-gnss, ipc only, never sent to the AGX,
# never the supervisor's source; the HMI prefers the AGX copy while it is fresh). PROPOSED by the RK side
# (2026-10-02); field names follow openpilot cereal where one exists.
struct GpsLocationData {
  flags @0 :UInt16;               # bit0 = has fix (as hasFix)
  latitude @1 :Float64;           # degrees, WGS84
  longitude @2 :Float64;          # degrees, WGS84
  altitude @3 :Float64;           # m above mean sea level
  speed @4 :Float32;              # m/s over ground
  bearingDeg @5 :Float32;         # course over ground, degrees true; use only when headingValid
  headingValid @6 :Bool;          # bearingDeg is a real course: reported by the receiver while moving >= 0.5 m/s
  hAccM @7 :Float32;              # m, horizontal accuracy (1 sigma); NaN = unknown
  hAccEstimated @8 :Bool;         # true: hAccM = HDOP x 2.5 m because the receiver reports no accuracy (no
                                  # GST/GBS) - an estimate, not a measurement; false: from the receiver
  vAccM @9 :Float32;              # m, vertical accuracy (1 sigma); NaN = unknown
  unixTimestampMillis @10 :Int64; # UTC time of the fix, from the receiver
  source @11 :Source;
  hasFix @12 :Bool;
  satelliteCount @13 :UInt8;      # satellites used in the fix
  hdop @14 :Float32;              # horizontal dilution of precision; NaN = unknown
  fixQuality @15 :UInt8;          # NMEA GGA quality: 0 none, 1 GNSS, 2 DGNSS, 4 RTK fixed, 5 RTK float, 6 dead reckoning
  fixType @16 :UInt8;             # 1 no fix, 2 2D, 3 3D (NMEA GSA)
  receiver @17 :Text;             # e.g. "u-blox GNSS receiver (USB, ttyACM0)"
  enum Source {
    agx @0;                       # the AGX's position (fused / supervisor's)
    rk @1;                        # the RK's own receiver: display copy only
  }
}
```

### 1.3 Envelope (`envelope/SPEC.md`, `dabus_envelope.py`, `envelope.h`, `golden_vectors.txt`)

The envelope is one ZMQ frame: a 32-byte little-endian header followed by the payload. The payload is "a Cap'n Proto message ... unpacked, single segment" (`SPEC.md:3-5`). Concretely it is standard capnp flat-array serialization including the segment table: C++ uses `capnp::messageToFlatArray` (`rk/camd/src/health_pub.cpp:64`) and Python uses `new_message(...).to_bytes()` (`rk/hmi/driveragent_hmi/bus.py:183`).

| off | size | field | value / meaning | source |
|---:|---:|---|---|---|
| 0 | 2 | magic | `0xDA5E` (bytes on wire `5e da`) | `SPEC.md:9`, `dabus_envelope.py:30` |
| 2 | 1 | ver | `1` | `SPEC.md:10`, `.py:31` |
| 3 | 1 | src_board | **1 = AGX**, 2 = RK | `SPEC.md:11`, `.py:32-33`, `envelope.h:16-17` |
| 4 | 2 | type_id | the channel's type_id (= ZMQ port) | `SPEC.md:12` |
| 6 | 2 | flags | bit0 source_is_replay, bit1 time_uncertain, bit2 degraded; others 0 | `SPEC.md:13`, `.py:34-36` |
| 8 | 4 | schema_hash | FNV-1a 32 of the struct's canonical text | `SPEC.md:14` |
| 12 | 4 | seq | per (src_board, type_id) counter, wraps at 2^32 | `SPEC.md:15` |
| 16 | 8 | t_ptp_ns | PTP time of the payload's event; until PTP is up the RK sends CLOCK_REALTIME with time_uncertain | `SPEC.md:16` |
| 24 | 4 | len | payload length | `SPEC.md:17` |
| 28 | 4 | crc32c | CRC-32C (Castagnoli) over bytes 0..27 followed by the payload | `SPEC.md:18` |
| 32 | len | payload | | `SPEC.md:19` |

- **Struct format:** `struct.Struct("<HBBHHIIQI")` covers the first 28 bytes (`dabus_envelope.py:37`).
- **CRC32C:** reflected polynomial `0x82F63B78`, init `0xFFFFFFFF`, final xor `0xFFFFFFFF` (`.py:42-59`). Check value `crc32c(b"123456789") == 0xE3069283` (`.py:158`).
- **FNV-1a 32:** offset `0x811C9DC5`, prime `0x01000193` (`.py:62-66`). Checks: `fnv1a32(b"")=0x811C9DC5`, `fnv1a32(b"a")=0xE40C292C` (`.py:159`).
- **Canonical struct text** (`SPEC.md:24-27`; code `.py:69-93`):
  - Regex `\bstruct\s+<Name>\b[^{]*\{` takes the first match in the file.
  - Brace-depth scan to the matching `}`, skipping `#`-to-end-of-line while counting braces. Nested structs and enums are included.
  - Then `#.*` is removed per line, each line is stripped, empty lines are dropped, and the lines are joined with `\n`. There is no trailing newline.
  - Hash = `fnv1a32(text.encode("utf-8"))` (`.py:96-97`).
  - Example I computed: canonical text of StateEcho = `'struct StateEcho {\nvalid @0 :Bool;\nsourceSeq @1 :UInt32;\nageMs @2 :UInt32;\ndegLevel @3 :UInt8;\nstate @4 :Text;\n}'`.
  - A struct that references another top-level struct (HmiHeartbeat → StateEcho) hashes only the field line `displayedStateEcho @2 :StateEcho;`, not the referenced struct's text. This follows from the code at `.py:69-93`.
- **How to hash a new struct:** `python3 envelope/dabus_envelope.py --schema-hash <capnp_file> <StructName>` prints 8 hex digits (`.py:151-156`). It works on any `.capnp` file, not just message.capnp.
- **Receivers** "drop a frame whose magic, version, length or CRC is wrong, and treat a frame whose schema_hash differs from their own for that type_id as a schema mismatch (not decoded)" (`SPEC.md:21-22`). `unpack()` check order: length ≥ 32 → magic/version → `len == len(payload)` → CRC (`.py:107-120`; C++ `envelope.h:83-100`). Flags are not checked by unpack.
- **Golden vectors** (`golden_vectors.txt:3-6`): the AGX-source vector `agx_source 1 5607 4 0badf00d 42 5 00010203` → `5eda0101e71504000df0ad0b2a000000050000000000000004000000ddfe328300010203`. Header lines 1-2 give the primitive checks. "Regenerating the vectors is a breaking change" (`SPEC.md:32`).

### 1.4 `codegen/generate.py`

- **Inputs:** `bus_registry.yaml` + `schema/message.capnp`. **Outputs:** `generated/cpp/bus_registry.h`, `generated/python/bus_registry.py`, `generated/schema_hashes.txt` (`generate.py:2-6`).
- **Checks** (`:8-10`, `:49-69`):
  - unique channel names and non-zero type ids;
  - a non-pending channel's struct must exist in the schema, and a `pending` one must not;
  - every top-level struct must be on a channel or listed as nested.
- **Hashes:** `env.schema_hash(schema_text, s)` for every top-level struct (`:71`), found by `top_level_structs()` (`:32-40`).
- **C++ constant naming:** `kSchemaHash<Struct>` and `kType<CamelCase(channel name)>` (`:76-82`).
- **To add an AGX struct:**
  1. Add it to message.capnp.
  2. Change its registry status from `pending` to `proposed`. Leaving it `pending` fails the check (`:62-63`).
  3. Bump `version`, run `generate.py`, and commit `generated/` (`rk/proto/README.md:29-37, 41`).

### 1.5 `generated/python/bus_registry.py` (full content)

`VERSION = 1`. `SCHEMA_HASH`:

| struct | hash |
|---|---|
| CameraHealth | 0xdea3299f |
| StateEcho | 0x87155568 |
| HmiHeartbeat | 0x624a6bf4 |
| EngageRequest | 0xb0f4e8f5 |
| DisengageRequest | 0x9184bd31 |
| HmiRequest | 0xd40a56c0 |
| BoardHelloRk | 0x95ffc373 |
| RecorderStatus | 0xef91a6d6 |
| SegmentEvent | 0x5e37be9f |
| GpsLocationData | 0x481b9320 |

Source: `rk/proto/generated/python/bus_registry.py:3-14`. `CHANNELS` holds the 16 registry rows with type_id, struct, from, to and status (`:15-32`). The C++ header `kBusRegistryVersion = 1` is at `generated/cpp/bus_registry.h:5`.

### 1.6 CHANGELOG

- **unreleased:** GpsLocationData proposed by the RK side; channel gps 5588 moved pending → proposed (`rk/proto/CHANGELOG.md:3-7`).
- **registry version 1, 2026-10-01:** repo created from the RK repo; RK structs proposed, AGX channels pending; envelope v1 with 4 golden vectors; BoardHelloRk @16-@21 (`:9-13`).

---

## 2. AGX→RK channels the HMI subscribes to today

### 2.1 `rk/config/rk.toml` `[hmi.channels.*]`

`agx_host = "10.42.0.1"` (`rk.toml:152`). `schemas = ["../proto/schema/message.capnp"]` (`:156`).

| channel | port | struct | max_age_ms | extra | line |
|---|---|---|---|---|---|
| autopilot_state | 5607 | AutopilotState | 500 | | :160-163 |
| arbiter_state | 0 | ArbiterState | 500 | "publisher and port not defined yet" | :165-168 |
| car_state | 5592 | CarState | 500 | | :170-173 |
| gps | 5588 | GpsLocationData | 2000 | | :175-178 |
| gps_rk | 5588 | GpsLocationData | 2000 | endpoint ipc gnss, src "rk" | :180-185 |
| board_hello_agx | 5612 | BoardHelloAgx | 3000 | | :187-190 |
| bev_frame | 8010 | BevFrame | 300 | | :192-195 |
| driver_guard | 8014 | DriverGuardResult | 300 | | :197-200 |
| recorder_status | 5614 | RecorderStatus | 2000 | ipc, src "rk" | :202-207 |
| ptp | 0 | PtpStatus | 2000 | local | :209-212 |

Publishers: heartbeat 5595, engage 5608, disengage 5609, request 5604 (which also goes to ipc recorder-cmd) (`:215-230`). `heartbeat_hz = 10`, `engage_hold_ms = 1000` (`:233-234`).

**Effective today:** only `gps` (5588) gets a TCP SUB to the AGX. Channels whose struct is not in the loaded schema get no socket at all ("no schema for …", `bus.py:103-104`). That covers 5607, 5592, 5612, 8010 and 8014.

**rk-logger** separately connects a SUB to every channel with port ≠ 0 and no `endpoint`: 5607, 5592, 5588, 5612, 8010, 8014 (`rk/logger/rk_logger.py:145-155`; `subscribe_agx = true` at `rk.toml:126`). It does this regardless of schema and records raw envelopes.

### 2.2 `rk/hmi/driveragent_hmi/bus.py`

- **Sockets:** every socket uses `connect()`, never bind (`:5-7`). SUB with `SUBSCRIBE ""`, `RCVHWM 16`, `LINGER 0`, connected to `tcp://{agx_host}:{port}` (`:107-112`). PUBs use `SNDHWM 16`, `LINGER 0`, `IMMEDIATE 1` (`:122-126`).
- **Schema loading:** each file in `schemas` is loaded with pycapnp. A struct is registered if `f"struct {name}" in text`, with hash `env.schema_hash(text, name)` (`:86-96`).
- **Validation order in `_accept`** (`:146-170`):
  1. `env.unpack` (length, magic/version, len, CRC).
  2. `src_board == ch.src` (AGX = 1 unless `src = "rk"`), `type_id == port`, `schema_hash == ch.schema_hash`.
  3. capnp decode (`from_bytes`).
  4. Only then store the value, `seq`, and `t_rx` (monotonic).
- **Unknown or mismatched schema hash:** `rejected += 1`, logged only for the first 3 rejects (`bus_reject ... schema=xxxxxxxx`), message dropped, channel stays stale (`:154-159`).
- **Flags:** not checked on receive (no flags use in `rk/hmi/driveragent_hmi/` except publish, `bus.py:184`).
- **Freshness:** `fresh()` = newest valid message age ≤ max_age, otherwise None and widgets show "—" (`:60-64`, `:172-175`). `poll()` drains at most 32 messages per channel per frame and keeps the newest (`:134-144`).
- **RK publish:** flags = time_uncertain, `t_ptp_ns = time.time_ns()`, src = RK (`:178-192`).

### 2.3 What the HMI reads from AGX structs (placeholder field names)

"field names (`vEgo`, `gear`, `state`, `degLevel`, `countdownMs`, `reasonCode`, ...) are placeholders to check against message.capnp when it lands" (`views.py:4-7`).

- **CarState:** `vEgo` (m/s → km/h) and `gear` (`views.py:107, 141-142`).
- **AutopilotState:** `state`, `degLevel`, `countdownMs`, `reasonCode` (`views.py:108-116`). The envelope `seq` is echoed in `StateEcho.sourceSeq` (`app.py:211-216`).
- **ArbiterState:** `state` lower-cased == "armed" enables ENGAGE (`views.py:149-150`).
- **Status chips** AGX (board_hello_agx), MCU and PTP read an optional `degraded` field. That is a payload field, not the envelope flag (`views.py:118-123, 144`).
- **Perception:** `perception = bus.fresh("bev_frame") is not None or bus.fresh("driver_guard") is not None` (`views.py:151`). It only switches the "NO PERCEPTION" chip; nothing is drawn from it.
- **Reason codes** the hand-over card knows (`rk/config/hmi.toml:55-67`): RK_LOST, HMI_LOST, LINK_C_LOST, GPS_HACC, TIME_DEGRADED, MODEL_LATENCY, CAM0_STALE, MODEL_INVALID, ENGINE_HASH, NO_VALID_PATH, GPS_LOST, CARSTATE_INVALID, RECORDER_FAIL.
- **Maintenance gate:** AutopilotState human states `{"human","disengaged","manual","off"}` (`screens/maintenance.py:52, 72`).

### 2.4 Widgets for detections, trajectories, BevFrame, DriverGuard and overlays: none implemented

- **World:** "Lane lines / objects from BevFrame and DriverGuardResult go here once message.capnp exists." (`screens/world.py:59`). Vehicle frame: x forward, y left, z up, origin at the rear-axle centre on the ground (`world.py:6-7`).
- **Cameras BEV:** "No schema on the board yet ... the drawing hook goes here with message.capnp" (`screens/cameras.py:280-292`). "No IPM is computed on the RK" (`:8-9`).
- **Hero overlay toggle** ("Overlay: lanes + masks") only shows the chip "NO PERCEPTION · overlay needs the AGX" (`cameras.py:238-245`). `widgets.tile()` has an `overlay` callback hook (`widgets.py:198-208`), but no caller passes one. `grep "overlay="` finds only the parameter definition (`cameras.py:67`).

### 2.5 How the HMI maps the camera image (relevant to box coordinates)

- **Texture:** hmi-video imports RAW UYVY 1920×1080 DMA-BUFs and renders each camera into an RGBA texture of `tex_w × tex_h` = **1280×720** (`app.py:175` `HmiVideo(a.lib, socket_path, 1280, 720, 150.0)`; `rk/hmi-video/hmi_video.h:3-7, 44-47`). This is the whole field of view; no crop happens on the RK.
- **Tile placement:** `tile_video()` "fit" letterboxes (scale = min, centred). "fill" crops the centre (`widgets.py:173-195`). The default is `tile_fit = "fit"` (`hmi.toml:14`).
- **Existing precedent for drawing on a camera tile:** the maintenance overlay projects into **capture pixels** (cameras.toml `image_width/height` = 1920×1080) and scales with `sx, sy = r.width / c.width, r.height / c.height` onto a 16:9 tile (`screens/maintenance.py:396, 460-473, 485`).
- **Camera model conventions:** cameras.toml K/distortion at capture size; radtan or kannala_brandt; yaw/pitch/roll applied Z-Y-X; yaw = pitch = roll = 0 looks along +x with image right = −y and image down = −z (`rk/config/cameras.toml:11-32`; `geometry.py:3-10`).

### 2.6 `rk/hmi/tests/agx_test.capnp` (verbatim, test-only)

```capnp
@0xf42f56d7f4bc69b7;
# TEST-ONLY schema for bench tests of the HMI (hand-over overlay). NOT the AGX's message.capnp: the real
# AutopilotState comes from the repo's message/message.capnp; field names here are the HMI's placeholder
# accessors (driveragent_hmi/views.py) and must be reconciled when message.capnp lands.
struct AutopilotState {
  state @0 :Text;
  degLevel @1 :UInt8;         # 0 none, 1..3 = D1..D3
  countdownMs @2 :UInt32;     # hand-over countdown at send time
  reasonCode @3 :Text;
}
```

Source: `rk/hmi/tests/agx_test.capnp:1-10`. It is loaded by the HMI only via `--schema` (`app.py:132-133, 158`).

### 2.7 `rk/hmi/tools/agx_standin.py`: sends nothing

It is a receive-only AGX stand-in. It **binds SUB** sockets on `--host` (default 127.0.0.1) for 5595 HmiHeartbeat, 5608 EngageRequest, 5609 DisengageRequest, 5604 HmiRequest and 5611 BoardHelloRk (`agx_standin.py:26-27, 42-47`).

- **Validation:** unpack, then `src_board == SRC_RK`, `type_id == port`, `schema_hash == env.schema_hash(text, struct)`, then decode (`:60-71`).
- **Logging:** echo changes, BoardHello calibration changes, and other messages with seq and flags (`:73-92`).
- **Exit:** 0 if no invalid message (`:102`).

The tool that does send is **`rk/hmi/tools/agx_scenario.py`**:
- Binds **PUB** on `--host:--port` (default 127.0.0.1:5607) (`:45-46, 61-62`).
- Sends **AutopilotState from the TEST schema** at **10 Hz** (`sleep(0.1)`, `:82`) with `flags = FLAG_TIME_UNCERTAIN`, `src = SRC_AGX`, `t = time.time_ns()`, seq incrementing (`:79-81`).
- Fields sent: `state`, `degLevel`, `reasonCode`, and `countdownMs` when the phase has one (`:76-78`).
- Timeline at `:36-44`; gate-test variant at `:46-49`.

---

## 3. Video to the AGX (FrameLink)

**Is FrameLink TX implemented at rk-v0.4.0? No.**
- `grep -i framelink` finds only comments: `rk/config/rk.toml:60`, `rk/camd/src/protocol.h:5`, `rk/camd/src/camera.h:2`, `rk/camd/tests/test_main.cpp:117`, `rk/ops/etc/sysctl-driveragent.conf:7`, plus docs.
- No UDP socket code exists: `grep SOCK_DGRAM|sendto|sendmmsg` finds only sd_notify (`rk/common/sd_notify.h:26,29`, `rk/common/sdnotify.py:16-17`).
- STATUS: "FrameLink TX deferred by Tony until after the HMI" (`rk/docs/STATUS.md:291`).

**Any other video sender?** None. `grep 'udpsink|rtph26|rtsp|mpph265enc|6000'` over `rk/` (excluding m0_raw) hits only BRINGUP_REPORT prose about `mpph265enc` and `udpsink` being installed (`BRINGUP_REPORT.md:203, 1235-1236, 1595`), `STATUS.md:184`, and unrelated numbers (`rk.toml:25`, `camd_consumer.cpp:268,290`, `config.cpp:361-368`). There is no RTP, RTSP or GStreamer sender. The recorder writes H.265 fMP4 to local disk only (`STATUS.md:505-511`).

**FrameLink spec (the only definition is the kickoff, `RK3588_AGENT_KICKOFF.md:86`):**
- **Header (40 B, little-endian):** `magic u32, ver u8, cam u8, fmt u8, health u8, seq u32, t_capture_ptp_ns u64, w u16, h u16, stride u16, exposure_us u16, source u8 (1=LIVE), reserved[3], payload_crc32c u32, header_crc32c u32`, then the payload. The field sizes sum to 40.
- **Magic value: NOT DEFINED.** I searched the kickoff, STATUS, BRINGUP_REPORT and rk/camd. The local DMA-BUF protocol magic `0x44434b52 "RKCD"` (`protocol.h:31`) is a different protocol.
- **fmt codes: NOT DEFINED** anywhere. The local protocol uses fourcc `'NV12'` and `'UYVY'` (`protocol.h:79`).
- **health u8 codes: NOT DEFINED.**
- **Fragment header:** "16 B fragment header" only. **Its layout is NOT DEFINED** anywhere (kickoff `:86`; BRINGUP `:783`, "each fragment = 16 B fragment header + data chunk, sent as one UDP/IPv4 datagram").
- **CRC32C:** payload_crc32c and header_crc32c. The coverage of header_crc32c is not specified. The polynomial is presumably the same as the envelope's, but the spec does not say so.
- **Ports:** UDP cam0 → 6000, cam1-5 → 6001-6005 (kickoff `:86, :135`).
- **MTU and fragment size:** 8,896 B fragment payload at MTU 9000, fallback 1,472 B at MTU 1500 (kickoff `:86`). BRINGUP corrects the fallback: 1,472 + 16 overflows MTU 1500, so the proposed data chunk is **1,456 B** (1,472 B UDP payload), and "AGX receiver must use the same numbers" (`BRINGUP_REPORT.md:1593`; gap row `:1631`). This is not yet agreed (question 15, `:1711`).
- **Bandwidth at MTU 9000:** 6 cams = 841.4 Mb/s (84.1 %); cam0 alone = 334.9 Mb/s (`BRINGUP_REPORT.md:782-800`).
- **Scaled sizes:** `[cam.cam0]` 1280×720 `scaled = true`; `[cam.cam1..cam5]` 704×396 `scaled = false`; `[cam.bench]` 1280×720 (`rk/config/rk.toml:62-97`). Kickoff M1: "cam0 → 1280×720, cam1–5 → 704×396" (`:85`).
- **Scaling is a full-frame resize with no crop:** RGA `srect{0,0,s.w,s.h}` → `drect{0,0,d.w,d.h}` (`rk/camd/src/rga_scaler.cpp:89-90`). So 1920×1080 → 1280×720 is exactly ÷1.5.
- **NV12 layout:** `stride = width`, `uv_offset = stride*height`, `size = 1.5*uv_offset` (`rga_scaler.cpp:35-43`). Input is UYVY 1920×1080 at 30 fps (`rk.toml:44-48`).
- **Colour:** "The RK side does no YUV->RGB conversion ... matrix/range below are the DECLARED encoding ... the single YUV->RGB conversion lives in the consumer (hmi-video shader, AGX pre-processing). BT.601 limited is the default until the Sensing camera datasheet says otherwise (UNVERIFIED)." `matrix = "bt601"`, `range = "limited"` (`rk.toml:50-57`). Enums: `Matrix{Bt601=1,Bt709=2}`, `Range{Limited=1,Full=2}` (`protocol.h:67-68`).
- **Demand-driven cameras:**
  - "cam0 always on; cam1–5 demand-driven (off by default, enabled by an HmiRequest/manifest flag) but always available to the recorder" (kickoff `:86`).
  - "cam1-5 only when a surround model is selected (static here; runtime switch via HmiRequest later)" (`rk.toml:60-61`).
  - The only runtime hook is `HmiRequest.kind = selectModel` with `arg` = model name (`message.capnp:79-92`). No code acts on it on the RK.
- **Camera roles:**
  - cam0 = FRONT = `gmsl_des29_linkA` (/dev/video0, port CAM1, 120° rectilinear, CONFIRMED) (`rk/boards/rk3588-da01/vehicle/camera_map.ini:284-287, 120-138`).
  - cam1-cam5 are unassigned/UNCONFIRMED (`:289-312`). The other cameras are captured unlabelled (labels `fisheye-190`, `video11..14`) and are "never used as model inputs" (`camera_map.ini:14-15`).
  - rk-camd refuses cam0 unless role = front and lens = rectilinear (`STATUS.md:100-101`).
- **Frame timing:**
  - V4L2 timestamp is CLOCK_MONOTONIC, flags MONOTONIC/EOF. About 20.8 ms constant from timestamp to dequeue suggests start-of-frame; this is unresolved (`STATUS.md:243-245`).
  - The fisheye has `capture_ts_offset_us = -12991` (documented, not applied) (`boards/rk3588-da01/vehicle/cameras.toml:66`).
  - The two deserializers' FSYNC phases are not locked (`STATUS.md:280-285`).
- **Socket buffers:** `net.core.rmem_max = wmem_max = 8388608` (`rk/ops/etc/sysctl-driveragent.conf:7-9`).

---

## 4. Status and health

- **CameraHealth (5572):** struct in §1.2. Publisher `rk/camd/src/health_pub.cpp`:
  - PUB connects to `tcp://10.42.0.1:5572` (`rk.toml:42`) with HWM 16, LINGER 0, IMMEDIATE 1 (`:25-37`).
  - `drops = no_free_output + lend_skips`, `exposureUs = 0`, `fps = fps_x100/100`, `scaledP99Us = rga_p99_us` (`:51-63`).
  - Envelope: src RK, `flags = time_uncertain`, plus **degraded when the link is not Live or the camera is unlabelled (cam 255)**; `t_ptp_ns = CLOCK_REALTIME` (`:67-77`).
- **BoardHelloRk (5611):** struct in §1.2. Publisher `rk/hello/rk_hello.py`:
  - 1 Hz, PUB connects with IMMEDIATE, SNDHWM 4 (`:141-145`).
  - `registryHash` = SHA-256 over the concatenated bytes of `../proto/schema/message.capnp` + `../proto/bus_registry.yaml` (`rk_hello.py:126-129`; `rk.toml:148`).
  - `calibrationSha256` = SHA-256 of the exact cameras.toml bytes, re-read every message (`:93-103, 184`).
  - `version = gitSha`, `powerW = NaN`; `recorderAlive` = RecorderStatus within 3 s (`:183, 189-198`).
  - Flags time_uncertain (`:199`).
- **RecorderStatus (5614) / SegmentEvent (5613):** structs in §1.2. They connect to the AGX (`rk.toml:115-116`).
- **BoardHello-AGX (5612): pending, no struct.** What the RK expects:
  - The HMI "AGX" chip goes green or amber from freshness (3 s) and an optional `degraded` field (`views.py:118-123,144`).
  - Settings page "Safety / AGX": "Read-only view of the AGX supervisor's configuration and BoardHello-AGX: waits for their schemas" (`screens/settings.py:50-51`).
  - Design wants the dock info line to show model, cal, reg and agx temperature; the model name and AGX/SSD temperatures are "unavailable" today (`STATUS.md:442-443`).
  - The design mock (`rk/docs/design/1 · Drive (LIVE, engaged)@2x.png`, an image, not code) shows "model: yolopx-v2 · cal 7f3a · reg 91c0 · rk 41 °C · agx 52 °C · ssd 44 °C", a "PTP 3 µs" chip and "AUTOPILOT · ENGAGED D0 · cap 25".
- **HTTP status API: none.** `grep flask|fastapi|aiohttp|http.server|/api/|HTTPServer|http://` over `rk/` finds only build/font URLs and rk-updater's `urllib` download from GCS (`rk/updater/rk_updater.py:53-54, 126`). Health check is over ZMQ: `rk/ops/health_check.py:4-10` listens on rk-logger's local monitor endpoint. **The RK reads nothing from the AGX over HTTP.**

---

## 5. Network

- **Link C** (kickoff `:139`): point-to-point 1 GbE, static 10.42.0.1/30 (AGX) / 10.42.0.2/30 (RK), MTU 9000 target with 1500 fallback.
  - Planned `mqprio`: TC0 = PTP + ZMQ + heartbeat, TC1 = FrameLink.
  - **Not possible on this kernel:** `CONFIG_NET_SCHED` is not set and eth0 has 1 TX queue. The interim is userspace pacing plus `SO_PRIORITY` (`BRINGUP_REPORT.md:1590`).
- **M3:** AGX is the PTP grandmaster on `eno1` (10.42.0.1/30) (kickoff `:100`). On the RK, Link C must be `eth0` (GMAC0, the only PHC `/dev/ptp0`, HW timestamps for L2 and UDPv4 PTP) (`BRINGUP_REPORT.md:592-593, 1627`). eth0 MTU range is 46-9000 and is currently at 1500; jumbo frames are unverified (`:595`).
- **Open questions to the AGX side:** "will `eno1` run MTU 9000? PTP transport L2 or UDPv4? Agree the MTU 1500 chunk of 1,456 B? Which Cap'n Proto and pyzmq versions does the AGX use (board offers capnp 0.8.0 from apt, pycapnp 2.2.4 wheels)?" (`BRINGUP_REPORT.md:1711`).
- **agx_host:** `"10.42.0.1"` in `rk/config/rk.toml:152`, `rk/boards/_template/board.toml:23` and `rk/boards/rk3588-da01/board.toml:24`. All CameraHealth, HMI, hello, recorder and logger sockets connect to it.
- **nftables:** not implemented. The kernel has no NF_TABLES, and nftables was dropped from the apt set (`BRINGUP_REPORT.md:1591`; `rk/setup/owner_apt.sh:2`). No nft, ptp4l or phc2sys config exists in `rk/ops` (grep finds none).
- **time_uncertain:** "Holdover > 60 s → set `time_uncertain` (flags bit 1) on every RK-originated frame and message" (kickoff `:101`). Today every RK message sets it, because there is no PTP (`bus.py:184`, `health_pub.cpp:72`, `rk_hello.py:199`; STATUS `:98, 287, 341`).
- **Timeouts the AGX applies** (kickoff `:141`):
  - HmiHeartbeat 500 ms → D1.
  - CameraHealth 2.5 s → camera INVALID.
  - FrameLink 150 ms or seq gap ≥ 3 → camera INVALID (cam0 INVALID → D2, controlled stop after 2 s).
  - BoardHello 3 s → RK_LOST.
  - `time_uncertain` → frames treated INVALID.
  - Note the registry's max_age for hmi_heartbeat is 300 ms (`bus_registry.yaml:18`), which differs from the kickoff's 500 ms.
- **Measured RK behaviour:** HmiHeartbeat median 100.0 ms, max 100.5 ms; after SIGSTOP none arrive (`STATUS.md:338-341`).

---

## 6. `rk/docs/STATUS.md` state

- **Current milestone header:** "M4 — HMI (started 2026-09-29)" (`:6`).
- **Done on board DA01 (rk3588-da01, board_id ami-01):**
  - M1 rk-camd accepted in bench mode; the 1 h soak passed (`:41, 273-291`).
  - Camera map CONFIRMED and cam0 published (`:306-311, 328-329`).
  - M4 HMI screens, bus, and publishers verified against the stand-in (`:327-341`).
  - M2 recorder (`:505-529`); M8 systemd ops (`:562-600`).
  - Settings, releases and rk-updater (`:608-688`).
  - Shared proto submodule (`:700-709`); rk-v0.3.0 tagged (`:710`); NVMe in service (`:719-726`).
  - GNSS and map (`:728-776`).
  - STATUS does not mention rk-v0.4.0 itself.
- **Deferred:**
  - **FrameLink TX** (`:291`).
  - **Link C / M3 PTP** "when the AGX is on the bench" (`:44-47`).
  - AGX-fed widgets "show NO DATA until Link C exists" (`:46-47`).
  - The labelled run and merging AGX structs (`:289-291`).
  - The maintenance gate from vehicle state is a TODO (`:698-699`).
- **Waiting on Tony:**
  - `owner_hmi_dev.sh`, the touch panel, the LAN IP (`:34-39`).
  - `owner_services.sh` / `owner_remote_bind.sh`, repo/deploy key, the GNSS check (`:111-119`).
  - The extrinsics_measured semantics (`:406-408`).
  - networkd-wait-online (`:583-584`).
  - Pull-the-plug test, cold-boot and re-soak items (`:577, 600`).
  - Hand-over texts are drafts for Tony's review (`hmi.toml:53`).
  - BRINGUP §16 questions (`BRINGUP_REPORT.md:1690-1716`).
- **"Decision needed" on cam0 size** (`STATUS.md:239-242`): "cam0 is 1280x720 (more work than the 704x396 bench size) and FrameLink will add load. Options: (a) reserve RGA3 core0 for cam0 and run cam1–5 on core1 ...; (b) keep both cores shared and accept p99 of about 3.6 ms + margin; (c) measure again with cam0 at 1280x720 once the map is CONFIRMED."
  - **Resolved: (b) shared cores** (`:52, :118`).
  - Measured afterwards: cam0 stand-in 1280×720 RGA p50 1.59 ms, p99 ~1.69 ms (`:278`).

---

## 7. What the AGX must publish for the HMI to draw boxes on camera tiles

**Nothing in the repo defines it.** Facts that constrain the design:

1. **No struct exists.** BevFrame (8010) and DriverGuardResult (8014) are `pending`, with no fields anywhere in the repo (`bus_registry.yaml:42-45`; `message.capnp:7-11`). There is no detection or box struct, no model-overlay channel, and no frame-identity field in any defined struct.
2. **The HMI's only expected inputs:**
   - "BevFrame / DriverGuardResult" for World (lanes, objects) (`world.py:1-3, 59`).
   - The cameras overlay "lanes + masks ... from the AGX's perception" (`cameras.py:6-7, 239`).
   - "the RK computes nothing" / "No IPM is computed on the RK" (`cameras.py:7-9`).
   - Kickoff M4: port `bev_widget.py` "draws from typed `BevFrame` 8010, single Y convention" (`RK3588_AGENT_KICKOFF.md:107`).
   - Design mocks (images, not code) show boxes labelled "CAR · 14 m" and "PED · 9 m", lane lines, "LANE KEEP" and "1 VRU" badges, "BevFrame 20 Hz · age 38 ms", and a "cam0 · FRONT · 1280×720 ... lanes + masks" tile (`rk/docs/design/1 · Drive (LIVE, engaged)@2x.png`, `2b · Cameras v2 · hero + filmstrip@2x.png`).
3. **Image coordinate frame on the RK:**
   - The tile shows the full 1920×1080 capture scaled to a 1280×720 texture, then fitted 16:9 in the tile (`app.py:175`, `widgets.py:173-195`).
   - cam0's FrameLink image is the same field of view, resized to 1280×720 with no crop (`rga_scaler.cpp:89-90`). So AGX pixel coords at 1280×720 map to capture pixels ×1.5.
   - The existing on-tile overlay code works in capture pixels (1920×1080, cameras.toml `image_width/height`) and scales by tile/capture (`maintenance.py:396, 473, 485`).
   - The 3D/world convention is the vehicle frame: x fwd, y left, z up, origin rear-axle centre on the ground (`world.py:6-7`, `cameras.toml:11-15`).
4. **Frame identity available on the RK side** (none of it on any bus message):
   - Local per-frame `v4l2_sequence`, `frame_no`, `t_capture_ns` (CLOCK_MONOTONIC) (`protocol.h:99-109`).
   - The FrameLink header would carry `seq` and `t_capture_ptp_ns` (kickoff `:86`).
   - BoardHelloRk carries `calibrationSha256` and `cameraMapSha256` for calibration identity (`message.capnp:100, 119`).
   - A per-frame identity for matching overlays to displayed frames would have to be added to the new AGX struct. The HMI displays the RK's own RAW frames, not FrameLink frames.
5. **Gating rules a new AGX struct must pass to be drawn:**
   - It must be in `rk/proto/schema/message.capnp`, and the RK must bump its submodule. The HMI loads only that file (`rk.toml:156`; `bus.py:86-96`).
   - Its registry status must become proposed or agreed (`generate.py:62-63`).
   - Envelope: `src_board = 1`, `type_id = port` (8010 or 8014), matching schema_hash, valid CRC. Arrival within max_age 300 ms (`rk.toml:192-200`).
   - The AGX must **bind** a PUB on 10.42.0.1:<port>.
   - The HMI also needs new drawing code; the hooks are empty (`world.py:59`, `cameras.py:280-292`, `widgets.py:207`).