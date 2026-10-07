"""Dashboard v2 tests: models (B), cameras (C), link (D), old processes (E).

Run: .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_dashboard_v2.py

A FAKE agx-infer publisher (ZMQ PUB in this process, contract agx-infer-status/1) sends the status
of six SIMULATED cameras, four models (2 RUNNING, 1 OFF, 1 FAILED) and snapshots. agx-infer itself
is NOT started. The dashboard runs as a subprocess on a test port (18800-18899) with its own
config, port file, history db and engine cache in AGX_DASH_TEST_OUT (default tests/out).
The password is read from .env in this process and is never printed.

Optional env:
  AGX_DASH_TEST_OUT      directory for the test files (default tests/out)
  AGX_DASH_TEST_PORT_MIN / AGX_DASH_TEST_PORT_MAX   test port range (default 18800-18899)
  AGX_DASH_TEST_PYLIB    directory with the quickjs Python package (page JS test); without it the
                         JS test is skipped when quickjs cannot be imported.
"""
from __future__ import annotations

import io
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.env import load_env  # noqa: E402
from dashboard.collectors.engines import CACHE_VERSION, current_boot_id, file_key  # noqa: E402

OUT = Path(os.environ.get("AGX_DASH_TEST_OUT") or (ROOT / "tests" / "out"))
# AGX_DASH_TEST_PORT_MIN / AGX_DASH_TEST_PORT_MAX override the default test ports 18800-18899
PORT_MIN = int(os.environ.get("AGX_DASH_TEST_PORT_MIN") or 18800)
PORT_MAX = int(os.environ.get("AGX_DASH_TEST_PORT_MAX") or 18899)
FAKE_PORT = PORT_MIN + 62 if PORT_MIN + 62 <= PORT_MAX else PORT_MIN
NOW_LOG: list[str] = []


def _free_port(start=PORT_MIN, end=PORT_MAX, avoid=()) -> int:
    for p in range(start, end + 1):
        if p in avoid:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"no free test port in {start}-{end}")


def _jpeg(text: str) -> bytes:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (320, 180), (30, 60, 90))
    ImageDraw.Draw(im).text((10, 10), text, fill=(255, 255, 255))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=70)
    return b.getvalue()


class FakeInfer:
    """Fake agx-infer status publisher (1 Hz status + 1 Hz snapshot per camera)."""

    ROLES = ["front", "right", "left", "right-back", "left-back", "back"]

    def __init__(self, endpoint: str):
        import zmq

        self.endpoint = endpoint
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.PUB)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.bind(endpoint)
        self.frozen_t: float | None = None   # last_frame_t stays at this value when set
        self.last_status_sent: float | None = None
        self.sent = 0
        self._stop = threading.Event()
        self._snap = [_jpeg(f"cam {n} SIMULATED") for n in range(6)]
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def status(self, now: float) -> dict:
        lft = self.frozen_t if self.frozen_t is not None else now - 0.03
        cams = []
        for n in range(6):
            cams.append({
                "cam": n, "role": self.ROLES[n], "port": 6000 + n, "mode": "sim", "receiving": self.frozen_t is None,
                "state": "SIMULATED" if self.frozen_t is None else "SIMULATED",  # the dashboard must not trust this
                "simulated": True, "fmt": "nv12", "width": 1280, "height": 720,
                "fps": 30.0, "fps_5s": 29.8, "bitrate_kbps": 331776.0 + n, "datagrams": 1000 * (n + 1),
                "lost_packets": n, "lost_fragments": n, "lost_frames": n // 2, "bad": 0,
                "decode_ms": {"p50": 1.5 + n / 10, "p95": 2.5, "max": 4.0},
                "frame_age_ms": round((now - lft) * 1000, 1), "last_seq": 123 + self.sent,
                "last_frame_t": lft,
            })
        lat = {k: {"p50": v, "p95": v * 1.5, "p99": v * 2} for k, v in
               (("pre", 2.0), ("infer", 9.0), ("post", 1.0), ("total", 12.0))}
        models = [
            {"name": "driverguard_yolopx", "engine": "/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine",
             "state": "RUNNING", "error": None, "reason": None, "enabled": True, "cameras": [0, 1, 2, 3, 4, 5],
             "fps": 180.0, "lat_ms": lat, "gpu_mem_mb": 410.0, "gpu_mem_note": "estimate: engine file + activation + I/O",
             "trt_match": True, "trt_version": "10.3.0", "load_warnings": [], "inputs": [], "outputs": [],
             "results_total": 5000 + self.sent},
            {"name": "driverguard_dtcp", "engine": "/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine",
             "state": "RUNNING", "error": None, "reason": None, "enabled": True, "cameras": [0], "fps": 10.0,
             "lat_ms": lat, "gpu_mem_mb": 120.0, "gpu_mem_note": "estimate: engine file + activation + I/O",
             "trt_match": True, "trt_version": "10.3.0", "load_warnings": [], "inputs": [], "outputs": [],
             "results_total": 700},
            {"name": "system1", "engine": None, "state": "OFF", "error": None,
             "reason": "Not a TensorRT model", "enabled": False, "cameras": [], "fps": 0.0, "lat_ms": {},
             "gpu_mem_mb": None, "results_total": 0},
            {"name": "sparsedrive_convnext_orin",
             "engine": "/home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt",
             "state": "FAILED", "error": "TEST: engine output check failed (cosine 0.39)", "reason": None,
             "enabled": False, "cameras": [0, 1, 2, 3, 4, 5], "fps": 0.0, "lat_ms": {}, "gpu_mem_mb": None,
             "results_total": 0},
        ]
        return {"schema": "agx-infer-status/1", "t": now,
                "node": {"state": "DEGRADED", "uptime_s": 12.0, "pid": 4242, "version": "fake-test",
                         "simulated": True, "errors": ["TEST fake publisher"]},
                "cameras": cams, "models": models,
                "publish": {"results_port": 5560, "status_port": 5561, "results_rate_hz": 190.0,
                            "subscribers": 2, "results_total": 5700 + self.sent, "last_result_t": now - 0.01},
                "link": {"last_frame_t": lft, "time_since_last_frame_ms": round((now - lft) * 1000, 1)}}

    def _run(self):
        while not self._stop.is_set():
            now = time.time()
            self.sock.send_multipart([b"status", json.dumps(self.status(now)).encode()])
            self.last_status_sent = now
            self.sent += 1
            if self.frozen_t is None:
                for n in range(6):
                    self.sock.send_multipart([f"snap.{n}".encode(), self._snap[n]])
            self._stop.wait(1.0)

    def freeze(self) -> float:
        """Stop the frames: keep sending status with the same last_frame_t."""
        self.frozen_t = time.time() - 0.03
        return self.frozen_t

    def stop(self):
        self._stop.set()
        self._t.join(timeout=3)
        self.sock.close(0)


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
def fake():
    port = FAKE_PORT if _port_free(FAKE_PORT) else _free_port()
    f = FakeInfer(f"tcp://127.0.0.1:{port}")
    yield f
    f.stop()


def _port_free(p: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", p))
            return True
        except OSError:
            return False


@pytest.fixture(scope="module")
def engines_dir():
    """Scan dir with two engine files that are NOT in config/models.yaml:
    injected_old.engine (its facts are INJECTED in the cache: not inspected again) and
    bogus_test.plan (not in the cache: inspected for real, load FAILED)."""
    d = OUT / "v2_engines_scan"
    d.mkdir(parents=True, exist_ok=True)
    inj = d / "injected_old.engine"
    inj.write_bytes(b"NOT-A-REAL-ENGINE-injected" * 10)
    bog = d / "bogus_test.plan"
    bog.write_bytes(b"NOT-A-REAL-ENGINE-bogus" * 10)
    real, key = file_key(str(inj))
    cache = {"version": CACHE_VERSION, "t": time.time(), "entries": {key: {
        "path": str(inj), "realpath": real, "size": inj.stat().st_size, "mtime": "2026-10-05 22:00:00",
        "sha256_16": "injected00000001", "trt_version": "10.3.0", "load": "OK", "messages": [],
        "boot_id": current_boot_id(),
        "trt_match": True, "trt_build_device": "Orin GPU (sm87)", "trt_device_warning": None, "io": [{"name": "images", "mode": "INPUT", "shape": [1, 3, 640, 640], "dtype": "HALF"},
                                  {"name": "out", "mode": "OUTPUT", "shape": [1, 100, 6], "dtype": "FLOAT"}]}}}
    cpath = OUT / "v2_engines_cache.json"
    cpath.write_text(json.dumps(cache))
    return d, cpath


@pytest.fixture(scope="module")
def server(creds, fake, engines_dir):
    OUT.mkdir(parents=True, exist_ok=True)
    scan_dir, cache = engines_dir
    with open(ROOT / "config" / "dashboard.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.update({
        "infer_status_endpoint": fake.endpoint,
        "port_file": str(OUT / "v2_dashboard_port"),
        "engines": {"cache": str(cache), "scan_dirs": [str(scan_dir)], "scan_interval_s": 1800,
                    "inspect_timeout_s": 120},
        "models_config": "config/models.yaml",
        "sources_config": "config/sources.yaml",
    })
    cfg["history"]["db"] = str(OUT / "v2_history.sqlite")
    cfg["model_store"] = str(OUT / "v2_model_store")   # never the real ~/agx-models
    cfg_path = OUT / "v2_dashboard_test.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    port = _free_port(avoid=(int(fake.endpoint.rsplit(":", 1)[1]),))
    pf = OUT / "v2_dashboard_port"
    pf.unlink(missing_ok=True)
    log = open(OUT / "v2_dashboard_test.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "dashboard.main", "--config", str(cfg_path), "--port", str(port),
         "--port-file", str(pf), "--history-db", str(OUT / "v2_history.sqlite")],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1"))
    base = None
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"dashboard exited early, see {OUT / 'v2_dashboard_test.log'}")
            if pf.exists():
                try:
                    p = int(pf.read_text().strip())
                    assert PORT_MIN <= p <= PORT_MAX + 50
                    r = httpx.get(f"http://127.0.0.1:{p}/api/health", auth=creds, timeout=2)
                    if r.status_code == 200:
                        base = f"http://127.0.0.1:{p}"
                        break
                except (ValueError, httpx.HTTPError):
                    pass
            time.sleep(0.3)
        if base is None:
            raise RuntimeError("dashboard did not answer in 20 s")
        yield base
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log.close()


def _get(base, path, creds, **kw):
    r = httpx.get(base + path, auth=creds, timeout=10, **kw)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


def _wait(fn, timeout, step=0.2):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(step)
    return last


def _save(name, doc):
    (OUT / name).write_text(json.dumps(doc, indent=1))


# ---------------------------------------------------------------- tests (order matters)
def test_01_models(server, creds, engines_dir):
    d = _wait(lambda: (lambda x: x if x["available"] and x["engine_scan"]["t"] and not x["engine_scan"]["running"]
                       and x["engine_scan"]["count"] >= 2 else None)(_get(server, "/api/models", creds)), 180, 0.5)
    assert d, "models not available or engine scan not done in 180 s"
    _save("v2_api_models_live.json", d)
    rows = {r["name"]: r for r in d["models"]}
    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())["models"]
    assert [r["name"] for r in d["models"]][:len(cfg)] == [m["name"] for m in cfg]  # one row per config model
    assert rows["driverguard_yolopx"]["state"] == "RUNNING" and rows["driverguard_dtcp"]["state"] == "RUNNING"
    assert rows["system1"]["state"] == "OFF" and rows["system1"]["reason"]
    sd = rows["sparsedrive_convnext_orin"]
    assert sd["state"] == "FAILED" and "cosine 0.39" in sd["error"]
    y = rows["driverguard_yolopx"]
    assert y["fps"] == 180.0 and y["lat_ms"]["total"] == {"p50": 12.0, "p95": 18.0, "p99": 24.0}
    assert y["lat_ms"]["pre"]["p50"] == 2.0 and y["lat_ms"]["infer"]["p50"] == 9.0
    assert y["gpu_mem_mb"] == 410.0 and "estimate" in y["gpu_mem_note"]
    # engine facts from tools/inspect_engines.py (real engine on disk)
    assert y["engine_file"] == "yolopx_v2_fp16.engine" and y["size_bytes"] > 1_000_000
    assert y["mtime"] and len(y["sha256_16"]) == 16 and isinstance(y["trt_match"], bool)
    assert y["inputs"] and y["outputs"], "I/O shapes from the engine inspection"
    assert isinstance(y["load_warnings"], list)
    # R13
    assert d["simulated"] is True and d["label"] == "SIMULATED"
    assert all(r["label"] == "SIMULATED" for r in d["models"] if r["live"])
    # engines not in the configuration: the injected cache entry + the real inspection of a bogus file
    ex = {Path(e["engine_realpath"]).name: e for e in d["engines_not_in_config"]}
    assert "injected_old.engine" in ex and ex["injected_old.engine"]["sha256_16"] == "injected00000001"
    assert ex["injected_old.engine"]["inputs"][0]["shape"] == [1, 3, 640, 640]
    assert "bogus_test.plan" in ex and ex["bogus_test.plan"]["engine_load"] == "FAILED"
    assert ex["bogus_test.plan"]["trt_match"] is False
    cfg_real = {os.path.realpath(m["engine"]) for m in cfg if m.get("engine")}
    assert not cfg_real & set(ex_r["engine_realpath"] for ex_r in d["engines_not_in_config"])
    sc = d["engine_scan"]
    assert sc["error"] is None and sc["count"] == 2
    cache = json.loads(engines_dir[1].read_text())
    assert len(cache["entries"]) == 2 + len(cfg_real)  # injected + bogus + config engines
    NOW_LOG.append(f"models: {[(r['name'], r['state']) for r in d['models']]}; "
                   f"not in config: {sorted(ex)}")


def test_02_cameras_simulated(server, creds):
    d = _wait(lambda: (lambda x: x if x["available"] and all(c["state"] == "SIMULATED" for c in x["cameras"])
                       else None)(_get(server, "/api/cameras", creds)), 10)
    assert d, "cameras not SIMULATED"
    _save("v2_api_cameras_live.json", d)
    assert len(d["cameras"]) == 6 and [c["cam"] for c in d["cameras"]] == list(range(6))
    assert d["stale_s"] == 0.5 and d["no_signal_s"] == 1.0 and d["no_data_s"] == 3
    assert abs(d["server_t"] - time.time()) < 2
    c0 = d["cameras"][0]
    assert c0["role"] == "front" and c0["label"] == "SIMULATED" and c0["simulated"] is True
    for k in ("fps", "bitrate_kbps", "lost_packets", "lost_frames", "decode_p50_ms", "frame_age_ms", "age_ms",
              "snapshot_t", "last_frame_t"):
        assert k in c0, k
    assert c0["age_ms"] < 1000 * d["hold_s"] and c0["frame_age_ms"] < 100 and c0["decode_p50_ms"] == 1.5
    assert d["label"] == "SIMULATED"
    assert 0.9 <= d["status_period_s"] <= 1.1 and d["hold_s"] == round(d["status_period_s"] + 0.3, 3)
    # frames flow, status at 1 Hz: no STALE / NO SIGNAL between two status messages (no flicker)
    bad = []
    t_end = time.time() + 2.5
    n = 0
    while time.time() < t_end:
        x = _get(server, "/api/cameras", creds)
        n += 1
        st = {c["state"] for c in x["cameras"]}
        if st != {"SIMULATED"}:
            bad.append((round(x["server_t"] - x["status_rx_t"], 2), sorted(st)))
        time.sleep(0.1)
    assert not bad and n >= 15, bad
    r = httpx.get(server + "/api/cameras/3/snapshot.jpg?t=123", auth=creds, timeout=5)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    # SSE carries the cameras document and the server time, and sends an event AT ONCE for each
    # new status (the page must not wait up to 1 s for a new last_frame_t: false NO SIGNAL)
    lags = []
    prev_rx = None
    with httpx.stream("GET", server + "/api/stream", auth=creds, timeout=10) as s:
        for line in s.iter_lines():
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                assert len(ev["cameras"]["cameras"]) == 6 and abs(ev["server_t"] - time.time()) < 2
                assert ev["cameras"]["cameras"][0]["state"] == "SIMULATED"
                rx = ev["cameras"]["status_rx_t"]
                if prev_rx is not None and rx != prev_rx:
                    lags.append(round(ev["cameras"]["server_t"] - rx, 3))
                prev_rx = rx
                if len(lags) >= 4:
                    break
    assert len(lags) == 4 and max(lags) < 0.25, lags
    NOW_LOG.append(f"SSE event delay after a new status (s): {lags}")


def test_03_health_and_link(server, creds):
    h = _get(server, "/api/health", creds)
    inf = h["infer"]
    assert inf is not None and inf["simulated"] is True and h["simulated"] is True
    assert {m["name"]: m["state"] for m in inf["models"]}["sparsedrive_convnext_orin"] == "FAILED"
    assert len(inf["cameras"]) == 6 and all(c["simulated"] for c in inf["cameras"])
    assert inf["results_rate_hz"] == 190.0 and inf["subscribers"] == 2
    assert "cameras_summary" in inf and "models_summary" in inf  # v1 fields stay
    # R13: every simulated item has the label
    assert all(m["label"] == "SIMULATED" for m in inf["models"]) and all(c["label"] == "SIMULATED" for c in inf["cameras"])
    assert [c["state"] for c in inf["cameras_summary"]["per_cam"]] == [c["state"] for c in inf["cameras"]]
    lk = h["link"]
    assert lk["subscribers"] == 2 and lk["results_rate_hz"] == 190.0 and lk["results_total"] >= 5700
    assert lk["last_result_t"] and 0 <= lk["time_since_last_frame_ms"] < 1300  # 1 Hz status: up to 1 s
    assert "ping_ms" in lk and "clock_offset_ms" in lk  # v1 ping + clock stay
    assert lk["simulated"] is True and lk["label"] == "SIMULATED"
    # healthy link: the value is the frame age of the status (about 30 ms), it does not climb to 1 s
    ages = [_get(server, "/api/link", creds)["time_since_last_frame_ms"] for _ in range(8) if not time.sleep(0.15)]
    assert max(ages) < 200, ages
    _save("v2_api_health_infer.json", {"infer": inf, "link": lk})


def test_04_no_signal_timing(server, creds, fake):
    """Frames stop (status continues with the same last_frame_t): NO SIGNAL for all six cameras at
    >= 1.0 s and < 1.5 s after the last frame."""
    t_last = fake.freeze()
    first_stale = first_nosig = None
    seen = []
    deadline = t_last + 3.0
    cli = httpx.Client(auth=creds, timeout=5)  # keep-alive: short poll interval
    while time.time() < deadline:
        r = cli.get(server + "/api/cameras")
        assert r.status_code == 200
        d = r.json()
        states = {c["state"] for c in d["cameras"]}
        seen.append((round(d["server_t"] - t_last, 3), sorted(states)))
        if first_stale is None and states == {"STALE"}:
            first_stale = d["server_t"] - t_last
        if states == {"NO SIGNAL"}:
            first_nosig = d["server_t"] - t_last
            obs = time.time() - t_last
            break
        time.sleep(0.02)
    cli.close()
    _save("v2_no_signal_timeline.json", {"t_last_frame": t_last, "samples": seen})
    assert first_nosig is not None, f"no NO SIGNAL in 3 s: {seen[-5:]}"
    assert 1.0 <= first_nosig < 1.5, first_nosig
    assert obs < 1.5, obs
    # STALE shows only when a status message reports age >= 0.5 s before NO SIGNAL (depends on the phase)
    assert first_stale is None or 0.5 <= first_stale < 1.0
    # before 0.5 s nothing changed, between 0.5 and 1.0 s only STALE
    for age, st in seen:
        if age < 0.5:
            assert st == ["SIMULATED"], (age, st)
        elif age < 1.0:
            assert st in (["SIMULATED"], ["STALE"]), (age, st)
    # the SIMULATED label stays on NO SIGNAL tiles (R13)
    assert all(c["label"] == "SIMULATED" for c in d["cameras"])
    # no frame: the rates of the last status are not shown
    assert all(c["fps"] is None and c["bitrate_kbps"] is None for c in d["cameras"])
    h = _get(server, "/api/health", creds)
    assert {c["state"] for c in h["infer"]["cameras_summary"]["per_cam"]} == {"NO SIGNAL"}
    assert {c["state"] for c in h["infer"]["cameras"]} == {"NO SIGNAL"}
    lk = _get(server, "/api/link", creds)
    assert lk["time_since_last_frame_ms"] >= 1000
    NOW_LOG.append(f"STALE at {first_stale if first_stale is None else round(first_stale, 3)} s, NO SIGNAL (all six) at {first_nosig:.3f} s "
                   f"(observed {obs:.3f} s) after the last frame; {len(seen)} polls")


def test_05_no_data_after_3s(server, creds, fake):
    fake.stop()
    t_stop = fake.last_status_sent
    d = _wait(lambda: (lambda x: x if all(c["state"] == "NO DATA" for c in x["cameras"]) else None)(
        _get(server, "/api/cameras", creds)), 6, 0.1)
    assert d, "cameras did not change to NO DATA"
    elapsed = d["server_t"] - t_stop
    _save("v2_api_cameras_nodata.json", d)
    assert 3.0 <= elapsed < 4.5, elapsed
    assert d["available"] is False and "agx-infer not running" in d["reason"]
    m = _get(server, "/api/models", creds)
    _save("v2_api_models_nodata.json", m)
    rows = {r["name"]: r for r in m["models"]}
    assert m["available"] is False
    assert rows["driverguard_yolopx"]["state"] == "NO DATA" and rows["driverguard_yolopx"]["reason"] == "agx-infer not running"
    assert rows["driverguard_yolopx"]["size_bytes"] > 0 and rows["driverguard_yolopx"]["sha256_16"]  # facts from the cache
    assert rows["system1"]["state"] == "OFF" and "TensorRT" in rows["system1"]["reason"]
    assert rows["sparsedrive_convnext_orin"]["state"] == "OFF" and "cosine" in rows["sparsedrive_convnext_orin"]["reason"]
    assert m["engines_not_in_config"], "engine list stays without agx-infer"
    h = _get(server, "/api/health", creds)
    assert h["infer"] is None and h["infer_state"] == "NO DATA" and h["simulated"] is False
    assert h["link"]["time_since_last_frame_ms"] is None and "not running" in h["link"]["infer_na"]
    NOW_LOG.append(f"NO DATA (all six) at {elapsed:.2f} s after the last status message")


def test_06_auth_and_read_only(server, creds):
    for p in ("/api/models", "/api/cameras", "/api/cameras/0/snapshot.jpg", "/api/stream", "/static/tiles.js",
              "/api/services", "/"):
        r = httpx.get(server + p, timeout=5)
        assert r.status_code == 401, p
        r = httpx.get(server + p, auth=(creds[0], creds[1] + "x"), timeout=5)
        assert r.status_code == 401, p
    for p in ("/api/models", "/api/cameras"):
        assert httpx.post(server + p, auth=creds, timeout=5).status_code == 405
        assert httpx.delete(server + p, auth=creds, timeout=5).status_code == 405
    assert httpx.get(server + "/api/cameras/6/snapshot.jpg", auth=creds, timeout=5).status_code == 404


def test_07_page_labels(server, creds):
    page = httpx.get(server + "/", auth=creds, timeout=5).text
    js = httpx.get(server + "/static/app.js", auth=creds, timeout=5).text
    tiles = httpx.get(server + "/static/tiles.js", auth=creds, timeout=5).text
    assert "/static/tiles.js" in page and 'id="cam-tiles"' in page and 'id="models-tbl"' in page
    assert "Engine files not in the configuration" in page
    assert "Old DriverAgent processes" in page
    assert "No systemd unit exists for the old DriverAgent stack; it starts by hand (~/s.sh)" in page
    assert "SIMULATED" in page and "SIMULATED" in tiles and '"SIMULATED"' in js
    assert "(estimate)" in js
    # the only write request of the page is the model control POST in postModelControl() (to /api/models/ only);
    # no service control and no delete (tests/test_dashboard_pages.py checks the details)
    import re
    assert [m.group(1) for m in re.finditer(r"method\s*:\s*[\"'](POST|PUT|DELETE|PATCH)", js)] == ["POST"]
    for bad in ('"DELETE"', '"PUT"', '"PATCH"'):
        assert bad not in js
    assert js.count('"POST"') == 1 and 'fetch("/api/models/" + path' in js
    assert "delete" not in js.lower()
    low = page.lower()
    for bad in (">stop<", ">start<", ">delete<", ">restart<", ">kill<"):
        assert bad not in low
    assert creds[1] not in page + js + tiles


def test_08_services_old_processes(server, creds):
    d = _get(server, "/api/services", creds)
    op = d["old_processes"]
    assert "processes" in op and op["note"].startswith("No systemd unit exists for the old DriverAgent stack")


def test_old_process_match():
    from dashboard.collectors.old_procs import find_old_processes, match

    assert match(["python3", "/home/tonyho/driveragent/start.py"], "/") == "start.py"
    assert match(["python3", "start.py"], "/home/tonyho/driveragent") == "start.py"
    assert match(["python3", "/home/tonyho/driveragent-agx/start.py"], "/") is None
    assert match(["python3", "start.py"], "/home/tonyho/driveragent-agx") is None
    assert match(["python3", "-m", "ui.ui"], "/") == "ui.ui"
    assert match(["python3", "/home/tonyho/driveragent/model/system1/run.py"], "/") == "model/system1/run.py"
    assert match(["python3", "-m", "dashboard.main"], "/") is None
    # a harmless process with "camtest" in its command line is found (read-only scan)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "camtest-dashboard-test"])
    try:
        time.sleep(0.3)
        found = find_old_processes()
        assert any(x["pid"] == p.pid and x["match"] == "camtest" for x in found["processes"]), found
    finally:
        p.kill()
        p.wait(timeout=5)


class _StubScanner:
    def facts_note(self, p):
        return None, None

    def found_notes(self):
        return []

    def status(self):
        return {}


def _client_with(st: dict):
    from dashboard.collectors.infer_status import InferStatusClient

    c = InferStatusClient("tcp://127.0.0.1:1")
    c._status, c._status_rx, c._status_rx_mono = st, time.time(), time.monotonic()
    return c


def test_bad_status_fields_do_not_break_the_api():
    """A field with a wrong type (lat_ms.total is a number, publish is a string, ...) gives n/a."""
    from dashboard.infer_views import InferViews

    now = time.time()
    st = {"schema": "agx-infer-status/1", "t": now, "node": "bad", "publish": "bad", "link": 5,
          "cameras": [{"cam": 0, "last_frame_t": now, "decode_ms": 3, "fps": "x"}, "bad"],
          "models": [{"name": "m", "lat_ms": {"total": 12.0, "pre": [1]}, "inputs": "bad",
                      "load_warnings": "bad", "cameras": 7}]}
    c = _client_with(st)
    v = InferViews(c, _StubScanner(), None, None)
    assert c.metrics() == {}
    assert c.summary()["infer"]["models_summary"]["per_model"][0]["lat_total_p50_ms"] is None
    m = v.models_doc()["models"][0]
    assert m["lat_ms"]["total"] == {"p50": None, "p95": None, "p99": None} and m["inputs"] == []
    assert v.cameras_doc()["cameras"][0]["state"] in ("OK", "SIMULATED")
    assert v.health_infer_extra()["results_rate_hz"] is None
    assert c.link_part()["results_rate_hz"] is None


def test_mixed_mode_camera_labels():
    """node.simulated is true when ONE camera is simulated: each camera uses its own flag."""
    from dashboard.infer_views import InferViews

    now = time.time()
    cams = [{"cam": n, "simulated": n == 0, "last_frame_t": now - 0.03, "fps": 30.0} for n in range(6)]
    c = _client_with({"schema": "agx-infer-status/1", "t": now, "node": {"simulated": True}, "cameras": cams,
                      "models": [{"name": "m", "state": "RUNNING", "lat_ms": {"total": {"p50": 5.0}}}]})
    v = InferViews(c, _StubScanner(), None, None)
    d = v.cameras_doc()
    assert [(x["state"], x["label"]) for x in d["cameras"][:2]] == [("SIMULATED", "SIMULATED"), ("OK", None)]
    assert d["label"] == "SIMULATED"
    mt = c.metrics()
    assert "sim_fps.cam0" in mt and "fps.cam1" in mt and "sim_lat_p50.m" in mt  # model: node flag
    assert v.models_doc()["models"][0]["label"] == "SIMULATED"


def test_hold_cap_and_status_gap():
    """hold = min(period + jitter, no_signal_s + 0.5): a slow status cannot push NO SIGNAL past 1.5 s
    (+ 0.25 s page check < 2 s, T6). A single long gap does not change the measured period."""
    import unittest.mock as um

    from dashboard.collectors.infer_status import InferStatusClient
    from dashboard.infer_views import InferViews

    c = InferStatusClient("tcp://127.0.0.1:1")
    for t in (0, 1, 2, 3, 5.6, 6.6, 7.6, 12.0, 13.0):  # one gap of 2.6 s and one of 4.4 s
        with um.patch("time.monotonic", return_value=1000.0 + t):
            c._handle([b"status", json.dumps({"schema": "agx-infer-status/1"}).encode()])
    assert abs(c.period_s - 1.0) < 1e-6 and c.seq == 9
    v = InferViews(c, _StubScanner(), None, None)
    assert v.hold_s() == 1.3
    c.period_s = 1.8
    assert v.hold_s() == 1.5
    now = time.time()
    # explicit live flags: a missing flag means SIMULATED (R13 fail-safe, L4)
    c._status, c._status_rx, c._status_rx_mono = ({"schema": "agx-infer-status/1", "t": now - 0.3,
                                                   "node": {"simulated": False},
                                                   "cameras": [{"cam": 0, "simulated": False,
                                                                "last_frame_t": now - 0.33}]},
                                                  now, time.monotonic())
    assert v.cameras_doc(now + 1.16)["cameras"][0]["state"] == "OK"
    assert v.cameras_doc(now + 1.18)["cameras"][0]["state"] == "NO SIGNAL"  # 1.51 s after the last frame


def test_engine_scanner_retry_and_pending(monkeypatch):
    """A FAILED inspection is done again at the next periodic scan; a changed file shows
    "inspection pending" (no old facts) and requests a scan."""
    import tools.inspect_engines as ie

    from dashboard.collectors.engines import PENDING, EngineScanner

    d = OUT / "v2_retry_scan"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "retry.engine"
    f.write_bytes(b"x" * 100)
    calls = []

    def fake_inspect(path, timeout=120.0):
        calls.append(path)
        ok = len(calls) >= 2
        return {"path": path, "realpath": os.path.realpath(path), "size": os.path.getsize(path),
                "load": "OK" if ok else "FAILED", "error": None if ok else "timeout after 0.05 s",
                "trt_match": ok}

    monkeypatch.setattr(ie, "inspect", fake_inspect)
    monkeypatch.setattr(ie, "scan", lambda dirs: [str(p) for p in d.iterdir() if p.suffix == ".engine"])
    cache = OUT / "v2_retry_cache.json"
    cache.unlink(missing_ok=True)
    sc = EngineScanner(cache, [str(d)], lambda: [], 1800, 1)
    sc.scan_once(retry_failed=True)
    assert sc.facts(str(f))["load"] == "FAILED" and len(calls) == 1
    sc.scan_once(retry_failed=False)           # wake scan: no retry
    assert len(calls) == 1
    sc2 = EngineScanner(cache, [str(d)], lambda: [], 1800, 1)  # restart: periodic scan retries
    sc2.scan_once(retry_failed=True)
    assert len(calls) == 2 and sc2.facts(str(f))["load"] == "OK"
    sc2.scan_once(retry_failed=True)           # OK result stays cached
    assert len(calls) == 2
    with open(f, "ab") as fh:
        fh.write(b"y")
    os.utime(f, (time.time() + 5, time.time() + 5))
    facts, note = sc2.facts_note(str(f))
    assert facts is None and note == PENDING and sc2._wake.is_set()
    assert sc2.found_notes() == [(os.path.realpath(f), None, PENDING)]
    sc2.scan_once(retry_failed=False)
    assert len(calls) == 3 and sc2.facts_note(str(f))[1] is None


def test_engine_cache_old_version_and_other_boot(monkeypatch, tmp_path):
    """A version 1 cache (old trt_match rule) is ignored. An entry of an other boot is inspected again (the
    TensorRT device warning depends on the boot), one time in each boot."""
    import tools.inspect_engines as ie

    from dashboard.collectors import engines as eng

    d = tmp_path / "eng"
    d.mkdir()
    f = d / "x.engine"
    f.write_bytes(b"x" * 100)
    calls = []

    def fake_inspect(path, timeout=120.0):
        calls.append(path)
        return {"path": path, "realpath": os.path.realpath(path), "size": os.path.getsize(path), "load": "OK",
                "trt_match": True, "trt_build_device": "Orin GPU (sm87)", "trt_device_warning": None}

    monkeypatch.setattr(ie, "inspect", fake_inspect)
    monkeypatch.setattr(ie, "scan", lambda dirs: [str(f)])
    monkeypatch.setattr(eng, "current_boot_id", lambda: "boot-B")
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"version": 1, "t": 0, "entries": {
        eng.file_key(str(f))[1]: {"load": "OK", "trt_match": False, "messages": ["WARNING: x"]}}}))
    sc = eng.EngineScanner(cache, [str(d)], lambda: [], 1800, 1)
    assert sc.facts(str(f)) is None and "unknown format" in sc.status()["error"]
    sc.scan_once(retry_failed=False)               # no retry: only the version check causes the inspection
    assert len(calls) == 1 and sc.facts(str(f))["trt_match"] is True
    assert json.loads(cache.read_text())["version"] == eng.CACHE_VERSION == 2
    sc.scan_once(retry_failed=False)               # same boot: the result stays cached
    assert len(calls) == 1
    monkeypatch.setattr(eng, "current_boot_id", lambda: "boot-C")
    sc.scan_once(retry_failed=False)               # other boot: inspected again, one time
    sc.scan_once(retry_failed=False)
    assert len(calls) == 2 and sc.facts(str(f))["boot_id"] == "boot-C"


class _FactsScanner(_StubScanner):
    def __init__(self, facts):
        self._facts = facts

    def facts_note(self, p):
        return self._facts, None


def test_live_trt_fields_replace_inspection_values():
    """An agx-infer with the new rule gives the values of THIS boot: a live 'no device warning' replaces the
    warning of the inspection. An older agx-infer (no trt_build_device) keeps the inspection values."""
    from dashboard.infer_views import InferViews

    warn = "WARNING: Using an engine plan file across different models of devices is not recommended"
    facts = {"load": "OK", "trt_match": True, "trt_build_device": "Orin GPU (sm87)", "trt_device_warning": warn,
             "messages": [warn], "io": []}
    v = InferViews(_client_with({}), _FactsScanner(facts), None, None)
    mc = {"name": "m", "enabled": True, "engine": "/nonexistent/m.engine"}
    r = v._row(mc, {"name": "m", "state": "RUNNING", "trt_match": True, "trt_build_device": "Orin GPU (sm87)",
                    "trt_device_warning": None, "load_warnings": []}, True, False)
    assert r["trt_match"] is True and r["trt_device_warning"] is None and r["load_warnings"] == []
    r = v._row(mc, {"name": "m", "state": "RUNNING", "trt_match": True, "trt_build_device": "Orin GPU (sm87)",
                    "trt_device_warning": warn, "load_warnings": [warn]}, True, False)
    assert r["trt_device_warning"] == warn and r["load_warnings"] == [warn]
    r = v._row(mc, {"name": "m", "state": "RUNNING", "trt_match": False, "load_warnings": [warn]}, True, False)
    assert r["trt_match"] is True and r["trt_build_device"] == "Orin GPU (sm87)" and r["trt_device_warning"] == warn
    r = v._row(mc, None, False, False)             # no live status: the inspection values
    assert r["trt_match"] is True and r["trt_device_warning"] == warn
    v = InferViews(_client_with({}), _StubScanner(), None, None)
    r = v._row(mc, {"name": "m", "state": "RUNNING", "trt_match": False}, True, False)
    assert r["trt_match"] is False                 # no inspection facts: the value of the older agx-infer


def _quickjs():
    pl = os.environ.get("AGX_DASH_TEST_PYLIB")
    if pl and pl not in sys.path:
        sys.path.insert(0, pl)
    try:
        import quickjs
    except ImportError:
        pytest.skip("quickjs not installed (set AGX_DASH_TEST_PYLIB)")
    return quickjs


def test_page_tile_state_quickjs():
    """tileState() of static/tiles.js in QuickJS with a timeline; app.js must compile."""
    quickjs = _quickjs()
    ctx = quickjs.Context()
    ctx.eval((ROOT / "dashboard" / "static" / "tiles.js").read_text())
    ctx.eval("var DOC = {available: true, status_rx_t: 1000.0, status_t: 1000.0, no_data_s: 3, stale_s: 0.5,"
             " no_signal_s: 1.0, hold_s: 1.3};"
             "var SIMCAM = {cam: 0, simulated: true, last_frame_t: 1000.0, state: 'SIMULATED'};"
             "var REALCAM = {cam: 1, simulated: false, last_frame_t: 1000.0, state: 'OK'};"
             # fresh status (made and received at nowS): known age = age
             "function ts(c, now, doc) { if (doc === undefined) { doc = JSON.parse(JSON.stringify(DOC));"
             " doc.status_t = now; doc.status_rx_t = now; }"
             " var r = AGXTiles.tileState(c, now, doc); return r.state + '|' + (r.label || '') + '|' + r.cls; }")

    def ts(cam, now, doc="undefined"):
        return ctx.eval(f"ts({cam}, {now}, {doc})")

    assert ts("SIMCAM", 1000.2) == "SIMULATED|SIMULATED|st-sim"
    assert ts("REALCAM", 1000.2) == "OK||st-ok"
    assert ts("SIMCAM", 1000.7) == "STALE|SIMULATED|st-stale"
    assert ts("REALCAM", 1000.7) == "STALE||st-stale"
    assert ts("SIMCAM", 1001.1) == "NO SIGNAL|SIMULATED|st-nosig"
    assert ts("REALCAM", 1001.1) == "NO SIGNAL||st-nosig"
    # between two status messages (status made at 1000.0): frames after it are not known yet
    assert ts("SIMCAM", 1000.7, "DOC") == "SIMULATED|SIMULATED|st-sim"
    assert ts("SIMCAM", 1001.29, "DOC") == "SIMULATED|SIMULATED|st-sim"
    assert ts("SIMCAM", 1001.31, "DOC") == "NO SIGNAL|SIMULATED|st-nosig"
    # no status for 3.5 s -> NO DATA
    assert ts("SIMCAM", 1003.5, "DOC") == "NO DATA||st-nodata"
    assert ts("SIMCAM", 1000.2, "{available: false, status_rx_t: 1000.0}") == "NO DATA||st-nodata"
    assert ts("SIMCAM", 1000.2, "null") == "NO DATA||st-nodata"
    assert ts("{cam: 2, simulated: true, last_frame_t: null}", 1000.2) == "NO SIGNAL|SIMULATED|st-nosig"

    # page loop: re-evaluated every 250 ms with Date.now()/1000 + serverOffset; status + SSE at 1 Hz,
    # last frame at 1000.0. The page clock is 7.3 s behind the server clock. Two phases:
    #   A: status messages at 1000.0, 1001.0, ...  B: status messages at 1000.95, 1001.95, ...
    def timeline(phase):
        ctx.eval("var doc = JSON.parse(JSON.stringify(DOC)); var serverOffset = 0; var TL = [];"
                 f"var ph = {phase}; var nextS = 1000.0 + ph;"
                 "for (var k = 0; k <= 12; k++) { var srv = 1000.0 + k * 0.25; var pageNow = srv - 7.3;"
                 " while (nextS <= srv + 1e-9) { doc.status_t = nextS; doc.status_rx_t = nextS + 0.01;"
                 "  serverOffset = nextS + 0.01 - (nextS + 0.01 - 7.3); nextS += 1.0; }"
                 " TL.push([k * 0.25, AGXTiles.tileState(SIMCAM, pageNow + serverOffset, doc).state]); }")
        tl = json.loads(ctx.eval("JSON.stringify(TL)"))
        first = {}
        for age, st in tl:
            first.setdefault(st, age)
        return tl, first

    tl_a, fa = timeline(0.0)
    assert fa == {"SIMULATED": 0.0, "NO SIGNAL": 1.0}, tl_a
    tl_b, fb = timeline(0.95)
    assert fb["SIMULATED"] == 0.0 and fb["STALE"] == 1.0 and 1.3 <= fb["NO SIGNAL"] <= 1.55, tl_b
    # SSE stops at 1001.0 (server time): NO DATA 3 s later
    ctx.eval("var doc2 = JSON.parse(JSON.stringify(DOC)); doc2.status_rx_t = 1001.0; doc2.status_t = 1001.0;")
    assert ctx.eval("AGXTiles.tileState(SIMCAM, 1003.9, doc2).state") == "NO SIGNAL"
    assert ctx.eval("AGXTiles.tileState(SIMCAM, 1004.0, doc2).state") == "NO DATA"
    # hold from the server is capped at no_signal_s + 0.5 also on the page
    ctx.eval("var doc3 = JSON.parse(JSON.stringify(DOC)); doc3.hold_s = 2.3; doc3.status_rx_t = 1001.4;")
    assert ctx.eval("AGXTiles.tileState(SIMCAM, 1001.49, doc3).state") == "SIMULATED"
    assert ctx.eval("AGXTiles.tileState(SIMCAM, 1001.51, doc3).state") == "NO SIGNAL"

    # page with the SSE push (event 0.05 s after each status), status phases 0.0 .. 0.95, 250 ms check:
    # frames flow for 5 s (no state other than SIMULATED), then stop: NO SIGNAL 1.0 .. 1.55 s later
    ctx.eval("""
      function pushRun(ph, tick0, off) {
        var doc = null, out = {bad: 0, nosig: null}, lastFrame = null;
        var stopAt = 1005.0 + ph + off;       // frames stop between two status messages
        var events = [];                       // [deliver time, doc]
        lastFrame = stopAt - 0.03;             // the newest real frame (30 fps until stopAt)
        for (var s = 1000.0 + ph; s < 1012; s += 1.0) {
          var lf = Math.min(s, stopAt) - 0.03;  // agx-infer reports the newest frame before s
          events.push([s + 0.05, {available: true, status_t: s, status_rx_t: s + 0.002, no_data_s: 3,
                       stale_s: 0.5, no_signal_s: 1.0, hold_s: 1.3, hold_cap_s: 1.5,
                       cam: {cam: 0, simulated: true, last_frame_t: lf}}]);
        }
        var ei = 0;
        for (var t = 1001.0 + tick0; t < 1011; t += 0.25) {
          while (ei < events.length && events[ei][0] <= t) { doc = events[ei][1]; ei++; }
          var r = AGXTiles.tileState(doc.cam, t, doc).state;
          if (t < stopAt) { if (r !== "SIMULATED") out.bad++; }
          else if (r === "NO SIGNAL" && out.nosig === null) out.nosig = t - lastFrame;
        }
        return out;
      }""")
    worst = []
    for ph in [x / 20 for x in range(20)]:
        for tick0 in (0.0, 0.07, 0.13, 0.2):
            for off in (0.02, 0.5, 0.97):
                r = json.loads(ctx.eval(f"JSON.stringify(pushRun({ph}, {tick0}, {off}))"))
                assert r["bad"] == 0, (ph, tick0, off, r)
                assert r["nosig"] is not None and 1.0 <= r["nosig"] <= 1.6, (ph, tick0, off, r)
                worst.append(r["nosig"])
    NOW_LOG.append(f"QuickJS SSE push, {len(worst)} cases: no false state while frames flow; NO SIGNAL "
                   f"{min(worst):.2f} .. {max(worst):.2f} s after the last frame")
    # app.js and router.js compile (syntax) in QuickJS
    for name in ("app.js", "router.js"):
        src = (ROOT / "dashboard" / "static" / name).read_text()
        assert ctx.eval("typeof new Function(" + json.dumps(src) + ")") == "function", name
    NOW_LOG.append(f"QuickJS timeline A (status at 1000.0+k): {tl_a}")
    NOW_LOG.append(f"QuickJS timeline B (status at 1000.95+k): {tl_b}")


def test_zz_print_summary():
    for line in NOW_LOG:
        print("RESULT", line)
