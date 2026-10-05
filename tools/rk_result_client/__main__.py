"""RK result client: subscribe to the AGX inference node like the RK3588 agent does, check every
message, and measure the latencies.

  python -m tools.rk_result_client --host 127.0.0.1 [--results-port 5560] [--status-port 5561]
      [--schema /home/tonyho/driveragent-agx/proto/agx_infer.capnp]
      [--envelope-dir /home/tonyho/driveragent-agx/common] [--seconds N] [--print]
      [--json out.json] [--expect-cams 0,1,2,3,4,5]

Dependencies: pyzmq, pycapnp, the schema file (.capnp) and dabus_envelope.py (the RK reference
envelope, loaded from --envelope-dir). This file imports no other project code, so you can copy it
to the RK3588 and run it as "python3 __main__.py ...".

Per message (results and status):
  1. dabus_envelope.unpack: length >= 32, magic 0xDA5E, version 1, len field, CRC-32C.
  2. src_board == 1 (AGX), type_id == the registered port of the channel (5560 / 5561; set by
     --result-type-id / --status-type-id, so a test on other ports still checks 5560 / 5561),
     schema_hash == dabus_envelope.schema_hash(schema text, struct name).
  3. Cap'n Proto decode (AgxPerceptionResult / AgxInferStatus).
A message that fails a step is a reject, counted by reason. It is not decoded.

Latencies per result (ms):
  agx_ms      = tAgxResultNs - tAgxRecvNs          frame received at the AGX -> result complete
                                                   (one clock: the AGX clock; always valid)
  e2e_recv_ms = t_client_recv - tAgxRecvNs         frame received at the AGX -> result received
                                                   at this client (valid only when this client and
                                                   the AGX use one clock: same host, or PTP)
  capture_ms  = t_client_recv - tCaptureNs         frame capture (sender clock) -> result received
                                                   at this client (valid only when this client and
                                                   the frame sender use one clock)
t_client_recv = time.time_ns() just after zmq recv() returns.

Checks: no duplicate (model, camId, frameSeq); frameSeq increases per (model, camId) (a big jump back
is a stream restart: counted, not an error); every camera of --expect-cams has results; no rejects.
Exit code: 0 = all checks pass, 1 = a check failed, 2 = setup error (files, arguments).

R8: the messages contain no control values, and this client prints none. R13: every simulated
result (envelope flag bit0 or capnp field "simulated") is printed with the tag SIMULATED.
"""
from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import json
import math
import os
import socket
import sys
import time
from collections import Counter, defaultdict, deque

import capnp  # pycapnp
import zmq

DEFAULT_SCHEMA = "/home/tonyho/driveragent-agx/proto/agx_infer.capnp"
DEFAULT_ENVELOPE_DIR = "/home/tonyho/driveragent-agx/common"
RESULT_STRUCT = "AgxPerceptionResult"
STATUS_STRUCT = "AgxInferStatus"
SRC_AGX = 1
U32 = 1 << 32
RESTART_JUMP = 300        # frameSeq back by more than this = stream restart (10 s at 30 fps)
WRAP_ZONE = 1 << 16       # last seq in the top 64k and new seq in the bottom 64k = uint32 wrap
DUP_WINDOW = 20000        # frameSeq values kept per (model, cam) for the duplicate check
MAX_EXAMPLES = 20


# ---- setup -----------------------------------------------------------------------------------------
def load_envelope(env_dir: str, crc_mode: str):
    """Load dabus_envelope.py from env_dir (RK: rk/proto/envelope, AGX: common).
    crc_mode "auto": when the pip package crc32c is installed, the reference module uses it for the
    CRC-32C (same result, ~1000x faster; checked against the RFC 3720 check value first)."""
    path = os.path.join(env_dir, "dabus_envelope.py")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no dabus_envelope.py in {env_dir}")
    spec = importlib.util.spec_from_file_location("dabus_envelope", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.CRC_IMPL = "reference (pure Python)"
    if crc_mode == "auto":
        try:
            import crc32c as fast  # optional

            def _fast(data, crc: int = 0) -> int:
                return fast.crc32c(bytes(data), crc) if crc else fast.crc32c(bytes(data))

            if _fast(b"123456789") == 0xE3069283 == mod.crc32c(b"123456789"):
                mod.crc32c = _fast   # unpack() calls the module global crc32c
                mod.CRC_IMPL = "crc32c package (checked against the reference)"
        except ImportError:
            pass
    return mod


def is_local_host(host: str) -> bool:
    """True when host is this machine (loopback or one of its own addresses)."""
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    own = set()
    for name in (socket.gethostname(), socket.getfqdn()):
        try:
            own |= {ai[4][0] for ai in socket.getaddrinfo(name, None)}
        except OSError:
            pass
    try:  # the source address that the kernel uses for host is one of our own addresses
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((host, 9))
            own.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    for a in addrs:
        try:
            if ipaddress.ip_address(a.split("%")[0]).is_loopback:
                return True
        except ValueError:
            continue
        if a in own:
            return True
    return False


# ---- statistics ------------------------------------------------------------------------------------
def pct(sorted_vals: list[float], p: float):
    """Nearest-rank percentile of a sorted list (None when empty)."""
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, math.ceil(p / 100.0 * len(sorted_vals)) - 1))
    return sorted_vals[k]


def lat_summary(vals: list[float]) -> dict:
    s = sorted(v for v in vals if v is not None and math.isfinite(v))
    r = lambda v: None if v is None else round(v, 3)  # noqa: E731
    return {"n": len(s), "p50": r(pct(s, 50)), "p95": r(pct(s, 95)), "p99": r(pct(s, 99)),
            "max": r(s[-1] if s else None), "min": r(s[0] if s else None),
            "negative": sum(1 for v in s if v < 0)}


def fnum(v, nd=1):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    return f"{v:.{nd}f}"


def flag_text(flags: int) -> str:
    out = []
    if flags & 1:
        out.append("SIMULATED")
    if flags & 2:
        out.append("time_uncertain")
    if flags & 4:
        out.append("DEGRADED")
    return ",".join(out) or "-"


class Stream:
    """Counters of one (model, camId)."""

    def __init__(self):
        self.count = 0
        self.simulated = 0
        self.degraded = 0
        self.t_first = None
        self.t_last = None
        self.first_seq = None
        self.last_seq = None
        self.seen = set()
        self.seen_order = deque()
        self.duplicates = 0
        self.restarts = 0
        self.out_of_order = 0
        self.skipped_frames = 0
        self.agx_ms: list[float] = []
        self.e2e_recv_ms: list[float] = []
        self.capture_ms: list[float] = []
        self.classes = Counter()
        self.detections = 0

    def remember(self, seq: int) -> None:
        self.seen.add(seq)
        self.seen_order.append(seq)
        if len(self.seen_order) > DUP_WINDOW:
            self.seen.discard(self.seen_order.popleft())

    def check_seq(self, seq: int) -> str:
        """Return "ok", "duplicate", "restart" or "out_of_order"; update the counters."""
        last = self.last_seq
        if last is None:
            self.first_seq = self.last_seq = seq
            self.remember(seq)
            return "ok"
        if seq in self.seen:
            self.duplicates += 1
            return "duplicate"
        if seq > last:
            self.skipped_frames += seq - last - 1
            self.last_seq = seq
            self.remember(seq)
            return "ok"
        if last >= U32 - WRAP_ZONE and seq < WRAP_ZONE:   # uint32 wrap
            self.skipped_frames += (seq + U32) - last - 1
            self.last_seq = seq
            self.remember(seq)
            return "ok"
        if last - seq > RESTART_JUMP:
            self.restarts += 1
            self.seen.clear()
            self.seen_order.clear()
            self.last_seq = seq
            self.remember(seq)
            return "restart"
        self.out_of_order += 1
        self.remember(seq)
        return "out_of_order"


# ---- client ----------------------------------------------------------------------------------------
class Client:
    def __init__(self, a, env_mod):
        self.a = a
        self.env = env_mod
        with open(a.schema, encoding="utf-8") as f:
            text = f.read()
        self.mod = capnp.load(os.path.abspath(a.schema))
        self.want_hash = {RESULT_STRUCT: env_mod.schema_hash(text, RESULT_STRUCT),
                          STATUS_STRUCT: env_mod.schema_hash(text, STATUS_STRUCT)}
        self.local = is_local_host(a.host)
        self.ctx = zmq.Context()
        self.socks = {}
        self.poller = zmq.Poller()
        self.type_id = {"result": a.result_type_id, "status": a.status_type_id}
        for port, kind in ((a.results_port, "result"), (a.status_port, "status")):
            if not port:
                continue
            s = self.ctx.socket(zmq.SUB)
            s.setsockopt(zmq.LINGER, 0)
            s.setsockopt(zmq.RCVHWM, 10000)
            s.setsockopt(zmq.SUBSCRIBE, b"")
            s.connect(f"tcp://{a.host}:{port}")
            self.socks[s] = (kind, port)
            self.poller.register(s, zmq.POLLIN)
        self.streams: dict[tuple[str, int], Stream] = defaultdict(Stream)
        self.rejects = {"result": Counter(), "status": Counter()}
        self.messages = Counter()
        self.flags = Counter()
        self.env_seq_last = {}
        self.env_seq_lost = Counter()
        self.dup_examples: list[dict] = []
        self.restart_examples: list[dict] = []
        self.ooo_examples: list[dict] = []
        self.sim_mismatch = 0
        self.proc_ms: list[float] = []
        self.status_recv_mono: list[float] = []
        self.status_last: dict | None = None
        self.warnings: list[str] = []
        self._warned = set()
        self.t_start = None
        self.t_end = None

    def warn(self, key: str, text: str) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        self.warnings.append(text)
        print(f"WARNING: {text}", file=sys.stderr, flush=True)

    def close(self) -> None:
        for s in self.socks:
            s.close(0)
        self.ctx.term()

    # -- envelope + decode -------------------------------------------------------------------------
    def check_envelope(self, kind: str, buf: bytes, struct_name: str):
        try:
            e = self.env.unpack(buf)
        except ValueError as ex:
            reason = {"short message": "short", "bad magic/version": "magic_version",
                      "length mismatch": "length", "crc mismatch": "crc"}.get(str(ex), str(ex))
            self.rejects[kind][reason] += 1
            return None
        if e["src_board"] != SRC_AGX:
            self.rejects[kind]["src_board"] += 1
            return None
        if e["type_id"] != self.type_id[kind]:
            self.rejects[kind]["type_id"] += 1
            return None
        if e["schema_hash"] != self.want_hash[struct_name]:
            self.rejects[kind]["schema_hash"] += 1
            self.warn(f"hash{kind}", f"{kind}: schema hash 0x{e['schema_hash']:08x} != "
                      f"0x{self.want_hash[struct_name]:08x} of {self.a.schema}: schema files differ")
            return None
        # envelope seq: one counter per (src_board, type_id); a gap = messages lost after build
        last = self.env_seq_last.get(kind)
        if last is not None:
            gap = (e["seq"] - last - 1) & 0xFFFFFFFF
            if gap < 0x80000000:
                self.env_seq_lost[kind] += gap
        self.env_seq_last[kind] = e["seq"]
        return e

    def handle_result(self, buf: bytes, t_recv_ns: int) -> None:
        e = self.check_envelope("result", buf, RESULT_STRUCT)
        if e is None:
            return
        try:
            with self.mod.AgxPerceptionResult.from_bytes(e["payload"]) as m:
                r = {"model": m.model, "cam": int(m.camId), "seq": int(m.frameSeq),
                     "t_cap": int(m.tCaptureNs), "t_recv": int(m.tAgxRecvNs),
                     "t_res": int(m.tAgxResultNs), "sim": bool(m.simulated), "source": m.source,
                     "classes": Counter(d.className or str(d.classId) for d in m.detections),
                     "ndet": len(m.detections), "npts": len(m.trajectory.points),
                     "masks": [k.name for k in m.masks]}
        except Exception as ex:  # noqa: BLE001
            self.rejects["result"]["capnp_decode"] += 1
            self.warn("decode", f"capnp decode error: {ex}")
            return
        self.messages["result_ok"] += 1
        fl = e["flags"]
        self.flags["result_bit0_source_is_replay"] += bool(fl & 1)
        self.flags["result_bit1_time_uncertain"] += bool(fl & 2)
        self.flags["result_bit2_degraded"] += bool(fl & 4)
        sim = r["sim"] or bool(fl & 1)
        if r["sim"] != bool(fl & 1):
            self.sim_mismatch += 1
            self.warn("simflag", "capnp 'simulated' and envelope flag bit0 differ (R13)")
        if fl & 2 and not self.local:
            self.warn("clock", f"time_uncertain is set and --host {self.a.host} is not this host: "
                      "e2e_recv_ms mixes two clocks (AGX and this client) and is not valid "
                      "without PTP. agx_ms stays valid.")

        st = self.streams[(r["model"], r["cam"])]
        verdict = st.check_seq(r["seq"])
        ex = {"model": r["model"], "cam": r["cam"], "frame_seq": r["seq"], "last_seq": st.last_seq}
        if verdict == "duplicate":
            if len(self.dup_examples) < MAX_EXAMPLES:
                self.dup_examples.append(ex)
            self.warn(f"dup{r['model']}{r['cam']}",
                      f"duplicate result {r['model']} cam{r['cam']} frameSeq {r['seq']}")
        elif verdict == "restart" and len(self.restart_examples) < MAX_EXAMPLES:
            self.restart_examples.append(ex)
        elif verdict == "out_of_order" and len(self.ooo_examples) < MAX_EXAMPLES:
            self.ooo_examples.append(ex)

        st.count += 1
        st.simulated += sim
        st.degraded += bool(fl & 4)
        st.t_first = st.t_first if st.t_first is not None else time.monotonic()
        st.t_last = time.monotonic()
        st.detections += r["ndet"]
        st.classes.update(r["classes"])
        agx = (r["t_res"] - r["t_recv"]) / 1e6 if r["t_recv"] else None
        e2e = (t_recv_ns - r["t_recv"]) / 1e6 if r["t_recv"] else None
        cap = (t_recv_ns - r["t_cap"]) / 1e6 if r["t_cap"] else None
        if agx is not None:
            st.agx_ms.append(agx)
        if e2e is not None:
            st.e2e_recv_ms.append(e2e)
        if cap is not None:
            st.capture_ms.append(cap)

        if self.a.print:
            top = " ".join(f"{k}:{v}" for k, v in r["classes"].most_common(3))
            tag = " SIMULATED" if sim else ""
            tag += " DEGRADED" if fl & 4 else ""
            tag += f" {verdict.upper()}" if verdict != "ok" else ""
            ts = time.strftime("%H:%M:%S", time.localtime(t_recv_ns / 1e9)) + \
                f".{(t_recv_ns // 1_000_000) % 1000:03d}"
            print(f"{ts} {r['model']} cam{r['cam']} seq={r['seq']} det={r['ndet']}"
                  f"{' [' + top + ']' if top else ''} traj={r['npts']} "
                  f"masks={len(r['masks'])}{tag} src={r['source']} agx={fnum(agx)}ms "
                  f"e2e_recv={fnum(e2e)}ms capture={fnum(cap)}ms", flush=True)

    def handle_status(self, buf: bytes, t_recv_ns: int) -> None:
        e = self.check_envelope("status", buf, STATUS_STRUCT)
        if e is None:
            return
        try:
            with self.mod.AgxInferStatus.from_bytes(e["payload"]) as s:
                st = {
                    "hostname": s.hostname, "version": s.version, "node_state": s.nodeState,
                    "simulated": bool(s.simulated), "uptime_s": int(s.uptimeS),
                    "t_status_ns": int(s.tStatusNs), "source_mode": s.sourceMode,
                    "flags": flag_text(e["flags"]),
                    "cameras": [{"cam": int(c.camId), "role": c.role, "state": c.state,
                                 "simulated": bool(c.simulated), "fps": round(float(c.fps), 2),
                                 "frame_age_ms": (None if math.isnan(c.frameAgeMs)
                                                  else round(float(c.frameAgeMs), 1)),
                                 "lost_frames": int(c.lostFrames), "lost_packets": int(c.lostPackets),
                                 "last_frame_seq": int(c.lastFrameSeq)} for c in s.cameras],
                    "models": [{"name": m.name, "state": m.state, "error": m.error,
                                "cameras": [int(x) for x in m.cameras], "fps": round(float(m.fps), 2),
                                "p50_ms": None if math.isnan(m.latencyP50Ms) else round(m.latencyP50Ms, 2),
                                "p95_ms": None if math.isnan(m.latencyP95Ms) else round(m.latencyP95Ms, 2),
                                "p99_ms": None if math.isnan(m.latencyP99Ms) else round(m.latencyP99Ms, 2)}
                               for m in s.models],
                    "errors": list(s.errors)[:5],
                    "results_port": int(s.resultsPort), "subscribers": int(s.resultSubscribers),
                    "results_rate_hz": round(float(s.resultsRateHz), 2),
                }
        except Exception as ex:  # noqa: BLE001
            self.rejects["status"]["capnp_decode"] += 1
            self.warn("sdecode", f"status capnp decode error: {ex}")
            return
        self.messages["status_ok"] += 1
        now = time.monotonic()
        prev = self.status_recv_mono[-1] if self.status_recv_mono else None
        self.status_recv_mono.append(now)
        self.status_last = st
        if self.a.print:
            iv = f"{now - prev:.3f}s" if prev is not None else "-"
            cams = " ".join(f"{c['cam']}:{c['state']}/{fnum(c['fps'])}fps" for c in st["cameras"])
            mods = " ".join(f"{m['name']}:{m['state']}/{fnum(m['fps'])}fps/"
                            f"p50={fnum(m['p50_ms'])},p95={fnum(m['p95_ms'])},p99={fnum(m['p99_ms'])}ms"
                            for m in st["models"])
            sim = " SIMULATED" if st["simulated"] or e["flags"] & 1 else ""
            print(f"STATUS node={st['node_state']}{sim} host={st['hostname']} mode={st['source_mode']} "
                  f"uptime={st['uptime_s']}s subs={st['subscribers']} rate={fnum(st['results_rate_hz'])}Hz "
                  f"interval={iv} | cams {cams or '-'} | models {mods or '-'}", flush=True)

    # -- loop ----------------------------------------------------------------------------------------
    def run(self) -> None:
        self.t_start = time.monotonic()
        t_end = self.t_start + self.a.seconds if self.a.seconds > 0 else None
        try:
            while True:
                rest = 0.2 if t_end is None else t_end - time.monotonic()
                if rest <= 0:
                    break
                for s, _ in self.poller.poll(int(min(rest, 0.2) * 1000)):
                    kind, port = self.socks[s]
                    while True:
                        try:
                            parts = s.recv_multipart(zmq.NOBLOCK)
                        except zmq.Again:
                            break
                        t_recv_ns = time.time_ns()
                        t0 = time.perf_counter()
                        self.messages[f"{kind}_frames"] += 1
                        if len(parts) != 1:
                            self.rejects[kind]["multipart"] += 1
                        elif kind == "result":
                            self.handle_result(parts[0], t_recv_ns)
                        else:
                            self.handle_status(parts[0], t_recv_ns)
                        self.proc_ms.append((time.perf_counter() - t0) * 1000.0)
                        if t_end is not None and time.monotonic() >= t_end:
                            break
        except KeyboardInterrupt:
            pass
        self.t_end = time.monotonic()

    # -- summary -------------------------------------------------------------------------------------
    def summary(self) -> dict:
        dur = (self.t_end or time.monotonic()) - (self.t_start or time.monotonic())
        per = []
        for (model, cam), st in sorted(self.streams.items()):
            span = (st.t_last - st.t_first) if st.count > 1 else 0.0
            per.append({
                "model": model, "cam": cam, "count": st.count,
                "rate_hz": round((st.count - 1) / span, 2) if span > 0 else None,
                "first_seq": st.first_seq, "last_seq": st.last_seq,
                "skipped_frames": st.skipped_frames, "duplicates": st.duplicates,
                "restarts": st.restarts, "out_of_order": st.out_of_order,
                "simulated": st.simulated, "degraded": st.degraded,
                "detections": st.detections, "top_classes": dict(st.classes.most_common(5)),
                "agx_ms": lat_summary(st.agx_ms), "e2e_recv_ms": lat_summary(st.e2e_recv_ms),
                "capture_ms": lat_summary(st.capture_ms)})
        iv = [b - a for a, b in zip(self.status_recv_mono, self.status_recv_mono[1:])]
        status_iv = {"n": len(iv), "mean_s": round(sum(iv) / len(iv), 4) if iv else None,
                     "max_s": round(max(iv), 4) if iv else None,
                     "min_s": round(min(iv), 4) if iv else None}
        cams_seen = sorted({cam for (_m, cam), st in self.streams.items() if st.count})
        missing = [c for c in self.a.expect_cams if c not in cams_seen]
        rejects = {k: dict(v) for k, v in self.rejects.items()}
        n_rej = sum(sum(v.values()) for v in self.rejects.values())
        n_dup = sum(st.duplicates for st in self.streams.values())
        n_ooo = sum(st.out_of_order for st in self.streams.values())
        n_ok = self.messages["result_ok"]
        checks = {
            "results_received": n_ok > 0,
            "expected_cameras": not missing,
            "no_rejects": n_rej == 0,
            "no_duplicates": n_dup == 0,
            "frame_seq_increases": n_ooo == 0,
        }
        if self.a.status_port:
            checks["status_received"] = self.messages["status_ok"] > 0
        e2e_valid = self.local or self.flags["result_bit1_time_uncertain"] == 0
        return {
            "tool": "rk_result_client", "host": self.a.host, "host_is_local": self.local,
            "results_port": self.a.results_port, "status_port": self.a.status_port,
            "type_id": self.type_id,
            "schema": os.path.abspath(self.a.schema),
            "schema_hash": {k: f"0x{v:08x}" for k, v in self.want_hash.items()},
            "envelope_module": os.path.abspath(os.path.join(self.a.envelope_dir, "dabus_envelope.py")),
            "crc_impl": getattr(self.env, "CRC_IMPL", "?"),
            "duration_s": round(dur, 3),
            "messages": dict(self.messages), "envelope_flags": dict(self.flags),
            "envelope_seq_lost": dict(self.env_seq_lost),
            "rejects": rejects, "rejects_total": n_rej,
            "duplicates": n_dup, "duplicate_examples": self.dup_examples,
            "restarts": sum(st.restarts for st in self.streams.values()),
            "restart_examples": self.restart_examples,
            "out_of_order": n_ooo, "out_of_order_examples": self.ooo_examples,
            "simulated_flag_mismatch": self.sim_mismatch,
            "expect_cams": self.a.expect_cams, "cams_seen": cams_seen, "cams_missing": missing,
            "latency_validity": {
                "agx_ms": "valid (one clock: AGX)",
                "e2e_recv_ms": "valid (client and AGX on one clock)" if e2e_valid else
                "NOT valid: client is not on the AGX host and time_uncertain is set (no PTP)",
                "capture_ms": "valid only when the client and the frame sender use one clock "
                              "(same host, or PTP)"},
            "client_proc_ms": lat_summary(self.proc_ms),
            "per_stream": per,
            "status": {"count": self.messages["status_ok"], "interval": status_iv,
                       "last": self.status_last},
            "warnings": self.warnings,
            "checks": checks,
            "exit_code": 0 if all(checks.values()) else 1,
        }


def print_summary(s: dict) -> None:
    p = print
    p("")
    p(f"=== rk_result_client summary: host {s['host']} (local={s['host_is_local']}), "
      f"{s['duration_s']} s, crc {s['crc_impl']} ===")
    p(f"messages {s['messages']}  flags {s['envelope_flags']}  envelope seq lost {s['envelope_seq_lost']}")
    p(f"{'model':<24} {'cam':>3} {'count':>6} {'Hz':>6} {'sim':>5} "
      f"{'agx_ms p50/p95/p99/max':>26} {'e2e_recv_ms p50/p95/p99/max':>30} "
      f"{'capture_ms p50/p95/p99/max':>30}")

    def q(d):
        return "/".join(fnum(d[k]) for k in ("p50", "p95", "p99", "max"))
    for r in s["per_stream"]:
        p(f"{r['model']:<24} {r['cam']:>3} {r['count']:>6} {fnum(r['rate_hz']):>6} "
          f"{r['simulated']:>5} {q(r['agx_ms']):>26} {q(r['e2e_recv_ms']):>30} {q(r['capture_ms']):>30}")
    st = s["status"]
    iv = st["interval"]
    p(f"status: {st['count']} messages, interval mean {fnum(iv['mean_s'], 3)} s, "
      f"max {fnum(iv['max_s'], 3)} s")
    if st["last"]:
        last = st["last"]
        p(f"status last: node {last['node_state']}{' SIMULATED' if last['simulated'] else ''}, "
          f"{len(last['cameras'])} cameras, {len(last['models'])} models, "
          f"subscribers {last['subscribers']}, rate {last['results_rate_hz']} Hz")
    p(f"rejects {s['rejects']}  duplicates {s['duplicates']}  restarts {s['restarts']}  "
      f"out_of_order {s['out_of_order']}")
    p(f"cameras seen {s['cams_seen']}  expected {s['expect_cams']}  missing {s['cams_missing']}")
    p(f"latency validity: e2e_recv_ms {s['latency_validity']['e2e_recv_ms']}")
    p(f"client processing ms p50/p99/max: {fnum(s['client_proc_ms']['p50'], 2)}/"
      f"{fnum(s['client_proc_ms']['p99'], 2)}/{fnum(s['client_proc_ms']['max'], 2)}")
    for k, v in s["checks"].items():
        p(f"check {k}: {'PASS' if v else 'FAIL'}")
    p(f"exit code {s['exit_code']}")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="rk_result_client", description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1", help="AGX address (RK3588: the AGX Link C address)")
    ap.add_argument("--results-port", type=int, default=5560)
    ap.add_argument("--status-port", type=int, default=5561, help="0 = do not subscribe to status")
    ap.add_argument("--result-type-id", type=int, default=5560,
                    help="expected envelope type_id of results (= the node port 5560)")
    ap.add_argument("--status-type-id", type=int, default=5561,
                    help="expected envelope type_id of status (= the node port 5561)")
    ap.add_argument("--schema", default=DEFAULT_SCHEMA)
    ap.add_argument("--envelope-dir", default=DEFAULT_ENVELOPE_DIR,
                    help="directory of dabus_envelope.py (RK repo: rk/proto/envelope)")
    ap.add_argument("--crc", choices=("auto", "reference"), default="auto",
                    help="auto: use the crc32c pip package when installed (same CRC-32C)")
    ap.add_argument("--seconds", type=float, default=10.0, help="run time, 0 = until Ctrl-C")
    ap.add_argument("--print", action="store_true", help="one line per result and per status")
    ap.add_argument("--json", metavar="FILE", help="write the summary as JSON")
    ap.add_argument("--expect-cams", default="", help="comma list, e.g. 0,1,2,3,4,5")
    a = ap.parse_args(argv)
    try:
        a.expect_cams = [int(x) for x in a.expect_cams.split(",") if x.strip() != ""]
    except ValueError:
        ap.error("--expect-cams: comma list of integers")
    return a


def main(argv=None) -> int:
    a = parse_args(argv)
    try:
        env_mod = load_envelope(a.envelope_dir, a.crc)
        client = Client(a, env_mod)
    except (OSError, KeyError, capnp.KjException) as ex:
        print(f"setup error: {ex}", file=sys.stderr)
        return 2
    print(f"rk_result_client: tcp://{a.host}:{a.results_port} (results) "
          f"tcp://{a.host}:{a.status_port} (status), schema hash "
          + ", ".join(f"{k} 0x{v:08x}" for k, v in client.want_hash.items())
          + f", host local={client.local}, {a.seconds} s", flush=True)
    try:
        client.run()
    finally:
        s = client.summary()
        client.close()
    print_summary(s)
    if a.json:
        d = os.path.dirname(os.path.abspath(a.json))
        os.makedirs(d, exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
        print(f"json: {a.json}")
    return s["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
