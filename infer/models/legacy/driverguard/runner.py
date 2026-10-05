"""DriverGuard inference loop: front cam → YOLOPX + DTCP → ZMQ publish.

Invoked by /home/tonyho/model/driverguard/run.py, which puts the driveragent
root, the jetson_bundle/jetson_runtime root, and this package on sys.path
first.
"""

import time
import threading

import cv2
import numpy as np

from message.capnp_pubsub import (Publisher, Subscriber, DaemonStatus,
                                  DaemonMessenger)

# jetson_bundle/jetson_runtime (on sys.path via run.py)
from trt_runner import TRTRunner
from preprocess import preprocess_yolopx, preprocess_dtcp
from yolopx_postprocess import (nms_yolopx, scale_coords, segmasks_from_logits)
from beta_mode import beta_mode_action

from runner.camera_reader import FrontCameraReader, CAM_WIDTH, CAM_HEIGHT
from runner.ego_state import SpeedProvider
from runner.mask_codec import encode_rle

SERVICE_NAME = "driverguard_runner"


class SDStatusGate:
    """Background subscriber to SelfDrivingStatus.enabled."""

    def __init__(self, addr, schema_file):
        self._enabled = True
        self._addr = addr
        self._schema_file = schema_file
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="driverguard_sd_gate")
        self._thread.start()

    def _run(self):
        try:
            sub = Subscriber(self._schema_file, "SelfDrivingStatus", self._addr)
        except Exception as e:
            print(f"[driverguard] sd_status gate: cannot subscribe to {self._addr}: "
                  f"{e}. Gate stays open.")
            return
        while not self._stop.is_set():
            try:
                msg = sub.receive()
                self._enabled = bool(getattr(msg, "enabled", True))
            except Exception:
                time.sleep(0.05)

    def is_enabled(self):
        return self._enabled


def _build_state_vec(speed_mps, target_xy, command):
    """Match build_state_vec in jetson_pipeline.py (DTCP dtcp_infer.py:146-150)."""
    speed = np.array([[speed_mps / 12.0]], dtype=np.float32)
    target = np.array([list(target_xy)], dtype=np.float32)
    cmd_one_hot = np.zeros((1, 6), dtype=np.float32)
    cmd_one_hot[0, int(command)] = 1.0
    return np.concatenate([speed, target, cmd_one_hot], axis=1)


def _run_one_frame(yolopx, dtcp, bgr, speed_mps, target_xy, command):
    """Single forward pass through YOLOPX + DTCP. Mirrors
    jetson_pipeline.run_one_frame."""
    # YOLOPX
    yx, h0, w0, pad_wh, _ratio = preprocess_yolopx(bgr)
    y_out = yolopx.infer({"image": yx})
    boxes = nms_yolopx(y_out["det"], conf_thres=0.30, iou_thres=0.45)
    if len(boxes):
        boxes[:, :4] = scale_coords(yx.shape[-2:], boxes[:, :4], (h0, w0))
    da_mask, ll_mask = segmasks_from_logits(
        y_out["da_seg"], y_out["ll_seg"],
        in_hw=yx.shape[-2:], pad_wh=pad_wh, out_hw=(h0, w0))

    # DTCP
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    dx = preprocess_dtcp(rgb)
    state = _build_state_vec(speed_mps, target_xy, command)
    target_arr = np.array([list(target_xy)], dtype=np.float32)
    d_out = dtcp.infer({"image": dx, "state": state, "target_point": target_arr})
    wp = d_out["pred_wp"][0]
    mu = d_out["mu"][0]
    sigma = d_out["sigma"][0]
    pred_speed_mps = float(d_out["pred_speed"][0, 0]) * 12.0
    throttle, steer, brake = beta_mode_action(mu, sigma)
    return {
        "boxes": boxes,           # (N, 6) xyxy + conf + cls
        "da_mask": da_mask,       # (H, W) uint8
        "ll_mask": ll_mask,       # (H, W) uint8
        "wp": wp,                 # (4, 2) ego frame
        "throttle": float(throttle),
        "steer": float(steer),
        "brake": float(brake),
        "pred_speed_mps": pred_speed_mps,
    }


def main(args):
    print(f"[driverguard] loading engines:\n"
          f"  yolopx: {args.yolopx_engine}\n"
          f"  dtcp:   {args.dtcp_engine}")
    yolopx = TRTRunner(args.yolopx_engine)
    dtcp = TRTRunner(args.dtcp_engine)
    print(f"[driverguard] {yolopx}")
    print(f"[driverguard] {dtcp}")

    try:
        daemon_status = DaemonStatus(name=SERVICE_NAME)
        daemon_log = DaemonMessenger(name=SERVICE_NAME)
    except Exception as e:
        print(f"[driverguard] heartbeat unavailable: {e}")
        daemon_status = None
        daemon_log = None

    camera = FrontCameraReader(socket_path=args.cam)
    camera.connect(max_retries=10)

    speed_provider = SpeedProvider()
    speed_provider.start()

    gate = None
    if args.gated:
        gate = SDStatusGate(args.sd_status_addr, args.schema)
        gate.start()

    pub_addr = f"tcp://*:{args.pub_port}"
    pub = Publisher(args.schema, "DriverGuardResult", pub_addr, bind=True)
    print(f"[driverguard] publishing DriverGuardResult on {pub_addr}")

    target_xy = tuple(args.target)
    command = int(args.command)
    period = 1.0 / max(args.rate, 0.1)
    frame_idx = 0

    try:
        while True:
            tick_start = time.perf_counter()
            t_now_ms = int(time.time() * 1000)

            if gate is not None and not gate.is_enabled():
                time.sleep(period)
                continue

            bgr = camera.read_bgr()
            if bgr is None:
                if daemon_log is not None:
                    try:
                        daemon_log.log("waiting for camera frame")
                    except Exception:
                        pass
                time.sleep(0.05)
                continue
            if bgr.shape[:2] != (CAM_HEIGHT, CAM_WIDTH):
                bgr = cv2.resize(bgr, (CAM_WIDTH, CAM_HEIGHT),
                                 interpolation=cv2.INTER_LINEAR)

            speed_mps = speed_provider.latest_speed_mps()

            t0 = time.perf_counter()
            try:
                result = _run_one_frame(yolopx, dtcp, bgr, speed_mps,
                                        target_xy, command)
            except Exception as e:
                print(f"[driverguard] inference failed: {e}")
                if daemon_status is not None:
                    try:
                        daemon_status.send(False, f"inference: {e}")
                    except Exception:
                        pass
                time.sleep(period)
                continue
            inference_ms = (time.perf_counter() - t0) * 1000.0

            wp = result["wp"]
            trajectory = [{"x": float(wp[i, 0]), "y": float(wp[i, 1])}
                          for i in range(wp.shape[0])]
            finite = bool(np.all(np.isfinite(wp)))

            try:
                da_rle = encode_rle(result["da_mask"])
                ll_rle = encode_rle(result["ll_mask"])
            except Exception as e:
                print(f"[driverguard] mask encode failed: {e}")
                da_rle = b""
                ll_rle = b""

            detections = []
            for row in result["boxes"]:
                detections.append({
                    "x1": float(row[0]),
                    "y1": float(row[1]),
                    "x2": float(row[2]),
                    "y2": float(row[3]),
                    "conf": float(row[4]),
                    "classId": int(row[5]) & 0xFF,
                })

            try:
                pub.publish(
                    timestamp=t_now_ms,
                    frame=frame_idx,
                    trajectory=trajectory,
                    throttle=result["throttle"],
                    steer=result["steer"],
                    brake=result["brake"],
                    predSpeedMps=result["pred_speed_mps"],
                    egoSpeedMps=float(speed_mps),
                    command=command,
                    inferenceMs=float(inference_ms),
                    finite=finite,
                    daMaskRle=da_rle,
                    llMaskRle=ll_rle,
                    maskWidth=CAM_WIDTH,
                    maskHeight=CAM_HEIGHT,
                    detections=detections,
                )
            except Exception as e:
                print(f"[driverguard] publish failed: {e}")

            if daemon_status is not None and frame_idx % 10 == 0:
                try:
                    daemon_status.send(
                        True,
                        f"frame={frame_idx} ms={inference_ms:.1f} "
                        f"det={len(detections)}")
                except Exception:
                    pass

            if frame_idx % 10 == 0:
                print(f"[driverguard] frame={frame_idx} {inference_ms:.1f} ms "
                      f"dets={len(detections)} "
                      f"t/s/b=({result['throttle']:.2f},{result['steer']:+.2f},"
                      f"{result['brake']:.2f}) "
                      f"wp4=({wp[-1, 0]:+.1f},{wp[-1, 1]:+.1f}) "
                      f"da_rle={len(da_rle)}B ll_rle={len(ll_rle)}B "
                      f"speed={speed_mps:.1f} m/s")

            frame_idx += 1
            if args.once:
                break

            elapsed = time.perf_counter() - tick_start
            if elapsed < period:
                time.sleep(period - elapsed)
    except KeyboardInterrupt:
        print("[driverguard] interrupted, shutting down")
    finally:
        camera.close()
        speed_provider.stop()
        if daemon_status is not None:
            try:
                daemon_status.send(False, "exiting")
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(
        "Do not run runner/runner.py directly. "
        "Use: python /home/tonyho/model/driverguard/run.py")
