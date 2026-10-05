"""Internal PUB socket (127.0.0.1:5562) for the dashboard: multipart [topic, payload].

  b"status"      JSON agx-infer-status/1, 1 Hz (StatusPublisher)
  b"snap.<cam>"  JPEG 320 px wide, 1 Hz per camera (SnapshotTask)
Two threads send on it, so every send takes a lock (ZMQ sockets are not thread-safe).
"""
from __future__ import annotations

import logging
import threading

import zmq

log = logging.getLogger("infer.internal")


class InternalPub:
    def __init__(self, host: str = "127.0.0.1", port: int = 5562, ctx: zmq.Context | None = None,
                 sndhwm: int = 50):
        self.endpoint = f"tcp://{host}:{port}"
        self._ctx = ctx or zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUB)
        self._sock.setsockopt(zmq.SNDHWM, sndhwm)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.bind(self.endpoint)
        self._lock = threading.Lock()
        self._closed = False
        self.sent = {}
        log.info("internal PUB bound %s", self.endpoint)

    def send(self, topic: bytes, payload: bytes) -> bool:
        with self._lock:
            if self._closed:
                return False
            try:
                self._sock.send_multipart([topic, payload], zmq.NOBLOCK)
            except zmq.Again:
                return False
            except zmq.ZMQError as e:
                log.error("internal send failed: %s", e)
                return False
            self.sent[topic] = self.sent.get(topic, 0) + 1
            return True

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._sock.close(0)
