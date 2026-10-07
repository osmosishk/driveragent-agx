"""AGX inference node.

  python -m infer.main --config config/infer.yaml [--mode sim|rk|file] [--seconds N]

Parts: Ingest (six cameras -> FrameStore), ModelManager (TensorRT models; on_result ->
ResultPublisher 5560 + result cache), StatusPublisher (5561 AgxInferStatus + 127.0.0.1:5562 JSON),
SnapshotTask (127.0.0.1:5562 JPEG), AdminServer (127.0.0.1:5563), RkInfoReceiver (SUB bound on 5564: DA01
RkCameraInfo, the camera names and roles; schema v2; a bind error leaves it out with a node error).
Board addresses: data/paired_boards.json (config/infer.yaml paired_boards_file; written by the pairing code of
agx-dashboard) is the one source of the FrameLink source filter and the RkCameraInfo peer allowlist. It is read at
start and again when it changes (checked once per status tick, 1 s), with no restart: the receive processes and the
ZAP handler get the new set (Node.check_paired_boards). A problem never opens the filter (a bad file at start
or boards with no usable address: refuse all; infer.ingest.ingest.PairedBoards).
Start set (config/infer.yaml start_set): "last_good" (default) runs the controller's last good set
(<model_store>/_state/last_good.json, built with controller.runtime.configs_for_set) when that file has a
non-empty set; else (and with "models_yaml") config/models.yaml as before. Instances can then be added and
removed at runtime over the admin socket (no process restart).
Logs go to stdout (journald). SIGTERM / SIGINT: clean stop of all parts within 5 s.
Rule R8: this node publishes perception results only. Rule R13: results from simulated frames have
simulated = true and envelope flag bit0.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time

import yaml
import zmq

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
log = logging.getLogger("infer.main")


def _path(p: str | None) -> str | None:
    if p is None:
        return None
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


START_SETS = ("last_good", "models_yaml")


def _models_yaml(cfg: dict) -> tuple[dict, str]:
    path = _path(cfg.get("models_config", "config/models.yaml"))
    with open(path) as f:
        return (yaml.safe_load(f) or {}), path


def select_models(cfg: dict) -> tuple[dict, str, list[str]]:
    """The model list at start: ({"models": [...]}, source in plain words, problems).

    start_set last_good (default): the controller's last good set when <model_store>/_state/last_good.json has a
    non-empty "set". A version that cannot run is left out and its reason is a problem. When no version of the
    set can run, config/models.yaml is used (and that is a problem too). start_set models_yaml, or no last good
    set: config/models.yaml."""
    problems: list[str] = []
    why = "no last good set"
    mode = str(cfg.get("start_set") or "last_good")
    if mode not in START_SETS:
        problems.append(f"start_set {mode!r} is not one of {', '.join(START_SETS)}: config/models.yaml is used")
        mode = "models_yaml"
    if mode == "last_good":
        try:
            from controller import runtime
            from controller.store import Store
            store = Store(cfg.get("model_store") or None)
            d = runtime.read_set(store, runtime.LAST_GOOD)
            items = list(d["set"]) if d else []
            if items:
                cfgs, bad = runtime.configs_for_set(store, items)
                problems += [f"last good set: {b}" for b in bad]
                where = store.state / runtime.LAST_GOOD
                if cfgs:
                    keys = ", ".join(f"{c['name']}@{c['version']}" for c in cfgs)
                    return ({"models": cfgs}, f"last good set {where} ({len(cfgs)} of {len(items)} instances: "
                            f"{keys})", problems)
                problems.append(f"no instance of the last good set {where} can run: config/models.yaml is used")
                why = "no instance of the last good set can run"
        except Exception as e:  # noqa: BLE001
            problems.append(f"last good set cannot be read: {type(e).__name__}: {e}: config/models.yaml is used")
            why = "the last good set cannot be read"
    models, path = _models_yaml(cfg)
    if mode == "models_yaml":
        why = "start_set models_yaml"
    return models, f"{path} ({why})", problems


class FallbackManager:
    """Used only when the ModelManager cannot be created: every enabled model is FAILED with the
    reason, so the status shows the problem (node state ERROR)."""

    def __init__(self, models_cfg: dict, error: str):
        self.error = error
        self.models = list((models_cfg or {}).get("models") or [])

    def start(self, should_stop=None):
        pass

    def stop(self):
        pass

    def stop_model(self, name):
        return {"ok": False, "error": self.error}

    start_model = stop_model

    def add_model(self, cfg):
        return False, self.error

    def remove_model(self, key):
        return False, self.error

    def status(self):
        out = []
        for m in self.models:
            en = bool(m.get("enabled"))
            ver = str(m.get("version") or "")
            out.append({"name": m.get("name"), "version": ver,
                        "instance": f"{m.get('name')}@{ver}" if ver else m.get("name"),
                        "engine": m.get("engine"), "engine_version": None,
                        "state": "FAILED" if en else "OFF", "error": self.error if en else None,
                        "reason": m.get("reason"), "enabled": en, "cameras": m.get("cameras") or [],
                        "fps": 0.0, "results_total": 0})
        return out


class Node:
    def __init__(self, cfg: dict, mode: str | None = None):
        from infer.admin import AdminServer
        from infer.draw import SnapshotTask
        from infer.ingest.ingest import Ingest
        from infer.publish import schema as sch
        from infer.publish.cache import ResultCache
        from infer.publish.internal import InternalPub
        from infer.publish.results import ResultPublisher
        from infer.publish.status import StatusPublisher
        from infer.status import NodeState, git_version

        self.cfg = cfg
        ports = cfg.get("ports") or {}
        bind = cfg.get("bind") or {}
        node_cfg = cfg.get("node") or {}
        self.stop_timeout_s = float(node_cfg.get("stop_timeout_s", 5.0))
        self.state = NodeState(version=git_version(ROOT),
                               no_signal_degraded_s=float(node_cfg.get("no_signal_degraded_s", 10.0)))
        log.info("driveragent-agx infer node %s pid %d", self.state.version, self.state.pid)
        proto = _path(cfg.get("proto", "proto/agx_infer.capnp"))
        sch.load(proto)  # logs the runtime schema hashes
        self.ctx = zmq.Context()
        self._parts: list = []   # (name, stop function), stopped in reverse order
        try:
            rc = cfg.get("results") or {}
            self.results = ResultPublisher(
                bind.get("results", "0.0.0.0"), int(ports.get("results", 5560)), proto,
                degraded_fn=self.state.degraded, sndhwm=int(rc.get("sndhwm", 100)),
                queue_max=int(rc.get("queue_max", 1000)),
                rate_window_s=float(rc.get("rate_window_s", 5.0)), ctx=self.ctx)
            self._parts.append(("results publisher", self.results.close))
            self.internal = InternalPub(bind.get("internal", "127.0.0.1"),
                                        int(ports.get("internal", 5562)), ctx=self.ctx)
            self._parts.append(("internal publisher", self.internal.close))
            self.cache = ResultCache()
            from infer.ingest.ingest import DEFAULT_PAIRED_FILE, PairedBoards
            self.paired = PairedBoards(_path(cfg.get("paired_boards_file") or DEFAULT_PAIRED_FILE))
            self.paired.poll()
            if self.paired.error:
                self.state.add_error(f"paired boards: {self.paired.error}")
            self.ingest = Ingest(_path(cfg.get("sources_config", "config/sources.yaml")), mode=mode,
                                 allowed_sources=self.paired.filter_addresses)
            log.info("ingest mode %s", self.ingest.mode)
            self.models_cfg, source, problems = select_models(cfg)
            log.info("model list from %s", source)
            for p in problems:
                log.error("start set: %s", p)
                self.state.add_error(f"start set: {p}")
            self.manager = self._make_manager()
            self.rkinfo = self._make_rkinfo(bind.get("rkinfo", "0.0.0.0"), int(ports.get("rkinfo", 5564)), proto)
            from controller.store import Store
            self.status = StatusPublisher(
                self.state, self.ingest, self.manager, self.results, self.internal,
                bind.get("status", "0.0.0.0"), int(ports.get("status", 5561)),
                float(cfg.get("status_period_s", 1.0)), proto, ctx=self.ctx,
                model_store=str(Store(cfg.get("model_store") or None).root),
                control_file=_path(cfg.get("control_config", "config/control.yaml")), rkinfo=self.rkinfo,
                paired=self.paired, on_tick=self.check_paired_boards)
            self._parts.append(("status publisher", self.status.stop))
            sc = cfg.get("snapshot") or {}
            self.snapshots = SnapshotTask(self.ingest.store, self.cache, self.internal,
                                          int(sc.get("width", 320)), float(sc.get("period_s", 1.0)),
                                          int(sc.get("jpeg_quality", 80)), cams=self.ingest.cams)
            ac = cfg.get("admin") or {}
            self.admin = AdminServer(self.ingest.store, self.manager, bind.get("admin", "127.0.0.1"),
                                     int(ports.get("admin", 5563)),
                                     int(ac.get("frame_jpeg_quality", 90)), ctx=self.ctx)
            self._parts.append(("admin server", self.admin.stop))
        except Exception:
            self._stop_parts()
            raise

    def check_paired_boards(self) -> bool:
        """Read data/paired_boards.json again when it changed; give a new address set to the FrameLink receivers and
        the RkCameraInfo ZAP allowlist (no restart). Called once per status tick. Returns True when the set changed."""
        err0 = self.paired.error
        changed = self.paired.poll()
        if self.paired.error and self.paired.error != err0:
            self.state.add_error(f"paired boards: {self.paired.error}")
        if not changed:
            return False
        addrs = self.paired.filter_addresses    # () = any source, (REFUSE_ALL,) = no source
        try:
            self.ingest.set_allowed_sources(addrs)
        except Exception as e:  # noqa: BLE001
            log.exception("FrameLink source filter update failed")
            self.state.add_error(f"FrameLink source filter update failed: {e}")
        if self.rkinfo is not None:
            try:
                self.rkinfo.set_allowed(addrs)
            except Exception as e:  # noqa: BLE001
                log.exception("RkCameraInfo allowlist update failed")
                self.state.add_error(f"RkCameraInfo allowlist update failed: {e}")
        from infer.ingest.ingest import describe_filter
        log.info("paired boards changed (seq %s, %s): FrameLink and RkCameraInfo from %s", self.paired.seq,
                 self.paired.state, describe_filter(addrs))
        return True

    def _make_rkinfo(self, host: str, port: int, proto: str | None):
        """RkCameraInfo receiver (infer/rkinfo.py), peers = the paired board addresses (data/paired_boards.json).
        None when it cannot be made: the node runs on (camera names from the config), with a node error."""
        try:
            from infer.rkinfo import RkInfoReceiver
            rk = RkInfoReceiver(host, port, self.paired.filter_addresses, proto)
        except Exception as e:  # noqa: BLE001
            msg = f"RkCameraInfo receiver on {host}:{port} not available: {type(e).__name__}: {e}"
            log.exception(msg)
            self.state.add_error(msg)
            return None
        self._parts.append(("rkinfo receiver", rk.stop))
        return rk

    def _make_manager(self):
        engines_dir = _path(self.cfg.get("engines_dir", "engines"))
        try:
            from infer.models.manager import ModelManager
            return ModelManager(self.models_cfg, self.ingest.store, self.on_result, engines_dir)
        except Exception as e:  # noqa: BLE001
            msg = f"ModelManager not available: {type(e).__name__}: {e}"
            log.exception(msg)
            self.state.add_error(msg)
            return FallbackManager(self.models_cfg, msg)

    def on_result(self, result: dict) -> None:
        """ModelManager callback (model worker threads)."""
        try:
            r = self.results.publish(result)
        except Exception as e:  # noqa: BLE001
            log.exception("publish failed")
            self.state.add_error(f"result publish failed: {e}")
            return
        if r is not None:
            self.cache.add(r)

    def start(self, should_stop=None) -> bool:
        """Start all parts. should_stop: optional function (True after SIGTERM / SIGINT); the start
        then ends early (no more engine loads, no workers, no snapshots). Returns False when it ended
        early."""
        stop_now = should_stop or (lambda: False)
        self.status.start()          # status shows STARTING from now
        self.admin.start()
        if self.rkinfo is not None:
            self.rkinfo.start()
        self.ingest.start()
        self._parts.insert(0, ("ingest", self.ingest.stop))
        self._parts.insert(0, ("model manager", self.manager.stop))
        if stop_now():
            log.info("stop requested during start: models not started")
            return False
        try:
            self.manager.start(should_stop=stop_now)
        except Exception as e:  # noqa: BLE001
            log.exception("ModelManager.start failed")
            self.state.add_error(f"ModelManager.start failed: {e}")
        if stop_now():
            log.info("stop requested during start: snapshots not started")
            return False
        self.snapshots.start()
        self._parts.insert(0, ("snapshots", self.snapshots.stop))
        self.state.started = True
        log.info("node started")
        return True

    def _stop_parts(self) -> None:
        # order: snapshots, models, ingest, then the sockets (admin, status, internal, results)
        parts = list(self._parts)
        self._parts.clear()
        first = [p for p in parts if p[0] in ("snapshots", "model manager", "ingest")]
        rest = [p for p in reversed(parts) if p not in first]
        for name, fn in first + rest:
            t0 = time.monotonic()
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("stop %s failed", name)
            log.info("stopped %s (%.2f s)", name, time.monotonic() - t0)
        try:
            self.ctx.destroy(linger=0)
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        self.state.stopping = True
        t0 = time.monotonic()
        th = threading.Thread(target=self._stop_parts, name="stop", daemon=True)
        th.start()
        th.join(self.stop_timeout_s)
        if th.is_alive():
            log.error("clean stop took more than %.1f s: exit now", self.stop_timeout_s)
            logging.shutdown()
            os._exit(3)
        log.info("node stopped in %.2f s", time.monotonic() - t0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="driveragent-agx inference node")
    ap.add_argument("--config", default=os.path.join(ROOT, "config", "infer.yaml"))
    ap.add_argument("--mode", choices=("sim", "rk", "file"), default=None,
                    help="ingest mode (default: config/sources.yaml or AGX_INGEST_MODE)")
    ap.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    a = ap.parse_args(argv)
    cfg = load_config(_path(a.config))
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, str(cfg.get("log_level", "INFO")).upper(),
                                                         logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stop_ev = threading.Event()
    n_sig = [0]

    def on_signal(signum, _frame):
        n_sig[0] += 1
        log.info("signal %s: stop", signal.Signals(signum).name)
        if n_sig[0] > 1:
            log.error("second signal: exit now")
            os._exit(4)
        stop_ev.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        node = Node(cfg, mode=a.mode)
    except Exception:  # noqa: BLE001
        log.exception("node start failed")
        return 2
    try:
        node.start(should_stop=stop_ev.is_set)
    except Exception:  # noqa: BLE001
        log.exception("node start failed")
        node.stop()
        return 2
    t_end = None if a.seconds is None else time.monotonic() + a.seconds
    while not stop_ev.is_set():
        if t_end is not None and time.monotonic() >= t_end:
            log.info("--seconds %.0f reached: stop", a.seconds)
            break
        stop_ev.wait(0.2)
    node.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
