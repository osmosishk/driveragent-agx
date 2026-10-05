"""Adapter base class: the preprocessing and postprocessing plug-in of one model.

An adapter converts one ingest Frame (NV12, BT.601 limited range) into the engine inputs, and the
engine outputs into the result parts of the node:

  detections  list of {"class_id", "class_name", "score", "x1", "y1", "x2", "y2", "track_id"}
              (box pixels in the FrameLink frame size: frame.width x frame.height)
  trajectory  None or {"frame": str, "points": [(x, y, t_s)], "inputs_valid": bool, "note": str}
  masks       list of {"name", "width", "height", "encoding", "data"}

Adapters keep no per-frame state. One adapter object is shared by all worker threads of a model.
Rule R8: an adapter never returns control values (throttle, steer, brake, mu, sigma, pred_speed).
"""
from __future__ import annotations

import cv2
import numpy as np

MASK_ENCODING = "rle-u16le-count-u8-value-rowmajor"


def _check_nv12(frame) -> np.ndarray:
    nv12 = frame.nv12
    want = (frame.height * 3 // 2, frame.width)
    if nv12 is None or tuple(nv12.shape) != want:
        got = None if nv12 is None else tuple(nv12.shape)
        raise ValueError(f"cam{frame.cam} seq {frame.seq}: NV12 shape {got} != {want}")
    return nv12


def nv12_to_bgr(frame) -> np.ndarray:
    """NV12 (BT.601 limited range) -> BGR uint8 (H x W x 3). See docs/MODELS.md section 5."""
    return cv2.cvtColor(_check_nv12(frame), cv2.COLOR_YUV2BGR_NV12)


def nv12_to_rgb(frame) -> np.ndarray:
    """NV12 (BT.601 limited range) -> RGB uint8 (H x W x 3)."""
    return cv2.cvtColor(_check_nv12(frame), cv2.COLOR_YUV2RGB_NV12)


class Adapter:
    """Base class. Subclasses set NAME and ENGINE_INPUT_SHAPES and implement preprocess/postprocess."""

    NAME = "base"
    # Engine input shapes by input name (docs/MODELS.md). Used for the trtexec --shapes argument
    # when an engine must be rebuilt from ONNX.
    ENGINE_INPUT_SHAPES: dict[str, tuple] = {}
    ENGINE_OUTPUTS: tuple = ()

    def __init__(self, cfg: dict, engine):
        self.cfg = dict(cfg or {})
        self.engine = engine
        self.options = dict(self.cfg.get("options") or {})
        if engine is not None:
            self._check_engine_io(engine)

    def _check_engine_io(self, engine) -> None:
        """Raise ValueError when the engine I/O does not match what this adapter needs."""
        ins = {t.name: tuple(t.shape) for t in engine.inputs()}
        outs = {t.name for t in engine.outputs()}
        for name, shape in self.ENGINE_INPUT_SHAPES.items():
            if name not in ins:
                raise ValueError(f"adapter {self.NAME}: engine has no input {name!r} (inputs: {sorted(ins)})")
            got = tuple(1 if d < 0 else d for d in ins[name])
            if got != tuple(shape):
                raise ValueError(f"adapter {self.NAME}: input {name!r} shape {got} != {tuple(shape)}")
        missing = [n for n in self.ENGINE_OUTPUTS if n not in outs]
        if missing:
            raise ValueError(f"adapter {self.NAME}: engine has no output(s) {missing} (outputs: {sorted(outs)})")

    def dummy_inputs(self) -> dict:
        """Zero inputs in the engine shapes (for warm-up)."""
        out = {}
        for t in self.engine.inputs():
            shape = tuple(1 if d < 0 else d for d in t.shape)
            out[t.name] = np.zeros(shape, dtype=np.float32)
        return out

    def preprocess(self, frame) -> tuple[dict, dict]:
        """Frame -> (engine inputs {name: np.ndarray}, ctx for postprocess)."""
        raise NotImplementedError

    def postprocess(self, outputs: dict, frame, ctx: dict) -> dict:
        """Engine outputs -> {"detections": [...], "trajectory": None | {...}, "masks": [...]}."""
        raise NotImplementedError

    @staticmethod
    def empty_result() -> dict:
        return {"detections": [], "trajectory": None, "masks": []}
