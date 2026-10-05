#!/usr/bin/env bash
# Install the two system units. NEEDS SUDO. Owner approval item (the night agent had no sudo).
# This script installs and STARTS the units. It does NOT enable them at boot.
# To enable at boot later (separate approval): sudo systemctl enable agx-infer.service agx-dashboard.service
set -euo pipefail
cd "$(dirname "$0")"
P=/home/tonyho/driveragent-agx
# 1. Stop the transient user units of the night run, so that ports 5560/5561/5562/5563/8700 are free.
systemctl --user stop agx-infer.service agx-dashboard.service agx-sim.service 2>/dev/null || true
# 2. Install and start the system units.
sudo install -m 0644 agx-infer.service /etc/systemd/system/agx-infer.service
sudo install -m 0644 agx-dashboard.service /etc/systemd/system/agx-dashboard.service
mkdir -p "$P/data" "$P/logs" "$P/engines"
sudo systemctl daemon-reload
sudo systemctl start agx-dashboard.service agx-infer.service
systemctl --no-pager status agx-dashboard.service agx-infer.service | head -30
echo "Installed and started. Not enabled at boot."
# Undo: sudo systemctl stop agx-infer agx-dashboard && sudo rm /etc/systemd/system/agx-{infer,dashboard}.service && sudo systemctl daemon-reload
