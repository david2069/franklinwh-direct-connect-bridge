"""#345 — the scheduler debug monitor says why each schedule is, or is not, running."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import sched_monitor as mon
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

NOON = dt.datetime(2026, 10, 28, 12, 5)


@pytest.fixture(autouse=True)
def _fresh():
    mon.clear()
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()
    yield
    mon.clear()


@pytest.fixture
def st(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


def _tick(st, now=NOON, soc=50):
    return sch.tick(settings=None, client=None, store=st, state={"soc": soc}, host="h",
                    gateway_id="gw-a", now=now, modbus_host="")


def _last(entry_id):
    return [ln for ln in mon.lines() if ln["entry_id"] == entry_id][-1]


def test_failing_condition_is_blocked_with_its_live_value(st):
    st.create_schedule(sid="b", name="low soc", spec={
        "gateway_id": "gw-a", "fire_at": "12:00", "duration_min": 60,
        "conditions": [{"sensor": "battery.soc_pct", "op": "<", "value": 20}]})
    _tick(st)
    ln = _last("b")
    assert ln["state"] == "blocked" and "live=50" in ln["detail"]
    assert ln["target"] == "gw-a"
    c = ln["conditions"][0]
    assert (c["kind"], c["sensor"], c["op"], c["value"], c["result"]) == \
        ("entry", "battery.soc_pct", "<", 20, False)
    assert c["live_value"] == 50


def test_outside_the_window_is_idle(st):
    st.create_schedule(sid="i", name="later", spec={"gateway_id": "gw-a", "fire_at": "18:00", "duration_min": 30})
    _tick(st)
    assert _last("i")["state"] == "idle" and "outside" in _last("i")["detail"]


def test_fires_then_stays_running_while_the_window_is_open(st):
    st.create_schedule(sid="r", name="noop", spec={"gateway_id": "gw-a", "fire_at": "12:00", "duration_min": 60})
    _tick(st)
    assert _last("r")["state"] == "running" and _last("r")["detail"].startswith("fired:")
    _tick(st, now=NOON + dt.timedelta(seconds=15))
    assert _last("r")["state"] == "running" and "window is open" in _last("r")["detail"]


def test_duration_hold_shows_seconds_left(st):
    st.create_schedule(sid="h", name="held", spec={
        "gateway_id": "gw-a", "fire_at": "12:00", "duration_min": 60, "entry_hold_s": 60})
    _tick(st)
    _tick(st, now=NOON + dt.timedelta(seconds=15))
    ln = _last("h")
    assert ln["state"] == "holding" and ln["detail"].startswith("45s left")


def test_the_loser_is_skipped_and_names_the_winner(st):
    for sid, prio in (("w", 9), ("l", 1)):
        st.create_schedule(sid=sid, name=f"rule-{sid}", spec={
            "gateway_id": "gw-a", "fire_at": "12:00", "duration_min": 60, "priority": prio,
            "action": {"kind": "set_mode", "mode": "self"}})
    _tick(st)
    assert _last("l")["state"] == "skipped" and "rule-w" in _last("l")["detail"]
    assert _last("w")["state"] in ("running", "retrying")


def test_a_disabled_schedule_writes_no_line(st):
    st.create_schedule(sid="d", name="off", spec={"gateway_id": "gw-a", "fire_at": "12:00", "duration_min": 60},
                       enabled=False)
    _tick(st)
    assert not [ln for ln in mon.lines() if ln["entry_id"] == "d"]


def test_a_failing_observer_never_breaks_the_tick(st, monkeypatch):
    st.create_schedule(sid="r", name="noop", spec={"gateway_id": "gw-a", "fire_at": "12:00", "duration_min": 60})
    def boom(**_):
        raise RuntimeError("observer")
    monkeypatch.setattr(mon, "record", boom)
    fired = _tick(st)
    assert [f["id"] for f in fired] == ["r"]


def test_ring_keeps_the_last_500_and_since_returns_only_newer():
    e = {"id": "x", "name": "x"}
    for _ in range(mon.MAX_LINES + 20):
        mon.record(gateway_id="g", entry=e, state="idle", detail="", snapshot={})
    allx = mon.lines()
    assert len(allx) == mon.MAX_LINES and allx[0]["seq"] == 21
    assert [ln["seq"] for ln in mon.lines(since=mon.last_seq() - 2)] == \
        [mon.last_seq() - 1, mon.last_seq()]
    assert mon.lines(entry_id="other") == []


def test_api_returns_lines_max_tick_and_last(st):
    mon.record(gateway_id="g", entry={"id": "a", "name": "A"}, state="idle", detail="",
               snapshot={})
    mon.record(gateway_id="g", entry={"id": "b", "name": "B"}, state="idle", detail="",
               snapshot={})
    c = TestClient(app_module.create_app())
    d = c.get("/api/scheduler/monitor").json()
    assert [ln["entry_id"] for ln in d["lines"]] == ["a", "b"]
    assert d["max"] == 500 and d["last"] == 2 and 5 <= d["tick_s"] <= 60
    assert [ln["entry_id"] for ln in
            c.get("/api/scheduler/monitor?entry_id=b").json()["lines"]] == ["b"]
    assert c.get("/api/scheduler/monitor?since=1").json()["lines"][0]["entry_id"] == "b"


def test_ui_card_polls_only_while_open_on_the_history_view():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    js = (root / "static/js/scheduler_tab.js").read_text()
    html = (root / "templates/tabs/scheduler.html").read_text()
    assert "api/scheduler/monitor?since=" in js
    assert ("this.mon.open && this.view === 'history'\n"
            "                   && this.$store.app.activeTab === 'scheduler'") in js
    assert "clearInterval(this._monTimer)" in js
    assert "this.$store.app.copyText(text)" in js            # http fallback (#327)
    hist = html.index("view === 'history'")
    assert hist < html.index('@click="monToggle()"') < html.index('x-if="logEvents"')
    assert ':title="monTrace(l)"' in html and 'x-text="monTrace(l)"' in html   # hover + tap
