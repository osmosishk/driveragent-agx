INPUT SOURCE: SIMULATED (1801 of 1801 status samples say simulated; R13)
Samples: sysmon 1830, status 1801. Duration 30.5 min.

| System value | mean | min | max | start (first 60 s) | end (last 60 s) | slope per hour |
|---|---|---|---|---|---|---|
| CPU total % | 32.0 | 28.0 | 40.4 | 32.4 | 31.5 | - |
| GPU load % | 59.3 | 0.0 | 99.9 | 53.4 | 54.6 | - |
| RAM used MB | 9993 | 9920 | 10118 | 9970 | 9962 | -46.4 MB/h |
| Power (sum of rails) W | 26.80 | 22.71 | 35.65 | 27.34 | 26.90 | - |
| Temperature cpu-thermal C | 65.1 | 64.2 | 67.2 | 65.6 | 65.0 | - |
| Temperature gpu-thermal C | 60.4 | 59.1 | 62.4 | 61.0 | 60.3 | - |
| Temperature soc0-thermal C | 61.2 | 60.5 | 61.9 | 61.7 | 61.1 | - |
| Temperature soc1-thermal C | 60.5 | 59.9 | 61.2 | 61.0 | 60.5 | - |
| Temperature soc2-thermal C | 61.4 | 60.8 | 62.4 | 61.9 | 61.4 | - |
| Temperature tj-thermal C | 65.0 | 64.2 | 67.2 | 65.6 | 65.0 | - |
| Power VDDQ_VDD2_1V8AO W | 2.54 | 2.32 | 3.03 | - | - | - |
| Power VDD_CPU_CV W | 3.14 | 2.38 | 6.36 | - | - | - |
| Power VDD_GPU_SOC W | 13.45 | 10.33 | 18.66 | - | - | - |
| Power VIN_SYS_5V0 W | 7.67 | 7.28 | 8.39 | - | - | - |

| Process | RSS start MB | RSS end MB | RSS max MB | RSS slope per hour | CPU % of one core (mean / max) | restarts seen (pid changes) |
|---|---|---|---|---|---|---|
| infer.main | 1633.9 | 1637.1 | 1638.5 | 2.7 MB/h | 279.1 / 303.9 | 0 |
| tools.rk_sim | 76.8 | 83.3 | 83.3 | 8.1 MB/h | 14.8 / 18.1 | 0 |
| dashboard.main | 57.7 | 61.6 | 61.6 | 8.4 MB/h | 4.0 / 26.9 | 0 |

| Camera | source | fps mean / min / max | states (samples) | lost frames (delta) | lost packets (delta) | ring overruns (delta) |
|---|---|---|---|---|---|---|
| cam0 | SIMULATED | 30.1 / 29.0 / 31.0 | SIMULATED: 1801 | 0 | 0 | 0 |
| cam1 | SIMULATED | 30.1 / 29.0 / 31.0 | SIMULATED: 1801 | 0 | 0 | 0 |
| cam2 | SIMULATED | 30.0 / 29.0 / 32.0 | SIMULATED: 1801 | 0 | 0 | 0 |
| cam3 | SIMULATED | 30.0 / 29.0 / 31.0 | SIMULATED: 1801 | 0 | 0 | 0 |
| cam4 | SIMULATED | 29.9 / 28.0 / 31.0 | SIMULATED: 1801 | 0 | 0 | 0 |
| cam5 | SIMULATED | 29.9 / 28.0 / 31.0 | SIMULATED: 1801 | 0 | 0 | 0 |

| Model | source | fps mean / min / max | total latency ms p50 / p95 / p99 (mean of 1 s values) | states (samples) | results (delta) | errors |
|---|---|---|---|---|---|---|
| driverguard_dtcp | SIMULATED | 10.0 / 9.8 / 10.0 | 39.2 / 75.7 / 104.0 | RUNNING: 1801 | 18000 | none |
| driverguard_yolopx | SIMULATED | 43.3 / 36.6 / 51.2 | 62.7 / 96.8 / 119.9 | RUNNING: 1801 | 77895 | none |
| sparsedrive_convnext_orin | SIMULATED | 0.0 / 0.0 / 0.0 | n/a / n/a / n/a | OFF: 1801 | 0 | none |
| system1 | SIMULATED | 0.0 / 0.0 / 0.0 | n/a / n/a / n/a | OFF: 1801 | 0 | none |

Node states (samples): RUNNING: 1801
Node errors seen: none

Client summary (tools.rk_result_client): see the JSON file. Key values:
- exit_code: 0
- rejects: {"result": {}, "status": {}}
- duplicates: 0
