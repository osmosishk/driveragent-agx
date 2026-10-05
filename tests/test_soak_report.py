"""R13: the soak report labels simulated input in the header and in the camera and model tables."""
import json

from tools import soak_report as sr


def _status(t, sim):
    return {"t": t, "node": {"state": "RUNNING", "simulated": sim, "errors": []},
            "cameras": [{"cam": 0, "fps": 30, "state": "SIMULATED" if sim else "OK", "simulated": sim,
                         "lost_frames": 0, "lost_packets": 0, "ring_overruns": 0}],
            "models": [{"name": "m", "fps": 10, "state": "RUNNING", "results_total": t,
                        "lat_ms": {"total": {"p50": 50, "p95": 70, "p99": 80}}}]}


def test_simulated_labels():
    sysmon = [{"t": float(i), "cpu_pct": 10, "ram_used_mb": 1000, "procs": {}} for i in range(5)]
    txt = sr.report(sysmon, [_status(i, True) for i in range(5)])
    assert "INPUT SOURCE: SIMULATED (5 of 5" in txt
    assert "| cam0 | SIMULATED |" in txt and "| m | SIMULATED |" in txt


def test_live_and_mixed_labels():
    sysmon = [{"t": float(i), "cpu_pct": 10, "ram_used_mb": 1000, "procs": {}} for i in range(4)]
    assert "INPUT SOURCE: LIVE" in sr.report(sysmon, [_status(i, False) for i in range(4)])
    mixed = sr.report(sysmon, [_status(0, True), _status(1, False)])
    assert "INPUT SOURCE: MIXED" in mixed and "| cam0 | MIXED |" in mixed
