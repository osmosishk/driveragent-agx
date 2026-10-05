"""Admin socket: ZMQ REP on tcp://127.0.0.1:5563 (localhost only). JSON requests:

  {"cmd": "models"}                        -> {"ok": true, "models": [ModelManager.status() ...]}
  {"cmd": "stop",  "model": name}          -> {"ok": ..., "model": name, "result": ...}
  {"cmd": "start", "model": name}          -> same
  {"cmd": "frame", "cam": c, "seq": s}     -> multipart [json meta, JPEG of the RAW frame
                                              (no drawing, full size, quality 90)]
  {"cmd": "newest", "cam": c}              -> same for the newest frame
  anything else                            -> {"ok": false, "error": "..."}
The server never runs shell commands. A host other than a loopback address is refused.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import threading

import zmq

from infer.draw import encode_jpeg, nv12_to_bgr

log = logging.getLogger("infer.admin")
MAX_REQ = 65536


def frame_meta(f) -> dict:
    return {"cam": f.cam, "seq": f.seq, "t_capture_ns": f.t_capture_ns, "t_recv_ns": f.t_recv_ns,
            "t_ready_ns": f.t_ready_ns, "width": f.width, "height": f.height, "fmt": f.fmt,
            "source": f.source, "simulated": f.simulated}


class AdminServer:
    def __init__(self, store, manager, host: str = "127.0.0.1", port: int = 5563,
                 jpeg_quality: int = 90, ctx: zmq.Context | None = None):
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
            raise ValueError(f"admin socket must bind a loopback address, not {host}")
        self.store = store
        self.manager = manager
        self.jpeg_quality = int(jpeg_quality)
        self.endpoint = f"tcp://{host}:{port}"
        self._ctx = ctx or zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.REP)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.MAXMSGSIZE, MAX_REQ)
        self._sock.bind(self.endpoint)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.requests = 0
        log.info("admin REP bound %s", self.endpoint)

    # ---- handlers --------------------------------------------------------------------------------
    def _frame_reply(self, f, req) -> list[bytes]:
        if f is None:
            return [json.dumps({"ok": False, "error": "frame not in recent ring", "request": req}).encode()]
        jpg = encode_jpeg(nv12_to_bgr(f.nv12), self.jpeg_quality)
        meta = {"ok": True, **frame_meta(f), "jpeg_bytes": len(jpg)}
        return [json.dumps(meta).encode(), jpg]

    def handle(self, raw: bytes) -> list[bytes]:
        try:
            req = json.loads(raw.decode("utf-8"))
            if not isinstance(req, dict):
                raise ValueError("request is not a JSON object")
        except (UnicodeDecodeError, ValueError) as e:
            return [json.dumps({"ok": False, "error": f"bad request: {e}"}).encode()]
        cmd = req.get("cmd")
        try:
            if cmd == "models":
                st = self.manager.status() if self.manager is not None else []
                return [json.dumps({"ok": True, "models": st}, default=str).encode()]
            if cmd in ("stop", "start"):
                name = req.get("model")
                if not isinstance(name, str) or not name:
                    return [json.dumps({"ok": False, "error": "field 'model' is missing"}).encode()]
                if self.manager is None:
                    return [json.dumps({"ok": False, "error": "no model manager"}).encode()]
                fn = self.manager.stop_model if cmd == "stop" else self.manager.start_model
                res = fn(name)
                ok = res is not False and not (isinstance(res, dict) and res.get("ok") is False)
                log.info("admin %s %s -> %s", cmd, name, res)
                return [json.dumps({"ok": ok, "cmd": cmd, "model": name, "result": res},
                                   default=str).encode()]
            if cmd in ("frame", "newest"):
                try:
                    cam = int(req.get("cam"))
                except (TypeError, ValueError):
                    return [json.dumps({"ok": False, "error": "field 'cam' is missing"}).encode()]
                if cam not in getattr(self.store, "cams", range(6)):
                    return [json.dumps({"ok": False, "error": f"unknown cam {cam}"}).encode()]
                if cmd == "newest":
                    return self._frame_reply(self.store.newest(cam), req)
                try:
                    seq = int(req.get("seq"))
                except (TypeError, ValueError):
                    return [json.dumps({"ok": False, "error": "field 'seq' is missing"}).encode()]
                return self._frame_reply(self.store.find(cam, seq), req)
            return [json.dumps({"ok": False, "error": f"unknown command {cmd!r}",
                                "commands": ["models", "stop", "start", "frame", "newest"]}).encode()]
        except Exception as e:  # noqa: BLE001
            log.exception("admin command %r failed", cmd)
            return [json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}).encode()]

    # ---- loop ------------------------------------------------------------------------------------
    def _run(self):
        poller = zmq.Poller()
        poller.register(self._sock, zmq.POLLIN)
        while not self._stop.is_set():
            try:
                if not dict(poller.poll(200)):
                    continue
                parts = self._sock.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                continue
            except zmq.ZMQError as e:
                if self._stop.is_set():
                    break
                log.error("admin recv failed: %s", e)
                continue
            self.requests += 1
            reply = self.handle(parts[0] if parts else b"")
            try:
                self._sock.send_multipart(reply)
            except zmq.ZMQError as e:
                log.error("admin send failed: %s", e)

    def start(self):
        self._thread = threading.Thread(target=self._run, name="admin", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._sock.close(0)
