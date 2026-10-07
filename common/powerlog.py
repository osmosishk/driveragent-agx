"""Power log core: the same file on the two machines (DA01 rk/common/powerlog.py, AGX02 common/powerlog.py).

It measures nothing itself. Power sources (plug-in parts, see docs/POWER_SOURCES.md) give Readings; the logger of each
machine calls PowerLog.add() once a second with the SENSOR readings and PowerLog.note_state() with the system state.
This module stores them in one SQLite file and answers the questions of the Power pages:

- samples: 1 s rows for the last hour (table s1), 10 s rows (mean/min/max + number of 1 s samples) for 30 days (s10),
  one row per day and series for one year (day: Wh, mean/min/max W, hours with data).
- energy: the sum of power over time only where samples exist. One 1 s sample stands for one second. A time without
  samples is a gap and adds nothing (it is not zero power): each energy value comes with its hours with data.
- events: each change of the system state (model set, sender, link, active unit, cameras, recording, power mode,
  control mode) with its time; before/after: the mean power of each series in the 60 s before and after an event.
- manual meter readings (label MANUAL, with the time and the system state at that moment) and the settings
  (correction factor per sensor series, battery capacity).

Labels (rule W2): SENSOR (a sensor on the machine reads it now), MANUAL (the owner typed a meter reading),
NO SENSOR. ESTIMATE only for the "time on a full battery". No power value is calculated from load or other signs.
The stored sample is always the raw sensor value; the correction factor is applied when a value is shown.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "power-log/1"
SENSOR, MANUAL, NO_SENSOR, ESTIMATE = "SENSOR", "MANUAL", "NO SENSOR", "ESTIMATE"
LABELS = (SENSOR, MANUAL, NO_SENSOR)
KEEP_S1_S = 3600 + 300            # 1 s rows: the last hour (+5 min so an event at the edge keeps its 60 s windows)
KEEP_S10_S = 30 * 86400           # 10 s rows: 30 days
KEEP_DAY_D = 366                  # day rows: one year
KEEP_EVENTS_S = 366 * 86400
MAX_MANUAL = 5000
FLUSH_S = 10                      # the 1 s samples are written in one transaction each 10 s
FRESH_S = 3.0                     # a SENSOR value older than this is not "now"
WINDOW_S = 60                     # before/after window
RANGES = {"1h": (3600, 1), "24h": (86400, 60), "7d": (7 * 86400, 600), "30d": (30 * 86400, 3600)}
EVENT_KINDS = ("models", "sender", "link", "agx_unit", "cameras", "recording", "power_mode", "control_mode")
SIZE_NOTE = ("1 s rows: at most 3900 per series; 10 s rows: at most 259200 per series (30 d); day rows: at most "
             "366 per series; events: one year; manual readings: at most 5000")


@dataclass
class Reading:
    """One value of a power source. watts is None when the source has no value now (label NO SENSOR)."""
    part: str                      # da01, agx02, router, screen, system, other (or "<part>:<rail>" for a rail)
    watts: float | None
    label: str                     # SENSOR / MANUAL / NO SENSOR
    t: float                       # wall time of the reading
    source: str                    # name of the source (jetson_rails, hwmon, manual, agx_status, ...)
    what: str = ""                 # the part of the system that it measures, in plain words
    rails: dict[str, float] = field(default_factory=dict)

    def doc(self) -> dict:
        return {"part": self.part, "watts": None if self.watts is None else round(self.watts, 3),
                "label": self.label, "t": round(self.t, 3), "source": self.source, "what": self.what,
                "rails": {k: round(v, 3) for k, v in self.rails.items()}}


class PowerSource:
    """Interface of a power source (plug-in). A new source (I2C sensor, meter with a serial or network interface,
    the PCB controller on the CAN bus) is one class with this interface; the pages need no change.

    name:  short name, [a-z][a-z0-9_]*
    read(now) -> list[Reading]: the values of now; never raises (an error gives a NO SENSOR reading with `what`
    set to the reason). Called once a second at most (rule W3): keep it cheap (sysfs reads, a cached socket).
    probe() -> dict: what the source found on this machine (paths, why it is or is not used), for the report and
    the page."""
    name = "source"

    def read(self, now: float) -> list[Reading]:
        raise NotImplementedError

    def probe(self) -> dict:
        return {"source": self.name}


def finite(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _day_start(day: str) -> float:
    return time.mktime(time.strptime(day, "%Y-%m-%d"))


class PowerLog:
    """One SQLite file. Thread-safe (one lock). Writer = the logger thread/task of the machine; the pages read through
    the same object, or through PowerLog(path, readonly=True) in another process."""

    def __init__(self, path: str, readonly: bool = False, clock=time.time):
        self.path, self.readonly, self.clock = path, readonly, clock
        self.lock = threading.Lock()
        self.pending: dict[tuple[int, int], float] = {}         # (series id, int t) -> watts, not written yet
        self.series: dict[str, int] = {}
        self.last_flush = 0.0
        self.error = ""
        self.state: dict[str, Any] = {}
        self._seen_state = False
        if readonly:
            self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5, check_same_thread=False)
        else:
            d = os.path.dirname(os.path.abspath(path))
            os.makedirs(d, mode=0o700, exist_ok=True)
            if not os.path.exists(path):
                os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
            self.db = sqlite3.connect(path, timeout=5, check_same_thread=False, isolation_level=None)
            self.db.executescript("""
                PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS series(id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, part TEXT,
                    source TEXT, what TEXT);
                CREATE TABLE IF NOT EXISTS s1(series INTEGER NOT NULL, t INTEGER NOT NULL, mw INTEGER NOT NULL,
                    PRIMARY KEY(series, t)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS s10(series INTEGER NOT NULL, t INTEGER NOT NULL, mean_mw INTEGER NOT NULL,
                    min_mw INTEGER NOT NULL, max_mw INTEGER NOT NULL, n INTEGER NOT NULL,
                    PRIMARY KEY(series, t)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS day(series INTEGER NOT NULL, day TEXT NOT NULL, wh REAL, mean_w REAL,
                    min_w REAL, max_w REAL, hours REAL, PRIMARY KEY(series, day)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, t REAL NOT NULL, kind TEXT NOT NULL,
                    value TEXT, prev TEXT, exact INTEGER NOT NULL DEFAULT 1, detail TEXT);
                CREATE INDEX IF NOT EXISTS ix_events_t ON events(t);
                CREATE TABLE IF NOT EXISTS manual(id INTEGER PRIMARY KEY, t REAL NOT NULL, part TEXT NOT NULL,
                    watts REAL NOT NULL, note TEXT, user TEXT, sensor_w REAL, state TEXT);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            """)
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema', ?)", (SCHEMA,))
            self.last_flush = self.clock()
        for sid, key in self.db.execute("SELECT id, key FROM series"):
            self.series[key] = sid

    # ---- writing ---------------------------------------------------------------------------------------------
    def _sid(self, key: str, part: str = "", source: str = "", what: str = "") -> int:
        sid = self.series.get(key)
        if sid is None:
            cur = self.db.execute("INSERT OR IGNORE INTO series(key, part, source, what) VALUES(?,?,?,?)",
                                  (key, part or key.split(":")[0], source, what))
            sid = cur.lastrowid if cur.rowcount else self.db.execute(
                "SELECT id FROM series WHERE key=?", (key,)).fetchone()[0]
            self.series[key] = sid
        return sid

    def add(self, readings: Iterable[Reading]) -> None:
        """Keep the SENSOR readings (raw watts) of this second; write each FLUSH_S seconds. Other labels are not
        samples (a manual reading goes through add_manual)."""
        with self.lock:
            for r in readings:
                w = finite(r.watts)
                if r.label != SENSOR or w is None:
                    continue
                sid = self._sid(r.part, r.part, r.source, r.what)
                self.pending[(sid, int(r.t))] = w
                for rail, rw in r.rails.items():
                    rw = finite(rw)
                    if rw is not None:
                        self.pending[(self._sid(f"{r.part}:{rail}", r.part, r.source, rail), int(r.t))] = rw
            if self.clock() - self.last_flush >= FLUSH_S:
                self._flush()

    def flush(self) -> None:
        with self.lock:
            self._flush()

    def _flush(self) -> None:
        self.last_flush = self.clock()
        if not self.pending:
            return
        rows = [(sid, t, int(round(w * 1000))) for (sid, t), w in self.pending.items()]
        self.pending = {}
        buckets = {(sid, t - t % 10) for sid, t, _ in rows}
        try:
            self.db.execute("BEGIN")
            self.db.executemany("INSERT OR REPLACE INTO s1(series, t, mw) VALUES(?,?,?)", rows)
            for sid, b in buckets:          # the 10 s row again from the 1 s rows of its bucket (complete or not)
                self.db.execute("""INSERT OR REPLACE INTO s10(series, t, mean_mw, min_mw, max_mw, n)
                    SELECT series, ?, CAST(ROUND(AVG(mw)) AS INTEGER), MIN(mw), MAX(mw), COUNT(*) FROM s1
                    WHERE series=? AND t>=? AND t<? GROUP BY series""", (b, sid, b, b + 10))
            for sid, day in {(sid, _day(b)) for sid, b in buckets}:
                self._day_row(sid, day)
            self.db.execute("COMMIT")
            self.error = ""
        except sqlite3.Error as e:
            self.db.execute("ROLLBACK") if self.db.in_transaction else None
            self.error = f"write: {e}"

    def _day_row(self, sid: int, day: str) -> None:
        t0 = _day_start(day)
        t1 = _day_start(_day(t0 + 93600))     # the next local midnight (also for a 23 h or 25 h day)
        r = self.db.execute("""SELECT SUM(mean_mw * n), SUM(n), MIN(min_mw), MAX(max_mw) FROM s10
            WHERE series=? AND t>=? AND t<?""", (sid, t0, t1)).fetchone()
        if r and r[1]:
            self.db.execute("INSERT OR REPLACE INTO day VALUES(?,?,?,?,?,?,?)",
                            (sid, day, r[0] / 1000 / 3600, r[0] / r[1] / 1000, r[2] / 1000, r[3] / 1000, r[1] / 3600))

    def prune(self) -> None:
        now = self.clock()
        with self.lock:
            try:
                self.db.execute("DELETE FROM s1 WHERE t < ?", (now - KEEP_S1_S,))
                self.db.execute("DELETE FROM s10 WHERE t < ?", (now - KEEP_S10_S,))
                self.db.execute("DELETE FROM day WHERE day < ?", (_day(now - KEEP_DAY_D * 86400),))
                self.db.execute("DELETE FROM events WHERE t < ?", (now - KEEP_EVENTS_S,))
                self.db.execute("DELETE FROM manual WHERE id NOT IN (SELECT id FROM manual ORDER BY id DESC LIMIT ?)",
                                (MAX_MANUAL,))
                self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as e:
                self.error = f"prune: {e}"

    # ---- events and state ------------------------------------------------------------------------------------
    def note_state(self, state: dict[str, Any], t: float | None = None) -> list[dict]:
        """Compare the system state with the last stored state; store one event per changed item. Items with the
        value None (not known now) make no event. The first state after a start: items that differ from the state
        stored before the stop give an event with exact=0 (the change was while the log did not run)."""
        t = self.clock() if t is None else t
        out = []
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key='last_state'").fetchone()
            last = json.loads(row[0]) if row else {}
            first = not self._seen_state
            self._seen_state = True
            changed = False
            for k, v in state.items():
                if v is None:
                    continue
                if k in last and last[k] == v:
                    continue
                changed = True
                if k in last:
                    ev = {"t": t, "kind": k, "value": json.dumps(v), "prev": json.dumps(last[k]),
                          "exact": 0 if first else 1}
                    self.db.execute("INSERT INTO events(t, kind, value, prev, exact) VALUES(?,?,?,?,?)",
                                    (ev["t"], k, ev["value"], ev["prev"], ev["exact"]))
                    out.append(ev)
                last[k] = v
            if changed:
                self.db.execute("INSERT OR REPLACE INTO settings VALUES('last_state', ?)", (json.dumps(last),))
            self.state = dict(last)
        return out

    def add_event(self, kind: str, value: Any, prev: Any = None, t: float | None = None, detail: str = "") -> None:
        with self.lock:
            self.db.execute("INSERT INTO events(t, kind, value, prev, exact, detail) VALUES(?,?,?,?,1,?)",
                            (self.clock() if t is None else t, kind, json.dumps(value), json.dumps(prev), detail))

    def events(self, since: float = 0, until: float | None = None, limit: int = 20) -> list[dict]:
        until = self.clock() + 1 if until is None else until
        with self.lock:
            rows = self.db.execute("""SELECT id, t, kind, value, prev, exact, detail FROM events
                WHERE t>=? AND t<? ORDER BY t DESC, id DESC LIMIT ?""", (since, until, limit)).fetchall()
        return [{"id": r[0], "t": r[1], "kind": r[2], "value": _loads(r[3]), "prev": _loads(r[4]),
                 "exact": bool(r[5]), "detail": r[6] or ""} for r in rows]

    # ---- manual readings and settings ------------------------------------------------------------------------
    def add_manual(self, part: str, watts: float, note: str, user: str, sensor_w: float | None,
                   state: dict | None, t: float | None = None) -> dict:
        t = self.clock() if t is None else t
        with self.lock:
            cur = self.db.execute("INSERT INTO manual(t, part, watts, note, user, sensor_w, state) "
                                  "VALUES(?,?,?,?,?,?,?)",
                                  (t, part, float(watts), note, user, sensor_w, json.dumps(state or {})))
        return {"id": cur.lastrowid, "t": t, "part": part, "watts": float(watts), "note": note, "user": user,
                "sensor_w": sensor_w}

    def manual(self, limit: int = 50, part: str | None = None) -> list[dict]:
        q, a = "SELECT id, t, part, watts, note, user, sensor_w, state FROM manual", []
        if part:
            q, a = q + " WHERE part=?", [part]
        with self.lock:
            rows = self.db.execute(q + " ORDER BY t DESC, id DESC LIMIT ?", (*a, limit)).fetchall()
        out = []
        for r in rows:
            sw = r[6]
            out.append({"id": r[0], "t": r[1], "part": r[2], "watts": r[3], "note": r[4] or "", "user": r[5] or "",
                        "sensor_w": sw, "ratio": round(r[3] / sw, 3) if sw else None, "state": _loads(r[7]) or {}})
        return out

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.lock:
            r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return _loads(r[0]) if r else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def factors(self) -> dict[str, float]:
        return {k: float(v) for k, v in (self.get_setting("factors", {}) or {}).items()}

    # ---- reading ---------------------------------------------------------------------------------------------
    def series_keys(self) -> list[str]:
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT key FROM series ORDER BY key")]

    def _ids(self, keys: Iterable[str] | None) -> dict[int, str]:
        with self.lock:
            rows = self.db.execute("SELECT id, key FROM series").fetchall()
        want = None if keys is None else set(keys)
        return {i: k for i, k in rows if want is None or k in want}

    def samples(self, since: float, until: float, bucket_s: int, keys: Iterable[str] | None = None) -> dict:
        """Mean power per bucket (weighted by the number of 1 s samples) and the seconds with data per bucket.
        A bucket without samples is None (a gap in the chart)."""
        ids = self._ids(keys)
        out: dict[str, dict[int, list[float]]] = {k: {} for k in ids.values()}
        flushed_to = None
        with self.lock:
            for sid, key in ids.items():
                # 1 s rows where they exist (the last hour), 10 s rows before that
                t1min = self.db.execute("SELECT MIN(t) FROM s1 WHERE series=?", (sid,)).fetchone()[0]
                cut = max(since, t1min) if t1min is not None else until
                if bucket_s >= 10:
                    q10 = self.db.execute("""SELECT (t / ?) * ?, SUM(mean_mw * n), SUM(n) FROM s10
                        WHERE series=? AND t>=? AND t<? GROUP BY 1""", (bucket_s, bucket_s, sid, since, until))
                    cut = until
                else:
                    q10 = self.db.execute("""SELECT t, mean_mw * n, n FROM s10 WHERE series=? AND t>=? AND t<?""",
                                          (sid, since, min(cut, until)))
                for b, s, n in q10:
                    out[key][int(b)] = [s / 1000, n]
                if cut < until:
                    for t, mw in self.db.execute("SELECT t, mw FROM s1 WHERE series=? AND t>=? AND t<?",
                                                 (sid, cut, until)):
                        b = int(t - t % bucket_s)
                        e = out[key].setdefault(b, [0.0, 0])
                        e[0] += mw / 1000
                        e[1] += 1
                for (s_id, t), w in self.pending.items():          # not written yet
                    if s_id == sid and since <= t < until:
                        b = int(t - t % bucket_s)
                        e = out[key].setdefault(b, [0.0, 0])
                        e[0] += w
                        e[1] += 1
                flushed_to = self.last_flush
        t0 = int(since - since % bucket_s)
        ts = list(range(t0, int(until), bucket_s))
        series = {k: [round(v[b][0] / v[b][1], 3) if b in v and v[b][1] else None for b in ts] for k, v in out.items()}
        cover = {k: [v[b][1] if b in v else 0 for b in ts] for k, v in out.items()}
        return {"t": ts, "bucket_s": bucket_s, "series": series, "seconds": cover, "flushed_to": flushed_to}

    def energy(self, since: float, until: float, keys: Iterable[str] | None = None) -> dict[str, dict]:
        """Wh per series in [since, until), only where samples exist, with the hours with data."""
        ids = self._ids(keys)
        out = {}
        with self.lock:
            for sid, key in ids.items():
                t1min = self.db.execute("SELECT MIN(t) FROM s1 WHERE series=?", (sid,)).fetchone()[0]
                # 10 s rows up to the first 10 s bucket that the 1 s rows cover fully, 1 s rows after it
                cut = until if t1min is None else max(since, min(until, math.ceil(t1min / 10) * 10))
                ws, n = 0.0, 0
                r = self.db.execute("SELECT SUM(mean_mw * n), SUM(n) FROM s10 WHERE series=? AND t>=? AND t<?",
                                    (sid, math.ceil(since / 10) * 10, cut)).fetchone()
                if r and r[1]:
                    ws, n = r[0] / 1000, r[1]
                r = self.db.execute("SELECT SUM(mw), COUNT(*) FROM s1 WHERE series=? AND t>=? AND t<?",
                                    (sid, max(since, cut), until)).fetchone()
                if r and r[1]:
                    ws, n = ws + r[0] / 1000, n + r[1]
                for (s_id, t), w in self.pending.items():     # not written yet: newer than each stored row
                    if s_id == sid and since <= t < until:
                        ws, n = ws + w, n + 1
                out[key] = {"wh": round(ws / 3600, 3), "hours": round(n / 3600, 3),
                            "mean_w": round(ws / n, 3) if n else None, "span_h": round((until - since) / 3600, 3)}
        return out

    def days(self, since_day: str, keys: Iterable[str] | None = None) -> list[dict]:
        ids = self._ids(keys)
        with self.lock:
            rows = self.db.execute("SELECT series, day, wh, mean_w, min_w, max_w, hours FROM day WHERE day>=? "
                                   "ORDER BY day", (since_day,)).fetchall()
        return [{"series": ids[r[0]], "day": r[1], "wh": round(r[2], 3), "mean_w": round(r[3], 3),
                 "min_w": round(r[4], 3), "max_w": round(r[5], 3), "hours": round(r[6], 3)}
                for r in rows if r[0] in ids]

    def window_mean(self, key: str, t0: float, t1: float) -> tuple[float | None, int]:
        """Mean power and number of 1 s samples in [t0, t1). 1 s rows if they cover the window, else the 10 s rows
        that lie fully inside it."""
        sid = self.series.get(key)
        if sid is None:
            ids = {v: k for k, v in self._ids([key]).items()}
            sid = ids.get(key)
            if sid is None:
                return None, 0
        a, b = math.ceil(t0), math.ceil(t1)
        with self.lock:
            s, n = 0.0, 0
            r = self.db.execute("SELECT SUM(mw), COUNT(*) FROM s1 WHERE series=? AND t>=? AND t<?",
                                (sid, a, b)).fetchone()
            if r and r[1]:
                s, n = r[0] / 1000, r[1]
            for (s_id, t), w in self.pending.items():
                if s_id == sid and a <= t < b:
                    s, n = s + w, n + 1
            if n == 0:
                r = self.db.execute("""SELECT SUM(mean_mw * n), SUM(n) FROM s10 WHERE series=? AND t>=? AND t+10<=?""",
                                    (sid, a, b)).fetchone()
                if r and r[1]:
                    s, n = r[0] / 1000, r[1]
        return (round(s / n, 3) if n else None), n

    def before_after(self, keys: list[str], limit: int = 20, window_s: int = WINDOW_S,
                     factors: dict[str, float] | None = None) -> list[dict]:
        """The last `limit` events; for each SENSOR series the mean power in the window before and after, and the
        difference. A window with less than half of its seconds is not used (value None + reason)."""
        now = self.clock()
        factors = factors or {}
        evs = self.events(limit=limit)
        lo = min((e["t"] for e in evs), default=now) - window_s
        all_t = [e["t"] for e in self.events(since=lo, limit=100000)]
        out = []
        for e in evs:
            t = e["t"]
            row = {**e, "parts": {}, "notes": []}
            if not e["exact"]:
                row["notes"].append("the change was while the power log did not run: the time is not exact")
            near = [x for x in all_t if x != t and t - window_s <= x <= t + window_s]
            if near:
                row["notes"].append(f"{len(near)} other event(s) in the {window_s} s windows")
            if t + window_s > now:
                row["notes"].append(f"the {window_s} s after the event are not complete yet")
            for k in keys:
                f = factors.get(k, 1.0)
                b, nb = self.window_mean(k, t - window_s, t)
                a, na = self.window_mean(k, t, t + window_s)
                ok_b, ok_a = nb >= window_s / 2, na >= window_s / 2
                p = {"before_w": b if ok_b else None, "after_w": a if ok_a else None, "n_before": nb, "n_after": na,
                     "factor": f}
                p["diff_w"] = round(a - b, 3) if ok_a and ok_b else None
                if p["diff_w"] is not None and f != 1.0:
                    p["diff_corrected_w"] = round(p["diff_w"] * f, 3)
                if not (ok_a and ok_b):
                    p["reason"] = "not enough samples " + ("before" if not ok_b else "after") + " the event"
                row["parts"][k] = p
            out.append(row)
        return out

    def csv_samples(self, since: float, until: float, keys: Iterable[str] | None = None) -> str:
        span = until - since
        bucket = 1 if span <= 2 * 3600 else 10
        d = self.samples(since, until, bucket, keys)
        f = io.StringIO()
        w = csv.writer(f)
        w.writerow(["time_utc", "unix_s", "series", "watts_sensor", "seconds_with_data", "label"])
        for i, t in enumerate(d["t"]):
            for k, vals in d["series"].items():
                if vals[i] is not None:
                    w.writerow([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)), t, k, vals[i],
                                d["seconds"][k][i], SENSOR])
        return f.getvalue()

    def csv_events(self, since: float, until: float) -> str:
        f = io.StringIO()
        w = csv.writer(f)
        w.writerow(["time_utc", "unix_s", "kind", "value", "previous", "time_exact", "detail"])
        for e in reversed(self.events(since, until, limit=1000000)):
            w.writerow([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e["t"])), round(e["t"], 3), e["kind"],
                        json.dumps(e["value"]), json.dumps(e["prev"]), int(e["exact"]), e["detail"]])
        return f.getvalue()

    def size(self) -> dict:
        b = 0
        for suf in ("", "-wal", "-shm"):
            try:
                b += os.path.getsize(self.path + suf)
            except OSError:
                pass
        with self.lock:
            n = {t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 (fixed names)
                 for t in ("s1", "s10", "day", "events", "manual")}
        return {"bytes": b, "rows": n, "limits": SIZE_NOTE, "error": self.error}

    def close(self) -> None:
        with self.lock:
            if not self.readonly:
                self._flush()
            self.db.close()


def _loads(s: Any) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return s


def system_total(now_parts: dict[str, Reading | None], factors: dict[str, float], now: float,
                 parts: Iterable[str]) -> dict:
    """The total of the parts with a SENSOR value that is valid now (fresh), raw and corrected, and the parts that
    are missing. A manual reading is never in the total."""
    raw = cor = 0.0
    used, missing = [], []
    for p in parts:
        r = now_parts.get(p)
        w = finite(r.watts) if r else None
        if r is None or r.label != SENSOR or w is None or now - r.t > FRESH_S:
            missing.append(p)
            continue
        used.append(p)
        raw += w
        cor += w * factors.get(p, 1.0)
    return {"sensor_w": round(raw, 3) if used else None, "corrected_w": round(cor, 3) if used else None,
            "parts": used, "missing": missing, "label": SENSOR if used else NO_SENSOR}


def battery_estimate(capacity_wh: float | None, total_w: float | None, missing: list[str]) -> dict | None:
    """Time on a full battery at the present power. ESTIMATE: it uses only the parts in the total."""
    c, w = finite(capacity_wh), finite(total_w)
    if not c or not w or w <= 0:
        return None
    return {"hours": round(c / w, 2), "label": ESTIMATE, "capacity_wh": c, "power_w": w,
            "note": "capacity / present total power" + (f"; the total has no value for: {', '.join(missing)}"
                                                         if missing else "")}
