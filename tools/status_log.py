"""Record the internal status of agx-infer (ZMQ SUB 127.0.0.1:5562, topic b"status") as JSON lines.

  python -m tools.status_log --seconds N --out file.jsonl [--endpoint tcp://127.0.0.1:5562]

Each line is the status JSON plus "rx_t" (receive time, unix s). Read-only consumer.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import zmq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--endpoint", default="tcp://127.0.0.1:5562")
    ap.add_argument("--every", type=int, default=1, help="keep 1 of N status messages (long runs)")
    a = ap.parse_args()
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.setsockopt(zmq.SUBSCRIBE, b"status")
    s.setsockopt(zmq.RCVTIMEO, 1000)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(a.endpoint)
    end = time.time() + a.seconds
    n = 0
    seen = 0
    with open(a.out, "w") as f:
        while time.time() < end:
            try:
                parts = s.recv_multipart()
            except zmq.Again:
                continue
            if len(parts) < 2 or parts[0] != b"status":
                continue
            try:
                d = json.loads(parts[1])
            except ValueError:
                continue
            seen += 1
            if (seen - 1) % max(1, a.every):
                continue
            d["rx_t"] = time.time()
            f.write(json.dumps(d) + "\n")
            f.flush()
            n += 1
    print(f"status messages recorded: {n} in {a.seconds:.0f} s -> {a.out}")
    s.close()
    return 0 if n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
