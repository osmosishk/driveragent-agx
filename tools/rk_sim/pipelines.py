"""GStreamer pipelines of the simulator. Each pipeline ends in an appsink named "sink".

The appsink has sync=false: the sender thread paces the frames itself (from the buffer PTS).
max-buffers is small and drop=false, so the pipeline blocks (back pressure) and reads the file
only a few frames ahead.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from infer.ingest.h265_decoder import gst_init, nv12_from_sample  # noqa: E402

SINK = "appsink name=sink emit-signals=false sync=false max-buffers=4 drop=false"
H265_OUT = ("h265parse config-interval=-1 ! "
            "video/x-h265,stream-format=byte-stream,alignment=au ! " + SINK)


def _q(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _enc(cfg) -> str:
    return (f"nvv4l2h265enc bitrate={cfg.h265_bitrate} iframeinterval={cfg.h265_iframeinterval} "
            f"idrinterval={cfg.h265_idrinterval} insert-sps-pps=1 maxperf-enable=1 ! ")


def _fps_frac(fps: float) -> str:
    if abs(fps - round(fps)) < 1e-6:
        return f"{int(round(fps))}/1"
    return f"{int(round(fps * 1000))}/1000"


def file_h265_passthrough(path: str) -> str:
    return f"filesrc location={_q(path)} ! qtdemux ! " + H265_OUT


def file_h265_transcode(path: str, cfg) -> str:
    return (f"filesrc location={_q(path)} ! qtdemux ! h265parse ! "
            "nvv4l2decoder enable-max-performance=1 ! nvvidconv ! "
            f"video/x-raw(memory:NVMM),format=NV12,width={cfg.h265_width},height={cfg.h265_height} ! "
            + _enc(cfg) + H265_OUT)


def file_nv12(path: str, w: int, h: int) -> str:
    return (f"filesrc location={_q(path)} ! qtdemux ! h265parse ! "
            "nvv4l2decoder enable-max-performance=1 ! nvvidconv ! "
            f"video/x-raw,format=NV12,width={w},height={h} ! " + SINK)


def pattern(cam: int, fmt: str, w: int, h: int, fps: float, cfg) -> str:
    # The text of the "counter" overlay is set for every frame by a pad probe (see Source).
    src = (f"videotestsrc pattern=ball is-live=false ! "
           f"video/x-raw,format=NV12,width={w},height={h},framerate={_fps_frac(fps)} ! "
           f'textoverlay text="CAM {cam} SIMULATED" valignment=top halignment=left '
           'font-desc="Sans Bold 28" shaded-background=true ! '
           'textoverlay name=counter text="frame 0" valignment=bottom halignment=right '
           'font-desc="Sans Bold 28" shaded-background=true ! ')
    if fmt == "nv12":
        return src + SINK
    # the capsfilter after textoverlay prevents GStreamer-CRITICAL caps messages from nvvidconv
    return src + "video/x-raw,format=NV12 ! nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! " + _enc(cfg) + H265_OUT


@dataclass
class Out:
    data: object          # bytes (h265) or numpy (h*3/2, w) uint8 (nv12, tightly packed)
    width: int
    height: int
    stride: int
    pts: int              # ns, or -1 when the buffer has no PTS
    duration: int         # ns, or -1


class Source:
    """One GStreamer pipeline with an appsink. Not thread safe: one sender thread uses it."""

    def __init__(self, desc: str, fmt: str, cam: int = 0, label: str = ""):
        gst_init()
        self.desc = desc
        self.fmt = fmt
        self.cam = cam
        self.label = label
        self.pipeline = Gst.parse_launch(desc)
        self.sink = self.pipeline.get_by_name("sink")
        self.bus = self.pipeline.get_bus()
        self.error = ""
        self.frames = 0
        self.playing = False
        self._caps = None
        self._w = self._h = 0
        counter = self.pipeline.get_by_name("counter")
        if counter is not None:
            self._count = 0
            pad = counter.get_static_pad("video_sink")
            pad.add_probe(Gst.PadProbeType.BUFFER, self._on_pattern_buffer, counter)

    def _on_pattern_buffer(self, pad, info, overlay):
        overlay.set_property("text", f"CAM {self.cam} frame {self._count}")
        self._count += 1
        return Gst.PadProbeReturn.OK

    def preroll(self) -> None:
        """Start the pipeline in PAUSED (opens the file, fills the appsink with the first frame)."""
        self.pipeline.set_state(Gst.State.PAUSED)

    def play(self) -> None:
        self.playing = True
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self, drain_timeout_s: float = 1.0) -> None:
        """Stop the pipeline and set it to NULL.

        A direct change to NULL can hang for ever when nvv4l2decoder feeds nvv4l2h265enc and the
        encoder output thread is blocked by a full or prerolled appsink (measured: about 1 stop
        in 6 hangs, JetPack, GStreamer 1.20.3). Thus: appsink drops buffers, pipeline PLAYING,
        EOS sent, the appsink is read until EOS (the pipeline is drained), then NULL."""
        try:
            if not self.eos():
                self.sink.set_property("drop", True)
                self.sink.set_property("max-buffers", 1)
                self.pipeline.set_state(Gst.State.PLAYING)
                self.pipeline.send_event(Gst.Event.new_eos())
                t_end = time.monotonic() + drain_timeout_s
                while time.monotonic() < t_end and not self.eos():
                    self.sink.emit("try-pull-sample", 20 * Gst.MSECOND)
                    if self.bus.have_pending() and self.poll_bus():
                        break
        except Exception:  # noqa: BLE001
            pass
        self.pipeline.set_state(Gst.State.NULL)
        self.playing = False

    def poll_bus(self) -> str:
        while True:
            msg = self.bus.pop_filtered(Gst.MessageType.ERROR)
            if msg is None:
                return self.error
            err, dbg = msg.parse_error()
            self.error = f"{err.message} ({msg.src.get_name() if msg.src else '?'})"

    def eos(self) -> bool:
        return bool(self.sink.get_property("eos"))

    def pull(self, timeout_s: float = 0.2) -> Out | None:
        """Next frame, or None (timeout, end of stream or error: see eos() and poll_bus())."""
        s = self.sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
        if s is None:
            self.poll_bus()
            return None
        buf = s.get_buffer()
        caps = s.get_caps()
        if caps is not self._caps:
            self._caps = caps
            st = caps.get_structure(0)
            self._w = st.get_value("width") or 0
            self._h = st.get_value("height") or 0
        pts = buf.pts if buf.pts != Gst.CLOCK_TIME_NONE else -1
        dur = buf.duration if buf.duration != Gst.CLOCK_TIME_NONE else -1
        self.frames += 1
        if self.fmt == "nv12":
            nv12 = nv12_from_sample(s)
            h, w = nv12.shape[0] * 2 // 3, nv12.shape[1]
            return Out(nv12, w, h, w, pts, dur)
        ok, mi = buf.map(Gst.MapFlags.READ)
        if not ok:
            self.error = "buffer map failed"
            return None
        try:
            data = bytes(mi.data)
        finally:
            buf.unmap(mi)
        return Out(data, self._w, self._h, 0, pts, dur)


def wait_state(src: Source, timeout_s: float = 5.0) -> bool:
    """Wait until the pipeline reached its target state. False on error or timeout."""
    ret, _cur, _pend = src.pipeline.get_state(int(timeout_s * Gst.SECOND))
    return ret in (Gst.StateChangeReturn.SUCCESS, Gst.StateChangeReturn.NO_PREROLL)


