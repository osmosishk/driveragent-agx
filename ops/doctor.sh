#!/usr/bin/env bash
# Check a running driveragent-agx installation. The script changes nothing. It never prints a password or a token.
#
# Usage: ops/doctor.sh [--instance agx] [--before-pairing] [--system-units]
#   --instance NAME    the units NAME-infer and NAME-dashboard (default agx)
#   --before-pairing   pairing and link items are information only (a new unit has no paired board yet)
#   --system-units     the units are system units (ops/install.sh --print-system-units), not user units
#
# Items: units active, dashboard /api/health with the password of .env, agx-infer status in the dashboard, model
# store readable, sensors readable (INA3221 rails, thermal zones), pairing state (paired boards), link state
# (result subscribers, last status). Output: PASS, FAIL (a necessary item), WARN or INFO lines.
# Exit 0 only when all necessary items pass, else 1.
set -uo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/lib/common.sh"

INSTANCE=$DEF_INSTANCE; BEFORE=0; SYSTEM=0
usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --instance) INSTANCE="${2:-}"; shift 2 ;;
    --before-pairing) BEFORE=1; shift ;;
    --system-units) SYSTEM=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
done
check_instance_name "$INSTANCE"
say "driveragent-agx doctor: instance $INSTANCE, repo $REPO, host $(hostname), $(date '+%Y-%m-%d %H:%M:%S %Z')"
say ""

# 1. Units
for t in dashboard infer; do
  u="$INSTANCE-$t.service"
  if [ "$SYSTEM" = 1 ]; then
    st="$(sprop "$u" ActiveState)"; sub="$(sprop "$u" SubState)"; kind="system unit"
    pid="$(sprop "$u" MainPID)"; nr="$(sprop "$u" NRestarts)"; en="$(systemctl is-enabled "$u" 2>/dev/null || true)"
  else
    st="$(uprop "$u" ActiveState)"; sub="$(uprop "$u" SubState)"; kind="user unit"
    [ "$(uprop "$u" Transient)" = yes ] && kind="TRANSIENT user unit (not installed; tools/svc.sh)"
    pid="$(uprop "$u" MainPID)"; nr="$(uprop "$u" NRestarts)"; en="$(systemctl --user is-enabled "$u" 2>/dev/null || true)"
  fi
  detail="$kind, $st/$sub, MainPID ${pid:-?}, restarts ${nr:-?}, enabled: ${en:-unknown}"
  if [ "$st" = active ]; then pass_item "unit $t" "$u: $detail"; else fail_item "unit $t" "$u: $detail"; fi
done

# 2-5 and 7-8 in Python: one place that reads .env (the password stays in the process; it is never printed).
"$SYS_PY" - "$REPO" "$BEFORE" <<'EOF'
import base64, glob, json, os, ssl, sys, time, urllib.request
import yaml

repo, before = sys.argv[1], sys.argv[2] == "1"
failed = False


def item(level, name, text):
    global failed
    if level == "FAIL":
        failed = True
    print(f"{level:5s} {name:24s} {text}", flush=True)


def load(name):
    try:
        with open(os.path.join(repo, "config", name), encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        item("FAIL", "config", f"config/{name}: {e}")
        return {}


dash, infer = load("dashboard.yaml"), load("infer.yaml")
env = {}
envf = os.path.join(repo, str(dash.get("env_file") or ".env"))
try:
    with open(envf, encoding="utf-8") as f:
        for ln in f:
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.rstrip("\n").split("=", 1)
                env[k.strip()] = v.strip()
    mode = os.stat(envf).st_mode & 0o777
    if mode & 0o077:
        item("WARN", "password file", f"{envf} has mode {mode:o}: use 600 (chmod 600 {envf})")
except OSError as e:
    item("FAIL", "password file", f"{envf}: {e.strerror}")
user, pw = env.get("AGX_DASH_USER") or "agx", env.get("AGX_DASH_PASSWORD") or ""
if not pw:
    item("FAIL", "password file", f"AGX_DASH_PASSWORD is empty in {envf}: the dashboard does not start")

port = dash.get("port") or 8700
pf = os.path.join(repo, str(dash.get("port_file") or "data/dashboard_port"))
try:
    with open(pf, encoding="utf-8") as f:
        port = int(f.read().strip() or port)
except (OSError, ValueError):
    pass
tls = bool(dash.get("tls_certfile"))
base = f"{'https' if tls else 'http'}://127.0.0.1:{port}"
ctx = ssl._create_unverified_context() if tls else None   # loopback check only
auth = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


def get(path):
    req = urllib.request.Request(base + path, headers={"Authorization": auth})
    with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


health = None
try:
    code, health = get("/api/health")
    item("PASS", "dashboard /api/health", f"{base}/api/health answers {code} with the password of .env; node_state "
         f"{health.get('node_state')} ({'; '.join(health.get('node_state_reasons') or []) or 'no reason'})")
except urllib.error.HTTPError as e:
    item("FAIL", "dashboard /api/health", f"{base}/api/health answers {e.code} ({'wrong password?' if e.code == 401 else e.reason})")
except Exception as e:  # noqa: BLE001
    item("FAIL", "dashboard /api/health", f"{base}/api/health: {type(e).__name__}: {e}")

# agx-infer status as the dashboard sees it
if health is not None:
    inf = health.get("infer")
    if isinstance(inf, dict):
        models = inf.get("models") or []
        act = [f"{m.get('name')} {m.get('state')}" for m in models if isinstance(m, dict)]
        cs = (inf.get("cameras_summary") or {}).get("states") or {}
        state = inf.get("state") or "?"
        why = "; ".join(str(r) for r in (inf.get("reasons") or inf.get("state_reasons") or []))
        item("PASS", "agx-infer status", f"agx-infer sends status: state {state}{f' ({why})' if why else ''}; models: "
             f"{', '.join(act) or 'none'}; cameras: {', '.join(f'{k} {v}' for k, v in cs.items()) or 'none'}")
        if not act:
            item("INFO", "models", "no model is active (normal for a new unit: deploy, build and activate a model, "
                 "docs/DEPLOY_MODEL.md). agx-infer shows ERROR 'no model is enabled' until then.")
    else:
        item("FAIL", "agx-infer status", "the dashboard has no status from agx-infer (is the infer unit running? "
             "infer_config / ports.internal)")

# Model store
store = os.path.expanduser(str(infer.get("model_store") or dash.get("model_store") or "~/agx-models"))
if os.path.isdir(store) and os.access(store, os.R_OK | os.X_OK):
    vers = [p for p in glob.glob(os.path.join(store, "[!_.]*", "*", "manifest.yaml"))]
    st = os.path.join(store, "_state")
    w = "writable" if os.access(st, os.W_OK) else "NOT writable"
    item("PASS" if os.access(st, os.W_OK) else "FAIL", "model store",
         f"{store}: {len(vers)} model version(s); _state {w}")
    tf = os.path.join(store, "_testframes", "front_1280x720.jpg")
    if not os.path.isfile(tf):
        item("WARN", "test frame", f"{tf} is missing: the inference check of a model needs it (docs/INSTALL_AGX.md)")
else:
    item("FAIL", "model store", f"{store} is not a readable folder")

# Sensors: INA3221 rails and thermal zones (the same files as the dashboard health sample)
rails = []
for d in glob.glob("/sys/bus/i2c/drivers/ina3221/*/hwmon/hwmon*"):
    for lab in sorted(glob.glob(os.path.join(d, "in*_label"))):
        try:
            name = open(lab).read().strip()
            n = os.path.basename(lab)[2:-6]
            mv = int(open(os.path.join(d, f"in{n}_input")).read())
            ma = int(open(os.path.join(d, f"curr{n}_input")).read())
            rails.append(f"{name} {mv * ma / 1000:.0f} mW")
        except Exception:  # noqa: BLE001
            pass
if rails:
    item("PASS", "sensors INA3221", "; ".join(rails))
else:
    item("FAIL", "sensors INA3221", "no INA3221 rail is readable (/sys/bus/i2c/drivers/ina3221/*/hwmon)")
temps = []
for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
    try:
        temps.append(f"{open(z + '/type').read().strip()} {int(open(z + '/temp').read()) / 1000:.1f} C")
    except Exception:  # noqa: BLE001  (some zones give no value: skip them)
        pass
if temps:
    item("PASS", "sensors thermal", f"{len(temps)} zones: " + ", ".join(temps[:4]) + (" ..." if len(temps) > 4 else ""))
else:
    item("FAIL", "sensors thermal", "no thermal zone is readable (/sys/class/thermal)")

# Pairing and link (from /api/pair/state; only counts and states are printed, never a code or a token)
lvl = "INFO" if before else "FAIL"
try:
    _c, ps = get("/api/pair/state")
    boards = ps.get("boards") or []
    other = ps.get("other_subscribers") or {}
    if boards:
        item("PASS", "pairing", f"{len(boards)} paired board(s): " + ", ".join(
            f"{b.get('name') or b.get('id')}" for b in boards if isinstance(b, dict)))
        ups = [b for b in boards if isinstance(b, dict) and b.get("link_state") == "UP"]
        txt = "; ".join(f"{b.get('name') or b.get('id')}: {b.get('link_state')} ({b.get('link_detail')})"
                        for b in boards if isinstance(b, dict))
        item("PASS" if ups else lvl, "link", txt)
    else:
        item(lvl, "pairing", "no paired board (pair one: docs/CONNECT_AGX.md)")
        item(lvl, "link", "no paired board: no link")
    if isinstance(other, dict) and other.get("count"):
        item("INFO", "other subscribers", f"{other['count']} result subscriber(s) that are not paired boards")
except Exception as e:  # noqa: BLE001
    item(lvl, "pairing", f"/api/pair/state: {type(e).__name__}: {e}")
if health is not None and isinstance(health.get("infer"), dict):
    inf = health["infer"]
    item("INFO", "results", f"result subscribers {inf.get('subscribers')}, results {inf.get('results_rate_hz')}/s, "
         f"status age {health.get('age_s')} s")
sys.exit(1 if failed else 0)
EOF
py_rc=$?
[ "$py_rc" = 0 ] || CHECK_FAILED=1

say ""
if [ "$CHECK_FAILED" = 0 ]; then say "DOCTOR PASSED: all necessary items pass."; exit 0; fi
say "DOCTOR FAILED: one or more necessary items fail (see the FAIL lines; docs/INSTALL_AGX.md, Troubleshooting)."
exit 1
