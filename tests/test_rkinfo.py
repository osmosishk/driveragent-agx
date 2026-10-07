"""Schema v2 tests: RkCameraInfo receiver (infer/rkinfo.py), camera names in the status, model control data in the
status (catalog, active set, control mode, last good set, change in progress).

No GPU, no TensorRT. Every socket binds port 0 on 127.0.0.1 (never the live ports 5560-5564 / 8700). Run:
  PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_rkinfo.py
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import pytest
import zmq

from common import dabus_envelope as ref
from infer import rkinfo as rki
from infer.ingest.frame_store import FrameStore
from infer.ingest.metrics import CameraMetrics
from infer.publish import schema as sch

# Golden vector made on DA01 (2026-10-07) with the REAL DA01 functions rk/agxlink/agxlink_core.py rkcam_fields() +
# rkcam_message() (pack_envelope with the native CRC-32C), DA01 schema copy rk/agxlink/schema/agx_infer.capnp (byte-
# identical to proto/agx_infer.capnp), pycapnp 2.2.4. Cameras: cam0 front/front CONFIRMED (CAM1, sent), cam1
# fisheye-190 no role (CAM2, sent), cam2 name "" -> label video11 (CAM3, not sent); hostname rk3588-da01,
# tNs 1791300000123456789, seq 7.
DA01_GOLDEN = bytes.fromhex(
    "5eda0102bc150200adff3c7407000000150d8401dcf9db1858010000a13fefc1000000002a00000000000000020002000200000000000000"
    "150d8401dcf9db180500000062000000090000007f000000726b333538382d6461303100000000000c000000010004000003000000000000"
    "350000008a0000003d000000320000003d0000002a0000003d000000320000000102000000000000390000008a0000004100000062000000"
    "450000002a000000450000000a0000000200000000000000410000008a0000004900000042000000490000002a000000490000000a000000"
    "676d736c5f64657332395f6c696e6b41000000000000000066726f6e7400000043414d310000000066726f6e74000000676d736c5f646573"
    "32395f6c696e6b420000000000000000666973686579652d313930000000000043414d32000000000000000000000000676d736c5f646573"
    "33305f6c696e6b410000000000000000766964656f31310043414d33000000000000000000000000")


# ---- the DA01 sender, copied from DA01 rk/agxlink/agxlink_core.py (rkcam_fields, rkcam_message, pack_envelope) -----
@dataclass
class CamInfo:            # the fields of DA01 agxlink_core.CamInfo that rkcam_fields() uses
    cam: int
    section: str
    label: str
    port: str = ""
    name: str = ""
    role: str = ""


def rkcam_fields(cams, sent, hostname: str, t_ns: int) -> dict:
    return {"schemaVersion": 2, "hostname": hostname, "tNs": int(t_ns),
            "cameras": [{"camId": c.cam, "section": c.section, "name": c.name or c.label, "port": c.port,
                         "role": c.role, "roleConfirmed": bool(c.role), "sent": c.cam in sent}
                        for c in sorted(cams, key=lambda c: c.cam)]}


def rkcam_message(rk_type, fields: dict, schema_hash: int, type_id: int, seq: int, src_board: int = ref.SRC_RK) -> bytes:
    payload = rk_type.new_message(**fields).to_bytes()
    # DA01 pack_envelope() = env.pack() (the native CRC gives the same bytes)
    return ref.pack(type_id, ref.FLAG_TIME_UNCERTAIN, schema_hash, seq, fields["tNs"], payload, src_board)


DA01_CAMS = [CamInfo(0, "gmsl_des29_linkA", "front", port="CAM1", name="front", role="front"),
             CamInfo(1, "gmsl_des29_linkB", "fisheye-190", port="CAM2", name="fisheye-190", role=""),
             CamInfo(2, "gmsl_des30_linkA", "video11", port="CAM3", name="", role="")]
T_NS = 1791300000123456789


@pytest.fixture()
def ctx():
    c = zmq.Context()
    yield c
    c.destroy(linger=0)


def _rk_type():
    return sch.load().mod.RkCameraInfo


def _msg(**kw) -> bytes:
    f = rkcam_fields(DA01_CAMS, {0, 1}, "rk3588-da01", T_NS)
    return rkcam_message(_rk_type(), f, kw.pop("schema_hash", 0x743CFFAD), kw.pop("type_id", 5564), kw.pop("seq", 7),
                         **kw)


# ---- message check ---------------------------------------------------------------------------------------------
def test_da01_golden_bytes_decode():
    # schema v3: the calculated RkCameraInfo hash changed (hash rule note in proto/), the struct did not: DA01 keeps
    # 0x743cffad on the wire and the receiver accepts both values
    both = frozenset((sch.load().hash["RkCameraInfo"], sch.RKINFO_V2_HASH))
    assert both == {0x506A649C, 0x743CFFAD}
    info, why = rki.check_message(DA01_GOLDEN, _rk_type(), both)
    assert why == "" and info is not None
    assert rki.check_message(_msg(schema_hash=0x506A649C), _rk_type(), both)[1] == ""
    assert info["hostname"] == "rk3588-da01" and info["t_ns"] == T_NS and info["schema_version"] == 2
    c = info["cameras"]
    assert sorted(c) == [0, 1, 2]
    assert c[0] == {"cam": 0, "section": "gmsl_des29_linkA", "name": "front", "port": "CAM1", "role": "front",
                    "role_confirmed": True, "sent": True}
    assert (c[1]["name"], c[1]["role"], c[1]["role_confirmed"], c[1]["sent"]) == ("fisheye-190", "", False, True)
    assert (c[2]["name"], c[2]["port"], c[2]["sent"]) == ("video11", "CAM3", False)
    e = ref.unpack(DA01_GOLDEN)
    assert (e["src_board"], e["type_id"], e["flags"], e["schema_hash"], e["seq"]) == (2, 5564, 2, 0x743CFFAD, 7)
    assert sch.segment_count(e["payload"]) == 1
    # the copied DA01 functions give a message that decodes the same
    info2, why2 = rki.check_message(_msg(), _rk_type(), 0x743CFFAD)
    assert why2 == "" and info2 == info


def test_refused_messages():
    t, h = _rk_type(), 0x743CFFAD
    assert rki.check_message(_msg(schema_hash=0x9086FA18), t, h) == (None, "schema_hash")
    assert rki.check_message(_msg(src_board=ref.SRC_AGX), t, h) == (None, "src_board")
    assert rki.check_message(_msg(type_id=5561), t, h) == (None, "type_id")
    bad = bytearray(DA01_GOLDEN)
    bad[-1] ^= 0xFF
    assert rki.check_message(bytes(bad), t, h) == (None, "envelope_crc")
    assert rki.check_message(b"\x00" * 10, t, h) == (None, "envelope_short")
    junk = ref.pack(5564, 2, h, 1, 1, b"\x07" * 24, ref.SRC_RK)   # right envelope, payload is not capnp
    info, why = rki.check_message(junk, t, h)
    assert info is None and why.startswith("decode:")


# ---- receiver over ZMQ -----------------------------------------------------------------------------------------
def _pub(ctx, endpoint):
    p = ctx.socket(zmq.PUB)
    p.setsockopt(zmq.LINGER, 0)
    p.connect(endpoint)
    return p


def _send_until(pub, raw, cond, timeout=5.0):
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        pub.send(raw, zmq.NOBLOCK)
        time.sleep(0.05)
        if cond():
            return True
    return False


def test_receiver_round_trip_and_refused(ctx):
    rx = rki.RkInfoReceiver("127.0.0.1", 0, allowed=["10.0.0.208", "10.0.0.209"], extra_allowed=["127.0.0.1"])
    try:
        assert rx.port not in range(5560, 5565) and rx.allowed == ("10.0.0.208", "10.0.0.209", "127.0.0.1")
        rx.start()
        pub = _pub(ctx, f"tcp://127.0.0.1:{rx.port}")
        # refused first: wrong hash (an AgxInferStatus v1 hash) and wrong src_board (AGX)
        assert _send_until(pub, _msg(schema_hash=0x9086FA18), lambda: rx.rejects.get("schema_hash", 0) > 0)
        assert _send_until(pub, _msg(src_board=ref.SRC_AGX), lambda: rx.rejects.get("src_board", 0) > 0)
        assert rx.received == 0 and rx.fresh() == {}
        # accepted: the DA01 golden frame
        assert _send_until(pub, DA01_GOLDEN, lambda: rx.received > 0)
        fr = rx.fresh()
        assert sorted(fr) == [0, 1, 2] and fr[0]["name"] == "front" and fr[0]["hostname"] == "rk3588-da01"
        st = rx.stats()
        assert st["hostname"] == "rk3588-da01" and st["fresh_cams"] == [0, 1, 2] and st["last_rx_t"] is not None
        assert set(st["rejects"]) == {"schema_hash", "src_board"}
        pub.close(0)
    finally:
        rx.stop()


def test_receiver_zap_refuses_other_address(ctx):
    """The allowlist has only DA01 addresses: a PUB from 127.0.0.1 is refused by ZAP (no message reaches us)."""
    rx = rki.RkInfoReceiver("127.0.0.1", 0, allowed=["10.0.0.208"])
    try:
        rx.start()
        pub = _pub(ctx, f"tcp://127.0.0.1:{rx.port}")
        assert not _send_until(pub, DA01_GOLDEN, lambda: rx.received > 0, timeout=1.5)
        assert rx.received == 0 and rx.rejects == {}
        pub.close(0)
    finally:
        rx.stop()


def test_receiver_own_context_does_not_filter_other_sockets(ctx):
    """The ZAP handler is per context: the receiver has its own, so a socket of another context (the node's
    status / admin sockets) still accepts 127.0.0.1 while the receiver runs with a DA01-only allowlist."""
    rx = rki.RkInfoReceiver("127.0.0.1", 0, allowed=["10.0.0.208"])
    try:
        rep = ctx.socket(zmq.PULL)
        rep.setsockopt(zmq.LINGER, 0)
        port = rep.bind_to_random_port("tcp://127.0.0.1", min_port=20000, max_port=30000)
        push = ctx.socket(zmq.PUSH)
        push.setsockopt(zmq.LINGER, 0)
        push.connect(f"tcp://127.0.0.1:{port}")
        push.send(b"x")
        assert rep.poll(2000) and rep.recv() == b"x"
        push.close(0)
        rep.close(0)
    finally:
        rx.stop()


def test_receiver_empty_allowlist_accepts_any(ctx, caplog):
    with caplog.at_level("INFO", logger="infer.rkinfo"):
        rx = rki.RkInfoReceiver("127.0.0.1", 0, allowed=[])
    try:
        assert any("no paired board address" in r.getMessage() for r in caplog.records)
        rx.start()
        pub = _pub(ctx, f"tcp://127.0.0.1:{rx.port}")
        assert _send_until(pub, DA01_GOLDEN, lambda: rx.received > 0)
        pub.close(0)
    finally:
        rx.stop()


# ---- names: rule + 3 s fallback --------------------------------------------------------------------------------
def _cfg_cams():
    return [{"cam": 0, "role": "front"}, {"cam": 1, "role": "fisheye-190 CAM2 (role unconfirmed)"},
            {"cam": 2, "role": "CAM3 (role unconfirmed)"}, {"cam": 3, "role": "CAM4 (role unconfirmed)"}]


def test_fresh_and_apply_names_fallback():
    rx = rki.RkInfoReceiver("127.0.0.1", 0, allowed=["10.0.0.208"])
    try:
        t0 = 1000.0
        assert rx.handle(DA01_GOLDEN, now_mono=t0) == ""
        assert sorted(rx.fresh(t0 + 2.9)) == [0, 1, 2]
        cams = rki.apply_names(_cfg_cams(), rx.fresh(t0 + 2.9))
        assert [(c["name"], c["role"], c["role_confirmed"], c["info_source"]) for c in cams] == [
            ("front", "front", True, "rk"),
            ("fisheye-190", "", False, "rk"),                 # DA01 has no role: no role
            ("video11", "", False, "rk"),
            ("", "CAM4 (role unconfirmed)", False, "config")]  # not in the DA01 message: config
        assert rx.fresh(t0 + 3.1) == {}                           # older than 3 s: not fresh
        cams = rki.apply_names(_cfg_cams(), rx.fresh(t0 + 3.1))
        assert [(c["name"], c["role"], c["role_confirmed"], c["info_source"]) for c in cams] == [
            ("", "front", False, "config"), ("", "fisheye-190 CAM2 (role unconfirmed)", False, "config"),
            ("", "CAM3 (role unconfirmed)", False, "config"), ("", "CAM4 (role unconfirmed)", False, "config")]
        # a confirmed flag with an empty role is no role
        rx.handle(rkcam_message(_rk_type(), {"schemaVersion": 2, "hostname": "h", "tNs": 1, "cameras": [
            {"camId": 3, "name": "x", "role": "", "roleConfirmed": True}]}, 0x743CFFAD, 5564, 1), now_mono=t0)
        c3 = rki.apply_names([{"cam": 3, "role": "cfg"}], rx.fresh(t0))[0]
        assert (c3["name"], c3["role"], c3["role_confirmed"]) == ("x", "", False)
    finally:
        rx.stop()


# ---- status v2 -------------------------------------------------------------------------------------------------
class FakeIngest:
    def __init__(self, mode="rk"):
        self.mode = mode
        self.cams = list(range(6))
        self.store = FrameStore(self.cams)
        roles = {0: "front", 1: "fisheye-190 CAM2 (role unconfirmed)"}
        self.metrics = {c: CameraMetrics(c, roles.get(c, f"CAM{c + 1} (role unconfirmed)"), 6000 + c, mode,
                                         self.store, expect_simulated=False) for c in self.cams}

    def metrics_snapshot(self):
        return [self.metrics[c].snapshot() for c in self.cams]


class FakeManager:
    def status(self):
        lat = {"total": {"p50": 20, "p95": 30, "p99": 40}}
        return [
            {"name": "yolopx", "version": "2.1", "instance": "yolopx@2.1", "state": "RUNNING", "enabled": True,
             "cameras": [0, 2], "fps": 10.0, "lat_ms": lat},
            {"name": "laneseg", "version": "1.0", "instance": "laneseg@1.0", "state": "LOADING", "enabled": True,
             "cameras": [1], "lat_ms": lat},
            {"name": "bad", "version": "0.1", "instance": "bad@0.1", "state": "FAILED", "enabled": True,
             "error": "no engine", "cameras": [3]},
            {"name": "legacy", "state": "LOADED", "enabled": True, "cameras": [5]},
        ]


class StubRk:
    def __init__(self, info):
        self.info = info

    def fresh(self):
        return self.info

    def stats(self):
        return {"endpoint": "tcp://127.0.0.1:0", "received": 1}


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, path)


def _bump_mtime(path):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def _publisher(ctx, tmp_path, rk=None, mode="rk"):
    from infer.publish.status import StatusPublisher
    from infer.status import NodeState
    node = NodeState(version="test")
    node.started = True
    ctl = tmp_path / "control.yaml"
    ctl.write_text("control_mode: vehicle\n")
    return StatusPublisher(node, FakeIngest(mode), FakeManager(), None, None, "127.0.0.1", 0, ctx=ctx,
                           model_store=str(tmp_path / "store"), control_file=str(ctl), rkinfo=rk)


CATALOG = {"t": 1.0, "control_mode": "bench", "change_in_progress": "activate yolopx@2.1",
           "entries": [{"name": "yolopx", "version": "2.1", "type": "yolopx", "state": "ACTIVE", "reason": None},
                       {"name": "bad", "version": "0.1", "type": "yolo", "state": "FAILED", "reason": "no engine"}]}
LAST_GOOD = {"t": 1.0, "set": [{"name": "yolopx", "version": "2.0", "cameras": [0]}], "source": "test",
             "user": "u", "reason": "r"}


def test_status_v2_capnp_and_json(ctx, tmp_path):
    state = tmp_path / "store" / "_state"
    _write(state / "catalog.json", dict(CATALOG, t=time.time()))       # fresh snapshot
    _write(state / "last_good.json", LAST_GOOD)
    info = {0: {"name": "front", "role": "front", "role_confirmed": True},
            1: {"name": "fisheye-190", "role": "", "role_confirmed": False}}
    sp = _publisher(ctx, tmp_path, rk=StubRk(info))
    try:
        models, cams = sp._models(), sp._cameras()
        buf = sp.build_capnp(models, cams, time.time_ns())
        assert sch.segment_count(buf) == 1
        with sch.load().mod.AgxInferStatus.from_bytes(buf) as m:
            assert m.schemaVersion == 2
            assert [(e.name, e.version, e.type, e.state, e.reason) for e in m.catalog] == [
                ("yolopx", "2.1", "yolopx", "ACTIVE", ""), ("bad", "0.1", "yolo", "FAILED", "no engine")]
            assert [(a.name, a.version, list(a.cameras)) for a in m.activeSet] == [
                ("yolopx", "2.1", [0, 2]), ("laneseg", "1.0", [1]), ("legacy", "", [5])]
            assert [(a.name, a.version, list(a.cameras)) for a in m.lastGoodSet] == [("yolopx", "2.0", [0])]
            assert m.controlMode == "vehicle"               # from config/control.yaml (the file the controller obeys)
            assert m.changeInProgress == "activate yolopx@2.1"
            assert [x.version for x in m.models] == ["2.1", "1.0", "0.1", ""]
            c = {x.camId: (x.name, x.role, x.roleConfirmed, x.infoSource) for x in m.cameras}
            assert c[0] == ("front", "front", True, "rk")
            assert c[1] == ("fisheye-190", "", False, "rk")
            assert c[2] == ("", "CAM3 (role unconfirmed)", False, "config")    # the fake ingest role (not sources.yaml)
        js = sp.build_json(models, cams)
        assert js["schema"] == "agx-infer-status/1"
        assert js["catalog"][1] == {"name": "bad", "version": "0.1", "type": "yolo", "state": "FAILED",
                                    "reason": "no engine"}
        assert js["active_set"][0] == {"name": "yolopx", "version": "2.1", "cameras": [0, 2]}
        assert js["last_good_set"] == [{"name": "yolopx", "version": "2.0", "cameras": [0]}]
        assert (js["control_mode"], js["change_in_progress"]) == ("vehicle", "activate yolopx@2.1")
        assert 0 <= js["catalog_age_s"] < 5
        assert js["rk_info"] == {"endpoint": "tcp://127.0.0.1:0", "received": 1}
        jc = {x["cam"]: x for x in js["cameras"]}
        assert (jc[1]["name"], jc[1]["role"], jc[1]["role_confirmed"], jc[1]["info_source"]) == \
            ("fisheye-190", "", False, "rk")
        assert jc[4]["info_source"] == "config" and jc[4]["role"] == "CAM5 (role unconfirmed)"
        json.dumps(js, allow_nan=False, default=str)

        # catalog.json changes (new mtime): read again; the change has ended
        _write(state / "catalog.json", dict(CATALOG, t=time.time(), change_in_progress="", control_mode="bench"))
        _bump_mtime(state / "catalog.json")
        assert sp.control(models)["change_in_progress"] == ""
        # a bad catalog.json: empty catalog, control mode from the control file (vehicle here)
        (state / "catalog.json").write_text("{not json")
        _bump_mtime(state / "catalog.json")
        ctl = sp.control(models)
        assert (ctl["catalog"], ctl["control_mode"], ctl["change_in_progress"]) == ([], "vehicle", "")
        # no catalog.json and no last_good.json
        os.unlink(state / "catalog.json")
        os.unlink(state / "last_good.json")
        ctl = sp.control(models)
        assert (ctl["catalog"], ctl["control_mode"], ctl["last_good_set"]) == ([], "vehicle", [])
        buf = sp.build_capnp(models, cams, time.time_ns(), ctl)
        with sch.load().mod.AgxInferStatus.from_bytes(buf) as m:
            assert len(m.catalog) == 0 and m.controlMode == "vehicle" and len(m.lastGoodSet) == 0
    finally:
        sp.stop()


def test_status_names_only_in_rk_mode_and_fallback(ctx, tmp_path):
    info = {0: {"name": "front", "role": "front", "role_confirmed": True}}
    sp = _publisher(ctx, tmp_path, rk=StubRk(info), mode="sim")
    try:
        c0 = sp._cameras()[0]
        assert (c0["name"], c0["info_source"]) == ("", "config")        # sim frames are not DA01 cameras
    finally:
        sp.stop()
    stub = StubRk(info)
    sp = _publisher(ctx, tmp_path, rk=stub)
    try:
        assert sp._cameras()[0]["info_source"] == "rk"
        stub.info = {}                                                   # DA01 info older than 3 s
        c0 = sp._cameras()[0]
        assert (c0["name"], c0["role"], c0["role_confirmed"], c0["info_source"]) == ("", "front", False, "config")
    finally:
        sp.stop()


def test_status_tick_with_real_receiver(ctx, tmp_path):
    """End to end in one process: DA01 frame -> receiver -> tick() -> capnp status on the PUB."""
    rx = rki.RkInfoReceiver("127.0.0.1", 0, allowed=[], extra_allowed=["127.0.0.1"])
    sp = _publisher(ctx, tmp_path, rk=rx)
    sub = ctx.socket(zmq.SUB)
    try:
        rx.start()
        pub = _pub(ctx, f"tcp://127.0.0.1:{rx.port}")
        assert _send_until(pub, DA01_GOLDEN, lambda: rx.received > 0)
        sub.setsockopt(zmq.LINGER, 0)
        sub.setsockopt(zmq.SUBSCRIBE, b"")
        sub.connect(sp._sock.getsockopt(zmq.LAST_ENDPOINT).decode())
        got = None
        t_end = time.monotonic() + 5
        while got is None and time.monotonic() < t_end:
            js = sp.tick()
            if sub.poll(100):
                got = sub.recv()
        assert got is not None
        e = ref.unpack(got)
        assert e["schema_hash"] == 0xEF12FE49 and e["type_id"] == 5561
        with sch.load().mod.AgxInferStatus.from_bytes(e["payload"]) as m:
            c = {x.camId: (x.name, x.role, x.roleConfirmed, x.infoSource) for x in m.cameras}
        assert c[0] == ("front", "front", True, "rk") and c[1] == ("fisheye-190", "", False, "rk")
        assert c[2] == ("video11", "", False, "rk") and c[3][3] == "config"
        assert js["rk_info"]["hostname"] == "rk3588-da01" and js["rk_info"]["fresh_cams"] == [0, 1, 2]
        pub.close(0)
    finally:
        sub.close(0)
        sp.stop()
        rx.stop()


def test_config_ports():
    import yaml
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, "config", "infer.yaml")) as f:
        cfg = yaml.safe_load(f)
    assert cfg["ports"]["rkinfo"] == 5564 and cfg["bind"]["rkinfo"] == "0.0.0.0"
    assert cfg["control_config"] == "config/control.yaml"
    assert sch.TYPE_RKINFO == 5564


def test_status_v2_review_fixes(ctx, tmp_path):
    """Review N4: (1) a file name with a surrogate escape (non-UTF-8 folder) must not stop the status; (2) an old
    controller snapshot (agx-dashboard does not run) gives no change in progress; (3) the control mode always comes
    from config/control.yaml; (4) the catalog in one status is limited."""
    from infer.publish import status as stmod
    state = tmp_path / "store" / "_state"
    bad = {"name": "mod\udce8le", "version": "1.0.0", "type": "", "state": "FAILED",
           "reason": "manifest error: no manifest.yaml in /x/mod\udce8le/1.0.0"}
    _write(state / "catalog.json", dict(CATALOG, t=time.time(), entries=CATALOG["entries"] + [bad]))
    sp = _publisher(ctx, tmp_path)
    try:
        models, cams = sp._models(), sp._cameras()
        buf = sp.build_capnp(models, cams, time.time_ns())
        with sch.load().mod.AgxInferStatus.from_bytes(buf) as m:
            assert [e.name for e in m.catalog] == ["yolopx", "bad", "mod?le"] and m.catalog[2].state == "FAILED"
        json.dumps(sp.build_json(models, cams), allow_nan=False, default=str)
        # (2) an old snapshot: the entries stay (last known), no change in progress
        _write(state / "catalog.json", dict(CATALOG, t=time.time() - 120))
        _bump_mtime(state / "catalog.json")
        ctl = sp.control(models)
        assert ctl["change_in_progress"] == "" and len(ctl["catalog"]) == 2 and ctl["catalog_age_s"] >= 119
        # (3) the control mode follows config/control.yaml when it changes, not the snapshot
        assert ctl["control_mode"] == "vehicle"
        (tmp_path / "control.yaml").write_text("control_mode: bench\n")
        _bump_mtime(tmp_path / "control.yaml")
        assert sp.control(models)["control_mode"] == "bench"
        # (4) at most CATALOG_MAX entries, reasons limited
        many = [{"name": f"m{i}", "version": "1", "type": "yolopx", "state": "NO ADAPTER", "reason": "x" * 2000}
                for i in range(stmod.CATALOG_MAX + 50)]
        _write(state / "catalog.json", dict(CATALOG, t=time.time(), entries=many))
        _bump_mtime(state / "catalog.json")
        ctl = sp.control(models)
        assert len(ctl["catalog"]) == stmod.CATALOG_MAX and len(ctl["catalog"][0]["reason"]) == stmod.REASON_MAX
        buf = sp.build_capnp(models, cams, time.time_ns(), ctl)
        assert sch.segment_count(buf) >= 1
    finally:
        sp.stop()


def test_text_is_valid_utf8():
    from infer.publish.status import _text
    assert _text(None) == "" and _text("a\udce8b") == "a?b" and len(_text("y" * 5000)) == 1000
    assert _text("front", 3) == "fro"
