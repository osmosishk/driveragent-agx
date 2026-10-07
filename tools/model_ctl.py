"""Model control over the local admin socket of infer.main (127.0.0.1:5563).

  python -m tools.model_ctl list
  python -m tools.model_ctl stop <name or name@version>
  python -m tools.model_ctl start <name or name@version>
  python -m tools.model_ctl add <name> <version> [--cameras 0,1] [--store ~/agx-models]
  python -m tools.model_ctl remove <name@version>

add: the runtime config of a model store version (controller.runtime.runtime_cfg) is sent to the running
infer.main (admin "add"); the instance loads in the background (see "list"). remove: admin "remove".
add and remove write a line in the controller audit log (<store>/_state/audit.jsonl, source command-line).

list: the first line gives the node source mode (sim / rk / file) and the input source, from the
internal status (127.0.0.1:5562, topic "status"). The SOURCE column is SIMULATED when the camera
input of the model is simulated (R13). Without status data, SOURCE is UNKNOWN: treat the
values as SIMULATED.
"""
from __future__ import annotations

import argparse
import getpass
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


def read_status(endpoint: str, timeout_ms: int = 2500) -> dict | None:
    """One internal status JSON (agx-infer-status/1) from the internal PUB, or None."""
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.setsockopt(zmq.LINGER, 0)
    s.setsockopt(zmq.RCVTIMEO, timeout_ms)
    s.setsockopt(zmq.MAXMSGSIZE, 4 * 1024 * 1024)
    s.setsockopt(zmq.SUBSCRIBE, b"status")
    s.connect(endpoint)
    try:
        while True:
            parts = s.recv_multipart()
            if len(parts) == 2 and parts[0] == b"status":
                return json.loads(parts[1])
    except (zmq.Again, ValueError):
        return None
    finally:
        s.close(0)


def node_source(status: dict | None) -> tuple[str, bool | None, dict]:
    """-> (mode, node simulated, {cam: simulated}). mode "unknown" and simulated None when there
    is no status."""
    if not status:
        return "unknown", None, {}
    cams = status.get("cameras") or []
    modes = sorted({str(c.get("mode")) for c in cams if c.get("mode")})
    mode = ",".join(modes) if modes else "unknown"
    node_sim = (status.get("node") or {}).get("simulated")
    cam_sim = {int(c["cam"]): bool(c.get("simulated", True)) for c in cams if "cam" in c}
    return mode, (None if node_sim is None else bool(node_sim)), cam_sim


def model_source(m: dict, mode: str, node_sim, cam_sim: dict) -> str:
    """SIMULATED / LIVE / UNKNOWN for one model (R13: SIMULATED when one input is simulated)."""
    if node_sim is None:
        return "UNKNOWN"
    if mode != "rk":
        return "SIMULATED"
    cams = [int(c) for c in m.get("cameras") or []]
    if not cams:
        return "SIMULATED" if node_sim else "LIVE"
    if any(cam_sim.get(c, True) for c in cams):
        return "SIMULATED"
    return "LIVE"


def _fmt_lat(m):
    p = ((m.get("lat_ms") or {}).get("total") or {}).get("p50")
    return "-" if p is None else f"{p:.1f}"


def add_request(store_root: str | None, name: str, version: str, cameras: str | None) -> dict:
    """Admin request {"cmd": "add", "model": cfg} of one store version. Raises ValueError with the reason."""
    from controller import runtime
    from controller.store import Store
    store = Store(store_root)
    m = store.get(name, version)
    if m is None:
        raise ValueError(f"{name}@{version} is not in the model store {store.root}")
    cams = None if not cameras else [int(c) for c in cameras.split(",") if c.strip()]
    return {"cmd": "add", "model": runtime.runtime_cfg(store, m, cams)}


def _audit(store_root: str | None, action: str, key: str, ok: bool, reason: str | None) -> None:
    try:
        from controller import audit
        from controller.store import Store
        name, _, version = key.partition("@")
        audit.append(Store(store_root).state, "command-line", getpass.getuser(), action, name, version or None,
                     "ok" if ok else "failed", reason)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: audit line not written: {e}", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="model control (admin socket of infer.main)")
    ap.add_argument("--admin", default="tcp://127.0.0.1:5563")
    ap.add_argument("--status", default="tcp://127.0.0.1:5562",
                    help="internal status PUB of infer.main (source mode for list)")
    ap.add_argument("--json", action="store_true", help="print the raw JSON reply")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for c in ("stop", "start"):
        sub.add_parser(c).add_argument("name")
    p_add = sub.add_parser("add", help="run a model store version (instance <name>@<version>)")
    p_add.add_argument("name")
    p_add.add_argument("version")
    p_add.add_argument("--cameras", default=None, help="comma separated camera ids (default: manifest default)")
    p_add.add_argument("--store", default=None, help="model store (default ~/agx-models)")
    p_rm = sub.add_parser("remove", help="stop and remove one instance <name>@<version>")
    p_rm.add_argument("key")
    p_rm.add_argument("--store", default=None, help="model store (default ~/agx-models), for the audit log")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        req = {"cmd": "models"}
    elif a.cmd == "add":
        try:
            req = add_request(a.store, a.name, a.version, a.cameras)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    elif a.cmd == "remove":
        req = {"cmd": "remove", "key": a.key}
    else:
        req = {"cmd": a.cmd, "model": a.name}
    try:
        rep = json.loads(request(a.admin, req, timeout_ms=70000 if a.cmd == "remove" else 5000)[0])
    except (TimeoutError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if a.cmd in ("add", "remove"):
        key = a.key if a.cmd == "remove" else f"{a.name}@{a.version}"
        _audit(a.store, a.cmd, key, bool(rep.get("ok")), rep.get("error"))
    if a.json or a.cmd != "list":
        print(json.dumps(rep, indent=2))
        return 0 if rep.get("ok") else 1
    if not rep.get("ok"):
        print(f"ERROR: {rep.get('error')}", file=sys.stderr)
        return 1
    mode, node_sim, cam_sim = node_source(read_status(a.status))
    if node_sim is None:
        src = "UNKNOWN (no status data: treat all values as SIMULATED)"
    else:
        src = "SIMULATED" if (node_sim or mode != "rk") else "LIVE"
    print(f"NODE SOURCE MODE: {mode}   INPUT: {src}")
    print(f"{'INSTANCE':28} {'STATE':8} {'EN':3} {'CAMERAS':14} {'SOURCE':9} {'FPS':>6} {'P50 ms':>7} "
          f"{'RESULTS':>8}  ERROR/REASON")
    for m in rep.get("models") or []:
        cams = ",".join(str(c) for c in m.get("cameras") or [])
        fps = m.get("fps")
        inst = str(m.get("instance") or m.get("name"))     # <name>@<version>, or the name (legacy entry)
        print(f"{inst:28} {str(m.get('state')):8} {'y' if m.get('enabled') else 'n':3} "
              f"{cams:14} {model_source(m, mode, node_sim, cam_sim):9} "
              f"{(f'{fps:.1f}' if isinstance(fps, (int, float)) else '-'):>6} {_fmt_lat(m):>7} "
              f"{m.get('results_total') or 0:>8}  {m.get('error') or m.get('reason') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
