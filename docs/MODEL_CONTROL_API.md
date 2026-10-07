# Model control API (AGX02 dashboard port)

The model controller runs in the agx-dashboard process (`controller/`). Its API is on the dashboard port
(`data/dashboard_port`, normally 8700). The store is `~/agx-models` (`docs/DEPLOY_MODEL.md`); it is not in git.

## 1. Authentication

| Who | How | Where |
|---|---|---|
| A person on the AGX dashboard page | HTTP Basic (`AGX_DASH_USER` / `AGX_DASH_PASSWORD` in `.env`) | every route |
| The rk console **server** of a paired board (for example DA01) | `Authorization: Bearer <token>` | `/api/models/*` and `GET /api/pair/boards` only |

- Each paired board has its own token. A board gets it one time, in the answer of `POST /api/pair` (pairing with a
  one-time code, `docs/PAIRING_API.md`). AGX02 keeps only the SHA-256 of each token, in `data/paired_boards.json`
  (mode 600, not in git). The board keeps its token in a mode-600 file (DA01: `~/.config/driveragent/agx_tokens/`).
  A browser never gets the token: the rk console server sends the request (owner rule M8).
- The token check is a constant-time compare with each stored hash. A removed board's token gets 401 at once,
  with `{"ok": false, "reason": "..."}` (`docs/PAIRING_API.md` Section 2). A refused token is not a failed login
  (no 429 from the polling of a removed board).
- With an accepted board address (`data/link_settings.json`, Settings page part "RK link"), a token request from an
  other client address gets `403 {"ok": false, "reason": "control is accepted only from <address>"}`.
- The old single token file `data/control.token` is not used any more: at the first start of this version, the
  dashboard moves it to the paired board `rk3588-da01` (only its hash) and renames it to `data/control.token.migrated`.
  The DA01 token stays the same, so the present pair keeps working with no new pairing.
- A `paired_boards.json` with a wrong mode or owner, or bad JSON, turns all board tokens off (Basic still works); the
  Settings page shows the problem.
- The IP allowlist of `config/dashboard.yaml` applies first (403). 10 failed logins in 300 s from one address give 429.
- Write requests from the page (Basic) also need the header `X-AGX-CSRF: 1` (Section 3).

## 2. Read routes

### GET /api/models/catalog
All model versions in the store, with state and reason.

```json
{"t": 1791366468.2, "store": "/home/tonyho/agx-models", "store_exists": true,
 "control_mode": "bench", "control_problem": null, "change_in_progress": null,
 "check_running": null, "check_queued": [],
 "counts": {"REGISTERED": 0, "NEEDS BUILD": 0, "BUILDING": 0, "READY": 0, "ACTIVE": 2, "FAILED": 0, "NO ADAPTER": 2},
 "entries": [{"key": "driverguard_yolopx@1", "name": "driverguard_yolopx", "version": "1", "type": "yolopx",
              "state": "ACTIVE", "reason": null, "description": "...", "output_kinds": ["boxes", "drivable_area", "lane_lines"],
              "cameras_permitted": [0, 1, 2, 3, 4, 5], "cameras_default": [0, 1, 2, 3, 4, 5],
              "files": [{"role": "engine", "path": "...", "sha256": "...", "exists": true}],
              "engine": {"path": "...", "built": false, "exists": true},
              "check": {"ok": true, "reason": null, "trt_version": "10.3.0", "trt_match": true,
                        "trt_device_warning": "WARNING: ...", "gpu_need_mb": 163.9, "inference_ms": 79.8, "checks": [...]},
              "live": {"state": "RUNNING", "cameras": [0, 1, 2, 3, 4, 5], "fps": 41.0,
                       "latency_ms": {"p50": 78, "p95": 114, "p99": 131}, "results_total": 123456},
              "job": null, "manifest_errors": []}]}
```

States (each `FAILED` has a reason in plain words):

| State | Meaning |
|---|---|
| `REGISTERED` | The manifest is valid. The checks are queued or run now (`reason` says which). |
| `NEEDS BUILD` | No engine yet, an ONNX file is there: build one on this AGX. |
| `BUILDING` | A build job runs now (`job` has the progress). |
| `READY` | All checks passed (Section 4.3 of the task): it can be activated. |
| `ACTIVE` | It runs now in agx-infer (`live`). |
| `FAILED` | Bad manifest, missing file, failed check, failed build or failed in agx-infer: see `reason`. |
| `NO ADAPTER` | Its `type` has no adapter in this version: it cannot be activated (`docs/ADD_MODEL_TYPE.md`). |

The checks run in a child process (`tools/model_check.py`), one at a time. Their result is stored in
`~/agx-models/_state/checks/<name>@<version>.json` and is checked again when a file or the manifest changes.
The TensorRT device warning is in `check.trt_device_warning` and `live.trt_device_warning`: information only.

### GET /api/models/control
```json
{"t": 1791366469.6, "control_mode": "bench", "control_problem": null,
 "control_file": "/home/tonyho/driveragent-agx/config/control.yaml", "change_in_progress": null,
 "active_set": [{"name": "driverguard_dtcp", "version": "1", "cameras": [0]},
                {"name": "driverguard_yolopx", "version": "1", "cameras": [0, 1, 2, 3, 4, 5]}],
 "last_good_set": null, "check_running": null}
```
- `control_mode` comes from `config/control.yaml`. **Only the owner changes that file; no API changes it.** A missing
  file means `bench`. A value that is not `bench` or `vehicle` means `vehicle` (refuse changes) with `control_problem`.

### GET /api/models/events?limit=100
The newest controller events, newest first (the audit log of Section 3): `{"t", "events": [...], "file"}`.

## 3. Write routes

| Route | Body | Does |
|---|---|---|
| `POST /api/models/{name}/{version}/build` | none | Build an engine from the version's ONNX file (state `NEEDS BUILD`) |
| `POST /api/models/{name}/{version}/activate` | `{"cameras": [0, 1]}` (optional) | Start the version on these cameras (default: the manifest default cameras) |
| `POST /api/models/{name}/{version}/deactivate` | none | Stop the version |
| `POST /api/models/rollback` | none | Put the last good set back |

- `202 {"ok": true, "accepted": true, "change": {"id", "action", "model", "t", "source", "user", "params"}}`: the change
  started. Its end is in `GET /api/models/control` (`change_in_progress` becomes null, `last_change` has `result` and
  `reason`) and in `GET /api/models/events`. A build answer also has `"warning"`: a build makes the active models slower.
- `4xx {"ok": false, "action", "model", "reason"}`: refused. The dashboards show `reason` as it is. Examples:
  - `control mode is vehicle: build, activate, deactivate and rollback are refused. Only the owner changes config/control.yaml.`
  - `another change runs now: activate driverguard_yolopx@2 since 21:14:03 (rk-console, tony). Only one change at a time.`
  - `driverguard_yolopx@1 is already active on cameras [0, 1, 2, 3, 4, 5]: deactivate it first to change its cameras`
  - `sparsedrive_convnext_orin@1 is NO ADAPTER: no adapter for type 'sparsedrive_backbone' ...`
  - `x@1: the checks are not done yet (owner rule M5)`, `not enough free memory for ...`
- A request from the page (Basic) must send `X-AGX-CSRF: 1`; a request with an `Origin` of another site is refused (403).
  A request of the rk console server (Bearer) sends its user name in `X-Actor`. The audit user is then
  `<X-Actor>@<board name>` (for example `tony@rk3588-da01`), or the board name when there is no `X-Actor`.

### Rules of the controller
- **One change at a time** (M4). A build is a change: during a build every other change is refused.
- **Checks first** (M5): only a version whose checks passed (state `READY`) can be activated.
- **Watchdog** (M6): after activate, agx-infer must give a valid result of the new instance in 20 s. If not, or if the
  instance fails, or agx-infer stops, the controller removes it, puts the last good set back and sets the version
  `FAILED` with the reason. Such a version can be activated again (its checks passed).
- **Control mode** (M7): `config/control.yaml` `control_mode: vehicle` refuses build, activate, deactivate and rollback.
- **No delete** (M2): no route and no tool deletes a model version.
- **Active set**: `~/agx-models/_state/active.json` (now) and `last_good.json` (the last set with valid results). Both are
  written only after a change that worked. After a restart, agx-infer loads `last_good.json`.
- **Audit** (M3): each request is one line in `~/agx-models/_state/audit.jsonl`: time, source (`agx-dashboard`,
  `rk-console`, `command-line`, `controller`), user, action, model, version, result (`started`, `ok`, `refused`,
  `failed`), reason.
- Several models can be active at the same time, also two versions of one model. Each result carries the model name and
  `modelVersion` = `<version>:<engine sha256[:16]>`.

## 4. Errors
`{"ok": false, "reason": "<plain words>"}` with 400 (bad request), 404 (no such model version), 409 (refused: another
change runs, wrong state, vehicle mode, ...), 503 (the controller does not run). The dashboards show `reason` as it is.
Authentication errors are plain text: 401, 403, 429.
