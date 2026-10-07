#!/usr/bin/env bash
# Install driveragent-agx on this Jetson for the user that runs this script (no sudo). docs/INSTALL_AGX.md.
#
# Usage: ops/install.sh [--instance agx] [--store ~/agx-models] [--dash-port 8700] [--zmq-base 5560]
#                       [--video-base 6000] [--mode rk|sim] [--no-enable] [--no-start] [--user-site]
#                       [--torch-index URL] [--takeover] [--yes]
#        ops/install.sh --print-system-units [--instance agx] [--user-site]
#
#   --instance NAME    unit names NAME-infer and NAME-dashboard, record data/install-NAME.json (default agx)
#   --store DIR        model store (default ~/agx-models). Made when missing (with _state and _incoming).
#   --dash-port N      dashboard TCP port (default 8700)
#   --zmq-base N       ZMQ TCP ports N..N+4: results, status, internal, admin, rkinfo (default 5560)
#   --video-base N     FrameLink UDP ports N..N+5, camera c = N+c (default 6000)
#   --mode rk|sim      camera source in a NEW config/sources.yaml (default rk)
#   --no-enable        do not enable the units (no start at boot / at login)
#   --no-start         do not start the units now
#   --user-site        do not set PYTHONNOUSERSITE=1 (the units and pip then also see ~/.local)
#   --torch-index URL  pip index for torch (default https://pypi.jetson-ai-lab.io/jp6/cu126)
#   --takeover         stop TRANSIENT units with the same names (tools/svc.sh) and start the installed units
#   --yes              no question (for --takeover)
#   --print-system-units  write system unit files to data/system-units/ and print them with the sudo commands
#                      for the owner. Installs nothing else.
#
# The repository is the folder of this script (any folder, any user). install.sh runs ops/preflight.sh first
# (same ports). A second run never replaces config/*.yaml, .env, data/* or the store: it prints "KEPT <path>".
# install.sh never activates a model. It never prints a password: it prints the PATH of the password file.
# Undo: ops/uninstall.sh --instance NAME [--purge].
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/lib/common.sh"

INSTANCE=$DEF_INSTANCE; STORE_ARG="$DEF_STORE"; DASH_PORT=$DEF_DASH_PORT; ZMQ_BASE=$DEF_ZMQ_BASE
VIDEO_BASE=$DEF_VIDEO_BASE; MODE=rk; ENABLE=1; START=1; USER_SITE=0; TORCH_INDEX="$DEF_TORCH_INDEX"
TAKEOVER=0; YES=0; PRINT_SYSTEM=0
usage() { sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
RERUN="ops/install.sh"
for a in "$@"; do case "$a" in --takeover|--yes) ;; *) RERUN="$RERUN $(printf '%q' "$a")" ;; esac; done
RERUN="$RERUN --takeover"
while [ $# -gt 0 ]; do
  case "$1" in
    --instance) INSTANCE="${2:-}"; shift 2 ;;
    --store) STORE_ARG="${2:-}"; shift 2 ;;
    --dash-port) DASH_PORT="${2:-}"; shift 2 ;;
    --zmq-base) ZMQ_BASE="${2:-}"; shift 2 ;;
    --video-base) VIDEO_BASE="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --no-enable) ENABLE=0; shift ;;
    --no-start) START=0; shift ;;
    --user-site) USER_SITE=1; shift ;;
    --torch-index) TORCH_INDEX="${2:-}"; shift 2 ;;
    --takeover) TAKEOVER=1; shift ;;
    --yes) YES=1; shift ;;
    --print-system-units) PRINT_SYSTEM=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
done

[ "$(id -u)" -ne 0 ] || die "do not run install.sh as root or with sudo. Run it as the user that runs the units."
check_instance_name "$INSTANCE"
check_port --dash-port "$DASH_PORT"; check_port --zmq-base "$ZMQ_BASE"; check_port --video-base "$VIDEO_BASE"
case "$MODE" in rk|sim) ;; *) die "--mode '$MODE': use rk or sim." ;; esac
STORE="$(expand_path "$STORE_ARG")"
case "$STORE" in /*) ;; *) STORE="$PWD/$STORE" ;; esac
[ "$STORE" != / ] && [ "$STORE" != "$HOME" ] && [ "$STORE" != "$REPO" ] || die "--store $STORE: give a folder of its own."
for d in infer dashboard controller config/templates requirements ops/units; do
  [ -d "$REPO/$d" ] || die "$REPO/$d is missing: run install.sh from a complete clone of driveragent-agx."
done

VENV="$REPO/.venv"; PY="$VENV/bin/python"
RECORD="$REPO/data/install-$INSTANCE.json"
UDIR="$(user_unit_dir)"
UNITS=("$INSTANCE-dashboard.service" "$INSTANCE-infer.service")
ME="$(id -un)"; MYGROUP="$(id -gn)"
URS=(); [ "$USER_SITE" = 1 ] && URS=(--user-site)

render() {  # template out
  "$SYS_PY" "$OPS_LIB/render_unit.py" "$1" "$2" --instance "$INSTANCE" --repo "$REPO" --python "$PY" \
    --user "$ME" --group "$MYGROUP" ${URS[@]+"${URS[@]}"}
}

# Unit state in the systemd user and system managers: none | installed | transient | system | other:<file>
unit_mode() {
  local u="$1" fp t
  if [ "$(sprop "$u" LoadState)" = loaded ] && [ -n "$(sprop "$u" FragmentPath)" ]; then echo system; return; fi
  t="$(uprop "$u" Transient)"; fp="$(uprop "$u" FragmentPath)"
  if [ "$t" = yes ]; then echo transient; return; fi
  if [ "$(uprop "$u" LoadState)" = loaded ] && [ -n "$fp" ]; then
    if [ "$fp" = "$UDIR/$u" ]; then echo installed; else echo "other:$fp"; fi
    return
  fi
  if [ -e "$UDIR/$u" ]; then echo installed; return; fi
  echo none
}

# ------------------------------------------------------------------------------------------------------------
if [ "$PRINT_SYSTEM" = 1 ]; then
  out="$REPO/data/system-units"
  mkdir -p "$out"
  for t in infer dashboard; do
    render "$OPS_DIR/units/system/agx-$t.service.in" "$out/$INSTANCE-$t.service"
    if [ -f "$RECORD" ]; then "$SYS_PY" "$OPS_LIB/record.py" add-made "$RECORD" file "$out/$INSTANCE-$t.service"; fi
  done
  for t in infer dashboard; do
    say "===== $out/$INSTANCE-$t.service"
    cat "$out/$INSTANCE-$t.service"
  done
  [ -x "$PY" ] || warn "$PY does not exist yet: run ops/install.sh --no-enable --no-start first (venv and config)."
  say ""
  say "Owner commands for SYSTEM units (they start at boot without linger). install.sh does not run them."
  say "1. Stop and disable the user units of this instance (no sudo):"
  for u in "${UNITS[@]}"; do
    case "$(unit_mode "$u")" in
      transient) say "   systemctl --user stop $u        # transient unit (tools/svc.sh)" ;;
      installed) say "   systemctl --user disable --now $u" ;;
      system) say "   ($u is a system unit already)" ;;
      *) say "   ($u: no user unit)" ;;
    esac
  done
  say "2. Install, enable and start the system units:"
  say "   sudo install -m 0644 '$out/$INSTANCE-infer.service' /etc/systemd/system/$INSTANCE-infer.service"
  say "   sudo install -m 0644 '$out/$INSTANCE-dashboard.service' /etc/systemd/system/$INSTANCE-dashboard.service"
  say "   sudo systemctl daemon-reload"
  say "   sudo systemctl enable --now $INSTANCE-dashboard.service $INSTANCE-infer.service"
  say "3. Check: ops/doctor.sh --instance $INSTANCE --system-units"
  say "Undo: sudo systemctl disable --now $INSTANCE-infer.service $INSTANCE-dashboard.service"
  say "      sudo rm /etc/systemd/system/$INSTANCE-infer.service /etc/systemd/system/$INSTANCE-dashboard.service"
  say "      sudo systemctl daemon-reload"
  say "Do not run the user units and the system units at the same time: they use the same ports."
  exit 0
fi

# ------------------------------------------------------------------------------------------------------------
T_ALL=$(date +%s)
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
: > "$WORK/made"; : > "$WORK/kept"
KEPT_LINES=(); OWNER=(); NOTES=()
made() { printf '%s\t%s\n' "$1" "$2" >> "$WORK/made"; say "MADE  $2"; }
kept() { printf '%s\t%s\n' "$1" "$2" >> "$WORK/kept"; KEPT_LINES+=("KEPT  $2"); say "KEPT  $2"; }
T_STEP=0
step() {
  [ "$T_STEP" = 0 ] || say "      ($(( $(date +%s) - T_STEP )) s)"
  T_STEP=$(date +%s); say ""; say "== $*"
}
was_made() {  # path: true when an earlier run of install made it (record)
  [ -f "$RECORD" ] && "$SYS_PY" "$OPS_LIB/record.py" list "$RECORD" made | cut -f2- | grep -qxF -- "$1"
}

say "driveragent-agx install: instance $INSTANCE, repo $REPO, user $ME, host $(hostname)"
say "store $STORE; dashboard $DASH_PORT; ZMQ $ZMQ_BASE-$((ZMQ_BASE + 4)); UDP $VIDEO_BASE-$((VIDEO_BASE + 5)); mode $MODE"
[ -f "$RECORD" ] && say "record $RECORD exists: this is a second run (existing files are kept)."

# 1. Preflight -----------------------------------------------------------------------------------------------
step "1/8 preflight (ops/preflight.sh)"
if ! "$OPS_DIR/preflight.sh" --dash-port "$DASH_PORT" --zmq-base "$ZMQ_BASE" --video-base "$VIDEO_BASE" \
     --store "$STORE" --instance "$INSTANCE"; then
  die "preflight failed: nothing was changed. Correct the FAIL items, or give other ports (--dash-port, --zmq-base, --video-base)."
fi

# Units with the same names that install must not touch.
declare -A UMODE
for u in "${UNITS[@]}"; do UMODE[$u]="$(unit_mode "$u")"; done
TAKE=()
for u in "${UNITS[@]}"; do
  case "${UMODE[$u]}" in
    transient)
      if [ "$TAKEOVER" = 1 ]; then TAKE+=("$u"); fi ;;
  esac
done
if [ "${#TAKE[@]}" -gt 0 ] && [ "$YES" != 1 ]; then
  if [ -t 0 ]; then
    say ""
    say "--takeover stops the running transient units: ${TAKE[*]}. The services are down until the installed units start."
    read -r -p "Type yes to continue: " ans
    [ "$ans" = yes ] || die "takeover cancelled: nothing was changed."
  else
    die "--takeover stops running services: give --yes as well (no terminal for the question). Nothing was changed."
  fi
fi

# 2. venv ----------------------------------------------------------------------------------------------------
step "2/8 Python venv ($VENV)"
if [ -x "$PY" ]; then
  kept venv "$VENV"
else
  [ ! -e "$VENV" ] || die "$VENV exists but has no bin/python: remove it by hand, then run install.sh again."
  "$SYS_PY" -m venv --system-site-packages "$VENV"
  made venv "$VENV"
fi

# 3. pip ------------------------------------------------------------------------------------------------------
step "3/8 pip install (requirements/agx-torch.txt from $TORCH_INDEX, then requirements/agx-venv.txt)"
# The same Python environment as the units: PYTHONNOUSERSITE=1 (unless --user-site). No pip settings of the user.
PIPENV=(env -u PIP_USER -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL -u PYTHONPATH)
if [ "$USER_SITE" = 1 ]; then PIPENV+=(-u PYTHONNOUSERSITE); else PIPENV+=(PYTHONNOUSERSITE=1); fi
PIPENV+=(PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1)
"${PIPENV[@]}" "$PY" -m pip install --index-url "$TORCH_INDEX" -r "$REPO/requirements/agx-torch.txt" \
  || die "pip install of requirements/agx-torch.txt failed (network? index $TORCH_INDEX). Run install.sh again after the fix."
"${PIPENV[@]}" "$PY" -m pip install -r "$REPO/requirements/agx-venv.txt" \
  || die "pip install of requirements/agx-venv.txt failed. Run install.sh again after the fix."
say "import check (the environment of the units):"
(cd "$REPO" && "${PIPENV[@]}" "$PY" - <<'EOF') || die "the import check failed: the units cannot start. See the error above."
import importlib, sys
mods = ["torch", "tensorrt", "cv2", "gi", "zmq", "capnp", "numpy", "onnx", "fastapi", "uvicorn", "starlette",
        "pydantic", "yaml", "psutil", "crc32c", "paho.mqtt.client", "httpx", "pytest"]
bad = []
for m in mods:
    try:
        x = importlib.import_module(m)
        v = getattr(x, "__version__", "") or getattr(x, "VERSION", "")
        print(f"  {m:18s} {v!s:12s} {getattr(x, '__file__', '') or ''}")
    except Exception as e:  # noqa: BLE001
        bad.append(f"{m}: {type(e).__name__}: {e}")
import torch
print(f"  torch CUDA build: {torch.version.cuda} (built with CUDA: {torch.backends.cuda.is_built()})")
if not torch.backends.cuda.is_built():
    bad.append("torch has no CUDA (a PyPI wheel?): install torch from the Jetson index")
for b in bad:
    print("  IMPORT ERROR " + b)
sys.exit(1 if bad else 0)
EOF

# 4. config -------------------------------------------------------------------------------------------------
step "4/8 config files (config/templates -> config)"
CFG="$REPO/config"
qstr() { "$SYS_PY" -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }
NEW_CFG=" "
for t in "$CFG"/templates/*.yaml; do
  f="$CFG/$(basename "$t")"
  if [ -e "$f" ]; then
    kept config "$f"
  else
    cp "$t" "$f"; chmod 644 "$f"
    made config "$f"; NEW_CFG="$NEW_CFG$(basename "$t") "
  fi
done
cfgset() { "$SYS_PY" "$OPS_LIB/cfgset.py" "$@" | sed 's/^/      /'; }
QSTORE="$(qstr "$STORE")"
if [[ "$NEW_CFG" == *" infer.yaml "* ]]; then
  cfgset "$CFG/infer.yaml" model_store "$QSTORE" ports.results "$ZMQ_BASE" ports.status "$((ZMQ_BASE + 1))" \
    ports.internal "$((ZMQ_BASE + 2))" ports.admin "$((ZMQ_BASE + 3))" ports.rkinfo "$((ZMQ_BASE + 4))"
fi
if [[ "$NEW_CFG" == *" dashboard.yaml "* ]]; then
  cfgset "$CFG/dashboard.yaml" port "$DASH_PORT" model_store "$QSTORE" unit_prefix "$INSTANCE"
  # The private IPv4 subnets of this unit (not docker 172.16.0.0/12, not 169.254.0.0/16, not loopback).
  private_addrs > "$WORK/addrs" || true
  while read -r ifc cidr; do
    net="$("$SYS_PY" - "$cidr" "$CFG/dashboard.yaml" <<'EOF'
import ipaddress, sys, yaml
net = ipaddress.ip_interface(sys.argv[1]).network
allow = (yaml.safe_load(open(sys.argv[2])) or {}).get("allow_cidrs") or []
for a in allow:
    try:
        if net.subnet_of(ipaddress.ip_network(str(a), strict=False)):
            sys.exit(0)        # already allowed
    except (ValueError, TypeError):
        pass
print(net)
EOF
)"
    if [ -n "$net" ]; then cfgset --append "$CFG/dashboard.yaml" allow_cidrs "$net" "$ifc subnet (ops/install.sh)"; fi
  done < "$WORK/addrs"
fi
if [[ "$NEW_CFG" == *" sources.yaml "* ]]; then
  cfgset "$CFG/sources.yaml" mode "$MODE" base_port "$VIDEO_BASE"
fi
if [[ "$NEW_CFG" == *" sim.yaml "* ]]; then
  cfgset "$CFG/sim.yaml" base_port "$VIDEO_BASE"
fi
# Kept files: say when a value differs from the options of this run (the file stays as it is).
cfg_note() {  # file key wanted
  local have
  [ -f "$CFG/$1" ] || return 0
  have="$(cfg_get "$CFG/$1" "$2" 2>/dev/null || echo '?')"
  if [ "$have" != "$3" ] && [ "$have" != "\"$3\"" ]; then
    NOTES+=("config/$1 $2 is $have, not $3 (the file is kept; change it by hand when necessary)")
  fi
}
for f in infer.yaml dashboard.yaml sources.yaml sim.yaml; do
  [[ "$NEW_CFG" == *" $f "* ]] && continue
  case "$f" in
    infer.yaml) cfg_note "$f" ports.results "$ZMQ_BASE" ;;
    dashboard.yaml) cfg_note "$f" port "$DASH_PORT" ;;
    sources.yaml) cfg_note "$f" base_port "$VIDEO_BASE"; cfg_note "$f" mode "$MODE" ;;
    sim.yaml) cfg_note "$f" base_port "$VIDEO_BASE" ;;
  esac
done

# 5. .env and data -------------------------------------------------------------------------------------------
step "5/8 password file (.env) and data folders"
if [ -e "$REPO/.env" ]; then
  kept env "$REPO/.env"
else
  [ -f "$REPO/.env.example" ] || die "$REPO/.env.example is missing."
  ( umask 077; "$SYS_PY" - "$REPO/.env.example" "$REPO/.env" <<'EOF'
import os, secrets, sys
src, dst = sys.argv[1:]
with open(src, encoding="utf-8") as f:
    lines = f.readlines()
pw = secrets.token_urlsafe(24)
out = ["AGX_DASH_PASSWORD=" + pw + "\n" if ln.startswith("AGX_DASH_PASSWORD=") else ln for ln in lines]
fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.writelines(out)
EOF
  )
  made env "$REPO/.env"
fi
for d in data logs engines; do
  if [ -d "$REPO/$d" ]; then
    kept dir "$REPO/$d"
  else
    ( umask 077; mkdir "$REPO/$d" ); made dir "$REPO/$d"
  fi
done
[ "$(stat -c %a "$REPO/data")" = 700 ] || NOTES+=("data/ has mode $(stat -c %a "$REPO/data"), not 700 (kept)")

# 6. model store ---------------------------------------------------------------------------------------------
step "6/8 model store ($STORE)"
if [ -d "$STORE" ]; then
  kept store "$STORE"
  for s in _state _incoming; do
    if [ ! -d "$STORE/$s" ]; then mkdir "$STORE/$s"; made store-sub "$STORE/$s"; fi
  done
else
  mkdir -p "$STORE/_state" "$STORE/_incoming"
  made store "$STORE"
fi
[ -f "$STORE/_testframes/front_1280x720.jpg" ] || NOTES+=("the store has no test frame _testframes/front_1280x720.jpg: the inference check of a model needs one (docs/INSTALL_AGX.md, section 9)")

# 7. units ---------------------------------------------------------------------------------------------------
step "7/8 systemd user units ($UDIR)"
if [ ! -d "$UDIR" ]; then
  top="$UDIR"; while [ ! -d "$(dirname "$top")" ]; do top="$(dirname "$top")"; done
  mkdir -p "$UDIR"
  made unit-dir "$top"      # uninstall removes it only when it is empty (rmdir)
fi
declare -A USTATE
INSTALL_UNITS=()
for u in "${UNITS[@]}"; do
  t="${u#"$INSTANCE"-}"; t="${t%.service}"
  case "${UMODE[$u]}" in
    transient)
      if [ "$TAKEOVER" != 1 ]; then
        USTATE[$u]="skipped: a transient unit $u is loaded (tools/svc.sh); not touched"
        OWNER+=("$u is a running TRANSIENT unit: install did not touch it. To change to the installed unit: $RERUN (it stops $u and starts the installed unit; the service is down for some seconds)")
        say "SKIP  $u: a transient unit with this name is loaded; not touched"
        continue
      fi ;;
    system)
      USTATE[$u]="skipped: a system unit $u exists"
      say "SKIP  $u: a SYSTEM unit with this name exists (/etc/systemd/system); no user unit is installed"
      continue ;;
    other:*)
      USTATE[$u]="skipped: ${UMODE[$u]}"
      say "SKIP  $u: a unit file that install did not make is loaded (${UMODE[$u]#other:})"
      continue ;;
  esac
  render "$OPS_DIR/units/agx-$t.service.in" "$WORK/$u"
  dest="$UDIR/$u"
  if [ -e "$dest" ] && cmp -s "$dest" "$WORK/$u"; then
    kept unit-file "$dest"; USTATE[$u]="installed (unchanged)"
  elif [ -e "$dest" ] && ! was_made "$dest"; then
    USTATE[$u]="skipped: $dest exists and install did not make it"
    say "SKIP  $dest exists and the record does not say that install made it: not replaced"
    continue
  else
    [ -e "$dest" ] && say "UPDATE $dest (made by an earlier run)"
    install -m 0644 "$WORK/$u" "$dest"
    made unit-file "$dest"; USTATE[$u]="installed (new file)"
  fi
  INSTALL_UNITS+=("$u")
done

if [ "${#TAKE[@]}" -gt 0 ]; then
  say "takeover: stop the transient units ${TAKE[*]}"
  for u in "${TAKE[@]}"; do systemctl --user stop "$u" || true; systemctl --user reset-failed "$u" 2>/dev/null || true; done
  for _i in $(seq 1 40); do
    left=""; for u in "${TAKE[@]}"; do if [ "$(uprop "$u" Transient)" = yes ]; then left="$left $u"; fi; done
    [ -z "$left" ] && break; sleep 0.25
  done
  [ -z "$left" ] || die "the transient units$left are still loaded. The unit files are written; start them later with: systemctl --user start ${TAKE[*]}"
fi
systemctl --user daemon-reload

for u in "${INSTALL_UNITS[@]}"; do
  if [ "$ENABLE" = 1 ]; then
    systemctl --user enable "$u" 2>&1 | sed 's/^/      /'
    USTATE[$u]="${USTATE[$u]}, enabled"
  else
    USTATE[$u]="${USTATE[$u]}, not enabled (--no-enable)"
  fi
done
if [ "$START" = 1 ]; then
  started=0
  for u in "${INSTALL_UNITS[@]}"; do      # dashboard first, then infer
    if systemctl --user is-active --quiet "$u"; then
      if [[ "${USTATE[$u]}" == *"new file"* ]]; then
        systemctl --user restart "$u"; say "RESTART $u (new unit file)"; started=1
      else
        say "ACTIVE $u (already running)"
      fi
    else
      systemctl --user reset-failed "$u" 2>/dev/null || true
      systemctl --user start "$u"; say "START $u"; started=1
    fi
  done
  if [ "$started" = 1 ]; then sleep 3; fi
  for u in "${INSTALL_UNITS[@]}"; do
    st="$(systemctl --user is-active "$u" 2>/dev/null || true)"
    USTATE[$u]="${USTATE[$u]}, $st"
    [ "$st" = active ] || NOTES+=("$u is $st: see journalctl --user -u $u -n 50")
  done
else
  for u in "${INSTALL_UNITS[@]}"; do USTATE[$u]="${USTATE[$u]}, not started (--no-start)"; done
  [ "${#TAKE[@]}" -gt 0 ] && NOTES+=("--takeover with --no-start: the services are stopped now. Start them: systemctl --user start ${UNITS[*]}")
fi

# 8. record and summary --------------------------------------------------------------------------------------
step "8/8 install record ($RECORD)"
for u in "${UNITS[@]}"; do printf '%s\t%s\t%s\n' "$u" "$UDIR/$u" "${USTATE[$u]:-}"; done > "$WORK/units"
units_json="$("$SYS_PY" -c '
import json, sys
rows = [ln.rstrip("\n").split("\t", 2) for ln in open(sys.argv[1], encoding="utf-8") if ln.strip()]
print(json.dumps({u: {"file": f, "state": st} for u, f, st in rows}))' "$WORK/units")"
opts_json="$("$SYS_PY" -c 'import json,sys; k=sys.argv[1::2]; v=sys.argv[2::2]; print(json.dumps(dict(zip(k,v))))' \
  instance "$INSTANCE" store "$STORE" dash_port "$DASH_PORT" zmq_base "$ZMQ_BASE" video_base "$VIDEO_BASE" \
  mode "$MODE" enable "$ENABLE" start "$START" user_site "$USER_SITE" torch_index "$TORCH_INDEX" takeover "$TAKEOVER")"
"$SYS_PY" "$OPS_LIB/record.py" update "$RECORD" --instance "$INSTANCE" --repo "$REPO" --store "$STORE" \
  --made "$WORK/made" --kept "$WORK/kept" --units "$units_json" --options "$opts_json"
say "written (mode 600, no secret)"
say "      ($(( $(date +%s) - T_STEP )) s)"

# Dashboard URLs: the port that the dashboard uses (data/dashboard_port), else the configured port.
port="$(cfg_get "$CFG/dashboard.yaml" port 2>/dev/null || echo "$DASH_PORT")"
if [ "$START" = 1 ] && [[ " ${INSTALL_UNITS[*]-} " == *" $INSTANCE-dashboard.service "* ]]; then
  pf="$REPO/$(cfg_get "$CFG/dashboard.yaml" port_file | tr -d '"')"
  for _i in $(seq 1 20); do if [ -s "$pf" ]; then break; fi; sleep 0.5; done
  if [ -s "$pf" ]; then port="$(tr -dc 0-9 < "$pf")"; fi
fi
scheme=http; [ "$(cfg_get "$CFG/dashboard.yaml" tls_certfile)" != null ] && scheme=https

say ""
say "==================== install summary (instance $INSTANCE, $(( $(date +%s) - T_ALL )) s) ===================="
say "Units:"
for u in "${UNITS[@]}"; do say "  $u: ${USTATE[$u]:-?}"; done
say "Dashboard URL(s) (port $port):"
say "  $scheme://127.0.0.1:$port/"
while read -r ifc cidr; do say "  $scheme://${cidr%/*}:$port/   ($ifc)"; done < <(private_addrs)
say "Dashboard user and password: in $REPO/.env (AGX_DASH_USER, AGX_DASH_PASSWORD; mode 600). Read it on this unit."
say "Model store: $STORE (no model is active; deploy, build and activate: docs/DEPLOY_MODEL.md)"
if [ "${#KEPT_LINES[@]}" -gt 0 ]; then
  say "Kept (not changed by this run):"
  for k in "${KEPT_LINES[@]}"; do say "  $k"; done
fi
if [ "$MODE" = sim ] && [[ "$NEW_CFG" == *" sources.yaml "* ]]; then
  NOTES+=("mode sim: no unit runs the simulator. Without it all cameras show NO SIGNAL. Start it by hand: cd $REPO && PYTHONPATH=. $PY -m tools.rk_sim --config config/sim.yaml")
fi
linger="$(loginctl show-user "$ME" -p Linger --value 2>/dev/null || true)"
if [ "$linger" != yes ]; then
  OWNER+=("start at boot: the owner runs: sudo loginctl enable-linger $ME   (without it the user units stop when the last session of $ME ends and do not start at boot). Or system units: ops/install.sh --print-system-units --instance $INSTANCE")
fi
if [ "${#NOTES[@]}" -gt 0 ]; then say "Notes:"; for n in "${NOTES[@]}"; do say "  - $n"; done; fi
if [ "${#OWNER[@]}" -gt 0 ]; then say "Owner steps (need sudo or a decision):"; for o in "${OWNER[@]}"; do say "  - $o"; done; fi
say "Next: ops/doctor.sh --instance $INSTANCE --before-pairing, then pair a board (docs/CONNECT_AGX.md)."
