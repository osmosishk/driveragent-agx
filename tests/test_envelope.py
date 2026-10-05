"""The AGX envelope must reproduce the RK golden vectors (copied from driveragent-proto)."""
import os

from common import dabus_envelope as ref
from common import envelope as env

HERE = os.path.dirname(os.path.abspath(__file__))


def test_golden_vectors():
    n = 0
    for ln in open(os.path.join(HERE, "dabus_golden_vectors.txt")):
        if ln.startswith("#") or not ln.strip():
            continue
        name, src, type_id, flags, schema, seq, t_ns, payload_hex, env_hex = ln.split()
        payload = b"" if payload_hex == "-" else bytes.fromhex(payload_hex)
        got = env.pack(int(type_id), int(flags), int(schema, 16), int(seq), int(t_ns), payload, int(src))
        assert got.hex() == env_hex, name
        u = env.unpack(bytes.fromhex(env_hex))
        assert u["payload"] == payload and u["seq"] == int(seq)
        n += 1
    assert n == 4


def test_fast_crc_matches_reference():
    data = os.urandom(5000)
    assert env.crc32c(data) == ref.crc32c(data)
    assert env.CRC_IMPL == "crc32c-package"


def test_reject_corrupt():
    m = bytearray(env.pack(5560, 0, 0x1234, 7, 99, b"hello"))
    m[-1] ^= 1
    try:
        env.unpack(bytes(m))
    except ValueError as e:
        assert "crc" in str(e)
    else:
        raise AssertionError("corrupt frame accepted")
