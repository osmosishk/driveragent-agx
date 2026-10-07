"""Entry: python -m dashboard.main --config config/dashboard.yaml [--port N] [--port-file PATH]
          [--history-db PATH] [--engines-cache PATH]

Port 8700 by default; if it is in use, the next free port (8701, ...) is used.
The chosen port is logged ("dashboard port <n>") and written to data/dashboard_port.
"""
from __future__ import annotations

import argparse
import logging
import socket
import sys

import uvicorn

from dashboard.app import create_app
from dashboard.config import load_config, resolve_path

log = logging.getLogger("dashboard")


class _NoAuthHeaderFilter(logging.Filter):
    """Safety net: drop any log record that contains an Authorization header."""

    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return "authorization" not in msg.lower()


def bind_first_free(host: str, start: int, tries: int = 50) -> socket.socket:
    last = None
    for port in range(start, start + tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            s.listen(128)
            s.set_inheritable(True)
            return s
        except OSError as e:
            last = e
            s.close()
    raise OSError(f"no free port in {start}..{start + tries - 1}: {last}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AGX dashboard (read-only)")
    ap.add_argument("--config", default="config/dashboard.yaml")
    ap.add_argument("--port", type=int, default=None, help="override config port")
    ap.add_argument("--port-file", default=None, help="override config port_file")
    ap.add_argument("--history-db", default=None, help="override history db path")
    ap.add_argument("--engines-cache", default=None, help="override engines.cache (engine facts cache file)")
    ap.add_argument("--model-store", default=None, help="override model_store (the model controller store)")
    ap.add_argument("--log-level", default="info")
    a = ap.parse_args(argv)

    logging.basicConfig(level=getattr(logging, a.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in logging.getLogger().handlers:
        h.addFilter(_NoAuthHeaderFilter())

    cfg = load_config(a.config)
    if a.port is not None:
        cfg["port"] = a.port
    if a.port_file:
        cfg["port_file"] = a.port_file
    if a.history_db:
        cfg["history"]["db"] = a.history_db
    if a.model_store:
        cfg["model_store"] = a.model_store
    if a.engines_cache:
        cfg["engines"]["cache"] = a.engines_cache

    try:
        app = create_app(cfg)
    except RuntimeError as e:
        log.error("%s", e)
        return 2

    host = cfg.get("bind") or "0.0.0.0"
    sock = bind_first_free(host, int(cfg["port"]))
    port = sock.getsockname()[1]
    log.info("dashboard port %d", port)
    print(f"dashboard port {port}", flush=True)
    pf = resolve_path(cfg.get("port_file"))
    if pf:
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(f"{port}\n")

    # Optional TLS (tls_certfile / tls_keyfile in config). Without TLS the Basic-auth password
    # crosses the network in clear text on every request: use the page through tailscale.
    tls = {}
    cert, key = resolve_path(cfg.get("tls_certfile")), resolve_path(cfg.get("tls_keyfile"))
    if cert and key:
        tls = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        log.info("dashboard TLS on")
    else:
        log.info("dashboard TLS off (plain HTTP): use the page through tailscale or loopback")
    config = uvicorn.Config(app, log_level=a.log_level.lower(), access_log=False,
                            timeout_graceful_shutdown=3, proxy_headers=False, server_header=False,
                            **tls)
    server = uvicorn.Server(config)
    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    sys.exit(main())
