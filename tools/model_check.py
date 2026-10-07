"""Model check of one version folder (owner Section 4.3). A short CHILD process: the GPU is freed at exit.

A model is READY only when, in this order (the first failure stops the check, later checks are "not run"):
  sha256       every file of the manifest agrees with its sha256 (1 MiB blocks)
  engine_load  the engine loads with the installed TensorRT (trt_version, trt_match, build device, device warning)
  io_match     engine inputs/outputs = manifest input.tensors / outputs.tensors (names, shapes with -1 as 1, dtypes)
  adapter      the adapter of the type exists and accepts the engine (its own engine I/O check)
  gpu_memory   need (engine + workers x (context + I/O)) + 512 MiB < free GPU memory measured BEFORE the load
  inference    one inference on a stored test frame: output names and shapes = manifest, postprocess result valid

  python -m tools.model_check <version folder> [--frame <jpg>] [--json]

Test frame: --frame, else <store>/_testframes/front_1280x720.jpg of the store of the version folder
(<store>/<name>/<version>); the controller gives the frame of its configured model store.

Output: the last stdout line is "CHECK:" + JSON (see run_check). Exit code 0 = ok, 1 = a check failed,
2 = usage error. Without --json, a readable list of the checks is printed before that line.
Nothing is written anywhere (the old engine folders are only read).
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time

import numpy as np

from controller import manifest as mf
from controller.store import DEFAULT_ROOT

TEST_FRAME = os.path.join("_testframes", "front_1280x720.jpg")     # below the model store
DEFAULT_FRAME = os.path.join(os.path.expanduser(DEFAULT_ROOT), TEST_FRAME)   # the frame of the default store


def store_frame(store_root: str) -> str:
    """The test frame of a model store: <store>/_testframes/front_1280x720.jpg."""
    return os.path.join(os.path.expanduser(str(store_root)), TEST_FRAME)


def default_frame(folder: str) -> str:
    """The test frame of the store that holds this version folder (<store>/<name>/<version>)."""
    return store_frame(os.path.dirname(os.path.dirname(os.path.abspath(folder))))
CHECKS = ("sha256", "engine_load", "io_match", "adapter", "gpu_memory", "inference")
GPU_RESERVE_MB = 512
MB = 1 << 20
# manifest dtype words -> TensorRT DataType names (engine TensorInfo.dtype)
DTYPES = {"float": "FLOAT", "float32": "FLOAT", "fp32": "FLOAT", "half": "HALF", "float16": "HALF",
          "fp16": "HALF", "int32": "INT32", "int8": "INT8", "int64": "INT64", "bool": "BOOL", "uint8": "UINT8",
          "bfloat16": "BF16", "bf16": "BF16", "fp8": "FP8"}


class CheckFailed(Exception):
    """A check failed: the message is the detail in plain words."""


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(MB), b""):
            h.update(b)
    return h.hexdigest()


def norm_dtype(d) -> str | None:
    """Manifest or engine dtype -> TensorRT DataType name ("FLOAT", "HALF", ...). None = not given."""
    if d is None or str(d).strip() == "":
        return None
    s = str(d).strip()
    return DTYPES.get(s.lower(), s.upper())


def norm_shape(shape) -> list[int]:
    return [1 if int(x) < 0 else int(x) for x in shape]


def io_differences(part: str, manifest_tensors: list[dict], engine_tensors: list[dict]) -> list[str]:
    """Plain-words differences between manifest tensors and engine tensors [{name, shape, dtype}] ([] = same)."""
    want = {str(t["name"]): t for t in manifest_tensors}
    have = {str(t["name"]): t for t in engine_tensors}
    diffs = []
    if set(want) != set(have):
        diffs.append(f"{part} names: manifest {sorted(want)}, engine {sorted(have)}")
    for name in sorted(set(want) & set(have)):
        ws, hs = norm_shape(want[name].get("shape") or []), norm_shape(have[name].get("shape") or [])
        if ws != hs:
            diffs.append(f"{part} {name}: shape manifest {ws}, engine {hs}")
        wd = norm_dtype(want[name].get("dtype"))
        if wd is None:
            diffs.append(f"{part} {name}: the manifest gives no dtype (engine {have[name].get('dtype')})")
        elif wd != norm_dtype(have[name].get("dtype")):
            diffs.append(f"{part} {name}: dtype manifest {want[name].get('dtype')}, engine {have[name].get('dtype')}")
    return diffs


def bgr_to_nv12(bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 (H x W x 3, H and W even) -> NV12 (H*3/2 x W): I420 from cv2, then U and V interleaved."""
    import cv2
    h, w = bgr.shape[:2]
    i420 = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
    y = i420[:h]
    u = i420[h:h + h // 4].reshape(-1)
    v = i420[h + h // 4:].reshape(-1)
    uv = np.empty(u.size * 2, dtype=np.uint8)
    uv[0::2], uv[1::2] = u, v
    return np.ascontiguousarray(np.vstack([y, uv.reshape(h // 2, w)]))


def frame_camera(m: mf.Manifest) -> int:
    """Camera id of the test frame: 0 for yolopx (the masks run there), else the first default camera."""
    if m.type == "yolopx":
        return 0
    permitted, default = m.cameras()
    return (default or permitted or [0])[0]


def _summary(res) -> dict:
    traj = res.get("trajectory")
    return {"detections": len(res.get("detections") or []),
            "masks": [str(x.get("name")) for x in res.get("masks") or [] if isinstance(x, dict)],
            "trajectory_points": len(traj.get("points") or []) if isinstance(traj, dict) else None}


def empty_result(key: str) -> dict:
    """All fields of the CHECK dict with empty values."""
    return {"ok": False, "reason": None, "checks": [], "key": key, "trt_version": None, "engine": None,
            "engine_sha256": None, "trt_match": None, "trt_build_device": None, "trt_device_warning": None,
            "hw_compat": None, "io": None, "gpu_need_mb": None, "gpu_free_mb": None, "inference_ms": None,
            "result_summary": None, "t": None, "duration_s": None}


class _Run:
    """State of one check run. GPU objects are released in free()."""

    def __init__(self, m: mf.Manifest, frame_path: str):
        self.m = m
        self.frame_path = frame_path
        self.out = empty_result(m.key)
        self.hashes: dict[str, str] = {}
        self.engine = None
        self.slot = None
        self.adapter = None
        self.free_before = None

    # -- the checks (each returns its detail text or raises CheckFailed) --------------------------------------
    def sha256(self) -> str:
        files = self.m.files()
        for f in files:
            if not os.path.isfile(f["path"]):
                raise CheckFailed(f"file {f['path']} does not exist")
            got = sha256_file(f["path"])
            self.hashes[f["path"]] = got
            if got != f["sha256"]:
                raise CheckFailed(f"sha256 of {f['path']} does not agree with the manifest "
                                  f"(file {got[:16]}..., manifest {f['sha256'][:16]}...)")
        eng = self._engine()
        if eng and eng["built"]:   # an engine built on this AGX: its sha256 is in build.json
            if not os.path.isfile(eng["path"]):
                raise CheckFailed(f"built engine {eng['path']} does not exist")
            got = sha256_file(eng["path"])
            self.hashes[eng["path"]] = got
            if got != eng["sha256"]:
                raise CheckFailed(f"sha256 of the built engine {eng['path']} does not agree with build.json "
                                  f"(file {got[:16]}..., build.json {str(eng['sha256'])[:16]}...)")
        if eng:
            self.out["engine"] = eng["path"]
            self.out["engine_sha256"] = self.hashes.get(eng["path"])
        return f"{len(files) + (1 if eng and eng['built'] else 0)} file(s) agree"

    def _engine(self) -> dict | None:
        """The engine of this version: the manifest engine file, else the engine built on this AGX (build.json)."""
        from pathlib import Path

        from controller.store import Store
        return Store(str(Path(self.m.folder).parents[1])).engine(self.m)

    def engine_load(self) -> str:
        eng = self._engine()
        if not eng:
            raise CheckFailed("no engine: the manifest has no engine file and no build is done")
        try:
            import tensorrt as trt
            import torch
            self.out["trt_version"] = trt.__version__
            # free GPU memory BEFORE this engine is loaded (the other active models are loaded in agx-infer)
            self.free_before = int(torch.cuda.mem_get_info()[0])
            from infer.models.trt_engine import TrtEngine
            self.engine = TrtEngine(eng["path"])
        except Exception as e:  # noqa: BLE001 - any load error is a failed check
            raise CheckFailed(f"the engine does not load with TensorRT {self.out['trt_version']}: "
                              f"{type(e).__name__}: {e}") from e
        e = self.engine
        self.out.update(trt_match=bool(e.trt_match), trt_build_device=e.trt_build_device,
                        trt_device_warning=e.trt_device_warning, hw_compat=e.hw_compat,
                        io={"inputs": [t.as_dict() for t in e.inputs()], "outputs": [t.as_dict() for t in e.outputs()]})
        return (f"loaded with TensorRT {e.trt_version}; trt_match {e.trt_match}; build device {e.trt_build_device}; "
                f"hardware compatibility {e.hw_compat}")

    def io_match(self) -> str:
        diffs = (io_differences("input", self.m.tensors("input"), self.out["io"]["inputs"])
                 + io_differences("output", self.m.tensors("outputs"), self.out["io"]["outputs"]))
        if diffs:
            raise CheckFailed("; ".join(diffs))
        return f"{len(self.out['io']['inputs'])} input(s) and {len(self.out['io']['outputs'])} output(s) agree"

    def adapter_check(self) -> str:
        try:
            from infer.models.adapters import get_adapter_class
            cls = get_adapter_class(self.m.adapter)
            self.adapter = cls({"options": self.m.adapter_options()}, self.engine)
        except Exception as e:  # noqa: BLE001
            raise CheckFailed(f"adapter {self.m.adapter}: {type(e).__name__}: {e}") from e
        return f"adapter {self.m.adapter} accepts the engine"

    def gpu_memory(self) -> str:
        try:
            self.slot = self.engine.new_slot()
        except Exception as e:  # noqa: BLE001
            raise CheckFailed(f"no execution context could be made: {type(e).__name__}: {e}") from e
        workers = self.m.runtime()["workers"]
        need = self.engine.file_size + workers * (self.slot.context_bytes + self.slot.io_bytes)
        need_mb, free_mb = round(need / MB, 1), round(self.free_before / MB, 1)
        self.out.update(gpu_need_mb=need_mb, gpu_free_mb=free_mb)
        if not need + GPU_RESERVE_MB * MB < self.free_before:
            raise CheckFailed(f"needs {need_mb} MB + {GPU_RESERVE_MB} MB reserve, only {free_mb} MB free")
        return f"needs {need_mb} MB ({workers} worker(s)), {free_mb} MB free"

    def inference(self) -> str:
        import cv2
        from infer.ingest.frame_store import Frame
        if not os.path.isfile(self.frame_path):
            raise CheckFailed(f"the test frame {self.frame_path} does not exist")
        bgr = cv2.imread(self.frame_path, cv2.IMREAD_COLOR)
        if bgr is None:
            raise CheckFailed(f"the test frame {self.frame_path} cannot be read as an image")
        h, w = bgr.shape[0] // 2 * 2, bgr.shape[1] // 2 * 2
        bgr = np.ascontiguousarray(bgr[:h, :w])
        cam = frame_camera(self.m)
        now = time.time_ns()
        frame = Frame(cam, 1, now, now, now, w, h, "nv12", "test-frame", bgr_to_nv12(bgr))
        try:
            inputs, ctx = self.adapter.preprocess(frame)
            outputs, ms = self.slot.infer(inputs)
        except Exception as e:  # noqa: BLE001
            raise CheckFailed(f"inference failed: {type(e).__name__}: {e}") from e
        self.out["inference_ms"] = round(ms, 2)
        bad = []
        for t in self.m.tensors("outputs"):
            name = str(t["name"])
            if name not in outputs:
                bad.append(f"no output {name}")
            elif list(outputs[name].shape) != norm_shape(t.get("shape") or []):
                bad.append(f"output {name} shape {list(outputs[name].shape)}, manifest {norm_shape(t['shape'])}")
        if bad:
            raise CheckFailed("; ".join(bad))
        try:
            res = self.adapter.postprocess(outputs, frame, ctx)
        except Exception as e:  # noqa: BLE001
            raise CheckFailed(f"postprocess failed: {type(e).__name__}: {e}") from e
        if not isinstance(res, dict):
            raise CheckFailed(f"postprocess returned {type(res).__name__}, not a dict")
        if not isinstance(res.get("detections"), list):
            raise CheckFailed("postprocess result: detections is not a list")
        if not (res.get("trajectory") is None or isinstance(res.get("trajectory"), dict)):
            raise CheckFailed("postprocess result: trajectory is not None or a dict")
        if not isinstance(res.get("masks"), list):
            raise CheckFailed("postprocess result: masks is not a list")
        s = dict(_summary(res), cam=cam, frame=self.frame_path, frame_size=[w, h])
        self.out["result_summary"] = s
        return (f"{ms:.1f} ms on cam{cam} {w}x{h}: {s['detections']} detection(s), masks {s['masks']}, "
                f"trajectory points {s['trajectory_points']}")

    # -- run + cleanup -------------------------------------------------------------------------------------
    def run(self) -> dict:
        steps = {"sha256": self.sha256, "engine_load": self.engine_load, "io_match": self.io_match,
                 "adapter": self.adapter_check, "gpu_memory": self.gpu_memory, "inference": self.inference}
        failed = False
        for name in CHECKS:
            if failed:
                self.out["checks"].append({"name": name, "ok": None, "detail": "not run"})
                continue
            try:
                detail = steps[name]()
                self.out["checks"].append({"name": name, "ok": True, "detail": detail})
            except CheckFailed as e:
                failed = True
                self.out["checks"].append({"name": name, "ok": False, "detail": str(e)})
                self.out["reason"] = f"{name} check failed: {e}"
            except Exception as e:  # noqa: BLE001 - an unexpected error is a failed check too
                failed = True
                self.out["checks"].append({"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}"})
                self.out["reason"] = f"{name} check failed: {type(e).__name__}: {e}"
        self.out["ok"] = not failed
        return self.out

    def free(self) -> None:
        """Release the GPU objects in order: contexts, engine, runtime; then the torch cache."""
        if self.slot is not None:
            self.slot.dev.clear()
            self.slot.host.clear()
            self.slot.context = None
            self.slot = None
        self.adapter = None
        if self.engine is not None:
            self.engine.slots.clear()
            self.engine.engine = None
            self.engine.runtime = None
            self.engine = None
        gc.collect()
        if "torch" in sys.modules:
            try:
                import torch
                if torch.cuda.is_initialized():
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - the process ends anyway
                pass


def run_check(folder: str, frame_path: str | None = None) -> dict:
    """Run all checks of one version folder. Returns the CHECK dict (never raises for a model problem).
    frame_path None: the test frame of the store of the folder (default_frame)."""
    frame_path = frame_path or default_frame(folder)
    t0 = time.monotonic()
    m = mf.load(folder)
    if m.errors:
        out = {"ok": False, "reason": "manifest: " + "; ".join(m.errors), "key": m.key,
               "checks": [{"name": n, "ok": None, "detail": "not run"} for n in CHECKS]}
    elif m.adapter is None:
        # no adapter: nothing is loaded
        reason = f"no adapter for type {m.type}"
        out = {"ok": False, "reason": reason, "key": m.key,
               "checks": [{"name": n, "ok": False if n == "adapter" else None,
                           "detail": reason if n == "adapter" else "not run"} for n in CHECKS]}
    else:
        r = _Run(m, frame_path)
        try:
            out = r.run()
        finally:
            r.free()
    base = empty_result(m.key)
    base.update(out)
    base["t"] = time.time()
    base["duration_s"] = round(time.monotonic() - t0, 3)
    return base


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.model_check", description=__doc__.splitlines()[0])
    ap.add_argument("folder", help="model version folder (with manifest.yaml)")
    ap.add_argument("--frame", default=None,
                    help=f"test frame JPEG (default <store>/{TEST_FRAME} of the store of the folder)")
    ap.add_argument("--json", action="store_true", help="print only the CHECK: line")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.folder):
        print(f"model_check: {a.folder} is not a folder", file=sys.stderr)
        return 2
    out = run_check(a.folder, os.path.expanduser(a.frame) if a.frame else None)
    if not a.json:
        for c in out["checks"]:
            mark = {True: "OK  ", False: "FAIL", None: "--  "}[c["ok"]]
            print(f"{mark} {c['name']:<12} {c['detail']}")
        print(f"{'READY' if out['ok'] else 'FAILED'}: {out['key']}" + ("" if out["ok"] else f" ({out['reason']})"))
    print("CHECK:" + json.dumps(out), flush=True)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
