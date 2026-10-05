"""T6 d: GET /api/health, /api/link, /api/services, /api/services/logs (excerpts). SIMULATED data."""
import json, sys, time, urllib.error
sys.path.insert(0, "/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad")
import dash
def get(path):
    try:
        st, b = dash.get(path, raw=True, timeout=15)
    except urllib.error.HTTPError as e:
        st, b = e.code, e.read()
    print(f"=== GET {path} -> HTTP {st}, {len(b)} B ===")
    return json.loads(b)
print("time", time.strftime("%Y-%m-%d %H:%M:%S"))
h = get("/api/health")
pick = {k: h.get(k) for k in ("schema", "hostname", "time_iso", "age_s", "stale", "node_state", "node_state_reasons", "infer_state", "infer_reason", "simulated", "errors")}
print(json.dumps(pick))
inf = h["infer"]
print("infer:", json.dumps({k: inf.get(k) for k in ("state", "simulated", "version", "uptime_s", "age_s")}))
print("infer.cameras_summary.states:", json.dumps(inf["cameras_summary"]["states"]))
print("gpu:", json.dumps(h["gpu"]), "| temps.max_c:", h["temps"]["max_c"], h["temps"]["max_zone"], "| ram pct:", h["ram"]["pct"])
l = get("/api/link")
print(json.dumps({k: v for k, v in l.items() if k != "ping_history"}))
print(f"ping_history: {len(l.get('ping_history') or [])} entries")
s = get("/api/services")
print("summary:", json.dumps(s["summary"]))
for u in s["units"]["user"]:
    print(f"  user unit {u['id']:24} {u['active_state']}/{u['sub_state']}  pid {u['main_pid']}  restarts {u['n_restarts']}  started {u['started']}")
d = get("/api/services/logs?unit=not-a-unit")
print(json.dumps(d))
for unit in d.get("allowed") or []:
    if not unit.startswith("agx-"): continue
    r = get(f"/api/services/logs?unit={unit}")
    lines = r.get("lines") if isinstance(r, dict) else r
    print(f"   keys {list(r.keys()) if isinstance(r, dict) else type(r).__name__}; lines: {len(lines) if isinstance(lines, list) else lines}")
    for x in (lines or [])[-2:] if isinstance(lines, list) else []:
        print("   |", (x if isinstance(x, str) else json.dumps(x))[:200])
