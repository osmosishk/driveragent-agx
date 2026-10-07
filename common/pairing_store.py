"""Paired boards of this AGX (docs/PAIRING_API.md). Pure stdlib. Read by agx-dashboard (read + write) and agx-infer (read).

Files (data/ is git-ignored; each file mode 600, owned by this user; written only atomically: a tmp file in the same
directory + fsync + os.replace, while holding fcntl.flock on <file>.lock):
  data/paired_boards.json  {"schema": "agx-paired-boards/1", "seq": N, "boards": [{id, name, addresses, token_sha256,
                            paired_t, last_seen_t, last_seen_addr, source}]}
                           THE ONE SOURCE OF THE BOARD ADDRESSES ON THIS AGX (agx-infer: FrameLink source filter and the
                           RkCameraInfo allowlist = the union of all "addresses"; board_addresses() below).
                           Only the SHA-256 of a token is stored. seq +1 when a board is added or removed or when its
                           addresses or token change; a last_seen update alone does not change seq.
  data/link_settings.json  {"accepted_board_address": ""}
Pairing codes live only in process memory (the hash of the code, the expiry): one use, 10 minutes (env
AGX_PAIR_CODE_TTL_S for a short test time), at most CODE_MAX_WRONG wrong codes, then the code is cancelled.
A token, a code or a hash is never logged.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
from pathlib import Path

log = logging.getLogger("pairing")

SCHEMA = "agx-paired-boards/1"
CODE_TTL_DEFAULT_S = 600.0
CODE_TTL_ENV = "AGX_PAIR_CODE_TTL_S"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no I, L, O, 0, 1 (easy to read and to type)
CODE_LEN = 8
CODE_MAX_WRONG = 5            # wrong codes while one code is open; then the code is cancelled
TOKEN_MIN_LEN = 32
TOKEN_BYTES = 32              # secrets.token_urlsafe(32): 43 characters
TOUCH_WRITE_S = 60.0          # last_seen goes to the file at most once in this time (a new address: at once)
MAX_BOARDS = 16
MAX_ADDRESSES = 16            # per board
MAX_BOARD_ADDRESSES_IN = 8    # in one pairing request
MAX_REMOVED_KEPT = 64         # token hashes of removed / replaced boards kept in memory (for the refusal reason only)
BOARD_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
BOARD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")
MIGRATION_BOARD = "rk3588-da01"


class PairingError(Exception):
    """A refused change: `status` is the HTTP status, the text is the reason in plain words."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def sha256_hex(value) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def norm_code(code) -> str:
    """The user may type the code with a dash, spaces or small letters."""
    return re.sub(r"[\s-]", "", str(code or "")).upper()


def fmt_code(code: str) -> str:
    return code[:4] + "-" + code[4:]


def board_id_from(name: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", str(name).lower()).strip("-_")[:32].strip("-_")
    return s if s and BOARD_ID_RE.match(s) else "board"


def ipv4(value) -> str | None:
    """A usable IPv4 board address as text, else None (no 0.0.0.0, multicast, broadcast, IPv6)."""
    try:
        a = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None
    if isinstance(a, ipaddress.IPv6Address):
        a = a.ipv4_mapped
        if a is None:
            return None
    if a.is_unspecified or a.is_multicast or a == ipaddress.IPv4Address("255.255.255.255"):
        return None
    return str(a)


def _dedup(seq) -> list[str]:
    out: list[str] = []
    for a in seq:
        if a and a not in out:
            out.append(a)
    return out


# ------------------------------------------------------------------------------------------------ file helpers
def file_problem(path: Path, st: os.stat_result | None = None) -> str | None:
    """None when the file is mode 600 (no group or other bits) and owned by this user."""
    try:
        st = st or os.stat(path)
    except OSError as e:
        return f"{path} cannot be read: {e.strerror}"
    if stat.S_IMODE(st.st_mode) & 0o077 or st.st_uid != os.getuid():
        return f"{path} must be mode 600 and owned by this user"
    return None


@contextlib.contextmanager
def locked(path: Path):
    """fcntl.flock (exclusive) on <path>.lock (mode 600) for a read-change-write."""
    lp = Path(str(path) + ".lock")
    lp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lp, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def atomic_write_json(path: Path, doc: dict) -> None:
    """tmp file (mode 600) in the same directory + fsync + os.replace + fsync of the directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    data = (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def _empty() -> dict:
    return {"schema": SCHEMA, "seq": 0, "boards": []}


def _clean_board(b) -> dict | None:
    if not isinstance(b, dict) or not BOARD_ID_RE.match(str(b.get("id") or "")):
        return None
    th = str(b.get("token_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", th):
        return None
    addrs = _dedup(ipv4(a) for a in (b.get("addresses") or []) if isinstance(a, str))
    num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None  # noqa: E731
    return {"id": b["id"], "name": str(b.get("name") or b["id"])[:64], "addresses": addrs[:MAX_ADDRESSES],
            "token_sha256": th, "paired_t": num(b.get("paired_t")), "last_seen_t": num(b.get("last_seen_t")),
            "last_seen_addr": ipv4(b.get("last_seen_addr")) if b.get("last_seen_addr") else None,
            "source": b.get("source") if b.get("source") in ("pairing", "migration") else "pairing"}


def read_boards_file(path) -> tuple[dict, str | None]:
    """(document, problem). A missing file: no boards, no problem. A bad mode, an other owner, bad JSON or a bad
    schema: no boards (fail closed) + the problem. Never raises."""
    p = Path(path)
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return _empty(), None
    except OSError as e:
        return _empty(), f"{p} cannot be read: {e.strerror}"
    prob = file_problem(p, st)
    if prob:
        return _empty(), prob
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        return _empty(), f"{p} is not valid JSON: {type(e).__name__}"
    if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("boards"), list):
        return _empty(), f"{p} does not have the schema {SCHEMA}"
    boards = [c for c in (_clean_board(b) for b in d["boards"]) if c]
    seq = d.get("seq") if isinstance(d.get("seq"), int) else 0
    return {"schema": SCHEMA, "seq": seq, "boards": boards}, None


def board_addresses(path) -> tuple[list[str], int, str | None]:
    """For agx-infer: (union of the addresses of all paired boards, seq, problem). A problem gives no addresses."""
    doc, prob = read_boards_file(path)
    return _dedup(a for b in doc["boards"] for a in b["addresses"]), doc["seq"], prob


def read_settings_file(path) -> tuple[dict, str | None]:
    p = Path(path)
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return {"accepted_board_address": ""}, None
    except OSError as e:
        return {"accepted_board_address": ""}, f"{p} cannot be read: {e.strerror}"
    prob = file_problem(p, st)
    if prob:
        return {"accepted_board_address": ""}, prob
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        return {"accepted_board_address": ""}, f"{p} is not valid JSON: {type(e).__name__}"
    acc = d.get("accepted_board_address") if isinstance(d, dict) else None
    if acc in (None, ""):
        return {"accepted_board_address": ""}, None
    if not isinstance(acc, str) or ipv4(acc) != acc.strip():
        return {"accepted_board_address": ""}, f"{p}: accepted_board_address {acc!r} is not an IPv4 address"
    return {"accepted_board_address": acc.strip()}, None


# ------------------------------------------------------------------------------------------------ the store
class PairingStore:
    """The paired boards, the link settings and the one open pairing code. Thread safe."""

    def __init__(self, boards_path, settings_path, clock=time.time, mono=time.monotonic):
        self.boards_path = Path(boards_path)
        self.settings_path = Path(settings_path)
        self._clock, self._mono = clock, mono
        self._lock = threading.RLock()
        self._sig = None
        self._doc = _empty()
        self.problem: str | None = None
        self._ssig = None
        self._settings = {"accepted_board_address": ""}
        self.settings_problem: str | None = None
        self._seen: dict[str, tuple[float, str]] = {}      # board id -> (t, addr), newest use of its token
        # token hash -> (board id, why) of boards removed or paired again in this process: only for the 401 reason.
        # A token in this map is NOT accepted. Lost at a restart (then the reason is the general one).
        self._gone: dict[str, tuple[str, str]] = {}
        self._code: dict | None = None

    # ---- read (the file is read again when it changes: mtime, size, inode)
    @staticmethod
    def _stat_sig(p: Path):
        try:
            st = os.stat(p)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino, st.st_mode, st.st_uid)

    def _load(self) -> dict:
        sig = self._stat_sig(self.boards_path)
        if sig != self._sig or sig is None:
            self._doc, self.problem = read_boards_file(self.boards_path)
            self._sig = sig
        return self._doc

    def doc(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._load()))

    def boards(self) -> list[dict]:
        """The boards with last_seen from memory (newer than the file), without token_sha256."""
        with self._lock:
            out = []
            for b in self._load()["boards"]:
                d = {k: v for k, v in b.items() if k != "token_sha256"}
                seen = self._seen.get(b["id"])
                if seen and (d["last_seen_t"] or 0) < seen[0]:
                    d["last_seen_t"], d["last_seen_addr"] = seen
                out.append(d)
            return out

    def settings(self) -> tuple[dict, str | None]:
        with self._lock:
            sig = self._stat_sig(self.settings_path)
            if sig != self._ssig or sig is None:
                self._settings, self.settings_problem = read_settings_file(self.settings_path)
                self._ssig = sig
            return dict(self._settings), self.settings_problem

    def check_token(self, token) -> dict | None:
        """The board {id, name} whose token hash matches, else None. Constant time over all boards (no early
        stop); a short token or a store problem gives None."""
        if isinstance(token, bytes):
            try:
                token = token.decode("ascii")
            except UnicodeDecodeError:
                return None
        token = str(token or "").strip()
        if len(token) < TOKEN_MIN_LEN:
            return None
        h = sha256_hex(token).encode()
        with self._lock:
            found = None
            for b in self._load()["boards"]:
                if secrets.compare_digest(h, b["token_sha256"].encode()) and found is None:
                    found = {"id": b["id"], "name": b["name"]}
            return found

    def token_refusal(self, token) -> str:
        """The 401 reason for a token that check_token() refused (plain words; never the token or its hash)."""
        if isinstance(token, bytes):
            token = token.decode("ascii", "replace")
        token = str(token or "").strip()
        again = "pair the board again with a new code (AGX dashboard: Settings, RK link)"
        if self.problem:
            return f"this AGX accepts no board token now: the paired boards file has a problem ({self.problem})"
        if len(token) >= TOKEN_MIN_LEN:
            with self._lock:
                gone = self._gone.get(sha256_hex(token))
            if gone:
                return f"the pairing of board {gone[0]} was {gone[1]} on this AGX: this token stops. " + again
        return "this AGX does not know this board token: " + again

    def _forget(self, token_sha256: str, board_id: str, why: str) -> None:
        with self._lock:
            self._gone[token_sha256] = (board_id, why)
            while len(self._gone) > MAX_REMOVED_KEPT:
                self._gone.pop(next(iter(self._gone)))

    # ---- write
    def _change(self, fn, bump: bool = True):
        """Read the file fresh under the file lock, fn(doc) changes it, write it atomically. A store problem
        (bad mode, bad JSON) refuses each change: the file is not overwritten."""
        with self._lock, locked(self.boards_path):
            doc, prob = read_boards_file(self.boards_path)
            if prob:
                raise PairingError(503, f"the paired boards file has a problem: {prob}")
            res = fn(doc)
            if bump:
                doc["seq"] = int(doc.get("seq") or 0) + 1
            atomic_write_json(self.boards_path, doc)
            self._sig = None
            self._load()
            return res

    def add_board(self, name: str, addresses, token_sha256: str, source: str = "pairing",
                  board_id: str | None = None) -> dict:
        bid = board_id or board_id_from(name)
        now = self._clock()

        old: list[str] = []

        def fn(doc):
            old[:] = [b["token_sha256"] for b in doc["boards"] if b["id"] == bid and b["token_sha256"] != token_sha256]
            boards = [b for b in doc["boards"] if b["id"] != bid]
            if len(boards) >= MAX_BOARDS:
                raise PairingError(409, f"this AGX has {MAX_BOARDS} paired boards: remove one first")
            b = {"id": bid, "name": str(name)[:64], "addresses": _dedup(addresses)[:MAX_ADDRESSES],
                 "token_sha256": token_sha256, "paired_t": round(now, 3), "last_seen_t": None,
                 "last_seen_addr": None, "source": source}
            boards.append(b)
            doc["boards"] = boards
            return {k: v for k, v in b.items() if k != "token_sha256"}
        res = self._change(fn)
        with self._lock:
            self._seen.pop(bid, None)
            self._gone.pop(token_sha256, None)
        for h in old:
            self._forget(h, bid, "paired again (a new token)")
        return res

    def remove(self, board_id: str) -> dict:
        """Remove a board. The answer has `boards_left` and `addresses_left` (the address union after the removal):
        0 addresses left = agx-infer has no board address (docs/PAIRING_API.md section 5, empty set)."""
        gone: list[str] = []

        def fn(doc):
            for b in doc["boards"]:
                if b["id"] == board_id:
                    doc["boards"] = [x for x in doc["boards"] if x["id"] != board_id]
                    gone.append(b["token_sha256"])
                    return {"id": b["id"], "name": b["name"], "boards_left": len(doc["boards"]),
                            "addresses_left": _dedup(a for x in doc["boards"] for a in x["addresses"])}
            raise PairingError(404, f"no paired board {board_id!r} on this AGX")
        res = self._change(fn)
        with self._lock:
            self._seen.pop(board_id, None)
        for h in gone:
            self._forget(h, board_id, "removed")
        return res

    def touch(self, board_id: str, addr: str | None, may_add=None) -> tuple[str | None, str | None]:
        """A request with the board token: last_seen in memory; to the file when the address is new for the board
        (seq +1: agx-infer gets the address) or once in TOUCH_WRITE_S (no seq change).
        may_add: None, or a callable() -> None (an address may be added) or the refusal reason (vehicle mode). It is
        called only for a new address. A refused new address: last_seen in memory only, no file write, no seq change.
        Returns (what, reason): ("added", None), ("refused", reason) or (None, None) (no new address)."""
        addr = ipv4(addr) if addr else None
        now = self._clock()
        with self._lock:
            b = next((x for x in self._load()["boards"] if x["id"] == board_id), None)
            if b is None:
                return None, None
            self._seen[board_id] = (round(now, 3), addr)
            new_addr = bool(addr) and addr not in b["addresses"]
            if new_addr and may_add is not None:
                why = may_add()
                if why:
                    return "refused", why
            if not new_addr and b["last_seen_t"] and now - b["last_seen_t"] < TOUCH_WRITE_S:
                return None, None

            def fn(doc):
                for x in doc["boards"]:
                    if x["id"] == board_id:
                        x["last_seen_t"], x["last_seen_addr"] = round(now, 3), addr
                        if addr and addr not in x["addresses"]:
                            a = x["addresses"] + [addr]
                            # keep the first address (the pairing request) and the newest ones
                            x["addresses"] = a if len(a) <= MAX_ADDRESSES else a[:1] + a[-(MAX_ADDRESSES - 1):]
                        return True
                return False
            try:
                self._change(fn, bump=new_addr)
            except (PairingError, OSError) as e:
                log.warning("last seen of board %s not written: %s", board_id, getattr(e, "reason", e))
                return ("refused", f"the paired boards file cannot be written: {getattr(e, 'reason', e)}") \
                    if new_addr else (None, None)
            return ("added", None) if new_addr else (None, None)

    def set_accepted(self, address: str) -> dict:
        address = (address or "").strip()
        if address and ipv4(address) != address:
            raise PairingError(400, f"{address!r} is not an IPv4 address. Use an address like 10.42.0.2, "
                                    "or leave the field empty")
        with self._lock, locked(self.settings_path):
            atomic_write_json(self.settings_path, {"accepted_board_address": address})
            self._ssig = None
        return self.settings()[0]

    # ---- the pairing code (process memory only)
    @staticmethod
    def code_ttl_s() -> float:
        try:
            v = float(os.environ.get(CODE_TTL_ENV, "") or CODE_TTL_DEFAULT_S)
        except ValueError:
            v = CODE_TTL_DEFAULT_S
        return v if v > 0 else CODE_TTL_DEFAULT_S

    def new_code(self, made_by: str) -> dict:
        """A new code. It cancels the open code (one code at a time). Returns {code, expires_t, ttl_s}."""
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        ttl = self.code_ttl_s()
        with self._lock:
            self._code = {"hash": sha256_hex(code), "expires_mono": self._mono() + ttl,
                          "expires_t": round(self._clock() + ttl, 3), "made_t": round(self._clock(), 3),
                          "made_by": str(made_by)[:64], "state": "open", "wrong": 0, "ttl_s": ttl}
            return {"code": fmt_code(code), "expires_t": self._code["expires_t"], "ttl_s": ttl}

    def _expire(self) -> None:
        c = self._code
        if c and c["state"] == "open" and self._mono() >= c["expires_mono"]:
            c["state"] = "expired"

    def code_state(self) -> dict:
        """Facts of the open code for the page: never the code."""
        with self._lock:
            self._expire()
            c = self._code
            if not c:
                return {"open": False, "state": "none"}
            left = max(0.0, c["expires_mono"] - self._mono()) if c["state"] == "open" else 0.0
            return {"open": c["state"] == "open", "state": c["state"], "expires_t": c["expires_t"],
                    "left_s": round(left, 1), "made_by": c["made_by"], "made_t": c["made_t"],
                    "wrong": c["wrong"], "wrong_max": CODE_MAX_WRONG}

    def pairing_open(self) -> bool:
        return self.code_state()["open"]

    def _ttl_text(self, ttl: float) -> str:
        return f"{ttl / 60:.0f} minutes" if ttl >= 120 else f"{ttl:.0f} s"

    def use_code(self, code) -> None:
        """Consume the open code, or raise PairingError(403, reason). Constant-time hash compare."""
        given = sha256_hex(norm_code(code)).encode()
        with self._lock:
            self._expire()
            c = self._code
            if c is None:
                raise PairingError(403, "no pairing code is open on this AGX: make a code on the AGX dashboard "
                                        "(Settings, RK link)")
            match = secrets.compare_digest(given, c["hash"].encode())
            if match:
                if c["state"] == "open":
                    c["state"] = "used"
                    return
                why = {"used": "this pairing code was used already",
                       "expired": f"this pairing code expired (it works for {self._ttl_text(c['ttl_s'])})",
                       "cancelled": "this pairing code was cancelled after too many wrong codes"}.get(c["state"], "this code stopped")
                raise PairingError(403, why + ": make a new code on the AGX dashboard (Settings, RK link)")
            if c["state"] == "open":
                c["wrong"] += 1
                if c["wrong"] >= CODE_MAX_WRONG:
                    c["state"] = "cancelled"
                    raise PairingError(403, f"the pairing code is not correct. {CODE_MAX_WRONG} wrong codes: the "
                                            "open code is cancelled. Make a new code")
            raise PairingError(403, "the pairing code is not correct")

    def pair(self, code, board_name, board_addresses, client_addr) -> dict:
        """Check the code, then add (or pair again) the board. Returns {board_id, token, board}; the token is in
        the answer only, the file has its SHA-256."""
        name = str(board_name or "").strip()
        if not BOARD_NAME_RE.match(name):
            raise PairingError(400, "board_name must be 1 to 64 characters: letters, digits, space, '.', '_', '-'")
        if board_addresses is None:
            board_addresses = []
        if not isinstance(board_addresses, list) or len(board_addresses) > MAX_BOARD_ADDRESSES_IN:
            raise PairingError(400, f"board_addresses must be a list of at most {MAX_BOARD_ADDRESSES_IN} "
                                    "IPv4 addresses")
        addrs = []
        for a in board_addresses:
            v = ipv4(a) if isinstance(a, str) else None
            if v is None:
                raise PairingError(400, f"board_addresses: {str(a)[:40]!r} is not an IPv4 address")
            addrs.append(v)
        if not isinstance(code, str) or not code.strip():
            raise PairingError(400, "the body must have the pairing code (code)")
        with self._lock:
            self._load()
            if self.problem:
                raise PairingError(503, f"the paired boards file has a problem: {self.problem}")
            if len(self._doc["boards"]) >= MAX_BOARDS and not any(
                    b["id"] == board_id_from(name) for b in self._doc["boards"]):
                raise PairingError(409, f"this AGX has {MAX_BOARDS} paired boards: remove one first")
            self.use_code(code)
            token = new_token()
            board = self.add_board(name, _dedup([ipv4(client_addr)] + addrs), sha256_hex(token), "pairing")
            return {"board_id": board["id"], "token": token, "board": board}


# ------------------------------------------------------------------------------------------------ migration (S6)
def migrate(store: PairingStore, token_path, addresses) -> dict | None:
    """Once, at dashboard start: when paired_boards.json does not exist and the old control token file exists,
    the token becomes the board "rk3588-da01" (its SHA-256 only, source "migration", addresses = the old config
    values); then the token file is renamed to <name>.migrated (mode 600, not used any more).
    Returns {board, from, to} or None (nothing to do). Raises PairingError when the old token cannot be used."""
    if not token_path:
        return None
    tp = Path(token_path)
    if store.boards_path.exists() or not tp.exists():
        return None
    try:
        tok = tp.read_bytes().strip().decode("ascii")
    except (OSError, UnicodeDecodeError) as e:
        raise PairingError(500, f"{tp} cannot be read for the migration: {type(e).__name__}")
    if len(tok) < TOKEN_MIN_LEN:
        raise PairingError(500, f"{tp}: the token has fewer than {TOKEN_MIN_LEN} characters; it is not migrated")
    addrs = _dedup(ipv4(a) for a in (addresses or []))
    board = store.add_board(MIGRATION_BOARD, addrs, sha256_hex(tok), "migration", board_id=MIGRATION_BOARD)
    dst = Path(str(tp) + ".migrated")
    os.replace(tp, dst)
    os.chmod(dst, 0o600)
    return {"board": board, "from": str(tp), "to": str(dst)}
