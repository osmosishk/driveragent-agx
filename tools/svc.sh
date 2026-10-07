#!/usr/bin/env bash
# Start / stop / show the driveragent-agx services as TRANSIENT systemd USER units.
#
# A transient user unit writes no unit file on disk and does not start at boot (the installed
# units come from ops/install.sh). Unit name: <prefix>-<name>. The prefix is the environment variable
# AGX_UNIT_PREFIX (default "agx": agx-dashboard, agx-infer, agx-sim; the same as config/dashboard.yaml
# unit_prefix).
#
# Usage: [AGX_UNIT_PREFIX=agx] tools/svc.sh start|stop|restart|status|logs  dashboard|infer|sim [extra args]
set -u
P="$(cd "$(dirname "$0")/.." && pwd)"
PY="$P/.venv/bin/python"
PREFIX="${AGX_UNIT_PREFIX:-agx}"
cmd="${1:-status}"; name="${2:-}"; shift 2 2>/dev/null || true

unit_of() { echo "$PREFIX-$1"; }
exec_of() {
  case "$1" in
    dashboard) echo "$PY -m dashboard.main --config $P/config/dashboard.yaml" ;;
    infer)     echo "$PY -m infer.main --config $P/config/infer.yaml" ;;
    sim)       echo "$PY -m tools.rk_sim --config $P/config/sim.yaml" ;;
    *) echo "unknown service: $1" >&2; return 1 ;;
  esac
}

case "$cmd" in
  start)
    [ -n "$name" ] || { echo "name?"; exit 2; }
    u="$(unit_of "$name")"; e="$(exec_of "$name")" || exit 2
    if systemctl --user is-active --quiet "$u"; then echo "$u already active"; exit 0; fi
    # A failed unit stays loaded (no --collect), so that its exit status stays visible in
    # "tools/svc.sh status". reset-failed removes the old failed unit before the new start.
    systemctl --user reset-failed "$u" 2>/dev/null || true
    # PWD: pycapnp reads PWD. Without it, capnp writes a warning in the log.
    # shellcheck disable=SC2086
    systemd-run --user --unit="$u" \
      --property=Restart=on-failure --property=RestartSec=3 \
      --property=StartLimitIntervalSec=120 --property=StartLimitBurst=10 \
      --working-directory="$P" --setenv=PWD="$P" \
      --setenv=PYTHONUNBUFFERED=1 --setenv=PYTHONPATH="$P" \
      --description="driveragent-agx $name (transient user unit, night run)" \
      $e "$@"
    ;;
  stop)    systemctl --user stop "$(unit_of "$name")" ;;
  restart) "$0" stop "$name"; sleep 1; "$0" start "$name" "$@" ;;
  status)
    if [ -n "$name" ]; then systemctl --user status "$(unit_of "$name")" --no-pager -n 0
    else systemctl --user list-units "$PREFIX-*" --all --no-pager --no-legend; fi ;;
  logs)    journalctl --user-unit "$(unit_of "$name")" --no-pager -n "${1:-100}" -o short-iso ;;
  *) echo "usage: $0 start|stop|restart|status|logs dashboard|infer|sim"; exit 2 ;;
esac
