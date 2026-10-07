# Link settings in the two dashboards - report

Task start: 2026-10-07 21:26:29 CST (DA01 clock). End of the work: 23:30 CST. All times are CST; AGX02 logs use BST
(BST = CST - 7 h). The same report is in the two repositories (driveragent and driveragent-agx, `docs/`). The owner
guide is `docs/CONNECT_AGX.md`.

## 1. Summary

| Task | State | Proof |
|---|---|---|
| P0 Baseline, Section 6 items 1 and 3 | DONE | Window 21:26:33-21:28:38 (section 3). Tests: AGX02 229 passed; DA01 28 PASS, 1 FAIL (router test, before this task). Lists: section 4. Answer to item 3: section 5. |
| P1 One settings file, rule S3 | DONE | `/etc/driveragent/agx_link.json` is the one source on DA01. Reload test 22:44:56: `agx_link_reload no_change trigger=file seq=1`; SIGHUP 22:45:52: `no_change trigger=sighup`; daemon PID 958891 and sender PID 958898 unchanged, sender restarts 0, largest result gap 0.08 s. D1: section 3. Commit DA01 38ebce2. |
| P2 AGX pairing, Settings "RK link", rule S6 | DONE | Migration 22:51:45: the present token became board `rk3588-da01` (hash only, mode 600); the DA01 token works with no new pairing. After the deploy the rk console deactivated `driverguard_dtcp` (last result +0.27 s) and activated it (first result +0.51 s, then 10.02/s). AGX02 suite 274 passed. Commit AGX02 f715271. |
| P3 rk console Settings, tests a-f | DONE | Section 6. a, b (with a limit: no second address of AGX02 is reachable), c, d, e (one defect found and repaired, commit DA01 46289ce), f. |
| P4 Documents | DONE | `docs/CONNECT_AGX.md` and this report in the two repositories. |

End state (window 23:23:04-23:25:08, check 23:26:52): the link is UP with DA01 and AGX02 (unit `agx02`, active and last
good, read from the settings file); YOLOPX 6.8-7.0 results/s on each of the six cameras and DTCP 10.0/s on camera 0;
stale 0 in the window (7 since 22:42, all at the switch of 23:00:52); the test entries are removed from the two lists
(DA01: one unit `agx02`, one token file; AGX02: one paired board `rk3588-da01`).

## 2. Restarts and stops (rule M9, rule S2)

| Time (CST) | Machine | What | Effect |
|---|---|---|---|
| 22:42:55.8 | DA01 | rk-agxlink-bench stop and start (P1: new link service code) | No results 0.88 s; link not UP 5.6 s |
| 22:43:59.3 | DA01 | 5-unit restart (rk-logger, rk-camd, rk-recorder, rk-hmi, rk-hello; P1: new code that reads the AGX address from the one file) | No AGX results 1.09 s; link stayed UP; capture and recording restarted for some seconds |
| 22:51:45 | AGX02 | agx-dashboard restart (P2: pairing code, migration) | Not in the result path |
| 22:52:24.95 | AGX02 | agx-infer restart (P2: source filter from the paired boards) | No results 6.51 s; link UP again 22:52:32.4 |
| 23:03:59.9-23:04:56.4 | AGX02 | agx-infer stop and start (P3d first run) | No results 60.66 s |
| 23:05:59.2-23:06:55.5 | AGX02 | agx-infer stop and start (P3d second run, the test itself) | No results 60.65 s |
| 23:09:05, 23:09:37 | AGX02 | agx-dashboard restart with a 15 s code time, then with the default (P3c) | Not in the result path |

A change of the link settings restarted no service in the tests: a reload, a switch to another unit, Sender ON/OFF and a
fallback stop only the sender child of rk-agxlink (the capture, the HMI and the recorder continue). The restarts in the
table are code deploys and the planned agx-infer stops of test d.

## 3. Numbers before and after

P0 baseline (21:26:33-21:28:38), after P1 (22:46:02-22:48:06), end (23:23:04-23:25:08). Same tools in each window.

| Item | P0 | After P1 | End |
|---|---|---|---|
| YOLOPX results/s per camera | 6.83 | 6.72-6.73 | 6.81-6.82 |
| YOLOPX capture to result p50 / p95 ms | 111-117 / 144-152 | 114-118 / 144-155 | 113-118 / 147-153 |
| DTCP results/s; p50 / p95 ms | 10.00; 72 / 104 | 10.00; 71 / 95 | 10.01; 88 / 110 |
| Link results received / stale / rejected | 6141 / 0 / 0 | 6070 / 0 / 0 | 6079 / 0 / 0 |
| rk-camd cam0 frames/s; sequence gaps | 29.99; 0 | 30.00; 0 | 30.00; 0 |
| rk-camd consumer drops (6 streams, 120 s) | 0 | 6 | 2 |
| HMI frames/s mean (lowest); frame p99 ms | 34.6 (31.2); 66.7 | 21.2 (20.9); 66.8 | 21.0 (20.6); 67.0 |
| DA01 CPU %; MemAvailable MB | 25.1; 5805 | 21.4; 5662 | 22.4; 5657 |
| rk-recorder CPU %; rk-hmi CPU % | 20.1; 22.4 | 19.8; 14.1 | 19.7; 14.0 |
| rk-agxlink CPU %; RSS MB | 16.8; 42.8 | 15.1; 41.6 | 15.6; 40.7 |
| AGX results/s; GPU GR3D %; highest temperature | 51.0; 52.6; 55.9 C | 50.4; 59.5; 55.9 C | 50.9; 57.7; 55.4 C |

Observation (HMI): the HMI has two frame-rate levels on the same screen ("cameras"): about 21 frames/s (frame p50
50 ms) and 32-46 frames/s (frame p50 17-33 ms). After each start in this session it ran at about 21 (16:55, 19:52, 22:46,
23:23). The HMI process that started at 19:51 ran at 32-46 from at least 21:58 until its restart at 22:43 (journal), so
the P0 window caught the higher level. The frame p99 is the same in all windows (66.7-67.0 ms). The link change does not
touch the HMI drawing; the HMI gets the same AGX address value as before. The cause of the two levels is not found.

## 4. Section 6 item 1: each place with an address or a port of the other machine

Before this task. "Now" tells where the value is after this task.

DA01 (driveragent):

| Place | Value | Read by | Now |
|---|---|---|---|
| `/etc/driveragent/board.toml:24` `[hmi.bus] agx_host` | 10.0.0.130 | rk-hmi, rk-hello, rk-logger, rk-recorder, rk-agxlink, rk-agxlink-tx, rk-console (at start) | Removed by the migration (history copy in /etc/driveragent/history). Value in agx_link.json |
| `rk/config/rk.toml:186` `[hmi.bus] agx_host` | 10.42.0.1 | same, when the board file has no value | Comment only |
| `rk/config/rk.toml:322-328` `[agx_link] host`, base_port, results/status/rkcam ports | "", 6000, 5560, 5561, 5564 | rk-agxlink, tx, rk-console | Comments; defaults in `rk/common/agxunits.py`, values per unit in agx_link.json |
| `rk/config/rk.toml:42` `[camd.zmq] camera_health` | tcp://10.42.0.1:5572 (old Link C, went out through the default gateway) | rk-camd | `camera_health = ""` + `camera_health_port = 5572`; host from agx_link.json |
| `rk/config/rk.toml:442-448` `[console.agx_control]` url, token_file | "" (http://host:8700), token path | rk-console | Replaced by agx_link.json and `~/.config/driveragent/agx_tokens/<unit>.token` |
| `rk/boards/rk3588-da01/board.toml:24`, `rk3588-da02/board.toml:14`, `_template/board.toml:23` | 10.42.0.1 | seed files | Comment only |
| `rk/agxlink/agxlink_core.py:47-53` DEFAULTS | host "", 6000, 5560, 5561, 5564 | rk-agxlink | From agxunits.py |
| `rk/agxlink/tx/slot.h:40-42`, `tx/framelink.h:28` | base_port 6000 (kBasePort unused) | rk-agxlink-tx | `--host` and `--base-port` from the daemon; kBasePort removed |
| `rk/agxlink/tx/main.cpp:116-163` | reads agx_host / host / base_port | rk-agxlink-tx | Still a fallback; the daemon always passes `--host` and `--base-port` |
| `rk/console/rkconsole/agxmodels.py:38-39` | AGX_PORT 8700, token path | rk-console | Active unit's host, api port and token |
| `rk/hmi/driveragent_hmi/bus.py:82-83`, `rk/hello/rk_hello.py:113-115`, `rk/logger/rk_logger.py:117` | agx_host (bus ports 5607, 5592, 5588, 5612, 8010, 8014, 5595, 5608, 5609, 5604, 5611; AGX02 opens none of them) | rk-hmi, rk-hello, rk-logger | Through `rk/common/rkconfig.py`: host of the active unit (at start) |
| `rk/recorder/src/main.cpp:104-142, 692, 724-732` | agx_host, ports 5614 / 5613 | rk-recorder | Host from agx_link.json (`rk/common/agx_link_file.h`), at start |
| `rk/setup/owner_net_router.sh:27-28` | AGX_NET 10.42.0.0/24, AGX 10.42.0.1 | owner script (routes of the DA02 router) | Not changed: network configuration (rule S1) |
| Tools: `rk/agxlink/tools/fl_rx.py:267`, `rk/hmi/tools/agx_standin.py:26`, `agx_scenario.py:48` | local test ports and 127.0.0.1 | bench tools | Not changed (local test tools) |
| Units, ops scripts | none | - | No unit holds an address |
| Tests, fixtures, docs | example values | - | Kept (allowed) |

AGX02 (driveragent-agx):

| Place | Value | Read by | Now |
|---|---|---|---|
| `config/sources.yaml:31` `rk_allowed_sources` | 10.0.0.208, 10.0.0.209 | agx-infer (FrameLink source filter, RkCameraInfo allowlist), at start | Removed; the addresses of `data/paired_boards.json`, read again within 1 s |
| `config/dashboard.yaml:23` `rk_ip` and `dashboard/config.py:20` default 100.64.0.180 | 10.0.0.208 | agx-dashboard link monitor (ping, clock offset), at start | Removed; the link monitor pings the paired boards |
| `data/control.token` | the DA01 control token | agx-dashboard | Migrated: board `rk3588-da01` in paired_boards.json (hash only); file kept as `data/control.token.migrated` (600) |
| `config/dashboard.yaml:15-19`, `dashboard/config.py:19`, `dashboard/auth.py:26-31` `allow_cidrs` | 127.0.0.0/8, 10.0.0.0/24, 10.42.0.0/30, 100.64.0.0/10 | agx-dashboard IP allowlist | Not changed: a network allowlist, not a board address |
| `config/infer.yaml:13-24` ports and binds, `config/sources.yaml` camera ports 6000-6005 | the AGX's own ports | agx-infer | Not changed (the AGX's own ports; shown read-only on the Settings page) |
| `config/sim.yaml:12-13`, `tools/rk_sim/config.py:32-33` | 127.0.0.1, 6000 | simulator | Not changed (local simulator) |
| Code comments, tests, docs | example values | - | Kept; one stale comment corrected (`config/infer.yaml:24`) |

## 5. Section 6 item 3: does the AGX need the address of the board?

Only one function needs it: the dashboard link monitor sends ping and an HTTP clock request TO the board, so it must
know where to send (`dashboard/collectors/link.py`, before: `rk_ip` at :30, ping :57, clock :81-101, clockdiff :108). Now
it takes the address of a paired board.

The other uses are filters, not needs:

- FrameLink source filter (agx-infer, `infer/ingest/rx_proc.py:229-241`): with no address, frames from each source are
  accepted; a wrong address blocks all frames.
- RkCameraInfo allowlist (`infer/rkinfo.py`): with no address, each peer can send names; a wrong address blocks them.
- Results and status (5560, 5561): the AGX binds; the board connects. No address is needed.
- Control (the token check in `dashboard/auth.py`): the token identifies the board, not the address.

The AGX learns the board address from the authenticated pairing request (its client address and the addresses that the
board sends) and keeps it in `data/paired_boards.json`. It does not learn addresses from FrameLink or ZMQ peers: those
have no authentication.

## 6. P3 tests (second rk console on port 8702 with the new code, rule M11; AGX02 API)

| Test | Proof |
|---|---|
| a | 23:00:12 unit "Wrong address test", 192.0.2.10. Test: "No TCP connection to 192.0.2.10:8700 (no answer in 3 s). Make sure that the AGX is on and on the same network." Make active: 409 "The unit is not paired. Test it with a pairing code first." |
| b | No second address of AGX02 is reachable from DA01 (its tailnet address 100.64.0.20 does not answer, and there is no DNS name; "agx02" is only an SSH alias of 10.0.0.130). So the second entry has the same address 10.0.0.130. New code: all 6 checks OK. Make active 23:00:52.6: largest gap of the HMI results 0.17 s, link "STARTING" 5.0 s, then "fresh results from 6 camera(s)" (7 old results counted stale). First entry again 23:02:15.7: gap 0.16 s, "STARTING" 5.0 s. Because one board has one pairing per AGX, the second pairing replaced the first token: the first entry's Test said "The AGX does not accept the stored token: pair again with a new code", and a new code repaired it. |
| c | A used code again: "the pairing code is not correct". With a 15 s code time (dashboard restarted with AGX_PAIR_CODE_TTL_S=15, then without it), a code used after 20 s: "this pairing code expired (it works for 15 s)". |
| d | 23:05:58.9 Make active, agx-infer stopped at once (23:05:59.2). 23:06:29.8: back to the last good unit, reason "AGX02 (10.0.0.130) did not send fresh results in 30 s (link DOWN: no AgxInferStatus yet). The link went back to AGX02 second entry." agx-infer started 23:06:55.5; link UP 23:07:01.1. (A first run at 23:03:48 stopped agx-infer too late: the switch had passed after 5 s.) |
| e | 23:10:22 Remove on the AGX side. The rk console control request was refused: "the pairing of board rk3588-da01 was removed on this AGX: this token stops. pair the board again with a new code (AGX02 dashboard: Settings, RK link)". DEFECT: the units table still said "paired". Repaired (commit DA01 46289ce): a refused token sets "not paired". After the repair the table shows "paired False". 23:14:27 pairing again from the rk console: all checks OK, the same control request reaches the model controller again. |
| f | control_mode vehicle 23:14:47: pairing code 409 "AGX02 is in vehicle mode (config/control.yaml): a pairing code is refused"; pairing 409 "... pairing is refused"; removal 409 "... the removal of a pairing is refused"; settings 409 "... a change of the link settings is refused". bench again 23:14:52 (no git difference). |

Also tested: the owner lock file (S7) `locked = true` gave 423 "The link settings are locked (owner file
/etc/driveragent/agx_link_lock)." for Add and Sender (the file is removed again: default off); Sender OFF set the link to
"OFF: sender off by the owner" for 20.3 s, ON brought it back. Audit (S8): 27 `agx.settings.*` rows on DA01 (no secret);
`pair.*` rows on AGX02 with source and user. No pairing code or token is in a log, an answer or a settings file.

## 7. Reviews

Each builder's work had an adversarial review; each high or medium finding was reproduced and repaired before the
deploy:

- Link service: a switch to a unit with no fallback stayed "trial" for ever; a settings write of the console could be
  lost in a write of the daemon.
- rk console: an unfinished "trial" blocked Make active for ever; a new token could be lost when the settings write failed
  after the pairing; a changed address kept the old token; the fallback unit could be changed during a trial.
- C++ readers: a bad `agx_host` value made rk-camd stop before the migration.
- AGX pairing: the old token's 401 answers locked the board out of a new pairing; in vehicle mode a token request could
  add an address; a bad boards file opened the source filter.

## 8. Known limits

- The dashboards use plain HTTP on the local network. The pairing code and the control token go in clear text.
- One board has one pairing per AGX: a new pairing of the same board replaces its old token.
- When no board is paired, agx-infer accepts video from each source (as before).
- rk-camd, rk-recorder, rk-hmi, rk-hello and rk-logger read the AGX address at their start; they use a new active unit at
  their next start. Today they only connect to AGX bus ports that AGX02 does not open.
- A used pairing code gets the reason "not correct", not "already used" (the AGX deletes a code at its first use).
- After Sender ON the link state is "UP, no camera sent" for about 1 s.
- The real rk-console runs the code of 16:44 until the owner step 9.1.
- `systemctl --user kill` cannot signal the transient unit rk-agxlink-bench; `kill -HUP <pid>` works. The file watch
  needs no signal.
- DA01 `rk/router/tests/test_router.py` fails as before this task.

## 9. Owner steps

### 9.1 sudo (DA01)

```
# the new rk console (AGX link, card Settings; the model part uses the active unit and its token)
cd ~/driveragent && rk/console/build.sh && sudo systemctl restart rk-console
# still open from the link task: rk-agxlink as a system unit (now the transient user unit rk-agxlink-bench);
# arms the boot dead-man switch: run commit-boot.sh in the same session after it
cd ~/driveragent && sudo rk/ops/install.sh && sudo rk/ops/commit-boot.sh
rk/agxlink/run_user.sh stop && sudo systemctl start rk-agxlink.service
```

The lock of the link settings (S7) needs no sudo: `echo "locked = true" > /etc/driveragent/agx_link_lock` (remove the
file or write `locked = false` to unlock).

### 9.2 Push (the agent did not push)

```
cd ~/driveragent && git push origin main
cd ~/driveragent-agx && git push
```

New commits: DA01 38ebce2 (P1), 46289ce (P3 repair), and the commit of these documents; AGX02 f715271 (P2) and the commit
of these documents.
