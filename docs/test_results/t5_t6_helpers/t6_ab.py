"""T6 a+b: stop agx-sim, poll /api/cameras every 100 ms; start agx-sim again, poll until SIMULATED."""
import subprocess, time, json, sys
sys.path.insert(0, "/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad")
import dash
SVC = "/home/tonyho/driveragent-agx/tools/svc.sh"
def poll(t_ref, seconds, target, log):
    first, lft, prev = {}, {}, {}
    t_end = time.time() + seconds
    while time.time() < t_end:
        t0 = time.time()
        try:
            d = dash.get("/api/cameras")
        except Exception as e:  # noqa
            log.append(f"{t0 - t_ref:+.3f} GET error {e}"); time.sleep(0.1); continue
        t1 = time.time()
        for c in d["cameras"]:
            cam = c["cam"]
            if prev.get(cam) != c["state"]:
                log.append(f"{t1 - t_ref:+.3f} s cam{cam} {prev.get(cam)} -> {c['state']} (last_frame_t {c.get('last_frame_t')}, frame_age_ms {c.get('frame_age_ms')}, server_t {d['server_t']:.3f}, status_t {d.get('status_t')})")
                prev[cam] = c["state"]
            if c["state"] == target and cam not in first:
                first[cam] = (t1, c.get("last_frame_t"), d["server_t"])
        if target == "SIMULATED" and len(first) == 6 and t1 - t_ref > 2: break
        time.sleep(max(0, 0.1 - (time.time() - t0)))
    return first
out = []
# a. NO SIGNAL
d0 = dash.get("/api/cameras")
out.append("before stop: " + " ".join(f"cam{c['cam']}:{c['state']}" for c in d0["cameras"]) + f" hold_s={d0['hold_s']} hold_cap_s={d0['hold_cap_s']} stale_s={d0['stale_s']} no_signal_s={d0['no_signal_s']}")
T0 = time.time()
r = subprocess.run([SVC, "stop", "sim"], capture_output=True, text=True)
T0e = time.time()
out.append(f"T0 = {T0:.3f} (before 'svc.sh stop sim'); stop command returned after {T0e - T0:.3f} s, rc {r.returncode} {r.stdout.strip()} {r.stderr.strip()}")
log = []
first = poll(T0, 5.0, "NO SIGNAL", log)
out += ["state changes (time after T0):"] + log
out.append("a. NO SIGNAL table: cam | time after T0 (s) | last_frame_t after T0 (s) | NO SIGNAL after last_frame_t (s)")
for cam in range(6):
    if cam in first:
        t1, lft, st = first[cam]
        out.append(f"   cam{cam} | {t1 - T0:.3f} | {lft - T0:+.3f} | {t1 - lft:.3f}")
    else:
        out.append(f"   cam{cam} | not NO SIGNAL in 5 s | - | -")
out.append(f"max time after T0: {max(first[c][0] - T0 for c in first):.3f} s, all six: {len(first) == 6}")
# b. start again
T1 = time.time()
r = subprocess.run([SVC, "start", "sim", "--sessions", "road"], capture_output=True, text=True)
T1e = time.time()
out.append(f"T1 = {T1:.3f} (before 'svc.sh start sim --sessions road'); start command returned after {T1e - T1:.3f} s, rc {r.returncode} {r.stdout.strip()} {r.stderr.strip()}")
log = []
first = poll(T1, 15.0, "SIMULATED", log)
out += ["state changes (time after T1):"] + log
out.append("b. SIMULATED again table: cam | time after T1 (s) | last_frame_t after T1 (s)")
for cam in range(6):
    if cam in first:
        t1, lft, st = first[cam]
        out.append(f"   cam{cam} | {t1 - T1:.3f} | {lft - T1:+.3f}")
    else:
        out.append(f"   cam{cam} | not SIMULATED in 15 s | -")
if first:
    out.append(f"max time after T1: {max(first[c][0] - T1 for c in first):.3f} s, all six: {len(first) == 6}")
print("\n".join(out))
