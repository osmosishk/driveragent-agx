"""Model store, manifest and catalog states (controller/manifest.py, store.py, catalog.py, control.py). Pure: no GPU."""
import copy
import os

import pytest
import yaml

from controller import catalog, manifest as mf
from controller.control import Controller, read_control_mode
from controller.store import Store

SHA = "a" * 64
GOOD = {
    "schema": mf.SCHEMA, "name": "det_model", "version": "1", "type": "yolopx", "description": "test model",
    "files": [{"role": "engine", "path": "det_model_1_fp16.engine", "sha256": SHA}],
    "input": {"tensors": [{"name": "image", "shape": [1, 3, 384, 640], "dtype": "FLOAT"}],
              "size": {"width": 640, "height": 384}, "colour_order": "RGB", "normalisation": "x/255"},
    "outputs": {"tensors": [{"name": "det", "shape": [1, 5040, 15], "dtype": "FLOAT"}], "kinds": ["boxes"]},
    "precision": "fp16", "cameras": {"permitted": [0, 1], "default": [0]},
    "adapter": {"class_names": ["a", "b"], "score_limit": 0.3, "options": {"iou_thres": 0.45}},
    "runtime": {"workers": 2, "max_fps_per_camera": 30}, "date": "2026-10-07",
}


def put(store_root, d, engine=True, onnx=False):
    vd = os.path.join(store_root, d["name"], d["version"])
    os.makedirs(vd, exist_ok=True)
    d = copy.deepcopy(d)
    if onnx:
        d["files"].append({"role": "onnx", "path": "model.onnx", "sha256": SHA})
        open(os.path.join(vd, "model.onnx"), "wb").write(b"onnx")
    if engine:
        open(os.path.join(vd, "det_model_1_fp16.engine"), "wb").write(b"ftrt")
    with open(os.path.join(vd, "manifest.yaml"), "w") as f:
        yaml.safe_dump(d, f)
    return mf.load(vd)


class FakeChecks:
    def __init__(self, results=None, busy=None, pending=()):
        self.results, self._busy, self._pending, self.requested = dict(results or {}), busy, list(pending), []

    def result(self, key):
        return self.results.get(key)

    def busy(self):
        return self._busy

    def pending(self):
        return self._pending

    def request(self, m):
        self.requested.append(m.key)


def test_manifest_valid_and_errors(tmp_path):
    m = put(tmp_path, GOOD)
    assert m.errors == [] and m.key == "det_model@1" and m.adapter == "yolopx_v2"
    assert m.adapter_options() == {"iou_thres": 0.45, "conf_thres": 0.3, "class_names": ["a", "b"]}
    assert m.file("engine")["path"] == os.path.join(str(tmp_path), "det_model", "1", "det_model_1_fp16.engine")
    bad = dict(GOOD, version=2, precision="fp64", cameras={"permitted": [0, 7], "default": [0]})
    m2 = put(tmp_path, dict(bad, version="2"))
    assert m2.errors == ["precision must be one of fp16, fp32, int8, mixed",
                         "cameras.permitted must be a list of camera ids 0..5"]
    errs = mf.validate(bad, str(tmp_path / "det_model" / "2"))
    assert any("version must be a quoted string" in e for e in errs)
    os.makedirs(tmp_path / "x" / "1")
    assert mf.load(str(tmp_path / "x" / "1")).errors[0].startswith("no manifest.yaml")


def test_catalog_states(tmp_path):
    store = Store(str(tmp_path))
    put(tmp_path, GOOD)                                                     # engine, check ok -> READY
    put(tmp_path, dict(GOOD, name="needs_build", files=[]), engine=False, onnx=True)
    put(tmp_path, dict(GOOD, name="no_files", files=[]), engine=False)      # -> FAILED
    put(tmp_path, dict(GOOD, name="odd_type", type="sparsedrive_backbone", files=[]), engine=False)
    put(tmp_path, dict(GOOD, name="registered"))                            # no check yet
    put(tmp_path, dict(GOOD, name="bad_check"))
    put(tmp_path, dict(GOOD, name="running"))
    os.makedirs(tmp_path / "_state")                                        # reserved: not a model
    checks = FakeChecks({"det_model@1": {"ok": True}, "bad_check@1": {"ok": False, "reason": "sha256 differs"},
                         "running@1": {"ok": True}}, busy="registered@1")
    live = [{"name": "running", "version": "1", "state": "RUNNING", "cameras": [0], "fps": 7.0,
             "lat_ms": {"total": {"p50": 80, "p95": 110, "p99": 130}}}]
    rows = {r["key"]: r for r in catalog.build(store, checks, live)}
    assert set(rows) == {"det_model@1", "needs_build@1", "no_files@1", "odd_type@1", "registered@1", "bad_check@1",
                         "running@1"}
    assert rows["det_model@1"]["state"] == "READY" and rows["det_model@1"]["reason"] is None
    assert rows["needs_build@1"]["state"] == "NEEDS BUILD"
    assert rows["no_files@1"]["state"] == "FAILED" and rows["no_files@1"]["reason"] == "no engine file and no ONNX file"
    assert rows["odd_type@1"]["state"] == "NO ADAPTER" and "sparsedrive_backbone" in rows["odd_type@1"]["reason"]
    assert rows["registered@1"]["state"] == "REGISTERED" and rows["registered@1"]["reason"] == "checks running now"
    assert rows["bad_check@1"]["state"] == "FAILED" and rows["bad_check@1"]["reason"] == "check failed: sha256 differs"
    r = rows["running@1"]
    assert r["state"] == "ACTIVE" and r["live"]["fps"] == 7.0 and r["live"]["latency_ms"]["p95"] == 110
    live[0]["state"] = "FAILED"
    live[0]["error"] = "3 errors in a row"
    rows = {r["key"]: r for r in catalog.build(store, checks, live)}
    assert rows["running@1"]["state"] == "FAILED" and "3 errors in a row" in rows["running@1"]["reason"]


def test_active_without_version_matched_by_engine(tmp_path):
    """agx-infer before N3 sends no version: an engine path match finds the version."""
    store = Store(str(tmp_path))
    m = put(tmp_path, GOOD)
    live = [{"name": "det_model", "engine": m.file("engine")["path"], "state": "RUNNING"}]
    rows = catalog.build(store, FakeChecks(), live)
    assert rows[0]["state"] == "ACTIVE"
    live[0]["engine"] = "/elsewhere/x.engine"
    assert catalog.build(store, FakeChecks(), live)[0]["state"] == "REGISTERED"


def test_control_mode_file(tmp_path):
    f = tmp_path / "control.yaml"
    assert read_control_mode(f)[0] == "bench"                               # no file: the default
    f.write_text("control_mode: vehicle\n")
    assert read_control_mode(f) == ("vehicle", None)
    f.write_text("control_mode: race\n")
    mode, problem = read_control_mode(f)
    assert mode == "vehicle" and "not bench or vehicle" in problem         # a bad value refuses changes


def test_controller_scan_queues_checks_and_writes_snapshot(tmp_path):
    put(tmp_path, GOOD)
    put(tmp_path, dict(GOOD, name="odd_type", type="system1", files=[]), engine=False)
    checks = FakeChecks()
    c = Controller(str(tmp_path), str(tmp_path), str(tmp_path / "control.yaml"), None, checks)
    c.scan()
    assert checks.requested == ["det_model@1"]                              # NO ADAPTER is not checked
    snap = catalog.snapshot(c.rows(), "bench")
    assert {(e["name"], e["state"]) for e in snap["entries"]} == {("det_model", "REGISTERED"), ("odd_type", "NO ADAPTER")}
    assert (tmp_path / "_state" / "catalog.json").is_file()
    doc = c.catalog_doc()
    assert doc["control_mode"] == "bench" and doc["counts"]["NO ADAPTER"] == 1 and len(doc["entries"]) == 2


@pytest.mark.parametrize("name,ok", [("good_name_1", True), ("Bad", False), ("_state", False), ("a" * 49, False)])
def test_name_rule(name, ok):
    assert bool(mf.NAME_RE.match(name)) is ok
