INPUT SOURCE: SIMULATED (301 of 301 status samples say simulated; R13)
Samples: sysmon 310, status 301. Duration 5.2 min.

| System value | mean | min | max | start (first 60 s) | end (last 60 s) | slope per hour |
|---|---|---|---|---|---|---|
| CPU total % | 38.2 | 35.3 | 42.8 | 38.3 | 38.2 | - |
| GPU load % | 65.5 | 0.0 | 99.9 | 58.0 | 63.5 | - |
| RAM used MB | 10098 | 9991 | 10243 | 10029 | 10150 | 1726.4 MB/h |
| Power (sum of rails) W | 27.43 | 23.41 | 35.06 | 27.48 | 27.55 | - |
| Temperature cpu-thermal C | 65.8 | 65.0 | 67.3 | 65.5 | 66.0 | - |
| Temperature gpu-thermal C | 60.9 | 59.8 | 62.3 | 60.6 | 61.1 | - |
| Temperature soc0-thermal C | 61.8 | 61.2 | 62.2 | 61.5 | 62.0 | - |
| Temperature soc1-thermal C | 61.1 | 60.7 | 61.6 | 60.9 | 61.3 | - |
| Temperature soc2-thermal C | 62.1 | 61.5 | 62.6 | 61.8 | 62.2 | - |
| Temperature tj-thermal C | 65.8 | 65.1 | 67.3 | 65.5 | 66.0 | - |
| Power VDDQ_VDD2_1V8AO W | 2.57 | 2.32 | 2.93 | - | - | - |
| Power VDD_CPU_CV W | 3.56 | 2.78 | 6.36 | - | - | - |
| Power VDD_GPU_SOC W | 13.54 | 10.73 | 18.27 | - | - | - |
| Power VIN_SYS_5V0 W | 7.76 | 7.38 | 8.29 | - | - | - |

| Process | RSS start MB | RSS end MB | RSS max MB | RSS slope per hour | CPU % of one core (mean / max) | restarts seen (pid changes) |
|---|---|---|---|---|---|---|
| infer.main | 1630.4 | 1630.8 | 1634.2 | 4.5 MB/h | 204.8 / 225.7 | 0 |
| tools.rk_sim | 548.1 | 700.0 | 703.3 | 2228.9 MB/h | 119.1 / 132.2 | 0 |
| dashboard.main | 57.0 | 57.5 | 57.6 | 7.1 MB/h | 3.7 / 16.5 | 0 |

| Camera | source | fps mean / min / max | states (samples) | lost frames (delta) | lost packets (delta) | ring overruns (delta) |
|---|---|---|---|---|---|---|
| cam0 | SIMULATED | 29.9 / 28.0 / 31.0 | SIMULATED: 301 | 53 | 757 | 0 |
| cam1 | SIMULATED | 30.0 / 29.0 / 31.0 | SIMULATED: 301 | 1 | 9 | 0 |
| cam2 | SIMULATED | 30.0 / 28.0 / 31.0 | SIMULATED: 301 | 7 | 63 | 0 |
| cam3 | SIMULATED | 30.0 / 29.0 / 31.0 | SIMULATED: 301 | 1 | 2 | 0 |
| cam4 | SIMULATED | 29.9 / 29.0 / 31.0 | SIMULATED: 301 | 1 | 3 | 0 |
| cam5 | SIMULATED | 29.8 / 29.0 / 31.0 | SIMULATED: 301 | 1 | 6 | 0 |

| Model | source | fps mean / min / max | total latency ms p50 / p95 / p99 (mean of 1 s values) | states (samples) | results (delta) | errors |
|---|---|---|---|---|---|---|
| driverguard_dtcp | SIMULATED | 10.0 / 10.0 / 10.0 | 53.4 / 75.8 / 90.1 | RUNNING: 301 | 3000 | none |
| driverguard_yolopx | SIMULATED | 44.7 / 38.2 / 53.2 | 61.6 / 89.7 / 107.2 | RUNNING: 301 | 13420 | none |
| sparsedrive_convnext_orin | SIMULATED | 0.0 / 0.0 / 0.0 | n/a / n/a / n/a | OFF: 301 | 0 | none |
| system1 | SIMULATED | 0.0 / 0.0 / 0.0 | n/a / n/a / n/a | OFF: 301 | 0 | none |

Node states (samples): RUNNING: 301
Node errors seen: none

Client summary (tools.rk_result_client): see the JSON file. Key values:
- exit_code: 0
- rejects: {"result": {}, "status": {}}
- duplicates: 0
