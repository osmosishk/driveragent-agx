# Cleanup proposal - agx02

Update of 2026-10-08 (night task, part B). This document is a proposal only. Nobody changed the machine. Nobody ran a cleanup command or a cleanup script. The owner must approve each row before somebody runs its command or a stage script. Do all SAVE FIRST steps before stage 3.

New role of this AGX: TensorRT inference and its own web dashboard (`~/driveragent-agx`, model store `~/agx-models`). The RK3588 (DA01) does camera capture, preprocessing, HMI, maps, recording, upload, CAN, decisions and display.

## Sources and how to read the values

- **(A)** = new audit, made **with root**: `agx02:~/agx_audit_agx02_20261007_201209/report.md`, 2026-10-07 20:12 BST. Line 30 of the report: `audit run  : 2026-10-07T20:12:09+01:00 as root (root=1)`. Section 0 (Flags) of this report has **no** flag "Run without root". The audit of 2026-10-05 (`docs/AGX_AUDIT.md`, and `~/agx_audit_agx02_20261005_202230`) had this flag. Thus the values for Docker, `/var/lib/docker`, `/root` and the processes of other users are now complete.
- **(M)** = measured now, read-only, as tonyho: 2026-10-07 20:28-20:35 BST (2026-10-08 03:28-03:35 CST). Commands: `du -sb`, `stat`, `find`, `df -B1`, `ps`, `systemctl is-enabled/is-active/show -p MemoryCurrent`, `docker ps/images/inspect/stats/system df`, `git --no-optional-locks status --porcelain`, `git rev-list --count @{u}..HEAD`, `git log --branches --not --remotes`, `git stash list`. No fetch. No change.
- **(O)** = first proposal of 2026-10-05 (audit without root, and four analysts). These values are not measured again.
- Sizes: GiB = 2^30 bytes. "RSS" = resident memory of the processes from `ps`. RSS counts shared pages more than once, so a sum of RSS is an upper limit.
- Disk now (M): `/` = `/dev/nvme0n1p1`, ext4, 915G; used 631,052,959,744 B; free 300,812,861,440 B (280.2 GiB). RAM now (M): 61.4 GiB total, 49.2 GiB available. Memory is not a problem now.

## What changed since the first proposal (2026-10-05)

1. `~/driveragent-agx` has a remote now (`git@github.com:osmosishk/driveragent-agx.git`), 0 uncommitted files, 0 unpushed commits (M). It is not a SAVE FIRST item any more.
2. **The live configuration uses old recordings.** `config/sim.yaml` has `video_root: /home/tonyho/driveragent/logger/video` and the session sets `bench` (8003-20260510_151020, _151120, _151220) and `road` (8003-20251109_105508, _105608, _105708). `config/sources.yaml` (file mode) uses 8003-20260510_150920 to _151220. Thus these 7 session folders (1.27 GiB), the folder `logger/video` and the repository `/home/tonyho/driveragent` stay in place (KEEP). The other recordings can go to the archive. The scripts find these references at run time.
3. The audit with root shows: `/var/lib/docker` 3.7G; the JSON log of the container `driveragent-valhalla` is 2.2G; `/root/.cache` 125M (ccache 122M); `/var/cache/apt` 744M; `lpd.service` (package `lpr`) runs.
4. The live venv `~/driveragent-agx/.venv` has `include-system-site-packages = true` and the user site `~/.local/lib/python3.10/site-packages` is on its `sys.path` (M). Thus `~/.local` is KEEP until the owner installs again with `ops/install.sh` (that install uses `PYTHONNOUSERSITE=1`).
5. Three scripts do the work in stages: `ops/cleanup/stage1_disable.sh`, `stage2_archive.sh`, `stage3_delete.sh` (section "Scripts").

## Main table

Proposal values: **KEEP**, **DISABLE**, **MOVE** (to the stage 2 archive `~/_archive_<date>/`, same file system), **DELETE**. The label **SAVE FIRST** means: do the owner step in section "SAVE FIRST steps" before stage 3 (or before the manual command). Git repositories with uncommitted or unpushed work are first in the table.

"stage1 (base)" = `ops/cleanup/stage1_disable.sh`; "stage1 (--with G)" = the same script with the group G; "stage2" = `ops/cleanup/stage2_archive.sh`; "stage3" = `ops/cleanup/stage3_delete.sh`; "manual" = the owner types the command (not in a script).

| # | Item | Type | Size or memory | What uses it | Proposal | Command | How to undo |
|---|---|---|---|---|---|---|---|
| 1 | `/home/tonyho/driveragent` (branch `main`) | repo | 542.6 GiB total (M); `.git` 79 MiB; code folders below 100 MiB each | Old full stack. Reference code. The live sim config reads 7 sessions in `logger/video` (row 30). `main`: 0 uncommitted, 0 ahead of `origin/main`, last commit 2026-05-22 bf78af3 (M). **2 unpushed commits** on local branch `claude/quizzical-elgamal-709408`: 0f266df and da3d058, 2026-05-07 (M). Git-ignored secrets: `config.ini`, `control/.env`, `gcs_upload.json`. | **SAVE FIRST**, then KEEP (the repo stays; rows 7, 8, 9 and 38 take parts of it) | SAVE FIRST step SF-1 (manual) | SF-1 undo |
| 2 | 4 worktrees of row 1: `.claude/worktrees/quizzical-elgamal-709408`, `.claude/worktrees/vigorous-wing-ea79d5`, `ui/.claude/worktrees/cool-dirac-3995ab`, `replay/.claude/worktrees/interesting-dhawan-7a9052` | repo (worktree) | 14M + 14M + 88M + 14M (M) | Claude Code session worktrees. 3 have 1 uncommitted change (`.claude/settings.local.json`); `interesting-dhawan-7a9052` is clean (M). Last commits 2026-04-02 to 2026-05-10. | **SAVE FIRST**, then DELETE | SF-2 (manual, after SF-1) | SF-2 undo |
| 3 | `/home/tonyho/model/yolopx/YOLOPX` | repo | 807M (A) | Third-party clone (`jiaoZ7688/YOLOPX`). **67 uncommitted**: 61 untracked, 4 deleted, 2 modified (M). 0 unpushed. Last commit 2025-03-28 35627f6. In the protected model folder. | **SAVE FIRST**, then KEEP | SF-3 (manual) | SF-3 undo |
| 4 | `/home/tonyho/Downloads/gstreamer` and its 9 subprojects (`dv`, `gl-headers`, `gperf`, `libavtp`, `libmicrodns`, `libnice`, `opus`, `orc`, `vpx`) | repo | 1.27 GiB (1,363,302,053 B, M) | GStreamer 1.24.12 build. It installed `/opt/gst-1.24` (row 52). **2 untracked**: `subprojects/.wraplock`, `subprojects/gperf.wrap`. Each subproject: 1 or 2 untracked generated files. Detached HEAD, no upstream. Last commit 2025-01-29 (M). | **SAVE FIRST**, then MOVE, then DELETE | SF-4, then stage2, then stage3 | before stage 3: `stage2_archive.sh --undo` |
| 5 | `/home/tonyho/Downloads/libnice` | repo | 26.7 MiB (M) | libnice 0.1.15 build tree (prefix `/usr`). `make uninstall` needs it. **1 untracked**: `m4/pkg.m4`. Detached HEAD, no upstream. Last commit 2018-12-27 (M). | **SAVE FIRST**, then MOVE, then DELETE | SF-5, then stage2, then stage3 | before stage 3: `stage2_archive.sh --undo`; after: restore the SF-5 tarball |
| 6 | `/home/tonyho/Downloads/jetson-jtop-patch` | repo | 117 KiB (M) | jetsonhacks patch for jtop. **1 modified** file (mode of `apply_jtop_fix.sh`). 0 unpushed. Last commit 2025-08-03 (M). | **SAVE FIRST**, then KEEP | SF-6 (manual) | SF-6 undo |
| 7 | Old recordings: 1860 session folders `/home/tonyho/driveragent/logger/video/8003-*` (all except the 7 of row 30) | directory | 266.5 GiB (286,156,787,665 B, M) | Old 6-camera recordings, car 8003, 2025-10-21 to 2026-05-10. No process writes here. `uploaded.db` lists the sessions as uploaded to GCS bucket `carvideo_osmosisai`, prefix `8003/` (O). Nobody checked the bucket. | **SAVE FIRST**, then MOVE, then DELETE | SF-7, then stage2, then stage3 | before stage 3: `stage2_archive.sh --undo`; after: SF-7 copy |
| 8 | Old recording archives: 1869 files `/home/tonyho/driveragent/logger/video/8003-*.tar.bz2` | file | 267.4 GiB (287,110,810,142 B, M) | Made by the old `logger/uploader.py` for the GCS upload. Same sessions as row 7. 2 archives have no session folder (8003-20260101_124700, 8003-20260401_153815) (O). | **SAVE FIRST**, then MOVE, then DELETE | SF-7, then stage2, then stage3 | as row 7 |
| 9 | Map data of the old stack: `location/valhalla_tiles` (2.38 GiB, 1436 root-owned entries), `location/united-kingdom-latest.osm.pbf` (1.84 GiB), `location/gb.mbtiles` (1.14 GiB), `location/england_greater-london.mbtiles` (81 MiB), `dev/uk.mbtiles` (1.55 GiB), all in `/home/tonyho/driveragent` | directory / file | 6.99 GiB (M) | `valhalla_tiles` is bind-mounted into the container of row 18. The other files were for the old map UI. Map work is now on the RK3588. | **SAVE FIRST**, then MOVE, then DELETE | SF-8, stage1 (container stop), then stage2, then stage3 | before stage 3: `stage2_archive.sh --undo` |
| 10 | `/home/tonyho/Downloads/calcam` (`calcam.py`, `cam0.yaml` to `cam5.yaml`, `venv/` 187M) | directory | 179 MiB (M) | Camera calibration of 2026-01. Not in git. Cameras are now on the RK3588. | **SAVE FIRST**, then MOVE, then DELETE | SF-9, then stage2, then stage3 | before stage 3: `stage2_archive.sh --undo` |
| 11 | `/home/tonyho/driveragent-agx` (repo, `.venv`, `.env`, `data/`, `config/`) | repo | 302 MiB (M); `.venv` 34 MiB | **New installation** (live units `agx-infer`, `agx-dashboard`). Clean, pushed: HEAD 970d5ac = upstream (M). | KEEP | none | not applicable |
| 12 | `/home/tonyho/driveragent-agx/ref/driveragent-hmi` | repo | 111M (A) | Reference clone of the RK3588 HMI project. Clean, detached HEAD, 0 unpushed (M). | KEEP | none | not applicable |
| 13 | `/home/tonyho/agx-models` | directory | 195 MiB (M) | **Model store** of the new installation (`model_store: ~/agx-models`). | KEEP | none | not applicable |
| 14 | Model files that the store manifests and `config/models.yaml` use: `/home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine`, `dtcp_v1_fp16.engine`; `jetson_bundle/onnx/yolopx_v2.onnx`, `dtcp_v1.onnx`; `sparsedrive/run/convnext_backbone_fp16_orin.trt`, `convnext_backbone_nchw_orin.onnx`; `system1/system1_deploy.pth` | file | engines 120.8M; sparsedrive run 745.6M; onnx 218.4M; system1 365.8M (A, folder values) | `path:` entries of `~/agx-models/*/*/manifest.yaml` and `config/models.yaml` (M). The scripts read these files at run time and refuse these paths. | KEEP | none | not applicable |
| 15 | Rest of `/home/tonyho/model` (weights, checkpoints, `yolopx/venv`, stage2 checkpoints) | directory | 5.36 GiB for the full folder (M) | `protected_dirs` and `engines.scan_dirs` of the live config. Owner rule: keep the old models. | KEEP | none | not applicable |
| 16 | `/home/tonyho/.local/lib/python3.10/site-packages` (torch, pyzmq 27.1.0, pycapnp 2.2.0, numpy 1.26.4, onnx 1.21.0, onnxruntime 1.23.2, httpx 0.28.1 and others) | package | `~/.local` 2.33 GiB (M) | The live venv imports them (user site on `sys.path`, M). KEEP until the owner installs again with `ops/install.sh` (then the venv has its own packages). | KEEP | none | not applicable |
| 17 | JetPack 6.2.1, L4T 36.4.7, CUDA 12.6, TensorRT 10.3.0, cuDNN, VPI, `/opt/nvidia`, `/usr/local/cuda-12.6`, build toolchain, nsight tools, `linux-firmware`, JetPack samples | package | `/usr` 15G, `/opt` 2.8G (A) | TensorRT engines and the runtime of the new installation. | KEEP | none | not applicable |
| 18 | `driveragent-valhalla` (image `ghcr.io/valhalla/valhalla:latest`, restart `unless-stopped`, port 8002) | container | RSS 105 MiB (valhalla 75.5 MiB, shim 13.1 MiB, 2 x docker-proxy 8.2 MiB) (M); container memory 72.4 MiB (M) | Old map routing. The only old-stack item that starts at boot. Mounts row 9. No client now (last request 2026-09-25, O). | DISABLE | stage1 (base): `docker update --restart=no driveragent-valhalla && docker stop driveragent-valhalla` | `stage1_disable.sh --undo` (sets `unless-stopped` again and starts it) |
| 19 | Container `driveragent-valhalla` itself and its JSON log `/var/lib/docker/containers/5b0fcc3b.../5b0fcc3b...-json.log` | container | log 2.2G (A) | Nothing after row 18. | DELETE | stage3: `docker rm driveragent-valhalla` | not possible after stage 3. Before: nothing to undo. To make it again: `bash /home/tonyho/driveragent/location/setup_valhalla.sh` (needs row 9 back) |
| 20 | Image `ghcr.io/valhalla/valhalla:latest` (ID 063da86ba07c) | image | 733.4 MB (M) | Only row 19. No volume, no build cache, no other image (M). | DELETE | stage3: `docker rmi ghcr.io/valhalla/valhalla:latest` (by name; the script checks the ID; no prune) | not possible after stage 3. Optional before: SF-10 (`docker save`). Else `docker pull` (can be a newer version) |
| 21 | `nvargus-daemon.service` | service | 12.7 MiB cgroup, RSS 9.4 MiB (M) | CSI camera daemon. No CSI camera use. Cameras are on the RK3588. | DISABLE | stage1 (base): `sudo systemctl disable --now nvargus-daemon.service` | `stage1_disable.sh --undo` (`sudo systemctl enable --now nvargus-daemon.service`) |
| 22 | `bluetooth.service` | service | RSS 4.4 MiB (M) | Bluetooth. Not used. | DISABLE | stage1 (base): `sudo systemctl disable --now bluetooth.service` | `stage1_disable.sh --undo` |
| 23 | `ModemManager.service` | service | RSS 10.9 MiB (M) | Modem manager. No modem (O). | DISABLE | stage1 (base): `sudo systemctl disable --now ModemManager.service` | `stage1_disable.sh --undo` |
| 24 | `kerneloops.service` | service | RSS 0.9 MiB (M) | Sends kernel oops reports to Ubuntu. | DISABLE | stage1 (base): `sudo systemctl disable --now kerneloops.service` | `stage1_disable.sh --undo` |
| 25 | `apport.service`, `apport-autoreport.path`, `apport-autoreport.timer` (`apport-autoreport.service` is FAILED, A) | service | 0 (M) | Crash report upload. It fails every 3 hours (whoopsie is not installed, O). | DISABLE | stage1 (base): `sudo systemctl disable --now apport-autoreport.path apport-autoreport.timer apport.service`, then `sudo systemctl reset-failed apport-autoreport.service` | `stage1_disable.sh --undo` |
| 26 | `rpcbind.service` + `rpcbind.socket` | service | RSS 2.1 MiB; port 111 (M, A) | NFS port mapper. No NFS mount. | DISABLE | stage1 (base): `sudo systemctl disable --now rpcbind.socket rpcbind.service` | `stage1_disable.sh --undo` |
| 27 | `lpd.service` (package `lpr`, SysV script) | service | RSS 0.1 MiB (M) | BSD line printer daemon. No printer. New item (A). | DISABLE | stage1 (base): `sudo systemctl disable --now lpd.service` | `stage1_disable.sh --undo` |
| 28 | `packagekit.service` (static) | service | RSS 74.2 MiB; cgroup 712 MiB with page cache (M) | Backend of GNOME Software and update-manager. apt does not use it. A static unit cannot be disabled: mask. | DISABLE | stage1 (base): `sudo systemctl mask --now packagekit.service` | `stage1_disable.sh --undo` (`sudo systemctl unmask packagekit.service`) |
| 29 | cups snap services `snap.cups.cupsd`, `snap.cups.cups-browsed` | service | RSS 29.9 MiB; cgroup 53.6 MiB; port 631 (M) | Printing. No printer use is known. | DISABLE (stage 1), DELETE later (row 44) | stage1 (base): `sudo snap stop --disable cups` | `stage1_disable.sh --undo` (`sudo snap start --enable cups`) |
| 30 | Sim recordings: `logger/video/8003-20260510_150920`, `_151020`, `_151120`, `_151220`, `8003-20251109_105508`, `_105608`, `_105708`; the folder `logger/video`; `logger/video/uploaded.db` | directory | 1.27 GiB (1,361,565,312 B, M); `uploaded.db` 228 KB (O) | `config/sim.yaml` (`video_root`, `session_sets`, `cameras[].files`) and `config/sources.yaml` (file mode). `uploaded.db` = only local record of the GCS upload. | KEEP | none (stage2 refuses them at run time) | not applicable |
| 31 | `nxserver.service` (NoMachine 9.5.7) | service | RSS 276.8 MiB for nxserver, nxnode, 2 x nxrunner, nxd; cgroup 257 MiB; port 4000 (M) | Remote desktop. Last client 2026-09-25 (O). | DISABLE (after open question 3) | stage1 (`--with nomachine`): `sudo systemctl disable --now nxserver.service` | `stage1_disable.sh --undo` |
| 32 | `openvpn.service` + `openvpn@uk-ovpn-agent-20.service` | service | RSS 8.1 MiB (M) | OpenVPN client to 139.162.209.77:1194. It does not connect (O). | DISABLE (after open question 2) | stage1 (`--with openvpn`): `sudo systemctl stop openvpn@uk-ovpn-agent-20.service && sudo systemctl disable --now openvpn.service` | `stage1_disable.sh --undo` |
| 33 | `avahi-daemon.service` + `.socket` | service | RSS 3.5 MiB (M) | mDNS name `agx02.local`. The RK3588 uses IP addresses. | DISABLE (after open question 5) | stage1 (`--with avahi`): `sudo systemctl disable --now avahi-daemon.socket avahi-daemon.service` | `stage1_disable.sh --undo` |
| 34 | Update timers: `apt-daily`, `apt-daily-upgrade`, `update-notifier-download`, `update-notifier-motd`, `motd-news`, `fwupd-refresh`, `ua-timer`, `snapd.snap-repair` | service (timer) | 0 | Background package downloads and update pop-ups. Risk: security updates do not download by themselves. | DISABLE (after open question 7) | stage1 (`--with update-timers`): `sudo systemctl disable --now <timer>` for each | `stage1_disable.sh --undo` |
| 35 | Graphical desktop: `gdm`, GNOME session with auto-login, Xorg, `gnome-software`, `update-manager`, `update-notifier`, 20 `nvpmodel_indicator` processes, tracker, evolution, ibus | service | RSS 2.04 GiB for 92 processes (upper limit, M); PSS about 1.4 GiB (O) | Local monitor and NoMachine desktop. Inference and the web dashboard do not need it. | DISABLE (after open question 3) | stage1 (`--with desktop`): `sudo systemctl set-default multi-user.target`. It has an effect at the next boot. The script does not reboot. | `stage1_disable.sh --undo` (`sudo systemctl set-default graphical.target`, then reboot) |
| 36 | Desktop helpers if the desktop stays: autostart of `gnome-software`, `update-notifier`, `nvpmodel_indicator`; user units `tracker-miner-fs-3`, `tracker-extract-3` | service | gnome-software 158 MiB, update-manager 247 MiB, update-notifier 28 MiB, nvpmodel_indicator 20 processes, tracker 31 MiB RSS (M) | Desktop pop-ups and file index. Not necessary if row 35 is done. | DISABLE (only if row 35 is not done) | manual: note N-1 | note N-1 |
| 37 | Old build and source trees: `/home/tonyho/Downloads/raylib` (0.54 GiB, clean, 353 root-owned files), `/home/tonyho/Downloads/cmake-3.31.7` (0.42 GiB, 119 root-owned), `/home/tonyho/Downloads/maplibre-native` (4.64 GiB, clean), `/home/tonyho/opencv` (0.47 GiB, 956 root-owned), `/home/tonyho/opencv_contrib` (0.10 GiB) | directory | 6.17 GiB together (M) | Sources of installed libraries (raylib, cmake 3.31.7, libmbgl-core, OpenCV 4.10.0). The installed files stay (note N-3). raylib and maplibre: clean, 0 unpushed (M). | MOVE, then DELETE | stage2, then stage3 | before stage 3: `stage2_archive.sh --undo`; after: clone and build again (note N-3) |
| 38 | `/home/tonyho/driveragent/location/mapgen` | file | 143 MiB (M) | Map image generator binary of the old UI. Git-ignored. | MOVE, then DELETE | stage2, then stage3 | before stage 3: `stage2_archive.sh --undo` |
| 39 | Small old files: `/home/tonyho/Downloads/nomachine.deb` (72 MiB, old 9.1.24), `/home/tonyho/jetson_out` (1.6 MiB), `/home/tonyho/agx_audit_agx02_20261005_202230` + `.tar.gz` (2.9 MiB; the 2026-10-07 audit replaces it), `/home/tonyho/s.sh`, `/home/tonyho/start-driveragent.sh` (old start scripts, root-owned) | directory / file | 76 MiB together (M) | Nothing. | MOVE, then DELETE | stage2, then stage3 | before stage 3: `stage2_archive.sh --undo` |
| 40 | Stage 2 archive `/home/tonyho/_archive_<date>/` (rows 4, 5, 7, 8, 9, 10, 37, 38, 39) | directory | 548.7 GiB (589,198,788,782 B, M) | Nothing after stage 2. | DELETE | stage3 (`sudo rm -rf --one-file-system` of the archive folder only) | **not possible** |
| 41 | `docker.service`, `containerd.service` | service | dockerd RSS 83 MiB, containerd 45 MiB (M) | Docker engine. No container after row 18. The dashboard shows the Docker state. Possible use later. | KEEP | none | not applicable |
| 42 | `jtop.service`, `nvpmodel.service`, `nvfancontrol.service`, NVIDIA base units (`nv`, `nvfb*`, `nvpower`, `nvphs`, `nvs-service`, `nv-tee-supplicant`, `nvidia-pva-allowd`, `nvzramconfig`, `nv-l4t-*`, `nvweston`, `nvmemwarning`, `nvgetty` and serial gettys) | service | jtop 24 MiB cgroup (M); others small | Health data of the dashboard (jtop), power mode, fan, JetPack base system, serial consoles. | KEEP | none | not applicable |
| 43 | `ssh`, `tailscaled`, `systemd-timesyncd`, `NetworkManager`, `wpa_supplicant`, `systemd-resolved`, `cron`, `anacron`, `rsyslog`, `haveged` | service | tailscaled 80 MiB cgroup, ssh 8.6 MiB (M) | Remote access, link to the RK3588, clock, network, logs. | KEEP | none | not applicable |
| 44 | Snaps: `cups` + base `core26`; `chromium` + `~/snap/chromium` (124M); runtimes `gnome-46-2404`, `mesa-2404`, `gtk-common-themes`, `core24`, `bare`; `gnome-42-2204`, `core22` | package | about 3.4 GiB together (O); `/var/lib/snapd` 3.4G (A) | Printing; browser (last use 2026-02); runtimes for chromium only. | DELETE | manual: note N-4 | note N-4 |
| 45 | `snapd.service`, `snapd.socket`, `snapd.seeded.service` | service | RSS 49 MiB (M) | Snap daemon. Necessary for row 44 (`snap remove`). | KEEP now; DISABLE after row 44 | manual (last): `sudo systemctl disable --now snapd.service snapd.socket snapd.seeded.service` | `sudo systemctl enable --now snapd.socket snapd.service snapd.seeded.service` |
| 46 | apt packages not used: `thunderbird*`, LibreOffice apps, games, media apps, printer and scanner drivers, `orca`/`brltty`/`speech-dispatcher`, `qemu-efi*` | package | about 0.7 GiB (O) | Desktop apps. Not used. | DELETE | manual: note N-5 | note N-5 |
| 47 | Old-stack user pip packages: `raylib`, `python-can`, `pyubx2`, `pynmeagps`, `pynmea2`, `pyrtcm`, `google-cloud-storage`, `google-cloud`, `mapbox-vector-tile` | package | about 23 MB (O) | Old UI, CAN, GNSS, upload, map code. The new code does not import them (M, grep). | DELETE (after the reinstall with `ops/install.sh`) | manual: note N-6 | note N-6 |
| 48 | Caches: `~/.cache/pip` (33 MiB), `~/.cache/ccache` (254 MiB), `/root/.cache/ccache` (122M), `/var/cache/apt` (744M) | directory | 1.1 GiB together (M, A) | Download and compiler caches. | DELETE | manual: note N-7 | caches fill again when needed |
| 49 | `~/.cache/torch`, `~/.cache/nvidia` | directory | 64K + 52M (O) | PyTorch and CUDA JIT caches. | KEEP | none | not applicable |
| 50 | `/var/log`, journal | directory | 141M; journal 64M (A) | System logs. | KEEP | none | not applicable |
| 51 | New audit `~/agx_audit_agx02_20261007_201209` + `.tar.gz`, `~/agx_audit.sh` | directory | 172K + 249K (A, M) | Source of this proposal. | KEEP | none | not applicable |
| 52 | `/opt/gst-1.24` (67M) and `~/gst124.env` | directory | 67M (A) | GStreamer 1.24 from row 4. User unknown (open question 9). | KEEP | none | not applicable |
| 53 | `~/Downloads/SG8A`, `SG8A.zip`, `gstwebrtcwrapper*`, `cmake-3.31.7.tar.gz`, `gslist.txt`, `OpenCV-4-10-0.sh`, `uk-ovpn-agent-20.conf` | directory / file | about 142 MiB (M) | GMSL camera driver kit, small sources and scripts. The `.conf` can hold VPN secrets. | KEEP | none | not applicable |
| 54 | `~/.vscode-server` (1.5G), `~/.claude` (967M), `~/.config`, `~/.ssh` | directory | 2.5 GiB (A) | Tools in use now. | KEEP | none | not applicable |
| 55 | `~/agx-night-dev`, `~/agx-installtest` | directory | 7.4 MiB (M) | Made by the night task. The lead removes them. Not part of this proposal. The scripts refuse them. | KEEP | none | not applicable |

Counts (55 rows): **SAVE FIRST 10** (rows 1 to 10; the 6 git repositories first; after the save: KEEP 1, 3, 6; DELETE 2; MOVE then DELETE 4, 5, 7, 8, 9, 10). **KEEP 18** (11 to 17, 30, 41 to 43, 49 to 55), plus row 45 (KEEP now, DISABLE after row 44). **DISABLE 16** (stage 1 base: 10 rows, 18 and 21 to 29; optional groups: 5 rows, 31 to 35; manual: row 36). **MOVE then DELETE 3** without SAVE FIRST (37 to 39). **DELETE 7** (stage 3: 19, 20, 40; manual: 44, 46, 47, 48). Row 29 is DISABLE now and DELETE later (row 44). The stage 2 archive gets rows 4, 5, 7, 8, 9, 10, 37, 38, 39.

## Expected result

Values: (M) measured 2026-10-07 20:28-20:35 BST, read-only; (A) audit 2026-10-07 20:12 BST.

| Stage | Services that stop | Memory that becomes free (RSS, upper limit) | Disk space that becomes free |
|---|---|---|---|
| 1 base | 10 services: nvargus-daemon, bluetooth, ModemManager, kerneloops, apport, rpcbind, lpd, packagekit (masked), snap.cups.cupsd, snap.cups.cups-browsed. 3 other units: apport-autoreport.path, apport-autoreport.timer, rpcbind.socket. 1 container: driveragent-valhalla. Ports closed: 8002, 111, 631. | 237 MiB (M): valhalla + shim + docker-proxy 105 MiB, packagekitd 74 MiB, cups 30 MiB, ModemManager 11 MiB, nvargus 9 MiB, bluetoothd 4 MiB, rpcbind 2 MiB, kerneloops 1 MiB, lpd 0.1 MiB. | 0. The container log (2.2G, A) stops growing. |
| 1 `--with nomachine` | nxserver (and nxnode, nxrunner, nxd). Port 4000 closed. | 277 MiB (M) | 0 |
| 1 `--with openvpn` | openvpn, openvpn@uk-ovpn-agent-20 | 8 MiB (M) | 0 |
| 1 `--with avahi` | avahi-daemon (+ socket). Port 5353 closed. | 3.5 MiB (M) | 0 |
| 1 `--with update-timers` | 8 timers | 0 (no apt or snap download in the background) | 0 |
| 1 `--with desktop` | at the next boot: gdm, Xorg, GNOME session (92 processes) | 2.04 GiB (M); PSS about 1.4 GiB (O) | 0 |
| 2 | none | 0 | 0 (rename on the same file system). 3749 items go to `~/_archive_<date>/`: 20 single items + 1860 session folders + 1869 `.tar.bz2` files. |
| 3 | none | 0 | 551.6 GiB: archive 548.7 GiB (M) + container log 2.2 GiB (A) + image 0.7 GiB (M). |
| manual rows 2, 44, 46, 47, 48 | snapd later (row 45) | snapd 49 MiB | about 5.3 GiB (estimate: worktrees 0.13, snaps 3.4 (O), apt 0.7 (O), pip 0.02 (O), caches 1.1 (M, A)) |

Stage 2 and stage 3, per group (M):

| Group | Rows | Bytes | GiB |
|---|---|---|---|
| Build and source trees (gstreamer 1.27, libnice 0.03, raylib 0.54, cmake 0.42, maplibre-native 4.64, opencv 0.47, opencv_contrib 0.10) | 4, 5, 37 | 8,010,825,694 | 7.46 |
| Small old files (calcam, nomachine.deb, jetson_out, old audit and its tarball, s.sh, start-driveragent.sh) | 10, 39 | 268,151,819 | 0.25 |
| Map data (valhalla_tiles 2.38, osm.pbf 1.84, gb.mbtiles 1.14, england mbtiles 0.08, uk.mbtiles 1.55, mapgen 0.14) | 9, 38 | 7,652,213,462 | 7.13 |
| Recording session folders (1860) | 7 | 286,156,787,665 | 266.50 |
| Recording archives (1869) | 8 | 287,110,810,142 | 267.39 |
| **Total archive** | 40 | **589,198,788,782** | **548.73** |

Free disk space: now 280.2 GiB (M). After stage 3: about 831.8 GiB (estimate: 280.2 + 548.7 + 2.9). After the manual rows: about 837 GiB. The sizes can change before the owner runs the stages; the scripts measure again at run time.

The SAVE FIRST copies (section below) that go to `/home/tonyho/backup` stay on the same disk: about 1 GiB at most (estimate: git bundle 80 MiB, YOLOPX untracked files with `weights/epoch-195.pth` 0.4 GiB, libnice tarball, gstreamer files, calcam yaml files, optional Valhalla image 0.7 GiB). The recordings and the map data must go to another machine (open questions 4 and 6).

## Owner order

1. **SAVE FIRST steps** SF-1 to SF-9 (and SF-10 if you want the exact Valhalla image). Answer the open questions.
2. **Stage 1 (base):** `cd ~/driveragent-agx && ops/cleanup/stage1_disable.sh --dry-run`, read the list, then `ops/cleanup/stage1_disable.sh` and type `DISABLE`. Add `--with <group>` only after the answer to its open question. Check the dashboard (`http://<agx>:8700`), `systemctl --user status agx-infer agx-dashboard`, the link to DA01.
3. **Wait some days** (proposal: 3 days, with one drive or bench run). If a problem comes: `ops/cleanup/stage1_disable.sh --undo`.
4. **Stage 2:** `ops/cleanup/stage2_archive.sh --dry-run`, read the list (full list in `~/.local/state/agx-cleanup/stage2-plan-*.tsv`; the 7 sim sessions must show REFUSE), then `ops/cleanup/stage2_archive.sh` and type `ARCHIVE`. Check the sim mode (`--sessions bench` and `road`) and the dashboard.
5. **Wait some days** (proposal: 7 days). If a problem comes: `ops/cleanup/stage2_archive.sh --undo`.
6. **Stage 3:** `ops/cleanup/stage3_delete.sh --dry-run`, read the list, then `ops/cleanup/stage3_delete.sh --confirm-saved` and type `DELETE`. **This cannot be undone.**
7. Manual rows (2, 36, 44 to 48) when you want, after the reinstall with `ops/install.sh` for row 47.

## SAVE FIRST steps (owner steps)

Nobody ran these steps. Replace `BACKUP_USER@BACKUP_HOST:/backup/agx02` and `RK_USER@<da01-ip>:/PATH/ON/DA01` with real values (open questions 4 and 6). `YYYYMMDD` = date of the save step. `/home/tonyho/backup` does not exist yet; the commands make it. It is on the same disk, so it is not an off-board backup.

**SF-1, row 1, `/home/tonyho/driveragent` (2 unpushed commits).** The push is the recommended step (push access not tested). The bundle is a local copy of all branches.
```
mkdir -p /home/tonyho/backup/git
git -C /home/tonyho/driveragent bundle create /home/tonyho/backup/git/driveragent-$(date +%Y%m%d).bundle --all
git -C /home/tonyho/driveragent push origin claude/quizzical-elgamal-709408
```
Undo: `git -C /home/tonyho/driveragent push origin --delete claude/quizzical-elgamal-709408` and `rm /home/tonyho/backup/git/driveragent-YYYYMMDD.bundle`. The git-ignored secrets (`config.ini`, `control/.env`, `gcs_upload.json`) are not in the bundle. The repo stays in place, so they stay too. The owner decides where else to keep them (open question 10). Do not print them.

**SF-2, row 2, worktrees.** Do SF-1 first (`quizzical-elgamal-709408` holds the 2 unpushed commits).
```
mkdir -p /home/tonyho/backup/git
for w in /home/tonyho/driveragent/.claude/worktrees/quizzical-elgamal-709408 /home/tonyho/driveragent/.claude/worktrees/vigorous-wing-ea79d5 /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab /home/tonyho/driveragent/replay/.claude/worktrees/interesting-dhawan-7a9052; do git -C "$w" diff > /home/tonyho/backup/git/worktree-$(basename "$w")-$(date +%Y%m%d).patch; done
# then (row 2, DELETE):
git -C /home/tonyho/driveragent worktree remove --force /home/tonyho/driveragent/.claude/worktrees/quizzical-elgamal-709408
git -C /home/tonyho/driveragent worktree remove --force /home/tonyho/driveragent/.claude/worktrees/vigorous-wing-ea79d5
git -C /home/tonyho/driveragent worktree remove --force /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab
git -C /home/tonyho/driveragent worktree remove --force /home/tonyho/driveragent/replay/.claude/worktrees/interesting-dhawan-7a9052
```
Undo (example; the branches stay in the repo): `git -C /home/tonyho/driveragent worktree add /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab claude/cool-dirac-3995ab && git -C /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab apply /home/tonyho/backup/git/worktree-cool-dirac-3995ab-YYYYMMDD.patch`.

**SF-3, row 3, YOLOPX (67 uncommitted).** A push is not possible (third-party origin).
```
mkdir -p /home/tonyho/backup/git
git -C /home/tonyho/model/yolopx/YOLOPX diff > /home/tonyho/backup/git/YOLOPX-$(date +%Y%m%d).patch
git -C /home/tonyho/model/yolopx/YOLOPX ls-files --others --exclude-standard -z | tar -C /home/tonyho/model/yolopx/YOLOPX --null -T - -czf /home/tonyho/backup/git/YOLOPX-untracked-$(date +%Y%m%d).tar.gz
```
Undo: `tar -C /home/tonyho/model/yolopx/YOLOPX -xzf /home/tonyho/backup/git/YOLOPX-untracked-YYYYMMDD.tar.gz && git -C /home/tonyho/model/yolopx/YOLOPX apply /home/tonyho/backup/git/YOLOPX-YYYYMMDD.patch`. The repo stays (KEEP); this step only makes a copy.

**SF-4, row 4, gstreamer (2 untracked; subprojects).**
```
mkdir -p /home/tonyho/backup/git
cp /home/tonyho/Downloads/gstreamer/build/meson-logs/install-log.txt /home/tonyho/backup/git/gstreamer-1.24.12-install-log.txt
cp /home/tonyho/Downloads/gstreamer/build/meson-info/intro-buildoptions.json /home/tonyho/backup/git/gstreamer-1.24.12-buildoptions.json
cp /home/tonyho/Downloads/gstreamer/subprojects/gperf.wrap /home/tonyho/Downloads/gstreamer/subprojects/.wraplock /home/tonyho/backup/git/
for d in dv gl-headers gperf libavtp libmicrodns libnice opus orc vpx; do printf '%s %s %s\n' "$d" "$(git -C /home/tonyho/Downloads/gstreamer/subprojects/$d remote get-url origin)" "$(git -C /home/tonyho/Downloads/gstreamer/subprojects/$d rev-parse HEAD)"; done > /home/tonyho/backup/git/gstreamer-subprojects-heads.txt
```
Undo after stage 3: `git clone https://gitlab.freedesktop.org/gstreamer/gstreamer.git /home/tonyho/Downloads/gstreamer && git -C /home/tonyho/Downloads/gstreamer checkout 1.24.12`, copy `gperf.wrap` back, configure with the saved build options (prefix `/opt/gst-1.24`). `install-log.txt` is the only list of the files in `/opt/gst-1.24`.

**SF-5, row 5, libnice (1 untracked).** `make uninstall` needs the full tree.
```
mkdir -p /home/tonyho/backup/git
tar -C /home/tonyho/Downloads -czf /home/tonyho/backup/git/libnice-0.1.15-buildtree-$(date +%Y%m%d).tar.gz libnice
```
Undo after stage 3: `tar -C /home/tonyho/Downloads -xzf /home/tonyho/backup/git/libnice-0.1.15-buildtree-YYYYMMDD.tar.gz`.

**SF-6, row 6, jetson-jtop-patch (1 modified).**
```
mkdir -p /home/tonyho/backup/git
git -C /home/tonyho/Downloads/jetson-jtop-patch diff > /home/tonyho/backup/git/jetson-jtop-patch-$(date +%Y%m%d).patch
```
Undo: `git -C /home/tonyho/Downloads/jetson-jtop-patch apply /home/tonyho/backup/git/jetson-jtop-patch-YYYYMMDD.patch`. The repo stays (KEEP).

**SF-7, rows 7 and 8, recordings (533.9 GiB).** Copy to another machine and compare. Do it before stage 2 (simple paths) or after stage 2 (then use the archive paths from `manifest.tsv`).
```
rsync -a --partial --info=progress2 --include='/8003-*/***' --include='/8003-*.tar.bz2' --include='/uploaded.db' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
rsync -a --checksum --dry-run --itemize-changes --include='/8003-*/***' --include='/8003-*.tar.bz2' --include='/uploaded.db' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/   # must print nothing
gsutil ls gs://carvideo_osmosisai/8003/ | wc -l   # optional; expect 1869 or more
```
Undo: the copy does not change the AGX. After stage 3: `rsync -a BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/ /home/tonyho/driveragent/logger/video/`.

**SF-8, row 9, map data.** Only if the RK3588 or another machine needs it (open question 4). The tiles folder has root-owned folders but all files are readable, so rsync needs no sudo.
```
rsync -a --partial --info=progress2 /home/tonyho/driveragent/location/valhalla_tiles /home/tonyho/driveragent/location/valhalla.json /home/tonyho/driveragent/location/united-kingdom-latest.osm.pbf /home/tonyho/driveragent/location/gb.mbtiles /home/tonyho/driveragent/location/england_greater-london.mbtiles /home/tonyho/driveragent/dev/uk.mbtiles RK_USER@<da01-ip>:/PATH/ON/DA01/maps/
```
Undo: the copy does not change the AGX. The `.osm.pbf` can also come again from Geofabrik (newer version).

**SF-9, row 10, calcam.**
```
mkdir -p /home/tonyho/backup/calcam && cp -a /home/tonyho/Downloads/calcam/calcam.py /home/tonyho/Downloads/calcam/cam*.yaml /home/tonyho/backup/calcam/
```
Optional: `rsync -a /home/tonyho/backup/calcam/ RK_USER@<da01-ip>:/PATH/ON/DA01/calibration/agx02_calcam/`. Undo after stage 3: `mkdir -p /home/tonyho/Downloads/calcam && cp -a /home/tonyho/backup/calcam/. /home/tonyho/Downloads/calcam/`.

**SF-10 (optional), row 20, exact Valhalla image.** The `latest` tag on ghcr.io can change.
```
mkdir -p /home/tonyho/backup && docker save ghcr.io/valhalla/valhalla:latest | gzip > /home/tonyho/backup/valhalla_latest_063da86ba07c.tar.gz
```
Undo after stage 3: `gunzip -c /home/tonyho/backup/valhalla_latest_063da86ba07c.tar.gz | docker load`.

## Scripts

All three scripts are in `ops/cleanup/` with `common.sh` (shared functions). Nobody ran them on AGX02. They were checked with `bash -n` and `shellcheck` 0.11.0 (no finding), and with dry runs in a fake environment on DA01 (stub `systemctl`, `docker`, `snap`, `sudo`; fake home with config, manifest, sessions and a git repo).

Common rules of the three scripts:
- `set -euo pipefail`. Run as `tonyho` on `agx02`. The scripts refuse root (also `sudo ./script`), another user and another host. Commands that need root use `sudo` inside the script.
- The script prints the full list with sizes or states first. Then the user must type the word: `DISABLE` (stage 1), `ARCHIVE` (stage 2), `RESTORE` / `UNDO` (undo), `DELETE` (stage 3). Other input stops the script before any change.
- `--dry-run` prints the list and the commands and changes nothing. **When stdin is not a terminal, the script always does a dry run** (it cannot ask for the typed word).
- The KEEP check runs at run time (stage 2 and stage 3): `~/driveragent-agx`, `~/agx-models`, `~/model`, `~/.local`, `~/.config`, `~/.ssh`, `~/agx-installtest`, `~/agx-night-dev` and everything in them; every path in `~/driveragent-agx/config/*.yaml` (absolute paths, globs cut at the first wildcard, and names under `video_root`; the folders of `protected_dirs`, `scan_dirs` and `model_store` with everything in them); every `path:` of `~/agx-models/*/*/manifest.yaml`; the mount sources of running containers. A KEEP item, an item in a KEEP folder, or an item that contains a KEEP path is refused. If the config or a manifest cannot be read, the script stops (no partial KEEP list).
- State and logs: `~/.local/state/agx-cleanup/`.

| Script | What it does | Undo |
|---|---|---|
| `stage1_disable.sh [--with G]... [--dry-run]` | Group `base` (rows 18, 21 to 29); optional groups `nomachine`, `openvpn`, `avahi`, `update-timers`, `desktop` (rows 31 to 35). `systemctl disable --now` for enabled units, `stop` for units that are only active, `mask --now` for packagekit, `snap stop --disable cups`, `docker update --restart=no` + `docker stop` for the container, `systemctl set-default multi-user.target` for the desktop. It refuses a KEEP unit (jtop, nvpmodel, nvfancontrol, ssh, tailscaled, systemd-*, NetworkManager, docker, containerd, agx-*, rk-*, NVIDIA base units). It writes the state before each change to `stage1-<time>.tsv`. `--list` shows all items. | `stage1_disable.sh --undo [STATE_FILE]`: enable, start, unmask, `snap start --enable`, restart policy and start of the container, old default target. In reverse order. |
| `stage2_archive.sh [--archive DIR] [--dry-run]` | Moves rows 4, 5, 7, 8, 9, 10, 37, 38, 39 to `~/_archive_<YYYYMMDD>/files/<original path>`. It refuses: KEEP items (the 7 sim sessions of row 30), items mounted by a running container (row 9 while row 18 runs), the current folder of a process, an item on another file system or mount than the archive (then `mv` would copy), a folder that the user cannot write. It writes `manifest.tsv` (original path, archive path, bytes, SAVE FIRST flag) line by line before each `mv`. The plan is in `stage2-plan-<time>.tsv`. | `stage2_archive.sh --undo [DIR]`: moves each item back (reverse order); it skips an item when the original path exists again. |
| `stage3_delete.sh [--archive DIR]... [--confirm-saved] [--no-docker] [--dry-run]` | Deletes the stage 2 archive(s) with `sudo rm -rf --one-file-system` (only folders `~/_archive_*` with a `manifest.tsv`), then `docker rm driveragent-valhalla` and `docker rmi ghcr.io/valhalla/valhalla:latest` (ID must start with 063da86ba07c; no other container may use it). No prune of any kind. It refuses: a running Valhalla container, a KEEP path in an archive, an original path that is a KEEP item now. It needs `--confirm-saved` when the archive has SAVE FIRST items or git repositories with uncommitted, unpushed or stashed work (read-only git checks at run time). It keeps a copy of each manifest in `~/.local/state/agx-cleanup/`. | **None. Stage 3 cannot be undone.** `--undo` stops with this message. |

## Notes

**N-1, row 36, desktop helpers (only if the desktop stays).** No sudo. Do not use `pkill -f`; use the PIDs.
```
mkdir -p ~/.config/autostart
printf '[Desktop Entry]\nHidden=true\n' > ~/.config/autostart/gnome-software-service.desktop
printf '[Desktop Entry]\nHidden=true\n' > ~/.config/autostart/update-notifier.desktop
printf '[Desktop Entry]\nHidden=true\n' > ~/.config/autostart/nvpmodel_indicator.desktop
systemctl --user mask tracker-miner-fs-3.service tracker-extract-3.service
```
The programs stop at the next desktop login (or stop them now with `kill <PID>`; PIDs from `pgrep -x gnome-software`, `pgrep -x update-notifier`). Undo: `rm ~/.config/autostart/gnome-software-service.desktop ~/.config/autostart/update-notifier.desktop ~/.config/autostart/nvpmodel_indicator.desktop && systemctl --user unmask tracker-miner-fs-3.service tracker-extract-3.service`. Do not remove the packages: `ubuntu-desktop` needs `update-manager` and `update-notifier`.

**N-2, desktop risk (row 35).** After the next boot, a monitor on the AGX shows only a text console. NoMachine cannot attach to a physical desktop. USB disks do not mount by themselves. ssh and tailscale are not affected. Do this row only after you confirm ssh over tailscale.

**N-3, installed outputs that stay (row 37 and rows 4, 5).** Stage 2 and stage 3 move or delete only the source trees. These installed files stay (their removal needs root and is not in this proposal): `/opt/gst-1.24` (row 4), `/usr/lib/aarch64-linux-gnu/libnice.so.10.8.0` (row 5), `/usr/local/lib/libraylib.so*`, `/usr/local/lib/libmbgl-core.so`, `/usr/local/bin/cmake` 3.31.7, OpenCV 4.10.0 in `/usr` (cv2 4.10.0 loads from there). Rebuild after stage 3 (undo of row 37): raylib `git clone https://github.com/raysan5/raylib.git && git checkout 9f831428`; maplibre-native `git clone --recursive https://github.com/maplibre/maplibre-native.git && git checkout 8f50a549275` (about 30 min); OpenCV 4.10.0 and opencv_contrib 4.10.0 from GitHub with `~/Downloads/OpenCV-4-10-0.sh` (several hours); cmake from `~/Downloads/cmake-3.31.7.tar.gz` (kept, row 53).

**N-4, row 44, snaps.** Do the cups row first, chromium before its runtimes. `snap remove` keeps a snapshot of the user data (`snap saved`). To keep the exact revisions, copy the `.snap` files first (root-only files, about 1.8 GiB).
```
mkdir -p /home/tonyho/backup/snaps
sudo cp -p /var/lib/snapd/snaps/cups_1261.snap /var/lib/snapd/snaps/core26_463.snap /home/tonyho/backup/snaps/
sudo snap remove cups && sudo snap remove core26
sudo cp -p /var/lib/snapd/snaps/chromium_3535.snap /home/tonyho/backup/snaps/
sudo snap remove chromium
sudo cp -p /var/lib/snapd/snaps/gnome-46-2404_169.snap /var/lib/snapd/snaps/mesa-2404_1836.snap /var/lib/snapd/snaps/gtk-common-themes_1535.snap /var/lib/snapd/snaps/core24_2125.snap /var/lib/snapd/snaps/bare_5.snap /home/tonyho/backup/snaps/
sudo snap remove gnome-46-2404 && sudo snap remove mesa-2404 && sudo snap remove gtk-common-themes && sudo snap remove core24 && sudo snap remove bare
sudo cp -p /var/lib/snapd/snaps/gnome-42-2204_264.snap /var/lib/snapd/snaps/core22_2956.snap /home/tonyho/backup/snaps/
sudo snap remove gnome-42-2204 && sudo snap remove core22
```
Undo (store revision, can be newer; bases first): `sudo snap install core26 && sudo snap install cups`; `sudo snap install core24 bare gtk-common-themes mesa-2404 gnome-46-2404 && sudo snap install chromium`; `sudo snap install core22 && sudo snap install gnome-42-2204`. Exact revision: `sudo snap install --dangerous /home/tonyho/backup/snaps/<name>_<rev>.snap` in the same order. User data: `snap saved`, then `sudo snap restore <set-id>`. If row 44 is done, row 29 (stage 1 undo for cups) has nothing to restore.

**N-5, row 46, apt packages.** Run each simulation first (no root). If the list shows `ubuntu-desktop`, `gnome-shell`, `gdm3`, `nautilus`, or any `nvidia-*`, `cuda-*`, `libnvinfer*`, `tensorrt*`, `libcudnn*`, `gstreamer*` or `python3-*` package, stop.
```
apt-get -s remove thunderbird thunderbird-gnome-support libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-draw libreoffice-math aisleriot gnome-mahjongg gnome-mines gnome-sudoku rhythmbox rhythmbox-plugins rhythmbox-plugin-alternative-toolbar rhythmbox-data totem totem-plugins totem-common shotwell shotwell-common cheese transmission-gtk transmission-common remmina remmina-common remmina-plugin-rdp remmina-plugin-secret remmina-plugin-vnc deja-dup simple-scan gnome-calendar gnome-todo printer-driver-brlaser printer-driver-c2esp printer-driver-foo2zjs printer-driver-foo2zjs-common printer-driver-m2300w printer-driver-min12xxw printer-driver-ptouch printer-driver-sag-gdi foomatic-filters ipp-usb sane-utils orca brltty speech-dispatcher speech-dispatcher-audio-plugins speech-dispatcher-espeak-ng qemu-efi qemu-efi-aarch64
# if the list is correct: the same command with "sudo apt-get remove" instead of "apt-get -s remove"
```
Undo: `sudo apt-get install <the same package list>` (the first proposal of 2026-10-05, notes 34 and 35, has the exact versions: `git show 970d5ac:docs/CLEANUP_PROPOSAL.md`).

**N-6, row 47, old-stack user pip packages.** Do it after the reinstall with `ops/install.sh` (then the live venv does not read `~/.local`). No sudo.
```
python3 -m pip freeze --user > ~/pip-user-freeze-$(date +%F).txt
python3 -m pip uninstall raylib python-can pyubx2 pynmeagps pynmea2 pyrtcm google-cloud-storage google-cloud mapbox-vector-tile
```
Undo: `python3 -m pip install --user raylib==5.5.0.3 python-can==4.6.1 pyubx2==1.2.58 pynmeagps==1.0.54 pynmea2==1.19.0 pyrtcm==1.1.9 google-cloud-storage==3.4.1 google-cloud==0.34.0 mapbox-vector-tile==2.2.0`. After this row, the old code in `/home/tonyho/driveragent` cannot run its UI, CAN, GNSS, upload and map parts on this AGX.

**N-7, row 48, caches.**
```
python3 -m pip cache purge
ccache -C
sudo rm -rf /root/.cache/ccache
sudo apt-get clean
```
No undo is necessary: the tools fill the caches again when they need them.

## Open questions for the owner

1. Does the push of SF-1 work (push access not tested)?
2. What is OpenVPN `uk-ovpn-agent-20` for? (stage 1 group `openvpn`)
3. Does anybody use NoMachine, the local monitor or the desktop? (groups `nomachine`, `desktop`)
4. Does the RK3588 (DA01) or another machine need the map data or Valhalla? Where must it go? (SF-8)
5. Does any DA01 config use `agx02.local`? (group `avahi`)
6. Which machine takes the recordings (about 534 GiB)? Is the GCS bucket enough? (SF-7)
7. Who installs security updates by hand if the update timers stop? (group `update-timers`)
8. Are `cam0.yaml` to `cam5.yaml` still valid? Does the inference code need them? (SF-9)
9. Does anything use `/opt/gst-1.24`? (row 52)
10. Where must the git-ignored secrets of `/home/tonyho/driveragent` go? (SF-1)
11. When does the owner install again with `ops/install.sh`? (rows 16 and 47)
12. Can the sim use other sessions, or a copy of the 7 sessions in a new place (for example `~/agx-data/video`)? Then `video_root` can change, and the full `/home/tonyho/driveragent` can go to the archive later (about 1.5 GiB more).
