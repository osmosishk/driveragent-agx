# Model controller on AGX02, model selection from DA01, one design - short report

Task start: 2026-10-07 16:54:36 CST. The owner changed the plan at about 20:16 CST: complete the N6 step, write this
short report, commit, do not push, stop. All times are CST (DA01 clock). AGX02 logs use BST (BST = CST - 7 h).
The same file is in the two repositories: DA01 `~/driveragent/docs/MODEL_CONTROLLER_REPORT.md` and AGX02
`~/driveragent-agx/docs/MODEL_CONTROLLER_REPORT.md`.

## 1. Tasks

| Task | State | Proof (short) |
|---|---|---|
| N1 Baseline | DONE | Window 16:55:00-16:57:04: YOLOPX 6.97 results/s per camera, capture-to-result p50 112-115 ms, p95 141-150 ms; DTCP 10.00/s; stale 0. AGX02 suite 145 passed. DA01 suite: all steps pass except the router test (fault from before this task, section 4). |
| N2 Model store, states, checks, catalog API (read) | DONE | The four models show with the correct state and reason (yolopx@1 and dtcp@1 ACTIVE, system1@1 and sparsedrive_convnext_orin@1 NO ADAPTER). The two active models stayed active. AGX02 suite 171 passed. Commit AGX02 4f8b996. |
| N3 Build, activate, deactivate, rollback, deploy tool, rules M3-M7 | DONE | a: DTCP stops 0.33 s after deactivate, comes back 0.65 s after activate. b: yolopx@2 deployed, built (1186 s), active with yolopx@1: labels "1:3412bafa..." and "2:e87c9c79...". c: SparseDrive refused (NO ADAPTER). d: vehicle mode refuses each change with the reason. e: after an agx-infer restart, the last good set loads. AGX02 suite 200 passed. Commit AGX02 14c5974. |
| N4 Status to DA01, camera names from DA01 | DONE | DA01 decodes status version 2 (catalog, active set, last good set, control mode). AGX02 shows the DA01 names; "role unconfirmed" only for cameras 1-5 (DA01 has no role for them). AGX02 suite 214 passed. Commits DA01 1946127, AGX02 8a6e557. |
| N5 rk console Models part, Overview AGX card, HMI | DONE | Tests N3a and N3d from the rk console UI (second console on port 8702, rule M11): DTCP stops 0.22 s after Deactivate and comes back 0.37 s after Activate; vehicle mode: three refusals with the AGX02 reason. Audit entries on the two machines. HMI: model labels and the pick button for two versions on one camera. DA01 suite 28 PASS, 1 FAIL (router, from before). Commit DA01 48babb1. |
| N6 One design | PARTIAL | DONE: one token file (DA01 commit 3844c00; the built rk console CSS is identical except 59 new tokens); AGX02 copy with the source commit; new AGX02 dashboard (sidebar, 8 pages, Models controls and audit list, information controls, all old values kept). AGX02 suite 229 passed in the live tree; commit AGX02 d534500; agx-dashboard restarted 20:17:01. NOT DONE: the pictures in the report (section 4). |
| N7 30-minute run, full report | NOT DONE | Stopped by the owner (section 4). This short report replaces the full report. |

Check after the last restart (20:17:19-20:17:26): link UP; active set = last good set; DTCP 10.0 results/s on
camera 0; YOLOPX 7.0-7.2 results/s on each camera 0-5; capture-to-result p95 130-153 ms; rejected 0; stale 1 of
246 680 results since 19:00.

## 2. Restarts (rule M9)

| Time (CST) | What | Effect |
|---|---|---|
| 17:46:34, 17:49:45 | agx-dashboard (N2 deploy) | No stop of the results |
| 18:10:24.7 | agx-infer restart 1 (N3 deploy) | No results 6.09 s |
| 18:11:43 | agx-dashboard (N3 deploy) | No stop of the results |
| 18:41:25.7 | agx-infer restart 2 (N3 test e) | No results 6.10 s |
| 19:00:47.5 | DA01 rk-agxlink-bench stop and start (N4: status versions 1 and 2) | No results to the HMI 0.86 s; link not UP 5.6 s |
| 19:27:42 | agx-dashboard (N4 deploy) | No stop of the results |
| 19:28:09.3 | agx-infer restart 3 (N4 deploy) | No results 6.28 s |
| 19:50:16-19:51:04 | DA01 display takeover (lightdm start and stop) for HMI pictures | Kiosk HMI off 48 s; capture and recording continued |
| 19:51:02 | DA01 5-unit restart (rk-logger, rk-camd, rk-recorder, rk-hmi, rk-hello) | Kiosk back with the N5 HMI code; no AGX results 1.29 s; capture and recording restarted |
| 20:17:01 | agx-dashboard (N6, owner step 1) | No stop of the results |

Stale results: 0 in each measured restart window. Two restart commands for DA01 ran on AGX02 by mistake at 18:58 and
18:59 (the gap tool sends its steps with ssh). AGX02 answered "not found". Nothing changed.

## 3. The 4 defects that the N6 reviewers found, and the repairs

All in `dashboard/static/app.js` and `index.html` of AGX02 (commit d534500).

1. High - Rollback dialog: when GET /api/models/control failed, the dialog read it again with no delay (about 235
   requests in 2 s), and the refusal reason was cleared. Repair: one read of the control document each time the
   dialog opens; a failed read shows "cannot read /api/models/control: <reason>"; a background refresh does not clear
   the error line. Check: 2 requests in place of 235; the 503 reason stays.
2. Medium - The Models table was built again about once a second: the keyboard focus went away, some clicks on
   Build, Activate, Deactivate and details were lost, and text in the open details could not be selected. Repair:
   rows are updated by key, and only a changed row group is replaced; a row group with selected text is not replaced;
   the focus moves to the new button; the page does not render while a mouse button or a finger is down; one 2 s
   timer for the two model requests. Check: focus kept for 4.5 s; 0 of 8 held clicks lost.
3. Medium - Browser Back while a confirmation dialog was open left a modal dialog that could not be seen, and the
   page did not take clicks. Repair: the dialog is outside the page sections; a page change closes it. Check: after
   Back there is no modal dialog and the navigation works.
4. Medium - Settings: the control mode badge showed an old value from the catalog and did not use the control
   poll. Repair: the control fields come from the newer of the catalog and control documents (by their time).
   Check: when the mode changed to vehicle, Settings showed "Vehicle: changes are refused".

Also in d534500: the audit list shows browser time, as the other times on the page.

The reviews of N4 and N5 found other defects. They are repaired too:
- N4 DA01 rk-agxlink (1946127): no per-camera rate window for a model instance that is not kept (memory growth with a
  faulty AGX).
- N4 AGX02 status (8a6e557): one file name that is not UTF-8 stopped every status message (now valid UTF-8 and
  limited texts); an old controller snapshot kept a "change in progress" (now only a snapshot of the last 30 s); the
  control mode comes from config/control.yaml; fallback camera texts and schema comments corrected.
- N5 (48babb1): rk console server: an AGX02 error answer that stalls gave a 500 with no audit row (now 502 with an
  audit row); a test console used the real token (now the token is next to the console password file). rk console
  UI: AGX02 errors and a missing token show their text. HMI: the pick buttons show for each visible camera.

## 4. Not done

- Pictures (N6 test): not in the report and not in the repositories. Pictures were taken before the change of plan
  (N5 tests 19:33-19:52; the pages of the two dashboards 20:05-20:10). They are only in the DA01 agent scratchpad
  (a temporary folder) and are not checked.
- 30-minute run (N7): it started at 20:13:34 and was stopped at 20:16:37 (owner instruction). No number from it is
  used. The leftover AGX02 measure processes were stopped by PID.
- Live test of rule M6 (watchdog rollback): not done. Unit tests cover it (tests/test_model_actions.py).
- The real rk-console runs the old code until the owner restarts it (section 5).
- Known faults from before this task: DA01 rk/router/tests/test_router.py (its child "rk_router.py run --duration 5"
  does not stop; router step FAIL).
- Left on the machines: AGX02 `~/driveragent-agx/ref/n6_tree` (git-ignored N6 test tree with a test `.env` that has a
  random password, not the real one); DA01 browser for UI tests `/mnt/nvme/driveragent/opt/pw-browsers` (662 MB);
  DA01 control token copy `~/.config/driveragent/agx_control.token` (mode 600, needed by the rk console).

## 5. Owner steps

### 5.1 sudo (DA01)

```
# load the N5/N6 rk console code (the control token is already in ~/.config/driveragent/agx_control.token)
cd ~/driveragent && rk/console/build.sh && sudo systemctl restart rk-console
# from the link task, still open: rk-agxlink as a system unit (now the transient user unit rk-agxlink-bench)
cd ~/driveragent && sudo rk/ops/install.sh
```

### 5.2 Push (the agent did not push)

```
# DA01: commits 1946127 (N4), 48babb1 (N5), 3844c00 (N6) and this report
cd ~/driveragent && git push origin main
# AGX02: commits 4f8b996 (N2), 14c5974 (N3), 8a6e557 (N4), d534500 (N6) and this report
cd ~/driveragent-agx && git push
```

### 5.3 Other

- AGX02 `config/control.yaml` is `control_mode: bench`. Set `vehicle` before the vehicle drives (rule M7).
- `driverguard_yolopx@2` (the N3b test copy, READY, not active) stays in the store: no function deletes a model
  (rule M2). Optional, by hand: `~/agx-models/driverguard_yolopx/2`.
- Optional: `rm -rf ~/driveragent-agx/ref/n6_tree` on AGX02.
