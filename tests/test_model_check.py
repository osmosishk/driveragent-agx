"""Model checks (owner Section 4.3): tools/model_check.py (child) and controller/checks.py (CheckRunner).

The CheckRunner tests use a fake child (a tiny tools/model_check.py in a temporary repo). One real check runs the
DTCP engine on AGX02 (skipped when the old engine is not there); it only reads the old engine.
"""
import hashlib
import json
import os
import subprocess
import sys
import textwrap
import time

import numpy as np
import pytest
import yaml

from controller import checks as ck
from controller import manifest as mf
from tools import model_check as mc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DTCP_ENGINE = "/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine"

FAKE_CHILD = r'''
import json, os, subprocess, sys, time
folder = sys.argv[1]
mode = open(os.path.join(folder, "mode")).read().strip()
key = os.path.basename(os.path.dirname(folder)) + "@" + os.path.basename(folder)
log = os.environ.get("FAKE_CHECK_LOG")
def note(what):
    if log:
        with open(log, "a") as f:
            f.write(f"{what} {key} {time.monotonic()}\n")
note("start")
if mode.startswith("sleep:"):
    time.sleep(float(mode.split(":")[1]))
elif mode == "hang":
    g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(os.path.join(folder, "grandchild.pid"), "w").write(str(g.pid))
    time.sleep(60)
elif mode == "noline":
    print("some output without the line")
    sys.stderr.write("x" * 500 + "\nRuntimeError: boom at the end\n")
    sys.exit(1)
note("end")
ok = mode != "fail"
print("CHECK:" + json.dumps({"ok": ok, "reason": None if ok else "inference check failed: bad", "checks": [],
                             "key": key, "argv": sys.argv[1:]}))
sys.exit(0 if ok else 1)
'''


# -- helpers ---------------------------------------------------------------------------------------------------
def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _fake_repo(tmp_path) -> str:
    repo = tmp_path / "fakerepo"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "__init__.py").write_text("")
    (repo / "tools" / "model_check.py").write_text(FAKE_CHILD)
    return str(repo)


def _version(store, name: str, version: str, mode: str = "ok") -> mf.Manifest:
    """A small version folder: manifest.yaml + one onnx file + the fake child mode."""
    folder = os.path.join(str(store), name, version)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "model.onnx"), "wb") as f:
        f.write(b"onnx" * 10)
    d = {"schema": mf.SCHEMA, "name": name, "version": version, "type": "dtcp", "description": "test",
         "files": [{"role": "onnx", "path": "model.onnx", "sha256": _sha(os.path.join(folder, "model.onnx"))}]}
    with open(os.path.join(folder, mf.MANIFEST), "w") as f:
        yaml.safe_dump(d, f)
    with open(os.path.join(folder, "mode"), "w") as f:
        f.write(mode)
    return mf.load(folder)


def _runner(tmp_path, **kw) -> ck.CheckRunner:
    return ck.CheckRunner(str(tmp_path / "store"), _fake_repo(tmp_path), sys.executable, **kw)


# -- CheckRunner with the fake child ---------------------------------------------------------------------------
def test_runner_stores_result_with_fingerprint(tmp_path):
    r = _runner(tmp_path)
    try:
        m = _version(tmp_path / "store", "alpha", "1")
        assert r.result(m.key) is None
        assert r.request(m) is True
        assert r.wait_idle(20)
        res = r.result(m.key)
        assert res["ok"] is True and res["key"] == "alpha@1" and res["exit_code"] == 0
        assert res["fingerprint"] == ck.fingerprint(m.folder) and res["folder"] == m.folder
        assert res["argv"] == [m.folder, "--json"]
        path = tmp_path / "store" / "_state" / "checks" / "alpha@1.json"
        assert json.loads(path.read_text())["ok"] is True
        assert not [p for p in os.listdir(path.parent) if ".tmp" in p]      # atomic write left no tmp file
    finally:
        r.stop()


def test_failed_check_result(tmp_path):
    r = _runner(tmp_path, frame="/x/frame.jpg")
    try:
        m = _version(tmp_path / "store", "alpha", "2", mode="fail")
        r.request(m)
        assert r.wait_idle(20)
        res = r.result(m.key)
        assert res["ok"] is False and res["reason"] == "inference check failed: bad" and res["exit_code"] == 1
        assert res["argv"] == [m.folder, "--json", "--frame", "/x/frame.jpg"]
    finally:
        r.stop()


def test_fingerprint_invalidation(tmp_path):
    r = _runner(tmp_path)
    try:
        m = _version(tmp_path / "store", "beta", "1")
        r.request(m)
        assert r.wait_idle(20) and r.result(m.key) is not None
        # a file of the manifest changes (size and mtime) -> stale
        onnx = os.path.join(m.folder, "model.onnx")
        with open(onnx, "ab") as f:
            f.write(b"more")
        assert r.result(m.key) is None
        r.request(m)
        assert r.wait_idle(20) and r.result(m.key) is not None
        # same size, new mtime -> stale
        st = os.stat(onnx)
        os.utime(onnx, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        assert r.result(m.key) is None
        r.request(m)
        assert r.wait_idle(20) and r.result(m.key) is not None
        # the manifest bytes change -> stale
        with open(os.path.join(m.folder, mf.MANIFEST), "a") as f:
            f.write("notes: changed\n")
        assert r.result(m.key) is None
        # a file of the manifest is removed -> stale
        r.request(m)
        assert r.wait_idle(20) and r.result(m.key) is not None
        os.remove(onnx)
        assert r.result(m.key) is None
    finally:
        r.stop()


def test_one_check_at_a_time(tmp_path, monkeypatch):
    log = tmp_path / "log.txt"
    monkeypatch.setenv("FAKE_CHECK_LOG", str(log))
    r = _runner(tmp_path)
    try:
        ms = [_version(tmp_path / "store", "gamma", str(i), mode="sleep:0.4") for i in range(3)]
        assert [r.request(m) for m in ms] == [True, True, True]
        assert r.request(ms[2]) is False                    # already queued
        t_end = time.monotonic() + 10
        while r.busy() is None and time.monotonic() < t_end:
            time.sleep(0.02)
        assert r.busy() == "gamma@0"
        assert r.request(ms[0]) is False                    # running now
        assert r.pending() == ["gamma@1", "gamma@2"]
        assert r.wait_idle(30)
        assert r.busy() is None and r.pending() == []
        rows = [ln.split() for ln in log.read_text().splitlines()]
        assert [(w, k) for w, k, _ in rows] == [("start", "gamma@0"), ("end", "gamma@0"), ("start", "gamma@1"),
                                                ("end", "gamma@1"), ("start", "gamma@2"), ("end", "gamma@2")]
        times = [float(t) for _, _, t in rows]
        assert times == sorted(times)                       # no overlap
        assert all(r.result(m.key)["ok"] for m in ms)
    finally:
        r.stop()


def test_timeout_kills_the_process_group(tmp_path):
    r = _runner(tmp_path, timeout_s=1.5)
    try:
        m = _version(tmp_path / "store", "delta", "1", mode="hang")
        t0 = time.monotonic()
        r.request(m)
        assert r.wait_idle(20)
        assert time.monotonic() - t0 < 10
        res = r.result(m.key)
        assert res["ok"] is False and res["reason"] == "check did not finish in 1.5 s"
        pid = int(open(os.path.join(m.folder, "grandchild.pid")).read())
        t_end = time.monotonic() + 5
        while time.monotonic() < t_end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the grandchild of the check still runs after the timeout")
    finally:
        r.stop()


def test_no_check_line_gives_stderr_tail(tmp_path):
    r = _runner(tmp_path)
    try:
        m = _version(tmp_path / "store", "eps", "1", mode="noline")
        r.request(m)
        assert r.wait_idle(20)
        res = r.result(m.key)
        assert res["ok"] is False and res["exit_code"] == 1
        assert res["reason"].endswith("RuntimeError: boom at the end") and len(res["reason"]) == ck.STDERR_TAIL
    finally:
        r.stop()


def test_stop_ends_thread_and_running_check(tmp_path):
    r = _runner(tmp_path, timeout_s=60)
    m = _version(tmp_path / "store", "zeta", "1", mode="hang")
    r.request(m)
    t_end = time.monotonic() + 10
    while r.busy() is None and time.monotonic() < t_end:
        time.sleep(0.02)
    t0 = time.monotonic()
    r.stop()
    assert time.monotonic() - t0 < 5 and not r._thread.is_alive()
    assert r.result(m.key) is None                          # an interrupted check stores no result
    assert r.request(m) is False


def test_checks_module_does_not_import_tensorrt():
    code = "import sys, controller.checks; print('tensorrt' in sys.modules, 'torch' in sys.modules)"
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stderr
    assert p.stdout.split() == ["False", "False"]


# -- model_check helpers (pure) --------------------------------------------------------------------------------
def test_io_differences():
    eng = [{"name": "image", "shape": [-1, 3, 256, 928], "dtype": "FLOAT"}]
    assert mc.io_differences("input", [{"name": "image", "shape": [1, 3, 256, 928], "dtype": "float32"}], eng) == []
    assert mc.io_differences("input", [{"name": "image", "shape": [-1, 3, 256, 928], "dtype": "FLOAT"}], eng) == []
    d = mc.io_differences("input", [{"name": "img", "shape": [1, 3, 256, 928], "dtype": "float32"}], eng)
    assert len(d) == 1 and "names" in d[0]
    d = mc.io_differences("input", [{"name": "image", "shape": [1, 3, 256, 920], "dtype": "fp16"}], eng)
    assert len(d) == 2 and "shape" in d[0] and "dtype" in d[1]
    d = mc.io_differences("input", [{"name": "image", "shape": [1, 3, 256, 928]}], eng)
    assert d and "no dtype" in d[0]


def test_bgr_to_nv12_round_trip():
    import cv2
    yy, xx = np.mgrid[0:72, 0:128]
    bgr = np.dstack([xx * 2, yy * 3, (xx + yy)]).astype(np.uint8)
    nv12 = mc.bgr_to_nv12(bgr)
    assert nv12.shape == (108, 128) and nv12.dtype == np.uint8
    back = cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)
    assert np.abs(back.astype(int) - bgr.astype(int)).mean() < 4


def test_usage_error_exit_2(tmp_path):
    p = subprocess.run([sys.executable, "-m", "tools.model_check", str(tmp_path / "missing")], cwd=ROOT,
                       capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=ROOT))
    assert p.returncode == 2 and "CHECK:" not in p.stdout


# -- real checks on AGX02 --------------------------------------------------------------------------------------
def _run_tool(folder: str, frame: str | None = None) -> tuple[int, dict]:
    cmd = [sys.executable, "-m", "tools.model_check", folder, "--json"] + (["--frame", frame] if frame else [])
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=240,
                       env=dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1"))
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("CHECK:")]
    assert lines, f"no CHECK line; stderr: {p.stderr[-500:]}"
    return p.returncode, json.loads(lines[-1][len("CHECK:"):])


def _frame(tmp_path) -> str:
    if os.path.isfile(mc.DEFAULT_FRAME):
        return mc.DEFAULT_FRAME
    import cv2
    yy, xx = np.mgrid[0:720, 0:1280]
    img = np.dstack([(xx // 5) % 256, (yy // 3) % 256, ((xx + yy) // 8) % 256]).astype(np.uint8)
    cv2.rectangle(img, (500, 380), (780, 600), (40, 40, 200), -1)
    p = str(tmp_path / "front_1280x720.jpg")
    cv2.imwrite(p, img)
    return p


def _dtcp_manifest(store, sha: str, type_: str = "dtcp") -> str:
    folder = os.path.join(str(store), "driverguard_dtcp", "1")
    os.makedirs(folder, exist_ok=True)
    t = lambda n, s: {"name": n, "shape": s, "dtype": "float32"}  # noqa: E731
    d = {"schema": mf.SCHEMA, "name": "driverguard_dtcp", "version": "1", "type": type_,
         "description": "DTCP v1 (old engine, read-only)",
         "files": [{"role": "engine", "path": DTCP_ENGINE, "sha256": sha}],
         "input": {"tensors": [t("image", [1, 3, 256, 928]), t("state", [1, 9]), t("target_point", [1, 2])],
                   "size": {"width": 928, "height": 256}, "colour_order": "RGB", "normalisation": "imagenet"},
         "precision": "fp16", "cameras": {"permitted": [0], "default": [0]},
         "adapter": {"options": {"command": 2, "target": [0.0, 20.0]}},
         "outputs": {"tensors": [t("pred_wp", [1, 4, 2]), t("mu", [1, 2]), t("sigma", [1, 2]),
                                 t("pred_speed", [1, 1])], "kinds": ["trajectory"]},
         "runtime": {"workers": 1, "max_fps_per_camera": 10}, "date": "2026-10-07"}
    with open(os.path.join(folder, mf.MANIFEST), "w") as f:
        yaml.safe_dump(d, f, sort_keys=False)
    assert mf.load(folder).errors == []
    return folder


@pytest.fixture(scope="module")
def dtcp_sha():
    if not os.path.isfile(DTCP_ENGINE):
        pytest.skip(f"{DTCP_ENGINE} does not exist (not AGX02)")
    return _sha(DTCP_ENGINE)


def test_real_dtcp_check(tmp_path, dtcp_sha):
    st = os.stat(DTCP_ENGINE)
    folder = _dtcp_manifest(tmp_path / "store", dtcp_sha)
    code, r = _run_tool(folder, _frame(tmp_path))
    assert code == 0 and r["ok"] is True and r["reason"] is None, r
    assert [c["name"] for c in r["checks"]] == list(mc.CHECKS) and all(c["ok"] for c in r["checks"])
    assert r["trt_match"] is True and r["trt_version"] and r["engine_sha256"] == dtcp_sha
    assert r["engine"] == DTCP_ENGINE and r["key"] == "driverguard_dtcp@1"
    assert r["gpu_need_mb"] > 0 and r["gpu_free_mb"] > r["gpu_need_mb"]
    assert r["inference_ms"] > 0 and r["result_summary"]["trajectory_points"] == 4
    assert {t["name"] for t in r["io"]["outputs"]} == {"pred_wp", "mu", "sigma", "pred_speed"}
    st2 = os.stat(DTCP_ENGINE)
    assert (st2.st_size, st2.st_mtime_ns) == (st.st_size, st.st_mtime_ns)      # the old engine is unchanged


def test_real_wrong_sha256(tmp_path, dtcp_sha):
    folder = _dtcp_manifest(tmp_path / "store", "0" * 64)
    code, r = _run_tool(folder)
    assert code == 1 and r["ok"] is False and r["reason"].startswith("sha256 check failed")
    assert r["checks"][0]["name"] == "sha256" and r["checks"][0]["ok"] is False
    assert all(c["detail"] == "not run" for c in r["checks"][1:])
    assert r["trt_version"] is None                                             # nothing was loaded


def test_no_adapter_type(tmp_path):
    folder = _dtcp_manifest(tmp_path / "store", "0" * 64, type_="system1")
    code, r = _run_tool(folder)
    assert code == 1 and r["ok"] is False and r["reason"] == "no adapter for type system1"
    assert r["trt_version"] is None and r["engine"] is None
