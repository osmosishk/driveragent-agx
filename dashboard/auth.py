"""HTTP Basic auth + IP allowlist as one pure ASGI middleware.

Pure ASGI (not BaseHTTPMiddleware) so it covers every route, static files and the SSE stream
without buffering. The Authorization header is never logged.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import logging
import re
import secrets
import time
from typing import Iterable

log = logging.getLogger("dashboard.auth")

REALM = "agx02-dashboard"

DEFAULT_ALLOW = (
    "127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "100.64.0.0/10", "169.254.0.0/16", "fc00::/7", "fe80::/10",
)


# failed-auth throttle: after FAIL_FREE failures from one IP inside FAIL_WINDOW_S, each further
# failed attempt is delayed (1 s, 2 s, ... up to FAIL_MAX_DELAY_S). A good login clears the count.
FAIL_WINDOW_S = 300.0
FAIL_FREE = 5
FAIL_MAX_DELAY_S = 5.0
LOG_EVERY_S = 60.0  # at most one deny / fail log line per IP and kind per minute
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def safe_path(path) -> str:
    """Path for a log line: no control chars (no log injection), max 200 chars."""
    return _CTRL_RE.sub("?", str(path or ""))[:200]


def parse_networks(cidrs: Iterable[str]) -> list:
    return [ipaddress.ip_network(c, strict=False) for c in cidrs]


def ip_allowed(ip: str | None, networks: list | None = None) -> bool:
    """True when ip is in one of the allowed networks. Unparsable / missing ip -> False."""
    if not ip:
        return False
    nets = networks if networks is not None else parse_networks(DEFAULT_ALLOW)
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])  # drop IPv6 zone id
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr.version == n.version and addr in n for n in nets)


def check_basic(header_value: bytes | None, user: str, password: str) -> bool:
    if not header_value or not password:
        return False
    try:
        scheme, _, token = header_value.decode("latin-1").partition(" ")
        if scheme.lower() != "basic":
            return False
        raw = base64.b64decode(token.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    u, sep, p = raw.partition(":")
    if not sep:
        return False
    ok_u = secrets.compare_digest(u.encode("utf-8"), user.encode("utf-8"))
    ok_p = secrets.compare_digest(p.encode("utf-8"), password.encode("utf-8"))
    return ok_u and ok_p


class GuardMiddleware:
    def __init__(self, app, user: str, password: str, allow_cidrs: Iterable[str]):
        self.app = app
        self.user = user
        self.password = password
        self.networks = parse_networks(allow_cidrs)
        self._fails: dict[str, list[float]] = {}   # ip -> failure times (monotonic)
        self._logged: dict[tuple[str, str], tuple[float, int]] = {}  # (kind, ip) -> (last log t, skipped)

    def _log_limited(self, kind: str, ip, path):
        """One log line per (kind, ip) per LOG_EVERY_S; the count of skipped lines goes in the next one."""
        now = time.monotonic()
        key = (kind, str(ip))
        last, skipped = self._logged.get(key, (0.0, 0))
        if now - last < LOG_EVERY_S and last:
            self._logged[key] = (last, skipped + 1)
            return
        if len(self._logged) > 4096:  # bound memory under a flood from many addresses
            self._logged.clear()
        self._logged[key] = (now, 0)
        log.warning("%s ip %s path %s%s", kind, safe_path(ip), safe_path(path),
                    f" ({skipped} more since last line)" if skipped else "")

    def _fail_delay(self, ip: str) -> float:
        now = time.monotonic()
        lst = [t for t in self._fails.get(ip, []) if now - t <= FAIL_WINDOW_S]
        lst.append(now)
        if len(self._fails) > 4096:
            self._fails.clear()
        self._fails[ip] = lst[-100:]
        extra = len(lst) - FAIL_FREE
        return min(FAIL_MAX_DELAY_S, float(extra)) if extra > 0 else 0.0

    async def _send_plain(self, send, status: int, body: bytes, extra_headers=()):
        headers = [(b"content-type", b"text/plain; charset=utf-8"),
                   (b"content-length", str(len(body)).encode()),
                   (b"cache-control", b"no-store")]
        headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        client = scope.get("client")
        ip = client[0] if client else None
        if not ip_allowed(ip, self.networks):
            self._log_limited("deny", ip, scope.get("path"))
            if scope["type"] == "http":
                return await self._send_plain(send, 403, b"Forbidden: address not allowed\n")
            return  # websocket: close without accept
        auth = None
        for k, v in scope.get("headers") or []:
            if k == b"authorization":
                auth = v
                break
        if not check_basic(auth, self.user, self.password):
            if auth is not None:
                # wrong credentials (a request with no header is the normal browser first try)
                self._log_limited("auth failed", ip, scope.get("path"))
                delay = self._fail_delay(str(ip))
                if delay:
                    await asyncio.sleep(delay)
            if scope["type"] == "http":
                return await self._send_plain(
                    send, 401, b"Unauthorized\n",
                    [(b"www-authenticate", f'Basic realm="{REALM}"'.encode())])
            return
        self._fails.pop(str(ip), None)
        return await self.app(scope, receive, send)
