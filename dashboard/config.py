"""Config loading with defaults (config/dashboard.yaml)."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from common.env import PROJECT_ROOT

DEFAULTS: dict = {
    "port": 8700,
    "port_file": "data/dashboard_port",
    "bind": "0.0.0.0",
    "env_file": ".env",
    "tls_certfile": None,
    "tls_keyfile": None,
    "allow_cidrs": [
        "127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "100.64.0.0/10", "169.254.0.0/16", "fc00::/7", "fe80::/10",
    ],
    "rk_ip": "100.64.0.180",
    "link": {
        "ping_interval_s": 2,
        "loss_window_s": 60,
        "clock_method": "auto",
        "clock_http_port": None,
        "clock_http_ports_auto": [80, 8080, 8000],
        "clock_interval_s": 30,
    },
    "infer_status_endpoint": "tcp://127.0.0.1:5562",
    "infer_stale_s": 3,
    "models_config": "config/models.yaml",
    "sources_config": "config/sources.yaml",
    "camera_status_jitter_s": 0.3,
    "engines": {
        "cache": "data/engines_cache.json",
        "scan_dirs": None,          # None = tools.inspect_engines.DEFAULT_SCAN
        "scan_interval_s": 1800,
        "inspect_timeout_s": 120,
    },
    "docker": True,
    "services": {
        "agx_units": ["agx-dashboard", "agx-infer", "agx-sim"],
        "log_units": ["agx-infer", "agx-dashboard"],
        "unit_refresh_s": 5,
        "docker_refresh_s": 10,
        "docker_inspect_cache_s": 30,
    },
    "old_units": ["docker.service"],
    "history": {
        "db": "data/history.sqlite",
        "max_mb": 50,
        "memory_s": 3600,
        "db_step_s": 10,
        "db_keep_s": 86400,
        "cleanup_interval_s": 600,
    },
    "limits": {
        "temp_c": {"warn": 70, "crit": 85},
        "ram_pct": {"warn": 80, "crit": 90},
        "disk_pct": {"warn": 80, "crit": 90},
    },
    "nvpmodel_interval_s": 30,
    "mqtt_interval_s": 5,
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve_path(p: str | None) -> Path | None:
    if not p:
        return None
    pp = Path(p)
    return pp if pp.is_absolute() else PROJECT_ROOT / pp


def load_config(path: str | None) -> dict:
    data: dict = {}
    if path:
        p = resolve_path(path)
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, data)
    # flat aliases accepted for convenience
    if "history_db" in data:
        cfg["history"]["db"] = data["history_db"]
    if "history_max_mb" in data:
        cfg["history"]["max_mb"] = data["history_max_mb"]
    return cfg
