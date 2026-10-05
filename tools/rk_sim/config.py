"""Configuration of the RK3588 simulator: config/sim.yaml plus command line overrides."""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

import yaml

from common.framelink import BASE_PORT, FRAG_PAYLOAD_JUMBO

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# RK design camera sizes for fmt nv12 (cam0 model size, cam1-5 model size)
RK_SIZE = {0: (1280, 720)}
RK_SIZE_SIDE = (704, 396)
ROLES = {0: "front", 1: "right", 2: "left", 3: "right-back", 4: "left-back", 5: "back"}


@dataclass
class CamCfg:
    cam: int
    role: str
    source: str               # "file" | "test-pattern"
    width: int
    height: int
    files: list[str] = field(default_factory=list)


@dataclass
class SimCfg:
    host: str = "127.0.0.1"
    base_port: int = BASE_PORT
    fps: float = 30.0
    fmt: str = "h265"
    fragment_payload: int = FRAG_PAYLOAD_JUMBO
    pace: bool = True
    pace_fraction: float = 0.6
    sndbuf: int = 4 * 1024 * 1024
    status_interval_s: float = 5.0
    measure_idr: bool = True
    transcode: bool = False
    h265_width: int = 1280
    h265_height: int = 720
    h265_bitrate: int = 4_000_000
    h265_iframeinterval: int = 15
    h265_idrinterval: int = 15
    seconds: float = 0.0      # 0 = run until SIGINT / SIGTERM
    video_root: str = ""
    session_sets: dict = field(default_factory=dict)
    cameras: list[CamCfg] = field(default_factory=list)


def resolve_path(p: str) -> str:
    """Absolute path; a relative path is first tried from the current directory, then the project."""
    if os.path.isabs(p) or os.path.exists(p):
        return os.path.abspath(p)
    return os.path.join(PROJECT_ROOT, p)


def load(path: str | None) -> SimCfg:
    raw: dict = {}
    if path:
        with open(resolve_path(path), encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    c = SimCfg()
    for k in ("host", "base_port", "fps", "fmt", "fragment_payload", "pace", "pace_fraction",
              "sndbuf", "status_interval_s", "measure_idr", "transcode"):
        if k in raw:
            setattr(c, k, type(getattr(c, k))(raw[k]))
    h = raw.get("h265") or {}
    c.h265_width = int(h.get("width", c.h265_width))
    c.h265_height = int(h.get("height", c.h265_height))
    c.h265_bitrate = int(h.get("bitrate", c.h265_bitrate))
    c.h265_iframeinterval = int(h.get("iframeinterval", c.h265_iframeinterval))
    c.h265_idrinterval = int(h.get("idrinterval", c.h265_idrinterval))
    root = c.video_root = str(raw.get("video_root", ""))
    c.session_sets = {str(k): [str(x) for x in v] for k, v in (raw.get("session_sets") or {}).items()}
    cams = raw.get("cameras")
    if not cams:  # no list in the file: six test-pattern cameras
        cams = [{"cam": n, "source": "test-pattern"} for n in range(6)]
    for d in cams:
        n = int(d["cam"])
        w, hh = RK_SIZE.get(n, RK_SIZE_SIDE)
        files = [f if os.path.isabs(f) else os.path.join(root, f) for f in (d.get("files") or [])]
        c.cameras.append(CamCfg(cam=n, role=str(d.get("role", ROLES.get(n, f"cam{n}"))),
                                source=str(d.get("source", "file" if files else "test-pattern")),
                                width=int(d.get("width", w)), height=int(d.get("height", hh)),
                                files=files))
    return c


def session_files(c: SimCfg, sessions: list[str], cam: int) -> list[str]:
    """Files of camera `cam` in the sessions: <video_root>/<session>/<role dir>/cam<N>_*.mp4."""
    out = []
    for sname in sessions:
        d = sname if os.path.isabs(sname) else os.path.join(c.video_root, sname)
        out += sorted(glob.glob(os.path.join(d, "*", f"cam{cam}_*.mp4")))
    return out


def apply_sessions(c: SimCfg, spec: str) -> list[str]:
    """--sessions NAME (a key of session_sets) or S1,S2,...: replace the file list of every
    file camera. Returns the session list."""
    sessions = c.session_sets.get(spec) or [x.strip() for x in spec.split(",") if x.strip()]
    for cc in c.cameras:
        cc.files = session_files(c, sessions, cc.cam)
        if cc.source == "file" and not cc.files:
            raise ValueError(f"cam{cc.cam}: no file in sessions {sessions}")
    return sessions


def apply_args(c: SimCfg, a) -> SimCfg:
    """Apply argparse overrides (None = keep the config value)."""
    if a.host is not None:
        c.host = a.host
    if a.base_port is not None:
        c.base_port = a.base_port
    if a.fmt is not None:
        c.fmt = a.fmt
    if a.seconds is not None:
        c.seconds = a.seconds
    if a.fps is not None:
        c.fps = a.fps
    if a.fragment_payload is not None:
        c.fragment_payload = a.fragment_payload
    if a.no_pace:
        c.pace = False
    if a.transcode:
        c.transcode = True
    if a.status_interval is not None:
        c.status_interval_s = a.status_interval
    if a.no_measure_idr:
        c.measure_idr = False
    if a.cams is not None:
        want = [int(x) for x in a.cams.split(",") if x.strip() != ""]
        have = {cc.cam: cc for cc in c.cameras}
        out = []
        for n in want:
            if n in have:
                out.append(have[n])
            else:  # camera not in the config: use a test pattern at the RK size
                w, h = RK_SIZE.get(n, RK_SIZE_SIDE)
                out.append(CamCfg(n, ROLES.get(n, f"cam{n}"), "test-pattern", w, h))
        c.cameras = out
    if a.source is not None:
        for cc in c.cameras:
            cc.source = a.source
    if a.sessions:
        apply_sessions(c, a.sessions)
    if c.fmt not in ("h265", "nv12"):
        raise ValueError(f"fmt must be h265 or nv12, not {c.fmt!r}")
    for cc in c.cameras:
        if cc.source not in ("file", "test-pattern"):
            raise ValueError(f"cam{cc.cam}: source must be file or test-pattern, not {cc.source!r}")
        if not 0 <= cc.cam <= 255:
            raise ValueError(f"cam {cc.cam} out of range")
    return c
