"""Read TensorRT engine files and print their I/O tensors (name, shape, dtype, mode).

Each engine is deserialized in its OWN subprocess (a bad engine cannot crash the caller, and GPU memory
is freed at exit). Used for docs/MODELS.md (T1 test) and by the dashboard (models part B).

  python -m tools.inspect_engines [--json] [--scan DIR ...] [ENGINE ...]

There is no default scan folder (the engines of a machine are machine data): give ENGINE files or --scan DIR
(for example --scan /home/<user>/model). The dashboard scans config/dashboard.yaml engines.scan_dirs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

from common import trt_compat

DEFAULT_SCAN: list[str] = []      # no machine folder in the code (config/dashboard.yaml engines.scan_dirs)
ENGINE_EXT = (".engine", ".trt", ".plan")

_CHILD = r"""
import json, sys, io, os, contextlib
p = sys.argv[1]
out = {"path": p}
try:
    import tensorrt as trt
    out["trt_version"] = trt.__version__
    class L(trt.ILogger):
        def __init__(self):
            trt.ILogger.__init__(self); self.msgs = []
        def log(self, sev, msg):
            if sev <= trt.ILogger.Severity.WARNING:
                self.msgs.append(f"{sev.name}: {msg}")
    lg = L()
    rt = trt.Runtime(lg)
    with open(p, "rb") as f:
        data = f.read()
    e = rt.deserialize_cuda_engine(data)
    out["load"] = "OK" if e is not None else "FAILED"
    out["messages"] = lg.msgs
    if e is not None:
        out["num_layers"] = e.num_layers
        out["profiles"] = e.num_optimization_profiles
        out["device_memory"] = int(getattr(e, "device_memory_size_v2", 0) or e.device_memory_size)
        out["hw_compat"] = getattr(getattr(e, "hardware_compatibility_level", None), "name", None)
        io_ = []
        for i in range(e.num_io_tensors):
            n = e.get_tensor_name(i)
            io_.append({"name": n, "mode": e.get_tensor_mode(n).name,
                        "shape": [int(x) for x in e.get_tensor_shape(n)],
                        "dtype": e.get_tensor_dtype(n).name})
        out["io"] = io_
except Exception as ex:
    out["load"] = "FAILED"
    out["error"] = f"{type(ex).__name__}: {ex}"
print("JSON:" + json.dumps(out))
"""


def sha256_16(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def inspect(path: str, timeout: float = 120.0) -> dict:
    real = os.path.realpath(path)
    st = os.stat(real)
    info = {"path": path, "realpath": real, "size": st.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            "sha256_16": sha256_16(real)}
    try:
        r = subprocess.run([sys.executable, "-c", _CHILD, real], capture_output=True, text=True,
                           timeout=timeout)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("JSON:")), None)
        if line is None:
            info.update({"load": "FAILED", "error": (r.stderr or r.stdout)[-500:]})
        else:
            child = json.loads(line[5:])
            child.pop("path", None)
            info.update(child)
            if r.stderr.strip():
                info.setdefault("messages", []).append(r.stderr.strip()[-300:])
    except subprocess.TimeoutExpired:
        info.update({"load": "FAILED", "error": f"timeout after {timeout} s"})
    # "match": loads with the installed TensorRT and the build device is an Orin GPU (common/trt_compat.py).
    # The TensorRT device warning is information only: trt_device_warning.
    info["trt_match"], info["trt_build_device"] = trt_compat.verdict(
        info.get("load") == "OK", info.get("hw_compat"), trt_compat.host_is_orin())
    info["trt_device_warning"] = trt_compat.device_warning(info.get("messages"))
    return info


def scan(dirs) -> list[str]:
    found = []
    for d in dirs:
        for root, _dirs, files in os.walk(d, followlinks=False):
            if "/venv" in root or "site-packages" in root:
                continue
            for fn in files:
                if fn.lower().endswith(ENGINE_EXT):
                    p = os.path.join(root, fn)
                    if not os.path.islink(p):
                        found.append(p)
    return sorted(found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("engines", nargs="*")
    ap.add_argument("--scan", nargs="*", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not a.engines and not a.scan and not DEFAULT_SCAN:
        print("inspect_engines: nothing to read: give ENGINE files or --scan DIR", file=sys.stderr)
        return 2
    paths = list(a.engines) + scan(a.scan if a.scan is not None else ([] if a.engines else DEFAULT_SCAN))
    res = [inspect(p) for p in paths]
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    for r in res:
        print(f"##### {r['path']}")
        print(f"size {r['size']} B  mtime {r['mtime']}  sha256[:16] {r['sha256_16']}")
        print(f"TensorRT {r.get('trt_version', '?')}  load {r.get('load')}  match {r['trt_match']}"
              + (f"  build device {r['trt_build_device']}" if r.get("trt_build_device") else "")
              + (f"  error {r['error']}" if r.get("error") else ""))
        if r.get("trt_device_warning"):
            print(f"  device warning (information only): {r['trt_device_warning']}")
        for m in r.get("messages", []):
            if m != r.get("trt_device_warning"):
                print(f"  message: {m}")
        if r.get("load") == "OK":
            print(f"layers {r['num_layers']}  profiles {r['profiles']}  device_memory {r['device_memory']} B")
            for t in r["io"]:
                print(f"  {t['mode']:6s} {t['name']:14s} {tuple(t['shape'])!s:22s} {t['dtype']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
