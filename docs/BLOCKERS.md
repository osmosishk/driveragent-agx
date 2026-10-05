# Blockers (agx02 night run)

Each item: what is blocked, why, what the owner must do.

## B1. No sudo
- Blocked: `sudo bash agx_audit.sh` (T0), install of `/etc/systemd/system/agx-*.service` (T7), `systemctl stop` of old system services.
- Why: `sudo -n true` gives "sudo: a password is required". No person is present to give the password.
- Effect: the audit ran as user `tonyho` without root. Docker data is complete (user is in group `docker`). Other users' files and some service data are partial.
- Owner action: run `sudo bash ~/agx_audit.sh` again if a full audit is necessary. Install the unit files (see T7 section).
