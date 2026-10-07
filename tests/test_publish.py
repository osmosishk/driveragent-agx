"""Tests of the node publishers, the admin socket and the drawing (no GPU, no TensorRT).

Ports 15560-15563 only. Run:
  PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_publish.py
"""
from __future__ import annotations

import json
import os
import time

import cv2
import numpy as np
import pytest
import zmq

from common import dabus_envelope as ref
from infer.ingest.frame_store import Frame, FrameStore
from infer.ingest.metrics import CameraMetrics
from infer.models.legacy.driverguard.mask_codec import encode_rle
from infer.publish import schema as sch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "tests", "out")
P_RES, P_STAT, P_INT, P_ADM = 15560, 15561, 15562, 15563

STATUS_KEYS = {"schema", "t", "node", "cameras", "models", "publish", "link"}
NODE_KEYS = {"state", "uptime_s", "pid", "version", "simulated", "errors"}
MODEL_KEYS = {"name", "engine", "engine_version", "state", "error", "reason", "enabled", "cameras",
              "fps", "lat_ms", "gpu_mem_mb", "gpu_mem_note", "trt_match", "trt_build_device",
              "trt_device_warning", "trt_version", "load_warnings", "inputs", "outputs", "results_total"}
DEV_WARN = "WARNING: Using an engine plan file across different models of devices (fake)"
PUBLISH_KEYS = {"results_port", "status_port", "results_rate_hz", "subscribers", "results_total",
                "last_result_t"}
LINK_KEYS = {"last_frame_t", "time_since_last_frame_ms"}


@pytest.fixture()
def ctx():
    c = zmq.Context()
    yield c
    c.destroy(linger=0)


def make_frame(cam=0, seq=7, w=1280, h=720, source="test-pattern") -> Frame:
    y = np.full((h, w), 90, np.uint8)
    y[h // 2:, :] = 60
    uv = np.full((h // 2, w), 128, np.uint8)
    now = time.time_ns()
    return Frame(cam=cam, seq=seq, t_capture_ns=now - 5_000_000, t_recv_ns=now - 2_000_000,
                 t_ready_ns=now - 1_000_000, width=w, height=h, fmt="nv12", source=source,
                 nv12=np.vstack([y, uv]))


def make_result(seq=7, simulated=True, source="test-pattern", traj=False, masks=False):
    r = {"model": "driverguard_yolopx", "model_version": "yolopx_v2_fp16.engine:3412bafa057a3a76",
         "cam": 0, "frame_seq": seq, "t_capture_ns": 1_790_000_000_000_000_001,
         "t_recv_ns": 1_790_000_000_000_000_002, "t_ready_ns": 1_790_000_000_000_000_003,
         "t_result_ns": 1_790_000_000_000_000_004, "frame_width": 1280, "frame_height": 720,
         "simulated": simulated, "source": source,
         "detections": [{"class_id": 2, "class_name": "car", "score": 0.875, "x1": 100.5, "y1": 200.25,
                         "x2": 300.0, "y2": 400.0, "track_id": 0},
                        {"class_id": 0, "class_name": "person", "score": 0.5, "x1": 600, "y1": 300,
                         "x2": 640, "y2": 420, "track_id": 0}],
         "trajectory": None, "masks": [],
         "timing": {"queue_ms": 1.0, "pre_ms": 2.0, "infer_ms": 17.5, "post_ms": 3.0, "total_ms": 23.5},
         # R8 guard: control values in the dict must never reach the wire
         "throttle": 0.7, "steer": 0.1, "brake": 0.0}
    if traj:
        r["model"] = "driverguard_dtcp"
        r["detections"] = []
        r["trajectory"] = {"frame": "x lateral right m, y forward m",
                           "points": [(0.0, 2.0, 0.5), (0.1, 4.0, 1.0), (0.2, 6.0, 1.5), (0.4, 8.0, 2.0)],
                           "inputs_valid": False, "note": "display only, not for control"}
    if masks:
        da = np.zeros((720, 1280), np.uint8)
        da[450:720, 200:1100] = 1
        ll = np.zeros((720, 1280), np.uint8)
        ll[450:720, 630:650] = 1
        r["masks"] = [{"name": "drivable_area", "width": 1280, "height": 720,
                       "encoding": "rle-u16le-count-u8-value-rowmajor", "data": encode_rle(da)},
                      {"name": "lane_line", "width": 1280, "height": 720,
                       "encoding": "rle-u16le-count-u8-value-rowmajor", "data": encode_rle(ll)}]
    return r


def sub_socket(ctx, port, topics=(b"",)):
    s = ctx.socket(zmq.SUB)
    s.setsockopt(zmq.LINGER, 0)
    for t in topics:
        s.setsockopt(zmq.SUBSCRIBE, t)
    s.connect(f"tcp://127.0.0.1:{port}")
    return s


def test_runtime_schema_hashes():
    s = sch.load()
    assert s.hash["AgxPerceptionResult"] == 0xAFCAFF02
    assert s.hash["AgxInferStatus"] == 0x9086FA18
    with open(sch.DEFAULT_PROTO) as f:
        txt = f.read()
    assert ref.schema_hash(txt, "AgxPerceptionResult") == 0xAFCAFF02


def test_result_publisher(ctx):
    from infer.publish.results import ResultPublisher
    degraded = [False]
    pub = ResultPublisher("127.0.0.1", P_RES, degraded_fn=lambda: degraded[0], ctx=ctx)
    sub = sub_socket(ctx, P_RES)
    try:
        # slow joiner: publish new frames until the SUB gets one
        seq, buf = 100, None
        t_end = time.monotonic() + 5
        while time.monotonic() < t_end and buf is None:
            seq += 1
            assert pub.publish(make_result(seq=seq, masks=True)) is not None
            if sub.poll(100):
                buf = sub.recv()
        assert buf is not None, "no result received"
        parts_more = sub.getsockopt(zmq.RCVMORE)
        assert parts_more == 0                 # ONE ZMQ frame, no topic frame
        e = ref.unpack(buf)                    # RK reference: magic, version, length, CRC
        assert e["src_board"] == 1 and e["type_id"] == 5560
        assert e["flags"] & 0b001 and e["flags"] & 0b010 and not e["flags"] & 0b100
        assert e["schema_hash"] == pub.hash == sch.load().hash["AgxPerceptionResult"] == 0xAFCAFF02
        assert e["t_ptp_ns"] == 1_790_000_000_000_000_004
        assert sch.segment_count(e["payload"]) == 1
        got_seq = e["seq"]
        with sch.load().mod.AgxPerceptionResult.from_bytes(e["payload"]) as m:
            want = make_result(seq=m.frameSeq, masks=True)
            assert m.schemaVersion == 1
            assert m.model == want["model"] and m.modelVersion == want["model_version"]
            assert m.camId == 0 and m.frameSeq > 100
            assert (m.tCaptureNs, m.tAgxRecvNs, m.tAgxReadyNs, m.tAgxResultNs) == (
                want["t_capture_ns"], want["t_recv_ns"], want["t_ready_ns"], want["t_result_ns"])
            assert (m.frameWidth, m.frameHeight) == (1280, 720)
            assert m.simulated is True and m.source == "test-pattern"
            assert len(m.detections) == 2
            d = m.detections[0]
            assert (d.classId, d.className, d.trackId) == (2, "car", 0)
            assert d.score == pytest.approx(0.875) and d.x1 == pytest.approx(100.5) and d.y1 == pytest.approx(200.25)
            assert (d.x2, d.y2) == (300.0, 400.0)
            assert len(m.trajectory.points) == 0 and m.trajectory.inputsValid is False
            assert [k.name for k in m.masks] == ["drivable_area", "lane_line"]
            assert bytes(m.masks[0].data) == want["masks"][0]["data"]
            assert m.masks[0].encoding == "rle-u16le-count-u8-value-rowmajor"
            assert m.timing.inferMs == pytest.approx(17.5) and m.timing.totalMs == pytest.approx(23.5)
            fields = set(m.schema.fieldnames)
            assert not fields & {"throttle", "steer", "brake", "mu", "sigma", "predSpeed"}

        # live result, node DEGRADED: bit0 clear, bit1 + bit2 set; trajectory present
        degraded[0] = True
        assert pub.publish(make_result(seq=5000, simulated=False, source="live", traj=True)) is not None
        e2 = None
        t_end = time.monotonic() + 3
        while time.monotonic() < t_end:
            if sub.poll(200):
                x = ref.unpack(sub.recv())
                with sch.load().mod.AgxPerceptionResult.from_bytes(x["payload"]) as m:
                    if m.frameSeq == 5000:
                        e2 = x
                        assert m.simulated is False and m.source == "live"
                        got_pts = [v for p in m.trajectory.points for v in (p.x, p.y, p.tS)]
                        assert got_pts == pytest.approx([0.0, 2.0, 0.5, 0.1, 4.0, 1.0, 0.2, 6.0, 1.5,
                                                         0.4, 8.0, 2.0])
                        assert m.trajectory.note == "display only, not for control"
                        break
        assert e2 is not None
        assert e2["flags"] == 0b110 and e2["seq"] > got_seq
        # R13: simulated=False but source not live -> still simulated + bit0
        r = pub.publish(make_result(seq=5001, simulated=False, source="replay"))
        assert r["simulated"] is True
        # never re-send an old result: same (model, cam, frame) is dropped
        assert pub.publish(make_result(seq=5001, simulated=False, source="replay")) is None
        assert pub.dropped_duplicate == 1
        time.sleep(0.3)
        st = pub.stats()
        assert st["subscribers"] == 1, st
        assert st["results_total"] >= 3 and st["results_rate_hz"] > 0
    finally:
        sub.close(0)
        pub.close()


class FakeManager:
    def __init__(self):
        self.calls = []
        self._st = [
            {"name": "driverguard_yolopx", "engine": "/x/yolopx_v2_fp16.engine",
             "engine_version": "yolopx_v2_fp16.engine:3412bafa057a3a76", "state": "RUNNING",
             "error": None, "reason": None, "enabled": True, "cameras": [0, 1, 2, 3, 4, 5], "fps": 30.0,
             "lat_ms": {"pre": {"p50": 2, "p95": 3, "p99": 4}, "infer": {"p50": 17, "p95": 23, "p99": 25},
                        "post": {"p50": 3, "p95": 4, "p99": 5}, "total": {"p50": 25, "p95": 30, "p99": 35}},
             "gpu_mem_mb": 180.0, "trt_match": True, "trt_build_device": "Orin GPU (sm87)",
             "trt_device_warning": DEV_WARN, "trt_version": "10.3.0", "load_warnings": [DEV_WARN],
             "inputs": [{"name": "image", "shape": [1, 3, 384, 640], "dtype": "FLOAT"}],
             "outputs": [], "results_total": 10},
            {"name": "system1", "engine": None, "state": "OFF", "enabled": False,
             "reason": "Not a TensorRT model", "cameras": [0, 1, 2, 3, 4, 5]},
        ]

    def status(self):
        return [dict(m) for m in self._st]

    def stop_model(self, name):
        self.calls.append(("stop", name))
        return name == "driverguard_yolopx"

    def start_model(self, name):
        self.calls.append(("start", name))
        return True


class FakeIngest:
    def __init__(self):
        self.mode = "sim"
        self.cams = list(range(6))
        self.store = FrameStore(self.cams)
        self.metrics = {c: CameraMetrics(c, f"role{c}", 6000 + c, "sim", self.store) for c in self.cams}

    def put(self, f):
        self.store.put(f)
        self.metrics[f.cam].on_frame(f)

    def metrics_snapshot(self):
        return [self.metrics[c].snapshot() for c in self.cams]


def test_status_publisher(ctx):
    from infer.publish.internal import InternalPub
    from infer.publish.results import ResultPublisher
    from infer.publish.status import StatusPublisher
    from infer.status import NodeState
    node = NodeState(version="test")
    node.started = True
    ing = FakeIngest()
    ing.put(make_frame(cam=0, seq=1))
    rp = ResultPublisher("127.0.0.1", P_RES, ctx=ctx)
    ip = InternalPub("127.0.0.1", P_INT, ctx=ctx)
    sp = StatusPublisher(node, ing, FakeManager(), rp, ip, "127.0.0.1", P_STAT, ctx=ctx)
    s_stat = sub_socket(ctx, P_STAT)
    s_int = sub_socket(ctx, P_INT, (b"status",))
    try:
        got_s = got_j = None
        t_end = time.monotonic() + 5
        while time.monotonic() < t_end and (got_s is None or got_j is None):
            sp.tick()
            if got_s is None and s_stat.poll(100):
                got_s = s_stat.recv()
            if got_j is None and s_int.poll(100):
                got_j = s_int.recv_multipart()
        assert got_s is not None and got_j is not None
        e = ref.unpack(got_s)
        assert e["src_board"] == 1 and e["type_id"] == 5561
        assert e["schema_hash"] == sp.hash == 0x9086FA18
        assert e["flags"] & 0b011 == 0b011          # simulated (sim mode) + time uncertain
        with sch.load().mod.AgxInferStatus.from_bytes(e["payload"]) as m:
            assert m.schemaVersion == 1 and m.version == "test" and m.sourceMode == "sim"
            assert m.simulated is True and m.resultsPort == P_RES
            assert len(m.cameras) == 6 and m.cameras[0].state == "SIMULATED"
            assert m.cameras[0].lastFrameSeq == 1
            assert np.isnan(m.cameras[3].frameAgeMs) and m.cameras[3].state == "NO SIGNAL"
            assert [x.name for x in m.models] == ["driverguard_yolopx", "system1"]
            assert m.models[0].latencyP50Ms == pytest.approx(25.0)
            assert list(m.models[0].cameras) == [0, 1, 2, 3, 4, 5]
            assert m.nodeState == "RUNNING"
            assert len(m.temps) >= 1
        topic, payload = got_j
        assert topic == b"status"
        js = json.loads(payload.decode("utf-8"))
        assert set(js) == STATUS_KEYS and js["schema"] == "agx-infer-status/1"
        assert set(js["node"]) == NODE_KEYS and js["node"]["simulated"] is True
        assert len(js["cameras"]) == 6
        for c in js["cameras"]:
            assert "state" in c and "last_frame_t" in c and "cam" in c
        assert js["cameras"][0]["state"] == "SIMULATED"
        assert len(js["models"]) == 2
        for mm in js["models"]:
            assert set(mm) == MODEL_KEYS
            assert set(mm["lat_ms"]) == {"pre", "infer", "post", "total"}
            assert mm["gpu_mem_note"] == "estimate: engine file + activation + I/O"
        y, s1 = js["models"]
        assert y["trt_match"] is True and y["trt_build_device"] == "Orin GPU (sm87)"
        assert y["trt_device_warning"] == DEV_WARN and y["load_warnings"] == [DEV_WARN]
        assert s1["trt_build_device"] is None and s1["trt_device_warning"] is None
        assert set(js["publish"]) == PUBLISH_KEYS and js["publish"]["status_port"] == P_STAT
        assert set(js["link"]) == LINK_KEYS and js["link"]["time_since_last_frame_ms"] is not None
    finally:
        s_stat.close(0)
        s_int.close(0)
        sp.stop()
        ip.close()
        rp.close()


def test_node_state_rules():
    from infer.status import NodeState
    n = NodeState(version="t", no_signal_degraded_s=10.0)
    run = [{"name": "a", "enabled": True, "state": "RUNNING"}]
    ok = {c: "SIMULATED" for c in range(6)}
    assert n.evaluate(run, ok, 0.0) == "STARTING"
    n.started = True
    assert n.evaluate(run, ok, 1.0) == "RUNNING"
    assert n.evaluate(run + [{"name": "b", "enabled": True, "state": "FAILED", "error": "x"}], ok, 2.0) == "DEGRADED"
    assert n.evaluate([{"name": "a", "enabled": True, "state": "LOADED"}], ok, 3.0) == "ERROR"
    cams = dict(ok)
    cams[3] = "NO SIGNAL"
    assert n.evaluate(run, cams, 10.0) == "RUNNING"
    assert n.evaluate(run, cams, 20.5) == "DEGRADED"
    assert n.evaluate(run, {c: "NO SIGNAL" for c in range(6)}, 21.0) == "RUNNING"  # no other camera runs
    n.add_error("e1")
    n.add_error("e1")
    n.add_error("e2")
    assert [e.split(" ", 1)[1] for e in n.errors()] == ["e2", "e1"]


def test_admin_server(ctx):
    from infer.admin import AdminServer
    store = FrameStore(range(6))
    store.put(make_frame(cam=1, seq=41, w=704, h=396))
    store.put(make_frame(cam=1, seq=42, w=704, h=396))
    mgr = FakeManager()
    adm = AdminServer(store, mgr, "127.0.0.1", P_ADM, ctx=ctx)
    adm.start()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, 3000)
    req.connect(f"tcp://127.0.0.1:{P_ADM}")

    def ask(obj):
        req.send(obj if isinstance(obj, bytes) else json.dumps(obj).encode())
        return req.recv_multipart()

    try:
        r = json.loads(ask({"cmd": "models"})[0])
        assert r["ok"] and [m["name"] for m in r["models"]] == ["driverguard_yolopx", "system1"]
        r = json.loads(ask({"cmd": "stop", "model": "driverguard_yolopx"})[0])
        assert r["ok"] and mgr.calls[-1] == ("stop", "driverguard_yolopx")
        r = json.loads(ask({"cmd": "start", "model": "driverguard_yolopx"})[0])
        assert r["ok"] and mgr.calls[-1] == ("start", "driverguard_yolopx")
        parts = ask({"cmd": "frame", "cam": 1, "seq": 41})
        meta = json.loads(parts[0])
        assert meta["ok"] and meta["seq"] == 41 and meta["simulated"] is True
        img = cv2.imdecode(np.frombuffer(parts[1], np.uint8), cv2.IMREAD_COLOR)
        assert img.shape == (396, 704, 3)            # raw frame, full size
        parts = ask({"cmd": "newest", "cam": 1})
        assert json.loads(parts[0])["seq"] == 42 and len(parts) == 2
        r = json.loads(ask({"cmd": "frame", "cam": 1, "seq": 9999})[0])
        assert not r["ok"] and r["error"] == "frame not in recent ring"
        r = json.loads(ask({"cmd": "rm -rf /"})[0])
        assert not r["ok"] and "unknown command" in r["error"]
        r = json.loads(ask(b"not json")[0])
        assert not r["ok"] and "bad request" in r["error"]
    finally:
        req.close(0)
        adm.stop()
    with pytest.raises(ValueError):
        AdminServer(store, mgr, "0.0.0.0", P_ADM + 1, ctx=ctx)


def test_normalize_runner_names():
    """infer/runner.py (BUILD A) sends frame_w / frame_h and (x, y, t_s) tuples."""
    from infer.publish.results import normalize_result
    r = make_result(seq=3, traj=True)
    r.pop("frame_width")
    r.pop("frame_height")
    r["frame_w"], r["frame_h"] = 704, 396
    n = normalize_result(r)
    assert (n["frame_width"], n["frame_height"]) == (704, 396)
    assert n["trajectory"]["points"][3] == {"x": 0.4, "y": 8.0, "t_s": 2.0}
    assert "throttle" not in n and "steer" not in n and "brake" not in n


def test_draw_and_snapshot(ctx):
    from infer.draw import SnapshotTask, draw_result, nv12_to_bgr, trajectory_pixels
    from infer.publish.cache import ResultCache
    from infer.publish.internal import InternalPub
    from infer.publish.results import normalize_result
    f = make_frame(cam=0, seq=7)
    bgr = nv12_to_bgr(f.nv12)
    rs = [normalize_result(make_result(seq=7, masks=True)), normalize_result(make_result(seq=7, traj=True))]
    out = draw_result(bgr, rs, corner="frame 7 | yolopx 7 | dtcp 7")
    assert out.shape == bgr.shape and not np.array_equal(out, bgr)
    # box outline uses the old UI car colour RGB (64,255,64) -> BGR (64,255,64)
    assert tuple(out[300, 100]) == (64, 255, 64)
    # SIMULATED text in red in the top-left corner
    assert (out[:60, :300, 2] > 200).any()
    pts = trajectory_pixels([(0.0, 2.0), (0.0, 0.1)], 1280, 720)
    assert pts[1] is None and pts[0][0] == pytest.approx(640) and pts[0][1] == pytest.approx(288 + 648 / 2.0)
    os.makedirs(OUT, exist_ok=True)
    cv2.imwrite(os.path.join(OUT, "test_draw.jpg"), out)

    cache = ResultCache()
    for r in rs:
        r["t_ready_ns"] = f.t_ready_ns
        cache.add(r)
    later = normalize_result(make_result(seq=9))
    later["t_ready_ns"] = f.t_ready_ns
    cache.add(later)                              # newer than the frame: not drawn on frame 7
    assert [r["frame_seq"] for r in cache.for_frame(0, 7, t_ready_ns=f.t_ready_ns)] == [7, 7]
    store = FrameStore(range(6))
    store.put(f)
    ip = InternalPub("127.0.0.1", P_INT, ctx=ctx)
    sub = sub_socket(ctx, P_INT, (b"snap.",))
    snap = SnapshotTask(store, cache, ip, width=320)
    try:
        got = None
        t_end = time.monotonic() + 5
        while time.monotonic() < t_end and got is None:
            assert snap.tick() == 1                # only cam0 has a frame
            if sub.poll(200):
                got = sub.recv_multipart()
        assert got is not None and got[0] == b"snap.0" and got[1][:2] == b"\xff\xd8"
        img = cv2.imdecode(np.frombuffer(got[1], np.uint8), cv2.IMREAD_COLOR)
        assert img.shape == (180, 320, 3)
        cv2.imwrite(os.path.join(OUT, "test_snap_cam0.jpg"), img)
    finally:
        sub.close(0)
        ip.close()
