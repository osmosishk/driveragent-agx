"""Model instances "<name>@<version>" added and removed at runtime (no process restart), and the start set.

  - two versions of one model name (driverguard_dtcp@a and @b, real DTCP engine) run at the same time on cam 0;
    remove one -> its results stop, the other runs on; duplicate key / unknown key / no version -> error
  - status() while instances are added and removed in other threads (fake engines, no GPU)
  - result publisher duplicate check and result cache use (instance, cam); snapshot label "name vV"
  - admin socket "instances" / "add" / "remove" round trip with a real ModelManager (fake engines)
  - infer.main.select_models: last good set of a temporary model store (manifest -> the old DTCP engine by
    absolute path) and the config/models.yaml fallback; the selected config runs (real DTCP engine)
Ports 15690-15699 only. GPU use: the DTCP engine only (~5 ms per inference).
"""
from __future__ import annotations

import json
import os
import threading
import time

import numpy as np
import pytest
import yaml
import zmq

from infer.ingest.frame_store import Frame, FrameStore

DTCP_ENGINE = "/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine"
DTCP_SHA256 = "1071ea90213eddc2efc0985229378c143afb68d3af7d5c9d7506dde06dc455b7"
P_PUB, P_ADM = 15691, 15692
needs_engine = pytest.mark.skipif(not os.path.isfile(DTCP_ENGINE), reason="DTCP engine missing")


def dtcp_cfg(version: str, cams=(0,), max_fps=10, engine=DTCP_ENGINE) -> dict:
    """The runtime_cfg() format (controller/runtime.py)."""
    return {"name": "driverguard_dtcp", "version": version, "group": "dtcp", "enabled": True, "engine": engine,
            "onnx": None, "adapter": "dtcp_v1", "cameras": list(cams), "workers": 1, "max_fps_per_camera": max_fps,
            "options": {"command": 2, "target": [0.0, 20.0], "ego_speed_mps": None}}


class Feeder:
    """Synthetic NV12 frames into the store at `fps` for each camera."""

    def __init__(self, store, cams, fps=30.0, w=1280, h=720):
        self.store, self.cams, self.period, self.w, self.h = store, list(cams), 1.0 / fps, w, h
        self.seq = 0
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        rng = np.random.default_rng(0)
        while not self._stop.is_set():
            self.seq += 1
            for cam in self.cams:
                nv = rng.integers(16, 235, size=(self.h * 3 // 2, self.w), dtype=np.uint8)
                now = time.time_ns()
                self.store.put(Frame(cam, self.seq, now, now, now, self.w, self.h, "nv12", "test-pattern", nv))
            self._stop.wait(self.period)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self.t.join()


class Collector:
    def __init__(self):
        self.lock = threading.Lock()
        self.results = []

    def __call__(self, r):
        with self.lock:
            self.results.append(r)

    def of(self, instance):
        with self.lock:
            return [r for r in self.results if r["instance"] == instance]


def wait(cond, timeout):
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def states(mgr) -> dict:
    return {m["instance"]: m["state"] for m in mgr.status()}


def no_dupes(results):
    last = {}
    for r in results:   # per (instance, cam) the seq only goes up: never twice, never an old one after a newer
        k = (r["instance"], r["cam"])
        assert r["frame_seq"] > last.get(k, -1)
        last[k] = r["frame_seq"]


# ---- real DTCP engine: two versions of one model name -------------------------------------------------------
@needs_engine
def test_two_versions_of_one_model_run_and_one_is_removed(tmp_path):
    from infer.models.manager import ModelManager
    store = FrameStore(range(6))
    col = Collector()
    mgr = ModelManager([], store, col, engines_dir=str(tmp_path / "engines"))
    a, b = "driverguard_dtcp@a", "driverguard_dtcp@b"
    try:
        mgr.start()
        with Feeder(store, [0], fps=30):
            t0 = time.monotonic()
            assert mgr.add_model(dtcp_cfg("a")) == (True, a)
            assert mgr.add_model(dtcp_cfg("b")) == (True, b)
            t_add = time.monotonic() - t0
            assert t_add < 0.5, f"add_model must return at once ({t_add:.2f} s)"
            assert set(states(mgr).values()) <= {"LOADING", "RUNNING"}
            assert wait(lambda: states(mgr) == {a: "RUNNING", b: "RUNNING"}
                        and len(col.of(a)) >= 5 and len(col.of(b)) >= 5, 30), mgr.status()
            st = {m["instance"]: m for m in mgr.status()}
            print("\nboth RUNNING after", round(time.monotonic() - t0, 2), "s;",
                  {k: (m["version"], m["fps"], m["results_total"]) for k, m in st.items()})
            assert (st[a]["name"], st[a]["version"]) == ("driverguard_dtcp", "a") and st[b]["version"] == "b"
            ra, rb = col.of(a)[-1], col.of(b)[-1]
            assert ra["model"] == rb["model"] == "driverguard_dtcp"
            assert ra["model_version"] == "a:1071ea90213eddc2" and rb["model_version"] == "b:1071ea90213eddc2"
            assert ra["cam"] == rb["cam"] == 0 and len(ra["trajectory"]["points"]) == 4

            # refused: duplicate key, no version, an ambiguous name; an unknown key
            ok, err = mgr.add_model(dtcp_cfg("a"))
            assert not ok and "exists already" in err
            ok, err = mgr.add_model(dict(dtcp_cfg("a"), version=""))
            assert not ok and "needs a version" in err
            r = mgr.stop_model("driverguard_dtcp")
            assert r["ok"] is False and "2 instances" in r["error"], r
            assert mgr.remove_model("nope@1") == (False, "no model instance nope@1")

            # remove a: its results stop, b runs on
            ok, txt = mgr.remove_model(a)
            assert ok, txt
            n_a, n_b = len(col.of(a)), len(col.of(b))
            time.sleep(1.0)
            print(f"after remove of {a}: a {n_a} -> {len(col.of(a))}, b {n_b} -> {len(col.of(b))}")
            assert len(col.of(a)) == n_a and len(col.of(b)) >= n_b + 5
            assert states(mgr) == {b: "RUNNING"}
            assert mgr.remove_model(a)[0] is False
            # the name has one instance now: stop / start by name work on b
            assert mgr.stop_model("driverguard_dtcp")["ok"] and states(mgr) == {b: "OFF"}
            assert mgr.start_model("driverguard_dtcp")["ok"] and states(mgr) == {b: "RUNNING"}

            # a again (same key after the remove), then a bad engine -> FAILED with the error
            assert mgr.add_model(dtcp_cfg("a")) == (True, a)
            assert wait(lambda: states(mgr).get(a) == "RUNNING", 30)
            assert mgr.add_model(dtcp_cfg("bad", engine=str(tmp_path / "missing.engine")))[0]
            assert wait(lambda: states(mgr).get("driverguard_dtcp@bad") == "FAILED", 10)
            bad = {m["instance"]: m for m in mgr.status()}["driverguard_dtcp@bad"]
            print("bad engine:", bad["state"], "|", bad["error"])
            assert "missing.engine" in bad["error"] and "no ONNX file configured" in bad["error"]
            assert mgr.remove_model("driverguard_dtcp@bad")[0]
            assert sorted(states(mgr)) == [a, b]
    finally:
        mgr.close()
    no_dupes(col.results)
    assert not mgr.add_model(dtcp_cfg("c"))[0]   # stopping / stopped manager: refused
    assert all(not t.name.startswith(("infer-", "load-")) for t in threading.enumerate())


# ---- fake engines (no GPU) ---------------------------------------------------------------------------------
class _T:
    def __init__(self, name, shape):
        self.name, self.shape, self.dtype = name, shape, "float32"


class FakeEngine:
    path = "/nonexistent/fake.engine"
    version_tag = "fake.engine:fakefakefakefake"
    sha256_16 = "fakefakefakefake"
    trt_match = True
    trt_build_device = "Orin GPU (sm87)"
    trt_device_warning = None
    trt_version = "fake"
    load_warnings: list = []

    def __init__(self):
        self.slots = []

    def inputs(self):
        return [_T("x", (1, 4))]

    def outputs(self):
        return [_T("y", (1, 4))]

    def gpu_bytes_estimate(self):
        return 0

    def new_slot(self):
        self.slots.append(self)
        return self

    def infer(self, inputs):
        return {"y": np.zeros((1, 4), np.float32)}, 0.1


class FakeAdapter:
    ENGINE_OUTPUTS = ("y",)

    def __init__(self, cfg, eng):
        pass

    def dummy_inputs(self):
        return {"x": np.zeros((1, 4), np.float32)}

    def preprocess(self, frame):
        return {"x": np.zeros((1, 4), np.float32)}, {}

    def postprocess(self, outs, frame, ctx):
        return {"detections": [], "trajectory": None, "masks": []}


def fake_manager(monkeypatch, tmp_path, results, load_s=0.0):
    from infer.models import manager as mm
    monkeypatch.setattr(mm, "get_adapter_class", lambda name: FakeAdapter)

    def try_engines(self, e):
        if load_s:
            time.sleep(load_s)
        e.engine_source = "config"
        return FakeEngine(), []

    monkeypatch.setattr(mm.ModelManager, "_try_engines", try_engines)
    store = FrameStore(range(6))
    mgr = mm.ModelManager([], store, results.append, engines_dir=str(tmp_path / "engines"), warmup=False)
    return mgr, store


def fake_cfg(name, version, cams=(0,)):
    return {"name": name, "version": version, "enabled": True, "engine": "/nonexistent/fake.engine",
            "onnx": None, "adapter": "fake", "cameras": list(cams), "workers": 1, "max_fps_per_camera": 50,
            "options": {}}


def test_status_is_safe_while_instances_are_added_and_removed(monkeypatch, tmp_path):
    results = []
    mgr, store = fake_manager(monkeypatch, tmp_path, results, load_s=0.01)
    errors, n_status = [], [0]
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            try:
                for m in mgr.status():
                    assert m["instance"].startswith("m") and "@" in m["instance"]
                _ = mgr.results_total, mgr.last_result_t
                n_status[0] += 1
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

    th = [threading.Thread(target=poll, daemon=True) for _ in range(2)]
    mgr.start()
    try:
        with Feeder(store, [0, 1], fps=50, w=64, h=32):
            for t in th:
                t.start()
            for i in range(15):
                keys = [mgr.add_model(fake_cfg(f"m{j}", str(i), cams=(j % 2,)))[1] for j in range(3)]
                assert all("@" in k for k in keys), keys
                time.sleep(0.03)
                for k in keys:
                    ok, txt = mgr.remove_model(k)
                    assert ok, txt
            ok, key = mgr.add_model(fake_cfg("m9", "v3"))
            assert ok and wait(lambda: states(mgr).get(key) == "RUNNING" and len(results) > 3, 5)
    finally:
        stop.set()
        for t in th:
            t.join(2)
        mgr.close()
    print(f"\nstatus calls during add/remove: {n_status[0]}, errors {errors[:3]}")
    assert not errors and n_status[0] > 10
    assert [m["instance"] for m in mgr.status()] == ["m9@v3"]
    r = [x for x in results if x["instance"] == "m9@v3"][-1]
    assert r["model"] == "m9" and r["model_version"] == "v3:fakefakefakefake"


def test_publisher_and_cache_keep_instances_apart():
    from infer.draw import corner_text
    from infer.publish.cache import ResultCache
    from infer.publish.results import ResultPublisher, normalize_result

    def res(instance, seq=7):
        name, _, ver = instance.partition("@")
        return {"model": name, "instance": instance, "model_version": f"{ver}:1071ea90213eddc2" if ver else "x:1",
                "cam": 0, "frame_seq": seq, "t_capture_ns": 1000 + seq, "t_ready_ns": 2000 + seq,
                "t_result_ns": 3000 + seq, "simulated": True, "source": "test-pattern",
                "detections": [], "trajectory": None, "masks": [], "timing": {}}

    assert normalize_result({"model": "driverguard_yolopx", "cam": 0})["instance"] == "driverguard_yolopx"
    ctx = zmq.Context()
    pub = ResultPublisher("127.0.0.1", P_PUB, ctx=ctx)
    try:
        ra = pub.publish(res("driverguard_dtcp@a"))
        rb = pub.publish(res("driverguard_dtcp@b"))      # same model name, cam and frame: another instance
        assert ra is not None and rb is not None
        assert (ra["instance"], rb["instance"]) == ("driverguard_dtcp@a", "driverguard_dtcp@b")
        assert pub.publish(res("driverguard_dtcp@a")) is None and pub.dropped_duplicate == 1
        assert pub.publish(res("driverguard_dtcp@a", seq=8)) is not None
    finally:
        pub.close()
        ctx.destroy(linger=0)
    cache = ResultCache()
    for r in (ra, rb, normalize_result(res("driverguard_yolopx"))):
        cache.add(r)
    got = cache.for_frame(0, 7)
    assert sorted(r["instance"] for r in got) == ["driverguard_dtcp@a", "driverguard_dtcp@b", "driverguard_yolopx"]
    assert cache.newest("driverguard_dtcp@b", 0)["model_version"] == "b:1071ea90213eddc2"
    assert corner_text(7, got) == "frame 7 | dtcp va 7 | dtcp vb 7 | yolopx 7"


def test_admin_instances_add_remove(monkeypatch, tmp_path):
    from infer.admin import AdminServer
    results = []
    mgr, store = fake_manager(monkeypatch, tmp_path, results)
    ctx = zmq.Context()
    adm = AdminServer(store, mgr, "127.0.0.1", P_ADM, ctx=ctx)
    adm.start()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, 5000)
    req.connect(f"tcp://127.0.0.1:{P_ADM}")

    def ask(obj):
        req.send(json.dumps(obj).encode())
        return json.loads(req.recv_multipart()[0])

    mgr.start()
    try:
        with Feeder(store, [0], fps=50, w=64, h=32):
            assert ask({"cmd": "instances"}) == {"ok": True, "instances": []}
            assert ask({"cmd": "add", "model": fake_cfg("yolo", "2")}) == {"ok": True, "key": "yolo@2"}
            assert wait(lambda: states(mgr) == {"yolo@2": "RUNNING"}, 5)
            r = ask({"cmd": "instances"})
            assert r["ok"] and [(m["instance"], m["name"], m["version"]) for m in r["instances"]] == \
                [("yolo@2", "yolo", "2")]
            assert ask({"cmd": "models"})["models"][0]["instance"] == "yolo@2"     # "models" is kept
            r = ask({"cmd": "add", "model": fake_cfg("yolo", "2")})
            assert r["ok"] is False and "exists already" in r["error"]
            r = ask({"cmd": "add", "model": "yolo@2"})
            assert r["ok"] is False and "'model'" in r["error"]
            r = ask({"cmd": "stop", "model": "yolo"})             # name with one instance
            assert r["ok"] and r["result"]["state"] == "OFF"
            assert ask({"cmd": "start", "model": "yolo@2"})["ok"]
            r = ask({"cmd": "remove", "key": "nope@1"})
            assert r == {"ok": False, "error": "no model instance nope@1"}
            assert ask({"cmd": "remove"})["ok"] is False
            assert ask({"cmd": "remove", "key": "yolo@2"}) == {"ok": True, "key": "yolo@2"}
            assert ask({"cmd": "instances"}) == {"ok": True, "instances": []}
            r = ask({"cmd": "bogus"})
            assert not r["ok"] and {"instances", "add", "remove"} <= set(r["commands"])
    finally:
        req.close(0)
        adm.stop()
        mgr.close()
        ctx.destroy(linger=0)


# ---- start set (infer.main.select_models) -------------------------------------------------------------------
def write_manifest(root, name="driverguard_dtcp", version="7", engine=DTCP_ENGINE):
    d = root / name / version
    d.mkdir(parents=True)
    m = {"schema": "agx-model-manifest/1", "name": name, "version": version, "type": "dtcp",
         "description": "test copy of the DTCP manifest (old engine by absolute path, read-only)",
         "files": [{"role": "engine", "path": engine, "sha256": DTCP_SHA256}],
         "input": {"tensors": [{"name": "image", "shape": [1, 3, 256, 928], "dtype": "FLOAT"},
                               {"name": "state", "shape": [1, 9], "dtype": "FLOAT"},
                               {"name": "target_point", "shape": [1, 2], "dtype": "FLOAT"}]},
         "outputs": {"tensors": [{"name": "pred_wp", "shape": [1, 4, 2], "dtype": "FLOAT"}],
                     "kinds": ["trajectory"]},
         "precision": "fp16", "cameras": {"permitted": [0], "default": [0]},
         "adapter": {"options": {"command": 2, "target": [0.0, 20.0], "ego_speed_mps": None}},
         "runtime": {"workers": 1, "max_fps_per_camera": 10}, "date": "2026-10-07"}
    (d / "manifest.yaml").write_text(yaml.safe_dump(m, sort_keys=False))


@pytest.fixture()
def start_cfg(tmp_path):
    from controller import runtime
    from controller.store import Store
    root = tmp_path / "store"
    write_manifest(root)
    models_yaml = tmp_path / "models.yaml"
    models_yaml.write_text(yaml.safe_dump({"models": [{"name": "legacy_model", "enabled": False,
                                                       "adapter": "none", "cameras": [0]}]}))
    store = Store(str(root))
    cfg = {"model_store": str(root), "start_set": "last_good", "models_config": str(models_yaml)}
    return cfg, store, runtime


def test_start_set_last_good_and_fallback(start_cfg):
    from infer.main import select_models
    cfg, store, runtime = start_cfg
    # no last_good.json -> config/models.yaml
    models, src, problems = select_models(cfg)
    print("\nno last good:", src, problems)
    assert [m["name"] for m in models["models"]] == ["legacy_model"] and "no last good set" in src
    assert problems == []
    # last good set: one runnable version, one that is not in the store
    runtime.write_set(store, runtime.LAST_GOOD, [{"name": "driverguard_dtcp", "version": "7", "cameras": [0]},
                                                 {"name": "nope", "version": "1", "cameras": [0]}],
                      "controller", "test", "test")
    models, src, problems = select_models(cfg)
    print("last good:", src, problems)
    assert "last good set" in src and "1 of 2 instances" in src and "driverguard_dtcp@7" in src
    assert problems == ["last good set: nope@1: not in the store"]
    (c,) = models["models"]
    assert (c["name"], c["version"], c["engine"], c["onnx"], c["adapter"], c["cameras"], c["enabled"]) == \
        ("driverguard_dtcp", "7", DTCP_ENGINE, None, "dtcp_v1", [0], True)
    assert c["max_fps_per_camera"] == 10 and c["options"]["command"] == 2
    # start_set models_yaml: always config/models.yaml
    models, src, problems = select_models(dict(cfg, start_set="models_yaml"))
    assert [m["name"] for m in models["models"]] == ["legacy_model"] and "start_set models_yaml" in src
    # unknown start_set -> models.yaml with a problem
    models, src, problems = select_models(dict(cfg, start_set="newest"))
    assert models["models"][0]["name"] == "legacy_model" and "not one of" in problems[0]
    # no version of the set can run -> models.yaml with the reasons
    runtime.write_set(store, runtime.LAST_GOOD, [{"name": "driverguard_dtcp", "version": "7", "cameras": [3]}],
                      "controller", "test", "test")
    models, src, problems = select_models(cfg)
    print("nothing runs:", src, problems)
    assert models["models"][0]["name"] == "legacy_model"
    assert "not permitted" in problems[0] and "config/models.yaml is used" in problems[-1]
    # an empty set -> models.yaml, no problem
    runtime.write_set(store, runtime.LAST_GOOD, [], "controller", "test", "test")
    models, src, problems = select_models(cfg)
    assert models["models"][0]["name"] == "legacy_model" and problems == [] and "no last good set" in src


@needs_engine
def test_start_set_runs(start_cfg, tmp_path):
    from infer.main import select_models
    from infer.models.manager import ModelManager
    cfg, store, runtime = start_cfg
    runtime.write_set(store, runtime.LAST_GOOD, [{"name": "driverguard_dtcp", "version": "7", "cameras": [0]}],
                      "controller", "test", "test")
    models, src, _problems = select_models(cfg)
    fs = FrameStore(range(6))
    col = Collector()
    mgr = ModelManager(models, fs, col, engines_dir=str(tmp_path / "engines"))
    try:
        with Feeder(fs, [0], fps=30):
            mgr.start()
            assert wait(lambda: len(col.of("driverguard_dtcp@7")) >= 3, 10), mgr.status()
            st = mgr.status()[0]
    finally:
        mgr.close()
    print("\nstart set", src, "->", st["instance"], st["state"], col.results[-1]["model_version"])
    assert st["instance"] == "driverguard_dtcp@7" and st["state"] == "RUNNING"
    assert col.results[-1]["model_version"] == "7:1071ea90213eddc2"
