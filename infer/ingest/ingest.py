"""AGX ingest: six camera sources -> one FrameStore + per-camera metrics.

mode sim  FrameLink UDP from tools.rk_sim on this AGX (bind 127.0.0.1). All frames are simulated.
mode rk   FrameLink UDP from the RK3588 (bind 0.0.0.0). Frames with source byte LIVE are "live".
mode file decode local recordings directly (no network). All frames are simulated ("file").

rk mode source filter: the union of the board addresses in data/paired_boards.json (the ONE source of
the board addresses on AGX02; written by the pairing code of agx-dashboard; PairedBoards below reads it).
Not empty = the receivers drop datagrams from other addresses (counter foreign_source_drops in the
camera metrics). Empty (no file, no board) = accept all, with a WARNING line. A problem never opens the
filter: a bad file at start, or boards with no usable address, give the set (REFUSE_ALL,) = refuse all
(PairedBoards below). Sim and file mode: no filter. The list changes at run time (set_allowed_sources), without a restart of agx-infer.
The old config key rk_allowed_sources (config/sources.yaml) is not used any more.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import sys
import time

import yaml

from common import framelink as fl
from infer.ingest.frame_store import FrameStore
from infer.ingest.metrics import CameraMetrics

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "config", "sources.yaml")
ROLES = {0: "front", 1: "right", 2: "left", 3: "right-back", 4: "left-back", 5: "back"}
MODES = ("sim", "rk", "file")

log = logging.getLogger("infer.ingest")


def parse_allowed_sources(value) -> tuple[str, ...]:
    """Source addresses -> tuple of IPv4 address strings. Raises ValueError for a bad entry
    (fail closed: a bad entry must not open the filter)."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    out = []
    for v in value:
        a = ipaddress.ip_address(str(v).strip())
        if a.version != 4:
            raise ValueError(f"source address {v!r} is not an IPv4 address (the sockets are IPv4)")
        out.append(str(a))
    return tuple(out)


PAIRED_SCHEMA = "agx-paired-boards/1"
DEFAULT_PAIRED_FILE = "data/paired_boards.json"
# Filter marker "refuse all": a set that holds only this address matches no source (a UDP datagram or a TCP peer
# never has the source address 0.0.0.0; the pairing code never stores it, common.pairing_store.ipv4).
REFUSE_ALL = "0.0.0.0"


def describe_filter(addrs) -> str:
    """Log text for a source filter set."""
    addrs = tuple(addrs or ())
    if not addrs:
        return "ANY source address (no paired board address)"
    if addrs == (REFUSE_ALL,):
        return "NO source address (refusing all: see the paired boards error)"
    return "only " + ", ".join(addrs)


def read_paired_boards(path) -> dict:
    """data/paired_boards.json -> {"missing", "problem", "addresses", "seq", "boards", "notes"}.
    The SAME rules as the dashboard (common.pairing_store.read_boards_file, builder C): so agx-infer and the
    Paired boards table see the same boards and addresses.
      problem: a file-level problem (not mode 600 / other owner, not JSON, wrong schema, boards not a list):
               no boards. The caller does not use the file.
      a bad board entry (id, token hash) or a bad address is left out (not the whole file); notes tells which.
    addresses: the union of the kept boards' IPv4 addresses (file order). Never raises."""
    from common import pairing_store as ps
    path = str(path)
    out = {"missing": False, "problem": None, "addresses": (), "seq": None, "boards": 0, "notes": []}
    if not os.path.exists(path):
        out["missing"] = True
        return out
    doc, problem = ps.read_boards_file(path)
    if problem:
        out["problem"] = problem
        return out
    out["seq"] = doc.get("seq")
    out["boards"] = len(doc["boards"])
    addrs: list[str] = []
    for b in doc["boards"]:
        for a in b["addresses"]:
            if a not in addrs:
                addrs.append(a)
    out["addresses"] = tuple(addrs)
    # notes: what the reader left out (a second, raw read; changes are rare)
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        raw_boards = raw.get("boards") if isinstance(raw, dict) else None
    except (OSError, ValueError):
        raw_boards = None          # replaced between the two reads: the next poll reads the new file
    if isinstance(raw_boards, list):
        kept = {b["id"]: b for b in doc["boards"]}
        notes = out["notes"]
        for i, rb in enumerate(raw_boards):
            bid = rb.get("id") if isinstance(rb, dict) else None
            cb = kept.get(bid) if isinstance(bid, str) else None
            if cb is None:
                notes.append(f"board #{i + 1} ({bid!r}) left out: not a valid board entry")
                continue
            ra = rb.get("addresses") or []
            ra = ra if isinstance(ra, list) else [ra]
            for v in ra:
                if not (isinstance(v, str) and ps.ipv4(v)):
                    notes.append(f"board {bid!r}: address {v!r} left out (not a usable IPv4 address)")
            valid = list(dict.fromkeys(x for x in (ps.ipv4(v) for v in ra if isinstance(v, str)) if x))
            if len(valid) > len(cb["addresses"]):
                notes.append(f"board {bid!r}: only the first {len(cb['addresses'])} addresses are used")
    return out


def parse_paired_boards(text: str) -> tuple[tuple[str, ...], int | None, list[str]]:
    """Paired boards JSON text -> (addresses, seq, notes) with the rules of read_paired_boards (tests, tools).
    Raises ValueError for a file-level problem."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "paired_boards.json")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        r = read_paired_boards(p)
    if r["problem"]:
        raise ValueError(r["problem"].replace(p, "paired_boards.json"))
    return r["addresses"], r["seq"], r["notes"]


class PairedBoards:
    """The board addresses from data/paired_boards.json, read again when the file changes (mtime_ns, size, inode).
    poll() costs one stat() when nothing changed. Rules (fail closed: a problem never opens the filter):
      no file, or a good file with no board: accept any source (filter ()), one WARNING per change to this state
      bad board entry / bad address: left out (the rest is used), the note is in `error`
      board(s) but no usable address, or entries left out and no address: REFUSE ALL (filter (REFUSE_ALL,))
      file-level problem (not JSON, schema, mode 600): keep the last good NOT EMPTY set; when there is none (start,
        or the last state was "accept any"): REFUSE ALL. `error` tells why.
    `addresses`: the board addresses in use (display). `filter_addresses`: the set for the FrameLink receivers and
    the RkCameraInfo ZAP allowlist (() = any, (REFUSE_ALL,) = none)."""

    def __init__(self, path: str):
        self.path = str(path)
        self.addresses: tuple[str, ...] = ()
        self.refuse_all = False
        self.seq: int | None = None
        self.loaded_t: float | None = None
        self.error: str | None = None
        # missing | no board | ok | error | error (refusing all) | no address (refusing all)
        self.state = "not read"
        self.notes: list[str] = []
        self.changes = 0                   # times the filter set changed after the first read
        self._key = None
        self._first = True

    @property
    def filter_addresses(self) -> tuple[str, ...]:
        if self.addresses:
            return self.addresses
        return (REFUSE_ALL,) if self.refuse_all else ()

    def poll(self) -> bool:
        """Read the file again when it changed. Returns True when the filter set changed (not on the first read)."""
        try:
            st = os.stat(self.path)
            key = (st.st_mtime_ns, st.st_size, st.st_ino)
        except FileNotFoundError:
            key = "missing"
        except OSError as e:
            key = f"stat: {e}"
        if key == self._key:
            return False
        self._key = key
        old = self.filter_addresses
        name = os.path.basename(self.path)
        if key == "missing":
            r = {"missing": True}
        elif isinstance(key, str):
            r = {"missing": False, "problem": f"{self.path} cannot be read: {key[6:]}"}
        else:
            r = read_paired_boards(self.path)
        if r.get("missing"):
            self.addresses, self.refuse_all, self.seq, self.error, self.notes = (), False, None, None, []
            self.state = "missing"
            self.loaded_t = time.time()
            log.warning("%s does not exist: FrameLink datagrams and RkCameraInfo peers from ANY source address "
                        "are accepted (pair a board on the AGX dashboard)", self.path)
        elif r.get("problem"):
            self.error = f"{name}: {r['problem']}".replace(self.path, name)
            if self.addresses:
                self.state = "error"
                log.error("paired boards file not used (the last good set stays: %s): %s",
                          ", ".join(self.addresses), self.error)
            else:
                self.refuse_all, self.state = True, "error (refusing all)"
                log.error("paired boards file not used and no last good board address: FrameLink datagrams and "
                          "RkCameraInfo peers from ALL source addresses are REFUSED until a good file: %s",
                          self.error)
        else:
            addrs, notes = r["addresses"], r["notes"]
            self.addresses, self.seq, self.notes = addrs, r["seq"], notes
            self.loaded_t = time.time()
            self.error = f"{name}: " + "; ".join(notes) if notes else None
            for n in notes:
                log.error("paired boards: %s", n)
            if addrs:
                self.refuse_all, self.state = False, "ok"
                if addrs != old or self._first:
                    log.info("paired boards (seq %s): accept FrameLink and RkCameraInfo only from %s", r["seq"],
                             ", ".join(addrs))
            elif r["boards"] or notes:
                self.refuse_all, self.state = True, "no address (refusing all)"
                if not notes:
                    self.error = f"{name}: {r['boards']} paired board(s) but no usable board address"
                log.error("%s: paired board(s) but no usable board address: FrameLink datagrams and RkCameraInfo "
                          "peers from ALL source addresses are REFUSED (%s)", self.path, self.error)
            else:
                self.refuse_all, self.state = False, "no board"
                log.warning("%s has no board address: FrameLink datagrams and RkCameraInfo peers from ANY "
                            "source address are accepted", self.path)
        first, self._first = self._first, False
        changed = self.filter_addresses != old and not first
        if changed:
            self.changes += 1
        return changed

    def snapshot(self) -> dict:
        """The "allowed_sources" key of the internal status (docs/PAIRING_API.md). when_empty: what an empty
        "addresses" means now: "any" (accept each source) or "none" (refuse all)."""
        return {"addresses": list(self.addresses), "from": os.path.basename(self.path), "seq": self.seq,
                "loaded_t": self.loaded_t, "error": self.error, "state": self.state, "changes": self.changes,
                "when_empty": "none" if self.refuse_all and not self.addresses else "any",
                "refusing_all": bool(self.refuse_all and not self.addresses)}


def load_config(cfg=None) -> dict:
    if cfg is None:
        cfg = DEFAULT_CONFIG
    if isinstance(cfg, (str, os.PathLike)):
        with open(cfg) as fh:
            cfg = yaml.safe_load(fh) or {}
    return dict(cfg)


class Ingest:
    def __init__(self, config=None, mode: str | None = None, allowed_sources=()):
        """allowed_sources: the board addresses at start (PairedBoards.addresses); rk mode only."""
        self.cfg = load_config(config)
        self.mode = mode or os.environ.get("AGX_INGEST_MODE") or self.cfg.get("mode", "sim")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {self.mode!r}")
        bh = self.cfg.get("bind_host", {})
        if isinstance(bh, dict):
            self.bind_host = bh.get(self.mode, "127.0.0.1" if self.mode == "sim" else "0.0.0.0")
        else:
            self.bind_host = bh
        # source filter: rk mode only (sim binds loopback, file has no network)
        self.allowed_sources = parse_allowed_sources(allowed_sources) if self.mode == "rk" else ()
        if "rk_allowed_sources" in self.cfg:
            log.info("config key rk_allowed_sources is not used any more: the board addresses come from "
                     "data/paired_boards.json")
        cams_cfg = {int(c["cam"]): c for c in self.cfg.get("cameras", [])}
        self.cams = list(range(6))  # always six cameras, even without config / signal
        self.store = FrameStore(self.cams, stale_s=float(self.cfg.get("stale_s", 0.5)),
                                no_signal_s=float(self.cfg.get("no_signal_s", 1.0)))
        expect_sim = self.mode != "rk"
        self.metrics: dict[int, CameraMetrics] = {}
        self.sources = []
        for cam in self.cams:
            c = cams_cfg.get(cam, {})
            # rk mode: the DA01 rk-camd camera name (role_rk) when present; else the old-stack role
            role = (c.get("role_rk") if self.mode == "rk" else None) or c.get("role", ROLES[cam])
            port = int(c.get("port", fl.BASE_PORT + cam))
            m = CameraMetrics(cam, role, port if self.mode != "file" else None, self.mode,
                              self.store, expect_simulated=expect_sim)
            self.metrics[cam] = m
            if c.get("enabled", True) is False:
                continue
            if self.mode == "file":
                from infer.ingest.file_source import FileSource
                self.sources.append(FileSource(cam, c.get("files", []), self.store, m,
                                               fps=float(self.cfg.get("file_fps", 30))))
            else:
                from infer.ingest.framelink_rx import FrameLinkReceiver
                self.sources.append(FrameLinkReceiver(
                    cam, port, self.bind_host, self.store, m, expect_simulated=expect_sim,
                    h265_resync_on_loss=bool(self.cfg.get("h265_resync_on_loss", True)),
                    rcvbuf=int(self.cfg.get("rcvbuf_bytes", 0) or 0),
                    reassembly_timeout_s=float(self.cfg.get("reassembly_timeout_s", 0.2)),
                    use_process=bool(self.cfg.get("rx_process", True)),
                    ring_slots=int(self.cfg.get("ring_slots", 8)),
                    max_frame=int(self.cfg.get("max_frame_bytes", 2 * 1024 * 1024)),
                    decoder_prestart=bool(self.cfg.get("decoder_prestart", True)),
                    allowed_sources=self.allowed_sources))
        self._started = False

    def start(self) -> None:
        # Only for rx_process: false (receive threads in this process share the GIL; the default
        # switch interval of 5 ms lets a socket overflow). Process-wide setting.
        if self.mode == "rk":
            if self.allowed_sources:
                log.info("rk mode: accept FrameLink datagrams from %s", describe_filter(self.allowed_sources))
            else:
                # INFO: PairedBoards writes the one WARNING for "no paired board"
                log.info("rk mode: no paired board address: FrameLink datagrams from ANY "
                         "source address are accepted on %s (pair a board: data/paired_boards.json)",
                         self.bind_host)
        si = self.cfg.get("gil_switch_interval_s", 0)
        if si and self.mode != "file":
            sys.setswitchinterval(float(si))
        started = []
        try:
            for s in self.sources:
                s.start()
                started.append(s)
        except Exception:
            for s in started:
                s.stop()
            raise
        self._started = True

    def stop(self) -> None:
        for s in self.sources:
            try:
                s.stop()
            except Exception:  # noqa: BLE001
                pass
        self._started = False

    def set_allowed_sources(self, addrs) -> bool:
        """New FrameLink source filter at run time (rk mode only; sim and file mode have no filter). No receiver
        restarts. Returns True when the list changed."""
        if self.mode != "rk":
            return False
        new = parse_allowed_sources(addrs)
        changed = new != self.allowed_sources
        self.allowed_sources = new
        for s in self.sources:
            if hasattr(s, "set_allowed_sources"):
                changed = s.set_allowed_sources(new) or changed
        if changed:
            if new:
                log.info("rk mode: FrameLink source filter changed: accept %s", describe_filter(new))
            else:
                log.info("rk mode: FrameLink source filter changed: no paired board address: datagrams from "
                         "ANY source address are accepted")
        return changed

    def source_stats(self, now_mono: float | None = None) -> dict:
        """FrameLink frames / dropped datagrams per source address over all cameras:
        {addr: {"frames_3s", "last_t", "dropped", "dropped_last_t"}} (addresses active in the last 60 s)."""
        now_mono = time.monotonic() if now_mono is None else now_mono
        out: dict[str, dict] = {}
        for s in self.sources:
            fn = getattr(s, "source_stats", None)
            if fn is None:
                continue
            try:
                st = fn(now_mono)
            except Exception:  # noqa: BLE001 - counters only
                log.exception("source stats failed")
                continue
            for a, e in st.items():
                o = out.setdefault(a, {"frames_3s": 0, "last_t": None, "dropped": 0, "dropped_last_t": None})
                o["frames_3s"] += int(e.get("frames_window") or 0)
                o["dropped"] += int(e.get("dropped") or 0)
                for k, src in (("last_t", "last_t"), ("dropped_last_t", "dropped_last_t")):
                    v = e.get(src)
                    if v is not None and (o[k] is None or v > o[k]):
                        o[k] = v
        return out

    def metrics_snapshot(self) -> list[dict]:
        out = []
        for c in self.cams:
            m = self.metrics[c]
            snap = m.snapshot()
            snap["foreign_source_drops"] = int(m.c.get("foreign_source_drops") or 0)
            out.append(snap)
        return out

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
