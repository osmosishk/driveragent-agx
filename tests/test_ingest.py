"""Ingest tests: FrameLink receive logic (NV12), H.265 loopback on test port 16060, camera states,
Ingest with six cameras, file mode with one old recording (read-only)."""
import glob
import os
import socket
import time

import numpy as np
import pytest

from common import framelink as fl
from infer.ingest.frame_store import FrameStore
from infer.ingest.framelink_rx import FrameLinkReceiver, h265_nal_types, has_idr
from infer.ingest.metrics import CameraMetrics


def _nv12_frame(cam, seq, w=704, h=396, stride=None, source=fl.SOURCE_TEST_PATTERN):
    stride = stride or w
    img = np.zeros((h * 3 // 2, stride), dtype=np.uint8)
    img[:, :w] = (np.arange(w, dtype=np.uint32)[None, :] + seq) % 256
    img[:, w:] = 0xEE  # padding, must not reach the store
    hd = fl.FrameHeader(cam=cam, fmt=fl.FMT_NV12, seq=seq, t_capture_ns=time.time_ns(), width=w,
                        height=h, stride=stride, source=source)
    return fl.pack_frame(hd, img.tobytes()), img[:, :w].copy()


def _rx(cam=1, port=16050, expect_simulated=True, use_process=False):
    store = FrameStore(range(6))
    m = CameraMetrics(cam, "right", port, "sim", store, expect_simulated)
    return FrameLinkReceiver(cam, port, "127.0.0.1", store, m, expect_simulated,
                             use_process=use_process), store, m


# (a) unit: datagrams of fake NV12 frames -> Frame in the store, metrics fps > 0 -------------------
def test_nv12_datagrams_to_store():
    rx, store, m = _rx(cam=1)
    for seq in range(10, 15):
        frame, img = _nv12_frame(1, seq, stride=768)
        for d in fl.fragments(frame, 1, seq, fl.FRAG_PAYLOAD_1500):
            rx.handle_datagram(d)
    f = store.newest(1)
    assert f is not None and f.seq == 14 and f.fmt == "nv12" and f.source == "test-pattern"
    assert f.nv12.shape == (396 * 3 // 2, 704) and np.array_equal(f.nv12, img)
    assert f.t_ready_ns == f.t_recv_ns and f.decode_ms == 0.0 and f.simulated
    s = m.snapshot()
    print("snapshot:", {k: s[k] for k in ("state", "fps", "bitrate_kbps", "datagrams", "lost_frames",
                                          "simulated", "width", "height")})
    assert s["fps"] > 0 and s["state"] == "SIMULATED" and s["simulated"] is True
    assert s["bitrate_kbps"] > 0 and s["lost_frames"] == 0 and s["bad"] == 0


def test_loss_bad_and_source_label():
    rx, store, m = _rx(cam=2)
    f1, _ = _nv12_frame(2, 1)
    f2, _ = _nv12_frame(2, 2)
    f5, _ = _nv12_frame(2, 5, source=fl.SOURCE_LIVE)  # LIVE byte in sim mode -> "replay"
    for d in fl.fragments(f1, 2, 1):
        rx.handle_datagram(d)
    d2 = list(fl.fragments(f2, 2, 2))
    for d in d2[:-1]:  # frame 2 loses its last fragment
        rx.handle_datagram(d)
    # frames 3 and 4 are fully missing
    for d in fl.fragments(f5, 2, 5):
        rx.handle_datagram(d)
    bad = bytearray(f1)
    bad[-1] ^= 0xFF  # payload CRC error
    for d in fl.fragments(bytes(bad), 2, 6):
        rx.handle_datagram(d)
    rx.flush()
    s = m.snapshot()
    print("loss snapshot:", {k: s[k] for k in ("lost_fragments", "abandoned_frames", "lost_frames",
                                               "missing_frames", "lost_packets", "bad",
                                               "source_mismatch")})
    assert store.newest(2).seq == 5 and store.newest(2).source == "replay"
    assert s["lost_fragments"] == 1 and s["abandoned_frames"] == 1
    assert s["lost_frames"] == 4 and s["missing_frames"] == 2 and s["lost_packets"] > 1
    assert s["bad_frames"] == 1 and s["source_mismatch"] == 1
    # rk mode: LIVE byte -> live
    rx2, store2, _ = _rx(cam=2, expect_simulated=False)
    for d in fl.fragments(f5, 2, 5):
        rx2.handle_datagram(d)
    assert store2.newest(2).source == "live" and not store2.newest(2).simulated


def test_shm_reassembler_matches_reference():
    import random
    from infer.ingest.rx_proc import SLOT_HDR, SLOT_HDR_LEN, ShmReassembler, slot_offset
    nslots, slot_size = 8, 2 * 1024 * 1024
    ring = bytearray(nslots * (SLOT_HDR_LEN + slot_size))
    r = ShmReassembler(0, memoryview(ring), nslots, slot_size)
    ref = fl.Reassembler(0)
    got, want = [], []
    frames = {}
    for seq in range(1, 9):
        frames[seq], _ = _nv12_frame(0, seq, w=1280, h=720)
    for seq, frame in frames.items():
        d = list(fl.fragments(frame, 0, seq, fl.FRAG_PAYLOAD_JUMBO))
        if seq == 3:
            d = d[:-2]          # frame 3 loses 2 fragments
        if seq == 5:
            continue            # frame 5 is fully lost
        random.shuffle(d)
        d.insert(len(d) // 2, d[0])   # one duplicate inside the frame
        for x in d:
            o = r.push(memoryview(x), 0.0)
            if o is not None:
                slot, gen, size, count = o
                base = slot_offset(slot, slot_size)
                assert SLOT_HDR.unpack_from(ring, base)[0] == gen
                got.append(bytes(ring[base + SLOT_HDR_LEN:base + SLOT_HDR_LEN + size]))
            o2 = ref.push(x, now=0.0)
            if o2 is not None:
                want.append(o2)
    assert got == want and len(got) == 6
    assert (r.lost_fragments, r.abandoned, r.bad) == (ref.lost_fragments, ref.abandoned, ref.bad)
    assert r.lost_fragments == 2 and r.abandoned == 1
    # late duplicate of a complete frame: dropped, not a new frame, not a loss
    assert r.push(memoryview(next(fl.fragments(frames[8], 0, 8))), 0.0) is None
    r.expire(1.0)
    assert r.late == 1 and r.lost_fragments == 2 and r.abandoned == 1
    # sender restart (seq starts again at 0 after more than 1000 frames): accepted
    r.last_done = 5000
    f0, _ = _nv12_frame(0, 0)
    outs = [r.push(memoryview(x), 2.0) for x in fl.fragments(f0, 0, 0)]
    assert outs[-1] is not None and r.late == 1
    # too large for the slot -> bad
    big = list(fl.fragments(b"x" * (slot_size + 100), 0, 99))
    assert all(r.push(memoryview(x), 0.0) is None for x in big) and r.bad > 0


# H.265 helpers -----------------------------------------------------------------------------------
ENC = ("videotestsrc num-buffers={n} pattern=smpte ! video/x-raw,width={w},height={h},framerate=30/1 ! "
       "nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! nvv4l2h265enc bitrate=4000000 "
       "iframeinterval=15 idrinterval=15 insert-sps-pps=1 maxperf-enable=1 ! "
       "h265parse config-interval=-1 ! video/x-h265,stream-format=byte-stream,alignment=au ! "
       "appsink name=sink sync=false emit-signals=false max-buffers=1000")


def _encode(n, w, h):
    from infer.ingest.h265_decoder import Gst, gst_init
    gst_init()
    p = Gst.parse_launch(ENC.format(n=n, w=w, h=h))
    sink = p.get_by_name("sink")
    p.set_state(Gst.State.PLAYING)
    aus = []
    while True:
        s = sink.emit("try-pull-sample", 5 * Gst.SECOND)
        if s is None:
            break
        b = s.get_buffer()
        ok, mi = b.map(Gst.MapFlags.READ)
        aus.append(bytes(mi.data))
        b.unmap(mi)
    p.set_state(Gst.State.NULL)
    return aus


def test_idr_detection_and_wait():
    aus = _encode(20, 704, 396)
    types0 = h265_nal_types(aus[0])
    print("AU0 NAL types:", types0, "AU1 NAL types:", h265_nal_types(aus[1]))
    assert has_idr(aus[0]) and {32, 33, 34} <= set(types0) and not has_idr(aus[1])
    rx, store, m = _rx(cam=3)
    rx.cam = 3
    # start in the middle of a GOP: AUs 1..14 have no IDR, AU 15 is the next IDR
    for seq in range(1, 20):
        hd = fl.FrameHeader(cam=3, fmt=fl.FMT_H265, seq=seq, t_capture_ns=time.time_ns(), width=704,
                            height=396, source=fl.SOURCE_REPLAY)
        for d in fl.fragments(fl.pack_frame(hd, aus[seq]), 3, seq):
            rx.handle_datagram(d)
        time.sleep(0.0333)
    time.sleep(0.3)
    rx.flush()
    s = m.snapshot()
    rx.stop()
    print("idr snapshot:", {k: s[k] for k in ("waiting_idr", "frames", "decoder_errors")})
    assert s["waiting_idr"] == 14 and s["frames"] >= 4


def _au(*types):
    return b"".join(b"\x00\x00\x00\x01" + bytes([t << 1, 1]) + b"\xAA" * 8 for t in types)


def test_idr_gate_cra_after_loss():
    from infer.ingest.framelink_rx import IdrGate
    g = IdrGate()
    assert not g.accept(_au(1)) and not g.accept(_au(21))       # no parameter sets yet
    assert g.accept(_au(32, 33, 34, 19)) and g.accept(_au(1))   # IDR + VPS/SPS/PPS: start
    g.resync()                                                  # a frame was lost
    assert not g.accept(_au(1)) and g.accept(_au(21))           # CRA restarts (params known)
    assert g.dropped == 3


# (b) loopback with real sockets: 30 H.265 frames to port 16060 -----------------------------------
@pytest.mark.parametrize("use_process", [True, False], ids=["rx-process", "rx-thread"])
def test_h265_loopback_port_16060(use_process):
    aus = _encode(30, 1280, 720)
    assert len(aus) == 30
    rx, store, m = _rx(cam=0, port=16060, use_process=use_process)
    seen = []
    orig_put = store.put

    def put(f):
        seen.append(f)
        orig_put(f)
    store.put = put
    rx.start()
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        t0 = time.monotonic()
        for i, au in enumerate(aus):
            hd = fl.FrameHeader(cam=0, fmt=fl.FMT_H265, seq=100 + i, t_capture_ns=time.time_ns(),
                                width=1280, height=720, source=fl.SOURCE_REPLAY)
            dg = list(fl.fragments(fl.pack_frame(hd, au), 0, 100 + i, fl.FRAG_PAYLOAD_JUMBO))
            for d in dg:
                tx.sendto(d, ("127.0.0.1", 16060))
                time.sleep(0.0333 / (len(dg) + 1))  # pace the fragments over the frame interval
            time.sleep(max(0.0, t0 + (i + 1) * 0.0333 - time.monotonic()))
        time.sleep(0.5)
        s = m.snapshot()
    finally:
        tx.close()
        rx.stop()
    dms = sorted(f.decode_ms for f in seen)
    print(f"loopback ({'process' if use_process else 'thread'}): frames in store {len(seen)} / 30, decode_ms p50 {dms[len(dms)//2]:.2f} "
          f"max {dms[-1]:.2f}, seq {seen[0].seq}..{seen[-1].seq}, simulated {seen[-1].simulated}, "
          f"rcvbuf {s['rcvbuf']}, datagrams {s['datagrams']}, lost {s['lost_frames']}")
    assert len(seen) >= 25
    assert all(f.decode_ms > 0 for f in seen)
    assert all(f.simulated and f.source == "replay" and f.fmt == "h265" for f in seen)
    assert seen[-1].nv12.shape == (1080, 1280) and seen[-1].t_ready_ns >= seen[-1].t_recv_ns
    assert s["simulated"] is True and s["decode_ms"]["p50"] > 0


# (c) STALE after 0.5 s and NO SIGNAL after 1.0 s without frames -----------------------------------
def test_state_stale_and_no_signal():
    rx, store, m = _rx(cam=4)
    assert m.snapshot()["state"] == "NO SIGNAL"
    frame, _ = _nv12_frame(4, 1)
    for d in fl.fragments(frame, 4, 1):
        rx.handle_datagram(d)
    t = store.newest(4).t_ready_mono
    states = {}
    for dt in (0.0, 0.3, 0.6, 0.9, 1.2):
        time.sleep(max(0.0, t + dt - time.monotonic()))
        states[dt] = m.snapshot()["state"]
    print("states:", states)
    assert states[0.0] == "SIMULATED" and states[0.3] == "SIMULATED"
    assert states[0.6] == "STALE" and states[0.9] == "STALE" and states[1.2] == "NO SIGNAL"
    s = m.snapshot()
    assert s["fps"] == 0 and s["receiving"] is False and s["frame_age_ms"] >= 1200


def test_ingest_six_cameras_no_signal():
    from infer.ingest.ingest import Ingest
    cfg = {"mode": "sim", "bind_host": {"sim": "127.0.0.1"},
           "cameras": [{"cam": c, "port": 16070 + c} for c in range(6)]}
    ing = Ingest(cfg)
    ing.start()
    try:
        time.sleep(0.3)
        snap = ing.metrics_snapshot()
    finally:
        ing.stop()
    assert [s["cam"] for s in snap] == list(range(6))
    assert all(s["state"] == "NO SIGNAL" and s["simulated"] for s in snap)
    assert [s["port"] for s in snap] == [16070 + c for c in range(6)]


FILES = sorted(glob.glob("/home/tonyho/driveragent/logger/video/8003-20260510_151220/back/cam5_*.mp4"))


@pytest.mark.skipif(not FILES, reason="old recording not found")
def test_file_mode_one_camera():
    from infer.ingest.ingest import Ingest
    cfg = {"mode": "file", "cameras": [{"cam": 5, "files": FILES}] +
           [{"cam": c, "enabled": False} for c in range(5)]}
    ing = Ingest(cfg)
    ing.start()
    try:
        time.sleep(3.0)
        s = ing.metrics_snapshot()[5]
        f = ing.store.newest(5)
    finally:
        ing.stop()
    print("file mode cam5:", {k: s[k] for k in ("state", "fps", "fps_5s", "frames", "width", "height",
                                                "decode_ms", "source", "last_error")})
    assert f is not None and f.source == "file" and f.simulated and f.nv12.shape == (1080, 1280)
    assert s["state"] == "SIMULATED" and 25 <= s["fps"] <= 35
    assert s["decode_ms"]["p50"] is not None and s["decode_ms"]["p50"] > 0


def test_port_in_use_gives_error_and_no_leftovers():
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 16055))
    try:
        rx, _, _ = _rx(cam=1, port=16055, use_process=True)
        with pytest.raises(OSError) as e:
            rx.start()
        print("bind error:", e.value)
        assert "16055" in str(e.value)
        assert rx._proc is None and rx._shm is None
    finally:
        blocker.close()


# ---- T3 review fixes ------------------------------------------------------------------------------
def test_shm_reassembler_restart_and_late_window():
    """A sender restart after a SHORT run (seq 309 -> 0) is a new stream, not 'late' datagrams."""
    from infer.ingest.rx_proc import SLOT_HDR_LEN, ShmReassembler
    nslots, slot_size = 8, 2 * 1024 * 1024
    r = ShmReassembler(1, memoryview(bytearray(nslots * (SLOT_HDR_LEN + slot_size))), nslots,
                       slot_size)
    t = 0.0
    for seq in (307, 308, 309):
        f, _ = _nv12_frame(1, seq)
        outs = [r.push(memoryview(x), t) for x in fl.fragments(f, 1, seq)]
        assert outs[-1] is not None
        t += 0.033
    # late duplicate of seq 308 (1 frame behind): dropped, counted in late
    f308, _ = _nv12_frame(1, 308)
    assert r.push(memoryview(next(fl.fragments(f308, 1, 308))), t) is None and r.late == 1
    # restart without a pause: seq 0 is 309 frames behind -> new stream
    f0, _ = _nv12_frame(1, 0)
    outs = [r.push(memoryview(x), t + 0.01) for x in fl.fragments(f0, 1, 0)]
    assert outs[-1] is not None and r.new_streams == 1 and r.late == 1
    for seq in (1, 2):
        f, _ = _nv12_frame(1, seq)
        assert [r.push(memoryview(x), t + 0.02 * seq) for x in fl.fragments(f, 1, seq)][-1]
    # restart after a quiet socket (>= timeout): seq 0 again, only 2 frames behind -> new stream
    outs = [r.push(memoryview(x), t + 1.0) for x in fl.fragments(f0, 1, 0)]
    assert outs[-1] is not None and r.new_streams == 2
    # wrong cam in the fragment header -> bad, not a frame
    f9, _ = _nv12_frame(2, 9)
    assert all(r.push(memoryview(x), t + 1.1) is None for x in fl.fragments(f9, 2, 9))
    assert r.abandoned == 0 and r.lost_fragments == 0 and r.bad > 0
    print("restart:", dict(late=r.late, new_streams=r.new_streams, bad=r.bad))


def test_thread_reassembler_duplicate_after_complete_is_not_loss():
    rx, store, m = _rx(cam=2)
    f1, _ = _nv12_frame(2, 1)
    f2, _ = _nv12_frame(2, 2)
    d1 = list(fl.fragments(f1, 2, 1))
    for d in d1:
        rx.handle_datagram(d)
    rx.handle_datagram(d1[0])            # duplicate after the frame is complete
    for d in fl.fragments(f2, 2, 2):
        rx.handle_datagram(d)
    rx.flush()
    s = m.snapshot()
    print("dup:", {k: s[k] for k in ("lost_fragments", "abandoned_frames", "late_datagrams")})
    assert s["lost_fragments"] == 0 and s["abandoned_frames"] == 0 and s["late_datagrams"] == 1
    assert store.newest(2).seq == 2


def test_rejected_frames_count_as_lost_and_foreign_frames_do_not():
    rx, store, m = _rx(cam=2)
    f1, _ = _nv12_frame(2, 1)
    for d in fl.fragments(f1, 2, 1):
        rx.handle_datagram(d)
    h = fl.FrameHeader(cam=2, fmt=99, seq=2, t_capture_ns=1, width=4, height=4)
    for d in fl.fragments(fl.pack_frame(h, b"x" * 10), 2, 2):     # unknown fmt
        rx.handle_datagram(d)
    h = fl.FrameHeader(cam=2, fmt=fl.FMT_NV12, seq=3, t_capture_ns=1, width=704, height=396)
    for d in fl.fragments(fl.pack_frame(h, b"x" * 10), 2, 3):     # NV12 too small
        rx.handle_datagram(d)
    h = fl.FrameHeader(cam=4, fmt=fl.FMT_NV12, seq=50, t_capture_ns=1, width=4, height=4)
    for d in fl.fragments(fl.pack_frame(h, b"x" * 24), 2, 4):     # header of another camera
        rx.handle_datagram(d)
    f5, _ = _nv12_frame(2, 4)
    for d in fl.fragments(f5, 2, 5):
        rx.handle_datagram(d)
    rx.flush()
    s = m.snapshot()
    print("rejects:", {k: s[k] for k in ("lost_frames", "bad_frames", "foreign_frames",
                                          "missing_frames")})
    assert s["lost_frames"] == 2 and s["bad_frames"] == 2 and s["foreign_frames"] == 1
    assert s["missing_frames"] == 0


class _FakeDecoder:
    def __init__(self):
        self.seqs = []
        self.errors = self.pushed = self.decoded = 0
        self._meta = {}

    def push(self, au, meta):
        self.seqs.append(meta["seq"])

    def poll_errors(self):
        return None

    def close(self):
        pass


def test_seq_reset_resyncs_h265_gate():
    rx, store, m = _rx(cam=3)
    rx.decoder = dec = _FakeDecoder()

    def send(seq, au):
        hd = fl.FrameHeader(cam=3, fmt=fl.FMT_H265, seq=seq, t_capture_ns=1, width=1280,
                            height=720, source=fl.SOURCE_REPLAY)
        for d in fl.fragments(fl.pack_frame(hd, au), 3, seq):
            rx.handle_datagram(d, now_mono=float(seq) * 0.033)
    send(0, _au(32, 33, 34, 19))
    for seq in range(1, 300):
        send(seq, _au(1))
    assert dec.seqs == list(range(300))
    dec.seqs.clear()
    # new stream from seq 1 (its IDR seq 0 was lost): P-frames must not reach the decoder
    for seq in range(1, 6):
        send(seq, _au(1))
    send(6, _au(21))                     # CRA without parameter sets: still waiting
    send(7, _au(32, 33, 34, 19))         # IDR with the parameter sets of the new stream
    send(8, _au(1))
    rx.flush()
    s = m.snapshot()
    print("after restart: pushed", dec.seqs, "seq_resets", s["seq_resets"], "waiting_idr",
          s["waiting_idr"])
    assert dec.seqs == [7, 8] and s["seq_resets"] == 1 and s["waiting_idr"] == 6


def _send_nv12(tx, port, cam, seqs, pause_mid=None):
    for seq in seqs:
        f, _ = _nv12_frame(cam, seq)
        dg = list(fl.fragments(f, cam, seq, fl.FRAG_PAYLOAD_JUMBO))
        for i, d in enumerate(dg):
            if pause_mid is not None and seq == pause_mid and i == len(dg) // 2:
                time.sleep(0.6)          # sender pause inside one frame (3 x reassembly timeout)
            tx.sendto(d, ("127.0.0.1", port))
            time.sleep(0.0002)
        time.sleep(0.03)


def test_process_mode_restart_pause_and_rx_kill():
    """Process mode, port 16061: (1) a pause inside one frame is not a loss, (2) a sender restart
    after a short run is accepted at once (seq_resets 1), (3) a killed receive process starts again."""
    import signal as sg
    rx, store, m = _rx(cam=1, port=16061, use_process=True)
    rx.start()
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _send_nv12(tx, 16061, 1, range(0, 20), pause_mid=10)
        time.sleep(0.3)
        s1 = m.snapshot()
        _send_nv12(tx, 16061, 1, range(0, 15))          # sender restart: seq 0 again
        time.sleep(0.3)
        s2 = m.snapshot()
        os.kill(rx.rx_pid, sg.SIGKILL)
        t_kill = time.monotonic()
        while m.snapshot()["rx_restarts"] < 1 and time.monotonic() - t_kill < 5.0:
            time.sleep(0.05)
        t_restart = time.monotonic() - t_kill
        _send_nv12(tx, 16061, 1, range(15, 25))
        time.sleep(0.3)
        s3 = m.snapshot()
    finally:
        tx.close()
        rx.stop()
    keys = ("frames", "lost_frames", "lost_fragments", "abandoned_frames", "seq_resets",
            "late_datagrams", "new_streams", "rx_restarts", "datagrams")
    print("pause:", {k: s1[k] for k in keys})
    print("restart:", {k: s2[k] for k in keys})
    print(f"rx kill: restarted after {t_restart:.2f} s:", {k: s3[k] for k in keys})
    assert s1["frames"] == 20 and s1["lost_frames"] == 0 and s1["abandoned_frames"] == 0
    assert s1["lost_fragments"] == 0
    assert s2["frames"] == 35 and s2["seq_resets"] == 1 and s2["lost_frames"] == 0
    assert s2["late_datagrams"] == 0 and s2["new_streams"] == 1
    assert s3["rx_restarts"] == 1 and s3["frames"] == 45 and store.newest(1).seq == 24
    assert s3["datagrams"] >= s2["datagrams"]          # counters stay cumulative
    assert rx._proc is None and rx._shm is None


def test_decoder_close_releases_fds():
    import gc
    from infer.ingest.h265_decoder import H265Decoder
    H265Decoder(0, lambda *a: None).close()     # warm-up: the first decoder opens shared fds
    gc.collect()
    n0 = len(os.listdir("/proc/self/fd"))
    for _ in range(4):
        d = H265Decoder(0, lambda *a: None)
        d.close()
        del d
    gc.collect()
    n1 = len(os.listdir("/proc/self/fd"))
    print(f"fds before {n0} after 4 create/close {n1}")
    assert n1 == n0       # old close(): +2 sockets per decoder (GstBus socketpair)


@pytest.mark.parametrize("mode", ["shm", "thread"])
def test_start_in_middle_of_frame_is_not_loss(mode):
    """The receiver starts while the sender runs: the first, partial frame is not a loss."""
    f1, _ = _nv12_frame(1, 41)
    f2, _ = _nv12_frame(1, 42)
    f3, _ = _nv12_frame(1, 43)
    d1 = list(fl.fragments(f1, 1, 41))[5:]          # joined at fragment 5
    d3 = list(fl.fragments(f3, 1, 43))[:-1]         # a real loss later: frame 43 incomplete
    rest = list(fl.fragments(f2, 1, 42)) + d3 + list(fl.fragments(_nv12_frame(1, 44)[0], 1, 44))
    if mode == "shm":
        from infer.ingest.rx_proc import SLOT_HDR_LEN, ShmReassembler
        r = ShmReassembler(1, memoryview(bytearray(8 * (SLOT_HDR_LEN + 2 ** 21))), 8, 2 ** 21)
        for x in d1 + rest:
            r.push(memoryview(x), 0.0)
        got = (r.start_partial, r.abandoned, r.lost_fragments)
    else:
        rx, store, m = _rx(cam=1)
        for x in d1 + rest:
            rx.handle_datagram(x)
        rx.flush()
        s = m.snapshot()
        got = (s["start_partial"], s["abandoned_frames"], s["lost_fragments"])
        assert s["lost_frames"] == 1 and s["frames"] == 2
    print(mode, "start_partial, abandoned, lost_fragments =", got)
    assert got == (1, 1, 1)
