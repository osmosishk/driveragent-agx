"""ModelManager + ModelWorker tests with synthetic NV12 frames in a FrameStore (no network).

  - a model with a corrupt engine and no ONNX -> FAILED with the error text; DTCP runs at the same time
  - a model whose frames are bad (worker exceptions) -> FAILED; the other model continues
  - disabled model -> OFF with its reason
  - stop_model / start_model; no result is sent twice or after a newer one; rate limit 10 Hz
  - two workers on three cameras: no duplicate (cam, seq), every camera served
  - fallback: engine does not load + ONNX exists -> trtexec is called (fake trtexec that copies the
    DTCP engine), the engine is written ONLY into engines_dir, the old engine is not changed
GPU use: the DTCP engine only (~5 ms per inference). Run time about 20 s.
"""
import hashlib
import os
import stat
import threading
import time

import numpy as np
import pytest

from common import trt_compat
from infer.ingest.frame_store import Frame, FrameStore
from infer.models.manager import ModelManager

DTCP_ENGINE = "/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine"
DTCP_ONNX = "/home/tonyho/model/jetson_bundle/onnx/dtcp_v1.onnx"
FORBIDDEN = {"throttle", "steer", "brake", "mu", "sigma", "pred_speed", "pred_speed_mps"}
CONTRACT_KEYS = {"name", "engine", "engine_version", "state", "error", "reason", "enabled", "cameras", "fps",
                 "lat_ms", "gpu_mem_mb", "gpu_mem_note", "trt_match", "trt_build_device", "trt_device_warning",
                 "trt_version", "load_warnings", "inputs", "outputs", "results_total"}

pytestmark = pytest.mark.skipif(not os.path.isfile(DTCP_ENGINE), reason="DTCP engine missing")


def dtcp_cfg(name="driverguard_dtcp", cams=(0,), workers=1, max_fps=10, engine=DTCP_ENGINE, onnx=DTCP_ONNX):
    return {"name": name, "group": "driverguard", "enabled": True, "engine": engine, "onnx": onnx,
            "adapter": "dtcp_v1", "cameras": list(cams), "workers": workers, "max_fps_per_camera": max_fps,
            "options": {"command": 2, "target": [0.0, 20.0], "ego_speed_mps": None}}


class Feeder:
    """Puts synthetic NV12 frames into the store at `fps` for each camera. bad_cams get NV12 data
    of the wrong shape (the adapter raises)."""

    def __init__(self, store, cams, fps=30.0, bad_cams=()):
        self.store, self.cams, self.period, self.bad = store, list(cams), 1.0 / fps, set(bad_cams)
        self.seq = 0
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        rng = np.random.default_rng(0)
        while not self._stop.is_set():
            self.seq += 1
            for cam in self.cams:
                w, h = (1280, 720) if cam == 0 else (704, 396)
                nv = rng.integers(16, 235, size=(h * 3 // 2, w), dtype=np.uint8)
                if cam in self.bad:
                    nv = nv[: h]  # wrong shape
                now = time.time_ns()
                self.store.put(Frame(cam, self.seq, now, now, now, w, h, "nv12", "test-pattern", nv))
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

    def of(self, model):
        with self.lock:
            return [r for r in self.results if r["model"] == model]


def walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from walk_keys(v)


def no_dupes(results):
    keys = [(r["model"], r["cam"], r["frame_seq"]) for r in results]
    assert len(keys) == len(set(keys)), "duplicate (model, cam, seq)"
    last = {}
    for r in results:  # per camera the seq only goes up (never an old result after a newer one)
        k = (r["model"], r["cam"])
        assert r["frame_seq"] > last.get(k, -1)
        last[k] = r["frame_seq"]


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    """Folder for test files: under the pytest base temp (--basetemp), not a fixed path in /tmp."""
    return str(tmp_path_factory.mktemp("manager"))


@pytest.fixture(scope="module", autouse=True)
def bad_engine(scratch):
    path = os.path.join(scratch, "bad.engine")
    with open(path, "wb") as f:
        f.write(np.random.default_rng(1).integers(0, 256, size=1 << 20, dtype=np.uint8).tobytes())
    yield path


def test_failed_model_is_isolated_and_stop_start(bad_engine, scratch):
    store = FrameStore(range(6))
    col = Collector()
    cfg = [
        {"name": "bad_model", "enabled": True, "engine": bad_engine, "onnx": None, "adapter": "yolopx_v2",
         "cameras": [0], "workers": 1, "max_fps_per_camera": 30, "options": {}},
        dtcp_cfg(),
        dtcp_cfg(name="dtcp_badframes", cams=(3,), max_fps=30),
        {"name": "system1", "enabled": False, "engine": None, "adapter": "none", "cameras": [0, 1],
         "reason": "Not a TensorRT model"},
    ]
    mgr = ModelManager(cfg, store, col, engines_dir=os.path.join(scratch, "engines_test"))
    try:
        with Feeder(store, [0, 3], fps=30, bad_cams=[3]):
            mgr.start()
            time.sleep(3.0)
            st = {m["name"]: m for m in mgr.status()}
            for m in st.values():
                assert CONTRACT_KEYS <= set(m)
            bad = st["bad_model"]
            print("\nbad_model:", bad["state"], "|", bad["error"])
            assert bad["state"] == "FAILED" and bad["error_t"] is not None
            assert "bad.engine" in bad["error"] and "no ONNX file configured" in bad["error"]
            bf = st["dtcp_badframes"]
            print("dtcp_badframes:", bf["state"], "|", bf["error"])
            assert bf["state"] == "FAILED" and "NV12 shape" in bf["error"] and bf["results_total"] == 0
            s1 = st["system1"]
            assert s1["state"] == "OFF" and s1["reason"] == "Not a TensorRT model" and s1["enabled"] is False
            d = st["driverguard_dtcp"]
            print("driverguard_dtcp:", d["state"], "fps", d["fps"], "results", d["results_total"],
                  "lat_ms", d["lat_ms"]["total"], "gpu_mem_mb", d["gpu_mem_mb"], d["engine_version"])
            assert d["state"] == "RUNNING" and d["error"] is None
            # trt_match: loads with the installed TensorRT + built on an Orin GPU (common/trt_compat.py).
            # The TensorRT device warning depends on the boot (total memory) and is information only.
            assert d["trt_match"] is True and d["trt_build_device"] == "Orin GPU (sm87)"
            assert d["trt_device_warning"] == trt_compat.device_warning(d["load_warnings"])
            assert d["results_total"] >= 20 and d["fps"] <= 11.5
            assert d["lat_ms"]["infer"]["p50"] is not None
            assert [i["name"] for i in d["inputs"]] == ["image", "state", "target_point"]
            res = col.of("driverguard_dtcp")
            assert len(res) == d["results_total"]
            r = res[-1]
            assert r["simulated"] is True and r["source"] == "test-pattern" and r["cam"] == 0
            assert (r["frame_w"], r["frame_h"]) == (1280, 720) and r["detections"] == [] and r["masks"] == []
            assert r["trajectory"]["inputs_valid"] is False and len(r["trajectory"]["points"]) == 4
            assert r["model_version"] == "dtcp_v1_fp16.engine:1071ea90213eddc2"
            assert set(r["timing"]) == {"queue_ms", "pre_ms", "infer_ms", "post_ms", "total_ms"}
            assert r["t_result_ns"] >= r["t_ready_ns"]
            assert not (FORBIDDEN & set(walk_keys(col.results)))

            # stop_model -> OFF, no new results; engine stays loaded
            assert mgr.stop_model("driverguard_dtcp")["ok"]
            n_stop = len(col.of("driverguard_dtcp"))
            last_seq = col.of("driverguard_dtcp")[-1]["frame_seq"]
            time.sleep(0.8)
            d = {m["name"]: m for m in mgr.status()}["driverguard_dtcp"]
            assert d["state"] == "OFF" and d["engine_version"] is not None and d["gpu_mem_mb"] > 0
            assert len(col.of("driverguard_dtcp")) == n_stop
            # start_model -> RUNNING, new results only for newer frames
            assert mgr.start_model("driverguard_dtcp") == {"ok": True, "state": "RUNNING", "error": None}
            time.sleep(1.0)
            after = col.of("driverguard_dtcp")[n_stop:]
            print(f"stop/start: {n_stop} results before stop, {len(after)} after start")
            assert len(after) >= 5 and min(r["frame_seq"] for r in after) > last_seq
            assert {m["name"]: m for m in mgr.status()}["driverguard_dtcp"]["state"] == "RUNNING"
            # a model with no adapter cannot start, it stays OFF
            assert mgr.start_model("system1")["ok"] is False
            assert {m["name"]: m for m in mgr.status()}["system1"]["state"] == "OFF"
            assert mgr.start_model("nope")["ok"] is False
    finally:
        mgr.close()
    no_dupes(col.results)
    assert all(not t.name.startswith("infer-") for t in threading.enumerate())


def test_two_workers_three_cameras_no_duplicates(scratch):
    store = FrameStore(range(6))
    col = Collector()
    mgr = ModelManager([dtcp_cfg(name="dtcp_multi", cams=(0, 1, 2), workers=2, max_fps=30)], store, col,
                       engines_dir=os.path.join(scratch, "engines_test"))
    try:
        with Feeder(store, [0, 1, 2], fps=30):
            mgr.start()
            time.sleep(3.0)
            st = mgr.status()[0]
    finally:
        mgr.close()
    res = col.results
    per_cam = {c: sum(1 for r in res if r["cam"] == c) for c in (0, 1, 2)}
    print(f"\n2 workers, 3 cams: results {len(res)} per cam {per_cam} fps {st['fps']} cam_fps {st['cam_fps']} "
          f"dropped_old {st['results_dropped_old']} lat total {st['lat_ms']['total']}")
    no_dupes(res)
    assert all(n >= 10 for n in per_cam.values())
    assert max(per_cam.values()) - min(per_cam.values()) <= max(5, 0.25 * max(per_cam.values()))
    assert {(r["frame_w"], r["frame_h"]) for r in res if r["cam"] == 1} == {(704, 396)}


def test_rebuild_fallback_with_fake_trtexec(bad_engine, scratch):
    """The trtexec fallback flow, without a real 5-10 min build: a fake trtexec copies the DTCP engine
    to --saveEngine. Checks the command line, the output folder and that the old engine is unchanged."""
    eng_dir = os.path.join(scratch, "engines_fallback_test")
    os.makedirs(eng_dir, exist_ok=True)
    for f in os.listdir(eng_dir):
        os.remove(os.path.join(eng_dir, f))
    args_file = os.path.join(scratch, "fake_trtexec.args")
    fake = os.path.join(scratch, "fake_trtexec.sh")
    with open(fake, "w") as f:
        f.write("#!/bin/sh\n"
                f'echo "$@" > {args_file}\n'
                'for a in "$@"; do case "$a" in --saveEngine=*) out="${a#--saveEngine=}";; esac; done\n'
                f'cp {DTCP_ENGINE} "$out"\n'
                'echo "&&&& PASSED fake"\n')
    os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
    sha_before = hashlib.sha256(open(bad_engine, "rb").read()).hexdigest()
    store = FrameStore(range(6))
    col = Collector()
    mgr = ModelManager([dtcp_cfg(name="dtcp_rebuilt", engine=bad_engine)], store, col, engines_dir=eng_dir,
                       trtexec=fake)
    try:
        with Feeder(store, [0], fps=30):
            mgr.start()
            t0 = time.monotonic()
            while mgr.status()[0]["state"] in ("LOADING",) and time.monotonic() - t0 < 30:
                time.sleep(0.1)
            time.sleep(1.5)
            st = mgr.status()[0]
    finally:
        mgr.close()
        listing = sorted(os.listdir(eng_dir))
        for f in listing:  # the copied 56 MB engine is not kept
            os.remove(os.path.join(eng_dir, f))
    args = open(args_file).read().split()
    print("\nfake trtexec args:", args)
    print("state", st["state"], "engine", st["engine"], "source", st["engine_source"], "reason", st["reason"])
    assert args == [f"--onnx={DTCP_ONNX}", f"--saveEngine={eng_dir}/dtcp_rebuilt_fp16.engine.partial", "--fp16",
                    "--shapes=image:1x3x256x928,state:1x9,target_point:1x2"]
    assert st["state"] == "RUNNING" and st["engine_source"] == "rebuilt"
    assert st["engine"] == f"{eng_dir}/dtcp_rebuilt_fp16.engine" and st["results_total"] > 0
    assert listing == ["dtcp_rebuilt_fp16.engine", "dtcp_rebuilt_fp16.engine.build.log"]
    assert hashlib.sha256(open(bad_engine, "rb").read()).hexdigest() == sha_before
    no_dupes(col.results)


def test_engines_dir_under_model_folder_is_refused():
    with pytest.raises(ValueError):
        ModelManager([], FrameStore(range(6)), lambda r: None, engines_dir="/home/tonyho/model/jetson_bundle/engines")
