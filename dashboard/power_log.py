"""Power log of this AGX (common/powerlog.py PowerLog, file data/power.sqlite; the pages: dashboard/power_api.py).

The logger does not read the INA3221 sensors itself: it is a listener of the HealthCollector and uses the power part
of the 1 s health snapshot (s["power"], the rails that the health thread reads already). common/power_sources.py
JetsonRails is used only for probe() (the System page shows what it found) and as the fallback when a snapshot has
no power part.

The health listener only puts (t, power, power mode) in a small queue (no SQLite work on the health thread). The
thread "power-log" takes each item, makes the Reading and the event state, and calls PowerLog.add() (one write each
10 s) and PowerLog.note_state(). It prunes the log once an hour.

Event state (the keys of the contract): models (active set of the model controller, active.json, read again when its
mtime changes), link (link state of the paired board with the newest last_seen), cameras (number of cameras that give
frames, from the agx-infer status), power_mode (nvpmodel mode of the health snapshot; the health thread reads it each
nvpmodel_interval_s), control_mode (config/control.yaml, read again when its mtime changes). sender, agx_unit and
recording are not known on the AGX (None: no event).

The power part of this unit is its node name (config node_name, default the short host name; common/machine.py).

A changed value makes an event only when it stays the same for HOLD_S seconds (a short flicker of the link or of a
camera makes no event). The event time is the first second of the new value. The first state after the start goes
to the log START_S seconds after the first sample (then the agx-infer status is received: no false link event).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path

from common.machine import node_name
from common.powerlog import FRESH_S, NO_SENSOR, SENSOR, PowerLog, Reading, finite
from dashboard.config import resolve_path

log = logging.getLogger("dashboard.power_log")

SOURCE = "jetson_rails"
HOLD_S = 3.0              # a new state value must stay this long to make an event
START_S = 5.0             # the first state waits this long after the first sample: just after the start the
                          # agx-infer status is not received yet (link "NO DATA", cameras not known: false events)
PRUNE_S = 3600.0
QUEUE_MAX = 30
NO_BOARD = "no paired board"
STATE_KEYS = ("models", "sender", "link", "agx_unit", "cameras", "recording", "power_mode", "control_mode")


def rails_what(names) -> str:
    """The same words as common/power_sources.py JetsonRails.what()."""
    names = ", ".join(names)
    return (f"sum of the module rails {names} (INA3221); the supply input is not measured" if names
            else "no INA3221 rail found")


def reading_from_power(p: dict, t: float, part: str | None = None) -> Reading | None:
    """The Reading of the health snapshot power part (dashboard/collectors/health.py _power). None: the part has no
    rails (then the caller uses the fallback). A rail that did not read gives NO SENSOR (the sum would be too low).
    part: the power part (None = the node name of common/machine.py)."""
    part = part or node_name(None)
    rails_in = (p or {}).get("rails") if isinstance(p, dict) else None
    if not isinstance(rails_in, dict) or not rails_in:
        return None
    rails: dict[str, float] = {}
    bad = []
    for name, r in rails_in.items():
        w = finite((r or {}).get("w")) if isinstance(r, dict) else None
        if w is None:
            bad.append(name)
        else:
            rails[name] = w
    if bad:
        return Reading(part, None, NO_SENSOR, t, SOURCE,
                       f"{len(bad)} rail(s) did not read ({', '.join(sorted(bad))})", rails)
    if "VDD_IN" in rails:     # a module with a board input rail: that rail is the total (the others are inside it)
        return Reading(part, rails["VDD_IN"], SENSOR, t, SOURCE, "VDD_IN rail (board input, INA3221)", rails)
    return Reading(part, sum(rails.values()), SENSOR, t, SOURCE, rails_what(sorted(rails)), rails)


class _MtimeJSON:
    """A small file read again only when its mtime, size or inode change."""

    def __init__(self, parse):
        self.parse = parse
        self.sig = None
        self.path = None
        self.value = None

    def get(self, path):
        try:
            st = os.stat(path)
            sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            sig = None
        if sig != self.sig or path != self.path:
            self.sig, self.path = sig, path
            try:
                self.value = self.parse(path, sig is not None)
            except Exception:  # a bad file: not known now
                log.exception("power log: cannot read %s", path)
                self.value = None
        return self.value


def _parse_models(path, exists):
    if not exists:
        return None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    items = d.get("set") if isinstance(d, dict) else None
    if not isinstance(items, list):
        return None
    return sorted(f"{i.get('name')}@{i.get('version')}" for i in items if isinstance(i, dict) and i.get("name"))


def _parse_control(path, _exists):
    from controller.control import read_control_mode
    return read_control_mode(path)[0]


class PowerLogger:
    """Hub-style collector: start() / stop() / latest(). The log file opens in start() (a test app with
    start_collectors=False opens no file; a test can call open() with its own path)."""

    def __init__(self, cfg: dict, hub):
        pc = cfg.get("power_log") or {}
        self.cfg = cfg
        self.hub = hub
        self.part = node_name(cfg)   # the power part of this unit (config node_name)
        self.enabled = bool(pc.get("enabled", True))
        self.db_path = resolve_path(pc.get("db") or "data/power.sqlite")
        self.db_text = str(pc.get("db") or "data/power.sqlite")
        self.log: PowerLog | None = None
        self.error: str | None = None
        self.now: Reading | None = None
        self.power_mode: str | None = None
        self.state_now: dict = {k: None for k in STATE_KEYS}
        self.dropped = 0
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rails = None           # common/power_sources.py JetsonRails, made on first use
        self._models = _MtimeJSON(_parse_models)
        self._control = _MtimeJSON(_parse_control)
        self._stable: dict = {}      # the state given to note_state
        self._cand: dict = {}        # key -> (new value, first time)
        self._first = True
        self._t_first = None         # time of the first sample after the start
        self._prune_t = 0.0
        self._listening = False

    # ---- life cycle
    def open(self, path=None) -> PowerLog | None:
        if path is not None:
            self.db_path, self.db_text = Path(path), str(path)
        try:
            self.log = PowerLog(str(self.db_path))
            self.error = None
        except Exception as e:  # the dashboard must start also without the power log
            log.exception("power log not opened")
            self.log, self.error = None, f"power log not opened: {e}"
        return self.log

    def start(self):
        if not self.enabled:
            return
        if self.log is None:
            self.open()
        if self.log is None:
            return
        if not self._listening:
            self.hub.health.add_listener(self.on_sample)
            self._listening = True
        self._thread = threading.Thread(target=self._run, name="power-log", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self.log is not None:
            try:
                self.log.close()        # writes the samples of the last seconds
            except Exception:
                log.exception("power log close failed")

    def sources(self) -> list[dict]:
        rs = self._jetson()
        try:
            d = rs.probe()
        except Exception as e:
            d = {"source": SOURCE, "used": False, "note": f"probe failed: {e}"}
        d["via"] = "the 1 s health snapshot of this dashboard (the rails are read once, by the health thread)"
        return [d]

    def _jetson(self):
        if self._rails is None:
            from common.power_sources import JetsonRails
            self._rails = JetsonRails(self.part)
        return self._rails

    # ---- the health thread: only a queue put
    def on_sample(self, s: dict):
        nvp = s.get("nvpmodel") if isinstance(s.get("nvpmodel"), dict) else {}
        try:
            self._q.put_nowait((s.get("t") or time.time(), s.get("power"), nvp.get("mode")))
        except queue.Full:
            self.dropped += 1
            if self.dropped in (1, 100) or self.dropped % 3600 == 0:
                log.warning("power log: queue full, %d samples dropped", self.dropped)

    # ---- the power-log thread
    def _run(self):
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self.process(*item)
            except Exception:  # never end the thread
                log.exception("power log sample failed")
            now = time.time()
            if now - self._prune_t >= PRUNE_S:
                self._prune_t = now
                try:
                    self.log.prune()
                except Exception:
                    log.exception("power log prune failed")

    def reading(self, power, t: float) -> Reading:
        r = reading_from_power(power, t, self.part) if isinstance(power, dict) else None
        if r is None:   # the snapshot has no power part: the fallback reads the sysfs files
            try:
                r = self._jetson().read(t)[0]
            except Exception as e:
                r = Reading(self.part, None, NO_SENSOR, t, SOURCE, f"read failed: {e}")
        return r

    def process(self, t: float, power, mode) -> None:
        r = self.reading(power, t)
        st = self.build_state(mode)
        with self._lock:
            self.now, self.power_mode, self.state_now = r, mode, st
        if self.log is None:
            return
        self.log.add([r])
        if self._t_first is None:
            self._t_first = t
        if self._first and t - self._t_first < START_S:
            return
        self.note(st, t)

    def note(self, st: dict, t: float) -> list[dict]:
        """The first state after the start goes to note_state at once (a change while the log did not run gets
        exact=0). After that, a changed item goes to note_state when it has stayed HOLD_S seconds."""
        out = []
        if self._first:
            self._first = False
            out += self.log.note_state(st, t)
            self._stable = {k: v for k, v in st.items() if v is not None}
            return out
        for k, v in st.items():
            if v is None or self._stable.get(k) == v:
                self._cand.pop(k, None)
                continue
            c = self._cand.get(k)
            if c is None or c[0] != v:
                self._cand[k] = (v, t)
                c = self._cand[k]
            if t - c[1] >= HOLD_S:
                out += self.log.note_state({k: v}, c[1])
                self._stable[k] = v
                self._cand.pop(k, None)
        return out

    # ---- event state
    def _state_dir(self) -> Path:
        c = getattr(self.hub, "controller", None)
        if c is not None:
            return c.store.state
        return Path(os.path.expanduser(self.cfg.get("model_store") or "~/agx-models")) / "_state"

    def _control_file(self):
        c = getattr(self.hub, "controller", None)
        if c is not None:
            return c.control_file
        return str(resolve_path(self.cfg.get("control_config") or "config/control.yaml"))

    def build_state(self, power_mode) -> dict:
        st = {k: None for k in STATE_KEYS}
        st["power_mode"] = power_mode if isinstance(power_mode, str) and power_mode else None
        try:
            st["models"] = self._models.get(str(self._state_dir() / "active.json"))
        except Exception:
            log.exception("power log: models state")
        try:
            st["control_mode"] = self._control.get(self._control_file())
        except Exception:
            log.exception("power log: control mode state")
        try:
            cur, _state, reason, _age = self.hub.infer.current()
        except Exception:
            cur, reason = None, "agx-infer status not readable"
        if cur is not None:
            cams = cur.get("cameras")
            if isinstance(cams, list):
                st["cameras"] = sum(1 for c in cams if isinstance(c, dict) and c.get("state")
                                    and c.get("state") != "NO SIGNAL")
        try:
            st["link"] = self.link_state(cur, reason)
        except Exception:
            log.exception("power log: link state")
        return st

    def link_state(self, cur, reason):
        pairing = getattr(self.hub, "pairing", None)
        if pairing is None:
            return None
        boards = pairing.boards()
        if not boards:
            return NO_BOARD
        b = max(boards, key=lambda x: x.get("last_seen_t") or 0)
        from dashboard.pairing_api import link_view
        rows, _other = link_view([b], cur, reason)
        return rows[0].get("link_state")

    # ---- documents
    def now_doc(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            r, mode = self.now, self.power_mode
        if r is None:
            d = Reading(self.part, None, NO_SENSOR, now, SOURCE,
                        "no sample yet" if self.enabled else "the power log is off (config power_log.enabled)").doc()
            d["age_s"] = None
        else:
            d = r.doc()
            d["age_s"] = round(max(0.0, now - r.t), 1)
            if now - r.t > FRESH_S:     # rule W2: SENSOR only for a value of now; no old rail value as now
                d.update(watts=None, label=NO_SENSOR, rails={},
                         what=f"no new sample for {d['age_s']} s ({r.what})")
        d["power_mode"] = mode
        return d

    def state_doc(self) -> dict:
        with self._lock:
            return dict(self.state_now)

    def log_doc(self) -> dict:
        d = {"path": self.db_text, "bytes": None, "rows": None, "limits": None,
             "error": self.error if self.enabled else "the power log is off (config power_log.enabled)"}
        if self.log is not None:
            try:
                d.update(self.log.size())
                d["error"] = d.get("error") or self.error or None
            except Exception as e:
                d["error"] = f"size: {e}"
        elif self.enabled and not d["error"]:
            d["error"] = "the power log is not open (the collectors did not start)"
        if self.dropped:
            d["error"] = ((d["error"] + "; ") if d["error"] else "") + f"{self.dropped} samples dropped (queue full)"
        return d
