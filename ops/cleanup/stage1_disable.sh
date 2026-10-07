#!/usr/bin/env bash
# Stage 1 of the AGX02 cleanup: stop the old services and the old container, and stop them from
# starting at boot. Stage 1 deletes nothing. You can undo it (--undo).
#
# Usage:
#   ops/cleanup/stage1_disable.sh [--dry-run] [--with GROUP]...   disable the units of the groups
#   ops/cleanup/stage1_disable.sh --undo [STATE_FILE] [--dry-run]  restore the state before stage 1
#   ops/cleanup/stage1_disable.sh --list                           show the groups and items, then stop
#
# Groups: "base" is always used. Add the other groups only after the owner answers the question in
# docs/CLEANUP_PROPOSAL.md (section "Open questions"):
#   base           nvargus-daemon, bluetooth, ModemManager, kerneloops, apport, rpcbind, lpd,
#                  packagekit (mask), cups snap services, Docker container driveragent-valhalla
#   nomachine      nxserver (NoMachine remote desktop)                     question 3
#   openvpn        openvpn + openvpn@uk-ovpn-agent-20                      question 2
#   avahi          avahi-daemon (mDNS name agx02.local)                    question 5
#   update-timers  apt-daily, apt-daily-upgrade, update-notifier-*, motd-news, fwupd-refresh,
#                  ua-timer, snapd.snap-repair                              question 7
#   desktop        boot target multi-user.target instead of graphical.target. This has an effect at
#                  the next boot only. The script does not reboot.         question 3
#
# Rules:
#   - Run as tonyho (not root) on agx02. The script uses sudo for systemctl and snap.
#   - The script prints the list first. Then you must type DISABLE (or UNDO for --undo).
#   - Without a terminal on stdin, the script always does a dry run.
#   - The script records the state before each change in
#     ~/.local/state/agx-cleanup/stage1-<time>.tsv. --undo reads the newest file (or the given file).
#   - The script refuses a unit of the KEEP list (jtop, nvpmodel, nvfancontrol, ssh, tailscale,
#     timesyncd, network, docker, containerd, agx-*, rk-* and the NVIDIA base units).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=common.sh
source "$HERE/common.sh"

# group|kind|name|what it is
# kind: unit = systemctl disable --now (or stop if not enabled); mask = systemctl mask --now;
#       snap = snap stop --disable; container = docker update --restart=no + docker stop;
#       target = systemctl set-default
ITEMS=(
    "base|unit|nvargus-daemon.service|CSI camera daemon; cameras are on the RK3588"
    "base|unit|bluetooth.service|Bluetooth"
    "base|unit|ModemManager.service|modem manager; no modem"
    "base|unit|kerneloops.service|kernel oops reports to Ubuntu"
    "base|unit|apport-autoreport.path|crash report upload trigger"
    "base|unit|apport-autoreport.timer|crash report upload timer (its service fails)"
    "base|unit|apport.service|crash report collector"
    "base|unit|rpcbind.socket|NFS port mapper socket (port 111)"
    "base|unit|rpcbind.service|NFS port mapper; no NFS mount"
    "base|unit|lpd.service|BSD line printer daemon"
    "base|mask|packagekit.service|backend of GNOME Software (static unit: mask)"
    "base|snap|cups|printing (snap cups: cupsd, cups-browsed; port 631)"
    "base|container|driveragent-valhalla|old map routing (Valhalla, port 8002)"
    "nomachine|unit|nxserver.service|NoMachine remote desktop (port 4000)"
    "openvpn|unit|openvpn@uk-ovpn-agent-20.service|OpenVPN client (does not connect)"
    "openvpn|unit|openvpn.service|OpenVPN autostart"
    "avahi|unit|avahi-daemon.socket|mDNS socket"
    "avahi|unit|avahi-daemon.service|mDNS name agx02.local"
    "update-timers|unit|apt-daily.timer|apt download timer"
    "update-timers|unit|apt-daily-upgrade.timer|apt upgrade timer"
    "update-timers|unit|update-notifier-download.timer|update pop-up timer"
    "update-timers|unit|update-notifier-motd.timer|update pop-up timer"
    "update-timers|unit|motd-news.timer|news in the login message"
    "update-timers|unit|fwupd-refresh.timer|firmware metadata download"
    "update-timers|unit|ua-timer.timer|Ubuntu Pro timer"
    "update-timers|unit|snapd.snap-repair.timer|snap repair timer"
    "desktop|target|multi-user.target|boot without the desktop (effect at the next boot)"
)
GROUPS_ALL="base nomachine openvpn avahi update-timers desktop"

# Units that stage 1 must never change.
KEEP_UNITS_RE='^(jtop|nvpmodel|nvfancontrol|nvphs|nvs-service|nv-tee-supplicant|nvidia-pva-allowd|nvzramconfig|nvpower|nv|nvfb.*|nv-l4t-.*|ssh|sshd|tailscaled|systemd-.*|NetworkManager.*|wpa_supplicant|docker|containerd|agx-.*|rk-.*|cron|dbus|getty@.*|serial-getty@.*)\.(service|socket|timer|path)$'

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d'; }

MODE=apply
STATE_FILE=""
SELECTED="base"
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --undo) MODE=undo
                if [ $# -gt 1 ] && [ "${2#--}" = "$2" ]; then STATE_FILE="$2"; shift; fi ;;
        --with) [ $# -gt 1 ] || die "--with needs a group name."
                case " $GROUPS_ALL " in *" $2 "*) ;; *) die "Unknown group: $2. Groups: $GROUPS_ALL" ;; esac
                SELECTED="$SELECTED $2"; shift ;;
        --list) MODE=list ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
    shift
done

selected() { case " $SELECTED " in *" $1 "*) return 0 ;; esac; return 1; }

if [ "$MODE" = list ]; then
    for it in "${ITEMS[@]}"; do
        IFS='|' read -r g k n w <<<"$it"
        printf '%-14s %-9s %-36s %s\n' "$g" "$k" "$n" "$w"
    done
    exit 0
fi

check_identity
check_terminal
pick_docker
mkdir -p "$CLEANUP_STATE"

# ------------------------------------------------------------- state of one item (read-only)
unit_mem() {
    local m
    m="$(systemctl show -p MemoryCurrent --value "$1" 2>/dev/null || true)"
    case "$m" in ''|'[not set]'|*[!0-9]*) printf '-' ;; *) human "$m" ;; esac
}

item_state() {   # kind name -> "prior1<TAB>prior2"
    local kind="$1" name="$2" a b
    case "$kind" in
        unit|mask)
            a="$(systemctl is-enabled "$name" 2>/dev/null || true)"; [ -n "$a" ] || a="not-found"
            b="$(systemctl is-active "$name" 2>/dev/null || true)"; [ -n "$b" ] || b="unknown" ;;
        snap)
            if command -v snap >/dev/null 2>&1 && snap list "$name" >/dev/null 2>&1; then
                # One word per service: enabled/disabled and active/inactive of the first service.
                a="$(snap services "$name" 2>/dev/null | awk 'NR>1 && $2=="enabled"{e=1} END{print (e?"enabled":"disabled")}')"
                b="$(snap services "$name" 2>/dev/null | awk 'NR>1 && $3=="active"{x=1} END{print (x?"active":"inactive")}')"
            else a="not-installed"; b="inactive"; fi ;;
        container)
            if [ ${#DOCKER[@]} -gt 0 ] && "${DOCKER[@]}" inspect "$name" >/dev/null 2>&1; then
                a="$("${DOCKER[@]}" inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$name")"
                b="$("${DOCKER[@]}" inspect -f '{{if .State.Running}}running{{else}}stopped{{end}}' "$name")"
            else a="not-found"; b="stopped"; fi ;;
        target)
            a="$(systemctl get-default)"; b="-" ;;
    esac
    printf '%s\t%s' "$a" "$b"
}

# ------------------------------------------------------------- change and undo of one item
apply_item() {   # kind name prior-enabled
    case "$1" in
        unit) if [ "$3" = enabled ]; then run sudo systemctl disable --now "$2"; else run sudo systemctl stop "$2"; fi ;;
        mask) run sudo systemctl mask --now "$2" ;;
        snap) run sudo snap stop --disable "$2" ;;
        container) run "${DOCKER[@]}" update --restart=no "$2"; run "${DOCKER[@]}" stop "$2" ;;
        target) run sudo systemctl set-default multi-user.target ;;
    esac
}

undo_item() {    # kind name prior1 prior2
    case "$1" in
        unit)
            if [ "$3" = enabled ]; then run sudo systemctl enable "$2"; fi
            if [ "$4" = active ]; then run sudo systemctl start "$2"; fi ;;
        mask)
            run sudo systemctl unmask "$2"
            if [ "$4" = active ]; then run sudo systemctl start "$2"; fi ;;
        snap)
            if [ "$3" = enabled ]; then run sudo snap start --enable "$2"
            elif [ "$4" = active ]; then run sudo snap start "$2"; fi ;;
        container)
            if [ "$3" != not-found ]; then run "${DOCKER[@]}" update --restart="$3" "$2"; fi
            if [ "$4" = running ]; then run "${DOCKER[@]}" start "$2"; fi ;;
        target)
            run sudo systemctl set-default "$3" ;;
    esac
}

# ------------------------------------------------------------------------------------ undo
if [ "$MODE" = undo ]; then
    if [ -z "$STATE_FILE" ]; then
        STATE_FILE="$(newest "$CLEANUP_STATE"/stage1-*.tsv)"
    fi
    [ -n "$STATE_FILE" ] && [ -f "$STATE_FILE" ] || die "No stage 1 state file found in $CLEANUP_STATE. Nothing to undo."
    say "Stage 1 UNDO. State file: $STATE_FILE"
    say "The script restores these items (in reverse order):"
    while IFS=$'\t' read -r -u 3 kind name p1 p2; do
        if [ "${kind:0:1}" = "#" ]; then continue; fi
        printf '  %-9s %-36s back to: %s / %s\n' "$kind" "$name" "$p1" "$p2"
    done 3< <(tac "$STATE_FILE")
    [ "$DRY_RUN" -eq 1 ] || confirm UNDO
    while IFS=$'\t' read -r -u 3 kind name p1 p2; do
        if [ "${kind:0:1}" = "#" ]; then continue; fi
        undo_item "$kind" "$name" "$p1" "$p2"
    done 3< <(tac "$STATE_FILE")
    if [ "$DRY_RUN" -eq 0 ]; then
        mv -- "$STATE_FILE" "$STATE_FILE.undone"
        say "Done. The state file is now $STATE_FILE.undone."
        say "If you restored the desktop target: it has an effect at the next boot."
    else
        say "Dry run: nothing changed."
    fi
    exit 0
fi

# ------------------------------------------------------------------------------- plan
say "Stage 1 DISABLE on $(hostname -s) as $(id -un). Groups: $SELECTED"
[ "$DRY_RUN" -eq 1 ] && say "DRY RUN: the script changes nothing."
say ""
printf '  %-9s %-36s %-24s %-10s %s\n' KIND NAME "STATE NOW" MEMORY ACTION
PLAN=()
for it in "${ITEMS[@]}"; do
    IFS='|' read -r g kind name _what <<<"$it"
    selected "$g" || continue
    if [ "$kind" = unit ] || [ "$kind" = mask ]; then
        if [[ "$name" =~ $KEEP_UNITS_RE ]]; then die "$name is a KEEP unit. The list in this script is wrong. Nothing changed."; fi
    fi
    st="$(item_state "$kind" "$name")"
    p1="${st%%$'\t'*}"; p2="${st#*$'\t'}"
    mem="-"
    action=""
    case "$kind" in
        unit)
            mem="$(unit_mem "$name")"
            if [ "$p1" = enabled ]; then action="disable --now"
            elif [ "$p2" = active ]; then action="stop (not enabled: $p1)"
            else action="SKIP (not enabled, not active)"; fi ;;
        mask)
            mem="$(unit_mem "$name")"
            if [ "$p1" = masked ]; then action="SKIP (masked)"; else action="mask --now"; fi ;;
        snap)
            if [ "$p1" = not-installed ]; then action="SKIP (not installed)"
            elif [ "$p1" = enabled ] || [ "$p2" = active ]; then action="snap stop --disable"
            else action="SKIP (disabled, inactive)"; fi ;;
        container)
            if [ "$p1" = not-found ]; then action="SKIP (not found)"
            else
                mem="$("${DOCKER[@]}" stats --no-stream --format '{{.MemUsage}}' "$name" 2>/dev/null | cut -d/ -f1 | tr -d ' ' || true)"
                [ -n "$mem" ] || mem="-"
                if [ "$p1" = no ] && [ "$p2" = stopped ]; then action="SKIP (restart=no, stopped)"
                else action="restart=no + stop"; fi
            fi ;;
        target)
            if [ "$p1" = multi-user.target ]; then action="SKIP (already multi-user.target)"
            else action="set-default multi-user.target (next boot)"; fi ;;
    esac
    printf '  %-9s %-36s %-24s %-10s %s\n' "$kind" "$name" "$p1/$p2" "$mem" "$action"
    case "$action" in SKIP*) ;; *) PLAN+=("$kind|$name|$p1|$p2|$action") ;; esac
done
say ""
say "Items to change: ${#PLAN[@]}. Memory = cgroup memory now (units) or container memory now."
say "Stage 1 deletes nothing. Undo: $0 --undo"
if [ ${#PLAN[@]} -eq 0 ]; then say "Nothing to do."; exit 0; fi
if [ "$DRY_RUN" -eq 1 ]; then
    say ""
    for p in "${PLAN[@]}"; do
        IFS='|' read -r kind name p1 p2 action <<<"$p"
        apply_item "$kind" "$name" "$p1"
    done
    say "Dry run: nothing changed."
    exit 0
fi

confirm DISABLE
sudo -v || die "sudo failed. Nothing changed."

STATE_FILE="$CLEANUP_STATE/stage1-$(date +%Y%m%d-%H%M%S).tsv"
printf '# stage1 state before change; host %s; user %s; %s\n' "$(hostname -s)" "$(id -un)" "$(date -Is)" >"$STATE_FILE"
say "State file: $STATE_FILE"
for p in "${PLAN[@]}"; do
    IFS='|' read -r kind name p1 p2 action <<<"$p"
    # Record the state first. Then a stop in the middle of the run can be undone.
    printf '%s\t%s\t%s\t%s\n' "$kind" "$name" "$p1" "$p2" >>"$STATE_FILE"
    apply_item "$kind" "$name" "$p1"
done
# The failed state of apport-autoreport.service stays after its timer stops. Clear it (no undo needed).
if selected base && [ "$(systemctl is-active apport-autoreport.service 2>/dev/null || true)" = failed ]; then
    run sudo systemctl reset-failed apport-autoreport.service
fi
say ""
say "Done. Stage 1 changed ${#PLAN[@]} items. Undo: $0 --undo $STATE_FILE"
say "Check the new installation now: systemctl --user status agx-infer agx-dashboard"
