"""RK3588 simulator (tools/rk_sim): run it for 3 s to a test port and check the FrameLink stream.

Each test starts `python -m tools.rk_sim --seconds 3` as a subprocess and receives on
UDP 127.0.0.1:16000+cam with common.framelink.Reassembler.
Pass: >= 60 frames, all CRCs ok, seq continuous from 0, source != LIVE, size and fmt correct.
"""
import os
import socket
import subprocess
import sys
import threading
import time

import pytest

from common import framelink as fl
from tools.rk_sim import config as simcfg
from tools.rk_sim.idr import nal_types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_PORT = 16000
# Old recordings of AGX02 (read-only input). The tests that need them are skipped when they are not there.
VIDEO_ROOT = os.environ.get("AGX_TEST_VIDEO_ROOT", "/home/tonyho/driveragent/logger/video")
REC = os.path.join(VIDEO_ROOT, "8003-20260510_151220/front/cam0_20260510_151220.mp4")
TEMPLATE = "config/templates/sim.yaml"     # a fresh clone has no config/sim.yaml
BENCH = ["8003-20260510_151020", "8003-20260510_151120", "8003-20260510_151220"]
ROAD = ["8003-20251109_105508", "8003-20251109_105608", "8003-20251109_105708"]
ROLES = ["front", "right", "left", "right-back", "left-back", "back"]


def rec_config() -> str:
    """A sim config with the old recordings (as the AGX02 config/sim.yaml): the file tests use it."""
    import yaml
    cams = [{"cam": n, "role": r, "source": "file", "width": 1280 if n == 0 else 704, "height": 720 if n == 0 else 396,
             "files": [f"{s}/{r}/cam{n}_{s.split('-', 1)[1]}.mp4" for s in BENCH]} for n, r in enumerate(ROLES)]
    os.makedirs(os.path.join(ROOT, "tests", "out"), exist_ok=True)
    path = os.path.join(ROOT, "tests", "out", "sim_recordings.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"video_root": VIDEO_ROOT, "session_sets": {"bench": BENCH, "road": ROAD}, "cameras": cams}, f)
    return path


class Rx(threading.Thread):
    def __init__(self, cam: int):
        super().__init__(daemon=True)
        self.cam = cam
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 212992)
        self.sock.bind(("127.0.0.1", BASE_PORT + cam))
        self.sock.settimeout(0.1)
        self.re = fl.Reassembler(cam)
        self.frames = []          # (header, payload bytes)
        self.crc_errors = 0
        self.stop = threading.Event()

    def run(self):
        buf = bytearray(65536)
        mv = memoryview(buf)
        while not self.stop.is_set():
            try:
                n = self.sock.recv_into(buf)
            except socket.timeout:
                continue
            f = self.re.push(mv[:n])
            if f is None:
                continue
            try:
                h, p = fl.unpack_frame(f)
                self.frames.append((h, bytes(p)))
            except fl.FrameError:
                self.crc_errors += 1
        self.sock.close()


def run_sim(cam: int, *args, seconds: float = 3.0, config: str = TEMPLATE) -> tuple[Rx, str]:
    rx = Rx(cam)
    rx.start()
    env = dict(os.environ, PYTHONPATH=ROOT)
    cmd = [sys.executable, "-m", "tools.rk_sim", "--config", config,
           "--seconds", str(seconds), "--cams", str(cam), "--base-port", str(BASE_PORT),
           "--status-interval", "1", *args]
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    finally:
        time.sleep(0.3)
        rx.stop.set()
        rx.join(2)
    out = p.stdout + p.stderr
    lines = [ln for ln in out.splitlines() if "cam" in ln or "SIMULATOR" in ln or "IDR" in ln]
    print("\n".join(lines))
    assert p.returncode == 0, out
    assert "threads still running" not in out, out
    assert "ERROR" not in out, out
    return rx, out


def check_stream(rx: Rx, cam: int, fmt: int, source: int, w: int, h: int):
    hs = [f[0] for f in rx.frames]
    seqs = [x.seq for x in hs]
    print(f"cam{cam}: frames {len(hs)}, seq {seqs[0] if seqs else None}..{seqs[-1] if seqs else None}, "
          f"crc errors {rx.crc_errors}, reassembler bad {rx.re.bad}, abandoned {rx.re.abandoned}, "
          f"lost fragments {rx.re.lost_fragments}")
    assert len(hs) >= 60
    assert rx.crc_errors == 0 and rx.re.bad == 0
    assert rx.re.abandoned == 0 and rx.re.lost_fragments == 0
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs))), "seq not continuous"
    assert seqs[0] == 0
    for x in hs:
        assert x.source != fl.SOURCE_LIVE
        assert x.source == source
        assert x.cam == cam and x.fmt == fmt and x.health == fl.HEALTH_LIVE
        assert (x.width, x.height) == (w, h)
    # capture times increase, about 30 fps
    t = [x.t_capture_ns for x in hs]
    assert all(b > a for a, b in zip(t, t[1:]))
    span = (t[-1] - t[0]) / 1e9
    fps = (len(t) - 1) / span
    print(f"cam{cam}: fps from t_capture_ns {fps:.2f}")
    assert 27.0 <= fps <= 33.0


def check_h265_start(rx: Rx):
    first = nal_types(rx.frames[0][1])
    assert {32, 33, 34} <= set(first) and (19 in first or 20 in first), first
    for _h, p in rx.frames:
        assert p[:4] == b"\0\0\0\1" or p[:3] == b"\0\0\1"


@pytest.mark.skipif(not os.path.isfile(REC), reason="recordings not found")
def test_file_h265_passthrough_cam0():
    rx, out = run_sim(0, "--fmt", "h265", config=rec_config())
    check_stream(rx, 0, fl.FMT_H265, fl.SOURCE_REPLAY, 1280, 720)
    check_h265_start(rx)
    assert all(h.stride == 0 for h, _ in rx.frames)
    assert "IDR interval" in out


@pytest.mark.skipif(not os.path.isfile(REC), reason="recordings not found")
def test_file_nv12_cam1():
    rx, _ = run_sim(1, "--fmt", "nv12", config=rec_config())
    check_stream(rx, 1, fl.FMT_NV12, fl.SOURCE_REPLAY, 704, 396)
    for h, p in rx.frames:
        assert h.stride == 704 and len(p) == 704 * 396 * 3 // 2


def test_pattern_h265_cam2():
    rx, _ = run_sim(2, "--fmt", "h265", "--source", "test-pattern")
    check_stream(rx, 2, fl.FMT_H265, fl.SOURCE_TEST_PATTERN, 1280, 720)
    check_h265_start(rx)
    # short GOP: one IDR every 15 frames
    idr = [i for i, (_h, p) in enumerate(rx.frames) if {19, 20} & set(nal_types(p))]
    gaps = {b - a for a, b in zip(idr, idr[1:])}
    print(f"cam2: IDR at {idr[:6]} ..., gaps {sorted(gaps)}")
    assert gaps == {15}


def test_pattern_nv12_cam3():
    rx, _ = run_sim(3, "--fmt", "nv12", "--source", "test-pattern")
    check_stream(rx, 3, fl.FMT_NV12, fl.SOURCE_TEST_PATTERN, 704, 396)
    # the picture changes from frame to frame (moving ball + frame counter)
    p0, p1 = rx.frames[0][1], rx.frames[1][1]
    assert p0 != p1


def test_nal_types():
    au = b"\0\0\0\1" + bytes([32 << 1, 1]) + b"\0\0\1" + bytes([19 << 1, 1]) + b"\xaa"
    assert nal_types(au) == [32, 19]


@pytest.mark.skipif(not os.path.isfile(REC), reason="recordings not found")
def test_road_sessions_cam0():
    """--sessions road: the file list comes from the road session set of the sim config."""
    cfg = rec_config()
    c = simcfg.load(cfg)
    simcfg.apply_sessions(c, "road")
    files = {cc.cam: cc.files for cc in c.cameras}
    assert all(len(f) == 3 for f in files.values()), files
    assert all("/8003-20251109_1055" in f[0] for f in files.values())
    rx, _ = run_sim(0, "--fmt", "h265", "--sessions", "road", "--no-measure-idr", config=cfg)
    check_stream(rx, 0, fl.FMT_H265, fl.SOURCE_REPLAY, 1280, 720)
    check_h265_start(rx)


def test_missing_file_falls_back_to_pattern():
    """A camera with no readable file sends the test pattern, with source = TEST_PATTERN."""
    os.makedirs(os.path.join(ROOT, "tests", "out"), exist_ok=True)
    cfg = os.path.join(ROOT, "tests", "out", "sim_missing_file.yaml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("fmt: nv12\ncameras:\n  - {cam: 4, role: left-back, source: file, width: 704, "
                "height: 396, files: [/nonexistent/cam4.mp4]}\n")
    rx, out = run_sim(4, config=cfg)
    assert "file not found" in out and "TEST PATTERN" in out
    check_stream(rx, 4, fl.FMT_NV12, fl.SOURCE_TEST_PATTERN, 704, 396)


def test_sender_no_catch_up_burst():
    """A sender thread that is late by 5 ms (GIL wait) sends at most max_burst+1 datagrams
    back-to-back, not the rest of the frame (old behaviour: about 5 ms / gap datagrams)."""
    import time as _t

    from common import framelink as fl
    from tools.rk_sim.sender import FrameLinkSender

    class FakeSock:
        def __init__(self):
            self.t = []

        def sendto(self, d, addr):
            self.t.append(_t.perf_counter())
            if len(self.t) == 20:
                _t.sleep(0.005)          # stall inside the frame

        def close(self):
            pass

    s = FrameLinkSender("127.0.0.1", 16099, 0, fl.FRAG_PAYLOAD_JUMBO, max_burst=4)
    s.sock.close()
    s.sock = FakeSock()
    hdr = fl.FrameHeader(cam=0, fmt=fl.FMT_NV12, seq=0, t_capture_ns=0, width=1280, height=720,
                         stride=1280)
    n = s.send(hdr, bytes(1280 * 1080), 1 / 30)
    gaps = [b - a for a, b in zip(s.sock.t, s.sock.t[1:])]
    run = best = 0
    for g in gaps[20:]:
        run = run + 1 if g < 40e-6 else 0
        best = max(best, run)
    print(f"datagrams {n}, max back-to-back after the stall {best}, max_burst_seen "
          f"{s.stats.max_burst_seen}, frame spread {(s.sock.t[-1] - s.sock.t[0]) * 1e3:.1f} ms")
    assert n == 156 and best <= 5 and s.stats.max_burst_seen <= 6
