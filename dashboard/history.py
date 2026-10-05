"""Metric history: 1 h at 1 s in memory, 24 h at 10 s in SQLite (WAL, one writer thread).

SQLite table samples(t INTEGER, metric TEXT, value REAL); t is the 10 s bucket start (unix s),
value is the average of the 1 s samples in that bucket.
Retention every cleanup_interval_s: delete rows older than db_keep_s. Then compare the LIVE data
size ((page_count - freelist_count) * page_size, free pages not counted) with max_mb: if it is
larger, compute one cut time from the bytes per row, delete the older rows in one DELETE and
VACUUM once. If only the file is larger (free pages), VACUUM once and delete no data.
"""
from __future__ import annotations

import collections
import logging
import os
import queue
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("dashboard.history")

BASE_METRICS = ["gpu_load_pct", "ram_used_pct", "temp_max_c", "power_total_w", "cpu_load_avg_pct"]


class History:
    def __init__(self, db_path: Path, max_mb: float = 50, memory_s: int = 3600, step_s: int = 10,
                 keep_s: int = 86400, cleanup_interval_s: int = 600):
        self.db_path = Path(db_path)
        self.max_bytes = int(float(max_mb) * 1024 * 1024)
        self.step = int(step_s)
        self.keep_s = int(keep_s)
        self.cleanup_interval = float(cleanup_interval_s)
        self._mem: collections.deque = collections.deque(maxlen=int(memory_s))
        self._lock = threading.Lock()
        self._bucket: int | None = None
        self._acc: dict[str, list[float]] = {}
        self._q: queue.Queue = queue.Queue(maxsize=1000)
        self._stop = threading.Event()
        self._writer: threading.Thread | None = None
        self.db_error: str | None = None

    # ---- lifecycle
    def start(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = threading.Thread(target=self._writer_loop, name="history-db", daemon=True)
        self._writer.start()

    def stop(self):
        self._stop.set()
        if self._writer:
            self._writer.join(timeout=5)

    # ---- input (called once per second by the health thread)
    def add(self, t: float, metrics: dict[str, float | None]):
        ti = int(t)
        with self._lock:
            self._mem.append((ti, dict(metrics)))
        b = ti - ti % self.step
        if self._bucket is None:
            self._bucket = b
        if b != self._bucket:
            rows = []
            for k, vals in self._acc.items():
                if vals:
                    rows.append((self._bucket, k, sum(vals) / len(vals)))
            if rows:
                try:
                    self._q.put_nowait(rows)
                except queue.Full:
                    log.warning("history queue full, rows dropped")
            self._acc = {}
            self._bucket = b
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                self._acc.setdefault(k, []).append(float(v))

    # ---- db writer (only thread that writes)
    def _connect(self, readonly=False) -> sqlite3.Connection:
        if readonly:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5)
        else:
            con = sqlite3.connect(str(self.db_path), timeout=10)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("CREATE TABLE IF NOT EXISTS samples (t INTEGER NOT NULL, metric TEXT NOT NULL, value REAL)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_samples_t ON samples(t)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_samples_mt ON samples(metric, t)")
            con.commit()
        return con

    def _db_size(self) -> int:
        n = 0
        for suf in ("", "-wal", "-shm"):
            try:
                n += os.path.getsize(str(self.db_path) + suf)
            except OSError:
                pass
        return n

    @staticmethod
    def _live_size(con: sqlite3.Connection) -> int:
        """Bytes in use by data and indexes (free pages not counted)."""
        pc = con.execute("PRAGMA page_count").fetchone()[0]
        fl = con.execute("PRAGMA freelist_count").fetchone()[0]
        ps = con.execute("PRAGMA page_size").fetchone()[0]
        return (pc - fl) * ps

    def _vacuum(self, con: sqlite3.Connection):
        con.execute("VACUUM")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _cleanup(self, con: sqlite3.Connection):
        con.execute("DELETE FROM samples WHERE t < ?", (int(time.time()) - self.keep_s,))
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        live = self._live_size(con)
        if live > self.max_bytes:
            n = con.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            if n:
                # keep the newest rows that fit in 90 % of the limit (one DELETE, one VACUUM)
                keep = int(n * (0.9 * self.max_bytes) / live)
                cut = (con.execute("SELECT t FROM samples ORDER BY t DESC LIMIT 1 OFFSET ?",
                                   (keep,)).fetchone() if keep > 0 else None)
                if cut is not None:
                    con.execute("DELETE FROM samples WHERE t <= ?", (cut[0],))
                else:
                    con.execute("DELETE FROM samples")
                con.commit()
            self._vacuum(con)
            log.info("history db over limit (live %d bytes): oldest rows deleted, file now %d bytes",
                     live, self._db_size())
        elif self._db_size() > self.max_bytes:
            # only free pages make the file large: give them back, keep all data
            self._vacuum(con)
            log.info("history db file over limit: VACUUM, file now %d bytes", self._db_size())
        if self._db_size() > self.max_bytes:
            log.warning("history db file still %d bytes after cleanup (limit %d)",
                        self._db_size(), self.max_bytes)

    def _writer_loop(self):
        try:
            con = self._connect()
        except sqlite3.Error as e:
            self.db_error = f"history db open failed: {e}"
            log.error(self.db_error)
            return
        last_clean = 0.0
        try:
            while not (self._stop.is_set() and self._q.empty()):
                try:
                    rows = self._q.get(timeout=1.0)
                    con.executemany("INSERT INTO samples (t, metric, value) VALUES (?, ?, ?)", rows)
                    con.commit()
                    self.db_error = None
                except queue.Empty:
                    pass
                except sqlite3.Error as e:
                    self.db_error = f"history db write failed: {e}"
                    log.error(self.db_error)
                if time.monotonic() - last_clean >= self.cleanup_interval:
                    last_clean = time.monotonic()
                    try:
                        self._cleanup(con)
                    except sqlite3.Error as e:
                        self.db_error = f"history cleanup failed: {e}"
                        log.error(self.db_error)
        finally:
            con.close()

    # ---- read
    def names(self) -> list[str]:
        with self._lock:
            keys = set(BASE_METRICS)
            for _, m in self._mem:
                keys.update(m.keys())
        return sorted(keys)

    def _db_rows(self, since: int, until: int | None, metrics: list[str] | None):
        if not self.db_path.exists():
            return []
        try:
            con = self._connect(readonly=True)
        except sqlite3.Error:
            return []
        try:
            q = "SELECT t, metric, value FROM samples WHERE t >= ?"
            args: list = [since]
            if until is not None:
                q += " AND t < ?"
                args.append(until)
            if metrics:
                q += " AND metric IN (%s)" % ",".join("?" * len(metrics))
                args.extend(metrics)
            q += " ORDER BY t"
            return con.execute(q, args).fetchall()
        except sqlite3.Error:
            return []
        finally:
            con.close()

    def query(self, range_s: int, metrics: list[str] | None) -> dict:
        now = int(time.time())
        since = now - range_s
        points: dict[int, dict[str, float | None]] = {}
        source = []
        if range_s <= 3600:
            with self._lock:
                mem = [(t, m) for (t, m) in self._mem if t >= since]
            mem_start = mem[0][0] if mem else now
            # memory is empty after a restart: fill the gap from the db (10 s resolution)
            if mem_start - since > 2 * self.step:
                for t, k, v in self._db_rows(since, mem_start, metrics):
                    points.setdefault(t, {})[k] = round(v, 2) if v is not None else None
                if points:
                    source.append(f"sqlite {self.step} s")
            for t, m in mem:
                points[t] = {k: v for k, v in m.items() if not metrics or k in metrics}
            source.append("memory 1 s")
        else:
            for t, k, v in self._db_rows(since, None, metrics):
                points.setdefault(t, {})[k] = round(v, 2) if v is not None else None
            source.append(f"sqlite {self.step} s")
        ts = sorted(points)
        names = metrics or sorted({k for p in points.values() for k in p} | set(BASE_METRICS))
        series = {n: [points[t].get(n) for t in ts] for n in names}
        return {"t": ts, "series": series, "range_s": range_s, "source": " + ".join(source),
                "db_error": self.db_error}
