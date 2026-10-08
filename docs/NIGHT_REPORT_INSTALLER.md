# Night report: AGX installer, cleanup preparation, long run (2026-10-08)

This report is the same in the two repositories (driveragent on DA01, driveragent-agx on AGX02).
Times: DA01 is CST, AGX02 is BST (CST - 7 h). The task started at 03:20:14 CST and the limit was 13:20 CST.

Git at the start: DA01 `main` 50e4290 and AGX02 `main` 970d5ac were equal to `origin/main` (0 ahead, 0 behind after
`git fetch`). GitHub `main` (970d5ac) does not have the installer. Thus the installer test used the LOCAL commit of
AGX02 (Section 3). Nothing was pushed.

## 1. Summary

| Part | State | Proof |
|---|---|---|
| A1 Machine data out of the software | DONE | Section 2 table. Full suite on AGX02 328 passed (live config); a copy with only `config/templates/` passed (304 passed, 3 skipped, GPU files deselected). Effective config of AGX02 before/after: same values (Section 2.3). |
| A2 Scripts in `ops/` | DONE | `ops/preflight.sh`, `install.sh`, `doctor.sh`, `uninstall.sh`, `export_model.sh`; test results in Section 3. |
| A3 Start at boot | DONE (document only) | `docs/INSTALL_AGX.md` Section 7: two methods with owner commands, recommendation: user units + linger. Not done on AGX02 (sudo; Section 7 of this report). |
| A4.1 Test installation (fresh clone, preflight, install, password, doctor, second run) | DONE | Section 3.1 to 3.4. |
| A4.2 Short model test (export, deploy, build, activate with the simulator, 1 min results, deactivate) | DONE | Section 3.5: dtcp@1 built in 77 s, 600 results in 60 s. GPU time about 2 min 50 s (limit 10 min). |
| A4.3 Uninstall and live check | DONE | Section 3.6: nothing of the test installation stays; live PIDs, link and results/s the same. |
| A4.4 Install on TARGET_SSH | NOT DONE | `TARGET_SSH` was not filled in (the value was the placeholder "<fill in, or "none">"). No second unit was available. |
| A4.5 `docs/INSTALL_AGX.md` | DONE | 13 sections, from an empty Jetson to "paired and one model active". |
| A1 proof on the running AGX02 processes | PARTIAL | The new code is on disk and tested with the live config. The running agx-infer and agx-dashboard were NOT restarted (rule X1; the restart was also refused by the tool permission check). They run the code of 970d5ac from memory until the owner restarts them (Section 7, step 2). |
| B Cleanup preparation | DONE | Audit with root found. `docs/CLEANUP_PROPOSAL.md` (55 rows), `ops/cleanup/stage{1,2,3}_*.sh`. No script and no command of them was run. Section 5. |
| C Long run | DONE | 8.0 h (04:19-12:20 CST), 2888 samples per machine, no gap. STABLE: link UP for the full run, no restart, 0 rejected, 0 stale, no trend (Section 6). |

Commits (not pushed):

| Repo | Commit | Content |
|---|---|---|
| AGX02 driveragent-agx | eb391fd | Part A: installer, machine data out of the repository |
| AGX02 driveragent-agx | e07cfe4 | Part B: cleanup proposal and stage scripts |
| AGX02 driveragent-agx | fda22bd | INSTALL_AGX corrections from the test |
| AGX02 driveragent-agx | (last) | this report |
| DA01 driveragent | (last) | this report |

Test suites at the end:

| Suite | Command | Result |
|---|---|---|
| AGX02 full suite (with GPU tests) | `cd ~/driveragent-agx && .venv/bin/python -m pytest -q -p no:cacheprovider tests` | `328 passed, 1 warning in 161.50s` (12:3x CST, before the report commit; the same at each commit tonight) |
| DA01 full suite (`da01_suite.sh`, 29 steps) | 12:25-12:47 CST | 28 PASS, 1 FAIL: `router` (subprocess.TimeoutExpired: the known failure from before these tasks). Console: `293 passed, 5 skipped in 296.58s`. The DA01 repository has only this report as a change. |

End state (12:25:40 CST): link UP, AGX02 active, sender ON, yolopx@1 7.0-7.2 results/s per camera, dtcp@1 10.0/s,
rejected 0, stale 0; agx-infer PID 387147 and agx-dashboard PID 386946 (NRestarts 0, the same as at the start).

## 2. Values that were true only for AGX02 (A1)

### 2.1 What I found and what I did

Line numbers are of 970d5ac.

| File : line | Value | What I did |
|---|---|---|
| `config/{infer,dashboard,sources,models,control,sim}.yaml` | all machine data | `git mv` to `config/templates/` with generic defaults. `/config/*.yaml` is in `.gitignore`. `ops/install.sh` makes `config/*.yaml`. The AGX02 files stay on AGX02 (not tracked any more). |
| `config/dashboard.yaml:17` | `10.0.0.0/24` (eno1 LAN of AGX02) | Not in the template. `install.sh` adds the private IPv4 subnets of the unit. |
| `config/dashboard.yaml:60` | `scan_dirs: [/home/tonyho/model]` | Template `[]`. |
| `config/dashboard.yaml:32` | `infer_status_endpoint` 5562 | Template `null`: the value comes from the infer ports. |
| `config/dashboard.yaml:67-68` | `agx-*` unit lists | Template `null` + new key `unit_prefix: agx`. |
| `config/dashboard.yaml:76-93` | `old_units` from the AGX02 audit | Template `[docker.service, nvpmodel.service, ssh.service]`; new key `old_stack_root: null`. |
| `config/models.yaml:21,22,36,37,58` | old engines and ONNX in `/home/tonyho/model` | Template `models: []`. The AGX02 list stays in the AGX02 file. The manifests that point to the old engines are in the model store `~/agx-models/<name>/<version>/manifest.yaml` (machine data, not in git). |
| `config/sources.yaml:9,58,63` | DA01, 10.0.0.130 | Generic text; new key `base_port: 6000`. |
| `config/sources.yaml:132-183` | `role_rk` of DA01, ports, recordings in `/home/tonyho/driveragent/logger/video` | Generic roles, no `role_rk`, ports from `base_port`, `files: []`. |
| `config/sim.yaml:110,113-175` | `video_root` and session sets of AGX02 | `video_root: ""`, `session_sets: {}`, all cameras `test-pattern`. |
| `config/infer.yaml:17,34` | "DA01" in comments | "RK board"; new key `protected_dirs: []`. |
| `dashboard/config.py:19`, `dashboard/auth.py:41` | `10.0.0.0/24` in the default allow list | Removed (default = template list). |
| `dashboard/config.py:29` | `tcp://127.0.0.1:5562` | Default `null` = `127.0.0.1:<ports.internal of infer_config>`, fallback 5562. |
| `controller/control.py:459` | `tcp://127.0.0.1:5563` | `127.0.0.1:<ports.admin of infer_config>`, fallback 5563. |
| `dashboard/config.py:46`, `tools/inspect_engines.py:20` | scan `/home/tonyho/model` | Default `[]`. `inspect_engines` without an argument stops with "give ENGINE or --scan". |
| `dashboard/config.py:52-53` | `agx-dashboard`, `agx-infer`, `agx-sim` | `<unit_prefix>-dashboard` etc. (default prefix `agx`). |
| `dashboard/auth.py:35` | realm `agx02-dashboard` | `<node_name>-dashboard`. |
| `dashboard/app.py:268`, `main.py:50`, `static/index.html`, `static/app.js` | "agx02" titles and fallbacks | `<node_name> dashboard`; the page uses `node_name` from `/api/health` (new field); neutral text "this AGX". |
| `dashboard/power_api.py:22,128`, `power_log.py:37`, `common/power_sources.py:33`, `static/app.js` power part | part `agx02` | Part = `node_name` (default: the short host name, on AGX02 `agx02`). The API answers have a field `part`. |
| `dashboard/mqtt_pub.py:36` | node `agx02` | `node_name`. |
| `dashboard/collectors/old_procs.py:10` | `/home/tonyho/driveragent` (old stack) | New key `old_stack_root` (default `null`: the view is empty with the reason "not configured"). |
| `infer/models/manager.py:46`, `controller/builder.py:22` | protected folder `/home/tonyho/model` | New key `protected_dirs` (infer.yaml and dashboard.yaml; default `[]`). The check now uses the real path (the old prefix test also matched `/home/tonyho/models...`). |
| `tools/register_existing_models.py:30-32` | absolute AGX02 paths | Relative names below a new required option `--root`. |
| `tools/deploy_model.sh:22,50` | default host `agx02` | `--host` or `$AGX_HOST`; no host = local deploy. |
| `tools/rk_result_client/__main__.py:57-58` | `/home/tonyho/driveragent-agx/...` | Relative to the repository of the file. |
| `tools/svc.sh:14,46` | unit prefix `agx-` | `$AGX_UNIT_PREFIX` (default `agx`; AGX02 transient units are the same). |
| `tools/model_check.py:31` | `~/agx-models/_testframes/...` | `<store in use>/_testframes/front_1280x720.jpg`; the controller gives the path. |
| `infer/ingest/ingest.py:280`, `dashboard/pairing_api.py:57` | port `6000 + cam` | Camera `port`, else `base_port + cam`. |
| `infer/models/legacy/driverguard/run_driverguard.py:19-20` | `/home/tonyho/...` roots | Environment variables (default empty); marked "reference code, not run". |
| `systemd/agx-*.service`, `systemd/install_units.sh` | `User=tonyho`, `/home/tonyho/driveragent-agx` | Removed. Unit templates in `ops/units/` (user units) and `ops/units/system/` (system units); `install.sh` fills in the user, the folder and the Python path. |
| `requirements-venv.txt` | packages from the user site of tonyho (`~/.local`) | `requirements/agx-venv.txt` and `requirements/agx-torch.txt` with fixed versions; installed INTO the venv. The units set `PYTHONNOUSERSITE=1`. |
| Kept (protocol constants, defaults, comments) | FrameLink base port 6000, envelope type ids 5560/5561/5564, default ports 5560-5564 and 8700, the migration board id `rk3588-da01` (used only when the old `data/control.token` exists), DA01 part names of the power log, comments and examples | No change: these are not machine data, or the installed value comes from the configuration. |

### 2.2 Keys added to the AGX02 files (so that AGX02 operates the same)

A copy of the AGX02 files before the change is in `agx02:~/agx-night-dev/live-config-backup-210256/` (with md5 sums).

- `config/dashboard.yaml`: `node_name: agx02`, `protected_dirs: [/home/tonyho/model]`, `old_stack_root: /home/tonyho/driveragent`.
- `config/infer.yaml`: `protected_dirs: [/home/tonyho/model]`. (agx-infer reads this file again when it changes; only the
  status settings are read again. No effect on the running process.)

### 2.3 Proof that AGX02 operates the same

- Effective configuration (old code + old files compared with new code + files with the new keys): the same values for the dashboard port 8700, allow list, model store `~/agx-models`, infer ports 5560-5564, realm `agx02-dashboard`, status endpoint 127.0.0.1:5562, admin endpoint 127.0.0.1:5563, unit lists, 14 old units, `old_stack_root`, scan dirs, protected dirs, camera ports 6000-6005, pairing ports. Only the format of the node name changed (`(none)` -> `agx02`).
- Full suite in `~/driveragent-agx` with the live config and the GPU tests: `328 passed, 1 warning in 162.94s`
  (before the task: 307 passed; 21 new tests).
- Not proved: the running processes. See Section 1 ("PARTIAL") and Section 7 step 2.

## 3. Installer test (A4)

### 3.1 Test installation

- Folder `~/agx-installtest/driveragent-agx`: `git clone git@github.com:osmosishk/driveragent-agx.git` (GitHub `main` =
  970d5ac), then `git fetch ~/driveragent-agx main` and `git reset --hard` to the local commit e07cfe4.
- Instance `agxtest`, units `agxtest-dashboard` and `agxtest-infer`, store `~/agx-installtest/models`, dashboard port 8710,
  ZMQ 5570-5574, FrameLink UDP 6010-6015 (mode `sim`, bound to 127.0.0.1). The live ports 8700, 5560-5564 and
  6000-6005 and the store `~/agx-models` were not used (rule X4).

### 3.2 Preflight and install

- `ops/preflight.sh --dash-port 8710 --zmq-base 5570 --video-base 6010`: all necessary items PASS, exit 0
  (Jetson AGX Orin, L4T R36.4.7 / JetPack 6.2.1+b38, TensorRT 10.3.0, Python 3.10.12, venv, cv2/gi/yaml/psutil,
  nvv4l2decoder, 279 GiB free, MemAvailable 49 GiB, ports free, time, systemd --user; INFO: linger is off).
- With the default ports, preflight gives FAIL for the three port items (the live system holds them) and exit 1. This
  is the correct result.
- `ops/install.sh --instance agxtest ... --mode sim --yes`: exit 0 in 63 s (preflight 2 s, venv 4 s, pip 51 s, config
  1 s, units 4 s). The pip step used the pip cache: the first download of torch 2.8.0 (226 MB, Jetson index) was in
  the helper test before (pip 71 s). The venv is 1015 MB and has torch 2.8.0 (CUDA 12.6) and numpy 1.26.4 inside;
  tensorrt and cv2 come from JetPack.
- The install printed the dashboard addresses (127.0.0.1, 10.0.0.130, 100.64.0.20 port 8710), the path of the password
  file (`.env`, mode 600) and the owner step `sudo loginctl enable-linger tonyho`. It did not activate a model.

### 3.3 Password and doctor

- Test dashboard with its own password: `200` on `/api/health`. With the live password: `401`. The test password on the
  live dashboard: `401`. Without a password: `401`. `.env` mode 600, `data/` mode 700.
- `ops/doctor.sh --instance agxtest --before-pairing`: `DOCTOR PASSED`, exit 0. Items: units PASS, dashboard PASS,
  agx-infer status PASS (state ERROR "no model is enabled": correct for a unit without a model), store PASS, INA3221
  PASS (4 rails), thermal PASS, pairing/link INFO (no board). WARN: no test frame in the new store.
- Without `--before-pairing`: exit 1 (no paired board). This is the correct result.

### 3.4 Second run

`ops/install.sh` again with the same options: exit 0 in 11 s. It printed `KEPT` for `.venv`, the six `config/*.yaml`,
`.env`, `data`, `logs`, `engines`, the store and the two unit files. md5 of the six config files and `.env`, the list
of the store and the unit PIDs: unchanged. Only the install record changed (it records the second run).

### 3.5 Model test (rule X5)

| Time (BST) | Step | GPU |
|---|---|---|
| 21:11:31 | `ops/export_model.sh driverguard_dtcp 1 --store ~/agx-models` (read-only) -> package with `manifest.yaml` + `dtcp_v1.onnx` (93 MB, sha256 checked); test frame copied into the test store | no |
| 21:11:31 | `tools/deploy_model.sh <package> --local --store ~/agx-installtest/models` -> NEEDS BUILD | no |
| 21:11:45 - 21:13:17 | build in the test dashboard (`POST /api/models/driverguard_dtcp/1/build`): trtexec 77.3 s, state READY | yes |
| 21:13:26 | simulator `tools.rk_sim --cams 0 --base-port 6010` (test pattern, H.265 by NVENC) | encoder |
| 21:13:38 - 21:13:44 | activate on camera 0 -> ACTIVE (with the inference check) | yes |
| 21:13:48 - 21:14:48 | `tools.rk_result_client --results-port 5570 --status-port 5571 --seconds 60`: 600 results, 10.0 Hz, all with the SIMULATED flag; agx_ms p50/p95/p99 58.6/64.9/67.4; 0 rejects, 0 duplicates, 0 sequence gaps; all checks PASS | yes |
| 21:14:54 | deactivate -> READY | - |
| 21:15:00 | simulator stopped (by its PID) | - |

GPU time of the test installation: about 2 min 50 s in total (limit 10 min). It was before Part C. The live results
during the build: dtcp 10.0/s, yolopx 6.8 to 9.0/s per camera (normal range).

Models of AGX02 and the export:

| Model | Export | Reason |
|---|---|---|
| driverguard_yolopx@1 | yes (ONNX 126 MB) | a new unit builds it (NEEDS BUILD) |
| driverguard_yolopx@2 | yes (ONNX 126 MB) | `--with-engine` also copies the engine (same device type and TensorRT only) |
| driverguard_dtcp@1 | yes (ONNX 93 MB) | tested tonight (Section 3.5) |
| sparsedrive_convnext_orin@1 | yes, but no use | the package has an ONNX file, but there is no adapter (state NO ADAPTER): a new unit cannot run it |
| system1@1 | NO | no ONNX file: the model is PyTorch only (`system1_deploy.pth`). A new unit cannot build it. |

### 3.6 Uninstall and the live system

- `ops/uninstall.sh --instance agxtest --purge --yes`: it printed the list first, then removed the two units (stop,
  disable, files), `.venv` (1015 MB), the six config files, `.env`, `data/`, `logs/`, `engines/`, the test store and
  the empty `~/.config/systemd` folders. Exit 0.
- After: `Unit agxtest-infer.service could not be found`, 0 `agxtest*` units, no `~/.config/systemd`, test ports free,
  no test process. Only the git clone stayed (with `__pycache__` made by Python); I removed the folder
  `~/agx-installtest` (rule X2).
- Live system before (03:29 CST) and after (04:15 CST): agx-infer PID 387147 and agx-dashboard PID 386946, NRestarts 0
  (same); ports 5560-5564, 8700, 6000-6005 (same); link UP; yolopx@1 6.8-7.8 results/s per camera before and 7.6-7.8
  after; dtcp@1 10.0/s; rejected 0; stale 0.
- Left on AGX02 from the tests: the pip cache grew from 33 MB to 313 MB (`~/.cache/pip`, torch wheel). The owner can
  remove it with `python3 -m pip cache purge`.

## 4. Models that cannot be exported

- `system1@1`: no ONNX file (PyTorch weights `system1_deploy.pth` only). A new unit cannot build it.
- `sparsedrive_convnext_orin@1`: it exports, but it has no adapter and its output was wrong before
  (`docs/MODELS.md`). A new unit cannot run it.

## 5. Part B result

The audit with root exists: `agx02:~/agx_audit_agx02_20261007_201209/report.md`, line 30
`audit run  : 2026-10-07T20:12:09+01:00 as root (root=1)`. Its Section 0 (Flags) has no flag "Run without root".
Thus Part B was done. Nothing was cleaned: no cleanup script and no command of them was run on AGX02 (also no dry
run there). The dry runs were done only on DA01 in a fake folder with stub commands.

Made (in the AGX repository, commit e07cfe4):

- `docs/CLEANUP_PROPOSAL.md`: one main table with 55 rows (item, type, size or memory, what uses it, proposal, command,
  how to undo). Counted from the table: SAVE FIRST 10 rows at the top (then KEEP 3, MOVE 6, DELETE 1), KEEP 19
  (one of them "KEEP now; DISABLE after row 44"), DISABLE 16, MOVE (then DELETE) 3, DELETE 7. Items of the new installation are KEEP: `~/driveragent-agx`, `~/agx-models`, the
  7 old model files that the manifests and the AGX02 `config/models.yaml` use (`/home/tonyho/model/...`), the rest of
  `~/model` (protected folder), `~/.local` site-packages (the live venv uses them until the owner reinstalls with
  `ops/install.sh`), JetPack/CUDA/TensorRT, jtop, nvpmodel, nvfancontrol, ssh, tailscale, timesyncd, the network,
  the Docker engine, and the 7 recording sessions that the AGX02 `config/sim.yaml` and `config/sources.yaml` use.
- `ops/cleanup/stage1_disable.sh` (disable at boot and stop; undo), `stage2_archive.sh` (move to one archive folder
  `~/_archive_<date>/` on the same file system; undo with the manifest), `stage3_delete.sh` (delete the archive and
  the Valhalla container and image only; no prune; cannot be undone), `common.sh`. Each script prints its list, asks for
  a typed word (`DISABLE`, `ARCHIVE`, `DELETE`), has `--dry-run` (always a dry run without a terminal), refuses root,
  a wrong user or host, and checks the KEEP list at run time. `bash -n` OK; shellcheck 0.11.0: no finding.

SAVE FIRST (git work first):

| Repository | Work that is not saved |
|---|---|
| `/home/tonyho/driveragent` | branch `claude/quizzical-elgamal-709408`: 2 commits not pushed (0f266df, da3d058, 2026-05-07). `main` is clean and pushed. |
| 4 worktrees of driveragent (`.claude/worktrees/...`) | 3 have 1 changed file each (`.claude/settings.local.json`) |
| `/home/tonyho/model/yolopx/YOLOPX` | 67 files (61 untracked, 4 deleted, 2 changed) |
| `/home/tonyho/Downloads/gstreamer` | 2 untracked files + generated files in 9 subprojects; no upstream |
| `/home/tonyho/Downloads/libnice` | 1 untracked file; no upstream; the build tree is needed for `make uninstall` |
| `/home/tonyho/Downloads/jetson-jtop-patch` | 1 changed file (mode) |
| data with no other known copy | the recordings (1860 session folders + 1869 `.tar.bz2`, 548 GiB), the map data, the calcam files |

Expected result (M = measured 2026-10-07 20:28-20:35 BST read-only; A = audit 20:12 BST):

| Stage | Services that stop | Memory that becomes free (RSS, upper limit) | Disk space that becomes free |
|---|---|---|---|
| 1 base | 10 services (nvargus-daemon, bluetooth, ModemManager, kerneloops, apport, rpcbind, lpd, packagekit (mask), cups snap x2), 3 path/timer/socket units, the container driveragent-valhalla; ports 8002, 111, 631 close | 237 MiB (M) | 0 |
| 1 optional groups | nomachine (277 MiB), openvpn (8 MiB), avahi (3.5 MiB), update timers (0), desktop at the next boot (2.04 GiB RSS, about 1.4 GiB PSS) | see left | 0 |
| 2 | none | 0 | 0 (rename on the same file system; 3749 items, 548.7 GiB go to the archive) |
| 3 | none | 0 | 551.6 GiB (archive 548.7 + container log 2.2 + image 0.7). Free: 280.2 GiB now -> about 831.8 GiB |

Owner order: SAVE FIRST steps, stage 1, wait about 3 days, stage 2, wait about 7 days, stage 3 (`--confirm-saved`).
`docs/CLEANUP_PROPOSAL.md` has 12 open questions; the optional groups of stage 1 refer to them.

## 6. Part C: long run

Run: 2026-10-08 04:19:20 to 12:20:30 CST (481.2 min = 8.0 h; the task asked for 4 h at least). One sample each
10 s on each machine: 2888 samples on DA01 and 2888 on AGX02, 0 bad lines, 0 gaps longer than 25 s. Recorder CPU:
DA01 sampler 43.5 s in 8 h (0.15 % of one core) + its journalctl reader 8.6 s; AGX02 sampler 57.4 s (0.20 %).
Nothing was changed or restarted on the two machines during the run. A watcher read the link state each 30 s.

Start state (04:19 CST): DA01 and AGX02 paired, AGX02 the active unit, `driverguard_yolopx@1` (6 cameras) and
`driverguard_dtcp@1` (cam0) active, sender ON. agx-infer and agx-dashboard ran the code of 970d5ac (Section 1).

### 6.1 Statement

**STABLE.** Evidence:

- Link UP for the full run (watcher: one state, "UP" from 04:19:43 to 12:20:23). AGX status age max 1.02 s.
- No restart: all 10 rk-* units of DA01 and agx-infer / agx-dashboard of AGX02 kept their PIDs; NRestarts 0;
  sender restarts 0; agx-infer uptime grew by 28870 s = the run time.
- Results: 1,491,476 received on DA01 = 1,491,478 sent by agx-infer (the 2 are in flight at the end). Rejected 0,
  stale 0, tcapture mismatch 0, instances dropped 0. All forwarded to the HMI.
- No value has a trend: the slopes are near 0 and the first and last 30 min agree (table 6.2).
- The memory of the services did not grow much (table 6.3). agx-infer grew by 22.5 MB in 8 h. This is small, but it
  continued for the full run (Section 8).

### 6.2 Values (mean / min / max; trend = slope per hour; first 30 min -> last 30 min)

| Value | Mean | Min | Max | Trend /h | First -> last 30 min |
|---|---|---|---|---|---|
| Link state | UP 100 % | - | - | - | UP -> UP |
| yolopx@1 results/s per camera (cam0..cam5, each) | 6.95 | 6.0 | 8.2 | -0.01 | 7.01 -> 6.93 |
| yolopx@1 results/s, all cameras | 41.69 | 37.2 | 48.8 | -0.05 | 42.02 -> 41.56 |
| dtcp@1 results/s (cam0) | 10.01 | 9.8 | 10.2 | 0 | 10.00 -> 10.01 |
| Capture-to-result p50, cam0 (ms) | 86.7 | 72.3 | 97.8 | +0.21 | 85.9 -> 85.6 |
| Capture-to-result p50, cam1..cam5 (ms) | 111.7 / 118.7 / 114.5 / 116.2 / 120.1 | 102.1 | 127.4 | <= 0.07 | same |
| Capture-to-result p95, cam0 (ms) | 131.7 | 123.8 | 136.4 | +0.06 | 130.7 -> 130.9 |
| Capture-to-result p95, cam1..cam5 (ms) | 146.7 / 154.6 / 149.3 / 151.2 / 156.1 | 137.6 | 168.5 | <= 0.07 | same |
| dtcp@1 capture-to-result p50 / p95 (ms) | 79.4 / 99.0 | 63.6 / 79.6 | 94.8 / 125.3 | 0.23 / 0.12 | 79.6 -> 79.3 / 98.2 -> 99.7 |
| Stale results / rejected results | 0 / 0 | 0 | 0 | 0 | 0 -> 0 |
| Capture frames/s, each of the 6 cameras (rk-camd) | 30.0 | 29.4 | 30.9 | 0 | 30.0 -> 30.0 |
| Sent frames/s to the AGX: cam0 / cam1..5 | 30.0 / 15.0 | 29.3 / 14.7 | 30.7 / 15.3 | 0 | same |
| HMI frames/s | 20.25 | 19.3 | 21.75 | +0.01 | 20.21 -> 20.25 |
| HMI frame time p99 (ms) | 76.5 | 66.7 | 100.0 | +0.03 | 76.8 -> 77.6 |
| HMI frame time p50 (ms) | 50.0 | 49.9 | 50.0 | 0 | 50.0 -> 50.0 |
| Recorder | not recording (100 %) | - | - | - | same |
| DA01 temperature, soc / gpu (C) | 37.8 / 37.0 | 37.0 / 36.1 | 39.8 / 37.9 | -0.09 / -0.03 | 38.1 -> 37.4 |
| AGX02 temperature, cpu / gpu / tj (C) | 55.3 / 50.9 / 55.3 | 54.4 / 49.5 / 54.3 | 57.6 / 53.2 / 57.6 | -0.14 | 55.7 -> 54.8 |
| AGX02 power, power log (W, sum of the 4 rails, SENSOR) | 24.07 | 22.68 | 26.26 | -0.02 | 24.23 -> 24.10 |
| AGX02 power as the DA01 console sees it (W) | 24.07 | 22.51 | 26.51 | -0.01 | 24.27 -> 24.12 |
| AGX02 rails: GPU_SOC / CPU_CV / SYS_5V0 / VDD2_1V8AO (W) | 12.88 / 1.72 / 7.20 / 2.27 | 11.76 / 1.60 / 7.06 / 2.16 | 14.67 / 2.24 / 7.41 / 2.39 | ~0 | same |
| DA01 CPU load (% of all cores) / load1 | 19.4 / 10.3 | 18.9 / 7.5 | 22.6 / 13.3 | +0.02 / 0 | 19.5 -> 19.4 |
| AGX02 CPU load (%) / load1 | 25.1 / 3.5 | 24.2 / 1.9 | 28.9 / 7.2 | 0 | 25.1 -> 25.1 |
| AGX02 GPU load (%) | 62.7 | 26.4 | 94.2 | +0.04 | 61.5 -> 62.8 |
| DA01 GPU load (%) | 13.1 | 7.3 | 23.4 | +0.03 | 13.0 -> 13.3 |
| DA01 / AGX02 MemAvailable (MB) | 5802 / 50802 | 5677 / 50763 | 5817 / 50834 | -0.5 / -2.5 | 5795 -> 5800 / 50814 -> 50790 |

Counters over the run (8.0 h): lost frames on the link (sum of the 6 cameras) 17 of 3,031,351 frames received by agx-infer
(cam0 6, cam1 1, cam2 1, cam3 5, cam4 2, cam5 2); lost packets cam0 132, cam3 33, others 5 to 11; sender
tx_errors 17 in total (one for each lost frame); AGX decoder errors 0; framelink drops 0; ring overruns 0. rk-camd `consumer_drops` grew
by about 360 per hour per camera (cam0 595/h) also in the normal state; capture seq_gaps, stalls, restarts and
no_free stayed 0.

### 6.3 Memory of each service (start -> end, median of 3 samples)

| Machine | Service | Start MB | End MB | Change | MB/h (slope) | PID (same for the run) |
|---|---|---|---|---|---|---|
| AGX02 | agx-infer (RSS of 8 processes) | 1508.6 | 1531.1 | +22.5 | +2.92 | 387147 |
| AGX02 | agx-infer (cgroup memory.current) | 723.2 | 746.0 | +22.8 | +2.94 | 387147 |
| AGX02 | agx-dashboard (RSS) | 72.9 | 74.2 | +1.3 | +0.13 | 386946 |
| AGX02 | agx-dashboard (memory.current) | 69.3 | 63.7 | -5.6 | +0.27 | 386946 |
| AGX02 | docker.service / Valhalla container (memory.current) | 124.4 / 87.5 | 124.6 / 87.5 | +0.2 / 0 | 0.02 / 0 | - |
| DA01 | rk-console | 56.2 | 64.5 | +8.3 | +0.94 | 1193860 |
| DA01 | rk-hello | 29.6 | 30.2 | +0.6 | +0.10 | 959442 |
| DA01 | rk-media (2 processes) | 93.6 | 93.9 | +0.3 | +0.03 | 942 |
| DA01 | rk-agxlink (2 processes) | 42.0 | 42.1 | +0.1 | +0.01 | 1029018 |
| DA01 | rk-hmi | 174.2 | 174.2 | 0 | 0 | 959446 |
| DA01 | rk-camd, rk-gnss, rk-logger, rk-mapgen, rk-recorder | 5.4, 27.5, 17.6, 21.2, 9.6 | same | 0 | 0 | same |

DA01 has no memory.current per unit (its system.slice has only the cpuset controller). The RSS of the unit processes
is used. AGX02 has no old-stack process (0 for the full run).

### 6.4 Events

- 04:19:43 link UP (the only link state of the run).
- No restart, no model change, no recorder change, no camera below 90 % of its frame rate, no stale or rejected result.
- Link packet loss: 17 single lost frames, each with a sender `tx_errors` +1 on DA01 at the same time. Times:
  04:30:30 (cam3), 05:30:30 (cam3), 06:12:50 (cam1), 06:18:00 (cam0), 07:26:30 (cam0), 07:38:00 (cam0),
  07:47:00 (cam5), 08:00:40 (cam4), 08:30:50 (cam0), 09:00:40 (cam0, cam4), 10:00:40 (cam0, cam5), 10:21:40 (cam3),
  10:38:10 (cam3), 11:00:40 (cam3), 11:21:40 (cam2). Several are at hh:00:40 or hh:30:30 (a periodic cause on the
  network or on DA01 is possible; not examined).
- The analysis also listed "RESET" lines (for example `lost_packets went back from 8 to 7`). They are NOT restarts:
  the PIDs did not change. The lost-packet counter of agx-infer goes back by 1 when a late packet arrives after it
  was counted as lost (the same value is in the DA01 status, which copies it).
- The single +1 values of `decoder_drops` that went back to 0 after 10 s are the same kind of value (a gauge, not a
  counter); the decoder error counter stayed 0.

### 6.5 HMI frames/s against time

| Time (CST) | 04:20 | 05:00 | 06:00 | 07:00 | 08:00 | 09:00 | 10:00 | 11:00 | 12:00 |
|---|---|---|---|---|---|---|---|---|---|
| HMI fps, 10-min mean | 20.0 | 20.5 | 20.3 | 20.2 | 20.0 | 20.0 | 20.3 | 20.6 | 20.6 |

All 50 10-min means (including the two short bins at the start and the end) are between 19.9 and 20.7 fps (screen "world" for the full run). The frame time p50 was 50.0 ms
in each sample. The change-point check (5-min means, step > 4 fps for > 2 min) found NO level change. Thus the run
did not show the change between about 21 and 35 frames/s of the day. Facts for the next search (not proved): the HMI
frame time sits exactly on 50 ms (a 20 Hz step), and the recorder did not record, nobody used the screen and
the screen stayed on "world" for the full run. A check during the day with recording and screen changes is
necessary to find the cause.


## 7. Owner steps

Nothing in this list was done tonight. Each step needs sudo, a push or an owner decision.

1. **Push** (the commits of this task and of the power log task are local):
   ```bash
   cd ~/driveragent && git push origin main                  # DA01
   ssh agx02 'cd ~/driveragent-agx && git push origin main'  # AGX02
   ```
2. **Load the new code on AGX02.** The running agx-infer and agx-dashboard still run the code of 970d5ac (rule X1:
   no stop tonight). Either restart the transient units (results stop for some seconds; the board reconnects):
   ```bash
   ssh agx02 'cd ~/driveragent-agx && tools/svc.sh restart dashboard && tools/svc.sh restart infer'
   ```
   or do step 3 at once (it also restarts them).
3. **Start at boot on AGX02** (recommended method: user units + linger, `docs/INSTALL_AGX.md` Sections 7.1 and 7.4).
   Do it at a planned time. Make sure first that the old stack does not take the GPU or the ports at boot (stage 1 of
   the cleanup disables the Valhalla container).
   ```bash
   cd ~/driveragent-agx
   ops/preflight.sh --instance agx         # the ports of the transient agx-* units count as free
   ops/install.sh --takeover --yes         # keeps config, .env, data, ~/agx-models, .venv; pip into the .venv
                                           # (about 1 GB, PYTHONNOUSERSITE=1); stops the transient units and starts
                                           # the installed user units
   ops/doctor.sh                           # all items PASS (DA01 is paired)
   sudo loginctl enable-linger tonyho      # start at boot
   ```
   Alternative (system units): `ops/install.sh --print-system-units` prints the files and the sudo commands
   (`docs/INSTALL_AGX.md` Section 7.3).
4. **Cleanup of AGX02** (`docs/CLEANUP_PROPOSAL.md`): first the SAVE FIRST steps SF-1 to SF-9 (replace the backup host
   placeholders), and the answers to the 12 open questions. Then:
   ```bash
   cd ~/driveragent-agx
   ops/cleanup/stage1_disable.sh --dry-run && ops/cleanup/stage1_disable.sh        # type DISABLE; undo: --undo
   # wait about 3 days
   ops/cleanup/stage2_archive.sh --dry-run && ops/cleanup/stage2_archive.sh        # type ARCHIVE; undo: --undo
   # wait about 7 days
   ops/cleanup/stage3_delete.sh --dry-run && ops/cleanup/stage3_delete.sh --confirm-saved   # type DELETE; no undo
   ```
5. **Optional:** `python3 -m pip cache purge` on AGX02 (the pip cache grew by 280 MB tonight: the torch wheel).
6. **Still open from the power log task:** `cd ~/driveragent && rk/console/build.sh && sudo systemctl restart
   rk-console`; then optional `sudo systemctl restart rk-agxlink` BEFORE `status: schema_version: 3` in the AGX02
   `config/infer.yaml`.


## 8. Defects and open decisions

| # | Defect or open decision | Effect | Proposal |
|---|---|---|---|
| D1 | The running agx-infer and agx-dashboard of AGX02 run the code of 970d5ac; the new code is only on disk (no restart tonight). | A module that the running dashboard imports later (for example at a model action) can come from the new code. Low risk: the new code is compatible with the live config (Section 2.3), but the mix is not tested. | Owner step 7.2 or 7.3 soon. |
| D2 | agx-infer memory grew by 22.5 MB in 8 h (2.9 MB/h), steady for the full run. | About 70 MB per day if it continues. Not a problem now (50 GB available), but a slow leak is possible. | Compare after the next restart (step 7.2) with a run of 24 h. |
| D3 | rk-console RSS grew by 8.3 MB in 8 h (0.94 MB/h). | Small. | Check again after the owner restarts rk-console (step 7.6). |
| D4 | The HMI stayed at about 20 fps for 8 h (frame time p50 = 50.0 ms exactly). The change between about 21 and 35 fps of the day did not occur. | The cause is still not known. | A day test with recording on/off and screen changes, with this recorder (`$N/partc`). |
| D5 | 17 single lost frames on the link in 8 h; many at hh:00:40 or hh:30:30. | 17 of 3.0 million frames; no stale result. | Look for a periodic task on DA01 or the network at these times. |
| D6 | A new unit without a model shows agx-infer state ERROR and dashboard CRIT ("no model is enabled"). doctor treats this as correct. | It can alarm a new owner. | Decision: a state such as IDLE for "no model" (code change). |
| D7 | The store of a new unit has no test frame; the inference check needs `<store>/_testframes/front_1280x720.jpg` (copied by hand in the test). | The first activation on a new unit fails without it. | Put a test frame into the export package or the repository (owner decision: it is a real camera picture). |
| D8 | `tools/model_store_cli.py` does not read `protected_dirs` (the dashboard controller does). | A deploy by the command line into a store inside a protected folder is not refused. | Small change later. |
| D9 | `sparsedrive_convnext_orin@1` exports but has no adapter; `system1@1` has no ONNX. | A new unit cannot run them. | Owner decision: keep them only on AGX02 or remove them from the store. |
| D10 | Not tested: start at boot (linger or system units), `--takeover` on the live AGX02, mode `rk` on a new unit, a fresh Jetson without the apt packages, `--user-site`, a second unit (TARGET_SSH not given). | The installer is tested only on AGX02 as a second instance. | Test on a second Jetson when one is available. |
| D11 | The tool permission check refused the restart of the live agx-dashboard (Section 1). | See D1. | - |
| D12 | config/*.yaml are not tracked any more. On AGX02, a `git checkout` of an old commit (with tracked config files) stops with "untracked working tree files would be overwritten". | The owner must move the files first for such a checkout. | Keep the backup `~/agx-night-dev/live-config-backup-210256/`. |
| D13 | Open questions 1 to 12 of `docs/CLEANUP_PROPOSAL.md` (for example the backup host for 548 GiB of recordings). | Stage 3 must wait for the SAVE FIRST steps. | Owner answers. |

Files left from this task (made tonight, not removed): `agx02:~/agx-night-dev/live-config-backup-210256/` (the AGX02
config files before the new keys; no secret), the pip cache (`~/.cache/pip`, +280 MB), and on DA01 the recorder data
and scripts in the session scratch folder. Removed: the test installation, the helper dev folders and
`agx02:~/agx-night-partc/` (its data is copied to DA01).

