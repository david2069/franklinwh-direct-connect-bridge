"""Ask before continuing, aligned with the schedule's notify rows (owner, 2026-11-12: "ask
before continuing is conflicting with the existing design for HA notifications… it also
lacks which device it notifies"; "align and fix, but you cannot have conflicts in the
notify option").

- It says which devices are asked: in the editor (All resolves to names), the list,
  Explain and the schedule log.
- Only devices that can show the buttons are asked (Companion apps).
- A chosen device that is switched off or removed later stays visible so it can be
  unticked, and never stops the schedule from being saved.
- No conflict with the notify rows: On entry messages go once per run (not on every retry
  of a failed action), and a run Ask skipped sends no On exit message either.
- Import warns about Ask devices it doesn't know, as it does for notify rows.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from franklinwh_ha_notify import NO, Answer

from franklinwh_direct_connect_bridge import app as app_module, resilience, state
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

from test_schedule_ask_step import ASK, NOW, _log, _settle, _tick, notifier  # noqa: F401

PKG = Path(sch.__file__).parent
HTML = (PKG / "templates/tabs/scheduler.html").read_text()
JS = (PKG / "static/js/scheduler_tab.js").read_text()


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "t.db"))
    s.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123", token="t")
    s.create_notify_device(dev_id="d1", alias="Phone", instance_id="home",
                           service="notify.mobile_app_phone")
    s.create_notify_device(dev_id="d2", alias="Tablet", instance_id="home",
                           service="notify.mobile_app_tab")
    s.create_notify_device(dev_id="d3", alias="Kitchen speaker", instance_id="home",
                           service="notify.alexa_media_kitchen")
    return s


def _schedule(st, sid="s1", ask=ASK, **spec):
    st.create_schedule(sid=sid, name=f"Rule {sid}", spec={
        "gateway_id": "gw", "fire_at": "18:00", "duration_min": 60, "conditions": [],
        "action": {}, "ha_actions": [], "ask": ask, **spec})


# ── who is asked ──────────────────────────────────────────────────────────────
def test_only_devices_that_can_show_the_buttons_are_asked(st, notifier):
    _schedule(st)
    _tick(st)
    assert [t.label for t in notifier.asked()[0]["targets"]] == ["Phone", "Tablet"]
    notifier.answer(Answer(NO))
    _settle()


def test_the_log_names_the_devices_asked(st, notifier):
    _schedule(st)
    _tick(st)
    notifier.asked()
    asking = [r for s, r in _log(st) if s == "asking"]
    assert asking and "on Phone, Tablet" in asking[0]
    notifier.answer(Answer(NO))
    _settle()


# ── no conflict with the notify rows ─────────────────────────────────────────
def test_on_entry_messages_go_once_per_run_not_on_every_retry(st, monkeypatch):
    sent = []
    monkeypatch.setattr(sch, "run_action", lambda a, **k: sent.append(a["kind"]) or "notify 'Phone': sent")
    monkeypatch.setattr(sch, "run_action_outcome", lambda *a, **k: resilience.Outcome(
        resilience.Verdict.FAILED, "set_mode", detail="mode -> tou: failed: offline"))
    entry = {"id": "s1", "name": "Rule", "action": {"kind": "set_mode", "mode": "tou"},
             "ha_actions": [{"device_id": "d1", "when": "fire", "message": "started"}],
             "_wkey": "2026-11-03", "duration_min": 60}
    for n in (1, 2, 3):                                 # the action fails; each tick retries
        sch._fire_entry(dict(entry, _occ_attempts=n), settings=None, client=None, store=st,
                        snapshot={}, host=None, gateway_id="gw", now=NOW)
    assert sent == ["notify"]
    sch._fire_entry(dict(entry, _wkey="2026-11-04", _occ_attempts=1), settings=None, client=None,
                    store=st, snapshot={}, host=None, gateway_id="gw", now=NOW)
    assert sent == ["notify", "notify"]                 # the next run gets its own


def test_a_run_ask_skipped_sends_no_on_exit_message(st, notifier, monkeypatch):
    sent = []
    monkeypatch.setattr(sch, "run_action", lambda a, **k: sent.append(a.get("when")) or "notify 'Phone': sent")
    _schedule(st, ha_actions=[{"device_id": "d1", "when": "exit", "message": "ended"}])
    _tick(st)
    notifier.answer(Answer(NO))
    _settle()
    _tick(st)
    import datetime as dt
    _tick(st, now=NOW + dt.timedelta(hours=2))          # the window has closed
    assert sent == []
    assert any("not sent" in r and "skipped" in r for _, r in _log(st))


# ── chosen devices that change later ─────────────────────────────────────────
@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(app_module, "_guard_writes", lambda: None, raising=False)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "first")
    from franklinwh_direct_connect_bridge import config, db
    st = db.get_store(config.get_settings())
    st.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123", token="t")
    st.create_notify_device(dev_id="p1", alias="Phone", instance_id="home",
                            service="notify.mobile_app_phone")
    yield TestClient(app_module.create_app()), st
    state.reset_gateways()


def test_a_removed_device_never_blocks_a_save(c):
    client, st = c
    body = {"name": "asked", "enabled": False, "fire_at": "10:00", "duration_min": 30,
            "gateway_id": "g1"}
    ask = {**ASK, "send_to": {"type": "device", "ids": ["p1"]}}
    sid = client.post("/api/schedules", json={**body, "ask": ask}).json()["id"]
    st.delete_notify_device("p1")
    r = client.put(f"/api/schedules/{sid}", json={**body, "enabled": True, "ask": ask})
    assert r.status_code == 200, r.text
    # a device that was never chosen and doesn't exist is still refused
    r = client.put(f"/api/schedules/{sid}", json={**body, "ask": {
        **ASK, "send_to": {"type": "device", "ids": ["p1", "nope"]}}})
    assert r.status_code == 422 and "unknown device 'nope'" in r.json()["detail"]


def test_import_warns_about_ask_devices_it_does_not_know():
    out = sch.validate_import({"name": "x", "fire_at": "10:00", "duration_min": 30,
                               "ask": {**ASK, "send_to": {"type": "device", "ids": ["gone"]}}},
                              gateway_ids=set(), device_ids={"d1"})
    assert any("gone" in w and "ask" in w.lower() for w in out["warnings"])


# ── the editor, the list and Explain say who ─────────────────────────────────
def test_the_editor_lists_off_and_removed_devices_so_they_can_be_unticked():
    block = HTML[HTML.index('data-testid="ask-send-to"'):]
    block = block[:block.index("</template>", block.index("askDeviceChoices"))]
    assert "askDeviceChoices" in block and "(off)" in JS and "(removed)" in JS


def test_all_enabled_devices_names_them():
    assert "askedNames(form.ask)" in HTML
    assert 'data-testid="ask-asked-names"' in HTML


def test_the_editor_shows_what_else_this_schedule_sends():
    assert 'data-testid="ask-also-notified"' in HTML and "alsoNotified(form)" in HTML


def test_the_list_and_explain_name_the_asked_devices():
    row = HTML[HTML.index("No gateway action"):][:600]
    assert "askedNames(s.ask)" in row
    explain = JS[JS.index("explain(s, level)"):][:3000]
    assert "askedNames(s.ask)" in explain
