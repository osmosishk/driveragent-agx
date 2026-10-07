"""Power log HTTP API of the AGX02 dashboard (all GET; data: dashboard/power_log.py, common/powerlog.py).

  GET /api/power                         Basic        now value, power mode, event state, log size, sources
  GET /api/power/samples?range=&rails=   Basic        chart data (range 1h, 24h, 7d, 30d; rails 0 or 1) + events
  GET /api/power/events?limit=20         Basic        the last events with the mean power before and after (1..100)
  GET /api/power/energy                  Basic        Wh and hours with data: today, 7 d, 30 d
  GET /api/power/export?kind=&range=     Basic        CSV file (kind samples or events)
  GET /api/power/now                     Basic or the token of a paired board (dashboard/auth.py TOKEN_ROUTES)
Labels (rule W2): SENSOR (the INA3221 rails read it now) or NO SENSOR. No value is calculated from the load.
A bad argument gives 400 {"error": ...}. When the log is not open the routes that read it give 503 {"error": ...}.
"""
from __future__ import annotations

import time

from fastapi import Query
from fastapi.responses import JSONResponse, Response

from common.powerlog import RANGES

SCHEMA = "agx-power/1"
PART = "agx02"
MAX_EVENTS_IN_RANGE = 500


def _json(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"cache-control": "no-store"})


def _bad(text: str) -> JSONResponse:
    return _json({"error": text}, 400)


def _day_start(now: float) -> float:
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def register(app, hub) -> None:
    def pw():
        return getattr(hub, "power", None)

    def plog():
        p = pw()
        return p.log if p is not None else None

    def closed() -> JSONResponse:
        p = pw()
        why = (p.log_doc().get("error") if p is not None else None) or "the power log is not open"
        return _json({"error": why}, 503)

    def keys(lg, rails: bool) -> list[str]:
        if not rails:
            return [PART]
        return [PART] + [k for k in lg.series_keys() if k.startswith(PART + ":")]

    def check_range(r: str):
        return None if r in RANGES else _bad("range must be one of " + ", ".join(RANGES))

    def check_rails(v: str):
        return None if v in ("0", "1") else _bad("rails must be 0 or 1")

    @app.get("/api/power")
    def api_power():
        p = pw()
        now = p.now_doc()
        return _json({"schema": SCHEMA, "now": now, "power_mode": now.get("power_mode"),
                      "state": p.state_doc(), "log": p.log_doc(), "sources": p.sources()})

    @app.get("/api/power/now")
    def api_power_now():
        d = pw().now_doc()
        return _json({k: d.get(k) for k in ("part", "watts", "label", "t", "rails", "what", "power_mode")})

    @app.get("/api/power/samples")
    def api_power_samples(range: str = Query("1h"), rails: str = Query("0")):
        bad = check_range(range) or check_rails(rails)
        if bad:
            return bad
        lg = plog()
        if lg is None:
            return closed()
        span, bucket = RANGES[range]
        now = time.time()
        since, until = now - span, now + 1
        d = lg.samples(since, until, bucket, keys(lg, rails == "1"))
        evs = lg.events(since, until, limit=MAX_EVENTS_IN_RANGE)
        d.update(range=range, events=[{k: e[k] for k in ("t", "kind", "value", "prev", "exact")} for e in evs])
        return _json(d)

    @app.get("/api/power/events")
    def api_power_events(limit: str = Query("20")):
        try:
            n = int(limit)
        except ValueError:
            n = 0
        if not 1 <= n <= 100:
            return _bad("limit must be a whole number from 1 to 100")
        lg = plog()
        if lg is None:
            return closed()
        return _json({"rows": lg.before_after([PART], n, factors=lg.factors())})

    @app.get("/api/power/energy")
    def api_power_energy():
        lg = plog()
        if lg is None:
            return closed()
        now = time.time()
        return _json({"today": lg.energy(_day_start(now), now, [PART]),
                      "d7": lg.energy(now - 7 * 86400, now, [PART]),
                      "d30": lg.energy(now - 30 * 86400, now, [PART])})

    @app.get("/api/power/export")
    def api_power_export(kind: str = Query("samples"), range: str = Query("24h"), rails: str = Query("0")):
        if kind not in ("samples", "events"):
            return _bad("kind must be samples or events")
        bad = check_range(range) or check_rails(rails)
        if bad:
            return bad
        lg = plog()
        if lg is None:
            return closed()
        now = time.time()
        since, until = now - RANGES[range][0], now + 1
        text = (lg.csv_samples(since, until, keys(lg, rails == "1")) if kind == "samples"
                else lg.csv_events(since, until))
        name = f"agx02-power-{kind}-{range}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}.csv"
        return Response(text, media_type="text/csv; charset=utf-8",
                        headers={"cache-control": "no-store", "content-disposition": f'attachment; filename="{name}"'})
