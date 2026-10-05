"""File mode: decode local recordings directly, no network.

filesrc ! qtdemux ! h265parse ! identity sync=true ! nvv4l2decoder ! nvvidconv ! NV12 appsink

identity sync=true paces the compressed stream in real time by the file timestamps (the recordings
are 30/1 fps). The decoder runs free after it, so decode_ms = time from the decoder input pad to
the appsink (same meaning as in the network path). At the end of a file the next file starts; after
the last file the list starts again (loop). Frames get source "file" (simulated).
"""
from __future__ import annotations

import glob
import threading
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from infer.ingest.frame_store import Frame, FrameStore
from infer.ingest.h265_decoder import gst_init, nv12_from_sample
from infer.ingest.metrics import CameraMetrics

PIPELINE = (
    "filesrc name=src ! qtdemux ! h265parse ! identity name=pace sync=true ! "
    "nvv4l2decoder name=dec enable-max-performance=1 ! nvvidconv ! video/x-raw,format=NV12 ! "
    "appsink name=sink emit-signals=true sync=false max-buffers=2 drop=true"
)


def expand_files(files) -> list[str]:
    """Each entry is a path or a glob pattern. Sorted per pattern, order of the list kept."""
    out: list[str] = []
    for f in files or []:
        hits = sorted(glob.glob(f)) if any(ch in f for ch in "*?[") else [f]
        out.extend(hits)
    return out


class FileSource:
    def __init__(self, cam: int, files, store: FrameStore, metrics: CameraMetrics, fps: float = 30):
        self.cam = cam
        self.files = expand_files(files)
        self.store = store
        self.metrics = metrics
        self.fps = fps          # nominal rate; real pacing follows the file timestamps
        self._idx = 0
        self._seq = 0
        self._t_in: dict[int, tuple[int, int]] = {}   # pts -> (monotonic_ns, time_ns) at decoder input
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.pipeline = None
        self.errors = 0
        self.loops = 0

    def start(self) -> None:
        if not self.files:
            self.metrics.set_error("file mode: no files for this camera")
            return
        gst_init()
        self.pipeline = Gst.parse_launch(PIPELINE)
        self.src = self.pipeline.get_by_name("src")
        sink = self.pipeline.get_by_name("sink")
        self._sink = sink
        self._sig = sink.connect("new-sample", self._on_sample)
        dec = self.pipeline.get_by_name("dec")
        self._probe_pad = dec.get_static_pad("sink")
        self._probe_id = self._probe_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_dec_in)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"file-cam{self.cam}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            # break the GObject -> bound method cycles, else the pipeline is never freed
            try:
                self._sink.disconnect(self._sig)
                self._probe_pad.remove_probe(self._probe_id)
            except Exception:  # noqa: BLE001
                pass
            self.pipeline = self.src = self._sink = self._probe_pad = None

    def _play(self, path: str) -> None:
        self.pipeline.set_state(Gst.State.NULL)
        with self._lock:
            self._t_in.clear()
        self.src.set_property("location", path)
        self.pipeline.set_state(Gst.State.PLAYING)

    def _next(self) -> None:
        self._idx += 1
        if self._idx >= len(self.files):
            self._idx = 0
            self.loops += 1
            self.metrics.set_counters(file_loops=self.loops)

    def _run(self) -> None:
        bus = self.pipeline.get_bus()
        self._play(self.files[self._idx])
        while not self._stop.is_set():
            msg = bus.timed_pop_filtered(100 * Gst.MSECOND,
                                         Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if msg is None:
                continue
            if msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                self.errors += 1
                self.metrics.set_counters(decoder_errors=self.errors)
                self.metrics.set_error(f"{self.files[self._idx]}: {err.message}")
                time.sleep(0.5)
            self._next()
            if not self._stop.is_set():
                self._play(self.files[self._idx])

    def _on_dec_in(self, pad, info):
        buf = info.get_buffer()
        if buf is not None:
            self.metrics.add_rx(buf.get_size(), 1)  # compressed bytes into the decoder (bitrate)
            with self._lock:
                self._t_in[buf.pts] = (time.monotonic_ns(), time.time_ns())
                if len(self._t_in) > 256:
                    for k in list(self._t_in)[:128]:
                        del self._t_in[k]
        return Gst.PadProbeReturn.OK

    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        pts = sample.get_buffer().pts
        now_mono_ns = time.monotonic_ns()
        t_ready = time.time_ns()
        with self._lock:
            t_in = self._t_in.pop(pts, None)
        try:
            nv12 = nv12_from_sample(sample)
        except Exception as e:  # noqa: BLE001
            self.errors += 1
            self.metrics.set_error(f"map: {e}")
            return Gst.FlowReturn.OK
        if t_in is None:
            decode_ms, t_cap = 0.0, t_ready
        else:
            decode_ms, t_cap = (now_mono_ns - t_in[0]) / 1e6, t_in[1]
        hh, w = nv12.shape
        self._seq += 1
        f = Frame(cam=self.cam, seq=self._seq, t_capture_ns=t_cap, t_recv_ns=t_cap,
                  t_ready_ns=t_ready, width=w, height=hh * 2 // 3, fmt="h265", source="file",
                  nv12=nv12, decode_ms=decode_ms)
        self.store.put(f)
        self.metrics.on_frame(f)
        return Gst.FlowReturn.OK
