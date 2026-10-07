"""TensorRT 10 engine wrapper: one deserialized engine, N execution contexts, torch CUDA buffers.

The old DriverGuard runner used pycuda with non-pinned host buffers (jetson_runtime/trt_runner.py).
This wrapper keeps the same TensorRT 10 tensor API calls (deserialize_cuda_engine,
create_execution_context, set_input_shape, set_tensor_address, execute_async_v3) but allocates the
device buffers with torch (CUDA 12.6) and uses pinned host buffers, so several worker threads can share
the CUDA context safely.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass

import numpy as np
import tensorrt as trt
import torch

from common import trt_compat

_TRT_TO_TORCH = {
    trt.DataType.FLOAT: torch.float32,
    trt.DataType.HALF: torch.float16,
    trt.DataType.INT32: torch.int32,
    trt.DataType.INT8: torch.int8,
    trt.DataType.BOOL: torch.bool,
}
if hasattr(trt.DataType, "INT64"):
    _TRT_TO_TORCH[trt.DataType.INT64] = torch.int64


class _Logger(trt.ILogger):
    def __init__(self):
        trt.ILogger.__init__(self)
        self.messages: list[str] = []

    def log(self, severity, msg):
        if severity <= trt.ILogger.Severity.WARNING:
            self.messages.append(f"{severity.name}: {msg}")


@dataclass
class TensorInfo:
    name: str
    mode: str          # "INPUT" | "OUTPUT"
    shape: tuple
    dtype: str

    def as_dict(self):
        return {"name": self.name, "mode": self.mode, "shape": list(self.shape), "dtype": self.dtype}


class EngineLoadError(RuntimeError):
    pass


def file_sha256_16(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


class TrtEngine:
    """Deserialized engine. Thread-safe factory for ExecutionSlots (one per worker thread)."""

    def __init__(self, path: str):
        self.path = path
        self.realpath = os.path.realpath(path)
        self.logger = _Logger()
        self.runtime = trt.Runtime(self.logger)
        try:
            with open(self.realpath, "rb") as f:
                data = f.read()
        except OSError as e:
            raise EngineLoadError(f"cannot read engine: {e}") from e
        self.file_size = len(data)
        self.sha256_16 = hashlib.sha256(data).hexdigest()[:16]
        self.engine = self.runtime.deserialize_cuda_engine(data)
        del data
        if self.engine is None:
            msgs = "; ".join(self.logger.messages[-3:]) or "deserialize_cuda_engine returned None"
            raise EngineLoadError(msgs)
        self.tensors: list[TensorInfo] = []
        for i in range(self.engine.num_io_tensors):
            n = self.engine.get_tensor_name(i)
            self.tensors.append(TensorInfo(
                n, self.engine.get_tensor_mode(n).name,
                tuple(int(x) for x in self.engine.get_tensor_shape(n)),
                self.engine.get_tensor_dtype(n).name))
        self.device_memory = int(getattr(self.engine, "device_memory_size_v2", 0)
                                 or self.engine.device_memory_size)
        self.trt_version = trt.__version__
        self.load_warnings = [m for m in self.logger.messages if m.startswith("WARNING")]
        hw = getattr(self.engine, "hardware_compatibility_level", None)
        self.hw_compat = getattr(hw, "name", None)
        # trt_match: loads with the installed TensorRT + built on an Orin GPU (common/trt_compat.py).
        # The device warning is information only.
        self._trt_match, self.trt_build_device = trt_compat.verdict(True, self.hw_compat,
                                                                    trt_compat.host_is_orin())
        self.trt_device_warning = trt_compat.device_warning(self.load_warnings)
        self._lock = threading.Lock()
        self.slots: list[ExecutionSlot] = []

    @property
    def trt_match(self) -> bool:
        return self._trt_match

    @property
    def version_tag(self) -> str:
        return f"{os.path.basename(self.realpath)}:{self.sha256_16}"

    def inputs(self):
        return [t for t in self.tensors if t.mode == "INPUT"]

    def outputs(self):
        return [t for t in self.tensors if t.mode == "OUTPUT"]

    def new_slot(self) -> "ExecutionSlot":
        with self._lock:
            s = ExecutionSlot(self)
            self.slots.append(s)
            return s

    def gpu_bytes_estimate(self) -> int:
        """Engine weights (~file size) + activation memory per context + I/O buffers per context."""
        return self.file_size + sum(s.context_bytes + s.io_bytes for s in self.slots)


class ExecutionSlot:
    """One execution context + CUDA stream + device/pinned-host I/O buffers. Use from ONE thread."""

    def __init__(self, eng: TrtEngine):
        self.eng = eng
        self.context = eng.engine.create_execution_context()
        if self.context is None:
            raise EngineLoadError("create_execution_context returned None")
        self.stream = torch.cuda.Stream()
        self.dev: dict[str, torch.Tensor] = {}
        self.host: dict[str, torch.Tensor] = {}
        self.io_bytes = 0
        self.context_bytes = eng.device_memory
        for t in eng.tensors:
            shape = tuple(1 if d < 0 else d for d in t.shape)
            if t.mode == "INPUT":
                self.context.set_input_shape(t.name, shape)
            dt = _TRT_TO_TORCH[eng.engine.get_tensor_dtype(t.name)]
            d = torch.empty(shape, dtype=dt, device="cuda")
            h = torch.empty(shape, dtype=dt, pin_memory=True)
            self.dev[t.name], self.host[t.name] = d, h
            self.io_bytes += d.numel() * d.element_size()
            self.context.set_tensor_address(t.name, d.data_ptr())

    def infer(self, inputs: dict[str, np.ndarray]) -> tuple[dict[str, np.ndarray], float]:
        """Copy inputs, run, copy outputs back. Returns (outputs as numpy copies, inference ms)."""
        t0 = time.perf_counter()
        with torch.cuda.stream(self.stream):
            for name, arr in inputs.items():
                h = self.host[name]
                src = torch.from_numpy(np.ascontiguousarray(arr, dtype=h.numpy().dtype))
                if tuple(src.shape) != tuple(h.shape):
                    raise ValueError(f"input {name}: shape {tuple(src.shape)} != {tuple(h.shape)}")
                h.copy_(src)
                self.dev[name].copy_(h, non_blocking=True)
            ok = self.context.execute_async_v3(self.stream.cuda_stream)
            if not ok:
                raise RuntimeError("execute_async_v3 returned False")
            for t in self.eng.outputs():
                self.host[t.name].copy_(self.dev[t.name], non_blocking=True)
        self.stream.synchronize()
        outs = {t.name: self.host[t.name].numpy().copy() for t in self.eng.outputs()}
        return outs, (time.perf_counter() - t0) * 1000.0
