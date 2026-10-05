"""Result viewer: check the results socket like the RK3588 does and draw the results on the exact frames.

  python -m tools.result_viewer --seconds 10 --out tests/out/viewer \
      [--results tcp://127.0.0.1:5560] [--admin tcp://127.0.0.1:5563]

1. SUB to the results socket for N seconds. Every message: RK reference envelope check
   (common.dabus_envelope.unpack: magic, version, length, CRC-32C), type_id 5560, src_board 1,
   schema hash = runtime hash of proto/agx_infer.capnp AgxPerceptionResult, then capnp decode.
2. For each camera: the newest driverguard_yolopx result -> request that exact frame (cam, frame_seq)
   from the admin socket (raw JPEG). When the frame is not in the ring any more, use a newer result.
3. Draw every model result with the same frame_seq (DTCP: the nearest seq on cam0, named in the
   picture), write <out>/cam<N>.jpg (full size) and <out>/all.jpg (3x2 contact sheet), print a table.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict, deque

import capnp  # noqa: F401  (pycapnp must be imported before the schema load)
import cv2
import numpy as np
import zmq

from common import dabus_envelope as ref
from infer.draw import draw_result
from infer.publish import schema as sch

YOLOPX = "driverguard_yolopx"
DTCP = "driverguard_dtcp"
TILE_W, TILE_H = 640, 360


def result_to_dict(m, flags: int) -> dict:
    tr = m.trajectory
    pts = [{"x": p.x, "y": p.y, "t_s": p.tS} for p in tr.points]
    return {
        "model": m.model, "model_version": m.modelVersion, "cam": m.camId, "frame_seq": m.frameSeq,
        "t_capture_ns": m.tCaptureNs, "t_recv_ns": m.tAgxRecvNs, "t_ready_ns": m.tAgxReadyNs,
        "t_result_ns": m.tAgxResultNs, "frame_width": m.frameWidth, "frame_height": m.frameHeight,
        "simulated": m.simulated, "source": m.source, "flags": flags,
        "detections": [{"class_id": d.classId, "class_name": d.className, "score": d.score,
                        "x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2, "track_id": d.trackId}
                       for d in m.detections],
        "trajectory": ({"frame": tr.frame, "points": pts, "inputs_valid": tr.inputsValid,
                        "note": tr.note} if pts else None),
        "masks": [{"name": k.name, "width": k.width, "height": k.height, "encoding": k.encoding,
                   "data": bytes(k.data)} for k in m.masks],
        "timing": {"total_ms": m.timing.totalMs},
    }


class Viewer:
    def __init__(self, results_ep: str, admin_ep: str, proto: str | None = None):
        self.schema = sch.load(proto)
        self.want_hash = self.schema.hash["AgxPerceptionResult"]
        self.ctx = zmq.Context()
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.LINGER, 0)
        self.sub.setsockopt(zmq.RCVHWM, 2000)
        self.sub.setsockopt(zmq.SUBSCRIBE, b"")
        self.sub.connect(results_ep)
        self.admin_ep = admin_ep
        self.hist: dict[tuple[str, int], deque] = defaultdict(lambda: deque(maxlen=200))
        self.stats = Counter()
        self.flag_bits = Counter()

    def close(self):
        self.sub.close(0)
        self.ctx.destroy(linger=0)

    def _handle(self, buf: bytes) -> None:
        self.stats["messages"] += 1
        try:
            e = ref.unpack(buf)
        except ValueError as ex:
            self.stats[f"bad envelope: {ex}"] += 1
            return
        if e["type_id"] != sch.TYPE_RESULT:
            self.stats[f"bad type_id {e['type_id']}"] += 1
            return
        if e["src_board"] != ref.SRC_AGX:
            self.stats[f"bad src_board {e['src_board']}"] += 1
            return
        if e["schema_hash"] != self.want_hash:
            self.stats[f"schema mismatch 0x{e['schema_hash']:08x}"] += 1
            return
        try:
            with self.schema.mod.AgxPerceptionResult.from_bytes(e["payload"]) as m:
                r = result_to_dict(m, e["flags"])
        except Exception as ex:  # noqa: BLE001
            self.stats[f"capnp decode error: {ex}"] += 1
            return
        self.stats["ok"] += 1
        f = e["flags"]
        self.flag_bits["bit0 source_is_replay"] += bool(f & ref.FLAG_SOURCE_IS_REPLAY)
        self.flag_bits["bit1 time_uncertain"] += bool(f & ref.FLAG_TIME_UNCERTAIN)
        self.flag_bits["bit2 degraded"] += bool(f & ref.FLAG_DEGRADED)
        if r["simulated"] and not f & ref.FLAG_SOURCE_IS_REPLAY:
            self.stats["R13 violation: simulated without flag bit0"] += 1
        self.hist[(r["model"], r["cam"])].append(r)

    def pump(self, seconds: float) -> None:
        t_end = time.monotonic() + seconds
        while True:
            rest = t_end - time.monotonic()
            if rest <= 0:
                break
            if not self.sub.poll(int(min(rest, 0.2) * 1000)):
                continue
            while True:
                try:
                    buf = self.sub.recv(zmq.NOBLOCK)
                except zmq.Again:
                    break
                self._handle(buf)
                if time.monotonic() >= t_end:
                    break

    def admin(self, req: dict, timeout_ms: int = 3000) -> list[bytes]:
        s = self.ctx.socket(zmq.REQ)
        s.setsockopt(zmq.LINGER, 0)
        s.setsockopt(zmq.RCVTIMEO, timeout_ms)
        s.connect(self.admin_ep)
        try:
            s.send(json.dumps(req).encode())
            return s.recv_multipart()
        finally:
            s.close(0)

    def fetch_frame(self, cam: int, seq: int):
        parts = self.admin({"cmd": "frame", "cam": cam, "seq": seq})
        meta = json.loads(parts[0])
        if not meta.get("ok") or len(parts) < 2:
            return meta, None
        img = cv2.imdecode(np.frombuffer(parts[1], np.uint8), cv2.IMREAD_COLOR)
        return meta, img

    def render_cam(self, cam: int, tries: int = 4):
        """-> (row dict, BGR picture or None)."""
        row = {"cam": cam, "frame_seq": None, "detections": 0, "classes": "", "simulated": None,
               "models": "", "note": ""}
        for attempt in range(tries):
            q = self.hist.get((YOLOPX, cam))
            if not q:
                row["note"] = f"no {YOLOPX} result"
                return row, None
            r = q[-1]
            try:
                meta, img = self.fetch_frame(cam, r["frame_seq"])
            except zmq.Again:
                row["note"] = "admin socket: no reply"
                return row, None
            if img is not None:
                break
            row["note"] = f"frame {r['frame_seq']} gone ({meta.get('error')})"
            self.pump(0.3)   # get newer results, then use the newest one
        else:
            return row, None
        seq = r["frame_seq"]
        draw = []
        for (model, c), hq in self.hist.items():
            if c != cam:
                continue
            same = [x for x in hq if x["frame_seq"] == seq]
            if same:
                draw.append(same[-1])
        used = ", ".join(f"{d['model']}@{d['frame_seq']}" for d in draw)
        extra = ""
        if cam == 0 and not any(d["model"] == DTCP for d in draw) and self.hist.get((DTCP, 0)):
            near = min(self.hist[(DTCP, 0)], key=lambda x: abs(x["frame_seq"] - seq))
            draw.append(near)
            extra = f"dtcp from frame {near['frame_seq']} (nearest; frame {seq} has none)"
            used += f", {DTCP}@{near['frame_seq']} (nearest)"
        corner = f"cam{cam} frame {seq} | results: " + used
        if extra:
            corner += "\n" + extra
        sim = bool(meta.get("simulated")) or any(d["simulated"] for d in draw)
        out = draw_result(img, draw, simulated=sim, corner=corner)
        det = [d for d in draw if d["model"] == YOLOPX]
        cls = Counter(x["class_name"] for d in det for x in d["detections"])
        row.update(frame_seq=seq, detections=sum(len(d["detections"]) for d in det),
                   classes=", ".join(f"{k} x{v}" for k, v in cls.most_common()),
                   simulated=sim, models=used, note=(row["note"] + "; " if row["note"] else "") + extra)
        return row, out


def contact_sheet(pics: dict) -> np.ndarray:
    sheet = np.zeros((TILE_H * 2, TILE_W * 3, 3), np.uint8)
    for cam in range(6):
        y, x = (cam // 3) * TILE_H, (cam % 3) * TILE_W
        img = pics.get(cam)
        if img is None:
            tile = np.zeros((TILE_H, TILE_W, 3), np.uint8)
            cv2.putText(tile, f"cam{cam}: no frame", (20, TILE_H // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (200, 200, 200), 2, cv2.LINE_AA)
        else:
            tile = cv2.resize(img, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)
        sheet[y:y + TILE_H, x:x + TILE_W] = tile
    return sheet


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="check the AGX results socket and draw results on their frames")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--out", default="tests/out/viewer")
    ap.add_argument("--results", default="tcp://127.0.0.1:5560")
    ap.add_argument("--admin", default="tcp://127.0.0.1:5563")
    ap.add_argument("--proto", default=None)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    v = Viewer(a.results, a.admin, a.proto)
    try:
        print(f"SUB {a.results} for {a.seconds:.0f} s (expected schema hash 0x{v.want_hash:08x})")
        v.pump(a.seconds)
        pics, rows = {}, []
        for cam in range(6):
            row, img = v.render_cam(cam)
            rows.append(row)
            if img is not None:
                pics[cam] = img
                cv2.imwrite(os.path.join(a.out, f"cam{cam}.jpg"), img)
        cv2.imwrite(os.path.join(a.out, "all.jpg"), contact_sheet(pics))
    finally:
        v.close()
    print("messages:", dict(v.stats))
    print("flags set (count):", dict(v.flag_bits))
    print("results per (model, cam) kept:", {f"{k[0]}/cam{k[1]}": len(q) for k, q in sorted(v.hist.items())})
    print(f"{'CAM':3} {'FRAME SEQ':>9} {'DETS':>4} {'SIM':5} CLASSES / MODELS / NOTE")
    for r in rows:
        print(f"{r['cam']:3} {str(r['frame_seq']):>9} {r['detections']:>4} {str(r['simulated']):5} "
              f"{r['classes'] or '-'} | {r['models'] or '-'} | {r['note'] or ''}")
    print(f"wrote {len(pics)} camera pictures + all.jpg to {os.path.abspath(a.out)}")
    bad = sum(n for k, n in v.stats.items() if k not in ("messages", "ok"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
