INPUT SOURCE: SIMULATED (1868 of 1868 status samples say simulated; R13)
Samples: sysmon 1867, status 1868. Duration 311.0 min.

| System value | mean | min | max | start (first 60 s) | end (last 60 s) | slope per hour |
|---|---|---|---|---|---|---|
| CPU total % | 30.4 | 29.0 | 36.5 | 32.4 | 30.0 | - |
| GPU load % | 63.0 | 0.0 | 99.9 | 87.4 | 37.1 | - |
| RAM used MB | 9862 | 9803 | 10110 | 9963 | 9834 | -21.1 MB/h |
| Power (sum of rails) W | 26.85 | 22.11 | 36.43 | 29.07 | 24.96 | - |
| Temperature cpu-thermal C | 64.7 | 63.7 | 67.6 | 65.8 | 63.9 | - |
| Temperature gpu-thermal C | 60.1 | 58.6 | 62.2 | 61.0 | 59.3 | - |
| Temperature soc0-thermal C | 60.9 | 60.1 | 61.8 | 61.8 | 60.3 | - |
| Temperature soc1-thermal C | 60.2 | 59.5 | 61.1 | 61.0 | 59.7 | - |
| Temperature soc2-thermal C | 61.1 | 60.3 | 62.0 | 61.9 | 60.5 | - |
| Temperature tj-thermal C | 64.8 | 63.7 | 67.6 | 65.8 | 64.0 | - |
| Power VDDQ_VDD2_1V8AO W | 2.54 | 2.22 | 3.03 | - | - | - |
| Power VDD_CPU_CV W | 3.11 | 2.38 | 5.96 | - | - | - |
| Power VDD_GPU_SOC W | 13.54 | 10.32 | 19.46 | - | - | - |
| Power VIN_SYS_5V0 W | 7.67 | 7.18 | 8.39 | - | - | - |

| Process | RSS start MB | RSS end MB | RSS max MB | RSS slope per hour | CPU % of one core (mean / max) | restarts seen (pid changes) |
|---|---|---|---|---|---|---|
| infer.main | 1634.9 | 1636.8 | 1641.2 | 0.4 MB/h | 279.7 / 289.1 | 0 |
| tools.rk_sim | 77.0 | 84.9 | 84.9 | 0.7 MB/h | 14.7 / 16.0 | 0 |
| dashboard.main | 57.7 | 69.2 | 69.2 | 1.3 MB/h | 4.1 / 7.1 | 0 |

| Camera | source | fps mean / min / max | states (samples) | lost frames (delta) | lost packets (delta) | ring overruns (delta) |
|---|---|---|---|---|---|---|
| cam0 | SIMULATED | 30.1 / 29.0 / 31.0 | SIMULATED: 1868 | 0 | 0 | 0 |
| cam1 | SIMULATED | 30.0 / 29.0 / 31.0 | SIMULATED: 1868 | 0 | 0 | 0 |
| cam2 | SIMULATED | 30.0 / 29.0 / 31.0 | SIMULATED: 1868 | 0 | 0 | 0 |
| cam3 | SIMULATED | 30.0 / 28.0 / 31.0 | SIMULATED: 1868 | 0 | 0 | 0 |
| cam4 | SIMULATED | 29.9 / 28.0 / 31.0 | SIMULATED: 1868 | 0 | 0 | 0 |
| cam5 | SIMULATED | 29.9 / 28.0 / 31.0 | SIMULATED: 1868 | 0 | 0 | 0 |

| Model | source | fps mean / min / max | total latency ms p50 / p95 / p99 (mean of 1 s values) | states (samples) | results (delta) | errors |
|---|---|---|---|---|---|---|
| driverguard_dtcp | SIMULATED | 10.0 / 10.0 / 10.0 | 39.2 / 75.4 / 102.7 | RUNNING: 1868 | 186700 | none |
| driverguard_yolopx | SIMULATED | 43.2 / 36.0 / 51.0 | 62.6 / 96.6 / 118.8 | RUNNING: 1868 | 808993 | none |
| sparsedrive_convnext_orin | SIMULATED | 0.0 / 0.0 / 0.0 | n/a / n/a / n/a | OFF: 1868 | 0 | none |
| system1 | SIMULATED | 0.0 / 0.0 / 0.0 | n/a / n/a / n/a | OFF: 1868 | 0 | none |

Node states (samples): RUNNING: 1868
Node errors seen: none

