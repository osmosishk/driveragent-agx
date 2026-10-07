#!/usr/bin/env python3
"""Checks for the power log core (common/powerlog.py; the same file is rk/common/powerlog.py on DA01), with stored
samples and a fake clock: 1 s / 10 s / day rows, energy only where samples exist (a gap is not zero), hours with data,
events from state changes, before/after means, manual readings and their ratio, the system total and the battery
ESTIMATE, CSV export, pruning. Plain asserts; also collected by pytest (test_* functions).

    python3 rk/common/tests/test_powerlog.py   (AGX02: PYTHONPATH=. .venv/bin/python -m pytest tests/test_powerlog.py)
"""
from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
import time
from pathlib import Path

from common import powerlog as P

T0 = time.mktime(time.strptime("2026-10-08 10:00:00", "%Y-%m-%d %H:%M:%S"))   # local time, 10 s aligned


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def mk(tmp: str, t: float = T0) -> tuple[P.PowerLog, Clock]:
    c = Clock(t)
    return P.PowerLog(os.path.join(tmp, "power.sqlite"), clock=c), c


def feed(log: P.PowerLog, clock: Clock, t0: float, secs: int, watts, part: str = "agx02", rails=None) -> None:
    for i in range(secs):
        clock.t = t0 + i + 0.2
        w = watts(i) if callable(watts) else watts
        log.add([P.Reading(part, w, P.SENSOR, clock.t, "test", rails=rails or {})])
    log.flush()


def test_rows_energy_gap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        feed(log, c, T0, 600, 20.0)                     # 10 min at 20 W
        # a gap of 10 min, then 10 min at 30 W
        feed(log, c, T0 + 1200, 600, 30.0)
        sz = log.size()
        assert sz["rows"]["s1"] == 1200, sz
        assert sz["rows"]["s10"] == 120, sz
        e = log.energy(T0, T0 + 1800)["agx02"]
        # 600 s * 20 W + 600 s * 30 W = 30000 Ws = 8.333 Wh; the gap adds nothing
        assert abs(e["wh"] - 8.333) < 0.01, e
        assert abs(e["hours"] - 1200 / 3600) < 0.001, e
        assert abs(e["mean_w"] - 25.0) < 0.001, e
        d = log.days("2026-10-01")
        assert len(d) == 1 and d[0]["day"] == "2026-10-08" and abs(d[0]["wh"] - 8.333) < 0.01, d
        assert d[0]["min_w"] == 20.0 and d[0]["max_w"] == 30.0 and abs(d[0]["hours"] - 0.3333) < 0.001, d
        s = log.samples(T0, T0 + 1800, 60)
        v = s["series"]["agx02"]
        assert v[0] == 20.0 and v[10] is None and v[25] == 30.0, v      # the gap is None, not 0
        assert s["seconds"]["agx02"][0] == 60 and s["seconds"]["agx02"][10] == 0
        log.close()


def test_energy_old_rows_use_10s() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        feed(log, c, T0, 300, 10.0)
        c.t = T0 + 3 * 3600                            # 1 s rows are pruned after an hour; 10 s rows stay
        log.prune()
        assert log.size()["rows"]["s1"] == 0
        e = log.energy(T0, T0 + 3600)["agx02"]
        assert abs(e["wh"] - 300 * 10 / 3600) < 0.001 and abs(e["hours"] - 300 / 3600) < 0.001, e
        m, n = log.window_mean("agx02", T0 + 60, T0 + 120)
        assert m == 10.0 and n == 60, (m, n)
        log.close()


def test_energy_joint_of_1s_and_10s_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        feed(log, c, T0, 100, 10.0)
        log.db.execute("DELETE FROM s1 WHERE t < ?", (T0 + 35,))     # as after a prune: 1 s rows start mid-bucket
        e = log.energy(T0, T0 + 100)["agx02"]
        assert abs(e["hours"] - 100 / 3600) < 0.0005 and abs(e["wh"] - 1000 / 3600) < 0.001, e
        log.close()


def test_pending_counts_before_flush() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        for i in range(5):
            c.t = T0 + i
            log.add([P.Reading("agx02", 40.0, P.SENSOR, c.t, "test")])
        assert log.size()["rows"]["s1"] == 0            # not written yet (one write each 10 s)
        assert log.energy(T0, T0 + 10)["agx02"]["hours"] == round(5 / 3600, 3)
        m, n = log.window_mean("agx02", T0, T0 + 5)
        assert m == 40.0 and n == 5
        log.close()


def test_labels_not_sensor_are_not_samples() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        log.add([P.Reading("da01", None, P.NO_SENSOR, T0, "hwmon"), P.Reading("da01", 39.0, P.MANUAL, T0, "manual"),
                 P.Reading("agx02", float("nan"), P.SENSOR, T0, "test")])
        log.flush()
        assert log.size()["rows"]["s1"] == 0 and log.series_keys() == []
        log.close()


def test_rails_are_series() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        feed(log, c, T0, 20, 22.0, rails={"VDD_GPU_SOC": 13.0, "VDD_CPU_CV": 2.0})
        assert log.series_keys() == ["agx02", "agx02:VDD_CPU_CV", "agx02:VDD_GPU_SOC"]
        assert log.energy(T0, T0 + 20, ["agx02:VDD_GPU_SOC"])["agx02:VDD_GPU_SOC"]["mean_w"] == 13.0
        log.close()


def test_events_and_before_after() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        c.t = T0
        assert log.note_state({"sender": True, "models": ["a@1", "b@1"], "recording": None}) == []   # first: baseline
        feed(log, c, T0, 120, lambda i: 30.0 if i < 60 else 24.0)
        ev = log.note_state({"sender": True, "models": ["a@1"]}, t=T0 + 60)
        assert len(ev) == 1 and ev[0]["kind"] == "models" and ev[0]["exact"] == 1, ev
        feed(log, c, T0 + 120, 120, 24.0)
        c.t = T0 + 240
        rows = log.before_after(["agx02", "da01"], factors={"agx02": 2.0})
        assert len(rows) == 1
        p = rows[0]["parts"]["agx02"]
        assert p["before_w"] == 30.0 and p["after_w"] == 24.0 and p["diff_w"] == -6.0, p
        assert p["diff_corrected_w"] == -12.0 and p["n_before"] == 60 and p["n_after"] == 60, p
        assert rows[0]["parts"]["da01"]["diff_w"] is None and rows[0]["notes"] == [], rows[0]
        assert rows[0]["value"] == ["a@1"] and rows[0]["prev"] == ["a@1", "b@1"]
        # an event whose 60 s after are not over yet, and one next to another event
        log.note_state({"sender": False}, t=T0 + 230)
        rows = log.before_after(["agx02"])
        assert "not complete yet" in " ".join(rows[0]["notes"]), rows[0]
        assert rows[0]["parts"]["agx02"]["after_w"] is None and "after" in rows[0]["parts"]["agx02"]["reason"]
        log.close()
        # a new start: a change while the log did not run gives an event with exact = False
        log2, c2 = mk(tmp, T0 + 600)
        ev = log2.note_state({"sender": True, "models": ["a@1"]})
        assert len(ev) == 1 and ev[0]["kind"] == "sender" and ev[0]["exact"] == 0, ev
        rows = log2.before_after(["agx02"])
        assert "not exact" in " ".join(rows[0]["notes"])
        log2.close()


def test_manual_ratio_total_estimate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        m = log.add_manual("agx02", 60.0, "meter at the supply input", "owner", 22.5, {"sender": True})
        assert m["id"] == 1
        got = log.manual()
        assert got[0]["ratio"] == round(60 / 22.5, 3) and got[0]["state"] == {"sender": True}
        log.add_manual("da01", 39.0, "", "owner", None, {})
        assert log.manual(part="da01")[0]["ratio"] is None
        now = T0
        parts = {"agx02": P.Reading("agx02", 22.5, P.SENSOR, now - 1, "x"),
                 "da01": P.Reading("da01", 39.0, P.MANUAL, now - 5, "manual"),
                 "router": None}
        tot = P.system_total(parts, {"agx02": 2.0}, now, ["da01", "agx02", "router"])
        assert tot["sensor_w"] == 22.5 and tot["corrected_w"] == 45.0, tot      # the manual 39 W is not in it
        assert tot["parts"] == ["agx02"] and tot["missing"] == ["da01", "router"], tot
        old = P.system_total({"agx02": P.Reading("agx02", 22.5, P.SENSOR, now - 10, "x")}, {}, now, ["agx02"])
        assert old["sensor_w"] is None and old["label"] == P.NO_SENSOR       # an old sensor value is not "now"
        est = P.battery_estimate(1000, 45.0, tot["missing"])
        assert est["label"] == P.ESTIMATE and est["hours"] == 22.22 and "da01" in est["note"]
        assert P.battery_estimate(None, 45.0, []) is None and P.battery_estimate(1000, None, []) is None
        log.set_setting("factors", {"agx02": 2.6})
        assert log.factors() == {"agx02": 2.6}
        log.close()


def test_csv_and_prune() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log, c = mk(tmp)
        feed(log, c, T0, 30, 12.0)
        log.note_state({"sender": True}, t=T0)
        log.note_state({"sender": False}, t=T0 + 10)
        rows = list(csv.reader(io.StringIO(log.csv_samples(T0, T0 + 30))))
        assert rows[0][0] == "time_utc" and len(rows) == 31 and rows[1][2] == "agx02" and rows[1][5] == "SENSOR"
        ev = list(csv.reader(io.StringIO(log.csv_events(T0 - 1, T0 + 30))))
        assert len(ev) == 2 and ev[1][2] == "sender" and ev[1][3] == "false"
        c.t = T0 + 40 * 86400
        log.prune()
        sz = log.size()
        assert sz["rows"]["s1"] == 0 and sz["rows"]["s10"] == 0 and sz["rows"]["day"] == 1, sz
        assert os.stat(os.path.join(tmp, "power.sqlite")).st_mode & 0o777 == 0o600
        log.close()
        ro = P.PowerLog(os.path.join(tmp, "power.sqlite"), readonly=True)
        assert ro.days("2026-01-01")[0]["day"] == "2026-10-08"
        ro.close()


def main() -> int:
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print(f"OK {n} tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
