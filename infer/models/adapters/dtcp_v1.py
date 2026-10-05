"""DTCP v1 adapter (driverguard_dtcp): 4 ego waypoints for DISPLAY ONLY.

Preprocessing: NV12 -> RGB (cv2.COLOR_YUV2RGB_NV12), then the UNCHANGED legacy preprocess_dtcp.
State vector: the same formula as the old runner _build_state_vec (runner.py:63-69):
    [speed_mps / 12, target_lat_right_m, target_fwd_m, one_hot(command, 6)]
The AGX has no CarState: ego speed 0 m/s is used (or a fixed value from the config). Command and
target are always assumed, so inputs_valid is always False (docs/MODELS.md 4.4).

Rule R8: only pred_wp is read. mu, sigma and pred_speed are NOT read and NOT returned; no throttle,
steer or brake is computed.
"""
from __future__ import annotations

import numpy as np

from infer.models.adapters.base import Adapter, nv12_to_rgb
from infer.models.legacy.driverguard.preprocess import preprocess_dtcp

COMMAND_NAMES = {0: "LEFT", 1: "RIGHT", 2: "STRAIGHT", 3: "LANE_FOLLOW", 4: "CHANGE_LEFT",
                 5: "CHANGE_RIGHT"}
WAYPOINT_T_S = (0.5, 1.0, 1.5, 2.0)
TRAJ_FRAME = ("DTCP ego frame: x = lateral, right positive (m); y = forward (m); "
              "origin = ego at frame time (model convention)")


def build_state_vec(speed_mps: float, target_xy, command: int) -> np.ndarray:
    """Same as the old runner _build_state_vec (legacy/driverguard/runner.py:63-69). The legacy
    module cannot be imported (it needs the old repo), so the 5 lines are repeated here."""
    speed = np.array([[speed_mps / 12.0]], dtype=np.float32)
    target = np.array([list(target_xy)], dtype=np.float32)
    cmd_one_hot = np.zeros((1, 6), dtype=np.float32)
    cmd_one_hot[0, int(command)] = 1.0
    return np.concatenate([speed, target, cmd_one_hot], axis=1)


def _fmt_num(v: float) -> str:
    return f"{v:g}"


class DtcpV1Adapter(Adapter):
    NAME = "dtcp_v1"
    ENGINE_INPUT_SHAPES = {"image": (1, 3, 256, 928), "state": (1, 9), "target_point": (1, 2)}
    ENGINE_OUTPUTS = ("pred_wp",)

    def __init__(self, cfg: dict, engine):
        super().__init__(cfg, engine)
        o = self.options
        self.command = int(o.get("command", 2))
        if self.command not in COMMAND_NAMES:
            raise ValueError(f"dtcp_v1: command {self.command} not in 0..5")
        tgt = o.get("target", [0.0, 20.0])
        if len(tgt) != 2:
            raise ValueError(f"dtcp_v1: target must be [lateral_right_m, forward_m], not {tgt!r}")
        self.target = (float(tgt[0]), float(tgt[1]))
        sp = o.get("ego_speed_mps")
        self.speed_known = sp is not None
        self.speed_mps = float(sp) if sp is not None else 0.0
        # Command and target are always assumed values, and a speed from the config is a fixed
        # value, not a measured CarState speed: the inputs are never all real (agx_infer.capnp
        # inputsValid = false: some model inputs were not real).
        self.inputs_valid = False
        speed_txt = (f"ego speed {_fmt_num(self.speed_mps)} m/s (fixed value from config)" if self.speed_known
                     else "ego speed 0 m/s (no CarState on the AGX)")
        self.note = (f"display only, not for control; assumed inputs: {speed_txt}, "
                     f"command {COMMAND_NAMES[self.command]}, "
                     f"target ({_fmt_num(self.target[0])}, {_fmt_num(self.target[1])}) m")
        # constant inputs, built once; shared by all workers (never written)
        self._state = build_state_vec(self.speed_mps, self.target, self.command)
        self._target_point = np.array([list(self.target)], dtype=np.float32)

    def preprocess_rgb(self, rgb: np.ndarray) -> tuple[dict, dict]:
        """RGB uint8 -> engine inputs. Image exactly legacy preprocess_dtcp."""
        return ({"image": preprocess_dtcp(rgb), "state": self._state,
                 "target_point": self._target_point}, {})

    def preprocess(self, frame) -> tuple[dict, dict]:
        return self.preprocess_rgb(nv12_to_rgb(frame))

    def postprocess(self, outputs: dict, frame, ctx: dict) -> dict:
        wp = np.asarray(outputs["pred_wp"], dtype=np.float64).reshape(-1, 2)
        if wp.shape[0] != len(WAYPOINT_T_S):
            raise ValueError(f"dtcp_v1: pred_wp has {wp.shape[0]} points, expected {len(WAYPOINT_T_S)}")
        if not np.all(np.isfinite(wp)):
            raise ValueError("dtcp_v1: pred_wp is not finite")
        points = [(float(wp[i, 0]), float(wp[i, 1]), float(WAYPOINT_T_S[i])) for i in range(wp.shape[0])]
        traj = {"frame": TRAJ_FRAME, "points": points, "inputs_valid": bool(self.inputs_valid),
                "note": self.note}
        return {"detections": [], "trajectory": traj, "masks": []}


ADAPTER_CLASS = DtcpV1Adapter
