"""#200: Pause holds a run. The tick leaves a paused run alone until Resume, and Pause finds
a run that already fired while its window is still open."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import db
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

NOW = dt.datetime(2026, 10, 21, 12, 5)


@pytest.fixture
def st(tmp_path, monkeypatch):
    s = MetricsStore(str(tmp_path / "m.db"))
    s.create_schedule(sid="p1", name="noon", spec={
        "fire_at": "12:00", "duration_min": 60, "gateway_id": "gw-a",
        "action": {"kind": "set_mode", "mode": "self"}})
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()
    return s


def _tick(st, monkeypatch, now=NOW, result="mode -> self: ok"):
    ran = []
    monkeypatch.setattr(sch, "run_action", lambda a, **k: ran.append(a) or result)
    sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
             gateway_id="gw-a", now=now, modbus_host="")
    return ran


def _forget_windows():
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()


def test_the_tick_leaves_a_paused_run_alone(st, monkeypatch):
    # A run still being retried (failed) is paused: the tick must not try it again.
    assert len(_tick(st, monkeypatch, result="mode -> self: failed: timeout")) >= 1
    assert st.occurrences_for("p1")[0]["status"] == "failed"
    st.pause_occurrence(st.occurrences_for("p1")[0]["id"])
    _forget_windows()
    assert _tick(st, monkeypatch, NOW + dt.timedelta(minutes=20)) == []
    assert st.occurrences_for("p1")[0]["status"] == "paused"


def test_pause_finds_a_run_that_already_fired(st, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda s=None: st)
    assert len(_tick(st, monkeypatch)) == 1
    assert st.occurrences_for("p1")[0]["status"] == "ok"
    monkeypatch.setattr(bc, "execute", lambda *a, **k: {"ok": True, "result": "ok"})
    import time as _time
    monkeypatch.setattr(_time, "time", lambda: NOW.timestamp() + 60)
    out = TestClient(app_module.create_app()).post("/api/schedules/p1/pause").json()
    assert out["paused"] is True
    assert st.occurrences_for("p1")[0]["status"] == "paused"


def test_resume_re_enters_a_run_that_had_fired(st, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda s=None: st)
    monkeypatch.setattr(bc, "execute", lambda *a, **k: {"ok": True, "result": "ok"})
    _tick(st, monkeypatch)
    import time as _time
    monkeypatch.setattr(_time, "time", lambda: NOW.timestamp() + 60)
    c = TestClient(app_module.create_app())
    assert c.post("/api/schedules/p1/pause").json()["paused"] is True
    assert c.post("/api/schedules/p1/resume").json()["resumed"] is True
    _forget_windows()
    assert len(_tick(st, monkeypatch, NOW + dt.timedelta(minutes=2))) == 1
