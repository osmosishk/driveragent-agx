@0xde51d8c1e15898c9;   # Unique schema ID (randomly chosen)

struct Message {
  content   @0 :Text;   # e.g. message text content
  timestamp @1 :UInt64; # e.g. a timestamp or counter
}

struct GpsLocationData {
  timestamp @0 :UInt64;    # Time in milliseconds since epoch (UTC)
  latitude  @1 :Float64;   # Latitude in decimal degrees
  longitude @2 :Float64;   # Longitude in decimal degrees
  altitude  @3 :Float64;   # Altitude in meters (AMSL)
  speed     @4 :Float64;   # Speed in m/s
  accuracy  @5 :Float64;   # Estimated horizontal accuracy (meters)
  bearing   @6 :Float64;   # Add this line
}

struct ZoomAndPanCommand {
  zoomDelta    @0 : Int8;    # +1 (zoom in), -1 (zoom out), 0 for no zoom change
  panOffsetX   @1 : Int32;   # Pan offset in horizontal pixels
  panOffsetY   @2 : Int32;   # Pan offset in vertical pixels
  styleMode    @3 : UInt8;   # 0=no change (default), 1=light, 2=dark
  renderWidth  @4 : UInt16;  # Desired viewport width in pixels (0 = no change)
  renderHeight @5 : UInt16;  # Desired viewport height in pixels (0 = no change)
}

struct DaemonStatus {
  timestamp @0  :UInt64; 
  name      @1  :Text;   # e.g. "uploader", "deleter"
  running   @2  :Bool;   # true if alive / started okay
  errorMsg  @3  :Text;   # non-empty if something went wrong
}

struct DaemonMessage {
  timestamp @0  :UInt64;    # ms since epoch, or however you like
  name      @1  :Text;   # e.g. "uploader", "deleter"
  message   @2  :Text;   # true if alive / started okay
}
 
struct ControlMessage {
  timestamp           @0  :UInt64;      # ms since epoch
  steerAngleDeg       @1  :Float32;     # Steering Wheel Angle       
  steerRateDeg        @2  :Float32;     # desired angular rate (°/s)
  steerTorque         @3  :Float32;     # desired torque in Nm
  accelPedal          @4  :Float32;     # gas pedal [%]
  brakePedal          @5  :Float32;     # brake pedal [%]
  gear                @6  :Text;        # gear mode: "D", "N", "R", or "" for no change
  free                @7  :Int16;       # -1 = no change, 0 = computer control, 1 = human control
}

struct RemoteControlMessage {
  timestamp           @0  :UInt64;      # ms since epoch
  steerAngleDeg       @1  :Float32;     # Steering Wheel Angle       
  steerRateDeg        @2  :Float32;     # desired angular rate (°/s)
  steerTorque         @3  :Float32;     # desired torque in Nm
  accelPedal          @4  :Float32;     # gas pedal [%]
  brakePedal          @5  :Float32;     # brake pedal [%]
  gear                @6  :Text;        # gear mode: "D", "N", "R", or "" for no change
  free                @7  :Int16;       # -1 = no change, 0 = computer control, 1 = human control
}

struct SystemMonitorMessage {
    timestamp @0 : UInt64;       # e.g. current time in ms
    cpuusage  @1 : Float32;  #
    gpuusage  @2 : UInt8;     # vel (0–255)
   
}

struct CameraFrameInfo {
    cameraId     @0 : UInt32;     # Camera identifier (0-5 for 6 cameras)
    frameNumber  @1 : UInt64;     # Sequential frame number for this camera
    timestamp    @2 : UInt64;     # Timestamp in nanoseconds since epoch
    width        @3 : UInt32;     # Frame width in pixels
    height       @4 : UInt32;     # Frame height in pixels
    format       @5 : Text;       # Pixel format (e.g., "RGBA", "UYVY")
    shmPath      @6 : Text;       # Shared memory path for this camera
    
    # Optional: Additional metadata
    fps          @7 : Float32;    # Current FPS
    dropCount    @8 : UInt64;     # Number of dropped frames
    latencyNs    @9 : UInt64;     # Processing latency in nanoseconds
}

struct CameraControlCommand {
    timestamp    @0 : UInt64;     # Timestamp in ms since epoch
    command      @1 : Text;       # Command: "start", "stop", "restart", "status"
    cameraId     @2 : Int32;      # Camera ID (-1 for all cameras, 0-5 for specific camera)
    numCameras   @3 : UInt32;     # Number of cameras to start (used with "start" command)
    forceCleanup @4 : Bool;       # Force cleanup of shared memory before start
}

struct Waypoint {
  lat @0 :Float64;
  lon @1 :Float64;
  index @2 :UInt32;
}

struct TrackingCommand {
  timestamp @0 :UInt64;
  recordingEnabled @1 :Bool;
  clearRecording @2 :Bool;
  clearWaypoints @3 :Bool;
  waypoints @4 :List(Waypoint);
}


struct CarState {
  timestamp  @0 :UInt64;  # ms since epoch (UTC)
  speedKph   @1 :Float32; # vehicle speed in km/h
  odometerKm @2 :Float64; # total odometer reading in km
  gear       @3 :Text;    # "N", "D", "R", "D/R", etc.
  handbrake  @4 :Bool;    # handbrake status.
  brake      @5 :UInt8;   # brake
  

}

struct CarDataMessage {
  timestamp   @0 :UInt64;
  free        @1 :UInt8;
  isRadio     @2 :UInt8;
  steerAngle  @3 :Int16;
  accel       @4 :UInt8;
  brake       @5 :UInt8;
  mode        @6 :UInt8;
  dash        @7 :UInt8;
}

struct SelfDrivingStatus {
  timestamp       @0 :UInt64;   # ms since epoch
  enabled         @1 :Bool;     # self-driving mode active
  showGroundTruth @2 :Bool;     # path overlay displayed
}

# Authoritative autopilot state, published by the self-driving supervisor
# (selfdrive/supervisor.py). The UI publishes SelfDrivingStatus as a *request*;
# the supervisor owns the lifecycle and emits AutopilotState as the *authority*.
# control-ami.py gates waypoint following on this and fails safe if it goes
# stale. Heartbeated at ~10 Hz even when disengaged.
struct AutopilotState {
  timestamp   @0 :UInt64;   # ms since epoch — heartbeat, used for staleness
  state       @1 :UInt8;    # 0=DISENGAGED 1=ARMING 2=ENGAGED 3=FAULT
  engaged     @2 :Bool;     # convenience: true iff state==ENGAGED
  reason      @3 :Text;     # "", "path_stale", "driver_override", ...
  activeModel @4 :Text;     # active model name, or ""
}

struct SelfDrivingPrediction {
  content   @0 :Text;   # e.g. message text content
  timestamp @1 :UInt64; # e.g. a timestamp or counter
}

struct WaypointCommand {
  timestamp       @0 :UInt64;
  steerAngleDeg   @1 :Float32;
  desiredSpeedKph @2 :Float32;    # Target speed in km/h
  brakePedal      @3 :Float32;
  gear            @4 :Text;
  free            @5 :Int16;
  desiredCurvature @6 :Float32;
}

struct ClonePathCommand {
  timestamp       @0 :UInt64;
  steerAngle      @1 :Int16;      # Raw steering (-1024 to 1024)
  accel           @2 :UInt8;      # Raw throttle (0-255)
  brake           @3 :UInt8;
  mode            @4 :UInt8;      # 0=NOP, 1=N, 2=D, 3=R
  enabled         @5 :Bool;
  waypointIndex   @6 :UInt32;
  totalWaypoints  @7 :UInt32;
  pathName        @8 :Text;
  desiredSpeedKph @9 :Float32;
}

struct RouteCommand {
  timestamp @0 :UInt64;
  destLat   @1 :Float64;          # Destination latitude
  destLon   @2 :Float64;          # Destination longitude
  action    @3 :Text;             # "start", "stop", "reroute"
}

struct RouteStatus {
  timestamp            @0 :UInt64;
  active               @1 :Bool;          # Navigation active
  distanceRemainingM   @2 :Float64;       # Meters to destination
  currentWaypointIndex @3 :UInt32;        # Progress along route
  totalWaypoints       @4 :UInt32;
  instruction          @5 :Text;          # Current maneuver instruction
  destLat              @6 :Float64;
  destLon              @7 :Float64;
  routeFile            @8 :Text;          # Path to active route JSON
}

# Active route projected into the vehicle (ego) frame:
#   x = forward meters, y = left meters
# Same coordinate convention as plan/ipm2.py centerline_bev so a
# perception-fusion node can compare points directly.
struct RouteGuidance {
  timestamp             @0 :UInt64;       # ms since epoch
  active                @1 :Bool;          # false = no active route; egoPoints is empty
  egoPoints             @2 :List(Point2D); # route points ahead of vehicle, ordered by distance
  bearingToLookaheadDeg @3 :Float32;       # +left / -right relative to vehicle heading
  curvatureLookahead    @4 :Float32;       # 1/m at lookahead (signed, +left)
  distToManeuverM       @5 :Float32;       # 0 if no upcoming maneuver
  maneuverTag           @6 :Text;          # "left", "right", "straight", "uturn", "" if none
  routeProgressFrac     @7 :Float32;       # 0..1 along total route
  headingValid          @8 :Bool;          # false if vehicle heading is stale (low-speed fallback)
  dtcpCommand           @9 :UInt8;         # 0=LEFT, 1=RIGHT, 2=STRAIGHT, 3=LANE_FOLLOW, 4=CHANGE_LEFT, 5=CHANGE_RIGHT (DriverGuard convention)
  distFromRouteM        @10 :Float32;      # haversine from current GPS to closest route waypoint (0 if no route)
  entrancePoint         @11 :Point2D;      # ego-frame (X=fwd, Y=left m) coordinates of the closest route waypoint
}

# ═══════════════════════════════════════════════════════════════
# SparseDrive Model Output Messages
# ═══════════════════════════════════════════════════════════════

struct Point2D {
  x @0 :Float32;
  y @1 :Float32;
}

struct Box2D {
  camId  @0 :UInt8;       # Camera index (0-5)
  xMin   @1 :Float32;     # Bounding box in 1280x720 pixel coords
  yMin   @2 :Float32;
  xMax   @3 :Float32;
  yMax   @4 :Float32;
}

struct SparseDriveDetection {
  classId    @0 :UInt8;      # 0-9 (car, truck, construction_vehicle, bus, trailer, barrier, motorcycle, bicycle, pedestrian, traffic_cone)
  className  @1 :Text;
  score      @2 :Float32;
  x          @3 :Float32;    # 3D position (ego frame, meters)
  y          @4 :Float32;
  z          @5 :Float32;
  length     @6 :Float32;    # dimensions (meters)
  width      @7 :Float32;
  height     @8 :Float32;
  yaw        @9 :Float32;    # orientation (radians)
  vx         @10 :Float32;   # velocity (m/s)
  vy         @11 :Float32;
  vz         @12 :Float32;
  boxes2d    @13 :List(Box2D);  # Projected 2D boxes per camera
}

struct SparseDriveMapElement {
  classId    @0 :UInt8;      # 0-2 (lane_divider, road_boundary, pedestrian_crossing)
  className  @1 :Text;
  score      @2 :Float32;
  points     @3 :List(Point2D);  # 20 BEV points
}

struct SparseDriveTrajectory {
  points @0 :List(Point2D);  # timesteps x 2D
  score  @1 :Float32;
  mode   @2 :UInt8;
}

struct SparseDriveResult {
  timestamp          @0 :UInt64;
  frame              @1 :UInt64;
  # Detections
  detections         @2 :List(SparseDriveDetection);
  # Map elements
  mapElements        @3 :List(SparseDriveMapElement);
  # Planning
  planTrajectory     @4 :List(Point2D);   # 6 timesteps ego plan
  planScore          @5 :Float32;
  planCommand        @6 :UInt8;
  planMode           @7 :UInt8;
  # Agent motion predictions
  motionTrajectories @8 :List(SparseDriveTrajectory);
  # Timing
  backboneMs         @9 :Float32;
  headMs             @10 :Float32;
  totalMs            @11 :Float32;
}

# ═══════════════════════════════════════════════════════════════
# System1 Model Output
# ═══════════════════════════════════════════════════════════════

struct System1Result {
  timestamp     @0 :UInt64;          # ms since epoch
  frame         @1 :UInt64;          # monotonic frame counter
  trajectory    @2 :List(Point2D);   # 6 waypoints in ego frame, meters (x=fwd, y=left)
  headings      @3 :List(Float32);   # 6 headings, radians (0=fwd, +=left)
  egoSpeedKph   @4 :Float32;         # ego speed at inference time
  cmd           @5 :UInt8;           # 0=straight, 1=left, 2=right
  inferenceMs   @6 :Float32;         # end-to-end model latency
  finite        @7 :Bool;            # all outputs are finite
}

# ═══════════════════════════════════════════════════════════════
# Model supervisor control (UI → start.py)
# ═══════════════════════════════════════════════════════════════

struct ModelControl {
  timestamp @0 :UInt64;   # ms since epoch
  action    @1 :Text;     # "start" or "stop"
  modelName @2 :Text;     # registry key, e.g. "system1", "yolopx"
}

# ═══════════════════════════════════════════════════════════════
# DriverGuard Model Output (YOLOPX perception + DTCP planner)
# ═══════════════════════════════════════════════════════════════

struct DriverGuardDetection {
  x1       @0 :Float32;
  y1       @1 :Float32;
  x2       @2 :Float32;
  y2       @3 :Float32;
  conf     @4 :Float32;
  classId  @5 :UInt8;     # 0..9, see CLASS_NAMES in yolopx_postprocess.py
}

struct DriverGuardResult {
  timestamp     @0  :UInt64;          # ms since epoch
  frame         @1  :UInt64;          # monotonic frame counter
  trajectory    @2  :List(Point2D);   # 4 waypoints in ego frame (x=lat_right_m, y=fwd_m)
  throttle      @3  :Float32;         # 0..1
  steer         @4  :Float32;         # -1..1
  brake         @5  :Float32;         # 0..1
  predSpeedMps  @6  :Float32;         # DTCP predicted next-step speed
  egoSpeedMps   @7  :Float32;         # observed ego speed at inference time
  command       @8  :UInt8;           # 0..5 DTCP convention (0=LEFT, 1=RIGHT, 2=STRAIGHT, 3=LANE_FOLLOW, 4=CHANGE_LEFT, 5=CHANGE_RIGHT)
  inferenceMs   @9  :Float32;         # end-to-end (YOLOPX+DTCP) latency
  finite        @10 :Bool;            # all outputs are finite

  # YOLOPX outputs
  daMaskRle     @11 :Data;            # run-length encoded binary drivable-area mask
  llMaskRle     @12 :Data;            # run-length encoded binary lane-line mask
  maskWidth     @13 :UInt16;
  maskHeight    @14 :UInt16;
  detections    @15 :List(DriverGuardDetection);
}

# ═══════════════════════════════════════════════════════════════
# Shadow-mode comparison: DriverGuard model vs human driving.
# Published by eval/comparator.py while the human drives manually and
# the model runs in shadow (the model never controls the car). The UI
# (BEV widget) subscribes to overlay the human path and show live metrics.
#   humanPathEgo is the human's intended path ahead (the arc implied by the
#   current steering angle), standard ego frame: x = forward m, y = left m.
# ═══════════════════════════════════════════════════════════════
struct ComparisonMetrics {
  timestamp      @0  :UInt64;          # ms since epoch — heartbeat
  # instantaneous errors (model minus human, this tick)
  steerErrNorm   @1  :Float32;         # model.steer - human steer, both -1..1
  throttleErr    @2  :Float32;         # model.throttle - human throttle, 0..1
  brakeErr       @3  :Float32;         # model.brake - human brake, 0..1
  speedErrMps    @4  :Float32;         # model.predSpeedMps - human speed
  crossTrackM    @5  :Float32;         # model trajectory vs human realized path
  headingErrDeg  @6  :Float32;         # reserved; 0 if not computed
  # running aggregates over the session
  steerRmse      @7  :Float32;
  throttleRmse   @8  :Float32;
  brakeRmse      @9  :Float32;
  crossTrackRmse @10 :Float32;
  sampleCount    @11 :UInt32;          # samples folded into the aggregates
  dgFresh        @12 :Bool;            # DriverGuard data fresh this tick
  humanFresh     @13 :Bool;            # human (CarData) data fresh this tick
  humanPathEgo   @14 :List(Point2D);   # human intended path ahead, x=fwd y=left m
}