#!/usr/bin/env bash
# Put a model package into the model store of AGX02 (docs/DEPLOY_MODEL.md). It does NOT build and does NOT activate.
#
# Usage: tools/deploy_model.sh <package dir> [--host agx02] [--store ~/agx-models] [--user U]
#                              [--repo ~/driveragent-agx] [--local | --remote]
#
# On the AGX itself (--local; automatic when the hostname is the --host value, or on a Jetson with no --host): runs "python -m tools.model_store_cli deploy <package dir>" of this repo.
# On a workstation (or --remote): copies the package with scp -r to <host>:<store>/_incoming/<name>-<version>-<rand>/
# and runs "python -m tools.model_store_cli deploy --staged <that folder>" on the host over ssh. The command-line
# tool checks the manifest and the sha256 values, refuses an existing version and writes the audit line.
# Exit code: 0 deployed, 1 not deployed (the reason is printed).
set -euo pipefail

usage() {
  sed -n '4,5p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}
die() { echo "deploy_model: $*" >&2; exit 1; }

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pkg=""
host="agx02"
# A literal ~ on purpose: the cli expands it (local), remote_path expands it to the remote home (remote).
# shellcheck disable=SC2088
store="~/agx-models"
user="${USER:-$(id -un)}@$(hostname -s 2>/dev/null || echo unknown)"
# shellcheck disable=SC2088
repo="~/driveragent-agx"
mode="auto"
host_given=0

while [ $# -gt 0 ]; do
  case "$1" in
    --host) [ $# -ge 2 ] || usage; host="$2"; host_given=1; shift 2 ;;
    --store) [ $# -ge 2 ] || usage; store="$2"; shift 2 ;;
    --user) [ $# -ge 2 ] || usage; user="$2"; shift 2 ;;
    --repo) [ $# -ge 2 ] || usage; repo="$2"; shift 2 ;;
    --local) mode="local"; shift ;;
    --remote) mode="remote"; shift ;;
    -h|--help) usage ;;
    -*) echo "deploy_model: unknown option $1" >&2; usage ;;
    *) [ -z "$pkg" ] || usage; pkg="$1"; shift ;;
  esac
done
[ -n "$pkg" ] || usage
[ -d "$pkg" ] || die "$pkg is not a folder"
[ -f "$pkg/manifest.yaml" ] || die "no manifest.yaml in $pkg"
pkg="$(cd "$pkg" && pwd)"

if [ "$mode" = "auto" ]; then
  # Local when this machine is the host. Also local on a Jetson (an AGX unit) when no --host was given: the
  # default host agx02 is then a different AGX, and a copy to it is not what the user wants.
  if [ "$(hostname -s 2>/dev/null || true)" = "$host" ]; then mode="local"
  elif [ "$host_given" = 0 ] && [ -f /etc/nv_tegra_release ]; then mode="local"
  else mode="remote"; fi
fi

if [ "$mode" = "local" ]; then
  py="${AGX_PYTHON:-$here/.venv/bin/python}"
  [ -x "$py" ] || py="$(command -v python3)" || die "no python found"
  echo "deploy_model: local deploy into $store"
  rc=0
  (cd "$here" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$here" \
    "$py" -m tools.model_store_cli deploy "$pkg" --store "$store" --user "$user") || rc=$?
  [ "$rc" -eq 0 ] || die "not deployed (exit $rc)"
  exit 0
fi

# Remote: scp follows symbolic links, so refuse them here (the cli refuses them on AGX02 too).
if [ -n "$(find "$pkg" -type l -print -quit)" ]; then
  die "the package contains a symbolic link: put the real files into the package"
fi
# name and version for the folder name only (the cli reads and checks the real manifest)
field() {
  sed -n "s/^$1:[[:space:]]*['\"]\{0,1\}\([A-Za-z0-9._-]*\).*/\1/p" "$pkg/manifest.yaml" | head -n 1
}
name="$(field name)"
version="$(field version)"
rand="$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
staged_name="${name:-package}-${version:-x}-${rand}"

ssh_q() { printf '%q' "$1"; }
# A leading ~ is expanded on the host (the remote home), not here.
remote_path() {
  # shellcheck disable=SC2088
  case "$1" in
    "~") printf '%s' "$remote_home" ;;
    "~/"*) printf '%s/%s' "$remote_home" "${1#\~/}" ;;
    *) printf '%s' "$1" ;;
  esac
}
remote_home="$(ssh "$host" 'printf %s "$HOME"')" || die "cannot reach $host with ssh"
[ -n "$remote_home" ] || die "cannot read the home folder on $host"
rstore="$(remote_path "$store")"
rrepo="$(remote_path "$repo")"
staged="$rstore/_incoming/$staged_name"

# The paths are quoted here (printf %q) on purpose: the remote shell gets them as single words.
# shellcheck disable=SC2029
ssh "$host" "test -d $(ssh_q "$rstore") && mkdir -p $(ssh_q "$rstore/_incoming") && test ! -e $(ssh_q "$staged")" \
  || die "the store $rstore does not exist on $host (or the upload folder cannot be made)"
# Early stop before a long copy (the cli makes the real check, with the audit line, after the copy).
if [ -n "$name" ] && [ -n "$version" ]; then
  # shellcheck disable=SC2029
  if ssh "$host" "test -e $(ssh_q "$rstore/$name/$version")"; then
    die "$host:$rstore/$name/$version exists: a version is never overwritten (owner rule M2). Give the package a new version"
  fi
fi
echo "deploy_model: copy $pkg -> $host:$staged"
scp -q -r "$pkg" "$host:$staged" || die "the copy to $host failed (the partial copy is in $host:$staged)"
echo "deploy_model: deploy on $host"
rc=0
# shellcheck disable=SC2029
ssh "$host" "cd $(ssh_q "$rrepo") && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m tools.model_store_cli \
deploy --staged $(ssh_q "$staged") --store $(ssh_q "$rstore") --user $(ssh_q "$user")" || rc=$?
[ "$rc" -eq 0 ] || die "not deployed (exit $rc on $host)"
exit 0
