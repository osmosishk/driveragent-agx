# shellcheck shell=bash disable=SC2034  # DOCKER, DRY_RUN and KEEP_LIST are used by the stage scripts
# Common functions of the cleanup scripts stage1_disable.sh, stage2_archive.sh, stage3_delete.sh.
# Do not run this file. The stage scripts read it with "source".
#
# Read docs/CLEANUP_PROPOSAL.md before you use a stage script.
#
# Values (the defaults are for AGX02). The variables are for tests in a fake environment only:
#   CLEANUP_USER   user that must run the scripts           (default: tonyho)
#   CLEANUP_HOST   short host name that must match         (default: agx02)
#   CLEANUP_HOME   home folder of that user                (default: /home/$CLEANUP_USER)
#   CLEANUP_REPO   live install of driveragent-agx         (default: $CLEANUP_HOME/driveragent-agx)
#   CLEANUP_STORE  live model store                        (default: $CLEANUP_HOME/agx-models)
#   CLEANUP_STATE  folder for state files and logs         (default: $CLEANUP_HOME/.local/state/agx-cleanup)

CLEANUP_USER="${CLEANUP_USER:-tonyho}"
CLEANUP_HOST="${CLEANUP_HOST:-agx02}"
CLEANUP_HOME="${CLEANUP_HOME:-/home/$CLEANUP_USER}"
CLEANUP_REPO="${CLEANUP_REPO:-$CLEANUP_HOME/driveragent-agx}"
CLEANUP_STORE="${CLEANUP_STORE:-$CLEANUP_HOME/agx-models}"
CLEANUP_STATE="${CLEANUP_STATE:-$CLEANUP_HOME/.local/state/agx-cleanup}"

DRY_RUN=0

say() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

# Size in bytes -> short text (for example 1.4GiB).
human() { numfmt --to=iec-i --suffix=B "${1:-0}" 2>/dev/null || printf '%sB' "${1:-0}"; }

# The scripts run only as the expected user (not as root) on the expected host.
check_identity() {
    [ "$(id -u)" -ne 0 ] || die "Do not run this script as root or with sudo. Run it as $CLEANUP_USER. The script uses sudo for the steps that need root."
    [ "$(id -un)" = "$CLEANUP_USER" ] || die "Wrong user: $(id -un). Run this script as $CLEANUP_USER."
    local h
    h="$(hostname -s)"
    [ "$h" = "$CLEANUP_HOST" ] || die "Wrong host: $h. This script is for $CLEANUP_HOST."
    [ -d "$CLEANUP_HOME" ] || die "Home folder $CLEANUP_HOME does not exist."
}

# Without a terminal, the script cannot ask for the typed confirmation. Then it does a dry run.
check_terminal() {
    if [ "$DRY_RUN" -eq 0 ] && ! [ -t 0 ]; then
        say "NOTE: stdin is not a terminal. The script cannot ask for a confirmation. It does a dry run."
        DRY_RUN=1
    fi
}

# confirm WORD: the user must type WORD. Other input stops the script. Nothing changed before this.
confirm() {
    local word="$1" answer=""
    say ""
    read -r -p "Type $word to continue (other input stops the script): " answer || true
    if [ "$answer" != "$word" ]; then
        say "Stopped. Nothing changed."
        exit 1
    fi
}

# run CMD...: prints the command, then runs it (or only prints it in a dry run).
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        say "  (dry run) $*"
    else
        say "  + $*"
        "$@"
    fi
}

# ---------------------------------------------------------------- KEEP items
# The KEEP list is made at run time. It has two kinds of entries:
#   TREE <path> <reason>  the path and everything in it stays. A candidate that is the path, is in
#                         it, or contains it is refused.
#                         Also the values of protected_dirs, scan_dirs and model_store in the config.
#   REF  <path> <reason>  a file or folder that the live install reads (config, model manifests).
#                         A candidate that is the path or contains it is refused. Other items
#                         in the same parent folder are not affected.
KEEP_LIST=""

build_keep_list() {
    local py
    py="$(command -v python3 || true)"
    [ -n "$py" ] || die "python3 not found. The KEEP check needs python3 with PyYAML. Nothing changed."
    "$py" -I -c 'import yaml' 2>/dev/null || die "python3 cannot import yaml. The KEEP check needs PyYAML. Nothing changed."
    [ -d "$CLEANUP_REPO/config" ] || die "$CLEANUP_REPO/config not found. The KEEP check needs the live config. Nothing changed."
    [ -d "$CLEANUP_STORE" ] || die "$CLEANUP_STORE not found. The KEEP check needs the model store. Nothing changed."

    local fixed
    fixed="$(printf 'TREE\t%s\t%s\n' \
        "$CLEANUP_REPO" "new installation (repo, .venv, .env, data, config)" \
        "$CLEANUP_STORE" "model store" \
        "$CLEANUP_HOME/model" "old models; protected_dirs; engines and ONNX of the store manifests" \
        "$CLEANUP_HOME/.local" "user-site Python packages that the live venv uses" \
        "$CLEANUP_HOME/.config" "user settings and user units" \
        "$CLEANUP_HOME/.ssh" "ssh keys" \
        "$CLEANUP_HOME/agx-installtest" "test installation of this task" \
        "$CLEANUP_HOME/agx-night-dev" "development copies of this task"
      printf 'REF\t%s\t%s\n' "$CLEANUP_HOME" "home folder")"

    local refs
    refs="$("$py" -I - "$CLEANUP_REPO" "$CLEANUP_STORE" <<'PY'
import glob, os, sys
import yaml

repo, store = sys.argv[1], sys.argv[2]
out = []

TREE_KEYS = ("protected_dirs", "scan_dirs", "model_store")

def strings(node, key=""):
    # Yields (string, name of the nearest dict key).
    if isinstance(node, dict):
        for k, v in node.items():
            yield from strings(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from strings(v, key)
    elif isinstance(node, str):
        yield node, key

def cut_glob(p):
    # Path part before the first glob character; then its folder if a glob was cut.
    for i, ch in enumerate(p):
        if ch in "*?[":
            return os.path.dirname(p[:i]) or "/"
    return p

def add(p, why, kind="REF"):
    p = os.path.normpath(os.path.expanduser(cut_glob(p)))
    out.append((kind, p, why))
    rp = os.path.realpath(p)
    if rp != p:
        out.append((kind, rp, why + " (real path)"))

def load(path):
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        print("ERROR\t%s\t%s" % (path, e))
        return None

cfgs = sorted(glob.glob(os.path.join(repo, "config", "*.yaml")))
for cfg in cfgs:
    data = load(cfg)
    if data is None:
        continue
    roots = []
    if isinstance(data, dict):
        for key in ("video_root",):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                roots.append(os.path.expanduser(v))
    for s, key in strings(data):
        s = s.strip()
        if s.startswith("/") or s.startswith("~/"):
            add(s, "used by " + cfg + (" (" + key + ")" if key in TREE_KEYS else ""),
                "TREE" if key in TREE_KEYS else "REF")
        elif s and roots and "\n" not in s:
            for r in roots:
                if os.path.lexists(os.path.join(r, cut_glob(s))):
                    add(os.path.join(r, s), "used by " + cfg + " (under video_root)")

for man in sorted(glob.glob(os.path.join(store, "*", "*", "manifest.yaml"))):
    data = load(man)
    if data is None:
        continue
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "path" and isinstance(v, str) and v.strip():
                    p = v if os.path.isabs(v) or v.startswith("~") else os.path.join(os.path.dirname(man), v)
                    add(p, "model file of " + man)
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(data)

for kind, p, why in out:
    print("%s\t%s\t%s" % (kind, p, why))
PY
)" || die "The KEEP check failed. Nothing changed."
    if printf '%s\n' "$refs" | grep -q '^ERROR'; then
        printf '%s\n' "$refs" | grep '^ERROR' >&2
        die "A config or manifest file cannot be read. The KEEP check is not complete. Nothing changed."
    fi
    KEEP_LIST="$fixed"$'\n'"$refs"
}

# keep_reason PATH: prints the reason and returns 0 if PATH is a KEEP item (or contains one).
keep_reason() {
    local c cr kind k why x
    c="$(realpath -ms -- "$1")"
    cr="$(realpath -m -- "$1")"
    while IFS=$'\t' read -r kind k why; do
        [ -n "$kind" ] || continue
        for x in "$c" "$cr"; do
            if [ "$x" = "$k" ]; then printf '%s' "is $k ($why)"; return 0; fi
            case "$k" in "$x"/*) printf '%s' "contains $k ($why)"; return 0 ;; esac
            if [ "$kind" = "TREE" ]; then
                case "$x" in "$k"/*) printf '%s' "is in $k ($why)"; return 0 ;; esac
            fi
        done
    done <<<"$KEEP_LIST"
    return 1
}

# newest PATTERN...: prints the newest existing file of the glob arguments (or nothing).
newest() {
    local f best="" bt=0 t
    for f in "$@"; do
        [ -e "$f" ] || continue
        t="$(stat -c %Y -- "$f")"
        if [ -z "$best" ] || [ "$t" -gt "$bt" ]; then best="$f"; bt="$t"; fi
    done
    printf '%s' "$best"
}

# Docker command: no sudo when the user is in the docker group, else sudo.
DOCKER=()
pick_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        DOCKER=()
    elif docker info >/dev/null 2>&1; then
        DOCKER=(docker)
    else
        DOCKER=(sudo docker)
    fi
}
