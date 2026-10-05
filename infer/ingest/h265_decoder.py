"""Hardware H.265 decode for one camera: appsrc -> h265parse -> nvv4l2decoder -> nvvidconv -> NV12 appsink.

Each pushed access unit gets a synthetic, strictly increasing PTS. The decoder keeps the PTS on its
output (no B-frames: output order = input order), so the frame identity (FrameLink seq, capture time,
receive time) is found again on the decoded frame through a PTS -> meta map.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable

import numpy as np

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo  # noqa: E402

_init_lock = threading.Lock()
_inited = False


def gst_init() -> None:
    global _inited
    with _init_lock:
        if not _inited:
            Gst.init(None)
            _inited = True


PIPELINE = (
    "appsrc name=src is-live=true format=time do-timestamp=false block=false "
    "caps=video/x-h265,stream-format=byte-stream,alignment=au ! "
    "h265parse ! nvv4l2decoder enable-max-performance=1 disable-dpb=1 ! "
    "nvvidconv ! video/x-raw,format=NV12 ! "
    "appsink name=sink emit-signals=true sync=false max-buffers=4 drop=true"
)

FrameCallback = Callable[[int, np.ndarray, dict, float], None]


def nv12_from_sample(sample) -> np.ndarray:
    """Return a tightly packed NV12 array (h*3/2, w) copied from a GstSample (handles row padding)."""
    caps = sample.get_caps()
    info = GstVideo.VideoInfo.new_from_caps(caps)
    w, h = info.width, info.height
    buf = sample.get_buffer()
    ok, mi = buf.map(Gst.MapFlags.READ)
    if not ok:
        raise RuntimeError("buffer map failed")
    try:
        raw = np.frombuffer(mi.data, dtype=np.uint8)
        s0, s1 = info.stride[0], info.stride[1]
        o0, o1 = info.offset[0], info.offset[1]
        out = np.empty((h * 3 // 2, w), dtype=np.uint8)
        out[:h] = np.lib.stride_tricks.as_strided(raw[o0:], shape=(h, w), strides=(s0, 1))
        out[h:] = np.lib.stride_tricks.as_strided(raw[o1:], shape=(h // 2, w), strides=(s1, 1))
        return out
    finally:
        buf.unmap(mi)


class H265Decoder:
    """One decoder per camera. push() is called from the receive thread; on_frame() runs in a
    GStreamer streaming thread with (cam, nv12, meta, decode_ms)."""

    def __init__(self, cam: int, on_frame: FrameCallback, max_inflight: int = 64):
        gst_init()
        self.cam = cam
        self.on_frame = on_frame
        self.pipeline = Gst.parse_launch(PIPELINE)
        self.src = self.pipeline.get_by_name("src")
        self.sink = self.pipeline.get_by_name("sink")
        # keep the handler id: close() disconnects it. Else the GObject -> bound method reference
        # cycle keeps the pipeline (and its bus socketpair, 2 fds) alive after close().
        self._sig = self.sink.connect("new-sample", self._on_sample)
        self._meta: OrderedDict[int, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._n = 0
        self.max_inflight = max_inflight
        self.decoded = 0
        self.pushed = 0
        self.errors = 0
        self.last_error = ""
        self._bus = self.pipeline.get_bus()  # no GLib main loop: poll_errors() reads it
        self.pipeline.set_state(Gst.State.PLAYING)

    def push(self, au: bytes, meta: dict) -> None:
        if self.src is None:  # closed
            return
        pts = self._n * 33_333_333  # synthetic, strictly increasing
        self._n += 1
        meta = dict(meta)
        meta["t_push_ns"] = time.monotonic_ns()
        with self._lock:
            self._meta[pts] = meta
            while len(self._meta) > self.max_inflight:  # decoder dropped some: forget the oldest
                self._meta.popitem(last=False)
        buf = Gst.Buffer.new_wrapped(au)
        buf.pts = pts
        buf.dts = pts
        buf.duration = 33_333_333
        self.pushed += 1
        ret = self.src.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK:
            self.errors += 1
            self.last_error = f"push-buffer {ret.value_nick}"

    def _on_sample(self, sink):
        # decode_ms = push -> decoder output (appsink callback entry). It does not include the
        # CPU copy of the NV12 frame below.
        t_out = time.monotonic_ns()
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        pts = sample.get_buffer().pts
        with self._lock:
            meta = self._meta.pop(pts, None)
            # entries older than this pts were dropped by the decoder
            for k in [k for k in self._meta if k < pts]:
                del self._meta[k]
        if meta is None:
            return Gst.FlowReturn.OK
        try:
            nv12 = nv12_from_sample(sample)
        except Exception as e:  # noqa: BLE001
            self.errors += 1
            self.last_error = f"map: {e}"
            return Gst.FlowReturn.OK
        decode_ms = (t_out - meta["t_push_ns"]) / 1e6
        self.decoded += 1
        try:
            self.on_frame(self.cam, nv12, meta, decode_ms)
        except Exception as e:  # noqa: BLE001
            self.errors += 1
            self.last_error = f"callback: {e}"
        return Gst.FlowReturn.OK

    def poll_errors(self) -> str | None:
        """Read pending bus errors without a GLib main loop. Returns the last error text or None."""
        last = None
        if self._bus is None:
            return None
        while True:
            msg = self._bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.WARNING)
            if msg is None:
                break
            if msg.type == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                self.errors += 1
                last = self.last_error = f"gst error: {err.message}"
        return last

    def close(self) -> None:
        if self.pipeline is None:
            return
        try:
            self.src.emit("end-of-stream")
        except Exception:  # noqa: BLE001
            pass
        self.pipeline.set_state(Gst.State.NULL)
        try:
            self.sink.disconnect(self._sig)
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._meta.clear()
        self.pipeline = self.src = self.sink = self._bus = None
