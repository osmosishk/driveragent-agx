# Old DriverAgent stack: read-only research report (old-stack)

I read the code in `/home/tonyho/driveragent` (HEAD `bf78af3`), but I did not run any git command that writes. I did not start any process from the old stack. I ran `ffprobe`, `gst-discoverer-1.0` and `ffmpeg` frame grabs on recordings, and the frame grabs were written only to `/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad/old-stack/`.

Right now nothing from the old stack is running. `ps` found no start.py, camtest, ui or control process, and `/tmp/driveragent.pid` does not exist. Only `/tmp/camsock` exists, and it does not come from the old stack.

---

## 1. Processes and how the stack is started

### start.py (`SERVICES` dict at `/home/tonyho/driveragent/start.py:25-96`)

Each command runs with cwd = the repo root unless a cwd is shown. "restart N" means `manage_with_restart` relaunches it after N seconds (`start.py:117-132`).

| group | command | cwd | restart | ports / IPC (bind unless noted) |
|---|---|---|---|---|
| visionipc | `./camtest -cam 6` (`start.py:27`; N comes from `config.ini:4`) | visionipc | no | shm `/tmp/cam0..5`; PUB 5572 (`camtest.cpp:592`); SUB-connect 5573 (`camtest.cpp:54,525`); daemon connect 5570/5571 (`camtest.cpp:582-585`) |
| message-proxy | `python3 -m message.daemon_proxy` (`start.py:34`) | root | 3 s | XSUB 5570/5571, XPUB 6570/6571 on 127.0.0.1 (`message/daemon_proxy.py:33,37,62,68`) |
| message-proxy | `python3 -m message.gateway` (`start.py:35`) | root | 3 s | 0.0.0.0:5600 data, 0.0.0.0:5601 auth (`message/service_list.yaml:4-6`, `message/gateway.py:129,252`) |
| message-proxy | `python3 -m message.configproxy` (`start.py:36`) | root | 3 s | 0.0.0.0:5610 (`message/configproxy.py:44,48,237-238`) |
| location | `./gpspub` (`start.py:39`) | location | no | 5588 GpsLocationData (`location/gpspub.cpp:478`) |
| location | `./mapgen` (`start.py:40`) | location | no | subscribes 5590/5588/5587 (`location/mapgen.cpp:269,324,380`); writes `/dev/shm/map.png` (`mapgen.cpp:58`) |
| location | `python3 -m location.route_planner --service` (`start.py:41`) | root | no | RouteCommand 5602 → RouteStatus 5603 (`service_list.yaml:38-39`) |
| location | `python3 -m location.path_follower` (`start.py:42`) | root | no | WaypointCommand 5597 (`location/path_follower.py:66,274-275`) |
| plan | `python3 -m plan.route_guidance` (`start.py:49`) | root | no | 5605 (`plan/route_guidance.py:39,227`) |
| plan | `python3 -m plan.fusion` (`start.py:50`) | root | no | 5606 (`plan/fusion.py:49,174`) |
| carstate | `python3 -m carstate.readami --bind --no-print` (`start.py:56-57`) | root | no | reads CAN `can1` (`carstate/readami.py:27,163`); CarState 5592 (`readami.py:34`) |
| selfdrive | `python3 -m selfdrive.supervisor` (`start.py:65-66`) | root | 3 s | AutopilotState 5607 (`selfdrive/supervisor.py:128`) |
| eval | `python3 -m eval.comparator` (`start.py:73-74`) | root | 3 s | 8015 (`eval/comparator.py:54`) |
| control | `python3 control.py` (`start.py:83`) | control | no | **CAN TX**; connects 9000 (`control/control.py:48,178`) |
| control | `python3 -m control.control-ami` (`start.py:84`) | root | no | binds 9000 (`control/control-ami.py:1514`, `control/control_config.ini:29`) |
| control | `python3 publish.py` (`start.py:85`) | control | no | reads CAN; binds 9001 and 5593 (`control/publish.py:27-28,56,69,94`) |
| logger | `python3 -m logger.uploader` (`start.py:89`) | root | 300 s | GCS upload |
| logger | `python3 -m logger.deleter` (`start.py:90`) | root | 300 s | **deletes the oldest 20 % of segments when VIDEO_ROOT > 1 GB** (`logger/deleter.py:31-32,66-85`) |
| ui | `python3 -m ui.ui` (`start.py:94`) | root | no | binds 5594, 5590, 5602, 5595, 5604, 5587 (`ui/newwidgets/data_bus.py:279-296`) and 5573 (`data_bus.py:159,163`) |

Other things start.py does:
- **Valhalla.** `ensure_valhalla()` runs `sg docker -c 'docker start driveragent-valhalla'` (`start.py:200-222`). The container is `restart: unless-stopped` and maps 0.0.0.0:8002→8002 (audit `raw/Container_details...txt`). It is running now.
- **Model supervisor.** A thread subscribes to ModelControl at `tcp://127.0.0.1:5604` (`start.py:109,174-197`). It launches `MODEL_REGISTRY` entries on demand (`start.py:102-106`):
  - `system1` → `python3 /home/tonyho/model/system1/run.py` (PUB `tcp://*:8011`, `model/system1/runner/runner.py:23`)
  - `yolopx` → `bash startmodel.sh` (`startmodel.sh:60-66`, reads `/tmp/cam0`)
  - `driverguard` → `python3 /home/tonyho/model/driverguard/run.py` (PUB `tcp://*:8014`, `model/driverguard/run.py:32`, `runner/runner.py:136-137`)
- **Pidfile.** `/tmp/driveragent.pid` (`start.py:21`). SIGHUP makes start.py re-exec itself (`start.py:336-366`).
- **UI recorders.** The UI spawns these on the record button or on motion over 1 km/h (`ui/ui.py:304-308,393-417`): `logger.encoder_265`, `logger.logger`, `logger.timestamp`. Their logs go to `/tmp/driveragent-recorder-logs` (`ui/ui.py:309`).

### systemd units, scripts and autostart

- **There are no old-stack systemd units.**
  - `grep -l driveragent /etc/systemd/system/*.service` returned nothing (rc=1).
  - A recursive grep over `/etc/systemd`, `/lib/systemd`, `/usr/lib/systemd` and `~/.config/systemd` also found nothing.
  - The audit list of hand-made units (`raw/Custom_systemd_units__created_by_hand_.txt`) contains only NVIDIA, jtop and snap units.
  - There is no user crontab, no rc.local and no autostart entry (`raw/Cron__rc.local__autostart__process_managers.txt`).
  - **For the dashboard:** there is no "old unit" to read state from. Detect the old stack from process/pid/shm state (see below) plus the docker container `driveragent-valhalla`.
- `~/s.sh:4-7`: `cd /home/tonyho/driveragent; python start.py`. This is the manual launcher.
- `~/start-driveragent.sh:4-10`: cd, then `./startup.sh`, then `sleep 5`. The line that starts Python is empty, so it never launches start.py.
- `startup.sh:1-11`: `sudo insmod ko/max9295.ko, ko/max9296.ko, ko/sgx-yuv-gmsl2.ko`, then `v4l2-ctl -d /dev/video0..5 -c sensor_mode=0,trig_pin=0xffff0007`.
- `startupcan.sh:5-7,12-15,44-54`: re-execs itself under sudo, then sets `can0` to 1 Mbit and `can1` to 500 kbit and brings them up. **Do not run.**
- `startmodel.sh:4-66`: YOLOPX venv, `tools/demotext.py --socket /tmp/cam0 --width 1280 --height 720`.

Ways to tell the old stack is running:
- `/tmp/driveragent.pid` (`start.py:21`)
- processes `camtest`, `python3 -m ui.ui`, `control.py`, `control.control-ami`
- sockets `/tmp/cam0..5`
- docker container `driveragent-valhalla`

## 2. Camera capture (visionipc/)

- **Binary.** `visionipc/camtest`, built from `camtest.cpp` (`visionipc/build_camtest.sh:10-18`).
- **Capture path.** It uses GMSL2 through V4L2, not nvargus:
  - pipeline: `v4l2src device=/dev/videoN io-mode=4 ! video/x-raw,format=UYVY,width=1920,height=1080,framerate=30/1 ! nvvidconv [flip-method] ! video/x-raw,format=RGBA,width=1280,height=720,framerate=30/1 ! queue max-size-buffers=5 leaky=downstream ! shmsink socket-path=/tmp/camN shm-size=5*1280*720*4 wait-for-connection=false sync=false` (`camtest.cpp:227,249-259`; constants at `camtest.cpp:31-35`)
  - kernel modules come from `startup.sh:1-3`
  - the sensor is IMX390 according to the doc (`visionipc/doc/skill.md:16`)
- **Numbering.** camN = `/dev/videoN` → `/tmp/camN` (`camtest.cpp:227,249`). At most 6 cameras (`camtest.cpp:35`). `-cam N` sets how many start (`camtest.cpp:568-569,601-604`).
- **Resolution and format.** 1280x720, 30 fps, RGBA (4 bytes per pixel), raw frames with no header. shmsink sends no caps, so consumers must set `video/x-raw,format=RGBA,width=1280,height=720,framerate=30/1` themselves (`ui/newwidgets/data_bus.py:81-86`; `model/driverguard/runner/camera_reader.py:13-20`).
- **Rotation.**
  - `camera_config.ini` is read from the cwd (`camtest.cpp:578`). It holds `cam0=0, cam1..3=0, cam4=180, cam5=0` (`visionipc/camera_config.ini:2-7`). The value maps to `flip-method=rotate-180` (`camtest.cpp:239-245`).
  - cam0 was 180 until commit `1353b8b` on 2026-05-21, which changed it to 0. The doc still says 180 and is stale (`visionipc/doc/skill.md:25,36`).
- **Control and metadata.**
  - CameraControlCommand on 5573 supports start, stop, restart and status (`camtest.cpp:389-449`).
  - CameraFrameInfo PUB is bound on 5572 (`camtest.cpp:592`), but `publishFrameInfo` is only defined (`camtest.cpp:193`) and never called. The current binary therefore sends no frame metadata.
- **Roles. The sources conflict.**
  - **Logger, replay and the docs** say: 0 front, 1 right, 2 left, 3 right-back, 4 left-back, 5 back.
    - `logger/encoder_265.py:60-67`
    - `logger/timestamp.py:47-54`
    - `replay/replaymanager.py:151-156`
    - `visionipc/doc/skill.md:25-30`
    - `calibration/doc/skill.md:8-13`
  - **The UI** says: 0 Front, 1 Left Front, 2 Left Back/Left Rear, 3 Rear, 4 Right Back/Right Rear, 5 Right Front.
    - `ui/newwidgets/main_camera.py:19` has `CAMERA_LABELS = ["Front", "Left Front", "Left Rear", "Rear", "Right Rear", "Right Front"]`
    - `ui/newwidgets/camera_strip.py:13-20`
    - mosaic order `[1,0,5,2,3,4]` (`main_camera.py:22-23`)
  - **What I saw in the frames.** These are my visual reading of the Nov-2025 grabs, not something the code states.
    - cam0 looks forward through the windscreen.
    - cam1 shows the right side and cam2 the left side, which matches the logger labels.
    - cam3 looks rearward through the rear window.
    - cam4 and cam5 are black.
  - **Conclusion.** cam0 = front is consistent everywhere. Do not trust the side labels for 2026 cabling without checking.
- **Calibration.** Extrinsics exist only for cam0 and cam1.
  - `calibration/camera_0_calibration.json`: pos 1.3/0.1/1.5 m, pitch −7°, yaw 0.
  - `camera_1_calibration.json`: yaw 0, so it is not useful for identifying the camera.
  - Intrinsics are in `calibration/cam0..5.yaml`.

## 3. message/

### Schema: `/home/tonyho/driveragent/message/message.capnp`

File id `@0xde51d8c1e15898c9` (line 1). There is no `BevFrame` struct in the old stack.

| struct (line) | fields |
|---|---|
| Message (3) | content:Text, timestamp:UInt64 |
| GpsLocationData (8) | timestamp:UInt64 (ms), latitude, longitude, altitude, speed (m/s), accuracy, bearing: all Float64 |
| ZoomAndPanCommand (18) | zoomDelta:Int8, panOffsetX:Int32, panOffsetY:Int32, styleMode:UInt8, renderWidth:UInt16, renderHeight:UInt16 |
| DaemonStatus (27) | timestamp:UInt64, name:Text, running:Bool, errorMsg:Text |
| DaemonMessage (34) | timestamp:UInt64, name:Text, message:Text |
| ControlMessage (40) / RemoteControlMessage (51) | timestamp:UInt64, steerAngleDeg, steerRateDeg, steerTorque, accelPedal, brakePedal (Float32), gear:Text, free:Int16 |
| SystemMonitorMessage (62) | timestamp:UInt64, cpuusage:Float32, gpuusage:UInt8 |
| CameraFrameInfo (69) | cameraId:UInt32, frameNumber:UInt64, timestamp:UInt64 (ns), width:UInt32, height:UInt32, format:Text, shmPath:Text, fps:Float32, dropCount:UInt64, latencyNs:UInt64 |
| CameraControlCommand (84) | timestamp:UInt64, command:Text, cameraId:Int32 (−1 = all), numCameras:UInt32, forceCleanup:Bool |
| Waypoint (92) | lat:Float64, lon:Float64, index:UInt32 |
| TrackingCommand (98) | timestamp, recordingEnabled, clearRecording, clearWaypoints, waypoints:List(Waypoint) |
| CarState (107) | timestamp:UInt64 (ms), speedKph:Float32, odometerKm:Float64, gear:Text, handbrake:Bool, brake:UInt8 |
| CarDataMessage (118) | timestamp:UInt64, free, isRadio:UInt8, steerAngle:Int16, accel, brake, mode, dash:UInt8 |
| SelfDrivingStatus (129) | timestamp, enabled:Bool, showGroundTruth:Bool |
| AutopilotState (140) | timestamp, state:UInt8 (0 DISENGAGED, 1 ARMING, 2 ENGAGED, 3 FAULT), engaged:Bool, reason:Text, activeModel:Text |
| SelfDrivingPrediction (148) | content:Text, timestamp |
| WaypointCommand (153) | timestamp, steerAngleDeg, desiredSpeedKph, brakePedal:Float32, gear:Text, free:Int16, desiredCurvature:Float32 |
| ClonePathCommand (163) | timestamp, steerAngle:Int16, accel:UInt8, brake:UInt8, mode:UInt8, enabled:Bool, waypointIndex:UInt32, totalWaypoints:UInt32, pathName:Text, desiredSpeedKph:Float32 |
| RouteCommand (176) | timestamp, destLat, destLon, action:Text |
| RouteStatus (183) | timestamp, active, distanceRemainingM, currentWaypointIndex, totalWaypoints, instruction, destLat, destLon, routeFile |
| RouteGuidance (199) | timestamp, active, egoPoints:List(Point2D) (x fwd, y left), bearingToLookaheadDeg, curvatureLookahead, distToManeuverM, maneuverTag:Text, routeProgressFrac, headingValid, dtcpCommand:UInt8, distFromRouteM, entrancePoint:Point2D |
| Point2D (218) | x:Float32, y:Float32 |
| Box2D (223) | camId:UInt8, xMin, yMin, xMax, yMax: Float32 in 1280x720 pixels |
| SparseDriveDetection (231) | classId:UInt8 (0 car, 1 truck, 2 construction_vehicle, 3 bus, 4 trailer, 5 barrier, 6 motorcycle, 7 bicycle, 8 pedestrian, 9 traffic_cone), className, score, x, y, z, length, width, height, yaw, vx, vy, vz, boxes2d:List(Box2D) |
| SparseDriveMapElement (248) | classId (0 lane_divider, 1 road_boundary, 2 pedestrian_crossing), className, score, points:List(Point2D) |
| SparseDriveTrajectory (255) | points:List(Point2D), score, mode:UInt8 |
| SparseDriveResult (261) | timestamp, frame, detections, mapElements, planTrajectory:List(Point2D), planScore, planCommand, planMode, motionTrajectories, backboneMs, headMs, totalMs |
| **System1Result (285)** | timestamp:UInt64 (ms), frame:UInt64, trajectory:List(Point2D) (6 waypoints, x = fwd, y = left, m), headings:List(Float32) (rad, + = left), egoSpeedKph:Float32, cmd:UInt8 (0 straight, 1 left, 2 right), inferenceMs:Float32, finite:Bool |
| ModelControl (300) | timestamp, action:Text ("start"/"stop"), modelName:Text |
| **DriverGuardDetection (310)** | x1, y1, x2, y2, conf: Float32; classId:UInt8 (0..9) |
| **DriverGuardResult (319)** | timestamp:UInt64 (ms), frame:UInt64, trajectory:List(Point2D) (**4 waypoints, x = lat_right_m, y = fwd_m**), throttle, steer, brake, predSpeedMps, egoSpeedMps:Float32, command:UInt8 (0 L, 1 R, 2 STRAIGHT, 3 LANE_FOLLOW, 4 CH_L, 5 CH_R), inferenceMs:Float32, finite:Bool, daMaskRle:Data, llMaskRle:Data, maskWidth:UInt16, maskHeight:UInt16, detections:List(DriverGuardDetection) |
| ComparisonMetrics (348) | timestamp, steerErrNorm, throttleErr, brakeErr, speedErrMps, crossTrackM, headingErrDeg, steerRmse, throttleRmse, brakeRmse, crossTrackRmse, sampleCount:UInt32, dgFresh, humanFresh, humanPathEgo:List(Point2D) |

Notes on DriverGuardResult:
- The model fills maskWidth/maskHeight with 1280/720 (`model/driverguard/runner/runner.py:223-224`), so box coordinates are 1280x720 pixels.
- The RLE format is records of (uint16 LE count, uint8 value), 3 bytes each (`ui/newwidgets/mask_codec.py:7-30`).

`BevFrame` is NOT FOUND in the old stack. It exists only in the new RK HMI reference, as a pending type on port 8010 (`/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/proto/generated/python/bus_registry.py:28`, `rk/config/rk.toml:194`).

### Pub/sub helper: `message/capnp_pubsub.py`

- **Framing.** Plain ZMQ PUB/SUB. The payload is `msg.to_bytes()`: unpacked capnp with its standard segment table (`capnp_pubsub.py:27-28`). **There is no envelope header.**
- **Topics.**
  - With topic_parts: multipart `[topic, payload]` (`capnp_pubsub.py:29-33`).
  - Without: a single frame (`capnp_pubsub.py:35`).
  - The subscriber always takes the last frame (`capnp_pubsub.py:61-64`).
  - Only DaemonStatus and DaemonMessage use topics, with the literal strings `'DaemonStatus'` and `'DaemonMessage'` (`capnp_pubsub.py:89,115`). Everything else is raw single-frame on its own port.
- **Defaults.** `bind=True` by default for Publisher (`capnp_pubsub.py:6`). The daemon helpers connect to 5570/5571 (`capnp_pubsub.py:74,100`).
- **Gateway.** The external stream on 5600 re-wraps messages as `[channel_name, topic|channel_name, payload]` (`message/gateway.py:268-277`).
- **camtest's C++ publisher.** Commands may arrive as aligned or packed capnp (`camtest.cpp:390-511`).

### service_list.yaml (`message/service_list.yaml`)

Format is `[port, enabled, has_topic]` (`gateway.py:53-58`).

- gateway 5600/5601, bind 0.0.0.0 (lines 2-6)
- DaemonStatus 6570, DaemonMessage 6571 (10-11)
- CameraFrameInfo 5572, CameraControlCommand 5573 (14-15)
- TrackingCommand 5587, GpsLocationData 5588, ZoomAndPanCommand 5590 (18-20)
- CarState 5592, CarDataMessage 5593, ControlMessage 5594 (23-25)
- ClonePathCommand 5599, WaypointCommand 5597 (29-30)
- SelfDrivingStatus 5595, RemoteControlMessage 5596, SystemMonitorMessage 5598 (32-34)
- RouteCommand 5602, RouteStatus 5603 (38-39)
- SelfDrivingPrediction 8002, SelfDrivingIPM 8010, System1Result 8011, SparseDriveResult 8012, DriverGuardResult 8014 (41-45)
- ModelControl 5604 (48)
- RouteGuidance 5605, WaypointCommandFused 5606 (51-52)
- AutopilotState 5607 (55)
- ComparisonMetrics 8015 (58)
- ControltoCAN 9000, CANtoContrl 9001 (61-62)

## 4. UI overlays (ui/newwidgets/)

- **Where overlays appear.** DriverGuard and System1 overlays are drawn only when the selected camera is cam0 (`main_camera.py:225-232`). SparseDrive boxes are drawn on any camera (`main_camera.py:234-239`).
- **Freshness.** Overlays are dropped when older than 1.0 s (`main_camera.py:301-303,418-423`).
- **DriverGuard (`_draw_driverguard_overlay`, `main_camera.py:413-540`).**
  - **Scaling.** Mask, box and contour pixel coordinates are scaled by `widget_w/maskWidth` and `widget_h/maskHeight` (default 1280x720) (`main_camera.py:425-431`).
  - **Drivable area.** Outer contours of the DA mask, drawn as green closed polylines, rgba (60,220,80,200), 3 px (`main_camera.py:434-451`).
  - **Lane lines.** LL contours as red polylines, (240,70,70,230), 4 px (`main_camera.py:454-464`).
  - **Contour extraction.** Contours come from `decode_rle` and then `cv2.findContours(RETR_EXTERNAL, CHAIN_APPROX_TC89_L1)`, keeping DA area > 200 and LL area > 50 (`data_bus.py:678-692`).
  - **Boxes.** Rectangle outline 2 px in the class colour. The label is `"{name} {conf:.2f}"` on a filled tag of the class colour with black text (`main_camera.py:466-487`).
  - **Class list** (`main_camera.py:398-399`; the same list is at `/home/tonyho/model/jetson_bundle/jetson_runtime/yolopx_postprocess.py:14-15`):
    ```
    ['person', 'rider', 'car', 'bus', 'truck', 'bike', 'motor', 'traffic light', 'traffic sign', 'train']
    ```
  - **Colours, RGB** (`main_camera.py:400-411`): person (64,64,255), rider (0,128,255), car (64,255,64), bus (255,200,64), truck (255,0,200), bike (255,255,0), motor (0,255,255), traffic light (128,0,255), traffic sign (128,255,128), train (200,200,200).
  - **DTCP trajectory.** This is a "virtual perspective" and deliberately not geometric (`main_camera.py:489-540`):
    - each point is (lat, fwd)
    - `py = horizon_y + K_v/fwd` with `horizon_y = y + 0.40h` and `K_v = 0.60h·1.5`
    - `px = cx + 0.30w·(lat/fwd)`
    - points with fwd ≤ 0.2 are skipped
    - drawn as a 5 px yellow (255,220,0) line with numbered dots of radius 7/9
- **System1 trajectory (`main_camera.py:291-376`).**
  - Ego (x fwd, y left) points are projected with the real cam0 calibration: K from `calibration/cam0.yaml` scaled to 1280x720, extrinsics from `camera_0_calibration.json` (`cam_projection.py:90-130`).
  - The path is prepended with (0,0), extrapolated to 40 m and densified ×8. It is drawn as a green 4 px line, with dots on the 6 real waypoints.
- **BEV variant.** `_draw_driverguard_on_bev` projects each box's bottom edge to the ground using hard-coded cam0 intrinsics fx 1564.7, fy 1559.8, cx 934.4, cy 650.0, height 1.5 m, pitch −7° (`main_camera.py:385-394,542-640`).
- **SparseDrive 2D colours.** Keyed by SparseDrive class id (`sparsedrive_camera_overlay.py:16-25+`).

## 5. Recordings

### Code

- **Video recorder: `logger/encoder_265.py`**
  - pipeline: `shmsrc socket-path=/tmp/camN ! RGBA 1280x720@30 ! nvvidconv ! NVMM I420 ! nvv4l2h265enc insert-sps-pps=true bitrate=5000000 preset-level=1 ! h265parse ! mp4mux ! filesink` (`encoder_265.py:101-108`)
  - output: **one MP4 (H.265) per camera per segment**
  - path: `{VIDEO_ROOT}/{CAR_ID}-{YYYYmmdd_HHMMSS}/{label}/cam{N}_{YYYYmmdd_HHMMSS}.mp4` (`encoder_265.py:96,196,201-205`)
  - labels at `encoder_265.py:60-67`
  - segment length 60 s (`config.ini:10`, `encoder_265.py:49,212`)
- **Configuration.**
  - `VIDEO_ROOT = /home/tonyho/driveragent/logger/video` (`config.ini:7`, `mainconfig.py:31`)
  - `car_id = 8003` (`config.ini:3`)
- **Message log.** `log/messages.bz2` in each segment, framed as `[u8 topic_len][topic][u32 LE len][capnp]` (`logger/logger.py:213,246-258`).
- **Timestamp logs.** `log/camera_timestamps.json` and `log/segment_summary.json` come from `logger/timestamp.py`.
- **Replay.** `replay/replaymanager.py:145-175` expects the same folder layout and pushes RGBA 1280x720@30 back into `/tmp/camN` through shmsink (`replay/replaymodule.py:217-226`).
- `assets.yaml` lists only models, mbtiles and ko files, no recordings (`assets.yaml:13-32`).
- There are no `.hevc` or `.mkv` recordings.

### On disk

Sources: audit `file_scan.tsv` and `Recordings_and_logs_by_directory...txt`, plus `ls`.

- **Location.** All recordings are in `/home/tonyho/driveragent/logger/video` (536 GB).
  - 1867 segment dirs, each with 6 camera folders
  - 1866 have 6 mp4 files; `8003-20251030_151557` has only 3, all 0 MB
  - archives `*.tar.bz2` and `uploaded.db` sit alongside
  - dates: 2025-10-21 … 2025-11-09, 2025-12-13, then 2026-05-10 (`8003-20260101_*` and `8003-20260401_*` exist only as tar.bz2)
- **Camera coverage.** In most Oct/Nov-2025 driving segments, left-back (cam4) and back (cam5) files are only 0–3 MB and decode to black frames. Only 8 segments have all 6 cameras at about 35 MB:
  - `8003-20251021_060453`
  - `8003-20260510_150620` … `8003-20260510_151220`
  - My frame grabs show both of these as indoor or bench footage with the vehicle not moving.

ffprobe / gst-discoverer results:

| file(s) | codec | WxH | fps | frames / duration |
|---|---|---|---|---|
| `8003-20260510_150820/{front,right,left,right-back,left-back,back}/cam{0..5}_20260510_150820.mp4` | hevc Main yuv420p, ~5.01 Mb/s | 1280x720 | r=30/1 | 1802–1803 / 60.06–60.10 s |
| `8003-20251021_060453/*/cam{0..5}_20251021_060453.mp4` | hevc Main | 1280x720 | r_frame_rate reports 3000/1 (timebase quirk); avg ≈ 30 | 1798–1800 / ~59.9–60.0 s |
| `8003-20251103_141933/*` | hevc | 1280x720 | 3000/1 (avg ≈ 30) | 1831–1833 / ~61.0 s |
| `8003-20251109_090844/*` | hevc | 1280x720 | 3000/1 (avg ≈ 30) | 1800–1802 / ~60.0 s |

gst-discoverer on the 20260510 front file reports container Quicktime, H.265 Main, 1280x720, 30/1, 1:00.095.

**Recommendation for a read-only simulator.** One file per camera, all from the same 60 s segment, with **cam0 = front**. Play at a forced 30 fps, because the 2025 files misreport r_frame_rate.

- **Driving set (recommended for perception and overlay).** Real UK road in daylight. cam0 to cam3 are live; cam4 and cam5 are black.
  - `/home/tonyho/driveragent/logger/video/8003-20251109_090844/front/cam0_20251109_090844.mp4` (FRONT)
  - `/home/tonyho/driveragent/logger/video/8003-20251109_090844/right/cam1_20251109_090844.mp4`
  - `/home/tonyho/driveragent/logger/video/8003-20251109_090844/left/cam2_20251109_090844.mp4`
  - `/home/tonyho/driveragent/logger/video/8003-20251109_090844/right-back/cam3_20251109_090844.mp4`
  - `/home/tonyho/driveragent/logger/video/8003-20251109_090844/left-back/cam4_20251109_090844.mp4` (black)
  - `/home/tonyho/driveragent/logger/video/8003-20251109_090844/back/cam5_20251109_090844.mp4` (black)
  - The neighbouring segments `..._090744` and `..._090944` continue the same drive.
- **All-6-live set.** Use this to test 6-stream plumbing; the footage is indoors and not moving.
  - `/home/tonyho/driveragent/logger/video/8003-20260510_150820/{front/cam0,right/cam1,left/cam2,right-back/cam3,left-back/cam4,back/cam5}_20260510_150820.mp4`
- **Rotation.** The recorded frames are already rotated by camtest at capture time, and the Nov-2025 front grab is upright. Do not rotate again on replay.

## 6. Ports used by the old stack (avoid these)

- **TCP ZMQ on 127.0.0.1** (from the tables above):
  - 5570, 5571, 6570, 6571
  - 5572, 5573
  - 5587, 5588, 5590
  - 5592–5599
  - 5602–5607
  - 8010, 8011, 8012, 8014, 8015
  - 9000, 9001
- **TCP on 0.0.0.0:**
  - 5600 and 5601 (gateway)
  - 5610 (configproxy)
  - **8002** (Valhalla docker, `location/setup_valhalla.sh:25`; currently listening per audit `raw/Listening_ports.txt`)
  - Port 8002 is also listed as SelfDrivingPrediction (`service_list.yaml:41`), and `plan/ipm2.py:499` defaults its input to `tcp://127.0.0.1:8002`.
- **Not started by start.py but present in the code:**
  - 5591 (`logger/boardlogger.py:36`)
  - 5555 (`logger/encoder.py:68`, `visionipc/campub20250524.cpp:222`)
  - camstream: 5510 TCP, 5000 UDP video, 5700/5701/5702 (`visionipc/camstream.cpp:45,57,60-62`)
  - `remote/remote.py` connects out to `172.30.0.12:6096` and binds 5596 (`remote/remote.py:39,41`)
- **Collision to watch.** The new RK HMI plans BevFrame on **8010** (`rk/proto/generated/python/bus_registry.py:28`). The old stack uses 8010 for SelfDrivingIPM (`service_list.yaml:42`; `plan/ipm2.py:501`), and the old UI subscribes to it (`data_bus.py:30`). The new node must not run alongside the old ipm2. 8014 (DriverGuardResult) is also bound by the old driverguard model (`runner.py:136`).
- **Shared memory and files:**
  - `/tmp/cam0..5` and `/dev/shm/cam*` (`camtest.cpp:100-104`)
  - `/dev/shm/map.png` and `/dev/shm/mbgl_cache.db` (`location/mapgen.cpp:58-59`)
  - `/tmp/driveragent.pid`
  - `/tmp/driveragent-recorder-logs`

## 7. Code that touches CAN or vehicle control (the new node must never start these)

- **CAN transmit:**
  - `control/control.py`: socketcan Bus at `control.py:72-74`, `can_bus.send` with ID 0xAB at `control.py:172-178`. The channel comes from `control/.env:7`, `CAN_DEVICE='can0'`.
  - `control/control-ami.py`: the control law; publishes ControltoCAN on `tcp://*:9000` (`control-ami.py:1514`). Its inputs are ControlMessage 5594, WaypointCommand 5597/5606 and AutopilotState 5607 (`control-ami.py:29-38,107-132`).
- **CAN receive** (read-only, but they open the bus and are part of the control chain):
  - `control/publish.py:94-98` (feedback frame → 5593/9001)
  - `carstate/readami.py:163` (`can1`)
  - `carstate/cantest.py:19`
- **CAN interface setup:** `startupcan.sh`, which needs sudo and runs `ip link set can0/can1 up`.
- **Upstream command sources** that feed control-ami:
  - `ui/ui.py`, `ui/newwidgets/keyboard_control.py` (ControlMessage at 10 Hz on 5594, `keyboard_control.py:10`) and `data_bus.py:279-296`
  - `selfdrive/supervisor.py` (engage authority, 5607)
  - `location/path_follower.py` (5597)
  - `plan/fusion.py` (5606)
  - `remote/remote.py` (G923 → RemoteControlMessage 5596)
- **Orchestrators that start all of the above:** `start.py` and `~/s.sh`.
- **Also destructive:** `logger/deleter.py`, which start.py runs every 300 s (`start.py:90`). It runs `shutil.rmtree` on the oldest 20 % of segments when VIDEO_ROOT > 1 GB (`deleter.py:31-32,66-85`). It filters by `CAR_ID` from the environment, default "8001" (`deleter.py:30,45-53`).
- **Legacy copies:** `unused_bk/control/publish-bk.py` and `unused_bk/carstate/readspeed.py`.