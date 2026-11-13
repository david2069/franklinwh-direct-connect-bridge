"""Scheduler notifications (#581): Failed, Missed, Aborted and No reply each have their own
switch and Send to under Notifications → Triggers (a Scheduler group), name the gateway,
and write an app-log warning in the push's words. A missed run is a warning alert of its
own; a failed run stays the critical SCHEDULE_FAILED (owner, 2026-11-12)."""
import datetime as dt
import logging
import pathlib

import pytest
from franklinwh_ha_notify import Answer

from franklinwh_direct_connect_bridge import (alerts, config, db, notify_engine, scheduler as sch,
                                              scheduler_worker, state)
from tests.test_schedule_ask_step import (ASK, _schedule, _settle, _tick,  # noqa: F401
                                          notifier, st)

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


@pytest.fixture(autouse=True)
def _fresh():
    alerts.reset()
    state.reset_gateways()
    state.register_gateway("gw", "192.0.2.10", "Garage")
    state.register_gateway("gw1", "192.0.2.11", "House")
    yield
    alerts.reset()
    state.reset_gateways()


@pytest.fixture
def pushes(monkeypatch):
    sent = []

    def fake_send(store, event, gateway=None, device_ids=None, **values):
        sent.append({"event": event, "gateway": gateway, "ids": device_ids, **values})
    monkeypatch.setattr(notify_engine.actionable, "send", fake_send)
    return sent


def test_the_scheduler_group_and_its_defaults():
    t = notify_engine.config(None)["triggers"]
    got = {k: (v["enabled"], v.get("group")) for k, v in t.items() if k.startswith("schedule_")}
    assert got == {"schedule_failed": (True, "Scheduler"), "schedule_missed": (True, "Scheduler"),
                   "schedule_aborted": (False, "Scheduler"),
                   "schedule_no_reply": (True, "Scheduler")}


def test_a_missed_run_is_a_warning_of_its_own_and_is_pushed(monkeypatch, pushes, caplog):
    s = config.get_settings()
    store = db.get_store(s)
    monkeypatch.setattr(store, "sweep_missed", lambda **k: [
        {"schedule_id": "s1", "name": "nightly", "gateway_id": "gw1", "attempts": 3}])
    with caplog.at_level(logging.WARNING):
        scheduler_worker.sweep(s)
    rows = store.alerts()
    assert [(r["code"], r["severity"]) for r in rows] == [("SCHEDULE_MISSED", "warning")]
    assert "House" in rows[0]["message"] and "missed" in rows[0]["message"]
    assert [p["event"] for p in pushes] == ["schedule_missed"]
    assert pushes[0]["gateway"] == "House" and pushes[0]["schedule"] == "nightly"
    assert any("missed its window" in r.getMessage() and "House" in r.getMessage()
               for r in caplog.records)


def test_a_failed_run_stays_critical_and_names_the_gateway(monkeypatch):
    store = db.get_store(config.get_settings())
    monkeypatch.setattr(sch, "run_action", lambda *a, **k: "force charge: failed — refused")
    monkeypatch.setattr(sch, "_fire_ha_phase", lambda *a, **k: [])
    entry = {"id": "s1", "name": "nightly", "action": {"kind": "set_mode"},
             "_wkey": "2026-10-09", "_wend": None, "_occ_id": None,
             "_occ_attempts": 1, "duration_min": 60}
    sch._fire_entry(entry, settings=None, client=None, store=store, snapshot={},
                    host="h", gateway_id="gw1", now=dt.datetime(2026, 10, 9, 18, 0))
    row = store.alerts()[0]
    assert (row["code"], row["severity"]) == ("SCHEDULE_FAILED", "critical")
    assert "House" in row["message"]


def test_the_failed_switch_and_send_to_steer_the_alerts_push(monkeypatch):
    from franklinwh_direct_connect_bridge import notify_buttons
    store = db.get_store(config.get_settings())
    asked = []
    monkeypatch.setattr(notify_buttons, "_ask_from_thread",
                        lambda store, event, buttons, ttl, *, ids=None, **k: asked.append(ids) or True)
    row = {"id": 1, "code": "SCHEDULE_FAILED", "gateway_id": "gw1", "title": "t", "message": "m"}
    store.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123", token="t")
    store.create_notify_device(dev_id="d1", alias="Phone", instance_id="home",
                               service="notify.mobile_app_phone")
    notify_engine.set_config(store, {"triggers": {"schedule_failed": {
        "target": {"type": "device", "ids": ["d1"]}}}})
    alerts._ask_phones(store, row)
    assert asked == [["d1"]]
    notify_engine.set_config(store, {"triggers": {"schedule_failed": {"enabled": False}}})
    alerts._ask_phones(store, row)
    assert asked == [["d1"]], "switched off: no push (the alert and HA notification stay)"
    alerts._ask_phones(store, {**row, "code": "COMMAND_REFUSED"})
    assert len(asked) == 2, "other alerts keep Critical alerts' Send to"


def test_no_reply_is_pushed_to_the_devices_asked_and_logged(st, notifier, pushes, caplog):
    _schedule(st, ask={**ASK, "send_to": {"type": "device", "ids": ["d9"]}})
    _tick(st)
    notifier.answer(Answer(None, timed_out=True))
    _settle()
    with caplog.at_level(logging.WARNING):
        _tick(st)
    np = [p for p in pushes if p["event"] == "schedule_no_reply"]
    assert len(np) == 1 and np[0]["gateway"] == "Garage" and np[0]["schedule"] == "Rule s1"
    assert np[0]["ids"] == ["d9"]
    assert "no reply in 5 min" in np[0]["detail"]
    assert any("Rule s1" in r.getMessage() and "no reply" in r.getMessage()
               for r in caplog.records if r.levelno == logging.WARNING)


def test_an_answered_question_sends_no_no_reply(st, notifier, pushes):
    from franklinwh_ha_notify import YES
    _schedule(st)
    _tick(st)
    notifier.answer(Answer(YES))
    _settle()
    _tick(st)
    assert not [p for p in pushes if p["event"] == "schedule_no_reply"]


def test_aborted_is_off_by_default_but_logged(st, pushes, caplog, monkeypatch):
    with caplog.at_level(logging.WARNING):
        sch.notify_run(st, "schedule_aborted", "Rule s1", "gw", "deferred — outranked")
    assert pushes == []
    assert any("Rule s1" in r.getMessage() and "outranked" in r.getMessage()
               for r in caplog.records)
    notify_engine.set_config(st, {"triggers": {"schedule_aborted": {"enabled": True}}})
    sch.notify_run(st, "schedule_aborted", "Rule s1", "gw", "deferred — outranked")
    assert [(p["event"], p["gateway"]) for p in pushes] == [("schedule_aborted", "Garage")]


def test_a_deferred_run_is_an_aborted_one(st, monkeypatch):
    called = []
    monkeypatch.setattr(sch, "notify_run", lambda store, event, name, gw, detail, **k:
                        called.append((event, name, gw)))
    monkeypatch.setattr(sch, "ha_snapshot", lambda store: {})
    for sid, pri in (("a", 5), ("b", 1)):
        st.create_schedule(sid=sid, name=f"Rule {sid}", spec={
            "gateway_id": "gw", "fire_at": "18:00", "duration_min": 60, "conditions": [],
            "priority": pri, "action": {"kind": "set_mode", "mode": "self"}, "ha_actions": []})
    monkeypatch.setattr(sch, "run_action", lambda *a, **k: "mode -> self: ok")
    for d in (sch._window_inside, sch._window_key, sch._gated_day, sch._dwell_since):
        d.clear()
    sch.tick(settings=None, client=None, store=st, state={}, gateway_id="gw",
             now=dt.datetime(2026, 11, 3, 18, 10))
    assert ("schedule_aborted", "Rule b", "gw") in called


def test_triggers_ui_shows_the_scheduler_group():
    html = (PKG / "templates" / "tabs" / "settings.html").read_text()
    js = (PKG / "static" / "js" / "settings_tab.js").read_text()
    assert 'data-testid="trigger-group"' in html and "triggerGroupStart(key)" in html
    assert "triggerGroupStart(key)" in js


def test_alert_help_tells_missed_from_failed():
    js = (PKG / "static" / "js" / "alerts.js").read_text()
    assert "SCHEDULE_MISSED:" in js
