"""Receive process for ONE camera port (no GIL sharing with the main process).

Reason: rmem_max is 212992 B, thus a socket holds only about 25-35 jumbo datagrams (a few ms of
cam0 NV12). Six receive threads in one Python process share the GIL; a thread that waits for the
GIL lets its socket overflow (measured: cam0 NV12 6 fps, UDP RcvbufErrors up). In its own process
the receive loop drains the socket without waiting.

The process does: recv_into (preallocated buffer) -> ShmReassembler, which writes each fragment
directly into a slot of a shared-memory ring (no copy of the full frame in this process). When a
frame is complete, a small message on a pipe tells the main process (slot, generation, length,
t_recv_ns, fragment count). The main process copies the slot, checks the generation again (slot
overrun) and does the CRC check and the rest.

Slot layout: u64 generation (0 while the slot is written) + frame bytes (FrameLink header+payload).

Keep the imports small: the spawn start method imports this module in the child.
"""
from __future__ import annotations

import os
import socket
import struct
import time

from common import framelink as fl

SLOT_HDR = struct.Struct("<Q")   # generation counter at the start of each slot
SLOT_HDR_LEN = 8
DGRAM_MAX = 65536


def slot_offset(slot: int, slot_size: int) -> int:
    return slot * (SLOT_HDR_LEN + slot_size)


class _Inflight:
    __slots__ = ("seq", "slot", "gen", "base", "count", "got", "seen", "size", "t_first", "t_last",
                 "joined")


class ShmReassembler:
    """Same rules and counters as common.framelink.Reassembler, but the fragments go directly
    into ring slots of `buf` (a memoryview of nslots * (8 + slot_size) bytes).
    Differences:
    - A fragment of a frame that is at most `late_window` frames behind the newest complete frame
      (duplicate or late datagram) is dropped and counted in `late`. The reference Reassembler
      opens a new frame for it, which later counts as abandoned with count-1 lost fragments.
    - A larger jump back, or any fragment after the socket was quiet for timeout_s or longer, is
      a NEW STREAM (sender restart, seq starts again): the fragment is accepted (`new_streams` +1).
      Before this fix a window of 1000 frames dropped a restarted stream for up to 33 s and no
      counter showed it.
    - A partial frame is NOT abandoned because the socket is quiet (sender pause, SIGSTOP). It is
      abandoned only when a newer frame completes, when max_inflight frames are open, or when it
      gets no fragment for timeout_s while other datagrams arrive.
    - A fragment with a cam field that is not this camera is bad (`bad` +1).
    - The receiver can start in the middle of a frame (the sender already runs). The FIRST frame
      opened with a fragment index > 0 is not counted as abandoned or lost when it does not
      complete; it is counted in `start_partial`.

    At most max_inflight frames are open; a new frame abandons the oldest one. A complete frame
    abandons all older open frames (newest frame wins). max_inflight < nslots, thus an open frame
    never shares its slot with a newer one.
    """

    def __init__(self, cam: int, buf, nslots: int, slot_size: int, timeout_s: float = 0.2,
                 max_inflight: int = 4, late_window: int | None = None):
        if max_inflight >= nslots:
            raise ValueError("max_inflight must be smaller than nslots")
        self.cam = cam
        self.buf = buf
        self.nslots = nslots
        self.slot_size = slot_size
        self.timeout_s = timeout_s
        self.max_inflight = max_inflight
        self.late_window = 2 * max_inflight if late_window is None else late_window
        self.open: dict[int, _Inflight] = {}
        self.gen = 0
        self.lost_fragments = 0
        self.abandoned = 0
        self.bad = 0
        self.datagrams = 0
        self.bytes = 0
        self.last_error = ""
        self.late = 0
        self.last_done: int | None = None
        self.new_streams = 0
        self.start_partial = 0
        self._t_expire = 0.0
        self._t_rx: float | None = None

    def _abandon(self, f: _Inflight) -> None:
        if f.joined:   # receiver started in the middle of this frame: not a loss
            self.start_partial += 1
            del self.open[f.seq]
            return
        self.abandoned += 1
        self.lost_fragments += f.count - f.got
        del self.open[f.seq]

    def expire(self, now: float) -> None:
        """Abandon partial frames older than timeout_s. The receive loop does NOT call this when
        the socket is quiet (a sender pause is not a loss); kept for tests and callers."""
        for f in [f for f in self.open.values() if now - f.t_last > self.timeout_s]:
            self._abandon(f)

    def push(self, dgram, now: float):
        """Feed one datagram. Returns (slot, gen, size, count) of a complete frame, or None."""
        self.datagrams += 1
        n = len(dgram)
        self.bytes += n
        quiet = self._t_rx is not None and now - self._t_rx >= self.timeout_s
        self._t_rx = now
        if n < fl.FRAG_LEN:
            self.bad += 1
            self.last_error = "short datagram"
            return None
        magic, ver, fcam, seq, idx, count, off = fl.FRAG.unpack_from(dgram)
        dn = n - fl.FRAG_LEN
        if magic != fl.FRAG_MAGIC or ver != fl.FRAG_VERSION or count == 0 or idx >= count or \
                off + dn > self.slot_size:
            self.bad += 1
            self.last_error = "bad fragment header" if off + dn <= self.slot_size else \
                f"frame larger than max_frame_bytes {self.slot_size}"
            return None
        if fcam != self.cam:
            self.bad += 1
            self.last_error = f"fragment of cam {fcam} on the port of cam {self.cam}"
            return None
        f = self.open.get(seq)
        if f is None:
            if self.last_done is not None:
                back = (self.last_done - seq) & 0xFFFFFFFF
                if back < 0x80000000 and (back > self.late_window or (quiet and back > 0)):
                    # large jump back, or first datagram after a quiet socket: new stream
                    self.new_streams += 1
                    self.last_done = None
                elif back <= self.late_window:
                    # fragment of a frame that is complete or a few frames older than the
                    # newest complete frame (duplicate or late datagram): not a new frame,
                    # not a loss
                    self.late += 1
                    return None
            if len(self.open) >= self.max_inflight:
                self._abandon(min(self.open.values(), key=lambda x: x.t_first))
            self.gen += 1
            f = _Inflight()
            f.seq, f.gen, f.count, f.got, f.size = seq, self.gen, count, 0, 0
            f.slot = self.gen % self.nslots
            f.base = slot_offset(f.slot, self.slot_size) + SLOT_HDR_LEN
            f.seen = bytearray(count)
            f.t_first = now
            f.joined = self.gen == 1 and idx != 0
            SLOT_HDR.pack_into(self.buf, f.base - SLOT_HDR_LEN, 0)  # slot is being written
            self.open[seq] = f
        elif idx >= f.count or f.seen[idx]:
            return None  # duplicate (or inconsistent count)
        f.seen[idx] = 1
        b = f.base + off
        self.buf[b:b + dn] = dgram[fl.FRAG_LEN:]
        f.got += 1
        f.t_last = now
        if idx == count - 1:
            f.size = off + dn
        if now - self._t_expire > 0.01:
            self._t_expire = now
            for o in [o for o in self.open.values() if o is not f and now - o.t_last > self.timeout_s]:
                self._abandon(o)
        if f.got == f.count:
            del self.open[seq]
            self.last_done = seq
            for o in [o for o in self.open.values() if ((seq - o.seq) & 0xFFFFFFFF) < 0x80000000]:
                self._abandon(o)
            SLOT_HDR.pack_into(self.buf, f.base - SLOT_HDR_LEN, f.gen)
            return f.slot, f.gen, f.size, f.count
        return None


def run(cam: int, bind_host: str, port: int, rcvbuf: int, shm_name: str, nslots: int,
        slot_size: int, conn, stop_evt, reassembly_timeout_s: float = 0.2,
        stats_interval_s: float = 0.05) -> None:
    import gc
    from multiprocessing import shared_memory

    # The main process owns and unlinks the segment. The spawn child uses the resource tracker of
    # the main process, thus do not unregister here (that removes the entry of the main process).
    shm = shared_memory.SharedMemory(name=shm_name)
    ppid = os.getppid()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        except OSError:
            pass
        sock.bind((bind_host, port))
    except OSError as e:
        conn.send(("err", f"bind {bind_host}:{port}: {e}"))
        sock.close()
        shm.close()
        return
    sock.settimeout(0.1)
    conn.send(("ready", sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF), os.getpid()))

    smv = shm.buf
    r = ShmReassembler(cam, smv, nslots, slot_size, reassembly_timeout_s,
                       max_inflight=min(4, nslots - 1))
    buf = bytearray(DGRAM_MAX)
    mv = memoryview(buf)
    recv_into = sock.recv_into
    push = r.push
    mono = time.monotonic
    send = conn.send
    t_stats = 0.0
    gc.freeze()          # few objects live here; no long GC pauses in the receive loop

    def stats():
        send(("s", r.datagrams, r.bytes, r.lost_fragments, r.abandoned, r.bad, r.last_error,
              r.late, r.new_streams, r.start_partial))

    try:
        while True:
            try:
                n = recv_into(buf)
            except socket.timeout:
                now = mono()
                # no r.expire(now) here: a quiet socket (sender pause) is not a loss. The
                # partial frame continues when the sender continues.
                stats()
                t_stats = now
                if stop_evt.is_set() or os.getppid() != ppid:
                    break  # stop, or the main process is gone
                continue
            now = mono()
            out = push(mv[:n], now)
            if out is not None:
                send(("f", out[0], out[1], out[2], time.time_ns(), out[3]))
            if now - t_stats >= stats_interval_s:
                t_stats = now
                stats()
                if stop_evt.is_set():
                    break
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        sock.close()
        r.buf = None
        del smv, r
        try:
            shm.close()
        except BufferError:
            pass
