# Deploy of driveragent-agx on demo - report

| Item | Value |
|---|---|
| Date | 2026-10-08, 19:18-19:50 BST (clock of `demo`, UTC+1) |
| Unit | `demo`: Jetson AGX Orin 64 GB, user `tonyho` |
| Repository | `~/driveragent-agx`, cloned from `main` at `970d5ac`; work on branch `deploy/demo` (commit `d6d09d5` and the commit of this report) |
| LAN address | `10.0.0.73/24` (eno1). Also tailscale `100.64.0.15`. |
| Dashboard | `http://10.0.0.73:8700/` (Settings, RK link: `http://10.0.0.73:8700/#/settings`) |
| Dashboard user and password | In `~/driveragent-agx/.env` on `demo` (mode 600, not in git): `AGX_DASH_USER` (value `agx`) and `AGX_DASH_PASSWORD` (random, 32 characters). The password is not in this report and not in a log. |
| Final state | `agx-dashboard` and `agx-infer` run as transient user units (started 19:43:16, 0 restarts), mode `rk`, no paired board, all 6 cameras NO SIGNAL, `control_mode: bench` |

The owner was not available. Each decision is in section 3.

## 1. Steps

| Step | State | Proof |
|---|---|---|
| 1 Preflight | DONE | hostname `demo`, user `tonyho`; `/etc/nv_tegra_release`: R36, REVISION 4.7 (JetPack 6.2.1); TensorRT 10.3.0.30; Python 3.10.12; free disk 804 GB of 915 GB; `nvpmodel -q`: MAXN (0); LAN `10.0.0.73/24`. All as expected. |
| 2 Clone | DONE | The folder did not exist. Clone of `main` at `970d5ac` ("Power log in the two dashboards (AGX02 part)"). |
| 3 Read | DONE | README.md, docs/CONNECT_AGX.md, docs/MODEL_CONTROLLER_REPORT.md, docs/DEPLOY_MODEL.md, docs/MODELS.md. |
| 4 venv | DONE | Section 2. `pip check`: "No broken requirements found". Imports OK. torch 2.8.0 and numpy 1.26.4 did not change. |
| 5 .env | DONE | `.env` mode 600, owner `tonyho`, git-ignored (`.gitignore:2`). Random password with the README command. `AGX_MQTT_ENABLED=0`. |
| 6 Machine values | DONE | Section 4. One correction in code (`tools/deploy_model.sh`, commit `d6d09d5`). No change in `config/`. |
| 7 Models | DONE | Section 5. The two enabled engines load with no device warning. DTCP waypoints are finite. Store `~/agx-models` with 3 models. |
| 8 Ports | DONE | Before the start: no listener on TCP 5560-5564, 8700 and UDP 6000-6005. No old process was stopped. |
| 9 Tests | DONE (2 known failures) | Section 6. 302 passed, 2 failed, 4 skipped (reference on AGX02: 274 passed). |
| 10 Simulator test | DONE | Section 7. 5 min 28 s with the recordings of `demo`. YOLOPX 7.4 results/s on each camera, DTCP 10.0 results/s. No error in the logs. |
| 11 Final state | DONE | Mode `rk` (`ingest mode rk` in the log), dashboard and infer active, 6 cameras NO SIGNAL. `loginctl enable-linger`: accepted, `Linger=yes`. |
| 12 Dashboard check | DONE (no picture) | Section 8. From `10.0.0.73`: `/api/health` 200, `/api/models` 200. The page and its 7 files 200. Settings, RK link APIs 200. `10.0.0.0/24` is in `allow_cidrs`: no change. |
| 13 DEPLOY_NEW_AGX.md | DONE | `docs/DEPLOY_NEW_AGX.md` on `deploy/demo`. |
| 14 This report | DONE | `docs/DEPLOY_DEMO_REPORT.md` on `deploy/demo`. |

## 2. Python packages

Venv: `python3 -m venv --system-site-packages .venv`, then
`.venv/bin/python -m pip install --no-deps --no-cache-dir -r requirements-venv.txt` (15 packages, all versions of the
file).

Packages from outside the venv (header of `requirements-venv.txt`):

| Package | AGX02 | demo before | Action |
|---|---|---|---|
| torch | 2.8.0 | 2.8.0 (user site) | none |
| pycuda | 2022.2.2 | **2026.1** (user site) | none (decision D3) |
| pyzmq | 27.1.0 | 27.1.0 | none |
| pycapnp | 2.2.0 | 2.2.0 | none |
| numpy | 1.26.4 | 1.26.4 | none |
| onnx | 1.21.0 | 1.21.0 | none |
| httpx | 0.28.1 | missing | `pip3 install --user --no-deps httpx==0.28.1` |
| httpcore | 1.0.9 | missing | `pip3 install --user --no-deps httpcore==1.0.9` |
| anyio | 4.13.0 | missing | `pip3 install --user --no-deps anyio==4.13.0` |
| h11 | 0.16.0 | missing | `pip3 install --user --no-deps h11==0.16.0` |
| tensorrt | 10.3.0 | 10.3.0 (apt) | none |
| cv2 | 4.10.0 | 4.10.0 (apt) | none |
| PyGObject | 3.42.1 | 3.42.1 (apt) | none |
| PyYAML | 5.4.1 | **6.0.3** (user site, in front of apt) | none (decision D3) |
| psutil | 5.9.0 | **7.1.3** (user site) | none (decision D3) |
| Pillow | 9.0.1 | **12.2.0** (user site) | none (decision D3) |

`pip check` then found two more missing packages that the header does not name. They were installed in the same way:
`exceptiongroup` 1.3.1 (needed by anyio and pytest) and `annotated-doc` 0.0.5 (needed by fastapi; without it
`import fastapi` fails). Each install: `pip3 install --user --no-deps --no-cache-dir <pkg>==<version>`, one at a time.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Venv packages with `--no-deps`. | Without it, pip installs a second copy of anyio and other packages in the venv. The AGX02 venv has only the 15 packages of the file. |
| D2 | Install `exceptiongroup` and `annotated-doc` (latest versions) in the user site. | `pip check` and `import fastapi` failed without them. The header does not give a version. |
| D3 | Keep pycuda 2026.1, PyYAML 6.0.3, psutil 7.1.3 and Pillow 12.2.0. | The rule is "install a missing package"; these are present. pycuda 2026.1 is used by the model registry (`~/driveragent-models`, rule R3). The tests and the simulator test pass with them. |
| D4 | Do not change `config/sources.yaml` and `config/sim.yaml` for the recordings. | The sessions `8003-2026...` are not on `demo`. Mode `file` is not used. The simulator got the 4 sessions of `demo` on the command line (`--sessions`), so no machine value went into git. |
| D5 | Do not register `sparsedrive_convnext_orin`, and do not change its path in `config/models.yaml`. | Its files (`convnext_backbone_fp16_orin.trt`, `convnext_backbone_nchw_orin.onnx`) are not on `demo`. The model is disabled and has no adapter. The engine `convnext_backbone_fp16.trt` on `demo` is a different engine with wrong output (docs/MODELS.md). |
| D6 | Keep `driverguard_dtcp` enabled with `dtcp_v1_fp16.engine`. | Its waypoints are finite on all 11 test frames and in the live simulator test (section 5). |
| D7 | Test frame for the model check from a recording of `demo`. | `~/agx-models/_testframes/front_1280x720.jpg` did not exist, and the model check needs it. Source: frame 100 of `8001-20260926_122805/front/cam0_20260926_122805.mp4` (1280x720, JPEG quality 95). |
| D8 | Correct the automatic mode of `tools/deploy_model.sh` (commit `d6d09d5`). | `agx02` resolves on `demo` (tailscale `100.64.0.20`). Before the change, the script with no option sent the package to the store of AGX02. Now it deploys locally when the hostname is the `--host` value, or on a Jetson when no `--host` is given. Test `test_deploy_model_sh_auto_mode_is_local_on_the_host` added; check on `demo` into a temporary store: "local deploy". |
| D9 | Repository-local git identity `osmosishk` / `tonyho@osmosis.com.hk`. | The identity that the owner set for the agent commits in `driveragent-models`. No global git setting changed. |
| D10 | Run the second full test run with the services stopped (19:40:47-19:43:16). | The tests start dashboards and use the GPU. No board was paired, so nothing used the services. |

## 4. Values specific to a machine (step 6)

`grep -rn -E '/home/tonyho|agx02|10\.0\.0\.' config/ tools/ systemd/`:

| Value | File | On demo | Action |
|---|---|---|---|
| `/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine`, `.../dtcp_v1_fp16.engine`, `.../onnx/yolopx_v2.onnx`, `.../onnx/dtcp_v1.onnx` | `config/models.yaml`, `tools/register_existing_models.py` | exist; the engines have the same sha256 as on AGX02 (`3412bafa...`, `1071ea90...`) | none |
| `/home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt` | `config/models.yaml`, `tools/register_existing_models.py` | missing | none (D5) |
| `/home/tonyho/model/system1/system1_deploy.pth` | `tools/register_existing_models.py` | exists | none |
| `/home/tonyho/model` | `config/dashboard.yaml` (`engines.scan_dirs`), `tools/inspect_engines.py` | exists | none |
| `/home/tonyho/driveragent/logger/video` and sessions `8003-20260510_*` | `config/sim.yaml`, `config/sources.yaml` | folder exists; sessions missing; `demo` has `8001-20260926_122805`, `_122905`, `_123016`, `_123045` (6 cameras each, H.265 1280x720, 30 fps) | none (D4) |
| `10.0.0.0/24` | `config/dashboard.yaml` (`allow_cidrs`) | `demo` is `10.0.0.73/24` | none: the subnet is in the list |
| `10.0.0.130` | `config/sources.yaml` (comment) | comment only | none |
| `/home/tonyho/driveragent-agx` | `systemd/*.service`, `systemd/install_units.sh`, `tools/rk_result_client` | same path | none |
| `agx02` | `tools/deploy_model.sh` | resolves to AGX02 over tailscale | corrected (D8) |

Other differences: `net.core.rmem_max` is 134217728 on `demo` (AGX02: 212992). No firewall service is active
(`ufw`, `firewalld`, `nftables` inactive).

## 5. Models (step 7)

`tools.inspect_engines` (TensorRT 10.3.0):

| Engine | Load | match | Device warning |
|---|---|---|---|
| `yolopx_v2_fp16.engine` (`3412bafa057a3a76`) | OK | True, Orin GPU (sm87) | none |
| `dtcp_v1_fp16.engine` (`1071ea90213eddc2`) | OK | True, Orin GPU (sm87) | none |

No engine was built.

DTCP: the engine of `config/models.yaml` ran through the node code (`TrtEngine` and `DtcpV1Adapter`). The inputs were
the inputs of the node: speed 0 m/s, command STRAIGHT, target (0, 20) m. The test used 11 frames: 3 nuScenes frames
(validation set of `driverguard@1.0.0`), 6 frames of 2 recordings of `demo`, 1 black frame and 1 grey frame. `pred_wp` was finite on all 11
frames (for example (-0.00, 2.64), (-0.04, 5.44), (-0.11, 8.32), (-0.17, 11.21) m). `mu`, `sigma` and `pred_speed` were
finite too. The node does not read them (rule R8). In the 5-minute simulator test, 2700 DTCP results came with no
error (the adapter refuses a waypoint that is not finite). Note: README section 7 of `driveragent-models` records this
engine (the same sha256) as "outputs not finite (mu/sigma collapse)". That test used different inputs. The file was not
replaced and `~/driveragent-models` was not changed.

Model store `~/agx-models`:

- `tools.register_existing_models --dry-run`, then the real run: `driverguard_yolopx@1`, `driverguard_dtcp@1`,
  `system1@1` WRITTEN. `sparsedrive_convnext_orin@1`: "ERROR file cannot be read" (D5). Exit code 1 (expected).
- Test frame: D7.
- `tools.model_check`: `driverguard_yolopx@1` READY (inference 72.4 ms on cam0), `driverguard_dtcp@1` READY
  (inference 12.7 ms, 4 trajectory points).
- Catalog after the start: `driverguard_yolopx@1` ACTIVE, `driverguard_dtcp@1` ACTIVE, `system1@1` NO ADAPTER.

## 6. Tests (step 9)

`PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/`

| Run | Commit | Result |
|---|---|---|
| 1 (19:25) | `970d5ac` | 2 failed, 301 passed, 4 skipped, 147 s |
| 2 (19:40) | `d6d09d5` (one more test) | 2 failed, 302 passed, 4 skipped, 144 s |

The full logs are in `test_logs/` (git-ignored).

Failures, the same in the two runs. The cause of each is a file difference between `demo` and AGX02, not a code
defect:

1. `tests/test_t1_models_doc.py::test_every_engine_and_tensor_is_in_models_md`: `docs/MODELS.md` is the inventory of
   AGX02. `demo` has engine files that it does not list, for example
   `/home/tonyho/model/driverguard/engines/dtcp_v1_fp16.engine` and
   `/home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp32.engine`.
2. `tests/test_dashboard_v2.py::test_01_models`: `assert 4 == (2 + 3)`. The engine cache has no entry for
   `convnext_backbone_fp16_orin.trt` because the file is not on `demo` (D5).

Skipped: 3 tests in `tests/test_rk_sim.py` ("recordings not found") and 1 in `tests/test_ingest.py` ("old recording
not found"). They need the AGX02 recordings `8003-20260510_*`.

## 7. Simulator test (step 10)

Commands (19:29:48-19:35:43):

```bash
tools/svc.sh start dashboard
tools/svc.sh start infer --mode sim
tools/svc.sh start sim --sessions 8001-20260926_122805,8001-20260926_122905,8001-20260926_123016,8001-20260926_123045
PYTHONPATH=. .venv/bin/python -m tools.sysmon --seconds 310 --out <scratch>/sysmon_sim.jsonl
PYTHONPATH=. .venv/bin/python -m tools.rk_result_client --host 127.0.0.1 --seconds 270
tools/svc.sh stop sim
```

The simulator sent 30.0 fps on each camera with 0 errors and 0 late frames. All data was SIMULATED (flag
`source_is_replay` on all 14 689 results).

Results (`rk_result_client`, 270 s):

| Model | Camera | Results | Results/s | Latency on the AGX p50 / p95 / p99 (ms) |
|---|---|---|---|---|
| driverguard_dtcp | 0 | 2700 | 10.0 | 77.4 / 92.9 / 114.7 |
| driverguard_yolopx | 0 | 1998 | 7.4 | 92.2 / 128.9 / 149.1 |
| driverguard_yolopx | 1 | 1998 | 7.4 | 78.5 / 107.2 / 126.3 |
| driverguard_yolopx | 2 | 1998 | 7.4 | 77.9 / 109.4 / 125.7 |
| driverguard_yolopx | 3 | 1999 | 7.4 | 82.5 / 109.1 / 123.2 |
| driverguard_yolopx | 4 | 1998 | 7.4 | 72.0 / 98.3 / 117.4 |
| driverguard_yolopx | 5 | 1998 | 7.4 | 78.6 / 105.8 / 119.1 |

Checks of `rk_result_client`: results received, expected cameras, no rejects, no duplicates, frame sequence
increases, status received: all PASS. Envelope sequence lost 0. Status: 270 messages, interval mean 1.000 s, max
1.044 s. (AGX02, `docs/MODEL_CONTROLLER_REPORT.md`: YOLOPX 6.97-7.2 results/s, DTCP 10.0.)

System (`tools.sysmon`, 310 samples, 1 s):

| Item | Value |
|---|---|
| GPU load | mean 59.9 %, p50 64.6 %, p95 99.8 % |
| CPU load | mean 31.0 % |
| Highest temperature | 59.5 °C (`tj-thermal`); CPU 59.1 °C, GPU 57.2 °C |
| Power (sum of the INA3221 rails) | mean 25.7 W, max 31.2 W |
| agx-infer memory | RSS max 1596 MB; RAM used max 14 331 MB of 65 894 MB |

Logs from the start of the simulator: 0 lines with ERROR, WARNING, CRITICAL or Traceback in `agx-infer`,
`agx-dashboard` and `agx-sim`. The only WARNING of `agx-infer` came at its start (19:29:48): "data/paired_boards.json
does not exist: ... from ANY source address are accepted". This is correct with no paired board.

## 8. Final state and dashboard check (steps 11, 12)

- `tools/svc.sh status`: `agx-dashboard.service` and `agx-infer.service` loaded, active, running. `agx-sim` stopped.
- agx-infer log: `infer node d6d09d5`, `ingest mode rk`, `driverguard_yolopx RUNNING (2 workers, cams [0..5])`,
  `driverguard_dtcp RUNNING (1 workers, cams [0])`, node state RUNNING. Two WARNING lines at the start (19:43:16-17):
  `paired_boards.json does not exist` (correct with no paired board), and `catalog snapshot is 154 s old`. agx-infer
  started in the same second as agx-dashboard and read the catalog from before the stop at 19:40:47. This has no effect
  after the dashboard writes the catalog again.
- Listeners: TCP `0.0.0.0:5560`, `0.0.0.0:5561`, `127.0.0.1:5562`, `127.0.0.1:5563`, `0.0.0.0:5564`, `0.0.0.0:8700`;
  UDP `0.0.0.0:6000-6005`.
- `loginctl show-user tonyho -p Linger`: `Linger=yes`.
- From the LAN address `10.0.0.73` (HTTP client on `demo`):
  - with no password, `/api/health` gives 401. With the password: `/api/health` 200 (hostname `demo`, node state OK,
    MAXN), `/api/models` 200 (driverguard_yolopx RUNNING, driverguard_dtcp RUNNING, system1 OFF,
    sparsedrive_convnext_orin OFF, each with its reason).
  - `/api/cameras`: cameras 0-5 `NO SIGNAL`, mode `rk`, `simulated: false`.
  - `/api/pair/info` (no password): `name demo`, `control_mode bench`, `pairing_open false`, ports 6000-6005, 5560,
    5561, 5564, 8700.
  - Settings, RK link: `/api/pair/state` 200 (addresses eno1 `10.0.0.73/24`, tailscale `100.64.0.15/32`, docker0),
    `/api/pair/settings` 200 (no accepted board address), `/api/pair/boards` 200 (empty). `/api/models/control` 200
    (`control_mode bench`).
  - Page `/` 200 (35 363 bytes, with the Settings section and the "Make pairing code" button); `app.js`, `router.js`,
    `tiles.js`, `style.css`, `tokens.css` and the two uPlot files 200. The page tests of the suite pass.
- Not done: a picture of the page in a browser. A headless Firefox did not finish in 90 s (no display). No check from a
  second host on the LAN: the Orin NX (`10.0.0.150`) did not answer ssh (about 19:39).

## 9. Changes on this machine

| Where | Change |
|---|---|
| `~/driveragent-agx` | New clone. Branch `deploy/demo`. Repository-local git identity (D9). New: `.venv`, `.env` (600), `data/` (made by the dashboard), `logs/`, `engines/` (empty), `test_logs/`, `tests/out/` (all git-ignored). |
| `~/.local/lib/python3.10/site-packages`, `~/.local/bin` | New: h11 0.16.0, anyio 4.13.0, httpcore 1.0.9, httpx 0.28.1, exceptiongroup 1.3.1, annotated-doc 0.0.5. New script `~/.local/bin/httpx` (from the httpx install). |
| `~/agx-models` | New model store: 3 manifests, `_testframes/front_1280x720.jpg`, `_state/` (made by the dashboard). |
| systemd user manager of `tonyho` | Transient units `agx-dashboard` and `agx-infer` (running), `agx-sim` (stopped at 19:35:43). Linger on (`/var/lib/systemd/linger/tonyho`). |
| `~/snap/firefox` | The agent made a temporary profile folder for the headless test and removed it. Firefox wrote font cache files in `common/.cache/fontconfig` and the file `7297/.config/ibus/bus`. |

Not changed: the old DriverAgent install (`~/driveragent`: recordings only read), `~/model` (only read),
`~/driveragent-models`, `/opt/driveragent/models` (validation frames only read), the publisher key, the Docker
container `driveragent-valhalla` (still up), `config/control.yaml` (`control_mode: bench`), all files in `config/`.
No `data/` from AGX02. No sudo. No reboot.

## 10. Stopped processes

No old process was stopped: no process used the ports or the GPU.

The agent stopped and started only its own units: `agx-infer` and `agx-dashboard` at 19:35:54-19:36:00 (end of the
simulator test, change to mode `rk`) and at 19:40:47-19:43:16 (test run 2). `agx-sim` stopped at 19:35:43. Start commands: `tools/svc.sh start dashboard`; `tools/svc.sh start infer --mode sim`
(agx-infer stopped at 19:35:54); `tools/svc.sh start infer` (agx-infer stopped at 19:40:47);
`tools/svc.sh start sim --sessions ...` (section 7).

## 11. After a reboot

The transient user units do not start at boot. Start them again with these two commands:

```bash
cd ~/driveragent-agx && tools/svc.sh start dashboard
cd ~/driveragent-agx && tools/svc.sh start infer
```

## 12. Blockers for the owner

| # | Item | Why | Owner action |
|---|---|---|---|
| B1 | System units | Needs sudo (rule R2). | Run `bash ~/driveragent-agx/systemd/install_units.sh` as `tonyho`. Do not use sudo. The script asks for the sudo password. It stops the transient user units and starts the system units. |
| B2 | Start at boot | Needs sudo and a separate approval. | After B1: `sudo systemctl enable agx-infer.service agx-dashboard.service`. Until then, use section 11 after each reboot. |
| B3 | Merge of `deploy/demo` | Rule R5: no push to `main`. | Review and merge commit `d6d09d5` (deploy_model.sh) and the two documents. |
| B4 | Two tests fail on `demo` | `docs/MODELS.md` and `config/models.yaml` describe the files of AGX02. | Decide: accept them as known failures on a second unit, or make the two tests depend on the unit. |
| B5 | Visual check of Settings, RK link | No browser picture tonight (section 8). | Open `http://10.0.0.73:8700/#/settings` before the pairing. |

## 13. Tomorrow: pair DA03 (docs/CONNECT_AGX.md)

1. Connect DA03 to the LAN of `demo` (`10.0.0.0/24`). On DA03, make sure that the link settings are not locked
   (`/etc/driveragent/agx_link_lock`: no file, or `locked = false`).
2. On `demo`, make sure that agx-dashboard and agx-infer run: `tools/svc.sh status`. After a reboot, use the two
   commands of section 11. On a computer on the LAN, open `http://10.0.0.73:8700/#/settings`. Log in. User: `agx`.
   Password: on `demo`, line `AGX_DASH_PASSWORD` of `~/driveragent-agx/.env`.
3. Open Settings, RK link, "This unit". Use the address `10.0.0.73` for DA03.
4. Push **Make pairing code**. The code works one time, for 10 minutes.
5. Open the rk console of DA03 and log in. Open the page **AGX link**, card **Settings**. Push **Add an AGX unit**.
   Type the **Name** (for example "demo"). Type the **Address** `10.0.0.73`. Type the **Pairing code** from step 4.
   Keep the default ports. Push **Save and pair**.
6. Read the Test result. When all checks pass, push **Make active** and confirm. In 30 s the card shows "ok" with the
   number of cameras that give results.
7. On the AGX dashboard: Settings, RK link, **Paired boards** shows DA03. The camera tiles change from NO SIGNAL to
   live frames. agx-infer then accepts video only from the addresses of the paired boards (`data/paired_boards.json`,
   no restart).
8. Status schema: agx-infer sends `AgxInferStatus` version 2 (`config/infer.yaml`, `status.schema_version: 2`). The
   check "schema versions agree" of the Test shows whether rk-agxlink on DA03 accepts it.
9. The AGX is in bench mode. Before the vehicle drives, the owner sets `control_mode: vehicle` in
   `config/control.yaml` on `demo`.
