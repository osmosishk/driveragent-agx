"""RkCameraInfo receiver (schema v2, RK3588 -> AGX, port 5564; docs/RK_AGX_INTERFACE.md).

DA01 (rk-agxlink) is the ONLY source of the camera names and roles. It CONNECTS a ZMQ PUB to tcp://<agx>:5564 and
sends one frame per second: 32-byte dabus envelope (src_board 2 = RK, type_id 5564, flag time_uncertain, schema
hash of RkCameraInfo 0x743cffad) + one unpacked single-segment Cap'n Proto RkCameraInfo.

This module BINDS a SUB (subscribe all) on tcp://<bind>:5564 (config/infer.yaml ports.rkinfo, bind.rkinfo).
- Peer filter: a ZAP IP allowlist (own small ZAP handler thread, NULL mechanism, zap_domain set) with the board
  addresses of data/paired_boards.json (the same list as the FrameLink receivers). set_allowed() changes the list at
  run time (no restart): the ZAP handler reads the current set for each new connection, and a message from a
  connected peer whose address left the list is refused ("peer_not_allowed"; the "Peer-Address" property of the
  frame). An empty list accepts any address, as the FrameLink receivers do. The receiver has ITS OWN zmq.Context:
  the ZAP handler of a context sees every socket of that context, and the node's other sockets (results, status,
  internal, admin) must not be filtered by this list.
- Source of the info: the peer address of each accepted message (stats "peers": {address: last wall time}) and the
  addresses that ZAP refused ("zap_refused").
- Envelope check (common/envelope.py: magic, version, length, CRC-32C), then src_board RK, type_id 5564, schema hash
  of RkCameraInfo (0x743cffad as DA01 sends it, or the calculated schema v3 value 0x506a649c; the struct is the
  same, see infer/publish/schema.py RKINFO_V2_HASH); then the capnp decode. A refused message is counted by reason
  and dropped.
- Keeps the newest info per camId with the receive time. fresh = received in the last FRESH_S (3 s).
- One daemon thread (poll 200 ms). It never touches frames or results: the status thread only reads a copy.

apply_names(): the camera name / role rule of the status (owner Section 4.7):
  fresh RK info for the camera: name = RK name, role = RK role when roleConfirmed and not empty else "",
                                roleConfirmed, infoSource "rk"
  no fresh RK info:             role = the config role (config/sources.yaml role_rk in rk mode), name = "",
                                roleConfirmed false, infoSource "config"
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter

import zmq

from common import envelope as env
from infer.publish import schema as sch
from infer.publish.internal import RateLimitedLog

log = logging.getLogger("infer.rkinfo")

FRESH_S = 3.0
ZAP_DOMAIN = b"agx-rkinfo"
MAX_MSG_BYTES = 65536          # an RkCameraInfo is a few hundred bytes; a larger inbound message closes that peer
ZAP_ENDPOINT = "inproc://zeromq.zap.01"
PEERS_MAX = 64                 # peer addresses kept in the stats
REJECT_WHY = {"short message": "envelope_short", "bad magic/version": "envelope_magic",
              "length mismatch": "envelope_length", "crc mismatch": "envelope_crc"}


def check_message(raw: bytes, rk_type, schema_hash, type_id: int = sch.TYPE_RKINFO) -> tuple[dict | None, str]:
    """(info dict, "") or (None, reject reason). schema_hash: one hash or a set of the accepted hashes.
    info = {"hostname", "t_ns", "schema_version", "cameras": {camId: {cam, section, name, port, role, role_confirmed,
    sent}}} (plain Python values, copied out of the buffer)."""
    try:
        m = env.unpack(raw)
    except ValueError as e:
        return None, REJECT_WHY.get(str(e), "envelope")
    if m["src_board"] != env.SRC_RK:
        return None, "src_board"
    if m["type_id"] != type_id:
        return None, "type_id"
    if m["schema_hash"] not in (schema_hash if isinstance(schema_hash, (set, frozenset, tuple)) else (schema_hash,)):
        return None, "schema_hash"
    try:
        with rk_type.from_bytes(m["payload"]) as r:
            cams = {}
            for c in r.cameras:
                cid = int(c.camId)
                cams[cid] = {"cam": cid, "section": str(c.section), "name": str(c.name), "port": str(c.port),
                             "role": str(c.role), "role_confirmed": bool(c.roleConfirmed), "sent": bool(c.sent)}
            info = {"hostname": str(r.hostname), "t_ns": int(r.tNs), "schema_version": int(r.schemaVersion),
                    "cameras": cams}
    except Exception as e:  # noqa: BLE001  (capnp.KjException, UnicodeDecodeError, ...)
        return None, "decode:" + type(e).__name__
    return info, ""


def _note(d: dict, key: str, value) -> None:
    """d[key] = value, at most PEERS_MAX keys (the oldest value leaves)."""
    if key not in d and len(d) >= PEERS_MAX:
        d.pop(min(d, key=d.get), None)
    d[key] = value


class _ZapHandler:
    """ZAP handler (RFC 27) for the receiver's own context: 200 when the set is empty or the peer address is in it,
    else 400. allowed_fn() gives the CURRENT set (a frozenset; read for each new connection)."""

    def __init__(self, ctx: zmq.Context, allowed_fn, on_result):
        self._allowed_fn = allowed_fn
        self._on_result = on_result
        self._sock = ctx.socket(zmq.REP)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.bind(ZAP_ENDPOINT)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="rkinfo-zap", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        sock = self._sock
        try:
            while not self._stop.is_set():
                try:
                    if not sock.poll(200):
                        continue
                    req = sock.recv_multipart()
                except zmq.ZMQError:
                    if self._stop.is_set():
                        break
                    self._stop.wait(0.2)
                    continue
                version, rid = (req + [b"", b""])[:2]
                addr = req[3].decode("utf-8", "replace") if len(req) > 3 else ""
                allowed = self._allowed_fn()
                ok = version == b"1.0" and (not allowed or addr in allowed)
                try:
                    sock.send_multipart([b"1.0", rid, b"200" if ok else b"400",
                                         b"OK" if ok else b"address not paired", b"", b""])
                except zmq.ZMQError:
                    pass
                try:
                    self._on_result(addr, ok)
                except Exception:  # noqa: BLE001 - counters only
                    pass
        finally:
            sock.close(0)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)


class RkInfoReceiver:
    def __init__(self, host: str = "0.0.0.0", port: int = sch.TYPE_RKINFO, allowed=(), proto_path: str | None = None,
                 fresh_s: float = FRESH_S, extra_allowed=()):
        """allowed: the paired board addresses (IPv4 strings; data/paired_boards.json); extra_allowed: more addresses
        that are always allowed while the list is not empty (tests: 127.0.0.1). Binds at once (a bind error
        raises: the caller runs without the receiver)."""
        self.schema = sch.load(proto_path)
        self.rk_type = self.schema.mod.RkCameraInfo
        self.hash = self.schema.hash["RkCameraInfo"]
        self.hashes = frozenset((self.hash, sch.RKINFO_V2_HASH))   # the struct is the same in v2 and v3
        self.fresh_s = float(fresh_s)
        self._extra = tuple(str(a) for a in extra_allowed)
        self.allowed: tuple[str, ...] = ()
        self._allowed_set: frozenset = frozenset()
        self._set_allowed(allowed)
        self.allowed_updates = 0
        self._ctx = zmq.Context()
        self._auth = None
        self._lock = threading.Lock()
        self.peers: dict[str, float] = {}          # peer address -> wall time of the last accepted message
        self.zap_refused: dict[str, float] = {}    # address -> wall time of the last connection that ZAP refused
        self.zap_counts: Counter = Counter()
        self._cams: dict[int, dict] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rlog = RateLimitedLog(log)
        self.received = 0
        self.rejects: Counter = Counter()
        self.last_rx_t: float | None = None     # wall clock of the last accepted message
        self.hostname = ""
        try:
            # always a ZAP handler: the list can change from empty to not empty at run time
            self._auth = _ZapHandler(self._ctx, lambda: self._allowed_set, self._on_zap)
            self._sock = self._ctx.socket(zmq.SUB)
            self._sock.setsockopt(zmq.LINGER, 0)
            self._sock.setsockopt(zmq.RCVHWM, 16)
            self._sock.setsockopt(zmq.MAXMSGSIZE, MAX_MSG_BYTES)
            self._sock.setsockopt(zmq.ZAP_DOMAIN, ZAP_DOMAIN)   # NULL mechanism: ZAP runs only with a domain
            self._sock.setsockopt(zmq.SUBSCRIBE, b"")
            self.endpoint = f"tcp://{host}:{int(port)}"
            self._sock.bind(self.endpoint)
            self.endpoint = self._sock.getsockopt(zmq.LAST_ENDPOINT).decode()   # port 0 (tests) -> the real port
        except Exception:
            self._close()
            raise
        if self.allowed:
            log.info("RkCameraInfo SUB bound %s (schema hash 0x%08x), peers allowed: %s", self.endpoint, self.hash,
                     ", ".join(self.allowed))
        else:
            # INFO: the paired boards reader writes the one WARNING for "no paired board"
            log.info("RkCameraInfo SUB bound %s: no paired board address: peers from ANY address are accepted",
                     self.endpoint)

    def _set_allowed(self, addrs) -> tuple[str, ...]:
        addrs = tuple(dict.fromkeys(str(a) for a in (addrs or ())))
        full = tuple(dict.fromkeys(addrs + self._extra)) if addrs else ()
        self.allowed = full
        self._allowed_set = frozenset(full)     # one reference swap: the ZAP thread reads it without a lock
        return full

    def set_allowed(self, addrs) -> bool:
        """New peer allowlist at run time (empty = any address). New connections: the ZAP handler. Connected peers:
        their messages are refused when their address is not in the new list. Returns True when it changed."""
        old = self.allowed
        new = self._set_allowed(addrs)
        if new == old:
            return False
        self.allowed_updates += 1
        if new == ("0.0.0.0",):     # infer.ingest.ingest.REFUSE_ALL: matches no peer
            log.info("RkCameraInfo peers: ALL refused (paired boards problem)")
        elif new:
            log.info("RkCameraInfo peers allowed: %s", ", ".join(new))
        else:
            log.info("RkCameraInfo peers: no paired board address: peers from ANY address are accepted")
        return True

    def _on_zap(self, addr: str, ok: bool) -> None:
        with self._lock:
            self.zap_counts["allowed" if ok else "refused"] += 1
            if not ok:
                _note(self.zap_refused, addr, time.time())
        if not ok:
            self._rlog.warning("zap:" + addr, "RkCameraInfo peer %s refused (not a paired board address)", addr)

    @property
    def port(self) -> int:
        return int(self.endpoint.rsplit(":", 1)[1])

    # ---- receive ---------------------------------------------------------------------------------
    def handle(self, raw: bytes, now_mono: float | None = None, peer: str | None = None) -> str:
        """Check and keep one message. peer: the TCP peer address (None = not known). Returns "" (accepted) or the
        reject reason."""
        allowed = self._allowed_set
        if peer and allowed and peer not in allowed:
            why = "peer_not_allowed"         # connected before its address left the list
            self.rejects[why] += 1
            self._rlog.warning("reject:" + why, "RkCameraInfo from %s refused: not a paired board address", peer)
            return why
        info, why = check_message(raw, self.rk_type, self.hashes)
        if info is None:
            self.rejects[why] += 1
            self._rlog.warning("reject:" + why, "RkCameraInfo refused: %s", why)
            return why
        t = time.monotonic() if now_mono is None else now_mono
        wall = time.time()
        with self._lock:
            for cid, c in info["cameras"].items():
                self._cams[cid] = dict(c, t_rx_mono=t, t_rx=wall, hostname=info["hostname"])
            self.received += 1
            self.last_rx_t = wall
            self.hostname = info["hostname"]
            if peer:
                _note(self.peers, peer, wall)
        return ""

    def _run(self) -> None:
        poller = zmq.Poller()
        poller.register(self._sock, zmq.POLLIN)
        while not self._stop.is_set():
            try:
                if not poller.poll(200):
                    continue
                for _ in range(64):
                    try:
                        frame = self._sock.recv(zmq.NOBLOCK, copy=False)
                    except zmq.Again:
                        break
                    try:
                        peer = frame.get("Peer-Address")
                    except (zmq.ZMQError, AttributeError, TypeError):
                        peer = None
                    self.handle(frame.bytes, peer=peer if isinstance(peer, str) else None)
            except zmq.ZMQError as e:
                if self._stop.is_set():
                    break
                self._rlog.warning("zmq", "RkCameraInfo receive error: %s", e)
                self._stop.wait(0.5)
            except Exception:  # noqa: BLE001
                log.exception("RkCameraInfo receive failed")
                self._stop.wait(0.5)

    # ---- read ------------------------------------------------------------------------------------
    def fresh(self, now_mono: float | None = None) -> dict[int, dict]:
        """{camId: info} of the cameras with RK info received in the last fresh_s."""
        t = time.monotonic() if now_mono is None else now_mono
        with self._lock:
            return {cid: dict(c) for cid, c in self._cams.items() if t - c["t_rx_mono"] <= self.fresh_s}

    def stats(self, now_mono: float | None = None) -> dict:
        t = time.monotonic() if now_mono is None else now_mono
        fr = self.fresh(t)
        with self._lock:
            return {"endpoint": self.endpoint, "allowed": list(self.allowed), "received": self.received,
                    "rejects": dict(self.rejects), "last_rx_t": self.last_rx_t, "hostname": self.hostname,
                    "fresh_s": self.fresh_s, "fresh_cams": sorted(fr), "peers": dict(self.peers),
                    "zap_refused": dict(self.zap_refused), "zap": dict(self.zap_counts),
                    "allowed_updates": self.allowed_updates}

    # ---- life ------------------------------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="rkinfo-sub", daemon=True)
        self._thread.start()

    def _close(self) -> None:
        s = getattr(self, "_sock", None)
        if s is not None:
            s.close(0)
            self._sock = None
        if self._auth is not None:
            try:
                self._auth.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._ctx.destroy(linger=0)
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._close()


def apply_names(cams: list[dict], info: dict[int, dict] | None) -> list[dict]:
    """Set name / role / role_confirmed / info_source of each status camera dict (in place; also returned).
    info: RkInfoReceiver.fresh() (None or {} = no fresh RK info). Without fresh info the role stays the config role
    that the ingest metrics give (config/sources.yaml role_rk in rk mode)."""
    info = info or {}
    for c in cams:
        i = info.get(int(c.get("cam", -1)))
        if i is not None:
            role = str(i.get("role") or "")
            confirmed = bool(i.get("role_confirmed")) and bool(role)
            c["name"] = str(i.get("name") or "")
            c["role"] = role if confirmed else ""
            c["role_confirmed"] = confirmed
            c["info_source"] = "rk"
        else:
            c["role"] = str(c.get("role") or "")
            c["name"] = ""
            c["role_confirmed"] = False
            c["info_source"] = "config"
    return cams
