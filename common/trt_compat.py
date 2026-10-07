"""TensorRT engine compatibility rule: trt_match and the device warning (owner decision 2026-10-07).

Pure Python (no TensorRT, CUDA or torch import), so that agx-infer (infer/models/trt_engine.py) and the
dashboard engine list (tools/inspect_engines.py) use the same rule.

trt_match is True when the engine loads with the installed TensorRT AND its build device is an Orin GPU.
Build device: TensorRT loads an engine that was built without hardware compatibility
(hardware_compatibility_level NONE) only on a GPU with the same compute capability as the build GPU, and
fails on any other GPU. Thus such an engine that loads on this Jetson Orin (tegra234, sm87) was built on an
Orin GPU. A hardware-compatible engine (AMPERE_PLUS) loads on any Ampere or newer GPU, so its build device
is not known: trt_match False.

The TensorRT warning "Using an engine plan file across different models of devices ..." is NOT part of
trt_match. It is reported in the separate field trt_device_warning, for information only. On AGX02 it comes
from a few kB difference of the total memory between the build boot and the current boot (a plan stores the
total memory of its build device; MemTotal changes at each boot), not from a different GPU.
"""
from __future__ import annotations

DEVICE_WARNING_TEXT = "different models of devices"
ORIN_DT_COMPATIBLE = b"nvidia,tegra234"     # Jetson AGX Orin / Orin NX / Orin Nano: Orin GPU, sm87
DT_COMPATIBLE_PATH = "/proc/device-tree/compatible"
ORIN_GPU = "Orin GPU (sm87)"


def host_is_orin(path: str = DT_COMPATIBLE_PATH) -> bool:
    """True when this machine is a Jetson Orin (device tree compatible list has nvidia,tegra234)."""
    try:
        with open(path, "rb") as f:
            return ORIN_DT_COMPATIBLE in f.read().split(b"\0")
    except OSError:
        return False


def device_warning(messages) -> str | None:
    """The TensorRT device warning among the load messages (information only), else None."""
    hits = [str(m) for m in (messages or []) if DEVICE_WARNING_TEXT in str(m)]
    if not hits:
        return None
    return next((m for m in hits if m.startswith("WARNING")), hits[0])


def verdict(loaded: bool, hw_compat: str | None, host_orin: bool) -> tuple[bool, str | None]:
    """(trt_match, build device text). loaded: the engine deserialized with the installed TensorRT.
    hw_compat: name of ICudaEngine.hardware_compatibility_level ("NONE", "AMPERE_PLUS") or None."""
    if not loaded:
        return False, None
    if hw_compat == "NONE":
        if host_orin:
            return True, ORIN_GPU
        return False, "same GPU type as this machine, which is not an Orin"
    if hw_compat is None:
        return False, "unknown: no hardware compatibility level"
    return False, f"unknown: hardware compatibility {hw_compat} loads on other GPU types too"
