"""dabus envelope (32 bytes) for the AGX side, fast path.

Same byte layout as the RK reference `common/dabus_envelope.py` (copied unchanged from
driveragent-proto). This module only replaces the pure-Python CRC-32C with the hardware
CRC-32C of the `crc32c` package when it is installed. tests/test_envelope.py checks that both
give the golden vectors of the RK repository.
"""
from __future__ import annotations

import struct
import time

from common import dabus_envelope as ref

try:  # ARMv8 CRC32 instructions: ~0.1 ms for a 1.4 MB frame
    import crc32c as _crc32c_mod

    def crc32c(data, crc: int = 0) -> int:
        return _crc32c_mod.crc32c(data, crc) if crc else _crc32c_mod.crc32c(data)

    CRC_IMPL = "crc32c-package"
except ImportError:  # pragma: no cover - slow fallback, correct but ~1000x slower
    crc32c = ref.crc32c
    CRC_IMPL = "pure-python"

MAGIC = ref.MAGIC
VERSION = ref.VERSION
SRC_AGX = ref.SRC_AGX
SRC_RK = ref.SRC_RK
FLAG_SOURCE_IS_REPLAY = ref.FLAG_SOURCE_IS_REPLAY
FLAG_TIME_UNCERTAIN = ref.FLAG_TIME_UNCERTAIN
FLAG_DEGRADED = ref.FLAG_DEGRADED
HEADER = ref.HEADER
HEADER_LEN = ref.HEADER_LEN
_CRC = struct.Struct("<I")

schema_hash = ref.schema_hash
canonical_struct_text = ref.canonical_struct_text


def pack(type_id: int, flags: int, schema: int, seq: int, t_ptp_ns: int, payload: bytes,
         src_board: int = SRC_AGX) -> bytes:
    head = HEADER.pack(MAGIC, VERSION, src_board, type_id, flags, schema, seq & 0xFFFFFFFF,
                       t_ptp_ns, len(payload))
    crc = crc32c(payload, crc32c(head)) if payload else crc32c(head)
    return head + _CRC.pack(crc) + payload


def unpack(buf: bytes) -> dict:
    if len(buf) < HEADER_LEN:
        raise ValueError("short message")
    magic, ver, src, type_id, flags, schema, seq, t_ns, length = HEADER.unpack_from(buf)
    (crc,) = _CRC.unpack_from(buf, 28)
    payload = memoryview(buf)[HEADER_LEN:]
    if magic != MAGIC or ver != VERSION:
        raise ValueError("bad magic/version")
    if length != len(payload):
        raise ValueError("length mismatch")
    want = crc32c(payload, crc32c(buf[:28])) if length else crc32c(buf[:28])
    if crc != want:
        raise ValueError("crc mismatch")
    return {"src_board": src, "type_id": type_id, "flags": flags, "schema_hash": schema,
            "seq": seq, "t_ptp_ns": t_ns, "payload": bytes(payload)}


class Sequencer:
    """Per (src_board, type_id) counter that wraps at 2^32."""

    def __init__(self) -> None:
        self._seq: dict[int, int] = {}

    def next(self, type_id: int) -> int:
        s = self._seq.get(type_id, 0)
        self._seq[type_id] = (s + 1) & 0xFFFFFFFF
        return s


def now_ns() -> int:
    """CLOCK_REALTIME in ns. The AGX has no PTP tonight: senders set FLAG_TIME_UNCERTAIN."""
    return time.time_ns()
