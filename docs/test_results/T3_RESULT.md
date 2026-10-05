# T3 result: RK3588 simulator to AGX ingest (2026-10-05)

## 1. Summary

- T3 (six H.265 streams from the recordings, 300 s): every camera got 30.0 fps with 0 lost packets and 0 lost frames. UDP RcvbufErrors did not increase (+0).
- NV12 (RK design sizes, 60 s, 806 Mbit/s in total): each camera lost 0 to 2 frames of about 1830, which is 0.11 % or less. Before the fixes, cam0 lost 1 to 10 %.
- I fixed 10 of the defects that the reviewers reported. I also fixed 2 new defects that I found. Section 6 gives the list.
- Tests: **33 passed in 42.88 s** (4 test files).
- The simulator plays the default recordings (8003-20260510_151020, _151120, _151220). These recordings show an indoor bench. They are not road video.

## 2. Commands

All commands start in `/home/tonyho/driveragent-agx` with `PYTHONPATH=/home/tonyho/driveragent-agx`.

Tests:
```
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_framelink.py tests/test_h265_decoder.py tests/test_rk_sim.py tests/test_ingest.py
```
(`-p no:cacheprovider` only stops pytest from writing `.pytest_cache`. It does not change the tests.)

T3, 300 s. The script is `scratchpad/t3/run_t3.sh t3_ingest_5min 300 1`:
```
.venv/bin/python -m tools.rk_sim --config config/sim.yaml > tests/out/t3_ingest_5min_sim.log &
sleep 5
tegrastats --interval 5000 > tests/out/t3_tegrastats.log &
.venv/bin/python -m infer.ingest.probe --config config/sources.yaml --seconds 300 \
    --json tests/out/t3_ingest_5min.json > tests/out/t3_ingest_5min_probe.log
kill tegrastats; kill -TERM <sim pid>        # sim rc 0
```
Run time: 22:22:09 to 22:27:16. Ports: UDP 6000-6005.

NV12, 60 s (`run_t3.sh t3_ingest_nv12_60s 60 0 --fmt nv12`):
```
.venv/bin/python -m tools.rk_sim --config config/sim.yaml --fmt nv12 > tests/out/t3_ingest_nv12_60s_sim.log &
sleep 5
.venv/bin/python -m infer.ingest.probe --config config/sources.yaml --seconds 60 \
    --json tests/out/t3_ingest_nv12_60s.json > tests/out/t3_ingest_nv12_60s_probe.log
kill -TERM <sim pid>                          # sim rc 0
```
Run time: 22:30:56 to 22:32:04.

## 3. T3: six H.265 streams, 300 s

Simulator: passthrough of the recorded H.265 (1280x720, 30 fps). It sent 9222 frames per camera with 0 errors, 0 late frames and a longest burst of 6 datagrams. IDR interval of the files: 256 AU (8.53 s), with VPS/SPS/PPS before every IDR.

| cam | role | fps avg / min | kbit/s avg | frames stored | lost packets | lost frames | decode p50 / p95 (ms) | max frame age (ms) |
|---|---|---|---|---|---|---|---|---|
| 0 | front | 30.0 / 29 | 5031 | 9014 | 0 | 0 | 15.2 / 22.4 | 46 |
| 1 | right | 30.0 / 29 | 5031 | 9015 | 0 | 0 | 10.8 / 15.9 | 50 |
| 2 | left | 30.0 / 30 | 5042 | 9015 | 0 | 0 | 8.4 / 9.3 | 27 |
| 3 | right-back | 29.95 / 14 | 5032 | 8985 | 0 | 0 | 19.0 / 23.4 | 54 |
| 4 | left-back | 29.95 / 15 | 5029 | 8985 | 0 | 0 | 20.3 / 24.0 | 57 |
| 5 | back | 29.94 / 15 | 5032 | 8985 | 0 | 0 | 14.9 / 22.9 | 64 |

- Decode p50 and p95 are for the last 300 frames at the end of the run. During the run, the p50 of each 1 s sample was 8.0 to 23.6 ms.
- Max frame age is the highest value in the 1 s samples, measured from `t_ready_mono`.
- Each camera was SIMULATED in all 300 of 300 samples. All frames had source `replay` and `simulated True`.
- Counters with a value of 0 on all cameras: abandoned_frames, bad, seq_resets, ring_overruns, late_datagrams, decoder_errors, decoder_drops, rx_restarts and internal_errors.
- waiting_idr (frames dropped at start before the first random-access picture): 16, 10, 4, 28, 22 and 15.
- Capture to store (time from the simulator appsink to the frame store), p50: 10.4 to 22.6 ms.
- The "fps min" of 14-15 on cam3-5 comes from one 1 s sample. I did not find the cause. A possible cause is the start: the receivers start one after the other and each one waits for its first random-access picture. The difference in "frames stored" agrees with this start order: frames + waiting_idr goes from 9030 (cam0) down to 9000 (cam5), with about 6 frames between cameras.
- The highest p95 in a single 1 s sample was 130 to 304 ms. I did not find the cause.

### CPU (12 cores. "Of one core" means that 100 % is one full core)

| Process | CPU avg | min / max |
|---|---|---|
| System total (probe, all 12 cores) | 15.1 % | 12.7 / 26.3 % |
| System total (tegrastats, mean of the 12 cores) | 14.6 % | single core max 34 % |
| Ingest main process (`infer.ingest.probe`) | 103.0 % of one core | 54.2 / 124.2 % |
| Receive processes, all 6 | 6.75 % of one core | 4.0 / 13.0 % |
| Receive process per camera | 1.06 to 1.19 % of one core each | – |
| Simulator (`tools.rk_sim`) | 15.2 % of one core | 10.6 / 19.1 % |

The CPU clock went from 729 to 2201 MHz (tegrastats).

### GPU

- GR3D load: 0 % in all 300 probe samples and in all 60 tegrastats samples.
- The hardware decoder (NVDEC) is not in GR3D. tegrastats on this system shows no NVDEC field, so I have no NVDEC load value.
- Power (tegrastats, average / max): VDD_GPU_SOC 3575 / 3575 mW, VDD_CPU_CV 1702 / 3178 mW, VIN_SYS_5V0 5143 / 5249 mW.

### RAM

- System RAM used (probe, MemTotal − MemAvailable): 7287.5 MB at start, 7463.3 MB at the end.
- tegrastats RAM: 8240 MB at the first sample, 8273 MB at the last sample, 8337 MB max.
- Ingest process RSS: 39.5 MB before start, 299.7 MB after start, 346.3 MB at the end.
- Separate check (190 s, same streams, test ports 16010-16015): RSS was 425.3 MB after 10 s and 428.0 MB after 190 s (+2.7 MB). I found no steady growth.

### Temperatures

| Zone | start | max | end |
|---|---|---|---|
| cpu | 53.9 °C | 55.0 °C | 54.4 °C |
| tj | 53.9 °C | 55.0 °C | 54.4 °C |
| soc0 / soc1 / soc2 | 50.0 / 50.1 / 49.6 °C | 50.9 / 50.8 / 50.4 °C | 50.6 / 50.6 / 50.4 °C |

The probe (1 s samples) measured a maximum of 55.81 °C.

## 4. NV12 test: RK design sizes, 60 s

Simulator: `--fmt nv12`. cam0 is 1280x720 (156 datagrams per frame) and cam1-5 are 704x396 (48 datagrams per frame), with stride = width. The simulator sent 2007 frames per camera with 0 errors, 0 late frames and a longest burst of 7 datagrams. The datagrams of one frame took 24.2 ms (cam0) and 7.3 to 10.2 ms (cam1-5).

| cam | size | fps avg / min | kbit/s avg | frames stored | lost packets | lost frames | max frame age (ms) | capture to store p50 (ms) | receive process CPU |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 1280x720 | 29.97 / 29 | 332509 | 1835 | 32 | 2 | 24 | 25.9 | 13.2 % |
| 1 | 704x396 | 30.0 / 30 | 100612 | 1831 | 0 | 0 | 28 | 10.9 | 5.7 % |
| 2 | 704x396 | 29.98 / 29 | 100492 | 1822 | 7 | 1 | 24 | 9.4 | 5.4 % |
| 3 | 704x396 | 29.97 / 29 | 100478 | 1813 | 19 | 2 | 24 | 8.0 | 5.0 % |
| 4 | 704x396 | 30.0 / 30 | 100556 | 1807 | 0 | 0 | 25 | 8.6 | 5.4 % |
| 5 | 704x396 | 30.0 / 30 | 100444 | 1800 | 0 | 0 | 33 | 11.0 | 5.6 % |

- There is no decode step for NV12 (decode_ms is not applicable).
- Each lost frame is an abandoned frame: some of its fragments did not arrive (missing_frames 0, ring_overruns 0). UDP RcvbufErrors: +58.
- CPU: system total 23.1 %, ingest main process 18.0 % of one core, the six receive processes 40.2 % of one core, and the simulator 124.6 % of one core.
- RAM used: 7377.0 MB at start, 7473.7 MB at the end. Max temperature: 54.75 °C.
- Other NV12 runs: an earlier 60 s run (before the `start_partial` fix) had cam0 2 lost frames, cam1-5 0 lost frames and RcvbufErrors +56. A 30 s run on test ports 16010-16015 stored 902 of 902 frames per camera, with 0 lost and RcvbufErrors +0.
- Before the fixes (builder and reviewer runs): cam0 lost 29 to 84 frames per run (1 to 10 %), with RcvbufErrors +653.

## 5. Tests

```
.................................                                        [100%]
33 passed in 42.88s
```
New tests (in `tests/test_ingest.py` and `tests/test_rk_sim.py`), with their real output:
- `test_shm_reassembler_restart_and_late_window`: `restart: {'late': 1, 'new_streams': 2, 'bad': 48}`
- `test_process_mode_restart_pause_and_rx_kill` (port 16061):
  - `pause: {'frames': 20, 'lost_frames': 0, 'lost_fragments': 0, 'abandoned_frames': 0, ...}`
  - `restart: {'frames': 35, 'lost_frames': 0, ..., 'seq_resets': 1, 'late_datagrams': 0, 'new_streams': 1, ...}`
  - `rx kill: restarted after 0.65 s: {'frames': 45, ..., 'rx_restarts': 1, 'datagrams': 2160}`
- `test_seq_reset_resyncs_h265_gate`: `after restart: pushed [7, 8] seq_resets 1 waiting_idr 6`
- `test_rejected_frames_count_as_lost_and_foreign_frames_do_not`: `{'lost_frames': 2, 'bad_frames': 2, 'foreign_frames': 1, 'missing_frames': 0}`
- `test_thread_reassembler_duplicate_after_complete_is_not_loss`: `{'lost_fragments': 0, 'abandoned_frames': 0, 'late_datagrams': 1}`
- `test_decoder_close_releases_fds`: `fds before 13 after 4 create/close 13`
- `test_start_in_middle_of_frame_is_not_loss[shm|thread]`: `start_partial, abandoned, lost_fragments = (1, 1, 1)`
- `test_sender_no_catch_up_burst`: `datagrams 156, max back-to-back after the stall 4, max_burst_seen 5, frame spread 24.4 ms`

## 6. Defects fixed

| # | Severity | Defect | Fix | Evidence after the fix |
|---|---|---|---|---|
| 1 | High | `rx_proc.py`: the 1000-frame "late" window dropped a restarted stream for as long as the first run lasted. No counter showed the drops. | A fragment is "late" only when it is 8 frames or less behind the last complete frame. A larger jump back, or data after the socket was quiet for 0.2 s, starts a new stream (`new_streams`). `late` goes to the main process (`late_datagrams`). | Simulator restart, real end-to-end run on ports 16010-16015: SIMULATED again after **0.28 s** (the reviewer measured 10.59 s before the fix). 602 of 602 frames stored, `seq_resets 1`, `new_streams 1`, `late 0`. |
| 2 | Medium | A seq reset did not resync the H.265 gate. P-frames of a new stream went to the old decoder state. | On a seq reset the gate waits for an IDR with VPS/SPS/PPS again. A receiver start also makes a new gate. | Test: only seq 7 (IDR) and seq 8 go to the decoder. |
| 3 | Medium | Process mode: a sender pause inside a frame counted lost frames and lost fragments, although no datagram was lost. | The receive loop does not abandon a partial frame because the socket is quiet. | Test with a 0.6 s pause in a frame: 20 of 20 frames, `lost 0`, `abandoned 0`. |
| 4 | Medium | `sender.py`: a late sender thread sent the rest of the frame in one burst (up to 1.39 MB). | Each datagram is due one gap after the previous one. A late thread can catch up by at most 4 datagrams. The status line shows `burst`. | 5 ms stall: the old sender sent 39 datagrams back-to-back, the new sender sends 4. In the T3 runs the longest burst was 6 (H.265) and 7 (NV12). NV12 loss went from 1-10 % to 0.11 % or less. |
| 5 | Medium | `H265Decoder.close()` leaked the pipeline (2 sockets per decoder). | Disconnect the `new-sample` handler and release the references. `FileSource.stop()` had the same pattern and has the same fix (I did not measure it separately). | Old code: +2 sockets per decoder (+10 after 5 decoders). New code: +0. |
| 6 | Medium | A receive process that stopped (crash or kill) was not started again. The camera stayed NO SIGNAL. One exception could stop the receive thread without an error. | A supervisor starts the process again with a backoff (0.5 s, doubled up to 5 s). The counters continue to add up across restarts (`rx_restarts`). Each frame and datagram is handled in try/except, and exceptions are counted in `internal_errors`. | SIGKILL of the receive process: restarted after 0.65 s and frames came again (`rx_restarts 1`). |
| 7 | Low | `decode_ms` included the CPU copy of the NV12 frame. | The time is taken when the appsink callback starts. | – |
| 8 | Low | Frames rejected for NV12 size or an unknown fmt were not in `lost_frames`. A frame of another camera counted as bad. | Rejected frames count in `lost_frames`. A frame of another camera counts in `foreign_frames` and is not a loss. | Test: `lost 2, bad 2, foreign 1, missing 0`. |
| 9 | Low | A caller without a `__main__` guard got an empty error message. | The message now gives the exit code and tells the caller to use `if __name__ == "__main__":`. The module docstring also says this. | – |
| 10 | Low | Thread mode: the `common/framelink.py` Reassembler counted a duplicate fragment of a complete frame as a loss. | `LateFilterReassembler` in `framelink_rx.py` drops these fragments before the reference code sees them. I did not edit `common/`. | Test: `lost_fragments 0, late_datagrams 1`. |
| 11 | New | When the receiver started in the middle of a frame, that first partial frame counted as a loss (NV12: `lost pkt` 10-31 with `lost frames 0`). | The first partial frame counts in `start_partial`, not as a loss. | Test in both receive modes: `(1, 1, 1)`. A real loss later is still counted. |
| 12 | New | The receive process accepted a fragment with the cam field of another camera. | The fragment counts as `bad`. | Test: 48 bad, 0 abandoned. |

Not reproduced: "the simulator did not stop with `--transcode`" happened in one builder run only. The robustness reviewer ran 5 transcode runs and all stopped with rc 0. I did not run transcode again.

Not fixed (`common/` is read-only for me): the bug in `common/framelink.py` `Reassembler.push` (a duplicate or late fragment of a complete frame opens a new frame and later counts as lost) is still there for other users of `common/`. The owner of `common/` must fix it. Use the rule of fix 1.

## 7. Known limits

1. **The default video is an indoor bench, not road video.** For road video use `--sessions road` (in those files cam4 and cam5 are almost black).
2. **CPU of the ingest main process.** For six H.265 1280x720 streams, the main process uses about 103 % of one core (max 124 %). Most of it is the CPU copy of the decoded NV12 frames. Model code in the same process will compete for this CPU.
3. **Decode time under load.** With six streams, the decode p50 is 8 to 20 ms per camera. With one camera it is 9.1 ms. I did not find the cause of the single-sample p95 values of 130-304 ms.
4. **NV12 loss.** The loss is 0.11 % or less per camera at 806 Mbit/s with rmem_max 212992 B. The sender bursts are now 7 datagrams or less. The remaining loss is probably caused by short stalls of the receive processes, but I did not prove this. The CPU clock is often at 729 MHz. RK design NV12 must be checked again with the real RK3588 and Link C.
5. **Two senders on one port are not supported.** By mistake, a simulator from a failed first attempt ran during one T3 attempt, so two simulators sent to ports 6000-6005. The ingest then gave about 2 fps per camera, `seq_resets` of about 9000 and `lost_frames` of about 5.2 million (each seq jump forward counts as lost frames). I repeated the run without the second simulator. The data of the bad run is in `tests/out/fault_two_sims_*`. A dashboard alarm for a high `seq_resets` rate (more than 1 per second) would show this fault.
6. **GPU load does not include NVDEC.** GR3D was 0 % and tegrastats shows no NVDEC field.
7. **rk mode is not tested with a real RK3588.** Link C (10.42.0.1) is not set up on this AGX.
8. **Start of an H.265 passthrough stream.** The IDR interval of the recordings is 256 AU (8.53 s). In T3 the ingest dropped 4 to 28 frames per camera before the first picture. After a sender restart, the ingest waits for an IDR with VPS/SPS/PPS. If the first IDR of the new stream is lost, the wait can be up to 8.5 s.
9. **Data sets.** The T3 300 s run was done before fix 11 (`start_partial`). That fix changes only a counter that was 0 in T3 (abandoned_frames 0 on all cameras). Thus the T3 JSON has no `start_partial` key, but its values are correct. The NV12 JSON is from the final code. The old file `tests/out/ingest_probe_sim_h265.json` is from an older ingest version.
10. **Thread mode** (`rx_process: false`) is still only for tests and H.265. Process mode is the default.

## 8. Files

Changed:
- `infer/ingest/rx_proc.py`: late window, new stream detection, no abandon on a quiet socket, cam check, `start_partial`, extended stats message.
- `infer/ingest/framelink_rx.py`: receive-process supervisor, `LateFilterReassembler`, gate resync on a seq reset, lost-frame accounting, `foreign_frames`, try/except, start error message.
- `infer/ingest/h265_decoder.py`: `close()` releases the pipeline, `decode_ms` timing.
- `infer/ingest/file_source.py`: `stop()` releases the pipeline.
- `infer/ingest/metrics.py`: new counters (`late_datagrams`, `new_streams`, `foreign_frames`, `rx_restarts`, `internal_errors`, `start_partial`).
- `infer/ingest/probe.py`: CPU per receive process, new counters in the JSON.
- `tools/rk_sim/sender.py`: pacing with no catch-up burst, `max_burst_seen`.
- `tools/rk_sim/sim.py`: `burst` in the status line.
- `config/sources.yaml`, `config/sim.yaml`: comments.
- `tests/test_ingest.py`, `tests/test_rk_sim.py`: 9 new test cases (24 before, 33 now).

Output in `tests/out/`:
- `t3_ingest_5min.json`, `t3_ingest_5min_probe.log`, `t3_ingest_5min_sim.log`, `t3_tegrastats.log`
- `t3_ingest_nv12_60s.json`, `t3_ingest_nv12_60s_probe.log`, `t3_ingest_nv12_60s_sim.log`
- `t3_pytest.log`
- `fault_two_sims_*` (the bad run with two simulators)

Cleanup: no simulator, ingest, probe or tegrastats process is left. No UDP port 6000-6005, 16000-16099 or 18000-18099 is open, and no `psm_` segment is left in /dev/shm.
