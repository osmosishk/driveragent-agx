# Final state check 2026-10-06T05:20:26+01:00
```
$ tools/svc.sh status
  agx-dashboard.service loaded active running driveragent-agx dashboard (transient user unit, night run)
  agx-infer.service     loaded active running driveragent-agx infer (transient user unit, night run)
  agx-sim.service       loaded active running driveragent-agx sim (transient user unit, night run)
agx-infer: MainPID=2067513 NRestarts=0 ExecMainStartTimestamp=Mon 2026-10-05 23:58:36 BST ActiveState=active 
agx-dashboard: MainPID=2067504 NRestarts=0 ExecMainStartTimestamp=Mon 2026-10-05 23:58:36 BST ActiveState=active 
agx-sim: MainPID=2076447 NRestarts=0 ExecMainStartTimestamp=Tue 2026-10-06 00:08:01 BST ActiveState=active 
$ journal warnings/errors of agx-infer, agx-sim, agx-dashboard since the restart 2026-10-05 23:58:30
0
$ python -m tools.model_ctl list
NODE SOURCE MODE: sim   INPUT: SIMULATED
NAME                         STATE    EN  CAMERAS        SOURCE       FPS  P50 ms  RESULTS  ERROR/REASON
driverguard_yolopx           RUNNING  y   0,1,2,3,4,5    SIMULATED   45.4    62.8   837178  
driverguard_dtcp             RUNNING  y   0              SIMULATED   10.0    38.2   193012  
system1                      OFF      n   0,1,2,3,4,5    SIMULATED    0.0       -        0  Not a TensorRT mod
sparsedrive_convnext_orin    OFF      n   0,1,2,3,4,5    SIMULATED    0.0       -        0  Backbone engine on
$ GET /api/health (selected fields)
node_state OK | infer state RUNNING | simulated True | label SIMULATED
cameras [(0, 'SIMULATED', 'SIMULATED'), (1, 'SIMULATED', 'SIMULATED'), (2, 'SIMULATED', 'SIMULATED'), (3, 'SIMULATED', 'SIMULATED'), (4, 'SIMULATED', 'SIMULATED'), (5, 'SIMULATED', 'SIMULATED')]
models [('driverguard_yolopx', 'RUNNING', 46.4), ('driverguard_dtcp', 'RUNNING', 10.0), ('system1', 'OFF', 0.0), ('sparsedrive_convnext_orin', 'OFF', 0.0)]
temps max 65.5 | power W 27.29 | ram used MiB 9442 | uptime h 260.2
link {'ping_ms': 11.7, 'loss_pct': 0.0, 'results_rate_hz': 56.8, 'subscribers': 0, 'clock_offset_ms': None}
```
