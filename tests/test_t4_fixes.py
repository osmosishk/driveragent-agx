"""Tests for the T4 review fixes (CPU only, no engine, no GPU). Port 15590 only.

  PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_t4_fixes.py
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import zmq

from common import envelope as env
from infer.ingest.frame_store import Frame, FrameStore

P_RES = 15590


def frame(cam=0, seq=1, t_cap=None, age_s=0.0, w=64, h=32):
    now = time.time_ns()
    nv12 = np.full((h * 3 // 2, w), 128, np.uint8)
    return Frame(cam=cam, seq=seq, t_capture_ns=t_cap if t_cap is not None else now, t_recv_ns=now,
                 t_ready_ns=now, width=w, height=h, fmt="nv12", source="test-pattern", nv12=nv12,
                 t_ready_mono=time.monotonic() - age_s)


# ---- robustness 1: old-stream result after a sender restart --------------------------------------
def test_scheduler_restart_race_old_stream_result_refused():
    from infer.runner import FrameScheduler
    s = FrameScheduler([0], None)
    a, ea = s.claim_epoch([frame(seq=9000, t_cap=1_000)], time.monotonic())
    assert a.seq == 9000
    b, eb = s.claim_epoch([frame(seq=1, t_cap=2_000)], time.monotonic())   # sender restart
    assert b.seq == 1 and eb == ea + 1 and s.restarts == 1
    assert s.mark_emitted(0, 1, eb) is True
    assert s.mark_emitted(0, 9000, ea) is False          # old stream: never after the new one
    nxt = [s.mark_emitted(0, q, eb) for q in range(2, 8)]
    assert nxt == [True] * 6                             # the new stream continues
    assert s.mark_emitted(0, 7, eb) is False             # no re-send


def test_scheduler_claim_compat():
    from infer.runner import FrameScheduler
    s = FrameScheduler([0, 1], None)
    assert s.claim([frame(cam=1, seq=3)], time.monotonic()).seq == 3
    assert s.claim([frame(cam=1, seq=3)], time.monotonic()) is None
    assert s.mark_emitted(1, 3) is True and s.mark_emitted(1, 3) is False


# ---- robustness 4: stale rule at result time ------------------------------------------------------
class _Adapter:
    def preprocess(self, f):
        return {"x": np.zeros(1, np.float32)}, {}

    def postprocess(self, outs, f, ctx):
        return {"detections": [], "trajectory": None, "masks": []}


def _entry():
    from infer.runner import FrameScheduler, ModelMetrics
    return SimpleNamespace(name="m", adapter=_Adapter(), engine=SimpleNamespace(version_tag="t"),
                           scheduler=FrameScheduler([0], None), metrics=ModelMetrics(),
                           stop_event=threading.Event(), report_error=lambda *a, **k: None)


def test_worker_drops_result_of_stale_frame():
    from infer.runner import ModelWorker
    e = _entry()
    got = []
    slot = SimpleNamespace(infer=lambda inputs: ({"y": np.zeros(1)}, 1.0))
    w = ModelWorker(e, 0, slot, FrameStore(cams=[0]), got.append)
    f_old, ep = e.scheduler.claim_epoch([frame(seq=5, age_s=0.6)], time.monotonic())
    w._process(f_old, ep)
    assert got == [] and e.metrics.results_dropped_stale == 1
    f_new, ep = e.scheduler.claim_epoch([frame(seq=6, age_s=0.01)], time.monotonic())
    w._process(f_new, ep)
    assert [r["frame_seq"] for r in got] == [6] and e.metrics.results_total == 1


# ---- robustness 2: a clean stop does not show ERROR ----------------------------------------------
def test_nodestate_keeps_state_while_stopping():
    from infer.status import NodeState
    n = NodeState(version="x")
    n.started = True
    run = [{"name": "a", "enabled": True, "state": "RUNNING"}]
    assert n.evaluate(run, {0: "SIMULATED"}) == "RUNNING"
    n.stopping = True
    loaded = [{"name": "a", "enabled": True, "state": "LOADED"}]
    assert n.evaluate(loaded, {0: "NO SIGNAL"}) == "RUNNING"
    assert n.errors() == []


# ---- robustness 3: SIGTERM during start ---------------------------------------------------------
def test_manager_start_should_stop_loads_nothing(tmp_path):
    from infer.models.manager import ModelManager
    cfg = [{"name": "a", "enabled": True, "engine": str(tmp_path / "missing.engine"),
            "adapter": "yolopx_v2", "cameras": [0]}]
    m = ModelManager(cfg, FrameStore(cams=[0]), lambda r: None, str(tmp_path))
    m.start(should_stop=lambda: True)
    st = m.status()[0]
    assert st["state"] != "FAILED" and st["error"] is None   # no load was tried
    m.stop()
    assert m.status()[0]["state"] == "OFF"


# ---- parity 1: DTCP inputs_valid ------------------------------------------------------------------
def test_dtcp_inputs_valid_false_with_config_speed():
    from infer.models.adapters.dtcp_v1 import DtcpV1Adapter
    a = DtcpV1Adapter({"options": {"ego_speed_mps": 5.0}}, None)
    out = a.postprocess({"pred_wp": np.array([[0, 1], [0, 2], [0, 3], [0, 4]], np.float32)}, None, {})
    assert out["trajectory"]["inputs_valid"] is False
    assert "fixed value from config" in out["trajectory"]["note"]


# ---- protocol 1: results seq in order with many producer threads --------------------------------
def test_results_seq_in_order_many_threads():
    from infer.publish.results import ResultPublisher
    ctx = zmq.Context()
    pub = ResultPublisher("127.0.0.1", P_RES, sndhwm=100000, queue_max=100000, ctx=ctx)
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt(zmq.SUBSCRIBE, b"")
    sub.connect(f"tcp://127.0.0.1:{P_RES}")

    def res(model, cam, seq):
        now = time.time_ns()
        return {"model": model, "model_version": "v", "cam": cam, "frame_seq": seq,
                "t_capture_ns": now, "t_recv_ns": now, "t_ready_ns": now, "t_result_ns": now,
                "frame_width": 64, "frame_height": 32, "simulated": True, "source": "test-pattern",
                "detections": [], "trajectory": None, "masks": [],
                "timing": {"queue_ms": 0, "pre_ms": 0, "infer_ms": 0, "post_ms": 0, "total_ms": 0}}
    try:
        k = 0
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:          # slow joiner
            k += 1
            pub.publish(res("warm", 0, k))
            if sub.poll(50):
                sub.recv()
                break
        while sub.poll(200):
            sub.recv()
        n_threads, n_each = 4, 400

        def run(i):
            for q in range(n_each):
                pub.publish(res(f"m{i}", i, q + 1))
        ths = [threading.Thread(target=run, args=(i,)) for i in range(n_threads)]
        for t in ths:
            t.start()
        seqs = []
        while len(seqs) < n_threads * n_each and sub.poll(2000):
            seqs.append(env.unpack(sub.recv())["seq"])
        for t in ths:
            t.join()
        assert len(seqs) == n_threads * n_each
        d = np.diff(np.asarray(seqs, dtype=np.int64))
        assert int((d != 1).sum()) == 0, f"seq reversals/gaps: {int((d <= 0).sum())}/{int((d > 1).sum())}"
    finally:
        sub.close(0)
        pub.close()
        ctx.destroy(linger=0)


# ---- protocol 2: snapshot of a camera with no signal ---------------------------------------------
def test_snapshot_no_signal_is_marked():
    from infer.draw import make_snapshot
    f = frame(seq=9, age_s=3.0, w=640, h=360)
    f.nv12[:360] = 200
    live = cv2.imdecode(np.frombuffer(make_snapshot(f, None, 320, 80, state="SIMULATED"), np.uint8), 1)
    dead = cv2.imdecode(np.frombuffer(make_snapshot(f, None, 320, 80, state="NO SIGNAL"), np.uint8), 1)
    assert live.shape == dead.shape == (180, 320, 3)
    # dark picture with red "NO SIGNAL" text in the centre
    assert dead[150:, :].mean() < 0.6 * live[150:, :].mean()
    mid = dead[60:120, 60:260].astype(int)
    red = (mid[..., 2] > 150) & (mid[..., 1] < 80) & (mid[..., 0] < 80)
    assert red.sum() > 100
