# Pairing API (AGX02 dashboard port)

An RK board (for example DA01) pairs with this AGX one time. The pairing gives the board a control token for the model
controller (`docs/MODEL_CONTROL_API.md`). The list of paired boards is also the one source of the board addresses on
AGX02: agx-infer accepts FrameLink video and RkCameraInfo camera names only from these addresses.

Code: `common/pairing_store.py` (the store, read and write), `dashboard/pairing_api.py` (the routes),
`dashboard/auth.py` (GuardMiddleware: the board tokens). The page: Settings, part "RK link".

## 1. Routes

All routes are on the dashboard port (`data/dashboard_port`, normally 8700). The IP allowlist (`allow_cidrs` of
`config/dashboard.yaml`) applies to every route first: 403 `Forbidden: address not allowed`. The failed-login limit
applies to every route: 10 failed logins (a wrong password or a wrong pairing code) in 300 s from one address give 429
for each request of that address. A refused board token is not a failed login (Section 2).

| Route | Auth | Answer |
|---|---|---|
| `GET /api/pair/info` | none (IP allowlist only) | `{agx, api, name, schema, control_mode, control_problem, pairing_open, ports}` |
| `POST /api/pair/code` | Basic + `X-AGX-CSRF: 1` | `{ok, code, expires_t, ttl_s, wrong_max}` |
| `POST /api/pair` | none (the code is in the body) | 201 `{ok, board_id, token, agx_name, addresses}` |
| `GET /api/pair/boards` | Basic, or a board token | `[{id, name, address, addresses, paired_t, last_seen_t, last_seen_addr, source, link_state, link_detail}]` |
| `GET /api/pair/state` | Basic | the Settings page document (Section 1.5) |
| `POST /api/pair/boards/{id}/remove` | Basic + `X-AGX-CSRF: 1` | `{ok, removed, boards_left, addresses_left, warning}` |
| `GET /api/pair/settings` | Basic | `{accepted_board_address, problem, line}` |
| `POST /api/pair/settings` | Basic + `X-AGX-CSRF: 1` | `{ok, accepted_board_address, warning}` |

A write request from the page must send `X-AGX-CSRF: 1`. A request with an `Origin` of another site is refused (403).
Errors are `{"ok": false, "reason": "<plain words>"}`. The pages show `reason` as it is.

### 1.1 GET /api/pair/info
No secret. The DA01 rk console uses it in its link test (check "api").
```json
{"agx": true, "api": "agx-pair/1", "name": "agx02",
 "schema": {"status": ["0xef12fe49"], "result": "0xafcaff02"},
 "control_mode": "bench", "control_problem": null, "pairing_open": false,
 "ports": {"video": [6000, 6001, 6002, 6003, 6004, 6005], "video_base": 6000, "results": 5560, "status": 5561,
           "rkinfo": 5564, "api": 8700}}
```
`schema`: the hashes that agx-infer sends (`infer/publish/schema.py`). `ports`: read only, from `config/infer.yaml`
(`ports`) and `config/sources.yaml` (`cameras[].port`); `api` is the port of this request.

### 1.2 POST /api/pair/code
Makes a new pairing code. The code is in this answer only (the page of the user who made it shows it). No GET answer has
the code. A new code cancels the open code (one code at a time).
```json
{"ok": true, "code": "K7QD-M2XP", "expires_t": 1791370600.0, "ttl_s": 600.0, "wrong_max": 5}
```
Errors: 401 (no login), 403 (no `X-AGX-CSRF: 1`), 409 vehicle mode:
`AGX02 is in vehicle mode (config/control.yaml): a pairing code is refused`.

### 1.3 POST /api/pair
Body (JSON, at most 16 KiB):
```json
{"code": "K7QD-M2XP", "board_name": "rk3588-da01", "board_addresses": ["10.0.0.208", "10.0.0.209"]}
```
- `code`: the code from the AGX02 page. A dash, spaces and small letters are accepted.
- `board_name`: 1 to 64 characters: letters, digits, space, `.`, `_`, `-`. The board id is made from it
  (small letters, `[a-z0-9][a-z0-9_-]{0,31}`). A board name that is paired already is paired again: it gets a new token
  and its old token stops at once.
- `board_addresses`: at most 8 IPv4 addresses of the board (its addresses on the interface toward the AGX). The client
  address of this request is always added first.

Answer 201:
```json
{"ok": true, "board_id": "rk3588-da01", "token": "<43 characters>", "agx_name": "agx02",
 "addresses": ["10.0.0.208", "10.0.0.209"]}
```
The token is in this answer only. AGX02 keeps only its SHA-256. The board keeps the token in a file with mode 600.

Errors:
| Status | Reason (examples) |
|---|---|
| 400 | `board_name must be 1 to 64 characters: ...`, `board_addresses: '10.0.0.300' is not an IPv4 address`, `the request body is not JSON` |
| 403 | `no pairing code is open on this AGX: make a code on the AGX02 dashboard (Settings, RK link)` |
| 403 | `the pairing code is not correct` |
| 403 | `the pairing code is not correct. 5 wrong codes: the open code is cancelled. Make a new code` |
| 403 | `this pairing code was used already: make a new code on the AGX02 dashboard (Settings, RK link)` |
| 403 | `this pairing code expired (it works for 10 minutes): make a new code ...` |
| 403 | `this pairing code was cancelled after too many wrong codes: make a new code ...` |
| 403 | `pairing is accepted only from 10.0.0.208 (accepted board address)` |
| 409 | `AGX02 is in vehicle mode (config/control.yaml): pairing is refused` |
| 409 | `this AGX has 16 paired boards: remove one first` |
| 429 | too many failed logins from this address (text answer of GuardMiddleware) |
| 503 | `the paired boards file has a problem: ...` |

Each 403 of a code counts as a failed login of the client address (Section 1). Vehicle mode is checked before the code:
a refused request does not use the code.

### 1.4 GET /api/pair/boards
Basic or a board token (the DA01 rk console can see the boards). No token and no token hash.
```json
[{"id": "rk3588-da01", "name": "rk3588-da01", "address": "10.0.0.208", "addresses": ["10.0.0.208", "10.0.0.209"],
  "paired_t": 1791370000.0, "last_seen_t": 1791370123.4, "last_seen_addr": "10.0.0.208", "source": "migration",
  "link_state": "UP", "link_detail": "frames in the last 3 s: 90; result subscription: yes; camera names: 0 s ago"}]
```
`address` = `last_seen_addr`, or the first address. `link_state` (Section 4): `UP`, `frames only`, `results only`,
`DOWN`, `NO DATA` (agx-infer sends no status, or an old agx-infer without the keys).

### 1.5 GET /api/pair/state (the Settings page)
```json
{"unit": {"name": "agx02", "addresses": [{"if": "eno1", "addrs": ["10.0.0.130/24"], "state": "up"}], "ports": {...}},
 "boards": [... as 1.4 ...],
 "other_subscribers": {"available": true, "reason": null, "count": 1, "addresses": ["10.0.0.99"]},
 "source_filter": {"mode": "only", "when_empty": "any", "addresses": ["10.0.0.208", "10.0.0.209"], "reason": null,
                   "error": null, "seq": 3},
 "code": {"open": true, "state": "open", "expires_t": 1791370600.0, "left_s": 412.3, "made_by": "agx",
          "made_t": 1791370000.0, "wrong": 0, "wrong_max": 5},
 "settings": {"accepted_board_address": ""}, "settings_problem": null,
 "accepted_line": "Empty: each paired board can control this AGX. With an address: only that address can control this AGX.",
 "store_problem": null, "seq": 3, "control_mode": "bench", "control_problem": null, "t": 1791370188.0}
```
`code.state`: `none`, `open`, `used`, `expired`, `cancelled`. `unit.addresses`: the IPv4 addresses of this AGX (from the
health collector, `ip -4 addr`). `other_subscribers`: result subscribers (port 5560) whose address belongs to no paired
board. `source_filter`: the FrameLink / RkCameraInfo source filter that agx-infer uses now (its `allowed_sources`,
Section 4): `mode` `only` (the `addresses`), `any` (no address: agx-infer accepts each source address), `none` (no
address: agx-infer accepts no source address), `unknown` (no status, or an old agx-infer; `reason`). `when_empty`: the
rule of agx-infer for an empty address set: its `allowed_sources.when_empty` (`any` or `none`); without that key
`any` (the rule of the present agx-infer, `infer/ingest/ingest.py` `PairedBoards`).

### 1.6 POST /api/pair/boards/{id}/remove
No body. Answer `{"ok": true, "removed": "rk3588-da01", "boards_left": 0, "addresses_left": [], "warning": "..."}`.
The token of the board gets 401 at once. `addresses_left`: the union of the board addresses after the removal. When it
is empty, `warning` is `no paired board address is left: agx-infer has no board address for its video source filter
(see 'Video source filter' on the Settings page)` (else null), and the audit line has the same text. Errors: 404
`no paired board 'x' on this AGX`, 409 `AGX02 is in vehicle mode (config/control.yaml): the removal of a pairing is
refused`. The page asks for a confirmation first. When no other paired board has an address, the dialog says so and
says what agx-infer then does (`source_filter.when_empty`): with the present agx-infer (`any`), the video source
filter is OFF until a board pairs again (Section 5, empty set).

### 1.7 GET and POST /api/pair/settings
`POST` body `{"accepted_board_address": "10.0.0.208"}` or `{"accepted_board_address": ""}`.
- Empty: each paired board can control this AGX.
- With an address: only that address can control this AGX. A board-token request from another client address gets
  `403 {"ok": false, "reason": "control is accepted only from 10.0.0.208"}`; a pairing request from another address
  gets 403 too. Basic logins (the page) are not limited by this setting.
Errors: 400 `'x' is not an IPv4 address. Use an address like 10.0.0.208, or leave the field empty`, 409 vehicle mode
(`... a change of the link settings is refused`). An address that no paired board has is saved with
`"warning": "no paired board has the address 10.9.9.9: no board can control this AGX now"`.

## 2. Board tokens
- `Authorization: Bearer <token>` is accepted on `/api/models/*` and on `GET /api/pair/boards` only. On other routes a
  token gets 401.
- The check: SHA-256 of the token, compared in constant time with each stored hash (no early stop).
- The audit user of a model request: `<X-Actor>@<board name>` (source `rk-console`), or the board name.
- Each accepted token request updates `last_seen_t` and `last_seen_addr` (in memory; in the file at most once in 60 s).
  In bench mode, a new client address of the board is added to its `addresses` at once (seq +1), so agx-infer accepts
  it; audit `pair.address_added` `ok`. In vehicle mode a new address is NOT added (it would change the agx-infer source
  filter): the request is served, `last_seen` changes in memory only, the file does not change; audit
  `pair.address_added` `refused` with the vehicle-mode reason, one time per board and address in the dashboard process.
- A refused token (unknown, removed, paired again): `401 {"ok": false, "reason": "..."}` with
  `WWW-Authenticate: Bearer realm="agx02-dashboard"`. Reasons: `the pairing of board rk3588-da01 was removed on this
  AGX: this token stops. pair the board again with a new code (AGX02 dashboard: Settings, RK link)`, `... was paired
  again (a new token) ...`, `this AGX does not know this board token: pair the board again ...` (the removed / replaced
  hashes are kept in memory only: after a dashboard restart the reason is this general one). A refused token is not a
  failed login: a token has 256 random bits, and a removed board polls with its old token until it pairs again; this
  polling must not block the address with 429 (that would block `POST /api/pair` of the same board). A token on a
  route without tokens also gets 401 and is not a failed login.
- A board token with a wrong client address (accepted board address set): 403, see 1.7. A refused write is audited
  (`pair.control`).

## 3. Code rules
- 8 characters from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (no I, L, O, 0, 1), shown as `XXXX-XXXX`.
- Only in process memory: the SHA-256 of the code, the expiry, the state. A dashboard restart drops the code.
- One use: a code that paired a board is `used`.
- 10 minutes (`ttl_s` 600). Test hook: the environment variable `AGX_PAIR_CODE_TTL_S` (seconds) of the dashboard
  process. Do not set it on the real unit.
- One code at a time: a new code cancels the open code.
- 5 wrong codes while a code is open: the code is `cancelled`. Each wrong, used or expired code also counts as a failed
  login of the client address (10 in 300 s: 429).
- The code and the token are never logged, never audited and never in a GET answer.

## 4. Link state of a board
From the internal status of agx-infer (port 5562, `agx-infer-status/1`) that the dashboard has. The keys (a missing key
= an old agx-infer):
- `board_sources`: `{"<ip>": {"framelink_frames_3s", "framelink_last_t", "rkinfo_last_t", "result_subscriber"}}`
- `allowed_sources`: `{"addresses", "from", "seq", "loaded_t", "error"}` (the address set that agx-infer uses)
- `result_subscribers`: `{"count", "addresses"}` (TCP peers of the results PUB 5560)

| link_state | Rule (over the addresses of the board) |
|---|---|
| `UP` | frames in the last 3 s and a result subscription |
| `frames only` | frames in the last 3 s, no result subscription |
| `results only` | a result subscription, no frames in the last 3 s |
| `DOWN` | none |
| `NO DATA` | agx-infer sends no status now, or it does not send these keys |

## 5. Storage
All files are in `data/` (git-ignored), mode 600, owned by the dashboard user. Writes are atomic: a tmp file in the same
directory (mode 600) + fsync + `os.replace` + fsync of the directory, while the process holds `fcntl.flock` on
`<file>.lock`.

`data/paired_boards.json`:
```json
{"schema": "agx-paired-boards/1", "seq": 3,
 "boards": [{"id": "rk3588-da01", "name": "rk3588-da01", "addresses": ["10.0.0.208", "10.0.0.209"],
             "token_sha256": "<64 hex>", "paired_t": 1791370000.0, "last_seen_t": 1791370123.4,
             "last_seen_addr": "10.0.0.208", "source": "migration"}]}
```
- `seq` +1 when a board is added or removed, or when its addresses or its token change. A `last_seen` update alone does
  not change `seq`.
- At most 16 boards, 16 addresses per board.
- A file with a wrong mode or owner, bad JSON or another schema: the dashboard accepts no board token and refuses each
  change (it does not overwrite the file). The Settings page shows the problem.
- agx-infer reads the same file (`config/infer.yaml` `paired_boards_file`) and uses the union of all `addresses` as the
  FrameLink source filter and the RkCameraInfo allowlist. It reads the file again when it changes, without a restart.
  `common.pairing_store.board_addresses(path)` gives the same union.
- Empty set: a file with no board (after the removal of the last board) or with no address. The present agx-infer
  (`infer/ingest/ingest.py` `PairedBoards`) then accepts each source address (the same as a missing file). The
  dashboard shows this (`source_filter`, the Remove dialog, the `warning` of the removal); it does not decide the rule.

`data/link_settings.json`: `{"accepted_board_address": ""}`. A file with a wrong mode, bad JSON or a value that is not
an IPv4 address: each board-token request and each pairing is refused with the problem (fail closed).

Config keys (`dashboard/config.py`, defaults): `paired_boards_file: data/paired_boards.json`,
`link_settings_file: data/link_settings.json`, `infer_config: config/infer.yaml` (ports for 1.1),
`control_token_file: data/control.token` (read only by the migration).

## 6. Audit
Each action is one line in the model controller audit (`<model_store>/_state/audit.jsonl`, `controller/audit.py`;
also in `GET /api/models/events`). `model` and `version` are null.

| action | source | user |
|---|---|---|
| `pair.code` | `agx-dashboard` | the page login |
| `pair` | `rk-console` | the board name of the request (`?` when there is none) |
| `pair.remove`, `pair.settings` | `agx-dashboard` | the page login |
| `pair.control` (refused board-token write, accepted board address) | `rk-console` | the board name |
| `pair.address_added` (a new client address of a board: `ok` in bench mode, `refused` in vehicle mode) | `rk-console` | the board name |
| `pair.migrate` | `controller` | `start-up migration` |

`result`: `ok`, `refused` or `failed`, with `reason`. Extra fields: `board_id`, `board_name`, `addresses`, `addr` (the
client address), `accepted_board_address`, `boards_left`, `addresses_left`. Never a code, a token or a token hash.

## 7. Migration of the old control token (owner rule S6)
At the first start of this version (only a real start: `create_app(start_collectors=True)`), when
`data/paired_boards.json` does not exist and `data/control.token` exists:
1. The token (32 characters or more) becomes the board `rk3588-da01` (name `rk3588-da01`, `source: "migration"`), with
   only its SHA-256.
2. Its `addresses` are the present `config/sources.yaml` `rk_allowed_sources` and `config/dashboard.yaml` `rk_ip`
   (the values in the files, not the code defaults).
3. `data/control.token` is renamed to `data/control.token.migrated` (mode 600). The dashboard does not use it any more.
4. The audit gets `pair.migrate` `ok` (or `failed` with the reason: then nothing changes).

When the two keys are not in the files any more, the board gets no address from the migration (a warning in the log):
its first board-token request adds its client address in bench mode (Section 2; not in vehicle mode). Until then
agx-infer has no board address. So the
deploy runs the migration (the dashboard restart) BEFORE the two keys leave the config files.

The DA01 side keeps the same token, so the present pair DA01-AGX02 keeps working with no new pairing. When
`paired_boards.json` exists, the migration does nothing. After the migration the owner removes `rk_allowed_sources`
from `config/sources.yaml` and `rk_ip` from `config/dashboard.yaml`.
