# Shared shell functions of the ops/ scripts (preflight, install, doctor, uninstall, export_model).
# Source this file. It does not change the system.
# shellcheck shell=bash
# The variables below are for the scripts that source this file. A "~" in a text is expanded by expand_path.
# shellcheck disable=SC2034,SC2088

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$OPS_DIR/.." && pwd)"
OPS_LIB="$OPS_DIR/lib"
SYS_PY=/usr/bin/python3          # the JetPack / apt Python (yaml, tensorrt, cv2, gi)

# Defaults (the Install contract). Ports: dashboard TCP, ZMQ TCP base .. base+4, FrameLink UDP base .. base+5.
DEF_INSTANCE=agx
DEF_STORE="~/agx-models"
DEF_DASH_PORT=8700
DEF_ZMQ_BASE=5560
DEF_VIDEO_BASE=6000
DEF_TORCH_INDEX="https://pypi.jetson-ai-lab.io/jp6/cu126"
SUPPORTED_TRT="10.3.0"           # space-separated list of TensorRT versions that the engines and builds are tested with

# systemctl --user needs XDG_RUNTIME_DIR (an ssh command without a login shell can have none).
if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -d "/run/user/$(id -u)" ]; then
  XDG_RUNTIME_DIR="/run/user/$(id -u)"
  export XDG_RUNTIME_DIR
fi

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# PASS / FAIL / INFO lines. Each FAIL of a necessary item sets CHECK_FAILED=1.
CHECK_FAILED=0
pass_item() { printf 'PASS  %-24s %s\n' "$1" "$2"; }
fail_item() { printf 'FAIL  %-24s %s\n' "$1" "$2"; CHECK_FAILED=1; }
info_item() { printf 'INFO  %-24s %s\n' "$1" "$2"; }
warn_item() { printf 'WARN  %-24s %s\n' "$1" "$2"; }

# Expand a leading ~ (the options take "~/agx-models" as text).
expand_path() {
  local p="$1"
  case "$p" in
    "~") p="$HOME" ;;
    "~/"*) p="$HOME/${p#\~/}" ;;
  esac
  printf '%s\n' "$p"
}

check_instance_name() {
  [[ "$1" =~ ^[a-z][a-z0-9]{0,15}$ ]] || die "instance name '$1': use 1-16 characters a-z and 0-9 (start with a letter)."
}

check_port() {
  [[ "$2" =~ ^[0-9]+$ ]] && [ "$2" -ge 1024 ] && [ "$2" -le 65000 ] || die "$1 '$2': use a number 1024..65000."
}

# The cgroup unit (for example agx-infer.service) of a PID, or empty.
unit_of_pid() {
  local cg
  cg="$(sed -n 's|^0::||p' "/proc/$1/cgroup" 2>/dev/null | head -1)"
  [ -n "$cg" ] || return 0
  basename "$cg" | grep -E '\.service$' || true
}

# Lines "<pid> <unit>" of the processes that listen on a port. $1 = tcp | udp, $2 = port.
# ss shows the PID only for the processes of this user (no root). Other holders give "? ?".
port_holders() {
  local proto="$1" port="$2" opt line pids pid
  if [ "$proto" = tcp ]; then opt=-Hltnp; else opt=-Hlunp; fi
  ss "$opt" "( sport = :$port )" 2>/dev/null | while IFS= read -r line; do
    pids="$(printf '%s\n' "$line" | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u)"
    if [ -z "$pids" ]; then echo "? ?"; continue; fi
    for pid in $pids; do echo "$pid $(unit_of_pid "$pid")"; done
  done | sort -u
}

# Unit properties of the systemd USER manager (empty when the unit is not known).
uprop() { systemctl --user show -p "$2" --value "$1" 2>/dev/null || true; }
# Unit properties of the systemd SYSTEM manager (read-only, no sudo).
sprop() { systemctl show -p "$2" --value "$1" 2>/dev/null || true; }

user_unit_dir() { printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"; }

# Private IPv4 addresses with prefix of this unit: "<iface> <addr>/<len>" lines.
# Skips loopback, link-local 169.254.0.0/16 and docker / bridge networks in 172.16.0.0/12.
private_addrs() {
  ip -4 -o addr show 2>/dev/null | awk '{print $2, $4}' | while read -r ifc cidr; do
    case "$ifc" in lo|docker*|br-*|veth*) continue ;; esac
    "$SYS_PY" - "$cidr" <<'EOF' && echo "$ifc $cidr"
import ipaddress, sys
i = ipaddress.ip_interface(sys.argv[1])
a = i.ip
bad = (a.is_loopback or a.is_link_local or a in ipaddress.ip_network("172.16.0.0/12")
       or not (a.is_private or a in ipaddress.ip_network("100.64.0.0/10")))
sys.exit(1 if bad else 0)
EOF
  done
}

# Read one value of a YAML file by a dotted path (JSON output; "null" when missing). $1 file, $2 path.
cfg_get() { "$SYS_PY" "$OPS_LIB/cfgset.py" --get "$1" "$2"; }
