# Model control API (AGX02 dashboard port)

The model controller runs in the agx-dashboard process (`controller/`). Its API is on the dashboard port
(`data/dashboard_port`, normally 8700). The store is `~/agx-models` (`docs/DEPLOY_MODEL.md`); it is not in git.

## 1. Authentication

| Who | How | Where |
|---|---|---|
| A person on the AGX dashboard page | HTTP Basic (`AGX_DASH_USER` / `AGX_DASH_PASSWORD` in `.env`) | every route |
| The DA01 rk console **server** | `Authorization: Bearer <token>` | `/api/models/*` only |

- The token is in `data/control.token` on AGX02 (mode 600, owner tonyho, not in git) and in a mode-600 file on DA01.
  A browser never gets the token: the rk console server sends the request (owner rule M8).
- A token file with a wrong mode or owner, or with fewer than 32 characters, turns the token off (Basic still works).
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
Added with the actions (task N3).

## 4. Errors
`{"ok": false, "reason": "<plain words>"}` with 400 (bad request), 404 (no such model version), 409 (refused: another
change runs, wrong state, vehicle mode, ...), 503 (the controller does not run). The dashboards show `reason` as it is.
Authentication errors are plain text: 401, 403, 429.
