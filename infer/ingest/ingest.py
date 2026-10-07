"""AGX ingest: six camera sources -> one FrameStore + per-camera metrics.

mode sim  FrameLink UDP from tools.rk_sim on this AGX (bind 127.0.0.1). All frames are simulated.
mode rk   FrameLink UDP from the RK3588 (bind 0.0.0.0). Frames with source byte LIVE are "live".
mode file decode local recordings directly (no network). All frames are simulated ("file").
mode local frames from the rk-camd frame socket on this machine (infer/ingest/local_source.py): one camera,
          NV12, no network, no decode. Frames are "live".

rk mode source filter: config key rk_allowed_sources (list of IP addresses). Not empty = the
receivers drop datagrams from other addresses (counter foreign_source_drops in the camera
metrics). Empty = accept all, with a WARNING line at start. Sim and file mode: no filter.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import sys

import yaml

from common import framelink as fl
from infer.ingest.frame_store import FrameStore
from infer.ingest.metrics import CameraMetrics

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "config", "sources.yaml")
ROLES = {0: "front", 1: "right", 2: "left", 3: "right-back", 4: "left-back", 5: "back"}
MODES = ("sim", "rk", "file", "local")

log = logging.getLogger("infer.ingest")


def parse_allowed_sources(value) -> tuple[str, ...]:
    """rk_allowed_sources -> tuple of IPv4 address strings. Raises ValueError for a bad entry
    (fail closed: a typing error must not open the filter)."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    out = []
    for v in value:
        a = ipaddress.ip_address(str(v).strip())
        if a.version != 4:
            raise ValueError(f"rk_allowed_sources: {v!r} is not an IPv4 address (the sockets are IPv4)")
        out.append(str(a))
    return tuple(out)


def load_config(cfg=None) -> dict:
    if cfg is None:
        cfg = DEFAULT_CONFIG
    if isinstance(cfg, (str, os.PathLike)):
        with open(cfg) as fh:
            cfg = yaml.safe_load(fh) or {}
    return dict(cfg)


class Ingest:
    def __init__(self, config=None, mode: str | None = None):
        self.cfg = load_config(config)
        self.mode = mode or os.environ.get("AGX_INGEST_MODE") or self.cfg.get("mode", "sim")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {self.mode!r}")
        bh = self.cfg.get("bind_host", {})
        if isinstance(bh, dict):
            self.bind_host = bh.get(self.mode, "127.0.0.1" if self.mode == "sim" else "0.0.0.0")
        else:
            self.bind_host = bh
        # source filter: rk mode only (sim binds loopback, file has no network)
        self.allowed_sources = parse_allowed_sources(self.cfg.get("rk_allowed_sources")) \
            if self.mode == "rk" else ()
        cams_cfg = {int(c["cam"]): c for c in self.cfg.get("cameras", [])}
        self.cams = list(range(6))  # always six cameras, even without config / signal
        self.store = FrameStore(self.cams, stale_s=float(self.cfg.get("stale_s", 0.5)),
                                no_signal_s=float(self.cfg.get("no_signal_s", 1.0)))
        expect_sim = self.mode not in ("rk", "local")
        local = self.cfg.get("local") or {}
        self.metrics: dict[int, CameraMetrics] = {}
        self.sources = []
        # local mode: the cameras that this unit does not have. They stay NO SIGNAL in the status, but they are
        # not a reason for the node state DEGRADED (infer/publish/status.py). Empty in the other modes.
        self.no_source: set[int] = ({c for c in self.cams if c != int(local.get("cam", 0))}
                                    if self.mode == "local" else set())
        for cam in self.cams:
            c = cams_cfg.get(cam, {})
            # rk mode: the DA01 rk-camd camera name (role_rk) when present; else the old-stack role
            role = (c.get("role_rk") if self.mode == "rk" else None) or c.get("role", ROLES[cam])
            port = int(c.get("port", fl.BASE_PORT + cam))
            m = CameraMetrics(cam, role, port if self.mode not in ("file", "local") else None, self.mode,
                              self.store, expect_simulated=expect_sim)
            self.metrics[cam] = m
            if c.get("enabled", True) is False:
                continue
            if self.mode == "local":
                # one camera only: the rk-camd stream local.rk_cam becomes camera local.cam (default 0)
                if cam == int(local.get("cam", 0)):
                    from infer.ingest.local_source import LocalSource
                    self.sources.append(LocalSource(
                        cam, self.store, m,
                        os.environ.get("AGX_LOCAL_FRAME_SOCKET") or str(local.get("socket", "")),
                        notify_socket=os.environ.get("AGX_LOCAL_NOTIFY_SOCKET", str(local.get("notify_socket", ""))),
                        rk_cam=int(local.get("rk_cam", 0))))
            elif self.mode == "file":
                from infer.ingest.file_source import FileSource
                self.sources.append(FileSource(cam, c.get("files", []), self.store, m,
                                               fps=float(self.cfg.get("file_fps", 30))))
            else:
                from infer.ingest.framelink_rx import FrameLinkReceiver
                self.sources.append(FrameLinkReceiver(
                    cam, port, self.bind_host, self.store, m, expect_simulated=expect_sim,
                    h265_resync_on_loss=bool(self.cfg.get("h265_resync_on_loss", True)),
                    rcvbuf=int(self.cfg.get("rcvbuf_bytes", 0) or 0),
                    reassembly_timeout_s=float(self.cfg.get("reassembly_timeout_s", 0.2)),
                    use_process=bool(self.cfg.get("rx_process", True)),
                    ring_slots=int(self.cfg.get("ring_slots", 8)),
                    max_frame=int(self.cfg.get("max_frame_bytes", 2 * 1024 * 1024)),
                    decoder_prestart=bool(self.cfg.get("decoder_prestart", True)),
                    allowed_sources=self.allowed_sources))
        self._started = False

    def start(self) -> None:
        # Only for rx_process: false (receive threads in this process share the GIL; the default
        # switch interval of 5 ms lets a socket overflow). Process-wide setting.
        if self.mode == "rk":
            if self.allowed_sources:
                log.info("rk mode: accept FrameLink datagrams only from %s",
                         ", ".join(self.allowed_sources))
            else:
                log.warning("rk mode: rk_allowed_sources is empty: FrameLink datagrams from ANY "
                            "source address are accepted on %s (set it in config/sources.yaml)",
                            self.bind_host)
        si = self.cfg.get("gil_switch_interval_s", 0)
        if si and self.mode not in ("file", "local"):
            sys.setswitchinterval(float(si))
        started = []
        try:
            for s in self.sources:
                s.start()
                started.append(s)
        except Exception:
            for s in started:
                s.stop()
            raise
        self._started = True

    def stop(self) -> None:
        for s in self.sources:
            try:
                s.stop()
            except Exception:  # noqa: BLE001
                pass
        self._started = False

    def metrics_snapshot(self) -> list[dict]:
        out = []
        for c in self.cams:
            m = self.metrics[c]
            snap = m.snapshot()
            snap["foreign_source_drops"] = int(m.c.get("foreign_source_drops") or 0)
            out.append(snap)
        return out

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
