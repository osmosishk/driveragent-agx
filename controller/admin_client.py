"""Client of the agx-infer admin socket (ZMQ REP on 127.0.0.1:5563, infer/admin.py). Pure Python + pyzmq.

A new REQ socket for each call (a REQ socket that timed out cannot be used again), LINGER 0, a receive timeout.
Commands used by the controller: "instances", "add" {"model": cfg}, "remove" {"key"}.
"""
from __future__ import annotations

import json

import zmq

DEFAULT_ENDPOINT = "tcp://127.0.0.1:5563"


class AdminClient:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout_s: float = 5.0):
        self.endpoint = endpoint
        self.timeout_ms = int(timeout_s * 1000)

    def call(self, req: dict, timeout_s: float | None = None) -> dict:
        """The JSON answer, or {"ok": false, "error": ...} when agx-infer does not answer."""
        tmo = self.timeout_ms if timeout_s is None else int(timeout_s * 1000)
        ctx = zmq.Context.instance()
        s = ctx.socket(zmq.REQ)
        s.setsockopt(zmq.LINGER, 0)
        s.setsockopt(zmq.RCVTIMEO, tmo)
        s.setsockopt(zmq.SNDTIMEO, tmo)
        try:
            s.connect(self.endpoint)
            s.send(json.dumps(req).encode())
            parts = s.recv_multipart()
            return json.loads(parts[0])
        except zmq.Again:
            return {"ok": False, "error": f"agx-infer did not answer on {self.endpoint} in {tmo / 1000:.0f} s "
                                          "(is agx-infer running?)"}
        except (zmq.ZMQError, ValueError) as e:
            return {"ok": False, "error": f"agx-infer admin socket error: {e}"}
        finally:
            s.close(0)

    def instances(self) -> tuple[list[dict] | None, str | None]:
        r = self.call({"cmd": "instances"})
        if not r.get("ok"):
            return None, r.get("error") or "no answer"
        return list(r.get("instances") or []), None

    def add(self, cfg: dict) -> tuple[bool, str]:
        r = self.call({"cmd": "add", "model": cfg}, timeout_s=15)
        return bool(r.get("ok")), str(r.get("key") if r.get("ok") else r.get("error"))

    def remove(self, key: str) -> tuple[bool, str]:
        r = self.call({"cmd": "remove", "key": key}, timeout_s=70)   # agx-infer stops the workers before it answers
        return bool(r.get("ok")), str(r.get("error") or "")
