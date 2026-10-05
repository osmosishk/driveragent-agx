"""Model control over the local admin socket of infer.main (127.0.0.1:5563).

  python -m tools.model_ctl list
  python -m tools.model_ctl stop <name>
  python -m tools.model_ctl start <name>
"""
from __future__ import annotations

import argparse
import json
import sys

import zmq


def request(endpoint: str, req: dict, timeout_ms: int = 5000) -> list[bytes]:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.LINGER, 0)
    s.setsockopt(zmq.RCVTIMEO, timeout_ms)
    s.setsockopt(zmq.SNDTIMEO, timeout_ms)
    s.connect(endpoint)
    try:
        s.send(json.dumps(req).encode())
        return s.recv_multipart()
    except zmq.Again:
        raise TimeoutError(f"no reply from {endpoint} in {timeout_ms} ms (is infer.main running?)")
    finally:
        s.close(0)


def _fmt_lat(m):
    p = ((m.get("lat_ms") or {}).get("total") or {}).get("p50")
    return "-" if p is None else f"{p:.1f}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="model control (admin socket of infer.main)")
    ap.add_argument("--admin", default="tcp://127.0.0.1:5563")
    ap.add_argument("--json", action="store_true", help="print the raw JSON reply")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for c in ("stop", "start"):
        sub.add_parser(c).add_argument("name")
    a = ap.parse_args(argv)
    req = {"cmd": "models"} if a.cmd == "list" else {"cmd": a.cmd, "model": a.name}
    try:
        rep = json.loads(request(a.admin, req)[0])
    except (TimeoutError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if a.json or a.cmd != "list":
        print(json.dumps(rep, indent=2))
        return 0 if rep.get("ok") else 1
    if not rep.get("ok"):
        print(f"ERROR: {rep.get('error')}", file=sys.stderr)
        return 1
    print(f"{'NAME':28} {'STATE':8} {'EN':3} {'CAMERAS':14} {'FPS':>6} {'P50 ms':>7} {'RESULTS':>8}  ERROR/REASON")
    for m in rep.get("models") or []:
        cams = ",".join(str(c) for c in m.get("cameras") or [])
        fps = m.get("fps")
        print(f"{str(m.get('name')):28} {str(m.get('state')):8} {'y' if m.get('enabled') else 'n':3} "
              f"{cams:14} {(f'{fps:.1f}' if isinstance(fps, (int, float)) else '-'):>6} {_fmt_lat(m):>7} "
              f"{m.get('results_total') or 0:>8}  {m.get('error') or m.get('reason') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
