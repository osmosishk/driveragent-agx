"""Models (part B) and cameras (part C) documents: config/models.yaml + engine facts + agx-infer status.

Camera state is calculated at REQUEST time (not only from the last status message):
  known = status_t - last_frame_t   frame age when agx-infer made the status (a lower limit)
  upper = now - last_frame_t        time since the newest frame we know of (an upper limit)
  hold  = min(status interval + jitter, no_signal_s + 0.5)   (about 1.0 + 0.3 s). Inside this time,
                                    frames that came after the status are not known yet, so `upper`
                                    alone is not a proof. The cap (1.5 s) keeps a stop visible on the
                                    page in less than 2 s (T6) also when agx-infer sends status slowly.
  NO SIGNAL  known >= no_signal_s (1.0 s)  or  upper >= max(no_signal_s, hold)
  STALE      known >= stale_s (0.5 s)      or  upper >= max(stale_s, hold)
  else SIMULATED (simulated source, R13) or OK.  No agx-infer status for 3 s -> NO DATA.
With a 1 Hz status a camera changes to NO SIGNAL 1.0 .. 1.3 s after its last frame (also between
two status messages), and a camera with frames does not change to STALE between two status messages.
With a status faster than 1/(no_signal_s - jitter) the change comes at no_signal_s exactly.
With a status slower than about 1/1.2 Hz the cap applies: a stop shows in 1.5 s at the latest, but
a camera with frames can show NO SIGNAL for a short time between two status messages.
The same rule is in static/tiles.js (tileState). The page gets an SSE event at once for each new
status (app.py), so it knows a new frame time as soon as the server knows it.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import yaml

from dashboard.collectors.infer_status import (NOT_RUNNING, _d, _l, cam_simulated, model_simulated,
                                                node_simulated)

log = logging.getLogger("dashboard.views")

NUM_CAMS = 6
SIM = "SIMULATED"
GPU_MEM_NOTE = "estimate"
_LAT_KEYS = ("pre", "infer", "post", "total")
_ERR_KEYS = ("last_error", "last_error_t", "errors_total", "queue_ms", "auto_restarts")
HOLD_CAP_EXTRA_S = 0.5  # hold_s <= no_signal_s + this (1.5 s): page NO SIGNAL < 2 s with the 250 ms check


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def camera_state(last_frame_t, now: float, status_t, stale_s: float, no_signal_s: float, hold_s: float,
                 simulated: bool):
    """(state, upper_age_s). Same rule as tileState() in static/tiles.js."""
    if last_frame_t is None:
        return "NO SIGNAL", None
    upper = max(0.0, now - float(last_frame_t))
    known = max(0.0, float(status_t) - float(last_frame_t)) if status_t is not None else upper
    if known >= no_signal_s or upper >= max(no_signal_s, hold_s):
        return "NO SIGNAL", upper
    if known >= stale_s or upper >= max(stale_s, hold_s):
        return "STALE", upper
    return (SIM if simulated else "OK"), upper


class _YamlFile:
    """Read a YAML file again only when its mtime changes."""

    def __init__(self, path):
        self.path = str(path) if path else None
        self._mtime = None
        self._data = None
        self.error = None
        self._lock = threading.Lock()

    def get(self):
        if not self.path:
            return None
        with self._lock:
            try:
                m = os.stat(self.path).st_mtime_ns
                if m != self._mtime:
                    with open(self.path, encoding="utf-8") as f:
                        self._data = yaml.safe_load(f) or {}
                    self._mtime = m
                    self.error = None
            except (OSError, yaml.YAMLError) as e:
                self.error = f"cannot read {self.path}: {e}"
            return self._data


class InferViews:
    def __init__(self, infer, scanner, models_config, sources_config, no_data_s: float = 3.0,
                 status_jitter_s: float = 0.3):
        self.infer = infer
        self.status_jitter_s = float(status_jitter_s)
        self.scanner = scanner
        self.models_yaml = _YamlFile(models_config)
        self.sources_yaml = _YamlFile(sources_config)
        self.no_data_s = float(no_data_s)

    # ---- config
    def config_models(self) -> list[dict]:
        d = self.models_yaml.get() or {}
        return [m for m in (d.get("models") or []) if isinstance(m, dict) and m.get("name")]

    def config_engines(self) -> list[str]:
        return [str(m["engine"]) for m in self.config_models() if m.get("engine")]

    def limits(self, st: dict | None) -> tuple[float, float, str]:
        """(stale_s, no_signal_s, source). agx-infer status first, then config/sources.yaml."""
        for src in (_d(st), _d(_d(st).get("ingest"))):
            s, n = _num(src.get("stale_s")), _num(src.get("no_signal_s"))
            if s is not None and n is not None:
                return s, n, "agx-infer status"
        d = self.sources_yaml.get() or {}
        s, n = _num(d.get("stale_s")), _num(d.get("no_signal_s"))
        if s is not None and n is not None:
            return s, n, str(self.sources_yaml.path)
        return 0.5, 1.0, "default"

    def roles(self) -> dict[int, dict]:
        d = self.sources_yaml.get() or {}
        rk = d.get("mode") == "rk"   # same rule as infer/ingest: role_rk in rk mode
        out = {}
        for c in _l(d.get("cameras")):
            if isinstance(c, dict) and isinstance(c.get("cam"), int):
                role = (c.get("role_rk") if rk else None) or c.get("role")
                out[c["cam"]] = {"role": role, "port": c.get("port")}
        return out

    # ---- cameras
    def timing(self, st: dict | None = None) -> tuple[float, float, str, float, float]:
        """(stale_s, no_signal_s, limits source, status period_s, hold_s)."""
        if st is None:
            st, _ = self.infer.raw()
        stale_s, no_signal_s, lim_src = self.limits(st)
        period = min(5.0, max(0.05, _num(getattr(self.infer, "period_s", 1.0)) or 1.0))
        hold_s = round(min(period + self.status_jitter_s, no_signal_s + HOLD_CAP_EXTRA_S), 3)
        return stale_s, no_signal_s, lim_src, period, hold_s

    def hold_s(self) -> float:
        return self.timing()[4]

    def cameras_doc(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        st, state, reason, age = self.infer.current()
        raw, rx = self.infer.raw()
        stale_s, no_signal_s, lim_src, period, hold_s = self.timing(st if st is not None else raw)
        status_t = _num(_d(st).get("t"))
        if status_t is None or (rx is not None and status_t > rx + 1.0):
            status_t = rx  # no (or a wrong) status time: use the receive time
        roles = self.roles()
        node_sim = node_simulated(st.get("node")) if st is not None else False
        by_cam = {}
        if st is not None:
            for c in _l(st.get("cameras")):
                if isinstance(c, dict) and isinstance(c.get("cam"), int) and 0 <= c["cam"] < NUM_CAMS:
                    by_cam[c["cam"]] = c
        cams = []
        for n in range(NUM_CAMS):
            base = {"cam": n, "role": (roles.get(n) or {}).get("role"), "port": (roles.get(n) or {}).get("port")}
            snap = self.infer.snapshot(n)
            snap_t = snap[1] if snap else None
            c = by_cam.get(n)
            if st is None or c is None:
                why = (reason or NOT_RUNNING) if st is None else "agx-infer status has no entry for this camera"
                base.update({"state": "NO DATA", "reason": why, "simulated": False, "label": None,
                             "age_ms": None, "last_frame_t": None, "snapshot_t": snap_t})
                cams.append(base)
                continue
            out = dict(base)
            out.update({k: v for k, v in c.items() if k not in ("state",)})
            if out.get("role") is None:
                out["role"] = base["role"]
            sim = cam_simulated(c, node_sim)
            lft = _num(c.get("last_frame_t"))
            if lft is None and _num(c.get("frame_age_ms")) is not None and _num(st.get("t")) is not None:
                lft = float(st["t"]) - float(c["frame_age_ms"]) / 1000.0
            cs, a = camera_state(lft, now, status_t, stale_s, no_signal_s, hold_s, sim)
            dm = _d(c.get("decode_ms"))
            if cs == "NO SIGNAL":
                # no frame now: the rates of the last status are not current
                out.update({"fps": None, "fps_5s": None, "bitrate_kbps": None,
                            "values_note": "no frame: frame rate and bit rate not shown"})
            out.update({
                "state": cs,
                "reason": None if cs in ("OK", SIM) else (
                    "no frame received" if a is None else f"last frame {a:.1f} s ago"),
                "infer_state": c.get("state"),
                "simulated": sim,
                "label": SIM if sim else None,
                "last_frame_t": lft,
                "age_ms": round(a * 1000.0, 1) if a is not None else None,
                "decode_p50_ms": _num(dm.get("p50")),
                # ingest error text of this camera (agx-infer status), null when there is none
                "last_error": (str(c["last_error"])[:300]
                               if isinstance(c.get("last_error"), str) and c["last_error"] else None),
                "snapshot_t": snap_t,
            })
            cams.append(out)
        any_sim = any(c.get("simulated") for c in cams)
        return {
            "available": st is not None,
            "status_seq": getattr(self.infer, "seq", None),
            "reason": None if st is not None else (reason or NOT_RUNNING),
            "infer_state": state,
            "server_t": now,
            "status_rx_t": rx,
            "status_t": status_t,
            "status_period_s": round(period, 3),
            "hold_s": hold_s,
            "hold_cap_s": round(no_signal_s + HOLD_CAP_EXTRA_S, 3),
            "status_age_s": round(now - rx, 2) if rx else None,
            "stale_s": stale_s,
            "no_signal_s": no_signal_s,
            "no_data_s": self.no_data_s,
            "limits_source": lim_src,
            "simulated": any_sim,
            "label": SIM if any_sim else None,
            "cameras": cams,
        }

    # ---- models
    @staticmethod
    def _io_from_facts(facts: dict | None, mode: str) -> list[dict]:
        if not facts:
            return []
        return [{"name": t.get("name"), "shape": t.get("shape"), "dtype": t.get("dtype")}
                for t in _l(facts.get("io")) if isinstance(t, dict) and t.get("mode") == mode]

    @staticmethod
    def _engine_part(path: str | None, facts: dict | None, note: str | None = None) -> dict:
        real = os.path.realpath(path) if path else None
        f = facts or {}
        return {
            "engine": path,
            "engine_file": os.path.basename(path) if path else None,
            "engine_realpath": real,
            "engine_exists": bool(real and os.path.exists(real)),
            "size_bytes": f.get("size"),
            "mtime": f.get("mtime"),
            "sha256_16": f.get("sha256_16"),
            "engine_load": f.get("load"),
            "engine_error": f.get("error"),
            "trt_version": f.get("trt_version"),
            "trt_match": f.get("trt_match"),
            "trt_build_device": f.get("trt_build_device"),
            "trt_device_warning": f.get("trt_device_warning"),  # information only
            "load_warnings": [str(m) for m in _l(f.get("messages"))],
            "device_memory_bytes": f.get("device_memory"),
            "inspected": bool(facts),
            "engine_note": note,
        }

    @staticmethod
    def _error_fields(sm: dict) -> dict:
        """last_error, last_error_t, errors_total, queue_ms, auto_restarts of one model entry of the
        agx-infer status. A field that is missing or has a wrong type gives None."""
        le = sm.get("last_error")
        q = sm.get("queue_ms")
        q = {p: _num(_d(q).get(p)) for p in ("p50", "p95", "p99")} if isinstance(q, dict) else None
        ints = {k: (sm[k] if isinstance(sm.get(k), int) and not isinstance(sm.get(k), bool) else None)
                for k in ("errors_total", "auto_restarts")}
        return {"last_error": str(le)[:500] if isinstance(le, str) and le else None,
                "last_error_t": _num(sm.get("last_error_t")),
                "queue_ms": q, **ints}

    def _row(self, mc: dict | None, sm: dict | None, st_ok: bool, node_sim: bool) -> dict:
        mc = mc or {}
        sm = sm if isinstance(sm, dict) else None
        name = mc.get("name") or (sm or {}).get("name")
        enabled = bool(mc.get("enabled", (sm or {}).get("enabled", False)))
        path = mc.get("engine") or (sm or {}).get("engine")
        facts, note = self.scanner.facts_note(path) if path else (None, None)
        row = {"name": name, "group": mc.get("group"), "enabled": enabled, "in_config": bool(mc),
               "adapter": mc.get("adapter")}
        row.update(self._engine_part(path, facts, note))
        if path is None:
            row["engine_error"] = "no engine file in the configuration"
        row["inputs"] = self._io_from_facts(facts, "INPUT")
        row["outputs"] = self._io_from_facts(facts, "OUTPUT")
        row["cameras"] = list(mc.get("cameras") or [])
        row.update({"state": None, "error": None, "reason": None, "fps": None,
                    "lat_ms": {k: {"p50": None, "p95": None, "p99": None} for k in _LAT_KEYS},
                    "gpu_mem_mb": None, "gpu_mem_note": GPU_MEM_NOTE, "results_total": None,
                    "live": False, "simulated": False, "label": None})
        # error / queue fields: null when agx-infer does not send them (no fake values)
        row.update({k: None for k in _ERR_KEYS})
        if sm is not None:
            sim = model_simulated(sm, node_sim)
            lat = _d(sm.get("lat_ms"))
            row.update({
                "state": sm.get("state") or "NO DATA",
                "error": sm.get("error"),
                "reason": sm.get("reason") or (mc.get("reason") if not enabled else None),
                "fps": _num(sm.get("fps")),
                "lat_ms": {k: {p: _num(_d(lat.get(k)).get(p)) for p in ("p50", "p95", "p99")}
                           for k in _LAT_KEYS},
                "gpu_mem_mb": _num(sm.get("gpu_mem_mb")),
                "gpu_mem_note": ("estimate" if not sm.get("gpu_mem_note") else
                                 (sm["gpu_mem_note"] if "estimate" in str(sm["gpu_mem_note"]).lower()
                                  else "estimate: " + str(sm["gpu_mem_note"]))),
                "results_total": sm.get("results_total") if isinstance(sm.get("results_total"), int) else None,
                "engine_version": sm.get("engine_version"),
                "live": True,
                "simulated": sim,
                "label": SIM if sim else None,
            })
            row.update(self._error_fields(sm))
            if _l(sm.get("cameras")):
                row["cameras"] = list(sm["cameras"])
            # An agx-infer with the 2026-10-07 rule sends trt_build_device for a loaded engine. Its trt values are
            # the values of THIS boot (the device warning depends on the boot), so they replace the inspection
            # values, also when they are empty. An older agx-infer (no trt_build_device key, old trt_match rule)
            # keeps the inspection values, which use the new rule.
            live_trt = "trt_build_device" in sm and isinstance(sm.get("trt_match"), bool)
            if live_trt:
                row["trt_match"] = sm["trt_match"]
                for k in ("trt_build_device", "trt_device_warning"):
                    row[k] = str(sm[k]) if sm.get(k) else None
                row["load_warnings"] = [str(w) for w in _l(sm.get("load_warnings"))]
            elif row.get("trt_match") is None and isinstance(sm.get("trt_match"), bool):
                row["trt_match"] = sm["trt_match"]  # no inspection facts yet: the value of the older agx-infer
            if sm.get("trt_version"):
                row["trt_version"] = str(sm["trt_version"])
            if not live_trt and _l(sm.get("load_warnings")):
                row["load_warnings"] = [str(w) for w in sm["load_warnings"]]
            for k in ("inputs", "outputs"):
                io = [t for t in _l(sm.get(k)) if isinstance(t, dict)]
                if io:
                    row[k] = io
        elif not enabled:
            row.update({"state": "OFF", "reason": mc.get("reason") or "disabled in config/models.yaml"})
        elif st_ok:
            row.update({"state": "NO DATA", "reason": "agx-infer status has no entry for this model"})
        else:
            row.update({"state": "NO DATA", "reason": NOT_RUNNING})
        return row

    def models_doc(self) -> dict:
        st, state, reason, age = self.infer.current()
        node_sim = node_simulated(st.get("node")) if st is not None else False
        live = {}
        if st is not None:
            for m in _l(st.get("models")):
                if isinstance(m, dict) and m.get("name"):
                    live[str(m["name"])] = m
        rows = []
        cfg = self.config_models()
        for mc in cfg:
            rows.append(self._row(mc, live.pop(str(mc["name"]), None), st is not None, node_sim))
        for sm in live.values():  # in the agx-infer status, but not in config/models.yaml
            rows.append(self._row(None, sm, True, node_sim))
        cfg_real = {os.path.realpath(p) for p in self.config_engines()}
        extra = []
        for real, f, note in self.scanner.found_notes():
            if real in cfg_real:
                continue
            e = self._engine_part((f or {}).get("path") or real, f, note)
            e["inputs"] = self._io_from_facts(f, "INPUT")
            e["outputs"] = self._io_from_facts(f, "OUTPUT")
            extra.append(e)
        any_sim = any(r.get("simulated") for r in rows)
        err = self.models_yaml.error
        return {
            "available": st is not None,
            "reason": None if st is not None else (reason or NOT_RUNNING),
            "infer_state": state,
            "status_age_s": age,
            "models_config": self.models_yaml.path,
            "config_error": err,
            "simulated": any_sim,
            "label": SIM if any_sim else None,
            "gpu_mem_note": "GPU memory values are an estimate (engine file + activation + I/O)",
            "models": rows,
            "engines_not_in_config": extra,
            "engine_scan": self.scanner.status(),
        }

    # ---- health summary
    def health_infer_extra(self, now: float | None = None) -> dict:
        """Added to /api/health "infer". Camera states are the states calculated NOW (the same as
        /api/cameras); cameras_summary is built from them too, so one reply has one state per camera.
        R13: every simulated item has "label": "SIMULATED"."""
        cams = self.cameras_doc(now)
        md = self.models_doc()
        st, _, _, _ = self.infer.current()
        pub = _d(_d(st).get("publish"))
        reported = {c.get("cam"): c.get("state") for c in _l(_d(st).get("cameras")) if isinstance(c, dict)}
        cam_items = [{"cam": c["cam"], "role": c.get("role"), "state": c["state"],
                      "reported_state": reported.get(c["cam"]), "fps": _num(c.get("fps")),
                      "frame_age_ms": _num(c.get("frame_age_ms")), "age_ms": c.get("age_ms"),
                      "simulated": bool(c.get("simulated")),
                      "label": SIM if c.get("simulated") else None} for c in cams["cameras"]]
        states: dict[str, int] = {}
        for c in cam_items:
            states[c["state"]] = states.get(c["state"], 0) + 1
        csim = any(c["simulated"] for c in cam_items)
        return {
            "models": [{"name": r["name"], "state": r["state"], "fps": r["fps"], "simulated": r["simulated"],
                        "label": SIM if r["simulated"] else None} for r in md["models"]],
            "cameras": [{k: c[k] for k in ("cam", "state", "fps", "simulated", "label")} for c in cam_items],
            "cameras_summary": {"total": len(cam_items), "states": states, "simulated": csim,
                                "label": SIM if csim else None,
                                "state_basis": "calculated now from last_frame_t (see /api/cameras)",
                                "per_cam": cam_items},
            "results_rate_hz": _num(pub.get("results_rate_hz")),
            "subscribers": pub.get("subscribers") if isinstance(pub.get("subscribers"), int) else None,
        }
