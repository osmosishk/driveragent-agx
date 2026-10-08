"""Model package deploy (tools/model_store_cli.py, tools/deploy_model.sh) into a temporary store. Pure: no GPU.

Every store and package is in pytest tmp_path: the real ~/agx-models is never touched.
"""
import copy
import hashlib
import os
import stat
import subprocess
import sys

import pytest
import yaml

from controller import audit, manifest as mf
from controller.store import Store
from tools import model_store_cli as cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "tools", "deploy_model.sh")
ONNX = b"fake onnx bytes for the deploy test\n"
MANIFEST = {
    "schema": mf.SCHEMA, "name": "det_model", "version": "2", "type": "yolopx", "description": "test model",
    "files": [{"role": "onnx", "path": "model.onnx", "sha256": hashlib.sha256(ONNX).hexdigest()}],
    "input": {"tensors": [{"name": "image", "shape": [1, 3, 384, 640], "dtype": "FLOAT"}],
              "size": {"width": 640, "height": 384}, "colour_order": "RGB", "normalisation": "x/255"},
    "outputs": {"tensors": [{"name": "det", "shape": [1, 5040, 15], "dtype": "FLOAT"}], "kinds": ["boxes"]},
    "precision": "fp16", "cameras": {"permitted": [0, 1], "default": [0]},
    "adapter": {"class_names": ["a", "b"], "score_limit": 0.3},
    "runtime": {"workers": 1, "max_fps_per_camera": 30}, "build": {"shapes": "image:1x3x384x640", "precision": "fp16"},
    "date": "2026-10-07",
}


def make_pkg(folder, data=ONNX, **changes):
    """A package folder with manifest.yaml + model.onnx. changes replace manifest fields."""
    os.makedirs(folder, exist_ok=True)
    d = copy.deepcopy(MANIFEST)
    d.update(changes)
    with open(os.path.join(folder, "model.onnx"), "wb") as f:
        f.write(data)
    with open(os.path.join(folder, "manifest.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(d, f, sort_keys=False)
    return str(folder)


@pytest.fixture
def store(tmp_path):
    s = tmp_path / "store"
    s.mkdir()
    return str(s)


def target(store, name="det_model", version="2"):
    return os.path.join(store, name, version)


def events(store):
    return audit.read(os.path.join(store, "_state"))


def incoming_left(store):
    d = os.path.join(store, cli.INCOMING)
    return [n for n in os.listdir(d) if not n.startswith(".")] if os.path.isdir(d) else []


def test_deploy_ok_writes_version_and_audit_line(tmp_path, store, capsys):
    pkg = make_pkg(tmp_path / "pkg")
    assert cli.main(["deploy", pkg, "--store", store, "--user", "tester"]) == 0
    out = capsys.readouterr().out
    t = target(store)
    assert open(os.path.join(t, "model.onnx"), "rb").read() == ONNX
    assert os.path.isfile(os.path.join(t, "manifest.yaml"))
    assert os.path.isfile(os.path.join(pkg, "model.onnx")), "the source package stays"
    assert incoming_left(store) == []
    assert not os.stat(os.path.join(t, "model.onnx")).st_mode & 0o222, "files are read-only"
    assert os.access(t, os.W_OK), "the version folder stays writable for a build"
    m = Store(store).get("det_model", "2")
    assert m is not None and m.errors == []
    ev = events(store)
    assert len(ev) == 1
    e = ev[0]
    assert (e["source"], e["user"], e["action"], e["model"], e["version"], e["result"]) == \
        ("command-line", "tester", "deploy", "det_model", "2", "ok")
    assert e["state"] == "NEEDS BUILD"
    assert "NEEDS BUILD" in out and "Next step" in out


def test_engine_package_is_registered(tmp_path, store):
    eng = b"engine bytes"
    files = [{"role": "engine", "path": "det.engine", "sha256": hashlib.sha256(eng).hexdigest()}]
    pkg = make_pkg(tmp_path / "pkg", files=files)
    open(os.path.join(pkg, "det.engine"), "wb").write(eng)
    assert cli.main(["deploy", pkg, "--store", store, "--user", "t"]) == 0
    assert events(store)[0]["state"] == "REGISTERED"


def test_sha256_mismatch_refused(tmp_path, store, capsys):
    pkg = make_pkg(tmp_path / "pkg", data=b"other bytes")
    assert cli.main(["deploy", pkg, "--store", store, "--user", "t"]) == 1
    assert "sha256 does not agree" in capsys.readouterr().err
    assert not os.path.exists(target(store))
    assert incoming_left(store) == []
    e = events(store)[0]
    assert e["result"] == "refused" and "sha256" in e["reason"] and e["model"] == "det_model"


def test_existing_version_refused_nothing_overwritten(tmp_path, store, capsys):
    assert cli.main(["deploy", make_pkg(tmp_path / "a"), "--store", store, "--user", "t"]) == 0
    new = b"new onnx with the same version"
    pkg2 = make_pkg(tmp_path / "b", data=new, files=[{"role": "onnx", "path": "model.onnx",
                                                       "sha256": hashlib.sha256(new).hexdigest()}])
    before = os.stat(os.path.join(target(store), "manifest.yaml")).st_mtime_ns
    assert cli.main(["deploy", pkg2, "--store", store, "--user", "t"]) == 1
    assert "never overwritten" in capsys.readouterr().err
    assert open(os.path.join(target(store), "model.onnx"), "rb").read() == ONNX
    assert os.stat(os.path.join(target(store), "manifest.yaml")).st_mtime_ns == before
    assert incoming_left(store) == []
    assert [e["result"] for e in events(store)] == ["refused", "ok"]


def test_absolute_path_refused(tmp_path, store, capsys):
    pkg = make_pkg(tmp_path / "pkg")
    absf = os.path.join(pkg, "model.onnx")
    pkg = make_pkg(tmp_path / "pkg", files=[{"role": "onnx", "path": absf, "sha256": hashlib.sha256(ONNX).hexdigest()}])
    assert cli.main(["validate", pkg, "--store", store]) == 1
    assert "no absolute path" in capsys.readouterr().out
    assert cli.main(["deploy", pkg, "--store", store, "--user", "t"]) == 1
    assert not os.path.exists(target(store))
    assert events(store)[0]["result"] == "refused"


def test_dotdot_path_refused(tmp_path, store, capsys):
    (tmp_path / "outside.onnx").write_bytes(ONNX)
    pkg = make_pkg(tmp_path / "pkg", files=[{"role": "onnx", "path": "../outside.onnx",
                                             "sha256": hashlib.sha256(ONNX).hexdigest()}])
    assert cli.main(["validate", pkg, "--store", store]) == 1
    assert "no '..'" in capsys.readouterr().out
    assert cli.main(["deploy", pkg, "--store", store, "--user", "t"]) == 1
    assert not os.path.exists(target(store))


def test_symlink_refused(tmp_path, store, capsys):
    pkg = make_pkg(tmp_path / "pkg")
    (tmp_path / "real.onnx").write_bytes(ONNX)
    os.unlink(os.path.join(pkg, "model.onnx"))
    os.symlink(tmp_path / "real.onnx", os.path.join(pkg, "model.onnx"))
    assert cli.main(["validate", pkg, "--store", store]) == 1
    assert "symbolic link" in capsys.readouterr().out


def test_validate_exit_codes(tmp_path, store, capsys):
    assert cli.main(["validate", make_pkg(tmp_path / "good"), "--store", store]) == 0
    assert "VALID: det_model@2" in capsys.readouterr().out
    missing = make_pkg(tmp_path / "missing")
    os.unlink(os.path.join(missing, "model.onnx"))
    assert cli.main(["validate", missing, "--store", store]) == 1
    assert "does not exist in the package" in capsys.readouterr().out
    assert cli.main(["validate", make_pkg(tmp_path / "badver", version=2), "--store", store]) == 1
    assert "version must be a quoted string" in capsys.readouterr().out
    assert cli.main(["validate", str(tmp_path / "nothing"), "--store", store]) == 1
    os.makedirs(tmp_path / "empty")
    assert cli.main(["validate", str(tmp_path / "empty"), "--store", store]) == 1
    assert "no manifest.yaml" in capsys.readouterr().out
    bj = make_pkg(tmp_path / "buildjson")
    open(os.path.join(bj, "build.json"), "w").write("{}")
    assert cli.main(["validate", bj, "--store", store]) == 1
    assert not os.listdir(store), "validate changes nothing"


def test_failed_expected_state_refused(tmp_path, store, capsys):
    pkg = make_pkg(tmp_path / "pkg", files=[])        # valid manifest, but no engine and no ONNX file
    assert cli.main(["deploy", pkg, "--store", store, "--user", "t"]) == 1
    assert "FAILED" in capsys.readouterr().err
    assert not os.path.exists(target(store))


def test_deploy_staged(tmp_path, store):
    inc = os.path.join(store, cli.INCOMING)
    staged = make_pkg(os.path.join(inc, "det_model-2-abcd1234"))
    assert cli.main(["deploy", "--staged", staged, "--store", store, "--user", "t"]) == 0
    assert not os.path.exists(staged) and os.path.isfile(os.path.join(target(store), "model.onnx"))
    # a staged folder outside _incoming, and a plain package inside the store, are refused
    other = make_pkg(tmp_path / "other", version="3")
    assert cli.main(["deploy", "--staged", other, "--store", store, "--user", "t"]) == 1
    inside = make_pkg(os.path.join(store, "det_model", "9"), version="9")
    assert cli.main(["deploy", inside, "--store", store, "--user", "t"]) == 1
    # a refused staged package stays for inspection
    bad = make_pkg(os.path.join(inc, "det_model-4-x"), version="4", data=b"wrong")
    assert cli.main(["deploy", "--staged", bad, "--store", store, "--user", "t"]) == 1
    assert os.path.isdir(bad) and not os.path.exists(target(store, version="4"))


def test_missing_store_refused(tmp_path):
    pkg = make_pkg(tmp_path / "pkg")
    assert cli.main(["deploy", pkg, "--store", str(tmp_path / "no_store"), "--user", "t"]) == 1
    assert not os.path.exists(tmp_path / "no_store")


def _run_script(*args, env=None):
    e = dict(os.environ, AGX_PYTHON=sys.executable, **(env or {}))
    return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, timeout=120, env=e)


def test_deploy_model_sh_local(tmp_path, store):
    pkg = make_pkg(tmp_path / "pkg")
    r = _run_script(pkg, "--local", "--store", store, "--user", "sh-test")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DEPLOYED det_model@2" in r.stdout and "NEEDS BUILD" in r.stdout
    assert os.path.isfile(os.path.join(target(store), "model.onnx"))
    assert events(store)[0]["user"] == "sh-test"
    r = _run_script(pkg, "--local", "--store", store)            # the same version again
    assert r.returncode == 1 and "never overwritten" in r.stderr
    assert _run_script(str(tmp_path / "nothing"), "--local", "--store", store).returncode == 1
    assert _run_script("--local").returncode == 1                 # usage


def test_deploy_model_sh_remote_with_fake_ssh(tmp_path, store):
    """The workstation path: scp -r into _incoming, then deploy --staged over ssh (ssh and scp run locally here)."""
    py = os.path.join(ROOT, ".venv", "bin", "python")
    if not os.access(py, os.X_OK):
        pytest.skip("the remote command needs <repo>/.venv/bin/python")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "ssh").write_text('#!/bin/bash\nshift\nexec bash -c "$*"\n')
    (fake / "scp").write_text('#!/bin/bash\nwhile [ "${1#-}" != "$1" ]; do shift; done\nexec cp -r "$1" "${2#*:}"\n')
    for f in ("ssh", "scp"):
        os.chmod(fake / f, 0o755)
    pkg = make_pkg(tmp_path / "pkg")
    env = {"PATH": f"{fake}:{os.environ['PATH']}"}
    r = _run_script(pkg, "--remote", "--host", "fakehost", "--store", store, "--repo", ROOT, "--user", "ws",
                    env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.isfile(os.path.join(target(store), "model.onnx")) and incoming_left(store) == []
    assert events(store)[0]["user"] == "ws" and events(store)[0]["result"] == "ok"
    r = _run_script(pkg, "--remote", "--host", "fakehost", "--store", store, "--repo", ROOT, env=env)
    assert r.returncode == 1 and "never overwritten" in r.stderr
    os.symlink(pkg + "/model.onnx", pkg + "/link.onnx")
    r = _run_script(pkg, "--remote", "--host", "fakehost", "--store", store, "--repo", ROOT, env=env)
    assert r.returncode == 1 and "symbolic link" in r.stderr
    st = os.stat(os.path.join(target(store), "model.onnx"))
    assert stat.S_ISREG(st.st_mode)


def test_deploy_model_sh_auto_mode_is_local_on_the_host(tmp_path, store):
    """No --local/--remote: the hostname is the --host value, so the deploy is local (ssh is never called)."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "hostname").write_text("#!/bin/bash\necho thisagx\n")
    (fake / "ssh").write_text("#!/bin/bash\necho 'ssh must not be called' >&2\nexit 99\n")
    for f in ("hostname", "ssh"):
        os.chmod(fake / f, 0o755)
    pkg = make_pkg(tmp_path / "pkg")
    env = {"PATH": f"{fake}:{os.environ['PATH']}"}
    r = _run_script(pkg, "--host", "thisagx", "--store", store, "--user", "auto", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "local deploy" in r.stdout and "DEPLOYED det_model@2" in r.stdout
    # an explicit other host stays remote (the fake ssh refuses: not deployed)
    r = _run_script(make_pkg(tmp_path / "pkg2"), "--host", "otheragx", "--store", store, env=env)
    assert r.returncode == 1 and "cannot reach otheragx" in r.stderr
