"""Board addresses from data/paired_boards.json (link settings task, builder D; docs/PAIRING_API.md):

- PairedBoards: read, mtime reload, missing file / no board / bad file rules.
- FrameLink source filter changed at run time with real UDP (process and thread mode): no new receive process.
- Per-source FrameLink counters (frames, drops).
- RkCameraInfo ZAP allowlist changed at run time; peer address of each message.
- Results PUB peer addresses (socket monitor + getpeername).
- The internal 5562 JSON keys allowed_sources / result_subscribers / board_sources.
- Node.check_paired_boards (the reload path of agx-infer, no restart).
- dashboard link monitor: the ping target comes from the paired boards.

Free ports only (port 0 / a port the kernel gave); never 5560-5564, 6000-6005, 8700. Run:
  PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_paired_sources.py
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time

import numpy as np
import pytest
import zmq

from common import framelink as fl
from infer.ingest.frame_store import FrameStore
from infer.ingest.framelink_rx import FrameLinkReceiver
from infer.ingest.ingest import REFUSE_ALL, Ingest, PairedBoards, parse_paired_boards
from infer.ingest.metrics import CameraMetrics

LIVE_PORTS = set(range(5560, 5565)) | set(range(6000, 6006)) | {8700}


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    assert p not in LIVE_PORTS
    return p


def _boards_doc(boards, seq=1):
    return {"schema": "agx-paired-boards/1", "seq": seq, "boards": boards}


def _board(bid, addrs, last_seen_t=None, last_seen_addr=None, paired_t=1.0):
    return {"id": bid, "name": bid.upper(), "addresses": addrs, "token_sha256": "0" * 64, "paired_t": paired_t,
            "last_seen_t": last_seen_t, "last_seen_addr": last_seen_addr, "source": "pairing"}


def _write(path, doc, bump=True, mode=0o600):
    """Atomic write as the pairing code does (tmp mode 600 + replace); bump the mtime so a fast rewrite is seen."""
    tmp = str(path) + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(doc if isinstance(doc, str) else json.dumps(doc))
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    if bump:
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def _wait(pred, timeout=5.0):
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def _nv12_frame(cam, seq, w=64, h=32):
    img = np.full((h * 3 // 2, w), seq % 256, dtype=np.uint8)
    hd = fl.FrameHeader(cam=cam, fmt=fl.FMT_NV12, seq=seq, t_capture_ns=time.time_ns(), width=w,
                        height=h, stride=w, source=fl.SOURCE_TEST_PATTERN)
    return fl.pack_frame(hd, img.tobytes())


def _send_frames(src_ip, port, cam, seqs):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((src_ip, 0))
    try:
        for seq in seqs:
            for d in fl.fragments(_nv12_frame(cam, seq), cam, seq, fl.FRAG_PAYLOAD_1500):
                s.sendto(d, ("127.0.0.1", port))
            time.sleep(0.01)
    finally:
        s.close()


# ---- PairedBoards ----------------------------------------------------------------------------------------------
def test_parse_paired_boards():
    addrs, seq, notes = parse_paired_boards(json.dumps(_boards_doc(
        [_board("a", ["10.0.0.208", "10.0.0.209"]), _board("b", ["10.0.0.209", "10.42.0.2", "fe80::1"])], seq=7)))
    assert addrs == ("10.0.0.208", "10.0.0.209", "10.42.0.2") and seq == 7
    assert len(notes) == 1 and "'fe80::1' left out" in notes[0]
    assert parse_paired_boards(json.dumps(_boards_doc([])))[0] == ()
    # file-level problems: the file is not used
    for bad in ("{", "[]", json.dumps({"schema": "x", "boards": []}), json.dumps(_boards_doc("x"))):
        with pytest.raises(ValueError):
            parse_paired_boards(bad)
    # a bad address or a bad board: only that one is left out, with a note (the rules of common.pairing_store)
    addrs, _, notes = parse_paired_boards(json.dumps(_boards_doc(
        [_board("rk3588-da01", ["10.0.0.208", "10.0.0.300"]), "x", dict(_board("bad", ["10.0.0.7"]), token_sha256="z"),
         _board("b", {"x": 1}), _board("c", ["10.0.0.9"])])))
    assert addrs == ("10.0.0.208", "10.0.0.9")
    assert any("'10.0.0.300' left out" in n for n in notes) and any("#2" in n for n in notes) \
        and any("'bad'" in n for n in notes) and any("board 'b'" in n for n in notes)


def test_reader_same_set_as_the_dashboard_reader(tmp_path):
    """agx-infer and the Paired boards table (common.pairing_store) see the same addresses (review finding)."""
    from common.pairing_store import board_addresses
    p = tmp_path / "paired_boards.json"
    docs = [_boards_doc([_board("rk3588-da01", ["10.0.0.208", "10.0.0.300"])], seq=3),
            _boards_doc([_board("a", ["::ffff:10.0.0.5", "0.0.0.0", "224.0.0.1", "10.0.0.5"]), _board("b", [])]),
            _boards_doc([dict(_board("a", ["10.0.0.1"]), id="Bad Id"), _board("b", ["10.0.0.2"])])]
    for d in docs:
        _write(p, d)
        pb = PairedBoards(str(p))
        pb.poll()
        assert list(pb.addresses) == board_addresses(str(p))[0] and pb.addresses and pb.state == "ok"


def test_paired_boards_reload_rules(tmp_path, caplog):
    p = tmp_path / "paired_boards.json"
    pb = PairedBoards(str(p))
    # missing file: accept any, one WARNING (a second poll with no change logs nothing)
    with caplog.at_level(logging.WARNING, logger="infer.ingest"):
        assert pb.poll() is False                      # the first read is not a "change"
        assert pb.poll() is False
    assert pb.addresses == () and pb.state == "missing" and pb.error is None
    assert sum("does not exist" in r.getMessage() for r in caplog.records) == 1
    # a board is paired: the set changes
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208"])], seq=1))
    assert pb.poll() is True and pb.addresses == ("10.0.0.208",) and pb.seq == 1 and pb.state == "ok"
    assert pb.poll() is False                          # no change: one stat()
    # the same set again with a new seq (last_seen update): no change of the set
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208"], last_seen_t=5.0)], seq=2))
    assert pb.poll() is False and pb.seq == 2
    # a bad file: the last good set stays, the error is reported
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="infer.ingest"):
        _write(p, "{ not json")
        assert pb.poll() is False
    assert pb.addresses == ("10.0.0.208",) and pb.state == "error" and "JSONDecodeError" in pb.error
    assert any("last good set stays" in r.getMessage() for r in caplog.records)
    snap = pb.snapshot()
    assert snap["addresses"] == ["10.0.0.208"] and snap["from"] == "paired_boards.json" and snap["error"]
    # good again: error cleared
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208"]), _board("b2", ["10.0.0.50"])], seq=3))
    assert pb.poll() is True and pb.addresses == ("10.0.0.208", "10.0.0.50") and pb.error is None
    # every board removed: accept any + WARNING
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="infer.ingest"):
        _write(p, _boards_doc([], seq=4))
        assert pb.poll() is True
    assert pb.addresses == () and pb.state == "no board"
    assert any("no board address" in r.getMessage() for r in caplog.records)
    # file removed: accept any
    _write(p, _boards_doc([_board("x", ["10.0.0.9"])], seq=5))
    assert pb.poll() is True
    p.unlink()
    assert pb.poll() is True and pb.addresses == () and pb.state == "missing"
    assert pb.snapshot()["changes"] == 5


def test_paired_boards_bad_file_at_start(tmp_path):
    p = tmp_path / "paired_boards.json"
    _write(p, json.dumps({"schema": "agx-paired-boards/1", "boards": "x"}))
    pb = PairedBoards(str(p))
    pb.poll()
    # fail closed: no last good set -> refuse all (never "accept any")
    assert pb.addresses == () and pb.state == "error (refusing all)" and "schema" in pb.error
    assert pb.filter_addresses == (REFUSE_ALL,)
    snap = pb.snapshot()
    assert snap["when_empty"] == "none" and snap["refusing_all"] is True and snap["addresses"] == []
    # a good file later: the board set, no error
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208"])]))
    assert pb.poll() is True and pb.filter_addresses == ("10.0.0.208",) and pb.error is None
    assert pb.snapshot()["when_empty"] == "any" and pb.snapshot()["refusing_all"] is False


def test_paired_boards_review_case_at_start(tmp_path):
    """Review finding: a board with one bad address at start. Old: the whole file refused -> accept ANY source.
    Now: the good address is used, the bad one is in the error."""
    p = tmp_path / "paired_boards.json"
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208", "10.0.0.300"], last_seen_addr="10.0.0.208")], 3))
    pb = PairedBoards(str(p))
    pb.poll()
    assert pb.filter_addresses == ("10.0.0.208",) and pb.state == "ok" and pb.seq == 3
    assert "10.0.0.300" in pb.error and pb.snapshot()["error"] == pb.error


@pytest.mark.parametrize("case", ["no_address", "all_bad", "all_boards_bad", "mode_644", "not_json"])
def test_paired_boards_fail_closed_at_start(tmp_path, case):
    p = tmp_path / "paired_boards.json"
    if case == "no_address":
        _write(p, _boards_doc([_board("rk3588-da01", [])]))
    elif case == "all_bad":
        _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.300", "fe80::1"])]))
    elif case == "all_boards_bad":
        _write(p, _boards_doc([dict(_board("a", ["10.0.0.208"]), token_sha256="x")]))
    elif case == "mode_644":
        _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208"])]), mode=0o644)
    else:
        _write(p, "{ not json")
    pb = PairedBoards(str(p))
    pb.poll()
    assert pb.filter_addresses == (REFUSE_ALL,), (case, pb.state, pb.error)
    assert pb.state.endswith("(refusing all)") and pb.error and pb.snapshot()["when_empty"] == "none"


def test_paired_boards_bad_file_after_accept_any_refuses_all(tmp_path):
    """At run time: "accept any" (no file) -> a bad file: refuse all (not the last "any" set); a bad file after a
    good set: the last good set stays (contract D)."""
    p = tmp_path / "paired_boards.json"
    pb = PairedBoards(str(p))
    pb.poll()
    assert pb.filter_addresses == ()
    _write(p, "{ bad")
    assert pb.poll() is True and pb.filter_addresses == (REFUSE_ALL,) and pb.state == "error (refusing all)"
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208"])]))
    assert pb.poll() is True and pb.filter_addresses == ("10.0.0.208",)
    _write(p, "{ bad again")
    assert pb.poll() is False and pb.filter_addresses == ("10.0.0.208",) and pb.state == "error"
    # the board loses its last address: refuse all
    _write(p, _boards_doc([_board("rk3588-da01", [])], seq=2))
    assert pb.poll() is True and pb.filter_addresses == (REFUSE_ALL,) and pb.state == "no address (refusing all)"
    # every board removed (a good file): accept any (contract D)
    _write(p, _boards_doc([], seq=3))
    assert pb.poll() is True and pb.filter_addresses == () and pb.state == "no board"


# ---- FrameLink source filter at run time (real UDP) --------------------------------------------------------------
@pytest.mark.parametrize("use_process", [True, False], ids=["rx_process", "thread"])
def test_framelink_filter_reload(use_process):
    cam, port = 1, _free_udp_port()
    store = FrameStore(range(6))
    m = CameraMetrics(cam, "right", port, "rk", store, expect_simulated=False)
    rx = FrameLinkReceiver(cam, port, "127.0.0.1", store, m, expect_simulated=False, use_process=use_process,
                           ring_slots=4, max_frame=65536, allowed_sources=["127.0.0.2"])
    rx.start()
    try:
        pid0 = rx.rx_pid
        # 1. only 127.0.0.2: a sender on 127.0.0.1 is dropped (counted per source)
        _send_frames("127.0.0.1", port, cam, range(1, 6))
        assert _wait(lambda: m.c.get("foreign_source_drops", 0) >= 5)
        assert _wait(lambda: rx.source_stats().get("127.0.0.1", {}).get("dropped", 0) >= 5)
        assert store.newest(cam) is None
        # 2. the paired set changes to 127.0.0.1: accepted by the SAME receive process
        assert rx.set_allowed_sources(["127.0.0.1"]) is True
        assert rx.set_allowed_sources(["127.0.0.1"]) is False          # same set: nothing to do
        time.sleep(0.2)                                                # the process reads the pipe at a stats time
        t0 = time.monotonic()
        ok = False
        seq = 100
        while time.monotonic() - t0 < 5 and not ok:
            _send_frames("127.0.0.1", port, cam, [seq])
            ok = store.newest(cam) is not None and store.newest(cam).seq == seq
            seq += 1
        assert ok, "frames from 127.0.0.1 not accepted after the reload"
        st = rx.source_stats()
        assert st["127.0.0.1"]["frames_window"] >= 1 and st["127.0.0.1"]["last_t"] is not None
        assert rx.rx_pid == pid0 and rx.rx_restarts == 0                # no new process
        # 3. now 127.0.0.2 only again: 127.0.0.1 is dropped again
        drops0 = m.c.get("foreign_source_drops", 0)
        rx.set_allowed_sources(["127.0.0.2"])
        time.sleep(0.2)
        n0 = store.newest(cam).seq
        _send_frames("127.0.0.1", port, cam, range(500, 505))
        assert _wait(lambda: m.c.get("foreign_source_drops", 0) >= drops0 + 5)
        assert store.newest(cam).seq == n0
        # 4. empty set = accept any (fast path), the source is still counted (sampled)
        rx.set_allowed_sources([])
        time.sleep(0.2)
        _send_frames("127.0.0.3", port, cam, range(600, 606))
        assert _wait(lambda: store.newest(cam).seq == 605)
        assert _wait(lambda: rx.source_stats().get("127.0.0.3", {}).get("frames_window", 0) >= 1)
        # 5. refuse all (paired boards problem): every source is dropped
        drops0 = m.c.get("foreign_source_drops", 0)
        n0 = store.newest(cam).seq
        rx.set_allowed_sources([REFUSE_ALL])
        time.sleep(0.2)
        for src in ("127.0.0.1", "127.0.0.3"):
            _send_frames(src, port, cam, range(700, 703))
        assert _wait(lambda: m.c.get("foreign_source_drops", 0) >= drops0 + 6)
        assert store.newest(cam).seq == n0
        assert rx.rx_pid == pid0 and rx.rx_restarts == 0 and rx.allowed_updates == 4
        print(f"{'process' if use_process else 'thread'}: sources {rx.source_stats()}")
    finally:
        rx.stop()


def test_framelink_filter_restarted_process_gets_the_new_set():
    """A receive process that ends is started again with the CURRENT set (not the one of the first start)."""
    cam, port = 2, _free_udp_port()
    store = FrameStore(range(6))
    m = CameraMetrics(cam, "left", port, "rk", store, expect_simulated=False)
    rx = FrameLinkReceiver(cam, port, "127.0.0.1", store, m, expect_simulated=False, use_process=True,
                           ring_slots=4, max_frame=65536, allowed_sources=["127.0.0.2"])
    rx.start()
    try:
        rx.set_allowed_sources(["127.0.0.1"])
        rx._proc.kill()
        assert _wait(lambda: rx.rx_restarts == 1, timeout=8.0)
        _send_frames("127.0.0.1", port, cam, range(1, 4))
        assert _wait(lambda: store.newest(cam) is not None and store.newest(cam).seq == 3)
    finally:
        rx.stop()


def test_ingest_set_allowed_and_source_stats():
    ports = [_free_udp_port() for _ in range(2)]
    cfg = {"cameras": [{"cam": c, "port": ports[c] if c < 2 else 1, "enabled": c < 2} for c in range(6)],
           "rx_process": True, "decoder_prestart": False, "bind_host": {"rk": "127.0.0.1"}, "ring_slots": 4,
           "max_frame_bytes": 65536}
    ing = Ingest(cfg, mode="rk", allowed_sources=["127.0.0.9"])
    ing.start()
    try:
        assert ing.set_allowed_sources(["127.0.0.1"]) is True
        assert ing.set_allowed_sources(["127.0.0.1"]) is False
        time.sleep(0.2)
        for c in (0, 1):
            _send_frames("127.0.0.1", ports[c], c, range(1, 4))
        assert _wait(lambda: ing.source_stats().get("127.0.0.1", {}).get("frames_3s", 0) >= 6)
        st = ing.source_stats()["127.0.0.1"]
        assert st["last_t"] is not None and st["dropped"] == 0
        with pytest.raises(ValueError):
            ing.set_allowed_sources(["::1"])
    finally:
        ing.stop()


# ---- RkCameraInfo ZAP allowlist at run time -------------------------------------------------------------------
def _rk_golden():
    from tests.test_rkinfo import DA01_GOLDEN
    return DA01_GOLDEN


@pytest.fixture()
def ctx():
    c = zmq.Context()
    yield c
    c.destroy(linger=0)


def _pub(ctx, port):
    p = ctx.socket(zmq.PUB)
    p.setsockopt(zmq.LINGER, 0)
    p.connect(f"tcp://127.0.0.1:{port}")
    return p


def _send_until(pub, raw, cond, timeout=4.0):
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        pub.send(raw, zmq.NOBLOCK)
        time.sleep(0.05)
        if cond():
            return True
    return False


def test_rkinfo_zap_allowlist_reload(ctx):
    from infer import rkinfo as rki
    raw = _rk_golden()
    rx = rki.RkInfoReceiver("127.0.0.1", 0, allowed=["10.0.0.208"])
    try:
        assert rx.port not in LIVE_PORTS
        rx.start()
        # 1. not paired: ZAP refuses 127.0.0.1, the refused address is recorded
        p1 = _pub(ctx, rx.port)
        assert not _send_until(p1, raw, lambda: rx.received > 0, timeout=1.5)
        assert "127.0.0.1" in rx.stats()["zap_refused"] and rx.stats()["zap"].get("refused", 0) >= 1
        p1.close(0)
        # 2. the board address is now paired: a new connection is accepted, without a restart
        assert rx.set_allowed(["127.0.0.1"]) is True and rx.set_allowed(["127.0.0.1"]) is False
        p2 = _pub(ctx, rx.port)
        assert _send_until(p2, raw, lambda: rx.received > 0)
        st = rx.stats()
        assert st["allowed"] == ["127.0.0.1"] and "127.0.0.1" in st["peers"] and st["allowed_updates"] == 1
        # 3. the board is removed: the CONNECTED peer's messages are refused (peer_not_allowed)
        rx.set_allowed(["10.0.0.208"])
        n = rx.received
        assert _send_until(p2, raw, lambda: rx.rejects.get("peer_not_allowed", 0) > 0)
        assert rx.received == n
        # 4. no board: any address
        rx.set_allowed([])
        assert _send_until(p2, raw, lambda: rx.received > n)
        # 5. refuse all (paired boards problem): the connected peer and a new connection are refused
        rx.set_allowed([REFUSE_ALL])
        n, z = rx.received, rx.stats()["zap"].get("refused", 0)
        assert _send_until(p2, raw, lambda: rx.rejects.get("peer_not_allowed", 0) > 1)
        p3 = _pub(ctx, rx.port)
        assert not _send_until(p3, raw, lambda: rx.received > n, timeout=1.0)
        assert rx.stats()["zap"].get("refused", 0) > z and rx.received == n
        p2.close(0)
        p3.close(0)
    finally:
        rx.stop()


def test_rkinfo_handle_peer_rule():
    from infer import rkinfo as rki
    rx = rki.RkInfoReceiver("127.0.0.1", 0, allowed=["10.0.0.208"])
    try:
        raw = _rk_golden()
        assert rx.handle(raw, peer="10.0.0.209") == "peer_not_allowed"
        assert rx.handle(raw, peer="10.0.0.208") == "" and "10.0.0.208" in rx.stats()["peers"]
        assert rx.handle(raw) == ""          # peer not known (old pyzmq): the ZAP check at connect is the filter
    finally:
        rx.stop()


# ---- results PUB peers ------------------------------------------------------------------------------------------
def test_results_subscriber_addresses(ctx):
    from infer.publish.results import ResultPublisher
    pub = ResultPublisher("127.0.0.1", 0, ctx=ctx)
    try:
        port = int(pub._sock.getsockopt(zmq.LAST_ENDPOINT).decode().rsplit(":", 1)[1])
        assert port not in LIVE_PORTS
        subs = []
        for _ in range(2):
            s = ctx.socket(zmq.SUB)
            s.setsockopt(zmq.LINGER, 0)
            s.setsockopt(zmq.SUBSCRIBE, b"")
            s.connect(f"tcp://127.0.0.1:{port}")
            subs.append(s)
        assert _wait(lambda: pub.stats()["subscribers"] == 2)
        assert pub.stats()["subscriber_addresses"] == ["127.0.0.1", "127.0.0.1"]
        subs[0].close(0)
        assert _wait(lambda: pub.stats()["subscribers"] == 1)
        assert pub.stats()["subscriber_addresses"] == ["127.0.0.1"]
        subs[1].close(0)
        assert _wait(lambda: pub.stats()["subscriber_addresses"] == [])
    finally:
        pub.close()


def test_peer_address_bad_fd():
    from infer.publish.results import peer_address
    assert peer_address(-1) == "?" and peer_address(None) == "?"
    a, b = socket.socketpair(socket.AF_UNIX)
    try:
        assert peer_address(a.fileno()) in ("?", "")
    finally:
        a.close()
        b.close()


# ---- internal 5562 JSON keys ------------------------------------------------------------------------------------
class _Paired:
    def snapshot(self):
        return {"addresses": ["10.0.0.208"], "from": "paired_boards.json", "seq": 3, "loaded_t": 1.0, "error": None,
                "state": "ok", "changes": 0}


class _Results:
    def stats(self):
        return {"results_port": 5560, "results_rate_hz": 1.0, "subscribers": 3,
                "subscriber_addresses": ["10.0.0.208", "10.0.0.77", "?"], "results_total": 1, "last_result_t": None}


class _Rk:
    def __init__(self):
        now = time.time()
        self.st = {"peers": {"10.0.0.208": now - 0.5, "10.0.0.66": now - 120}, "zap_refused": {"10.0.0.99": now}}

    def fresh(self):
        return {}

    def stats(self):
        return dict(self.st)


def test_status_json_board_keys(tmp_path):
    from infer.publish.status import StatusPublisher, board_sources
    from infer.status import NodeState
    from tests.test_rkinfo import FakeIngest, FakeManager

    class Ing(FakeIngest):
        def source_stats(self):
            return {"10.0.0.208": {"frames_3s": 90, "last_t": 5.0, "dropped": 0, "dropped_last_t": None},
                    "10.0.0.50": {"frames_3s": 0, "last_t": None, "dropped": 12, "dropped_last_t": 6.0},
                    "other": {"frames_3s": 0, "last_t": None, "dropped": 3, "dropped_last_t": 6.0}}

    node = NodeState(version="test")
    node.started = True
    calls = []
    zc = zmq.Context()
    sp = StatusPublisher(node, Ing(), FakeManager(), _Results(), None, "127.0.0.1", 0, ctx=zc,
                         model_store=None, control_file=None, rkinfo=_Rk(), paired=_Paired(),
                         on_tick=lambda: calls.append(1))
    try:
        js = sp.tick()
        assert calls == [1]
        json.dumps(js)
        assert js["schema"] == "agx-infer-status/1"
        assert js["allowed_sources"]["addresses"] == ["10.0.0.208"] and js["allowed_sources"]["seq"] == 3
        assert js["result_subscribers"] == {"count": 3, "addresses": ["10.0.0.208", "10.0.0.77"]}
        bs = js["board_sources"]
        assert set(bs) == {"10.0.0.208", "10.0.0.50", "10.0.0.77", "10.0.0.99"}   # 10.0.0.66: older than 60 s
        e = bs["10.0.0.208"]
        assert (e["framelink_frames_3s"], e["framelink_last_t"], e["result_subscriber"], e["allowed"]) == \
            (90, 5.0, True, True) and e["rkinfo_last_t"] is not None
        assert bs["10.0.0.50"]["framelink_dropped"] == 12 and bs["10.0.0.50"]["allowed"] is False
        assert bs["10.0.0.77"]["result_subscriber"] is True and bs["10.0.0.77"]["framelink_frames_3s"] == 0
        assert bs["10.0.0.99"]["rkinfo_refused_last_t"] is not None
        for v in bs.values():
            assert {"framelink_frames_3s", "framelink_last_t", "rkinfo_last_t", "result_subscriber"} <= set(v)
        # a failing hook does not stop the status
        sp.on_tick = lambda: 1 / 0
        assert sp.tick()["schema"] == "agx-infer-status/1"
        # no paired object (old caller): keys present, allowed_sources None
        sp.paired = None
        js = sp.tick()
        assert js["allowed_sources"] is None and js["board_sources"]["10.0.0.50"]["allowed"] is True
    finally:
        sp.stop()
        zc.destroy(linger=0)
    assert board_sources(None, None, None) == {}
    # refuse all: no address is "allowed"
    bs = board_sources({"10.0.0.208": {"frames_3s": 0}}, None, ["10.0.0.77"], [], refuse_all=True)
    assert bs["10.0.0.208"]["allowed"] is False and bs["10.0.0.77"]["allowed"] is False


# ---- Node.check_paired_boards (the agx-infer reload path) -------------------------------------------------------
def test_node_check_paired_boards(tmp_path):
    from infer.main import Node
    from infer.status import NodeState

    class FakeIng:
        def __init__(self):
            self.calls = []

        def set_allowed_sources(self, a):
            self.calls.append(tuple(a))

    class FakeRk:
        def __init__(self):
            self.calls = []

        def set_allowed(self, a):
            self.calls.append(tuple(a))

    p = tmp_path / "paired_boards.json"
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208", "10.0.0.209"])]))
    n = object.__new__(Node)
    n.paired = PairedBoards(str(p))
    n.paired.poll()
    n.ingest, n.rkinfo, n.state = FakeIng(), FakeRk(), NodeState(version="t")
    assert n.check_paired_boards() is False and n.ingest.calls == []
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208"])], seq=2))
    assert n.check_paired_boards() is True
    assert n.ingest.calls == [("10.0.0.208",)] and n.rkinfo.calls == [("10.0.0.208",)]
    _write(p, "bad")
    assert n.check_paired_boards() is False and any("paired boards" in e for e in n.state.errors())
    assert n.paired.addresses == ("10.0.0.208",)
    # the board loses its last usable address: the receivers and ZAP get the refuse-all set (not "any")
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.300"])], seq=3))
    assert n.check_paired_boards() is True
    assert n.ingest.calls[-1] == (REFUSE_ALL,) and n.rkinfo.calls[-1] == (REFUSE_ALL,)
    assert any("10.0.0.300" in e for e in n.state.errors())


def test_node_reads_paired_file_path_from_config():
    import inspect

    from infer import main
    src = inspect.getsource(main.Node.__init__)
    assert "paired_boards_file" in src and "allowed_sources=self.paired.filter_addresses" in src
    assert "self.paired.filter_addresses" in inspect.getsource(main.Node._make_rkinfo)


# ---- dashboard link monitor -------------------------------------------------------------------------------------
def _link_cfg(path):
    from dashboard.config import load_config
    cfg = load_config(None)
    cfg["paired_boards_file"] = str(path)
    return cfg


def test_link_ping_targets():
    from dashboard.collectors.link import ping_targets
    t = ping_targets(_boards_doc([
        _board("old", ["10.0.0.5"], last_seen_t=10.0),
        _board("new", ["10.0.0.208", "10.0.0.209"], last_seen_t=20.0, last_seen_addr="10.0.0.209"),
        _board("noaddr", [], last_seen_t=30.0),
        _board("never", ["10.0.0.7"], last_seen_t=None, paired_t=15.0)]))
    assert [(x["board_id"], x["address"]) for x in t] == [("new", "10.0.0.209"), ("never", "10.0.0.7"),
                                                          ("old", "10.0.0.5")]


def test_link_monitor_target_from_paired_file(tmp_path, monkeypatch):
    from dashboard.collectors import link as lk
    p = tmp_path / "paired_boards.json"
    lm = lk.LinkMonitor(_link_cfg(p))
    # no file: no ping, a plain reason
    runs = []
    monkeypatch.setattr(lk.subprocess, "run", lambda *a, **k: runs.append(a) or (_ for _ in ()).throw(OSError()))
    s = lm.summary()
    assert s["rk_ip"] is None and s["ping_error"] == lk.NO_BOARD and s["board_id"] is None
    assert lm._ping_once() == (None, lk.NO_BOARD) and runs == []
    assert "no paired board" in lm._measure_clock()["clock_note"]
    # a board: ping its last_seen address
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208", "10.0.0.209"], last_seen_t=5.0,
                                  last_seen_addr="10.0.0.208")]))

    class R:
        returncode, stdout = 0, "64 bytes from 10.0.0.208: icmp_seq=1 ttl=64 time=0.42 ms"

    seen = []
    monkeypatch.setattr(lk.subprocess, "run", lambda args, **k: seen.append(args) or R())
    assert lm.refresh_target() is True and lm.refresh_target() is False
    assert lm._ping_once() == (0.42, None) and seen[-1][-1] == "10.0.0.208"
    with lm._lock:
        lm._pings.append((time.time(), 0.42))
    s = lm.summary()
    assert (s["rk_ip"], s["board_id"], s["board_name"]) == ("10.0.0.208", "rk3588-da01", "RK3588-DA01")
    assert s["loss_samples"] == 1 and s["boards"][0]["address"] == "10.0.0.208" and "paired_boards.json" in \
        s["target_from"]
    # a second board seen later: the target changes, the ping history of the old address is cleared
    _write(p, _boards_doc([_board("rk3588-da01", ["10.0.0.208"], last_seen_t=5.0),
                           _board("da02", ["10.0.0.150"], last_seen_t=9.0)], seq=2))
    assert lm.refresh_target() is True
    s = lm.summary()
    assert s["rk_ip"] == "10.0.0.150" and s["board_id"] == "da02" and s["loss_samples"] == 0
    # a bad file: the target stays, the error shows
    _write(p, "{bad")
    assert lm.refresh_target() is False and lm.summary()["rk_ip"] == "10.0.0.150"
    assert lm.summary()["paired_error"]
    # every board removed: no target
    _write(p, _boards_doc([], seq=3))
    assert lm.refresh_target() is True and lm.summary()["rk_ip"] is None


def test_rk_ip_and_rk_allowed_sources_removed_from_config():
    import yaml

    from dashboard.config import DEFAULTS
    root = os.path.join(os.path.dirname(__file__), "..")
    assert "rk_ip" not in DEFAULTS
    assert "rk_ip" not in (yaml.safe_load(open(os.path.join(root, "config", "templates", "dashboard.yaml"))) or {})
    src = os.path.join(root, "config", "templates", "sources.yaml")
    assert "rk_allowed_sources" not in (yaml.safe_load(open(src)) or {})
