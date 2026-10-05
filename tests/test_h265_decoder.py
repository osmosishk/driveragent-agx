"""Hardware H.265 round trip: nvv4l2h265enc AUs -> H265Decoder (nvv4l2decoder) keeps frame identity."""
import threading
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from infer.ingest.h265_decoder import H265Decoder, gst_init

PACE = 0.0333
ENC = ("videotestsrc num-buffers={n} pattern=ball ! video/x-raw,width={w},height={h},framerate=30/1 ! "
       "nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! nvv4l2h265enc bitrate=4000000 "
       "iframeinterval=15 idrinterval=15 insert-sps-pps=1 maxperf-enable=1 ! "
       "h265parse config-interval=-1 ! video/x-h265,stream-format=byte-stream,alignment=au ! "
       "appsink name=sink sync=false emit-signals=false max-buffers=1000")


def encode(n, w, h):
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


def test_roundtrip_keeps_identity():
    for (w, h) in ((1280, 720), (704, 396)):
        aus = encode(45, w, h)
        assert len(aus) == 45
        got = []
        done = threading.Event()

        def on_frame(cam, nv12, meta, dms):
            got.append((meta["seq"], nv12.shape, dms))
            if len(got) == len(aus):
                done.set()

        d = H265Decoder(2, on_frame)
        for i, au in enumerate(aus):
            d.push(au, {"seq": 1000 + i, "t_capture_ns": i})
            time.sleep(PACE)
        done.wait(5)
        d.close()
        assert [g[0] for g in got] == list(range(1000, 1000 + len(aus)))
        assert all(g[1] == (h * 3 // 2, w) for g in got)
        print(f"{w}x{h}: {len(got)} frames, decode ms p50={sorted(g[2] for g in got)[len(got)//2]:.2f}")
