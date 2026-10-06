"""One full-size JPEG per camera with the newest AGX results drawn on their exact frame (+ JSON side file).

  python -m tools.result_jpeg --cams 0,1,2,3,4,5 [--prefix j2] [--out tests/out/da01] [--seconds 3]
      [--results tcp://127.0.0.1:5560] [--admin tcp://127.0.0.1:5563]

Needs no restart and no config change of agx-infer: it reads the results socket (5560, RK reference envelope
check) and asks the admin socket (127.0.0.1:5563, command "frame") for the decoded frame with the SAME
frameSeq (full size, JPEG q90 made from the NV12 frame). The admin socket keeps only the last few frames of
each camera, so the tool tries the newest frames first and listens again when a frame is gone.

Choice of the frame (per camera): the newest frameSeq that has a result of EVERY model that runs on that
camera (exact match). If no such frame is still in the ring, the newest frame with a result of the most models;
a model without a result for that frame is then drawn from its NEAREST frameSeq and the distance is written
in the picture and in the JSON (seq_delta). Drawing: infer/draw.py draw_result (colours, labels, masks,
"display only" trajectory text, SIMULATED label).

Output: <out>/<prefix>_cam<N>.jpg and <out>/<prefix>_cam<N>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import cv2
import zmq

from infer.draw import draw_result
from tools.result_viewer.__main__ import Viewer


def choose_frame(hist_by_model: dict, models: list[str]):
    """hist_by_model: model -> list of result dicts (one camera). Return candidate frameSeqs, best first:
    sorted by (number of models with a result for that seq, seq), both descending."""
    count = Counter()
    for m in models:
        for r in hist_by_model.get(m, ()):
            count[r["frame_seq"]] += 1
    return sorted(count, key=lambda s: (count[s], s), reverse=True), count


def pick_results(hist_by_model: dict, models: list[str], seq: int) -> list[dict]:
    """For each model: the result of frame `seq`, else the result with the nearest frameSeq (seq_delta set)."""
    out = []
    for m in models:
        q = list(hist_by_model.get(m, ()))
        if not q:
            continue
        same = [r for r in q if r["frame_seq"] == seq]
        r = dict(same[-1] if same else min(q, key=lambda x: (abs(x["frame_seq"] - seq), -x["frame_seq"])))
        r["seq_delta"] = r["frame_seq"] - seq
        out.append(r)
    return out


def side_record(cam: int, meta: dict, drawn: list[dict], models: list[str], tries: int) -> dict:
    exact = bool(drawn) and all(r["seq_delta"] == 0 for r in drawn) and len(drawn) == len(models)
    return {
        "camId": cam,
        "frame": {k: meta.get(k) for k in ("seq", "t_capture_ns", "t_recv_ns", "t_ready_ns", "width",
                                           "height", "fmt", "source", "simulated")},
        "models_expected": models,
        "models_missing": [m for m in models if m not in {r["model"] for r in drawn}],
        "exact_match": exact,
        "results": [{
            "model": r["model"], "model_version": r["model_version"], "frameSeq": r["frame_seq"],
            "seq_delta": r["seq_delta"], "tCaptureNs": r["t_capture_ns"], "tAgxResultNs": r["t_result_ns"],
            "frameWidth": r["frame_width"], "frameHeight": r["frame_height"],
            "simulated": r["simulated"], "source": r["source"],
            "detections": len(r["detections"]),
            "classes": dict(Counter(d["class_name"] for d in r["detections"])),
            "trajectory_points": len((r.get("trajectory") or {}).get("points", [])),
            "masks": [m["name"] for m in r["masks"]],
        } for r in drawn],
        "fetch_tries": tries,
        "written_unix_s": round(time.time(), 3),
    }


def corner_lines(cam: int, meta: dict, drawn: list[dict]) -> str:
    src = meta.get("source")
    sim = "SIMULATED" if meta.get("simulated") else "LIVE"
    l1 = (f"cam{cam} frame {meta.get('seq')} {meta.get('width')}x{meta.get('height')} {meta.get('fmt')} "
          f"source {src} ({sim}) tCaptureNs {meta.get('t_capture_ns')}")
    parts = []
    for r in drawn:
        d = "" if r["seq_delta"] == 0 else f" (nearest, {r['seq_delta']:+d} frames)"
        parts.append(f"{r['model']}@{r['frame_seq']}{d}")
    return l1 + "\nresults: " + (", ".join(parts) if parts else "none")


def camera_models(v: Viewer, cam: int) -> list[str]:
    """Running models for this camera, from the admin socket ("models")."""
    try:
        st = json.loads(v.admin({"cmd": "models"})[0])
    except (zmq.Again, ValueError, IndexError):
        st = {}
    names = [m["name"] for m in st.get("models", []) if m.get("state") == "RUNNING" and cam in (m.get("cameras") or [])]
    if names:
        return names
    return sorted({m for (m, c) in v.hist if c == cam})   # fallback: the models seen on the socket


def box_model(hist: dict, models: list[str]) -> str | None:
    """The model that gives the boxes: the one with the most detections in the kept results."""
    best, n_best = (models[0] if models else None), -1
    for m in models:
        n = sum(len(r["detections"]) for r in hist.get(m, ()))
        if n > n_best:
            best, n_best = m, n
    return best


def _finish(cam, meta, img, hist, models, seq, tries):
    drawn = pick_results(hist, models, seq)
    sim = bool(meta.get("simulated")) or any(r["simulated"] for r in drawn)
    pic = draw_result(img, drawn, simulated=sim, corner=corner_lines(cam, meta, drawn))
    return pic, side_record(cam, meta, drawn, models, tries)


def render(v: Viewer, cam: int, models: list[str], exact_wait_s: float = 8.0, fallback_rounds: int = 6):
    """1. Up to exact_wait_s: fetch the newest frame that has a result of EVERY model, as soon as it is seen
          (the admin ring keeps only a few frames, so wait for new results and try at once).
       2. Else: the newest fetchable frame with the most models, and among those a frame where the box model
          (YOLOPX) is exact; the other models are drawn from their nearest frame (seq_delta in the JSON)."""
    tries, tried = 0, set()
    t_end = time.monotonic() + exact_wait_s
    while time.monotonic() < t_end:
        hist = {m: list(v.hist.get((m, cam), ())) for m in models}
        cands, count = choose_frame(hist, models)
        full = [s for s in cands if count[s] == len(models) and s not in tried]
        for seq in full[:3]:
            tries += 1
            tried.add(seq)
            meta, img = v.fetch_frame(cam, seq)
            if img is not None:
                return _finish(cam, meta, img, hist, models, seq, tries)
        v.pump(0.1)
    for _ in range(fallback_rounds):
        hist = {m: list(v.hist.get((m, cam), ())) for m in models}
        cands, count = choose_frame(hist, models)
        bm = box_model(hist, models)
        bseqs = {r["frame_seq"] for r in hist.get(bm, ())}
        ranked = sorted(cands, key=lambda s: (count[s], s in bseqs, s), reverse=True)
        for seq in ranked[:6]:
            tries += 1
            meta, img = v.fetch_frame(cam, seq)
            if img is not None:
                return _finish(cam, meta, img, hist, models, seq, tries)
        v.pump(0.3)
    return None, {"camId": cam, "error": "no frame with a result was still in the admin ring",
                  "models_expected": models, "fetch_tries": tries}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="one full-size JPEG per camera with the newest results drawn")
    ap.add_argument("--cams", default="0,1,2,3,4,5")
    ap.add_argument("--prefix", default="j2")
    ap.add_argument("--out", default="tests/out/da01")
    ap.add_argument("--seconds", type=float, default=3.0, help="listen time before the first try")
    ap.add_argument("--results", default="tcp://127.0.0.1:5560")
    ap.add_argument("--admin", default="tcp://127.0.0.1:5563")
    ap.add_argument("--proto", default=None)
    a = ap.parse_args(argv)
    cams = [int(c) for c in a.cams.split(",") if c.strip() != ""]
    os.makedirs(a.out, exist_ok=True)
    v = Viewer(a.results, a.admin, a.proto)
    bad = 0
    try:
        v.pump(a.seconds)
        for cam in cams:
            models = camera_models(v, cam)
            pic, rec = render(v, cam, models)
            base = os.path.join(a.out, f"{a.prefix}_cam{cam}")
            with open(base + ".json", "w") as f:
                json.dump(rec, f, indent=1)
            if pic is None:
                bad += 1
                print(f"cam{cam}: NO PICTURE: {rec.get('error')}")
                continue
            cv2.imwrite(base + ".jpg", pic)
            fr = rec["frame"]
            res = ", ".join(f"{r['model']}@{r['frameSeq']}(d{r['seq_delta']:+d}, {r['detections']} det)"
                            for r in rec["results"])
            print(f"cam{cam}: {base}.jpg frame {fr['seq']} {fr['width']}x{fr['height']} source {fr['source']} "
                  f"simulated {fr['simulated']} exact_match {rec['exact_match']} | {res}")
    finally:
        v.close()
    errs = {k: n for k, n in v.stats.items() if k not in ("messages", "ok")}
    print("results socket:", dict(v.stats), "| envelope errors:", errs or "none")
    return 1 if (bad or errs) else 0


if __name__ == "__main__":
    sys.exit(main())
