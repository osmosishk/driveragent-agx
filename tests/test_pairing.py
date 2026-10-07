"""Pairing of RK boards on the AGX02 dashboard (common/pairing_store.py, dashboard/pairing_api.py, dashboard/auth.py;
docs/PAIRING_API.md). In-process app with temporary files only: never the real data/ files, never the real password.

- store: mode 600, atomic write, only the SHA-256 of a token
- code: one use, expiry (short TTL), failed-try limit (per code, and per address -> 429)
- a removed board's token -> 401 at once (with the reason; not a failed login: the board can pair again at once);
  accepted board address; vehicle mode refusals (also: no new board address from a token request)
- the removal of the last board address: warning; the source filter of agx-infer on the page
- migration of a temporary control.token
- no secret in the logs, the audit or a GET answer; the UI POST rule
"""
from __future__ import annotations

import json
import logging
import os
import re
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from common import pairing_store as ps
from dashboard import auth, pairing_api

ROOT = Path(__file__).resolve().parent.parent
PW = "pair-test-pw-0001"
DA01 = "10.0.0.208"


def basic():
    import base64
    return {"Authorization": "Basic " + base64.b64encode(f"u:{PW}".encode()).decode()}


def page():   # a write request of the page: Basic + the CSRF header
    return dict(basic(), **{"X-AGX-CSRF": "1"})


def bearer(tok):
    return {"Authorization": "Bearer " + tok}


def mode600(p) -> bool:
    return stat.S_IMODE(os.stat(p).st_mode) == 0o600


@pytest.fixture()
def env(tmp_path):
    """Config with temporary paths; returns a factory of apps."""
    from dashboard.config import load_config

    cfg = load_config("config/templates/dashboard.yaml")
    cfg["allow_cidrs"] = cfg["allow_cidrs"] + ["10.0.0.0/24"]   # the LAN of the test boards (ops/install.sh adds it)
    cfg.update({"infer_config": "config/templates/infer.yaml",
                "model_store": str(tmp_path / "store"), "control_config": str(tmp_path / "control.yaml"),
                "control_token_file": str(tmp_path / "control.token"),
                "paired_boards_file": str(tmp_path / "paired_boards.json"),
                "link_settings_file": str(tmp_path / "link_settings.json"),
                "sources_config": str(tmp_path / "sources.yaml")})
    cfg["history"]["db"] = str(tmp_path / "h.sqlite")
    cfg["engines"]["cache"] = str(tmp_path / "ec.json")
    cfg["model_control"] = True
    (tmp_path / "sources.yaml").write_text('rk_allowed_sources: ["10.0.0.208", "10.0.0.209"]\n')

    class Env:
        path = tmp_path
        conf = cfg

        def app(self, migrate=False):
            from dashboard.app import create_app
            return create_app(cfg, env={"AGX_DASH_USER": "u", "AGX_DASH_PASSWORD": PW}, start_collectors=False,
                              migrate=migrate)

        def mode(self, m):
            (tmp_path / "control.yaml").write_text(f"control_mode: {m}\n")

        def audit(self):
            f = tmp_path / "store" / "_state" / "audit.jsonl"
            return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    return Env()


def client(app, ip=DA01):
    return TestClient(app, client=(ip, 50000))


def make_code(c) -> str:
    r = c.post("/api/pair/code", headers=page())
    assert r.status_code == 200, r.text
    d = r.json()
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", d["code"]) and d["ttl_s"] > 0
    return d["code"]


def pair(c, code, name="rk3588-da01", addrs=("10.0.0.208", "10.0.0.209")):
    return c.post("/api/pair", json={"code": code, "board_name": name, "board_addresses": list(addrs)})


# ---------------------------------------------------------------- store
def test_store_mode_600_atomic_and_hash_only(tmp_path, monkeypatch):
    s = ps.PairingStore(tmp_path / "data" / "paired_boards.json", tmp_path / "data" / "link_settings.json")
    code = s.new_code("tester")["code"]
    res = s.pair(code, "rk3588-da01", ["10.0.0.209"], "10.0.0.208")
    tok = res["token"]
    f = s.boards_path
    assert mode600(f) and mode600(str(f) + ".lock")
    text = f.read_text()
    assert tok not in text and ps.sha256_hex(tok) in text and "token" not in json.dumps(res["board"])
    d = json.loads(text)
    assert d["schema"] == "agx-paired-boards/1" and d["seq"] == 1
    b = d["boards"][0]
    assert b["id"] == "rk3588-da01" and b["addresses"] == ["10.0.0.208", "10.0.0.209"] and b["source"] == "pairing"
    assert set(b) == {"id", "name", "addresses", "token_sha256", "paired_t", "last_seen_t", "last_seen_addr", "source"}
    assert ps.board_addresses(f) == (["10.0.0.208", "10.0.0.209"], 1, None)
    assert s.check_token(tok) == {"id": "rk3588-da01", "name": "rk3588-da01"}
    assert s.check_token(tok[:-1] + ("A" if tok[-1] != "A" else "B")) is None and s.check_token("short") is None
    # atomic: a failed replace leaves the old file as it was and no tmp file
    before = f.read_bytes()

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(ps.os, "replace", boom)
    with pytest.raises(OSError):
        s.remove("rk3588-da01")
    monkeypatch.undo()
    assert f.read_bytes() == before
    assert not [p for p in f.parent.iterdir() if p.name.endswith(".tmp")]
    # the settings file: mode 600 too
    s.set_accepted("10.0.0.208")
    assert mode600(s.settings_path) and s.settings() == ({"accepted_board_address": "10.0.0.208"}, None)
    with pytest.raises(ps.PairingError) as e:
        s.set_accepted("10.0.0.300")
    assert e.value.status == 400
    # a wrong mode: no token is accepted (fail closed) and each change is refused; the file is not overwritten
    os.chmod(f, 0o644)
    assert s.check_token(tok) is None and "mode 600" in s.problem
    with pytest.raises(ps.PairingError):
        s.remove("rk3588-da01")
    assert f.read_bytes() == before and ps.board_addresses(f)[0] == []


def test_touch_new_address_and_last_seen(tmp_path):
    t = [1000.0]
    s = ps.PairingStore(tmp_path / "b.json", tmp_path / "s.json", clock=lambda: t[0])
    tok = s.pair(s.new_code("x")["code"], "board one", [], "10.0.0.208")["token"]
    seq = json.loads(s.boards_path.read_text())["seq"]
    s.touch("board-one", "10.0.0.208")       # first use: written, no seq change (same address)
    d = json.loads(s.boards_path.read_text())
    assert d["seq"] == seq and d["boards"][0]["last_seen_t"] == 1000.0
    t[0] += 5
    s.touch("board-one", "10.0.0.208")       # 5 s later: memory only
    assert json.loads(s.boards_path.read_text())["boards"][0]["last_seen_t"] == 1000.0
    assert s.boards()[0]["last_seen_t"] == 1005.0
    s.touch("board-one", "10.0.0.77")        # a new address: written at once, seq +1 (agx-infer reads it)
    d = json.loads(s.boards_path.read_text())
    assert d["seq"] == seq + 1 and d["boards"][0]["addresses"] == ["10.0.0.208", "10.0.0.77"]
    assert s.check_token(tok)["id"] == "board-one"


# ---------------------------------------------------------------- code rules
def test_code_one_use(env):
    app = env.app()
    c = client(app)
    code = make_code(c)
    assert c.get("/api/pair/info").json()["pairing_open"] is True
    r = pair(c, code.lower().replace("-", " "))      # small letters and a space are accepted
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["board_id"] == "rk3588-da01" and len(d["token"]) >= 32 and d["agx_name"]
    r = pair(c, code)
    assert r.status_code == 403 and "used already" in r.json()["reason"]
    assert c.get("/api/pair/info").json()["pairing_open"] is False
    assert c.get("/api/models/control", headers=bearer(d["token"])).status_code == 200
    # a new pairing of the same board name gives a new token; the old token stops
    r2 = pair(c, make_code(c))
    assert r2.status_code == 201
    assert c.get("/api/models/control", headers=bearer(d["token"])).status_code == 401
    assert c.get("/api/models/control", headers=bearer(r2.json()["token"])).status_code == 200


def test_code_expiry_short_ttl(env, monkeypatch):
    monkeypatch.setenv(ps.CODE_TTL_ENV, "1")
    t = [100.0]
    app = env.app()
    app.state.pairing._mono = lambda: t[0]
    c = client(app)
    code = make_code(c)
    st = c.get("/api/pair/state", headers=basic()).json()["code"]
    assert st["open"] and st["left_s"] == 1.0 and "code" not in st
    t[0] += 1.5
    r = pair(c, code)
    assert r.status_code == 403 and "expired" in r.json()["reason"]
    assert c.get("/api/pair/state", headers=basic()).json()["code"]["state"] == "expired"
    assert pair(c, "ABCD-EFGH").json()["reason"] == "the pairing code is not correct"


def test_no_code_open(env):
    c = client(env.app())
    r = pair(c, "ABCD-EFGH")
    assert r.status_code == 403 and "no pairing code is open" in r.json()["reason"]


def test_failed_try_limit_per_code_and_per_address(env):
    app = env.app()
    c = client(app)
    code = make_code(c)
    other = client(app, "10.0.0.50")
    for i in range(ps.CODE_MAX_WRONG):
        r = pair(other, "WXYZ-WXY" + "23456789"[i])
        assert r.status_code == 403
    assert "cancelled" in r.json()["reason"]
    r = pair(c, code)                                     # the right code is cancelled now
    assert r.status_code == 403 and "cancelled" in r.json()["reason"]
    # per address: FAIL_LIMIT failed tries in the window -> 429 for each request of that address
    for _ in range(auth.FAIL_LIMIT - ps.CODE_MAX_WRONG):
        assert pair(other, "WXYZ-WXYZ").status_code == 403
    r = pair(other, "WXYZ-WXYZ")
    assert r.status_code == 429
    assert other.get("/api/pair/info").status_code == 429
    assert c.get("/api/pair/info").status_code == 200         # other addresses are not blocked
    ev = [e for e in env.audit() if e["action"] == "pair"]
    assert len(ev) == ps.CODE_MAX_WRONG + 1 + auth.FAIL_LIMIT - ps.CODE_MAX_WRONG
    assert all(e["result"] == "refused" and e["source"] == "rk-console" for e in ev)


def test_ip_allowlist_still_applies(env):
    app = env.app()
    assert client(app, "8.8.8.8").get("/api/pair/info").status_code == 403
    assert pair(client(app, "8.8.8.8"), "ABCD-EFGH").status_code == 403


# ---------------------------------------------------------------- tokens
def test_removed_board_token_refused_at_once(env):
    app = env.app()
    c = client(app)
    tok = pair(c, make_code(c)).json()["token"]
    assert c.get("/api/pair/boards", headers=bearer(tok)).status_code == 200
    r = c.post("/api/pair/boards/rk3588-da01/remove", headers=page())
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["removed"] == "rk3588-da01"
    assert c.get("/api/models/control", headers=bearer(tok)).status_code == 401
    assert c.post("/api/models/rollback", headers=bearer(tok)).status_code == 401
    assert c.post("/api/pair/boards/rk3588-da01/remove", headers=page()).status_code == 404
    assert c.get("/api/pair/boards", headers=basic()).json() == []


def test_removed_board_polling_does_not_block_pairing_again(env):
    """Review C-pairing R1: the old token of a removed board (the DA01 rk console polls 3 GETs per refresh) must not
    count as failed logins: else 429 blocks POST /api/pair of the same board."""
    app = env.app()
    c = client(app)
    tok = pair(c, make_code(c)).json()["token"]
    owner = client(app, "10.0.0.50")
    assert owner.post("/api/pair/boards/rk3588-da01/remove", headers=page()).status_code == 200
    for _ in range(auth.FAIL_LIMIT + 5):
        r = c.get("/api/models/control", headers=bearer(tok))
        assert r.status_code == 401, r.text
        assert "rk3588-da01 was removed" in r.json()["reason"] and "pair the board again" in r.json()["reason"]
        assert r.headers["www-authenticate"].startswith("Bearer")
    for _ in range(auth.FAIL_LIMIT + 5):          # a token on a route without tokens: 401, not a failed login
        assert c.get("/api/health", headers=bearer(tok)).status_code == 401
    assert c.get("/api/models/control", headers=bearer("u" * 43)).json()["reason"].startswith(
        "this AGX does not know this board token")
    r = pair(c, make_code(owner))
    assert r.status_code == 201, r.text
    tok2 = r.json()["token"]
    assert c.get("/api/models/control", headers=bearer(tok2)).status_code == 200
    # pair again with the same name: the old token of that pairing gets the reason "paired again"
    r = pair(c, make_code(owner))
    assert r.status_code == 201
    assert "paired again" in c.get("/api/models/control", headers=bearer(tok2)).json()["reason"]
    # a wrong password still counts: FAIL_LIMIT of them -> 429
    bad = {"Authorization": "Basic " + __import__("base64").b64encode(b"u:wrong").decode()}
    x = client(app, "10.0.0.51")
    for _ in range(auth.FAIL_LIMIT):
        assert x.get("/api/health", headers=bad).status_code == 401
    assert x.get("/api/health", headers=bad).status_code == 429


def test_vehicle_mode_no_new_board_address(env):
    """Review C-pairing R2: in vehicle mode a token request from a new client address does not change
    paired_boards.json (the agx-infer source filter); bench mode adds it, with an audit line."""
    app = env.app()
    c = client(app)
    tok = pair(c, make_code(c)).json()["token"]
    f = env.path / "paired_boards.json"
    before = json.loads(f.read_text())
    env.mode("vehicle")
    c2 = client(app, "10.0.0.77")
    for _ in range(3):
        assert c2.get("/api/models/control", headers=bearer(tok)).status_code == 200
    d = json.loads(f.read_text())
    assert d["seq"] == before["seq"] and d["boards"][0]["addresses"] == ["10.0.0.208", "10.0.0.209"]
    assert ps.board_addresses(f)[0] == ["10.0.0.208", "10.0.0.209"]
    rows = c.get("/api/pair/boards", headers=basic()).json()
    assert rows[0]["last_seen_addr"] == "10.0.0.77"          # last seen in memory
    ev = [e for e in env.audit() if e["action"] == "pair.address_added"]
    assert len(ev) == 1 and ev[0]["result"] == "refused" and "vehicle mode" in ev[0]["reason"]
    assert ev[0]["addr"] == "10.0.0.77" and ev[0]["board_id"] == "rk3588-da01" and ev[0]["source"] == "rk-console"
    env.mode("bench")
    assert c2.get("/api/models/control", headers=bearer(tok)).status_code == 200
    d = json.loads(f.read_text())
    assert d["seq"] == before["seq"] + 1 and d["boards"][0]["addresses"][-1] == "10.0.0.77"
    ev = [e for e in env.audit() if e["action"] == "pair.address_added"]
    assert [e["result"] for e in ev] == ["refused", "ok"] and ev[1]["addr"] == "10.0.0.77"


def test_remove_last_board_address_warning_and_source_filter(env):
    """Review C-pairing R3 (C side): the removal of the last board address gives a warning, and the Settings page
    shows the source filter that agx-infer uses (contract section F allowed_sources)."""
    app = env.app()
    c = client(app)
    pair(c, make_code(c))
    pair(c, make_code(c), name="board two", addrs=("10.0.0.120",))
    r = c.post("/api/pair/boards/board-two/remove", headers=page())
    assert r.json()["warning"] is None and r.json()["addresses_left"] == ["10.0.0.208", "10.0.0.209"]
    r = c.post("/api/pair/boards/rk3588-da01/remove", headers=page())
    d = r.json()
    assert r.status_code == 200 and d["boards_left"] == 0 and d["addresses_left"] == []
    assert d["warning"] == pairing_api.NO_ADDRESS_LEFT
    ev = [e for e in env.audit() if e["action"] == "pair.remove"]
    assert ev[-1]["reason"] == pairing_api.NO_ADDRESS_LEFT and ev[-1]["addresses_left"] == []
    hub = app.state.hub
    for allowed, mode, when in (({"addresses": ["10.0.0.208"], "seq": 3, "error": None}, "only", "any"),
                                ({"addresses": [], "seq": 4, "error": None}, "any", "any"),
                                ({"addresses": [], "seq": 4, "when_empty": "none"}, "none", "none")):
        st = {"schema": "agx-infer-status/1", "allowed_sources": allowed}
        hub.infer.current = lambda st=st: (st, "RUNNING", None, 0.1)
        sf = c.get("/api/pair/state", headers=basic()).json()["source_filter"]
        assert (sf["mode"], sf["when_empty"]) == (mode, when), sf
    hub.infer.current = lambda: ({"schema": "agx-infer-status/1"}, "RUNNING", None, 0.1)    # an old agx-infer
    assert c.get("/api/pair/state", headers=basic()).json()["source_filter"]["mode"] == "unknown"
    hub.infer.current = lambda: (None, "DOWN", "agx-infer is not running", None)
    sf = c.get("/api/pair/state", headers=basic()).json()["source_filter"]
    assert sf["mode"] == "unknown" and sf["reason"] == "agx-infer is not running"


def test_token_routes_only(env):
    app = env.app()
    c = client(app)
    tok = pair(c, make_code(c)).json()["token"]
    rows = c.get("/api/pair/boards", headers=bearer(tok)).json()
    assert rows[0]["id"] == "rk3588-da01" and rows[0]["address"] == DA01
    assert rows[0]["last_seen_t"] and rows[0]["link_state"] == "NO DATA"
    for path in ("/api/pair/state", "/api/pair/settings", "/api/health"):
        assert c.get(path, headers=bearer(tok)).status_code == 401, path
    assert c.post("/api/pair/code", headers=bearer(tok)).status_code == 401
    assert c.post("/api/pair/settings", headers=bearer(tok), json={"accepted_board_address": ""}).status_code == 401
    # the page routes need the login and the CSRF header
    assert c.get("/api/pair/state").status_code == 401
    r = c.post("/api/pair/code", headers=basic())
    assert r.status_code == 403 and "X-AGX-CSRF" in r.json()["reason"]
    # the model audit user: X-Actor @ board name
    c.post("/api/models/rollback", headers=dict(bearer(tok), **{"X-Actor": "tony"}))
    ev = [e for e in env.audit() if e["action"] == "rollback"]
    assert ev[0]["source"] == "rk-console" and ev[0]["user"] == "tony@rk3588-da01"


def test_accepted_board_address(env):
    app = env.app()
    c = client(app)
    tok = pair(c, make_code(c)).json()["token"]
    r = c.post("/api/pair/settings", headers=page(), json={"accepted_board_address": "10.0.0.209"})
    assert r.status_code == 200 and r.json()["accepted_board_address"] == "10.0.0.209" and r.json()["warning"] is None
    assert mode600(env.path / "link_settings.json")
    r = c.get("/api/models/control", headers=bearer(tok))          # from .208: refused
    assert r.status_code == 403 and r.json()["reason"] == "control is accepted only from 10.0.0.209"
    assert client(app, "10.0.0.209").get("/api/models/control", headers=bearer(tok)).status_code == 200
    # pairing from another address is refused too
    code = make_code(c)
    r = pair(c, code)
    assert r.status_code == 403 and "only from 10.0.0.209" in r.json()["reason"]
    # bad value -> 400; empty -> each paired board
    r = c.post("/api/pair/settings", headers=page(), json={"accepted_board_address": "dsa01"})
    assert r.status_code == 400 and "IPv4" in r.json()["reason"]
    r = c.post("/api/pair/settings", headers=page(), json={"accepted_board_address": "10.9.9.9"})
    assert r.status_code == 200 and "no paired board" in r.json()["warning"]
    assert c.post("/api/pair/settings", headers=page(), json={"accepted_board_address": ""}).status_code == 200
    assert c.get("/api/models/control", headers=bearer(tok)).status_code == 200
    g = c.get("/api/pair/settings", headers=basic()).json()
    assert g["accepted_board_address"] == "" and g["line"] == pairing_api.ACCEPTED_LINE


def test_vehicle_mode_refusals(env):
    app = env.app()
    c = client(app)
    code = make_code(c)
    tok = pair(c, code).json()["token"]
    code2 = make_code(c)
    env.mode("vehicle")
    assert c.get("/api/pair/info").json()["control_mode"] == "vehicle"
    for r in (c.post("/api/pair/code", headers=page()),
              pair(c, code2, name="board two"),
              c.post("/api/pair/boards/rk3588-da01/remove", headers=page()),
              c.post("/api/pair/settings", headers=page(), json={"accepted_board_address": "10.0.0.208"})):
        assert r.status_code == 409 and "vehicle mode" in r.json()["reason"], r.text
    # the board token still works (reads; a model change is refused by the controller in vehicle mode)
    assert c.get("/api/models/control", headers=bearer(tok)).status_code == 200
    ev = [e for e in env.audit() if e["action"].startswith("pair") and e["result"] == "refused"]
    assert {e["action"] for e in ev} == {"pair.code", "pair", "pair.remove", "pair.settings"}
    env.mode("bench")
    assert pair(c, code2, name="board two").status_code == 201       # the code was not used by the refusal


# ---------------------------------------------------------------- migration (S6)
def test_migration_from_control_token(env):
    tok = "m" * 43
    tf = env.path / "control.token"
    tf.write_text(tok + "\n")
    os.chmod(tf, 0o600)
    dy = env.path / "dashboard.yaml"
    dy.write_text('rk_ip: "10.0.0.208"\n')
    env.conf["config_file"] = str(dy)
    app = env.app(migrate=True)
    assert not tf.exists() and mode600(env.path / "control.token.migrated")
    assert (env.path / "control.token.migrated").read_text().strip() == tok
    bf = env.path / "paired_boards.json"
    assert mode600(bf) and tok not in bf.read_text()
    d = json.loads(bf.read_text())
    b = d["boards"][0]
    assert (b["id"], b["name"], b["source"]) == ("rk3588-da01", "rk3588-da01", "migration")
    assert b["addresses"] == ["10.0.0.208", "10.0.0.209"] and b["token_sha256"] == ps.sha256_hex(tok)
    c = client(app)
    assert c.get("/api/models/control", headers=bearer(tok)).status_code == 200      # the present pair keeps working
    ev = [e for e in env.audit() if e["action"] == "pair.migrate"]
    assert len(ev) == 1 and ev[0]["result"] == "ok" and ev[0]["source"] == "controller"
    # once only: a second start does nothing (a new control.token is not used)
    tf.write_text("n" * 43)
    os.chmod(tf, 0o600)
    app2 = env.app(migrate=True)
    assert tf.exists() and json.loads(bf.read_text())["seq"] == d["seq"]
    assert client(app2).get("/api/models/control", headers=bearer("n" * 43)).status_code == 401
    # no migration in the default test start (start_collectors=False)
    bf.unlink()
    env.app()
    assert not bf.exists() and tf.exists()


def test_migration_short_token_not_used(env):
    tf = env.path / "control.token"
    tf.write_text("short\n")
    os.chmod(tf, 0o600)
    env.app(migrate=True)
    assert tf.exists() and not (env.path / "paired_boards.json").exists()
    assert [e["result"] for e in env.audit() if e["action"] == "pair.migrate"] == ["failed"]


# ---------------------------------------------------------------- link state (contract section F)
def test_link_view():
    boards = [{"id": "a", "addresses": ["10.0.0.208"]}, {"id": "b", "addresses": ["10.0.0.5"]},
              {"id": "c", "addresses": ["10.0.0.6"]}, {"id": "d", "addresses": ["10.0.0.7"]}]
    st = {"board_sources": {"10.0.0.208": {"framelink_frames_3s": 90, "framelink_last_t": 1.0, "rkinfo_last_t": None,
                                           "result_subscriber": True},
                            "10.0.0.5": {"framelink_frames_3s": 30, "result_subscriber": False},
                            "10.0.0.6": {"framelink_frames_3s": 0, "result_subscriber": False}},
          "result_subscribers": {"count": 3, "addresses": ["10.0.0.208", "10.0.0.6", "10.0.0.99"]}}
    rows, other = pairing_api.link_view([dict(b) for b in boards], st, None)
    assert [r["link_state"] for r in rows] == ["UP", "frames only", "results only", "DOWN"]
    assert other == {"available": True, "reason": None, "count": 1, "addresses": ["10.0.0.99"]}
    rows, other = pairing_api.link_view([dict(b) for b in boards], {"node": {}}, None)     # an old agx-infer
    assert {r["link_state"] for r in rows} == {"NO DATA"} and other["count"] is None and not other["available"]
    rows, other = pairing_api.link_view([dict(b) for b in boards], None, "agx-infer is not running")
    assert rows[0]["link_detail"] == "agx-infer is not running"


def test_state_uses_the_infer_status(env):
    app = env.app()
    c = client(app)
    pair(c, make_code(c))
    hub = app.state.hub
    st = {"schema": "agx-infer-status/1", "t": 1.0, "node": {"state": "RUNNING"},
          "board_sources": {DA01: {"framelink_frames_3s": 90, "result_subscriber": True}},
          "result_subscribers": {"count": 2, "addresses": [DA01, "10.0.0.99"]}}
    hub.infer.current = lambda: (st, "RUNNING", None, 0.1)
    d = c.get("/api/pair/state", headers=basic()).json()
    assert d["boards"][0]["link_state"] == "UP" and d["other_subscribers"]["count"] == 1
    assert d["unit"]["ports"]["results"] == 5560 and d["unit"]["ports"]["status"] == 5561
    assert d["unit"]["ports"]["rkinfo"] == 5564 and d["unit"]["ports"]["video"][0] == 6000
    assert d["accepted_line"] == pairing_api.ACCEPTED_LINE


# ---------------------------------------------------------------- no secret in logs, audit or GET answers
def test_no_secret_in_logs_audit_or_get(env, caplog):
    caplog.set_level(logging.DEBUG)
    app = env.app()
    c = client(app)
    code = make_code(c)
    tok = pair(c, code).json()["token"]
    c.get("/api/models/control", headers=bearer(tok))
    pair(c, code)                                               # a used code: refused, logged and audited
    secrets_ = [tok, code, code.replace("-", ""), ps.sha256_hex(tok), ps.sha256_hex(code.replace("-", ""))]
    gets = [c.get("/api/pair/info").text, c.get("/api/pair/boards", headers=basic()).text,
            c.get("/api/pair/boards", headers=bearer(tok)).text, c.get("/api/pair/state", headers=basic()).text,
            c.get("/api/pair/settings", headers=basic()).text, c.get("/api/models/events", headers=basic()).text]
    audit_text = (env.path / "store" / "_state" / "audit.jsonl").read_text()
    for s in secrets_:
        assert s not in caplog.text
        assert s not in audit_text
        for g in gets:
            assert s not in g
    assert "token_sha256" not in "".join(gets)
    info = c.get("/api/pair/info").json()
    assert info["agx"] is True and set(info) >= {"name", "schema", "control_mode", "pairing_open", "ports"}


# ---------------------------------------------------------------- the UI POST rule (the page part)
def test_ui_rk_link_part_and_post_rule():
    static = ROOT / "dashboard" / "static"
    page_ = (static / "index.html").read_text()
    app_js = (static / "app.js").read_text()
    for i in ("c-pair", "pr-name", "pr-addrs", "pr-p-video", "pr-p-results", "pr-p-status", "pr-p-rkinfo", "pr-p-api",
              "pr-code-btn", "pr-code", "pr-code-left", "pr-boards", "pr-others", "pr-filter", "pr-acc", "pr-acc-save",
              "pr-dlg"):
        assert page_.count(f'id="{i}"') == 1, i
    assert ">Make pairing code<" in page_
    assert pairing_api.ACCEPTED_LINE in page_
    # each write goes through postWrite() to /api/models/ or /api/pair/; the refusal reason is shown as it is
    calls = re.findall(r"postWrite\(\"(/api/[^\"]+)\"", app_js)
    assert calls and all(p.startswith(("/api/models/", "/api/pair/")) for p in calls)
    assert app_js.count("refusalText(res)") >= 4
    # the code comes only from the answer of this page's own POST; the poll reads /api/pair/state (no code there)
    assert app_js.count("pairCode = { code: res.doc.code") == 1
    assert 'getJSON("/api/pair/state")' in app_js
    # the Remove dialog warns when the removal leaves no board address (agx-infer source filter)
    assert 'id: "pr-dlg-last"' in app_js and "addressesLeft(b)" in app_js and "d.source_filter" in app_js
