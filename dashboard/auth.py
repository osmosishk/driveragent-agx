"""HTTP Basic auth + IP allowlist + the board tokens of the paired boards, as one pure ASGI middleware.

Pure ASGI (not BaseHTTPMiddleware) so it covers every route, static files and the SSE stream
without buffering. The Authorization header is never logged.

Kinds of a request (scope["state"]["auth_kind"]):
  basic   HTTP Basic: a person on the page (every route)
  token   "Authorization: Bearer <token>" of a paired board (common/pairing_store.py; the SHA-256 of the token is in
          data/paired_boards.json): only on /api/models/* and GET /api/pair/boards. scope["state"]["board"] =
          {id, name}. With an accepted board address (data/link_settings.json), a token request from another
          client address gets 403 "control is accepted only from <address>". A removed board's token: 401 at once,
          with a JSON reason. A refused board token is NOT a failed login: a token has 256 random bits (it cannot
          be guessed), and a removed board keeps polling with its old token until its owner pairs it again: that
          polling must not block the address (429) and so block the new pairing of the same board.
  public  no credentials: only GET /api/pair/info and POST /api/pair (the pairing code is in the body;
          dashboard/pairing_api.py records a wrong code as a failed login of the address)
The IP allowlist and the 429 block apply to each kind. Failed logins are: a wrong Basic password, a wrong pairing code.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import json
import logging
import re
import secrets
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
# Board tokens (owner rule M8) are accepted only on these paths: the rk console server of a paired board uses them.
TOKEN_PREFIXES = ("/api/models/",)
TOKEN_ROUTES = (("GET", "/api/pair/boards"),)
# No credentials needed (the IP allowlist and the failed-login limit still apply).
PUBLIC_ROUTES = (("GET", "/api/pair/info"), ("POST", "/api/pair"))


class LoginFails:
    """Failed logins per IP (monotonic times). One object is shared by GuardMiddleware and the pairing API (a wrong
    pairing code counts as a failed login). Order: the IP with the oldest last failure first."""

    def __init__(self):
        self.data: OrderedDict[str, list[float]] = OrderedDict()

    def recent(self, ip: str, now: float) -> list[float]:
        lst = self.data.get(ip)
        if not lst:
            return []
        lst = [t for t in lst if now - t <= FAIL_WINDOW_S]
        if lst:
            self.data[ip] = lst
        else:
            self.data.pop(ip, None)
        return lst

    def blocked_for(self, ip: str) -> float:
        """Seconds until this IP can try again (0.0 = not blocked). No wait here."""
        now = time.monotonic()
        lst = self.recent(ip, now)
        if len(lst) < FAIL_LIMIT:
            return 0.0
        # the block ends when enough old failures leave the window
        return max(1.0, FAIL_WINDOW_S - (now - lst[-FAIL_LIMIT]))

    def record(self, ip: str) -> None:
        now = time.monotonic()
        lst = self.recent(ip, now)
        lst.append(now)
        self.data[ip] = lst[-(FAIL_LIMIT * 2):]
        self.data.move_to_end(ip)
        while len(self.data) > FAIL_MAX_IPS:  # bound memory: remove only the oldest entries
            self.data.popitem(last=False)

    def ok(self, ip: str) -> None:
        self.data.pop(ip, None)


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


def ip_text(ip) -> str:
    """The client address as plain IPv4 text (an IPv4-mapped IPv6 address gives its IPv4 part)."""
    try:
        a = ipaddress.ip_address(str(ip or "").split("%", 1)[0])
    except ValueError:
        return str(ip or "")
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    return str(a)


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
    def __init__(self, app, user: str, password: str, allow_cidrs: Iterable[str], pairing=None,
                 fails: LoginFails | None = None, audit=None, vehicle=None):
        self.app = app
        self.user = user
        self.password = password
        self.networks = parse_networks(allow_cidrs)
        self.pairing = pairing          # common.pairing_store.PairingStore, or None: no board token is accepted
        self.audit = audit              # callable(source, user, action, result, reason, **extra) or None
        # callable(what) -> None (bench) or the vehicle-mode refusal reason; None: never vehicle mode
        self.vehicle = vehicle
        self._addr_noted: OrderedDict[tuple[str, str], None] = OrderedDict()   # (board, addr) refusals audited
        self.fails = fails if fails is not None else LoginFails()
        self._fails = self.fails.data   # ip -> failure times (the same dict object)
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

    def _blocked_for(self, ip: str) -> float:
        return self.fails.blocked_for(ip)

    def _record_fail(self, ip: str) -> None:
        self.fails.record(ip)

    async def _send_plain(self, send, status: int, body: bytes, extra_headers=()):
        headers = [(b"content-type", b"text/plain; charset=utf-8"),
                   (b"content-length", str(len(body)).encode()),
                   (b"cache-control", b"no-store")]
        headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def _send_json(self, send, status: int, doc: dict, extra_headers=()):
        body = json.dumps(doc).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"no-store"), *extra_headers]})
        await send({"type": "http.response.body", "body": body})

    def _board_check(self, ip) -> str | None:
        """None = the address may use a board token; else the refusal reason (accepted board address)."""
        settings, problem = self.pairing.settings()
        if problem:
            return f"control is refused: the link settings file has a problem ({problem})"
        acc = settings.get("accepted_board_address") or ""
        if acc and acc != ip_text(ip):
            return f"control is accepted only from {acc}"
        return None

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
        method = scope.get("method", "GET")
        path = str(scope.get("path") or "")
        if scope["type"] == "http" and (method, path) in PUBLIC_ROUTES:
            scope.setdefault("state", {})["auth_kind"] = "public"
            return await self.app(scope, receive, send)
        auth = None
        for k, v in scope.get("headers") or []:
            if k == b"authorization":
                auth = v
                break
        kind = board = None
        bearer = auth is not None and auth[:7].lower() == b"bearer "
        if bearer:
            if self.pairing is not None and (path.startswith(TOKEN_PREFIXES) or (method, path) in TOKEN_ROUTES):
                board = self.pairing.check_token(auth[7:].strip())
                if board is not None:
                    kind = "token"
                else:
                    # not a failed login (see the module text): 401 with the reason, no 429 count
                    self._log_limited("board token refused", ip, path)
                    if scope["type"] == "http":
                        return await self._send_json(
                            send, 401, {"ok": False, "reason": self.pairing.token_refusal(auth[7:].strip())},
                            [(b"www-authenticate", f'Bearer realm="{REALM}"'.encode())])
                    return
        elif check_basic(auth, self.user, self.password):
            kind = "basic"
        if kind is None:
            if auth is not None and not bearer:
                # wrong credentials (a request with no header is the normal browser first try)
                self._log_limited("auth failed", ip, path)
                self._record_fail(str(ip))
            if scope["type"] == "http":
                return await self._send_plain(
                    send, 401, b"Unauthorized\n",
                    [(b"www-authenticate", f'Basic realm="{REALM}"'.encode())])
            return
        self.fails.ok(str(ip))
        st = scope.setdefault("state", {})
        st["auth_kind"] = kind   # "basic" (a person on the page) | "token" (the rk console server of a paired board)
        if kind == "token":
            why = self._board_check(ip)
            if why:
                self._log_limited("board address refused", ip, path)
                if self.audit is not None and method == "POST":
                    self.audit("rk-console", board["name"], "pair.control", "refused", why, board_id=board["id"],
                               addr=ip_text(ip), path=safe_path(path))
                if scope["type"] == "http":
                    return await self._send_json(send, 403, {"ok": False, "reason": why})
                return
            st["board"] = board
            await asyncio.to_thread(self._touch, board, ip_text(ip))
        return await self.app(scope, receive, send)

    def _touch(self, board: dict, addr: str) -> None:
        """last_seen of the board; a new client address is added to its addresses (agx-infer then accepts it) only
        in bench mode. Each added address is audited; a refused one once per (board, address) in this process."""
        may_add = (lambda: self.vehicle("a new board address")) if self.vehicle is not None else None
        what, why = self.pairing.touch(board["id"], addr, may_add)
        if what is None or self.audit is None:
            return
        if what == "added":
            self._addr_noted.pop((board["id"], addr), None)
            self.audit("rk-console", board["name"], "pair.address_added", "ok", None, board_id=board["id"], addr=addr)
            log.info("board %s: new address %s added to its addresses", board["id"], safe_path(addr))
            return
        key = (board["id"], addr)
        if key in self._addr_noted:
            return
        self._addr_noted[key] = None
        while len(self._addr_noted) > LOG_MAX_KEYS:
            self._addr_noted.popitem(last=False)
        self.audit("rk-console", board["name"], "pair.address_added", "refused", why, board_id=board["id"], addr=addr)
        log.warning("board %s: new address %s not added: %s", board["id"], safe_path(addr), why)
