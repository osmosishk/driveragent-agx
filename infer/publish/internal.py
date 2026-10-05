"""Internal PUB socket (127.0.0.1:5562) for the dashboard: multipart [topic, payload].

  b"status"      JSON agx-infer-status/1, 1 Hz (StatusPublisher)
  b"snap.<cam>"  JPEG 320 px wide, 1 Hz per camera (SnapshotTask)
Two threads send on it, so every send takes a lock (ZMQ sockets are not thread-safe).

Security: a PUB socket receives only subscription messages. MAXMSGSIZE (PUB_MAX_IN_BYTES) closes
the connection of a peer that sends a larger message (no memory use by a bad peer).
Log: a repeated error writes at most 1 line per LOG_EVERY_S per message kind (RateLimitedLog).
"""
from __future__ import annotations

import logging
import threading
import time

import zmq

log = logging.getLogger("infer.internal")

PUB_MAX_IN_BYTES = 4096   # largest inbound message on a PUB socket (subscriptions only)
LOG_EVERY_S = 10.0


class RateLimitedLog:
    """At most 1 log line per `every_s` per message kind. The next line gives the number of
    lines that were not written ("N more since last line"). Thread-safe."""

    def __init__(self, logger: logging.Logger, every_s: float = LOG_EVERY_S):
        self.logger = logger
        self.every_s = float(every_s)
        self._lock = threading.Lock()
        self._last: dict[str, tuple[float, int]] = {}

    def log(self, level: int, kind: str, msg: str, *args, **kw) -> bool:
        """Write the line when allowed (kw go to Logger.log, for example exc_info=True).
        Returns True when a line was written."""
        now = time.monotonic()
        with self._lock:
            last, skipped = self._last.get(kind, (None, 0))
            if last is not None and now - last < self.every_s:
                self._last[kind] = (last, skipped + 1)
                return False
            if len(self._last) > 1024:   # bound the memory (kinds are few in normal use)
                self._last.clear()
            self._last[kind] = (now, 0)
        if skipped:
            msg = msg + " (%d more since last line)"
            args = args + (skipped,)
        self.logger.log(level, msg, *args, **kw)
        return True

    def error(self, kind: str, msg: str, *args, **kw) -> bool:
        return self.log(logging.ERROR, kind, msg, *args, **kw)

    def warning(self, kind: str, msg: str, *args, **kw) -> bool:
        return self.log(logging.WARNING, kind, msg, *args, **kw)


class InternalPub:
    def __init__(self, host: str = "127.0.0.1", port: int = 5562, ctx: zmq.Context | None = None,
                 sndhwm: int = 50):
        self.endpoint = f"tcp://{host}:{port}"
        self._ctx = ctx or zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUB)
        self._sock.setsockopt(zmq.SNDHWM, sndhwm)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.MAXMSGSIZE, PUB_MAX_IN_BYTES)
        self._sock.bind(self.endpoint)
        self._lock = threading.Lock()
        self._closed = False
        self._rlog = RateLimitedLog(log)
        self.sent = {}
        self.errors = 0
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
                self.errors += 1
                # the kind is the topic family ("status", "snap"): one line per 10 s each
                kind = bytes(topic).split(b".", 1)[0].decode("ascii", "replace")
                self._rlog.error(f"send.{kind}", "internal send failed (topic %s): %s",
                                 bytes(topic).decode("ascii", "replace"), e)
                return False
            self.sent[topic] = self.sent.get(topic, 0) + 1
            return True

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._sock.close(0)
