#!/usr/bin/env python3
"""Make a model package (docs/DEPLOY_MODEL.md section 2) from one version of a model store (ops/export_model.sh).

  export_model.py NAME VERSION --store DIR --out DIR [--with-engine]

The store is only READ. The package <out>/<name>-<version>/ gets manifest.yaml and the ONNX file, with the path
rewritten to a package-relative name; the sha256 of the manifest is kept (the tool checks the source file against
it). Files with the role "weights" or "other" are not exported (the tool lists them). --with-engine also copies the
engine: the engine of the manifest, or the engine that the build on this unit made (build.json). An engine runs only
on the same device type with the same TensorRT version.
Exit 0 = package made, 1 = cannot export (for example no ONNX file), 2 = wrong command line.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sys
import time

import yaml


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fail(msg: str) -> int:
    print(f"cannot export: {msg}", file=sys.stderr)
    return 1


def device() -> str:
    try:
        with open("/proc/device-tree/model", encoding="utf-8", errors="replace") as f:
            return f.read().strip("\0\n ")
    except OSError:
        return "unknown device"


def unique_name(used: set, name: str) -> str:
    base, ext = os.path.splitext(name)
    n, i = name, 1
    while n in used or n in ("manifest.yaml", "build.json", "build.log"):
        i += 1
        n = f"{base}_{i}{ext}"
    used.add(n)
    return n


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--with-engine"]
    with_engine = "--with-engine" in argv
    if len(args) != 6 or args[2] != "--store" or args[4] != "--out":
        print(__doc__, file=sys.stderr)
        return 2
    name, version, store, out = args[0], args[1], args[3], args[5]
    store = os.path.abspath(os.path.expanduser(store))
    vdir = os.path.join(store, name, version)
    mpath = os.path.join(vdir, "manifest.yaml")
    if not os.path.isfile(mpath):
        return fail(f"{mpath} does not exist (check the name, the version and --store)")
    with open(mpath, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    if not isinstance(d, dict):
        return fail(f"{mpath} is not a YAML mapping")
    files = d.get("files") if isinstance(d.get("files"), list) else []
    pkg = os.path.join(os.path.abspath(os.path.expanduser(out)), f"{name}-{version}")
    if os.path.lexists(pkg):
        return fail(f"{pkg} exists: give another --out folder or remove it")

    def src_of(f: dict) -> str:
        p = os.path.expanduser(str(f.get("path") or ""))
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(vdir, p))

    onnx = [f for f in files if isinstance(f, dict) and f.get("role") == "onnx"]
    if not onnx:
        roles = ", ".join(f"{f.get('role')} {f.get('path')}" for f in files if isinstance(f, dict)) or "no files"
        return fail(f"no ONNX file in the manifest of {name}@{version} ({roles}). A new unit builds its engine "
                    "from an ONNX file.")
    src = src_of(onnx[0])
    if not os.path.isfile(src):
        return fail(f"no ONNX file: {src} of the manifest does not exist on this unit")
    want = str(onnx[0].get("sha256") or "").lower()
    print(f"sha256 of {src} ...", flush=True)
    got = sha256_file(src)
    if got != want:
        return fail(f"the ONNX file {src} has sha256 {got}, the manifest says {want}")

    used: set = set()
    new_files = []
    copies = []
    onnx_name = unique_name(used, os.path.basename(src))
    new_files.append({"role": "onnx", "path": onnx_name, "sha256": want})
    copies.append((src, onnx_name))

    engine_note = None
    if with_engine:
        eng = [f for f in files if isinstance(f, dict) and f.get("role") == "engine"]
        esrc, esha, origin = None, None, None
        if eng and os.path.isfile(src_of(eng[0])):
            esrc, esha, origin = src_of(eng[0]), str(eng[0].get("sha256") or "").lower(), "the manifest"
        else:
            bj = os.path.join(vdir, "build.json")
            try:
                with open(bj, encoding="utf-8") as f:
                    b = json.load(f)
            except (OSError, ValueError):
                b = {}
            for k in ("engine",):
                p = b.get(k) if isinstance(b, dict) else None
                if isinstance(p, str) and p:
                    p = p if os.path.isabs(p) else os.path.join(vdir, p)
                    if os.path.isfile(p):
                        esrc, origin = p, "the build on this unit (build.json)"
                        esha = str(b.get("engine_sha256") or "").lower() or None
                        break
            if esrc is None:
                cands = sorted(x for x in os.listdir(vdir) if x.endswith(".engine"))
                if cands:
                    esrc, origin = os.path.join(vdir, cands[0]), "the version folder"
        if esrc is None:
            return fail(f"--with-engine: {name}@{version} has no engine file on this unit (export without --with-engine)")
        print(f"sha256 of {esrc} ...", flush=True)
        egot = sha256_file(esrc)
        if esha and egot != esha:
            return fail(f"the engine {esrc} has sha256 {egot}, the manifest says {esha}")
        ename = unique_name(used, os.path.basename(esrc))
        new_files.append({"role": "engine", "path": ename, "sha256": egot})
        copies.append((esrc, ename))
        engine_note = (f"the engine ({origin}) runs only on the same device type ({device()}) with the same TensorRT "
                       "version. On another device type, export without --with-engine and build the engine there.")
    dropped = [f"{f.get('role')} {f.get('path')}" for f in files if isinstance(f, dict)
               and f.get("role") not in ("onnx", "engine")]
    if not with_engine:
        dropped += [f"engine {f.get('path')} (use --with-engine)" for f in files
                    if isinstance(f, dict) and f.get("role") == "engine"]

    tmp = pkg + ".part"
    if os.path.lexists(tmp):
        return fail(f"{tmp} exists (an interrupted export?): remove it")
    os.makedirs(tmp)
    try:
        for s, n in copies:
            print(f"copy {s} -> {os.path.join(pkg, n)}", flush=True)
            shutil.copyfile(s, os.path.join(tmp, n))
            os.chmod(os.path.join(tmp, n), 0o644)
        nd = dict(d)
        nd["files"] = new_files
        head = (f"# Model store manifest. Schema: controller/manifest.py.\n"
                f"# Exported by ops/export_model.sh from {socket.gethostname()}:{vdir} on "
                f"{time.strftime('%Y-%m-%d %H:%M:%S %Z')}.\n")
        with open(os.path.join(tmp, "manifest.yaml"), "w", encoding="utf-8") as f:
            f.write(head)
            yaml.safe_dump(nd, f, sort_keys=False, allow_unicode=True, width=120)
        os.chmod(os.path.join(tmp, "manifest.yaml"), 0o644)
        for s, n in copies:                       # check the copies again
            if sha256_file(os.path.join(tmp, n)) != next(x["sha256"] for x in new_files if x["path"] == n):
                raise OSError(f"the copy of {s} has another sha256")
        os.rename(tmp, pkg)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    print(f"EXPORTED {name}@{version} -> {pkg}")
    for x in new_files:
        print(f"  {x['role']:7s} {x['path']}  sha256 {x['sha256']}")
    for x in dropped:
        print(f"  not exported: {x}")
    if engine_note:
        print(f"NOTE: {engine_note}")
    print("Next: copy the folder to the new unit, then: .venv/bin/python -m tools.model_store_cli validate <folder>, "
          "and tools/deploy_model.sh <folder> (docs/DEPLOY_MODEL.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
