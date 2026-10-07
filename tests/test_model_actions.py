"""Controller write side with a FAKE agx-infer admin (no GPU): control mode (M7), one change at a time (M4), audit
(M3), checks before activation (M5), the watchdog with rollback (M6), deactivate, rollback and build."""
import hashlib
import json
import os
import stat
import sys
import threading
import time

import yaml

from controller import audit
from controller import manifest as mf
from controller.control import Controller
from controller.runtime import ACTIVE, LAST_GOOD, read_set, write_set
from controller.store import Store


def man(name, version="1", engine=True, onnx=False, cams=(0, 1)):
    files = []
    if engine:
        files.append({"role": "engine", "path": "m.engine", "sha256": "a" * 64})
    if onnx:
        files.append({"role": "onnx", "path": "model.onnx", "sha256": hashlib.sha256(b"onnx").hexdigest()})
    return {"schema": mf.SCHEMA, "name": name, "version": version, "type": "yolopx", "description": "test",
            "files": files, "input": {"tensors": [{"name": "image", "shape": [1, 3, 8, 8], "dtype": "FLOAT"}]},
            "outputs": {"tensors": [{"name": "det", "shape": [1, 4], "dtype": "FLOAT"}], "kinds": ["boxes"]},
            "precision": "fp16", "cameras": {"permitted": list(cams), "default": [cams[0]]},
            "build": {"shapes": "image:1x3x8x8"}, "date": "2026-10-07"}


def put(root, d):
    vd = os.path.join(root, d["name"], d["version"])
    os.makedirs(vd, exist_ok=True)
    if any(f["role"] == "engine" for f in d["files"]):
        open(os.path.join(vd, "m.engine"), "wb").write(b"ftrt")
    if any(f["role"] == "onnx" for f in d["files"]):
        open(os.path.join(vd, "model.onnx"), "wb").write(b"onnx")
    with open(os.path.join(vd, "manifest.yaml"), "w") as f:
        yaml.safe_dump(d, f)


class FakeChecks:
    def __init__(self, ok=True):
        self.ok, self.requested = ok, []

    def result(self, key):
        return {"ok": self.ok, "reason": None if self.ok else "sha256 differs", "gpu_need_mb": 10.0}

    def busy(self):
        return None

    def pending(self):
        return []

    def request(self, m):
        self.requested.append(m.key)

    def stop(self):
        pass


class FakeAdmin:
    """agx-infer instances in memory. mode per key: ok | no_results | fail | refuse."""

    def __init__(self):
        self.inst, self.mode, self.block = {}, {}, None

    def instances(self):
        for k, i in self.inst.items():
            m = self.mode.get(k, "ok")
            if m == "ok":
                i["state"], i["results_total"] = "RUNNING", i["results_total"] + 1
            elif m == "fail":
                i["state"], i["error"] = "FAILED", "3 errors in a row"
            else:
                i["state"] = "RUNNING"
        return [dict(v) for v in self.inst.values()], None

    def add(self, cfg):
        if self.block is not None:
            self.block.wait(10)
        k = f"{cfg['name']}@{cfg['version']}"
        if self.mode.get(k) == "refuse":
            return False, "engine does not load"
        if k in self.inst:
            return False, f"duplicate {k}"
        self.inst[k] = {"instance": k, "name": cfg["name"], "version": cfg["version"], "cameras": cfg["cameras"],
                        "state": "LOADING", "results_total": 0, "error": None}
        return True, k

    def remove(self, key):
        return (True, "") if self.inst.pop(key, None) is not None else (False, f"no model instance {key}")


class FakeInfer:
    def __init__(self, admin):
        self.admin = admin

    def current(self):
        ms = [{"name": i["name"], "version": i["version"], "instance": k, "state": i["state"], "cameras": i["cameras"],
               "results_total": i["results_total"]} for k, i in self.admin.inst.items()]
        return {"models": ms}, "OK", None, 0.0


def make(tmp_path, ok=True, watchdog_s=1.5):
    root = str(tmp_path / "store")
    put(root, man("a"))
    put(root, man("b"))
    put(root, dict(man("c"), type="system1"))
    admin = FakeAdmin()
    admin.add({"name": "a", "version": "1", "cameras": [0]})            # a@1 runs before the test
    admin.instances()
    store = Store(root)
    write_set(store, LAST_GOOD, [{"name": "a", "version": "1", "cameras": [0]}], "controller", "test", "start")
    ctl = Controller(root, str(tmp_path), str(tmp_path / "control.yaml"), FakeInfer(admin), FakeChecks(ok), admin,
                     watchdog_s=watchdog_s)
    return ctl, admin, store


def wait_done(ctl, t=10.0):
    end = time.time() + t
    while ctl.change is not None and time.time() < end:
        time.sleep(0.05)
    assert ctl.change is None, "the change did not end"
    return ctl.last_change


def test_activate_ok_writes_sets_and_audit(tmp_path):
    ctl, admin, store = make(tmp_path)
    code, doc = ctl.request("activate", "b", "1", {"cameras": [1]}, "rk-console", "owner")
    assert code == 202 and doc["ok"] and doc["change"]["model"] == "b@1"
    lc = wait_done(ctl)
    assert lc["result"] == "ok", lc
    assert {(i["name"], tuple(i["cameras"])) for i in read_set(store, LAST_GOOD)["set"]} == {("a", (0,)), ("b", (1,))}
    assert read_set(store, ACTIVE)["set"] == read_set(store, LAST_GOOD)["set"]
    ev = audit.read(store.state)
    assert [(e["action"], e["result"], e["source"], e["user"]) for e in ev[:2]] == [
        ("activate", "ok", "rk-console", "owner"), ("activate", "started", "rk-console", "owner")]
    assert ev[0]["cameras"] == [1]


def test_watchdog_no_result_rolls_back(tmp_path):
    ctl, admin, store = make(tmp_path, watchdog_s=1.0)
    admin.mode["b@1"] = "no_results"
    assert ctl.request("activate", "b", "1", {}, "agx-dashboard", "agx")[0] == 202
    lc = wait_done(ctl)
    assert lc["result"] == "failed" and "no valid result in 1 s" in lc["reason"]
    assert "the last good set runs again" in lc["reason"]
    assert "b@1" not in admin.inst and admin.inst["a@1"]["state"] == "RUNNING"
    row = ctl.row("b@1")
    assert row["state"] == "FAILED" and "no valid result" in row["reason"]
    assert read_set(store, LAST_GOOD)["set"] == [{"name": "a", "version": "1", "cameras": [0]}]
    admin.mode["b@1"] = "ok"                                    # a watchdog failure can be tried again
    assert ctl.request("activate", "b", "1", {}, "agx-dashboard", "agx")[0] == 202
    assert wait_done(ctl)["result"] == "ok" and ctl.row("b@1")["state"] == "ACTIVE"


def test_watchdog_failed_instance_rolls_back(tmp_path):
    ctl, admin, store = make(tmp_path)
    admin.mode["b@1"] = "fail"
    ctl.request("activate", "b", "1", {}, "agx-dashboard", "agx")
    lc = wait_done(ctl)
    assert lc["result"] == "failed" and "failed in agx-infer: 3 errors in a row" in lc["reason"]
    assert set(admin.inst) == {"a@1"}


def test_refusals(tmp_path):
    ctl, admin, store = make(tmp_path)
    assert ctl.request("activate", "zzz", "1")[0] == 404
    code, doc = ctl.request("activate", "c", "1")
    assert code == 409 and "NO ADAPTER" in doc["reason"]
    code, doc = ctl.request("activate", "a", "1")
    assert code == 409 and "already active" in doc["reason"]
    code, doc = ctl.request("activate", "b", "1", {"cameras": [5]})
    assert code == 409 and "not permitted" in doc["reason"]
    code, doc = ctl.request("deactivate", "b", "1")
    assert code == 409 and "not active" in doc["reason"]
    assert ctl.request("activate", "b", "1", {"cameras": "x"})[0] == 400
    assert ctl.request("explode")[0] == 400
    assert all(e["result"] == "refused" for e in audit.read(store.state))


def test_checks_must_pass(tmp_path):
    ctl, admin, store = make(tmp_path, ok=False)
    code, doc = ctl.request("activate", "b", "1")
    assert code == 409 and "checks failed" in doc["reason"]


def test_vehicle_mode_refuses_everything(tmp_path):
    ctl, admin, store = make(tmp_path)
    (tmp_path / "control.yaml").write_text("control_mode: vehicle\n")
    for args in (("activate", "b", "1"), ("deactivate", "a", "1"), ("build", "b", "1"), ("rollback",)):
        code, doc = ctl.request(*args)
        assert code == 409 and doc["reason"].startswith("control mode is vehicle"), args
    assert set(admin.inst) == {"a@1"}
    (tmp_path / "control.yaml").write_text("control_mode: bench\n")
    assert ctl.request("activate", "b", "1")[0] == 202
    wait_done(ctl)


def test_one_change_at_a_time(tmp_path):
    ctl, admin, store = make(tmp_path)
    admin.block = threading.Event()
    assert ctl.request("activate", "b", "1", {}, "agx-dashboard", "one")[0] == 202
    code, doc = ctl.request("deactivate", "a", "1", {}, "rk-console", "two")
    assert code == 409 and doc["reason"].startswith("another change runs now: activate b@1")
    admin.block.set()
    assert wait_done(ctl)["result"] == "ok"


def test_deactivate_and_rollback(tmp_path):
    ctl, admin, store = make(tmp_path)
    assert ctl.request("deactivate", "a", "1")[0] == 202
    assert wait_done(ctl)["result"] == "ok" and admin.inst == {}
    assert read_set(store, LAST_GOOD)["set"] == []                  # the operator's new set
    code, doc = ctl.request("rollback")
    assert code == 409 and doc["reason"] == "no last good set is stored yet"
    write_set(store, LAST_GOOD, [{"name": "a", "version": "1", "cameras": [0]}], "controller", "test", "x")
    assert ctl.request("rollback")[0] == 202
    assert wait_done(ctl)["result"] == "ok" and set(admin.inst) == {"a@1"}
    assert ctl.request("rollback")[1]["reason"] == "the active set is already the last good set"


def test_build_with_fake_trtexec(tmp_path):
    ctl, admin, store = make(tmp_path)
    put(store.root, man("d", engine=False, onnx=True))
    fake = tmp_path / "trtexec"
    fake.write_text("#!" + sys.executable + "\nimport sys, time\n"
                    "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--saveEngine=')][0]\n"
                    "print('building', sys.argv[1:]); time.sleep(0.5); open(out, 'wb').write(b'ftrt-built')\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    ctl.trtexec = str(fake)
    assert ctl.row("d@1")["state"] == "NEEDS BUILD"
    code, doc = ctl.request("build", "d", "1", {}, "agx-dashboard", "agx")
    assert code == 202 and "fewer results" in doc["warning"]
    code2, doc2 = ctl.request("activate", "b", "1")
    assert code2 == 409 and "another change runs now: build d@1" in doc2["reason"]
    lc = wait_done(ctl)
    assert lc["result"] == "ok", lc
    info = json.loads((store.root / "d" / "1" / "build.json").read_text())
    assert info["state"] == "done" and info["engine"] == "d_1_fp16.engine"
    assert (store.root / "d" / "1" / "d_1_fp16.engine").read_bytes() == b"ftrt-built"
    assert ctl.checks.requested[-1] == "d@1"                        # checks queued for the new engine
    assert "--fp16" in (store.root / "d" / "1" / "build.log").read_text()
