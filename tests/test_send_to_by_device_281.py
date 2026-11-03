"""#281 N3 by device: a schedule's Ask step and each auto-notify trigger go to all enabled
devices (the default) or to the devices chosen."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from franklinwh_ha_notify import YES, Answer

from franklinwh_direct_connect_bridge import app as app_module, notify_engine, state
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

from test_schedule_ask_step import ASK, _schedule, _settle, _tick, notifier  # noqa: F401

PKG = Path(sch.__file__).parent


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "t.db"))
    s.create_notify_device(dev_id="d1", alias="Phone", instance_id="home",
                           service="notify.mobile_app_phone")
    s.create_notify_device(dev_id="d2", alias="Tablet", instance_id="home",
                           service="notify.mobile_app_tab")
    s.create_notify_device(dev_id="d3", alias="Old", instance_id="home",
                           service="notify.mobile_app_old", enabled=False)
    return s


# ── the Ask step ──────────────────────────────────────────────────────────────
def test_send_to_is_validated():
    assert sch._ask_errors(ASK) == []                                   # old schedules
    assert sch._ask_errors({**ASK, "send_to": {"type": "all"}}) == []
    assert sch._ask_errors({**ASK, "send_to": {"type": "device", "ids": ["d1"]}}) == []
    for bad in ({"type": "role", "role": "admin"}, {"type": "device", "ids": []},
                {"type": "device"}, "all"):
        assert any("send to" in e for e in sch._ask_errors({**ASK, "send_to": bad})), bad


def test_targets_follow_send_to(st):
    def names(send_to=None):
        return [t.label for t in sch._ask_targets(st, send_to)]
    assert names() == ["Phone", "Tablet"]
    assert names({"type": "all"}) == ["Phone", "Tablet"]
    assert names({"type": "device", "ids": ["d2"]}) == ["Tablet"]
    # a chosen device that is switched off stays off
    assert names({"type": "device", "ids": ["d2", "d3"]}) == ["Tablet"]


def test_the_question_goes_to_the_chosen_devices(st, notifier):  # noqa: F811
    _schedule(st, ask={**ASK, "send_to": {"type": "device", "ids": ["d2"]}})
    _tick(st)
    assert [t.label for t in notifier.calls[0]["targets"]] == ["Tablet"]
    notifier.answer(Answer(YES))
    _settle()


def test_without_send_to_the_question_goes_to_every_enabled_device(st, notifier):  # noqa: F811
    _schedule(st)
    _tick(st)
    assert [t.label for t in notifier.calls[0]["targets"]] == ["Phone", "Tablet"]
    notifier.answer(Answer(YES))
    _settle()


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(app_module, "_guard_writes", lambda: None, raising=False)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "first")
    from franklinwh_direct_connect_bridge import config, db
    db.get_store(config.get_settings()).create_notify_device(
        dev_id="p1", alias="Phone", instance_id="home", service="notify.mobile_app_phone")
    yield TestClient(app_module.create_app())
    state.reset_gateways()


def test_the_api_saves_send_to_and_refuses_unknown_devices_and_roles(c):
    dev = "p1"
    body = {"name": "asked", "enabled": False, "fire_at": "10:00", "gateway_id": "g1"}
    ok = {**ASK, "send_to": {"type": "device", "ids": [dev]}}
    r = c.post("/api/schedules", json={**body, "ask": ok})
    assert r.status_code == 201 and r.json()["ask"] == ok
    r = c.post("/api/schedules", json={**body, "ask": {**ASK, "send_to": {
        "type": "device", "ids": ["nope"]}}})
    assert r.status_code == 422 and "unknown device 'nope'" in r.json()["detail"]
    r = c.post("/api/schedules", json={**body, "ask": {**ASK, "send_to": {
        "type": "role", "role": "admin"}}})
    assert r.status_code == 422


def test_the_ask_box_has_a_send_to_picker():
    html = (PKG / "templates/tabs/scheduler.html").read_text()
    box = html[html.index('data-testid="ask-send-to"'):]
    box = box[:box.index("<!-- entry conditions")]
    assert 'x-model="form.ask.send_to.to"' in box and 'x-model="form.ask.send_to.ids"' in box
    assert "devices.filter(x => x.enabled)" in box          # the enabled devices
    assert "mobile_app_" in box and "flex-wrap" in box
    js = (PKG / "static/js/scheduler_tab.js").read_text()
    assert "out.send_to = { type: 'device'" in js


# ── the auto-notify triggers ───────────────────────────────────────────────────
def test_a_trigger_can_go_to_several_chosen_devices():
    html = (PKG / "templates/tabs/settings.html").read_text()
    assert 'data-testid="trigger-target-devices"' in html
    assert '<option value="device"' in html
    js = (PKG / "static/js/settings_tab.js").read_text()
    assert "toggleTriggerDevice(key, t, id, on)" in js


def test_several_chosen_devices_are_kept_and_sent_to(tmp_path, fake_notifier):
    s = MetricsStore(str(tmp_path / "n.db"))
    s.create_ha_instance(ha_id="ha1", name="Home", base_url="http://ha.test", token="t")
    for i, svc in (("d1", "mobile_app_a"), ("d2", "mobile_app_b"), ("d3", "mobile_app_c")):
        s.create_notify_device(dev_id=i, alias=i, instance_id="ha1", service=f"notify.{svc}")
    sends = fake_notifier(s)
    target = {"type": "device", "ids": ["d1", "d3"]}
    notify_engine.set_config(s, {"triggers": {"off_grid": {"target": target}}})
    assert notify_engine.config(s)["triggers"]["off_grid"]["target"] == target
    assert notify_engine.fire(s, "off_grid", gateway="Shed") == 2
    assert sorted(sends[-1]["targets"]) == ["ha1::mobile_app_a", "ha1::mobile_app_c"]
