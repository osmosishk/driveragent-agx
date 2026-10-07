#!/usr/bin/env bash
# Export one model version of a model store as a package for another unit (docs/DEPLOY_MODEL.md section 2).
# The store is only READ. The script writes only the package folder <out>/<name>-<version>/.
#
# Usage: ops/export_model.sh <name> <version> [--store ~/agx-models] [--out DIR] [--with-engine]
#   --store DIR      the model store to read (default ~/agx-models)
#   --out DIR        the folder for the package (default: the current folder). The package is <out>/<name>-<version>.
#   --with-engine    also copy the engine. An engine runs only on the same device type (for example Jetson AGX Orin
#                    64 GB) with the same TensorRT version (10.3.0). A unit of another type must build its own
#                    engine from the ONNX file: export without --with-engine.
#
# The package has manifest.yaml and the ONNX file (the manifest path is rewritten to the package-relative name;
# the sha256 stays). A version without an ONNX file cannot be exported: exit 1 with "cannot export: no ONNX file".
# Then the script checks the package with tools/model_store_cli.py validate (against an empty temporary store).
# Exit 0 = package made and valid, 1 = cannot export or not valid, 2 = wrong command line.
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/lib/common.sh"

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 2 ] || usage
NAME="$1"; VERSION="$2"; shift 2
STORE="$DEF_STORE"; OUT="$PWD"; ENG=()
while [ $# -gt 0 ]; do
  case "$1" in
    --store) STORE="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --with-engine) ENG=(--with-engine); shift ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
done
STORE="$(expand_path "$STORE")"; OUT="$(expand_path "$OUT")"
mkdir -p "$OUT"
"$SYS_PY" "$OPS_LIB/export_model.py" "$NAME" "$VERSION" --store "$STORE" --out "$OUT" ${ENG[@]+"${ENG[@]}"} || exit 1

# Check the package with the store tool of this repository (an empty temporary store: no store is changed).
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="$SYS_PY"
TMPS="$(mktemp -d)"; trap 'rm -rf "$TMPS"' EXIT
say ""
say "check: python -m tools.model_store_cli validate $OUT/$NAME-$VERSION"
if (cd "$REPO" && PYTHONPATH="$REPO" "$PY" -m tools.model_store_cli validate "$OUT/$NAME-$VERSION" --store "$TMPS"); then
  exit 0
fi
say "The package is NOT valid (see the PROBLEM lines). It stays in $OUT/$NAME-$VERSION for inspection."
exit 1
