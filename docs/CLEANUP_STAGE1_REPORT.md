# AGX02 cleanup stage 1 and start at boot - report

Task "AGX02 cleanup stage 1 and start at boot, HMI frame-rate test, DA01 journal" (2026-10-09). The DA01 parts (journal, HMI frame rate) are in `driveragent-hmi/docs/HMI_FPS_AND_JOURNAL_REPORT.md`.

Times: AGX02 shows BST (UTC+1), DA01 shows CST (UTC+8). 07:00 BST = 14:00 CST.

## 1. Summary

| Part | State | Proof |
|---|---|---|
| A1.1 state before | DONE | Section 3 (values of 2026-10-09 06:57-07:02 BST) |
| A1.2 table of stage 1 | DONE | Section 4 (dry run of `ops/cleanup/stage1_disable.sh`, 13 items in group `base`) |
| A1.3 check against rule Z3 | DONE | Section 5: group `base` disables no Z3 item and no port, device or file of the new software |
| A1.4 SAVE FIRST repositories | DONE | Section 6: stage 1 deletes nothing, so they do not block this task |
| A1.5 start at boot | DONE (user part; no start limit after the review) | Section 7: unit files in `~/.config/systemd/user`, links in `default.target.wants`; undo tested. Linger: owner step |
| A1.6 acceptance script | DONE | `ops/accept_stage1.sh`; before values in `tests/out/stage1/before_agx.json` (folder ignored by git: machine data) |
| Stage 1 (owner) | WAITING FOR OWNER | - |
| Reboot and section 5 acceptance | WAITING FOR OWNER | - |

`main` of this repository was 5 commits ahead of `origin/main` at the start (rule Z6: not pushed; the work continues on the local commits).

## 2. Important facts found before stage 1

1. `agx-infer` and `agx-dashboard` run as **TRANSIENT** user units (`tools/svc.sh`, night run 2026-10-07 18:19-18:20 BST). A transient unit has no unit file and does not start at boot. `systemctl --user enable` refuses a transient unit ("Unit ... is transient or generated"). Thus I wrote the unit files from the templates of `ops/units/` (with `ops/lib/render_unit.py`, the same tool as `ops/install.sh`) and made the two links in `default.target.wants` by hand. This is the same result as `enable`. Nothing restarted.
2. The live processes run the code of 970d5ac (loaded on 2026-10-07). `HEAD` is 0fbbc2c (the night task: 20 files changed in `infer/`, `dashboard/`, `controller/`). **The reboot is the first start of the HEAD code on the live installation.** The import check of HEAD with the live venv passes (`import infer.main, dashboard.main, controller`). The night task tested HEAD in the test installation `~/agx-installtest`.
3. `config/infer.yaml` has `status.schema_version: 2`. `rk-agxlink` on DA01 started on 2026-10-07 23:34 CST, before the v3 change (50e4290). It accepts only v2. Keep 2 until the owner restarts `rk-agxlink`.
4. At start, `agx-infer` loads the last good set (`start_set: last_good`, `~/agx-models/_state/last_good.json`): `driverguard_yolopx@1` on cameras 0-5 and `driverguard_dtcp@1` on camera 0.
5. The unit files use the user site `~/.local` (the same as the live transient units, and the same as `ops/install.sh --user-site`). The live venv needs it (CLEANUP_PROPOSAL.md row 16).
6. The GNOME session logs in automatically at boot (`who`: `:0` since boot). This session also starts the user manager. Thus a start at boot is possible also without linger, but only while the desktop auto-login stays. Linger makes the start independent of the desktop.
7. The wall clock of AGX02 stepped by about 2 h after the last boot (the clock was 2 h behind at boot, NTP corrected it later). After the reboot, the units start before this correction. I check on DA01 that the link does not wait for it (user manager "10:12:18 BST", boot "12:12:20 BST" from `/proc/uptime`). The acceptance script uses the monotonic clock (seconds after boot) for the start times.

## 3. State before stage 1 (A1.1)

Measured 2026-10-09 06:57-07:02 BST, read-only (`ops/accept_stage1.sh --save`, `jtop`, `free`, `systemctl`, `docker`, `ss`, power log `data/power.sqlite`).

| Value | Before |
|---|---|
| Uptime, boot | up since 2026-10-06 (2 d 18 h); boot 21.3 s (kernel 9.3 s + user space 12.0 s) |
| Boot target | `graphical.target` |
| Linger | no |
| Power with the models active | 23.9 W (mean of 10 min, sum of the 4 INA3221 rails; VDD_GPU_SOC 12.6 W, VIN_SYS_5V0 7.2 W, VDDQ 2.3 W, VDD_CPU_CV 1.6 W). The supply input is not measured. |
| Memory in use | 12,367 MiB (MemTotal - MemAvailable) of 62,841 MiB |
| GPU memory in use | 488 MiB (jtop RAM "shared" = NvMap) |
| GPU | 918 MHz, load 36 % (jtop sample); nvpmodel MAXN; fan 26 % |
| Temperatures | CPU 54.5 C, GPU 50.9 C, SOC 50.4-50.6 C, TJ 54.9 C |
| Models | `driverguard_yolopx` RUNNING 38.8 results/s (6 cameras), `driverguard_dtcp` RUNNING 10.0 results/s; system1 and sparsedrive OFF |
| New-software units | `agx-infer` active (transient, since 2026-10-07 18:20:19 BST), `agx-dashboard` active (transient, since 18:19:42 BST), `agx-sim` not loaded |
| Container | `driveragent-valhalla` running, restart `unless-stopped`, port 8002 |
| Old-stack processes | `valhalla_service` (in the container) only |
| Link on DA01 | rk3588-da01 UP, 315 frames in 3 s, result subscription yes (AGX view). DA01 values: see `driveragent-hmi/docs/HMI_FPS_AND_JOURNAL_REPORT.md` section "Link before the reboot" |

Units that start at boot (system, enabled) and active units: `tests/out/stage1/before_units.txt` (not in git).

## 4. What stage 1 changes (A1.2)

Command: `ops/cleanup/stage1_disable.sh` (group `base` only). Dry run 2026-10-09 07:00 BST: 13 items to change.

| # | Unit or container | What it does now (state, memory) | What uses it | Effect when it does not start at boot | Undo (single item; `ops/cleanup/stage1_disable.sh --undo` does all) |
|---|---|---|---|---|---|
| 1 | `nvargus-daemon.service` | enabled/active, 13 MiB. CSI camera daemon of JetPack | nothing: no CSI camera, no `/dev/video*`; the new software gets frames over UDP (FrameLink) | none for the new software; a CSI camera tool (`nvgstcapture`, `nvarguscamerasrc`) cannot run | `sudo systemctl enable --now nvargus-daemon.service` |
| 2 | `bluetooth.service` | enabled/active, 1.9 MiB | nothing | no Bluetooth | `sudo systemctl enable --now bluetooth.service` |
| 3 | `ModemManager.service` | enabled/active, 7.5 MiB | nothing: no modem. NetworkManager does not need it for Ethernet or Wi-Fi | a USB modem does not connect by itself | `sudo systemctl enable --now ModemManager.service` |
| 4 | `kerneloops.service` | enabled/active, 1.5 MiB | nothing | kernel oops reports are not sent to Ubuntu | `sudo systemctl enable --now kerneloops.service` |
| 5 | `apport-autoreport.path` | enabled/active | starts `apport-autoreport.service` (that fails every 3 h, whoopsie is not installed) | no failed unit every 3 h | `sudo systemctl enable --now apport-autoreport.path` |
| 6 | `apport-autoreport.timer` | enabled/active | the same | the same | `sudo systemctl enable --now apport-autoreport.timer` |
| 7 | `apport.service` | enabled/active | crash report collector | no crash report files in `/var/crash` (core dumps are not changed) | `sudo systemctl enable --now apport.service` |
| 8 | `rpcbind.socket` | enabled/active, port 111 | `rpcbind.service` only; no NFS mount in `/etc/fstab` | port 111 closed | `sudo systemctl enable --now rpcbind.socket` |
| 9 | `rpcbind.service` | enabled/active, 2.1 MiB | the same | the same | `sudo systemctl enable --now rpcbind.service` |
| 10 | `lpd.service` | enabled/active, 0.6 MiB | nothing: no printer | no BSD printing | `sudo systemctl enable --now lpd.service` |
| 11 | `packagekit.service` (static: mask) | static/active, 1.3 GiB cgroup (mostly page cache), RSS 74 MiB | GNOME Software, update-manager (desktop pop-ups); apt does not use it | GNOME Software cannot install or update; `apt` works | `sudo systemctl unmask packagekit.service` (it starts on demand) |
| 12 | snap `cups` (`snap.cups.cupsd`, `snap.cups.cups-browsed`) | enabled/active, port 631 | nothing: no printer | no printing | `sudo snap start --enable cups` |
| 13 | container `driveragent-valhalla` | running, restart `unless-stopped`, 72 MiB, port 8002; mounts `/home/tonyho/driveragent/location/valhalla.json` and `valhalla_tiles` | nothing now (old map routing; last request 2026-09-25) | port 8002 closed; the container log (2.2 GB) stops growing | `docker update --restart=unless-stopped driveragent-valhalla && docker start driveragent-valhalla` |

The script writes the state before each change to `~/.local/state/agx-cleanup/stage1-<time>.tsv`. `--undo` reads the newest file and restores each item in reverse order.

Not in this stage 1 (optional groups, not in the owner command): `--with nomachine`, `--with openvpn`, `--with avahi`, `--with update-timers`, `--with desktop`. They need the answers to the open questions of `docs/CLEANUP_PROPOSAL.md`. `nomachine` and `openvpn` are remote access (rule Z3): `nxserver` is active now with a session (`nxnode`, `nxrunner` run).

## 5. Check against rule Z3 (A1.3)

| Z3 item | Unit | In stage 1 (base)? | State now |
|---|---|---|---|
| SSH | `ssh.service` | no | enabled/active |
| Network | `NetworkManager`, `wpa_supplicant`, `systemd-resolved` | no | enabled/active |
| Tailscale | `tailscaled.service` | no | enabled/active (the owner logs in over Tailscale: `last` shows 100.x addresses) |
| Other remote access | `nxserver.service` (NoMachine) | no (group `nomachine` is not used) | enabled/active |
| Time | `systemd-timesyncd` | no | enabled/active, NTPSynchronized=yes |
| NVIDIA power mode, fan | `nvpmodel` (oneshot), `nvfancontrol`, `jtop` | no | enabled; nvfancontrol and jtop active |
| New software | `agx-infer`, `agx-dashboard`, `docker`, `containerd` | no | active |

Result: **stage 1 (base) disables no Z3 item.** The KEEP guard of the script (`KEEP_UNITS_RE`) does not list `nxserver`, `openvpn` or `avahi`. Thus the guard does not protect NoMachine: only the group selection does (`--with nomachine` is not in the owner command). `ModemManager`: `mmcli -L` shows "No modems were found"; `nmcli` shows no gsm or wwan device. `rpcbind`: no NFS mount and no `rpc-statd`. `packagekit` mask: apt keeps working.

Ports, devices and files: the new software uses TCP 5560-5564 (ZMQ), TCP 8700 (dashboard), UDP 6000-6005 (FrameLink), `/dev/nvhost*` and `/dev/nvmap` (TensorRT), `~/agx-models`, `~/driveragent-agx`, `~/.local`, `/home/tonyho/model`. Stage 1 closes 111, 631 and 8002. None of the 13 items holds one of these. The new code has no reference to an item of stage 1 (grep of `infer/`, `dashboard/`, `controller/`, `config/`). `config/dashboard.yaml` `old_units` shows `nvargus-daemon`, `snap.cups.cupsd` and `packagekit` on the dashboard page only: after stage 1 they show "inactive". This is information, not an error.

## 6. Repositories with SAVE FIRST (A1.4)

`docs/CLEANUP_PROPOSAL.md` rows 1-6: `/home/tonyho/driveragent` (2 unpushed commits on a local branch), its 4 worktrees, `/home/tonyho/model/yolopx/YOLOPX` (67 uncommitted), `~/Downloads/gstreamer` (2 untracked + subprojects), `~/Downloads/libnice` (1 untracked), `~/Downloads/jetson-jtop-patch` (1 modified). Rows 7-10 (recordings, map data, calcam) also have SAVE FIRST.

**Stage 1 deletes nothing and moves nothing. The SAVE FIRST items do not block stage 1 or this task.** They are necessary before stage 3 (and before the manual DELETE of row 2). Stage 2 and stage 3 are not part of this task.

## 7. Start at boot (A1.5)

Done (no sudo), 2026-10-09 06:59 BST:

```
~/.config/systemd/user/agx-infer.service       (sha256 9d18d524...; from ops/units/agx-infer.service.in)
~/.config/systemd/user/agx-dashboard.service   (sha256 e8fbea51...; from ops/units/agx-dashboard.service.in)
~/.config/systemd/user/default.target.wants/agx-infer.service     -> ../agx-infer.service
~/.config/systemd/user/default.target.wants/agx-dashboard.service -> ../agx-dashboard.service
```

Changes after the review (commit 2f4950c): the two templates have `StartLimitIntervalSec=0` and `RestartSec=5` (before: 10 starts in 120 s, then the unit stays failed). At boot a unit must keep trying without a person. The command line and the environment are the same as the transient units of `tools/svc.sh` (`PWD`, `PYTHONUNBUFFERED=1`, `PYTHONPATH`, no `PYTHONNOUSERSITE`).

`agx-sim` stays disabled (no unit file).

Until the reboot: do not stop and start the two services with `tools/svc.sh`. When a transient unit stops, the name resolves to the new unit file, and `systemd-run` (svc.sh) then fails with "Unit ... already exists". If a service stops before the reboot, use `systemctl --user start agx-infer` (or `agx-dashboard`); it then runs the HEAD code. `systemd-analyze --user verify` passes. The running transient units did not change (no daemon-reload, no restart). The new files take effect at the next start of the user manager (the reboot).

Undo (tested 2026-10-09 07:00 BST: files removed, units stayed active, files written again):
```
rm ~/.config/systemd/user/default.target.wants/agx-infer.service ~/.config/systemd/user/default.target.wants/agx-dashboard.service
rm ~/.config/systemd/user/agx-infer.service ~/.config/systemd/user/agx-dashboard.service
```
Note for a later `ops/install.sh`: the install record `data/install-agx.json` does not list these files, so `install.sh` does not replace them ("exists and install did not make it"). Run the undo first, then `ops/install.sh`.

Linger (owner step, sudo): `sudo loginctl enable-linger tonyho`. Undo: `sudo loginctl disable-linger tonyho`.

## 8. Acceptance script (A1.6)

`ops/accept_stage1.sh [--save FILE] [--before FILE] [--da01 FILE]`. It changes nothing (read-only; it writes only the `--save` file). One line for each item of task section 5: PASS, FAIL, SKIP (data from DA01 is missing) or INFO. Items 1b and 8 need a JSON file from DA01 (link DOWN time, first result per camera, restarts on DA01, results/s, capture-to-result p50/p95, stale results).

Item 2 proof of linger: with linger, logind starts `user@1000` at boot before any session; without linger, the GNOME auto-login session starts it. The script compares the start of `user@1000` with the first logind "New session" line (monotonic time), and the first start of each unit in this boot (user journal) with the first SSH login. It also prints the restarts of the units. Item 4b counts only the model control actions `activate`, `deactivate`, `rollback` from the rk console after the boot. Item 5 also needs each old unit disabled or masked. Item 6 also needs `nvpmodel` Result=success. Run the script 15 min or more after the boot (10-min power mean, NTP).

Run before stage 1 (2026-10-09 07:19 BST): PASS 1a, 3a, 3b, 4a, 4b, 6; FAIL 2a (linger no), 2b (user manager 19.5 s after boot, after the first session at 17.5 s: no linger), 2c and 2d (transient units), 5 (13 old items and the container active). These FAIL lines are the expected state before stage 1.

## 9. Review of this preparation

Three independent review agents checked the claims of this report and of the DA01 report (read-only). Results used here: the start limit of the units (fixed), the svc.sh trap before the reboot (written in section 7), the linger proof of item 2 (fixed), the action filter of item 4b, the enabled check of item 5 and the nvpmodel check of item 6 (fixed), the KEEP guard and NoMachine (section 5).
