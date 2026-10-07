#!/bin/bash
# Set-up of agx-infer on the Jetson Orin NX single-camera unit (branch nx/local-source). NO ROOT.
#   config/orin-nx/setup.sh [all|venv|test]
#     venv   .venv in this checkout (with the system packages: TensorRT, torch, OpenCV) + requirements.lock
#     test   the repo tests of the parts that the branch changes
# The unit (systemd/orin-nx/agx-infer.service) is installed by rk/ops/jetson/user-services.sh of driveragent-hmi.
set -euo pipefail
AGX=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd -P)
# The shell of this unit points pip to the Jetson AI Lab index; these packages come from PyPI.
export PIP_INDEX_URL=https://pypi.org/simple PIP_CONFIG_FILE=/dev/null PIP_DISABLE_PIP_VERSION_CHECK=1
export PYTHONDONTWRITEBYTECODE=1
[ "$(id -u)" != 0 ] || { echo "run as the service user, not root" >&2; exit 1; }

venv() {
    [ -x "$AGX/.venv/bin/python" ] || python3 -m venv --system-site-packages "$AGX/.venv"
    "$AGX/.venv/bin/pip" install -q -r "$AGX/config/orin-nx/requirements.lock"
    "$AGX/.venv/bin/python" -B -c "import crc32c, torch, tensorrt, capnp, zmq, yaml, cv2; print('venv ok: tensorrt', tensorrt.__version__, 'torch', torch.__version__)"
    mkdir -p "$HOME/.local/state/driveragent-agx/models"
}

tests() {
    cd "$AGX"
    "$AGX/.venv/bin/python" -B -m pytest -q -p no:cacheprovider tests/test_ingest.py tests/test_publish.py \
        tests/test_manager.py tests/test_rkinfo.py tests/test_envelope.py tests/test_repo_rules.py 2>&1 \
        | grep -E "passed|failed|error" | tail -1
}

case "${1:-all}" in
    venv) venv ;;
    test) tests ;;
    all) venv; tests ;;
    *) echo "usage: $0 [all|venv|test]" >&2; exit 2 ;;
esac
