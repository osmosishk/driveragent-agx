"""Model controller HTTP API on the dashboard port (docs/MODEL_CONTROL_API.md).

Read routes:
  GET  /api/models/catalog                       all model versions in the store with state and reason
  GET  /api/models/control                       control mode, change in progress, active set, last good set
  GET  /api/models/events?limit=N                the audit log, newest first
Write routes (202 = the change started; 4xx = refused, {"ok": false, "reason": ...}):
  POST /api/models/{name}/{version}/build
  POST /api/models/{name}/{version}/activate     body {"cameras": [..]} (optional: default = the manifest default)
  POST /api/models/{name}/{version}/deactivate
  POST /api/models/rollback
Authentication: dashboard/auth.py GuardMiddleware. HTTP Basic (a person on the AGX page: source agx-dashboard; a write
request must also send "X-AGX-CSRF: 1" and, when it sends Origin, the same origin) or, on /api/models/ only, the
Bearer token of a paired board (docs/PAIRING_API.md; source rk-console; audit user "<X-Actor>@<board name>", or the
board name when there is no X-Actor header).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
from urllib.parse import urlsplit

from fastapi import Query, Request
from fastapi.responses import JSONResponse

from controller.audit import clean

BODY_MAX = 16 * 1024


def _json(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"cache-control": "no-store"})


def actor(request: Request) -> tuple[str, str]:
    """(source, user) of a request for the audit log."""
    kind = getattr(request.state, "auth_kind", None)
    if kind == "token":
        board = getattr(request.state, "board", None) or {}
        name = clean(board.get("name") or "rk-console", 40)
        who = clean(request.headers.get("x-actor") or "", 40)
        return "rk-console", clean(f"{who}@{name}" if who else name, 82)
    if kind == "basic":
        try:
            raw = base64.b64decode(request.headers.get("authorization", "").split(" ", 1)[1]).decode("utf-8")
            return "agx-dashboard", clean(raw.partition(":")[0])
        except (IndexError, binascii.Error, UnicodeDecodeError, ValueError):
            return "agx-dashboard", "?"
    return "unknown", "?"


def csrf_problem(request: Request) -> str | None:
    """A write request from a browser (Basic auth) must send X-AGX-CSRF: 1 and, if it sends Origin, this origin."""
    if getattr(request.state, "auth_kind", None) == "token":
        return None
    if request.headers.get("x-agx-csrf") != "1":
        return "a write request from the page must send the header X-AGX-CSRF: 1"
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        return "a write request from another site is refused"
    return None


async def _body(request: Request) -> tuple[dict | None, str | None]:
    raw = await request.body()
    if len(raw) > BODY_MAX:
        return None, "the request body is too large"
    if not raw.strip():
        return {}, None
    try:
        d = json.loads(raw)
    except ValueError:
        return None, "the request body is not JSON"
    return (d, None) if isinstance(d, dict) else (None, "the request body must be a JSON object")


def register(app, hub) -> None:
    def ctl():
        return getattr(hub, "controller", None)

    def unavailable():
        reason = getattr(hub, "controller_error", None) or "the model controller is not running on this dashboard"
        return _json({"ok": False, "reason": reason}, 503)

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

    async def write(request: Request, action: str, name: str | None, version: str | None):
        c = ctl()
        if c is None:
            return unavailable()
        bad = csrf_problem(request)
        if bad:
            return _json({"ok": False, "reason": bad}, 403)
        body, problem = await _body(request)
        if problem:
            return _json({"ok": False, "reason": problem}, 400)
        params = {"cameras": body["cameras"]} if "cameras" in body else {}
        source, user = actor(request)
        status, doc = await asyncio.to_thread(c.request, action, name, version, params, source, user)
        return _json(doc, status)

    @app.post("/api/models/rollback")
    async def api_models_rollback(request: Request):
        return await write(request, "rollback", None, None)

    @app.post("/api/models/{name}/{version}/{action}")
    async def api_models_action(name: str, version: str, action: str, request: Request):
        if action not in ("build", "activate", "deactivate"):
            return _json({"ok": False, "reason": f"unknown action {action!r} (build, activate, deactivate)"}, 404)
        return await write(request, action, name, version)
