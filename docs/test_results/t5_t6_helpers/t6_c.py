"""T6 c: stop driverguard_dtcp with model_ctl, poll /api/models 15 s, start it again."""
import subprocess, time, sys, os
sys.path.insert(0, "/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad")
import dash
P = "/home/tonyho/driveragent-agx"
env = dict(os.environ, PYTHONPATH=P)
def ctl(*a):
    r = subprocess.run([f"{P}/.venv/bin/python", "-m", "tools.model_ctl", *a], capture_output=True, text=True, cwd=P, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()
def row(t_ref):
    d = dash.get("/api/models")
    m = {x["name"]: x for x in d["models"]}
    a, b = m["driverguard_dtcp"], m["driverguard_yolopx"]
    return (f"{time.time() - t_ref:6.2f} s | dtcp {a['state']:8} fps {a['fps']:5.1f} results_total {a['results_total']:6} | "
            f"yolopx {b['state']:8} fps {b['fps']:5.1f} results_total {b['results_total']:6}"), a, b
t = time.time()
print("before:", row(t)[0])
rc, o = ctl("stop", "driverguard_dtcp"); T = time.time()
print(f"$ python -m tools.model_ctl stop driverguard_dtcp  (rc {rc})\n{o}")
ok = True; prev_total = None; dtcp_total0 = None; fails = []
while time.time() - T < 15:
    s, a, b = row(T); print(s)
    if time.time() - T > 2:   # allow 2 s for the status to show the change
        if a["state"] != "OFF": fails.append(f"dtcp {a['state']} at {s[:8]}")
        if b["state"] != "RUNNING" or not b["fps"] > 0: fails.append(f"yolopx {b['state']} fps {b['fps']}")
        if prev_total is not None and b["results_total"] <= prev_total: fails.append(f"yolopx results_total not increasing at {s[:8]}")
        if dtcp_total0 is None: dtcp_total0 = a["results_total"]
        elif a["results_total"] != dtcp_total0: fails.append("dtcp results_total changes while OFF")
    prev_total = b["results_total"]
    time.sleep(1.0)
print("check while stopped:", "PASS" if not fails else f"FAIL {fails}")
rc, o = ctl("start", "driverguard_dtcp"); T = time.time()
print(f"$ python -m tools.model_ctl start driverguard_dtcp  (rc {rc})\n{o}")
running_at = None
while time.time() - T < 20:
    s, a, b = row(T); print(s)
    if a["state"] == "RUNNING" and a["fps"] > 0 and running_at is None:
        running_at = time.time() - T
    if running_at is not None and time.time() - T > running_at + 2: break
    time.sleep(0.5)
print(f"dtcp RUNNING with fps > 0 again after {running_at:.2f} s" if running_at is not None else "dtcp NOT RUNNING in 20 s")
rc, o = ctl("list"); print(f"$ python -m tools.model_ctl list  (rc {rc})\n{o}")
