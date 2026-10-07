#!/usr/bin/env bash
# Stage 2 of the AGX02 cleanup: move old folders and files into ONE archive folder on the same file
# system (~/_archive_<date>/). The move is a rename: it is fast and needs no free space.
# Stage 2 deletes nothing. You can undo it (--undo).
#
# Usage:
#   ops/cleanup/stage2_archive.sh [--dry-run] [--archive DIR]   move the items of the list below
#   ops/cleanup/stage2_archive.sh --undo [DIR] [--dry-run]      move all items back (newest archive
#                                                               if DIR is not given)
#
# Rules:
#   - Do stage 1 first (the Valhalla container must be stopped: it mounts the map tiles).
#   - Do the SAVE FIRST steps of docs/CLEANUP_PROPOSAL.md first. Stage 2 is safe without them
#     (nothing is deleted), but stage 3 refuses SAVE FIRST items without --confirm-saved.
#   - Run as tonyho (not root) on agx02. Stage 2 needs no sudo.
#   - The script prints the list and the sizes first. Then you must type ARCHIVE (or RESTORE for
#     --undo). Without a terminal on stdin, the script always does a dry run.
#   - The script refuses (does not move) an item that:
#       * is a KEEP item, is in a KEEP folder or contains one (~/driveragent-agx, ~/agx-models,
#         ~/model, ~/.local, ~/.config, ~/.ssh), or contains a file that the live config
#         (~/driveragent-agx/config/*.yaml) or a store manifest (~/agx-models/*/*/manifest.yaml)
#         uses. Example: the sim recordings 8003-20260510_15xxxx and 8003-20251109_1055xx-1057xx.
#       * is a mount source of a running Docker container;
#       * is the current folder of one of your processes;
#       * is on another file system or mount than the archive (then mv would copy);
#       * is a folder that you cannot write (a root-owned folder).
#   - The archive has a manifest (manifest.tsv): original path, archive path, size, SAVE FIRST flag.
#     --undo uses it. The plan of each run is also in ~/.local/state/agx-cleanup/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=common.sh
source "$HERE/common.sh"

H="$CLEANUP_HOME"
# save_first|path or glob|what it is
# save_first=1: the owner must do the SAVE FIRST step of the proposal before stage 3.
ITEMS=(
    "1|$H/Downloads/gstreamer|GStreamer 1.24.12 source and build (installed /opt/gst-1.24 stays); 2 untracked files"
    "1|$H/Downloads/libnice|libnice 0.1.15 build tree (make uninstall needs it); 1 untracked file"
    "0|$H/Downloads/raylib|raylib clone, clean (installed libraylib stays)"
    "0|$H/Downloads/cmake-3.31.7|cmake 3.31.7 build tree (installed cmake stays)"
    "0|$H/Downloads/maplibre-native|maplibre-native clone, clean (renderer of the old map UI)"
    "0|$H/opencv|OpenCV 4.10.0 build tree (installed OpenCV stays)"
    "0|$H/opencv_contrib|OpenCV extra modules source"
    "1|$H/Downloads/calcam|camera calibration script + cam0-5.yaml + venv (copy the yaml files first)"
    "0|$H/Downloads/nomachine.deb|old NoMachine installer 9.1.24 (installed 9.5.7)"
    "0|$H/jetson_out|test output 2026-05-11"
    "0|$H/agx_audit_agx02_20261005_202230|first audit run (no root); the 2026-10-07 audit replaces it"
    "0|$H/agx_audit_agx02_20261005_202230.tar.gz|tarball of the first audit run"
    "0|$H/s.sh|start script of the old stack (root-owned file)"
    "0|$H/start-driveragent.sh|start script of the old stack (root-owned file)"
    "1|$H/driveragent/location/valhalla_tiles|Valhalla routing tiles (old map service)"
    "1|$H/driveragent/location/united-kingdom-latest.osm.pbf|OSM source of the tiles"
    "1|$H/driveragent/location/gb.mbtiles|map display tiles of the old UI"
    "1|$H/driveragent/location/england_greater-london.mbtiles|map display tiles of the old UI"
    "1|$H/driveragent/dev/uk.mbtiles|second UK tile set (dev copy)"
    "0|$H/driveragent/location/mapgen|map image generator binary of the old UI"
    "1|$H/driveragent/logger/video/8003-*|old recordings (session folders and .tar.bz2 archives)"
)

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d'; }

MODE=apply
ARCHIVE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --undo) MODE=undo
                if [ $# -gt 1 ] && [ "${2#--}" = "$2" ]; then ARCHIVE="$2"; shift; fi ;;
        --archive) [ $# -gt 1 ] || die "--archive needs a folder."; ARCHIVE="$2"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
    shift
done

check_identity
check_terminal
mkdir -p "$CLEANUP_STATE"

check_archive_name() {
    case "$1" in
        "$H"/_archive_*) ;;
        *) die "The archive must be a folder $H/_archive_<name>. Given: $1" ;;
    esac
    case "${1#"$H"/}" in */*) die "The archive must be directly in $H. Given: $1" ;; esac
}

# ------------------------------------------------------------------------------------ undo
if [ "$MODE" = undo ]; then
    if [ -z "$ARCHIVE" ]; then
        m="$(newest "$H"/_archive_*/manifest.tsv)"
        [ -n "$m" ] || die "No archive with a manifest.tsv in $H. Nothing to undo."
        ARCHIVE="$(dirname "$m")"
    fi
    ARCHIVE="$(realpath -ms -- "$ARCHIVE")"
    check_archive_name "$ARCHIVE"
    MANIFEST="$ARCHIVE/manifest.tsv"
    [ -f "$MANIFEST" ] || die "$MANIFEST not found. Nothing to undo."
    say "Stage 2 UNDO. Archive: $ARCHIVE"
    n=0; skip=0
    while IFS=$'\t' read -r -u 3 src dest bytes sf note; do
        if [ "${src:0:1}" = "#" ]; then continue; fi
        if [ -e "$src" ] || [ -L "$src" ]; then say "  SKIP (the original path exists again): $src"; skip=$((skip + 1))
        elif ! [ -e "$dest" ] && ! [ -L "$dest" ]; then say "  SKIP (not in the archive): $src"; skip=$((skip + 1))
        else n=$((n + 1)); fi
    done 3<"$MANIFEST"
    say "Items to move back: $n. Items to skip: $skip."
    if [ "$n" -eq 0 ]; then say "Nothing to do."; exit 0; fi
    [ "$DRY_RUN" -eq 1 ] || confirm RESTORE
    while IFS=$'\t' read -r -u 3 src dest bytes sf note; do
        if [ "${src:0:1}" = "#" ]; then continue; fi
        if [ -e "$src" ] || [ -L "$src" ]; then continue; fi
        if ! [ -e "$dest" ] && ! [ -L "$dest" ]; then continue; fi
        if [ "$DRY_RUN" -eq 0 ]; then mkdir -p -- "$(dirname -- "$src")"; fi
        run mv -T -- "$dest" "$src"
    done 3< <(tac "$MANIFEST")
    if [ "$DRY_RUN" -eq 1 ]; then say "Dry run: nothing changed."; exit 0; fi
    done_name="$ARCHIVE/manifest.restored-$(date +%Y%m%d-%H%M%S).tsv"
    mv -- "$MANIFEST" "$done_name"
    find "$ARCHIVE/files" -depth -type d -empty -delete 2>/dev/null || true
    say "Done. The manifest is now $done_name."
    say "If $ARCHIVE has no other files, you can remove it: rm -r $ARCHIVE"
    exit 0
fi

# ------------------------------------------------------------------------------- plan
[ -n "$ARCHIVE" ] || ARCHIVE="$H/_archive_$(date +%Y%m%d)"
ARCHIVE="$(realpath -ms -- "$ARCHIVE")"
check_archive_name "$ARCHIVE"
MANIFEST="$ARCHIVE/manifest.tsv"

say "Stage 2 ARCHIVE on $(hostname -s) as $(id -un). Archive: $ARCHIVE"
[ "$DRY_RUN" -eq 1 ] && say "DRY RUN: the script changes nothing."
say "Reading the KEEP list (live config, store manifests, fixed KEEP folders) ..."
build_keep_list

# Mount sources of running containers are also KEEP (in use).
pick_docker
if [ ${#DOCKER[@]} -gt 0 ]; then
    while read -r cid; do
        [ -n "$cid" ] || continue
        cname="$("${DOCKER[@]}" inspect -f '{{.Name}}' "$cid" 2>/dev/null || true)"
        while read -r msrc; do
            [ -n "$msrc" ] || continue
            KEEP_LIST="$KEEP_LIST"$'\n'"REF"$'\t'"$msrc"$'\t'"mounted by the running container ${cname#/}"
        done < <("${DOCKER[@]}" inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$cid" 2>/dev/null || true)
    done < <("${DOCKER[@]}" ps -q 2>/dev/null || true)
fi

# Current folders of my processes.
CWDS="$(for p in /proc/[0-9]*; do readlink "$p/cwd" 2>/dev/null || true; done | sort -u)"

ARCH_DEV="$(stat -c %d -- "$H")"
ARCH_MNT="$(findmnt -n -o TARGET -T "$H")"

PLAN_FILE="$CLEANUP_STATE/stage2-plan-$(date +%Y%m%d-%H%M%S).tsv"
PLAN=()
total=0
refused=0
{
    printf '# stage2 plan; archive %s; %s\n' "$ARCHIVE" "$(date -Is)"
    printf '# status\tpath\tbytes\tsave_first\treason or note\n'
} >"$PLAN_FILE"

say ""
printf '  %-6s %-10s %-5s %s\n' STATUS SIZE SAVE1 "ITEM"
for it in "${ITEMS[@]}"; do
    IFS='|' read -r sf pattern note <<<"$it"
    shopt -s nullglob
    # shellcheck disable=SC2206  # the glob is wanted here
    matches=( $pattern )
    shopt -u nullglob
    if [ ${#matches[@]} -eq 0 ]; then
        printf '  %-6s %-10s %-5s %s\n' SKIP - "$sf" "$pattern (not found)"
        continue
    fi
    g_n=0; g_bytes=0; g_ref=0
    for src in "${matches[@]}"; do
        if ! [ -e "$src" ] && ! [ -L "$src" ]; then
            printf '  %-6s %-10s %-5s %s\n' SKIP - "$sf" "$src (not found)"
            continue
        fi
        src="$(realpath -ms -- "$src")"
        reason=""
        if r="$(keep_reason "$src")"; then reason="KEEP: $r"
        elif [ -n "$(printf '%s\n' "$CWDS" | awk -v s="$src" '$0==s || index($0, s"/")==1' | head -n1)" ]; then reason="in use: current folder of a process"
        elif [ "$(stat -c %d -- "$src")" != "$ARCH_DEV" ] || [ "$(findmnt -n -o TARGET -T "$src")" != "$ARCH_MNT" ]; then reason="other file system or mount than the archive"
        elif mountpoint -q -- "$src"; then reason="is a mount point"
        elif [ -d "$src" ] && ! [ -L "$src" ] && ! [ -w "$src" ]; then reason="folder is not writable for $(id -un) (root-owned?)"
        elif [ -e "$MANIFEST" ] && cut -f1 "$MANIFEST" | grep -qxF -- "$src"; then reason="already in the manifest"
        fi
        bytes="$(du -sb -- "$src" 2>/dev/null | cut -f1 || true)"; bytes="${bytes:-0}"
        if [ -n "$reason" ]; then
            printf 'REFUSED\t%s\t%s\t%s\t%s\n' "$src" "$bytes" "$sf" "$reason" >>"$PLAN_FILE"
            printf '  %-6s %-10s %-5s %s\n' REFUSE "$(human "$bytes")" "$sf" "$src -- $reason"
            g_ref=$((g_ref + 1)); refused=$((refused + 1))
            continue
        fi
        printf 'MOVE\t%s\t%s\t%s\t%s\n' "$src" "$bytes" "$sf" "$note" >>"$PLAN_FILE"
        PLAN+=("$src|$bytes|$sf|$note")
        g_n=$((g_n + 1)); g_bytes=$((g_bytes + bytes)); total=$((total + bytes))
    done
    if [ "$g_n" -gt 0 ]; then
        if [ ${#matches[@]} -eq 1 ]; then label="$pattern"; else label="$pattern ($g_n items; $g_ref refused)"; fi
        printf '  %-6s %-10s %-5s %s\n' MOVE "$(human "$g_bytes")" "$sf" "$label"
    fi
done
say ""
say "Items to move: ${#PLAN[@]} ($(human "$total")). Refused: $refused."
say "Full list: $PLAN_FILE"
say "Free disk space does not change in stage 2 (rename on the same file system: $ARCH_MNT)."
say "Undo: $0 --undo $ARCHIVE"
if [ ${#PLAN[@]} -eq 0 ]; then say "Nothing to do."; exit 0; fi
if [ "$DRY_RUN" -eq 1 ]; then
    say ""
    say "Example commands (first 3 items):"
    for p in "${PLAN[@]:0:3}"; do
        IFS='|' read -r src bytes sf note <<<"$p"
        run mv -T -- "$src" "$ARCHIVE/files$src"
    done
    say "Dry run: nothing changed."
    exit 0
fi

confirm ARCHIVE

mkdir -p -- "$ARCHIVE/files"
chmod 700 -- "$ARCHIVE"
if ! [ -f "$MANIFEST" ]; then
    {
        printf '# stage2 manifest; host %s; user %s; started %s\n' "$(hostname -s)" "$(id -un)" "$(date -Is)"
        printf '# original_path\tarchive_path\tbytes\tsave_first\tnote\n'
    } >"$MANIFEST"
fi
moved=0
for p in "${PLAN[@]}"; do
    IFS='|' read -r src bytes sf note <<<"$p"
    dest="$ARCHIVE/files$src"
    if [ -e "$dest" ] || [ -L "$dest" ]; then warn "$dest exists. Not moved: $src"; continue; fi
    mkdir -p -- "$(dirname -- "$dest")"
    # Write the manifest line first. Then a stop in the middle of the run can be undone.
    printf '%s\t%s\t%s\t%s\t%s\n' "$src" "$dest" "$bytes" "$sf" "$note" >>"$MANIFEST"
    mv -T -- "$src" "$dest"
    if [ -e "$src" ] || ! { [ -e "$dest" ] || [ -L "$dest" ]; }; then die "Move of $src is not complete. Stop. Check $MANIFEST."; fi
    moved=$((moved + 1))
done
say ""
say "Done. Moved $moved items ($(human "$total")) to $ARCHIVE."
say "Manifest: $MANIFEST"
say "Undo: $0 --undo $ARCHIVE"
say "Check the new installation now (dashboard, infer, sim). Wait some days before stage 3."
