"""Machine data is configuration, not code (night task A1): the keys node_name, protected_dirs, old_stack_root,
infer_status_endpoint / infer_admin_endpoint (from the infer ports), unit_prefix, engines.scan_dirs, sources base_port,
and the config templates. Pure: no GPU, no network, no real config/*.yaml (a fresh clone has none).

Run: PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_machine_config.py
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import socket
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "config" / "templates"
TEMPLATE_NAMES = ("infer", "dashboard", "sources", "models", "control", "sim")
# values that are true only for AGX02 (its user, its LAN, its name)
MACHINE_RE = re.compile(r"/home/tonyho|\b10\.0\.0\.|agx02", re.IGNORECASE)
# folders of code that runs on a unit. Not scanned: tests/, docs/, ref/, systemd/ (old unit files of AGX02, the ops
# helper replaces them), infer/models/legacy/ (reference copy of the old DriverGuard code, never run).
CODE_DIRS = ("common", "controller", "dashboard", "infer", "tools", "proto")
SKIP_PARTS = ("infer/models/legacy/", "__pycache__")


def short_host() -> str:
    return socket.gethostname().split(".")[0] or "agx"


def load(**over) -> dict:
    """The effective config of the dashboard template with these keys changed (as in a config file)."""
    from dashboard.config import DEFAULTS, _merge, effective
    data = yaml.safe_load((TEMPLATES / "dashboard.yaml").read_text(encoding="utf-8"))
    data.update(over)
    return effective(_merge(DEFAULTS, data))


# ---------------------------------------------------------------- templates
@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_template_is_valid_yaml_without_agx02_values(name):
    text = (TEMPLATES / f"{name}.yaml").read_text(encoding="utf-8")
    assert isinstance(yaml.safe_load(text), dict), name
    bad = [ln for ln in text.splitlines() if MACHINE_RE.search(ln) and "example" not in ln.lower()]
    assert not bad, (name, bad)
    assert "DA01" not in text.replace("example", ""), name


def test_template_values():
    d = yaml.safe_load((TEMPLATES / "dashboard.yaml").read_text())
    assert d["node_name"] is None and d["port"] == 8700 and d["old_stack_root"] is None
    assert d["allow_cidrs"] == ["127.0.0.0/8", "10.42.0.0/30", "100.64.0.0/10"]
    assert d["engines"]["scan_dirs"] == [] and d["protected_dirs"] == [] and d["unit_prefix"] == "agx"
    assert d["old_units"] == ["docker.service", "nvpmodel.service", "ssh.service"]
    i = yaml.safe_load((TEMPLATES / "infer.yaml").read_text())
    assert i["ports"] == {"results": 5560, "status": 5561, "internal": 5562, "admin": 5563, "rkinfo": 5564}
    assert i["model_store"] == "~/agx-models" and i["status"]["schema_version"] == 2 and i["protected_dirs"] == []
    s = yaml.safe_load((TEMPLATES / "sources.yaml").read_text())
    assert s["mode"] == "rk" and s["base_port"] == 6000
    assert [c["role"] for c in s["cameras"]] == ["front", "right", "left", "right-back", "left-back", "back"]
    assert all("role_rk" not in c and "port" not in c and c["files"] == [] for c in s["cameras"])
    assert yaml.safe_load((TEMPLATES / "models.yaml").read_text())["models"] == []
    assert yaml.safe_load((TEMPLATES / "control.yaml").read_text())["control_mode"] == "bench"
    sim = yaml.safe_load((TEMPLATES / "sim.yaml").read_text())
    assert sim["video_root"] == "" and all(c["source"] == "test-pattern" for c in sim["cameras"])


def test_config_yaml_files_are_not_tracked():
    gi = (ROOT / ".gitignore").read_text().splitlines()
    assert "/config/*.yaml" in gi


def _py_strings(path: Path) -> list[tuple[int, str]]:
    """The string constants of a Python file that are not docstrings (comments are not tokens of the AST)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docs.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _strip_comments(path: Path) -> list[tuple[int, str]]:
    """Lines of a shell, JS, HTML, CSS or capnp file without the comments."""
    text = path.read_text(encoding="utf-8")
    ext = path.suffix
    if ext in (".js", ".css"):
        text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    if ext == ".html":
        text = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    out = []
    for i, ln in enumerate(text.splitlines(), 1):
        if ext in (".sh", ".capnp", ".in") or path.name.endswith(".sh"):
            ln = re.sub(r"(^|\s)#.*$", "", ln)
        if ext == ".js":
            ln = re.sub(r"(^|\s)//.*$", "", ln)
        out.append((i, ln))
    return out


def test_code_has_no_agx02_value_outside_comments():
    bad = []
    for d in CODE_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            rel = p.relative_to(ROOT).as_posix()
            if not p.is_file() or any(s in rel + "/" for s in SKIP_PARTS):
                continue
            if p.suffix == ".py":
                items = _py_strings(p)
            elif p.suffix in (".sh", ".js", ".html", ".css", ".capnp") or (p.suffix == "" and p.name.endswith("sh")):
                items = _strip_comments(p)
            else:
                continue
            bad += [(rel, n, s.strip()[:120]) for n, s in items if MACHINE_RE.search(s)]
    assert not bad, bad


# ---------------------------------------------------------------- node_name
def test_node_name_default_is_the_short_host_name():
    from common.machine import node_name
    assert load()["node_name"] == short_host()
    assert node_name({}) == short_host() and node_name({"node_name": "  "}) == short_host()
    assert load(node_name="unit9")["node_name"] == "unit9"


def test_node_name_in_realm_title_health_and_mqtt(tmp_path, monkeypatch):
    from dashboard import mqtt_pub
    from dashboard.app import create_app

    def app_for(node):
        cfg = load(model_control=False, node_name=node)
        cfg["history"]["db"] = str(tmp_path / "h.sqlite")
        cfg["engines"]["cache"] = str(tmp_path / "ec.json")
        cfg.update(paired_boards_file=str(tmp_path / "pb.json"), link_settings_file=str(tmp_path / "ls.json"))
        return create_app(cfg, env={"AGX_DASH_USER": "u", "AGX_DASH_PASSWORD": "pw-test"}, start_collectors=False)

    async def get(app, auth=None):
        tr = httpx.ASGITransport(app=app, client=("127.0.0.1", 40000))
        async with httpx.AsyncClient(transport=tr, base_url="http://unit") as c:
            return await c.get("/api/health", auth=auth)

    app = app_for("unit9")
    assert app.title == "unit9 dashboard"
    r = asyncio.run(get(app))
    assert r.status_code == 401 and r.headers["www-authenticate"] == 'Basic realm="unit9-dashboard"'
    h = asyncio.run(get(app, ("u", "pw-test"))).json()
    assert h["node_name"] == "unit9"
    assert app.state.hub.power.part == "unit9"
    r = asyncio.run(get(app_for(None)))
    assert r.headers["www-authenticate"] == f'Basic realm="{short_host()}-dashboard"'

    # MQTT topic: <prefix>/<node>/health; no node = the short host name
    class FakeClient:
        def __init__(self, *a, **k):
            self.k = k

        def __getattr__(self, name):      # every client method: no network
            return lambda *a, **k: None

    class FakeMod:
        Client = FakeClient
        CallbackAPIVersion = type("V", (), {"VERSION2": 2})

    import sys
    import types
    pkg, sub = types.ModuleType("paho"), types.ModuleType("paho.mqtt")
    monkeypatch.setitem(sys.modules, "paho", pkg)
    monkeypatch.setitem(sys.modules, "paho.mqtt", sub)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", FakeMod)
    env = {"AGX_MQTT_HOST": "broker.test", "AGX_MQTT_TOPIC_PREFIX": "fleet"}
    assert mqtt_pub.MqttPublisher(env, dict, 5, node="unit9").topic == "fleet/unit9/health"
    assert mqtt_pub.MqttPublisher(env, dict, 5).topic == f"fleet/{short_host()}/health"


# ---------------------------------------------------------------- protected_dirs
def test_protected_dirs_from_config(tmp_path):
    from common.machine import inside_protected
    from controller import manifest as mf
    from controller.builder import BuildJob
    from controller.control import Controller

    prot = tmp_path / "model"
    (prot / "x" / "1").mkdir(parents=True)
    (tmp_path / "models_other").mkdir()
    assert load()["protected_dirs"] == []
    cfg = load(protected_dirs=[str(prot), None, ""])
    assert cfg["protected_dirs"] == [os.path.realpath(prot)]
    assert inside_protected(prot / "x", cfg["protected_dirs"]) == os.path.realpath(prot)
    assert inside_protected(tmp_path / "models_other", cfg["protected_dirs"]) is None     # not a prefix match
    assert inside_protected("/anything", None) is None
    with pytest.raises(ValueError, match="protected"):
        Controller(str(prot / "store"), str(tmp_path), str(tmp_path / "control.yaml"), protected_dirs=[str(prot)])
    Controller(str(tmp_path / "store"), str(tmp_path), str(tmp_path / "control.yaml"), protected_dirs=[str(prot)])
    m = mf.Manifest(folder=str(prot / "x" / "1"), data={"name": "x", "version": "1"})
    with pytest.raises(ValueError, match="protected"):
        BuildJob(m, protected_dirs=[str(prot)])


def test_infer_engines_dir_and_protected_dirs(tmp_path):
    pytest.importorskip("tensorrt", reason="infer.models.manager needs TensorRT")
    from infer.ingest.frame_store import FrameStore
    from infer.models.manager import ModelManager

    prot = tmp_path / "model"
    (prot / "engines").mkdir(parents=True)
    with pytest.raises(ValueError):
        ModelManager([], FrameStore(range(6)), lambda r: None, engines_dir=str(prot / "engines"),
                     protected_dirs=[str(prot)])
    mm = ModelManager([], FrameStore(range(6)), lambda r: None, engines_dir=str(prot / "engines"))  # [] = none
    mm.stop()


# ---------------------------------------------------------------- old_stack_root
def test_old_stack_root_null_means_not_configured():
    from dashboard.collectors.services import ServicesCollector
    cfg = load()
    assert cfg["old_stack_root"] is None
    sc = ServicesCollector(cfg)
    assert sc.old_root is None and "old_stack_root" in sc._old_procs["note"]
    assert ServicesCollector(load(old_stack_root="/home/u/driveragent")).old_root == "/home/u/driveragent"


# ---------------------------------------------------------------- endpoints from the infer ports
def test_status_and_admin_endpoint_from_infer_ports(tmp_path):
    from controller.control import from_config
    from dashboard.config import infer_admin_endpoint, infer_status_endpoint

    inf = tmp_path / "infer.yaml"
    inf.write_text("ports: {results: 5570, status: 5571, internal: 5572, admin: 5573, rkinfo: 5574}\n")
    cfg = load(infer_config=str(inf))
    assert cfg["infer_status_endpoint"] == "tcp://127.0.0.1:5572"
    assert cfg["infer_admin_endpoint"] == "tcp://127.0.0.1:5573"
    # the template infer.yaml; a missing file gives 5562 / 5563
    assert load(infer_config="config/templates/infer.yaml")["infer_admin_endpoint"] == "tcp://127.0.0.1:5563"
    miss = {"infer_config": str(tmp_path / "none.yaml")}
    assert infer_status_endpoint(miss) == "tcp://127.0.0.1:5562" and infer_admin_endpoint(miss) == "tcp://127.0.0.1:5563"
    # an explicit value stays (AGX02 sets infer_status_endpoint)
    assert load(infer_config=str(inf), infer_status_endpoint="tcp://127.0.0.1:6662")["infer_status_endpoint"] == \
        "tcp://127.0.0.1:6662"
    # the controller of the dashboard uses the admin endpoint
    ctl = from_config(dict(cfg, model_store=str(tmp_path / "store"), control_config=str(tmp_path / "c.yaml")),
                      tmp_path, None)
    try:
        assert ctl.admin.endpoint == "tcp://127.0.0.1:5573"
        # the model checks use the test frame of the configured store
        assert ctl.checks.frame == str(tmp_path / "store" / "_testframes" / "front_1280x720.jpg")
    finally:
        ctl.checks.stop()


# ---------------------------------------------------------------- unit_prefix, scan_dirs
def test_unit_prefix_gives_the_service_lists():
    from dashboard.collectors.services import ServicesCollector
    from dashboard.config import DEFAULTS

    cfg = load()
    assert cfg["services"]["agx_units"] == ["agx-dashboard", "agx-infer", "agx-sim"]
    assert cfg["services"]["log_units"] == ["agx-infer", "agx-dashboard", "agx-sim"]
    cfg = load(unit_prefix="agxtest")
    assert cfg["services"]["agx_units"] == ["agxtest-dashboard", "agxtest-infer", "agxtest-sim"]
    assert ServicesCollector(cfg).log_units == ["agxtest-infer", "agxtest-dashboard", "agxtest-sim"]
    # lists in the config stay as they are (AGX02 sets them)
    over = dict(DEFAULTS["services"], agx_units=["agx-dashboard"], log_units=["agx-infer"])
    cfg = load(unit_prefix="other", services=over)
    assert cfg["services"]["agx_units"] == ["agx-dashboard"] and cfg["services"]["log_units"] == ["agx-infer"]
    # a raw dict without the lists (old config, no load_config) does not crash
    assert ServicesCollector({"services": {}}).agx_units == ["agx-dashboard", "agx-infer", "agx-sim"]


def test_engines_scan_dirs_default_empty():
    from tools import inspect_engines as ie
    assert load()["engines"]["scan_dirs"] == [] and ie.DEFAULT_SCAN == []
    assert load(engines={"cache": "x", "scan_dirs": None})["engines"]["scan_dirs"] == []


# ---------------------------------------------------------------- sources base_port
def test_sources_base_port_ingest_and_pairing_ports(tmp_path):
    from dashboard.pairing_api import read_ports
    from infer.ingest.ingest import Ingest

    cams = [{"cam": c, "enabled": False} for c in range(6)]
    cams[2]["port"] = 16702
    ing = Ingest({"base_port": 16600, "cameras": cams, "rx_process": False, "decoder_prestart": False}, mode="sim")
    ports = {s["cam"]: s["port"] for s in ing.metrics_snapshot()}
    assert ports == {0: 16600, 1: 16601, 2: 16702, 3: 16603, 4: 16604, 5: 16605}
    ing = Ingest({"cameras": [], "rx_process": False, "decoder_prestart": False}, mode="sim")
    assert [s["port"] for s in ing.metrics_snapshot()] == [6000 + n for n in range(6)]

    src = tmp_path / "sources.yaml"
    src.write_text("base_port: 6010\ncameras: [{cam: 0}, {cam: 1}]\n")
    p = read_ports(tmp_path / "none.yaml", src)
    assert p["video"] == [6010 + n for n in range(6)] and p["video_base"] == 6010
    assert (p["results"], p["status"], p["rkinfo"]) == (5560, 5561, 5564)
    src.write_text("base_port: 6010\ncameras: " + str([{"cam": n, "port": 7000 + n} for n in range(6)]) + "\n")
    p = read_ports(None, src)        # per-camera ports: as before
    assert p["video"] == [7000 + n for n in range(6)] and p["video_base"] == 7000
    p = read_ports(None, ROOT / "config" / "templates" / "sources.yaml")
    assert p["video"] == [6000 + n for n in range(6)]


# ---------------------------------------------------------------- tools
def test_model_check_frame_of_the_store():
    from tools import model_check as mc
    assert mc.default_frame("/srv/store/yolo/2") == "/srv/store/_testframes/front_1280x720.jpg"
    assert mc.store_frame("/srv/s2") == "/srv/s2/_testframes/front_1280x720.jpg"
    assert mc.DEFAULT_FRAME == os.path.expanduser("~/agx-models/_testframes/front_1280x720.jpg")   # default store


def test_register_existing_models_needs_root(tmp_path, capsys):
    from tools import register_existing_models as rem

    with pytest.raises(SystemExit):
        rem.main(["--store", str(tmp_path), "--dry-run"])
    specs = rem.specs("/srv/old-models")
    paths = [f["path"] for s in specs for f in s["files"]]
    assert all(p.startswith("/srv/old-models/") for p in paths), paths
    assert "/srv/old-models/jetson_bundle/engines/yolopx_v2_fp16.engine" in paths


def test_rk_result_client_defaults_are_in_the_repo():
    pytest.importorskip("capnp")
    from tools.rk_result_client import __main__ as rc
    assert rc.DEFAULT_SCHEMA == str(ROOT / "proto" / "agx_infer.capnp") and os.path.isfile(rc.DEFAULT_SCHEMA)
    assert rc.DEFAULT_ENVELOPE_DIR == str(ROOT / "common")
