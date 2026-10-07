"""trt_match rule (owner decision 2026-10-07): the engine loads with the installed TensorRT AND its build
device is an Orin GPU. The TensorRT device warning is information only (trt_device_warning)."""
import json
import os
import subprocess

import pytest

from common import trt_compat
from tools import inspect_engines as ie

YOLOPX = "/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine"
DEV_WARN = ("WARNING: Using an engine plan file across different models of devices is not recommended and is "
            "likely to affect performance or even cause errors.")


def test_verdict():
    assert trt_compat.verdict(False, "NONE", True) == (False, None)
    assert trt_compat.verdict(True, "NONE", True) == (True, "Orin GPU (sm87)")
    ok, dev = trt_compat.verdict(True, "NONE", False)
    assert ok is False and "not an Orin" in dev
    ok, dev = trt_compat.verdict(True, "AMPERE_PLUS", True)
    assert ok is False and dev.startswith("unknown") and "AMPERE_PLUS" in dev
    ok, dev = trt_compat.verdict(True, None, True)
    assert ok is False and dev.startswith("unknown")


def test_device_warning_is_separate():
    assert trt_compat.device_warning([]) is None and trt_compat.device_warning(None) is None
    assert trt_compat.device_warning(["WARNING: some other warning"]) is None
    stderr_form = "[TRT] [W] Using an engine plan file across different models of devices is not recommended"
    assert trt_compat.device_warning([stderr_form, DEV_WARN]) == DEV_WARN      # the logger form first
    assert trt_compat.device_warning([stderr_form]) == stderr_form


def test_host_is_orin(tmp_path):
    f = tmp_path / "compatible"
    f.write_bytes(b"nvidia,p3737-0000+p3701-0005\0nvidia,p3701-0005\0nvidia,tegra234\0")
    assert trt_compat.host_is_orin(str(f)) is True
    f.write_bytes(b"nvidia,p2822-0000+p2888-0001\0nvidia,tegra194\0")              # Xavier: not Orin
    assert trt_compat.host_is_orin(str(f)) is False
    f.write_bytes(b"nvidia,tegra2340\0")                                          # no partial match
    assert trt_compat.host_is_orin(str(f)) is False
    assert trt_compat.host_is_orin(str(tmp_path / "missing")) is False


def _fake_child(monkeypatch, child: dict, orin: bool = True):
    def run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 0, stdout="JSON:" + json.dumps(child), stderr="")
    monkeypatch.setattr(ie.subprocess, "run", run)
    monkeypatch.setattr(ie.trt_compat, "host_is_orin", lambda: orin)


def test_inspect_device_warning_does_not_change_match(monkeypatch, tmp_path):
    f = tmp_path / "x.engine"
    f.write_bytes(b"ftrt" + b"\0" * 60)
    _fake_child(monkeypatch, {"load": "OK", "messages": [DEV_WARN], "hw_compat": "NONE", "io": []})
    r = ie.inspect(str(f))
    assert r["trt_match"] is True and r["trt_build_device"] == "Orin GPU (sm87)"
    assert r["trt_device_warning"] == DEV_WARN and r["messages"] == [DEV_WARN]
    _fake_child(monkeypatch, {"load": "OK", "messages": [], "hw_compat": "NONE", "io": []})
    r = ie.inspect(str(f))
    assert r["trt_match"] is True and r["trt_device_warning"] is None
    _fake_child(monkeypatch, {"load": "OK", "messages": [], "hw_compat": "AMPERE_PLUS", "io": []})
    assert ie.inspect(str(f))["trt_match"] is False
    _fake_child(monkeypatch, {"load": "OK", "messages": [], "hw_compat": "NONE", "io": []}, orin=False)
    assert ie.inspect(str(f))["trt_match"] is False
    _fake_child(monkeypatch, {"load": "FAILED", "messages": [], "error": "x"})
    r = ie.inspect(str(f))
    assert r["trt_match"] is False and r["trt_build_device"] is None


@pytest.mark.skipif(not os.path.isfile(YOLOPX) or not trt_compat.host_is_orin(),
                    reason="needs the YOLOPX engine on a Jetson Orin")
def test_real_engine_on_this_orin():
    r = ie.inspect(YOLOPX)
    assert r["load"] == "OK" and r["hw_compat"] == "NONE"
    assert r["trt_match"] is True and r["trt_build_device"] == "Orin GPU (sm87)"
    dw = r["trt_device_warning"]          # present or not: it depends on the boot (total memory)
    assert dw is None or "different models of devices" in dw
