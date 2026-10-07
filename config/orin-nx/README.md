# Orin NX single-camera unit (hostname `orin-nx`)

Branch rule (Tony, 2026-10-07): `nx/local-source` is a long-lived branch. It is the inference service of the
single-camera Orin NX unit. It is never merged into `main`, and there is no PR to `main`. The unit installs from
`nx/local-source` only. Updates go one way: `main` is merged into `nx/local-source` when Tony tells. After each
merge: run the tests and the reboot proof, then report.

The HMI of the unit follows the same rule: repo `driveragent-hmi`, branch `nx/single-cam`
(`rk/docs/JETSON_PORT.md` and `rk/docs/VEHICLE_TEST.md` there).

## What the branch adds

Source mode `local`: the node reads NV12 frames from the frame socket of the camera daemon on the same board.
There is no network, no encode, and no decode. The models, the adapters, and the publishers are unchanged.

New files (no merge conflict possible):
- `infer/ingest/local_source.py`
- `config/orin-nx/infer.yaml`, `sources.yaml`, `models.yaml`, this file

Shared files that the branch edits (a merge of `main` can conflict here):

| Shared file | Edit |
|---|---|
| `infer/ingest/ingest.py` | Mode `local` in `MODES`; the `LocalSource` for one camera; `no_source` (cameras the unit does not have). |
| `infer/main.py` | `--mode local`. |
| `infer/publish/status.py` | Mode `local` is live, as `rk`; a camera in `no_source` is not a reason for `DEGRADED`. |

## Start (by hand; no unit is installed)

```
bash ~/da-bench/driverguard.sh start|stop|status
```

The models are the engines of `driverguard@1.0.1` in `/opt/driveragent/models` (read only; `models.yaml` names
the two files). Tests after a merge:

```
~/da-bench/agx_venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_ingest.py tests/test_publish.py \
    tests/test_manager.py tests/test_rkinfo.py tests/test_envelope.py tests/test_repo_rules.py
```
