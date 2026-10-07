"""Tests for the final review fixes on the dashboard side (fixer 2).

M2  narrow IP allowlist (same list in config/dashboard.yaml, dashboard/auth.py, dashboard/config.py)
L1  failed-login limit per IP: 429 at once, no sleep, eviction of the oldest entries only
M13 / L27  model last_error, errors_total, queue_ms (and auto_restarts) and camera last_error
M14 agx-sim in log_units; system unit logs (journalctl -u) when the system unit is active
M15 / L3  MQTT: disabled by default, mocked paho client, refuse credentials without TLS, R11 note
L4  missing or non-bool "simulated" flag -> SIMULATED (R13 fail-safe)
L5  every /api/health object with simulated true has "label": "SIMULATED"
L9  legacy DriverGuard reference copies are found by the old-process scan

Run: .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_final_fixes_dashboard.py
No server, no network, no real MQTT broker. The legacy scripts are never run.
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
import types
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard import auth  # noqa: E402

EXPECTED_ALLOW = ["127.0.0.0/8", "10.0.0.0/24", "10.42.0.0/30", "100.64.0.0/10"]
PW = "test-only-pw"


# ---------------------------------------------------------------- helpers
def _app(tmp_path=None, cfg_over=None, start=False):
    from dashboard.app import create_app
    from dashboard.config import load_config

    cfg = load_config("config/dashboard.yaml")
    if tmp_path is not None:
        cfg["history"]["db"] = str(tmp_path / "h.sqlite")
        cfg["engines"]["cache"] = str(tmp_path / "ec.json")
        cfg["engines"]["scan_dirs"] = [str(tmp_path)]
    cfg["model_control"] = False   # these tests do not test the model controller (tests/test_model_store.py)
    cfg.update(cfg_over or {})
    return create_app(cfg, env={"AGX_DASH_USER": "u", "AGX_DASH_PASSWORD": PW}, start_collectors=start)


def _client_with(st: dict):
    from dashboard.collectors.infer_status import InferStatusClient

    c = InferStatusClient("tcp://127.0.0.1:1")
    c._status, c._status_rx, c._status_rx_mono = st, time.time(), time.monotonic()
    return c


class _StubScanner:
    def facts_note(self, p):
        return None, None

    def found_notes(self):
        return []

    def status(self):
        return {}


def _status(node: dict | None, cams: list, models: list) -> dict:
    st = {"schema": "agx-infer-status/1", "t": time.time(), "cameras": cams, "models": models}
    if node is not None:
        st["node"] = node
    return st


# ---------------------------------------------------------------- M2
def test_m2_allowlist_same_in_all_three_places():
    from dashboard.config import DEFAULTS

    y = yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text())
    assert y["allow_cidrs"] == EXPECTED_ALLOW
    assert list(auth.DEFAULT_ALLOW) == EXPECTED_ALLOW
    assert DEFAULTS["allow_cidrs"] == EXPECTED_ALLOW
    for ok in ("127.0.0.1", "10.0.0.130", "10.0.0.255", "10.42.0.1", "10.42.0.2", "100.64.0.180",
               "100.127.255.254", "::ffff:10.0.0.130"):
        assert auth.ip_allowed(ok), ok
    for bad in ("172.17.0.2", "172.16.0.1", "192.168.1.5", "169.254.10.1", "10.0.1.1", "10.1.0.1",
                "10.42.0.4", "::1", "fe80::1", "fd00::1", "8.8.8.8"):
        assert not auth.ip_allowed(bad), bad


def test_m2_docker_bridge_gets_403(tmp_path):
    app = _app(tmp_path)

    async def go(ip):
        tr = httpx.ASGITransport(app=app, client=(ip, 40000))
        async with httpx.AsyncClient(transport=tr, base_url="http://agx02") as c:
            return (await c.get("/api/services/logs?unit=nope", auth=("u", PW))).status_code

    assert asyncio.run(go("172.17.0.2")) == 403
    assert asyncio.run(go("192.168.1.5")) == 403
    assert asyncio.run(go("10.0.0.130")) == 400   # allowed, login OK, unit not in whitelist


# ---------------------------------------------------------------- L1
def _guard():
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return auth.GuardMiddleware(inner, "u", PW, EXPECTED_ALLOW)


def _req(g, ip, pw):
    async def go():
        tr = httpx.ASGITransport(app=g, client=(ip, 40000))
        async with httpx.AsyncClient(transport=tr, base_url="http://agx02") as c:
            return await c.get("/", auth=("u", pw) if pw is not None else None)
    return asyncio.run(go())


def test_l1_429_at_once_after_limit(monkeypatch):
    slept = []

    async def no_sleep(*a, **k):  # the guard must never sleep
        slept.append(a)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    g = _guard()
    ip = "10.0.0.50"
    codes = [_req(g, ip, "bad").status_code for _ in range(auth.FAIL_LIMIT)]
    assert codes == [401] * auth.FAIL_LIMIT
    t0 = time.monotonic()
    r = _req(g, ip, "bad")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    r = _req(g, ip, PW)  # also the correct password: the block is not a password oracle
    assert r.status_code == 429
    r = _req(g, ip, None)
    assert r.status_code == 429
    assert time.monotonic() - t0 < 1.0 and not slept
    # other addresses are not blocked
    assert _req(g, "10.0.0.51", PW).status_code == 200
    assert _req(g, "100.64.0.180", "bad").status_code == 401


def test_l1_block_ends_after_window(monkeypatch):
    g = _guard()
    ip = "10.0.0.60"
    for _ in range(auth.FAIL_LIMIT):
        _req(g, ip, "bad")
    assert _req(g, ip, PW).status_code == 429
    real = time.monotonic
    monkeypatch.setattr(auth.time, "monotonic", lambda: real() + auth.FAIL_WINDOW_S + 1)
    assert _req(g, ip, PW).status_code == 200
    assert ip not in g._fails  # a good login clears the count


def test_l1_parallel_requests_do_not_get_around_the_limit():
    g = _guard()
    ip = "10.0.0.70"

    async def go():
        tr = httpx.ASGITransport(app=g, client=(ip, 40000))
        async with httpx.AsyncClient(transport=tr, base_url="http://agx02") as c:
            rs = await asyncio.gather(*[c.get("/", auth=("u", f"bad{i}")) for i in range(40)])
            return [r.status_code for r in rs]

    codes = asyncio.run(go())
    assert codes.count(401) == auth.FAIL_LIMIT and codes.count(429) == 40 - auth.FAIL_LIMIT


def test_l1_eviction_removes_only_the_oldest(monkeypatch):
    monkeypatch.setattr(auth, "FAIL_MAX_IPS", 5)
    g = _guard()
    blocked = "10.0.0.80"
    for i in range(3):
        _req(g, f"10.0.0.{10 + i}", "bad")       # 3 old entries
    for _ in range(auth.FAIL_LIMIT):
        _req(g, blocked, "bad")                  # newest entry, blocked
    for i in range(3):
        _req(g, f"100.64.0.{10 + i}", "bad")     # 3 newer entries -> 7 > 5: the 2 oldest go
    assert len(g._fails) == 5
    assert "10.0.0.10" not in g._fails and "10.0.0.11" not in g._fails
    assert "10.0.0.12" in g._fails and blocked in g._fails
    assert _req(g, blocked, PW).status_code == 429  # the block was not cleared by the eviction
    src = (ROOT / "dashboard" / "auth.py").read_text()
    assert "_fails.clear()" not in src and "asyncio.sleep" not in src


# ---------------------------------------------------------------- M13 / L27
def test_m13_model_error_fields_and_camera_last_error():
    from dashboard.infer_views import InferViews

    now = time.time()
    q = {"p50": 1.5, "p95": 3.0, "p99": 4.0}
    models = [{"name": "a", "state": "RUNNING", "last_error": "cuda: out of memory", "last_error_t": now - 5,
               "errors_total": 3, "queue_ms": q, "auto_restarts": 2},
              {"name": "b", "state": "RUNNING"},                                   # fields not sent
              {"name": "c", "state": "RUNNING", "last_error": 7, "errors_total": "x", "queue_ms": 5}]
    cams = [{"cam": 0, "simulated": True, "last_frame_t": now - 0.03, "last_error": "short datagram"},
            {"cam": 1, "simulated": True, "last_frame_t": now - 0.03, "last_error": ""}]
    v = InferViews(_client_with(_status({"simulated": True}, cams, models)), _StubScanner(), None, None)
    rows = {r["name"]: r for r in v.models_doc()["models"]}
    a = rows["a"]
    assert a["last_error"] == "cuda: out of memory" and a["errors_total"] == 3 and a["auto_restarts"] == 2
    assert abs(a["last_error_t"] - (now - 5)) < 1e-6 and a["queue_ms"] == q
    for name in ("b", "c"):  # missing or wrong type: null, no fake values
        assert all(rows[name][k] is None for k in
                   ("last_error", "last_error_t", "errors_total", "queue_ms", "auto_restarts")), rows[name]
    cd = v.cameras_doc()["cameras"]
    assert cd[0]["last_error"] == "short datagram" and cd[1]["last_error"] is None
    js = (ROOT / "dashboard" / "static" / "app.js").read_text()
    assert "m.last_error" in js and "m.queue_ms" in js and "m.errors_total" in js and "c.last_error" in js


# ---------------------------------------------------------------- M14
def test_m14_log_units_and_system_or_user_journal(monkeypatch):
    from dashboard.collectors import services
    from dashboard.config import DEFAULTS, load_config

    cfg = load_config("config/dashboard.yaml")
    assert "agx-sim" in cfg["services"]["log_units"] and "agx-sim" in DEFAULTS["services"]["log_units"]
    assert 'value="agx-sim"' in (ROOT / "dashboard" / "static" / "index.html").read_text()
    calls = []
    state = {"active": True}

    def fake_run(argv, timeout=5.0):
        calls.append(list(argv))
        if argv[:2] == ["systemctl", "is-active"]:
            return (0, "active\n", "") if state["active"] else (3, "inactive\n", "")
        return 0, "2026-10-05T23:00:00 agx02 x[1]: line\n", ""
    monkeypatch.setattr(services, "_run", fake_run)
    sc = services.ServicesCollector(cfg)
    d = sc.logs("agx-sim", 10)
    assert d["source"] == "system" and calls[-1][:3] == ["journalctl", "-u", "agx-sim"]
    assert calls[-2] == ["systemctl", "is-active", "--", "agx-sim"]
    state["active"] = False
    d = sc.logs("agx-sim", 10)
    assert d["source"] == "user" and calls[-1][:2] == ["journalctl", "--user-unit=agx-sim"]
    assert d["lines"] == ["2026-10-05T23:00:00 agx02 x[1]: line"]
    with pytest.raises(ValueError):
        sc.logs("ssh", 10)


# ---------------------------------------------------------------- M15 / L3
_MQTT_KEYS = ("AGX_MQTT_ENABLED", "AGX_MQTT_HOST", "AGX_MQTT_PORT", "AGX_MQTT_USER", "AGX_MQTT_PASSWORD",
              "AGX_MQTT_TOPIC_PREFIX", "AGX_MQTT_TLS")


@pytest.fixture
def clean_mqtt_env(monkeypatch):
    for k in _MQTT_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_m15_mqtt_disabled_by_default(monkeypatch, clean_mqtt_env):
    from dashboard import mqtt_pub

    made = []
    real_socket = socket.socket

    class CountSocket(real_socket):
        def __init__(self, *a, **k):
            made.append(a)
            super().__init__(*a, **k)
    monkeypatch.setattr(socket, "socket", CountSocket)
    for k in [m for m in sys.modules if m == "paho" or m.startswith("paho.")]:
        monkeypatch.delitem(sys.modules, k)
    env_example = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env_example[k] = v
    for env in ({}, env_example, {"AGX_MQTT_ENABLED": "1"}, {"AGX_MQTT_ENABLED": "0", "AGX_MQTT_HOST": "h"}):
        assert mqtt_pub.start_mqtt(env, lambda: {}) is None
    assert made == [] and "paho.mqtt.client" not in sys.modules  # no socket, paho not imported
    note = "Enabling MQTT sends data off this machine: owner approval needed (rule R11)"
    assert note in (ROOT / ".env.example").read_text()


class _FakePaho:
    """Stand-in for paho.mqtt.client: records the calls, opens no socket."""

    def __init__(self):
        self.clients = []
        fake = self

        class CallbackAPIVersion:
            VERSION2 = 2

        class Client:
            def __init__(self, *a, **k):
                self.args, self.kwargs = a, k
                self.published, self.user, self.tls, self.connected_to = [], None, False, None
                fake.clients.append(self)

            def username_pw_set(self, u, p=None):
                self.user = u

            def tls_set(self, **k):
                self.tls = True

            def reconnect_delay_set(self, **k):
                pass

            def connect_async(self, host, port, keepalive=60):
                self.connected_to = (host, port)

            def loop_start(self):
                pass

            def loop_stop(self):
                pass

            def disconnect(self):
                pass

            def is_connected(self):
                return True

            def publish(self, topic, payload, qos=0, retain=False):
                self.published.append((time.monotonic(), topic, payload, qos, retain))

        self.mod = types.ModuleType("paho.mqtt.client")
        self.mod.Client = Client
        self.mod.CallbackAPIVersion = CallbackAPIVersion

    def install(self, monkeypatch):
        pkg = types.ModuleType("paho")
        sub = types.ModuleType("paho.mqtt")
        pkg.mqtt = sub
        sub.client = self.mod
        monkeypatch.setitem(sys.modules, "paho", pkg)
        monkeypatch.setitem(sys.modules, "paho.mqtt", sub)
        monkeypatch.setitem(sys.modules, "paho.mqtt.client", self.mod)


def test_m15_mqtt_mocked_topic_interval_simulated(monkeypatch, clean_mqtt_env):
    from dashboard import mqtt_pub

    fp = _FakePaho()
    fp.install(monkeypatch)
    health = {"schema": "agx-health/1", "simulated": True, "label": "SIMULATED"}
    env = {"AGX_MQTT_ENABLED": "1", "AGX_MQTT_HOST": "broker.test", "AGX_MQTT_TOPIC_PREFIX": "/fleet/"}
    pub = mqtt_pub.start_mqtt(env, lambda: dict(health), interval_s=0.1)
    try:
        assert pub is not None and len(fp.clients) == 1
        cl = fp.clients[0]
        assert cl.connected_to == ("broker.test", 1883) and cl.user is None and cl.tls is False
        deadline = time.time() + 3
        while time.time() < deadline and len(cl.published) < 4:
            time.sleep(0.02)
    finally:
        pub.stop()
    msgs = list(cl.published)
    assert len(msgs) >= 4
    assert {m[1] for m in msgs} == {"fleet/agx02/health"}
    gaps = [b[0] - a[0] for a, b in zip(msgs, msgs[1:])]
    assert all(0.08 <= gp <= 0.5 for gp in gaps), gaps
    for m in msgs:
        d = json.loads(m[2])
        assert "simulated" in d and d["simulated"] is True and d["label"] == "SIMULATED"
        assert m[3] == 0 and m[4] is False
    assert pub.interval == 0.1
    cfg = yaml.safe_load((ROOT / "config" / "dashboard.yaml").read_text())
    assert cfg["mqtt_interval_s"] == 5  # the dashboard passes this interval to start_mqtt


def test_l3_mqtt_refuses_credentials_without_tls(monkeypatch, clean_mqtt_env):
    from dashboard import mqtt_pub

    fp = _FakePaho()
    fp.install(monkeypatch)
    for tls in ("", "0", "no"):
        env = {"AGX_MQTT_ENABLED": "1", "AGX_MQTT_HOST": "broker.test", "AGX_MQTT_USER": "agx",
               "AGX_MQTT_PASSWORD": "pw-test", "AGX_MQTT_TLS": tls}
        assert mqtt_pub.start_mqtt(env, lambda: {}) is None
        with pytest.raises(ValueError):
            mqtt_pub.MqttPublisher(env, lambda: {})
    assert fp.clients == []  # no client made
    env["AGX_MQTT_TLS"] = "1"
    pub = mqtt_pub.start_mqtt(env, lambda: {}, interval_s=60)
    try:
        assert pub is not None and fp.clients[0].user == "agx" and fp.clients[0].tls is True
        assert fp.clients[0].connected_to == ("broker.test", 8883)
    finally:
        pub.stop()


# ---------------------------------------------------------------- L4
@pytest.mark.parametrize("flag", ["missing", "yes", 1, None])
def test_l4_missing_or_non_bool_flag_is_simulated(flag):
    from dashboard.infer_views import InferViews

    now = time.time()
    node = {"state": "RUNNING"}
    cam = {"cam": 0, "last_frame_t": now - 0.03, "fps": 30.0}
    model = {"name": "m", "state": "RUNNING", "fps": 10.0, "lat_ms": {"total": {"p50": 5.0}}}
    if flag != "missing":
        node["simulated"] = flag
        cam["simulated"] = flag
    c = _client_with(_status(node, [cam], [model]))
    v = InferViews(c, _StubScanner(), None, None)
    cd = v.cameras_doc()
    assert cd["cameras"][0]["state"] == "SIMULATED" and cd["cameras"][0]["label"] == "SIMULATED"
    md = v.models_doc()
    assert md["models"][0]["simulated"] is True and md["models"][0]["label"] == "SIMULATED"
    s = c.summary()["infer"]
    assert s["simulated"] is True and s["label"] == "SIMULATED"
    assert s["cameras_summary"]["per_cam"][0]["simulated"] is True
    assert s["models_summary"]["per_model"][0]["simulated"] is True
    assert c.metrics() == {"sim_fps.cam0": 30.0, "sim_lat_p50.m": 5.0}
    assert c.link_part()["label"] == "SIMULATED"


def test_l4_no_node_object_is_simulated_and_explicit_false_is_live():
    from dashboard.infer_views import InferViews

    now = time.time()
    model = {"name": "m", "state": "RUNNING", "lat_ms": {"total": {"p50": 5.0}}}
    c = _client_with(_status(None, [{"cam": 0, "simulated": False, "last_frame_t": now - 0.03, "fps": 30.0},
                                    {"cam": 1, "last_frame_t": now - 0.03, "fps": 30.0}], [model]))
    v = InferViews(c, _StubScanner(), None, None)
    cams = v.cameras_doc()["cameras"]
    assert (cams[0]["state"], cams[1]["state"]) == ("OK", "SIMULATED")  # own flag false stays live
    assert v.models_doc()["models"][0]["label"] == "SIMULATED"           # no node flag: simulated
    # live: all flags are explicit false -> no SIMULATED label
    c = _client_with(_status({"simulated": False}, [{"cam": 0, "simulated": False, "last_frame_t": now - 0.03,
                                                      "fps": 30.0}], [model]))
    v = InferViews(c, _StubScanner(), None, None)
    assert v.cameras_doc()["cameras"][0]["state"] == "OK"
    assert v.models_doc()["models"][0]["simulated"] is False
    assert c.metrics() == {"fps.cam0": 30.0, "lat_p50.m": 5.0}


# ---------------------------------------------------------------- L5
def _walk(x, path="$"):
    if isinstance(x, dict):
        yield path, x
        for k, v in x.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")


def test_l5_every_simulated_health_object_has_label(tmp_path):
    app = _app(tmp_path)
    hub = app.state.hub
    now = time.time()
    cams = [{"cam": n, "simulated": True, "last_frame_t": now - 0.03, "fps": 30.0, "state": "SIMULATED"}
            for n in range(6)]
    models = [{"name": "m", "state": "RUNNING", "fps": 10.0, "lat_ms": {"total": {"p50": 5.0}}}]
    st = _status({"state": "RUNNING", "simulated": True, "errors": []}, cams, models)
    hub.infer._status, hub.infer._status_rx, hub.infer._status_rx_mono = st, now, time.monotonic()
    doc = hub.health_doc()
    assert doc["simulated"] is True and doc["label"] == "SIMULATED"
    sims = [(p, d) for p, d in _walk(doc) if d.get("simulated") is True]
    assert len(sims) >= 10, [p for p, _ in sims]
    missing = [p for p, d in sims if d.get("label") != "SIMULATED"]
    assert not missing, missing
    for key in ("cameras_summary", "models_summary"):
        assert doc["infer"][key]["label"] == "SIMULATED", key

    from dashboard.app import label_simulated
    d = label_simulated({"a": [{"simulated": True}, {"simulated": False}], "simulated": True, "label": None})
    assert d["label"] == "SIMULATED" and d["a"][0]["label"] == "SIMULATED" and "label" not in d["a"][1]


# ---------------------------------------------------------------- L9
def test_l9_legacy_driverguard_scripts_are_found():
    from dashboard.collectors.old_procs import LEGACY_SCRIPTS, match

    base = str(ROOT / "infer" / "models" / "legacy" / "driverguard")
    for n in LEGACY_SCRIPTS:
        want = "legacy/driverguard/" + n
        assert match(["python3", f"{base}/{n}"], "/") == want
        assert match(["python3", f"infer/models/legacy/driverguard/{n}"], str(ROOT)) == want
        assert match(["python3", n, "--cam", "0"], base) == want                  # run in its directory
        assert match(["python3", "-m", "infer.models.legacy.driverguard." + n[:-3]], "/") == \
            "infer.models.legacy.driverguard." + n[:-3]
    # not legacy: the new runner, the dashboard, a same-name file in another directory
    assert match(["python3", str(ROOT / "infer" / "runner.py")], "/") is None
    assert match(["python3", "runner.py"], str(ROOT / "infer")) is None
    assert match(["python3", "-m", "infer.runner"], "/") is None
    assert match(["python3", "-m", "dashboard.main"], "/") is None
    assert match(["python3", "/tmp/camera_reader.py"], "/") is None


def test_roles_fallback_uses_role_rk_in_rk_mode(tmp_path):
    """J1: dashboard roles() follows the same rule as infer/ingest (role_rk only when mode is rk)."""
    import os as _os

    from dashboard.infer_views import InferViews

    cams = ("cameras:\n"
            "  - {cam: 0, role: front, role_rk: front, port: 6000}\n"
            "  - {cam: 1, role: right, role_rk: \"fisheye-190 CAM2 (role unconfirmed)\", port: 6001}\n"
            "  - {cam: 2, role: left, port: 6002}\n")
    y = tmp_path / "sources.yaml"
    y.write_text("mode: rk\n" + cams)
    v = InferViews(_client_with(_status({"simulated": False}, [], [])), _StubScanner(), None, str(y))
    r = v.roles()
    assert r[1]["role"] == "fisheye-190 CAM2 (role unconfirmed)" and r[0]["role"] == "front"
    assert r[2]["role"] == "left" and r[1]["port"] == 6001
    st = _os.stat(y)
    y.write_text("mode: sim\n" + cams)
    _os.utime(y, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))   # new mtime: the file is read again
    assert v.roles()[1]["role"] == "right"
