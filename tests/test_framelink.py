import os
import random

from common import framelink as fl


def _frame(cam=0, seq=1, size=1280 * 720 * 3 // 2, fmt=fl.FMT_NV12, source=fl.SOURCE_REPLAY):
    payload = os.urandom(size)
    h = fl.FrameHeader(cam=cam, fmt=fmt, seq=seq, t_capture_ns=123456789, width=1280, height=720,
                       stride=1280, source=source)
    return fl.pack_frame(h, payload), payload


def test_pack_unpack_roundtrip():
    frame, payload = _frame()
    h, p = fl.unpack_frame(frame)
    assert bytes(p) == payload and h.seq == 1 and h.width == 1280 and h.simulated


def test_header_crc_detects_change():
    frame, _ = _frame()
    b = bytearray(frame)
    b[8] ^= 1  # seq
    try:
        fl.unpack_frame(bytes(b))
    except fl.FrameError as e:
        assert "header crc" in str(e)
    else:
        raise AssertionError


def test_fragment_reassemble_out_of_order_and_mtu1500():
    for maxp in (fl.FRAG_PAYLOAD_JUMBO, fl.FRAG_PAYLOAD_1500):
        frame, payload = _frame(seq=5)
        d = list(fl.fragments(frame, 0, 5, maxp))
        random.shuffle(d)
        r = fl.Reassembler(0)
        outs = [o for o in (r.push(x, now=0.0) for x in d) if o is not None]
        assert len(outs) == 1 and outs[0] == frame
        assert all(len(x) <= fl.FRAG_LEN + maxp for x in d)


def test_loss_counts_and_newest_wins():
    r = fl.Reassembler(0)
    f1, _ = _frame(seq=1, size=50000)
    f2, _ = _frame(seq=2, size=50000)
    d1 = list(fl.fragments(f1, 0, 1))
    d2 = list(fl.fragments(f2, 0, 2))
    for x in d1[:-1]:        # last fragment of frame 1 is lost
        assert r.push(x, now=0.0) is None
    outs = [o for o in (r.push(x, now=0.01) for x in d2) if o is not None]
    assert outs == [f2]
    assert r.abandoned == 1 and r.lost_fragments == 1


def test_h265_variable_size():
    frame, payload = _frame(size=12345, fmt=fl.FMT_H265)
    r = fl.Reassembler(3)
    outs = [o for o in (r.push(x, now=0.0) for x in fl.fragments(frame, 3, 1, 1456)) if o is not None]
    h, p = fl.unpack_frame(outs[0])
    assert h.fmt == fl.FMT_H265 and bytes(p) == payload


def test_late_duplicate_after_complete_is_not_loss():
    r = fl.Reassembler(0)
    f5, _ = _frame(seq=5, size=30000)
    d5 = list(fl.fragments(f5, 0, 5))
    assert [o for o in (r.push(x, now=0.0) for x in d5) if o] == [f5]
    assert r.push(d5[1], now=0.01) is None          # duplicate of the complete frame
    f6, _ = _frame(seq=6, size=30000)
    assert [o for o in (r.push(x, now=0.02) for x in fl.fragments(f6, 0, 6)) if o] == [f6]
    assert r.push(d5[0], now=0.03) is None          # late fragment of an older frame
    assert r.late == 2 and r.abandoned == 0 and r.lost_fragments == 0


def test_sender_restart_is_a_new_stream():
    r = fl.Reassembler(0)
    f, _ = _frame(seq=1000, size=20000)
    assert [o for o in (r.push(x, now=0.0) for x in fl.fragments(f, 0, 1000)) if o] == [f]
    g, _ = _frame(seq=0, size=20000)               # restart: seq goes far back
    assert [o for o in (r.push(x, now=0.1) for x in fl.fragments(g, 0, 0)) if o] == [g]
    assert r.late == 0 and r.abandoned == 0
