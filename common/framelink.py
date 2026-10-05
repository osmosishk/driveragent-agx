"""FrameLink: RK3588 -> AGX camera frames over UDP.

Source of the format: RK repository tag rk-v0.4.0, RK3588_AGENT_KICKOFF.md section M1 + section 4:
  "Per-frame FrameLink header (40 B, little-endian): magic u32, ver u8, cam u8, fmt u8, health u8,
   seq u32, t_capture_ptp_ns u64, w u16, h u16, stride u16, exposure_us u16, source u8 (1=LIVE),
   reserved[3], payload_crc32c u32, header_crc32c u32, then payload. UDP to the AGX: cam0 -> port 6000,
   cam1-5 -> 6001-6005; fragment at 8,896 B payload (MTU 9000) with a 16 B fragment header,
   fallback 1,472 B at MTU 1500."

The RK repository does NOT define (FrameLink TX is not implemented at rk-v0.4.0). The values below are
AGX PROPOSALS, marked "PROPOSAL" and listed in docs/RK_AGX_INTERFACE.md for the RK agent to confirm:
  - the magic value, the fmt codes, the source codes other than 1=LIVE,
  - the CRC coverage (header_crc32c over bytes 0..35, payload_crc32c over the payload),
  - the 16-byte fragment header layout.
The health byte uses rk-camd LinkState (rk/camd/src/protocol.h): 0 NotStarted, 1 Starting, 2 Live,
3 Stalled, 4 NoSignal.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass

from common.envelope import crc32c

# ---- frame header (40 B) -------------------------------------------------------------------------
MAGIC = 0x4B4E4C46          # PROPOSAL: b"FLNK" read as little-endian u32
VERSION = 1
HEADER = struct.Struct("<IBBBBIQHHHHB3sII")
HEADER_LEN = 40
assert HEADER.size == HEADER_LEN

FMT_NV12 = 1                # RK design: RGA NV12 at model size (cam0 1280x720, cam1-5 704x396)
FMT_H265 = 2                # PROPOSAL: one H.265 access unit (Annex-B), for the night-task Section 6 codec
FMT_NAMES = {FMT_NV12: "nv12", FMT_H265: "h265"}

SOURCE_LIVE = 1             # RK defined
SOURCE_REPLAY = 2           # PROPOSAL: replay of a recording (simulator)
SOURCE_TEST_PATTERN = 3     # PROPOSAL: synthetic test pattern (simulator)
SOURCE_NAMES = {SOURCE_LIVE: "live", SOURCE_REPLAY: "replay", SOURCE_TEST_PATTERN: "test-pattern"}

HEALTH_NOT_STARTED, HEALTH_STARTING, HEALTH_LIVE, HEALTH_STALLED, HEALTH_NO_SIGNAL = range(5)

BASE_PORT = 6000            # RK defined: camN -> 6000 + N

# ---- fragment header (16 B), PROPOSAL ------------------------------------------------------------
FRAG_MAGIC = 0x4C46         # b"FL" little-endian
FRAG_VERSION = 1
FRAG = struct.Struct("<HBBIHHI")   # magic, ver, cam, seq, idx, count, offset
FRAG_LEN = 16
assert FRAG.size == FRAG_LEN
FRAG_PAYLOAD_JUMBO = 8896   # RK defined (MTU 9000)
FRAG_PAYLOAD_1500 = 1472 - FRAG_LEN   # 1472 B = largest UDP payload at MTU 1500


@dataclass
class FrameHeader:
    cam: int
    fmt: int
    seq: int
    t_capture_ns: int
    width: int
    height: int
    stride: int = 0
    health: int = HEALTH_LIVE
    exposure_us: int = 0
    source: int = SOURCE_LIVE
    payload_crc32c: int = 0
    header_crc32c: int = 0
    version: int = VERSION

    @property
    def simulated(self) -> bool:
        return self.source != SOURCE_LIVE


def pack_frame(h: FrameHeader, payload) -> bytes:
    """Return header (40 B) + payload, with both CRCs filled in."""
    pcrc = crc32c(payload)
    head36 = HEADER.pack(MAGIC, h.version, h.cam, h.fmt, h.health, h.seq & 0xFFFFFFFF,
                         h.t_capture_ns, h.width, h.height, h.stride, h.exposure_us, h.source,
                         b"\0\0\0", pcrc, 0)[:36]
    return head36 + struct.pack("<I", crc32c(head36)) + bytes(payload)


class FrameError(ValueError):
    pass


def unpack_frame(buf, check_payload_crc: bool = True) -> tuple[FrameHeader, memoryview]:
    if len(buf) < HEADER_LEN:
        raise FrameError("short frame")
    (magic, ver, cam, fmt, health, seq, t_ns, w, h, stride, exp_us, source, _res, pcrc,
     hcrc) = HEADER.unpack_from(buf)
    if magic != MAGIC:
        raise FrameError(f"bad magic 0x{magic:08x}")
    if ver != VERSION:
        raise FrameError(f"bad version {ver}")
    if crc32c(bytes(buf[:36])) != hcrc:
        raise FrameError("header crc mismatch")
    payload = memoryview(buf)[HEADER_LEN:]
    if check_payload_crc and crc32c(payload) != pcrc:
        raise FrameError("payload crc mismatch")
    return FrameHeader(cam, fmt, seq, t_ns, w, h, stride, health, exp_us, source, pcrc, hcrc,
                       ver), payload


def fragments(frame: bytes, cam: int, seq: int, max_payload: int = FRAG_PAYLOAD_JUMBO):
    """Split header+payload into UDP datagrams (16 B fragment header + data)."""
    n = (len(frame) + max_payload - 1) // max_payload
    if n > 0xFFFF:
        raise FrameError("too many fragments")
    mv = memoryview(frame)
    for i in range(n):
        off = i * max_payload
        yield FRAG.pack(FRAG_MAGIC, FRAG_VERSION, cam, seq & 0xFFFFFFFF, i, n, off) + \
            bytes(mv[off:off + max_payload])


class _Slot:
    __slots__ = ("seq", "count", "got", "seen", "size", "buf", "t_first", "t_last")

    def __init__(self, cap: int):
        self.buf = bytearray(cap)
        self.seq = -1
        self.count = 0
        self.got = 0
        self.seen: set[int] = set()
        self.size = 0
        self.t_first = 0.0
        self.t_last = 0.0

    def reset(self, seq: int, count: int, now: float):
        self.seq, self.count, self.got, self.size = seq, count, 0, 0
        self.seen = set()
        self.t_first = self.t_last = now


class Reassembler:
    """Reassembles fragments of ONE camera port. Keeps at most `slots` frames in flight.

    complete frames are returned by push(); counters describe loss:
      lost_fragments  - fragments that never arrived in abandoned frames
      abandoned       - frames started but not completed (dropped by a newer frame or timeout)
      bad             - datagrams or frames that failed a check (magic, crc, size)
      late            - fragments of the newest complete frame or of a frame at most LATE_WINDOW
                        frames older (duplicates and late arrivals): dropped, NOT a loss
    A seq that is more than LATE_WINDOW frames older than the newest complete frame starts a new
    stream (for example a sender restart): it is accepted.
    """

    LATE_WINDOW = 8

    def __init__(self, cam: int, max_frame: int = 4 * 1024 * 1024, slots: int = 4,
                 timeout_s: float = 0.2):
        self.cam = cam
        self.slots = [_Slot(max_frame) for _ in range(slots)]
        self.max_frame = max_frame
        self.timeout_s = timeout_s
        self.lost_fragments = 0
        self.abandoned = 0
        self.bad = 0
        self.late = 0
        self._last_done: int | None = None
        self.datagrams = 0
        self.bytes = 0
        self.last_error = ""

    def _abandon(self, s: _Slot):
        if s.seq >= 0:
            self.abandoned += 1
            self.lost_fragments += s.count - s.got
        s.seq = -1

    def push(self, dgram, now: float | None = None):
        """Feed one datagram. Returns bytes of a complete frame (header+payload) or None."""
        now = time.monotonic() if now is None else now
        self.datagrams += 1
        self.bytes += len(dgram)
        if len(dgram) < FRAG_LEN:
            self.bad += 1
            self.last_error = "short datagram"
            return None
        magic, ver, cam, seq, idx, count, off = FRAG.unpack_from(dgram)
        n = len(dgram) - FRAG_LEN
        if magic != FRAG_MAGIC or ver != FRAG_VERSION or count == 0 or idx >= count or \
                off + n > self.max_frame:
            self.bad += 1
            self.last_error = "bad fragment header"
            return None
        if self._last_done is not None and \
                ((self._last_done - seq) & 0xFFFFFFFF) <= self.LATE_WINDOW:
            self.late += 1
            return None
        slot = None
        for s in self.slots:
            if s.seq == seq:
                slot = s
                break
        if slot is None:
            # take a free slot, else the oldest one (that frame is lost)
            free = [s for s in self.slots if s.seq < 0]
            if free:
                slot = free[0]
            else:
                slot = min(self.slots, key=lambda s: s.t_first)
                self._abandon(slot)
            slot.reset(seq, count, now)
        if idx in slot.seen:
            return None  # duplicate
        slot.seen.add(idx)
        slot.buf[off:off + n] = memoryview(dgram)[FRAG_LEN:]
        slot.got += 1
        slot.t_last = now
        if idx == count - 1:
            slot.size = off + n
        # expire stale partial frames
        for s in self.slots:
            if s is not slot and s.seq >= 0 and now - s.t_last > self.timeout_s:
                self._abandon(s)
        if slot.got == slot.count:
            out = bytes(slot.buf[:slot.size])
            slot.seq = -1
            self._last_done = seq
            # frames older than this one can never be useful any more (newest frame wins)
            for s in self.slots:
                if s.seq >= 0 and ((seq - s.seq) & 0xFFFFFFFF) < 0x80000000:
                    self._abandon(s)
            return out
        return None
