"""Actionable Notifications: one notify path (#576, owner-approved 2026-11-12; "I asked for
Actionable Notifications and it was called this and inserted arbitrarily … not aligning
with existing Notifications").

A schedule notifies only through its Home Assistant notify rows. A notify row can be
**Actionable**: it carries the buttons, the wait and what no reply does, and the run waits
for the answer. The Notify battery action and the separate "Ask before continuing" block
are gone; saved schedules move over on save, on import and once at start-up."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from franklinwh_ha_notify import NO, Answer

from franklinwh_direct_connect_bridge import app as app_module, state
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

from test_schedule_ask_step import NOW, _log, _settle, _tick, notifier  # noqa: F401

PKG = Path(sch.__file__).parent
HTML = (PKG / "templates/tabs/scheduler.html").read_text()
JS = (PKG / "static/js/scheduler_tab.js").read_text()

ACTIONABLE = {"ha_kind": "notify", "when": "fire", "actionable": True, "title": "Battery",
              "message": "Charge now?", "timeout_min": 5, "if_no_reply": "skip",
              "send_to": {"type": "all"}}


# ── one shape ────────────────────────────────────────────────────────────────
def test_the_notify_action_becomes_an_on_entry_notify_row():
    spec = sch.normalize_spec({"action": {"kind": "notify", "device_id": "d1", "title": "T",
                                          "message": "M"}, "ha_actions": []})
    assert spec["action"] == {}
    assert spec["ha_actions"] == [{"ha_kind": "notify", "device_id": "d1", "title": "T",
                                   "message": "M", "when": "fire"}]


def test_ask_becomes_an_actionable_notify_row():
    spec = sch.normalize_spec({"action": {"kind": "set_mode", "mode": "tou"}, "ha_actions": [],
                               "ask": {"question": "Charge now?", "timeout_min": 5,
                                       "if_no_reply": "skip", "send_to": {"type": "all"}}})
    assert "ask" not in spec or not spec["ask"]
    row = spec["ha_actions"][0]
    assert row["actionable"] is True and row["message"] == "Charge now?" and row["when"] == "fire"
    assert row["timeout_min"] == 5 and row["if_no_reply"] == "skip"
    assert sch.normalize_spec(spec) == spec                     # once only


def test_the_engine_reads_the_actionable_row_as_its_ask():
    ask = sch.entry_ask({"ha_actions": [{"ha_kind": "notify", "device_id": "d1", "message": "x"},
                                        ACTIONABLE]})
    assert ask["question"] == "Charge now?" and ask["timeout_min"] == 5
    assert ask["send_to"] == {"type": "all"}
    assert sch.entry_ask({"ha_actions": []}) == {}


# ── validation ───────────────────────────────────────────────────────────────
def test_one_actionable_row_on_entry_only():
    two = sch.validate_spec({"fire_at": "10:00", "duration_min": 30, "action": {},
                             "ha_actions": [ACTIONABLE, ACTIONABLE]})
    assert any("one actionable notification" in e for e in two)
    on_exit = sch.validate_spec({"fire_at": "10:00", "duration_min": 30, "action": {},
                                 "ha_actions": [{**ACTIONABLE, "when": "exit"}]})
    assert any("actionable notification" in e and "on entry" in e for e in on_exit)
    no_q = sch.validate_spec({"fire_at": "10:00", "duration_min": 30, "action": {},
                              "ha_actions": [{**ACTIONABLE, "message": ""}]})
    assert any("actionable notification needs a message" in e for e in no_q)


def test_notify_is_no_longer_a_battery_action():
    assert "notify" not in sch.ACTIONS


# ── it runs ──────────────────────────────────────────────────────────────────
@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "t.db"))
    s.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123", token="t")
    s.create_notify_device(dev_id="d1", alias="Phone", instance_id="home",
                           service="notify.mobile_app_phone")
    return s


def test_an_actionable_row_asks_and_is_not_also_sent_as_a_plain_message(st, notifier, monkeypatch):
    sent = []
    monkeypatch.setattr(sch, "run_action", lambda a, **k: sent.append(a) or "notify: sent")
    st.create_schedule(sid="s1", name="Rule", spec={
        "gateway_id": "gw", "fire_at": "18:00", "duration_min": 60, "conditions": [],
        "action": {}, "ha_actions": [ACTIONABLE]})
    _tick(st)
    asked = notifier.asked()[0]
    assert [t.label for t in asked["targets"]] == ["Phone"]
    notifier.answer(Answer(NO))
    _settle()
    _tick(st)
    assert sent == []                                          # asked, never sent plain
    assert any(s == "asking" for s, _ in _log(st))


# ── saved schedules move over ────────────────────────────────────────────────
@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(app_module, "_guard_writes", lambda: None, raising=False)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "first")
    from franklinwh_direct_connect_bridge import config, db
    store = db.get_store(config.get_settings())
    store.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123", token="t")
    store.create_notify_device(dev_id="p1", alias="Phone", instance_id="home",
                               service="notify.mobile_app_phone")
    yield TestClient(app_module.create_app()), store
    state.reset_gateways()


def test_a_legacy_save_is_stored_in_the_one_shape(c):
    client, store = c
    r = client.post("/api/schedules", json={
        "name": "old", "enabled": False, "fire_at": "10:00", "duration_min": 30,
        "gateway_id": "g1", "action": {"kind": "notify", "device_id": "p1", "message": "hi"},
        "ask": {"question": "Go?", "timeout_min": 5, "if_no_reply": "skip"}})
    assert r.status_code == 201, r.text
    row = store.schedule(r.json()["id"])
    assert row["action"] == {} and not row.get("ask")
    kinds = [(h.get("actionable", False), h.get("message")) for h in row["ha_actions"]]
    assert (False, "hi") in kinds and (True, "Go?") in kinds


def test_saved_schedules_move_over_at_start_up(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    s.create_schedule(sid="s1", name="old", spec={
        "gateway_id": "g1", "fire_at": "10:00", "duration_min": 30,
        "action": {"kind": "notify", "device_id": "p1", "message": "hi"}, "ha_actions": [],
        "ask": {"question": "Go?", "timeout_min": 5, "if_no_reply": "skip"}})
    assert sch.migrate_notify_paths(s) == 1
    row = s.schedule("s1")
    assert row["action"] == {} and not row.get("ask") and len(row["ha_actions"]) == 2
    assert sch.migrate_notify_paths(s) == 0


def test_templates_are_served_in_the_one_shape(c):
    client, _ = c
    presets = client.get("/api/schedules/presets").json()["presets"]
    for p in presets:
        spec = p.get("spec") or {}
        assert not spec.get("ask"), p["id"]
        assert (spec.get("action") or {}).get("kind") != "notify", p["id"]
    ask_ones = [p for p in presets if any(h.get("actionable") for h in (p.get("spec") or {}).get("ha_actions", []))]
    assert ask_ones                                               # e.g. the off-grid asks


def test_import_moves_them_over_too():
    out = sch.normalize_spec({"name": "x", "action": {"kind": "notify", "device_id": "gone",
                                                      "message": "m"}, "ha_actions": []})
    v = sch.validate_import({**out, "fire_at": "10:00", "duration_min": 30},
                            gateway_ids=set(), device_ids=set())
    assert any("gone" in w for w in v["warnings"])


# ── the editor ───────────────────────────────────────────────────────────────
def test_the_editor_has_no_separate_ask_block_and_the_row_is_actionable():
    assert 'data-testid="ask-on"' not in HTML and "Ask before continuing" not in HTML
    row = HTML[HTML.index("<!-- notify fields -->"):]
    row = row[:row.index("<!-- service GUIDED")]
    assert 'data-testid="notify-actionable"' in row and "Actionable notification" in row
    for t in ("ask-timeout", "ask-no-reply", "ask-send-to", "ask-asked-names"):
        assert f'data-testid="{t}"' in row, t
    assert "askOf(" in JS and "Actionable" in JS


def test_an_actionable_row_has_no_guard_the_entry_conditions_decide():
    i = HTML.index("<!-- optional guard")
    assert 'x-show="!ha.actionable"' in HTML[i:i + 400]
    spec = sch.normalize_spec({"action": {}, "ha_actions": [], "ask": {"question": "q",
                                                                     "timeout_min": 5,
                                                                     "if_no_reply": "skip"}})
    assert "guard" not in spec["ha_actions"][0]
