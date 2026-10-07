"""Model controller HTTP API on the dashboard port: routes and the two kinds of auth (dashboard/control_api.py,
dashboard/auth.py: Basic, and the board token of a paired board, common/pairing_store.py). In-process app, a temporary
store and a temporary token file (moved to a temporary paired_boards.json by the start-up migration): never the real
ones."""
import base64
import os

import pytest
from fastapi.testclient import TestClient

PW = "api-test-pw-0001"
TOKEN = "t" * 43


def basic(u="u", p=PW):
    return {"Authorization": "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()}


@pytest.fixture()
def client(tmp_path):
    from dashboard.app import create_app
    from dashboard.config import load_config

    tok = tmp_path / "control.token"
    tok.write_text(TOKEN + "\n")
    os.chmod(tok, 0o600)
    cfg = load_config("config/templates/dashboard.yaml")
    cfg.update({"model_store": str(tmp_path / "store"), "control_token_file": str(tok),
                "control_config": str(tmp_path / "control.yaml"),
                "paired_boards_file": str(tmp_path / "paired_boards.json"),
                "link_settings_file": str(tmp_path / "link_settings.json")})
    cfg["history"]["db"] = str(tmp_path / "h.sqlite")
    cfg["engines"]["cache"] = str(tmp_path / "ec.json")
    app = create_app(cfg, env={"AGX_DASH_USER": "u", "AGX_DASH_PASSWORD": PW}, start_collectors=False,
                     migrate=True)   # the old token file becomes the paired board rk3588-da01
    with TestClient(app, client=("127.0.0.1", 50000)) as c:   # the IP allowlist accepts loopback
        c.tok = tok
        c.boards = tmp_path / "paired_boards.json"
        yield c


def test_read_routes_with_basic(client):
    for path in ("/api/models/catalog", "/api/models/control", "/api/models/events"):
        r = client.get(path, headers=basic())
        assert r.status_code == 200, (path, r.text)
        assert r.headers["cache-control"] == "no-store"
    d = client.get("/api/models/catalog", headers=basic()).json()
    assert d["entries"] == [] and d["control_mode"] == "bench" and "no control" not in str(d["control_problem"])
    assert client.get("/api/models/control", headers=basic()).json()["change_in_progress"] is None


def test_token_only_on_model_paths(client):
    tok = {"Authorization": "Bearer " + TOKEN}
    assert client.get("/api/models/catalog", headers=tok).status_code == 200
    assert client.get("/api/health", headers=tok).status_code == 401          # the token is for /api/models/ only
    assert client.get("/api/power/now", headers=tok).status_code == 200       # + GET /api/power/now (power log)
    assert client.get("/api/power", headers=tok).status_code == 401
    assert client.get("/api/power/samples", headers=tok).status_code == 401
    assert client.get("/api/power/now").status_code == 401
    assert client.get("/api/models/catalog", headers={"Authorization": "Bearer " + "x" * 43}).status_code == 401
    assert client.get("/api/models/catalog").status_code == 401
    assert client.get("/api/models/catalog", headers=basic(p="wrong")).status_code == 401


def test_paired_boards_file_must_be_mode_600(client):
    assert not client.tok.exists() and client.tok.with_name("control.token.migrated").exists()
    assert oct(os.stat(client.boards).st_mode & 0o777) == "0o600"
    os.chmod(client.boards, 0o644)                                             # a wrong mode turns all tokens off
    assert client.get("/api/models/catalog", headers={"Authorization": "Bearer " + TOKEN}).status_code == 401
    os.chmod(client.boards, 0o600)
    assert client.get("/api/models/catalog", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
    assert client.get("/api/models/catalog", headers={"Authorization": "Bearer short"}).status_code == 401


def test_write_routes_csrf_and_actor(client, tmp_path):
    from controller import audit

    # a page request (Basic) without the CSRF header is refused before the controller sees it
    r = client.post("/api/models/x/1/activate", headers=basic(), json={})
    assert r.status_code == 403 and "X-AGX-CSRF" in r.json()["reason"]
    r = client.post("/api/models/x/1/activate", headers=dict(basic(), **{"X-AGX-CSRF": "1", "Origin": "http://evil"}))
    assert r.status_code == 403 and "another site" in r.json()["reason"]
    r = client.post("/api/models/x/1/activate", headers=dict(basic(), **{"X-AGX-CSRF": "1"}), json={"cameras": [0]})
    assert r.status_code == 404 and r.json() == {"ok": False, "action": "activate", "model": "x@1",
                                                 "reason": "no model x@1 in the store"}
    # the rk console server (token) needs no CSRF header; its user comes in X-Actor, the board name is added
    tok = {"Authorization": "Bearer " + TOKEN, "X-Actor": "tony"}
    r = client.post("/api/models/rollback", headers=tok)
    assert r.status_code == 409 and r.json()["reason"] == "no last good set is stored yet"
    assert client.post("/api/models/x/1/explode", headers=tok).status_code == 404
    assert client.post("/api/models/x/1/build", headers=tok, content=b"[1]").status_code == 400
    # (pair.address_added: the migrated board had no address; its first token request added it, docs/PAIRING_API.md)
    ev = [e for e in audit.read(tmp_path / "store" / "_state") if not e["action"].startswith("pair.")]
    assert [(e["action"], e["source"], e["user"], e["result"]) for e in ev[:2]] == [
        ("rollback", "rk-console", "tony@rk3588-da01", "refused"), ("activate", "agx-dashboard", "u", "refused")]
    # a GET of /api/models (the old page route) stays read-only
    assert client.post("/api/models", headers=tok).status_code in (401, 405)
