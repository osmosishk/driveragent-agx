"""Local mode: frames from the rk-camd frame socket on this machine. No network, no encode, no decode.

For a unit where the camera daemon and this inference node run on the same board (the Jetson single-camera
unit). The source is a consumer of the rk-camd local frame protocol v2 (driveragent-hmi rk/camd/src/protocol.h):
AF_UNIX SOCK_SEQPACKET, one DMA-BUF fd per ring buffer (SCM_RIGHTS), FRAME messages that lend a buffer, RELEASE
when done. Only the RAW stream of one rk-camd camera is used, and it must be NV12 (the Jetson rk-camd; the
RK3588 RAW stream is UYVY and goes over FrameLink instead).

Per frame: the lent buffer is mapped read-only (mapped once per session), the luma and chroma rows are copied
without their row padding into one tightly packed NV12 array (the Frame format of the frame store), and the
buffer is released at once. The frame store keeps only the newest frame, so the models never queue frames.

Frame identity: seq = the low 32 bits of rk-camd frame_no; t_capture_ns = the rk-camd capture time
(CLOCK_MONOTONIC) moved to CLOCK_REALTIME with the offset of this moment (one machine, so no clock error).
Frames are "live".

Link daemon (rk_agxlink.py of driveragent-hmi): it gives a result to the HMI only when it knows the frame
(cam, seq) from the sender's FRAME notification. On the RK3588 the FrameLink sender writes those. Here there is
no sender, so this source writes the same notifications (contract C2, 48-byte FRAME; STATS and SENDER once per
second) to local.notify_socket when it is set. A daemon that is absent costs nothing (non-blocking datagrams).

config/sources.yaml:
    mode: local
    local:
      socket: /run/user/1000/driveragent/frames.sock    # or the environment variable AGX_LOCAL_FRAME_SOCKET
      notify_socket: /run/user/1000/driveragent/agx-link.sock   # "" = no notifications (AGX_LOCAL_NOTIFY_SOCKET)
      rk_cam: 0          # rk-camd cam_id of the stream to use (255 = an unlabelled bench stream)
"""
from __future__ import annotations

import fcntl
import json
import logging
import mmap
import os
import socket
import struct
import threading
import time

import numpy as np

from infer.ingest.frame_store import Frame, FrameStore
from infer.ingest.metrics import CameraMetrics

log = logging.getLogger("infer.ingest.local")

# rk-camd local frame protocol v2 (little-endian, packed)
MAGIC = 0x44434B52          # "RKCD"
VERSION = 2
MSG_HELLO, MSG_STREAM_INFO, MSG_BUFFER, MSG_READY, MSG_FRAME, MSG_RELEASE, MSG_HEALTH = 1, 2, 3, 4, 5, 6, 7
HEADER = struct.Struct("<IHHI")                       # magic, version, type, payload length
HELLO = struct.Struct("<I32s")                        # flags, consumer name
STREAM_INFO = struct.Struct("<BBBB32s16sIHHIIIBBBB")  # 76 B
BUFFER = struct.Struct("<BBH")
FRAME = struct.Struct("<BBHIQQQQI")                   # 44 B
RELEASE = struct.Struct("<BBHQ")
HELLO_RAW_FRAMES = 1 << 1
KIND_RAW = 1
FOURCC_NV12 = int.from_bytes(b"NV12", "little")
# link daemon notifications (driveragent-hmi rk/agxlink/tx/notify.h)
NOTE_FRAME = struct.Struct("<BBHIQQQIIII")            # 48 B: type 1, cam, flags, seq, t_capture_mono_ns,
                                                      # t_capture_real_ns, t_sent_mono_ns, frame_no,
                                                      # v4l2_sequence, au_bytes, enc_us
NOTE_STATS, NOTE_SENDER = 2, 3
# DMA-BUF CPU access bracket (linux/dma-buf.h): _IOW('b', 0, struct dma_buf_sync {__u64 flags})
DMA_BUF_IOCTL_SYNC = 0x40086200
DMA_SYNC_READ, DMA_SYNC_START, DMA_SYNC_END = 1, 0, 4
RETRY_S = 2.0


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("utf-8", "replace")


class LocalSource:
    def __init__(self, cam: int, store: FrameStore, metrics: CameraMetrics, socket_path: str,
                 notify_socket: str = "", rk_cam: int = 0):
        self.cam = cam                    # camera id on the AGX side (FrameLink cam, result camId)
        self.store = store
        self.metrics = metrics
        self.socket_path = socket_path
        self.notify_path = notify_socket
        self.rk_cam = rk_cam              # rk-camd cam_id of the stream to use
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._notify: socket.socket | None = None
        self.frames = 0
        self.sessions = 0
        self.errors = 0

    # -- life cycle ---------------------------------------------------------------------------------
    def start(self) -> None:
        if not self.socket_path:
            self.metrics.set_error("local mode: no frame socket (config local.socket or AGX_LOCAL_FRAME_SOCKET)")
            return
        if self.notify_path:
            self._notify = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self._notify.setblocking(False)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"local-cam{self.cam}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._notify is not None:
            self._notify.close()
            self._notify = None

    # -- notifications to the link daemon -----------------------------------------------------------
    def _note(self, data: bytes) -> None:
        if self._notify is None:
            return
        try:
            self._notify.sendto(data, self.notify_path)
        except OSError:
            pass   # no daemon, or its socket is full: never a wait

    # -- one session with rk-camd -------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._session()
            except OSError as e:
                self.errors += 1
                self.metrics.set_error(f"frame socket {self.socket_path}: {e}")
            except ValueError as e:
                self.errors += 1
                self.metrics.set_error(f"frame socket protocol: {e}")
            self.metrics.set_counters(local_sessions=self.sessions, local_errors=self.errors)
            self._note(bytes([NOTE_SENDER]) + json.dumps({"pid": os.getpid(), "camd_connected": False}).encode())
            self._stop.wait(RETRY_S)

    def _session(self) -> None:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        maps: dict[tuple[int, int], tuple[mmap.mmap, np.ndarray, int]] = {}
        try:
            s.settimeout(1.0)
            s.connect(self.socket_path)
            hello = HELLO.pack(HELLO_RAW_FRAMES, b"agx-infer-local")
            s.send(HEADER.pack(MAGIC, VERSION, MSG_HELLO, len(hello)) + hello)
            self.sessions += 1
            infos: dict[int, tuple] = {}
            counts: dict[int, int] = {}
            use = -1                       # stream id of the RAW stream that is used
            last_stats = time.monotonic()
            n_stats = 0
            while not self._stop.is_set():
                try:
                    data, anc, _flags, _addr = s.recvmsg(4096, socket.CMSG_SPACE(4 * 4))
                except socket.timeout:
                    data, anc = None, []
                fds: list[int] = []
                for level, ctype, cdata in anc:
                    if level == socket.SOL_SOCKET and ctype == socket.SCM_RIGHTS:
                        fds.extend(struct.unpack(f"<{len(cdata) // 4}i", cdata[:len(cdata) // 4 * 4]))
                if data is not None:
                    if not data:
                        raise OSError("rk-camd closed the socket")
                    if len(data) < HEADER.size:
                        raise ValueError("short message")
                    magic, version, mtype, plen = HEADER.unpack_from(data)
                    body = data[HEADER.size:]
                    if magic != MAGIC or version != VERSION or plen != len(body):
                        raise ValueError(f"bad header (magic {magic:#x}, version {version}, length {plen})")
                    if mtype == MSG_STREAM_INFO:
                        si = STREAM_INFO.unpack(body)
                        infos[si[0]] = si
                        counts[si[0]] = 0
                    elif mtype == MSG_BUFFER:
                        sid, index, _ = BUFFER.unpack(body)
                        if len(fds) != 1 or sid not in infos or index != counts[sid]:
                            raise ValueError("BUFFER without its fd or out of order")
                        counts[sid] += 1
                        si = infos[sid]
                        if si[15] == KIND_RAW and si[1] == self.rk_cam and si[6] == FOURCC_NV12:
                            mm = mmap.mmap(fds[0], si[11], mmap.MAP_SHARED, mmap.PROT_READ)
                            maps[(sid, index)] = (mm, np.frombuffer(mm, dtype=np.uint8), fds[0])
                            fds = []
                    elif mtype == MSG_READY:
                        use = self._pick(infos)
                        self._note(bytes([NOTE_SENDER]) +
                                   json.dumps({"pid": os.getpid(), "camd_connected": True}).encode())
                    elif mtype == MSG_FRAME:
                        f = FRAME.unpack(body)
                        if f[0] == use:
                            self._frame(infos[use], maps.get((f[0], f[1])), f)
                            n_stats += 1
                        s.send(HEADER.pack(MAGIC, VERSION, MSG_RELEASE, RELEASE.size) +
                               RELEASE.pack(f[0], f[1], 0, f[4]))
                for fd in fds:             # an fd that was not kept
                    os.close(fd)
                now = time.monotonic()
                if now - last_stats >= 1.0 and use >= 0:
                    si = infos[use]
                    self._note(bytes([NOTE_STATS]) + json.dumps(
                        {"cam": self.cam, "fps": round(n_stats / (now - last_stats), 2), "kbps": 0, "w": si[7],
                         "h": si[8], "errors": self.errors, "skipped": 0, "enc_us_p99": 0}).encode())
                    self._note(bytes([NOTE_SENDER]) +
                               json.dumps({"pid": os.getpid(), "camd_connected": True}).encode())
                    last_stats, n_stats = now, 0
        finally:
            s.close()
            for mm, arr, fd in maps.values():
                del arr
                try:
                    mm.close()
                except BufferError:        # a frame array still refers to it: the map goes with that array
                    pass
                os.close(fd)

    def _pick(self, infos: dict[int, tuple]) -> int:
        """The stream id of the RAW stream of rk_cam. It must be NV12."""
        for sid, si in sorted(infos.items()):
            if si[15] == KIND_RAW and si[1] == self.rk_cam:
                if si[6] != FOURCC_NV12:
                    raise ValueError(f"the RAW stream of rk-camd cam {self.rk_cam} is not NV12 "
                                     f"(fourcc {si[6]:#x}): local mode needs the Jetson rk-camd")
                log.info("local source: cam %d <- rk-camd stream %d (%s, role %s) NV12 %dx%d stride %d, %d buffers",
                         self.cam, sid, _cstr(si[4]), _cstr(si[5]) or "-", si[7], si[8], si[9], si[12])
                return sid
        raise ValueError(f"rk-camd has no RAW stream for cam {self.rk_cam}")

    def _frame(self, si: tuple, mapped, f: tuple) -> None:
        if mapped is None:
            raise ValueError("FRAME for a buffer that was not announced")
        _mm, buf, fd = mapped
        w, h, stride, uv_offset = si[7], si[8], si[9], si[10]
        _sid, _index, _flags, v4l2_seq, frame_no, t_capture_mono, _t_deq, _t_ready, _ts_flags = f
        t0 = time.monotonic_ns()
        sync = struct.pack("<Q", DMA_SYNC_START | DMA_SYNC_READ)
        try:
            fcntl.ioctl(fd, DMA_BUF_IOCTL_SYNC, sync)
        except OSError:
            pass
        nv12 = np.empty((h * 3 // 2, w), dtype=np.uint8)
        nv12[:h] = buf[:stride * h].reshape(h, stride)[:, :w]
        nv12[h:] = buf[uv_offset:uv_offset + stride * (h // 2)].reshape(h // 2, stride)[:, :w]
        try:
            fcntl.ioctl(fd, DMA_BUF_IOCTL_SYNC, struct.pack("<Q", DMA_SYNC_END | DMA_SYNC_READ))
        except OSError:
            pass
        now_mono = time.monotonic_ns()
        now_real = time.time_ns()
        t_capture_real = now_real - (now_mono - t_capture_mono)
        seq = frame_no & 0xFFFFFFFF
        # The daemon must know the frame before a result of it can arrive: notify first, then store.
        self._note(NOTE_FRAME.pack(1, self.cam, 0, seq, t_capture_mono, t_capture_real, now_mono, seq,
                                   v4l2_seq & 0xFFFFFFFF, 0, (now_mono - t0) // 1000))
        frame = Frame(cam=self.cam, seq=seq, t_capture_ns=t_capture_real, t_recv_ns=now_real, t_ready_ns=now_real,
                      width=w, height=h, fmt="nv12", source="live", nv12=nv12,
                      decode_ms=(now_mono - t0) / 1e6)
        self.store.put(frame)
        self.metrics.add_rx(nv12.size, 1)
        self.metrics.on_frame(frame)
        self.frames += 1
