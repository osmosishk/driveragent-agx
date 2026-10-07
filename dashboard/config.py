"""Config loading with defaults (config/dashboard.yaml; template: config/templates/dashboard.yaml).

load_config() also fills the values that come from other values (effective()): node_name (null = the short host
name), infer_status_endpoint / infer_admin_endpoint (null = the ports of infer_config on 127.0.0.1), the services
unit lists (null = made from unit_prefix), engines.scan_dirs (null = []), protected_dirs (null = []).
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from common.env import PROJECT_ROOT
from common.machine import node_name, protected_dirs

DEFAULT_STATUS_PORT = 5562      # agx-infer ports.internal when infer_config has no value
DEFAULT_ADMIN_PORT = 5563       # agx-infer ports.admin when infer_config has no value
UNIT_KINDS = ("dashboard", "infer", "sim")
LOG_UNIT_KINDS = ("infer", "dashboard", "sim")

DEFAULTS: dict = {
    "node_name": None,          # null = the short host name (common/machine.py)
    "port": 8700,
    "port_file": "data/dashboard_port",
    "bind": "0.0.0.0",
    "env_file": ".env",
    "tls_certfile": None,
    "tls_keyfile": None,
    # IPv4 only (the socket is IPv4). Same list as dashboard/auth.py DEFAULT_ALLOW.
    # ops/install.sh adds the private IPv4 subnets of the unit to config/dashboard.yaml.
    "allow_cidrs": ["127.0.0.0/8", "10.42.0.0/30", "100.64.0.0/10"],
    # rk_ip is not used any more: the link monitor pings the paired boards (data/paired_boards.json)
    "link": {
        "ping_interval_s": 2,
        "loss_window_s": 60,
        "clock_method": "auto",
        "clock_http_port": None,
        "clock_http_ports_auto": [80, 8080, 8000],
        "clock_interval_s": 30,
    },
    # null = tcp://127.0.0.1:<infer_config ports.internal / ports.admin> (5562 / 5563 when not given)
    "infer_status_endpoint": None,
    "infer_admin_endpoint": None,
    # model controller (controller/, docs/MODEL_CONTROL_API.md)
    "model_control": True,
    "model_store": "~/agx-models",
    "control_config": "config/control.yaml",
    "control_token_file": "data/control.token",   # read only by the start-up migration (docs/PAIRING_API.md)
    # pairing (docs/PAIRING_API.md, common/pairing_store.py). Both files mode 600, in data/ (not in git).
    "paired_boards_file": "data/paired_boards.json",
    "link_settings_file": "data/link_settings.json",
    "infer_config": "config/infer.yaml",          # the ports that GET /api/pair/info shows (read only)
    "model_check_timeout_s": 180,
    "infer_stale_s": 3,
    "models_config": "config/models.yaml",
    "sources_config": "config/sources.yaml",
    "protected_dirs": [],       # folders that are never written (controller builds, model store)
    "old_stack_root": None,     # null = no old stack: the old-process view is empty ("not configured")
    "camera_status_jitter_s": 0.3,
    "engines": {
        "cache": "data/engines_cache.json",
        "scan_dirs": [],            # more folders to scan (null = []); the engines of models_config are always read
        "scan_interval_s": 1800,
        "inspect_timeout_s": 120,
    },
    "docker": True,
    "unit_prefix": "agx",       # unit names <prefix>-dashboard, <prefix>-infer, <prefix>-sim
    "services": {
        "agx_units": None,      # null = [<prefix>-dashboard, <prefix>-infer, <prefix>-sim]
        "log_units": None,      # null = [<prefix>-infer, <prefix>-dashboard, <prefix>-sim]
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
    # power log (dashboard/power_log.py, common/powerlog.py): the 1 s rails of the health snapshot and the events
    "power_log": {
        "db": "data/power.sqlite",
        "enabled": True,
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


def infer_ports(cfg: dict) -> dict:
    """ports of config/infer.yaml (cfg infer_config). {} when the file cannot be read."""
    try:
        with open(resolve_path(cfg.get("infer_config") or "config/infer.yaml"), encoding="utf-8") as f:
            ports = (yaml.safe_load(f) or {}).get("ports") or {}
        return ports if isinstance(ports, dict) else {}
    except (OSError, TypeError, AttributeError, yaml.YAMLError):
        return {}


def _endpoint(cfg: dict, key: str, port_key: str, default_port: int) -> str:
    if cfg.get(key):
        return str(cfg[key])
    port = infer_ports(cfg).get(port_key)
    return f"tcp://127.0.0.1:{port if isinstance(port, int) and not isinstance(port, bool) else default_port}"


def infer_status_endpoint(cfg: dict) -> str:
    """Internal status PUB of agx-infer: the config value, else 127.0.0.1 and infer_config ports.internal."""
    return _endpoint(cfg, "infer_status_endpoint", "internal", DEFAULT_STATUS_PORT)


def infer_admin_endpoint(cfg: dict) -> str:
    """Admin REP of agx-infer: the config value, else 127.0.0.1 and infer_config ports.admin."""
    return _endpoint(cfg, "infer_admin_endpoint", "admin", DEFAULT_ADMIN_PORT)


def unit_names(cfg: dict, kinds=UNIT_KINDS) -> list[str]:
    prefix = str(cfg.get("unit_prefix") or "agx")
    return [f"{prefix}-{k}" for k in kinds]


def service_units(cfg: dict) -> tuple[list[str], list[str]]:
    """(agx_units, log_units): the services lists of the config, else made from unit_prefix."""
    sc = cfg.get("services") or {}
    agx = sc.get("agx_units")
    logs = sc.get("log_units")
    return (list(agx) if agx is not None else unit_names(cfg, UNIT_KINDS),
            list(logs) if logs is not None else unit_names(cfg, LOG_UNIT_KINDS))


def effective(cfg: dict) -> dict:
    """Fill the values that come from other values (see the module text). Changes cfg and returns it."""
    cfg["node_name"] = node_name(cfg)
    cfg["infer_status_endpoint"] = infer_status_endpoint(cfg)
    cfg["infer_admin_endpoint"] = infer_admin_endpoint(cfg)
    if not isinstance(cfg.get("services"), dict):
        cfg["services"] = copy.deepcopy(DEFAULTS["services"])
    cfg["services"]["agx_units"], cfg["services"]["log_units"] = service_units(cfg)
    if not isinstance(cfg.get("engines"), dict):
        cfg["engines"] = copy.deepcopy(DEFAULTS["engines"])
    if cfg["engines"].get("scan_dirs") is None:
        cfg["engines"]["scan_dirs"] = []
    cfg["protected_dirs"] = protected_dirs(cfg.get("protected_dirs"))
    if not cfg.get("old_stack_root"):
        cfg["old_stack_root"] = None
    return cfg


def load_config(path: str | None) -> dict:
    data: dict = {}
    if path:
        p = resolve_path(path)
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, data)
    # the file that gave the values: the pairing migration reads the old rk_ip from it (not from the code default)
    cfg["config_file"] = str(resolve_path(path)) if path else None
    # flat aliases accepted for convenience
    if "history_db" in data:
        cfg["history"]["db"] = data["history_db"]
    if "history_max_mb" in data:
        cfg["history"]["max_mb"] = data["history_max_mb"]
    return effective(cfg)
