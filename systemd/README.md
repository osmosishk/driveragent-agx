# systemd units

The unit files and the install scripts are in `ops/` now. See `docs/INSTALL_AGX.md`.

- `ops/units/agx-infer.service.in`, `ops/units/agx-dashboard.service.in`: systemd USER units. `ops/install.sh` makes
  `~/.config/systemd/user/<instance>-{infer,dashboard}.service` from them (no sudo).
- `ops/units/system/*.service.in`: SYSTEM units for an owner who prefers them. `ops/install.sh --print-system-units`
  writes the files to `data/system-units/` and prints them with the exact sudo commands. It does not install them.

The old files of this folder (`agx-infer.service`, `agx-dashboard.service`, `install_units.sh`, with fixed paths for
`/home/tonyho/driveragent-agx`) are removed. The git history has them.
