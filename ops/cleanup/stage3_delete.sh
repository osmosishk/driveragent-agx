#!/usr/bin/env bash
# Stage 3 of the AGX02 cleanup: delete the stage 2 archive(s) and the Docker data of the old stack
# (container driveragent-valhalla and image ghcr.io/valhalla/valhalla:latest, by name).
#
#   STAGE 3 CANNOT BE UNDONE. The deleted data is gone from this machine.
#
# Usage:
#   ops/cleanup/stage3_delete.sh [--dry-run] [--archive DIR]... [--confirm-saved] [--no-docker]
#
#   --archive DIR    delete only this archive (default: all ~/_archive_*/ folders with a manifest.tsv)
#   --confirm-saved  necessary when an archive has SAVE FIRST items or git repositories with
#                    uncommitted, unpushed or stashed work. Give it only after you did the SAVE
#                    FIRST steps of docs/CLEANUP_PROPOSAL.md.
#   --no-docker      do not delete the container and the image
#
# Rules:
#   - Do stage 1 and stage 2 first. Wait some days. Check that the new installation works.
#   - Run as tonyho (not root) on agx02. The archive has root-owned files (map tiles, build trees):
#     the script uses "sudo rm -rf --one-file-system" for the archive folder only.
#   - The script prints the list and the sizes first. Then you must type DELETE.
#     Without a terminal on stdin, the script always does a dry run.
#   - The script refuses to delete when a KEEP item (live config, store manifests, KEEP folders)
#     points into an archive, when an archive is not a folder ~/_archive_<name>, or when the
#     Valhalla container is running or another container uses the Valhalla image.
#   - No "docker system prune", no "docker image prune", no "docker volume prune". The script
#     removes only the container and the image named below.
#   - A copy of each deleted manifest stays in ~/.local/state/agx-cleanup/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR source=common.sh
source "$HERE/common.sh"

H="$CLEANUP_HOME"
OLD_CONTAINER="driveragent-valhalla"
OLD_IMAGE="ghcr.io/valhalla/valhalla:latest"
OLD_IMAGE_ID="063da86ba07c"   # image ID from the audit 2026-10-07; the script refuses another ID

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d'; }

ARCHIVES=()
SAVED=0
DO_DOCKER=1
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --archive) [ $# -gt 1 ] || die "--archive needs a folder."; ARCHIVES+=("$(realpath -ms -- "$2")"); shift ;;
        --confirm-saved) SAVED=1 ;;
        --no-docker) DO_DOCKER=0 ;;
        --undo) die "Stage 3 cannot be undone. Use stage2_archive.sh --undo BEFORE stage 3." ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1 (see --help)" ;;
    esac
    shift
done

check_identity
check_terminal
mkdir -p "$CLEANUP_STATE"

say "Stage 3 DELETE on $(hostname -s) as $(id -un)."
say "STAGE 3 CANNOT BE UNDONE."
[ "$DRY_RUN" -eq 1 ] && say "DRY RUN: the script changes nothing."

if [ ${#ARCHIVES[@]} -eq 0 ]; then
    for m in "$H"/_archive_*/manifest.tsv; do
        if [ -f "$m" ]; then ARCHIVES+=("$(dirname "$m")"); fi
    done
fi

say "Reading the KEEP list (live config, store manifests, fixed KEEP folders) ..."
build_keep_list

# ------------------------------------------------------------------------- archives: checks
BLOCK=0      # 1 = an error that stops the script
NEED_SAVED=0 # 1 = SAVE FIRST items or unsaved git work exist
arch_total=0
say ""
for a in "${ARCHIVES[@]}"; do
    case "$a" in "$H"/_archive_*) ;; *) die "Not an archive folder: $a (must be $H/_archive_<name>)." ;; esac
    case "${a#"$H"/}" in */*) die "Not an archive folder: $a (must be directly in $H)." ;; esac
    if ! [ -d "$a" ] || [ -L "$a" ]; then die "Archive $a is not a folder."; fi
    [ -f "$a/manifest.tsv" ] || die "Archive $a has no manifest.tsv. The script deletes only archives made by stage 2."
    if r="$(keep_reason "$a")"; then die "Archive $a is a KEEP item: $r"; fi
    # A KEEP reference must not point into the archive (for example a config changed after stage 2).
    while IFS=$'\t' read -r kind k why; do
        case "$k" in "$a"/*|"$a") say "  ERROR: $k is in the archive and is used: $why"; BLOCK=1 ;; esac
    done <<<"$KEEP_LIST"
    bytes="$(du -sb -- "$a" 2>/dev/null | cut -f1 || true)"; bytes="${bytes:-0}"
    arch_total=$((arch_total + bytes))
    n_items=0; n_sf=0
    while IFS=$'\t' read -r -u 3 src dest b sf note; do
        if [ "${src:0:1}" = "#" ]; then continue; fi
        if ! [ -e "$dest" ] && ! [ -L "$dest" ]; then continue; fi
        n_items=$((n_items + 1))
        if [ "$sf" = 1 ]; then n_sf=$((n_sf + 1)); fi
        # The original path must not be a KEEP item now (config can change after stage 2).
        if r="$(keep_reason "$src")"; then say "  ERROR: $src is a KEEP item now: $r. Move it back with stage2_archive.sh --undo."; BLOCK=1; fi
    done 3<"$a/manifest.tsv"
    say "Archive $a: $n_items items, $(human "$bytes"), SAVE FIRST items: $n_sf"
    if [ "$n_sf" -gt 0 ]; then
        NEED_SAVED=1
        while IFS=$'\t' read -r -u 3 src dest b sf note; do
            if [ "${src:0:1}" = "#" ] || [ "$sf" != 1 ]; then continue; fi
            if [ -e "$dest" ] || [ -L "$dest" ]; then say "    SAVE FIRST: $src ($(human "$b")) -- $note"; fi
        done 3<"$a/manifest.tsv"
    fi
    # Git repositories in the archive with work that is not on a remote (read-only checks).
    while read -r -u 4 gitdir; do
        repo="$(dirname -- "$gitdir")"
        dirty="$(git --no-optional-locks -C "$repo" status --porcelain 2>/dev/null | wc -l || true)"
        unpushed="$(git --no-optional-locks -C "$repo" log --oneline --branches --not --remotes 2>/dev/null | wc -l || true)"
        stashes="$(git --no-optional-locks -C "$repo" stash list 2>/dev/null | wc -l || true)"
        if [ "${dirty:-0}" -gt 0 ] || [ "${unpushed:-0}" -gt 0 ] || [ "${stashes:-0}" -gt 0 ]; then
            say "    GIT WORK NOT SAVED: $repo (uncommitted $dirty, unpushed $unpushed, stashes $stashes)"
            NEED_SAVED=1
        fi
    done 4< <(while IFS=$'\t' read -r -u 5 src dest b sf note; do
                  if [ "${src:0:1}" = "#" ] || ! [ -d "$dest" ] || [ -L "$dest" ]; then continue; fi
                  find "$dest" -maxdepth 4 -name .git 2>/dev/null || true
              done 5<"$a/manifest.tsv")
done
[ ${#ARCHIVES[@]} -gt 0 ] || say "No archive found (no $H/_archive_*/manifest.tsv)."

# ---------------------------------------------------------------------------- Docker: checks
DOCKER_PLAN=()
if [ "$DO_DOCKER" -eq 1 ]; then
    pick_docker
    if [ ${#DOCKER[@]} -eq 0 ]; then
        say "Docker: not installed. Nothing to do for Docker."
    else
        if "${DOCKER[@]}" inspect "$OLD_CONTAINER" >/dev/null 2>&1; then
            running="$("${DOCKER[@]}" inspect -f '{{.State.Running}}' "$OLD_CONTAINER")"
            if [ "$running" = true ]; then
                say "  ERROR: container $OLD_CONTAINER is running. Do stage 1 first."; BLOCK=1
            else
                DOCKER_PLAN+=("container|$OLD_CONTAINER")
                say "Docker container $OLD_CONTAINER: stopped. The script removes it (with its log file)."
            fi
        else
            say "Docker container $OLD_CONTAINER: not found."
        fi
        if "${DOCKER[@]}" image inspect "$OLD_IMAGE" >/dev/null 2>&1; then
            iid="$("${DOCKER[@]}" image inspect -f '{{.Id}}' "$OLD_IMAGE")"; iid="${iid#sha256:}"
            isize="$("${DOCKER[@]}" image inspect -f '{{.Size}}' "$OLD_IMAGE")"
            case "$iid" in
                "$OLD_IMAGE_ID"*) ;;
                *) say "  ERROR: $OLD_IMAGE has the ID ${iid:0:12}, not $OLD_IMAGE_ID. Check it by hand."; BLOCK=1 ;;
            esac
            users="$("${DOCKER[@]}" ps -a --filter "ancestor=$iid" --format '{{.Names}}' | grep -vxF "$OLD_CONTAINER" || true)"
            if [ -n "$users" ]; then
                say "  ERROR: other containers use $OLD_IMAGE: $users"; BLOCK=1
            else
                DOCKER_PLAN+=("image|$OLD_IMAGE")
                say "Docker image $OLD_IMAGE (${iid:0:12}): $(human "$isize"). The script removes it."
            fi
        else
            say "Docker image $OLD_IMAGE: not found."
        fi
    fi
fi

say ""
say "Archive data to delete: $(human "$arch_total") in ${#ARCHIVES[@]} archive(s). Docker items: ${#DOCKER_PLAN[@]}."
if [ "$BLOCK" -eq 1 ]; then die "Stage 3 stops because of the errors above. Nothing changed."; fi
if [ "$NEED_SAVED" -eq 1 ] && [ "$SAVED" -eq 0 ]; then
    die "The archive has SAVE FIRST items or unsaved git work (list above). Do the SAVE FIRST steps of docs/CLEANUP_PROPOSAL.md, then run again with --confirm-saved. Nothing changed."
fi
if [ ${#ARCHIVES[@]} -eq 0 ] && [ ${#DOCKER_PLAN[@]} -eq 0 ]; then say "Nothing to do."; exit 0; fi

if [ "$DRY_RUN" -eq 0 ]; then
    say ""
    say "STAGE 3 CANNOT BE UNDONE. After this step, stage2_archive.sh --undo cannot restore the data."
    confirm DELETE
    sudo -v || die "sudo failed. Nothing changed."
fi

ts="$(date +%Y%m%d-%H%M%S)"
for a in "${ARCHIVES[@]}"; do
    if [ "$DRY_RUN" -eq 0 ]; then
        cp -- "$a/manifest.tsv" "$CLEANUP_STATE/stage3-deleted-$(basename "$a")-$ts.tsv"
    fi
    run sudo rm -rf --one-file-system -- "$a"
done
for d in "${DOCKER_PLAN[@]}"; do
    IFS='|' read -r kind name <<<"$d"
    case "$kind" in
        container) run "${DOCKER[@]}" rm "$name" ;;
        image) run "${DOCKER[@]}" rmi "$name" ;;
    esac
done
if [ "$DRY_RUN" -eq 1 ]; then say "Dry run: nothing changed."; exit 0; fi
say ""
say "Done. Free space now:"
df -h -- "$H"
say "Copies of the deleted manifests: $CLEANUP_STATE/stage3-deleted-*-$ts.tsv"
