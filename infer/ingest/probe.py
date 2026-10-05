"""Ingest probe: start the ingest, print camera status every 5 s, write a JSON summary at the end.

  python -m infer.ingest.probe --config config/sources.yaml --seconds 60 [--json out.json] [--mode file]

Samples every 1 s: camera metrics, CPU % (total, this process, simulator process tools.rk_sim if it
runs), GPU load %, RAM used MB, temperatures.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

import psutil

from infer.ingest.ingest import Ingest

GPU_LOAD = "/sys/devices/platform/bus@0/17000000.gpu/load"
THERMAL = "/sys/devices/virtual/thermal"


def gpu_load_pct() -> float | None:
    try:
        with open(GPU_LOAD) as fh:
            return int(fh.read().strip()) / 10.0
    except (OSError, ValueError):
        return None


def ram_used_mb() -> float | None:
    try:
        kv = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, v = line.split(":", 1)
                kv[k] = int(v.split()[0])
        return round((kv["MemTotal"] - kv["MemAvailable"]) / 1024.0, 1)
    except (OSError, KeyError, ValueError):
        return None


def temps_c() -> dict:
    out = {}
    try:
        for z in sorted(os.listdir(THERMAL)):
            if not z.startswith("thermal_zone"):
                continue
            try:
                with open(f"{THERMAL}/{z}/type") as fh:
                    name = fh.read().strip()
                with open(f"{THERMAL}/{z}/temp", "rb") as fh:
                    t = int(fh.read().strip()) / 1000.0
            except Exception:  # noqa: BLE001 - some zones fail to read (sensor off)
                continue
            if -40 < t < 150:
                out[name] = t
    except OSError:
        pass
    return out


def find_sim_procs() -> list[psutil.Process]:
    me = os.getpid()
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            argv = p.info["cmdline"] or []
            cl = " ".join(argv)
        except (psutil.Error, TypeError):
            continue
        if p.info["pid"] != me and argv and "python" in os.path.basename(argv[0]) and \
                "tools.rk_sim" in cl and "infer.ingest.probe" not in cl and "pytest" not in cl:
            out.append(p)
    return out


def _stats(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return {"avg": None, "min": None, "max": None, "n": 0}
    return {"avg": round(sum(v) / len(v), 2), "min": round(min(v), 2), "max": round(max(v), 2),
            "n": len(v)}


def _fmt(x, f="{:.1f}", none="-"):
    return none if x is None else f.format(x)


def line(s: dict) -> str:
    d = s["decode_ms"]
    return (f"cam{s['cam']} {s['role']:<10} {s['state']:<9} fps {s['fps']:4.1f} "
            f"kbit/s {s['bitrate_kbps']:8.1f} lost pkt {s['lost_packets']} frm {s['lost_frames']} "
            f"bad {s['bad']} idr-wait {s['waiting_idr']} decode p50 {_fmt(d['p50'])} ms "
            f"age {_fmt(s['frame_age_ms'], '{:.0f}')} ms")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AGX ingest probe")
    ap.add_argument("--config", default="config/sources.yaml")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--json", default=None)
    ap.add_argument("--mode", default=None, choices=["sim", "rk", "file"])
    ap.add_argument("--interval", type=float, default=5.0, help="print interval in s")
    a = ap.parse_args(argv)

    stop = {"flag": False}

    def _sig(_s, _f):
        stop["flag"] = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    me = psutil.Process()
    psutil.cpu_percent(None)
    me.cpu_percent(None)
    sim = find_sim_procs()
    for p in sim:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    sys_start = {"ram_used_mb": ram_used_mb(), "rss_mb": round(me.memory_info().rss / 2**20, 1),
                 "t": time.time()}

    ing = Ingest(a.config, mode=a.mode)
    print(f"ingest mode {ing.mode} bind {ing.bind_host if ing.mode != 'file' else '-'} "
          f"cams {len(ing.cams)} seconds {a.seconds:g} sim procs {[p.pid for p in sim]}", flush=True)
    ing.start()
    rss_after_start = round(me.memory_info().rss / 2**20, 1)
    kids = {}  # receive processes (rx_process: true)
    kid_cpu_by_cam: dict = {}

    def kids_cpu():
        tot, rss = 0.0, 0
        cam_of = {getattr(s, "rx_pid", None): s.cam for s in ing.sources}
        for k in me.children(recursive=True):
            try:
                if k.pid not in kids:
                    k.cpu_percent(None)
                    kids[k.pid] = k
                    continue
                v = kids[k.pid].cpu_percent(None)  # same object: psutil keeps the last sample
                tot += v
                rss += k.memory_info().rss
                c = cam_of.get(k.pid)
                kid_cpu_by_cam.setdefault(f"cam{c}" if c is not None else f"pid{k.pid}",
                                          []).append(v)
            except psutil.Error:
                pass
        return tot, rss
    kids_cpu()
    per_cam = {c: {"fps": [], "bitrate_kbps": [], "decode_p50": [], "decode_p95": [],
                   "age_ms": [], "states": {}} for c in ing.cams}
    cpu_tot, cpu_me, cpu_sim, gpu, tmax, cpu_kids = [], [], [], [], [], []
    kids_rss = 0
    t0 = time.monotonic()
    t_print = t0
    last = []
    try:
        while not stop["flag"]:
            time.sleep(max(0.0, 1.0 - ((time.monotonic() - t0) % 1.0)))
            now = time.monotonic()
            last = ing.metrics_snapshot()
            for s in last:
                pc = per_cam[s["cam"]]
                pc["fps"].append(s["fps"])
                pc["bitrate_kbps"].append(s["bitrate_kbps"])
                pc["decode_p50"].append(s["decode_ms"]["p50"])
                pc["decode_p95"].append(s["decode_ms"]["p95"])
                pc["age_ms"].append(s["frame_age_ms"])
                pc["states"][s["state"]] = pc["states"].get(s["state"], 0) + 1
            cpu_tot.append(psutil.cpu_percent(None))
            cpu_me.append(me.cpu_percent(None))
            kc, kids_rss = kids_cpu()
            cpu_kids.append(kc)
            if int(now - t0) % 5 == 0:  # the simulator can start after the probe
                for p in find_sim_procs():
                    if p.pid not in {q.pid for q in sim}:
                        try:
                            p.cpu_percent(None)
                            sim.append(p)
                        except psutil.Error:
                            pass
            if sim:
                tot = 0.0
                for p in sim:
                    try:
                        tot += p.cpu_percent(None)
                    except psutil.Error:
                        pass
                cpu_sim.append(tot)
            gpu.append(gpu_load_pct())
            t = temps_c()
            tmax.append(max(t.values()) if t else None)
            if now - t_print >= a.interval - 0.01:
                t_print = now
                print(f"--- t={now - t0:5.1f} s  cpu {cpu_tot[-1]:.0f}%  ingest {cpu_me[-1]:.0f}% "
                      f"+ rx procs {cpu_kids[-1]:.0f}% (of one core)  gpu {_fmt(gpu[-1], '{:.0f}')}%", flush=True)
                for s in last:
                    print("  " + line(s), flush=True)
            if now - t0 >= a.seconds:
                break
    finally:
        ing.stop()

    summary = {
        "mode": ing.mode, "bind_host": ing.bind_host if ing.mode != "file" else None,
        "seconds": round(time.monotonic() - t0, 1), "config": os.path.abspath(a.config),
        "t_start_unix": sys_start["t"], "cameras": [],
        "system": {
            "cpu_total_pct": _stats(cpu_tot),
            "cpu_ingest_proc_pct_of_one_core": _stats(cpu_me),
            "cpu_rx_child_procs_pct_of_one_core": _stats(cpu_kids),
            "cpu_rx_child_by_cam_pct_of_one_core": {k: _stats(v) for k, v in
                                                    sorted(kid_cpu_by_cam.items())},
            "rx_child_procs": len(kids), "rx_child_rss_mb_end": round(kids_rss / 2**20, 1),
            "cpu_sim_proc_pct_of_one_core": _stats(cpu_sim) if sim else None,
            "sim_pids": [p.pid for p in sim],
            "cpu_count": psutil.cpu_count(),
            "gpu_load_pct": _stats(gpu),
            "ram_used_mb_start": sys_start["ram_used_mb"], "ram_used_mb_end": ram_used_mb(),
            "rss_mb_start": sys_start["rss_mb"], "rss_mb_after_start": rss_after_start,
            "rss_mb_end": round(me.memory_info().rss / 2**20, 1),
            "temp_max_c": _stats(tmax),
            "temps_end_c": temps_c(),
        },
    }
    for s in last:
        pc = per_cam[s["cam"]]
        ages = [x for x in pc["age_ms"] if x is not None]
        summary["cameras"].append({
            "cam": s["cam"], "role": s["role"], "port": s["port"], "state_end": s["state"],
            "states_seen_s": pc["states"], "simulated": s["simulated"], "source": s["source"],
            "fmt": s["fmt"], "width": s["width"], "height": s["height"],
            "fps": _stats(pc["fps"]), "bitrate_kbps": _stats(pc["bitrate_kbps"]),
            "frames": s["frames"], "datagrams": s["datagrams"],
            "lost_packets": s["lost_packets"], "lost_fragments": s["lost_fragments"],
            "lost_frames": s["lost_frames"], "abandoned_frames": s["abandoned_frames"],
            "missing_frames": s["missing_frames"], "bad": s["bad"],
            "waiting_idr": s["waiting_idr"], "decoder_errors": s["decoder_errors"],
            "decoder_drops": s["decoder_drops"], "seq_resets": s["seq_resets"],
            "ring_overruns": s["ring_overruns"], "late_datagrams": s["late_datagrams"],
            "new_streams": s["new_streams"], "foreign_frames": s["foreign_frames"],
            "rx_restarts": s["rx_restarts"], "internal_errors": s["internal_errors"],
            "start_partial": s["start_partial"],
            "decode_ms_p50": _stats(pc["decode_p50"]), "decode_ms_p95": _stats(pc["decode_p95"]),
            "decode_ms_last300": s["decode_ms"],
            "capture_to_ready_ms_last300": s["capture_to_ready_ms"],
            "frame_age_ms_max": max(ages) if ages else None,
            "rcvbuf": s["rcvbuf"], "last_error": s["last_error"],
        })
    print("--- summary", flush=True)
    for c in summary["cameras"]:
        print(f"  cam{c['cam']} fps avg {_fmt(c['fps']['avg'])} min {_fmt(c['fps']['min'])} "
              f"kbit/s avg {_fmt(c['bitrate_kbps']['avg'])} frames {c['frames']} "
              f"lost pkt {c['lost_packets']} frm {c['lost_frames']} "
              f"decode p50 {_fmt(c['decode_ms_last300']['p50'])} p95 "
              f"{_fmt(c['decode_ms_last300']['p95'])} ms age max {_fmt(c['frame_age_ms_max'], '{:.0f}')} ms",
              flush=True)
    sy = summary["system"]
    print(f"  cpu total avg {sy['cpu_total_pct']['avg']}%  ingest avg "
          f"{sy['cpu_ingest_proc_pct_of_one_core']['avg']}% + rx procs "
          f"{sy['cpu_rx_child_procs_pct_of_one_core']['avg']}% of one core  sim "
          f"{(sy['cpu_sim_proc_pct_of_one_core'] or {}).get('avg')}%  gpu avg {sy['gpu_load_pct']['avg']}%  "
          f"ram {sy['ram_used_mb_start']} -> {sy['ram_used_mb_end']} MB  rss {sy['rss_mb_start']} -> "
          f"{sy['rss_mb_end']} MB  temp max {sy['temp_max_c']['max']} C", flush=True)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w") as fh:
            json.dump(summary, fh, indent=1)
        print(f"json: {a.json}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
