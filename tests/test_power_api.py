"""Power log of the AGX02 dashboard: the routes (dashboard/power_api.py) and the logger (dashboard/power_log.py).

In-process app (start_collectors=False: no thread, no sensor read), a PowerLog in tmp_path with stored samples, a fake
health snapshot for the logger. Never the real data/power.sqlite.

Run: PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_power_api.py
"""
import base64
import csv
import io
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from common.powerlog import NO_SENSOR, SENSOR, PowerLog, Reading

PW = "power-test-pw-0001"
TOKEN = "p" * 43
RAILS = {"VDD_GPU_SOC": {"v": 19.1, "a": 0.6, "w": 11.5}, "VDD_CPU_CV": {"v": 19.1, "a": 0.15, "w": 2.8},
         "VIN_SYS_5V0": {"v": 5.0, "a": 1.4, "w": 7.2}, "VDDQ_VDD2_1V8AO": {"v": 1.8, "a": 0.5, "w": 0.9}}


def basic(u="u", p=PW):
    return {"Authorization": "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()}


def power(rails=RAILS):
    return {"total_w": 22.4, "total_source": "sum", "total_rails": sorted(rails), "rails": json.loads(json.dumps(rails))}


@pytest.fixture()
def client(tmp_path):
    from dashboard.app import create_app
    from dashboard.config import load_config

    tok = tmp_path / "control.token"
    tok.write_text(TOKEN + "\n")
    os.chmod(tok, 0o600)
    cfg = load_config("config/dashboard.yaml")
    cfg.update({"model_store": str(tmp_path / "store"), "control_token_file": str(tok),
                "control_config": str(tmp_path / "control.yaml"),
                "paired_boards_file": str(tmp_path / "paired_boards.json"),
                "link_settings_file": str(tmp_path / "link_settings.json")})
    cfg["history"]["db"] = str(tmp_path / "h.sqlite")
    cfg["engines"]["cache"] = str(tmp_path / "ec.json")
    cfg["power_log"]["db"] = str(tmp_path / "power.sqlite")
    app = create_app(cfg, env={"AGX_DASH_USER": "u", "AGX_DASH_PASSWORD": PW}, start_collectors=False,
                     migrate=True)   # the token file becomes a paired board: its token works on /api/power/now
    hub = app.state.hub
    assert hub.power.log is None and not (tmp_path / "power.sqlite").exists()   # no file without the collectors
    lg = hub.power.open()
    now = time.time()
    t0 = int(now) - 300
    for i in range(240):                     # 240 s of samples: 20 W, then 30 W after the event at t0 + 120
        w = 20.0 if i < 120 else 30.0
        lg.add([Reading("agx02", w, SENSOR, t0 + i, "jetson_rails", "test rails", {"VDD_GPU_SOC": w / 2})])
    lg.flush()
    lg.note_state({"models": ["a@1"], "power_mode": "MAXN"}, t0 - 10)
    lg.note_state({"models": ["a@1", "b@1"]}, t0 + 120)
    hub.power.process(now, power(), "MAXN")
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        c.hub, c.t0 = hub, t0
        yield c


def test_power_doc(client):
    r = client.get("/api/power", headers=basic())
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["schema"] == "agx-power/1" and d["power_mode"] == "MAXN"
    n = d["now"]
    assert n["part"] == "agx02" and n["label"] == SENSOR and n["watts"] == pytest.approx(22.4)
    assert set(n["rails"]) == set(RAILS) and "supply input is not measured" in n["what"] and n["age_s"] < 3
    assert set(d["state"]) >= {"models", "link", "cameras", "power_mode", "control_mode", "sender", "agx_unit",
                               "recording"}
    assert d["state"]["sender"] is None and d["state"]["control_mode"] == "bench"
    assert d["log"]["rows"]["s1"] >= 240 and d["log"]["path"].endswith("power.sqlite") and not d["log"]["error"]
    assert d["sources"][0]["source"] == "jetson_rails" and "health snapshot" in d["sources"][0]["via"]


def test_now_route_and_token(client):
    tok = {"Authorization": "Bearer " + TOKEN}
    for h in (basic(), tok):
        r = client.get("/api/power/now", headers=h)
        assert r.status_code == 200
        assert set(r.json()) == {"part", "watts", "label", "t", "rails", "what", "power_mode"}
    for path in ("/api/power", "/api/power/samples", "/api/power/events", "/api/power/energy", "/api/power/export",
                 "/api/health"):
        assert client.get(path, headers=tok).status_code == 401, path
    assert client.get("/api/power/now").status_code == 401


def test_now_is_no_sensor_when_old(client):
    client.hub.power.process(time.time() - 10, power(), "MAXN")
    d = client.get("/api/power/now", headers=basic()).json()
    assert d["label"] == NO_SENSOR and d["watts"] is None and "no new sample" in d["what"]


def test_samples_and_events_in_range(client):
    d = client.get("/api/power/samples?range=1h", headers=basic()).json()
    assert d["range"] == "1h" and d["bucket_s"] == 1 and list(d["series"]) == ["agx02"]
    vals = [v for v in d["series"]["agx02"] if v is not None]
    assert 20.0 in vals and 30.0 in vals and len(d["t"]) == len(d["series"]["agx02"]) == len(d["seconds"]["agx02"])
    kinds = [(e["kind"], e["value"]) for e in d["events"]]
    assert ("models", ["a@1", "b@1"]) in kinds
    assert set(d["events"][0]) == {"t", "kind", "value", "prev", "exact"}
    d = client.get("/api/power/samples?range=24h&rails=1", headers=basic()).json()
    assert d["bucket_s"] == 60 and {"agx02", "agx02:VDD_GPU_SOC"} <= set(d["series"])
    assert all(k == "agx02" or k.startswith("agx02:") for k in d["series"])
    for rg, b in (("7d", 600), ("30d", 3600)):
        assert client.get(f"/api/power/samples?range={rg}", headers=basic()).json()["bucket_s"] == b


@pytest.mark.parametrize("q", ["range=2h", "range=", "range=1h&rails=2", "rails=yes"])
def test_samples_bad_args(client, q):
    r = client.get("/api/power/samples?" + q, headers=basic())
    assert r.status_code == 400 and "error" in r.json()


def test_events_before_after(client):
    rows = client.get("/api/power/events", headers=basic()).json()["rows"]
    ev = [r for r in rows if r["kind"] == "models"][0]
    p = ev["parts"]["agx02"]
    assert p["before_w"] == pytest.approx(20.0) and p["after_w"] == pytest.approx(30.0)
    assert p["diff_w"] == pytest.approx(10.0)
    assert len(client.get("/api/power/events?limit=1", headers=basic()).json()["rows"]) == 1
    for q in ("0", "101", "x", "-1", "2.5"):
        r = client.get("/api/power/events?limit=" + q, headers=basic())
        assert r.status_code == 400, q


def test_energy(client):
    d = client.get("/api/power/energy", headers=basic()).json()
    assert set(d) == {"today", "d7", "d30"}
    e = d["d7"]["agx02"]
    # 120 s at 20 W + 120 s at 30 W (+ the one sample of now) = 6000 Ws = 1.667 Wh
    assert e["wh"] == pytest.approx(6022.4 / 3600, abs=0.01) and e["hours"] == pytest.approx(241 / 3600, abs=1e-3)
    assert d["d30"]["agx02"]["wh"] == pytest.approx(e["wh"])


def test_export_csv(client):
    r = client.get("/api/power/export?kind=samples&range=1h", headers=basic())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="agx02-power-samples-1h-')
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:4] == ["time_utc", "unix_s", "series", "watts_sensor"] and len(rows) > 200
    assert {x[2] for x in rows[1:]} == {"agx02"} and all(x[5] == SENSOR for x in rows[1:])
    r = client.get("/api/power/export?kind=events&range=24h", headers=basic())
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][2] == "kind" and any(x[2] == "models" for x in rows[1:])
    for q in ("kind=x", "kind=samples&range=1y", "kind=events&rails=3"):
        assert client.get("/api/power/export?" + q, headers=basic()).status_code == 400, q


def test_routes_503_when_log_not_open(client):
    client.hub.power.log = None
    r = client.get("/api/power/samples", headers=basic())
    assert r.status_code == 503 and r.json()["error"]
    assert client.get("/api/power", headers=basic()).json()["log"]["error"]


# ---------------------------------------------------------------- the logger (fake hub, fake snapshot)
class _Health:
    def __init__(self):
        self.fns = []

    def add_listener(self, fn):
        self.fns.append(fn)


class _Infer:
    def __init__(self):
        self.st = None

    def current(self):
        if self.st is None:
            return None, "NO DATA", "agx-infer is not running", None
        return self.st, "RUNNING", None, 0.2


class _Pairing:
    def __init__(self, boards):
        self.b = boards

    def boards(self):
        return json.loads(json.dumps(self.b))


class _Hub:
    def __init__(self, boards=()):
        self.health, self.infer, self.controller = _Health(), _Infer(), None
        self.pairing = _Pairing(list(boards))


def _logger(tmp_path, boards=()):
    from dashboard.power_log import PowerLogger

    cfg = {"model_store": str(tmp_path / "store"), "control_config": str(tmp_path / "control.yaml"),
           "power_log": {"db": str(tmp_path / "p.sqlite"), "enabled": True}}
    hub = _Hub(boards)
    pl = PowerLogger(cfg, hub)
    pl.open()
    return pl, hub


def test_reading_from_snapshot():
    from dashboard.power_log import reading_from_power

    r = reading_from_power(power(), 100.0)
    assert r.label == SENSOR and r.watts == pytest.approx(22.4) and r.t == 100.0 and r.source == "jetson_rails"
    assert r.rails["VDDQ_VDD2_1V8AO"] == 0.9 and "VIN_SYS_5V0" in r.what
    bad = dict(RAILS, VDD_CPU_CV={"v": None, "a": None, "w": None, "na": "not readable"})
    r = reading_from_power(power(bad), 100.0)
    assert r.label == NO_SENSOR and r.watts is None and "VDD_CPU_CV" in r.what
    r = reading_from_power(power(dict(RAILS, VDD_IN={"v": 19, "a": 2, "w": 38.0})), 1.0)
    assert r.watts == 38.0 and "VDD_IN" in r.what
    assert reading_from_power({"total_w": None, "rails": {}}, 1.0) is None


def test_fallback_when_snapshot_has_no_power(tmp_path):
    pl, _hub = _logger(tmp_path)

    class _Rails:
        n = 0

        def read(self, t):
            self.n += 1
            return [Reading("agx02", 5.0, SENSOR, t, "jetson_rails", "fallback", {"X": 5.0})]

    pl._rails = _Rails()
    assert pl.reading(power(), 1.0).watts == pytest.approx(22.4) and pl._rails.n == 0   # no second sensor read
    assert pl.reading(None, 1.0).what == "fallback" and pl.reading({"rails": {}}, 1.0).watts == 5.0


def test_state_from_files_infer_and_pairing(tmp_path):
    (tmp_path / "store" / "_state").mkdir(parents=True)
    (tmp_path / "store" / "_state" / "active.json").write_text(json.dumps(
        {"set": [{"name": "y", "version": "1", "cameras": [0]}, {"name": "d", "version": "2", "cameras": [0]}]}))
    (tmp_path / "control.yaml").write_text("control_mode: vehicle\n")
    pl, hub = _logger(tmp_path, [{"id": "a", "addresses": ["10.0.0.5"], "last_seen_t": 5},
                                 {"id": "b", "addresses": ["10.0.0.6"], "last_seen_t": 9}])
    st = pl.build_state("MAXN")
    assert st["models"] == ["d@2", "y@1"] and st["control_mode"] == "vehicle" and st["power_mode"] == "MAXN"
    assert st["cameras"] is None and st["link"] == "NO DATA"
    assert st["sender"] is None and st["agx_unit"] is None and st["recording"] is None
    hub.infer.st = {"cameras": [{"state": "OK"}, {"state": "STALE"}, {"state": "NO SIGNAL"}, {"state": "SIMULATED"}],
                    "board_sources": {"10.0.0.6": {"framelink_frames_3s": 30, "result_subscriber": True}},
                    "result_subscribers": {"addresses": ["10.0.0.6"]}}
    st = pl.build_state(None)
    assert st["cameras"] == 3 and st["link"] == "UP" and st["power_mode"] is None   # the newest last_seen: board b
    hub.pairing.b = []
    assert pl.build_state(None)["link"] == "no paired board"
    (tmp_path / "store" / "_state" / "active.json").write_text(json.dumps({"set": []}) + " ")   # new size: read again
    assert pl.build_state(None)["models"] == []
    os.unlink(tmp_path / "control.yaml")
    assert pl.build_state(None)["control_mode"] == "bench"


def test_events_need_hold_time(tmp_path):
    pl, _hub = _logger(tmp_path)
    base = {"models": ["a@1"], "link": "UP", "cameras": 6, "power_mode": "MAXN", "control_mode": "bench"}
    assert pl.note(dict(base), 1000.0) == []                       # the first state: stored, no event (empty log)
    assert pl.note(dict(base, cameras=5), 1001.0) == []            # a short flicker ...
    assert pl.note(dict(base), 1002.0) == []                       # ... makes no event
    assert pl.note(dict(base, link="DOWN"), 1003.0) == []
    assert pl.note(dict(base, link="DOWN"), 1005.0) == []
    ev = pl.note(dict(base, link="DOWN", cameras=None), 1006.0)     # 3 s: the event, at the first second
    assert [(e["kind"], e["t"], e["value"], e["prev"]) for e in ev] == [("link", 1003.0, '"DOWN"', '"UP"')]
    assert pl.log.events(0, 2000)[0]["exact"] is True
    # a restart: the first state goes to the log at once; a change while the log did not run gets exact=0
    pl.log.close()
    pl2, _ = _logger(tmp_path)
    ev = pl2.note(dict(base, link="DOWN", power_mode="50W"), 2000.0)
    assert [(e["kind"], e["exact"]) for e in ev] == [("power_mode", 0)]


def test_listener_only_queues_and_process_writes(tmp_path):
    pl, hub = _logger(tmp_path)
    pl.start()
    try:
        assert hub.health.fns == [pl.on_sample]
        now = time.time()
        for i in range(3):
            pl.on_sample({"t": now + i, "power": power(), "nvpmodel": {"mode": "MAXN", "id": 0, "error": None}})
        deadline = time.time() + 5
        while pl.now is None or pl.now.t < now + 2:
            assert time.time() < deadline, "the power-log thread did not take the samples"
            time.sleep(0.05)
        assert pl.now_doc(now + 2)["label"] == SENSOR and pl.state_doc()["power_mode"] == "MAXN"
    finally:
        pl.stop()
    lg = PowerLog(str(tmp_path / "p.sqlite"), readonly=True)
    assert lg.size()["rows"]["s1"] >= 3 * 5     # close() wrote the last samples: total + 4 rails per second
    lg.close()


def test_queue_full_drops_and_counts(tmp_path):
    pl, _hub = _logger(tmp_path)
    for i in range(40):
        pl.on_sample({"t": float(i), "power": power()})
    assert pl.dropped == 10 and "10 samples dropped" in pl.log_doc()["error"]


def test_off_by_config(tmp_path):
    from dashboard.power_log import PowerLogger

    hub = _Hub()
    pl = PowerLogger({"power_log": {"db": str(tmp_path / "off.sqlite"), "enabled": False}}, hub)
    pl.start()
    pl.stop()
    assert pl.log is None and not (tmp_path / "off.sqlite").exists() and hub.health.fns == []
    assert pl.now_doc()["label"] == NO_SENSOR and "off" in pl.log_doc()["error"]


def test_first_state_waits_for_the_infer_status(tmp_path):
    # before the stop: link UP, 6 cameras. Just after the start the agx-infer status is not received yet (link
    # "NO DATA", cameras not known): that must make no event.
    pl, hub = _logger(tmp_path, [{"id": "b", "addresses": ["10.0.0.6"], "last_seen_t": 9}])
    pl.log.note_state({"link": "UP", "cameras": 6}, 900.0)
    up = {"cameras": [{"state": "OK"}] * 6, "board_sources": {"10.0.0.6": {"framelink_frames_3s": 30}},
          "result_subscribers": {"addresses": ["10.0.0.6"]}}
    pl.process(1000.0, power(), "MAXN")                     # no agx-infer status yet
    hub.infer.st = up
    for t in range(1001, 1010):
        pl.process(float(t), power(), "MAXN")
    assert [e for e in pl.log.events(0, 2000) if e["kind"] in ("link", "cameras")] == []


def test_old_partial_rails_are_not_shown_as_now(tmp_path):
    pl, _hub = _logger(tmp_path)
    bad = dict(RAILS, VDD_CPU_CV={"v": None, "a": None, "w": None, "na": "not readable"})
    pl.process(100.0, power(bad), "MAXN")
    assert pl.now_doc(101.0)["rails"]                       # the rails that read, now
    d = pl.now_doc(110.0)
    assert d["label"] == NO_SENSOR and d["watts"] is None and d["rails"] == {}
