# Cleanup proposal - agx02

This document is a proposal only. Nobody changed the machine tonight. The audit ran without root, because sudo needs a password. Thus, some data is partial, and the table marks these items "not visible without root" or "unknown". The source is `/home/tonyho/driveragent-agx/docs/audit/agx_audit_agx02_20261005_210334/report.md`. A copy is in `docs/AGX_AUDIT.md`. Four read-only analysts (git, services, storage, packages) checked the items again tonight. The owner must approve each row before somebody runs its command. Do all SAVE FIRST rows before any other row. Read note 1 (placeholders) and note 2 (order of work) before you start.

New role of this AGX: TensorRT inference and its own web dashboard. The RK3588 now does camera capture, preprocessing, HMI/UI, maps (Valhalla), recording, upload, CAN, decisions and display.

| # | Item | Type | Size or memory | What uses it | Proposal | Exact command | How to undo |
|---|---|---|---|---|---|---|---|
| 1 | `/home/tonyho/driveragent-agx` | git repository | 150M (.venv 36M, ref 111M, docs 3.4M) | New inference-node project, made tonight. This is the only copy. It has 0 commits and no remote (expected). 9 top-level entries are untracked. `.gitignore` excludes `.venv/`, `ref/` and `docs/audit/`. | SAVE FIRST, then KEEP | See note 37. | See note 37. |
| 2 | `/home/tonyho/driveragent` | git repository | 543G total (mostly git-ignored data); `.git` 81M | Old full DriverAgent stack. Reference code for the new project. `main` = `origin/main`. 2 unpushed commits are on local branch `claude/quizzical-elgamal-709408`. | SAVE FIRST, then KEEP | See note 3. | See note 3. |
| 3 | 4 linked worktrees of `/home/tonyho/driveragent` under `.claude/worktrees`, `ui/.claude/worktrees`, `replay/.claude/worktrees` | directory | 130M (2 x 14M + 88M + 14M) | Claude Code session worktrees. Last commits 2026-04-02 to 2026-05-10. 3 worktrees have 1 change: `.claude/settings.local.json`. `interesting-dhawan-7a9052` is clean. | SAVE FIRST, then DELETE | See note 4. | See note 4. |
| 4 | `/home/tonyho/model/yolopx/YOLOPX` | git repository | 807M (weights 379M, logs 109M) | Third-party YOLOPX clone. 67 local changes: 2 modified, 4 deleted, 61 untracked (incl. `weights/epoch-195.pth` and 5 local scripts). Inside the model folder. | SAVE FIRST, then KEEP | See note 5. | See note 5. |
| 5 | `/home/tonyho/Downloads/gstreamer` | git repository | 1.4G (.git 298M, subprojects 728M, build 338M) | GStreamer 1.24.12 source build. It installed `/opt/gst-1.24` (67M). No code reference to `/opt/gst-1.24` was found. 2 untracked files: `subprojects/.wraplock`, `subprojects/gperf.wrap`. 1 root-owned file. | SAVE FIRST, then DELETE | See note 6. | See note 6. |
| 6 | `/home/tonyho/Downloads/gstreamer/subprojects/{dv,gl-headers,gperf,libavtp,libmicrodns,libnice,opus,orc,vpx}` | git repository | In the 1.4G of row 5 (vpx 114M, opus 27M, others under 7M) | Meson subprojects of the gstreamer build. Third-party code. Only generated files are local. | SAVE FIRST, then DELETE | See note 7. | See note 7. |
| 7 | `/home/tonyho/Downloads/libnice` | git repository | 28M | libnice 0.1.15 build tree, prefix `/usr`. Likely the source of the unowned `/usr/lib/aarch64-linux-gnu/libnice.so.10.8.0` (inference, see note 30). 1 untracked file (`m4/pkg.m4`). 1 root-owned file in a tonyho folder, so `rm -rf` works without sudo. | SAVE FIRST, then DELETE | See note 8. | `tar -C /home/tonyho/Downloads -xzf /home/tonyho/backup/git/libnice-0.1.15-buildtree-YYYYMMDD.tar.gz` |
| 8 | `/home/tonyho/Downloads/jetson-jtop-patch` | git repository | 212K | jetsonhacks patch script for jtop. jtop stays. Only change: file mode of `apply_jtop_fix.sh`. | SAVE FIRST, then KEEP | `mkdir -p /home/tonyho/backup/git && git -C /home/tonyho/Downloads/jetson-jtop-patch diff > /home/tonyho/backup/git/jetson-jtop-patch-$(date +%Y%m%d).patch` | `git -C /home/tonyho/Downloads/jetson-jtop-patch apply /home/tonyho/backup/git/jetson-jtop-patch-YYYYMMDD.patch` |
| 9 | `/home/tonyho/Downloads/raylib` | git repository | 566M (.git 404M); 353 root-owned files | Clean raylib clone. It installed `/usr/local/lib/libraylib.so.5.5.0`. Only `driveragent/unused_bk` names raylib. UI moved to the RK3588. | SAVE FIRST, then DELETE | See note 9. | See note 9. |
| 10 | `/home/tonyho/opencv` | directory | 508M (build 214M, .cache 78M); 956 root-owned files | Build tree of OpenCV 4.10.0 that is installed in `/usr` (not owned by dpkg). The installed runtime stays. | SAVE FIRST, then DELETE | See note 10. | See note 10. |
| 11 | `/home/tonyho/Downloads/cmake-3.31.7` | directory | 520M; 119 root-owned files | Source and build of `/usr/local/bin/cmake` 3.31.7. The installed cmake stays. | SAVE FIRST, then DELETE | See note 11. | See note 11. |
| 12 | `ghcr.io/valhalla/valhalla:latest` (image 063da86ba07c, arm64) | image | 733MB | Only Docker image on the AGX. Used only by container `driveragent-valhalla` (row 52). | SAVE FIRST, then DELETE | See note 12. Do row 52 first. | See note 12. |
| 13 | `/home/tonyho/driveragent/logger/video/8003-202510*` (520 session folders) | directory | 74.9 GiB, 4674 files | Old 6-camera recordings, car 8003, 2025-10-21 to 2025-10-31. No process writes here. | SAVE FIRST, then DELETE | See note 14. | See note 14. |
| 14 | `/home/tonyho/driveragent/logger/video/8003-202511*` (1339 session folders) | directory | 191.3 GiB, 12049 files | Old 6-camera recordings, car 8003, 2025-11-01 to 2025-11-09. | SAVE FIRST, then DELETE | See note 15. | See note 15. |
| 15 | `/home/tonyho/driveragent/logger/video/8003-202512*` and `8003-202605*` (8 session folders) | directory | 1.5 GiB, 65 files | Test recordings, 2025-12-13 and 2026-05-10. | SAVE FIRST, then DELETE | See note 16. | See note 16. |
| 16 | `/home/tonyho/driveragent/logger/video/8003-*.tar.bz2` (1869 archives) | file | 267.4 GiB | Made by `logger/uploader.py` for GCS upload. `uploaded.db` marks all as uploaded. 2 archives have no raw folder. | SAVE FIRST, then DELETE | See note 17. | See note 17. |
| 17 | `/home/tonyho/driveragent/logger/video/uploaded.db` | file | 228 KB | SQLite list of uploaded archives (1942 rows). Only local record of what reached GCS. | SAVE FIRST, then KEEP | `mkdir -p /home/tonyho/backup && cp -a /home/tonyho/driveragent/logger/video/uploaded.db /home/tonyho/backup/uploaded.db.agx02.20261005` | `cp -a /home/tonyho/backup/uploaded.db.agx02.20261005 /home/tonyho/driveragent/logger/video/uploaded.db` |
| 18 | `/home/tonyho/Downloads/calcam` (`calcam.py`, `cam0.yaml` to `cam5.yaml`) | directory | about 34 KB without venv | Camera calibration script and 6 calibration files (2026-01-18/19). Not in any git repo. Cameras are now on the RK3588. | SAVE FIRST, then MOVE TO RK3588 | See note 18. | See note 18. |
| 19 | `jtop.service` (jetson-stats 4.3.2) | service | 24.4 MiB | GPU and temperature monitor. The new node and dashboard can read it. | KEEP | none (keep) | not applicable (nothing changed) |
| 20 | NVIDIA L4T boot and init units: `nv`, `nvfb-early`, `nvfb`, `nvfb-udev`, `nv-late-init`, `nvpower`, `nvpmodel`, `nvcpupowerfix`, `nv_nvsciipc_init`, `nvramoopsconfig`, `nv-l4t-bootloader-config`, `l4t-rootfs-validation-config`, `nv-l4t-usb-device-mode` (+ `-runtime`) | service | 0 (oneshot) | JetPack base system: power mode, first-boot config, NvSciIpc, A/B boot check, USB recovery port. Owned by `nvidia-l4t-*` packages. | KEEP | none (keep) | not applicable (nothing changed) |
| 21 | `nv-tee-supplicant`, `nv-ftpm-device-provision`, `nv-ms-tpm-removal` | service | 2.9 MiB; others 0 | OP-TEE client and firmware TPM. See note 31 for the exit status 1. | KEEP | none (keep) | not applicable (nothing changed) |
| 22 | `nvfancontrol.service` | service | 0.5 MiB | Fan control. Inference makes heat. | KEEP | none (keep) | not applicable (nothing changed) |
| 23 | `nvphs.service` | service | 0.7 MiB | NVIDIA power hinting daemon. | KEEP | none (keep) | not applicable (nothing changed) |
| 24 | `nvidia-pva-allowd.service` | service | 11.5 MiB | PVA accelerator allowlists (VPI). | KEEP | none (keep) | not applicable (nothing changed) |
| 25 | `nvs-service.service` | service | 1.8 MiB | NVIDIA sensor HAL daemon. | KEEP | none (keep) | not applicable (nothing changed) |
| 26 | `nvzramconfig.service` | service | 0 (oneshot); 30Gi zram swap, 0B used | Compressed RAM swap. Protects TensorRT engine load from out-of-memory. | KEEP | none (keep) | not applicable (nothing changed) |
| 27 | `nvweston`, `nvmemwarning`, `nvwifibt` | service | 0 (inactive) | Stock NVIDIA helpers. They ran at boot and exited. | KEEP | none (keep) | not applicable (nothing changed) |
| 28 | `nvgetty`, `serial-getty@ttyAMA0`, `serial-getty@ttyGS0`, `serial-getty@ttyTCU0` | service | about 0.2 MiB each | Serial login consoles. Recovery path if the network fails. | KEEP | none (keep) | not applicable (nothing changed) |
| 29 | Core system and remote access: `ssh`, `tailscaled`, `NetworkManager`, `wpa_supplicant`, `systemd-resolved`, `systemd-timesyncd`, `cron`, `anacron`, `rsyslog`, `haveged`, `seatd`, `sssd`, `systemd-oomd` | service | tailscaled 85 MiB (cgroup), NetworkManager 12.8 MiB, others small | Base OS and remote access. tailscale carries the link to the RK3588 (100.64.0.180). | KEEP | none (keep) | not applicable (nothing changed) |
| 30 | `docker.service`, `containerd.service`, `docker.socket` (docker-ce 29.4.3, nvidia-container-toolkit 1.16.2) | service | docker 147 MiB, containerd 79 MiB (cgroup) | Docker engine. Runs only `driveragent-valhalla` now. Task rule: keep. | KEEP | none (keep) | not applicable (nothing changed) |
| 31 | Maintenance timers: `anacron`, `dpkg-db-backup`, `man-db`, `e2scrub_all`, `fstrim`, `systemd-tmpfiles-clean` | timer | 0 | Stock Ubuntu housekeeping. | KEEP | none (keep) | not applicable (nothing changed) |
| 32 | Cron: `/etc/cron.d`, `/etc/cron.daily`, `/etc/cron.weekly`, `/etc/cron.monthly`; tonyho crontab | cron | n/a | Stock package files only. No DriverAgent job. tonyho has no crontab. Root crontab: not visible without root. | KEEP | none (keep) | not applicable (nothing changed) |
| 33 | `evolution-data-server`, `goa-daemon`, `ibus`, `gsd-*` (GNOME session helpers) | service | evolution-* about 150 MB, goa 37 MB, ibus about 87 MiB RSS | GNOME session parts. gnome-shell needs the packages. Row 35 stops them. | KEEP | none (keep) | not applicable (nothing changed) |
| 34 | `nvargus-daemon.service` | service | 15.2 MiB | Argus camera daemon. No `nvarguscamerasrc` use found. `/dev/video0` cannot open. Cameras are on the RK3588. The new dashboard only shows its state (`config/dashboard.yaml`, `old_units`). | DISABLE | `sudo systemctl disable --now nvargus-daemon.service` | `sudo systemctl enable --now nvargus-daemon.service` |
| 35 | Graphical desktop: `gdm.service`, `graphical.target`, GNOME session with auto-login for tonyho | service | about 1.4 GiB RSS (PSS 1379 MB) for the desktop session | Local HDMI and NoMachine desktop. Inference and the web dashboard do not need it. | DISABLE | `sudo systemctl set-default multi-user.target` then `sudo reboot` | `sudo systemctl set-default graphical.target` then `sudo reboot` |
| 36 | Desktop helpers: `accounts-daemon`, `power-profiles-daemon`, `switcheroo-control`, `udisks2`, `colord`, `rtkit-daemon` | service | about 40 MiB total | Desktop support only (accounts list, power profiles, USB auto-mount, color). | DISABLE | Covered by row 35: `sudo systemctl set-default multi-user.target` | `sudo systemctl set-default graphical.target` |
| 37 | `gnome-software` autostart (`/etc/xdg/autostart/gnome-software-service.desktop`) | autostart | 610 MiB RSS (largest process) | GNOME Software background update check. | DISABLE | See note 21. | `rm ~/.config/autostart/gnome-software-service.desktop` |
| 38 | `update-notifier` and `update-manager` window | autostart | update-manager 259 MiB RSS (open about 9.6 days), update-notifier 29 MiB | Desktop update pop-up. | DISABLE | See note 21. | `rm ~/.config/autostart/update-notifier.desktop` |
| 39 | `nvpmodel_indicator` tray icon | autostart | 20 python3 processes, PSS 69 MB | Power-mode tray icon. jtop and `nvpmodel` CLI do the same job. | DISABLE | See note 21. | `rm ~/.config/autostart/nvpmodel_indicator.desktop` |
| 40 | `tracker-miner-fs-3.service`, `tracker-extract-3.service` (user units) | service | 34 MB RSS; index 13 MB | GNOME file search indexer. It reads the large home folder. | DISABLE | `systemctl --user mask tracker-miner-fs-3.service tracker-extract-3.service && systemctl --user stop tracker-miner-fs-3.service tracker-extract-3.service` | `systemctl --user unmask tracker-miner-fs-3.service tracker-extract-3.service && systemctl --user start tracker-miner-fs-3.service` |
| 41 | `packagekit.service` (static) | service | 85 MiB RSS | Backend for GNOME Software and update-manager. apt does not use it. | DISABLE | `sudo systemctl mask --now packagekit.service` | `sudo systemctl unmask packagekit.service` |
| 42 | `nxserver.service` (NoMachine 9.5.7) | service | about 394 MiB RSS; port 4000 open | Remote desktop. Last client: 2026-09-25 16:33, 7 s. | DISABLE | `sudo systemctl disable --now nxserver.service` | `sudo systemctl enable --now nxserver.service` |
| 43 | `bluetooth.service` | service | 1.9 MiB | Bluetooth stack. No use for inference. | DISABLE | `sudo systemctl disable --now bluetooth.service` | `sudo systemctl enable --now bluetooth.service` |
| 44 | `ModemManager.service` | service | 7.6 MiB | Modem manager. `mmcli -L`: no modems. | DISABLE | `sudo systemctl disable --now ModemManager.service` | `sudo systemctl enable --now ModemManager.service` |
| 45 | `apport-autoreport.service` (FAILED) + `.path` + `.timer` + `apport.service` | service | 0 | Crash report upload. Fails every 3 hours: whoopsie is not installed. | DISABLE | `sudo systemctl disable --now apport-autoreport.path apport-autoreport.timer apport.service && sudo systemctl reset-failed apport-autoreport.service` | `sudo systemctl enable --now apport.service apport-autoreport.path apport-autoreport.timer` |
| 46 | `kerneloops.service` | service | 1.4 MiB | Sends kernel oops reports to Ubuntu. | DISABLE | `sudo systemctl disable --now kerneloops.service` | `sudo systemctl enable --now kerneloops.service` |
| 47 | `avahi-daemon.service` + `.socket` | service | 1.9 MiB | mDNS name `agx02.local`. The RK3588 uses tailscale IPs. | DISABLE | `sudo systemctl disable --now avahi-daemon.service avahi-daemon.socket` (only after note 24 check) | `sudo systemctl enable --now avahi-daemon.socket avahi-daemon.service` |
| 48 | `rpcbind.service` + `.socket` | service | 2.0 MiB; port 111 open | NFS port mapper. No NFS mounts exist. | DISABLE | `sudo systemctl disable --now rpcbind.service rpcbind.socket` | `sudo systemctl enable --now rpcbind.socket rpcbind.service` |
| 49 | `openvpn.service` + `openvpn@uk-ovpn-agent-20.service` | service | 3.6 MiB | OpenVPN client to 139.162.209.77:1194. It does not connect (see note 25). | DISABLE | `sudo systemctl disable --now openvpn.service openvpn@uk-ovpn-agent-20.service` (only after owner check) | `sudo systemctl enable --now openvpn.service && sudo systemctl start openvpn@uk-ovpn-agent-20.service` |
| 50 | Update timers: `apt-daily`, `apt-daily-upgrade`, `update-notifier-download`, `update-notifier-motd`, `motd-news`, `fwupd-refresh`, `ua-timer`, `snapd.snap-repair` | timer | 0 | Background package downloads and update pop-ups. | DISABLE | See note 26. | See note 26. |
| 51 | `snapd.service`, `snapd.socket`, `snapd.seeded.service` | service | 56 MiB RSS | Snap daemon. After rows 89 to 92, only the snapd snap stays. | DISABLE | `sudo systemctl disable --now snapd.service snapd.socket snapd.seeded.service` (last step, see note 27) | `sudo systemctl enable --now snapd.socket snapd.service snapd.seeded.service` |
| 52 | `driveragent-valhalla` (container, restart `unless-stopped`) | container | 128 MiB RSS; writable layer 0B; port 8002 | Old map routing. Only old-stack item that starts at boot. Last request 2026-09-25 09:08. No client now. | MOVE TO RK3588 | `docker update --restart=no driveragent-valhalla && docker stop driveragent-valhalla` | `docker update --restart=unless-stopped driveragent-valhalla && docker start driveragent-valhalla` |
| 53 | `/home/tonyho/driveragent/location/valhalla_tiles` (+ `valhalla.json`, tracked in git) | directory | 2.4G | Valhalla routing tiles, bind-mounted into row 52. The container made 88 root-owned folders (1436 root-owned entries). The delete needs sudo. | MOVE TO RK3588 | See note 28. | See note 28. |
| 54 | `/home/tonyho/driveragent/location/united-kingdom-latest.osm.pbf` | file | 1.9G (1970984358 bytes) | OSM source to build tiles. | MOVE TO RK3588 | See note 28. | See note 28. |
| 55 | `/home/tonyho/driveragent/location/gb.mbtiles` + `england_greater-london.mbtiles` | file | 1.2G + 82M (1226051584 + 85114880 bytes) | Map display tiles for the old UI. | MOVE TO RK3588 | See note 28. | See note 28. |
| 56 | `/home/tonyho/driveragent/dev/uk.mbtiles` | file | 1.6G | Second UK tile set (dev copy). | MOVE TO RK3588 | See note 28. | See note 28. |
| 57 | `/home/tonyho/driveragent/location/mapgen` (binary) | file | 143M | Map image generator of the old UI. Git-ignored. | DELETE | `mkdir -p /home/tonyho/backup && cp -a /home/tonyho/driveragent/location/mapgen /home/tonyho/backup/mapgen.agx02 && rm /home/tonyho/driveragent/location/mapgen` | `cp -a /home/tonyho/backup/mapgen.agx02 /home/tonyho/driveragent/location/mapgen` |
| 58 | `/home/tonyho/Downloads/maplibre-native` | git repository | 4.9G (.git 3.2G, build 867M) | Clean clone, map renderer for the old mapgen. Maps are on the RK3588. | DELETE | `rm -rf /home/tonyho/Downloads/maplibre-native` | See note 29. |
| 59 | `/home/tonyho/opencv_contrib` | directory | 105M | Extra-module source (4.10.0 zip, from `OpenCV-4-10-0.sh`) for the OpenCV build. The runtime does not read it. | DELETE | `rm -rf /home/tonyho/opencv_contrib` | `wget -O /home/tonyho/opencv_contrib-4.10.0.zip https://github.com/opencv/opencv_contrib/archive/4.10.0.zip && unzip -q /home/tonyho/opencv_contrib-4.10.0.zip -d /home/tonyho && mv /home/tonyho/opencv_contrib-4.10.0 /home/tonyho/opencv_contrib && rm /home/tonyho/opencv_contrib-4.10.0.zip` |
| 60 | `/home/tonyho/jetson_out` | directory | 1.7M | Test output, 2026-05-11. No code reference. | DELETE | `mkdir -p /home/tonyho/backup && tar czf /home/tonyho/backup/jetson_out.tgz -C /home/tonyho jetson_out && rm -rf /home/tonyho/jetson_out` | `tar xzf /home/tonyho/backup/jetson_out.tgz -C /home/tonyho` |
| 61 | `/home/tonyho/Downloads/calcam/venv` | directory | 187M | venv for `calcam.py` only (numpy 2.2.6, opencv-python 4.10.0.84). Do row 18 first. | DELETE | `rm -rf /home/tonyho/Downloads/calcam/venv` | `python3 -m venv /home/tonyho/Downloads/calcam/venv && /home/tonyho/Downloads/calcam/venv/bin/pip install numpy==2.2.6 opencv-python==4.10.0.84` |
| 62 | `/home/tonyho/Downloads/nomachine.deb` | file | 72M | Old installer: the .deb is version 9.1.24-6. The installed package is 9.5.7-3, so the system does not need this file. | DELETE | `rsync -a /home/tonyho/Downloads/nomachine.deb BACKUP_USER@BACKUP_HOST:/backup/agx02/Downloads/ && rm /home/tonyho/Downloads/nomachine.deb` | `rsync -a BACKUP_USER@BACKUP_HOST:/backup/agx02/Downloads/nomachine.deb /home/tonyho/Downloads/` |
| 63 | `/home/tonyho/agx_audit_agx02_20261005_202230` | directory | 2.8M | Earlier audit run (20:22). The 21:03 run replaces it. | DELETE | `mkdir -p /home/tonyho/backup && tar czf /home/tonyho/backup/agx_audit_agx02_20261005_202230.tgz -C /home/tonyho agx_audit_agx02_20261005_202230 && rm -rf /home/tonyho/agx_audit_agx02_20261005_202230` | `tar xzf /home/tonyho/backup/agx_audit_agx02_20261005_202230.tgz -C /home/tonyho` |
| 64 | `/home/tonyho/.cache/pip` | directory | 31M | pip download cache. | DELETE | `rsync -a /home/tonyho/.cache/pip BACKUP_USER@BACKUP_HOST:/backup/agx02/cache/ && rm -rf /home/tonyho/.cache/pip` | `rsync -a BACKUP_USER@BACKUP_HOST:/backup/agx02/cache/pip /home/tonyho/.cache/` |
| 65 | `/home/tonyho/.cache/ccache` | directory | 283M | Compiler cache from the 2025-10-13 builds. | DELETE | `rsync -a /home/tonyho/.cache/ccache BACKUP_USER@BACKUP_HOST:/backup/agx02/cache/ && ccache -C` | `rsync -a BACKUP_USER@BACKUP_HOST:/backup/agx02/cache/ccache /home/tonyho/.cache/` |
| 66 | `/var/cache/apt` | directory | 601M total; archives 465M (361 .deb, no NVIDIA .deb) | apt download cache. | DELETE | `rsync -a --include='*.deb' --exclude='*' /var/cache/apt/archives/ BACKUP_USER@BACKUP_HOST:/backup/agx02/apt-archives/ && sudo apt-get clean` | `mkdir -p /home/tonyho/backup/apt-archives && rsync -a BACKUP_USER@BACKUP_HOST:/backup/agx02/apt-archives/ /home/tonyho/backup/apt-archives/ && sudo cp -p /home/tonyho/backup/apt-archives/*.deb /var/cache/apt/archives/` (apt rebuilds `pkgcache.bin` by itself) |
| 67 | `/home/tonyho/driveragent-agx/ref/driveragent-hmi` | git repository | 111M | Clean reference clone of the RK3588 HMI project. All commits are on the remote. | KEEP | none (keep) | not applicable (nothing changed) |
| 68 | `/home/tonyho/driveragent-agx/.venv` | directory | 36M | venv of the new project. It loads torch from `~/.local` (tested). | KEEP | none (keep) | not applicable (nothing changed) |
| 69 | `/home/tonyho/driveragent/replay/unused/test.mp4`, `test1.mp4` | file | 72.1M | Test videos tracked in git. The worktree copy goes with row 3. | KEEP | none (keep) | not applicable (nothing changed) |
| 70 | `/opt/gst-1.24` | directory | 67M | Custom GStreamer 1.24 from row 5. User unknown. No code reference found. | KEEP | none (keep) | not applicable (nothing changed) |
| 71 | `/home/tonyho/Downloads/SG8A` and `SG8A.zip` | directory | 87M + 43M | GMSL camera driver kit. Needed after a re-flash or if cameras come back. | KEEP | none (keep) | not applicable (nothing changed) |
| 72 | `/home/tonyho/Downloads` small items: `gstwebrtcwrapper/`, `gstwebrtcwrapper.tar`, `cmake-3.31.7.tar.gz`, `gslist.txt`, `OpenCV-4-10-0.sh`, `uk-ovpn-agent-20.conf` | directory | about 15M | Small sources and scripts. The .conf can hold VPN credentials. | KEEP | none (keep) | not applicable (nothing changed) |
| 73 | TensorRT engines and ONNX: `/home/tonyho/model/jetson_bundle/engines/*.engine`, `/home/tonyho/model/sparsedrive/run/*.trt`, `jetson_bundle/onnx/*.onnx`, `sparsedrive/run/*.onnx`, `system1/backbone_nchw.onnx(+.data)` | directory | engines 120.8M + .trt 172.5M; ONNX about 910M | Core of the new inference role. | KEEP | none (keep) | not applicable (nothing changed) |
| 74 | `/home/tonyho/model/jetson_bundle/weights` (`yolopx_v2_epoch30.pth`, `dtcp_nusc_route_v1.pt`) | file | 476.8M | Source weights of the two active engines. | KEEP | none (keep) | not applicable (nothing changed) |
| 75 | `/home/tonyho/model/sparsedrive/checkpoints/best.pth` | file | 426.7M | Source checkpoint of the SparseDrive ONNX/TRT files. | KEEP | none (keep) | not applicable (nothing changed) |
| 76 | `/home/tonyho/model/system1/system1_deploy.pth`, `system1_scorer.pth` | file | 364.4M | PyTorch inference weights of `system1/run.py`. | KEEP | none (keep) | not applicable (nothing changed) |
| 77 | `/home/tonyho/model/stage2/checkpoints/stage2_convnext_v2_lr4/best.pth` | file | 311.5M | Only deployable stage2 artifact. No ONNX/engine yet. | KEEP | none (keep) | not applicable (nothing changed) |
| 78 | `/home/tonyho/model/stage2/checkpoints/stage2_convnext_v2_lr4/latest.pth` | file | 305.4M | Training resume point. Not used for inference. Inside the model folder (task rule: keep). | KEEP | none (keep) | not applicable (nothing changed). Optional later action: note 32. |
| 79 | `/home/tonyho/model/yolopx/YOLOPX/weights/epoch-195.pth` | file | 378.2M | Old YOLOPX v1 weights for `startmodel.sh`. Not the source of any engine. Inside the model folder. | KEEP | none (keep) | not applicable (nothing changed). Optional later action: note 32. |
| 80 | `/home/tonyho/model/yolopx/venv` | directory | 1.5G | PyTorch YOLOPX venv (torch 2.8.0) for `startmodel.sh`. Inside the model folder. | KEEP | none (keep) | not applicable (nothing changed). Optional later action: note 32. |
| 81 | `/home/tonyho/.local/lib/python3.10/site-packages` (all except row 100) | directory | 1.3G (torch 695M) | Inference runtime: torch, torch_tensorrt, pycuda, onnx, onnxruntime, numpy. The new `.venv` uses it. | KEEP | none (keep) | not applicable (nothing changed) |
| 82 | `/home/tonyho/.cache/torch`, `/home/tonyho/.cache/nvidia` | directory | 64K + 52M | PyTorch kernel cache and CUDA JIT cache. | KEEP | none (keep) | not applicable (nothing changed) |
| 83 | `/var/log/journal` and `/var/log` | directory | journal 88.0M; /var/log 131M | System logs. Default journald settings. | KEEP | none (keep) | not applicable (nothing changed) |
| 84 | `/var/crash` | directory | 4.0K, empty | Crash dump folder. Nothing to clean. | KEEP | none (keep) | not applicable (nothing changed) |
| 85 | `/home/tonyho/.local/share/Trash` | directory | 264K, 0 files | Desktop trash. Empty. | KEEP | none (keep) | not applicable (nothing changed) |
| 86 | `/home/tonyho/.vscode-server` | directory | 1.5G (cli 1.3G, 5 servers) | VS Code remote server. | KEEP | none (keep) | not applicable (nothing changed) |
| 87 | `/home/tonyho/.claude`, `/home/tonyho/.local/share/claude` | directory | 917M + 918M | Claude Code data and binaries. In use now. | KEEP | none (keep) | not applicable (nothing changed) |
| 88 | `/opt/nvidia` (nsight, vpi3), `/opt/ota_package`, `/usr/local/cuda-12.6` | directory | 2.4G + 343M; `/usr` 15G | JetPack SDK tools, OTA package, CUDA runtime. | KEEP | none (keep) | not applicable (nothing changed) |
| 89 | `cups` snap (rev 1261 + disabled 1237) and its base `core26` | package | about 41 MB RSS; disk 150 MiB; port 631 open | Printing. No printer use is known. core26 is the base of cups only. The new dashboard only shows the state of the cups units. | DELETE | See note 41. | See note 41. |
| 90 | `chromium` snap (rev 3535 + disabled 3527) and `~/snap/chromium` | package | 371.2 MiB + 124M user data | Web browser. Last profile write 2026-02-23. No script uses it. | DELETE | See note 41. | See note 41. |
| 91 | Snap runtimes for chromium only: `gnome-46-2404`, `mesa-2404`, `gtk-common-themes`, `core24`, `bare` | package | 1692 MiB | Only chromium connects to them. Do row 90 first. | DELETE | See note 41. | See note 41. |
| 92 | `gnome-42-2204` and `core22` snaps | package | 1144 MiB | No snap connects to them. | DELETE | See note 41. | See note 41. |
| 93 | `thunderbird`, `thunderbird-gnome-support` | package | 259.2 MiB | E-mail client. Never used (`~/.thunderbird` does not exist). | DELETE | `apt-get -s remove thunderbird thunderbird-gnome-support` then `sudo apt-get remove thunderbird thunderbird-gnome-support` (note 34) | `sudo apt-get install thunderbird=1:140.7.1+build1-0ubuntu0.22.04.1 thunderbird-gnome-support=1:140.7.1+build1-0ubuntu0.22.04.1` |
| 94 | LibreOffice apps: `libreoffice-writer`, `-calc`, `-impress`, `-draw`, `-math` | package | 94.5 MiB | Office suite. Last use 2025-10-23. Core packages stay (note 34). | DELETE | See note 35. | See note 35. |
| 95 | Games: `aisleriot`, `gnome-mahjongg`, `gnome-mines`, `gnome-sudoku` | package | 13.6 MiB | Games. | DELETE | See note 35. | See note 35. |
| 96 | Media and utility apps: rhythmbox, totem, shotwell, cheese, transmission, remmina, deja-dup, simple-scan, gnome-calendar, gnome-todo (21 packages) | package | 21.9 MiB | Desktop apps. No config folders found. | DELETE | See note 35. | See note 35. |
| 97 | Printer and scanner drivers (11 packages: `printer-driver-*`, `foomatic-filters`, `ipp-usb`, `sane-utils`) | package | 11.6 MiB | Printer and scanner support. | DELETE | See note 35. | See note 35. |
| 98 | Accessibility: `orca`, `brltty`, `speech-dispatcher` (+ 2 plugins) | package | 36.0 MiB | Screen reader and Braille. brltty can claim USB-serial adapters. | DELETE | See note 35. | See note 35. |
| 99 | `qemu-efi`, `qemu-efi-aarch64` | package | 258.1 MiB | UEFI images for QEMU VMs. No QEMU or libvirt is installed. | DELETE | `apt-get -s remove qemu-efi qemu-efi-aarch64` then `sudo apt-get remove qemu-efi qemu-efi-aarch64` | `sudo apt-get install qemu-efi=2022.02-3ubuntu0.22.04.5 qemu-efi-aarch64=2022.02-3ubuntu0.22.04.5` |
| 100 | Old DriverAgent user pip packages: raylib, python-can, pyubx2, pynmeagps, pynmea2, pyrtcm, google-cloud-storage, google-cloud, mapbox-vector-tile | package | about 23 MB | Old UI, CAN, GNSS, upload and map code only. No package requires them. | DELETE | See note 36. | See note 36. |
| 101 | `unattended-upgrades` | package | not installed | Nothing. No automatic upgrade can change JetPack. | KEEP | none (keep) | not applicable (nothing changed) |
| 102 | NVIDIA developer tools: nsight-compute, nsight-systems, nsight-graphics | package | about 2.2 GB | GPU profilers from nvidia-jetpack. Useful to profile engines. | KEEP | none (keep) | not applicable (nothing changed) |
| 103 | CUDA, cuDNN and TensorRT dev packages (`libcudnn9-cuda-12`, `libcublas-dev-12-6`, `libnvinfer-dev`, `cuda-nvcc-12-6` and others) | package | largest 955 MiB, 614 MiB, 586 MiB, 563 MiB | TensorRT engine build and runtime. Protected. | KEEP | none (keep) | not applicable (nothing changed) |
| 104 | JetPack samples: `libnvinfer-samples`, `nvidia-l4t-graphics-demos`, `vpi3-samples`, `nvidia-l4t-vulkan-sc-*` | package | about 349 MiB | Samples from nvidia-jetpack. Protected. | KEEP | none (keep) | not applicable (nothing changed) |
| 105 | `linux-firmware` | package | 1089.8 MiB | Kernel firmware files. Protected. | KEEP | none (keep) | not applicable (nothing changed) |
| 106 | Build toolchain: llvm-14, clang, cmake, build-essential, gcc-11 | package | about 481 MiB | Compilers for TensorRT plugins and native code. | KEEP | none (keep) | not applicable (nothing changed) |

## Notes

1. **Placeholders.** `RK_USER`, `/PATH/ON/RK3588`, `BACKUP_USER`, `BACKUP_HOST`, `/backup/agx02` and `REMOTE_URL` are placeholders. The owner must replace them. The RK3588 address `100.64.0.180` (tailscale0) comes from `raw/Link_to_RK3588.txt`. Free space on the RK3588 and on the backup host is unknown. Replace `YYYYMMDD` with the date of the save step. `/home/tonyho/backup` does not exist yet. The commands make it. It is on the same disk as the data, so it is not an off-board backup.

2. **Order of work.**
   1. Do all SAVE FIRST rows (1 to 18). Do row 2 before row 3.
   2. Confirm ssh access over tailscale. Then do the service rows (34 to 51). Do row 89 (cups) and row 35 (desktop) before row 51 (snapd).
   3. Do row 52 (container stop). Then row 12 (image). Then rows 53 to 56 (map data).
   4. Do the directory rows (57 to 66). Rows 62, 64, 65 and 66 need the backup host (note 1).
   5. Do the snap rows in this order: 89, 90, 91, 92. Then row 51.
   6. Do the apt and pip rows (93 to 100).
   Rows 37 to 40 are not necessary if you do row 35. They help only if you keep the desktop.

3. **Row 2, `/home/tonyho/driveragent`.** The push is the recommended step. The remote is the team GitHub repo (SSH), so the 2 commits leave this machine. The bundle is a local fallback. Push access was not tested (unknown).
   ```
   mkdir -p /home/tonyho/backup/git
   git -C /home/tonyho/driveragent bundle create /home/tonyho/backup/git/driveragent-$(date +%Y%m%d).bundle --all
   git -C /home/tonyho/driveragent push origin claude/quizzical-elgamal-709408
   ```
   Undo:
   ```
   git -C /home/tonyho/driveragent push origin --delete claude/quizzical-elgamal-709408
   git clone /home/tonyho/backup/git/driveragent-YYYYMMDD.bundle /home/tonyho/driveragent-restore
   rm /home/tonyho/backup/git/driveragent-YYYYMMDD.bundle
   ```
   Evidence: `git status --porcelain` = 0; `git log --branches --not --remotes` = 2 commits (0f266df, da3d058, 2026-05-07); stash = 0; remote `git@github.com:osmosishk/DriverAgent.git`. Risk: a bundle or a push saves only committed history. These git-ignored files are NOT saved by this row: `config.ini`, `assets.yaml`, `control/.env`, `gcs_upload.json` (3 copies), `ko/`, `location/*.mbtiles`, `location/united-kingdom-latest.osm.pbf`, `location/valhalla_tiles/`, `location/mapgen`, `logger/video/`, `visionipc/campub`, `visionipc/camtest`, logs. Other rows handle the data. The secrets have no row: the owner must decide where to keep them. Do not delete this repo.

4. **Row 3, worktrees.** Do row 2 first, because `quizzical-elgamal-709408` holds the 2 unpushed commits.
   ```
   mkdir -p /home/tonyho/backup/git
   for w in /home/tonyho/driveragent/.claude/worktrees/quizzical-elgamal-709408 /home/tonyho/driveragent/.claude/worktrees/vigorous-wing-ea79d5 /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab /home/tonyho/driveragent/replay/.claude/worktrees/interesting-dhawan-7a9052; do git -C "$w" diff > /home/tonyho/backup/git/worktree-$(basename "$w")-$(date +%Y%m%d).patch; done
   git -C /home/tonyho/driveragent worktree remove --force /home/tonyho/driveragent/.claude/worktrees/quizzical-elgamal-709408
   git -C /home/tonyho/driveragent worktree remove --force /home/tonyho/driveragent/.claude/worktrees/vigorous-wing-ea79d5
   git -C /home/tonyho/driveragent worktree remove --force /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab
   git -C /home/tonyho/driveragent worktree remove --force /home/tonyho/driveragent/replay/.claude/worktrees/interesting-dhawan-7a9052
   ```
   Undo, for each worktree (example):
   ```
   git -C /home/tonyho/driveragent worktree add /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab claude/cool-dirac-3995ab
   git -C /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab apply /home/tonyho/backup/git/worktree-cool-dirac-3995ab-YYYYMMDD.patch
   ```
   The branches stay in the main repo. The worktree copy of `replay/unused/*.mp4` (72M) goes with `cool-dirac-3995ab`.

5. **Row 4, YOLOPX.** A push is not possible: origin is a third-party repo (`jiaoZ7688/YOLOPX`). There are 0 local commits.
   ```
   mkdir -p /home/tonyho/backup/git
   git -C /home/tonyho/model/yolopx/YOLOPX diff > /home/tonyho/backup/git/YOLOPX-$(date +%Y%m%d).patch
   git -C /home/tonyho/model/yolopx/YOLOPX ls-files --others --exclude-standard -z | tar -C /home/tonyho/model/yolopx/YOLOPX --null -T - -czf /home/tonyho/backup/git/YOLOPX-untracked-$(date +%Y%m%d).tar.gz
   ```
   Undo:
   ```
   tar -C /home/tonyho/model/yolopx/YOLOPX -xzf /home/tonyho/backup/git/YOLOPX-untracked-YYYYMMDD.tar.gz
   git -C /home/tonyho/model/yolopx/YOLOPX apply /home/tonyho/backup/git/YOLOPX-YYYYMMDD.patch
   ```
   Risk: `weights/epoch-195.pth` is not in git and is not the same file as `jetson_bundle/weights/yolopx_v2_epoch30.pth`. Which weight made `yolopx_v2_fp16.engine`: the storage analyst says `yolopx_v2_epoch30.pth`; the git analyst says unknown.

6. **Row 5, gstreamer.** 1 file is root-owned: `build/meson-logs/install-log.txt` (`find ! -user tonyho`, run now). Its folder belongs to tonyho, so `rm -rf` works without sudo. The file is world-readable, so `cp` works.
   ```
   mkdir -p /home/tonyho/backup/git
   cp /home/tonyho/Downloads/gstreamer/build/meson-logs/install-log.txt /home/tonyho/backup/git/gstreamer-1.24.12-install-log.txt
   cp /home/tonyho/Downloads/gstreamer/build/meson-info/intro-buildoptions.json /home/tonyho/backup/git/gstreamer-1.24.12-buildoptions.json
   cp /home/tonyho/Downloads/gstreamer/subprojects/gperf.wrap /home/tonyho/backup/git/gstreamer-1.24.12-gperf.wrap
   rm -rf /home/tonyho/Downloads/gstreamer
   ```
   Undo:
   ```
   git clone https://gitlab.freedesktop.org/gstreamer/gstreamer.git /home/tonyho/Downloads/gstreamer && git -C /home/tonyho/Downloads/gstreamer checkout 1.24.12
   cp /home/tonyho/backup/git/gstreamer-1.24.12-gperf.wrap /home/tonyho/Downloads/gstreamer/subprojects/gperf.wrap
   ```
   Then configure with the saved build options (prefix `/opt/gst-1.24`) and build. `/opt/gst-1.24` stays installed. `install-log.txt` (1523 lines) is the only list of its files.

7. **Row 6, gstreamer subprojects.** Run this before row 5. The `rm -rf` of row 5 deletes them.
   ```
   mkdir -p /home/tonyho/backup/git
   for d in dv gl-headers gperf libavtp libmicrodns libnice opus orc vpx; do printf '%s %s %s\n' "$d" "$(git -C /home/tonyho/Downloads/gstreamer/subprojects/$d remote get-url origin)" "$(git -C /home/tonyho/Downloads/gstreamer/subprojects/$d rev-parse HEAD)"; done > /home/tonyho/backup/git/gstreamer-subprojects-heads.txt
   ```
   Undo: clone gstreamer again (note 6) and run `meson setup`. Meson downloads the subprojects again from the tracked `.wrap` files.

8. **Row 7, libnice.** Save the whole build tree. `make uninstall` needs it to remove the files in `/usr`.
   ```
   mkdir -p /home/tonyho/backup/git
   tar -C /home/tonyho/Downloads -czf /home/tonyho/backup/git/libnice-0.1.15-buildtree-$(date +%Y%m%d).tar.gz libnice
   rm -rf /home/tonyho/Downloads/libnice
   ```

9. **Row 9, raylib.** 353 files are root-owned (`find ! -user tonyho`, run now).
   ```
   mkdir -p /home/tonyho/backup/raylib && cp /home/tonyho/Downloads/raylib/build/install_manifest.txt /home/tonyho/backup/raylib/
   sudo rm -rf /home/tonyho/Downloads/raylib
   ```
   Undo: `git clone https://github.com/raysan5/raylib.git /home/tonyho/Downloads/raylib && git -C /home/tonyho/Downloads/raylib checkout 9f831428`, then rebuild with cmake.

10. **Row 10, OpenCV build tree.**
    ```
    mkdir -p /home/tonyho/backup/opencv-4.10.0 && cp /home/tonyho/opencv/build/install_manifest.txt /home/tonyho/opencv/build/CMakeCache.txt /home/tonyho/Downloads/OpenCV-4-10-0.sh /home/tonyho/backup/opencv-4.10.0/
    sudo rm -rf /home/tonyho/opencv
    ```
    Undo: `wget -O /home/tonyho/opencv-4.10.0.zip https://github.com/opencv/opencv/archive/4.10.0.zip && unzip -q /home/tonyho/opencv-4.10.0.zip -d /home/tonyho && mv /home/tonyho/opencv-4.10.0 /home/tonyho/opencv`, then rebuild with the options in the saved `CMakeCache.txt` (several hours). The installed OpenCV in `/usr` keeps working. Do row 59 (opencv_contrib) together with this row.

11. **Row 11, cmake 3.31.7 build.** Keep `/home/tonyho/Downloads/cmake-3.31.7.tar.gz`.
    ```
    mkdir -p /home/tonyho/backup/cmake-3.31.7 && cp /home/tonyho/Downloads/cmake-3.31.7/install_manifest.txt /home/tonyho/backup/cmake-3.31.7/
    sudo rm -rf /home/tonyho/Downloads/cmake-3.31.7
    ```
    Undo: `tar xzf /home/tonyho/Downloads/cmake-3.31.7.tar.gz -C /home/tonyho/Downloads && cd /home/tonyho/Downloads/cmake-3.31.7 && ./bootstrap && make -j8`.

12. **Row 12, Valhalla image.** The `latest` tag on ghcr.io can change. The saved file is the only exact copy.
    ```
    mkdir -p /home/tonyho/backup && docker save ghcr.io/valhalla/valhalla:latest | gzip > /home/tonyho/backup/valhalla_latest_063da86ba07c.tar.gz
    # optional: give the image to the RK3588
    scp /home/tonyho/backup/valhalla_latest_063da86ba07c.tar.gz RK_USER@100.64.0.180:/tmp/ && ssh RK_USER@100.64.0.180 'gunzip -c /tmp/valhalla_latest_063da86ba07c.tar.gz | docker load'
    # after row 52:
    docker rm driveragent-valhalla && docker rmi ghcr.io/valhalla/valhalla:latest
    ```
    Undo:
    ```
    gunzip -c /home/tonyho/backup/valhalla_latest_063da86ba07c.tar.gz | docker load && docker run -d --name driveragent-valhalla --restart unless-stopped -p 8002:8002 -v /home/tonyho/driveragent/location/valhalla.json:/data/valhalla.json -v /home/tonyho/driveragent/location/valhalla_tiles:/data/valhalla_tiles ghcr.io/valhalla/valhalla:latest valhalla_service /data/valhalla.json 4
    ```
    Or run `bash /home/tonyho/driveragent/location/setup_valhalla.sh`.

13. **Recordings (rows 13 to 17), common facts.** The recordings are on disk twice. `logger/video` is 536G (du). The raw session folders hold 11199 mp4 files (about 267.7 GiB). The 1869 `.tar.bz2` archives (267.4 GiB) hold the same sessions. Deleting either copy frees about 267 GiB. `uploaded.db` lists all 1869 archives as uploaded to bucket `carvideo_osmosisai`, prefix `8003/`. Nobody checked the bucket. 2 archives have no raw folder: `8003-20260101_124700.tar.bz2` (404MB) and `8003-20260401_153815.tar.bz2` (2.6MB). On this machine they are the only copy of those sessions. No logger, uploader or deleter process runs now. `logger/deleter.py` defaults to `CAR_ID` 8001, so it never matched these 8003 folders. The backup host needs about 535 GiB free (unknown). Run the checksum dry run before every delete. It must show no output. If the old uploader runs again, it makes new archives from the raw folders.

14. **Row 13, recordings Oct 2025.**
    ```
    rsync -a --partial --info=progress2 --include='/8003-202510*/***' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
    rsync -a --checksum --dry-run --itemize-changes --include='/8003-202510*/***' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
    find /home/tonyho/driveragent/logger/video -mindepth 1 -maxdepth 1 -type d -name '8003-202510*' -exec rm -rf {} +
    ```
    Undo: `rsync -a --include='/8003-202510*/***' --exclude='*' BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/ /home/tonyho/driveragent/logger/video/`

15. **Row 14, recordings Nov 2025.** This is the largest single saving.
    ```
    rsync -a --partial --info=progress2 --include='/8003-202511*/***' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
    rsync -a --checksum --dry-run --itemize-changes --include='/8003-202511*/***' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
    find /home/tonyho/driveragent/logger/video -mindepth 1 -maxdepth 1 -type d -name '8003-202511*' -exec rm -rf {} +
    ```
    Undo: `rsync -a --include='/8003-202511*/***' --exclude='*' BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/ /home/tonyho/driveragent/logger/video/`

16. **Row 15, recordings Dec 2025 and May 2026.**
    ```
    rsync -a --partial --info=progress2 --include='/8003-202512*/***' --include='/8003-202605*/***' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
    rsync -a --checksum --dry-run --itemize-changes --include='/8003-202512*/***' --include='/8003-202605*/***' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
    find /home/tonyho/driveragent/logger/video -mindepth 1 -maxdepth 1 -type d \( -name '8003-202512*' -o -name '8003-202605*' \) -exec rm -rf {} +
    ```
    Undo: `rsync -a --include='/8003-202512*/***' --include='/8003-202605*/***' --exclude='*' BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/ /home/tonyho/driveragent/logger/video/`

17. **Row 16, archives.** The optional `gsutil` check needs gcloud access.
    ```
    rsync -a --partial --info=progress2 --include='/8003-*.tar.bz2' --include='/uploaded.db' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
    rsync -a --checksum --dry-run --itemize-changes --include='/8003-*.tar.bz2' --include='/uploaded.db' --exclude='*' /home/tonyho/driveragent/logger/video/ BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/
    gsutil ls gs://carvideo_osmosisai/8003/ | wc -l   # expect 1869 or more
    find /home/tonyho/driveragent/logger/video -mindepth 1 -maxdepth 1 -type f -name '8003-*.tar.bz2' -delete
    ```
    Undo: `rsync -a --include='/8003-*.tar.bz2' --exclude='*' BACKUP_USER@BACKUP_HOST:/backup/agx02/logger/video/ /home/tonyho/driveragent/logger/video/`. Or, per file: `gsutil cp gs://carvideo_osmosisai/8003/<name>.tar.bz2 /home/tonyho/driveragent/logger/video/`.

18. **Row 18, calcam.** Do not delete the AGX copy before a copy exists on the RK3588 and off-board.
    ```
    mkdir -p /home/tonyho/backup/calcam && cp -a /home/tonyho/Downloads/calcam/calcam.py /home/tonyho/Downloads/calcam/cam*.yaml /home/tonyho/backup/calcam/
    rsync -a /home/tonyho/backup/calcam/ RK_USER@100.64.0.180:/PATH/ON/RK3588/calibration/agx02_calcam/
    ```
    If the inference code needs the camera intrinsics or extrinsics, also copy `cam*.yaml` into `/home/tonyho/driveragent-agx/config/`.
    Undo (these commands remove only the copies; the AGX files do not change):
    ```
    ssh RK_USER@100.64.0.180 'rm -rf /PATH/ON/RK3588/calibration/agx02_calcam'
    rm -rf /home/tonyho/backup/calcam
    ```
    If somebody deleted the AGX copy later, restore it: `mkdir -p /home/tonyho/Downloads/calcam && cp -a /home/tonyho/backup/calcam/. /home/tonyho/Downloads/calcam/`.

19. **Row 35, desktop, evidence.** `systemctl get-default` = `graphical.target`. `/etc/gdm3/custom.conf`: `AutomaticLoginEnable=True`, `AutomaticLogin=tonyho`, `WaylandEnable=false`. The 49 stock entries in `/etc/xdg/autostart` and the user units (pipewire, pulseaudio, tracker, gnome-keyring) also stop with this row. Do not edit or delete the `.desktop` files. `~/.config/autostart` does not exist now.

20. **Row 35, desktop, risk.** A monitor on the AGX shows only a text console. The nvpmodel tray icon goes away. Use `nvpmodel` or jtop. NoMachine cannot attach to a physical desktop. It must make a virtual desktop (behaviour unknown), or you use ssh. USB disks do not auto-mount (row 36). Save open work first: the reboot ends the session. ssh and tailscale are not affected. Do this row only after you confirm ssh over tailscale.

21. **Rows 37 to 39, autostart entries.** These need no sudo.
    ```
    mkdir -p ~/.config/autostart
    printf '[Desktop Entry]\nHidden=true\n' > ~/.config/autostart/gnome-software-service.desktop
    pkill -u tonyho -f 'gnome-software --gapplication-service'

    printf '[Desktop Entry]\nHidden=true\n' > ~/.config/autostart/update-notifier.desktop
    pkill -u tonyho -f /usr/bin/update-manager
    pkill -u tonyho -x update-notifier

    printf '[Desktop Entry]\nHidden=true\n' > ~/.config/autostart/nvpmodel_indicator.desktop
    pkill -u tonyho -f nvpmodel_indicator.py
    ```
    The undo removes the file. The program starts again at the next desktop login. Do not remove the packages: `ubuntu-desktop` has a hard Depends on `update-manager` and `update-notifier`, and `nvidia-l4t-*` is protected.

22. **Row 41, packagekit.** It is a static unit, so `disable` has no effect. `mask` is necessary. GNOME Software, update-manager and `pkcon` stop. apt and dpkg are not affected. Do not remove the package: `ubuntu-desktop` needs `gstreamer1.0-packagekit`.

23. **Row 42, NoMachine.** Last client 2026-09-25 16:33:33 from 10.0.0.124, closed after 7 s (`/usr/NX/var/log/daemon.log`; mtime 2026-09-25 16:33, checked now). Do this row after the owner confirms that nobody needs the remote desktop. Do not run `apt-get remove nomachine` now: no apt repository has it.

24. **Row 47, avahi.** The name `agx02.local` stops on the LAN. The RK3588 config is not on this machine, so nobody checked it. Disable avahi only if no RK3588 config uses `agx02.local`. Otherwise keep it.

25. **Row 49, OpenVPN.** Checked now: the unit is `active`, the journal shows reconnect attempts to 139.162.209.77:1194, and `/sys/class/net` has no `tun` interface. The services analyst saw `TLS key negotiation failed` and a restart every minute. The config file stays on disk. Keep tailscale. The owner must say what this VPN is for before the change.

26. **Row 50, update timers.**
    ```
    sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer update-notifier-download.timer update-notifier-motd.timer motd-news.timer fwupd-refresh.timer ua-timer.timer snapd.snap-repair.timer
    ```
    Undo:
    ```
    sudo systemctl enable --now apt-daily.timer apt-daily-upgrade.timer update-notifier-download.timer update-notifier-motd.timer motd-news.timer fwupd-refresh.timer ua-timer.timer snapd.snap-repair.timer
    ```
    Risk: security updates do not download automatically. The owner must run `sudo apt update && sudo apt upgrade` by hand. Benefit: no apt lock and no network use during a drive.

27. **Row 51, snapd.** Do this row last. `snap remove` needs snapd. Disable `snapd.socket` with `snapd.service`, or snapd starts again on demand. The `snap` command and auto-refresh stop. The packages analyst proposed KEEP. This table uses DISABLE (services analyst) because no app snap stays after rows 89 to 92.

28. **Rows 53 to 56, map data.** Do row 52 first: the container fails to start without the tiles. Confirm that the RK3588 Valhalla serves routes before you delete. Do not delete `valhalla.json`: git tracks it. `valhalla_tiles` has 88 root-owned folders (run now), so its delete needs sudo. All its files are readable, so rsync works without sudo.
    ```
    # row 53
    rsync -a --partial --info=progress2 /home/tonyho/driveragent/location/valhalla_tiles /home/tonyho/driveragent/location/valhalla.json RK_USER@100.64.0.180:/PATH/ON/RK3588/valhalla/
    rsync -a --checksum --dry-run --itemize-changes /home/tonyho/driveragent/location/valhalla_tiles /home/tonyho/driveragent/location/valhalla.json RK_USER@100.64.0.180:/PATH/ON/RK3588/valhalla/
    sudo rm -rf /home/tonyho/driveragent/location/valhalla_tiles
    # row 54
    rsync -a --partial --info=progress2 /home/tonyho/driveragent/location/united-kingdom-latest.osm.pbf RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/ && rsync -a --checksum --dry-run --itemize-changes /home/tonyho/driveragent/location/united-kingdom-latest.osm.pbf RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/ && rm /home/tonyho/driveragent/location/united-kingdom-latest.osm.pbf
    # row 55
    rsync -a --partial --info=progress2 /home/tonyho/driveragent/location/gb.mbtiles /home/tonyho/driveragent/location/england_greater-london.mbtiles RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/ && rsync -a --checksum --dry-run --itemize-changes /home/tonyho/driveragent/location/gb.mbtiles /home/tonyho/driveragent/location/england_greater-london.mbtiles RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/ && rm /home/tonyho/driveragent/location/gb.mbtiles /home/tonyho/driveragent/location/england_greater-london.mbtiles
    # row 56
    rsync -a --partial --info=progress2 /home/tonyho/driveragent/dev/uk.mbtiles RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/ && rsync -a --checksum --dry-run --itemize-changes /home/tonyho/driveragent/dev/uk.mbtiles RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/ && rm /home/tonyho/driveragent/dev/uk.mbtiles
    ```
    Undo:
    ```
    rsync -a RK_USER@100.64.0.180:/PATH/ON/RK3588/valhalla/valhalla_tiles /home/tonyho/driveragent/location/
    rsync -a RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/united-kingdom-latest.osm.pbf /home/tonyho/driveragent/location/
    rsync -a RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/gb.mbtiles RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/england_greater-london.mbtiles /home/tonyho/driveragent/location/
    rsync -a RK_USER@100.64.0.180:/PATH/ON/RK3588/maps/uk.mbtiles /home/tonyho/driveragent/dev/
    ```
    The `.osm.pbf` can also come again from Geofabrik (newer version).

29. **Row 58, maplibre-native.** The repo is clean: 0 local changes, 0 unpushed commits, 0 stashes. Undo:
    ```
    git clone --recursive https://github.com/maplibre/maplibre-native.git /home/tonyho/Downloads/maplibre-native && git -C /home/tonyho/Downloads/maplibre-native checkout 8f50a549275 && git -C /home/tonyho/Downloads/maplibre-native submodule update --init --recursive
    cmake -B build-linux-opengl -G Ninja -DCMAKE_BUILD_TYPE=Release -DMLN_WITH_OPENGL=ON && ninja -C build-linux-opengl mbgl-core
    ```
    The rebuild takes about 30 min. `location/mapgen` (row 57) cannot be rebuilt without it.

30. **Installed outputs that stay.** These rows delete only the source trees. These installed files stay. Their removal needs root and is not in this proposal:
    - `/opt/gst-1.24` (67M), from row 5. List of files: the saved `install-log.txt`.
    - `/usr/local/lib/libraylib.so*`, from row 9.
    - `/usr/local/lib/libmbgl-core.so`, from row 58 (`ls /usr/local/lib`, run now).
    - `/usr/local/bin/cmake` 3.31.7, from row 11. TensorRT tool builds use it.
    - OpenCV 4.10.0 in `/usr` (cv2 and `libopencv_*.so.4.10.0`), from row 10.
    - `/usr/lib/aarch64-linux-gnu/libnice.so.10.8.0` and `libnice.la` (2025-10-16). No package owns them. The `libnice.so` symlink (owned by `libnice-dev`) points to 10.8.0. Their origin from row 7 is an inference from prefix and dates.

31. **Not visible without root.** Root crontab (`/var/spool/cron/crontabs/root`). Why `nv-ftpm-device-provision` exits with status 1. Real size of `/var/lib/docker` (du shows 4.0K; `docker system df` shows 733.4MB of images). `/root/.cache`. `/var/cache/apt/archives/partial`. PSS of root processes. Whether root or other users' processes use `/opt/gst-1.24` or libnice 10.8.0.

32. **Rows 78 to 80, model folder.** The task rule says: keep `/home/tonyho/model`. Thus these rows are KEEP, and this proposal gives no command for them. The storage analyst proposed SAVE FIRST, then DELETE, because the new node uses TensorRT engines. Possible gain: about 2.2 GiB. If the owner wants this later, the owner must write a new, separate proposal with a backup and a restore step. Rows 79 and 80 are used by `driveragent/startmodel.sh` (old PyTorch YOLOPX path).

33. **Row 91, snap runtimes.** Do row 90 first. snap refuses to remove a base or content snap while another snap uses it. Note 41 gives the commands.
    `snap remove` keeps an automatic snapshot of user data (see `snap saved`). The snapshot uses some disk space for a period (size unknown). If the owner keeps chromium, skip rows 90 and 91. Then remove only the disabled old revisions: `sudo snap remove chromium --revision=3527`, `core22 --revision=2438`, `core24 --revision=1644`, `cups --revision=1237`, `gnome-42-2204 --revision=245`, `gnome-46-2404 --revision=154`, `mesa-2404 --revision=1166` (1.67 GB total). Do not remove the disabled snapd 25205 revision: snapd is held at 2.68.5. The units `snap.chromium.daemon` and `snap.mesa-2404.component-monitor` (both disabled now) go away with these snaps.

34. **apt rule (rows 93 to 99).** Run each `apt-get -s remove ...` line first. It is a simulation and needs no root. Read the list. If it shows `ubuntu-desktop`, `ubuntu-desktop-minimal`, `gnome-shell`, `gdm3`, `nautilus`, or any `nvidia-*`, `cuda-*`, `libnvinfer*`, `tensorrt*`, `libcudnn*`, `gstreamer*` or `python3-*` package, stop. Remove the item that causes it. After the removals, do not remove more packages. Do not delete package configuration files. Nobody ran the simulation tonight. These stay on purpose: `update-manager`, `update-notifier`, `yelp`, `printer-driver-pnm2ppa`, `foomatic-db-compressed-ppds`, `openprinting-ppds`, `gstreamer1.0-packagekit` (hard Depends of `ubuntu-desktop`), `libreoffice-core` and `libreoffice-common` (`python3-uno` needs them), `libsane1` (colord needs it).

35. **Rows 94 to 98, apt commands.** Use the note 34 rule for each line pair.
    ```
    # row 94
    apt-get -s remove libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-draw libreoffice-math
    sudo apt-get remove libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-draw libreoffice-math
    # row 95
    apt-get -s remove aisleriot gnome-mahjongg gnome-mines gnome-sudoku
    sudo apt-get remove aisleriot gnome-mahjongg gnome-mines gnome-sudoku
    # row 96
    apt-get -s remove rhythmbox rhythmbox-plugins rhythmbox-plugin-alternative-toolbar rhythmbox-data totem totem-plugins totem-common shotwell shotwell-common cheese transmission-gtk transmission-common remmina remmina-common remmina-plugin-rdp remmina-plugin-secret remmina-plugin-vnc deja-dup simple-scan gnome-calendar gnome-todo
    sudo apt-get remove rhythmbox rhythmbox-plugins rhythmbox-plugin-alternative-toolbar rhythmbox-data totem totem-plugins totem-common shotwell shotwell-common cheese transmission-gtk transmission-common remmina remmina-common remmina-plugin-rdp remmina-plugin-secret remmina-plugin-vnc deja-dup simple-scan gnome-calendar gnome-todo
    # row 97
    apt-get -s remove printer-driver-brlaser printer-driver-c2esp printer-driver-foo2zjs printer-driver-foo2zjs-common printer-driver-m2300w printer-driver-min12xxw printer-driver-ptouch printer-driver-sag-gdi foomatic-filters ipp-usb sane-utils
    sudo apt-get remove printer-driver-brlaser printer-driver-c2esp printer-driver-foo2zjs printer-driver-foo2zjs-common printer-driver-m2300w printer-driver-min12xxw printer-driver-ptouch printer-driver-sag-gdi foomatic-filters ipp-usb sane-utils
    # row 98
    apt-get -s remove orca brltty speech-dispatcher speech-dispatcher-audio-plugins speech-dispatcher-espeak-ng
    sudo apt-get remove orca brltty speech-dispatcher speech-dispatcher-audio-plugins speech-dispatcher-espeak-ng
    ```
    Undo:
    ```
    # row 94
    sudo apt-get install libreoffice-writer=1:7.3.7-0ubuntu0.22.04.10 libreoffice-calc=1:7.3.7-0ubuntu0.22.04.10 libreoffice-impress=1:7.3.7-0ubuntu0.22.04.10 libreoffice-draw=1:7.3.7-0ubuntu0.22.04.10 libreoffice-math=1:7.3.7-0ubuntu0.22.04.10
    # row 95
    sudo apt-get install aisleriot=1:3.22.22-1 gnome-mahjongg=1:3.38.3-2 gnome-mines=1:40.1-1 gnome-sudoku=1:42.0-1
    # row 96
    sudo apt-get install rhythmbox=3.4.4-5ubuntu1 rhythmbox-plugins=3.4.4-5ubuntu1 rhythmbox-plugin-alternative-toolbar=0.20.2-1 rhythmbox-data=3.4.4-5ubuntu1 totem=42.0-1ubuntu1 totem-plugins=42.0-1ubuntu1 totem-common=42.0-1ubuntu1 shotwell=0.30.14-1ubuntu6 shotwell-common=0.30.14-1ubuntu6 cheese=41.1-1build1 transmission-gtk=3.00-2ubuntu2.1 transmission-common=3.00-2ubuntu2.1 remmina=1.4.25+dfsg-1ubuntu0.1 remmina-common=1.4.25+dfsg-1ubuntu0.1 remmina-plugin-rdp=1.4.25+dfsg-1ubuntu0.1 remmina-plugin-secret=1.4.25+dfsg-1ubuntu0.1 remmina-plugin-vnc=1.4.25+dfsg-1ubuntu0.1 deja-dup=42.9-1ubuntu3 simple-scan=42.0-1 gnome-calendar=41.2-3 gnome-todo=3.28.1-6ubuntu1
    # row 97
    sudo apt-get install printer-driver-brlaser=6-3 printer-driver-c2esp=27-11build1 printer-driver-foo2zjs=20200505dfsg0-2ubuntu2.22.04.1 printer-driver-foo2zjs-common=20200505dfsg0-2ubuntu2.22.04.1 printer-driver-m2300w=0.51-15build1 printer-driver-min12xxw=0.0.9-11build2 printer-driver-ptouch=1.6-2build1 printer-driver-sag-gdi=0.1-8 foomatic-filters=4.0.17-13 ipp-usb=0.9.20-1ubuntu0.22.04.2 sane-utils=1.1.1-5
    # row 98
    sudo apt-get install orca=42.0-1ubuntu2 brltty=6.4-4ubuntu3 speech-dispatcher=0.11.1-1ubuntu3 speech-dispatcher-audio-plugins=0.11.1-1ubuntu3 speech-dispatcher-espeak-ng=0.11.1-1ubuntu3
    ```

36. **Row 100, user pip packages.** No sudo needed. pip asks for confirmation. Their dependencies (google-auth, proto-plus, rsa and others) stay.
    ```
    pip3 freeze --user > ~/pip-user-freeze-$(date +%F).txt
    pip3 uninstall raylib python-can pyubx2 pynmeagps pynmea2 pyrtcm google-cloud-storage google-cloud mapbox-vector-tile
    ```
    Undo:
    ```
    pip3 install --user raylib==5.5.0.3 python-can==4.6.1 pyubx2==1.2.58 pynmeagps==1.0.54 pynmea2==1.19.0 pyrtcm==1.1.9 google-cloud-storage==3.4.1 google-cloud==0.34.0 mapbox-vector-tile==2.2.0
    ```
    After this row, the reference code in `/home/tonyho/driveragent` cannot run its UI, CAN, GNSS, upload and map parts on this AGX. aiortc and av (WebRTC, 114 MB) stay: the new dashboard can need video streaming.

37. **Row 1, new project `/home/tonyho/driveragent-agx`.** This is the only copy. It has 0 commits and no remote. This is expected for a project made tonight. The proposal is KEEP. Save it first. The `.gitignore` already excludes `.venv/`, `ref/` and `docs/audit/`.
    Step 1. Make a local tarball now (no sudo):
    ```
    mkdir -p /home/tonyho/backup/git
    tar -C /home/tonyho -czf /home/tonyho/backup/git/driveragent-agx-$(date +%Y%m%d).tar.gz --exclude=driveragent-agx/.venv --exclude=driveragent-agx/ref driveragent-agx
    ```
    Step 2. The owner adds a git remote and pushes. Replace `REMOTE_URL` (note 1):
    ```
    git -C /home/tonyho/driveragent-agx remote add origin REMOTE_URL
    git -C /home/tonyho/driveragent-agx add -A
    git -C /home/tonyho/driveragent-agx commit -m "Initial commit"
    git -C /home/tonyho/driveragent-agx push -u origin HEAD
    ```
    Undo (the files in the folder do not change):
    ```
    git -C /home/tonyho/driveragent-agx push origin --delete $(git -C /home/tonyho/driveragent-agx branch --show-current)
    git -C /home/tonyho/driveragent-agx remote remove origin
    git -C /home/tonyho/driveragent-agx update-ref -d HEAD
    git -C /home/tonyho/driveragent-agx rm -r -q --cached .
    rm /home/tonyho/backup/git/driveragent-agx-YYYYMMDD.tar.gz
    ```
    To restore the files from the tarball: `tar -C /home/tonyho -xzf /home/tonyho/backup/git/driveragent-agx-YYYYMMDD.tar.gz`.

38. **Other observations (no row).**
    - PID 86637 (`python3 -`, 13 MiB, PPID 1, since 2026-09-25 10:31) is a leftover of an earlier Claude Code background task. The owner can stop it with `kill 86637`.
    - A `claude --resume` process (PID 104172, 369 MB RSS, about 10 days) and the tmux sessions `audit` and `new` are open. Close them by hand when you do not need them.
    - cv2 4.10.0 loads from `/usr/lib/python3/dist-packages`, but dpkg also has `libopencv-dev` 4.8.0 (JetPack) and `libopencv-core4.5d`. Check this version mix. It is not a cleanup item.
    - can0 and can1 are DOWN. No CAN, control or actuation unit exists on this AGX.
    - Directory and file atimes are not usable as a last-use date. The root fs uses relatime, and most files show a read on 2026-09-25 (boot day) or 2026-10-05 20:12 (audit scan).

39. **Analyst conflicts and how this table resolves them.**
    - Unpushed commits of `/home/tonyho/driveragent`: on local branch `claude/quizzical-elgamal-709408`, not on `main` (git analyst, more specific).
    - `/home/tonyho/driveragent-agx` size: 150M now (du, run now). The audit showed 3.0M before `.venv` and `ref/` were added.
    - `/home/tonyho/driveragent-agx`: KEEP (task rule) and SAVE FIRST (no remote, no commits). Row 1 uses "SAVE FIRST, then KEEP".
    - maplibre: the git analyst wrote "not installed in /usr/local/lib". `ls /usr/local/lib` (run now) shows `libmbgl-core.so`. Note 30 uses this.
    - libnice: SAVE FIRST with a tarball (git analyst) over plain DELETE (storage analyst), because `make uninstall` needs the tree.
    - raylib: SAVE FIRST and `sudo rm` (storage analyst) over plain `rm -rf` (git analyst): 353 root-owned files (run now).
    - gstreamer: plain `rm -rf`. The 1 root-owned file is in a tonyho folder (run now).
    - cups: DELETE (storage and packages) over DISABLE (services).
    - chromium: DELETE (packages) over KEEP (storage), because row 35 removes the desktop.
    - snapd: DISABLE (services) over KEEP (packages). See note 27.
    - avahi and OpenVPN: DISABLE (services) over KEEP (packages), only after the owner checks (notes 24, 25).
    - Model folder rows 78 to 80: KEEP (task rule) over SAVE FIRST/DELETE (storage). See note 32.
    - Same item from several analysts merged into one row: Valhalla container, docker engine, jtop, desktop/gdm (with the generic autostart row), packagekit, NoMachine, ModemManager, bluetooth, nvargus, apport and kerneloops (services rows used), apt cache, pip cache, calcam, calcam venv, maplibre, `~/.local` site-packages, tailscaled (in row 29).

40. **Open questions for the owner.**
    1. Does the push of row 2 work (push access not tested)?
    2. What is OpenVPN `uk-ovpn-agent-20` for?
    3. Does anybody still use NoMachine or the local monitor?
    4. Does the RK3588 Valhalla already have the tiles? Does any client still call AGX port 8002? Where on the RK3588 must the map data go?
    5. Does any RK3588 config use `agx02.local`?
    6. Which backup host takes about 535 GiB of recordings? Is the GCS bucket plus one backup copy enough? (MOVE TO RK3588 is possible only with about 270 GiB free there.)
    7. Will the node serve only TensorRT engines, or also the PyTorch system1 path? (system1 needs torch in `~/.local`.)
    8. Are `cam0.yaml` to `cam5.yaml` still valid? Does the inference code need them?
    9. Does anything use `/opt/gst-1.24`?
    10. Where must the git-ignored secrets of `/home/tonyho/driveragent` go (`config.ini`, `control/.env`, `gcs_upload.json`)?

41. **Rows 89 to 92, snaps: commands and exact undo.** The store keeps only the newest revision. Thus `snap install <name>` can give a newer revision. To get the exact revision back, the commands first copy the current `.snap` files. These files are readable only by root, so the copy needs sudo. The copies use about 1.8 GiB on the same disk. Move them to the backup host after a test period. Do row 89 first. Do row 90 before row 91.
    ```
    mkdir -p /home/tonyho/backup/snaps
    # row 89
    sudo cp -p /var/lib/snapd/snaps/cups_1261.snap /var/lib/snapd/snaps/core26_463.snap /home/tonyho/backup/snaps/
    sudo snap remove cups
    sudo snap remove core26
    # row 90
    sudo cp -p /var/lib/snapd/snaps/chromium_3535.snap /home/tonyho/backup/snaps/
    sudo snap remove chromium
    # row 91 (this order)
    sudo cp -p /var/lib/snapd/snaps/gnome-46-2404_169.snap /var/lib/snapd/snaps/mesa-2404_1836.snap /var/lib/snapd/snaps/gtk-common-themes_1535.snap /var/lib/snapd/snaps/core24_2125.snap /var/lib/snapd/snaps/bare_5.snap /home/tonyho/backup/snaps/
    sudo snap remove gnome-46-2404
    sudo snap remove mesa-2404
    sudo snap remove gtk-common-themes
    sudo snap remove core24
    sudo snap remove bare
    # row 92
    sudo cp -p /var/lib/snapd/snaps/gnome-42-2204_264.snap /var/lib/snapd/snaps/core22_2956.snap /home/tonyho/backup/snaps/
    sudo snap remove gnome-42-2204
    sudo snap remove core22
    ```
    Undo with the store revision (it can be newer). Install bases before the snaps that use them:
    ```
    # row 89
    sudo snap install core26 && sudo snap install cups
    # row 90 and row 91
    sudo snap install core24 bare gtk-common-themes mesa-2404 gnome-46-2404 && sudo snap install chromium
    # row 92
    sudo snap install core22 && sudo snap install gnome-42-2204
    ```
    Undo with the exact revision (no automatic refresh; connect the interfaces by hand with `snap connect`):
    ```
    sudo snap install --dangerous /home/tonyho/backup/snaps/core26_463.snap && sudo snap install --dangerous /home/tonyho/backup/snaps/cups_1261.snap
    sudo snap install --dangerous /home/tonyho/backup/snaps/bare_5.snap && sudo snap install --dangerous /home/tonyho/backup/snaps/core24_2125.snap && sudo snap install --dangerous /home/tonyho/backup/snaps/gtk-common-themes_1535.snap && sudo snap install --dangerous /home/tonyho/backup/snaps/mesa-2404_1836.snap && sudo snap install --dangerous /home/tonyho/backup/snaps/gnome-46-2404_169.snap && sudo snap install --dangerous /home/tonyho/backup/snaps/chromium_3535.snap
    sudo snap install --dangerous /home/tonyho/backup/snaps/core22_2956.snap && sudo snap install --dangerous /home/tonyho/backup/snaps/gnome-42-2204_264.snap
    ```
    `snap remove` also keeps an automatic snapshot of user data. Use `snap saved`, then `sudo snap restore <set-id>`, to get the data back.

## Totals

Disk now: 588G used, 281G free on `/` (915G, `df -h /`, run now). All sizes are GiB from `du -h`, unless the row gives another unit. The sum assumes that the owner approves every DELETE and MOVE row, including SAVE FIRST, then DELETE.

Disk freed on the AGX, per group (du, run now):

- Recordings, raw folders and archives (rows 13, 14, 15, 16): 535.1 GiB.
- Map data moved to the RK3588 (rows 53, 54, 55, 56): 7.0 GiB (7506157568 bytes).
- Source and build trees, mapgen, worktrees (rows 3, 5, 6, 7, 9, 10, 11, 57, 58, 59): 8.2 GiB (8783192064 bytes).
- Small files, venv, caches (rows 60 to 66: jetson_out, calcam venv, nomachine.deb, old audit, pip, ccache, apt archives): 1.0 GiB. This is an estimate: apt counts only the 465M archives.
- Docker image (row 12): 0.7 GiB (733 MB).
- Snaps and `~/snap/chromium` (rows 89 to 92): 3.4 GiB. This is an estimate from the `.snap` file sizes. Snap snapshots use some space for a period.
- apt packages (rows 93 to 99): 0.7 GiB. This is an estimate from dpkg Installed-Size. The simulation can show more or fewer packages.
- User pip packages (row 100): 0.02 GiB (estimate).
- **Total: about 556 GiB.**

- Backups that the commands write to `/home/tonyho/backup` stay on the same disk. They use about 3.1 GiB at most (estimate, before compression): snap files 1.8 GiB (note 41), Valhalla image, YOLOPX untracked files, mapgen copy, libnice tarball, new-project tarball, small files. The pip, ccache, apt and nomachine.deb backups go to the backup host.
- Expected free space after all rows: about 834 GiB (estimate: 281 + 556 - 3.1).
- Rows 78 to 80 (KEEP, note 32) are not counted.
- The MOVE rows need about 7.0 GiB free on the RK3588 (unknown now). The recording rows need about 535 GiB free on the backup host (unknown now).
- RAM: the DISABLE rows for the desktop, NoMachine, packagekit, snapd and cups free about 2 GiB RSS of 61 GiB. The Valhalla container frees 128 MiB. RAM is not a problem now (3.8 GB used).
- Installed files listed in note 30 stay. Their removal needs root and is not counted.
