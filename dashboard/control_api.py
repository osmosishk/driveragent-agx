"""Model controller HTTP API on the dashboard port (docs/MODEL_CONTROL_API.md).

Read routes (any authenticated user):
  GET /api/models/catalog    all model versions in the store with state and reason
  GET /api/models/control    control mode, change in progress, active set, last good set
  GET /api/models/events     the newest controller events (audit log)
Authentication is done by dashboard/auth.py GuardMiddleware: HTTP Basic (the AGX page) or, on /api/models/ only, a
Bearer token from the control token file (the DA01 rk console server; the browser never has the token).
"""
from __future__ import annotations

from fastapi import Query
from fastapi.responses import JSONResponse


def _json(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"cache-control": "no-store"})


def register(app, hub) -> None:
    def ctl():
        return getattr(hub, "controller", None)

    def unavailable():
        return _json({"ok": False, "reason": "the model controller is not running on this dashboard"}, 503)

    @app.get("/api/models/catalog")
    def api_models_catalog():
        c = ctl()
        return _json(c.catalog_doc()) if c is not None else unavailable()

    @app.get("/api/models/control")
    def api_models_control():
        c = ctl()
        return _json(c.control_doc()) if c is not None else unavailable()

    @app.get("/api/models/events")
    def api_models_events(limit: int = Query(100, ge=1, le=1000)):
        c = ctl()
        return _json(c.events_doc(limit)) if c is not None else unavailable()
