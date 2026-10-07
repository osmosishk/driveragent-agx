# driveragent-agx

AGX inference node for DriverAgent. The Jetson AGX Orin (agx02) receives six camera streams from the
RK3588, runs the TensorRT models, and publishes the results to the RK3588. It also has its own web
dashboard. The RK3588 does capture, HMI, maps, recording, upload, CAN and display.

This repository was made in one night run (2026-10-05). Read `docs/MORNING_REPORT.md` first.

## Data flow

```
RK3588 (or tools/rk_sim)                       AGX agx02
 6 cameras --FrameLink UDP 6000-6005--> infer/ingest (nvv4l2decoder, newest frame per camera)
                                            |
                                            v
                                       infer/models (TensorRT: driverguard_yolopx, driverguard_dtcp)
                                            |
 RK3588 <--ZMQ 5560 results, 5561 status--  infer/publish (dabus envelope + Cap'n Proto)
                                            |
                                   127.0.0.1:5562 --> dashboard (port 8700, Basic auth)
```

## Set-up

Needed: Jetson AGX Orin with JetPack 6.2.1 (L4T R36.4), TensorRT 10.3.0, Python 3.10. The full procedure for a new
unit (from an empty Jetson to "paired with a board and one model active") is in `docs/INSTALL_AGX.md`. Short form:

```
git clone git@github.com:osmosishk/driveragent-agx.git ~/driveragent-agx
cd ~/driveragent-agx
ops/preflight.sh                     # checks only; PASS / FAIL per item
ops/install.sh                       # venv, pinned packages, config/*.yaml, .env (random password), units
ops/doctor.sh --before-pairing       # PASS / FAIL per item
```

`ops/install.sh` makes the venv `.venv` (`--system-site-packages`) and installs the fixed versions of
`requirements/agx-torch.txt` (torch for Jetson) and `requirements/agx-venv.txt` (all other packages; its header lists
the packages that come from JetPack / apt). `requirements-venv.txt` only points to `requirements/agx-venv.txt`.
It makes `config/*.yaml` from `config/templates/` (only missing files) and `.env` from `.env.example` with a new
random dashboard password (mode 600). It never prints the password: it prints the path of `.env`.
Do not commit `.env`. The dashboard does not start when `AGX_DASH_PASSWORD` is empty.

## Start and stop

`ops/install.sh` installs two systemd USER units, `agx-infer` and `agx-dashboard` (`--instance NAME` changes the
prefix). For a start at boot, the owner runs `sudo loginctl enable-linger <user>` one time, or installs system units
(`ops/install.sh --print-system-units` prints the files and the sudo commands). See `docs/INSTALL_AGX.md` section 7.

```
systemctl --user status agx-dashboard agx-infer
systemctl --user restart agx-infer
journalctl --user-unit agx-infer -n 100
ops/doctor.sh                                # PASS / FAIL per item
PYTHONPATH=. .venv/bin/python -m tools.model_ctl list            # model states (admin socket, local only)
ops/uninstall.sh                             # removes the units and the venv that install made (--purge: more)
```

`tools/svc.sh` starts the services as TRANSIENT user units (no unit file, no start at boot). Use it only where
`ops/install.sh` did not install the units (AGX02 until the owner switch, `docs/INSTALL_AGX.md` section 7.4), and for
the simulator: `tools/svc.sh start sim --sessions road` (SIMULATED input). No unit exists for the simulator: in mode
`sim`, keep it running, or set `mode: rk` in `config/sources.yaml`.

## Dashboard

- URL: `http://<agx address>:8700/` (for example `http://10.0.0.130:8700/` or `http://100.64.0.20:8700/`).
- User and password: in `.env` (mode 600, not in git): `AGX_DASH_USER`, `AGX_DASH_PASSWORD`.
- Only private source addresses can connect. All routes are read-only.
- API: `/api/health`, `/api/models`, `/api/cameras`, `/api/link`, `/api/services`, `/api/history`,
  `/api/stream` (SSE).

## Ports

| Port | Use |
|---|---|
| UDP 6000-6005 | FrameLink camera input (cam N = 6000 + N) |
| TCP 5560 | results PUB (`AgxPerceptionResult`, all interfaces) |
| TCP 5561 | status PUB 1 Hz (`AgxInferStatus`, all interfaces) |
| TCP 127.0.0.1:5562 | internal status + snapshots for the dashboard |
| TCP 127.0.0.1:5563 | admin socket (model stop/start, frames for the viewer) |
| TCP 8700 | dashboard |

## Tools

| Command | Use |
|---|---|
| `python -m tools.rk_sim --config config/sim.yaml [--sessions road] [--fmt nv12]` | RK3588 simulator (FrameLink sender) |
| `python -m infer.ingest.probe --config config/sources.yaml --seconds 60` | camera input metrics only |
| `python -m tools.rk_result_client --host 127.0.0.1 --seconds 60` | example result subscriber for the RK agent |
| `python -m tools.result_viewer --seconds 10 --out tests/out/viewer` | draw the published results on their frames |
| `python -m tools.inspect_engines --scan DIR` | list every engine file with its I/O tensors |
| `python -m tools.sysmon --seconds N --out f.jsonl` | system samples (CPU, GPU, RAM, temperatures, power) |

Run every command from the repository root with `PYTHONPATH=.` and `.venv/bin/python`.

## Tests

```
PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/
```

Test logs: a test log larger than 1 MB (1,000,000 bytes) goes to `test_logs/`, which git ignores. Commit only the
summary: the result document of the test and one line in `docs/test_results/RAW_LOGS.md` (path, size, sha256, time
span). `tests/test_repo_rules.py` fails when a tracked test log is larger than 1 MB.

## Notes and limits

- UDP ports 6000-6005: only ONE sender per camera port. Do not run `tools.rk_sim` and the RK3588
  sender at the same time. Only one receiver can bind the ports: stop `agx-infer` before
  `infer.ingest.probe`.
- Tests: `tests/test_rk_sim.py::test_missing_file_falls_back_to_pattern` can fail under heavy load
  (strict zero-loss UDP check). It passes when it runs alone.
- Mode `rk` is not tested with the real RK3588. The RK3588 does not send FrameLink yet
  (`docs/BLOCKERS.md` B3).
- Transient user units (`tools/svc.sh`) stop when the last session of the user ends (Linger=no)
  and at reboot. For a permanent service, use `ops/install.sh` and linger or system units (see "Start and stop").
- The dashboard uses plain HTTP with Basic auth: the password crosses the network. Use it through
  tailscale or loopback, or set TLS (`tls_certfile` and `tls_keyfile` in `config/dashboard.yaml`).
- MQTT publisher: written, DISABLED. Enable it only with owner approval (rule R11: data goes off
  the machine).
- All data from the simulator or from files is SIMULATED and is labelled SIMULATED (rule R13).

## Documents

| File | Content |
|---|---|
| `docs/INSTALL_AGX.md` | install a new AGX unit (ops/ scripts), start at boot, pairing, first model, uninstall |
| `docs/MORNING_REPORT.md` | status of the night run, numbers, decisions for the owner |
| `docs/RK_AGX_INTERFACE.md` | interface RK3588 <-> AGX (FrameLink, envelope, results, status) |
| `docs/RK_TASKS.md` | work for the RK3588 agent, with tests |
| `docs/MODELS.md` | every engine file, pre/post-processing, model decisions |
| `docs/CLEANUP_PROPOSAL.md` | cleanup proposal for this machine (proposal only) |
| `docs/AGX_AUDIT.md` | audit report |
| `docs/NIGHT_LOG.md` | decisions and events of the night run |
| `docs/BLOCKERS.md` | items that need the owner |
| `docs/test_results/` | real test outputs |
| `proto/agx_infer.capnp` | result and status schema (version 1) |
