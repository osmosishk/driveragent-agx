# Power log in the two dashboards - report

Task start: 2026-10-08 00:26:25 CST (DA01 clock). End of the work: 02:00 CST. All times are CST; AGX02 logs use BST
(BST = CST - 7 h). The same report is in the two repositories (driveragent and driveragent-agx, `docs/`). How to add
a power source: `docs/POWER_SOURCES.md`.

The power log measures and shows. It does not save power. No power mode, clock, governor, fan or display setting was
changed. No model, camera or sender was stopped to test a saving (rule W1).

## 1. Summary

| Task | State | Proof |
|---|---|---|
| Q0 Read, sensors, baseline | DONE | Sensors: section 2. Baseline window 00:39:45-00:41:49 (section 5). The first window (00:29:55) did not measure rk-agxlink: the owner had moved it to the system unit `rk-agxlink.service` at 23:34. |
| Q1 AGX02: sources, log, page | DONE | `tegrastats` and the log at the same second: 30 of 30 seconds have a log sample; total difference +0.44 W mean, 1.04 W mean of the absolute values (4.3 %). 60 samples in the first 60 s. agx-dashboard CPU 6.29 % before, 6.46 % after (+0.17 % of one core). Live page: section 4. |
| Q2 DA01: sources, log, Power page | DONE | AGX02 26.29 W `SENSOR` on the rk console (second instance, port 8702). DA01 `NO SENSOR`. A manual reading of 39 W for DA01 shows `MANUAL` with its time (01:27:51) and the System total (25.38 W) has only AGX02 and names DA01 as missing. Section 4. |
| Q3 Before and after, no change of the system | DONE | Unit tests with stored samples (3 suites) and a replay of real data: the AGX power history of the last 24 h and the 10 model changes in the AGX audit log. Section 6. |
| Q4 Report, commit | DONE | This report. Commits: one in each repository, title "Power log in the two dashboards". Not pushed. |

End state (check 01:57:14): the link is UP with DA01 and AGX02 (unit `agx02`, active and last good); YOLOPX 41.8
results/s (6 cameras) and DTCP 10.2/s; stale 0, rejected 0. The second rk console (port 8702) is stopped. The AGX02
power log runs in agx-dashboard. The DA01 power log starts when the owner restarts rk-console (section 9).

## 2. What each machine can measure

| Machine | Source | Label | What it measures | What it does not measure |
|---|---|---|---|---|
| AGX02 | `jetson_rails` | `SENSOR` | The four INA3221 rails of the module: VDD_GPU_SOC, VDD_CPU_CV, VIN_SYS_5V0 (`/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon3`), VDDQ_VDD2_1V8AO (`1-0041/hwmon/hwmon4`). Total = sum of the rails, about 22-34 W tonight. | The supply input of the carrier board: there is no VDD_IN rail. The owner meter reads about 60 W at the input. The ratio meter / sensor was 2.28 (60 W / 26.29 W). Set the correction factor on the Power page. |
| DA01 | `hwmon` | `NO SENSOR` | Nothing. | The supply input. Found: hwmon0-6 are temperatures, hwmon8 is the fan. hwmon7 and `/sys/class/power_supply/tcpm-source-psy-5-004e` are the USB-C port (chip husb311, i2c-5 0x4e) that GIVES power to the screen (power role "source"): online 0, 0 V, 0 A. `vcc12v_dcin` is a fixed regulator value (12 V), not a measurement. The SARADC (`iio:device0`) has one user, `adc-keys` (buttons). |
| Router, screen, other | `manual` | `MANUAL` | The meter readings that the owner types. | No sensor. |

`tegrastats` shows 3 of the 4 rails (not VDDQ_VDD2_1V8AO). The log reads the same sysfs files once a second.

The AGX power mode (nvpmodel, "MAXN") is read each 30 s. A power mode event can be up to 30 s late.

## 3. What was made

### AGX02 (driveragent-agx)

- `common/powerlog.py` (same file as DA01 `rk/common/powerlog.py`): the SQLite log. 1 s rows for the last hour, 10 s
  rows (mean, minimum, maximum, number of samples) for 30 days, one row per day for one year (Wh, mean, minimum,
  maximum, hours with data). Energy only where samples exist: one 1 s sample stands for one second; a time without
  samples is a gap, not zero. Events, before and after (60 s), manual readings, settings, CSV export.
- `common/power_sources.py`: `JetsonRails` (1.2 ms CPU for one read).
- `dashboard/power_log.py`: the logger in agx-dashboard. It uses the 1 s health snapshot (the rails are read once,
  by the health thread). The SQLite work is in its own thread. Events: model set, link, cameras with frames, power
  mode, control mode. A new value must stay 3 s before it makes an event; the first state waits 5 s after a start.
- `dashboard/power_api.py`: `GET /api/power`, `/api/power/samples`, `/api/power/events`, `/api/power/energy`,
  `/api/power/export` (Basic) and `/api/power/now` (also with a board token, for the rk console).
- System page, card "Power log": value with its label, rails, power mode, chart 1 h / 24 h / 7 d / 30 d with the
  events as dashed lines, before and after table, energy table, CSV links, log size.
- Status message v3 (`proto/agx_infer.capnp` fields @20-@24: powerTotalW, powerRails, powerLabel, powerWhat,
  powerMode). The setting `status: schema_version` in `config/infer.yaml` is 2 now (section 8). agx-infer reads it
  again when the file changes (no restart).
- Log file `data/power.sqlite` (mode 600). Size limit: section 7.

### DA01 (driveragent)

- `rk/common/powerlog.py` (core, see above).
- `rk/console/rkconsole/power.py`: sources `agx_status` (the AGX power from the status message, when rk-agxlink gives
  it), `agx_http` (`GET /api/power/now` with the board token, sent by the console server, at most once a second; used
  only while the status message has no power fields), `hwmon` (only the channels in `[console.power] hwmon`), `manual`;
  the logger (one writer: a file lock; a second console opens the log read-only); the event state each second (model
  set, sender, link, active AGX unit, cameras that give frames, recording from the RecorderStatus of rk-recorder, AGX
  power mode, control mode).
- Routes `GET /api/v1/power`, `/samples`, `/events`, `/energy`, `/manual`, `/export`; `POST /api/v1/power/manual` and
  `/settings` (login, CSRF, confirm, audit `power.manual.add`, `power.settings`).
- Page **Power**: Now (one card per part and "System total"), chart, before and after, energy, manual reading,
  settings (correction factor per sensor part, battery capacity; "time on a full battery" with the label `ESTIMATE`),
  export. Overview "Battery" tile: line "Power now".
- rk-agxlink accepts the status v1, v2 and v3 and puts the power fields in the status file
  (`rk/agxlink/agxlink_core.py`, `rk_agxlink.py`, schema copy byte-identical to the AGX file). It is on disk; the
  running rk-agxlink uses it after its next start (section 8).
- Log file: `/mnt/nvme/driveragent/console/power.sqlite` (made by the rk console at its next start).

One change outside the plan: when the constant `schemaVersion` changes from 2 to 3, the calculated hash of
RkCameraInfo also changes (0x743CFFAD to 0x506A649C), although the struct is the same. The cause is the hash rule: it
starts at the first text "struct RkCameraInfo", which is in a header comment. Repair: DA01 always sends the old value;
the AGX accepts the two values. This works in each restart order. Tested: section 6.

## 4. Live checks

AGX02 dashboard, System page, card "Power log" (01:25 CST, after the agx-dashboard restart): 26.9 W `SENSOR`, the
4 rails, power mode MAXN, sample age 0.3 s, state (model set, link UP, 6 cameras, bench), chart with the agx-infer
restart dip at 01:20, energy "2.2 Wh, 0.1 h with data of 18.4 h" (today). No browser error. Phone width: no
horizontal scroll.

rk console, second instance (port 8702, rule M11; the real console runs the old code until the owner restarts it):

```
01:27:47  da01   NO SENSOR  watts None
          agx02  SENSOR     watts 26.29 corrected 26.29 factor 1.0 via 'AGX dashboard (HTTP)' age 1.6
          total  {'sensor_w': 26.29, 'parts': ['agx02'], 'missing': ['da01', 'router', 'screen', 'other'], 'label': 'SENSOR'}
          state  {'models': ['driverguard_dtcp@1', 'driverguard_yolopx@1'], 'sender': True, 'link': 'UP',
                  'agx_unit': 'agx02', 'cameras': 6, 'recording': False, 'power_mode': 'MAXN', 'control_mode': 'bench'}
POST manual da01 39 W -> 200 {"id":1, "part":"da01", "watts":39.0, "label":"MANUAL", "sensor_w":null}
01:27:54  da01   NO SENSOR  watts None | manual 39.0 W at 01:27:51 label MANUAL
          agx02  SENSOR     watts 25.38
          total  {'sensor_w': 25.38, 'parts': ['agx02'], 'missing': ['da01', 'router', 'screen', 'other']}
POST manual agx02 60 W -> 200 {"sensor_w": 26.29, "label": "MANUAL", "ratio": 2.282}
```

The browser check of the page (desk 1280x800 and phone 390x844): no console error; the labels `SENSOR`, `MANUAL`,
`NO SENSOR` show; the DA01 card shows "Meter reading 39.0 W at 01:27, 27 s ago. A past reading: it is not the
present value and it is not in the total."; the Overview "Battery" tile shows "POWER NOW 23.1 W SENSOR".

The test log of the second instance is in the scratch folder. It is not the owner's log.

## 5. Numbers before and after (rule D1)

Baseline (00:39:45-00:41:49) and end (01:54:11-01:56:15, the second console on 8702 still ran). Same tools as in
the earlier tasks.

| Item | Baseline | End |
|---|---|---|
| DA01 CPU busy %; MemAvailable MB | 21.1; 5726 | 20.8; 5709 |
| rk-camd CPU %; cam0 frames/s; sequence gaps (6 cameras) | 1.3; 30.00; 0 | 1.3; 30.00; 0 |
| rk-camd consumer drops (6 streams, 120 s) | 192 | 59 |
| rk-recorder CPU %; rk-hmi CPU % | 19.7; 10.2 | 19.5; 9.9 |
| HMI frames/s mean (lowest); frame p99 ms | 20.5 (19.8); 83.4 | 20.2 (19.8); 83.4 |
| rk-console (8701, old code) CPU %; RSS MB | 3.2; 55.5 | 2.6; 57.8 |
| Second rk console (8702, new code with the power log) CPU % | - | 1.45 |
| rk-agxlink CPU %; RSS MB | 15.0; 39.9 | 14.7; 42.0 |
| Link results received / stale / rejected (120 s) | 6386 / 0 / 0 | 6088 / 0 / 0 |
| YOLOPX results/s per camera; capture to result p50 / p95 ms | 7.16-7.17; 110-120 / 139-155 | 6.83; 112-121 / 141-154 |
| DTCP results/s; p50 / p95 ms | 10.00; 66 / 103 | 10.00; 71 / 82 |
| AGX02 YOLOPX frames/s (internal status); results/s; GPU GR3D % | 42.4; 52.4; 55.2 | 41.6; 51.6; 60.6 |
| AGX02 agx-dashboard CPU % (separate 120 s windows) | 6.29 | 6.46 |

The YOLOPX rate is set by the AGX GPU (GR3D 55-61 %). The end value 6.83 is in the range of the earlier tasks
(6.72-7.0); the baseline 7.17 was the highest. agx-infer was restarted at 01:20 and its status code (v2 mode) adds no
work. The AGX window tool (`tests/out/j0/j0_measure.py`, not in git) now computes the v3 hash from the schema file, so
it counted 0 status messages on 5561 in the end window: a tool limit. rk-agxlink got each status message (link UP,
rejected 0).

## 6. Tests

| Suite | Command | Result |
|---|---|---|
| Core (DA01) | `python3 rk/common/tests/test_powerlog.py` | `OK 9 tests` |
| AGX02 full suite | `PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/` | `307 passed, 1 warning in 161.10s` |
| AGX02 after the last format change of the core | `... pytest tests/test_powerlog.py tests/test_power_api.py` | `30 passed, 1 warning in 3.35s` |
| DA01 console | `cd rk/console && .venv/bin/python -m pytest -q -p no:cacheprovider` | `292 passed, 6 skipped in 282.78s` |
| DA01 console UI (Playwright, new build) | `pytest -m ui tests/` (with `DA_UI_DIST`) | `5 passed`; `tests/test_ui_power.py` `1 passed`; the main e2e test against the new build `1 passed` |
| DA01 rk-agxlink | `rk/hmi/.venv/bin/python rk/agxlink/tests/test_agxlink.py` | `test_agxlink: 31 tests passed` |
| DA01 full suite (`da01_suite.sh`, 30 steps) | | 28 PASS; `router` FAIL (a time-out, the known failure from before this task); `ruff` FAIL (import order and 2 long lines in new code), repaired after the run: `ruff check` gives `All checks passed!` |

Cross-check of the status message v3: a v3 frame made by the AGX publisher (real INA3221 reads, `nvpmodel -q`) was
decoded on DA01 by `check_envelope` + `status_fields`: schemaVersion 3, powerTotalW 30.0, powerLabel "SENSOR",
powerMode "MAXN", 4 rails. The running rk-agxlink got the v2-mode status of the new agx-infer with rejected 0.

Q3 replay of real data (AGX02, `tests/out/q3_replay.py`; a temporary log; nothing on the machine changed). Samples:
the 8180 power 10 s means of agx-dashboard history (24 h). Events: the 10 model changes with result "ok" in the AGX
audit log. Check: the plain SQL mean of the same history rows.

| Time (BST) | Event | Before W | After W | Difference W | Plain mean before / after | Notes |
|---|---|---|---|---|---|---|
| 11:12:59 | deactivate driverguard_dtcp@1 | 24.15 | 22.42 | -1.74 | 24.29 / 22.47 | |
| 11:16:40 | activate driverguard_dtcp@1 | 22.47 | 23.76 | +1.28 | 22.47 / 23.76 | |
| 11:39:57 | activate driverguard_yolopx@2 | 26.53 | 45.56 | +19.03 | 26.53 / 45.56 | |
| 11:43:56 | deactivate driverguard_yolopx@2 | 44.53 | 27.56 | -16.96 | 44.53 / 27.56 | |
| 12:47:00 | deactivate driverguard_dtcp@1 | 23.05 | 22.53 | -0.52 | 23.05 / 22.53 | 1 other event in the windows |
| 12:47:41 | activate driverguard_dtcp@1 | 22.25 | 23.14 | +0.89 | 22.25 / 23.14 | 1 other event in the windows |
| 12:49:46 | activate driverguard_yolopx@2 | 23.46 | 38.13 | +14.67 | 23.46 / 38.13 | |
| 12:52:10 | deactivate driverguard_yolopx@2 | 42.19 | 27.78 | -14.40 | 42.19 / 27.78 | |
| 15:53:58 | deactivate driverguard_dtcp@1 | 23.38 | 22.65 | -0.73 | 23.38 / 22.65 | 1 other event in the windows |
| 15:54:35 | activate driverguard_dtcp@1 | 22.66 | 23.21 | +0.55 | 22.66 / 23.22 | 1 other event in the windows |

The first row differs from the plain mean by 0.14 W: the log aligns the 10 s rows to the 10 s grid, so it used 6 rows
and the plain query 5. These are module rail values (not corrected).

Q1 `tegrastats` against the log at the same second (AGX02 18:21:38-18:22:08 BST, `tests/out/q1_tegra.py`):

| Item | Result |
|---|---|
| Seconds | tegrastats 30, with a log sample 30, without 0 |
| Total: log - (tegrastats 3 rails + log VDDQ_VDD2_1V8AO) | mean +0.436 W, mean of absolute values 1.041 W (4.31 % of the total), max 3.103 W |
| VDD_GPU_SOC | mean +0.387 W, max 2.400 W |
| VDD_CPU_CV | mean -0.026 W, max 0.401 W |
| VIN_SYS_5V0 | mean +0.075 W, max 0.304 W |

The two tools read the sensors at different times in the same second. VDD_GPU_SOC changes fast with the GPU load; the
slow rails agree within 0.1 W.

Rule W3 (load of the power log):

| Item | Result |
|---|---|
| Samples | one each second (1 s rows), written in one transaction each 10 s |
| AGX02 agx-dashboard CPU (120 s windows, the page not open) | 6.29 % before, 6.46 % after: +0.17 % of one core |
| AGX02 logger work (bench, 3600 s) | 0.31 ms CPU each second (0.03 % of one core); the sensor read is in the existing health thread |
| AGX02 page reads, only while the System page is open | about 0.2-0.4 % of one core (reviewer bench with 30 days of data) |
| DA01 power collector (bench, 1200 ticks) | 0.142 ms CPU each second (0.014 % of one core) |
| agx-infer, status v3 mode (not on now) | one rail read each second: 1.2 ms CPU (0.12 % of one core) |

## 7. Log size

One series = one part or one rail. AGX02 has 5 series (total and 4 rails). DA01 has one series for each part with a
sensor (now only AGX02).

| Table | Limit | Size of one row |
|---|---|---|
| 1 s rows | 1 h + 5 min: 3900 rows per series | about 20 bytes |
| 10 s rows | 30 days: 259 200 rows per series | about 30 bytes |
| Day rows | 366 per series | about 60 bytes |
| Events | one year | about 100 bytes |
| Manual readings | 5000 | about 300 bytes |

Upper limit: about 9 MB per series (30 days of 10 s rows with the primary key), so about 45 MB on AGX02 and about
10 MB on DA01 with the present series. The old rows are removed each hour. After the first hour on AGX02 the file was
0.8 MB.

## 8. Restarts and stops (rule W4, rule M9)

| Time (CST) | Machine | What | Effect |
|---|---|---|---|
| 01:19:42 | AGX02 | agx-dashboard restart (power log, API, System page) | Not in the result path |
| 01:20:17 | AGX02 | agx-infer restart, the one restart of this task (status publisher with v3 support, in v2 mode) | No results 6.41 s (01:20:17.083-01:20:23.494); link DOWN at 01:20:20.5 ("no AgxInferStatus for 3.9 s"), UP at 01:20:24.5; rejected 0; sender restarts 0 |
| 01:26:44 | DA01 | second rk console started on port 8702 (transient user unit `rk-console-pw`; a test instance, not an rk-* unit); restarted at 01:27:39 with the real token folder | None on the capture, the HMI or the recorder |
| 01:57:14 | DA01 | second rk console stopped | None |

No rk-* unit of DA01 was restarted. rk-console and rk-agxlink are system units now (the owner installed them at
23:33-23:34); my sudo rules do not include them.

## 9. Owner steps

Do these steps in this order.

1. Load the new rk console (Power page, Overview "Power now", the power log on DA01). The capture, the HMI and the
   recorder continue.
   ```
   cd ~/driveragent && rk/console/build.sh && sudo systemctl restart rk-console
   ```
   The console then makes `/mnt/nvme/driveragent/console/power.sqlite` and logs one sample each second. Until then,
   DA01 logs nothing.
2. Optional: let the AGX send its power in the status message (v3). The rk console uses the HTTP path until then;
   the values are the same.
   1. On DA01 first: `sudo systemctl restart rk-agxlink` (the running rk-agxlink refuses a v3 message and the link goes
      DOWN). Measured before for a restart of the link service: no results about 0.9 s, link UP again after about
      6 s.
   2. Then on AGX02: in `~/driveragent-agx/config/infer.yaml` set `status:` `schema_version: 3`. agx-infer reads the
      change in about 1 s. It needs no restart.
   3. Check: the Power page shows "Via: status message" for AGX02.
   To go back: set `schema_version: 2`.
3. Set the correction factor of AGX02 on the Power page (Settings). Type a meter reading for AGX02 first: the list
   shows the ratio meter / sensor (tonight 2.28 with 60 W). Optional: type the battery capacity in Wh.
4. Push:
   ```
   cd ~/driveragent && git push origin main
   cd ~/driveragent-agx && git push
   ```

## 10. Limits and observations

- DA01 has no power sensor. Its card shows `NO SENSOR` and the meter reading with its time. To measure DA01, fit a
  sensor on the supply input (I2C with a kernel driver, or a meter with an interface): `docs/POWER_SOURCES.md`.
- The AGX02 value is the sum of the module rails, not the supply input. The corrected value uses one factor for all
  loads; the ratio can change with the load.
- The before and after table shows the change of the measured parts only. A change of DA01 power (for example the
  screen off) is not visible until DA01 has a sensor.
- An event that lasts less than 3 s makes no event on AGX02 (hold time). The agx-infer restart at 01:20 (link DOWN
  4 s) made no AGX event because the "link" value of the AGX dashboard changed for less than 3 s.
- A change that happens while a log does not run gets an event with "the time is not exact" at the next start.
- The AGX dashboard shows the version of agx-infer as "fc8f955-dirty" until the next agx-infer restart (the code was
  started before the commit).
- The before and after values with a factor: the energy and the differences on the rk console use the factor of now
  for the whole period.
- Phone width (390 px): the page width is 413 px on the Power page and 414 px on the System page (not changed by this
  task). The cause is the bottom navigation bar; no element of the page itself is wider than the screen.
- The HMI frame rate has two levels after a start (about 21 and 32-46 frames/s; see the earlier report). Compare the
  D1 HMI values with this in mind.
