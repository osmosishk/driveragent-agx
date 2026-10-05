"""FrameLink receiver for ONE camera: UDP socket -> reassembly -> FrameLink check -> FrameStore.

Two receive paths (same frame handling after the reassembly):
  use_process=True (default): a receive process (infer/ingest/rx_proc.py) drains the socket
    (recv_into a preallocated buffer) and reassembles into a shared-memory ring. One thread here
    reads the pipe, copies the frame from the ring and handles it.
  use_process=False: one thread here drains the socket and uses common.framelink.Reassembler.
    Unit tests call handle_datagram() directly (no socket).
Frame handling: header CRC + payload CRC (bad frames counted), seq gaps (lost frames).
NV12 frames go to the store in the receive thread. H.265 frames go to the hardware decoder; the
decoder callback (GStreamer thread) puts the decoded frame in the store. H.265 frames before the
first IDR (and after a loss, until the next IRAP picture) are dropped and counted in waiting_idr.

Robustness:
  - The receive process is supervised: when it ends (crash, kill), it starts again after a
    backoff (0.5 s, doubled up to 5 s). Counter rx_restarts.
  - An exception in the per-frame / per-datagram work is counted (internal_errors) and the
    thread continues.
  - A seq jump back (sender restart) resets the H.265 gate: the new stream must start with an
    IDR + VPS/SPS/PPS again.
  - The spawn start method imports the caller's main module in the child: a caller script must use
    `if __name__ == "__main__":`.

Source label (R13): Frame.source is "live" only when the FrameLink source byte is SOURCE_LIVE AND
the configured mode is "rk" (expect_simulated False). In sim mode every frame is simulated: a frame
with source byte LIVE gets the label "replay" and the counter source_mismatch goes up.
"""
from __future__ import annotations

import socket
import threading
import time

import numpy as np

from common import framelink as fl
from infer.ingest.frame_store import Frame, FrameStore
from infer.ingest.metrics import CameraMetrics

NAL_IDR = (19, 20)          # IDR_W_RADL, IDR_N_LP
NAL_RAP = (16, 17, 18, 19, 20, 21)   # BLA, IDR, CRA: random access points (IRAP)
NAL_PARAM = (32, 33, 34)    # VPS, SPS, PPS
DGRAM_MAX = 65536


def rmem_max() -> int:
    try:
        with open("/proc/sys/net/core/rmem_max") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return 212992


def h265_nal_types(au, limit: int = 16) -> list[int]:
    """NAL unit types of an Annex-B access unit (first `limit` NAL units)."""
    b = bytes(au) if not isinstance(au, (bytes, bytearray)) else au
    out = []
    i = b.find(b"\x00\x00\x01")
    while i >= 0 and len(out) < limit:
        j = i + 3
        if j < len(b):
            out.append((b[j] >> 1) & 0x3F)
        i = b.find(b"\x00\x00\x01", j)
    return out


def has_idr(au) -> bool:
    return any(t in NAL_IDR for t in h265_nal_types(au))


class IdrGate:
    """Drops H.265 access units until the decoder can start (or restart after a loss).

    Start: the first AU must hold an IDR (19/20) or another IRAP picture (16-21) together with
    VPS/SPS/PPS (32-34). Restart after a loss (resync()): an IRAP picture is sufficient when the
    parameter sets were seen before. Reason: the old recordings have an IDR with VPS/SPS/PPS only
    every 256 frames, but a CRA (21) every 30 frames; there are no leading pictures (no B-frames).
    """

    def __init__(self):
        self.waiting = True
        self.have_params = False
        self.dropped = 0

    def resync(self) -> None:
        self.waiting = True

    def accept(self, au) -> bool:
        if not self.waiting:
            return True
        types = h265_nal_types(au)
        params = all(t in types for t in NAL_PARAM)
        if params:
            self.have_params = True
        if self.have_params and any(t in NAL_RAP for t in types):
            self.waiting = False
            return True
        self.dropped += 1
        return False


def source_label(source_byte: int, expect_simulated: bool) -> tuple[str, bool]:
    """Return (label, mismatch)."""
    if source_byte == fl.SOURCE_LIVE:
        if expect_simulated:
            return "replay", True
        return "live", False
    return fl.SOURCE_NAMES.get(source_byte, "unknown"), False


class _RemoteCounters:
    """Reassembler counters reported by the receive process. Cumulative over restarts of the
    receive process: `base` holds the totals of the earlier processes."""

    FIELDS = ("datagrams", "bytes", "lost_fragments", "abandoned", "bad", "late", "new_streams",
              "start_partial")

    def __init__(self):
        for k in self.FIELDS:
            setattr(self, k, 0)
        self.base = dict.fromkeys(self.FIELDS, 0)
        self.last_error = ""

    def update(self, vals: dict) -> None:
        for k, v in vals.items():
            setattr(self, k, self.base[k] + v)

    def new_process(self) -> None:
        self.base = {k: getattr(self, k) for k in self.FIELDS}


class LateFilterReassembler(fl.Reassembler):
    """common.framelink.Reassembler with the late-fragment rule of rx_proc.ShmReassembler.

    The reference Reassembler opens a new frame for a duplicate or late fragment of a frame that
    is already complete; that frame is later abandoned and counts count-1 lost fragments (no data
    was lost). common/ is read-only here, thus this subclass drops such fragments before the
    reference code sees them and counts them in `late`. Same new-stream rule as ShmReassembler.
    """

    def __init__(self, cam: int, *a, late_window: int = 8, **kw):
        super().__init__(cam, *a, **kw)
        self.late_window = late_window
        self.late = 0
        self.new_streams = 0
        self.start_partial = 0
        self.last_done: int | None = None
        self._t_rx: float | None = None
        self._first = True
        self._join_seq: int | None = None   # first frame, joined in the middle (not a loss)

    def _abandon(self, s):
        if s.seq >= 0 and s.seq == self._join_seq:
            self.start_partial += 1
            self._join_seq = None
            s.seq = -1
            return
        super()._abandon(s)

    def push(self, dgram, now: float | None = None):
        now = time.monotonic() if now is None else now
        quiet = self._t_rx is not None and now - self._t_rx >= self.timeout_s
        self._t_rx = now
        if self._first and len(dgram) >= fl.FRAG_LEN:
            self._first = False
            hdr = fl.FRAG.unpack_from(dgram)
            if hdr[4] != 0:
                self._join_seq = hdr[3]
        if len(dgram) >= fl.FRAG_LEN and self.last_done is not None:
            magic, ver, _cam, seq, _idx, _count, _off = fl.FRAG.unpack_from(dgram)
            if magic == fl.FRAG_MAGIC and ver == fl.FRAG_VERSION and \
                    not any(sl.seq == seq for sl in self.slots):
                back = (self.last_done - seq) & 0xFFFFFFFF
                if back < 0x80000000 and (back > self.late_window or (quiet and back > 0)):
                    self.new_streams += 1
                    self.last_done = None
                elif back <= self.late_window:
                    self.datagrams += 1
                    self.bytes += len(dgram)
                    self.late += 1
                    return None
        out = super().push(dgram, now)
        if out is not None:
            self.last_done = fl.FRAG.unpack_from(dgram)[3]
            self._join_seq = None
        return out


class FrameLinkReceiver:
    def __init__(self, cam: int, port: int, bind_host: str, store: FrameStore,
                 metrics: CameraMetrics, expect_simulated: bool = True,
                 h265_resync_on_loss: bool = True, rcvbuf: int = 0,
                 reassembly_timeout_s: float = 0.2, use_process: bool = True,
                 ring_slots: int = 8, max_frame: int = 2 * 1024 * 1024,
                 decoder_prestart: bool = False):
        self.cam = cam
        self.port = port
        self.bind_host = bind_host
        self.store = store
        self.metrics = metrics
        self.expect_simulated = expect_simulated
        self.h265_resync_on_loss = h265_resync_on_loss
        self.rcvbuf_req = rcvbuf or rmem_max()
        self.reassembly_timeout_s = reassembly_timeout_s
        self.use_process = use_process
        self.ring_slots = ring_slots
        self.max_frame = max_frame
        self.reasm = LateFilterReassembler(cam, max_frame=max_frame,
                                           timeout_s=reassembly_timeout_s)
        self.ring_overruns = 0
        self.decoder_prestart = decoder_prestart
        self._proc = None
        self._shm = None
        self._conn = None
        self._stop_evt = None
        self.decoder = None
        self.gate = IdrGate()
        self._last_seq: int | None = None
        self.lost_frames = 0
        self.bad_frames = 0
        self.seq_resets = 0
        self.waiting_idr = 0
        self.source_mismatch = 0
        self.foreign_frames = 0     # frames with the header of another camera (not a loss here)
        self.rx_restarts = 0
        self.internal_errors = 0
        self.rx_pid = None
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pend_bytes = 0
        self._pend_dg = 0
        self._t_flush = 0.0
        self.rcvbuf = None

    # ---- lifecycle ---------------------------------------------------------------------------------
    def _make_decoder(self) -> None:
        from infer.ingest.h265_decoder import H265Decoder  # GStreamer only when needed
        self.decoder = H265Decoder(self.cam, self._on_decoded)

    def start(self) -> None:
        # a new start = a new decoder and a new stream: the gate waits for IDR + VPS/SPS/PPS
        self.gate = IdrGate()
        self._last_seq = None
        # The first decoder creation takes about 0.15 s (more with six cameras at the same time).
        # Create it before the first frame, so that the first IDR frames are not lost.
        if self.decoder_prestart and self.decoder is None:
            self._make_decoder()
        if self.use_process:
            self._start_process()
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf_req)
        except OSError:
            pass
        self.rcvbuf = s.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        s.bind((self.bind_host, self.port))
        s.settimeout(0.1)
        self._sock = s
        self.metrics.set_counters(rcvbuf=self.rcvbuf)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"flrx-cam{self.cam}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._stop_evt is not None:
            self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._stop_child()
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if self.decoder is not None:
            self.decoder.close()
            self.decoder = None

    # ---- process mode -----------------------------------------------------------------------------
    def _spawn_child(self) -> None:
        """Start the receive process and wait for "ready". Sets _proc, _shm, _conn, _stop_evt.
        Raises OSError (and cleans up) when the process does not get ready."""
        import multiprocessing as mp
        from multiprocessing import shared_memory

        from infer.ingest import rx_proc

        ctx = mp.get_context("spawn")  # no fork of a process with GStreamer threads
        size = self.ring_slots * (rx_proc.SLOT_HDR_LEN + self.max_frame)
        self._shm = shared_memory.SharedMemory(create=True, size=size)
        rd, wr = ctx.Pipe(duplex=False)
        self._stop_evt = ctx.Event()
        self._proc = ctx.Process(
            target=rx_proc.run, name=f"flrx-cam{self.cam}", daemon=True,
            args=(self.cam, self.bind_host, self.port, self.rcvbuf_req, self._shm.name,
                  self.ring_slots, self.max_frame, wr, self._stop_evt, self.reassembly_timeout_s))
        self._proc.start()
        wr.close()
        self._conn = rd
        try:
            msg = rd.recv() if rd.poll(10.0) else ("err", "receive process did not start in 10 s")
        except (EOFError, OSError) as e:
            self._proc.join(2.0)
            msg = ("err", f"receive process ended at start (exit code {self._proc.exitcode}). "
                          "With the spawn start method the caller script must use "
                          "'if __name__ == \"__main__\":'. "
                          f"({type(e).__name__}{': ' + str(e) if str(e) else ''})")
        if msg[0] != "ready":
            self._stop_child()
            raise OSError(f"cam{self.cam}: {msg[1]}")
        self.rcvbuf = msg[1]
        self.rx_pid = msg[2]
        self.metrics.set_counters(rcvbuf=self.rcvbuf)

    def _stop_child(self) -> None:
        if self._stop_evt is not None:
            self._stop_evt.set()
        if self._conn is not None:
            self._conn.close()  # a child blocked in send() gets BrokenPipeError and ends
            self._conn = None
        if self._proc is not None:
            self._proc.join(timeout=2.0)
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=1.0)
            self._proc = None
        if self._shm is not None:
            try:
                self._shm.close()
            except BufferError:
                pass
            try:
                self._shm.unlink()
            except FileNotFoundError:
                pass
            self._shm = None
        self._stop_evt = None

    def _start_process(self) -> None:
        self._spawn_child()
        self.reasm = _RemoteCounters()
        self._stop.clear()
        self._thread = threading.Thread(target=self._supervise, name=f"flrx-cam{self.cam}",
                                        daemon=True)
        self._thread.start()

    def _supervise(self) -> None:
        """Read the pipe of the receive process. When the process ends, start it again."""
        backoff = 0.5
        while not self._stop.is_set():
            t_up = time.monotonic()
            reason = self._run_pipe()
            if self._stop.is_set():
                break
            self.metrics.set_error(f"receive process ended ({reason}); restart in {backoff:.1f} s")
            self._stop_child()
            if time.monotonic() - t_up > 30.0:
                backoff = 0.5   # it ran for some time: start again fast
            while not self._stop.is_set():
                if self._stop.wait(backoff):
                    break
                backoff = min(5.0, backoff * 2)
                try:
                    self._spawn_child()
                except Exception as e:  # noqa: BLE001
                    self.metrics.set_error(f"receive process restart failed: {e}")
                    continue
                self.reasm.new_process()
                self.rx_restarts += 1
                self.metrics.set_error("")
                self.flush()
                break

    def _run_pipe(self) -> str:
        from infer.ingest import rx_proc

        conn = self._conn
        smv = self._shm.buf
        r = self.reasm
        t_house = time.monotonic()
        reason = "stop"
        try:
            while not self._stop.is_set():
                try:
                    if not conn.poll(0.1):
                        self.housekeeping()
                        if self._proc is not None and not self._proc.is_alive():
                            reason = f"exit code {self._proc.exitcode}"
                            break
                        continue
                    msg = conn.recv()
                except (EOFError, OSError) as e:
                    reason = f"pipe: {type(e).__name__}"
                    break
                try:
                    kind = msg[0]
                    if kind == "f":
                        _, slot, gen, ln, t_recv_ns, nfrags = msg
                        off = rx_proc.slot_offset(slot, self.max_frame) + rx_proc.SLOT_HDR_LEN
                        raw = bytes(smv[off:off + ln])
                        if rx_proc.SLOT_HDR.unpack_from(smv, off - rx_proc.SLOT_HDR_LEN)[0] != gen:
                            # the child wrote this slot again: frame is lost (the next frame
                            # shows the seq gap, thus lost_frames counts it there)
                            self.ring_overruns += 1
                            continue
                        self._on_complete(raw, t_recv_ns, nfrags)
                    elif kind == "s":
                        _, dg, nb, lf, ab, bad, err, late, ns, sp = msg
                        ddg, dnb = dg - (r.datagrams - r.base["datagrams"]), \
                            nb - (r.bytes - r.base["bytes"])
                        r.update(dict(datagrams=dg, bytes=nb, lost_fragments=lf, abandoned=ab,
                                      bad=bad, late=late, new_streams=ns, start_partial=sp))
                        if ddg:
                            self._pend_dg += ddg
                            self._pend_bytes += dnb
                        if err and err != r.last_error:
                            r.last_error = err
                            self.metrics.set_error(err)
                except Exception as e:  # noqa: BLE001 - one bad frame must not stop the camera
                    self.internal_errors += 1
                    self.metrics.set_error(f"internal: {type(e).__name__}: {e}")
                now = time.monotonic()
                if now - t_house > 0.5:
                    t_house = now
                    self.housekeeping()
                else:
                    self.flush(now)
        finally:
            del smv
        return reason

    def _run(self) -> None:
        buf = bytearray(DGRAM_MAX)
        mv = memoryview(buf)
        sock = self._sock
        while not self._stop.is_set():
            try:
                n = sock.recv_into(buf)
            except socket.timeout:
                self.housekeeping()
                continue
            except OSError as e:
                if self._stop.is_set():
                    break
                self.metrics.set_error(f"recv: {e}")
                time.sleep(0.05)
                continue
            try:
                self.handle_datagram(mv[:n])
            except Exception as e:  # noqa: BLE001 - one bad datagram must not stop the camera
                self.internal_errors += 1
                self.metrics.set_error(f"internal: {type(e).__name__}: {e}")

    # ---- datagram path (no socket needed: unit tests call this directly) -----------------------------
    def handle_datagram(self, dgram, now_mono: float | None = None) -> Frame | None:
        now = time.monotonic() if now_mono is None else now_mono
        self._pend_bytes += len(dgram)
        self._pend_dg += 1
        out = self.reasm.push(dgram, now)
        frame = None
        if out is not None:
            t_recv_ns = time.time_ns()
            frame = self._on_complete(out, t_recv_ns, fl.FRAG.unpack_from(dgram)[5])
        if out is not None or now - self._t_flush >= 0.02:
            self.flush(now)
        return frame

    def flush(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self._pend_dg:
            self.metrics.add_rx(self._pend_bytes, self._pend_dg, now)
            self._pend_bytes = self._pend_dg = 0
        self._t_flush = now
        r = self.reasm
        dec = self.decoder
        self.metrics.set_counters(
            lost_fragments=r.lost_fragments, abandoned_frames=r.abandoned,
            bad_datagrams=r.bad, bad_frames=self.bad_frames, lost_frames=self.lost_frames,
            late_datagrams=getattr(r, "late", 0), new_streams=getattr(r, "new_streams", 0),
            start_partial=getattr(r, "start_partial", 0),
            foreign_frames=self.foreign_frames, rx_restarts=self.rx_restarts,
            internal_errors=self.internal_errors,
            waiting_idr=self.waiting_idr, seq_resets=self.seq_resets,
            source_mismatch=self.source_mismatch, ring_overruns=self.ring_overruns,
            decoder_errors=dec.errors if dec else 0,
            decoder_drops=max(0, dec.pushed - dec.decoded - len(dec._meta)) if dec else 0)

    def housekeeping(self) -> None:
        if self.decoder is not None:
            err = self.decoder.poll_errors()
            if err:
                self.metrics.set_error(err)
        self.flush()

    def _on_complete(self, raw: bytes, t_recv_ns: int, nfrags: int) -> Frame | None:
        try:
            h, payload = fl.unpack_frame(raw, check_payload_crc=False)
        except fl.FrameError as e:
            # header bad: seq unknown, the frame shows up later as a seq gap (in lost_frames)
            self.bad_frames += 1
            self.metrics.set_error(str(e))
            return None
        if h.cam != self.cam:
            # a frame of another camera: not a frame of this stream, thus not a loss here
            self.foreign_frames += 1
            self.metrics.set_error(f"cam {h.cam} on port of cam {self.cam}")
            return None
        # seq gaps (lost frames). A large jump back = sender restart, not loss.
        gap = 0
        if self._last_seq is not None:
            d = (h.seq - self._last_seq) & 0xFFFFFFFF
            if d == 0:
                return None  # duplicate frame
            if d >= 0x80000000 or d > 100000:
                # sender restart: a new stream. The H.265 decoder must start again with an IDR
                # and the (maybe new) VPS/SPS/PPS of the new stream.
                self.seq_resets += 1
                self.gate.resync()
                self.gate.have_params = False
            else:
                gap = d - 1
        self._last_seq = h.seq
        self.lost_frames += gap
        if fl.crc32c(payload) != h.payload_crc32c:
            # header good, payload bad: seq known, count the frame as lost here
            self.bad_frames += 1
            self.lost_frames += 1
            self.metrics.set_error("payload crc mismatch")
            if h.fmt == fl.FMT_H265 and self.h265_resync_on_loss:
                self.gate.resync()
            return None
        self.metrics.health = h.health
        label, mismatch = source_label(h.source, self.expect_simulated)
        if mismatch:
            self.source_mismatch += 1

        if h.fmt == fl.FMT_NV12:
            return self._nv12(h, payload, t_recv_ns, label, nfrags)
        if h.fmt == fl.FMT_H265:
            self._h265(h, payload, t_recv_ns, label, nfrags, gap)
            return None
        self.bad_frames += 1
        self.lost_frames += 1     # header good, seq known: the frame does not get to the store
        self.metrics.set_error(f"unknown fmt {h.fmt}")
        return None

    def _nv12(self, h, payload, t_recv_ns, label, nfrags) -> Frame | None:
        w, ht = h.width, h.height
        stride = h.stride or w
        rows = ht * 3 // 2
        if w == 0 or ht == 0 or stride < w or len(payload) < stride * rows:
            self.bad_frames += 1
            self.lost_frames += 1
            self.metrics.set_error(f"nv12 size: {w}x{ht} stride {stride} payload {len(payload)}")
            return None
        src = np.frombuffer(payload, dtype=np.uint8, count=stride * rows).reshape(rows, stride)
        nv12 = np.ascontiguousarray(src[:, :w])  # copy: the payload buffer is not kept
        f = Frame(cam=self.cam, seq=h.seq, t_capture_ns=h.t_capture_ns, t_recv_ns=t_recv_ns,
                  t_ready_ns=t_recv_ns, width=w, height=ht, fmt="nv12", source=label, nv12=nv12,
                  decode_ms=0.0)
        self.store.put(f)
        self.metrics.on_frame(f, nfrags)
        return f

    def _h265(self, h, payload, t_recv_ns, label, nfrags, gap) -> None:
        if gap and self.h265_resync_on_loss:
            self.gate.resync()
        if not self.gate.accept(payload):
            self.waiting_idr += 1
            return
        if self.decoder is None:
            self._make_decoder()
        meta = {"seq": h.seq, "t_capture_ns": h.t_capture_ns, "t_recv_ns": t_recv_ns,
                "source": label, "nfrags": nfrags}
        self.decoder.push(bytes(payload), meta)

    def _on_decoded(self, cam, nv12, meta, decode_ms) -> None:
        t_ready = time.time_ns()
        hh, w = nv12.shape
        f = Frame(cam=cam, seq=meta["seq"], t_capture_ns=meta["t_capture_ns"],
                  t_recv_ns=meta["t_recv_ns"], t_ready_ns=t_ready, width=w, height=hh * 2 // 3,
                  fmt="h265", source=meta["source"], nv12=nv12, decode_ms=decode_ms)
        self.store.put(f)
        self.metrics.on_frame(f, meta.get("nfrags"))
