<!-- Copy of /home/tonyho/driveragent-agx/docs/audit/agx_audit_agx02_20261005_210334/report.md. Run: 2026-10-05 21:03 by the night agent as user tonyho WITHOUT sudo (sudo needs a password). Command: cd /home/tonyho/driveragent-agx/docs/audit && OUT=/home/tonyho/driveragent-agx/docs/audit/agx_audit_agx02_20261005_210334 RK_IP=100.64.0.180 bash ~/agx_audit.sh . Full raw output: /home/tonyho/driveragent-agx/docs/audit/agx_audit_agx02_20261005_210334/raw/ (not in git). -->

# AGX audit - agx02 - 2026-10-05 21:04

Read-only audit, script v1.0. Nothing on the machine was changed. Secrets are masked; check before sharing outside the team.

## 0. Flags

- **Run without root**: Docker, other users' files and some services are incomplete. Re-run with sudo.
- Boots into the **desktop (graphical.target)**: uses RAM/GPU that a headless inference node does not need.
- **1 failed systemd unit(s)**.
- **24 hand-made systemd unit(s) start at boot** (section 3).
- **1 Docker container(s) restart automatically** (section 5).
- **14 git repo(s) have uncommitted or unpushed work** - push before any cleanup (section 9).
- **1 git repo(s) have no remote** - this machine holds the only copy.
- **26 model files, 3.3G** (5 TensorRT engines).
- **11718 recording/log files, 267.0G**.

## 1. System

### Identity

```
model      : NVIDIA Jetson AGX Orin Developer Kit
hostname   : agx02
os         : Ubuntu 22.04.5 LTS
kernel     : 5.15.148-tegra aarch64
l4t        : # R36 (release), REVISION: 4.7, GCID: 42132812, BOARD: generic, EABI: aarch64, DATE: Thu Sep 18 22:54:44 UTC 2025
jetpack    : 6.2.1+b38
l4t-core   : 36.4.7-20250918154033
uptime     : up 1 week, 3 days, 11 hours, 56 minutes   load: 0.12 0.13 0.09
boot target: graphical.target
cpu cores  : 12
audit run  : 2026-10-05T21:03:34+01:00 as tonyho (root=0)
```

### Power mode, temperature, load

```
NV Power Mode: MAXN
0
--- thermal zones
cpu-thermal        52 C
soc0-thermal       49 C
soc1-thermal       49 C
soc2-thermal       48 C
tj-thermal         52 C
--- tegrastats (1 sample)
10-05-2026 21:03:35 RAM 5137/62841MB (lfb 2x4MB) SWAP 0/31420MB (cached 0MB) CPU [1%@729,25%@729,1%@729,1%@729,2%@729,1%@729,0%@729,0%@729,2%@729,14%@729,1%@729,0%@729] GR3D_FREQ 0% cpu@52.875C soc2@48.656C soc0@49.062C tj@52.875C soc1@49.031C VDD_GPU_SOC 3178mW/3178mW VDD_CPU_CV 794mW/794mW VIN_SYS_5V0 4543mW/4543mW
```

### Memory and swap

```
               total        used        free      shared  buff/cache   available
Mem:            61Gi       3.7Gi        37Gi        94Mi        20Gi        56Gi
Swap:           30Gi          0B        30Gi
--- swap
NAME        TYPE      SIZE USED PRIO
/dev/zram0  partition 2.6G   0B    5
/dev/zram1  partition 2.6G   0B    5
/dev/zram2  partition 2.6G   0B    5
/dev/zram3  partition 2.6G   0B    5
/dev/zram4  partition 2.6G   0B    5
/dev/zram5  partition 2.6G   0B    5
/dev/zram6  partition 2.6G   0B    5
/dev/zram7  partition 2.6G   0B    5
/dev/zram8  partition 2.6G   0B    5
/dev/zram9  partition 2.6G   0B    5
... (2 more lines - full output: raw/Memory_and_swap.txt)
```

### Clock and time sync

```
               Local time: Mon 2026-10-05 21:03:36 BST
           Universal time: Mon 2026-10-05 20:03:36 UTC
                 RTC time: Mon 2026-10-05 20:03:37
                Time zone: Europe/London (BST, +0100)
System clock synchronized: yes
              NTP service: active
          RTC in local TZ: no
--- time-sync services (needed later to match AGX results to RK3588 frames)
systemd-timesyncd: active
```

## 2. AI / inference stack

### NVIDIA and inference packages

```
libnvinfer10 10.3.0.30-1+cuda12.5
libopencv 4.8.0-1-g6371ee1
nvidia-container-toolkit 1.16.2-1
nvidia-cudnn 6.2.1+b38
nvidia-l4t-core 36.4.7-20250918154033
nvidia-l4t-gstreamer 36.4.7-20250918154033
nvidia-l4t-multimedia 36.4.7-20250918154033
nvidia-opencv 6.2.1+b38
nvidia-tensorrt 6.2.1+b38
nvidia-vpi 6.2.1+b38
python3-libnvinfer 10.3.0.30-1+cuda12.5
tensorrt 10.3.0.30-1+cuda12.5
--- cuda dirs
/usr/local/cuda
/usr/local/cuda-12
/usr/local/cuda-12.6
--- trtexec
-rwxr-xr-x 1 root root 1695696 Sep 14  2024 /usr/src/tensorrt/bin/trtexec
--- ROS
none
--- GStreamer
gst-inspect-1.0 version 1.20.3
GStreamer 1.20.3
nvv4l2decoder: ok
nvv4l2h265enc: ok
nvvidconv: ok
rtph265depay: ok
rtph264depay: ok
```

### Python packages and environments

```
interpreter: /usr/bin/python3  Python 3.10.12
tensorrt                 10.3.0
pycuda                   2022.2.2
torch                    2.8.0
torchvision              0.23.0
onnx                     1.21.0
onnxruntime              1.23.2
numpy                    1.26.4
pyzmq                    27.1.0
pycapnp                  2.2.0
jetson-stats             4.3.2
import tensorrt          10.3.0
import cv2               4.10.0
pip packages total       195
--- virtualenvs / conda envs
/home/tonyho/Downloads/calcam/venv
/home/tonyho/model/yolopx/venv
```

## 3. Services and autostart

### Custom systemd units (created by hand)

```
jtop.service | enabled=enabled | active=active
    Description=jtop service
    After=multi-user.target
    Environment="JTOP_SERVICE=True"
    ExecStart=/usr/local/bin/jtop --force
    Restart=on-failure
nv-ftpm-device-provision.service | enabled=enabled | active=inactive
    Description=fTPM Device Provisioning Service
    After=nv-tee-supplicant.service multi-user.target
    ExecStart=/etc/systemd/nv-ftpm-device-provision.sh
nv-late-init.service | enabled=enabled | active=inactive
    Description=NVIDIA Late Init Script
    After=multi-user.target
    ExecStart=/etc/systemd/nv-late-init.sh
nv-ms-tpm-removal.service | enabled=disabled | active=inactive
    Description=Remove fTPM TEE kernel module
    ExecStart=/etc/systemd/nv-ms-tpm-removal.sh
nv-tee-supplicant.service | enabled=enabled | active=active
    Description=OP-TEE Client Supplicant
    After=systemd-modules-load.service
    Environment=RETRY_COUNT=30
    Environment=RETRY_INTERVAL=0.1
    ExecStart=/etc/systemd/nv-tee-supplicant.sh
    Restart=always
nv.service | enabled=enabled | active=inactive
    Description=NVIDIA specific script
    After=nvfb.service
    ExecStart=/etc/systemd/nv.sh
nv_nvsciipc_init.service | enabled=enabled | active=inactive
    Description=NvSciIpc initialization
    After=sysinit.target
    After=nvfb-early.service
    After=nvfb.service
    ExecStart=/bin/sh /etc/systemd/nv_nvsciipc_init.sh
nvargus-daemon.service | enabled=enabled | active=active
    Description=Argus daemon
    After=nv.service
    After=nvpmodel.service
    After=network-online.target
    ExecStart=/usr/sbin/nvargus-daemon
    Restart=on-failure
nvcpupowerfix.service | enabled=enabled | active=inactive
    Description=Nvidia CPU Power Fix
    After=suspend.target
    User=root
    ExecStart=/etc/systemd/nvcpupowerfix.sh
nvfancontrol.service | enabled=enabled | active=active
    Description=nvfancontrol service
    After=nvfb-early.service nvpower.service
    ExecStart=/usr/sbin/nvfancontrol &
    Restart=on-failure
nvfb-early.service | enabled=enabled | active=inactive
    Description=NVIDIA specific early first-boot script
    ExecStart=/etc/systemd/nvfb-early.sh
nvfb-udev.service | enabled=enabled | active=active
    Description=NVIDIA specific first-boot udev script
    ExecStart=/etc/systemd/nvfb-udev.sh
nvfb.service | enabled=enabled | active=inactive
    Description=NVIDIA specific first-boot script
    ExecStart=/etc/systemd/nvfb.sh
nvgetty.service | enabled=enabled | active=inactive
    Description=UART on ttyTHS0
    After=nv.service
    After=nvpmodel.service
    After=getty.target
    ExecStart=/etc/systemd/nvgetty.sh
nvidia-pva-allowd.service | enabled=enabled | active=active
    Description=service for managing PVA allowlists
    ExecStart=/opt/nvidia/pva-allow-2/bin/nvidiaPvaAllowd.py
    Environment=PYTHONUNBUFFERED=1
    Restart=on-failure
nvmemwarning.service | enabled=enabled | active=inactive
    Description=Display Low memory warning
    After=nv.service
    ExecStart=/etc/systemd/nvmemwarning.sh
nvphs.service | enabled=enabled | active=active
    Description=PHS daemon
    After=nv.service
    After=nvpmodel.service
    ExecStart=/usr/sbin/nvphsd
nvpmodel.service | enabled=enabled | active=inactive
    Description=nvpmodel service
    After=nv.service nvpower.service
    ExecStart=/etc/systemd/nvpmodel.sh
nvpower.service | enabled=enabled | active=inactive
    Description=NVIDIA specific power script
    After=systemd-modules-load.service
    ExecStart=/etc/systemd/nvpower.sh
nvramoopsconfig.service | enabled=enabled | active=inactive
    Description=ramoops module
    After=nv.service
    ExecStart=/etc/systemd/nvramoops.sh
nvs-service.service | enabled=enabled | active=active
    Description=NVS-SERVICE Embedded Sensor HAL Daemon
    After=nvfb-early.service
    After=nv.service
    After=network-online.target
    ExecStart=/usr/sbin/nvs-service
    Restart=on-failure
nvweston.service | enabled=enabled | active=inactive
    Description=NVIDIA weston service
    ExecStart=/etc/systemd/nvweston.sh
nvwifibt.service | enabled=static | active=inactive
    Description=NVIDIA bluetooth/wifi init script
    After=nv.service
    ExecStart=/etc/systemd/nvwifibt.sh
nvzramconfig.service | enabled=enabled | active=inactive
    Description=ZRAM configuration
    After=nv.service
    After=nvpmodel.service
    ExecStart=/etc/systemd/nvzramconfig.sh
snap.chromium.daemon.service | enabled=disabled | active=inactive
    Description=Service for snap application chromium.daemon
    After=snap-chromium-3535.mount network.target snapd.apparmor.service
    EnvironmentFile=-/etc/environment
    ExecStart=/usr/bin/snap run chromium.daemon
    Restart=on-failure
    WorkingDirectory=/var/snap/chromium/3535
snap.cups.cups-browsed.service | enabled=enabled | active=active
    Description=Service for snap application cups.cups-browsed
    After=snap-cups-1261.mount network.target snapd.apparmor.service
    EnvironmentFile=-/etc/environment
    ExecStart=/usr/bin/snap run cups.cups-browsed
    Restart=always
    WorkingDirectory=/var/snap/cups/1261
snap.cups.cupsd.service | enabled=enabled | active=active
    Description=Service for snap application cups.cupsd
    After=snap-cups-1261.mount network.target snapd.apparmor.service
    EnvironmentFile=-/etc/environment
    ExecStart=/usr/bin/snap run cups.cupsd
    Restart=always
    WorkingDirectory=/var/snap/cups/1261
snap.mesa-2404.component-monitor.service | enabled=disabled | active=inactive
    Description=Service for snap application mesa-2404.component-monitor
    After=snap-mesa\x2d2404-1836.mount network.target snapd.apparmor.service
    EnvironmentFile=-/etc/environment
    ExecStart=/usr/bin/snap run mesa-2404.component-monitor
    Restart=always
    WorkingDirectory=/var/snap/mesa-2404/1836
```

### Running services

```
accounts-daemon.service
avahi-daemon.service
bluetooth.service
colord.service
containerd.service
cron.service
dbus.service
docker.service
gdm.service
haveged.service
jtop.service
kerneloops.service
ModemManager.service
networkd-dispatcher.service
NetworkManager.service
nv-tee-supplicant.service
nvargus-daemon.service
nvfancontrol.service
nvidia-pva-allowd.service
nvphs.service
nvs-service.service
nxserver.service
openvpn@uk-ovpn-agent-20.service
packagekit.service
polkit.service
power-profiles-daemon.service
rpcbind.service
rsyslog.service
rtkit-daemon.service
seatd.service
serial-getty@ttyAMA0.service
serial-getty@ttyGS0.service
serial-getty@ttyTCU0.service
snap.cups.cups-browsed.service
snap.cups.cupsd.service
snapd.service
ssh.service
switcheroo-control.service
systemd-journald.service
systemd-logind.service
systemd-resolved.service
systemd-timedated.service
systemd-timesyncd.service
systemd-udevd.service
tailscaled.service
udisks2.service
upower.service
user@1000.service
wpa_supplicant.service
```

### Enabled services (start at boot)

```
accounts-daemon.service
anacron.service
apparmor.service
avahi-daemon.service
binfmt-support.service
blk-availability.service
bluetooth.service
console-setup.service
containerd.service
cron.service
dmesg.service
docker.service
e2scrub_reap.service
getty@.service
haveged.service
jtop.service
kerneloops.service
keyboard-setup.service
l4t-rootfs-validation-config.service
lvm2-monitor.service
ModemManager.service
networkd-dispatcher.service
NetworkManager-dispatcher.service
NetworkManager.service
nv-ftpm-device-provision.service
nv-l4t-bootloader-config.service
nv-l4t-usb-device-mode.service
nv-late-init.service
nv-tee-supplicant.service
nv.service
nv_nvsciipc_init.service
nvargus-daemon.service
nvcpupowerfix.service
nvfancontrol.service
nvfb-early.service
nvfb-udev.service
nvfb.service
nvgetty.service
nvidia-pva-allowd.service
nvmefc-boot-connections.service
nvmemwarning.service
nvmf-autoconnect.service
nvphs.service
nvpmodel.service
nvpower.service
nvramoopsconfig.service
nvs-service.service
nvweston.service
nvzramconfig.service
nxserver.service
openvpn.service
power-profiles-daemon.service
resolvconf-pull-resolved.service
resolvconf.service
rpcbind.service
rsyslog.service
seatd.service
secureboot-db.service
setvtrgb.service
snap.cups.cups-browsed.service
snap.cups.cupsd.service
snapd.apparmor.service
snapd.autoimport.service
snapd.core-fixup.service
snapd.recovery-chooser-trigger.service
snapd.seeded.service
snapd.service
snapd.system-shutdown.service
ssh.service
sssd.service
switcheroo-control.service
systemd-oomd.service
systemd-pstore.service
systemd-resolved.service
systemd-timesyncd.service
tailscaled.service
ua-reboot-cmds.service
ubuntu-advantage.service
udisks2.service
wpa_supplicant.service
```

### Failed units

```
* apport-autoreport.service loaded failed failed Process error reports when automatic reporting is enabled
```

### Timers

```
NEXT                        LEFT          LAST                        PASSED        UNIT                           ACTIVATES
Mon 2026-10-05 21:30:07 BST 26min left    Mon 2026-10-05 20:30:20 BST 33min ago     anacron.timer                  anacron.service
Mon 2026-10-05 22:14:36 BST 1h 10min left Mon 2026-10-05 19:14:36 BST 1h 49min ago  apport-autoreport.timer        apport-autoreport.service
Tue 2026-10-06 00:00:00 BST 2h 56min left Mon 2026-10-05 00:00:00 BST 21h ago       dpkg-db-backup.timer           dpkg-db-backup.service
Tue 2026-10-06 00:41:55 BST 3h 38min left Mon 2026-10-05 09:38:28 BST 11h ago       man-db.timer                   man-db.service
Tue 2026-10-06 03:15:48 BST 6h left       Mon 2026-10-05 12:10:52 BST 8h ago        motd-news.timer                motd-news.service
Tue 2026-10-06 05:20:47 BST 8h left       Mon 2026-10-05 17:47:16 BST 3h 16min ago  fwupd-refresh.timer            fwupd-refresh.service
Tue 2026-10-06 06:05:38 BST 9h left       Mon 2026-10-05 06:05:46 BST 14h ago       apt-daily-upgrade.timer        apt-daily-upgrade.service
Tue 2026-10-06 06:25:08 BST 9h left       Mon 2026-10-05 18:26:23 BST 2h 37min ago  apt-daily.timer                apt-daily.service
Tue 2026-10-06 09:12:44 BST 12h left      Mon 2026-10-05 09:12:44 BST 11h ago       update-notifier-download.timer update-notifier-download.service
Tue 2026-10-06 09:22:40 BST 12h left      Mon 2026-10-05 09:22:40 BST 11h ago       systemd-tmpfiles-clean.timer   systemd-tmpfiles-clean.service
Sat 2026-10-10 17:48:45 BST 4 days left   Wed 2026-09-30 15:37:46 BST 5 days ago    update-notifier-motd.timer     update-notifier-motd.service
Sun 2026-10-11 03:10:00 BST 5 days left   Sun 2026-10-04 03:10:22 BST 1 day 17h ago e2scrub_all.timer              e2scrub_all.service
Mon 2026-10-12 00:52:23 BST 6 days left   Mon 2026-10-05 00:58:38 BST 20h ago       fstrim.timer                   fstrim.service
n/a                         n/a           n/a                         n/a           snapd.snap-repair.timer        snapd.snap-repair.service
n/a                         n/a           n/a                         n/a           ua-timer.timer                 ua-timer.service

15 timers listed.
```

### Common removal candidates - current status only

```
UNIT                               ENABLED    ACTIVE
gdm3                               alias      active
gdm                                static     active
bluetooth                          enabled    active
ModemManager                       enabled    active
apport                             enabled    active
kerneloops                         enabled    active
snapd                              enabled    active
avahi-daemon                       enabled    active
packagekit                         static     active
colord                             static     active
speech-dispatcher                  disabled   inactive
rtkit-daemon                       disabled   active
udisks2                            enabled    active
fwupd                              static     inactive
nvargus-daemon                     enabled    active
nv-l4t-usb-device-mode             enabled    active
nvzramconfig                       enabled    inactive
docker                             enabled    active
containerd                         enabled    active
nxserver                           enabled    active
tailscaled                         enabled    active
openvpn                            enabled    active
wpa_supplicant                     enabled    active
NetworkManager-wait-online         disabled   inactive
jtop                               enabled    active
```

### Cron, rc.local, autostart, process managers

```
--- /etc/cron.d
anacron
e2scrub_all
--- /etc/rc.local
(none)
--- desktop autostart
--- shell rc files that start programs (lines with nohup / & / python / docker)
--- process managers
audit: 1 windows (created Fri Sep 25 09:15:27 2026)
new: 1 windows (created Mon Oct  5 20:12:22 2026)
```

## 4. Processes right now

### Top CPU

```
    PID USER     %CPU %MEM   RSS ELAPSED COMMAND
1749854 tonyho    1.7  0.7 458884   3076 claude
1788164 root      1.6  0.0  3788       5 /lib/systemd/systemd-timedated
1788011 tonyho    0.8  0.0 32152       7 /usr/libexec/tracker-extract-3
 104172 tonyho    0.6  0.5 377748 880274 claude -resume
   1808 nx        0.5  0.2 187780 906994 /usr/NX/bin/nxserver.bin --daemon
1788033 tonyho    0.4  0.0  3564       7 bash /home/tonyho/agx_audit.sh
   2277 root      0.3  0.2 130872 906992 valhalla_service /data/valhalla.json 4
    414 root      0.2  0.0  6432  906999 /lib/systemd/systemd-udevd
   3325 root      0.2  0.0 32408  906990 /usr/NX/bin/nxrunner.bin --update ask --background --root /var/NX/nx/.nx
 104512 tonyho    0.2  0.0 40932  880202 /usr/NX/bin/nxplayer.bin --dialog users
    849 root      0.1  0.0     0  906996 [sugov:0]
    851 root      0.1  0.0     0  906996 [sugov:4]
    854 root      0.1  0.0     0  906996 [sugov:8]
   2471 tonyho    0.1  0.3 224512 906992 /usr/bin/gnome-shell
      1 root      0.0  0.0 12896  907008 /sbin/init 2
      2 root      0.0  0.0     0  907008 [kthreadd]
      3 root      0.0  0.0     0  907008 [rcu_gp]
      4 root      0.0  0.0     0  907008 [rcu_par_gp]
      5 root      0.0  0.0     0  907008 [slub_flushwq]
      6 root      0.0  0.0     0  907008 [netns]
```

### Top memory

```
    PID USER     %CPU %MEM   RSS ELAPSED COMMAND
   3094 tonyho    0.0  0.9 624328 906990 /usr/bin/gnome-software --gapplication-service
1749854 tonyho    1.7  0.7 458884   3076 claude
 104172 tonyho    0.6  0.5 377748 880274 claude -resume
 659777 tonyho    0.0  0.4 265132 831681 /usr/bin/python3 /usr/bin/update-manager --no-update --no-focus-on-map
   2471 tonyho    0.1  0.3 224512 906992 /usr/bin/gnome-shell
   1808 nx        0.5  0.2 187780 906994 /usr/NX/bin/nxserver.bin --daemon
   2277 root      0.3  0.2 130872 906992 valhalla_service /data/valhalla.json 4
   1781 root      0.0  0.1 107936 906994 /usr/lib/xorg/Xorg vt2 -displayfd 3 -auth /run/user/1000/gdm/Xauthority -nolisten tcp -background none -noreset -keeptty -novtswitch -verbose 3
    318 root      0.0  0.1 101992 907000 /lib/systemd/systemd-journald
   1418 root      0.0  0.1 92752  906994 /usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
   2615 tonyho    0.0  0.1 87672  906991 /usr/NX/bin/nxnode.bin
   2949 root      0.0  0.1 86744  906990 /usr/libexec/packagekitd
   3373 tonyho    0.0  0.1 78316  906990 /usr/libexec/tracker-miner-fs-3
    911 root      0.0  0.1 76448  906996 /usr/sbin/tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/run/tailscale/tailscaled.sock --port=41641
   3103 tonyho    0.0  0.1 67032  906990 /usr/libexec/evolution-data-server/evolution-alarm-notify
    818 root      0.0  0.0 56348  906996 /usr/lib/snapd/snapd
   1206 root      0.0  0.0 54768  906994 /usr/bin/containerd
   3002 tonyho    0.0  0.0 51404  906990 /usr/libexec/xdg-desktop-portal-gnome
   3083 tonyho    0.0  0.0 43924  906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   2871 tonyho    0.0  0.0 43024  906991 /usr/NX/bin/nxrunner.bin --monitor --pid 2157
```

### Application processes (python, gstreamer, ros, web, map...)

```
    347 root      907000 [nvmap-bz]
    784 root      906996 python3 /opt/nvidia/pva-allow-2/bin/nvidiaPvaAllowd.py
   2367 root      906992 /usr/bin/python3 /usr/local/bin/jtop --force
   2528 root      906991 /usr/bin/python3 /usr/local/bin/jtop --force
   2540 root      906991 /usr/bin/python3 /usr/local/bin/jtop --force
   2614 root      906991 /usr/NX/bin/nxexec --node /usr/NX/bin/nxexec --nopam --user tonyho --priority realtime --mode 0 --pid 61
   3083 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3313 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3315 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3317 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3319 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3320 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3322 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3323 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3324 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3335 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3337 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3339 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3341 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3344 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3346 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3349 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3351 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3352 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3354 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
   3355 tonyho    906990 python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py
  86637 tonyho    901932 python3 -
 659777 tonyho    831681 /usr/bin/python3 /usr/bin/update-manager --no-update --no-focus-on-map
```

## 5. Docker

### Docker overview

```
Docker version 29.4.3, build 055a478
root dir: /var/lib/docker   storage: overlay2   default runtime: runc   containers: 1 (running 1)   images: 1
--- disk use
TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
Images          1         1         733.4MB   0B (0%)
Containers      1         1         0B        0B
Local Volumes   0         0         0B        0B
Build Cache     0         0         0B        0B
```

### Containers

```
NAMES                  IMAGE                              STATUS       PORTS                                         SIZE
driveragent-valhalla   ghcr.io/valhalla/valhalla:latest   Up 10 days   0.0.0.0:8002->8002/tcp, [::]:8002->8002/tcp   0B (virtual 733MB)
```

### Container details (restart policy, mounts, ports)

```
--- driveragent-valhalla
image     : ghcr.io/valhalla/valhalla:latest
state     : running | started 2026-09-25T08:07:09 | finished 2026-09-25T08:06:21
restart   : unless-stopped
runtime   : runc | network: bridge | privileged: False
ports     : 0.0.0.0:8002->8002/tcp, :::8002->8002/tcp
command   : valhalla_service /data/valhalla.json 4
mount     : bind /home/tonyho/driveragent/location/valhalla.json -> /data/valhalla.json
mount     : bind /home/tonyho/driveragent/location/valhalla_tiles -> /data/valhalla_tiles
env names : LD_LIBRARY_PATH PATH
```

### Images

```
REPOSITORY:TAG                     IMAGE ID       SIZE      CREATED
ghcr.io/valhalla/valhalla:latest   063da86ba07c   733MB     7 months ago
```

### Volumes and networks

```
DRIVER    VOLUME NAME
--- networks
NETWORK ID     NAME      DRIVER    SCOPE
b6c21140bf4a   bridge    bridge    local
b03b90309375   host      host      local
5bf423a7304a   none      null      local
```

### Compose files and Dockerfiles on disk

```
/home/tonyho/Downloads/maplibre-native/docker/Dockerfile
/home/tonyho/Downloads/maplibre-native/docker/Dockerfile.dockerignore
/home/tonyho/opencv_contrib/modules/cannops/Dockerfile
```

## 6. Network

### Interfaces, routes, links, VPN

```
lo               UNKNOWN        127.0.0.1/8 ::1/128 
can0             DOWN           
wlP1p1s0         DOWN           
can1             DOWN           
eno1             UP             10.0.0.130/24 fd7c:91e9:be3d:35ee:fde1:ab20:5211:a085/64 fd7c:91e9:be3d:35ee:49ac:3535:23ff:ca63/64 fd7c:91e9:be3d:35ee:1ff:afcf:bc84:1e1a/64 fd7c:91e9:be3d:35ee:dfe6:c0dd:9ee4:fdd5/64 fd7c:91e9:be3d:35ee:5790:85a8:68f8:d8ef/64 fd7c:91e9:be3d:35ee:853b:f38c:17a4:1f72/64 fd7c:91e9:be3d:35ee:b4c4:859:8ecb:7edf/64 fd7c:91e9:be3d:35ee:105b:e9ca:d764:7f2b/64 fe80::7667:50b5:912d:b911/64 
l4tbr0           DOWN           
usb0             DOWN           
usb1             DOWN           
tailscale0       UNKNOWN        100.64.0.20/32 fe80::8d71:1f57:57a3:d3ca/64 
docker0          UP             172.17.0.1/16 fe80::4cae:6bff:fe94:6273/64 
vethd73d22b@if2  UP             fe80::3ce1:fcff:fe18:f1f2/64 
--- routes
default via 10.0.0.1 dev eno1 proto static metric 100 
10.0.0.0/24 dev eno1 proto kernel scope link src 10.0.0.130 metric 100 
100.64.0.12 dev tailscale0 
100.64.0.13 dev tailscale0 
100.64.0.15 dev tailscale0 
100.64.0.19 dev tailscale0 
100.64.0.89 dev tailscale0 
100.64.0.117 dev tailscale0 
100.64.0.125 dev tailscale0 
100.64.0.136 dev tailscale0 
100.64.0.158 dev tailscale0 
100.64.0.180 dev tailscale0 
100.64.0.181 dev tailscale0 
100.64.0.182 dev tailscale0 
100.68.31.20 dev tailscale0 
100.69.84.76 dev tailscale0 
100.71.14.86 dev tailscale0 
100.76.140.55 dev tailscale0 
100.85.0.3 dev tailscale0 
100.85.0.31 dev tailscale0 
100.85.0.32 dev tailscale0 
100.85.0.33 dev tailscale0 
100.85.0.34 dev tailscale0 
100.85.0.47 dev tailscale0 
100.85.0.92 dev tailscale0 
100.85.0.93 dev tailscale0 
100.85.0.94 dev tailscale0 
100.85.0.96 dev tailscale0 
100.85.0.97 dev tailscale0 
100.85.0.173 dev tailscale0 
100.85.0.174 dev tailscale0 
100.85.0.178 dev tailscale0 
100.85.0.179 dev tailscale0 
100.85.0.180 dev tailscale0 
100.85.0.181 dev tailscale0 
100.85.0.182 dev tailscale0 
100.85.0.183 dev tailscale0 
100.85.0.184 dev tailscale0 
100.85.0.185 dev tailscale0 
100.85.0.186 dev tailscale0 
100.85.0.187 dev tailscale0 
100.85.0.188 dev tailscale0 
100.85.0.203 dev tailscale0 
100.85.0.204 dev tailscale0 
100.85.0.208 dev tailscale0 
100.85.0.211 dev tailscale0 
100.85.0.212 dev tailscale0 
100.85.0.213 dev tailscale0 
100.85.0.215 dev tailscale0 
100.85.0.216 dev tailscale0 
100.85.0.218 dev tailscale0 
100.85.0.227 dev tailscale0 
100.85.0.228 dev tailscale0 
100.85.0.229 dev tailscale0 
100.85.0.230 dev tailscale0 
100.85.0.231 dev tailscale0 
100.85.0.232 dev tailscale0 
100.85.0.233 dev tailscale0 
100.85.0.234 dev tailscale0 
100.85.0.235 dev tailscale0 
100.85.0.236 dev tailscale0 
100.85.0.237 dev tailscale0 
100.85.0.238 dev tailscale0 
100.85.0.239 dev tailscale0 
100.85.0.240 dev tailscale0 
100.85.0.245 dev tailscale0 
100.85.0.246 dev tailscale0 
100.85.0.247 dev tailscale0 
100.85.0.250 dev tailscale0 
100.85.0.254 dev tailscale0 
100.85.1.1 dev tailscale0 
100.85.1.8 dev tailscale0 
100.85.1.9 dev tailscale0 
100.85.1.10 dev tailscale0 
100.85.1.11 dev tailscale0 
100.85.4.108 dev tailscale0 
100.85.4.237 dev tailscale0 
100.85.13.114 dev tailscale0 
... (71 more lines - full output: raw/Interfaces__routes__links__VPN.txt)
```

### Listening ports

```
tcp   0.0.0.0:111                  
tcp   0.0.0.0:22                   
tcp   0.0.0.0:4000                 
tcp   0.0.0.0:631                  
tcp   0.0.0.0:8002                 
tcp   100.64.0.20:32943            
tcp   127.0.0.1:12001              users:(("nxnode.bin",pid=2615,fd=20))
tcp   127.0.0.1:21574              
tcp   127.0.0.1:23631              
tcp   127.0.0.1:25001              users:(("nxrunner.bin",pid=2871,fd=14))
tcp   127.0.0.1:42599              users:(("nxplayer.bin",pid=104512,fd=46))
tcp   127.0.0.1:7001               users:(("nxnode.bin",pid=2615,fd=27))
tcp   127.0.0.53%lo:53             
tcp   [::1]:7001                   users:(("nxnode.bin",pid=2615,fd=25))
tcp   [::]:111                     
tcp   [::]:22                      
tcp   [::]:4000                    
tcp   [::]:631                     
tcp   [::]:8002                    
udp   *:111                        
udp   *:37714                      
udp   *:4000                       
udp   *:41641                      
udp   *:5353                       
udp   0.0.0.0:111                  
udp   0.0.0.0:38755                
udp   0.0.0.0:4000                 
udp   0.0.0.0:41641                
udp   0.0.0.0:5353                 
udp   10.0.0.130:5353              
udp   100.64.0.20:5353             
udp   127.0.0.53:53                
udp   172.17.0.1:5353              
```

### Link to RK3588

```
--- 100.64.0.180 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3004ms
rtt min/avg/max/mdev = 9.552/17.017/31.990/9.079 ms
100.64.0.180 dev tailscale0 src 100.64.0.20 uid 1000 
```

## 7. Attached hardware

### Disks, cameras, USB, CAN, serial

```
--- block devices
NAME           SIZE TYPE FSTYPE   MOUNTPOINT                   MODEL
loop0            4K loop          /snap/bare/5                 
loop1         54.2M loop          /snap/core26/463             
loop2        186.8M loop          /snap/chromium/3527          
loop3           69M loop          /snap/core22/2438            
loop4           69M loop          /snap/core22/2956            
loop5         61.9M loop          /snap/core24/1644            
loop6         61.8M loop          /snap/core24/2125            
loop7        561.1M loop          /snap/gnome-46-2404/169      
loop8         47.9M loop squashfs /snap/cups/1237              
loop9          503M loop squashfs /snap/gnome-42-2204/245      
loop10       503.1M loop squashfs /snap/gnome-42-2204/264      
loop12       552.9M loop squashfs /snap/gnome-46-2404/154      
loop13        91.7M loop squashfs /snap/gtk-common-themes/1535 
loop14       174.6M loop squashfs /snap/mesa-2404/1166         
loop15       188.2M loop squashfs /snap/mesa-2404/1836         
loop16        44.3M loop squashfs /snap/snapd/24724            
loop17        44.2M loop squashfs /snap/snapd/25205            
loop18          16M loop                                       
loop19       184.3M loop squashfs /snap/chromium/3535          
loop20        48.2M loop squashfs /snap/cups/1261              
mmcblk0       59.2G disk                                       
|-mmcblk0p1   57.8G part ext4                                  
|-mmcblk0p2    128M part                                       
|-mmcblk0p3    768K part                                       
|-mmcblk0p4   31.6M part                                       
|-mmcblk0p5    128M part                                       
|-mmcblk0p6    768K part                                       
|-mmcblk0p7   31.6M part                                       
|-mmcblk0p8     80M part                                       
|-mmcblk0p9    512K part                                       
|-mmcblk0p10    64M part vfat                                  
|-mmcblk0p11    80M part                                       
|-mmcblk0p12   512K part                                       
|-mmcblk0p13    64M part                                       
|-mmcblk0p14   400M part                                       
`-mmcblk0p15 479.5M part                                       
mmcblk0boot0     4M disk                                       
mmcblk0boot1     4M disk                                       
zram0          2.6G disk          [SWAP]                       
zram1          2.6G disk          [SWAP]                       
zram2          2.6G disk          [SWAP]                       
zram3          2.6G disk          [SWAP]                       
zram4          2.6G disk          [SWAP]                       
zram5          2.6G disk          [SWAP]                       
zram6          2.6G disk          [SWAP]                       
zram7          2.6G disk          [SWAP]                       
zram8          2.6G disk          [SWAP]                       
zram9          2.6G disk          [SWAP]                       
zram10         2.6G disk          [SWAP]                       
zram11         2.6G disk          [SWAP]                       
nvme0n1      931.5G disk                                       WD_BLACK SN850X 1000GB
|-nvme0n1p1  930.1G part ext4     /                            
|-nvme0n1p2    128M part                                       
|-nvme0n1p3    768K part                                       
|-nvme0n1p4   31.6M part                                       
|-nvme0n1p5    128M part                                       
|-nvme0n1p6    768K part                                       
|-nvme0n1p7   31.6M part                                       
|-nvme0n1p8     80M part                                       
|-nvme0n1p9    512K part                                       
|-nvme0n1p10    64M part vfat     /boot/efi                    
|-nvme0n1p11    80M part                                       
|-nvme0n1p12   512K part                                       
|-nvme0n1p13    64M part                                       
|-nvme0n1p14   400M part                                       
`-nvme0n1p15 479.5M part                                       
--- video devices
Cannot open device /dev/video0, exiting.
NVIDIA Tegra Video Input Device (platform:tegra-camrtc-ca):
	/dev/media0

--- usb
Bus 002 Device 002: ID 0bda:0420 Realtek Semiconductor Corp. 4-Port USB 3.0 Hub
Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 001 Device 003: ID 0bda:5420 Realtek Semiconductor Corp. 4-Port USB 2.0 Hub
Bus 001 Device 002: ID 13d3:3549 IMC Networks Bluetooth Radio
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
--- can
can0             DOWN           <NOARP,ECHO> 
can1             DOWN           <NOARP,ECHO> 
--- serial
no ttyUSB/ttyACM
```

## 8. Storage

### Filesystems

```
Filesystem      Type  Size  Used Avail Use% Mounted on
/dev/nvme0n1p1  ext4  915G  587G  281G  68% /
/dev/nvme0n1p10 vfat   63M  110K   63M   1% /boot/efi
```

### Top-level directories

```
584G	/
562G	/home
15G	/usr
4.7G	/var
2.8G	/opt
80M	/boot
19M	/etc
16M	/tmp
56K	/snap
16K	/lost+found
12K	/media
4.0K	/srv
4.0K	/root
4.0K	/mnt
4.0K	/data
```

### Code and data directories (2 levels)

```
562G	/home/tonyho
562G	/home
543G	/home/tonyho/driveragent
7.8G	/home/tonyho/Downloads
5.5G	/home/tonyho/model
2.2G	/home/tonyho/.local
1.5G	/home/tonyho/.vscode-server
903M	/home/tonyho/.claude
508M	/home/tonyho/opencv
390M	/home/tonyho/.cache
124M	/home/tonyho/snap
105M	/home/tonyho/opencv_contrib
9.0M	/home/tonyho/.nx
2.8M	/home/tonyho/agx_audit_agx02_20261005_202230
1.7M	/home/tonyho/jetson_out
1004K	/home/tonyho/.config
332K	/home/tonyho/driveragent-agx
260K	/home/tonyho/.dotnet
36K	/home/tonyho/Pictures
28K	/home/tonyho/Desktop
24K	/home/tonyho/.ssh
16K	/home/tonyho/.dbus
12K	/home/tonyho/.fontconfig
8.0K	/home/tonyho/Documents
8.0K	/home/tonyho/.qt
8.0K	/home/tonyho/.nv
8.0K	/home/tonyho/.copilot
4.0K	/home/tonyho/Templates
4.0K	/home/tonyho/Public
4.0K	/home/tonyho/Music

4.0K	/root

2.8G	/opt
2.4G	/opt/nvidia
919M	/opt/nvidia/nsight-compute
818M	/opt/nvidia/nsight-systems
492M	/opt/nvidia/nsight-graphics-for-embeddedlinux
343M	/opt/ota_package
283M	/opt/ota_package/t23x
131M	/opt/nvidia/vpi3
67M	/opt/gst-1.24
52M	/opt/gst-1.24/lib
17M	/opt/nvidia/l4t-usb-device-mode
7.6M	/opt/gst-1.24/include
5.9M	/opt/gst-1.24/bin
1.1M	/opt/gst-1.24/var
744K	/opt/gst-1.24/share
640K	/opt/nvidia/pva-sdk-2.5
324K	/opt/nvidia/jetson-io
92K	/opt/gst-1.24/libexec
72K	/opt/nvidia/camera
52K	/opt/gst-1.24/etc
40K	/opt/nvidia/pva-allow-2
40K	/opt/nvidia/l4t-bootloader-config
12K	/opt/nvidia/l4t-rootfs-validation-config
4.0K	/opt/nvidia/debs
4.0K	/opt/nvidia/deb_repos
4.0K	/opt/containerd

4.0K	/srv

4.0K	/data

4.0K	/mnt

12K	/media
4.0K	/media/tonyho
4.0K	/media/nomachine

```

### Caches, logs, package stores

```
601M	/var/cache/apt
131M	/var/log
4.0K	/var/crash
4.0K	/var/lib/docker
3.4G	/var/lib/snapd
4.0K	/var/lib/containerd
16M	/tmp
52K	/var/tmp
390M	/home/tonyho/.cache
26M	/home/tonyho/.cache/pip
64K	/home/tonyho/.cache/torch
2.2G	/home/tonyho/.local
8.0K	/home/tonyho/.nv
7.8G	/home/tonyho/Downloads
264K	/home/tonyho/.local/share/Trash
124M	/home/tonyho/snap
Archived and active journals take up 88.0M in the file system.
--- snaps
Name               Version                         Rev    Tracking       Publisher       Notes
bare               1.0                             5      latest/stable  canonical**     base
chromium           153.0.8010.47                   3535   latest/stable  canonical**     -
core22             20260824                        2956   latest/stable  canonical**     base
core24             20260824                        2125   latest/stable  canonical**     base
core26             20260629                        463    latest/stable  canonical**     base
cups               2.4.19-6                        1261   latest/stable  openprinting**  -
gnome-42-2204      0+git.4982e7b-sdk0+git.69b626a  264    latest/stable  canonical**     -
gnome-46-2404      0+git.b31ceab-sdk0+git.f80dd8b  169    latest/stable  canonical**     -
gtk-common-themes  0.1-81-g442e511                 1535   latest/stable  canonical**     -
mesa-2404          25.2.8-snap288                  1836   latest/stable  canonical**     -
snapd              2.68.5                          24724  latest/stable  canonical**     snapd,held
```

### Model files by directory

```
745.6M       8 files  [trt,onnx]  /home/tonyho/model/sparsedrive/run
616.9M       2 files  [pth]  /home/tonyho/model/stage2/checkpoints/stage2_convnext_v2_lr4
476.8M       2 files  [pt,pth]  /home/tonyho/model/jetson_bundle/weights
426.7M       1 files  [pth]  /home/tonyho/model/sparsedrive/checkpoints
378.2M       1 files  [pth]  /home/tonyho/model/yolopx/YOLOPX/weights
365.8M       3 files  [pth,onnx]  /home/tonyho/model/system1
218.4M       2 files  [onnx]  /home/tonyho/model/jetson_bundle/onnx
120.8M       2 files  [engine]  /home/tonyho/model/jetson_bundle/engines
1.2M         1 files  [caffemodel]  /home/tonyho/opencv_contrib/modules/cnn_3dobj/testdata/cv
966.2K       2 files  [caffemodel]  /home/tonyho/opencv/build/downloads/wechat_qrcode
966.2K       2 files  [caffemodel]  /home/tonyho/opencv/.cache/wechat_qrcode
```

LAST-READ is the file access date. A model not read for months is probably not in use (not reliable if the disk is mounted with noatime).

### Model files (all)

```
SIZE      MODIFIED    LAST-READ   PATH
53.4M     2026-05-11  2026-09-25  /home/tonyho/model/jetson_bundle/engines/dtcp_v1_fp16.engine
67.4M     2026-05-11  2026-09-25  /home/tonyho/model/jetson_bundle/engines/yolopx_v2_fp16.engine
92.5M     2026-05-11  2026-09-25  /home/tonyho/model/jetson_bundle/onnx/dtcp_v1.onnx
125.8M    2026-05-11  2026-09-25  /home/tonyho/model/jetson_bundle/onnx/yolopx_v2.onnx
98.5M     2026-05-11  2026-09-25  /home/tonyho/model/jetson_bundle/weights/dtcp_nusc_route_v1.pt
378.4M    2026-05-11  2026-09-25  /home/tonyho/model/jetson_bundle/weights/yolopx_v2_epoch30.pth
426.7M    2026-04-02  2026-09-25  /home/tonyho/model/sparsedrive/checkpoints/best.pth
102.6M    2026-04-02  2026-09-25  /home/tonyho/model/sparsedrive/run/backbone_450x800.onnx
117.8M    2026-04-02  2026-09-25  /home/tonyho/model/sparsedrive/run/convnext_backbone_450x800.onnx
60.4M     2026-04-02  2026-09-25  /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16.trt
60.3M     2026-04-03  2026-09-25  /home/tonyho/model/sparsedrive/run/convnext_backbone_fp16_orin.trt
117.8M    2026-04-02  2026-09-25  /home/tonyho/model/sparsedrive/run/convnext_backbone_nchw_ln.onnx
118.0M    2026-04-03  2026-09-25  /home/tonyho/model/sparsedrive/run/convnext_backbone_nchw_orin.onnx
116.9M    2026-04-02  2026-09-25  /home/tonyho/model/sparsedrive/run/convnext_nchw_backbone.onnx
51.8M     2026-04-03  2026-09-25  /home/tonyho/model/sparsedrive/run/resnet_backbone_fp16_orin.trt
311.5M    2026-05-08  2026-09-25  /home/tonyho/model/stage2/checkpoints/stage2_convnext_v2_lr4/best.pth
305.4M    2026-05-08  2026-09-25  /home/tonyho/model/stage2/checkpoints/stage2_convnext_v2_lr4/latest.pth
1.3M      2026-05-03  2026-09-25  /home/tonyho/model/system1/backbone_nchw.onnx
240.6M    2026-05-03  2026-09-25  /home/tonyho/model/system1/system1_deploy.pth
123.8M    2026-05-03  2026-09-25  /home/tonyho/model/system1/system1_scorer.pth
378.2M    2025-05-29  2026-09-25  /home/tonyho/model/yolopx/YOLOPX/weights/epoch-195.pth
942.8K    2025-10-14  2025-10-14  /home/tonyho/opencv/.cache/wechat_qrcode/238e2b2d6f3c18d6c3a30de0c31e23cf-detect.caffemodel
23.4K     2025-10-14  2025-10-14  /home/tonyho/opencv/.cache/wechat_qrcode/cbfcd60361a73beb8c583eea7e8e6664-sr.caffemodel
942.8K    2025-10-14  2025-10-14  /home/tonyho/opencv/build/downloads/wechat_qrcode/detect.caffemodel
23.4K     2025-10-14  2025-10-14  /home/tonyho/opencv/build/downloads/wechat_qrcode/sr.caffemodel
1.2M      2024-05-30  2024-05-30  /home/tonyho/opencv_contrib/modules/cnn_3dobj/testdata/cv/3d_triplet_iter_30000.caffemodel
```

### Recordings and logs by directory (video, rosbag, rlog)

```
777.9M        1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_125900/front
72.1M         2 files  newest 2026-05-10  /home/tonyho/driveragent/ui/.claude/worktrees/cool-dirac-3995ab/replay/unused
72.1M         2 files  newest 2025-11-09  /home/tonyho/driveragent/replay/unused
39.2M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_180507/left
39.2M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_180507/right-back
39.2M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_180507/front
39.2M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_180507/right
37.0M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_130801/right-back
36.9M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_130801/right
36.9M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_130801/left
36.9M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_130801/front
36.7M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_182009/right
36.7M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_182009/left
36.7M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_141933/left
36.6M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_141933/right
36.6M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_144236/right
36.6M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_141933/right-back
36.6M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_144236/left
36.6M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_144236/front
36.6M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_144236/right-back
36.6M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_144739/left
36.6M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_144739/right
36.6M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_182009/front
36.5M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_182009/right-back
36.5M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_144739/front
36.5M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_144739/right-back
36.5M         1 files  newest 2025-11-07  /home/tonyho/driveragent/logger/video/8003-20251107_161908/left
36.5M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_141933/front
36.5M         1 files  newest 2025-11-07  /home/tonyho/driveragent/logger/video/8003-20251107_161908/front
36.4M         1 files  newest 2025-11-07  /home/tonyho/driveragent/logger/video/8003-20251107_161908/right-back
36.4M         1 files  newest 2025-11-07  /home/tonyho/driveragent/logger/video/8003-20251107_161908/right
36.4M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_150438/right
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_151740/right-back
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_151740/left
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_140532/front
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_150438/front
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_151740/front
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_151740/right
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_150438/left
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_140532/left
36.3M         1 files  newest 2025-11-09  /home/tonyho/driveragent/logger/video/8003-20251109_130723/right
36.3M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_142033/left
36.3M         1 files  newest 2025-11-09  /home/tonyho/driveragent/logger/video/8003-20251109_133426/left
36.2M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_103456/right
36.2M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_151442/right-back
36.2M         1 files  newest 2025-11-09  /home/tonyho/driveragent/logger/video/8003-20251109_140829/right
36.2M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_140532/right
36.2M         1 files  newest 2025-11-09  /home/tonyho/driveragent/logger/video/8003-20251109_125622/right
36.2M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_151442/left
36.2M         1 files  newest 2025-11-01  /home/tonyho/driveragent/logger/video/8003-20251101_104633/front
36.2M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_150438/right-back
36.2M         1 files  newest 2025-11-07  /home/tonyho/driveragent/logger/video/8003-20251107_165212/right
36.2M         1 files  newest 2025-11-09  /home/tonyho/driveragent/logger/video/8003-20251109_133426/front
36.2M         1 files  newest 2025-11-03  /home/tonyho/driveragent/logger/video/8003-20251103_134529/right
36.2M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_100349/left
36.2M         1 files  newest 2025-11-09  /home/tonyho/driveragent/logger/video/8003-20251109_130723/left
36.2M         1 files  newest 2025-11-09  /home/tonyho/driveragent/logger/video/8003-20251109_140829/front
36.2M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_151442/right
36.2M         1 files  newest 2025-10-31  /home/tonyho/driveragent/logger/video/8003-20251031_151442/front
36.2M         1 files  newest 2025-11-09  /home/tonyho/driveragent/logger/video/8003-20251109_140829/left
... (11598 more lines - full output: raw/Recordings_and_logs_by_directory__video__rosbag__rlog_.txt)
```

### Files larger than 300 MB

```
SIZE      MODIFIED    LAST-READ   PATH
2.4G      2025-10-13  2026-10-05  /home/tonyho/Downloads/maplibre-native/.git/objects/pack/pack-af02cd40b9a23620bfdbc3de7b1e199d2638be76.pack
1.8G      2025-10-13  2026-09-25  /home/tonyho/driveragent/location/united-kingdom-latest.osm.pbf
1.6G      2025-10-13  2026-09-25  /home/tonyho/driveragent/dev/uk.mbtiles
1.1G      2025-10-27  2026-09-25  /home/tonyho/driveragent/location/gb.mbtiles
893.0M    2026-05-10  2026-09-25  /home/tonyho/driveragent/logger/video/8003-20251031_125900.tar.bz2
777.9M    2025-10-31  2026-09-25  /home/tonyho/driveragent/logger/video/8003-20251031_125900/front/cam0_20251031_125900.mp4
437.3M    2024-08-14  2025-10-13  /usr/local/cuda-12.6/targets/aarch64-linux/lib/libcublasLt_static.a
426.7M    2026-04-02  2026-09-25  /home/tonyho/model/sparsedrive/checkpoints/best.pth
402.2M    2025-10-13  2026-10-05  /home/tonyho/Downloads/raylib/.git/objects/pack/pack-edbf87b49066fbacaa89fa4def2d42a63f34e659.pack
385.3M    2026-05-04  2026-09-25  /home/tonyho/driveragent/logger/video/8003-20260101_124700.tar.bz2
378.4M    2026-05-11  2026-09-25  /home/tonyho/model/jetson_bundle/weights/yolopx_v2_epoch30.pth
378.2M    2025-05-29  2026-09-25  /home/tonyho/model/yolopx/YOLOPX/weights/epoch-195.pth
338.9M    2024-08-14  2025-10-13  /usr/local/cuda-12.6/targets/aarch64-linux/lib/libcusparse_static.a
321.5M    2024-08-14  2026-10-05  /usr/local/cuda-12.6/targets/aarch64-linux/lib/libcublasLt.so.12.6.1.4
311.5M    2026-05-08  2026-09-25  /home/tonyho/model/stage2/checkpoints/stage2_convnext_v2_lr4/best.pth
305.4M    2026-05-08  2026-09-25  /home/tonyho/model/stage2/checkpoints/stage2_convnext_v2_lr4/latest.pth
304.2M    2024-08-14  2026-09-25  /usr/local/cuda-12.6/targets/aarch64-linux/lib/libcusparse.so.12.5.3.3
```

### Paths named after known projects (driveragent, driverguard, system1, map...)

```
f /home/tonyho/.cache/ccache/0/1/4249rai65l4s7q8flp29kvuosml0tp0M
f /home/tonyho/.cache/ccache/0/3/1era0hbg4018evpii2jo8klbmn1j5osM
f /home/tonyho/.cache/ccache/1/f/73c4gosm5ch0rmikhd6i3n4hmfd9o42R
f /home/tonyho/.cache/ccache/3/0/0erosm3p4ntn5db1fkdj7chl1l2mao0R
f /home/tonyho/.cache/ccache/3/9/3fh3osmeej3g3mafaf469jrmpnipicuR
f /home/tonyho/.cache/ccache/6/5/7f6gv6rh9ri46q0s6q7501sjvkchmosM
f /home/tonyho/.cache/ccache/7/a/b3pj2s3q03osm455e70a4kpj9j00cseM
f /home/tonyho/.cache/ccache/8/6/212r4eupbaetq5cl20nhjkhnkosmtqmM
f /home/tonyho/.cache/ccache/9/b/03un8bld1m4gjfa91osm17ihlgguvveR
f /home/tonyho/.cache/ccache/b/4/abaj66atnq3grjlkbkcpdt1l26v7iosM
f /home/tonyho/.cache/ccache/b/a/15vjhcfhdj5js9qb4et1jou436vg0osM
f /home/tonyho/.cache/ccache/d/c/6dbdui55umcalvva4652drckc3i2bosM
f /home/tonyho/.cache/ccache/d/f/f10v9dqjdha61cnrc7475isnjsgiosmR
f /home/tonyho/.cache/ccache/e/e/ef695395rk2i1kqj4ao6lff4d1d28osM
f /home/tonyho/.cache/ccache/f/e/a4p26tbses3d7ocnis8ra6ks49usoosM
d /home/tonyho/.cache/claude-cli-nodejs/-home-tonyho-driveragent
d /home/tonyho/.cache/claude-cli-nodejs/-home-tonyho-driveragent-location
d /home/tonyho/.cache/claude-cli-nodejs/-home-tonyho-driveragent-ui--claude-worktrees-cool-dirac-3995ab
d /home/tonyho/.cache/claude-cli-nodejs/-home-tonyho-model-system1
d /home/tonyho/.claude/projects/-home-tonyho-driveragent
d /home/tonyho/.claude/projects/-home-tonyho-driveragent-ui--claude-worktrees-cool-dirac-3995ab
f /home/tonyho/.claude/projects/-home-tonyho-model/memory/driveragent_ipc.md
f /home/tonyho/Downloads/cmake-3.31.7/Bootstrap.cmk/cmBinUtilsMacOSMachOGetRuntimeDependenciesTool.o
f /home/tonyho/Downloads/cmake-3.31.7/Bootstrap.cmk/cmBinUtilsMacOSMachOLinker.o
f /home/tonyho/Downloads/cmake-3.31.7/Bootstrap.cmk/cmBinUtilsMacOSMachOOToolGetRuntimeDependenciesTool.o
f /home/tonyho/Downloads/cmake-3.31.7/Source/cmBinUtilsMacOSMachOGetRuntimeDependenciesTool.cxx
f /home/tonyho/Downloads/cmake-3.31.7/Source/cmBinUtilsMacOSMachOGetRuntimeDependenciesTool.h
f /home/tonyho/Downloads/cmake-3.31.7/Source/cmBinUtilsMacOSMachOLinker.cxx
f /home/tonyho/Downloads/cmake-3.31.7/Source/cmBinUtilsMacOSMachOLinker.h
f /home/tonyho/Downloads/cmake-3.31.7/Source/cmBinUtilsMacOSMachOOToolGetRuntimeDependenciesTool.cxx
f /home/tonyho/Downloads/cmake-3.31.7/Source/cmBinUtilsMacOSMachOOToolGetRuntimeDependenciesTool.h
d /home/tonyho/Downloads/cmake-3.31.7/Tests/QtAutogen/MocOsMacros
f /home/tonyho/agx_audit_agx02_20261005_202230/raw/Paths_named_after_known_projects__driveragent__driverguard__system1__map..._.txt
d /home/tonyho/driveragent
d /home/tonyho/driveragent-agx
d /home/tonyho/driveragent/.claude/worktrees/quizzical-elgamal-709408/driveragent
f /home/tonyho/driveragent/.claude/worktrees/quizzical-elgamal-709408/install_valhalla.sh
d /home/tonyho/driveragent/.claude/worktrees/vigorous-wing-ea79d5/driveragent
f /home/tonyho/driveragent/.claude/worktrees/vigorous-wing-ea79d5/install_valhalla.sh
f /home/tonyho/driveragent/install_valhalla.sh
f /home/tonyho/driveragent/location/setup_valhalla.sh
f /home/tonyho/driveragent/location/united-kingdom-latest.osm.pbf
f /home/tonyho/driveragent/location/valhalla.json
d /home/tonyho/driveragent/location/valhalla_tiles
d /home/tonyho/model/driverguard
d /home/tonyho/model/system1
f /home/tonyho/model/system1/__pycache__/run_system1.cpython-310.pyc
f /home/tonyho/model/system1/__pycache__/run_system1.cpython-312.pyc
f /home/tonyho/model/system1/__pycache__/system1_model.cpython-310.pyc
f /home/tonyho/model/system1/run_system1.py
f /home/tonyho/model/system1/system1_deploy.pth
f /home/tonyho/model/system1/system1_model.py
f /home/tonyho/model/system1/system1_scorer.pth
f /home/tonyho/model/watch_system1.py
f /home/tonyho/start-driveragent.sh
--- directories with 'map' / 'tile' / 'nav' in the name
/home/tonyho/Downloads/maplibre-native
/home/tonyho/driveragent/location/valhalla_tiles
```

## 9. Git repositories

NOT-SAFE-TO-DELETE = uncommitted changes, unpushed commits or stashes exist. NO-REMOTE = the only copy is on this machine.

### Repositories

```
--- /home/tonyho/Downloads/gstreamer   [NOT-SAFE-TO-DELETE]
    remote  : https://gitlab.freedesktop.org/gstreamer/gstreamer.git
    branch  : HEAD   last commit: 2025-01-29 88e3121647 Release 1.24.12
    pending : uncommitted=2  unpushed-commits=0  stashes=0   size: 1.4G
--- /home/tonyho/Downloads/gstreamer/subprojects/dv   [NOT-SAFE-TO-DELETE]
    remote  : https://gitlab.freedesktop.org/gstreamer/meson-ports/libdv.git
    branch  : meson   last commit: 2023-01-17 4a28ebb quant: Fix buffer overflow detected by ASAN
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 3.6M
--- /home/tonyho/Downloads/gstreamer/subprojects/gl-headers   [NOT-SAFE-TO-DELETE]
    remote  : https://gitlab.freedesktop.org/gstreamer/meson-ports/gl-headers.git
    branch  : HEAD   last commit: 2019-03-23 5c8c7c0 meson: create empty abyss, wglext etc. subdirs in the build directory
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 1.3M
--- /home/tonyho/Downloads/gstreamer/subprojects/gperf   [NOT-SAFE-TO-DELETE]
    remote  : https://gitlab.freedesktop.org/tpm/gperf.git
    branch  : meson   last commit: 2023-04-13 c24359b Merge branch 'meson' into 'meson'
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 4.9M
--- /home/tonyho/Downloads/gstreamer/subprojects/libavtp   [NOT-SAFE-TO-DELETE]
    remote  : https://github.com/Avnu/libavtp.git
    branch  : HEAD   last commit: 2022-02-09 3599a5b build: Update version to 0.2.0
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 724K
--- /home/tonyho/Downloads/gstreamer/subprojects/libmicrodns   [NOT-SAFE-TO-DELETE]
    remote  : https://github.com/videolabs/libmicrodns.git
    branch  : HEAD   last commit: 2022-05-27 2489a7a Meson: Simplify pkgconfig generator
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 880K
--- /home/tonyho/Downloads/gstreamer/subprojects/libnice   [NOT-SAFE-TO-DELETE]
    remote  : https://gitlab.freedesktop.org/libnice/libnice.git
    branch  : HEAD   last commit: 2024-03-04 ae3eb16f version 0.1.22
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 6.6M
--- /home/tonyho/Downloads/gstreamer/subprojects/opus   [NOT-SAFE-TO-DELETE]
    remote  : https://gitlab.xiph.org/xiph/opus.git
    branch  : HEAD   last commit: 2021-07-07 6b6035ae Remove an unused parameter
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 27M
--- /home/tonyho/Downloads/gstreamer/subprojects/orc   [NOT-SAFE-TO-DELETE]
    remote  : https://gitlab.freedesktop.org/gstreamer/orc.git
    branch  : HEAD   last commit: 2024-02-27 f071d3a Release 0.4.38
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 5.8M
--- /home/tonyho/Downloads/gstreamer/subprojects/vpx   [NOT-SAFE-TO-DELETE]
    remote  : https://gitlab.freedesktop.org/gstreamer/meson-ports/libvpx.git
    branch  : meson-1.13   last commit: 2024-07-10 1fdc1f7de meson: Fix typo in the tiny_ssim executable clause
    pending : uncommitted=2  unpushed-commits=0  stashes=0   size: 114M
--- /home/tonyho/Downloads/jetson-jtop-patch   [NOT-SAFE-TO-DELETE]
    remote  : https://github.com/jetsonhacks/jetson-jtop-patch.git
    branch  : main   last commit: 2025-08-03 05e1456 Update README.md
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 212K
--- /home/tonyho/Downloads/libnice   [NOT-SAFE-TO-DELETE]
    remote  : https://github.com/libnice/libnice.git
    branch  : HEAD   last commit: 2018-12-27 e25c3e51 Version 0.1.15
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 28M
--- /home/tonyho/Downloads/maplibre-native   [clean]
    remote  : https://github.com/maplibre/maplibre-native.git
    branch  : main   last commit: 2025-10-13 8f50a549275 chore(deps): update bazel (#3850)
    pending : uncommitted=0  unpushed-commits=0  stashes=0   size: 4.9G
--- /home/tonyho/Downloads/raylib   [clean]
    remote  : https://github.com/raysan5/raylib.git
    branch  : master   last commit: 2025-10-09 9f831428 Update core_render_texture.c
    pending : uncommitted=0  unpushed-commits=0  stashes=0   size: 566M
--- /home/tonyho/driveragent-agx   [NO-REMOTE]
    remote  : none
    branch  : HEAD   last commit: 
    pending : uncommitted=1  unpushed-commits=0  stashes=0   size: 3.0M
--- /home/tonyho/driveragent   [NOT-SAFE-TO-DELETE]
    remote  : git@github.com:osmosishk/DriverAgent.git
    branch  : main   last commit: 2026-05-22 bf78af3 [demo] sync 2026-05-22 17:01
    pending : uncommitted=0  unpushed-commits=2  stashes=0   size: 543G
--- /home/tonyho/model/yolopx/YOLOPX   [NOT-SAFE-TO-DELETE]
    remote  : https://github.com/jiaoZ7688/YOLOPX.git
    branch  : main   last commit: 2025-03-28 35627f6 Update demo.py
    pending : uncommitted=67  unpushed-commits=0  stashes=0   size: 807M
```
