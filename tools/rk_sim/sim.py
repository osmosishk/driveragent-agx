"""RK3588 simulator: sends FrameLink frames (H.265 access units or NV12) on UDP, camera N -> port
base_port + N, like the RK3588 will do. One sender thread per camera.

Frame identity in the FrameLink header:
  seq           per camera, starts at 0, +1 per frame, continues over file changes (loop)
  t_capture_ns  time.time_ns() (CLOCK_REALTIME of this computer) at the moment the frame leaves the
                appsink. The simulator has no capture clock. It is NOT the recording time.
  health        LIVE (2): the simulated link is up
  source        REPLAY (2) for files, TEST_PATTERN (3) for the test pattern. NEVER LIVE (1).
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

from common.framelink import (FMT_H265, FMT_NV12, HEALTH_LIVE, SOURCE_REPLAY,
                              SOURCE_TEST_PATTERN, FrameHeader)
from tools.rk_sim import config as cfgmod
from tools.rk_sim import pipelines as pl
from tools.rk_sim.sender import FrameLinkSender, Stats


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


class CameraWorker(threading.Thread):
    """Reads frames of one camera from GStreamer, paces them in real time and sends them."""

    def __init__(self, cc: cfgmod.CamCfg, cfg: cfgmod.SimCfg, stop: threading.Event):
        super().__init__(name=f"cam{cc.cam}", daemon=True)
        self.cc = cc
        self.cfg = cfg
        self.stop_ev = stop
        self.stats = Stats()
        self.fmt = cfg.fmt
        self.fmt_code = FMT_H265 if cfg.fmt == "h265" else FMT_NV12
        self.files = [f for f in cc.files if os.path.isfile(f)]
        missing = [f for f in cc.files if not os.path.isfile(f)]
        for f in missing:
            log(f"WARNING cam{cc.cam}: file not found, skip: {f}")
            self.stats.source_errors += 1
        self.kind = cc.source
        if self.kind == "file" and not self.files:
            log(f"WARNING cam{cc.cam}: no file found. The camera sends the TEST PATTERN.")
            self.kind = "test-pattern"
        self.source_code = SOURCE_REPLAY if self.kind == "file" else SOURCE_TEST_PATTERN
        self.nominal = 1.0 / cfg.fps
        self.sender = FrameLinkSender(cfg.host, cfg.base_port + cc.cam, cc.cam, cfg.fragment_payload,
                                      cfg.pace, cfg.pace_fraction, sndbuf=cfg.sndbuf,
                                      stats=self.stats)
        self.seq = 0
        self.first_sent = threading.Event()
        self.file_idx = 0
        self.cur: pl.Source | None = None
        self.nxt: pl.Source | None = None
        self.loops = 0

    # ---- sources -------------------------------------------------------------------------------
    def _desc(self, path: str | None) -> str:
        c, cc = self.cfg, self.cc
        if self.kind == "test-pattern":
            w, h = (cc.width, cc.height) if self.fmt == "nv12" else (c.h265_width, c.h265_height)
            return pl.pattern(cc.cam, self.fmt, w, h, c.fps, c)
        if self.fmt == "nv12":
            return pl.file_nv12(path, cc.width, cc.height)
        if c.transcode:
            return pl.file_h265_transcode(path, c)
        return pl.file_h265_passthrough(path)

    def _make(self, idx: int) -> pl.Source | None:
        path = self.files[idx % len(self.files)] if self.kind == "file" else None
        try:
            s = pl.Source(self._desc(path), self.fmt, self.cc.cam, label=path or "test-pattern")
        except Exception as e:  # noqa: BLE001 - parse error
            self._source_error(f"pipeline: {e}")
            return None
        s.preroll()
        return s

    def _source_error(self, text: str) -> None:
        with self.stats.lock:
            self.stats.source_errors += 1
            self.stats.last_error = text
        log(f"ERROR cam{self.cc.cam}: {text}")

    def _advance(self) -> None:
        """Current source ended: go to the next file (loop) or restart the pattern."""
        if self.cur is not None:
            self.cur.stop()
        self.cur = None
        if self.kind == "file":
            self.file_idx += 1
            if self.file_idx % len(self.files) == 0:
                self.loops += 1
        self.cur, self.nxt = self.nxt, None

    def _ensure_source(self) -> bool:
        if self.cur is None:
            self.cur = self._make(self.file_idx)
            if self.cur is None:
                return False
        if not self.cur.playing:
            self.cur.play()
            with self.stats.lock:
                self.stats.file = self.cur.label
            # prepare the next file now, so the change at end of file has no start-up gap
            if self.kind == "file" and self.nxt is None:
                self.nxt = self._make(self.file_idx + 1)
        return True

    def _next_frame(self) -> pl.Out | None:
        if not self._ensure_source():
            self.stop_ev.wait(1.0)
            return None
        out = self.cur.pull(0.2)
        if out is not None:
            return out
        err = self.cur.poll_bus()
        if err:
            self._source_error(f"{self.cur.label}: {err}")
            self._advance()
            self.stop_ev.wait(0.5)  # no tight loop on a bad file
            return None
        if self.cur.eos():
            if self.kind == "file":
                log(f"cam{self.cc.cam}: end of {os.path.basename(self.cur.label)} "
                    f"({self.cur.frames} frames), next file")
            self._advance()
        return None

    # ---- main loop -----------------------------------------------------------------------------
    def run(self) -> None:
        due = None          # monotonic time when the next frame must leave the appsink
        last_dur = self.nominal
        try:
            while not self.stop_ev.is_set():
                if due is not None:
                    dt = due - time.monotonic()
                    if dt > 0 and self.stop_ev.wait(dt):
                        break
                out = self._next_frame()
                if out is None:
                    continue
                t_capture_ns = time.time_ns()      # frame leaves the appsink now
                now = time.monotonic()
                if due is None or now - due > 2 * last_dur:
                    if due is not None:
                        with self.stats.lock:
                            self.stats.late += 1
                    due = now                      # start again, no catch-up burst
                if out.duration > 0:
                    last_dur = min(max(out.duration / 1e9, 0.001), 0.5)
                else:
                    last_dur = self.nominal
                due += last_dur
                if self.fmt == "nv12":
                    payload = out.data.tobytes()
                    stride = out.width
                else:
                    payload = out.data
                    stride = 0
                hdr = FrameHeader(cam=self.cc.cam, fmt=self.fmt_code, seq=self.seq,
                                  t_capture_ns=t_capture_ns, width=out.width, height=out.height,
                                  stride=stride, health=HEALTH_LIVE, source=self.source_code)
                self.sender.send(hdr, payload, last_dur)
                self.seq = (self.seq + 1) & 0xFFFFFFFF
                self.first_sent.set()
        except Exception as e:  # noqa: BLE001
            self._source_error(f"worker stopped: {type(e).__name__}: {e}")
        finally:
            for s in (self.cur, self.nxt):
                if s is not None:
                    s.stop()
            self.cur = self.nxt = None
            self.sender.close()


def measure_idr_bg(cfg: cfgmod.SimCfg, workers: list[CameraWorker], stop: threading.Event):
    from tools.rk_sim.idr import measure
    for w in workers:
        if stop.is_set():
            return
        if w.kind != "file" or cfg.fmt != "h265" or cfg.transcode:
            continue
        try:
            info = measure(w.files[0])
            log(f"cam{w.cc.cam} {os.path.basename(w.files[0])}: {info.line()}")
        except Exception as e:  # noqa: BLE001
            log(f"cam{w.cc.cam}: IDR measurement failed: {e}")


def status_line(workers: list[CameraWorker], prev: dict, dt: float) -> str:
    parts = []
    for w in workers:
        s = w.stats.snapshot()
        p = prev.get(w.cc.cam, {"frames": 0, "bytes": 0, "send_s": 0.0})
        nf = s["frames"] - p["frames"]
        fps = nf / dt if dt > 0 else 0.0
        kbps = (s["bytes"] - p["bytes"]) * 8 / 1000 / dt if dt > 0 else 0.0
        sms = (s["send_s"] - p["send_s"]) / nf * 1000 if nf else 0.0
        parts.append(f"cam{w.cc.cam} {fps:4.1f} fps {kbps:7.0f} kbit/s sent {s['frames']} "
                     f"err {s['errors']}/{s['source_errors']} late {s['late']} spread {sms:.1f} ms "
                     f"burst {s['max_burst_seen']}")
        prev[w.cc.cam] = s
    return " | ".join(parts)


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="python -m tools.rk_sim",
                                 description="RK3588 simulator: FrameLink camera frames on UDP.")
    ap.add_argument("--config", default="config/sim.yaml")
    ap.add_argument("--seconds", type=float, default=None, help="stop after N s (0 = no limit)")
    ap.add_argument("--fmt", choices=("h265", "nv12"), default=None)
    ap.add_argument("--cams", default=None, help="comma list, for example 0,1,2,3,4,5")
    ap.add_argument("--host", default=None)
    ap.add_argument("--base-port", type=int, default=None)
    ap.add_argument("--source", choices=("file", "test-pattern"), default=None,
                    help="use this source for all selected cameras")
    ap.add_argument("--sessions", default=None,
                    help="name of a session_sets entry in the config (bench, road) or a comma list "
                         "of session directories: the file list of every camera comes from them")
    ap.add_argument("--fps", type=float, default=None, help="frame rate of test-pattern sources")
    ap.add_argument("--fragment-payload", type=int, default=None)
    ap.add_argument("--transcode", action="store_true", help="h265 from file: decode + encode, short GOP")
    ap.add_argument("--no-pace", action="store_true", help="send all datagrams of a frame at once")
    ap.add_argument("--no-measure-idr", action="store_true")
    ap.add_argument("--status-interval", type=float, default=None, help="status line period, s")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(sys.argv[1:] if argv is None else argv)
    cfg = cfgmod.apply_args(cfgmod.load(a.config), a)
    if not cfg.cameras:
        log("ERROR: no camera selected")
        return 2
    stop = threading.Event()

    def on_signal(signum, _frame):
        log(f"signal {signal.Signals(signum).name}: stop")
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    workers = [CameraWorker(cc, cfg, stop) for cc in cfg.cameras]
    log(f"RK3588 SIMULATOR: fmt {cfg.fmt}{' (transcode)' if cfg.transcode and cfg.fmt == 'h265' else ''}, "
        f"to {cfg.host}:{cfg.base_port}+cam, fragment payload {cfg.fragment_payload} B, "
        f"pace {'on' if cfg.pace else 'off'} (max {cfg.pace_fraction:.0%} of frame interval), "
        f"SO_SNDBUF {workers[0].sender.sndbuf} B. source is never LIVE.")
    for w in workers:
        src = w.kind if w.kind != "file" else f"file x{len(w.files)} ({os.path.basename(w.files[0])} ...)"
        size = (f"{w.cc.width}x{w.cc.height}" if cfg.fmt == "nv12" else
                ("file size" if w.kind == "file" and not cfg.transcode else
                 f"{cfg.h265_width}x{cfg.h265_height}"))
        log(f"cam{w.cc.cam} {w.cc.role}: {src}, {size} -> udp {cfg.host}:{cfg.base_port + w.cc.cam}")
    for w in workers:
        w.start()
    if cfg.measure_idr:
        threading.Thread(target=measure_idr_bg, args=(cfg, workers, stop), name="idr",
                         daemon=True).start()

    # --seconds counts from the first frame of every camera (pipeline start-up is not counted)
    t0 = time.monotonic()
    for w in workers:
        if not w.first_sent.wait(max(0.0, t0 + 10.0 - time.monotonic())) or stop.is_set():
            break
    if not stop.is_set():
        log(f"first frame of all cameras after {time.monotonic() - t0:.2f} s" if
            all(w.first_sent.is_set() for w in workers) else
            "WARNING: some cameras sent no frame in 10 s: " +
            ",".join(w.name for w in workers if not w.first_sent.is_set()))
    t_start = time.monotonic()
    t_last = t_start
    prev: dict = {}
    try:
        while not stop.is_set():
            remain = cfg.status_interval_s
            if cfg.seconds > 0:
                remain = min(remain, t_start + cfg.seconds - time.monotonic())
                if remain <= 0:
                    break
            stop.wait(max(remain, 0.0))
            now = time.monotonic()
            if now - t_last >= cfg.status_interval_s - 0.01:
                log(status_line(workers, prev, now - t_last))
                t_last = now
    finally:
        stop.set()
        now = time.monotonic()
        for w in workers:
            w.join(timeout=5.0)
        log("final: " + status_line(workers, {}, now - t_start).replace(" fps", " fps(avg)"))
        alive = [w.name for w in workers if w.is_alive()]
        if alive:
            log(f"WARNING: threads still running: {alive}")
    return 0
