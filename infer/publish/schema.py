"""Cap'n Proto schema of the node (proto/agx_infer.capnp) and the runtime schema hashes.

The schema hash is calculated at runtime from the .capnp file text with the RK reference rule
(common.dabus_envelope.schema_hash). Expected values for schema version 1 are below; a different
value is logged as an error (the RK side then rejects the messages as a schema mismatch).
"""
from __future__ import annotations

import logging
import os
import struct
import threading

import capnp

from common import envelope as env

log = logging.getLogger("infer.schema")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_PROTO = os.path.join(ROOT, "proto", "agx_infer.capnp")
TYPE_RESULT = 5560
TYPE_STATUS = 5561
EXPECTED_HASH = {"AgxPerceptionResult": 0xAFCAFF02, "AgxInferStatus": 0x9086FA18}

_lock = threading.Lock()
_cache: dict[str, "Schema"] = {}


class Schema:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        with open(self.path, encoding="utf-8") as f:
            self.text = f.read()
        self.mod = capnp.load(self.path)
        self.hash = {name: env.schema_hash(self.text, name) for name in EXPECTED_HASH}
        self.version = int(getattr(self.mod, "schemaVersion", 1))
        for name, h in self.hash.items():
            want = EXPECTED_HASH[name]
            if h == want:
                log.info("schema hash %s = 0x%08x (OK, %s)", name, h, self.path)
            else:
                log.error("schema hash %s = 0x%08x, expected 0x%08x: tell the RK side", name, h, want)


def load(path: str | None = None) -> Schema:
    p = os.path.abspath(path or DEFAULT_PROTO)
    with _lock:
        s = _cache.get(p)
        if s is None:
            s = _cache[p] = Schema(p)
        return s


def new_builder(struct_type, size_bytes: int):
    """Root builder with one first segment big enough for size_bytes, so that to_bytes() gives a
    single-segment message (RK rule: unpacked, single segment)."""
    words = max(1024, int(size_bytes) // 8 + 1024)
    mb = capnp._MallocMessageBuilder(words)
    return mb, mb.init_root(struct_type)


def segment_count(buf: bytes) -> int:
    return struct.unpack_from("<I", buf, 0)[0] + 1
