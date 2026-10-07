#!/usr/bin/env bash
# Remove what ops/install.sh made for one instance. The record data/install-<instance>.json is the only source:
# a path that is not in the record is never removed. The script prints the list first.
#
# Usage: ops/uninstall.sh [--instance agx] [--purge] [--yes]
#   --instance NAME  the instance of ops/install.sh (default agx)
#   --purge          also remove the config files, .env, data/, logs/, engines/ and the model store, but ONLY when
#                    install made them (a file or a store that install KEPT stays). data/ holds the pairing data.
#   --yes            no question
#
# Without --purge: stop, disable and delete the user unit files of the record, and remove .venv (if install made
# it). config/*.yaml, .env, data/, the model store and the record stay.
# The script never touches a TRANSIENT unit (tools/svc.sh), a system unit or a unit file that install did not make.
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/lib/common.sh"

INSTANCE=$DEF_INSTANCE; PURGE=0; YES=0
usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --instance) INSTANCE="${2:-}"; shift 2 ;;
    --purge) PURGE=1; shift ;;
    --yes) YES=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
done
[ "$(id -u)" -ne 0 ] || die "do not run uninstall.sh as root or with sudo."
check_instance_name "$INSTANCE"
RECORD="$REPO/data/install-$INSTANCE.json"
[ -f "$RECORD" ] || die "no install record $RECORD: nothing is removed (uninstall removes only what install made)."
REC_REPO="$("$SYS_PY" "$OPS_LIB/record.py" get "$RECORD" repo | tr -d '"')"
[ "$REC_REPO" = "$REPO" ] || die "the record is for the repository $REC_REPO, not $REPO: nothing is removed."
UDIR="$(user_unit_dir)"

# Safety: a path to remove must be in the repo, in the user unit folder, or the recorded store; never / or $HOME.
REC_STORE="$("$SYS_PY" "$OPS_LIB/record.py" get "$RECORD" store | tr -d '"')"
safe_path() {
  local p="$1"
  case "$p" in ""|/|"$HOME"|"$HOME/"|"$REPO"|"$REPO/") return 1 ;; esac
  case "$p" in
    "$REPO"/*|"$UDIR"/*) return 0 ;;
    "$REC_STORE"|"$REC_STORE"/_state|"$REC_STORE"/_incoming) return 0 ;;
  esac
  return 1
}

UNIT_FILES=(); VENV=(); PURGE_LIST=(); SKIP=(); UNIT_DIRS=()
while IFS=$'\t' read -r kind path; do
  [ -n "$path" ] || continue
  if [ "$kind" = unit-dir ]; then UNIT_DIRS+=("$path"); continue; fi   # only rmdir when empty: no safe_path check
  if ! safe_path "$path"; then SKIP+=("$path (outside the repo, the unit folder and the store: not removed)"); continue; fi
  case "$kind" in
    unit-file) UNIT_FILES+=("$path") ;;
    venv) VENV+=("$path") ;;
    config|env|dir|store|store-sub|file) PURGE_LIST+=("$kind"$'\t'"$path") ;;
    *) SKIP+=("$path (kind $kind: not known)") ;;
  esac
done < <("$SYS_PY" "$OPS_LIB/record.py" list "$RECORD" made)

say "driveragent-agx uninstall: instance $INSTANCE, repo $REPO$([ "$PURGE" = 1 ] && echo ', PURGE')"
say "The script removes:"
n=0
for f in "${UNIT_FILES[@]}"; do
  u="$(basename "$f")"
  if [ "$(uprop "$u" Transient)" = yes ]; then SKIP+=("$u (a TRANSIENT unit with this name is loaded: not touched)"); continue; fi
  say "  unit  $u: stop, disable, delete $f"; n=$((n + 1))
done
for v in "${VENV[@]}"; do say "  venv  $v ($(du -sh "$v" 2>/dev/null | cut -f1))"; n=$((n + 1)); done
if [ "$PURGE" = 1 ]; then
  for e in "${PURGE_LIST[@]}"; do
    k="${e%%$'\t'*}"; p="${e#*$'\t'}"
    [ -e "$p" ] || continue
    extra=""
    case "$k" in
      store) extra=" (the MODEL STORE: $(find "$p" -mindepth 2 -maxdepth 2 -path "$p/[!_.]*" -type d 2>/dev/null | wc -l) model version(s))" ;;
      dir) [ "$p" = "$REPO/data" ] && extra=" (pairing data, tokens, history, this record)" ;;
    esac
    say "  $k  $p$extra"; n=$((n + 1))
  done
fi
say "The script keeps:"
if [ "$PURGE" != 1 ]; then
  say "  config/*.yaml, .env, data/ (pairing, this record), logs/, engines/ and the model store (use --purge to remove what install made)"
fi
while IFS=$'\t' read -r _k path; do [ -n "$path" ] && say "  $path (install KEPT it: never removed)"; done \
  < <("$SYS_PY" "$OPS_LIB/record.py" list "$RECORD" kept)
for s in "${SKIP[@]}"; do say "  $s"; done
if [ "$n" = 0 ]; then say "Nothing to remove."; exit 0; fi

if [ "$YES" != 1 ]; then
  [ -t 0 ] || die "give --yes (no terminal for the question). Nothing was removed."
  read -r -p "Type yes to remove the items above: " ans
  [ "$ans" = yes ] || die "cancelled: nothing was removed."
fi

# Units
removed_units=0
for f in "${UNIT_FILES[@]}"; do
  u="$(basename "$f")"
  [ "$(uprop "$u" Transient)" = yes ] && continue
  systemctl --user disable --now "$u" 2>&1 | sed 's/^/      /' || true
  rm -f "$f"; say "REMOVED $f"; removed_units=1
done
if [ "$removed_units" = 1 ]; then
  systemctl --user daemon-reload
  for f in "${UNIT_FILES[@]}"; do systemctl --user reset-failed "$(basename "$f")" 2>/dev/null || true; done
fi
for v in "${VENV[@]}"; do rm -rf "$v"; say "REMOVED $v"; done
# Unit folders that install made: remove the empty folders only (rmdir), from the deepest up to the recorded one.
for top in "${UNIT_DIRS[@]}"; do
  case "$UDIR" in "$top"|"$top"/*) ;; *) continue ;; esac
  rmdir "$UDIR"/*.wants 2>/dev/null || true
  d="$UDIR"
  while :; do
    rmdir "$d" 2>/dev/null || break
    say "REMOVED $d (empty folder)"
    [ "$d" = "$top" ] && break
    d="$(dirname "$d")"
  done
done
if [ "$PURGE" != 1 ]; then
  "$SYS_PY" "$OPS_LIB/record.py" uninstalled "$RECORD" unit-file venv unit-dir
  say "The record $RECORD stays (config, .env, data and the store too). ops/uninstall.sh --purge removes them later."
  exit 0
fi

# Purge: store sub-folders first, then files, then folders; data/ (with the record) last.
order() { case "$1" in store-sub) echo 1 ;; store) echo 2 ;; config|env|file) echo 3 ;; dir) echo 4 ;; *) echo 5 ;; esac; }
DATA_LAST=""
while IFS=$'\t' read -r _o k p; do
  [ -e "$p" ] || continue
  if [ "$p" = "$REPO/data" ]; then DATA_LAST="$p"; continue; fi
  if [ -d "$p" ]; then rm -rf "$p"; else rm -f "$p"; fi
  say "REMOVED $p"
done < <(for e in "${PURGE_LIST[@]}"; do printf '%s\t%s\n' "$(order "${e%%$'\t'*}")" "$e"; done | sort -n)
if [ -n "$DATA_LAST" ]; then
  rm -rf "$DATA_LAST"; say "REMOVED $DATA_LAST (with the record)"
else
  "$SYS_PY" "$OPS_LIB/record.py" uninstalled "$RECORD" unit-file venv unit-dir config env dir store store-sub file
  say "The record $RECORD stays (data/ was KEPT by install)."
fi
say "Uninstall done."
