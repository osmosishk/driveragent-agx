# Cleanup proposal - demo (PHASE A)

| Item | Value |
|---|---|
| Date | 2026-10-08, 20:40-22:00 BST (clock of `demo`) |
| Unit | `demo`: Jetson AGX Orin 64 GB, L4T R36.4.7, user `tonyho`. Disk `/`: 915G, 65G used, 804G free. |
| State | PHASE A (2026-10-08). PHASE B part 1 (2026-10-09): items 3, 20, 23, 26, 33, 34, 35, 40, 41a, 41b, 43, 44, 45, 47, 48, 58, 76 moved to `~/_old_agx_20261009/` (list: `MOVES.txt` there). Section 6 is version 2. The rest of this line is the PHASE A state: this document is a proposal. Nothing was deleted, moved, renamed, stopped or disabled. No sudo. No reboot. |
| Method | Six read-only surveys (folders, services, git, dependencies, only copies, recordings) and one critic that checked the five most important claims again. The surveys used no key and called no cloud API. |
| Reference | `docs/CLEANUP_PROPOSAL.md` (AGX02). The table format is the same, with two more columns: "Last change" and "Sudo". |

New role of `demo`: TensorRT inference node (`~/driveragent-agx`, units `agx-dashboard` and `agx-infer`) and the model
registry host (`~/driveragent-models`, `/opt/driveragent/models`). The old DriverAgent stack does not run on `demo`:
no `start.py`, logger, uploader or UI process runs. The only old item that runs is the Docker container
`driveragent-valhalla`.

Disk space is not a problem on `demo` (8 % used). The aim of the cleanup is a node that does not depend on old files,
and the removal of old secrets and only copies from places where they can be lost.

## 1. How to read this document

- **Proposal words:** KEEP; SAVE FIRST, then KEEP; SAVE FIRST, then DELETE; SAVE FIRST, then MOVE TO RK3588; DELETE;
  DISABLE.
- **DELETE in PHASE B is a move.** Each approved DELETE item moves to `~/_old_agx_<date>/` with the same path below it
  (owner rule, PHASE B step 2). The real delete (`rm`) comes only after a second approval (note 2).
- **Command and undo:** the table uses two shell functions. Note 1 defines them. `oldmv <path>` moves an item.
  `oldback <path>` moves it back.
- **SAVE FIRST:** the save commands are in note 3 (one save step for each group). The save folder is on the same disk.
  It is not an off-board copy. The owner selects an off-board place (note 3).
- **Sudo:** "no" = the user `tonyho` can do it. `~/_old_agx_<date>` is on the same filesystem as all items, so a move is a
  rename. A rename of a folder that `tonyho` owns works also when it contains root-owned files. A later `rm -rf` of
  such a folder needs sudo.
- **Unknown:** a fact that could not be proved. Section 7 lists them.

## 2. Inventory and proposal

### 2.1 Old DriverAgent stack, backups and model folders

| # | Item | Type | Size | Last change | What uses it | Proposal | Command (PHASE B) | Undo | Sudo |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `~/driveragent` | git repository | 7.2G (`.git` 77M) | HEAD 2026-09-28 (`159fe72`) | (a) Docker `driveragent-valhalla` binds `location/` (item 56). (b) Each da-models runtime: `DRIVERAGENT_ROOT` default (`message/`, `calibration/`). (c) `config/sim.yaml` `video_root` (`logger/video`). Not the running node. | SAVE FIRST, then KEEP. MOVE only after the independence plan (section 6) and items 56, 57, 59, 60. Before `oldmv /home/tonyho/driveragent`, move back the children that moved before (items 2, 3, 19, 20) with `oldback`. | Note 3, group G1. | Note 3, group G1. | no |
| 2 | `~/driveragent/logs` | directory | 282M (56 `control-ami_*.log`) | 2026-09-28 12:49 | nothing | SAVE FIRST, then DELETE | `oldmv /home/tonyho/driveragent/logs` | `oldback /home/tonyho/driveragent/logs` | no |
| 3 | `~/driveragent/replay/.claude/worktrees/interesting-dhawan-7a9052` | empty directory | 0 | 2026-05-09 | nothing (not a registered worktree) | DELETE | `oldmv /home/tonyho/driveragent/replay/.claude/worktrees/interesting-dhawan-7a9052` | `oldback` (same path) | no |
| 4 | `~/driveragent-bk` | git repository with 0 commits | 5.6G | 2026-04-29 (newest file) | nothing (one comment in `~/driveragent/start.py:77`) | SAVE FIRST, then DELETE | `oldmv /home/tonyho/driveragent-bk` | `oldback /home/tonyho/driveragent-bk` | no (move); yes (final `rm`: 1437 root-owned entries in `location/valhalla_tiles`) |
| 5 | `~/model` (whole tree) | directory | 6.0G | 2026-10-07 | **The running node.** `config/models.yaml:21-22,36-37` and the manifests in `~/agx-models` name `~/model/jetson_bundle` engines and ONNX files. No `last_good.json` exists, so agx-infer loads them at each start. Also: dashboard engine scan (`dashboard.yaml` `scan_dirs`), 6 test files, `da-models publish` sources. | KEEP until the independence plan is done. Then items 6 to 11. | none now | not applicable | no |
| 6 | `~/model/jetson_bundle` | directory | 1.3G | 2026-10-07 06:30 | The running engines `yolopx_v2_fp16.engine` and `dtcp_v1_fp16.engine`, and the rebuild ONNX files. Only copies (section 5). | SAVE FIRST, then DELETE (after section 6) | `oldmv /home/tonyho/model/jetson_bundle` | `oldback /home/tonyho/model/jetson_bundle` | no |
| 7 | `~/model/driverguard` | directory | 273M | 2026-05-26 | Old `run.py` of the old stack. Its 3 engines are byte copies of the `jetson_bundle` engines. | SAVE FIRST, then DELETE (after section 6) | `oldmv /home/tonyho/model/driverguard` | `oldback /home/tonyho/model/driverguard` | no |
| 8 | `~/model/system1` | directory | 577M | 2026-05-25 | `~/agx-models/system1/1/manifest.yaml` (model has no adapter). `system1_deploy.pth` is in GCS. `system1_scorer.pth` and `vocabulary/` are only copies. | SAVE FIRST, then DELETE (after section 6) | `oldmv /home/tonyho/model/system1` | `oldback /home/tonyho/model/system1` | no |
| 9 | `~/model/sparsedrive` | directory | 1.7G | 2026-10-07 | nothing (model disabled). `sparsedrive_deploy.tar.gz` (333 MB) is cut short ("Unexpected EOF"). | SAVE FIRST, then DELETE | `oldmv /home/tonyho/model/sparsedrive` | `oldback /home/tonyho/model/sparsedrive` | no |
| 10 | `~/model/yolopx/venv` | Python venv | 1.4G | 2026-05 | Only `~/driveragent/startmodel.sh` (old stack) | DELETE | `oldmv /home/tonyho/model/yolopx/venv` | `oldback /home/tonyho/model/yolopx/venv` | no |
| 11 | `~/model/yolopx/YOLOPX` | git repository (upstream `jiaoZ7688/YOLOPX`) | 808M | 2026-05-07 | `releases/yolopx-0.1.0.yaml` (publish source). `weights/epoch-195.pth` is in GCS (yolopx 0.1.0, same sha256). 6 local scripts and 109M logs are only copies. | SAVE FIRST, then DELETE (after section 6) | `oldmv /home/tonyho/model/yolopx/YOLOPX` | `oldback /home/tonyho/model/yolopx/YOLOPX` | no |
| 12 | `~/play` | directory | 4.2G | 2025-10-01 | nothing (`~/driveragent/replay/unused/replay.py:38`, unused code) | SAVE FIRST, then DELETE. `play/train` and `play/allvideo` (2.1G) are byte copies of `play/video` files: no save. | `oldmv /home/tonyho/play` | `oldback /home/tonyho/play` | no |
| 13 | `~/development` | directory | 1.7G | 2026-03-25 | nothing. `video/` = 9 recording sessions of 2025-09 (section 4). `people/` = face detection demo (venv 520M). | SAVE FIRST, then DELETE | `oldmv /home/tonyho/development` | `oldback /home/tonyho/development` | no |
| 14 | `~/bev` | directory | 8.1M | 2026-03-11 | nothing. RidgeRun libpanorama evaluation files. | SAVE FIRST, then DELETE | `oldmv /home/tonyho/bev` | `oldback /home/tonyho/bev` | no |
| 15 | `~/setup` | directory | 24K | 2026-05-09 | nothing (no reference). `bootstrap.sh` (different from `~/driveragent/bootstrap.sh`), `bootstrap.env` (secret), `gcs_upload.json` (key copy, mode 664). | SAVE FIRST, then DELETE (save `bootstrap.sh` only; item 39 for the secrets) | `oldmv /home/tonyho/setup` | `oldback /home/tonyho/setup` | no |
| 16 | `~/Documents/remote_nav_status_api` | git repository (GitLab) | 50M | 2025-11-27 | nothing. Not an AGX item. | SAVE FIRST, then DELETE | `oldmv /home/tonyho/Documents/remote_nav_status_api` | `oldback` (same path) | no (move); yes (final `rm`: root-owned `.venv`) |
| 17 | `~/Documents/race_sim_connect_api` | git repository (GitLab) | 7.3M | 2025-09-27 | nothing. Not an AGX item. | SAVE FIRST, then DELETE | `oldmv /home/tonyho/Documents/race_sim_connect_api` | `oldback` (same path) | no (move); yes (final `rm`: root-owned `.venv`) |

### 2.2 Recordings (section 4 has the evidence)

| # | Item | Type | Size | Last change | What uses it | Proposal | Command (PHASE B) | Undo | Sudo |
|---|---|---|---|---|---|---|---|---|---|
| 18 | `~/driveragent/logger/video/8001-20260926_{122805,122905,123016,123045}` (4 session folders) | directory | 500 MiB (524,588,425 B) | 2026-09-26 | Simulator input of the node (command line, `docs/DEPLOY_DEMO_REPORT.md`). Source of the model-check test frame (already copied into the store). | KEEP. The independence plan copies them to `~/agx-data/recordings/` (section 6, step 5). | none | not applicable | no |
| 19 | `~/driveragent/logger/video/8001-20260926_*.tar.bz2` (4 archives) | file | 502 MiB (526,605,653 B) | 2026-09-28 | nothing. `uploaded.db` has a row for each. GCS: unknown. | KEEP until the owner checks GCS (note 6). Then DELETE. | after the check: `oldmv` each archive, one call for each path | `oldback` each archive, one call for each path | no |
| 20 | `~/driveragent/logger/video/8001-20260818_{104346,104904}.tar.bz2` | file | 14 B each | 2026-08-18 | nothing. Empty bzip2 streams (0 bytes of data). No folder, no db row. | DELETE | `oldmv /home/tonyho/driveragent/logger/video/8001-20260818_104346.tar.bz2` and the same for `_104904` | `oldback` (same paths) | no |
| 21 | `~/driveragent/logger/video/uploaded.db` | SQLite file | 12 KB, 37 rows | 2026-09-28 09:48 | Only local record of the uploads | SAVE FIRST, then KEEP | Note 3, group R. | Note 3, group R. | no |
| 22 | Old logger group (`~/driveragent/start.py` starts `logger.uploader` and `logger.deleter`) | process (not running) | 0 | not applicable | nothing starts it now (no unit, cron or autostart entry) | DISABLE (no command is necessary). **Do not start `start.py` on demo:** `deleter.py` uses car id 8001 (the car id of demo) and deletes the oldest 20 % of the sessions above 1 GiB. The folder is 22.7 MB below that limit. It would delete item 18 first. | none | not applicable | no |

### 2.3 Downloads, build trees and installed results

| # | Item | Type | Size | Last change | What uses it | Proposal | Command (PHASE B) | Undo | Sudo |
|---|---|---|---|---|---|---|---|---|---|
| 23 | `~/Downloads/maplibre-native` (+49 submodules) | git repository (upstream, clean) | 4.3G (`.git` 3.2G) | 2026-05-09 | Only `~/driveragent/location/build_mapgen.sh` (rebuild of `mapgen`, old map UI) | DELETE | `oldmv /home/tonyho/Downloads/maplibre-native` | `oldback /home/tonyho/Downloads/maplibre-native` | no |
| 24 | `~/Downloads/raylib` | git repository (upstream, clean) | 562M | 2025-09-27 | Its build installed `/usr/local/lib/libraylib.so.5.5.0` (item 29). The old UI uses the pip `raylib` in `~/.local`. | SAVE FIRST (install manifest), then DELETE | `oldmv /home/tonyho/Downloads/raylib` | `oldback /home/tonyho/Downloads/raylib` | no (move); yes (final `rm`: 331 root-owned files) |
| 25 | `~/opencv` (not git) | source and build tree | 507M | 2025-09-27 | Its build installed OpenCV 4.10.0 in `/usr` (item 29). **The running agx-infer maps 61 of these installed libraries (2026-10-08; the number can change).** The tree is not read at run time. | SAVE FIRST (install manifest, CMake cache), then DELETE | `oldmv /home/tonyho/opencv` | `oldback /home/tonyho/opencv` | no (move); yes (final `rm`: 963 root-owned files) |
| 26 | `~/opencv_contrib` | source tree | 105M | 2024-05-30 | Only the `~/opencv` build | DELETE | `oldmv /home/tonyho/opencv_contrib` | `oldback /home/tonyho/opencv_contrib` | no |
| 27 | `~/Downloads/cmake-3.31.9` and `cmake-3.31.9.tar.gz` | source and build tree, archive | 520M + 11M | 2025-09-27 | Its build installed `/usr/local/bin/cmake` 3.31.9 (item 29) | SAVE FIRST (install manifest), then DELETE | `oldmv /home/tonyho/Downloads/cmake-3.31.9` and `oldmv /home/tonyho/Downloads/cmake-3.31.9.tar.gz` | `oldback` (same paths) | no (move); yes (final `rm`: 119 root-owned files) |
| 28 | `~/Downloads/OpenCV-4-10-0.sh` | file | 6.9K | 2025-09-27 | The build recipe of item 25 | SAVE FIRST, then DELETE | `oldmv /home/tonyho/Downloads/OpenCV-4-10-0.sh` | `oldback` (same path) | no |
| 29 | Installed results: OpenCV 4.10.0 in `/usr/lib/aarch64-linux-gnu` and `/usr/lib/python3/dist-packages/cv2`; `/usr/local/lib/libraylib*`; `/usr/local/bin/cmake` 3.31.9 | installed files (not owned by dpkg) | not measured | 2025-09-27 | OpenCV: agx-infer (running). raylib, cmake: nothing that runs. | KEEP | none | not applicable | yes (any removal) |
| 30 | `~/Downloads/jetson-jtop-patch` | git repository | 212K | 2025-09-20 | jtop fix (only a file mode change) | SAVE FIRST, then KEEP (as AGX02 row 8) | Note 3, group G2. | Note 3, group G2. | no |
| 31 | `~/Downloads/calcam` (`calcam.py`, `cam0.yaml` to `cam5.yaml`, `venv` 180M) | directory | 187M | 2026-01-20 | nothing. The 6 yaml files differ from the GitHub calibration files: only copies. | SAVE FIRST, then MOVE TO RK3588 (yaml and script; the venv is DELETE) | `oldmv /home/tonyho/Downloads/calcam` (after the copy to the RK3588) | `oldback /home/tonyho/Downloads/calcam` | no |
| 32 | `~/Downloads/SG8A` | directory | 43M | 2025-11-15 | GMSL2 camera driver kit (JetPack 6.2). Not loaded now. | KEEP (needed for a re-flash with GMSL cameras) | none | not applicable | no |
| 33 | `~/Downloads/SG8A.zip` | file | 44M | 2025-10-10 | nothing. Same 19 files as item 32. | DELETE | `oldmv /home/tonyho/Downloads/SG8A.zip` | `oldback` (same path) | no |
| 34 | `~/Downloads/nomachine.deb` (9.1.24-6; installed is 9.9.6-2) | file | 75M | 2025-07-24 | nothing | DELETE | `oldmv /home/tonyho/Downloads/nomachine.deb` | `oldback` (same path) | no |
| 35 | `~/Downloads/bg.jpg` | file | 27K | 2025-09-27 | nothing. Byte copy of `~/driveragent/asset/bg.jpg`. | DELETE | `oldmv /home/tonyho/Downloads/bg.jpg` | `oldback` (same path) | no |

### 2.4 Secrets, caches and small files

| # | Item | Type | Size | Last change | What uses it | Proposal | Command (PHASE B) | Undo | Sudo |
|---|---|---|---|---|---|---|---|---|---|
| 36 | `~/.gitconfig` | file, mode 664 | 86 B | 2025-09-26 | One global `url.<...>.insteadOf` rule with a GitLab access token. Git adds the token to each `https://gitlab.com/` URL (items 16, 17). No identity. | Owner item (note 7): revoke the token, then DELETE the rule | Note 7 | Note 7 | no |
| 37 | VPN profiles `~/uk-ovpn-agent-15.conf` and `~/Downloads/uk-ovpn-agent-18.conf` (two different files, mode 664) | file | 5K each | 2025-10-22, 2025-09-20 | nothing. No `openvpn@` instance, `/etc/openvpn/client` is empty. | DELETE (secret: the owner keeps the profiles in a safe place first) | `oldmv /home/tonyho/uk-ovpn-agent-15.conf` and `oldmv /home/tonyho/Downloads/uk-ovpn-agent-18.conf` | `oldback` (same paths) | no |
| 38 | `gcs_upload.json` (write key of `gcs-upload@`, 5 copies, the same sha256): `~/driveragent` (600), `~/setup`, `~/driveragent-bk`, `~/driveragent-bk/logger`, `~/driveragent-bk/location/old` (all 664) | file | 2.3K each | 2025-10-10 to 2026-05-09 | Only the old uploader (`~/driveragent`, not running) | KEEP the copy in `~/driveragent` (600). DELETE the 4 other copies (they move with items 4 and 15). Owner: rotate the key (note 7). | with items 4 and 15 | with items 4 and 15 | no |
| 39 | Other secret files (not read): `~/setup/bootstrap.env`, `~/play/.env`, `~/driveragent/control/.env`, `~/driveragent-bk/control/.env` (different, only copy), `~/Documents/*/.env`, `~/driveragent/config.ini` | file, mode 664 (most) | under 1K each | 2025-09 to 2026-05 | Old stack and old projects only | They move with their folders (items 4, 12, 15, 16, 17). The save commands exclude them. The owner decides if a copy is necessary (note 7). | with the folder | with the folder | no |
| 40 | `~/.insightface` | directory | 631M | 2026-03-16 | Only `~/development/people` (item 13). Can be downloaded again. | DELETE | `oldmv /home/tonyho/.insightface` | `oldback /home/tonyho/.insightface` | no |
| 41a | `~/.cache/pip` | cache | 870M | 2026-10-08 | pip (cache only) | DELETE | `oldmv /home/tonyho/.cache/pip` | `oldback /home/tonyho/.cache/pip` | no |
| 41b | `~/.cache/ccache` | cache | 91M | 2026-05-09 | the maplibre build only | DELETE | `oldmv /home/tonyho/.cache/ccache` | `oldback /home/tonyho/.cache/ccache` | no |
| 42 | `~/.cache` other parts: `torch` 84M, `nvidia` 19M (CUDA), `gstreamer-1.0` (used by agx-infer), `da-models-staging`, `tracker3` and others | cache | about 150M | 2026-10-08 | agx-infer (GStreamer, CUDA), da-models | KEEP | none | not applicable | no |
| 43 | `~/.vscode-server` | directory | 3.4G | 2026-05-21 | VS Code remote (no process now). 5 server builds (1.5G), extension cache `data/CachedExtensionVSIXs` (454M). | DELETE the 4 older server builds and the VSIX cache. KEEP the newest build `0958016b` and the extensions. | Note 4 | Note 4 | no |
| 44 | `~/.codex` (48M), `~/.copilot` (12K), `~/.dotnet` (268K) | directory | 48M | 2026-05-14 | Other AI tools and the VS Code .NET helper. No process. | DELETE | `oldmv /home/tonyho/.codex` (and the same for `.copilot`, `.dotnet`) | `oldback` (same paths) | no |
| 45 | `~/.local/share/Trash` | directory | 5.6M | 2026-05-12 | nothing | DELETE | `oldmv /home/tonyho/.local/share/Trash` | `oldback /home/tonyho/.local/share/Trash` | no |
| 46 | `~/brake.log` | file (candump text) | 828K | 2026-01-07 | nothing | SAVE FIRST, then DELETE | `oldmv /home/tonyho/brake.log` | `oldback /home/tonyho/brake.log` | no |
| 47 | `~/minicom.log` | file | 35 B | 2025-11-15 | nothing | DELETE | `oldmv /home/tonyho/minicom.log` | `oldback /home/tonyho/minicom.log` | no |
| 48 | `~/snapd_24724.snap`, `~/snapd_24724.assert` | file | 44M | 2025-09-16 | nothing. The same snapd revision 24724 is installed. | DELETE | `oldmv /home/tonyho/snapd_24724.snap` and `oldmv /home/tonyho/snapd_24724.assert` | `oldback` (same paths) | no |
| 49 | `~/.local` (`lib/python3.10/site-packages` 1.3G, `bin`, `share/claude`) | directory | 2.4G | 2026-10-08 | **The running node:** torch, numpy, pyzmq, pycapnp, PyYAML, psutil, pycuda, httpx and others come from here | KEEP | none | not applicable | no |
| 50 | `~/snap/firefox` | directory | 1.4G | 2026-10-08 | Firefox snap | KEEP | none | not applicable | no |
| 51 | `~/.nx` | directory | 15M | 2026-10-07 | NoMachine (`nxnode.bin` has files open) | KEEP while item 61 runs | none | not applicable | no |
| 52 | `~/.dbus` (root:tonyho 700), `~/.gnupg` (root:root 700) | directory | 4K each | 2025-09/11 | Made by an old sudo GUI run | KEEP (a change needs sudo, no gain) | none | not applicable | yes |
| 53 | Protected by rule R3: `~/driveragent-agx`, `~/agx-models`, `~/driveragent-models`, `/opt/driveragent/models`, `~/.config/driveragent-models` (publisher key) | directory | 60M, 384K, 3.2M, 1.6G, 6K | 2026-10-08 | The node and the registry | KEEP | none | not applicable | no |
| 54 | `/opt/nvidia` (1.8G: nsight-compute, deepstream 7.1, vpi3), `/opt/ota_package` (343M), `/opt/containerd` | directory (dpkg) | 2.1G | 2025-11-14 | JetPack | KEEP | none | not applicable | yes (any removal) |
| 55 | Other home items: `~/.config` (288K), `~/.ssh`, `~/.nv` (CUDA cache), `~/.pip` (`pip.conf`, no credential; pip uses it), `~/.qt`, `~/.claude.json`, `~/Documents/NoMachine` (empty), `~/.cache/torch`, `~/Desktop`, `~/Pictures`, `~/Music`, `~/Public`, `~/Templates`, `~/Videos` (empty), shell files, `~/.claude` (this agent) | directory, file | small | various | desktop and tools | KEEP | none | not applicable | no |

### 2.5 Docker and map data

| # | Item | Type | Size | Last change | What uses it | Proposal | Command (PHASE B) | Undo | Sudo |
|---|---|---|---|---|---|---|---|---|---|
| 56 | Container `driveragent-valhalla` (image `2f4b9b17cda4`, restart `unless-stopped`, port 8002, bind `~/driveragent/location` -> `/custom_files`) | container | 42 MiB RAM | created 2026-05-10. Last request 2026-09-28 11:25 UTC. No request since the boot of 2026-10-05. | Old map UI (`ui/newwidgets/data_bus.py:519`), old `start.py`. **The new node does not use port 8002.** The dashboard only reads its state. | SAVE FIRST, then MOVE TO RK3588 (as AGX02 row 52) | Note 5 | Note 5 | no (tonyho is in group `docker`) |
| 57 | Image `ghcr.io/valhalla/valhalla:latest` `2f4b9b17cda4` | image | 693MB | 2026-05-07 | item 56 only | SAVE FIRST, then DELETE (after item 56) | Note 5 | Note 5 | no |
| 58 | Dangling image `ghcr.io/valhalla/valhalla:<none>` `ca66a15903a4` | image | 700MB | 2026-04-01 | nothing | DELETE | `docker rmi ca66a15903a4` (save first if wanted: note 5) | `docker load` from the save, or pull digest `sha256:0d1e590f...` (availability unknown) | no |
| 59 | Map data in `~/driveragent/location`: `valhalla_tiles` 2.6G (root-owned), `united-kingdom-latest.osm.pbf` 2.1G, `gb.mbtiles` 1.2G, `mapgen` 13M | directory, file | 5.8G | 2026-05-22 | item 56 (bind mount) | SAVE FIRST, then MOVE TO RK3588 (with item 56; the tiles can be rebuilt from the pbf) | Note 5 | Note 5 | no (copy and move of `location/`); yes (move of `valhalla_tiles` alone) |
| 60 | `~/driveragent-bk/location/england_greater-london.mbtiles` | file | 82M | 2025-10-10 | nothing. Only copy on demo. AGX02 has a file with the same byte size (hash not compared). | SAVE FIRST, then MOVE TO RK3588 (with item 59) | moves with item 4 | moves with item 4 | no |

### 2.6 systemd system units, timers, user units, cron and autostart

All system unit commands need sudo. In PHASE B the owner runs them, or gives the agent sudo. The node does not need any
unit in this part.

| # | Item | Type | Memory | Last change | What uses it | Proposal | Command (PHASE B) | Undo | Sudo |
|---|---|---|---|---|---|---|---|---|---|
| 61 | `nxserver.service` (NoMachine 9.9.6-2) | service | 420.7 MiB | log 2026-09-28 14:32 | Remote desktop. Last client: unknown. | DISABLE (owner decides) | `sudo systemctl disable --now nxserver.service` | `sudo systemctl enable --now nxserver.service` | yes |
| 62 | `packagekit.service` (static) | service | 504.6 MiB | running | GNOME Software, update-manager | DISABLE | `sudo systemctl mask --now packagekit.service` | `sudo systemctl unmask packagekit.service` | yes |
| 63 | `fwupd.service` (static) and `fwupd-refresh.timer` | service | 176.2 MiB | running | Firmware updates | DISABLE | `sudo systemctl mask --now fwupd.service fwupd-refresh.timer` | `sudo systemctl unmask fwupd.service fwupd-refresh.timer && sudo systemctl start fwupd-refresh.timer` | yes |
| 64 | `gdm.service` and the GNOME session (auto-login `tonyho`) | service | desktop PSS about 1640 MiB | running | Local HDMI and NoMachine desktop | DISABLE (owner decides). Needs a reboot: the transient units stop, so start the node again (section 11 of `DEPLOY_DEMO_REPORT.md`). | `sudo systemctl set-default multi-user.target` | `sudo systemctl set-default graphical.target` | yes |
| 65 | `nvargus-daemon.service` | service | 15.4 MiB | running | CSI cameras. No `/dev/video*`. The node uses UDP cameras. | DISABLE | `sudo systemctl disable --now nvargus-daemon.service` | `sudo systemctl enable --now nvargus-daemon.service` | yes |
| 66 | `snap.cups.cupsd` and `snap.cups.cups-browsed` | service | 74.8 MiB | running | Printing | DISABLE | `sudo snap stop --disable cups` (snapd keeps the state of snap services) | `sudo snap start --enable cups` | yes |
| 67 | `bluetooth`, `ModemManager` (no modem), `kerneloops`, `rpcbind` (+ socket) | service | about 13 MiB | running | nothing | DISABLE | `sudo systemctl disable --now bluetooth.service ModemManager.service kerneloops.service rpcbind.service rpcbind.socket` | `sudo systemctl enable --now bluetooth.service ModemManager.service kerneloops.service rpcbind.socket rpcbind.service` | yes |
| 68 | `avahi-daemon` (+ socket) | service | 1.6 MiB | running | mDNS `demo.local`. Use by the RK3588: unknown. | DISABLE after the owner checks that no board uses `demo.local` | `sudo systemctl disable --now avahi-daemon.service avahi-daemon.socket` | `sudo systemctl enable --now avahi-daemon.socket avahi-daemon.service` | yes |
| 69 | `apport-autoreport` (`.service` failed: whoopsie is not installed; `.path`, `.timer`) | service | 0 | failed 2026-10-08 18:21 | nothing | DISABLE | `sudo systemctl disable --now apport-autoreport.path apport-autoreport.timer && sudo systemctl reset-failed apport-autoreport.service` | `sudo systemctl enable --now apport-autoreport.path apport-autoreport.timer` | yes |
| 70 | Update timers: `apt-daily`, `apt-daily-upgrade`, `update-notifier-download`, `update-notifier-motd`, `motd-news`, `ua-timer`, `snapd.snap-repair` | timer | 0 | stock | Automatic updates. Risk: security updates do not download automatically. | DISABLE (as AGX02 note 26) | `sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer update-notifier-download.timer update-notifier-motd.timer motd-news.timer ua-timer.timer snapd.snap-repair.timer` | the same command with `enable --now` | yes |
| 71 | `jtop.service` (jetson-stats 4.3.2) | service | 25.9 MiB | running | Monitor tool. The dashboard does not need it (it reads `/proc` and `/sys`). | KEEP (as AGX02 row 19) | none | not applicable | - |
| 72 | `docker.service`, `containerd.service`, `docker.socket` | service | 229 MiB | running | item 56 only | KEEP (after item 56, the owner can disable them) | none | not applicable | yes (to disable) |
| 73 | `snapd` | service | 77.1 MiB | running | Firefox and cups snaps | KEEP | none | not applicable | - |
| 74 | `openvpn.service` (`/bin/true`, no instance) | service | 0 | exited | nothing | KEEP (no cost) | none | not applicable | - |
| 75 | Stock units: NVIDIA L4T units (`nv*`, `l4t-*`, `nvzramconfig`, `nvfancontrol`, `nvphs`, `nvs-service`, `nvidia-pva-allowd`, `nv-tee-supplicant`), core services (`ssh`, `tailscaled`, `NetworkManager`, `chrony`, `systemd-resolved`, `cron`, `anacron`, `rsyslog`, `polkit`, serial gettys), housekeeping timers (`anacron`, `dpkg-db-backup`, `man-db`, `e2scrub_all`, `fstrim`, `systemd-tmpfiles-clean`), installed but inactive units (`isc-dhcp-server`, `nftables`, `systemd-networkd`, and others) | service, timer | small | stock | JetPack and remote access | KEEP | none | not applicable | - |
| 76 | User unit `tracker-miner-fs-3` (indexes the home folder) | user service | PSS 19 MiB | running | nothing | DISABLE | `systemctl --user mask tracker-miner-fs-3.service tracker-extract-3.service && systemctl --user stop tracker-miner-fs-3.service` | `systemctl --user unmask tracker-miner-fs-3.service tracker-extract-3.service` | no |
| 77 | User units `agx-dashboard`, `agx-infer` (transient) | user service | 1.06 GiB | 2026-10-08 19:43 | The node | KEEP (rule R3) | none | not applicable | - |
| 78 | Autostart: `gnome-software` (PSS 745 MiB), `update-notifier` and `update-manager` (PSS 217 MiB), `nvpmodel_indicator` (23 processes, PSS 70 MiB) | autostart entries (stock, `/etc/xdg/autostart`) | about 1 GiB | running | Desktop | DISABLE (not necessary if item 64 is approved) | Note 4 | Note 4 | no |
| 79 | cron: `tonyho` has no crontab; `/etc/cron.*` has stock files only; root crontab: not visible without root | cron | 0 | stock | nothing | KEEP | none | not applicable | - |

## 3. Git repositories

Read with `git --no-optional-locks` (no index change). The GitHub state comes from `git ls-remote` (no fetch).

| Repository | Remote | Commits not pushed | Files not committed | Worktrees | Stashes | Notes |
|---|---|---|---|---|---|---|
| `~/driveragent` | `git@github.com:osmosishk/DriverAgent.git` | 0 (`main` 159fe72 = GitHub) | 0. Ignored local files: `config.ini`, `assets.yaml`, `paths/route_active.json`, `ko/`, map data, `logs/`, `logger/video/`, binaries, secrets | main only. One empty folder (item 3). | **1, only local:** `stash@{0}` 2026-05-10 "sync-auto-stash", 9 paths. 5 of them are in no commit (`config.ini`, `location/setup_valhalla.sh`, `paths/route_active.json`, `start.py`, `ui/ui.py`). Treat it as secret (`config.ini`). | Last fetch 2026-09-28 |
| `~/driveragent-bk` | same | 0 (no local branch: `main` is unborn) | Not a normal status. 314 files are in no GitHub blob. After the removal of byte copies of `~/driveragent` and `~/Downloads/SG8A` files, 121 files are left: 111 code and data files (5.6 MB, for example `control/control-ami.py`, `calibration/camera_0..5_calibration.json`, `path/path_20260110_*.json`), 7 config or secret files, `england_greater-london.mbtiles` (85 MB), `gb.mbtiles` (the same bytes as the `~/driveragent` copy by `cmp`) and the old public `osm.pbf`. Also 185 logs (48.9 MB). | main only | 0 | 1437 root-owned entries in `location/valhalla_tiles` |
| `~/driveragent-agx` | `https://github.com/osmosishk/driveragent-agx.git` | 0 (`deploy/demo` 7ab77fb and `main` 970d5ac are on GitHub) | 0 | main only | 0 | Protected |
| `~/driveragent-models` | `git@github.com:osmosishk/driveragent-models.git` | 0 (`main` 16132a1) | 0 | main only | 0 | Protected |
| `~/model/yolopx/YOLOPX` | `https://github.com/jiaoZ7688/YOLOPX.git` (third party) | 0 | 2 modified (`tools/demo.py` is unique; `requirements.txt` is in driveragent-models), 65 untracked: unique `tools/demo1.py`, `democ.py`, `demotext2.py`, `run.py`; `logs/` 109M; `weights/epoch-195.pth` (in GCS) | main only | 0 | |
| `~/Downloads/maplibre-native` (+49 submodules) | upstream | 0 | 0 (submodules clean) | main only | 0 | |
| `~/Downloads/raylib` | upstream | 0 | 0 | main only | 0 | |
| `~/Downloads/jetson-jtop-patch` | upstream | 0 | 1 (file mode only) | main only | 0 | |
| `~/Documents/remote_nav_status_api` | GitLab `osmosis_ai/remote_nav_status_api` (the token comes from `~/.gitconfig`) | 0 against the local remote-tracking refs (last fetch 2025-11-27). GitLab now: unknown (not checked: it needs the token) | `D tests/zmq_test.py`, `?? module/zmq_test.py` (unique); ignored `out/` 12.9M, `.env` | main only | 0 | |
| `~/Documents/race_sim_connect_api` | GitLab `osmosis_ai/race_sim_connect_api` | 0 (last fetch 2025-09-27). GitLab now: unknown | `M main.py` (+28/-6, unique); ignored `out/` 2.9M, `.env` | main only | 0 | |
| `~/.codex/.tmp/plugins` | `https://github.com/openai/plugins.git` | 0 | 0 | main only | 0 | Tool cache (item 44) |

`~/opencv` and `~/opencv_contrib` are not git repositories. No git bundle exists. Patches that are in no repository:
`~/model/jetson_bundle/runner_patches/000{1,2,3}-*.diff` (section 5).

## 4. Recordings

Upload proof: `uploaded.db` (read-only). The old uploader writes a row only after the upload call returns with no
error, or after GCS reports that the object exists. The row has no size or checksum. GCS was not checked: no read
credential may be used (rule R3 for the publisher key; the uploader key is a write key of a different service). Target
of the old uploader: `gs://carvideo_osmosisai/8001/<session>.tar.bz2`.

| Session | Folder (size, files) | Archive | `uploaded.db` | GCS | Used by the node | Proposal |
|---|---|---|---|---|---|---|
| `8001-20260926_122805` | 226,678,978 B, 6 mp4 + 2 log | 227,568,060 B, `bzip2 -t` OK | row 2026-09-28T08:45:52Z | unknown | simulator input; test frame source | folder KEEP (item 18); archive KEEP until note 6 |
| `8001-20260926_122905` | 153,469,534 B, 8 files | 154,064,581 B, OK | row 08:47:10Z | unknown | simulator input | same |
| `8001-20260926_123016` | 93,461,841 B, 8 files | 93,816,279 B, OK | row 08:48:06Z | unknown | simulator input | same |
| `8001-20260926_123045` | 50,978,072 B, 8 files | 51,156,733 B, OK | row 08:48:36Z | unknown | simulator input | same |
| `8001-20260818_104346`, `_104904` | no folder | 14 B each, empty bzip2 | no row | unknown (never uploaded by this code) | no | DELETE (item 20) |
| `~/play/video`: 27 sessions (2025-05-02, 2025-06-17, 2025-06-29), 51 mp4 (50 different contents) | 2,233,825,832 B | none | no row (the first row is 2026-01-17; the deleter can also remove rows) | unknown | no | SAVE FIRST, then DELETE (item 12) |
| `~/play/train` (23 mp4), `~/play/allvideo` (27 mp4) | 2.1G | none | not applicable | not applicable | no | byte copies of `play/video` files: DELETE with item 12, no save |
| `~/development/video`: 9 sessions 2025-09-20 to 2025-09-26 (6 with 6 cameras, 1 with 3 cameras, 2 with 0-byte files) and `26_sep_data.csv` | 1,180,323,835 B | 8 bz2 logs | no row | unknown | no | SAVE FIRST, then DELETE (item 13) |

The other 33 rows of `uploaded.db` (2026-01-17 to 2026-04-11) have no local file. Who removed those files is unknown.
No other recording is on `demo` (`find` for video, bag and archive files; `~/Videos` and `/mnt` are empty; `/data` is
root-only: unknown).

## 5. Dependencies and only copies

### 5.1 Paths outside `~/driveragent-agx` that are read

| Path | Read by | When | Evidence | What breaks if it moves |
|---|---|---|---|---|
| `~/model/jetson_bundle/engines/yolopx_v2_fp16.engine`, `dtcp_v1_fp16.engine` | agx-infer, dashboard controller (manifests), model check, dashboard engine scan | **each start of agx-infer** (no `last_good.json`) | `config/models.yaml:21,36`; `~/agx-models/driverguard_*/1/manifest.yaml`; live status | The running process continues (no file is open). The next start: both models FAILED. |
| `~/model/jetson_bundle/onnx/yolopx_v2.onnx`, `dtcp_v1.onnx` | agx-infer (rebuild when an engine does not load), manifests | only at an engine load failure | `config/models.yaml:22,37`; `infer/models/manager.py:476` | No rebuild |
| `~/model/system1/system1_deploy.pth` | `~/agx-models/system1/1` manifest | catalog check only (NO ADAPTER) | manifest | The catalog shows the check failure |
| `~/model` (whole tree) | dashboard engine scan every 1800 s | runtime | `config/dashboard.yaml:60-61` (on main: machine data; template `scan_dirs: []`; `tools/inspect_engines.py:23` `DEFAULT_SCAN = []`) | Handled: the card shows a missing folder |
| `~/model/...` engines, ONNX, samples | 6 test files; `tests/test_t1_models_doc.py` (on main: `AGX_OLD_MODELS`, default `/home/tonyho/model`) | tests | `tests/test_manager.py:25-26` and 5 others | 6 files: PASS changes to SKIPPED. `test_t1_models_doc` fails now and continues to fail. |
| `~/model/...` ONNX, weights, samples, `MANIFEST.json` | `da-models publish` | publish only | `~/driveragent-models/releases/*.yaml` | A new publish of those releases fails. `verify` and `pull` read only `/opt/driveragent/models`. |
| `~/driveragent/logger/video` | `tools/rk_sim` | simulator tests | `config/sim.yaml:49` | The simulator file source fails (use absolute `--sessions` paths or `--source test-pattern`) |
| `~/driveragent/logger/video/8003-*` | agx-infer in `mode: file`; 2 tests | only in mode file | `config/sources.yaml:86-134` | Nothing: these sessions are not on demo |
| `~/driveragent/message/{__init__.py,capnp_pubsub.py,message.capnp}` | each da-models runtime (`DRIVERAGENT_ROOT` default `~/driveragent`), `~/driveragent-models/tools/live_rate.py` | when a da-models runtime runs (none runs now) | `~/driveragent-models/runtime/driverguard/run.py:22,24`, `driverguard/runner/ego_state.py:13-17`, `driverguard/runner/route_guidance_provider.py:19-23`, `system1/system1/run.py:21,23`, `system1/system1/runner/runner.py:22`, `system1/system1/runner/ego_state.py:19-23` | Import error, unless `DRIVERAGENT_ROOT` points to a copy |
| `~/driveragent/calibration` | system1 runtime, `~/driveragent-models/tools/bench_system1.py` | da-models runtime | `~/driveragent-models/runtime/system1/system1/runner/calibration.py:31` | Identity calibration or failure. Note: only `camera_0/1_calibration.json` exist here; `~/driveragent-bk/calibration` has camera 0 to 5 (different, only copies). |
| `~/driveragent/location` | Docker `driveragent-valhalla` | at each container start (boot) | `docker inspect` bind | The map service fails |
| `~/.local/lib/python3.10/site-packages` | agx-infer, agx-dashboard, da-models | runtime | `/proc/<pid>/maps` | **The node does not start** (KEEP, item 49) |
| OpenCV 4.10.0 in `/usr/lib/aarch64-linux-gnu`, `/usr/lib/python3/dist-packages/cv2` | agx-infer | runtime | `/proc/<pid>/maps` (61 libraries) | KEEP (item 29) |
| `/usr/src/tensorrt/bin/trtexec` | agx-infer and controller rebuild, `da-models build` | rebuild | `manager.py:45`, `controller/builder.py:19` | KEEP (JetPack) |

The code of `~/driveragent-agx` has its own copies of the old pre- and post-processing (`infer/models/legacy`). It
imports nothing from `~/model` or `~/driveragent`. The constants `READ_ONLY_ROOTS` (`manager.py:46`) and
`FORBIDDEN_PREFIX` (`controller/builder.py:22`) only refuse writes there.

### 5.2 Files that exist only on demo

Proof: GCS = the sha256 is a published file (a files entry) in `~/driveragent-models/models.yaml` or `releases/*.yaml`, or a member of a published archive (no GCS call). An `upstream.weights` sha256 is only a record, not a published file. GitHub = the
blob is in a commit on GitHub (`ls-remote`). AGX02 = the sha256 prefix is in an AGX02 document (`docs/MODELS.md`,
2026-10-05/07); "path+size" = only the same path and size in `docs/AGX_AUDIT.md` or `docs/CLEANUP_PROPOSAL.md` (not a
proof). AGX02 was not reachable for a live check.

| Path | Size | sha256[:16] | GitHub | GCS | AGX02 | Group |
|---|---|---|---|---|---|---|
| `~/model/jetson_bundle/onnx/dtcp_v1.onnx` (rebuild source of the running DTCP engine) | 97,041,705 | `ece3c62634de446b` | no | no | no (the AGX02 `dtcp_v1.onnx` is the demo `.broken` file) | **P1** |
| `~/model/jetson_bundle/weights/dtcp_nusc_route_v1.pt` | 103,239,980 | `e342c0b5d9d5b07b` | no | no (sha only as an upstream record) | path+size | **P1** |
| `~/model/jetson_bundle/weights/yolopx_v2_epoch30.pth` | 396,733,326 | `98736417397d5a0a` | no | no (sha only as an upstream record) | path+size | **P1** |
| `~/model/system1/system1_scorer.pth` | 129,864,601 | `76f36f9332dde1c0` | no | no | path+size | **P1** |
| `~/model/system1/vocabulary/` (3 files) | 25,541,400 | `8277767b2c90c904` (npz) | no | no | unknown | **P1** |
| `~/model/jetson_bundle/{pc_export_scripts, source (10 files), runner_patches (3 diffs), build_engines.sh, publish_bundle.py, INSTALLED.json, SYNC_PROTOCOL.md, engines/build_fp32_*.log}`, `~/model/driverguard/{run.py,runner/runner.py}.pre-v1-fp32` | about 0.2 MB | per file | no | no | unknown | **P1** (`INSTALLED.json` has an e-mail address: keep it private) |
| `~/driveragent-bk/calibration/` (camera 0-5 json, speed, steering, bev and control config) | 13,135 | per file | no | no | no | **P1** |
| `~/driveragent-bk/path/path_20260110_*.json` (4) | 1,401,694 | per file | no | no | no | **P1** |
| `~/Downloads/calcam/{calcam.py, cam0..cam5.yaml}` | 61,980 | cam0 `2301721d3653...` | no | no | unknown (the AGX02 set has other dates and a different size) | **P1** |
| `~/play/video` (27 sessions) | 2,233,825,832 | per file | no | unknown | no | **P2** |
| `~/development/video` (9 sessions + csv) | 1,180,323,835 | per file | no | unknown | no | **P2** |
| `~/driveragent/logs`, `~/driveragent-bk/logs` (185 bk-only files), `~/model/yolopx/YOLOPX/logs` | 295,059,604 + 48,964,609 + 113,983,585 | - | no | no | unknown | **P2** |
| `~/Documents/*/out` and the local changes of items 16, 17 | 16.5 MB | - | no | no | no | **P2** |
| `~/driveragent` `stash@{0}` | small | - | no | no | unknown | **P2** (secret: never push) |
| `~/driveragent-bk`: 111 code and data files, `england_greater-london.mbtiles` | 5.6 MB + 85,114,880 | london `32c4b477ad40d608` | no | no | mbtiles: path+size | **P3** |
| `~/model/jetson_bundle/engines/dtcp_v1_fp32.engine` (+ copy in `driverguard/engines`) | 155,349,444 | `15698f0f5acc5568` | no | no (the GCS engine is a rebuild, `391efbfb...`) | no | **P3** (can be rebuilt; save only for a byte-exact rollback) |
| `~/model/jetson_bundle/onnx/dtcp_v1_fix.onnx` | 97,041,146 | `2f8eea7118f33d9d` | no | no | no | **P3** |
| `~/model/sparsedrive/run/convnext_backbone_{decomposed,nofusion,simplified}.onnx`, SparseDrive code and `calibration.json` | about 370 MB | per file | no | no | no | **P3** |
| `~/model/yolopx/YOLOPX` local scripts (6) | 66 KB | per file | no | no | probably (count only) | **P3** |
| Old runner code: `~/model/jetson_bundle/validate_jetson.py`, `~/model/driverguard/run.py`, `~/model/driverguard/runner/*.py`, `~/model/system1/run.py`, `~/model/system1/runner/*.py` | about 70 KB | per file | no | no | unknown | **P3** |
| `~/bev`, `~/setup/bootstrap.sh`, `~/play/*.py`, `~/development/*.py`, `~/development/people/*.py`, `~/brake.log` | about 9.2 MB | - | no | no | no | **P3** |

**Not only copies** (proved): `yolopx_v2.onnx`, `dtcp_v1_main.onnx`, `dtcp_v1_control.onnx`, `MANIFEST.json`,
`samples/*`, `system1_deploy.pth`, `backbone_nchw.onnx(.data)`, `YOLOPX/weights/epoch-195.pth` (all in GCS); the
running engines `yolopx_v2_fp16.engine` (`3412bafa...`) and `dtcp_v1_fp16.engine` (`1071ea90...`),
`dtcp_v1.onnx.broken`, `sparsedrive/checkpoints/best.pth` and the 6 other SparseDrive run files (on AGX02 by sha256);
`~/driveragent/calibration/*` (in GitHub; `driveragent-models` README section 7 says "not published", which is true only
for GCS); `~/driveragent/ko/*.ko` (= `~/Downloads/SG8A/ko`); the `replay/*.mp4` test clips (in GitHub).

Note: README section 7 of `driveragent-models` calls `dtcp_v1_fp16.engine` an only copy on demo. AGX02 `docs/MODELS.md`
lists the same sha256 (`1071ea90213eddc2`) on AGX02. It is not an only copy. It stays because the node runs it.

Sizes to save: P1 0.70 GiB, P2 3.62 GiB, P3 0.73 GiB. Total about 5.05 GiB.

## 6. Change to main and independence plan (version 2, 2026-10-09)

This section replaces the first plan (2026-10-08). `main` now has the installer (`ops/install.sh`, `ops/preflight.sh`,
`ops/doctor.sh`, `ops/export_model.sh`, `ops/uninstall.sh`, `docs/INSTALL_AGX.md`). The machine data is not in git:
`config/*.yaml` are made from `config/templates/` and git ignores them. Part A and Part B are approved (2026-10-09).
Part C is not approved yet.

What the installer does from the first plan: no step completely. Partly: step 2 (`ops/export_model.sh` makes a
package with relative paths, but `install.sh` does not run it), step 6 (the templates have `models: []` and
`scan_dirs: []`, but install uses them only for a file that is missing) and step 10 (`ops/doctor.sh` checks the units,
`/api/health`, the store, the sensors and the pairing; it does not run the tests, a simulator test or
`da-models verify`). New items that the first plan did not have: pinned packages, user unit files with start at boot,
an install record and `ops/uninstall.sh`.

The AGX02 scripts: `ops/accept_stage1.sh` does not apply as it is (fixed values for AGX02: board `rk3588-da01`, set `@1`,
`systemd-timesyncd`, the units `lpd` and `apport.service`, power series `agx02`). Use `ops/doctor.sh` and the checks of
step B9. `ops/cleanup/stage1_disable.sh` can do items 61 to 70 only with a demo item list (no `lpd`, no
`apport.service`, no container before item 56 is approved) and `CLEANUP_HOST=demo`. `stage2_archive.sh` and
`stage3_delete.sh` do not apply (other archive layout; `rm`).

### Part A: preparation (no stop of the node)

1. Save the P1 files and copy the 4 sessions: **done 2026-10-09**. `~/backup/demo_20261009/p1.tar` (754,974,720 B,
   152 members, `tar -d` identical, `SHA256SUMS`). `~/agx-data/recordings/` (501 MB, sha256 identical).
2. Make the branch `deploy/demo-2` from `origin/main` in a separate worktree. Cherry-pick the two document commits,
   remove `docs/DEPLOY_NEW_AGX.md` (`docs/INSTALL_AGX.md` replaces it), correct the two demo documents, push the new
   branch. `deploy/demo` stays as the record. Then remove the worktree (a branch can be in only one worktree).
3. Backup in `~/agx-backup/demo-<date>/` (mode 700): `config/*.yaml`, `.env`, `.venv` (`cp -a`), and `pip freeze` of the
   venv and of `~/.local`. `data/` is copied after the stop (below), so that its SQLite files are consistent.

### Part B: change to main with the installer

Before step 4: record the sha256 of `data/paired_boards.json` (or "absent"), a sha256 of the dashboard password (the
value is not shown) and the pairing and link state (`/api/pair/boards`, `/api/link`). Stop the node
(`tools/svc.sh stop infer`, `tools/svc.sh stop dashboard`): the old processes must not run on the new code. Copy
`data/` to the backup. The node stays stopped until step 8 (some minutes; accepted on this bench unit).

4. In `~/driveragent-agx`: `git switch deploy/demo-2`. Git removes the tracked files `config/*.yaml` and `systemd/*`.
   Put the 6 config files back from the backup at once. Add `protected_dirs: [/home/tonyho/model]` to
   `config/dashboard.yaml` and `config/infer.yaml` (as on AGX02). `chmod 700 data`.
5. `ops/preflight.sh --instance agx`.
6. `ops/install.sh --user-site --no-enable --no-start`: packages into the venv, the kept files stay, the unit files are
   written. `--user-site`: the units keep torch, numpy and pycuda from `~/.local`, as before and as on AGX02.
7. `tools.model_check` for `driverguard_yolopx/1` and `driverguard_dtcp/1` with the new code.
8. `ops/install.sh --user-site --takeover --yes`: the installed units `agx-dashboard` and `agx-infer` are enabled and
   start. With Linger=yes they start at boot (no sudo).
9. Checks: `ops/doctor.sh --before-pairing`; the test suite (units stopped during the run); a 5-minute simulator test
   (set `mode: sim` in `config/sources.yaml`, restart agx-infer, `tools/svc.sh start sim --sessions` with the absolute
   paths of `~/agx-data/recordings`, then `mode: rk` again and restart). Then prove: mode rk; `data/paired_boards.json`
   has the same sha256 as before (or is still absent); the password did not change; the units are enabled and
   Linger=yes; if a board was paired, its link is UP again.
10. Rollback (when a step fails; no second method): `ops/uninstall.sh --yes` (when an install record exists), move the
    current `.venv` and `data/` to `~/_old_agx_<date>/rollback/`, `git switch deploy/demo`, put back `config/*.yaml`,
    `.env`, `data/` and `.venv` from the backup, then `tools/svc.sh start dashboard` and `tools/svc.sh start infer`.

### Part C: independence from `~/model` (not approved yet)

1. Make the packages: `ops/export_model.sh driverguard_yolopx 1 --with-engine` and the same for `driverguard_dtcp`
   (relative paths, sha256 check). Change `version` to `'2'` in each package manifest (the tool keeps `'1'`).
2. `tools/deploy_model.sh <package>` (on main: no host = local), then `tools.model_check ~/agx-models/<name>/2`.
   Expected: READY with no build (the same engine bytes).
3. Activate `driverguard_yolopx@2` and `driverguard_dtcp@2` (bench mode). The controller writes
   `_state/last_good.json`. Restart agx-infer once and prove the start from the store (about 6 s).
4. `config/models.yaml`: `models: []` or the store paths (machine data now: no git change).
5. Copies for the da-models runtimes: `message/{__init__.py,capnp_pubsub.py,message.capnp}` and the calibration to
   `/home/tonyho/agx-data/shared/`; `DRIVERAGENT_ROOT=/home/tonyho/agx-data/shared` for each da-models runtime.
6. Map service to the RK3588 (items 56, 57, 59, 60) before `~/driveragent` moves.
7. Checks: `ops/doctor.sh`, `tools.model_check`, the tests, a simulator test, `da-models verify`. Then items 5 to 11
   and item 1 can move.
8. Tests on main: `tests/test_t1_models_doc.py` runs while `AGX_OLD_MODELS` (default `/home/tonyho/model`) exists, and
   it fails on demo (demo has other engine files than AGX02). `tests/test_dashboard_v2.py::test_01_models` counts the
   SparseDrive engine path that is not on demo, and it fails (correction for the owner of main: count only the files
   that exist).

## 7. Unknowns

- GCS state of the 4 archives of item 19 and of the recordings in `~/play` and `~/development`: no read credential may be
  used.
- GitLab state of items 16 and 17: a check needs the token of `~/.gitconfig`.
- AGX02: no live check (no access from demo). Each "on AGX02" claim comes from AGX02 documents of 2026-10-05/07.
- Root-only data: root crontab, `/data` (root:root 700), NoMachine history, the owner of UDP ports 45970 and 49261.
- The client of the Valhalla requests of 2026-09-28 and 2026-08-18 (the log has no source address).
- Content of `config.ini` and of `stash@{0}` (not read on purpose: possible secret).
- No `da-models verify` baseline on demo (not run in PHASE A: it can write `/opt/driveragent/models/.lock`).

## Notes

1. **Move helpers (PHASE B).** Run these lines once in the PHASE B shell. Write the date of the move in place of
   `YYYYMMDD`.
   ```
   D=/home/tonyho/_old_agx_YYYYMMDD
   oldmv() {
     [ -n "$D" ] && [ $# -eq 1 ] || { echo 'oldmv: set D, give one path' >&2; return 2; }
     case $1 in /*) ;; *) echo 'oldmv: absolute path only' >&2; return 2;; esac
     p=${1%/}
     [ -e "$p" ] || { echo "oldmv: missing $p" >&2; return 1; }
     [ -e "$D$p" ] && { echo "oldmv: $D$p exists (a child moved before?)" >&2; return 1; }
     mkdir -p "$D$(dirname "$p")" && mv -n -T "$p" "$D$p" && [ ! -e "$p" ]
   }
   oldback() {
     [ -n "$D" ] && [ $# -eq 1 ] || return 2; p=${1%/}
     [ -e "$p" ] && { echo "oldback: $p exists" >&2; return 1; }
     mv -n -T "$D$p" "$p" && [ ! -e "$D$p" ] || return 1
     q=$D$(dirname "$p")   # remove the empty folders that the move leaves below $D
     while [ "$q" != "$D" ] && rmdir "$q" 2>/dev/null; do q=$(dirname "$q"); done
   }
   ```
   Give one absolute path for each call (no glob). The functions never overwrite, and they stop with a message when
   the target exists. When a child of a folder moved before (for example item 2 before item 1), `oldback` the child
   first, then move the folder.

2. **Final delete (after the second owner approval only).** `rm -rf "$D/home/tonyho/<path>"`. Use `sudo rm -rf` for items
   4, 16, 17, 24, 25 and 27 (root-owned files inside). For Docker: `docker rm driveragent-valhalla` and
   `docker rmi 2f4b9b17cda4` (no sudo). There is no undo after `rm`, except the saves of note 3.

3. **SAVE FIRST commands.** `B=/home/tonyho/backup/demo_YYYYMMDD` is on the same disk: it protects against a wrong move,
   not against a disk failure. After the save, copy `B` off the machine. Proposal: a new bucket or a new prefix that
   the owner selects (not `gs://driveragent-model`, which holds the model registry). Undo of each save: `rm -rf "$B/<file>"`
   (the saves only read the sources). Two G1 files can contain a secret: `private/driveragent.bundle` (it holds
   `refs/stash` and the GitHub history, which contains the secret files of note 7) and
   `private/driveragent-stash0.patch` (a `config.ini` change). Keep `$B/private` on the machine until the owner has
   read them. No other save includes a secret file.
   ```
   set -o pipefail
   B=/home/tonyho/backup/demo_YYYYMMDD; mkdir -p "$B/private"; cd /home/tonyho
   # G1 - ~/driveragent (item 1): all refs incl. the stash (keep the bundle private), the stash patch, small local files
   git -C driveragent bundle create "$B/private/driveragent.bundle" --all
   git -C driveragent stash show -p 'stash@{0}' > "$B/private/driveragent-stash0.patch"
   tar -C driveragent -czf "$B/driveragent-localfiles.tar.gz" assets.yaml paths/route_active.json ko
   # restore: git clone "$B/private/driveragent.bundle" driveragent-restore &&
   #   git -C driveragent-restore fetch "$B/private/driveragent.bundle" refs/stash && git -C driveragent-restore stash apply FETCH_HEAD
   # G2 - small repositories (items 11, 16, 17, 30)
   git -C model/yolopx/YOLOPX diff > "$B/YOLOPX.patch"
   git -C model/yolopx/YOLOPX ls-files --others --exclude-standard -z -- tools | tar -C model/yolopx/YOLOPX --null -T - -czf "$B/YOLOPX-tools.tar.gz"
   git -C Documents/remote_nav_status_api bundle create "$B/remote_nav_status_api.bundle" --all
   tar -C Documents/remote_nav_status_api -czf "$B/remote_nav_status_api-local.tar.gz" module/zmq_test.py out
   git -C Documents/race_sim_connect_api bundle create "$B/race_sim_connect_api.bundle" --all
   git -C Documents/race_sim_connect_api diff > "$B/race_sim_connect_api.patch"
   tar -C Documents/race_sim_connect_api -czf "$B/race_sim_connect_api-out.tar.gz" out
   git -C Downloads/jetson-jtop-patch diff > "$B/jetson-jtop-patch.patch"
   # G3 - install records (items 24, 25, 27, 28)
   cp Downloads/raylib/build/install_manifest.txt "$B/raylib-install_manifest.txt"
   cp opencv/build/install_manifest.txt "$B/opencv-install_manifest.txt"; cp opencv/build/CMakeCache.txt "$B/opencv-CMakeCache.txt"
   cp Downloads/cmake-3.31.9/install_manifest.txt "$B/cmake-install_manifest.txt"; cp Downloads/OpenCV-4-10-0.sh "$B/"
   # P1 - cannot be rebuilt (0.70 GiB)
   tar -cf "$B/p1.tar" model/jetson_bundle/onnx/dtcp_v1.onnx model/jetson_bundle/weights \
     model/system1/system1_scorer.pth model/system1/vocabulary model/jetson_bundle/pc_export_scripts \
     model/jetson_bundle/source model/jetson_bundle/runner_patches model/jetson_bundle/build_engines.sh \
     model/jetson_bundle/publish_bundle.py model/jetson_bundle/INSTALLED.json model/jetson_bundle/SYNC_PROTOCOL.md \
     model/jetson_bundle/engines/build_fp32_*.log model/driverguard/run.py.pre-v1-fp32 \
     model/driverguard/runner/runner.py.pre-v1-fp32 driveragent-bk/calibration driveragent-bk/path \
     Downloads/calcam/calcam.py Downloads/calcam/cam?.yaml
   # P2 - recordings and logs (3.62 GiB)
   tar -cf "$B/p2-recordings.tar" play/video development/video
   tar -czf "$B/p2-logs.tar.gz" driveragent/logs driveragent-bk/logs model/yolopx/YOLOPX/logs
   # P3 - can be rebuilt or low value (0.73 GiB)
   tar -czf "$B/p3-driveragent-bk.tar.gz" --exclude=.git --exclude=__pycache__ --exclude=valhalla_tiles \
     --exclude=united-kingdom-latest.osm.pbf --exclude=gb.mbtiles --exclude='test*.mp4' --exclude=logs \
     --exclude=gcs_upload.json --exclude=.env --exclude=config.ini --exclude=settings.local.json \
     --exclude=gslist.txt --exclude=service_list.yaml driveragent-bk
   tar -cf "$B/p3-model.tar" model/jetson_bundle/engines/dtcp_v1_fp32.engine model/jetson_bundle/onnx/dtcp_v1_fix.onnx \
     model/sparsedrive/run/convnext_backbone_decomposed.onnx model/sparsedrive/run/convnext_backbone_nofusion.onnx \
     model/sparsedrive/run/convnext_backbone_simplified.onnx model/sparsedrive/models model/sparsedrive/run/calibration.json \
     model/sparsedrive/run/hybrid_inference.py model/sparsedrive/run/camera_integration.py model/sparsedrive/run/build_trt_engine.py \
     model/sparsedrive/install.sh model/sparsedrive/package.sh model/sparsedrive/convnext_jetson_deploy.md \
     model/sparsedrive/run/trt_build.log model/jetson_bundle/validate_jetson.py model/driverguard/run.py \
     model/driverguard/runner/*.py model/system1/run.py model/system1/runner/*.py
   tar -czf "$B/p3-small.tar.gz" bev setup/bootstrap.sh play/extract.py play/replay.py play/return.py \
     development/people/*.py development/people/requirements.txt development/*.py brake.log
   # R - upload record (item 21)
   cp -a driveragent/logger/video/uploaded.db "$B/uploaded.db"
   (cd "$B" && sha256sum * > SHA256SUMS)
   ```

4. **VS Code server and autostart (items 43, 78).**
   ```
   for s in 41dd792b 8b640eef cfbea10c e7fb5e96; do
     oldmv "$(ls -d /home/tonyho/.vscode-server/cli/servers/Stable-$s*)"; oldmv "$(ls -d /home/tonyho/.vscode-server/code-$s*)"
   done
   oldmv /home/tonyho/.vscode-server/data/CachedExtensionVSIXs
   mkdir -p ~/.config/autostart
   for f in gnome-software-service update-notifier nvpmodel_indicator; do printf '[Desktop Entry]\nHidden=true\n' > ~/.config/autostart/$f.desktop; done
   ```
   Undo: `for p in "$D"/home/tonyho/.vscode-server/cli/servers/Stable-* "$D"/home/tonyho/.vscode-server/code-* "$D"/home/tonyho/.vscode-server/data/CachedExtensionVSIXs; do oldback "${p#$D}"; done`
   and `rm ~/.config/autostart/{gnome-software-service,update-notifier,nvpmodel_indicator}.desktop`.
   The autostart change has an effect at the next desktop login.

5. **Valhalla (items 56, 57, 59).** No sudo (group `docker`).
   ```
   mkdir -p "$B/docker"
   docker inspect driveragent-valhalla > "$B/docker/driveragent-valhalla.inspect.json"
   set -o pipefail
   docker save ghcr.io/valhalla/valhalla:latest | gzip > "$B/docker/valhalla_2f4b9b17cda4.tar.gz" && gunzip -t "$B/docker/valhalla_2f4b9b17cda4.tar.gz"
   docker update --restart=no driveragent-valhalla && docker stop driveragent-valhalla
   # copy the map data to the RK3588 (RK_USER, RK_HOST and the path are placeholders; free space on the RK3588: unknown)
   rsync -a --checksum /home/tonyho/driveragent/location/{united-kingdom-latest.osm.pbf,gb.mbtiles} /home/tonyho/driveragent-bk/location/england_greater-london.mbtiles RK_USER@RK_HOST:/PATH/ON/RK3588/
   ```
   Undo: `docker update --restart=unless-stopped driveragent-valhalla && docker start driveragent-valhalla`. After a
   delete (note 2): `gunzip -c "$B/docker/valhalla_2f4b9b17cda4.tar.gz" | docker load`, then
   `bash ~/driveragent/location/setup_valhalla.sh start`. The tiles (root-owned) can be rebuilt on the RK3588 from the
   pbf file. Dangling image (item 58), optional save: `docker save ca66a15903a4 | gzip > "$B/docker/valhalla_ca66a15903a4.tar.gz"`.

6. **GCS check of the 4 archives (item 19).** The owner runs it with a credential that can read the bucket. Expected
   sizes: 227568060, 154064581, 93816279, 51156733.
   ```
   gcloud storage ls -l gs://carvideo_osmosisai/8001/8001-20260926_12*.tar.bz2
   ```
   When each object exists with the same size, the archives can move (item 19).

7. **Secrets (owner items; no value is in this document).**
   - GitLab token in `~/.gitconfig` (item 36): revoke it in GitLab. Then remove the rule:
     `git config --global --remove-section 'url.<the rule>'` (the owner reads the key name). Undo: not necessary after
     revoke. Note: during this audit, `git remote -v` and `git config --list --name-only` showed the token in agent tool
     output, so it is also in local agent transcripts under `~/.claude/projects`. Revoke it.
   - Upload key `gcs_upload.json` (item 38): 5 copies, 4 with mode 664 (`~` is mode 750, so only the user and group
     `tonyho` can read them). Rotate the key if a copy left the machine. Keep one copy (mode 600).
   - `.env` files and `config.ini` (item 39): the owner decides. They are not in any save.
   - `gslist.txt` (a value in the format of a Google OAuth client secret, in a `tokeninfo` URL) and
     `message/service_list.yaml` (a password) are tracked in `~/driveragent` and are on GitHub since commit `3d1c844`.
     Copies are in `~/driveragent-bk`. Rotate both values. The P3 save excludes them; the G1 bundle contains them.
   - `stash@{0}` contains a `config.ini` change: keep the bundle of note 3 private. `config.ini` was in GitHub history
     (commits `3d1c844` to `3b51d53`): if it held a secret, rotate that secret.

8. **Order of PHASE B work.**
   1. Note 3 (all saves), then copy `B` off the machine.
   2. Section 6 (independence plan) and its checks.
   3. Items 56, 57, 59, 60 (map service to the RK3588).
   4. The move items of section 2 in table order. After each group: `tools/svc.sh status`, the test suite, and
      `da-models verify` (PHASE B step 3).
   5. Items 61 to 70 (sudo, owner).
   6. After 14 days with no problem: note 2 (final delete), with the second approval.

## Totals

All sizes are `du` values (GiB unless written). The sum assumes that the owner approves every DELETE and MOVE item.

| Group | Items | Size |
|---|---|---|
| Old trees and backups | 2, 4, 6 to 11 | about 11.9 |
| Old recordings and projects | 12, 13, 14, 16, 17, 20 | about 6.0 |
| Downloads and build trees | 23 to 28, 31 (venv), 33 to 35 | about 6.3 |
| Caches and tool data | 40, 41a, 41b, 43 (4 old servers 1.1, VSIX cache 0.45), 44, 45, 48 | about 3.3 |
| Docker images | 57, 58 | 1.3 (1.39 GB) |
| Map data (copied to the RK3588) | 59, 60 | 0 now. Item 59 (5.8) leaves demo only with item 1. Item 60 is in item 4. |
| **Total** | | **about 29 GiB** |

- `~/driveragent` itself (item 1, 7.2G with the map data) is not in the sum. It moves only after section 6 and the
  map items.
- The saves of note 3 use about 5.1 GiB more (plus the Docker image save, about 0.7 GiB).
- Expected free space after all items and the final delete, with the saves still on demo: about 827 GiB of 915 GiB.
- RAM: items 61 to 68 and 78 free about 3 GiB of 61 GiB. RAM is not a problem now (12.8 GiB used).
