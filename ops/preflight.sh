#!/usr/bin/env bash
# Check that this Jetson can run driveragent-agx. The script changes nothing.
#
# Usage: ops/preflight.sh [--dash-port 8700] [--zmq-base 5560] [--video-base 6000] [--store ~/agx-models]
#                         [--instance NAME]
#   --instance NAME  ports that the units NAME-infer / NAME-dashboard hold count as free (a second install run,
#                    or the transient units that ops/install.sh --takeover replaces).
#
# Output: one line per item: PASS, FAIL (a necessary item), WARN (an optional item) or INFO, with the reason.
# Exit 0 only when all necessary items pass. Exit 1 when one or more necessary items fail. Exit 2: wrong options.
set -uo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/lib/common.sh"

DASH_PORT=$DEF_DASH_PORT; ZMQ_BASE=$DEF_ZMQ_BASE; VIDEO_BASE=$DEF_VIDEO_BASE; STORE="$DEF_STORE"; INSTANCE=""
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dash-port) DASH_PORT="${2:-}"; shift 2 ;;
    --zmq-base) ZMQ_BASE="${2:-}"; shift 2 ;;
    --video-base) VIDEO_BASE="${2:-}"; shift 2 ;;
    --store) STORE="${2:-}"; shift 2 ;;
    --instance) INSTANCE="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
done
check_port --dash-port "$DASH_PORT"; check_port --zmq-base "$ZMQ_BASE"; check_port --video-base "$VIDEO_BASE"
[ -z "$INSTANCE" ] || check_instance_name "$INSTANCE"
STORE="$(expand_path "$STORE")"

say "driveragent-agx preflight: host $(hostname), user $(id -un), repo $REPO"
say "ports: dashboard TCP $DASH_PORT, ZMQ TCP $ZMQ_BASE-$((ZMQ_BASE + 4)), FrameLink UDP $VIDEO_BASE-$((VIDEO_BASE + 5))"
say "store: $STORE"
say ""

# 1. Jetson model
model="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)"
case "$model" in
  *"AGX Orin"*) pass_item "jetson model" "$model" ;;
  *Orin*) warn_item "jetson model" "$model: not an AGX Orin. The engines and the GPU memory limits are for AGX Orin." ;;
  "") fail_item "jetson model" "/proc/device-tree/model is not readable: this is not a Jetson" ;;
  *) fail_item "jetson model" "$model: not a Jetson Orin" ;;
esac

# 2. L4T / JetPack
l4t="$(head -1 /etc/nv_tegra_release 2>/dev/null || true)"
rel="$(printf '%s' "$l4t" | sed -n 's/^# R\([0-9]*\) (release), REVISION: \([0-9.]*\).*/\1.\2/p')"
jp="$(dpkg-query -W -f='${Version}' nvidia-jetpack 2>/dev/null || true)"
if [ -z "$rel" ]; then
  fail_item "L4T / JetPack" "/etc/nv_tegra_release is missing: JetPack 6 is necessary"
elif [ "${rel%%.*}" = 36 ]; then
  pass_item "L4T / JetPack" "L4T R$rel${jp:+, nvidia-jetpack $jp} (JetPack 6)"
else
  fail_item "L4T / JetPack" "L4T R$rel: JetPack 6 (L4T R36) is necessary"
fi

# 3. TensorRT (Python bindings of the system Python: the venv uses them)
trt="$("$SYS_PY" -c 'import tensorrt; print(tensorrt.__version__)' 2>/dev/null || true)"
ok=""
for v in $SUPPORTED_TRT; do case "$trt" in "$v"|"$v".*) ok=1 ;; esac; done
if [ -z "$trt" ]; then
  fail_item "TensorRT" "python3 cannot import tensorrt (JetPack package python3-libnvinfer)"
elif [ -n "$ok" ]; then
  pass_item "TensorRT" "$trt (supported: $SUPPORTED_TRT)"
else
  fail_item "TensorRT" "$trt is not in the supported list ($SUPPORTED_TRT)"
fi

# 4. Python 3.10
pyv="$("$SYS_PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
case "$pyv" in
  3.10.*) pass_item "python 3.10" "$SYS_PY $pyv" ;;
  "") fail_item "python 3.10" "$SYS_PY is missing" ;;
  *) fail_item "python 3.10" "$SYS_PY is $pyv: Python 3.10 is necessary (the TensorRT bindings of JetPack 6)" ;;
esac

# 5. python3-venv (ensurepip)
if "$SYS_PY" -c 'import venv, ensurepip' 2>/dev/null; then
  pass_item "python3-venv" "venv and ensurepip are installed"
else
  fail_item "python3-venv" "ensurepip is missing: the owner installs it with: sudo apt install python3-venv"
fi

# 6. System Python modules from JetPack / apt (the venv uses them; never from pip)
missing=""; found=""
for m in cv2 gi yaml psutil; do
  v="$("$SYS_PY" -c "import $m as x; print(getattr(x, '__version__', 'ok'))" 2>/dev/null || true)"
  if [ -n "$v" ]; then found="$found $m $v,"; else missing="$missing $m"; fi
done
if [ -z "$missing" ]; then
  found="${found# }"; pass_item "system python modules" "${found%,}"
else
  fail_item "system python modules" "missing:$missing (apt: python3-opencv from JetPack, python3-gi, python3-yaml, python3-psutil)"
fi
if "$SYS_PY" -c 'import PIL' 2>/dev/null; then
  info_item "python3-pil" "present (only the tests use it)"
else
  warn_item "python3-pil" "missing: only tests/test_dashboard_v2.py needs it (sudo apt install python3-pil)"
fi

# 7. nvv4l2decoder (GStreamer H.265 decoder of JetPack)
if ! command -v gst-inspect-1.0 >/dev/null 2>&1; then
  fail_item "nvv4l2decoder" "gst-inspect-1.0 is missing (GStreamer of JetPack)"
elif gst-inspect-1.0 nvv4l2decoder >/dev/null 2>&1; then
  pass_item "nvv4l2decoder" "GStreamer element present"
else
  fail_item "nvv4l2decoder" "GStreamer element nvv4l2decoder is missing (JetPack multimedia: nvidia-l4t-gstreamer)"
fi

# 8. Free disk at the repo and at the store (>= 20 GiB). A store that does not exist yet: its nearest parent.
need=$((20 * 1024 * 1024 * 1024))
disk_check() {
  local label="$1" p="$2" avail
  while [ ! -e "$p" ] && [ "$p" != / ]; do p="$(dirname "$p")"; done
  avail="$(df -B1 --output=avail "$p" 2>/dev/null | tail -1 | tr -d ' ')"
  if [ -z "$avail" ]; then fail_item "$label" "df cannot read $p"; return; fi
  if [ "$avail" -ge "$need" ]; then
    pass_item "$label" "$((avail / 1073741824)) GiB free at $p (>= 20 GiB)"
  else
    fail_item "$label" "$((avail / 1073741824)) GiB free at $p (20 GiB necessary: venv about 3 GiB, engines, models)"
  fi
}
disk_check "disk (repo)" "$REPO"
disk_check "disk (store)" "$STORE"

# 9. Free GPU memory (Jetson: CPU and GPU share the RAM, thus MemAvailable)
mem_kb="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
if [ "${mem_kb:-0}" -ge $((6 * 1024 * 1024)) ]; then
  pass_item "free GPU memory" "MemAvailable $((mem_kb / 1048576)) GiB (>= 6 GiB; shared CPU/GPU memory)"
else
  fail_item "free GPU memory" "MemAvailable $((${mem_kb:-0} / 1048576)) GiB: 6 GiB is necessary (stop other GPU programs)"
fi

# 10. Ports. A port that the units of --instance hold counts as free for this instance.
own_units=""
[ -n "$INSTANCE" ] && own_units="$INSTANCE-infer.service $INSTANCE-dashboard.service"
port_check() {
  local proto="$1" port="$2" holders others="" own="" pid unit
  holders="$(port_holders "$proto" "$port")"
  [ -n "$holders" ] || return 0
  while read -r pid unit; do
    if [ -n "$own_units" ] && [ -n "$unit" ] && [[ " $own_units " == *" $unit "* ]]; then
      own="$own $unit"
    elif [ "$pid" = "?" ]; then
      others="$others another user"
    else
      others="$others pid $pid${unit:+ ($unit)}"
    fi
  done <<< "$holders"
  if [ -n "$others" ]; then
    echo "B $proto/$port:$others"
  else
    # shellcheck disable=SC2086  # split the unit names on purpose
    own="$(printf '%s\n' $own | sort -u | paste -sd, -)"
    echo "O $proto/$port ($own)"
  fi
}
port_report() {
  local label="$1"; shift
  local busy="" ownp="" line
  for spec in "$@"; do
    line="$(port_check "${spec%%/*}" "${spec##*/}")"
    case "$line" in
      B*) busy="$busy; ${line#B }" ;;
      O*) ownp="$ownp; ${line#O }" ;;
    esac
  done
  if [ -n "$busy" ]; then
    fail_item "$label" "in use:${busy#;}"
  elif [ -n "$ownp" ]; then
    pass_item "$label" "free for instance $INSTANCE (held by its own units:${ownp#;})"
  else
    pass_item "$label" "free"
  fi
}
port_report "port dashboard" "tcp/$DASH_PORT"
zspecs=(); for i in 0 1 2 3 4; do zspecs+=("tcp/$((ZMQ_BASE + i))"); done
port_report "ports ZMQ $ZMQ_BASE-$((ZMQ_BASE + 4))" "${zspecs[@]}"
vspecs=(); for i in 0 1 2 3 4 5; do vspecs+=("udp/$((VIDEO_BASE + i))"); done
port_report "ports UDP $VIDEO_BASE-$((VIDEO_BASE + 5))" "${vspecs[@]}"

# 11. System time (year >= 2026 necessary; NTP sync optional)
year="$(date +%Y)"
if [ "$year" -ge 2026 ]; then
  pass_item "system time" "$(date '+%Y-%m-%d %H:%M:%S %Z')"
else
  fail_item "system time" "$(date '+%Y-%m-%d %H:%M:%S %Z'): the clock is wrong (pairing, TLS and logs need the real time)"
fi
ntp="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
if [ "$ntp" = yes ]; then info_item "NTP" "synchronized"; else warn_item "NTP" "not synchronized (${ntp:-unknown}): optional"; fi

# 12. systemd --user
if systemctl --user show-environment >/dev/null 2>&1; then
  pass_item "systemd --user" "the user manager of $(id -un) answers"
else
  fail_item "systemd --user" "systemctl --user does not answer (log in once with ssh, or the owner runs: sudo loginctl enable-linger $(id -un))"
fi
linger="$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || true)"
if [ "$linger" = yes ]; then
  info_item "linger" "yes: the user units start at boot"
else
  info_item "linger" "${linger:-unknown}: user units stop at logout and do not start at boot (owner step: sudo loginctl enable-linger $(id -un))"
fi

say ""
if [ "$CHECK_FAILED" = 0 ]; then
  say "PREFLIGHT PASSED: all necessary items pass."
  exit 0
fi
say "PREFLIGHT FAILED: one or more necessary items fail (see the FAIL lines)."
exit 1
