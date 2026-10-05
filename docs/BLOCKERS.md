# Blockers (agx02 night run)

Each item: what is blocked, why, what the owner must do.

## B1. No sudo
- Blocked: `sudo bash agx_audit.sh` (T0), install of `/etc/systemd/system/agx-*.service` (T7), `systemctl stop` of old system services.
- Why: `sudo -n true` gives "sudo: a password is required". No person is present to give the password.
- Effect: the audit ran as user `tonyho` without root. Docker data is complete (user is in group `docker`). Other users' files and some service data are partial.
- Owner action: run `sudo bash ~/agx_audit.sh` again if a full audit is necessary. Install the unit files (see T7 section).

## B2. System unit files not installed (T7.3)
- Blocked: install of `agx-infer.service` and `agx-dashboard.service` into `/etc/systemd/system`. Needs sudo (B1).
- Done instead: the unit files are ready in `systemd/`. The services run tonight as TRANSIENT systemd USER units (`tools/svc.sh start dashboard|infer|sim`). They write no unit file on disk and they do not start at boot.
- Risk: transient user units stop when the user manager of `tonyho` stops (Linger=no: when the last session of `tonyho` ends) and at reboot.
- Owner action: `sudo bash ~/driveragent-agx/systemd/install_units.sh` (stops the transient units, installs, starts; does NOT enable at boot). Enable at boot is a separate approval: `sudo systemctl enable agx-infer.service agx-dashboard.service`.

## B3. No test with the real RK3588 cameras (T7.1)
- Blocked: the RK3588 (DA01, rk-v0.4.0) does not send FrameLink yet (TX "deferred", `rk/docs/STATUS.md:291`). Its config sends to `agx_host = 10.42.0.1` (Link C), which is not configured. Over tailscale the board answers only on ports 22, 111, 4000, 5555. Rule R9 allows no change on the board.
- Done instead: `docs/RK_TASKS.md` (exact work for the RK agent, with tests), `tools/framelink_ref/` (C++ sender reference + golden vectors), simulator tests.

## B4. Link C and socket buffers (network configuration, rule R5)
- Blocked: `10.42.0.1/30` on `eno1`, MTU 9000, and `net.core.rmem_max` (now 212992 B; the RK design uses 8388608 B). These are network/system configuration changes and need root.
- Effect tonight: FrameLink NV12 at full RK rate works on loopback with <= 0.11 % frame loss (T3). A larger socket buffer gives more margin.

## B5. Clock offset AGX <-> RK3588 not measurable
- Blocked: the board gives no time service that a read-only probe can use (no HTTP, no NTP answer; `clockdiff` not installed; installing it needs root).
- Effect: cross-board latency cannot be measured. The envelope flag `time_uncertain` is set on every AGX message.

## B6. No git remote (rule R10)
- The new repository has local commits only. Owner action: add a remote and push.
