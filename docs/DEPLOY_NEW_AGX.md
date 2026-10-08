# Deploy driveragent-agx on a new AGX unit

These are the steps that worked on the second AGX unit (`demo`, 2026-10-08, branch `deploy/demo`). The result of that
deploy is in `docs/DEPLOY_DEMO_REPORT.md`. Do the steps in this order. Run them as the normal user (`tonyho`).
No step needs sudo, except the owner items in step 13.

Write the values of your unit in place of the words in angle brackets: `<agx address>` is the LAN address of the new
unit (for example from `ip -4 -o addr show`).

## 1. Preflight

Record these values. Stop when they are different from the expected values.

```bash
hostname; whoami
cat /etc/nv_tegra_release                       # expected: R36 (release), REVISION: 4.x  (JetPack 6.2.1)
dpkg -l | grep -E '^ii\s+tensorrt\s'            # expected: 10.3.0.x
python3 --version                               # expected: Python 3.10.x
df -h /                                         # at least 20 GB free (store, engines, logs)
nvpmodel -q                                     # MAXN (mode 0)
ip -4 -o addr show                              # the LAN address of the unit
```

## 2. Clone

```bash
git clone https://github.com/osmosishk/driveragent-agx.git ~/driveragent-agx
cd ~/driveragent-agx && git log --oneline -1
```

If `~/driveragent-agx` exists, do not overwrite it. Run `git fetch`. Then compare with `git status` and
`git log HEAD..origin/main`.

This guide and the correction of `tools/deploy_model.sh` (commit `d6d09d5`) are on `main` only after the owner merges
the branch `deploy/demo`. Before that merge, clone with `-b deploy/demo`. To check, run
`git log --oneline | grep d6d09d5`: it must give one line.

Make a branch for the changes of the unit. Use the repository-local git identity (no global change):

```bash
git checkout -b deploy/<unit name>
git config user.name osmosishk
git config user.email tonyho@osmosis.com.hk
```

Do not push to `main`. The owner merges the branch.

## 3. Python packages

The venv uses the system packages. Some packages must be in the user site (`~/.local`), with the versions in the header
of `requirements-venv.txt`.

1. Make the venv. Install the venv packages with `--no-deps`. With this option, pip does not install a second copy of
   a package that comes from outside the venv.

   ```bash
   cd ~/driveragent-agx
   python3 -m venv --system-site-packages .venv
   .venv/bin/python -m pip install --no-deps --no-cache-dir -r requirements-venv.txt
   ```

2. Find the packages from outside the venv that are missing:

   ```bash
   python3 - <<'EOF'
   import importlib.metadata as m
   want = {"torch": "2.8.0", "pycuda": "2022.2.2", "pyzmq": "27.1.0", "pycapnp": "2.2.0", "numpy": "1.26.4",
           "onnx": "1.21.0", "httpx": "0.28.1", "httpcore": "1.0.9", "anyio": "4.13.0", "h11": "0.16.0",
           "tensorrt": "10.3.0", "PyGObject": "3.42.1", "PyYAML": "5.4.1", "psutil": "5.9.0", "Pillow": "9.0.1"}
   for k, v in want.items():
       try:
           print(f"{k:10} want {v:9} have {m.version(k)}")
       except m.PackageNotFoundError:
           print(f"{k:10} want {v:9} MISSING")
   EOF
   ```

3. Install each MISSING user-site package (pycuda, pyzmq, pycapnp, onnx, httpx, httpcore, anyio, h11; never torch)
   in the user site. Install them one at a time, with the version of the list. If tensorrt, PyGObject, PyYAML, psutil
   or Pillow is missing, stop. These packages come from JetPack (apt) and need sudo. Write the missing package in the
   report for the owner.

   ```bash
   pip3 install --user --no-deps --no-cache-dir h11==0.16.0      # example; one command for each missing package
   ```

   Do not install or change torch or numpy. Do not change a package that is present with a different version. Write
   that package and its version in the report.

4. Find the dependencies that are still missing. Install them in the same way:

   ```bash
   .venv/bin/python -m pip check
   ```

   On `demo`, `pip check` found two packages that are not in the header: `exceptiongroup` (for anyio and pytest) and
   `annotated-doc` (for fastapi). Install them one at a time:

   ```bash
   pip3 install --user --no-deps --no-cache-dir exceptiongroup==1.3.1
   pip3 install --user --no-deps --no-cache-dir annotated-doc==0.0.5
   ```

5. Check the imports:

   ```bash
   .venv/bin/python -c "import fastapi, uvicorn, httpx, zmq, capnp, yaml, cv2, tensorrt, pycuda.driver, psutil, gi, \
   paho.mqtt, crc32c, numpy, torch; print('imports OK', numpy.__version__, torch.__version__)"
   ```

   Expected: `imports OK 1.26.4 2.8.0`, and `pip check` gives `No broken requirements found.`

## 4. Dashboard password

```bash
cd ~/driveragent-agx
cp .env.example .env
chmod 600 .env
PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
sed -i "s|^AGX_DASH_PASSWORD=.*|AGX_DASH_PASSWORD=$PW|" .env; unset PW
stat -c '%a %n' .env                             # expected: 600 .env
```

Do not show the password in a terminal log, a document or a commit. The user name is `AGX_DASH_USER` in `.env`.

## 5. Values that are specific to a machine

```bash
grep -rn -E '/home/tonyho|agx02|10\.0\.0\.' config/ tools/ systemd/
```

Make sure that each path exists on the new unit. On `demo` the result was:

| Value | Where | Use | On demo |
|---|---|---|---|
| `/home/tonyho/model/jetson_bundle/...` | `config/models.yaml`, `tools/register_existing_models.py` | YOLOPX and DTCP engines and ONNX files | Exist |
| `/home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt` (and `..._nchw_orin.onnx`) | same | `sparsedrive_convnext_orin` (disabled, no adapter) | Missing. Not registered. Two tests fail (step 8). |
| `/home/tonyho/model/system1/system1_deploy.pth` | `tools/register_existing_models.py` | `system1` (disabled, no adapter) | Exists |
| `/home/tonyho/model` | `config/dashboard.yaml` `engines.scan_dirs`, `tools/inspect_engines.py` | engine list on the dashboard | Exists |
| `/home/tonyho/driveragent/logger/video/8003-2026...` | `config/sources.yaml` (mode `file`), `config/sim.yaml` | recordings for the simulator and for mode `file` | `video_root` exists, but the sessions are different. Give the sessions of the unit on the command line (step 9). No change in git. |
| `10.0.0.0/24` | `config/dashboard.yaml` `allow_cidrs` | LAN addresses that can open the dashboard | Make sure that the LAN subnet of the unit is in the list. |
| `/home/tonyho/driveragent-agx` | `systemd/*.service`, `systemd/install_units.sh`, `tools/rk_result_client` (defaults of `--schema` and `--envelope-dir`) | system units, result client | Same path |
| `agx02` | `tools/deploy_model.sh` | default `--host` | On a Jetson with no `--host`, the script now deploys locally (commit `d6d09d5`). |

If the user is not `tonyho`, change all these paths.

## 6. Models

1. Read each engine of `config/models.yaml`:

   ```bash
   PYTHONPATH=. .venv/bin/python -m tools.inspect_engines \
       /home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine \
       /home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine
   ```

   Each enabled engine must show `load OK` and `match True`. The deploy task of `demo` also asked for no line
   `device warning`. The code treats this warning as information only (`common/trt_compat.py`): if it shows, write it
   in the report.

   If an engine of `config/models.yaml` does not load, and agx-infer starts from `config/models.yaml` (no last good set
   in `~/agx-models/_state/last_good.json`), agx-infer builds a new engine from the ONNX file into `engines/` at its
   start (YOLOPX: about 14 minutes). The old engine file stays as it is. With a last good set, agx-infer does not build:
   the model is FAILED. Then build the engine with the controller (`docs/DEPLOY_MODEL.md`).

2. Make the model store and register the models. Do the dry run first:

   ```bash
   PYTHONPATH=. .venv/bin/python -m tools.register_existing_models --dry-run
   PYTHONPATH=. .venv/bin/python -m tools.register_existing_models
   ```

   Compare the sha256 values with `docs/MODELS.md` (YOLOPX engine `3412bafa057a3a76`, DTCP engine
   `1071ea90213eddc2`). A model with a missing file gets an `ERROR` line, and the tool does not write it. The other
   models are written. Exit code 1 is then expected.

3. Put a test frame into the store. The model check needs it (`tools/model_check.py`). Use a front camera frame of
   1280x720 from a recording of the unit:

   ```bash
   mkdir -p ~/agx-models/_testframes
   PYTHONPATH=. .venv/bin/python - <<'EOF'
   import cv2, glob, os
   mp4 = sorted(glob.glob(os.path.expanduser("~/driveragent/logger/video/*/front/cam0_*.mp4")))[0]
   cap = cv2.VideoCapture(mp4); cap.set(cv2.CAP_PROP_POS_FRAMES, 100); ok, bgr = cap.read()
   bgr = cv2.resize(bgr, (1280, 720), interpolation=cv2.INTER_AREA) if bgr.shape[:2] != (720, 1280) else bgr
   cv2.imwrite(os.path.expanduser("~/agx-models/_testframes/front_1280x720.jpg"), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
   print("test frame from", mp4)
   EOF
   ```

4. Check the two DriverGuard models:

   ```bash
   PYTHONPATH=. .venv/bin/python -m tools.model_check ~/agx-models/driverguard_yolopx/1
   PYTHONPATH=. .venv/bin/python -m tools.model_check ~/agx-models/driverguard_dtcp/1
   ```

   Expected: `READY` for the two models. The DTCP check fails when `pred_wp` is not finite (the adapter refuses it).
   When DTCP is not finite, set `enabled: false` with a `reason` for `driverguard_dtcp` in `config/models.yaml`.

## 7. Ports

These ports must be free: TCP 5560-5564 and 8700, UDP 6000-6005.

```bash
ss -Hltnp '( sport >= :5560 and sport <= :5564 ) or ( sport = :8700 )'
ss -Hlunp '( sport >= :6000 and sport <= :6005 )'
```

If there is no output, the ports are free. If an old process uses a port, stop only that process. Do not disable it
and do not delete it. Write the process and its start command in the report.

## 8. Tests

```bash
mkdir -p test_logs
PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/ > test_logs/pytest.txt 2>&1; tail -5 test_logs/pytest.txt
```

Run the tests BEFORE the services start (the tests use the GPU and start dashboards). Two tests compare the files of
the unit with the AGX02 inventory. They fail when the unit has different engine files:

- `tests/test_t1_models_doc.py::test_every_engine_and_tensor_is_in_models_md`: an engine in `/home/tonyho/model` is
  not in `docs/MODELS.md`.
- `tests/test_dashboard_v2.py::test_01_models`: an engine of `config/models.yaml` is missing (the engine cache has one
  entry less).

Each other failure is a real problem. On `demo`: 302 passed, 2 failed (these two), 4 skipped.

## 9. Simulator test (5 minutes)

```bash
tools/svc.sh start dashboard
tools/svc.sh start infer --mode sim
# recordings of the unit (each session: <video_root>/<session>/<role>/camN_*.mp4):
tools/svc.sh start sim --sessions <session 1>,<session 2>,<session 3>
# or, when the unit has no recordings:
#   tools/svc.sh start sim --source test-pattern
PYTHONPATH=. .venv/bin/python -m tools.sysmon --seconds 300 --out /tmp/sysmon_sim.jsonl &
PYTHONPATH=. .venv/bin/python -m tools.rk_result_client --host 127.0.0.1 --seconds 270
tools/svc.sh logs infer 200 | grep -E 'ERROR|Traceback|not finite'
tools/svc.sh stop sim
```

Expected (`demo`): YOLOPX about 7.4 results/s on each camera 0-5, DTCP 10.0 results/s on camera 0, all checks of
`rk_result_client` PASS, no ERROR line in the logs.

## 10. Final state: mode rk

`config/sources.yaml` has `mode: rk`. Keep `config/control.yaml` at `control_mode: bench`. Do not copy `data/` from a
different unit: the tokens and the pairings are for one unit only.

```bash
tools/svc.sh stop infer; tools/svc.sh stop dashboard
tools/svc.sh start dashboard
tools/svc.sh start infer
loginctl --no-ask-password enable-linger "$USER"   # the units then stay after the session ends
loginctl show-user "$USER" -p Linger              # expected: Linger=yes
```

With no paired board, all cameras show NO SIGNAL. This is correct.

## 11. Dashboard check

```bash
curl -s http://<agx address>:8700/api/pair/info          # no password needed (IP allowlist only)
```

Do a check of the APIs with the user and the password of `.env`. The command does not show the password:

```bash
( set -a; . ./.env; set +a
  for p in health models cameras pair/state; do
    printf 'user = "%s:%s"\n' "$AGX_DASH_USER" "$AGX_DASH_PASSWORD" | \
      curl -s -o /dev/null -w "$p %{http_code}\n" -K - "http://<agx address>:8700/api/$p"
  done )
```

Each line must show 200. Open `http://<agx address>:8700/#/settings` in a browser on the LAN. The part RK link shows the button
**Make pairing code**. Make sure that the LAN subnet of the unit is in `allow_cidrs` of `config/dashboard.yaml`.

## 12. After a reboot

The transient user units do not start at boot. Start them again:

```bash
cd ~/driveragent-agx && tools/svc.sh start dashboard
cd ~/driveragent-agx && tools/svc.sh start infer
```

## 13. Owner items (sudo)

- System units: run `bash ~/driveragent-agx/systemd/install_units.sh` as the normal user. Do not use sudo. The script
  asks for the sudo password. It stops the transient user units and starts the system units. It does not enable them
  at boot.
- Start at boot (separate approval): `sudo systemctl enable agx-infer.service agx-dashboard.service`.

## 14. Pair the RK3588 board

Use `docs/CONNECT_AGX.md` (the two dashboards only).
