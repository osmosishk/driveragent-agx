# AGX02 dashboard: pages and where each value is now

The page has the shell of the DA01 rk console: a left sidebar (at 900 px or less a bottom tab bar), a header and
eight pages with hash routing (`dashboard/static/router.js`). The design values come from
`dashboard/static/tokens.css`, a copy of the rk console tokens (`tools/sync_tokens.sh` makes the copy).
`tests/test_dashboard_pages.py` checks this list against the page.

No value of the old single page is lost. Each old element id is still on the page, once. The long explanations are
now behind an information control: the "i" button next to a card title shows and hides the text.

## 1. The pages

| Page | Hash | Cards |
|---|---|---|
| Overview | `#/overview` | banner (node state and reasons), status tiles, agx-infer card |
| Cameras | `#/cameras` | Cameras (six tiles) |
| Models | `#/models`, `#/models/<name>@<version>` | Models (catalog + details + actions), Engine files not in the configuration, Audit |
| RK link | `#/rklink` | RK3588 link (with "From agx-infer") |
| System | `#/system` | CPU, GPU and memory, Temperatures, Power, Disks, Network |
| Services | `#/services` | Services, Logs |
| History | `#/history` | History (six charts) |
| Settings | `#/settings` | Theme, Control mode, Version, Refresh periods |

The Overview tiles open their page: Cameras, Models, agx-infer (Services page), RK link, System, Disks (System
page), Services.

## 2. Inventory: old value -> page and card

| Old value (inventory, N1 section 8) | Element ids | Now |
|---|---|---|
| Host name, page title | `host` | header (all pages); also sidebar `side-host` and the browser title |
| Node state badge with source tooltip, SIMULATED | `node-state`, `sim-badge` | header |
| Time, Uptime, Power mode | `time`, `uptime`, `nvp` | header |
| Connection pill (Connected / Not connected / Data error / Server error / No data for N s) | `conn` | header; also sidebar foot (Live) |
| Reasons bar "Node state X: ..." | `state-reasons` | under the header on each page; Overview: in the banner |
| Cameras card, SIMULATED, note | `c-cams`, `cams-sim`, `cams-note` | Cameras > Cameras |
| Camera limits note (stale_s, no_signal_s, no_data_s, limits_source, status_period_s) | `cams-limits` | Cameras > Cameras, info control |
| Six camera tiles: name, DA01 name and role, SIMULATED, state, snapshot / "No picture" + overlay, fps, bit rate, lost packets (frames), decode p50, frame age, reason, last error | `cam-tiles` | Cameras > Cameras |
| Models card, SIMULATED, config error, unavailable reason | `c-models`, `models-sim`, `models-note`, `models-reason` | Models > Models |
| Models table (all columns of the old table) | `models-tbl` | Models > Models: the catalog table. The old columns and the old detail row are in the details of each row (open the row) |
| Engine file, realpath, "File not found", size, date, sha256 (16) | in `models-tbl` details | Models > Models > details > Engine |
| TensorRT match, TensorRT version, "Load FAILED", build device, load messages | in `models-tbl` details | Models > Models > details > Engine (match and version also in the extra table) |
| TensorRT device warning | in `models-tbl` / `extra-tbl` details | Models > details only (Engine, Check, Live) |
| Inputs and outputs | in `models-tbl` details | Models > Models > details > Engine |
| State, SIMULATED, error, last error with time, Errors, reason, group, "Not in config/models.yaml" | in `models-tbl` details | Models > Models > details > agx-infer (state also in the row) |
| Cameras, fps, latency p50 / p95 / p99, per stage pre / infer / post | in `models-tbl` (row + details) | Models > Models |
| GPU memory (estimate), queue wait p50 / p95 / p99, results, automatic restarts, path | in `models-tbl` details | Models > Models > details > agx-infer and Engine |
| Engine files not in the configuration (n): engine file, size, date, sha256 (16), TensorRT match, inputs and outputs | `extra-tbl`, `extra-sum` | Models > Engine files not in the configuration (row details: build device, device warning, load messages) |
| Scan note (time, running, count, dirs, interval, error, GPU memory note) | `scan-note` | Models > Engine files not in the configuration, info control |
| CPU average, per core load, frequency, bar | `c-cpu`, `cpu-avg`, `cpu-cores` | System > CPU |
| GPU load + bar, GPU frequency, RAM + level + bar, Swap, "same RAM" note | `c-gpu`, `gpu-load`, `gpu-bar`, `gpu-freq`, `ram`, `ram-bar`, `swap` | System > GPU and memory (note: info control) |
| Temperatures: maximum with level, zones, "(max)", "not readable" | `c-temp`, `temp-max`, `temp-tbl` | System > Temperatures |
| Power total, source note, rails V / A / W, fan PWM and rpm | `c-power`, `power-total`, `power-src`, `power-tbl`, `fan` | System > Power |
| Disks: mount, fs, % used, free of total, level, bar | `c-disk`, `disks` | System > Disks |
| Network: interface, state, speed, RX, TX, IPv4 | `c-net`, `net-tbl` | System > Network |
| RK3588 address, ping, packet loss (window), clock offset | `c-link`, `rk-ip`, `ping`, `loss-k`, `loss`, `clock` | RK link > RK3588 link |
| Clock note | `clock-note` | RK link > RK3588 link, info control |
| From agx-infer: SIMULATED, time since last frame (basis), result publish rate, subscribers, results total, last result | `link-sim`, `frame-age`, `res-rate`, `subs`, `res-total`, `res-last` | RK link > RK3588 link |
| agx-infer: state, SIMULATED, status age and version or reason, no-data placeholder | `c-infer`, `infer-state`, `infer-sim`, `infer-reason`, `infer-wait` | Overview > agx-infer (version also in Settings > Version) |
| agx-infer: cameras table, models table, errors | `infer-summary` | Overview > agx-infer |
| agx units: unit, user manager, system manager, PID, restarts, memory | `c-svc`, `agx-tbl` | Services > Services |
| Docker containers (running / total): name, state, status, restart policy, image | `docker-sum`, `docker-tbl` | Services > Services |
| Old DriverAgent processes (count): PID, user, match, command line | `oldp-sum`, `oldp-tbl` | Services > Services |
| Old DriverAgent processes note (~/s.sh) | `oldp-note` | Services > Services, info control |
| Old units (active / total): unit, state, unit file, PID, memory | `old-det`, `old-sum`, `old-tbl` | Services > Services |
| Services error note | `svc-err` | Services > Services |
| Logs: unit select (agx-infer, agx-dashboard, agx-sim), updated time and unit kind, 100 lines | `c-logs`, `logs-det`, `logs-unit`, `logs-t`, `logs` | Services > Logs |
| History: 1 h / 24 h, source and point count | `c-hist`, `hist-src` | History > History |
| Charts: load, RAM, maximum temperature, power, fps per camera, latency p50 per model (SIMULATED) | `ch-load`, `ch-ram`, `ch-temp`, `ch-power`, `ch-fps`, `ch-lat` | History > History |
| Footer text | (no id) | under each page (new text: only the Models page changes something) |

## 3. New on the pages

- Overview: banner and status tiles (Cameras, Models, agx-infer, RK link, System, Disks, Services).
- Models: control mode badge (`mc-mode`), change in progress (`mc-change`), Rollback (`mc-rollback`), last change
  (`mc-last`), counts, checks queue and store, the catalog state with its reason and the build progress, actions
  Build / Activate / Deactivate with a confirmation dialog (`mc-dlg`, camera picker for Activate), the manifest facts
  and the check result in the details, the audit list (`models-events`). AGX02 gives the refusal reason; the page shows
  it as it is. No delete function.
  The dialog is outside the page sections: a page change (also browser Back) closes it, except while its request
  runs. The table rows change only when their data changes, so the focus, a pressed button and a text selection stay.
  The control mode, change and last change come from the newer of the catalog and the control document.
- Settings: theme (system / light / dark, kept in this browser), control mode (read-only), page and agx-infer version,
  refresh periods.

## 4. Data flow

| Data | Period | When |
|---|---|---|
| `/api/stream` (SSE: health, cameras, services summary) | 1 s and at once for each agx-infer status | always |
| Camera tile state (`tiles.js`) | 250 ms | always |
| Snapshots | 1 s (only a new one) | always |
| `/api/models/catalog` | 2 s on Models, 10 s on Overview | while that page shows |
| `/api/models` | 2 s | while Models shows |
| `/api/models/events?limit=50`, `/api/models/control` | 5 s (control: 10 s on Settings) | while Models (Settings) shows |
| `/api/services` | 5 s | while Services shows (the Overview uses the SSE summary) |
| `/api/services/logs` | 5 s | while Services shows and the logs are open |
| `/api/history` | 10 s (1 h) or 60 s (24 h) | always; the charts get their width when History shows |
