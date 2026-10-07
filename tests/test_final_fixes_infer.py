"""Tests of the final review fixes, infer side (M3, L15, M4, M8, L8, L7, L6).

Test ports only: ZMQ 15610-15629, UDP 16510-16519. No GPU, no TensorRT engine (fake engines).
"""
import io
import json
import logging
import os
import socket
import threading
import time
from contextlib import redirect_stdout

import numpy as np
import pytest
import zmq

from common import framelink as fl
from infer.ingest.frame_store import Frame, FrameStore
from infer.ingest.framelink_rx import FrameLinkReceiver
from infer.ingest.metrics import CameraMetrics

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "scratch")   # in the repo (git-ignored)
FORBIDDEN = {"throttle", "steer", "brake", "mu", "sigma", "pred_speed", "pred_speed_mps"}


# ---- M3: MAXMSGSIZE on the PUB sockets ------------------------------------------------------------
class _Node:
    hostname, version, state, pid = "test", "test", "OK", 0

    def uptime_s(self):
        return 1.0

    def errors(self):
        return []

    def add_error(self, _t):
        pass


def test_pub_sockets_have_maxmsgsize():
    from infer.publish.internal import PUB_MAX_IN_BYTES, InternalPub
    from infer.publish.results import ResultPublisher
    from infer.publish.status import StatusPublisher

    ctx = zmq.Context()
    rp = ResultPublisher("127.0.0.1", 15610, ctx=ctx)
    ip = InternalPub("127.0.0.1", 15612, ctx=ctx)
    sp = StatusPublisher(_Node(), None, None, rp, ip, host="127.0.0.1", port=15611, ctx=ctx)
    try:
        got = {"results": rp._sock.getsockopt(zmq.MAXMSGSIZE),
               "status": sp._sock.getsockopt(zmq.MAXMSGSIZE),
               "internal": ip._sock.getsockopt(zmq.MAXMSGSIZE)}
        print("MAXMSGSIZE:", got)
        assert PUB_MAX_IN_BYTES == 4096
        assert set(got.values()) == {4096}
        # a subscriber still gets messages (subscriptions are small)
        sub = ctx.socket(zmq.SUB)
        sub.setsockopt(zmq.LINGER, 0)
        sub.setsockopt(zmq.SUBSCRIBE, b"")
        sub.setsockopt(zmq.RCVTIMEO, 200)
        sub.connect("tcp://127.0.0.1:15612")
        got_msg = None
        t_end = time.monotonic() + 3.0
        while got_msg is None and time.monotonic() < t_end:
            ip.send(b"status", b"{}")
            try:
                got_msg = sub.recv_multipart()
            except zmq.Again:
                pass
        sub.close(0)
        assert got_msg == [b"status", b"{}"]
    finally:
        sp.stop()
        ip.close()
        rp.close()
        ctx.term()


# ---- L15: rate-limited error lines ----------------------------------------------------------------
def test_rate_limited_log(caplog):
    from infer.publish.internal import RateLimitedLog

    lg = logging.getLogger("test.ratelimit")
    rl = RateLimitedLog(lg, every_s=0.2)
    with caplog.at_level(logging.ERROR, logger="test.ratelimit"):
        written = [rl.error("send", "send failed: %s", i) for i in range(5)]
        rl.error("other", "other kind")          # another kind has its own limit
        time.sleep(0.25)
        rl.error("send", "send failed: %s", 99)
    lines = [r.getMessage() for r in caplog.records]
    print("log lines:", lines)
    assert written == [True, False, False, False, False]
    assert lines == ["send failed: 0", "other kind", "send failed: 99 (4 more since last line)"]


def test_results_build_errors_rate_limited(caplog):
    from infer.publish.results import ResultPublisher

    ctx = zmq.Context()
    rp = ResultPublisher("127.0.0.1", 15613, ctx=ctx)
    try:
        with caplog.at_level(logging.ERROR, logger="infer.results"):
            for i in range(20):   # a bad box (2 values) -> build error
                assert rp.publish({"model": "m", "cam": 0, "frame_seq": i,
                                   "detections": [{"box": [1, 2]}]}) is None
        lines = [r for r in caplog.records if r.name == "infer.results" and r.levelno >= logging.ERROR]
        print("errors:", rp.errors, "log lines:", len(lines))
        assert rp.errors == 20 and len(lines) == 1
    finally:
        rp.close()
        ctx.term()


# ---- M4: FrameLink source filter ------------------------------------------------------------------
def _nv12_frame(cam, seq, w=64, h=32):
    img = np.full((h * 3 // 2, w), seq % 256, dtype=np.uint8)
    hd = fl.FrameHeader(cam=cam, fmt=fl.FMT_NV12, seq=seq, t_capture_ns=time.time_ns(), width=w,
                        height=h, stride=w, source=fl.SOURCE_TEST_PATTERN)
    return fl.pack_frame(hd, img.tobytes())


def _send_frames(src_ip, port, cam, seqs):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((src_ip, 0))
    try:
        for seq in seqs:
            for d in fl.fragments(_nv12_frame(cam, seq), cam, seq, fl.FRAG_PAYLOAD_1500):
                s.sendto(d, ("127.0.0.1", port))
            time.sleep(0.01)
    finally:
        s.close()


def _wait(pred, timeout=5.0):
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


@pytest.mark.parametrize("use_process", [True, False], ids=["rx_process", "thread"])
def test_source_filter_loopback(use_process):
    cam, port = 1, 16510 if use_process else 16511
    # 1. allowed ["127.0.0.2"]: a sender on 127.0.0.1 is dropped
    store = FrameStore(range(6))
    m = CameraMetrics(cam, "right", port, "rk", store, expect_simulated=False)
    rx = FrameLinkReceiver(cam, port, "127.0.0.1", store, m, expect_simulated=False,
                           use_process=use_process, ring_slots=4, max_frame=65536,
                           allowed_sources=["127.0.0.2"])
    rx.start()
    try:
        _send_frames("127.0.0.1", port, cam, range(1, 6))
        # the receiver flushes its counters itself (socket timeout 0.1 s / stats of the process)
        assert _wait(lambda: m.c.get("foreign_source_drops", 0) >= 5)
        time.sleep(0.3)
        drops = m.c.get("foreign_source_drops", 0)
        print(f"{'process' if use_process else 'thread'} allowed 127.0.0.2, sender 127.0.0.1: "
              f"foreign_source_drops={drops} frames={m.frames_total} datagrams={m.datagrams}")
        assert drops >= 5 and store.newest(cam) is None and m.datagrams == 0
        # a sender on 127.0.0.2 is accepted by the same receiver
        _send_frames("127.0.0.2", port, cam, range(10, 13))
        assert _wait(lambda: store.newest(cam) is not None and store.newest(cam).seq == 12)
    finally:
        rx.stop()
    # 2. allowed ["127.0.0.1"]: the same sender is accepted
    store = FrameStore(range(6))
    m = CameraMetrics(cam, "right", port, "rk", store, expect_simulated=False)
    rx = FrameLinkReceiver(cam, port, "127.0.0.1", store, m, expect_simulated=False,
                           use_process=use_process, ring_slots=4, max_frame=65536,
                           allowed_sources=["127.0.0.1"])
    rx.start()
    try:
        _send_frames("127.0.0.1", port, cam, range(1, 6))
        assert _wait(lambda: store.newest(cam) is not None and store.newest(cam).seq == 5)
        time.sleep(0.3)
        print(f"allowed 127.0.0.1: frames={m.frames_total} drops={m.c.get('foreign_source_drops')}")
        assert m.c.get("foreign_source_drops", 0) == 0
    finally:
        rx.stop()


def test_ingest_allowed_sources_config(caplog):
    """The board addresses come from data/paired_boards.json (Ingest(allowed_sources=...)); the old config key
    rk_allowed_sources is not used and not in config/sources.yaml any more."""
    from infer.ingest.ingest import Ingest, parse_allowed_sources

    base = {"cameras": [{"cam": c, "port": 16512 + c, "enabled": c == 0} for c in range(6)],
            "rx_process": False, "decoder_prestart": False}
    # rk mode, no address: accept all (INFO at start; the paired boards reader writes the WARNING)
    ing = Ingest(dict(base, bind_host={"rk": "127.0.0.1"}), mode="rk")
    assert ing.allowed_sources == () and ing.sources[0].allowed_sources == ()
    with caplog.at_level(logging.INFO, logger="infer.ingest"):
        ing.start()
        ing.stop()
    assert any("no paired board address" in r.getMessage() for r in caplog.records)
    snap = ing.metrics_snapshot()
    assert all(s["foreign_source_drops"] == 0 for s in snap)
    # rk mode with addresses; the old key is ignored (INFO line)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="infer.ingest"):
        ing = Ingest(dict(base, rk_allowed_sources=["10.9.9.9"]), mode="rk", allowed_sources=["10.42.0.2"])
    assert ing.sources[0].allowed_sources == ("10.42.0.2",)
    assert any("rk_allowed_sources is not used" in r.getMessage() for r in caplog.records)
    # sim mode: no filter (loopback bind)
    ing = Ingest(dict(base), mode="sim", allowed_sources=["10.42.0.2"])
    assert ing.allowed_sources == () and ing.bind_host == "127.0.0.1"
    assert ing.set_allowed_sources(["10.42.0.3"]) is False and ing.sources[0].allowed_sources == ()
    # a bad entry is an error (fail closed)
    with pytest.raises(ValueError):
        parse_allowed_sources(["10.42.0.300"])
    with pytest.raises(ValueError):
        parse_allowed_sources(["::1"])
    # the config template does not have the old key any more
    import yaml
    cfg = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config", "templates", "sources.yaml")))
    assert "rk_allowed_sources" not in cfg


def test_ingest_role_rk_only_in_rk_mode():
    """J1: in rk mode the camera label is role_rk (DA01 rk-camd camera); in sim mode it stays role."""
    from infer.ingest.ingest import ROLES, Ingest

    cams = [{"cam": 0, "role": "front", "role_rk": "front", "port": 16530, "enabled": False},
            {"cam": 1, "role": "right", "role_rk": "fisheye-190 CAM2 (role unconfirmed)", "port": 16531,
             "enabled": False},
            {"cam": 2, "role": "left", "port": 16532, "enabled": False}]          # no role_rk
    base = {"cameras": cams, "rx_process": False, "decoder_prestart": False}
    rk = {s["cam"]: s["role"] for s in Ingest(dict(base), mode="rk").metrics_snapshot()}
    sim = {s["cam"]: s["role"] for s in Ingest(dict(base), mode="sim").metrics_snapshot()}
    assert rk[1] == "fisheye-190 CAM2 (role unconfirmed)" and rk[0] == "front"
    assert rk[2] == "left" and rk[3] == ROLES[3]        # fallback: role, then ROLES
    assert sim[1] == "right" and sim[2] == "left" and sim[3] == ROLES[3]


# ---- M8: automatic restart of a FAILED model -------------------------------------------------------
class _T:
    def __init__(self, name, shape):
        self.name, self.shape, self.dtype = name, shape, "float32"


class FakeEngine:
    path = "/nonexistent/fake.engine"
    version_tag = "fake-1"
    trt_match = True
    trt_build_device = "Orin GPU (sm87)"
    trt_device_warning = "WARNING: Using an engine plan file across different models of devices (fake)"
    trt_version = "fake"
    load_warnings = [trt_device_warning]

    def inputs(self):
        return [_T("x", (1, 4))]

    def outputs(self):
        return [_T("y", (1, 4))]

    def gpu_bytes_estimate(self):
        return 0

    def new_slot(self):
        return self

    def infer(self, inputs):
        return {"y": np.zeros((1, 4), np.float32), "mu": np.zeros(2), "sigma": np.zeros(2)}, 0.1


class FakeAdapter:
    """Fails the first `fail_n` postprocess calls (class counter), then works."""
    ENGINE_OUTPUTS = ("y",)
    fail_n = 3
    calls = 0
    seen_keys: set = set()
    lock = threading.Lock()

    def __init__(self, cfg, eng):
        pass

    def dummy_inputs(self):
        return {"x": np.zeros((1, 4), np.float32)}

    def preprocess(self, frame):
        return {"x": np.zeros((1, 4), np.float32)}, {}

    def postprocess(self, outs, frame, ctx):
        cls = type(self)
        with cls.lock:
            cls.calls += 1
            n = cls.calls
            cls.seen_keys |= set(outs)
        if n <= cls.fail_n:
            raise RuntimeError(f"fake worker error {n}")
        return {"detections": [], "trajectory": None, "masks": []}


class Feeder:
    def __init__(self, store, cam=0, fps=50.0):
        self.store, self.cam, self.period = store, cam, 1.0 / fps
        self.seq = 0
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        nv = np.zeros((48, 64), np.uint8)
        while not self._stop.is_set():
            self.seq += 1
            now = time.time_ns()
            self.store.put(Frame(self.cam, self.seq, now, now, now, 64, 32, "nv12", "test-pattern", nv))
            self._stop.wait(self.period)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self.t.join()


def _mgr(monkeypatch, fail_n, backoff=0.2, backoff_max=0.8, engine=True):
    from infer.models import manager as mm

    adapter = type("FA", (FakeAdapter,), {"fail_n": fail_n, "calls": 0, "seen_keys": set(),
                                          "lock": threading.Lock()})
    monkeypatch.setattr(mm, "get_adapter_class", lambda name: adapter)

    def try_engines(self, e):
        if not engine:
            return None, ["fake: engine does not load"]
        e.engine_source = "config"
        return FakeEngine(), []

    monkeypatch.setattr(mm.ModelManager, "_try_engines", try_engines)
    store = FrameStore(range(6))
    results = []
    cfg = [{"name": "fake", "enabled": True, "engine": "/nonexistent/fake.engine", "adapter": "fake",
            "cameras": [0], "workers": 1, "max_fps_per_camera": 50}]
    mgr = mm.ModelManager(cfg, store, results.append, engines_dir=os.path.join(SCRATCH, "engines_t"),
                          warmup=False, restart_backoff_s=backoff, restart_backoff_max_s=backoff_max)
    return mgr, store, results, adapter


def test_failed_model_restarts_automatically(monkeypatch, caplog):
    mgr, store, results, adapter = _mgr(monkeypatch, fail_n=3)
    states = []
    with caplog.at_level(logging.WARNING, logger="agx.infer.manager"), Feeder(store):
        mgr.start()
        try:
            assert _wait(lambda: mgr.status()[0]["state"] == "FAILED", 5)
            st = mgr.status()[0]
            states.append((st["state"], st["auto_restarts"], st["restart_in_s"]))
            assert st["auto_restarts"] == 0 and st["restart_in_s"] is not None
            assert _wait(lambda: mgr.status()[0]["state"] == "RUNNING" and len(results) >= 5, 5)
            st = mgr.status()[0]
            states.append((st["state"], st["auto_restarts"], st["restart_in_s"]))
        finally:
            mgr.stop()
    print("states:", states, "results:", len(results))
    assert st["auto_restarts"] == 1 and st["error"] is None
    # the status carries the engine's trt fields; the device warning does not change trt_match
    assert st["trt_match"] is True and st["trt_build_device"] == FakeEngine.trt_build_device
    assert st["trt_device_warning"] == FakeEngine.trt_device_warning
    assert any("automatic restart 1" in r.getMessage() for r in caplog.records)
    # L8: the adapter got only its ENGINE_OUTPUTS (no mu / sigma)
    assert adapter.seen_keys == {"y"}


def test_backoff_doubles_up_to_max(monkeypatch):
    mgr, store, _results, _a = _mgr(monkeypatch, fail_n=10 ** 9, backoff=0.1, backoff_max=0.4)
    e = mgr.models["fake"]
    with Feeder(store):
        mgr.start()
        try:
            assert _wait(lambda: e.auto_restarts >= 3, 10)
        finally:
            mgr.stop()
    print("auto_restarts:", e.auto_restarts, "backoff now:", e.restart_backoff)
    assert e.restart_backoff == pytest.approx(0.4)
    assert e.restart_due is None and e.state in ("FAILED", "LOADED")   # stop(): no more restarts


def test_manual_stop_is_not_restarted(monkeypatch):
    mgr, store, _results, _a = _mgr(monkeypatch, fail_n=10 ** 9, backoff=0.5)
    with Feeder(store):
        mgr.start()
        try:
            assert _wait(lambda: mgr.status()[0]["state"] == "FAILED", 5)
            assert mgr.stop_model("fake")["ok"]
            time.sleep(1.2)
            st = mgr.status()[0]
        finally:
            mgr.stop()
    print("after stop_model:", st["state"], st["auto_restarts"], st["restart_in_s"])
    assert st["state"] == "OFF" and st["auto_restarts"] == 0 and st["restart_in_s"] is None


def test_load_error_is_not_restarted(monkeypatch):
    mgr, store, _results, _a = _mgr(monkeypatch, fail_n=0, backoff=0.1, engine=False)
    mgr.start()
    try:
        time.sleep(0.6)
        st = mgr.status()[0]
    finally:
        mgr.stop()
    print("load error:", st["state"], st["error"], st["auto_restarts"])
    assert st["state"] == "FAILED" and st["error"].startswith("load:")
    assert st["auto_restarts"] == 0 and st["restart_in_s"] is None


# ---- L8: DTCP postprocess gets only pred_wp --------------------------------------------------------
def test_dtcp_postprocess_gets_only_pred_wp():
    from infer.models.adapters.dtcp_v1 import DtcpV1Adapter
    from infer.runner import FrameScheduler, ModelMetrics, ModelWorker, adapter_outputs

    seen = []

    class Spy(DtcpV1Adapter):
        def preprocess(self, frame):
            return {"image": np.zeros((1, 3, 256, 928), np.float32)}, {}

        def postprocess(self, outputs, frame, ctx):
            seen.append(sorted(outputs))
            return super().postprocess(outputs, frame, ctx)

    class Slot:
        def infer(self, inputs):
            return {"pred_wp": np.arange(8, dtype=np.float32).reshape(1, 4, 2),
                    "mu": np.zeros((1, 2)), "sigma": np.ones((1, 2)),
                    "pred_speed": np.ones((1, 1))}, 1.0

    class Entry:
        name = "driverguard_dtcp"
        cameras = [0]
        adapter = Spy({"options": {"command": 2}}, None)
        engine = FakeEngine()
        scheduler = FrameScheduler([0], None)
        metrics = ModelMetrics()
        stop_event = threading.Event()

        def report_error(self, text, fatal=False):
            raise AssertionError(text)

    store = FrameStore(range(6))
    results = []
    w = ModelWorker(Entry(), 0, Slot(), store, results.append)
    now = time.time_ns()
    f = Frame(0, 1, now, now, now, 64, 32, "nv12", "test-pattern", np.zeros((48, 64), np.uint8))
    w._process(f, None)
    print("postprocess got:", seen, "result trajectory note:", results[0]["trajectory"]["note"])
    assert seen == [["pred_wp"]]
    assert len(results) == 1 and len(results[0]["trajectory"]["points"]) == 4

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                yield from walk(v)
    assert not (FORBIDDEN & set(walk(results[0])))
    assert set(adapter_outputs(Entry.adapter, Slot().infer({})[0])) == {"pred_wp"}


# ---- L7: snapshot trajectory text -------------------------------------------------------------------
def test_trajectory_text_says_display_only(monkeypatch):
    from infer import draw

    texts = []
    real = draw._text
    monkeypatch.setattr(draw, "_text", lambda img, s, *a, **k: (texts.append(s), real(img, s, *a, **k)))
    r = {"model": "driverguard_dtcp", "simulated": True, "detections": [], "masks": [],
         "trajectory": {"frame": "x", "points": [{"x": 0.0, "y": 5.0 * i, "t_s": 0.5 * i}
                                                 for i in range(1, 5)], "inputs_valid": False}}
    draw.draw_result(np.zeros((180, 320, 3), np.uint8), [r])
    print("texts:", texts)
    assert "display only, not for control" in texts
    assert any("virtual perspective" in t for t in texts)


# ---- L6: model_ctl list shows the source -----------------------------------------------------------
def _fake_admin(ctx, port, models, stop):
    s = ctx.socket(zmq.REP)
    s.setsockopt(zmq.LINGER, 0)
    s.bind(f"tcp://127.0.0.1:{port}")
    s.setsockopt(zmq.RCVTIMEO, 100)
    while not stop.is_set():
        try:
            s.recv()
        except zmq.Again:
            continue
        s.send(json.dumps({"ok": True, "models": models}).encode())
    s.close(0)


def _fake_status(ctx, port, status, stop):
    s = ctx.socket(zmq.PUB)
    s.setsockopt(zmq.LINGER, 0)
    s.bind(f"tcp://127.0.0.1:{port}")
    while not stop.wait(0.05):
        s.send_multipart([b"status", json.dumps(status).encode()])
    s.close(0)


def _run_ctl(argv):
    from tools import model_ctl
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = model_ctl.main(argv)
    return rc, buf.getvalue()


def test_model_ctl_list_source_column():
    models = [{"name": "yolopx", "state": "RUNNING", "enabled": True, "cameras": [0, 1], "fps": 9.5,
               "lat_ms": {"total": {"p50": 12.0}}, "results_total": 10}]
    status = {"schema": "agx-infer-status/1", "node": {"simulated": True},
              "cameras": [{"cam": c, "mode": "sim", "simulated": True} for c in range(6)]}
    ctx = zmq.Context()
    stop = threading.Event()
    ths = [threading.Thread(target=_fake_admin, args=(ctx, 15620, models, stop), daemon=True),
           threading.Thread(target=_fake_status, args=(ctx, 15621, status, stop), daemon=True)]
    for t in ths:
        t.start()
    try:
        rc, out = _run_ctl(["--admin", "tcp://127.0.0.1:15620", "--status", "tcp://127.0.0.1:15621",
                            "list"])
        print(out)
        lines = out.splitlines()
        assert rc == 0
        assert lines[0].startswith("NODE SOURCE MODE: sim") and "INPUT: SIMULATED" in lines[0]
        assert "SOURCE" in lines[1]
        assert "yolopx" in lines[2] and "SIMULATED" in lines[2]
        # no status data: UNKNOWN, with the text to treat it as SIMULATED
        rc, out = _run_ctl(["--admin", "tcp://127.0.0.1:15620", "--status", "tcp://127.0.0.1:15622",
                            "list"])
        print(out)
        assert rc == 0 and "UNKNOWN" in out.splitlines()[0] and "SIMULATED" in out.splitlines()[0]
        assert "UNKNOWN" in out.splitlines()[2]
    finally:
        stop.set()
        for t in ths:
            t.join(2)
        ctx.term()


def test_model_source_rk_live():
    from tools.model_ctl import model_source, node_source
    st = {"node": {"simulated": True},
          "cameras": [{"cam": 0, "mode": "rk", "simulated": False},
                      {"cam": 3, "mode": "rk", "simulated": True}]}
    mode, ns, cs = node_source(st)
    assert mode == "rk"
    assert model_source({"cameras": [0]}, mode, ns, cs) == "LIVE"
    assert model_source({"cameras": [0, 3]}, mode, ns, cs) == "SIMULATED"
