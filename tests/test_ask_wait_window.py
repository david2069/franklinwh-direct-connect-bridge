"""The "Ask before continuing" wait (owner decision, 2026-11-04).

A new schedule waits 5 minutes for a reply (was 10); a save is refused when the wait is
longer than the schedule's window, because a reply after the window closes never runs the
action; and the question tells the phone how long it has to answer.
"""
import datetime as dt
from pathlib import Path

import pytest
from franklinwh_ha_notify import YES, Answer

from franklinwh_direct_connect_bridge import scheduler as sch
from tests.test_schedule_ask_step import (ASK, NOW, _schedule, _settle, _tick,  # noqa: F401
                                          notifier, st)

ROOT = Path(sch.__file__).parent


def _spec(ask_wait, **spec):
    base = {"trigger_type": "daily", "fire_at": "18:00", "duration_min": 60,
            "action": {"kind": "set_mode", "mode": "self"},
            "ask": {**ASK, "timeout_min": ask_wait}}
    return {**base, **spec}


def _window_errors(spec):
    return [e for e in sch.validate_spec(spec) if "window" in e and "ask" in e]


def test_a_new_schedule_waits_5_minutes():
    js = (ROOT / "static/js/scheduler_tab.js").read_text()
    assert "timeout_min: 5, if_no_reply: 'skip'" in js
    assert "timeout_min: 10" not in js


@pytest.mark.parametrize("spec,ok", [
    (_spec(60), True),                                      # wait = window
    (_spec(61), False),                                     # one minute too long
    (_spec(30, trigger_type="weekly", days=[0]), True),
    (_spec(90, trigger_type="once", start_date="2026-11-05"), False),
    (_spec(20, trigger_type="interval", interval_min=60, duration_min=15), False),
    (_spec(15, trigger_type="cron", cron="0 3 * * *", duration_min=15), True),
    # 'window': the shortest of its windows bounds the wait.
    (_spec(45, trigger_type="window", windows=[{"start": "18:00", "end": "18:30"},
                                               {"start": "20:00", "end": "22:00"}]), False),
    (_spec(30, trigger_type="window", windows=[{"start": "23:30", "end": "00:30"},
                                               {"start": "18:00", "end": "18:30"}]), True),
    # Duration 0 runs only in its start minute: a 1-minute wait is all that fits.
    (_spec(1, duration_min=0), True),
    (_spec(5, duration_min=0), False),
    (_spec(5, trigger_type="interval", interval_min=60, duration_min=0), False),
    # 'always' has no time window: any wait.
    (_spec(240, trigger_type="always", duration_min=0), True),
])
def test_the_wait_must_fit_the_window(spec, ok):
    assert (_window_errors(spec) == []) is ok, sch.validate_spec(spec)


def test_the_refusal_says_both_numbers():
    (err,) = _window_errors(_spec(90))
    assert "90 min" in err and "60 min" in err


def test_a_schedule_without_the_step_is_not_checked():
    assert _window_errors({**_spec(5, duration_min=0), "ask": {}}) == []


def test_a_saved_schedule_with_a_longer_wait_still_runs(st, notifier):
    _schedule(st, ask={**ASK, "timeout_min": 90})          # saved before this rule
    assert _tick(st) == []
    assert notifier.calls[0]["timeout_s"] == 90 * 60
    notifier.answer(Answer(YES))
    _settle()
    assert [f["id"] for f in _tick(st, NOW + dt.timedelta(minutes=1))] == ["s1"]


def test_the_question_tells_the_deadline(st, notifier, monkeypatch):
    monkeypatch.setattr(sch, "snapshot_from_state", lambda state: {"battery.soc_pct": 41})
    _schedule(st, ask={**ASK, "question": "SoC %battery.soc_pct%%. Charge?", "timeout_min": 7})
    _tick(st)
    assert notifier.calls[0]["question"] == "SoC 41%. Charge? (reply within 7 min)"


# ── the save route ────────────────────────────────────────────────────────────
@pytest.fixture
def c(monkeypatch):
    from fastapi.testclient import TestClient

    from franklinwh_direct_connect_bridge import app as app_module
    from franklinwh_direct_connect_bridge import state
    monkeypatch.setattr(app_module, "_guard_writes", lambda: None, raising=False)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "first")
    yield TestClient(app_module.create_app())
    state.reset_gateways()


BODY = {"name": "asked", "enabled": False, "fire_at": "10:00", "duration_min": 30,
        "gateway_id": "g1", "ask": {**ASK, "timeout_min": 30}}


def test_the_editor_shows_the_refusal(c):
    r = c.post("/api/schedules", json={**BODY, "ask": {**ASK, "timeout_min": 45}})
    assert r.status_code == 422
    assert "the wait (45 min) is longer than the schedule's window (30 min)" in r.text


def test_a_saved_schedule_with_a_longer_wait_can_still_be_toggled(c):
    from franklinwh_direct_connect_bridge import db
    from franklinwh_direct_connect_bridge.config import get_settings
    sid = c.post("/api/schedules", json=BODY).json()["id"]
    st = db.get_store(get_settings())
    row = st.schedule(sid)
    spec = {k: row[k] for k in ("fire_at", "duration_min", "gateway_id", "action", "ask")}
    st.update_schedule(sid, name="asked", enabled=False,              # saved before the rule
                       spec={**spec, "ask": {**ASK, "timeout_min": 90}})
    on = c.put(f"/api/schedules/{sid}", json={"name": "asked", "enabled": True})
    assert on.status_code == 200 and on.json()["ask"]["timeout_min"] == 90
    longer = c.put(f"/api/schedules/{sid}", json={"name": "asked",
                                                   "ask": {**ASK, "timeout_min": 120}})
    assert longer.status_code == 422 and "120 min" in longer.text
