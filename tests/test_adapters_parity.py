"""Parity of the new adapters with the legacy DriverGuard functions (same engine, same image).

For each of the 3 sample JPEGs (/home/tonyho/model/jetson_bundle/samples/cam_front, 1600x900):
  1. adapter.preprocess_bgr(bgr) == legacy preprocess_yolopx(bgr)            (max abs diff < 1e-6)
     adapter.preprocess(frame) == legacy preprocess_yolopx(NV12 -> BGR)       (the frame path)
  2. one TensorRT run; adapter.postprocess == legacy nms_yolopx + scale_coords + segmasks_from_logits
     on the same outputs (boxes and decoded RLE masks identical)
  3. agreement with the reference npz (as the T1 research): BGR path and NV12 path
  4. DTCP: adapter preprocess == legacy preprocess_dtcp, state vector == old _build_state_vec values
GPU use: 2 engines, about 10 inferences. Run time < 30 s.
"""
import glob
import os

import cv2
import numpy as np
import pytest

from infer.ingest.frame_store import Frame
from infer.models.legacy.driverguard.mask_codec import decode_rle
from infer.models.legacy.driverguard.preprocess import preprocess_dtcp, preprocess_yolopx
from infer.models.legacy.driverguard.yolopx_postprocess import (CLASS_NAMES, nms_yolopx, scale_coords,
                                                                 segmasks_from_logits)

SAMPLES = sorted(glob.glob("/home/tonyho/model/jetson_bundle/samples/cam_front/*.jpg"))
REF = "/home/tonyho/model/jetson_bundle/samples/reference_yolopx/e036014a715945aa965f4ec24e8639c9_yolopx.npz"
YOLOPX_ENGINE = "/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine"
DTCP_ENGINE = "/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine"
FORBIDDEN = {"throttle", "steer", "brake", "mu", "sigma", "pred_speed", "pred_speed_mps"}

pytestmark = pytest.mark.skipif(not (SAMPLES and os.path.isfile(REF) and os.path.isfile(YOLOPX_ENGINE)),
                                reason="sample data or engines missing")


def bgr_to_nv12(bgr):
    """BGR -> I420 (OpenCV, BT.601 limited) -> NV12 (Y plane, then interleaved U,V)."""
    h, w = bgr.shape[:2]
    i420 = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
    y = i420[:h]
    u = i420[h:h + h // 4].reshape(h // 2, w // 2)
    v = i420[h + h // 4:].reshape(h // 2, w // 2)
    uv = np.empty((h // 2, w), dtype=np.uint8)
    uv[:, 0::2], uv[:, 1::2] = u, v
    return np.ascontiguousarray(np.vstack([y, uv]))


def make_frame(bgr, cam=0, seq=1):
    h, w = bgr.shape[:2]
    t = 1_000_000_000
    return Frame(cam, seq, t, t, t, w, h, "nv12", "file", bgr_to_nv12(bgr))


def walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from walk_keys(v)


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i + 1e-9)


def ref_match(boxes, ref_boxes):
    """Number of reference boxes with a box of the same class at IoU > 0.95 (T1 research rule)."""
    n = 0
    for r in ref_boxes:
        best = max([iou(r, b) for b in boxes if int(b[5]) == int(r[5])] or [0.0])
        n += best > 0.95
    return n


@pytest.fixture(scope="module")
def yolopx():
    from infer.models.adapters.yolopx_v2 import YolopxV2Adapter
    from infer.models.trt_engine import TrtEngine
    eng = TrtEngine(YOLOPX_ENGINE)
    cfg = {"options": {"conf_thres": 0.30, "iou_thres": 0.45, "max_det": 300, "masks_cameras": [0]}}
    return YolopxV2Adapter(cfg, eng), eng.new_slot()


@pytest.fixture(scope="module")
def dtcp():
    from infer.models.adapters.dtcp_v1 import DtcpV1Adapter
    from infer.models.trt_engine import TrtEngine
    eng = TrtEngine(DTCP_ENGINE)
    cfg = {"options": {"command": 2, "target": [0.0, 20.0], "ego_speed_mps": None}}
    return DtcpV1Adapter(cfg, eng), eng.new_slot()


def test_yolopx_parity(yolopx):
    adapter, slot = yolopx
    ref = np.load(REF)
    print()
    rows = []
    for k, path in enumerate(SAMPLES):
        bgr = cv2.imread(path)
        h0, w0 = bgr.shape[:2]
        frame = make_frame(bgr)

        # 1. preprocessing: same BGR -> identical tensor
        x_leg, lh, lw, pad_leg, _ = preprocess_yolopx(bgr)
        inp, ctx = adapter.preprocess_bgr(bgr)
        d_bgr = float(np.abs(inp["image"] - x_leg).max())
        assert d_bgr < 1e-6
        assert ctx["pad_wh"] == pad_leg and ctx["img_hw"] == (lh, lw)
        # frame path: NV12 -> BGR (cv2.COLOR_YUV2BGR_NV12) -> legacy
        bgr_nv = cv2.cvtColor(frame.nv12, cv2.COLOR_YUV2BGR_NV12)
        inp_f, ctx_f = adapter.preprocess(frame)
        d_frame = float(np.abs(inp_f["image"] - preprocess_yolopx(bgr_nv)[0]).max())
        assert d_frame < 1e-6

        # 2. one TRT run, legacy and adapter postprocessing on the same outputs
        outs, ms = slot.infer({"image": x_leg})
        outs2, _ = slot.infer({"image": x_leg})
        trt_rerun_diff = max(float(np.abs(outs[n] - outs2[n]).max()) for n in outs)
        b_leg = nms_yolopx(outs["det"], conf_thres=0.30, iou_thres=0.45)
        if len(b_leg):
            b_leg[:, :4] = scale_coords(x_leg.shape[-2:], b_leg[:, :4], (lh, lw))
        da_leg, ll_leg = segmasks_from_logits(outs["da_seg"], outs["ll_seg"], in_hw=x_leg.shape[-2:],
                                              pad_wh=pad_leg, out_hw=(lh, lw))
        res = adapter.postprocess(outs, frame, ctx)
        assert not (FORBIDDEN & set(walk_keys(res)))
        assert res["trajectory"] is None
        dets = res["detections"]
        assert len(dets) == len(b_leg)
        for d, b in zip(dets, b_leg):
            assert [d["x1"], d["y1"], d["x2"], d["y2"], d["score"]] == [float(v) for v in b[:5]]
            assert d["class_id"] == int(b[5]) and d["class_name"] == CLASS_NAMES[int(b[5])]
            assert d["track_id"] == 0
            assert 0 <= d["x1"] <= d["x2"] <= w0 and 0 <= d["y1"] <= d["y2"] <= h0
        masks = {m["name"]: m for m in res["masks"]}
        assert set(masks) == {"drivable_area", "lane_line"}
        for name, want in (("drivable_area", da_leg), ("lane_line", ll_leg)):
            m = masks[name]
            assert (m["width"], m["height"]) == (w0, h0)
            assert m["encoding"] == "rle-u16le-count-u8-value-rowmajor"
            assert np.array_equal(decode_rle(m["data"], h0, w0), want)
        # masks only for masks_cameras
        assert adapter.postprocess(outs, make_frame(bgr, cam=1), ctx)["masks"] == []

        # 3. agreement with the reference (900x1600)
        rb, rda, rll = ref[f"f{k:04d}_boxes"], ref[f"f{k:04d}_da"], ref[f"f{k:04d}_ll"]
        assert rda.shape == (h0, w0)
        # NV12 path: full adapter pipeline from the Frame
        outs_f, _ = slot.infer(inp_f)
        res_f = adapter.postprocess(outs_f, frame, ctx_f)
        b_f = np.array([[d["x1"], d["y1"], d["x2"], d["y2"], d["score"], d["class_id"]]
                        for d in res_f["detections"]], dtype=np.float32).reshape(-1, 6)
        mf = {m["name"]: decode_rle(m["data"], h0, w0) for m in res_f["masks"]}
        row = {
            "frame": k, "pre_diff_bgr": d_bgr, "pre_diff_nv12": d_frame, "trt_rerun_diff": trt_rerun_diff,
            "ref_boxes": len(rb),
            "bgr_boxes": len(b_leg), "bgr_match": ref_match(b_leg, rb),
            "bgr_da": float((da_leg == rda).mean()), "bgr_ll": float((ll_leg == rll).mean()),
            "nv12_boxes": len(b_f), "nv12_match": ref_match(b_f, rb),
            "nv12_da": float((mf["drivable_area"] == rda).mean()),
            "nv12_ll": float((mf["lane_line"] == rll).mean()),
        }
        rows.append(row)
        print("parity " + " ".join(f"{a}={v:.6f}" if isinstance(v, float) else f"{a}={v}" for a, v in row.items()))
        assert row["bgr_da"] >= 0.99 and row["bgr_ll"] >= 0.99
        assert row["nv12_da"] >= 0.99 and row["nv12_ll"] >= 0.99
        assert row["bgr_boxes"] == row["ref_boxes"]
    tot = {k: sum(r[k] for r in rows) for k in ("ref_boxes", "bgr_boxes", "bgr_match", "nv12_boxes", "nv12_match")}
    print("parity totals", tot,
          "min bgr_da %.5f bgr_ll %.5f nv12_da %.5f nv12_ll %.5f" % (
              min(r["bgr_da"] for r in rows), min(r["bgr_ll"] for r in rows),
              min(r["nv12_da"] for r in rows), min(r["nv12_ll"] for r in rows)))


def test_dtcp_parity(dtcp):
    from infer.models.adapters.dtcp_v1 import TRAJ_FRAME
    adapter, slot = dtcp
    print()
    for k, path in enumerate(SAMPLES):
        bgr = cv2.imread(path)
        frame = make_frame(bgr)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        inp, ctx = adapter.preprocess_rgb(rgb)
        assert float(np.abs(inp["image"] - preprocess_dtcp(rgb)).max()) < 1e-6
        # old runner: state = [speed/12, lat_right, fwd, one_hot(2, 6)] with speed 0, target (0, 20)
        assert inp["state"].dtype == np.float32 and inp["state"].shape == (1, 9)
        assert inp["state"].tolist() == [[0.0, 0.0, 20.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]]
        assert inp["target_point"].tolist() == [[0.0, 20.0]]
        # frame path: NV12 -> RGB (cv2.COLOR_YUV2RGB_NV12) -> legacy
        inp_f, _ = adapter.preprocess(frame)
        rgb_nv = cv2.cvtColor(frame.nv12, cv2.COLOR_YUV2RGB_NV12)
        assert float(np.abs(inp_f["image"] - preprocess_dtcp(rgb_nv)).max()) < 1e-6

        outs, _ = slot.infer(inp)
        res = adapter.postprocess(outs, frame, ctx)
        outs_f, _ = slot.infer(inp_f)
        res_f = adapter.postprocess(outs_f, frame, {})
        assert not (FORBIDDEN & set(walk_keys(res)))
        assert res["detections"] == [] and res["masks"] == []
        tr = res["trajectory"]
        assert tr["frame"] == TRAJ_FRAME and tr["inputs_valid"] is False
        assert tr["note"] == ("display only, not for control; assumed inputs: ego speed 0 m/s "
                              "(no CarState on the AGX), command STRAIGHT, target (0, 20) m")
        assert [p[2] for p in tr["points"]] == [0.5, 1.0, 1.5, 2.0]
        wp = outs["pred_wp"][0]
        assert [(p[0], p[1]) for p in tr["points"]] == [(float(wp[i, 0]), float(wp[i, 1])) for i in range(4)]
        dmax = max(abs(a[j] - b[j]) for a, b in zip(tr["points"], res_f["trajectory"]["points"]) for j in (0, 1))
        print(f"dtcp frame{k} bgr-path wp={[(round(p[0], 3), round(p[1], 3)) for p in tr['points']]} "
              f"nv12-path max diff {dmax:.4f} m")
