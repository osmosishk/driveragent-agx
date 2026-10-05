"""Draw results on a camera picture (old DriverAgent UI style) + the 1 Hz snapshot task.

Old UI references (/home/tonyho/driveragent/ui/newwidgets/):
  main_camera.py:400-411   class colours (RGB; converted to BGR here)
  main_camera.py:434-464   drivable area green contour 3 px, lane line red contour 4 px
  main_camera.py:466-487   box 2 px, label "{name} {conf:.2f}", black text on a filled class-colour tag
  main_camera.py:489-540   DTCP "virtual perspective" (NOT a calibrated projection)
  data_bus.py:684-692      contours: RETR_EXTERNAL, CHAIN_APPROX_TC89_L1, DA area > 200, LL area > 50
All coordinates in a result are in its frame_width x frame_height pixel space. The picture can have
another size: coordinates are scaled.
"""
from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

from infer.models.legacy.driverguard.mask_codec import decode_rle

log = logging.getLogger("infer.draw")

CLASS_NAMES = ['person', 'rider', 'car', 'bus', 'truck', 'bike', 'motor', 'traffic light',
               'traffic sign', 'train']
_CLASS_COLORS_RGB = [(64, 64, 255), (0, 128, 255), (64, 255, 64), (255, 200, 64), (255, 0, 200),
                     (255, 255, 0), (0, 255, 255), (128, 0, 255), (128, 255, 128), (200, 200, 200)]
CLASS_COLORS_BGR = [(b, g, r) for (r, g, b) in _CLASS_COLORS_RGB]
DA_BGR = (80, 220, 60)       # RGB (60, 220, 80)
LL_BGR = (70, 70, 240)       # RGB (240, 70, 70)
WP_BGR = (0, 220, 255)       # RGB (255, 220, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
SIM_BGR = (0, 0, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX
RLE_ENCODING = "rle-u16le-count-u8-value-rowmajor"


def nv12_to_bgr(nv12: np.ndarray) -> np.ndarray:
    """FrameLink NV12 (BT.601 limited range) -> BGR uint8 (same conversion as the models)."""
    return cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)


def _text(img, s, org, scale, color, thick=1, outline=True):
    if outline:
        cv2.putText(img, s, org, FONT, scale, BLACK, thick + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, FONT, scale, color, thick, cv2.LINE_AA)


def mask_contours(mask_entry: dict) -> list[np.ndarray]:
    """Decode one RLE mask and return its outer contours in mask pixels (old UI area rule)."""
    if mask_entry.get("encoding", RLE_ENCODING) != RLE_ENCODING:
        return []
    h, w = int(mask_entry["height"]), int(mask_entry["width"])
    if h <= 0 or w <= 0:
        return []
    m = decode_rle(bytes(mask_entry["data"]), h, w)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_L1)
    min_area = 200 if mask_entry.get("name") == "drivable_area" else 50
    return [c for c in cnts if cv2.contourArea(c) > min_area]


def _draw_masks(img, r, W, H):
    for mk in r.get("masks") or []:
        name = mk.get("name")
        if name not in ("drivable_area", "lane_line"):
            continue
        try:
            cnts = mask_contours(mk)
        except Exception as e:  # noqa: BLE001
            log.warning("mask decode failed (%s): %s", name, e)
            continue
        if not cnts:
            continue
        sx, sy = W / float(mk["width"]), H / float(mk["height"])
        scaled = [np.round(c.astype(np.float32) * (sx, sy)).astype(np.int32) for c in cnts]
        color = DA_BGR if name == "drivable_area" else LL_BGR
        base = 3 if name == "drivable_area" else 4
        thick = max(1, int(round(base * W / 1280.0)))
        cv2.polylines(img, scaled, True, color, thick, cv2.LINE_AA)


def _draw_boxes(img, r, W, H, fw, fh):
    sx, sy = W / float(fw), H / float(fh)
    scale = max(0.35, 0.5 * W / 1280.0) if W >= 640 else 0.3
    pad = 3
    for d in r.get("detections") or []:
        cid = int(d.get("class_id", 0))
        color = CLASS_COLORS_BGR[cid % len(CLASS_COLORS_BGR)]
        x1, y1 = int(round(d["x1"] * sx)), int(round(d["y1"] * sy))
        x2, y2 = int(round(d["x2"] * sx)), int(round(d["y2"] * sy))
        x2, y2 = max(x2, x1 + 2), max(y2, y1 + 2)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2 if W >= 640 else 1)
        name = d.get("class_name") or (CLASS_NAMES[cid] if 0 <= cid < len(CLASS_NAMES) else f"cls{cid}")
        label = f"{name} {float(d.get('score', 0.0)):.2f}"
        (tw, th), base = cv2.getTextSize(label, FONT, scale, 1)
        bg_h = th + base + 2
        by = max(0, y1 - bg_h)
        cv2.rectangle(img, (x1, by), (x1 + tw + 2 * pad, by + bg_h), color, -1)
        cv2.putText(img, label, (x1 + pad, by + th + 1), FONT, scale, BLACK, 1, cv2.LINE_AA)


def trajectory_pixels(points, W: int, H: int) -> list:
    """Old UI "virtual perspective" (main_camera.py:489-540). points: (lat_right_m, fwd_m).
    Returns (px, py) or None per point. NOT a calibrated projection."""
    horizon_y = H * 0.40
    k_v = (H * 0.60) * 1.5
    k_u = W * 0.30
    cx = W / 2.0
    out = []
    for lat, fwd in points:
        fwd, lat = float(fwd), float(lat)
        if fwd <= 0.2:
            out.append(None)
            continue
        py = horizon_y + k_v / fwd
        px = cx + k_u * (lat / fwd)
        if py > H - 4:
            py = H - 4
        if px < -20 or px > W + 20:
            out.append(None)
            continue
        out.append((px, py))
    return out


def _draw_trajectory(img, r, W, H):
    tr = r.get("trajectory")
    if not tr or not tr.get("points"):
        return
    pts = trajectory_pixels([(p["x"], p["y"]) for p in tr["points"]], W, H)
    s = W / 1280.0
    lw = max(2, int(round(5 * s)))
    for a, b in zip(pts, pts[1:]):
        if a is None or b is None:
            continue
        cv2.line(img, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), WP_BGR, lw, cv2.LINE_AA)
    r_out, r_in = max(4, int(round(9 * s))), max(3, int(round(7 * s)))
    fs = max(0.3, 0.45 * s)
    for i, p in enumerate(pts):
        if p is None:
            continue
        c = (int(p[0]), int(p[1]))
        cv2.circle(img, c, r_out, BLACK, -1, cv2.LINE_AA)
        cv2.circle(img, c, r_in, WP_BGR, -1, cv2.LINE_AA)
        (tw, th), _ = cv2.getTextSize(str(i + 1), FONT, fs, 1)
        cv2.putText(img, str(i + 1), (c[0] - tw // 2, c[1] + th // 2), FONT, fs, BLACK, 1, cv2.LINE_AA)
    note = "virtual perspective, not calibrated"
    if not tr.get("inputs_valid", False):
        note += "; inputs assumed"
    fs2 = max(0.28, 0.45 * s)
    (tw, th), _ = cv2.getTextSize(note, FONT, fs2, 1)
    _text(img, note, (max(2, W // 2 - tw // 2), H - 6), fs2, WP_BGR)


def draw_result(bgr: np.ndarray, results, simulated: bool | None = None,
                corner: str | None = None, copy: bool = True) -> np.ndarray:
    """Draw a list of results (canonical result dicts) on a BGR picture and return it.

    simulated: True -> big "SIMULATED" text top-left. None -> True when any result is simulated.
    corner: extra text (for example the frame seq and the result seqs), drawn below "SIMULATED".
    """
    img = bgr.copy() if copy else bgr
    H, W = img.shape[:2]
    if isinstance(results, dict):
        results = [results]
    results = list(results or [])
    for r in results:   # masks first, boxes and the trajectory on top
        _draw_masks(img, r, W, H)
    for r in results:
        fw, fh = r.get("frame_width") or W, r.get("frame_height") or H
        _draw_boxes(img, r, W, H, fw, fh)
    for r in results:
        _draw_trajectory(img, r, W, H)
    if simulated is None:
        simulated = any(r.get("simulated", True) for r in results)
    y = 0
    if simulated:
        fs = max(0.6, 1.4 * W / 1280.0)
        th_ = max(1, int(round(3 * W / 1280.0)))
        (tw, th), _ = cv2.getTextSize("SIMULATED", FONT, fs, th_)
        y = th + 8
        _text(img, "SIMULATED", (6, y), fs, SIM_BGR, th_)
    if corner:
        fs = max(0.3, 0.5 * W / 1280.0)
        for line in corner.split("\n"):
            (tw, th), _ = cv2.getTextSize(line, FONT, fs, 1)
            y += th + 6
            _text(img, line, (6, y), fs, WHITE)
    return img


def short_model(name: str) -> str:
    return name.replace("driverguard_", "")


def corner_text(frame_seq: int, results) -> str:
    parts = [f"frame {frame_seq}"]
    for r in results:
        parts.append(f"{short_model(r['model'])} {r['frame_seq']}")
    return " | ".join(parts)


def encode_jpeg(bgr: np.ndarray, quality: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


def make_snapshot(frame, cache, width: int = 320, quality: int = 80, state: str | None = None) -> bytes:
    """Newest frame -> picture 'width' px wide with the newest results of every model for that
    camera (result frame_seq <= frame seq), JPEG.
    state: FrameStore.state(cam). For "STALE" or "NO SIGNAL" the picture is made dark, no result is
    drawn, and the text "<state> - last frame N s ago" is drawn on it, so the picture is never shown
    as a live picture."""
    bgr = nv12_to_bgr(frame.nv12)
    h0, w0 = bgr.shape[:2]
    if w0 != width:
        nh = max(1, int(round(h0 * width / float(w0))))
        bgr = cv2.resize(bgr, (width, nh), interpolation=cv2.INTER_AREA)
    if state in ("STALE", "NO SIGNAL"):
        img = (bgr.astype(np.uint16) * 2 // 5).astype(np.uint8)
        img = draw_result(img, [], simulated=frame.simulated, corner=f"frame {frame.seq}", copy=False)
        H, W = img.shape[:2]
        lines = [state, f"last frame {frame.age_s():.0f} s ago"]
        fs = [max(0.6, 1.6 * W / 1280.0 * 2), max(0.35, 0.5 * W / 1280.0 * 2)]
        y = H // 2
        for line, f_ in zip(lines, fs):
            th_ = 2 if f_ >= 0.6 else 1
            (tw, th), _ = cv2.getTextSize(line, FONT, f_, th_)
            _text(img, line, (max(2, W // 2 - tw // 2), y), f_, SIM_BGR if line == state else WHITE, th_)
            y += th + 10
        return encode_jpeg(img, quality)
    rs = cache.for_frame(frame.cam, frame.seq, t_ready_ns=frame.t_ready_ns) if cache else []
    img = draw_result(bgr, rs, simulated=frame.simulated, corner=corner_text(frame.seq, rs),
                      copy=False)
    return encode_jpeg(img, quality)


class SnapshotTask:
    """Every period_s: for each camera with a newest frame, publish [b"snap.<cam>", jpeg]."""

    def __init__(self, store, cache, internal_pub, width: int = 320, period_s: float = 1.0,
                 quality: int = 80, cams=range(6)):
        self.store = store
        self.cache = cache
        self.pub = internal_pub
        self.width = int(width)
        self.period_s = float(period_s)
        self.quality = int(quality)
        self.cams = list(cams)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent = 0
        self.errors = 0

    def tick(self) -> int:
        n = 0
        for cam in self.cams:
            f = self.store.newest(cam)
            if f is None:
                continue
            try:
                st = self.store.state(cam) if hasattr(self.store, "state") else None
                jpg = make_snapshot(f, self.cache, self.width, self.quality, state=st)
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("snapshot cam%d failed", cam)
                continue
            if self.pub.send(f"snap.{cam}".encode(), jpg):
                n += 1
        self.sent += n
        return n

    def _run(self):
        nxt = time.monotonic()
        while not self._stop.is_set():
            self.tick()
            nxt += self.period_s
            d = nxt - time.monotonic()
            if d < 0:
                nxt, d = time.monotonic(), 0
            self._stop.wait(d)

    def start(self):
        self._thread = threading.Thread(target=self._run, name="snapshots", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
