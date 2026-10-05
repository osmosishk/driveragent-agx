"""FrameLink UDP sender for one camera, with datagram pacing and counters."""
from __future__ import annotations

import socket
import threading
import time

from common.framelink import FrameHeader, fragments, pack_frame


class Stats:
    """Counters of one camera. The sender thread writes, the status thread reads (snapshot)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.frames = 0
        self.datagrams = 0
        self.bytes = 0
        self.errors = 0           # failed sendto() calls
        self.source_errors = 0    # pipeline errors, missing files
        self.late = 0             # frames that left the appsink later than 2 frame intervals
        self.send_s = 0.0         # sum of the time from first to last datagram of a frame
        self.max_burst_seen = 0   # longest run of datagrams sent back-to-back (< gap/4 apart)
        self.last_error = ""
        self.file = ""

    def snapshot(self) -> dict:
        with self.lock:
            return dict(frames=self.frames, datagrams=self.datagrams, bytes=self.bytes,
                        errors=self.errors, source_errors=self.source_errors, late=self.late,
                        send_s=self.send_s, last_error=self.last_error, file=self.file,
                        max_burst_seen=self.max_burst_seen)


class FrameLinkSender:
    """Sends one FrameLink frame as fragments. Pacing: the datagrams of one frame are spread
    evenly over min(pace_fraction * frame interval, n * gap_s). gap_s limits the datagram rate
    (default 150 us per datagram, about 59 MB/s at 8912 B datagrams), so small H.265 frames are
    not delayed by a long spread and large NV12 frames never use more than pace_fraction.

    No catch-up burst: each datagram is due one gap after the previous one. When the thread is late
    (GIL wait, scheduler, SIGSTOP), at most max_burst datagrams go out back-to-back, then the gap
    applies again. Before this fix a late thread sent all remaining datagrams of the frame at once
    (cam0 NV12: up to 156 x 8912 B = 1.39 MB), which overflows the receive buffer (rmem_max 212992 B).
    The frame then takes longer than the pace window; the frame loop in sim.py does not catch up.
    max_burst_seen counts the longest back-to-back run (status line "burst")."""

    def __init__(self, host: str, port: int, cam: int, frag_payload: int, pace: bool = True,
                 pace_fraction: float = 0.6, gap_s: float = 150e-6, sndbuf: int = 4 << 20,
                 stats: Stats | None = None, max_burst: int = 4):
        self.addr = (host, port)
        self.cam = cam
        self.frag_payload = frag_payload
        self.pace = pace
        self.pace_fraction = pace_fraction
        self.gap_s = gap_s
        self.max_burst = max(1, int(max_burst))
        self.stats = stats or Stats()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf)
        except OSError:
            pass
        self.sndbuf = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)

    def send(self, hdr: FrameHeader, payload, interval_s: float) -> int:
        """Pack and send one frame. Returns the number of datagrams sent without error."""
        frame = pack_frame(hdr, payload)
        dgrams = list(fragments(frame, self.cam, hdr.seq, self.frag_payload))
        n = len(dgrams)
        gap = 0.0
        if self.pace and n > 1:
            span = min(self.pace_fraction * interval_s, n * self.gap_s)
            gap = span / n
        ok = nbytes = err = 0
        last_err = ""
        pc = time.perf_counter
        t0 = pc()
        t_next = t0               # time when the next datagram is due
        slack = self.max_burst * gap
        run = run_max = 0         # datagrams sent less than gap/4 after the previous one
        t_prev = -1.0
        for d in dgrams:
            if gap:
                now = pc()
                dt = t_next - now
                if dt > 50e-6:
                    time.sleep(dt)
                # next datagram: one gap after this one; a late thread may catch up at most
                # max_burst datagrams
                t_next = max(t_next, now - slack) + gap
                t_send = pc()
                if t_send - t_prev < 0.25 * gap:
                    run += 1
                    run_max = max(run_max, run)
                else:
                    run = 1
                t_prev = t_send
            try:
                self.sock.sendto(d, self.addr)
                ok += 1
                nbytes += len(d)
            except OSError as e:
                err += 1
                last_err = f"sendto: {e}"
        t1 = time.perf_counter()
        st = self.stats
        with st.lock:
            st.frames += 1
            st.datagrams += ok
            st.bytes += nbytes
            st.errors += err
            st.send_s += t1 - t0
            st.max_burst_seen = max(st.max_burst_seen, run_max)
            if last_err:
                st.last_error = last_err
        return ok

    def close(self) -> None:
        self.sock.close()
