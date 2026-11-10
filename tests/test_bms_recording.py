"""Battery recordings (owner, 2026-11-11): Record from the live trend, scheduled recordings
on the Charts tab, and auto-purge at 90 days / 200 MB, both changeable in Settings."""

import datetime as dt
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, environment
from franklinwh_direct_connect_bridge import bms_record, db
from franklinwh_direct_connect_bridge.bms_record import Recorder
from franklinwh_direct_connect_bridge.db import MetricsStore

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"


def cells():
    return {"batVolt": [3300] * 16, "batTemp": [20.0] * 16, "batSoc": 50.0,
            "batSoh": 94.9, "batTotalVolt": 53.0, "currGrp": -4.0}


# -- Record from the live trend: up to 24 h ----------------------------------
def test_a_day_at_five_seconds_fits():
    assert bms_record.MAX_SAMPLES >= 24 * 3600 // 5


def test_live_trend_has_a_record_button_that_keeps_it_on_the_bridge():
    html = (ROOT / "templates/tabs/battery.html").read_text()
    js = (ROOT / "static/js/battery_tab.js").read_text()
    card = html[html.index("sample(s) this session"):html.index("<!-- Charts: recorded sessions -->")]
    assert "recordLive()" in card and "stopRecording()" in card
    assert "Not persisted" not in card
    assert "recordLive()" in js
    assert "Math.max(5" in js                    # never under the recorder's 5 s floor


# -- purge -------------------------------------------------------------------
def _session(s, started, n=3, ended=True):
    sid = s.start_bms_session(apower_sn="SN", now=started)
    for i in range(n):
        s.add_bms_sample(sid, cells(), ts=started + i)
    if ended:
        s.end_bms_session(sid, now=started + n)
    return sid


def test_old_finished_sessions_are_purged_by_age():
    s = MetricsStore(":memory:")
    now = 1_800_000_000
    old = _session(s, now - 100 * 86400)
    new = _session(s, now - 10 * 86400)
    assert s.prune_bms(90, 200, now) == 1
    assert s.bms_session(old) is None and s.bms_session(new) is not None
    s.close()


def test_oldest_go_first_past_the_size_cap_and_a_running_one_is_kept():
    s = MetricsStore(":memory:")
    now = 1_800_000_000
    a = _session(s, now - 3000, n=50)
    b = _session(s, now - 2000, n=50)
    running = _session(s, now - 5000, n=50, ended=False)     # oldest, but still recording
    per = s.bms_bytes() / 3
    cap_mb = (per * 2.5) / 1_000_000          # room for two and a half, running one included
    s.prune_bms(90, cap_mb, now)
    assert s.bms_session(running) is not None
    assert s.bms_session(a) is None and s.bms_session(b) is not None
    s.close()


def test_maintenance_purges_recordings():
    s = MetricsStore(":memory:")
    now = int(time.time())
    old = _session(s, now - 200 * 86400)
    db.history_maintenance(s, 365, now, bms_keep_days=90, bms_max_mb=200)
    assert s.bms_session(old) is None
    s.close()


def test_a_finished_recording_runs_the_purge(monkeypatch):
    s, r = MetricsStore(":memory:"), Recorder()
    old = _session(s, int(time.time()) - 200 * 86400)
    r.start(s, cells, samples=1, interval_s=5, purge=(90, 200))
    while r.status()["active"]:
        time.sleep(0.05)
    assert s.bms_session(old) is None
    s.close()


# -- schedules ---------------------------------------------------------------
def test_schedule_roundtrip_and_due():
    s = MetricsStore(":memory:")
    sid = s.add_bms_schedule(gateway_id="gw", at="02:00", minutes=30, interval_s=10,
                             days=[1, 3], dev_id=1)
    row = s.bms_schedules()[0]
    assert row["id"] == sid and row["days"] == [1, 3] and row["enabled"] is True
    tue = dt.datetime(2026, 11, 10, 2, 5)                    # a Tuesday (weekday 1)
    due = bms_record.due(s.bms_schedules(), tue)
    assert [d["id"] for d in due] == [sid]
    assert due[0]["samples"] == (30 - 5) * 60 // 10          # what is left of the window
    assert bms_record.due(s.bms_schedules(), tue.replace(hour=3)) == []     # window over
    assert bms_record.due(s.bms_schedules(), tue + dt.timedelta(days=1)) == []  # Wednesday
    s.set_bms_schedule_ran(sid, "2026-11-10")
    assert bms_record.due(s.bms_schedules(), tue) == []      # once a day
    s.update_bms_schedule(sid, enabled=False)
    s.set_bms_schedule_ran(sid, "")
    assert bms_record.due(s.bms_schedules(), tue) == []      # switched off
    assert s.delete_bms_schedule(sid) == 1 and s.bms_schedules() == []
    s.close()


def test_the_worker_starts_a_due_schedule_once_and_skips_while_one_runs(monkeypatch):
    from franklinwh_direct_connect_bridge import scheduler_worker, state, client as cl
    s = MetricsStore(":memory:")
    bms_record._recorder = Recorder()
    monkeypatch.setattr(scheduler_worker, "get_store", lambda settings: s)
    monkeypatch.setattr(cl, "battery", lambda *a, **k: {"cells": cells()})
    state.register_gateway("gw-rec", "10.0.0.9", "Home")
    try:
        now = dt.datetime.now()
        s.add_bms_schedule(gateway_id="gw-rec", at=now.strftime("%H:%M"), minutes=5,
                           interval_s=5, days=list(range(7)), dev_id=1)
        started = scheduler_worker.bms_schedule_tick(config.Settings(), now=now)
        assert len(started) == 1
        assert bms_record.get_recorder().status()["active"]
        assert scheduler_worker.bms_schedule_tick(config.Settings(), now=now) == []   # ran today
        bms_record.get_recorder().stop()
        while bms_record.get_recorder().status()["active"]:
            time.sleep(0.05)
    finally:
        state.unregister_gateway("gw-rec")
        s.close()


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    bms_record._recorder = Recorder()
    yield TestClient(app_module.create_app())
    store.close()
    config._settings = None


def test_schedule_routes(api):
    from franklinwh_direct_connect_bridge import state
    state.register_gateway("gw-s", "10.0.0.8", "Home")
    try:
        r = api.post("/api/battery/record/schedules?gateway=gw-s",
                     json={"at": "02:00", "minutes": 30, "interval_s": 10, "days": [0, 6],
                           "dev_id": 1})
        assert r.status_code == 200
        sid = r.json()["schedules"][0]["id"]
        assert api.post("/api/battery/record/schedules?gateway=gw-s",
                        json={"at": "25:00", "minutes": 30, "interval_s": 10,
                              "days": [0]}).status_code == 422
        assert api.post("/api/battery/record/schedules?gateway=gw-s",
                        json={"at": "02:00", "minutes": 30, "interval_s": 2,
                              "days": [0]}).status_code == 422
        r = api.post(f"/api/battery/record/schedules/{sid}?gateway=gw-s", json={"enabled": False})
        assert r.json()["schedules"][0]["enabled"] is False
        assert len(api.get("/api/battery/record/schedules?gateway=gw-s").json()["schedules"]) == 1
        assert api.delete(f"/api/battery/record/schedules/{sid}?gateway=gw-s").status_code == 200
        assert api.get("/api/battery/record/schedules?gateway=gw-s").json()["schedules"] == []
    finally:
        state.unregister_gateway("gw-s")


def test_purge_settings_are_shown_and_saved(api):
    info = api.get("/api/metrics/info").json()
    assert info["bms_keep_days"] == 90 and info["bms_max_mb"] == 200
    assert "bms_bytes" in info
    r = api.put("/api/metrics/settings", json={"bms_keep_days": 30, "bms_max_mb": 50})
    assert r.status_code == 200
    info = api.get("/api/metrics/info").json()
    assert info["bms_keep_days"] == 30 and info["bms_max_mb"] == 50
    assert api.put("/api/metrics/settings", json={"bms_keep_days": 0}).status_code == 422
    assert api.put("/api/metrics/settings", json={"bms_max_mb": -1}).status_code == 422


def test_charts_tab_and_settings_show_the_new_controls():
    html = (ROOT / "templates/tabs/battery.html").read_text()
    charts = html[html.index("<!-- Charts: recorded sessions -->"):]
    assert "Scheduled recordings" in charts and "saveSchedule()" in charts
    st = (ROOT / "templates/tabs/settings.html").read_text()
    assert "bms_keep_days" in st and "bms_max_mb" in st
