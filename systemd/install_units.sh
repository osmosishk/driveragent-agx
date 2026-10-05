#!/usr/bin/env bash
# Install and start the two system units agx-infer and agx-dashboard. Owner approval item.
#
# Run as tonyho, NOT with sudo:   bash ~/driveragent-agx/systemd/install_units.sh
# The script asks for the sudo password. It uses sudo only for: install of the unit files,
# daemon-reload and start.
#
# This script installs and STARTS the units. It does NOT enable them at boot.
# To enable at boot later (separate approval): sudo systemctl enable agx-infer.service agx-dashboard.service
#
# Undo: sudo systemctl stop agx-infer agx-dashboard
#       sudo rm /etc/systemd/system/agx-{infer,dashboard}.service && sudo systemctl daemon-reload
set -euo pipefail

if [ "$EUID" -eq 0 ]; then
  echo "ERROR: do not run this script as root or with sudo." >&2
  echo "Run it as tonyho: bash ~/driveragent-agx/systemd/install_units.sh" >&2
  echo "(The script must stop the transient USER units of tonyho. It asks for the sudo password.)" >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
P=/home/tonyho/driveragent-agx
UNITS="agx-infer.service agx-dashboard.service"
TCP_PORTS="5560 5561 5562 5563 8700"

for f in agx-infer.service agx-dashboard.service; do
  [ -f "$HERE/$f" ] || { echo "ERROR: $HERE/$f is missing." >&2; exit 1; }
done

# 0. The system units must not run already (a second start gives port conflicts).
for u in $UNITS; do
  if systemctl is-active --quiet "$u"; then
    echo "ERROR: the system unit $u is already active. Nothing was changed." >&2
    echo "To install the unit files again: sudo systemctl stop agx-infer agx-dashboard, then run this script again." >&2
    exit 1
  fi
done

# 1. Make the data directories as tonyho (the units run as User=tonyho and write there).
mkdir -p "$P/data" "$P/logs" "$P/engines"

# 2. Stop the transient USER units of the night run (as tonyho, no sudo).
#    agx-sim is not stopped: it only sends UDP and binds no port of the units.
for u in agx-infer.service agx-dashboard.service; do
  if systemctl --user is-active --quiet "$u"; then
    echo "Stop transient user unit $u"
    systemctl --user stop "$u"
  fi
  systemctl --user reset-failed "$u" 2>/dev/null || true
done

# 3. The TCP ports 5560-5563 and 8700 must be free before the start.
port_busy() {
  ss -Hltn "( sport = :$1 )" 2>/dev/null | grep -q .
}
busy=""
for i in $(seq 1 20); do
  busy=""
  for p in $TCP_PORTS; do
    if port_busy "$p"; then busy="$busy $p"; fi
  done
  [ -z "$busy" ] && break
  sleep 0.5
done
if [ -n "$busy" ]; then
  echo "ERROR: these TCP ports are still in use:$busy" >&2
  echo "The system units were NOT installed. Find the process: ss -ltnp | grep -E ':(5560|5561|5562|5563|8700) '" >&2
  echo "To start the transient user units again: tools/svc.sh start infer; tools/svc.sh start dashboard" >&2
  exit 1
fi
echo "TCP ports$(printf ' %s' $TCP_PORTS) are free."

# 4. Install, daemon-reload and start (sudo only here).
echo "sudo is needed for the next steps. Enter the sudo password if asked."
sudo install -m 0644 "$HERE/agx-infer.service" /etc/systemd/system/agx-infer.service
sudo install -m 0644 "$HERE/agx-dashboard.service" /etc/systemd/system/agx-dashboard.service
sudo systemctl daemon-reload
sudo systemctl start agx-dashboard.service agx-infer.service
systemctl --no-pager status agx-dashboard.service agx-infer.service | head -30 || true
echo
echo "Installed and started. NOT enabled at boot."

# 5. Simulator note. There is NO system unit for the simulator (tools.rk_sim).
mode="$(sed -n 's/^mode:[[:space:]]*\([a-z]*\).*/\1/p' "$P/config/sources.yaml" | head -1)"
echo
echo "NOTE: no system unit exists for the simulator agx-sim."
echo "config/sources.yaml mode: ${mode:-unknown}"
if [ "$mode" = "sim" ]; then
  echo "In mode sim, agx-infer gets frames only from the simulator. Without it, all cameras show NO SIGNAL."
  echo "Do one of these:"
  echo "  - start the simulator as a transient user unit: tools/svc.sh start sim"
  echo "    (it stops when the last session of tonyho ends, and at reboot), or"
  echo "  - set 'mode: rk' in config/sources.yaml when the RK3588 sends FrameLink,"
  echo "    then: sudo systemctl restart agx-infer.service"
  if systemctl --user is-active --quiet agx-sim.service; then
    echo "agx-sim is active now (transient user unit). The input data is SIMULATED."
  else
    echo "agx-sim is NOT active now."
  fi
fi
