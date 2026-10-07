"""Model controller HTTP API on the dashboard port: routes and the two kinds of auth (dashboard/control_api.py,
dashboard/auth.py TokenFile). In-process app, a temporary store and a temporary token file: never the real ones."""
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
    cfg = load_config("config/dashboard.yaml")
    cfg.update({"model_store": str(tmp_path / "store"), "control_token_file": str(tok),
                "control_config": str(tmp_path / "control.yaml")})
    cfg["history"]["db"] = str(tmp_path / "h.sqlite")
    cfg["engines"]["cache"] = str(tmp_path / "ec.json")
    app = create_app(cfg, env={"AGX_DASH_USER": "u", "AGX_DASH_PASSWORD": PW}, start_collectors=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as c:   # the IP allowlist accepts loopback
        c.tok = tok
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
    assert client.get("/api/models/catalog", headers={"Authorization": "Bearer " + "x" * 43}).status_code == 401
    assert client.get("/api/models/catalog").status_code == 401
    assert client.get("/api/models/catalog", headers=basic(p="wrong")).status_code == 401


def test_token_file_must_be_mode_600(client):
    os.chmod(client.tok, 0o644)
    assert client.get("/api/models/catalog", headers={"Authorization": "Bearer " + TOKEN}).status_code == 401
    os.chmod(client.tok, 0o600)
    assert client.get("/api/models/catalog", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
    client.tok.write_text("short\n")                                           # fewer than 32 characters: off
    assert client.get("/api/models/catalog", headers={"Authorization": "Bearer short"}).status_code == 401
