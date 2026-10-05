"""The FrameLink golden vectors (shared with the RK C++ reference tools/framelink_ref/) must match the
AGX receiver codec common/framelink.py: same frame bytes, same fragments, and the receiver accepts them."""
import os

from common import framelink as fl

GV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "framelink_ref", "golden_vectors.txt")


def test_golden_vectors():
    n = 0
    for ln in open(GV):
        if ln.startswith("#") or not ln.strip():
            continue
        (name, cam, fmt, seq, t_ns, w, h, stride, health, exp_us, source, payload_hex, frame_hex, chunk, nfr,
         f0, flast) = ln.split()
        payload = bytes.fromhex(payload_hex)
        hd = fl.FrameHeader(cam=int(cam), fmt=int(fmt), seq=int(seq), t_capture_ns=int(t_ns), width=int(w),
                            height=int(h), stride=int(stride), health=int(health), exposure_us=int(exp_us),
                            source=int(source))
        frame = fl.pack_frame(hd, payload)
        assert frame.hex() == frame_hex, name
        frags = list(fl.fragments(frame, int(cam), int(seq), int(chunk)))
        assert len(frags) == int(nfr) and frags[0].hex() == f0 and frags[-1].hex() == flast, name
        r = fl.Reassembler(int(cam))
        out = [o for o in (r.push(bytes.fromhex(x) if isinstance(x, str) else x, now=0.0) for x in reversed(frags)) if o]
        h2, p2 = fl.unpack_frame(out[0])
        assert bytes(p2) == payload and h2.seq == int(seq) and h2.source == int(source), name
        n += 1
    assert n == 3
