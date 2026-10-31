"""#374 P2: every companion push goes through one path (notify_push, on franklinwh-ha-notify).

It checks the Push notifications switch (#171), logs every delivery whichever feature
sent it, and stubs only the network edge (the package's ``send``).
"""
import pytest
from franklinwh_ha_notify.send import Delivery, SendResult

from franklinwh_direct_connect_bridge import config, notify_engine, notify_push, scheduler, vpp_monitor
from franklinwh_direct_connect_bridge.db import MetricsStore


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    s.create_ha_instance(ha_id="ha1", name="Home", base_url="http://ha", token="t")
    s.create_notify_device(dev_id="d1", alias="Phone", instance_id="ha1",
                           service="notify.mobile_app_phone")
    return s


@pytest.fixture
def sent(monkeypatch):
    seen = []

    async def fake_send(instances, targets, title, message, *a, **k):
        seen.extend((instances[t.instance_id], t, title) for t in targets)
        return SendResult([Delivery(t.key, True) for t in targets])
    monkeypatch.setattr(notify_push, "send", fake_send)
    return seen


def _switch(monkeypatch, on):
    monkeypatch.setattr(config.get_settings(), "ha_notify", on)


def _scheduler_notify(st):
    return scheduler.run_action({"kind": "notify", "device_id": "d1", "title": "T",
                                 "message": "M"}, settings=config.get_settings(), client=None,
                                store=st, snapshot={})


def test_the_switch_off_stops_every_automatic_push(st, sent, monkeypatch):
    _switch(monkeypatch, False)
    assert notify_engine.fire(st, "off_grid", "T", "M") == 0
    assert vpp_monitor._notify_devices(st, "T", "M") == 0
    assert "push notifications are off" in _scheduler_notify(st)
    assert sent == []
    assert all(e["device"] == "(push notifications are off)" for e in st.notify_log())


def test_a_test_the_user_presses_still_sends_with_the_switch_off(st, sent, monkeypatch):
    _switch(monkeypatch, False)
    assert notify_engine.fire(st, "test", "T", "M") == 1
    assert len(sent) == 1


def test_every_path_is_logged_per_device(st, sent, monkeypatch):
    _switch(monkeypatch, True)
    notify_engine.fire(st, "off_grid", "T", "M")
    vpp_monitor._notify_devices(st, "T", "M")
    assert "sent" in _scheduler_notify(st)
    events = sorted(e["event"] for e in st.notify_log())
    assert events == ["dispatch", "off_grid", "schedule"]
    assert all(e["device"] == "Phone" and e["ok"] == 1 for e in st.notify_log())


def test_the_notify_prefix_is_dropped_for_ha(st, sent, monkeypatch):
    _switch(monkeypatch, True)
    notify_engine.fire(st, "off_grid", "T", "M")
    ha, target, _ = sent[0]
    assert target.service == "mobile_app_phone" and ha.base_url == "http://ha"


def test_the_supervisor_instance_reads_its_token_live(st, sent, monkeypatch):
    _switch(monkeypatch, True)
    st.create_ha_instance(ha_id="sup", name="This HA", base_url="http://supervisor/core",
                          token="stale")
    st.create_notify_device(dev_id="d2", alias="Tablet", instance_id="sup",
                            service="mobile_app_tablet")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "fresh")
    notify_engine.fire(st, "off_grid", "T", "M")
    sup = next(ha for ha, t, _ in sent if t.instance_id == "sup")
    assert sup.bearer() == "fresh"


def test_no_token_is_an_answer_not_a_send(st, sent, monkeypatch):
    _switch(monkeypatch, True)
    st.update_ha_instance("ha1", token="")
    r = notify_push.push(st, config.get_settings(), "test", "T", "M", ignore_switch=True)
    assert sent == [] and r["results"][0]["error"] == "no token configured for this instance"
