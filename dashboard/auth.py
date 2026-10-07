"""HTTP Basic auth + IP allowlist as one pure ASGI middleware.

Pure ASGI (not BaseHTTPMiddleware) so it covers every route, static files and the SSE stream
without buffering. The Authorization header is never logged.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import logging
import os
import re
import secrets
import stat
import time
from collections import OrderedDict
from typing import Iterable

log = logging.getLogger("dashboard.auth")

REALM = "agx02-dashboard"

# IPv4 only (the socket is IPv4: config bind 0.0.0.0). Same list as config/dashboard.yaml and
# dashboard/config.py. Docker bridges (172.16.0.0/12), 192.168.0.0/16 and link-local are NOT allowed.
DEFAULT_ALLOW = (
    "127.0.0.0/8",     # loopback
    "10.0.0.0/24",     # eno1 LAN
    "10.42.0.0/30",    # future Link C (direct cable to the RK3588)
    "100.64.0.0/10",   # tailscale tailnet: the RK3588 and the operator devices
)


# Failed-login limit per IP: when one IP has FAIL_LIMIT or more failed logins inside FAIL_WINDOW_S,
# each request from that IP gets 429 at once (no sleep: no task or thread waits), also with the
# correct password, until fewer than FAIL_LIMIT failures are inside FAIL_WINDOW_S. A good login
# (below the limit) clears the count of that IP. At most FAIL_MAX_IPS addresses are kept: the
# oldest go first.
FAIL_WINDOW_S = 300.0
FAIL_LIMIT = 10
FAIL_MAX_IPS = 4096
LOG_MAX_KEYS = 4096
LOG_EVERY_S = 60.0  # at most one deny / fail log line per IP and kind per minute
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
# The control token (owner rule M8) is accepted only on these paths: the DA01 rk console server uses it.
TOKEN_PREFIXES = ("/api/models/",)
TOKEN_MIN_LEN = 32


class TokenFile:
    """The model-control token: a file with mode 600, owned by this user, not in git. It is read again when it
    changes. A missing file or a wrong mode turns the token off (Basic auth still works); `problem` says why."""

    def __init__(self, path):
        self.path = str(path) if path else None
        self.problem: str | None = None
        self._sig = None
        self._token: bytes | None = None

    def get(self) -> bytes | None:
        if not self.path:
            self.problem = "no control token file is configured"
            return None
        try:
            st = os.stat(self.path)
        except OSError:
            self.problem, self._sig, self._token = f"{self.path} does not exist", None, None
            return None
        if stat.S_IMODE(st.st_mode) & 0o077 or st.st_uid != os.getuid():
            self.problem, self._sig, self._token = f"{self.path} must be mode 600 and owned by this user", None, None
            return None
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        if sig != self._sig:
            try:
                with open(self.path, "rb") as f:
                    tok = f.read().strip()
            except OSError as e:
                self.problem, self._token = f"{self.path} cannot be read: {e}", None
                return None
            self._token = tok if len(tok) >= TOKEN_MIN_LEN else None
            self.problem = None if self._token else f"{self.path}: the token needs {TOKEN_MIN_LEN} characters or more"
            self._sig = sig
        return self._token


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
    def __init__(self, app, user: str, password: str, allow_cidrs: Iterable[str], token_file=None):
        self.app = app
        self.user = user
        self.password = password
        self.networks = parse_networks(allow_cidrs)
        self.token = TokenFile(token_file)
        # ip -> failure times (monotonic). Order: the IP with the oldest last failure first.
        self._fails: OrderedDict[str, list[float]] = OrderedDict()
        # (kind, ip) -> (last log t, skipped). Order: the oldest log line first.
        self._logged: OrderedDict[tuple[str, str], tuple[float, int]] = OrderedDict()

    def _log_limited(self, kind: str, ip, path):
        """One log line per (kind, ip) per LOG_EVERY_S; the count of skipped lines goes in the next one."""
        now = time.monotonic()
        key = (kind, str(ip))
        last, skipped = self._logged.get(key, (0.0, 0))
        if now - last < LOG_EVERY_S and last:
            self._logged[key] = (last, skipped + 1)
            return
        self._logged[key] = (now, 0)
        self._logged.move_to_end(key)
        while len(self._logged) > LOG_MAX_KEYS:  # bound memory: remove only the oldest entries
            self._logged.popitem(last=False)
        log.warning("%s ip %s path %s%s", kind, safe_path(ip), safe_path(path),
                    f" ({skipped} more since last line)" if skipped else "")

    def _recent_fails(self, ip: str, now: float) -> list[float]:
        lst = self._fails.get(ip)
        if not lst:
            return []
        lst = [t for t in lst if now - t <= FAIL_WINDOW_S]
        if lst:
            self._fails[ip] = lst
        else:
            self._fails.pop(ip, None)
        return lst

    def _blocked_for(self, ip: str) -> float:
        """Seconds until this IP can try again (0.0 = not blocked). No wait here."""
        now = time.monotonic()
        lst = self._recent_fails(ip, now)
        if len(lst) < FAIL_LIMIT:
            return 0.0
        # the block ends when enough old failures leave the window
        return max(1.0, FAIL_WINDOW_S - (now - lst[-FAIL_LIMIT]))

    def _record_fail(self, ip: str) -> None:
        now = time.monotonic()
        lst = self._recent_fails(ip, now)
        lst.append(now)
        self._fails[ip] = lst[-(FAIL_LIMIT * 2):]
        self._fails.move_to_end(ip)
        while len(self._fails) > FAIL_MAX_IPS:  # bound memory: remove only the oldest entries
            self._fails.popitem(last=False)

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
        retry = self._blocked_for(str(ip))
        if retry:
            # too many failed logins from this IP: 429 at once, the password is not checked
            self._log_limited("login blocked", ip, scope.get("path"))
            if scope["type"] == "http":
                return await self._send_plain(
                    send, 429, b"Too many failed logins from this address. Try again later.\n",
                    [(b"retry-after", str(int(retry + 0.999)).encode())])
            return
        auth = None
        for k, v in scope.get("headers") or []:
            if k == b"authorization":
                auth = v
                break
        kind = None
        if auth is not None and auth[:7].lower() == b"bearer ":
            if str(scope.get("path") or "").startswith(TOKEN_PREFIXES):
                tok = self.token.get()
                if tok is not None and secrets.compare_digest(auth[7:].strip(), tok):
                    kind = "token"
        elif check_basic(auth, self.user, self.password):
            kind = "basic"
        if kind is None:
            if auth is not None:
                # wrong credentials (a request with no header is the normal browser first try)
                self._log_limited("auth failed", ip, scope.get("path"))
                self._record_fail(str(ip))
            if scope["type"] == "http":
                return await self._send_plain(
                    send, 401, b"Unauthorized\n",
                    [(b"www-authenticate", f'Basic realm="{REALM}"'.encode())])
            return
        self._fails.pop(str(ip), None)
        scope.setdefault("state", {})["auth_kind"] = kind   # "basic" (a person on the page) | "token" (rk console)
        return await self.app(scope, receive, send)
