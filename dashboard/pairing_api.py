"""Pairing API of the AGX dashboard (docs/PAIRING_API.md; store: common/pairing_store.py).

  GET  /api/pair/info                no auth (IP allowlist)   {agx, name, schema, control_mode, pairing_open, ports}
  POST /api/pair/code                Basic + X-AGX-CSRF       {ok, code, expires_t, ttl_s}       vehicle -> 409
  POST /api/pair                     no auth (code in body)   201 {board_id, token, agx_name}   403 {reason}; vehicle 409
  GET  /api/pair/boards              Basic or a board token   [{id, name, address, addresses, paired_t, last_seen_t, ...}]
  GET  /api/pair/state               Basic                    the Settings page: this unit, boards, code state, settings
  POST /api/pair/boards/{id}/remove  Basic + X-AGX-CSRF       {ok, removed}                       vehicle -> 409
  GET  /api/pair/settings            Basic                    {accepted_board_address}
  POST /api/pair/settings            Basic + X-AGX-CSRF       {accepted_board_address}            vehicle -> 409
Each action goes to the model controller audit (<model_store>/_state/audit.jsonl) with source and user. No answer of a
GET has a secret; the code is only in the answer of POST /api/pair/code, the token only in the answer of POST /api/pair.
"""
from __future__ import annotations

import logging
import os
import socket
import time
from pathlib import Path

import yaml
from fastapi import Request

from common.pairing_store import CODE_MAX_WRONG, PairingError, ipv4
from controller import audit as audit_log
from controller.audit import clean
from controller.control import read_control_mode
from dashboard.auth import ip_text
from dashboard.config import resolve_path
from dashboard.control_api import _body, _json, actor, csrf_problem

log = logging.getLogger("dashboard.pairing")

API = "agx-pair/1"
DEFAULT_PORTS = {"video_base": 6000, "results": 5560, "status": 5561, "rkinfo": 5564}
ACCEPTED_LINE = ("Empty: each paired board can control this AGX. "
                 "With an address: only that address can control this AGX.")


def schema_hashes() -> dict:
    """The hashes that agx-infer sends (infer/publish/schema.py constants; no capnp load here)."""
    try:
        from infer.publish.schema import EXPECTED_HASH, STATUS_V2_HASH
        # v3, and v2 (sent while config/infer.yaml status.schema_version is 2)
        return {"status": ["0x%08x" % EXPECTED_HASH["AgxInferStatus"], "0x%08x" % STATUS_V2_HASH],
                "result": "0x%08x" % EXPECTED_HASH["AgxPerceptionResult"]}
    except Exception as e:   # the dashboard must answer also without pycapnp
        log.warning("schema hashes not known: %s", e)
        return {"status": [], "result": None}


def read_ports(infer_cfg: Path | None, sources_cfg: Path | None) -> dict:
    """The AGX ports for the RK board, from config/infer.yaml and config/sources.yaml (read only; defaults when a
    file cannot be read). Video: the cameras with their own "port" give the list (as before); else
    base_port + 0..5 (sources.yaml base_port, default 6000)."""
    out = dict(DEFAULT_PORTS)
    out["video"] = [out["video_base"] + n for n in range(6)]
    try:
        with open(infer_cfg, encoding="utf-8") as f:
            ports = (yaml.safe_load(f) or {}).get("ports") or {}
        for k in ("results", "status", "rkinfo"):
            if isinstance(ports.get(k), int):
                out[k] = ports[k]
    except (OSError, TypeError, yaml.YAMLError, AttributeError):
        pass
    try:
        with open(sources_cfg, encoding="utf-8") as f:
            src = yaml.safe_load(f) or {}
        base = src.get("base_port")
        if isinstance(base, int) and not isinstance(base, bool) and base > 0:
            out["video"], out["video_base"] = [base + n for n in range(6)], base
        cams = src.get("cameras") or []
        vp = sorted(c["port"] for c in cams if isinstance(c, dict) and isinstance(c.get("port"), int))
        if vp:
            out["video"], out["video_base"] = vp, vp[0]
    except (OSError, TypeError, yaml.YAMLError, AttributeError):
        pass
    return out


def link_view(boards: list[dict], st: dict | None, reason: str | None) -> tuple[list[dict], dict]:
    """Link state per board from the agx-infer internal status (contract section F keys board_sources,
    result_subscribers; a missing key = an old agx-infer). Returns (boards with link_state + link_detail, other)."""
    if st is None:
        for b in boards:
            b["link_state"], b["link_detail"] = "NO DATA", reason or "agx-infer sends no status"
        return boards, {"available": False, "reason": reason or "agx-infer sends no status", "count": None,
                        "addresses": []}
    bs = st.get("board_sources")
    rs = st.get("result_subscribers")
    bs = bs if isinstance(bs, dict) else None
    rs = rs if isinstance(rs, dict) else None
    if bs is None and rs is None:
        why = "this agx-infer version sends no link data per board"
        for b in boards:
            b["link_state"], b["link_detail"] = "NO DATA", why
        return boards, {"available": False, "reason": why, "count": None, "addresses": []}
    sub_addrs = [a for a in (rs or {}).get("addresses") or [] if isinstance(a, str)]
    paired = set()
    now = time.time()
    for b in boards:
        addrs = b.get("addresses") or []
        paired.update(addrs)
        frames = 0
        info_t = None
        results = False
        for a in addrs:
            s = (bs or {}).get(a)
            if isinstance(s, dict):
                n = s.get("framelink_frames_3s")
                frames += n if isinstance(n, int) and not isinstance(n, bool) else 0
                t = s.get("rkinfo_last_t")
                if isinstance(t, (int, float)) and (info_t is None or t > info_t):
                    info_t = t
                results = results or s.get("result_subscriber") is True
            results = results or a in sub_addrs
        state = ("UP" if frames and results else "frames only" if frames else "results only" if results
                 else "DOWN")
        parts = [f"frames in the last 3 s: {frames}" if bs is not None else "frames: not known",
                 "result subscription: " + ("yes" if results else "no")]
        if info_t is not None:
            parts.append(f"camera names: {max(0.0, now - info_t):.0f} s ago")
        b["link_state"], b["link_detail"] = state, "; ".join(parts)
    other = [a for a in sub_addrs if a not in paired]
    count = len(other) if rs is not None and "addresses" in rs else None
    return boards, {"available": rs is not None, "reason": None if rs is not None else
                    "this agx-infer version does not send the result subscribers", "count": count,
                    "addresses": other}


# The present agx-infer rule for an empty address set (infer/ingest/ingest.py PairedBoards): no board address = the
# source filter is off. agx-infer can say its rule in allowed_sources.when_empty ("any" or "none"); see source_filter().
NO_ADDRESS_LEFT = ("no paired board address is left: agx-infer has no board address for its video source filter "
                   "(see 'Video source filter' on the Settings page)")


def source_filter(st: dict | None, reason: str | None) -> dict:
    """The FrameLink / RkCameraInfo source filter that agx-infer uses (internal status key allowed_sources, contract
    section F). mode: "only" (addresses), "any" (no address: agx-infer accepts each source address), "none" (no
    address: agx-infer accepts no source), "unknown" (no status / an old agx-infer)."""
    a = st.get("allowed_sources") if isinstance(st, dict) else None
    if not isinstance(a, dict):
        if st is None:
            why = reason or "agx-infer sends no status"
        else:
            why = "this agx-infer version does not send its source filter"
        return {"mode": "unknown", "when_empty": None, "addresses": [], "reason": why, "error": None, "seq": None}
    addrs = [x for x in (a.get("addresses") or []) if isinstance(x, str)]
    # the present agx-infer: no address = accept any source (no when_empty key). "none": accept no source.
    when_empty = a.get("when_empty") if a.get("when_empty") in ("any", "none") else "any"
    mode = "only" if addrs else when_empty
    err = a.get("error") if isinstance(a.get("error"), str) else None
    seq = a.get("seq") if isinstance(a.get("seq"), int) and not isinstance(a.get("seq"), bool) else None
    return {"mode": mode, "when_empty": when_empty, "addresses": addrs, "reason": None, "error": err, "seq": seq}


def register(app, hub, pairing, fails, cfg: dict) -> None:
    control_file = resolve_path(cfg.get("control_config") or "config/control.yaml")
    ports_cache = read_ports(resolve_path(cfg.get("infer_config")), resolve_path(cfg.get("sources_config")))
    hashes = schema_hashes()
    hostname = socket.gethostname()

    def state_dir() -> Path:
        c = getattr(hub, "controller", None)
        if c is not None:
            return c.store.state
        return Path(os.path.expanduser(cfg.get("model_store") or "~/agx-models")) / "_state"

    def audit(source, user, action, result, reason=None, **extra):
        audit_log.append(state_dir(), source, user, action, None, None, result, reason, **extra)

    app.state.pair_audit = audit

    def mode() -> tuple[str, str | None]:
        return read_control_mode(control_file)

    def vehicle_refusal(what: str) -> str | None:
        m, problem = mode()
        if m == "vehicle":
            return f"This AGX is in vehicle mode (config/control.yaml): {what} is refused" + \
                (f" ({problem})" if problem else "")
        return None

    app.state.pair_vehicle_refusal = vehicle_refusal   # GuardMiddleware: no new board address in vehicle mode

    def ports(request: Request) -> dict:
        p = dict(ports_cache)
        srv = request.scope.get("server")
        p["api"] = srv[1] if srv and srv[1] else int(cfg.get("port") or 8700)
        return p

    def need_basic(request: Request):
        if getattr(request.state, "auth_kind", None) != "basic":
            return _json({"ok": False, "reason": "this route needs the dashboard login"}, 401)
        return None

    def board_rows(with_filter: bool = False):
        st, _state, reason, _age = hub.infer.current()
        rows = pairing.boards()
        for b in rows:
            b["address"] = b.get("last_seen_addr") or (b["addresses"][0] if b["addresses"] else None)
        rows, other = link_view(rows, st, reason)
        if with_filter:
            return rows, other, source_filter(st, reason)
        return rows, other

    def unit_doc(request: Request) -> dict:
        try:
            h = hub.health.latest() or {}
        except Exception:
            h = {}
        nets = [{"if": n.get("if"), "addrs": list(n.get("addrs") or []), "state": n.get("state")}
                for n in (h.get("net") or []) if isinstance(n, dict) and n.get("addrs")]
        return {"name": h.get("hostname") or hostname, "addresses": nets, "ports": ports(request)}

    @app.get("/api/pair/info")
    def api_pair_info(request: Request):
        m, problem = mode()
        return _json({"agx": True, "api": API, "name": hostname, "schema": hashes, "control_mode": m,
                      "control_problem": problem, "pairing_open": pairing.pairing_open(), "ports": ports(request)})

    @app.post("/api/pair/code")
    async def api_pair_code(request: Request):
        bad = need_basic(request)
        if bad:
            return bad
        source, user = actor(request)
        why = csrf_problem(request)
        if why:
            return _json({"ok": False, "reason": why}, 403)
        why = vehicle_refusal("a pairing code")
        if why:
            audit(source, user, "pair.code", "refused", why)
            return _json({"ok": False, "reason": why}, 409)
        doc = pairing.new_code(user)
        audit(source, user, "pair.code", "ok", None, expires_t=doc["expires_t"])
        return _json({"ok": True, "code": doc["code"], "expires_t": doc["expires_t"], "ttl_s": doc["ttl_s"],
                      "wrong_max": CODE_MAX_WRONG})

    @app.post("/api/pair")
    async def api_pair(request: Request):
        ip = ip_text(request.client.host if request.client else "")
        body, problem = await _body(request)
        name = clean((body or {}).get("board_name") or "?") if isinstance(body, dict) else "?"
        if problem:
            audit("rk-console", name, "pair", "refused", problem, addr=ip)
            return _json({"ok": False, "reason": problem}, 400)
        why = vehicle_refusal("pairing")
        if why:
            audit("rk-console", name, "pair", "refused", why, addr=ip)
            return _json({"ok": False, "reason": why}, 409)
        settings, sprob = pairing.settings()
        acc = settings.get("accepted_board_address") or ""
        if sprob or (acc and acc != ip):
            why = (f"pairing is refused: the link settings file has a problem ({sprob})" if sprob else
                   f"pairing is accepted only from {acc} (accepted board address)")
            audit("rk-console", name, "pair", "refused", why, addr=ip)
            return _json({"ok": False, "reason": why}, 403)
        try:
            res = pairing.pair(body.get("code"), body.get("board_name"), body.get("board_addresses"), ip)
        except PairingError as e:
            if e.status == 403:
                fails.record(ip)   # a wrong, used or expired code counts as a failed login of this address
            audit("rk-console", name, "pair", "refused", e.reason, addr=ip)
            return _json({"ok": False, "reason": e.reason}, e.status)
        except OSError as e:
            audit("rk-console", name, "pair", "failed", f"the paired boards file cannot be written: {e.strerror}",
                  addr=ip)
            return _json({"ok": False, "reason": f"the paired boards file cannot be written: {e.strerror}"}, 500)
        b = res["board"]
        fails.ok(ip)
        audit("rk-console", b["name"], "pair", "ok", None, board_id=b["id"], addresses=b["addresses"], addr=ip)
        log.info("board %s paired from %s", b["id"], ip)
        return _json({"ok": True, "board_id": b["id"], "token": res["token"], "agx_name": hostname,
                      "addresses": b["addresses"]}, 201)

    @app.get("/api/pair/boards")
    def api_pair_boards(request: Request):
        rows, _other = board_rows()
        return _json(rows)

    @app.get("/api/pair/state")
    def api_pair_state(request: Request):
        bad = need_basic(request)
        if bad:
            return bad
        rows, other, sfilter = board_rows(with_filter=True)
        settings, sprob = pairing.settings()
        m, problem = mode()
        _doc = pairing.doc()
        return _json({"unit": unit_doc(request), "boards": rows, "other_subscribers": other,
                      "source_filter": sfilter,
                      "code": pairing.code_state(), "settings": settings, "settings_problem": sprob,
                      "accepted_line": ACCEPTED_LINE, "store_problem": pairing.problem, "seq": _doc["seq"],
                      "control_mode": m, "control_problem": problem, "t": time.time()})

    @app.post("/api/pair/boards/{board_id}/remove")
    async def api_pair_remove(board_id: str, request: Request):
        bad = need_basic(request)
        if bad:
            return bad
        source, user = actor(request)
        why = csrf_problem(request)
        if why:
            return _json({"ok": False, "reason": why}, 403)
        bid = clean(board_id, 40)
        why = vehicle_refusal("the removal of a pairing")
        if why:
            audit(source, user, "pair.remove", "refused", why, board_id=bid)
            return _json({"ok": False, "reason": why}, 409)
        try:
            b = pairing.remove(board_id)
        except PairingError as e:
            audit(source, user, "pair.remove", "refused", e.reason, board_id=bid)
            return _json({"ok": False, "reason": e.reason}, e.status)
        except OSError as e:
            audit(source, user, "pair.remove", "failed", e.strerror, board_id=bid)
            return _json({"ok": False, "reason": f"the paired boards file cannot be written: {e.strerror}"}, 500)
        warn = None
        if not b["addresses_left"]:
            warn = NO_ADDRESS_LEFT
        audit(source, user, "pair.remove", "ok", warn, board_id=b["id"], board_name=b["name"],
              boards_left=b["boards_left"], addresses_left=b["addresses_left"])
        return _json({"ok": True, "removed": b["id"], "boards_left": b["boards_left"],
                      "addresses_left": b["addresses_left"], "warning": warn})

    @app.get("/api/pair/settings")
    def api_pair_settings_get(request: Request):
        bad = need_basic(request)
        if bad:
            return bad
        settings, sprob = pairing.settings()
        return _json(dict(settings, problem=sprob, line=ACCEPTED_LINE))

    @app.post("/api/pair/settings")
    async def api_pair_settings_post(request: Request):
        bad = need_basic(request)
        if bad:
            return bad
        source, user = actor(request)
        why = csrf_problem(request)
        if why:
            return _json({"ok": False, "reason": why}, 403)
        body, problem = await _body(request)
        if problem or "accepted_board_address" not in (body or {}) or \
                not isinstance(body.get("accepted_board_address"), str):
            reason = problem or "the body must have accepted_board_address (text; empty = no limit)"
            return _json({"ok": False, "reason": reason}, 400)
        new = body["accepted_board_address"].strip()
        why = vehicle_refusal("a change of the link settings")
        if why:
            audit(source, user, "pair.settings", "refused", why, accepted_board_address=clean(new, 40))
            return _json({"ok": False, "reason": why}, 409)
        try:
            doc = pairing.set_accepted(new)
        except PairingError as e:
            audit(source, user, "pair.settings", "refused", e.reason, accepted_board_address=clean(new, 40))
            return _json({"ok": False, "reason": e.reason}, e.status)
        except OSError as e:
            audit(source, user, "pair.settings", "failed", e.strerror)
            return _json({"ok": False, "reason": f"the link settings file cannot be written: {e.strerror}"}, 500)
        known = {a for b in pairing.boards() for a in b["addresses"]}
        warn = None
        if new and new not in known:
            warn = f"no paired board has the address {new}: no board can control this AGX now"
        audit(source, user, "pair.settings", "ok", warn, accepted_board_address=new)
        return _json({"ok": True, "accepted_board_address": doc["accepted_board_address"], "warning": warn})


def migrate_at_start(pairing, cfg: dict, audit) -> dict | None:
    """Start-up migration (contract S6): data/control.token -> board rk3588-da01. Addresses: config/sources.yaml
    rk_allowed_sources + rk_ip of the dashboard yaml (the file value, not the code default)."""
    from common.pairing_store import migrate
    addrs: list[str] = []
    try:
        with open(resolve_path(cfg.get("sources_config")), encoding="utf-8") as f:
            v = (yaml.safe_load(f) or {}).get("rk_allowed_sources") or []
        addrs += [v] if isinstance(v, str) else [str(a) for a in v] if isinstance(v, list) else []
    except (OSError, TypeError, yaml.YAMLError, AttributeError):
        pass
    try:
        if cfg.get("config_file"):
            with open(cfg["config_file"], encoding="utf-8") as f:
                rk = (yaml.safe_load(f) or {}).get("rk_ip")
            if rk:
                addrs.append(str(rk))
    except (OSError, TypeError, yaml.YAMLError, AttributeError):
        pass
    addrs = [a for a in (ipv4(x) for x in addrs) if a]
    try:
        res = migrate(pairing, resolve_path(cfg.get("control_token_file")), addrs)
    except (PairingError, OSError) as e:
        why = getattr(e, "reason", None) or str(e)
        log.error("pairing migration failed: %s", why)
        audit("controller", "start-up migration", "pair.migrate", "failed", why)
        return None
    if res and not res["board"]["addresses"]:
        log.warning("pairing migration: config/sources.yaml rk_allowed_sources and the rk_ip of the dashboard yaml "
                    "are not there: the board %s has no address yet. Its first control request adds its address "
                    "in bench mode (not in vehicle mode). Until then agx-infer has no board address",
                    res["board"]["id"])
    if res:
        b = res["board"]
        log.info("pairing migration: the control token is now the paired board %s (addresses %s); %s -> %s",
                 b["id"], ", ".join(b["addresses"]) or "none", res["from"], res["to"])
        audit("controller", "start-up migration", "pair.migrate", "ok", None, board_id=b["id"],
              addresses=b["addresses"], moved_to=os.path.basename(res["to"]))
    return res
