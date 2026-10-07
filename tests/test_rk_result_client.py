"""Tests of tools/rk_result_client (the RK3588 example subscriber). No GPU, no infer.main.

The test starts the real ResultPublisher + StatusPublisher of infer/publish on the test ports
15600 / 15601, publishes SIMULATED synthetic results of six cameras (R13: simulated=True,
source "test-pattern"), and runs the client as a subprocess with --seconds 4 --json.
Run:
  PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_rk_result_client.py
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import time

import pytest
import zmq

from infer.publish.results import ResultPublisher

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "tests", "out")
CLIENT_FILE = os.path.join(ROOT, "tools", "rk_result_client", "__main__.py")
P_RES, P_STAT = 15600, 15601
CAMS = list(range(6))
MODEL = "test_model_sim"
RATE_HZ = 20.0            # per camera


class FakeStore:
    def state(self, cam):
        return "SIMULATED"

    def newest(self, cam):
        return None


class FakeIngest:
    mode = "sim"

    def __init__(self):
        self.store = FakeStore()

    def metrics_snapshot(self):
        return [{"cam": c, "role": f"role{c}", "fps": RATE_HZ, "frame_age_ms": 10.0,
                 "simulated": True, "lost_frames": 0, "lost_packets": 0, "last_seq": 0,
                 "last_error": ""} for c in CAMS]


class FakeManager:
    def status(self):
        return [{"name": MODEL, "enabled": True, "state": "RUNNING", "cameras": CAMS,
                 "fps": RATE_HZ * len(CAMS),
                 "lat_ms": {"total": {"p50": 2.0, "p95": 3.0, "p99": 4.0}}}]


def make_result(cam: int, seq: int) -> dict:
    now = time.time_ns()
    return {"model": MODEL, "model_version": "synthetic:0", "cam": cam, "frame_seq": seq,
            "t_capture_ns": now - 5_000_000, "t_recv_ns": now - 3_000_000,
            "t_ready_ns": now - 3_000_000, "t_result_ns": now,
            "frame_width": 1280, "frame_height": 720, "simulated": True, "source": "test-pattern",
            "detections": [{"class_id": 2, "class_name": "car", "score": 0.9,
                            "x1": 10, "y1": 20, "x2": 110, "y2": 220}],
            "timing": {"total_ms": 3.0}}


class Feeder(threading.Thread):
    """Publishes RATE_HZ results per camera. With faults=True, 0.5 s after the first subscriber:
    one duplicate (cam0, an old frameSeq) and one corrupt frame (one payload byte changed: CRC)."""

    def __init__(self, rp: ResultPublisher, faults: bool):
        super().__init__(daemon=True)
        self.rp = rp
        self.faults = faults
        self.stop = threading.Event()
        self.sent = {c: [] for c in CAMS}
        self.injected = {"duplicate": None, "corrupt": 0}

    def run(self):
        seq = 1000
        t_sub = None
        nxt = time.monotonic()
        while not self.stop.is_set():
            for c in CAMS:
                if self.rp.publish(make_result(c, seq)) is not None:
                    self.sent[c].append(seq)
            if self.rp.stats()["subscribers"] > 0 and t_sub is None:
                t_sub = time.monotonic()
            if self.faults and t_sub and time.monotonic() - t_sub > 0.5 \
                    and self.injected["duplicate"] is None:
                dup = seq - 1   # already published; the publisher only drops a repeat of the LAST id
                assert self.rp.publish(make_result(0, dup)) is not None
                self.injected["duplicate"] = dup
                msg, _ = self.rp.make_message(make_result(1, 999_999))
                bad = bytearray(msg)
                bad[-1] ^= 0xFF
                self.rp._q.put_nowait(bytes(bad))   # test only: raw frame on the same PUB socket
                self.injected["corrupt"] += 1
            seq += 1
            nxt += 1.0 / RATE_HZ
            self.stop.wait(max(0.0, nxt - time.monotonic()))


@pytest.fixture()
def node():
    from infer.publish.status import StatusPublisher
    from infer.status import NodeState
    ctx = zmq.Context()
    st = NodeState(version="test")
    st.started = True
    rp = ResultPublisher("127.0.0.1", P_RES, ctx=ctx)
    sp = StatusPublisher(st, FakeIngest(), FakeManager(), rp, None, "127.0.0.1", P_STAT,
                         period_s=1.0, ctx=ctx)
    sp.start()
    feeders = []

    def start_feeder(faults: bool) -> Feeder:
        f = Feeder(rp, faults)
        f.start()
        feeders.append(f)
        return f
    yield start_feeder
    for f in feeders:
        f.stop.set()
        f.join(timeout=2)
    sp.stop()
    rp.close()
    ctx.destroy(linger=0)


def run_client(name: str, *extra: str, seconds: float = 4.0):
    os.makedirs(OUT, exist_ok=True)
    js = os.path.join(OUT, f"rk_result_client_{name}.json")
    if os.path.exists(js):
        os.remove(js)
    cmd = [sys.executable, "-m", "tools.rk_result_client", "--host", "127.0.0.1",
           "--results-port", str(P_RES), "--status-port", str(P_STAT),
           "--seconds", str(seconds), "--json", js, *extra]
    envv = dict(os.environ, PYTHONPATH=ROOT)
    p = subprocess.run(cmd, cwd=ROOT, env=envv, capture_output=True, text=True, timeout=60)
    with open(os.path.join(OUT, f"rk_result_client_{name}.log"), "w") as f:
        f.write(f"$ {' '.join(cmd)}\n--- stdout\n{p.stdout}\n--- stderr\n{p.stderr}\nexit {p.returncode}\n")
    with open(js) as f:
        return p, json.load(f)


def check_streams(s: dict, feeder: Feeder) -> None:
    per = {r["cam"]: r for r in s["per_stream"]}
    assert sorted(per) == CAMS
    for c in CAMS:
        r = per[c]
        assert r["model"] == MODEL
        assert r["count"] >= 30, r                                    # ~3 s x 20 Hz
        assert r["simulated"] == r["count"]                           # R13
        assert 15.0 <= r["rate_hz"] <= 25.0, r
        assert r["first_seq"] in feeder.sent[c] and r["last_seq"] in feeder.sent[c]
        # no loss: every frameSeq from first to last was received once (+ the injected duplicate)
        assert r["count"] == r["last_seq"] - r["first_seq"] + 1 + r["duplicates"], r
        assert r["skipped_frames"] == 0
        for k in ("agx_ms", "e2e_recv_ms", "capture_ms"):
            assert r[k]["n"] == r["count"] and r[k]["negative"] == 0
        assert 2.9 <= r["agx_ms"]["p50"] <= 3.1                       # t_result - t_recv = 3 ms
        assert r["e2e_recv_ms"]["p50"] >= 3.0 and r["capture_ms"]["p50"] >= 5.0
    assert s["messages"]["result_ok"] == sum(r["count"] for r in per.values())
    iv = s["status"]["interval"]
    assert s["status"]["count"] >= 3 and iv["n"] >= 2
    assert 0.9 <= iv["mean_s"] <= 1.1 and iv["max_s"] <= 1.3, iv
    last = s["status"]["last"]
    assert last["node_state"] == "RUNNING" and last["simulated"] is True
    assert [c["cam"] for c in last["cameras"]] == CAMS
    assert last["models"][0]["name"] == MODEL and last["models"][0]["p95_ms"] == 3.0
    assert s["host_is_local"] is True
    assert s["schema_hash"] == {"AgxPerceptionResult": "0xafcaff02", "AgxInferStatus": "0x2c23c715"}   # schema v3


def test_clean_run_exit_0(node):
    feeder = node(faults=False)
    p, s = run_client("clean", "--expect-cams", "0,1,2,3,4,5")
    assert p.returncode == 0, p.stdout + p.stderr
    check_streams(s, feeder)
    assert s["rejects_total"] == 0 and s["duplicates"] == 0 and s["out_of_order"] == 0
    assert s["envelope_seq_lost"].get("result", 0) == 0
    assert all(s["checks"].values()) and s["exit_code"] == 0


def test_duplicate_and_corrupt_frame_exit_1(node):
    feeder = node(faults=True)
    p, s = run_client("faults", "--expect-cams", "0,1,2,3,4,5", "--print")
    assert feeder.injected["duplicate"] is not None and feeder.injected["corrupt"] == 1
    assert p.returncode == 1, p.stdout + p.stderr
    check_streams(s, feeder)
    assert s["duplicates"] == 1
    assert s["duplicate_examples"][0]["cam"] == 0
    assert s["duplicate_examples"][0]["frame_seq"] == feeder.injected["duplicate"]
    assert s["rejects"]["result"] == {"crc": 1} and s["rejects_total"] == 1
    assert s["envelope_seq_lost"]["result"] == 1     # the rejected frame had one envelope seq
    assert s["out_of_order"] == 0 and s["restarts"] == 0
    failed = sorted(k for k, v in s["checks"].items() if not v)
    assert failed == ["no_duplicates", "no_rejects"]
    lines = [ln for ln in p.stdout.splitlines() if f" {MODEL} cam" in ln]
    assert len(lines) == s["messages"]["result_ok"]
    assert all(" SIMULATED" in ln for ln in lines)                   # R13 tag on every line
    assert sum(" DUPLICATE" in ln for ln in lines) == 1
    assert sum(ln.startswith("STATUS node=RUNNING SIMULATED") for ln in p.stdout.splitlines()) \
        == s["status"]["count"]


def test_missing_camera_exit_1(node):
    node(faults=False)
    p, s = run_client("missing_cam", "--expect-cams", "0,1,2,3,4,5,6", "--status-port", "0",
                      "--crc", "reference", seconds=2.0)
    assert p.returncode == 1
    assert s["crc_impl"].startswith("reference")      # pure-Python CRC-32C of dabus_envelope.py
    assert s["rejects_total"] == 0 and s["messages"]["result_ok"] > 0
    assert s["cams_missing"] == [6]
    assert [k for k, v in s["checks"].items() if not v] == ["expected_cameras"]


def test_frame_seq_rules():
    import importlib.util
    spec = importlib.util.spec_from_file_location("rk_result_client_main", CLIENT_FILE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    st = m.Stream()
    assert [st.check_seq(x) for x in (10, 11, 13, 12, 13)] == \
        ["ok", "ok", "ok", "out_of_order", "duplicate"]
    assert st.skipped_frames == 1
    assert st.check_seq(2) == "out_of_order"          # back by 11 (< RESTART_JUMP)
    assert st.check_seq(5000) == "ok"
    assert st.check_seq(0) == "restart"               # big jump back = stream restart
    assert st.check_seq(1) == "ok"                    # old values are no duplicates after restart
    w = m.Stream()
    assert [w.check_seq(x) for x in (2**32 - 2, 2**32 - 1, 0, 1)] == ["ok"] * 4   # uint32 wrap
    assert m.lat_summary([3.0, 1.0, 2.0, -1.0])["p50"] == 1.0
    assert m.lat_summary([3.0, 1.0, 2.0, -1.0])["negative"] == 1


def test_client_imports_no_project_code():
    tree = ast.parse(open(CLIENT_FILE, encoding="utf-8").read())
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            assert n.level == 0, "relative import"
            names.add(n.module.split(".")[0])
    third_party = names - set(sys.stdlib_module_names)
    assert third_party <= {"capnp", "zmq", "crc32c"}, third_party
    assert not names & {"infer", "common", "tools", "dashboard", "proto"}
