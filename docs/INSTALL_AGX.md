# Install a new AGX unit

This document tells you how to install driveragent-agx on a new Jetson AGX Orin. You start with a Jetson that has
JetPack. At the end, the unit is paired with an RK3588 board and one model is active.

The scripts are in `ops/`. They run as a normal user. They never use sudo. A step that needs sudo is an owner step:
the scripts print the exact command, and you run it.

| Step | Section | Time (measured on AGX02, 2026-10-08) |
|---|---|---|
| Check the Jetson | 3 | 2 s |
| Install | 4 | 82 s (the download of torch, 226 MB, included) |
| Check the installation | 6 | 1 s |
| Start at boot | 7 | owner step (sudo) |
| Pair with a board | 8 | 2 minutes, on the two dashboards |
| Deploy, build and activate a model | 9 | the build: about 20 minutes (example below) |

## 1. Requirements

| Item | Value | Checked by |
|---|---|---|
| Computer | NVIDIA Jetson AGX Orin (tested: AGX Orin Developer Kit 64 GB) | `ops/preflight.sh` |
| JetPack | 6.2.1 (L4T R36.4). JetPack 6 (L4T R36) is necessary. | `ops/preflight.sh` |
| TensorRT | 10.3.0 (JetPack). The engines and the builds are tested only with this version. | `ops/preflight.sh` |
| Python | 3.10 (`/usr/bin/python3` of JetPack) with `python3-venv` | `ops/preflight.sh` |
| System Python packages | `cv2` (OpenCV of JetPack), `gi` (python3-gi), `yaml` (python3-yaml), `psutil` (python3-psutil). Optional: `PIL` (python3-pil, only for tests). | `ops/preflight.sh` |
| GStreamer | the element `nvv4l2decoder` (JetPack multimedia) | `ops/preflight.sh` |
| Disk | 20 GiB free at the repository and at the model store. The venv uses about 1.0 GiB. An engine uses 70-200 MB. | `ops/preflight.sh` |
| Memory | 6 GiB `MemAvailable` (the GPU uses the same memory) | `ops/preflight.sh` |
| Ports | free: TCP 8700 (dashboard), TCP 5560-5564 (ZMQ), UDP 6000-6005 (cameras). Other ports: options of `ops/install.sh`. | `ops/preflight.sh` |
| Clock | the year is 2026 or later. NTP synchronization is optional. | `ops/preflight.sh` |
| systemd | the user manager answers (`systemctl --user`) | `ops/preflight.sh` |
| Network | access to `https://pypi.jetson-ai-lab.io` (torch) and `https://pypi.org` (all other packages), only during the install | - |
| git | to get the code | - |

The scripts never install a system package. When a system package is missing, `ops/preflight.sh` gives the FAIL line
with the apt package. The owner installs it, for example: `sudo apt install python3-venv python3-psutil`.

## 2. Get the code

Log in as the user that will run the services (any user; the examples use `tonyho`). Clone the repository into any
folder:

```bash
git clone git@github.com:osmosishk/driveragent-agx.git ~/driveragent-agx
# or, without an ssh key for GitHub:
git clone https://github.com/osmosishk/driveragent-agx.git ~/driveragent-agx
cd ~/driveragent-agx
```

## 3. Check the Jetson: ops/preflight.sh

```bash
ops/preflight.sh [--dash-port 8700] [--zmq-base 5560] [--video-base 6000] [--store ~/agx-models] [--instance NAME]
```

The script changes nothing. It writes one line per item: `PASS`, `FAIL` (a necessary item), `WARN` (an optional item) or
`INFO`, with the reason. Exit 0 only when all necessary items pass.

Example (AGX02, free test ports):

```text
PASS  jetson model             NVIDIA Jetson AGX Orin Developer Kit
PASS  L4T / JetPack            L4T R36.4.7, nvidia-jetpack 6.2.1+b38 (JetPack 6)
PASS  TensorRT                 10.3.0 (supported: 10.3.0)
PASS  python 3.10              /usr/bin/python3 3.10.12
PASS  python3-venv             venv and ensurepip are installed
PASS  system python modules    cv2 4.10.0, gi 3.42.1, yaml 5.4.1, psutil 5.9.0
PASS  nvv4l2decoder            GStreamer element present
PASS  disk (repo)              280 GiB free at /home/tonyho/agx-night-dev/a2 (>= 20 GiB)
PASS  disk (store)             280 GiB free at /home/tonyho/agx-night-dev (>= 20 GiB)
PASS  free GPU memory          MemAvailable 49 GiB (>= 6 GiB; shared CPU/GPU memory)
PASS  port dashboard           free
PASS  ports ZMQ 5580-5584      free
PASS  ports UDP 6020-6025      free
PASS  system time              2026-10-07 20:37:08 BST
PASS  systemd --user           the user manager of tonyho answers
PREFLIGHT PASSED: all necessary items pass.
```

A port that another program uses gives FAIL with the PID and the unit of that program, for example
`FAIL  port dashboard  in use: tcp/8700: pid 386946 (agx-dashboard.service)`. Then stop that program, or give other
ports (Section 4). With `--instance NAME`, the ports of the units `NAME-infer` and `NAME-dashboard` count as free
(a second install, or a takeover, Section 7.4).

## 4. Install: ops/install.sh

```bash
ops/install.sh [--instance agx] [--store ~/agx-models] [--dash-port 8700] [--zmq-base 5560] [--video-base 6000]
               [--mode rk|sim] [--no-enable] [--no-start] [--user-site] [--torch-index URL] [--takeover] [--yes]
```

| Option | Default | Meaning |
|---|---|---|
| `--instance NAME` | `agx` | The unit names `NAME-infer` and `NAME-dashboard`, the record `data/install-NAME.json`. |
| `--store DIR` | `~/agx-models` | The model store. Made when it is missing (with `_state` and `_incoming`). |
| `--dash-port N` | `8700` | The TCP port of the dashboard. |
| `--zmq-base N` | `5560` | ZMQ TCP ports N to N+4: results, status, internal, admin, rkinfo. |
| `--video-base N` | `6000` | FrameLink UDP ports N to N+5 (camera c = N + c). |
| `--mode rk\|sim` | `rk` | The camera source in a new `config/sources.yaml`. `sim` = the simulator `tools.rk_sim` on this unit. |
| `--no-enable` | - | Do not enable the units (they do not start at login or boot). |
| `--no-start` | - | Do not start the units now. |
| `--user-site` | - | Do not set `PYTHONNOUSERSITE=1`: pip and the units also see `~/.local`. Not recommended. |
| `--torch-index URL` | `https://pypi.jetson-ai-lab.io/jp6/cu126` | The pip index for torch (CUDA 12.6 wheels for JetPack 6). |
| `--takeover` | - | Stop TRANSIENT units with the same names (`tools/svc.sh`) and start the installed units (Section 7.4). |
| `--yes` | - | No question (for `--takeover` without a terminal). |
| `--print-system-units` | - | Only write the system unit files and print them with the sudo commands (Section 7.3). |

The script does these steps. It writes the time of each step.

1. It runs `ops/preflight.sh` with the same ports. A FAIL stops the install. Nothing is changed then.
2. It makes the venv `.venv` (`python3 -m venv --system-site-packages`).
3. It installs the fixed versions of `requirements/agx-torch.txt` (torch 2.8.0 for Jetson, from the Jetson index
   only) and then `requirements/agx-venv.txt` (from PyPI), with `PYTHONNOUSERSITE=1`. Then it imports each module
   in the environment of the units, and stops when one import fails or when torch has no CUDA.
4. It makes `config/*.yaml` from `config/templates/*.yaml` (only files that are missing). In the new files it sets the
   values of this instance: ports, model store, `unit_prefix`, mode. It adds the private IPv4 subnets of this unit to
   `allow_cidrs` of a NEW `config/dashboard.yaml` (not docker 172.16.0.0/12, not 169.254.0.0/16, not loopback). The
   tool `ops/lib/cfgset.py` changes only the value: all comments stay.
5. It makes `.env` from `.env.example` with a new random dashboard password (Python `secrets`, mode 600), and the
   folders `data/` (mode 700), `logs/` and `engines/`.
6. It makes the model store (`<store>/_state`, `<store>/_incoming`).
7. It makes the user units `~/.config/systemd/user/NAME-infer.service` and `NAME-dashboard.service` from
   `ops/units/*.service.in`, runs `systemctl --user daemon-reload`, enables them (not with `--no-enable`) and starts
   the dashboard and then agx-infer (not with `--no-start`). The units work for a repository in any folder and for any
   user.
8. It writes the record `data/install-NAME.json` (mode 600, no secret): what it made, what it kept, the options.

The install never activates a model.

At the end the script writes a summary: the state of each unit, the dashboard URL for each address of the unit, the
PATH of the password file, the kept files, notes, and the owner steps. Example (test instance on AGX02):

```text
==================== install summary (instance agxdev, 82 s) ====================
Units:
  agxdev-dashboard.service: installed (new file), not enabled (--no-enable), active
  agxdev-infer.service: installed (new file), not enabled (--no-enable), active
Dashboard URL(s) (port 8720):
  http://127.0.0.1:8720/
  http://10.0.0.130:8720/   (eno1)
  http://100.64.0.20:8720/   (tailscale0)
Dashboard user and password: in /home/tonyho/agx-night-dev/ops-inst/driveragent-agx/.env (AGX_DASH_USER, AGX_DASH_PASSWORD; mode 600). Read it on this unit.
Model store: /home/tonyho/agx-night-dev/ops-store (no model is active; deploy, build and activate: docs/DEPLOY_MODEL.md)
Owner steps (need sudo or a decision):
  - start at boot: the owner runs: sudo loginctl enable-linger tonyho ...
```

### 4.1 A second run

You can run `ops/install.sh` again with the same options (for example after `git pull`). A second run never
replaces `config/*.yaml`, `.env`, `data/*` or the model store. It writes `KEPT <path>` for each of them. It runs pip
again (13 s when nothing changed) and replaces a unit file only when the template changed. When a kept config file
has a value that is not the value of the options (for example another port), the summary says so. Change the file by
hand when necessary.

### 4.2 What install does not do

- It does not install system packages (apt) and does not use sudo.
- It does not enable linger and does not install system units (Section 7).
- It does not start the simulator. In mode `sim`, start it by hand:
  `PYTHONPATH=. .venv/bin/python -m tools.rk_sim --config config/sim.yaml` (all frames are SIMULATED).
- It does not activate a model (Section 9).

## 5. The password file

The dashboard user and password are in `.env` in the repository folder (`AGX_DASH_USER`, `AGX_DASH_PASSWORD`;
mode 600, not in git). The scripts never print the password. Read it on the unit:

```bash
grep '^AGX_DASH_' ~/driveragent-agx/.env
```

Do not send the password in a chat, a ticket or a log. To make a new password, write a new value in `.env`, then
`systemctl --user restart agx-dashboard`.

## 6. Check the installation: ops/doctor.sh

```bash
ops/doctor.sh [--instance agx] [--before-pairing] [--system-units]
```

The script changes nothing and never prints a password or a token. Exit 0 only when all necessary items pass. With
`--before-pairing`, the pairing and link items are information only. Example (test instance, no board, no model):

```text
PASS  unit dashboard           agxdev-dashboard.service: user unit, active/running, MainPID 427023, restarts 0, enabled: disabled
PASS  unit infer               agxdev-infer.service: user unit, active/running, MainPID 427027, restarts 0, enabled: disabled
PASS  dashboard /api/health    http://127.0.0.1:8720/api/health answers 200 with the password of .env; node_state CRIT (agx-infer ERROR)
PASS  agx-infer status         agx-infer sends status: state ERROR; models: none; cameras: NO SIGNAL 6
INFO  models                   no model is active (normal for a new unit: deploy, build and activate a model, docs/DEPLOY_MODEL.md). agx-infer shows ERROR 'no model is enabled' until then.
PASS  model store              /home/tonyho/agx-night-dev/ops-store: 0 model version(s); _state writable
WARN  test frame               /home/tonyho/agx-night-dev/ops-store/_testframes/front_1280x720.jpg is missing: the inference check of a model needs it (docs/INSTALL_AGX.md)
PASS  sensors INA3221          VDDQ_VDD2_1V8AO 2621 mW; VDD_GPU_SOC 14394 mW; VDD_CPU_CV 4400 mW; VIN_SYS_5V0 7685 mW
PASS  sensors thermal          6 zones: cpu-thermal 58.4 C, gpu-thermal 53.2 C, soc0-thermal 54.0 C, soc1-thermal 53.2 C ...
INFO  pairing                  no paired board (pair one: docs/CONNECT_AGX.md)
INFO  link                     no paired board: no link
INFO  results                  result subscribers 0, results 0.0/s, status age 0.7 s
DOCTOR PASSED: all necessary items pass.
```

A new unit has no model. Then agx-infer is in the state ERROR ("no model is enabled") and the dashboard shows
CRIT. This is correct until a model is active (Section 9).

## 7. Start at boot

User units start when the user logs in, and stop when the last session of the user ends. For a start at boot, use
ONE of the two methods below. Both need sudo one time (an owner step).

### 7.1 Recommended: user units and linger

```bash
sudo loginctl enable-linger tonyho          # one time; the user manager of tonyho then starts at boot
ops/install.sh                              # (if not done) installs and ENABLES the user units
systemctl --user is-enabled agx-infer agx-dashboard     # "enabled"
```

To stop the start at boot: `systemctl --user disable agx-infer agx-dashboard` (the units stay installed), or
`sudo loginctl disable-linger tonyho` (all user units of tonyho).

We recommend this method, for these reasons:

- After the one `loginctl` command, the user does all changes without sudo: install, update, uninstall, restart,
  logs (`journalctl --user-unit agx-infer`).
- `ops/install.sh`, `ops/doctor.sh` and `ops/uninstall.sh` manage these units completely. They were tested with them.
- No file of the system (`/etc`) changes. The unit files are in the home folder of the user.

### 7.2 Commands of the user units

```bash
systemctl --user status agx-dashboard agx-infer
systemctl --user restart agx-infer
journalctl --user-unit agx-infer -n 100 --no-pager
```

### 7.3 Alternative: system units

System units start at boot without linger. They also have `NoNewPrivileges`, `PrivateTmp` and `ProtectSystem=full`.
Each change then needs sudo, and `ops/uninstall.sh` does not remove them. To use them:

```bash
ops/install.sh --no-enable --no-start        # venv, config, .env, store (if not done)
ops/install.sh --print-system-units          # writes data/system-units/agx-{infer,dashboard}.service and prints
                                             # the files and these commands:
systemctl --user disable --now agx-dashboard.service agx-infer.service     # if the user units are installed
sudo install -m 0644 ~/driveragent-agx/data/system-units/agx-infer.service /etc/systemd/system/agx-infer.service
sudo install -m 0644 ~/driveragent-agx/data/system-units/agx-dashboard.service /etc/systemd/system/agx-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now agx-dashboard.service agx-infer.service
ops/doctor.sh --system-units
```

Undo: `sudo systemctl disable --now agx-infer.service agx-dashboard.service`, then
`sudo rm /etc/systemd/system/agx-infer.service /etc/systemd/system/agx-dashboard.service` and
`sudo systemctl daemon-reload`. Do not run the user units and the system units at the same time: they use the same
ports.

### 7.4 AGX02: the switch from the transient units

On AGX02 the services run tonight as TRANSIENT user units (`tools/svc.sh`: no unit file, no start at boot, linger
is off). The start at boot is NOT done on AGX02 tonight, for two reasons: it needs sudo (linger or system units), and
the old DriverAgent stack can also start parts at boot (its Docker container `driveragent-valhalla`; see
`docs/CLEANUP_PROPOSAL.md`). The owner does the switch at a planned time:

```bash
cd ~/driveragent-agx
git pull                                       # the version with ops/ (on AGX02 it is already there)
ops/preflight.sh --instance agx                # the ports of the transient agx-* units count as free
ops/install.sh --takeover --yes                # keeps config/*.yaml, .env, data/, ~/agx-models and .venv (KEPT);
                                               # runs pip into the kept .venv (with PYTHONNOUSERSITE=1);
                                               # stops the transient agx-dashboard and agx-infer,
                                               # installs, enables and starts the user units
ops/doctor.sh                                  # all items PASS (the board DA01 is paired)
sudo loginctl enable-linger tonyho             # owner: start at boot
```

- Without `--takeover`, `ops/install.sh` does not touch a running transient unit: it installs nothing for it and
  prints this owner step.
- The services are down for some seconds (test: the takeover run took 15 s; the units started 6 s after the stop).
  agx-infer starts with the last good model set (`~/agx-models/_state/last_good.json`): the engines load again.
  The board reconnects by itself.
- The transient simulator unit `agx-sim` is not touched.
- After the switch, use `systemctl --user` for agx-dashboard and agx-infer. `tools/svc.sh start dashboard|infer` does
  not work for them any more (a unit file with the same name exists).
- Back to the transient units: `ops/uninstall.sh` (it removes only the unit files; the kept `.venv` stays), then
  `tools/svc.sh start dashboard` and `tools/svc.sh start infer`.
- Before the first reboot with linger: make sure that the old stack does not take the GPU or the ports at boot.

## 8. Pair the unit with a board

Follow `docs/CONNECT_AGX.md`. Short form:

1. AGX dashboard (`http://<AGX address>:8700`, user and password from `.env`): page **Settings**, part **RK link**.
   Read the address under **This unit**. Push **Make pairing code** (one time, 10 minutes).
2. rk console of the board: page **AGX link**, card **Settings**, **Add an AGX unit**. Type the **Name**, the
   **Address** and the **Pairing code**. Push **Save and pair**. Read the result of the Test.
3. When all checks pass, push **Make active** and confirm.
4. Check: AGX dashboard, **Settings**, **RK link**, table **Paired boards**: the board and its link state. Then
   `ops/doctor.sh` (without `--before-pairing`): the items `pairing` and `link` PASS.

The unit must be in bench mode for the pairing (`config/control.yaml`: `control_mode: bench`, the default of the
template).

## 9. Deploy, build and activate a model

A new unit has an empty model store. Read `docs/DEPLOY_MODEL.md` (the package and the deploy) and
`docs/MODEL_CONTROL_API.md` (build, activate).

1. Get a package. From another unit, use `ops/export_model.sh` (Section 10). Copy the folder to the new unit, for
   example `scp -r agx02:agx-pkgs/driverguard_yolopx-2 ~/model-packages/`.
2. Put a test frame into the store. The inference check of a model needs a real camera frame
   `<store>/_testframes/front_1280x720.jpg`. Copy it from a unit that has one:
   `mkdir -p ~/agx-models/_testframes && scp 'agx02:agx-models/_testframes/front_1280x720.*' ~/agx-models/_testframes/`.
   (The check reads `<store>/_testframes/front_1280x720.jpg` of the store in use.)
3. Check and deploy the package:

   ```bash
   cd ~/driveragent-agx
   .venv/bin/python -m tools.model_store_cli validate ~/model-packages/driverguard_yolopx-2
   tools/deploy_model.sh ~/model-packages/driverguard_yolopx-2 --local
   ```

   The catalog shows the version as NEEDS BUILD (ONNX only).
4. Build the engine: AGX dashboard, page **Models**, the build button of the version (or
   `POST /api/models/<name>/<version>/build`). A new unit always builds its engines from the ONNX file: an engine
   works only on the same device type with the same TensorRT version. The build uses the GPU. Examples on AGX02
   while the live system ran: `driverguard_yolopx@2` took 1186 s (2026-10-07); `driverguard_dtcp@1` took 77 s
   (test installation, 2026-10-08).
5. After the build, the checks run. When the state is READY, activate it: page **Models**, the activate button (or
   `POST /api/models/<name>/<version>/activate`). The state is ACTIVE.
6. Check: `ops/doctor.sh` shows the model in the item `agx-infer status`.

The rk console of a paired board can also start the build and the activation (page **AGX link**).

## 10. Export a model from another unit: ops/export_model.sh

```bash
ops/export_model.sh <name> <version> [--store ~/agx-models] [--out DIR] [--with-engine]
```

The script only reads the store. It writes the package `<out>/<name>-<version>/`: `manifest.yaml` and the ONNX
file. The manifest path becomes the package-relative file name; the sha256 stays (the script checks the source
file against it). Then it checks the package with `tools/model_store_cli.py validate` against an empty temporary
store. A version without an ONNX file cannot be exported (exit 1, `cannot export: no ONNX file ...`).

`--with-engine` also copies the engine (from the manifest, or the engine that the build on this unit made). The engine
works only on the same device type with the same TensorRT version. For a unit of another type, export without
`--with-engine` and build there.

The models in the AGX02 store (2026-10-08):

| Version | Export | Reason / result |
|---|---|---|
| `driverguard_yolopx@1` | yes | ONNX `yolopx_v2.onnx` (126 MB). Expected state after deploy: NEEDS BUILD. |
| `driverguard_yolopx@2` | yes | ONNX `model.onnx` (126 MB). NEEDS BUILD; with `--with-engine`: REGISTERED (AGX Orin + TensorRT 10.3.0 only). |
| `driverguard_dtcp@1` | yes | ONNX `dtcp_v1.onnx` (93 MB). NEEDS BUILD. |
| `sparsedrive_convnext_orin@1` | yes, but it cannot run | ONNX (119 MB). NO ADAPTER (type `sparsedrive_backbone` has no adapter; see `docs/MODELS.md` section 7.2). |
| `system1@1` | no | `cannot export: no ONNX file` (only PyTorch weights `system1_deploy.pth`). |

## 11. Uninstall: ops/uninstall.sh

```bash
ops/uninstall.sh [--instance agx] [--purge] [--yes]
```

The script removes only what the record `data/install-NAME.json` says that install made. It prints the list first and
asks (or `--yes`).

- Without `--purge`: it stops, disables and deletes the user unit files, and removes `.venv` (when install made it).
  `config/*.yaml`, `.env`, `data/`, `logs/`, `engines/`, the store and the record stay.
- With `--purge`: also the config files, `.env`, `data/` (pairing data, tokens, history), `logs/`, `engines/` and the
  model store, but ONLY when install made them. A file or a store that install KEPT stays.
- It never touches a transient unit, a system unit, or a unit file that install did not make.

Test on AGX02 (instance agxdev): `--purge` removed the 2 unit files, `.venv` (1015 MB), 6 config files, `.env`,
`data/`, `logs/`, `engines/`, the store and the empty folder `~/.config/systemd`, in 5 s. After it, no `agxdev` unit
was loaded and the ports were free.

## 12. Troubleshooting

| doctor / preflight item | FAIL means | Do this |
|---|---|---|
| `jetson model`, `L4T / JetPack`, `TensorRT` | Not an AGX Orin with JetPack 6 / TensorRT 10.3.0 | Flash JetPack 6.2.1. Other versions are not tested. |
| `python3-venv`, `system python modules` | An apt package is missing | Owner: `sudo apt install python3-venv python3-gi python3-yaml python3-psutil` |
| `nvv4l2decoder` | GStreamer of JetPack is missing | Owner: install the JetPack multimedia packages (`nvidia-l4t-gstreamer`). |
| `disk`, `free GPU memory` | Not enough space or memory | Free disk space. Stop other GPU programs (for example the old stack). |
| `port ...` | Another program uses the port (the line gives the PID and unit) | Stop it, or install with other ports (`--dash-port`, `--zmq-base`, `--video-base`). |
| `systemd --user` | No user manager | Log in once with ssh, or owner: `sudo loginctl enable-linger <user>`. |
| `unit dashboard` / `unit infer` | The unit is not active | `journalctl --user-unit agx-infer -n 50`. Then `systemctl --user restart agx-infer`. |
| `dashboard /api/health` 401 | The password of `.env` is not the password that the dashboard read | `systemctl --user restart agx-dashboard` after a change of `.env`. |
| `dashboard /api/health` connection refused | The dashboard does not run, or uses another port | See the unit item; the port is in `data/dashboard_port`. |
| `agx-infer status` | The dashboard gets no status from agx-infer | Check the unit `agx-infer`, and that `ports.internal` of `config/infer.yaml` is the port that the dashboard reads (`infer_config`). |
| `model store` | The store folder is missing or `_state` is not writable | `ops/install.sh` again (it makes the store), or correct the owner and mode. |
| `test frame` (WARN) | The inference check cannot run | Section 9, step 2. |
| `sensors INA3221` / `sensors thermal` | The sysfs files are not readable | A JetPack or device-tree problem; the power log and the health page show n/a. |
| `pairing` / `link` | No paired board, or the board sends no frames / does not subscribe | `docs/CONNECT_AGX.md`; rk console **AGX link**, **Test**. |
| install: `pip install ... failed` | No network, or the index is not available | Correct the network and run `ops/install.sh` again (it continues). |
| install: `the import check failed` | A package does not import in the venv | Read the `IMPORT ERROR` line. Do not use `--user-site` to hide the problem. |

## 13. Files

| Path | Content |
|---|---|
| `ops/preflight.sh`, `ops/install.sh`, `ops/doctor.sh`, `ops/uninstall.sh`, `ops/export_model.sh` | the scripts |
| `ops/lib/common.sh` | shared shell functions and the defaults |
| `ops/lib/cfgset.py` | change one value of a YAML file and keep the comments |
| `ops/lib/record.py` | the install record |
| `ops/lib/render_unit.py` | makes a unit file from a template |
| `ops/lib/export_model.py` | makes a model package |
| `ops/units/*.service.in` | user unit templates |
| `ops/units/system/*.service.in` | system unit templates (Section 7.3) |
| `requirements/agx-torch.txt`, `requirements/agx-venv.txt` | the fixed package versions |
| `config/templates/*.yaml` | the config templates (in git). `config/*.yaml` is machine data (not in git). |
| `data/install-NAME.json` | the install record (not in git) |
