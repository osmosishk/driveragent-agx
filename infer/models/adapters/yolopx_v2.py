"""YOLOPX v2 adapter (driverguard_yolopx): 10-class boxes + drivable-area and lane-line masks.

Pre- and postprocessing are the UNCHANGED legacy DriverGuard functions (infer/models/legacy/driverguard,
docs/MODELS.md section 3). The only difference to the old runner: the frame comes from NV12 with
cv2.COLOR_YUV2BGR_NV12, so preprocess_yolopx gets true BGR (the old camera reader swapped R and B).
"""
from __future__ import annotations

import numpy as np

from infer.models.adapters.base import MASK_ENCODING, Adapter, nv12_to_bgr
from infer.models.legacy.driverguard.mask_codec import encode_rle
from infer.models.legacy.driverguard.preprocess import preprocess_yolopx
from infer.models.legacy.driverguard.yolopx_postprocess import (CLASS_NAMES, nms_yolopx, scale_coords,
                                                                 segmasks_from_logits)

IN_HW = (384, 640)


class YolopxV2Adapter(Adapter):
    NAME = "yolopx_v2"
    ENGINE_INPUT_SHAPES = {"image": (1, 3, 384, 640)}
    ENGINE_OUTPUTS = ("det", "da_seg", "ll_seg")

    def __init__(self, cfg: dict, engine):
        super().__init__(cfg, engine)
        o = self.options
        self.conf_thres = float(o.get("conf_thres", 0.30))
        self.iou_thres = float(o.get("iou_thres", 0.45))
        self.max_det = int(o.get("max_det", 300))
        self.masks_cameras = {int(c) for c in (o.get("masks_cameras") or [])}

    # -- preprocessing ------------------------------------------------------------------------------
    def preprocess_bgr(self, bgr: np.ndarray) -> tuple[dict, dict]:
        """BGR uint8 -> engine inputs. Exactly legacy preprocess_yolopx."""
        x, h0, w0, pad_wh, ratio = preprocess_yolopx(bgr, in_shape=IN_HW)
        ctx = {"in_hw": tuple(x.shape[-2:]), "img_hw": (int(h0), int(w0)), "pad_wh": pad_wh,
               "ratio": ratio}
        return {"image": x}, ctx

    def preprocess(self, frame) -> tuple[dict, dict]:
        return self.preprocess_bgr(nv12_to_bgr(frame))

    # -- postprocessing -----------------------------------------------------------------------------
    def boxes_from_outputs(self, outputs: dict, ctx: dict, out_hw: tuple) -> np.ndarray:
        """(N, 6) x1, y1, x2, y2, score, cls in out_hw pixels (legacy nms_yolopx + scale_coords)."""
        boxes = nms_yolopx(outputs["det"], conf_thres=self.conf_thres, iou_thres=self.iou_thres,
                           max_det=self.max_det)
        if not len(boxes):
            return boxes
        h0, w0 = ctx["img_hw"]
        boxes[:, :4] = scale_coords(ctx["in_hw"], boxes[:, :4], (h0, w0))
        out_h, out_w = out_hw
        if (out_h, out_w) != (h0, w0):  # only when the image was not made from this frame
            boxes[:, [0, 2]] *= out_w / w0
            boxes[:, [1, 3]] *= out_h / h0
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, out_w)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, out_h)
        return boxes

    def masks_from_outputs(self, outputs: dict, ctx: dict, out_hw: tuple) -> tuple:
        """(drivable_area, lane_line) uint8 {0,1} masks at out_hw (legacy segmasks_from_logits)."""
        return segmasks_from_logits(outputs["da_seg"], outputs["ll_seg"], in_hw=ctx["in_hw"],
                                    pad_wh=ctx["pad_wh"], out_hw=out_hw)

    def postprocess(self, outputs: dict, frame, ctx: dict) -> dict:
        out_hw = (int(frame.height), int(frame.width))
        boxes = self.boxes_from_outputs(outputs, ctx, out_hw)
        dets = []
        for row in boxes:
            cls = int(row[5])
            dets.append({
                "class_id": cls,
                "class_name": CLASS_NAMES[cls] if 0 <= cls < len(CLASS_NAMES) else f"class{cls}",
                "score": float(row[4]),
                "x1": float(row[0]), "y1": float(row[1]), "x2": float(row[2]), "y2": float(row[3]),
                "track_id": 0,
            })
        masks = []
        if int(frame.cam) in self.masks_cameras:
            da, ll = self.masks_from_outputs(outputs, ctx, out_hw)
            for name, m in (("drivable_area", da), ("lane_line", ll)):
                masks.append({"name": name, "width": out_hw[1], "height": out_hw[0],
                              "encoding": MASK_ENCODING, "data": encode_rle(m)})
        return {"detections": dets, "trajectory": None, "masks": masks}


ADAPTER_CLASS = YolopxV2Adapter
