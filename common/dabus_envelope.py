#!/usr/bin/env python3
"""DriverAgent bus envelope (kick-off section 4), reference implementation with golden vectors.

32-byte little-endian header on every ZMQ message, both directions:

    off size field
      0   2  magic        0xDA5E
      2   1  ver          1
      3   1  src_board    1 = AGX, 2 = RK
      4   2  type_id      message type (bus registry; provisional: the ZMQ port number)
      6   2  flags        bit0 source_is_replay, bit1 time_uncertain, bit2 degraded
      8   4  schema_hash  FNV-1a 32 of the canonical capnp struct text (see canonical_struct_text)
     12   4  seq          per (src_board, type_id) counter, wraps at 2^32
     16   8  t_ptp_ns     PTP time of the payload's event (RK: CLOCK_REALTIME + time_uncertain until M3)
     24   4  len          payload length in bytes
     28   4  crc32c       CRC-32C (Castagnoli) over bytes [0..27] followed by the payload
     32      payload      capnp message (unpacked, single segment flat array)

Run as a script: `dabus_envelope.py --write golden_vectors.txt` regenerates the vectors,
`dabus_envelope.py --check golden_vectors.txt` verifies them. The C++ implementation
(envelope.h, test_envelope.cpp) is tested against the same file; the AGX side tests its own against it too.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys

MAGIC = 0xDA5E
VERSION = 1
SRC_AGX = 1
SRC_RK = 2
FLAG_SOURCE_IS_REPLAY = 1 << 0
FLAG_TIME_UNCERTAIN = 1 << 1
FLAG_DEGRADED = 1 << 2
HEADER = struct.Struct("<HBBHHIIQI")  # everything before the CRC: 28 bytes
HEADER_LEN = 32
assert HEADER.size == 28


def _crc32c_table() -> list[int]:
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
        table.append(c)
    return table


_TABLE = _crc32c_table()


def crc32c(data: bytes, crc: int = 0) -> int:
    crc ^= 0xFFFFFFFF
    for b in data:
        crc = _TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def fnv1a32(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def canonical_struct_text(capnp_text: str, name: str) -> str:
    """The struct's text from 'struct <name>' to its matching '}' (nested enums/structs included),
    with '#' comments removed, each line stripped, empty lines dropped, joined by '\\n'."""
    m = re.search(r"\bstruct\s+" + re.escape(name) + r"\b[^{]*\{", capnp_text)
    if not m:
        raise KeyError(f"struct {name} not found")
    depth, i = 0, m.start()
    body_start = m.start()
    while i < len(capnp_text):
        ch = capnp_text[i]
        if ch == "#":
            i = capnp_text.find("\n", i)
            if i < 0:
                break
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    raw = capnp_text[body_start:i + 1]
    lines = [re.sub(r"#.*", "", ln).strip() for ln in raw.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def schema_hash(capnp_text: str, name: str) -> int:
    return fnv1a32(canonical_struct_text(capnp_text, name).encode("utf-8"))


def pack(type_id: int, flags: int, schema: int, seq: int, t_ptp_ns: int, payload: bytes,
         src_board: int = SRC_RK) -> bytes:
    head = HEADER.pack(MAGIC, VERSION, src_board, type_id, flags, schema, seq & 0xFFFFFFFF, t_ptp_ns,
                       len(payload))
    return head + struct.pack("<I", crc32c(head + payload)) + payload


def unpack(buf: bytes) -> dict:
    if len(buf) < HEADER_LEN:
        raise ValueError("short message")
    magic, ver, src, type_id, flags, schema, seq, t_ns, length = HEADER.unpack_from(buf)
    (crc,) = struct.unpack_from("<I", buf, 28)
    payload = buf[HEADER_LEN:]
    if magic != MAGIC or ver != VERSION:
        raise ValueError("bad magic/version")
    if length != len(payload):
        raise ValueError("length mismatch")
    if crc != crc32c(buf[:28] + payload):
        raise ValueError("crc mismatch")
    return {"src_board": src, "type_id": type_id, "flags": flags, "schema_hash": schema, "seq": seq,
            "t_ptp_ns": t_ns, "payload": payload}


# (name, type_id, flags, schema_hash, seq, t_ptp_ns, payload)
_CASES = [
    ("empty", 5572, 0, 0x00000000, 0, 0, b""),
    ("crc_check_string", 5572, FLAG_TIME_UNCERTAIN, 0x12345678, 1, 1790610000123456789, b"123456789"),
    ("all_flags_wrap_seq", 5611, 0x7, 0xDEADBEEF, 0xFFFFFFFF, 2**63 - 1, bytes(range(256)) * 2),
    ("agx_source", 5607, FLAG_DEGRADED, 0x0BADF00D, 42, 5, b"\x00\x01\x02\x03", SRC_AGX),
]


def golden_lines() -> list[str]:
    out = [
        "# dabus golden vectors: name src type flags schema seq t_ptp_ns payload_hex envelope_hex",
        f"# crc32c('123456789') = {crc32c(b'123456789'):08x}; fnv1a32('') = {fnv1a32(b''):08x}; "
        f"fnv1a32('a') = {fnv1a32(b'a'):08x}",
    ]
    for case in _CASES:
        name, type_id, flags, schema, seq, t_ns, payload = case[:7]
        src = case[7] if len(case) > 7 else SRC_RK
        env = pack(type_id, flags, schema, seq, t_ns, payload, src)
        out.append(f"{name} {src} {type_id} {flags} {schema:08x} {seq} {t_ns} {payload.hex() or '-'} {env.hex()}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", metavar="FILE")
    g.add_argument("--check", metavar="FILE")
    g.add_argument("--schema-hash", nargs=2, metavar=("CAPNP_FILE", "STRUCT"))
    a = ap.parse_args()
    if a.schema_hash:
        with open(a.schema_hash[0], encoding="utf-8") as f:
            print(f"{schema_hash(f.read(), a.schema_hash[1]):08x}")
        return 0
    # Known-answer checks of the primitives (RFC 3720 CRC32C check value; FNV-1a test vectors).
    assert crc32c(b"123456789") == 0xE3069283
    assert fnv1a32(b"") == 0x811C9DC5 and fnv1a32(b"a") == 0xE40C292C
    lines = golden_lines()
    if a.write:
        with open(a.write, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"wrote {len(lines) - 2} vectors to {a.write}")
        return 0
    with open(a.check, encoding="utf-8") as f:
        have = [ln.rstrip("\n") for ln in f]
    for ln in have:
        if ln.startswith("#") or not ln:
            continue
        env = bytes.fromhex(ln.split()[-1])
        d = unpack(env)  # raises on any mismatch
        assert d["payload"].hex() == (ln.split()[7] if ln.split()[7] != "-" else "")
    if have != lines:
        print("golden vectors differ from this implementation", file=sys.stderr)
        return 1
    print(f"ok: {len(lines) - 2} vectors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
