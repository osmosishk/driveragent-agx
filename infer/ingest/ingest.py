"""AGX ingest: six camera sources -> one FrameStore + per-camera metrics.

mode sim  FrameLink UDP from tools.rk_sim on this AGX (bind 127.0.0.1). All frames are simulated.
mode rk   FrameLink UDP from the RK3588 (bind 0.0.0.0). Frames with source byte LIVE are "live".
mode file decode local recordings directly (no network). All frames are simulated ("file").
"""
from __future__ import annotations

import os
import sys

import yaml

from common import framelink as fl
from infer.ingest.frame_store import FrameStore
from infer.ingest.metrics import CameraMetrics

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "config", "sources.yaml")
ROLES = {0: "front", 1: "right", 2: "left", 3: "right-back", 4: "left-back", 5: "back"}
MODES = ("sim", "rk", "file")


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
        cams_cfg = {int(c["cam"]): c for c in self.cfg.get("cameras", [])}
        self.cams = list(range(6))  # always six cameras, even without config / signal
        self.store = FrameStore(self.cams, stale_s=float(self.cfg.get("stale_s", 0.5)),
                                no_signal_s=float(self.cfg.get("no_signal_s", 1.0)))
        expect_sim = self.mode != "rk"
        self.metrics: dict[int, CameraMetrics] = {}
        self.sources = []
        for cam in self.cams:
            c = cams_cfg.get(cam, {})
            role = c.get("role", ROLES[cam])
            port = int(c.get("port", fl.BASE_PORT + cam))
            m = CameraMetrics(cam, role, port if self.mode != "file" else None, self.mode,
                              self.store, expect_simulated=expect_sim)
            self.metrics[cam] = m
            if c.get("enabled", True) is False:
                continue
            if self.mode == "file":
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
                    decoder_prestart=bool(self.cfg.get("decoder_prestart", True))))
        self._started = False

    def start(self) -> None:
        # Only for rx_process: false (receive threads in this process share the GIL; the default
        # switch interval of 5 ms lets a socket overflow). Process-wide setting.
        si = self.cfg.get("gil_switch_interval_s", 0)
        if si and self.mode != "file":
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
        return [self.metrics[c].snapshot() for c in self.cams]

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
