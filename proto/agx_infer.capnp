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
