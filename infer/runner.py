"""Model workers: frame scheduling, TensorRT execution, timing and metrics.

One ModelWorker thread = one TensorRT ExecutionSlot. All workers of one model share one
FrameScheduler (claims under a per-model lock) and one ModelMetrics.

Scheduling (each worker, in a loop):
  1. cameras that are allowed now (max_fps_per_camera, token rule below)
  2. FrameStore.wait_new(those cameras, seq already claimed per camera, timeout <= 0.1 s)
     (the store gives only frames that are not stale)
  3. CLAIM under the model lock: of the returned frames, take the camera whose last processed time
     is the oldest (fairness). A claimed (cam, seq) is never given to a second worker.
  4. preprocess -> ExecutionSlot.infer -> postprocess, timed; build the result dict; on_result(result)
     at most once per (model, cam, seq), and never for a frame older than the last result given out
     for that camera (FrameScheduler.mark_emitted). Each claim keeps the camera "epoch" (it goes up
     on every source restart): a result of a frame claimed before a restart is never given out
     after the restart. A result whose frame is older than the stale time (FrameStore.stale_s,
     0.5 s) when it completes is dropped too (stale rule).

Rate rule per camera: claim only when now >= next_allowed; after a claim,
next_allowed = max(next_allowed + 1/max_fps, now + 0.5/max_fps). The long-run rate is <= max_fps
and a short delay (jitter) does not drop a frame.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from collections import deque

import numpy as np

log = logging.getLogger("agx.infer.runner")

LAT_WINDOW_S = 60.0
FPS_WINDOW_S = 5.0
LAT_STAGES = ("queue", "pre", "infer", "post", "total")
WAIT_TIMEOUT_S = 0.1


def _pcts(vals) -> dict:
    if not vals:
        return {"p50": None, "p95": None, "p99": None}
    a = np.asarray(vals, dtype=np.float64)
    p = np.percentile(a, [50, 95, 99])
    return {"p50": round(float(p[0]), 3), "p95": round(float(p[1]), 3), "p99": round(float(p[2]), 3)}


class ModelMetrics:
    """Thread-safe metrics of one model: fps (last 5 s), latency percentiles (last 60 s), counters."""

    def __init__(self, lat_window_s: float = LAT_WINDOW_S, fps_window_s: float = FPS_WINDOW_S,
                 maxlen: int = 50000):
        self.lat_window_s = lat_window_s
        self.fps_window_s = fps_window_s
        self._lock = threading.Lock()
        self._lat: deque = deque(maxlen=maxlen)    # (t_mono, queue, pre, infer, post, total)
        self._done: deque = deque(maxlen=maxlen)   # (t_mono, cam)
        self.results_total = 0
        self.results_by_cam: dict[int, int] = {}
        self.errors_total = 0
        self.consecutive_errors = 0
        self.on_result_errors = 0
        self.results_dropped_old = 0     # completed after a newer result of the same camera
        self.results_dropped_stale = 0   # frame older than the stale time when the result completed
        self.last_error: str | None = None
        self.last_error_t: float | None = None
        self.last_result_t: float | None = None
        self.running_since: float | None = None   # monotonic

    def add_result(self, cam: int, timing: dict, now_mono: float | None = None) -> None:
        now = time.monotonic() if now_mono is None else now_mono
        with self._lock:
            self._lat.append((now, timing["queue_ms"], timing["pre_ms"], timing["infer_ms"],
                              timing["post_ms"], timing["total_ms"]))
            self._done.append((now, cam))
            self.results_total += 1
            self.results_by_cam[cam] = self.results_by_cam.get(cam, 0) + 1
            self.consecutive_errors = 0
            self.last_result_t = time.time()

    def add_error(self, text: str) -> int:
        with self._lock:
            self.errors_total += 1
            self.consecutive_errors += 1
            self.last_error = text
            self.last_error_t = time.time()
            return self.consecutive_errors

    def _prune(self, now: float) -> None:
        while self._lat and now - self._lat[0][0] > self.lat_window_s:
            self._lat.popleft()
        while self._done and now - self._done[0][0] > self.fps_window_s:
            self._done.popleft()

    def _window(self, now: float) -> float:
        w = self.fps_window_s
        if self.running_since is not None:
            w = min(w, max(now - self.running_since, 0.5))
        return w

    def fps(self, now_mono: float | None = None) -> float:
        now = time.monotonic() if now_mono is None else now_mono
        with self._lock:
            self._prune(now)
            return round(len(self._done) / self._window(now), 2)

    def cam_fps(self, now_mono: float | None = None) -> dict:
        now = time.monotonic() if now_mono is None else now_mono
        with self._lock:
            self._prune(now)
            w = self._window(now)
            out: dict[int, float] = {}
            for _, c in self._done:
                out[c] = out.get(c, 0) + 1
            return {str(c): round(n / w, 2) for c, n in sorted(out.items())}

    def latency(self, now_mono: float | None = None) -> dict:
        now = time.monotonic() if now_mono is None else now_mono
        with self._lock:
            self._prune(now)
            rows = list(self._lat)
        out = {}
        for i, st in enumerate(LAT_STAGES):
            out[st] = _pcts([r[i + 1] for r in rows])
        return out


class FrameScheduler:
    """Per-model claim table. All methods are thread-safe."""

    def __init__(self, cams, max_fps_per_camera: float | None):
        self.cams = [int(c) for c in cams]
        self.lock = threading.Lock()
        mf = float(max_fps_per_camera or 0)
        self.interval = 1.0 / mf if mf > 0 else 0.0
        self.claimed_seq: dict[int, int] = {}
        self.claimed_tcap: dict[int, int] = {}
        self.last_start: dict[int, float] = {c: 0.0 for c in self.cams}
        self.next_allowed: dict[int, float] = {c: 0.0 for c in self.cams}
        self.last_emitted: dict[int, int] = {}
        self.epoch: dict[int, int] = {c: 0 for c in self.cams}   # +1 on every source restart
        self.restarts = 0

    def eligible(self, now: float) -> tuple[list[int], float]:
        """(cameras allowed now, seconds until the next not-allowed camera is allowed)."""
        with self.lock:
            ok, wait = [], WAIT_TIMEOUT_S
            for c in self.cams:
                d = self.next_allowed[c] - now
                if d <= 0:
                    ok.append(c)
                else:
                    wait = min(wait, d)
            return ok, max(wait, 0.001)

    def claimed_snapshot(self) -> dict[int, int]:
        with self.lock:
            return dict(self.claimed_seq)

    def claim(self, frames, now: float):
        """Pick and claim one frame of `frames` (fairness: oldest last processed camera). None if
        every frame is claimed already or its camera is not allowed now."""
        return self.claim_epoch(frames, now)[0]

    def claim_epoch(self, frames, now: float):
        """As claim(), but returns (frame, epoch of its camera at the claim) or (None, None). Give
        the epoch to mark_emitted()."""
        with self.lock:
            best = None
            for f in frames:
                c = f.cam
                if c not in self.next_allowed or now < self.next_allowed[c]:
                    continue
                last = self.claimed_seq.get(c)
                if last is not None and f.seq == last:
                    continue
                if last is not None and f.seq < last and f.t_capture_ns <= self.claimed_tcap.get(c, 0):
                    continue  # an older frame: never process it after a newer one
                if best is None or self.last_start[c] < self.last_start[best.cam]:
                    best = f
            if best is None:
                return None, None
            c = best.cam
            last = self.claimed_seq.get(c)
            if last is not None and best.seq < last:
                # seq went back with a newer capture time: the source restarted
                self.last_emitted.pop(c, None)
                self.epoch[c] = self.epoch.get(c, 0) + 1
                self.restarts += 1
            self.claimed_seq[c] = best.seq
            self.claimed_tcap[c] = best.t_capture_ns
            self.last_start[c] = now
            if self.interval > 0:
                self.next_allowed[c] = max(self.next_allowed[c] + self.interval, now + 0.5 * self.interval)
            return best, self.epoch.get(c, 0)

    def mark_emitted(self, cam: int, seq: int, epoch: int | None = None) -> bool:
        """True when (cam, seq) is newer than every result of this camera given out before (since
        the last source restart). False for a second result of the same frame, for the result of
        an older frame that completes after a newer one (two workers), and for the result of a
        frame claimed before the last source restart (epoch older than the current epoch): such a
        result is dropped, so a result is never sent twice and never after a newer one."""
        with self.lock:
            if epoch is not None and epoch != self.epoch.get(cam, 0):
                return False
            last = self.last_emitted.get(cam)
            if last is not None and seq <= last:
                return False
            self.last_emitted[cam] = seq
            return True


def adapter_outputs(adapter, outs: dict) -> dict:
    """Only the engine outputs that the adapter lists in ENGINE_OUTPUTS (rule R8: for DTCP only
    pred_wp; mu, sigma and pred_speed never reach postprocess). An adapter with an empty
    ENGINE_OUTPUTS gets all outputs (test adapters only; the real adapters list their outputs)."""
    names = getattr(adapter, "ENGINE_OUTPUTS", ()) or ()
    if not names:
        return outs
    return {k: outs[k] for k in names if k in outs}


class ModelWorker(threading.Thread):
    """One worker thread of one model. `entry` is the manager's ModelEntry (duck-typed): it gives
    name, cameras, adapter, engine, scheduler, metrics, stop_event and report_error(text) -> None."""

    def __init__(self, entry, index: int, slot, store, on_result):
        super().__init__(name=f"infer-{entry.name}-{index}", daemon=True)
        self.entry = entry
        self.index = index
        self.slot = slot
        self.store = store
        self.on_result = on_result
        self.stop_event: threading.Event = entry.stop_event

    def run(self) -> None:
        e = self.entry
        sched: FrameScheduler = e.scheduler
        while not self.stop_event.is_set():
            try:
                now = time.monotonic()
                cams, wait_s = sched.eligible(now)
                if not cams:
                    self.stop_event.wait(wait_s)
                    continue
                timeout = WAIT_TIMEOUT_S if len(cams) == len(sched.cams) else min(WAIT_TIMEOUT_S, wait_s)
                frames = self.store.wait_new(cams, sched.claimed_snapshot(), timeout)
                if not frames or self.stop_event.is_set():
                    continue
                frame, epoch = sched.claim_epoch(frames, time.monotonic())
                if frame is None:
                    continue
            except Exception as ex:  # scheduling error: a code bug, not a frame problem
                e.report_error(f"worker {self.index} scheduling: {type(ex).__name__}: {ex}", fatal=True)
                log.error("%s", traceback.format_exc())
                return
            self._process(frame, epoch)

    def _process(self, frame, epoch: int | None = None) -> None:
        e = self.entry
        t_start = time.monotonic()
        try:
            inputs, ctx = e.adapter.preprocess(frame)
            t_pre = time.monotonic()
            outs, infer_ms = self.slot.infer(inputs)
            t_inf = time.monotonic()
            parts = e.adapter.postprocess(adapter_outputs(e.adapter, outs), frame, ctx)
            t_end = time.monotonic()
        except Exception as ex:
            log.warning("model %s cam%d seq %d: %s", e.name, frame.cam, frame.seq, traceback.format_exc())
            e.report_error(f"cam{frame.cam} seq {frame.seq}: {type(ex).__name__}: {ex}")
            return
        t_result_ns = time.time_ns()
        timing = {
            "queue_ms": round((t_start - frame.t_ready_mono) * 1000.0, 3),
            "pre_ms": round((t_pre - t_start) * 1000.0, 3),
            "infer_ms": round(float(infer_ms), 3),
            "post_ms": round((t_end - t_inf) * 1000.0, 3),
            "total_ms": round((t_end - frame.t_ready_mono) * 1000.0, 3),
        }
        result = {
            "model": e.name,
            "model_version": e.engine.version_tag,
            "cam": int(frame.cam),
            "frame_seq": int(frame.seq),
            "t_capture_ns": int(frame.t_capture_ns),
            "t_recv_ns": int(frame.t_recv_ns),
            "t_ready_ns": int(frame.t_ready_ns),
            "t_result_ns": t_result_ns,
            "frame_w": int(frame.width),
            "frame_h": int(frame.height),
            "simulated": bool(frame.simulated),
            "source": frame.source,
            "detections": parts.get("detections") or [],
            "trajectory": parts.get("trajectory"),
            "masks": parts.get("masks") or [],
            "timing": timing,
        }
        if self.stop_event.is_set():  # model stopped or FAILED while this frame ran: no result
            return
        stale_s = getattr(self.store, "stale_s", None)
        if stale_s is not None and frame.age_s() >= stale_s:   # stale rule: no result of an old frame
            with e.metrics._lock:
                e.metrics.results_dropped_stale += 1
            return
        if not e.scheduler.mark_emitted(frame.cam, frame.seq, epoch):
            with e.metrics._lock:
                e.metrics.results_dropped_old += 1
            return
        e.metrics.add_result(frame.cam, timing)
        try:
            self.on_result(result)
        except Exception:  # a publisher problem: count it, the model keeps running
            with e.metrics._lock:
                e.metrics.on_result_errors += 1
            log.error("model %s: on_result failed: %s", e.name, traceback.format_exc())
