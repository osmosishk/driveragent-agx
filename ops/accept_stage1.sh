#!/usr/bin/env bash
# Acceptance check of the AGX02 cleanup stage 1 and of the start at boot (task "AGX02 cleanup stage 1 and start
# at boot", section 5). The script changes nothing on the machine: it reads systemd, docker, /proc, sysfs, the
# model store, the power log and the dashboard API (password of .env, never printed). It writes only the file of
# --save. It never prints a password, a token or a pairing code.
#
# Usage: ops/accept_stage1.sh [--save FILE] [--before FILE] [--da01 FILE] [--instance agx]
#   --save FILE    write the measured values (JSON) to FILE (use it before stage 1: the "before" values)
#   --before FILE  compare with the values of an earlier --save (items 7 and 8)
#   --da01 FILE    JSON from DA01 (link DOWN time, first result per camera, rk restarts, results/s, capture-to-
#                  result p50/p95, stale results; before and after). Items 1 and 8 need it.
#
# Items (section 5): 1 link back without a person; 2 units started at boot through linger; 3 last good set active,
# agx-sim not active; 4 pairing valid, model control request from the rk console accepted; 5 old stack not active;
# 6 rule Z3 items active; 7 compare with the state before; 8 link numbers agree with the values before.
# Output: one line per check, PASS / FAIL / INFO / SKIP. Exit 0 only when no check fails.
# Run it 15 min or more after a boot: item 7 uses a 10-min power mean, item 6 needs NTP synchronised.
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/lib/common.sh"

INSTANCE=$DEF_INSTANCE; SAVE=""; BEFORE_F=""; DA01_F=""
usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --instance) INSTANCE="${2:-}"; shift 2 ;;
    --save) SAVE="${2:-}"; shift 2 ;;
    --before) BEFORE_F="${2:-}"; shift 2 ;;
    --da01) DA01_F="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
done
check_instance_name "$INSTANCE"
say "accept_stage1: instance $INSTANCE, repo $REPO, host $(hostname), $(date '+%Y-%m-%d %H:%M:%S %Z')"

exec "$SYS_PY" - "$REPO" "$INSTANCE" "$SAVE" "$BEFORE_F" "$DA01_F" <<'EOF'
import base64, glob, json, os, re, sqlite3, subprocess, sys, time, urllib.request

repo, inst, save_f, before_f, da01_f = sys.argv[1:6]
HOME = os.path.expanduser("~")
failed = []
V = {"t": time.time()}   # measured values (--save)


def item(level, n, name, text):
    if level == "FAIL":
        failed.append(f"{n} {name}")
    print(f"{level:4s} {n:3s} {name:30s} {text}", flush=True)


def sh(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    return r.stdout.strip()


def uprop(u, p):
    return sh("systemctl", "--user", "show", "-p", p, "--value", u)


def sprop(u, p):
    return sh("systemctl", "show", "-p", p, "--value", u)


def load_json(f):
    if not f:
        return None
    with open(f, encoding="utf-8") as fh:
        return json.load(fh)


before = load_json(before_f)
da01 = load_json(da01_f)

# ---------------------------------------------------------------- boot facts
boot_t = time.time() - float(open("/proc/uptime").read().split()[0])
V["boot_t"] = boot_t
V["boot_target"] = sh("systemctl", "get-default")
print(f"INFO     boot                           boot at {time.strftime('%F %T %Z', time.localtime(boot_t))}, "
      f"default target {V['boot_target']}")

# ---------------------------------------------------------------- dashboard API (password stays here)
env = {}
try:
    with open(os.path.join(repo, ".env"), encoding="utf-8") as f:
        for ln in f:
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.rstrip("\n").split("=", 1)
                env[k.strip()] = v.strip()
except OSError:
    pass
port = 8700
try:
    port = int(open(os.path.join(repo, "data", "dashboard_port")).read().strip() or port)
except (OSError, ValueError):
    pass
auth = "Basic " + base64.b64encode(("%s:%s" % (env.get("AGX_DASH_USER") or "agx",
                                                env.get("AGX_DASH_PASSWORD") or "")).encode()).decode()


def get(path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Authorization": auth})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


try:
    health = get("/api/health")
except Exception as e:  # noqa: BLE001
    health = None
    print(f"INFO     dashboard                      /api/health: {type(e).__name__}: {e}")
try:
    pair = get("/api/pair/state")
except Exception as e:  # noqa: BLE001
    pair = None
    print(f"INFO     dashboard                      /api/pair/state: {type(e).__name__}: {e}")
board = None
if pair:
    board = next((b for b in pair.get("boards") or [] if isinstance(b, dict) and b.get("id") == "rk3588-da01"), None)

# ---------------------------------------------------------------- 1. link back with no action by a person
if board and board.get("link_state") == "UP":
    item("PASS", "1a", "link UP (AGX view)", f"rk3588-da01: {board.get('link_state')} ({board.get('link_detail')})")
else:
    item("FAIL", "1a", "link UP (AGX view)", f"rk3588-da01: {board.get('link_state') if board else 'no paired board'}"
         f" ({board.get('link_detail') if board else '-'})")
if da01 is None:
    item("SKIP", "1b", "DOWN -> first result (DA01)", "needs --da01 FILE (measured on DA01)")
else:
    a = da01.get("after") or {}
    first = a.get("first_result_t") or {}
    down = a.get("down_t")
    restarts = a.get("rk_unit_restarts")
    ok = bool(down) and len(first) == 6 and restarts == 0
    gaps = ", ".join(f"cam{c} {t - down:.1f} s" for c, t in sorted(first.items())) if down else "-"
    item("PASS" if ok else "FAIL", "1b", "DOWN -> first result (DA01)",
         f"DOWN at {time.strftime('%T', time.localtime(down)) if down else '?'}; first result: {gaps or 'none'}; "
         f"restarts of rk units on DA01 during the reboot: {restarts}")

# ---------------------------------------------------------------- 2. units started at boot through linger
linger = sh("loginctl", "show-user", os.environ.get("USER", "tonyho"), "-p", "Linger", "--value")
item("PASS" if linger == "yes" else "FAIL", "2a", "linger", f"Linger={linger or '?'}")
def mono(v):   # systemd ...TimestampMonotonic (us since boot) -> s since boot; None when not set
    try:
        return int(v) / 1e6 if int(v) > 0 else None
    except ValueError:
        return None


# Times as seconds since boot (monotonic): the wall clock can step after boot (NTP), the monotonic clock cannot.
um = mono(sprop(f"user@{os.getuid()}.service", "ActiveEnterTimestampMonotonic"))


def first_line(*args):   # first journal line of this boot as seconds after boot (short-monotonic)
    for ln in sh("journalctl", "-b", "-o", "short-monotonic", "--no-pager", *args).splitlines():
        m = re.match(r"\[\s*([0-9.]+)\]", ln)
        if m:
            return float(m.group(1))
    return None


# With linger, logind starts user@<uid> at boot, before any session. Without linger, only a session (the GNOME
# auto-login or an SSH login) starts it. Proof: the user manager is up before the first logind session.
first_session = first_line("-u", "systemd-logind", "-g", f"New session .* of user {os.environ.get('USER', 'tonyho')}")
first_ssh = first_line("-u", "ssh", "-g", "Accepted")
sess_txt = (f"first session {first_session:.1f} s after boot" if first_session is not None else "no session found")
ok_um = um is not None and linger == "yes" and (first_session is None or um < first_session)
item("PASS" if ok_um else "FAIL", "2b", "user manager before sessions",
     f"user@{os.getuid()} up {f'{um:.1f} s after boot' if um is not None else '?'}; {sess_txt}; "
     f"first SSH login {f'{first_ssh:.1f} s after boot' if first_ssh is not None else 'none'}")
for t in ("infer", "dashboard"):
    u = f"{inst}-{t}.service"
    st, frag = uprop(u, "ActiveState"), uprop(u, "FragmentPath")
    start = first_line("--user", "-u", u, "-g", "^Started ")
    nr = uprop(u, "NRestarts")
    en = sh("systemctl", "--user", "is-enabled", u)
    transient = uprop(u, "Transient") == "yes"
    V[f"{t}_start_s_after_boot"] = start
    ok = (st == "active" and not transient and en == "enabled" and start is not None
          and (first_ssh is None or start < first_ssh) and (first_session is None or start < first_session + 120))
    item("PASS" if ok else "FAIL", "2c" if t == "infer" else "2d", f"{u} at boot",
         f"{st}, {'TRANSIENT' if transient else 'unit file ' + frag}, {en}; first start "
         f"{f'{start:.1f} s after boot' if start is not None else 'not in this boot'}; restarts {nr}")

# ---------------------------------------------------------------- 3. last good set active, agx-sim not active
store = os.path.join(HOME, "agx-models")
want = {("driverguard_yolopx", "1"): [0, 1, 2, 3, 4, 5], ("driverguard_dtcp", "1"): [0]}
try:
    act = json.load(open(os.path.join(store, "_state", "active.json")))
    got = {(s["name"], str(s["version"])): sorted(s.get("cameras") or []) for s in act.get("set") or []}
except (OSError, ValueError, KeyError) as e:
    got, act = {}, {}
    print(f"INFO     model store                    active.json: {e}")
running = {m.get("name"): m for m in ((health or {}).get("infer") or {}).get("models") or [] if isinstance(m, dict)}
ok = got == want and all(running.get(n, {}).get("state") == "RUNNING" for n, _v in want)
item("PASS" if ok else "FAIL", "3a", "last good set active",
     "active.json: " + (", ".join(f"{n}@{v} cams {c}" for (n, v), c in sorted(got.items())) or "none") + "; agx-infer: "
     + (", ".join(f"{n} {m.get('state')} {m.get('fps')} fps" for n, m in running.items()
                  if m.get("state") != "OFF") or "no model running"))
sim = sh("systemctl", "--user", "is-active", f"{inst}-sim.service")
item("PASS" if sim != "active" else "FAIL", "3b", f"{inst}-sim not active", f"{inst}-sim: {sim or 'not loaded'}")

# ---------------------------------------------------------------- 4. pairing valid, model control request accepted
if board:
    item("PASS", "4a", "pairing rk3588-da01", f"paired, addresses {board.get('addresses')}, last seen "
         f"{time.time() - (board.get('last_seen_t') or 0):.1f} s ago from {board.get('last_seen_addr')}")
else:
    item("FAIL", "4a", "pairing rk3588-da01", "no paired board rk3588-da01 in /api/pair/state")
acc = None
CONTROL = ("activate", "deactivate", "rollback")   # model control actions of the controller audit
try:
    for ln in open(os.path.join(store, "_state", "audit.jsonl"), encoding="utf-8"):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("source") == "rk-console" and e.get("t", 0) >= boot_t and e.get("action") in CONTROL:
            acc = e if e.get("result") == "ok" else (acc or e)
except OSError:
    pass
last_txt = f"{acc.get('action')} -> {acc.get('result')}" if acc else "none"
if acc and acc.get("result") == "ok":
    item("PASS", "4b", "control request from rk console", f"{acc.get('time')}: {acc.get('action')} "
         f"{acc.get('model') or ''} -> {acc.get('result')}")
else:
    item("FAIL", "4b", "control request from rk console",
         f"no accepted model request from the rk console after boot (last: {last_txt})")

# ---------------------------------------------------------------- 5. old stack not active
OLD_UNITS = ["nvargus-daemon.service", "bluetooth.service", "ModemManager.service", "kerneloops.service",
             "apport-autoreport.path", "apport-autoreport.timer", "apport.service", "rpcbind.socket", "rpcbind.service",
             "lpd.service", "packagekit.service", "snap.cups.cupsd.service", "snap.cups.cups-browsed.service"]
states = {u: (sh("systemctl", "is-enabled", u) or "-", sh("systemctl", "is-active", u) or "-") for u in OLD_UNITS}
cont = sh("docker", "inspect", "-f", "{{.HostConfig.RestartPolicy.Name}} {{.State.Status}}", "driveragent-valhalla")
oldp = []
for d in glob.glob("/proc/[0-9]*"):
    try:
        cmd = open(d + "/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        continue
    if "/home/tonyho/driveragent/" in cmd or "valhalla_service" in cmd or "start-driveragent" in cmd:
        oldp.append(f"{d[6:]}:{cmd[:60]}")
act_units = [u for u, (e, a) in states.items() if a in ("active", "activating", "reloading")
             or e not in ("disabled", "masked", "-", "not-found")]
ok = not act_units and not cont.endswith("running") and not oldp
item("PASS" if ok else "FAIL", "5", "old stack not active",
     "; ".join(f"{u} {e}/{a}" for u, (e, a) in states.items()) + f"; container driveragent-valhalla: {cont or 'not found'}"
     + f"; old-stack processes: {', '.join(oldp) or 'none'}")

# ---------------------------------------------------------------- 6. rule Z3 items active
KEEP = {"ssh.service": "active", "NetworkManager.service": "active", "wpa_supplicant.service": "active",
        "systemd-resolved.service": "active", "tailscaled.service": "active", "systemd-timesyncd.service": "active",
        "nvpmodel.service": "enabled", "nvfancontrol.service": "active", "jtop.service": "active",
        "docker.service": "active", "containerd.service": "active", "nxserver.service": "active"}
bad, txt = [], []
for u, need in KEEP.items():
    e, a = sh("systemctl", "is-enabled", u), sh("systemctl", "is-active", u)
    txt.append(f"{u.removesuffix('.service')} {e}/{a}")
    if (need == "active" and a != "active") or e not in ("enabled", "static", "alias"):
        bad.append(u)
nvp = sprop("nvpmodel.service", "Result")
if nvp != "success":
    bad.append(f"nvpmodel.service Result={nvp}")
txt.append(f"nvpmodel mode {sh('nvpmodel', '-q').splitlines()[0] if sh('nvpmodel', '-q') else '?'}")
ntp = sh("timedatectl", "show", "-p", "NTPSynchronized", "--value")
ts_ip = sh("tailscale", "ip", "-4")
item("PASS" if not bad and ntp == "yes" else "FAIL", "6", "rule Z3 items active",
     "; ".join(txt) + f"; NTPSynchronized={ntp}; tailscale ip {'present' if ts_ip else 'none'}"
     + (f"; NOT OK: {', '.join(bad)}" if bad else ""))

# ---------------------------------------------------------------- 7. compare with the state before
mem = {}
for ln in open("/proc/meminfo"):
    k, v = ln.split(":", 1)
    mem[k] = int(v.split()[0])
V["mem_used_mib"] = round((mem["MemTotal"] - mem["MemAvailable"]) / 1024)
gpu_shared = None
try:
    from jtop import jtop   # jtop service (jetson-stats): RAM "shared" = GPU memory (NvMap)
    with jtop() as j:
        gpu_shared = round(j.memory["RAM"]["shared"] / 1024)
except Exception:  # noqa: BLE001
    pass
V["gpu_mem_mib"] = gpu_shared
try:
    c = sqlite3.connect(f"file:{repo}/data/power.sqlite?mode=ro", uri=True)
    r = c.execute("select avg(mw), count(*) from s1 where series=(select id from series where key='agx02') and t>?",
                  (time.time() - 600,)).fetchone()
    V["power_w_10min"] = round(r[0] / 1000, 2) if r[0] else None
except sqlite3.Error:
    V["power_w_10min"] = None
V["temps_c"] = {}
for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
    try:
        t = int(open(z + "/temp").read()) / 1000
        if t > -40:
            V["temps_c"][open(z + "/type").read().strip()] = round(t, 1)
    except Exception:  # noqa: BLE001  (some zones give no value: skip them)
        pass
V["models_running"] = sorted(n for n, m in running.items() if m.get("state") == "RUNNING")
if da01 and (da01.get("after") or {}).get("link_up_t"):
    V["boot_to_link_up_s"] = round(da01["after"]["link_up_t"] - boot_t, 1)
txt = (f"memory in use {V['mem_used_mib']} MiB; GPU memory {gpu_shared} MiB; power {V['power_w_10min']} W "
       f"(10 min mean, rails); temps {V['temps_c']}; target {V['boot_target']}; boot -> link UP "
       f"{V.get('boot_to_link_up_s', '?')} s; models {V['models_running']}")
if before is None:
    item("INFO", "7", "state now", txt + " (no --before file: no comparison)")
else:
    b = before
    checks = []
    if b.get("mem_used_mib") is not None:
        checks.append(("memory", V["mem_used_mib"] <= b["mem_used_mib"] + 512,
                       f"memory {b['mem_used_mib']} -> {V['mem_used_mib']} MiB"))
    if b.get("gpu_mem_mib") is not None and gpu_shared is not None:
        checks.append(("gpu", gpu_shared <= b["gpu_mem_mib"] + 256, f"GPU memory {b['gpu_mem_mib']} -> {gpu_shared} MiB"))
    if b.get("power_w_10min") and V["power_w_10min"]:
        checks.append(("power", V["power_w_10min"] <= b["power_w_10min"] + 2.0,
                       f"power {b['power_w_10min']} -> {V['power_w_10min']} W"))
    tb, ta = max((b.get("temps_c") or {}).values(), default=None), max(V["temps_c"].values(), default=None)
    if tb is not None and ta is not None:
        checks.append(("temp", ta <= tb + 5.0, f"max temperature {tb} -> {ta} C"))
    checks.append(("target", V["boot_target"] == b.get("boot_target"),
                   f"target {b.get('boot_target')} -> {V['boot_target']}"))
    checks.append(("models", V["models_running"] == b.get("models_running"),
                   f"models {b.get('models_running')} -> {V['models_running']}"))
    item("PASS" if all(ok for _n, ok, _t in checks) else "FAIL", "7", "compare with before",
         "; ".join(t + ("" if ok else " (NOT OK)") for _n, ok, t in checks)
         + f"; boot -> link UP {V.get('boot_to_link_up_s', '?')} s")

# ---------------------------------------------------------------- 8. link numbers agree with the values before
if da01 is None or not da01.get("before") or not da01.get("after"):
    item("SKIP", "8", "results/s, c2r, stale (DA01)", "needs --da01 FILE with 'before' and 'after'")
else:
    b8, a8 = da01["before"], da01["after"]
    out, ok = [], True
    for k, tol in (("results_per_s", 0.1),):
        for inst_name, vb in (b8.get(k) or {}).items():
            va = (a8.get(k) or {}).get(inst_name)
            good = va is not None and va >= vb * (1 - tol)
            ok &= good
            out.append(f"{inst_name} {vb} -> {va}/s" + ("" if good else " (NOT OK)"))
    for k, add in (("c2r_p50_ms", 5.0), ("c2r_p95_ms", 10.0)):
        vb, va = b8.get(k), a8.get(k)
        if vb is not None:
            good = va is not None and va <= vb * 1.2 + add
            ok &= good
            out.append(f"{k} {vb} -> {va}" + ("" if good else " (NOT OK)"))
    sb, sa = b8.get("stale_per_min"), a8.get("stale_per_min")
    good = sa is not None and sa <= (sb or 0) + 1
    ok &= good
    out.append(f"stale/min {sb} -> {sa}" + ("" if good else " (NOT OK)"))
    item("PASS" if ok else "FAIL", "8", "results/s, c2r, stale (DA01)", "; ".join(out))

if save_f:
    with open(save_f, "w", encoding="utf-8") as f:
        json.dump(V, f, indent=1)
    print(f"INFO     save                           values written to {save_f}")
print("")
print("ACCEPTANCE " + ("PASSED: no check fails." if not failed else f"FAILED: {', '.join(failed)}"))
sys.exit(1 if failed else 0)
EOF
