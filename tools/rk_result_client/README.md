# rk_result_client

Example subscriber for the RK3588 agent. It receives the results and the status of the AGX
inference node, checks each message, and measures the latencies.

Interface: `docs/RK_AGX_INTERFACE.md`, sections 4 and 5.

| Channel | Socket | Struct | Schema hash | Rate |
|---|---|---|---|---|
| Results | ZMQ PUB `tcp://<agx>:5560` (the AGX binds, the RK connects) | `AgxPerceptionResult` | `0xafcaff02` | One message for each (model, camera, frame) |
| Status | ZMQ PUB `tcp://<agx>:5561` | `AgxInferStatus` | `0xef12fe49` (schema v2; v1 was `0x9086fa18`) | 1 Hz |

The client takes the expected hashes from the schema file that it loads (`--schema`): use the same
`proto/agx_infer.capnp` as the AGX node (schema version 2 since 2026-10-07).

One ZMQ frame = 32-byte dabus envelope + Cap'n Proto payload (unpacked, single segment).

## 1. What the client does

For each message:

1. `dabus_envelope.unpack()`: it checks the length (32 bytes or more), the magic `0xDA5E`, the
   version `1`, the `len` field and the CRC-32C.
2. It checks `src_board == 1` (AGX), `type_id` (5560 for results, 5561 for status) and
   `schema_hash == dabus_envelope.schema_hash(<schema text>, <struct name>)`.
3. It decodes the Cap'n Proto payload.

When a step fails, the client does not decode the message. It counts a reject with the reason:
`short`, `magic_version`, `length`, `crc`, `src_board`, `type_id`, `schema_hash`, `capnp_decode`,
`multipart`.

Checks:

- No duplicate `(model, camId, frameSeq)`.
- `frameSeq` increases for each `(model, camId)`. A jump back of more than 300 frames is a stream
  restart. The client counts it, but it is not an error. A small jump back is `out_of_order`
  (an error). A uint32 wrap is correct.
- Each camera in `--expect-cams` has one or more results during the run.
- The envelope `seq` gaps (counter for each type_id) show the number of messages that are lost
  after the AGX made them (`envelope_seq_lost`, for information).

Exit code: `0` = all checks pass (results received, all expected cameras, no rejects, no duplicates,
`frameSeq` increases, status received). `1` = one or more checks fail. `2` = setup error (file not
found, bad schema).

R8: the messages have no control values. The client prints no control values.
R13: the client adds the tag `SIMULATED` to each result that has envelope flag bit0
(`source_is_replay`) or the capnp field `simulated = true`. When the two do not agree, the client
gives a warning.

## 2. Dependencies

The client is one file: `__main__.py`. It imports no other project code.

| Item | Use |
|---|---|
| `pyzmq` | SUB sockets |
| `pycapnp` | Load the `.capnp` file, decode the payload |
| Schema file `agx_infer.capnp` | Struct definitions and schema hash text |
| `dabus_envelope.py` | RK reference envelope (`unpack`, `schema_hash`), from `--envelope-dir` |
| `crc32c` (optional) | Fast CRC-32C. The client uses it only when it gives the same check value as the reference. `--crc reference` disables it. |

The pure-Python CRC-32C of `dabus_envelope.py` needs approximately 20 ms for 100 KB on the AGX
(measured: `19.9 ms per 100 KB`). With masks at full rate this can be too slow. Install `crc32c`
on the RK3588 for live runs.

## 3. How to run it on the RK3588

1. Copy the client and the schema to the RK3588:

   ```
   scp -r tools/rk_result_client proto/agx_infer.capnp rk:~/agx_client/
   ```

2. Install the packages (in the RK virtual environment):

   ```
   pip install pyzmq pycapnp crc32c
   ```

3. Run it. Use the RK envelope directory `rk/proto/envelope` (it contains `dabus_envelope.py`).
   Set `--host` to the AGX Link C address `10.42.0.1`. Link C is not configured yet. Until it is,
   use the tailscale address of the AGX, `100.64.0.20` (`docs/RK_AGX_INTERFACE.md` section 2.2).

   ```
   cd ~/agx_client
   python3 rk_result_client/__main__.py --host 10.42.0.1 \
       --schema ~/agx_client/agx_infer.capnp \
       --envelope-dir <RK repo>/rk/proto/envelope \
       --seconds 30 --print --json /tmp/agx_results.json --expect-cams 0,1,2,3,4,5
   ```

On the AGX (from the repository root):

```
PYTHONPATH=. .venv/bin/python -m tools.rk_result_client --host 127.0.0.1 --seconds 10 --print \
    --json tests/out/rk_client.json --expect-cams 0,1,2,3,4,5
```

Options:

| Option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | AGX address |
| `--results-port` / `--status-port` | `5560` / `5561` | `--status-port 0` = no status |
| `--result-type-id` / `--status-type-id` | `5560` / `5561` | Expected envelope `type_id` (= the node port). Use these when you connect to a test port. |
| `--schema` | `/home/tonyho/driveragent-agx/proto/agx_infer.capnp` | Schema file |
| `--envelope-dir` | `/home/tonyho/driveragent-agx/common` | Directory of `dabus_envelope.py` |
| `--crc` | `auto` | `auto` or `reference` |
| `--seconds` | `10` | Run time. `0` = until Ctrl-C. |
| `--print` | off | One line for each result and each status message |
| `--json FILE` | none | Write the summary as JSON |
| `--expect-cams` | none | Comma list of cameras that must have results |

Result line (example from the test, simulated data):

```
22:48:33.229 test_model_sim cam0 seq=1003 det=1 [car:1] traj=0 masks=0 SIMULATED src=test-pattern agx=3.0ms e2e_recv=4.6ms capture=6.6ms
```

Status line: node state, `SIMULATED`, host name, source mode, uptime, result subscribers, result
rate, the measured status interval, each camera (state, fps) and each model (state, fps,
p50/p95/p99 of `totalMs`).

## 4. Latencies

All values are in milliseconds. `t_client_recv` = `time.time_ns()` on the client, just after
`recv()` returns.

| Name | Formula | Meaning | Valid when |
|---|---|---|---|
| `agx_ms` | `tAgxResultNs - tAgxRecvNs` | Time in the AGX: frame received (last fragment) to result complete | Always. One clock (AGX). |
| `e2e_recv_ms` | `t_client_recv - tAgxRecvNs` | Time from frame receive (at the AGX) to result receive (at the client) | Only when the client and the AGX use one clock: same host, or PTP between the boards. |
| `capture_ms` | `t_client_recv - tCaptureNs` | Time from frame capture (sender clock) to result receive (at the client) | Only when the client and the frame sender use one clock. Example: the client runs on the RK3588 and the RK3588 sends the frames, or PTP. |

Envelope flag bit1 `time_uncertain` is set on every AGX message (no PTP yet). When this flag is set
and `--host` is not this host, the client prints a warning: `e2e_recv_ms` then contains the clock
offset between the two boards. The JSON field `latency_validity` gives the same information.
A negative latency (column `negative` in the JSON) is a sign of a clock offset.

`e2e_recv_ms` also includes the time that a message waits in the ZMQ receive queue of the client.
Look at `client_proc_ms`: when it is near the message interval, the client is too slow.

## 5. How to port the checks to rk/hmi bus.py

The RK HMI receiver (`rk/hmi/driveragent_hmi/bus.py`, lines 146-170) already drops messages with a
bad envelope, a wrong `src_board` or a wrong `type_id`. The HMI does not subscribe to 5560 or 5561
yet (`docs/RK_AGX_INTERFACE.md` section 9). To add them:

1. Add `AgxPerceptionResult` (type_id 5560) and `AgxInferStatus` (type_id 5561) to the HMI channel
   list. Load `agx_infer.capnp` and calculate the hashes with `dabus_envelope.schema_hash()`. Do not
   write the hash values as constants.
2. Use the same receive order as `Client.check_envelope()` and `Client.handle_result()`:
   unpack -> `src_board == 1` -> `type_id` -> `schema_hash` -> capnp decode. Count each reject by
   reason. Do not decode a message with a different schema hash.
3. Copy the class `Stream` (method `check_seq`) for the duplicate and `frameSeq` checks. Keep one
   `Stream` for each `(model, camId)`. Drop a duplicate result. Do not drop the result after a
   restart.
4. Show `SIMULATED` on the screen when flag bit0 or the field `simulated` is set (R13).
5. Show `agx_ms` always. Show `e2e_recv_ms` and `capture_ms` only when the clocks are the same
   (`time_uncertain` is 0, or the HMI runs on the same host as the clock source).
6. Use the status message for the "NO PERCEPTION" chip: no status for more than 3 s, or
   `nodeState` is `ERROR` -> no perception.

## 6. Test

```
cd /home/tonyho/driveragent-agx
PYTHONPATH=/home/tonyho/driveragent-agx .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_rk_result_client.py
```

The test uses the real `ResultPublisher` and `StatusPublisher` of `infer/publish` on the test ports
15600 / 15601 (no GPU). It sends simulated results for six cameras, one duplicate and one corrupt
frame. The client logs and JSON files are in `tests/out/rk_result_client_*.{log,json}`.
