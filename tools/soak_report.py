"""Summarise a soak run: system samples (tools.sysmon), node status (tools.status_log), client summary.

  python -m tools.soak_report --sysmon S.jsonl --status T.jsonl [--client C.json] [--out report.md]

Memory: start = mean of the first 60 s, end = mean of the last 60 s, slope = least-squares fit over the
whole run in MB per hour. A leak shows as a positive slope that is large against the noise.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import defaultdict


def _load(path):
    out = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    return out


def _slope_per_h(ts, ys):
    pts = [(t, y) for t, y in zip(ts, ys) if y is not None]
    if len(pts) < 3:
        return None
    mt = st.fmean(t for t, _ in pts)
    my = st.fmean(y for _, y in pts)
    den = sum((t - mt) ** 2 for t, _ in pts)
    if den == 0:
        return None
    return sum((t - mt) * (y - my) for t, y in pts) / den * 3600.0


def _window(ts, ys, first=True, span=60.0):
    pts = [(t, y) for t, y in zip(ts, ys) if y is not None]
    if not pts:
        return None
    if first:
        t0 = pts[0][0]
        sel = [y for t, y in pts if t - t0 <= span]
    else:
        t1 = pts[-1][0]
        sel = [y for t, y in pts if t1 - t <= span]
    return st.fmean(sel) if sel else None


def _f(x, nd=1):
    return "n/a" if x is None else f"{x:.{nd}f}"


def _stats(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None, None, None
    return st.fmean(v), min(v), max(v)


def report(sysmon, status, client=None) -> str:
    L = []
    ts = [s["t"] for s in sysmon]
    dur = (ts[-1] - ts[0]) if len(ts) > 1 else 0
    L.append(f"Samples: sysmon {len(sysmon)} (1 s), status {len(status)}. Duration {dur/60:.1f} min.")
    L.append("")
    # ---- system
    L.append("| System value | mean | min | max | start (first 60 s) | end (last 60 s) | slope per hour |")
    L.append("|---|---|---|---|---|---|---|")
    for key, name, nd in (("cpu_pct", "CPU total %", 1), ("gpu_load_pct", "GPU load %", 1),
                          ("ram_used_mb", "RAM used MB", 0), ("power_total_w", "Power (sum of rails) W", 2)):
        ys = [s.get(key) for s in sysmon]
        m, lo, hi = _stats(ys)
        sl = _slope_per_h(ts, ys) if key == "ram_used_mb" else None
        L.append(f"| {name} | {_f(m, nd)} | {_f(lo, nd)} | {_f(hi, nd)} | {_f(_window(ts, ys), nd)} | "
                 f"{_f(_window(ts, ys, False), nd)} | {_f(sl, 1) + ' MB/h' if sl is not None else '-'} |")
    zones = sorted({z for s in sysmon for z in (s.get("temps_c") or {})})
    for z in zones:
        ys = [(s.get("temps_c") or {}).get(z) for s in sysmon]
        m, lo, hi = _stats(ys)
        L.append(f"| Temperature {z} C | {_f(m)} | {_f(lo)} | {_f(hi)} | {_f(_window(ts, ys))} | "
                 f"{_f(_window(ts, ys, False))} | - |")
    rails = sorted({r for s in sysmon for r in (s.get("power_w") or {})})
    for r in rails:
        ys = [(s.get("power_w") or {}).get(r) for s in sysmon]
        m, lo, hi = _stats(ys)
        L.append(f"| Power {r} W | {_f(m, 2)} | {_f(lo, 2)} | {_f(hi, 2)} | - | - | - |")
    L.append("")
    # ---- processes
    L.append("| Process | RSS start MB | RSS end MB | RSS max MB | RSS slope per hour | CPU % of one core (mean / max) | restarts seen (pid changes) |")
    L.append("|---|---|---|---|---|---|---|")
    for key in ("infer.main", "tools.rk_sim", "dashboard.main"):
        rss, cpu, pids = [], [], []
        for s in sysmon:
            pl = (s.get("procs") or {}).get(key) or []
            if pl:
                rss.append(sum(p.get("rss_mb", 0) for p in pl))
                cpu.append(sum(p.get("cpu_pct", 0) for p in pl))
                pids.append(tuple(sorted(p.get("pid") for p in pl)))
            else:
                rss.append(None)
                cpu.append(None)
        changes = sum(1 for a, b in zip(pids, pids[1:]) if a != b)
        sl = _slope_per_h(ts, rss)
        m, _, hi = _stats(cpu)
        _, _, rhi = _stats(rss)
        L.append(f"| {key} | {_f(_window(ts, rss))} | {_f(_window(ts, rss, False))} | {_f(rhi)} | "
                 f"{_f(sl) + ' MB/h' if sl is not None else 'n/a'} | {_f(m)} / {_f(hi)} | {changes} |")
    L.append("")
    # ---- cameras from status
    if status:
        cams = defaultdict(lambda: {"fps": [], "states": defaultdict(int), "first": None, "last": None})
        models = defaultdict(lambda: {"fps": [], "p50": [], "p95": [], "p99": [], "states": defaultdict(int),
                                      "first": None, "last": None, "errors": set()})
        node_states = defaultdict(int)
        node_errors = set()
        for s in status:
            node_states[(s.get("node") or {}).get("state")] += 1
            for e in (s.get("node") or {}).get("errors") or []:
                node_errors.add(str(e)[:160])
            for c in s.get("cameras") or []:
                k = c.get("cam")
                cams[k]["fps"].append(c.get("fps"))
                cams[k]["states"][c.get("state")] += 1
                cams[k]["first"] = cams[k]["first"] or c
                cams[k]["last"] = c
            for m in s.get("models") or []:
                k = m.get("name")
                tot = (m.get("lat_ms") or {}).get("total") or {}
                models[k]["fps"].append(m.get("fps"))
                for q in ("p50", "p95", "p99"):
                    models[k][q].append(tot.get(q))
                models[k]["states"][m.get("state")] += 1
                models[k]["first"] = models[k]["first"] or m
                models[k]["last"] = m
                if m.get("error"):
                    models[k]["errors"].add(str(m.get("error"))[:160])
        L.append("| Camera | fps mean / min / max | states (samples) | lost frames (delta) | lost packets (delta) | ring overruns (delta) |")
        L.append("|---|---|---|---|---|---|")
        for k in sorted(cams, key=lambda x: (x is None, x)):
            c = cams[k]
            m, lo, hi = _stats(c["fps"])

            def d(field):
                a = (c["first"] or {}).get(field)
                b = (c["last"] or {}).get(field)
                return "n/a" if a is None or b is None else str(b - a)
            stx = ", ".join(f"{s}: {n}" for s, n in sorted(c["states"].items(), key=lambda x: str(x[0])))
            L.append(f"| cam{k} | {_f(m)} / {_f(lo)} / {_f(hi)} | {stx} | {d('lost_frames')} | "
                     f"{d('lost_packets')} | {d('ring_overruns')} |")
        L.append("")
        L.append("| Model | fps mean / min / max | total latency ms p50 / p95 / p99 (mean of 1 s values) | states (samples) | results (delta) | errors |")
        L.append("|---|---|---|---|---|---|")
        for k in sorted(models):
            mm = models[k]
            m, lo, hi = _stats(mm["fps"])
            p50 = _stats(mm["p50"])[0]
            p95 = _stats(mm["p95"])[0]
            p99 = _stats(mm["p99"])[0]
            a = (mm["first"] or {}).get("results_total")
            b = (mm["last"] or {}).get("results_total")
            stx = ", ".join(f"{s}: {n}" for s, n in sorted(mm["states"].items(), key=lambda x: str(x[0])))
            L.append(f"| {k} | {_f(m)} / {_f(lo)} / {_f(hi)} | {_f(p50)} / {_f(p95)} / {_f(p99)} | {stx} | "
                     f"{'n/a' if a is None or b is None else b - a} | {'; '.join(sorted(mm['errors'])) or 'none'} |")
        L.append("")
        L.append("Node states (samples): " + ", ".join(f"{s}: {n}" for s, n in node_states.items()))
        L.append("Node errors seen: " + ("; ".join(sorted(node_errors)) if node_errors else "none"))
        L.append("")
    if client:
        L.append("Client summary (tools.rk_result_client): see the JSON file. Key values:")
        for k in ("exit_code", "rejects", "duplicates", "status_interval"):
            if k in client:
                L.append(f"- {k}: {json.dumps(client[k])[:300]}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sysmon", required=True)
    ap.add_argument("--status", required=True)
    ap.add_argument("--client")
    ap.add_argument("--out")
    a = ap.parse_args()
    sysmon = _load(a.sysmon)
    status = _load(a.status)
    client = None
    if a.client:
        try:
            client = json.load(open(a.client))
        except (OSError, ValueError):
            client = None
    if not sysmon:
        print("no sysmon samples", file=sys.stderr)
        return 1
    txt = report(sysmon, status, client)
    if a.out:
        open(a.out, "w").write(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
