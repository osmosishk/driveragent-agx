"""Dashboard tests. Run: .venv/bin/python -m pytest -q tests/test_dashboard.py

Starts the dashboard as a subprocess on a free test port (18700+), with its port file and
history db in tests/out/ (never the real data/ files). The password is read from .env in this
process and is never printed.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.env import load_env  # noqa: E402
from dashboard.auth import ip_allowed  # noqa: E402

# AGX_DASH_TEST_OUT / AGX_DASH_TEST_PORT_MIN / AGX_DASH_TEST_PORT_MAX override the defaults
# (tests/out and 18700-18799), e.g. to run next to other test instances.
OUT = Path(os.environ.get("AGX_DASH_TEST_OUT") or (ROOT / "tests" / "out"))
PORT_MIN = int(os.environ.get("AGX_DASH_TEST_PORT_MIN") or 18700)
PORT_MAX = int(os.environ.get("AGX_DASH_TEST_PORT_MAX") or 18799)
NODE = "testnode"   # config node_name of the test server: auth realm "<node>-dashboard"


def _free_port(start=None, end=None) -> int:
    start = PORT_MIN if start is None else start
    end = PORT_MAX if end is None else end
    for p in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"no free test port in {start}-{end}")


class _Creds(tuple):
    """(user, password) for httpx; repr() hides the password in test reports."""

    def __repr__(self):
        return f"('{self[0]}', '<hidden>')"


@pytest.fixture(scope="module")
def creds():
    env = load_env(ROOT / ".env")
    pw = env.get("AGX_DASH_PASSWORD", "")
    if not pw:
        pytest.skip("AGX_DASH_PASSWORD not set in .env")
    return _Creds((env.get("AGX_DASH_USER") or "agx", pw))


@pytest.fixture(scope="module")
def server(creds):
    OUT.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    log = open(OUT / "dashboard_test.log", "w")
    # the template config (a fresh clone has no config/dashboard.yaml), the pairing files in tests/out: the start-up
    # pairing migration must never move the real data/control.token or write the real data/paired_boards.json
    # (docs/PAIRING_API.md)
    import yaml
    with open(ROOT / "config" / "templates" / "dashboard.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.update({"node_name": NODE, "control_token_file": str(OUT / "control_test.token"),
                "paired_boards_file": str(OUT / "paired_boards_test.json"),
                "link_settings_file": str(OUT / "link_settings_test.json"),
                "power_log": {"db": str(OUT / "power_test.sqlite"), "enabled": True}})   # never the real power log
    cfg_path = OUT / "dashboard_test.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    proc = subprocess.Popen(
        [sys.executable, "-m", "dashboard.main", "--config", str(cfg_path),
         "--port", str(port), "--port-file", str(OUT / "dashboard_port"),
         "--history-db", str(OUT / "history_test.sqlite"),
         "--engines-cache", str(OUT / "engines_cache_test.json"),
         "--model-store", str(OUT / "model_store_test")],   # never the real ~/agx-models
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1"))
    base = None
    try:
        # the server may take the next free port if `port` was taken meanwhile
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("dashboard exited early, see tests/out/dashboard_test.log")
            pf = OUT / "dashboard_port"
            if pf.exists():
                try:
                    p = int(pf.read_text().strip())
                    r = httpx.get(f"http://127.0.0.1:{p}/api/health", auth=creds, timeout=2)
                    if r.status_code == 200:
                        base = f"http://127.0.0.1:{p}"
                        break
                except (ValueError, httpx.HTTPError):
                    pass
            time.sleep(0.3)
        if base is None:
            raise RuntimeError("dashboard did not answer in 20 s")
        time.sleep(1.5)  # let the 1 s collectors make deltas
        yield base
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log.close()


def _meminfo_total_mb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) / 1024
    raise AssertionError("no MemTotal")


def test_health_real_values(server, creds):
    r = httpx.get(server + "/api/health", auth=creds, timeout=5)
    assert r.status_code == 200
    h = r.json()
    assert h["schema"] == "agx-health/1"
    assert len(h["cpu"]["per_core"]) == os.cpu_count()
    tot = _meminfo_total_mb()
    assert abs(h["ram"]["total_mb"] - tot) <= 0.05 * tot
    assert h["temps"]["max_c"] is not None and 10 <= h["temps"]["max_c"] <= 110
    assert h["uptime_s"] > 0
    assert h["node_state"] in ("OK", "WARN", "CRIT")
    for k in ("hostname", "time", "nvpmodel", "gpu", "swap", "power", "fan", "disk", "net", "link", "infer", "errors"):
        assert k in h


def test_no_password_401(server):
    r = httpx.get(server + "/api/health", timeout=5)
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == f'Basic realm="{NODE}-dashboard"'


def test_wrong_password_401(server, creds):
    r = httpx.get(server + "/api/health", auth=(creds[0], creds[1] + "x"), timeout=5)
    assert r.status_code == 401
    r = httpx.get(server + "/static/app.js", auth=("nobody", "wrong"), timeout=5)
    assert r.status_code == 401


def test_page(server, creds):
    r = httpx.get(server + "/", auth=creds, timeout=5)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>agx dashboard</title>" in r.text     # neutral text: the page sets the node name
    assert creds[1] not in r.text
    assert "http://" not in r.text and "https://" not in r.text
    # tokens.css (the design values of the rk console) loads before style.css; router.js before app.js
    t = r.text
    assert t.index('href="/static/tokens.css"') < t.index('href="/static/style.css"')
    assert t.index('src="/static/router.js"') < t.index('src="/static/app.js"')
    for p in ("/static/app.js", "/static/router.js", "/static/tiles.js", "/static/style.css", "/static/tokens.css",
              "/static/vendor/uPlot.iife.min.js"):
        rr = httpx.get(server + p, auth=creds, timeout=5)
        assert rr.status_code == 200
        assert creds[1] not in rr.text
        assert "http://" not in rr.text and "https://" not in rr.text or p.startswith("/static/vendor/")
    tok = httpx.get(server + "/static/tokens.css", auth=creds, timeout=5).text
    assert tok.splitlines()[0].startswith("/* source: driveragent rk/console/ui/src/styles/tokens.css, commit ")


def test_live_values_change(server, creds):
    a = httpx.get(server + "/api/health", auth=creds, timeout=5).json()
    time.sleep(1.2)
    b = httpx.get(server + "/api/health", auth=creds, timeout=5).json()
    assert a["time"] != b["time"]
    live_a = (a["cpu"]["per_core"], a["uptime_s"], a["power"]["total_w"], a["temps"]["zones"],
              [n["rx_bps"] for n in a["net"]])
    live_b = (b["cpu"]["per_core"], b["uptime_s"], b["power"]["total_w"], b["temps"]["zones"],
              [n["rx_bps"] for n in b["net"]])
    assert live_a != live_b


def test_stream_events(server, creds):
    n = 0
    t0 = time.time()
    with httpx.stream("GET", server + "/api/stream", auth=creds, timeout=10) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data:"):
                d = json.loads(line[5:])
                assert "health" in d and "services" in d
                n += 1
            if time.time() - t0 > 3.5:
                break
    assert n >= 3


def test_read_only_and_logs_whitelist(server, creds):
    assert httpx.post(server + "/api/health", auth=creds, timeout=5).status_code == 405
    assert httpx.get(server + "/api/services/logs?unit=ssh", auth=creds, timeout=5).status_code == 400
    r = httpx.get(server + "/api/services/logs?unit=agx-infer", auth=creds, timeout=10)
    assert r.status_code == 200 and "lines" in r.json()
    r = httpx.get(server + "/api/models", auth=creds, timeout=5).json()
    assert "available" in r
    r = httpx.get(server + "/api/cameras/0/snapshot.jpg", auth=creds, timeout=5)
    assert r.status_code in (200, 404)
    h = httpx.get(server + "/api/history?range=1h&metrics=gpu_load_pct,temp_max_c", auth=creds, timeout=5).json()
    assert set(h["series"]) == {"gpu_load_pct", "temp_max_c"} and len(h["t"]) == len(h["series"]["temp_max_c"])


def test_allowlist():
    from dashboard.auth import parse_networks

    assert not ip_allowed("8.8.8.8")
    assert not ip_allowed("10.0.0.130")         # a LAN is not in the code default: ops/install.sh adds it to the config
    assert ip_allowed("10.0.0.130", parse_networks(["10.0.0.0/24"]))
    assert ip_allowed("100.64.0.180")
    assert ip_allowed("127.0.0.1")
    assert ip_allowed("::ffff:127.0.0.1")       # IPv4-mapped form of an allowed address
    assert ip_allowed("10.42.0.1")              # future Link C
    # narrowed list (M2): docker bridge, 192.168/16, link-local, other 10/8 and IPv6 are not allowed
    for bad in ("172.17.0.2", "192.168.1.5", "::ffff:192.168.1.5", "169.254.1.1", "10.0.1.5",
                "10.42.0.4", "::1", "fe80::1"):
        assert not ip_allowed(bad), bad
    assert not ip_allowed("1.1.1.1")
    assert not ip_allowed("100.128.0.1")
    assert not ip_allowed("")
    assert not ip_allowed(None)


def test_infer_client_contract():
    """In-process: fake PUB on a test port -> client sees status, snapshot, then NO DATA after 3 s."""
    import zmq
    from dashboard.collectors.infer_status import InferStatusClient

    port = _free_port(PORT_MIN + (PORT_MAX - PORT_MIN) // 2)
    ep = f"tcp://127.0.0.1:{port}"
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.setsockopt(zmq.LINGER, 0)
    pub.bind(ep)
    cli = InferStatusClient(ep, stale_s=3)
    cli.start()
    try:
        st = {"schema": "agx-infer-status/1", "t": time.time(),
              "node": {"state": "RUNNING", "uptime_s": 1, "pid": 1, "version": "test", "simulated": True, "errors": []},
              "cameras": [{"cam": 0, "role": "front", "state": "SIMULATED", "simulated": True, "fps": 15.0}],
              "models": [{"name": "yolo", "state": "RUNNING", "fps": 15.0,
                          "lat_ms": {"total": {"p50": 12.5, "p95": 20.0, "p99": 25.0}}}],
              "publish": {"results_rate_hz": 15.0, "subscribers": 1},
              "link": {"last_frame_t": time.time(), "time_since_last_frame_ms": 40}}
        jpeg = b"\xff\xd8\xff\xe0" + b"0" * 100 + b"\xff\xd9"
        deadline = time.time() + 5
        while time.time() < deadline and cli.current()[0] is None:
            pub.send_multipart([b"status", json.dumps(st).encode()])
            pub.send_multipart([b"snap.0", jpeg])
            time.sleep(0.1)
        s = cli.summary()
        assert s["infer"] is not None and s["infer_state"] == "RUNNING"
        assert s["infer"]["simulated"] is True
        assert s["infer"]["models_summary"]["per_model"][0]["simulated"] is True
        # R13: simulated values go to the history under a sim_ prefix, never as real data
        assert cli.metrics() == {"sim_fps.cam0": 15.0, "sim_lat_p50.yolo": 12.5}
        assert cli.link_part()["subscribers"] == 1
        assert cli.snapshot(0)[0] == jpeg
        real = json.loads(json.dumps(st))
        real["node"]["simulated"] = False
        real["cameras"][0].update(simulated=False, state="OK")
        deadline = time.time() + 5
        while time.time() < deadline and "fps.cam0" not in cli.metrics():
            pub.send_multipart([b"status", json.dumps(real).encode()])
            time.sleep(0.1)
        assert cli.metrics() == {"fps.cam0": 15.0, "lat_p50.yolo": 12.5}
        time.sleep(3.3)
        s = cli.summary()
        assert s["infer"] is None and s["infer_state"] == "NO DATA"
        assert "not running" in s["infer_reason"]
    finally:
        cli.stop()
        pub.close(0)


def test_guard_403_and_401_in_process():
    """IP allowlist middleware (403) and auth (401) through ASGI with a fake client address."""
    import asyncio

    from dashboard.app import create_app
    from dashboard.config import load_config

    app = create_app(dict(load_config("config/templates/dashboard.yaml"), model_control=False),
                     env={"AGX_DASH_USER": "u", "AGX_DASH_PASSWORD": "test-only-pw"},
                     start_collectors=False)

    async def go(client_ip, auth):
        tr = httpx.ASGITransport(app=app, client=(client_ip, 40000))
        async with httpx.AsyncClient(transport=tr, base_url="http://agx02") as c:
            return (await c.get("/api/services/logs?unit=nope", auth=auth)).status_code

    assert asyncio.run(go("8.8.8.8", ("u", "test-only-pw"))) == 403
    assert asyncio.run(go("172.17.0.2", ("u", "test-only-pw"))) == 403  # docker bridge: not allowed (M2)
    assert asyncio.run(go("10.42.0.2", None)) == 401                  # Link C: allowed by the template
    assert asyncio.run(go("10.42.0.2", ("u", "bad"))) == 401
    assert asyncio.run(go("100.64.0.180", ("u", "test-only-pw"))) == 400  # allowed, auth ok, unit not in whitelist

    async def headers(client_ip, auth):
        tr = httpx.ASGITransport(app=app, client=(client_ip, 40000))
        async with httpx.AsyncClient(transport=tr, base_url="http://agx02") as c:
            return (await c.get("/api/health", auth=auth)).headers

    # 401 / 403 replies also carry the security headers (SecurityHeaders is the outer middleware)
    for ip, auth in (("8.8.8.8", None), ("10.42.0.2", None)):
        h = asyncio.run(headers(ip, auth))
        assert "content-security-policy" in h and h.get("x-content-type-options") == "nosniff"


def test_small_rules():
    """Pure functions: level merge, unit-name filter, log-path cleaning."""
    from dashboard.auth import safe_path
    from dashboard.collectors.health import worst
    from dashboard.collectors.services import UNIT_RE

    assert worst(["n/a", "n/a"]) == "n/a"
    assert worst(["n/a", "ok"]) == "ok"
    assert worst(["ok", "warn", "n/a"]) == "warn"
    assert worst(["crit", "ok"]) == "crit"
    for good in ("agx-infer", "docker.service", "getty@tty1.service"):
        assert UNIT_RE.match(good)
    for bad in ("--help", "-x", "a b", "x;id", ""):
        assert not UNIT_RE.match(bad)
    assert "\n" not in safe_path("/a\nFAKE LOG LINE") and len(safe_path("x" * 500)) == 200


def test_history_cleanup_keeps_data_under_limit(tmp_path):
    """Free pages must not count: data that fits the limit is not deleted; over the limit, one
    cut brings the file under the limit."""
    from dashboard.history import History

    db = tmp_path / "h.sqlite"
    h = History(db, max_mb=50)
    con = h._connect()
    now = int(time.time())
    names = ["m%d" % i for i in range(10)]
    rows = [(t, n, 1.0) for t in range(now - 30 * 3600, now, 10) for n in names]
    con.executemany("INSERT INTO samples (t, metric, value) VALUES (?, ?, ?)", rows)
    con.commit()
    h._cleanup(con)  # age delete only: 24 h stays
    live = h._live_size(con)
    span = con.execute("SELECT MAX(t) - MIN(t) FROM samples").fetchone()[0]
    assert span >= 86400 - 20
    # limit just above the live size, file still has free pages from the age delete
    h.max_bytes = int(live * 1.05)
    con.execute("INSERT INTO samples (t, metric, value) VALUES (?, ?, ?)", (now - 40 * 3600, "old", 1.0))
    con.commit()
    h._cleanup(con)
    assert con.execute("SELECT MAX(t) - MIN(t) FROM samples").fetchone()[0] >= 86400 - 20
    # limit far below: one cut, file under the limit
    h.max_bytes = int(live * 0.3)
    h._cleanup(con)
    assert h._db_size() <= h.max_bytes
    assert con.execute("SELECT COUNT(*) FROM samples").fetchone()[0] > 0
    con.close()
