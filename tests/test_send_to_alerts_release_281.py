"""#281: critical alerts (Acknowledge / Re-discover) and the Release / Keep question each
have a Send to setting, as the auto-notify triggers do: all enabled devices (the default)
or the devices chosen."""
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import notify_buttons, notify_engine

from test_notify_buttons import running, sent, store  # noqa: F401
from test_send_to_by_device_281 import c  # noqa: F401

PKG = Path(notify_engine.__file__).parent


@pytest.fixture
def more(store):  # noqa: F811
    store.create_notify_device(dev_id="p4", alias="Tablet", instance_id="home",
                               service="notify.mobile_app_tab", enabled=True)
    store.create_notify_device(dev_id="p5", alias="Speaker", instance_id="home",
                               service="notify.alexa_media_kitchen", enabled=True)
    return store


def _choose(st, key, ids):
    notify_engine.set_config(st, {"asks": {key: {"target": {"type": "device", "ids": ids}}}})


def test_both_default_to_all_devices_and_keep_a_choice(more):
    asks = notify_engine.config(more)["asks"]
    assert set(asks) == {"alert", "force_running"}
    assert all(a["target"] == {"type": "all"} for a in asks.values())
    assert asks["alert"]["label"] and asks["force_running"]["label"]
    _choose(more, "alert", ["p4"])
    assert notify_engine.config(more)["asks"]["alert"]["target"] == {"type": "device", "ids": ["p4"]}
    assert notify_engine.config(more)["asks"]["force_running"]["target"] == {"type": "all"}
    notify_engine.set_config(more, {"asks": {"alert": {"target": {"type": "all"}}}})
    assert notify_engine.config(more)["asks"]["alert"]["target"] == {"type": "all"}


def test_roles_are_refused(more):
    with pytest.raises(ValueError):
        notify_engine.set_config(more, {"asks": {"alert": {"target": {"type": "role",
                                                                      "role": "admin"}}}})


def test_release_goes_to_every_enabled_device_by_default(running, sent, more):  # noqa: F811
    assert notify_buttons.ask_release(more, "192.0.2.10", "t", "m")
    assert sorted(sent[-1]["targets"]) == ["alexa_media_kitchen", "mobile_app_phone",
                                           "mobile_app_tab"]


def test_release_goes_to_the_chosen_devices(running, sent, more):  # noqa: F811
    _choose(more, "force_running", ["p4", "p2"])          # p2 is switched off: stays off
    assert notify_buttons.ask_release(more, "192.0.2.10", "t", "m")
    assert sent[-1]["targets"] == ["mobile_app_tab"]


def test_alert_goes_to_the_chosen_devices(running, sent, more):  # noqa: F811
    _choose(more, "alert", ["p1"])
    row = {"id": 1, "code": "X", "title": "Alert", "message": "m", "gateway_id": ""}
    assert notify_buttons.ask_alert(more, row)
    assert sent[-1]["targets"] == ["mobile_app_phone"]


def test_no_chosen_device_shows_buttons_so_the_caller_falls_back(running, sent, more):  # noqa: F811
    _choose(more, "force_running", ["p5"])
    assert notify_buttons.ask_release(more, "192.0.2.10", "t", "m") is False
    assert sent == []


def test_the_api_saves_and_refuses_roles(c):  # noqa: F811
    t = {"type": "device", "ids": ["p1"]}
    r = c.put("/api/notify/triggers", json={"asks": {"force_running": {"target": t}}})
    assert r.status_code == 200 and r.json()["config"]["asks"]["force_running"]["target"] == t
    assert c.get("/api/notify/triggers").json()["config"]["asks"]["force_running"]["target"] == t
    r = c.put("/api/notify/triggers",
              json={"asks": {"alert": {"target": {"type": "role", "role": "admin"}}}})
    assert r.status_code == 422


def test_the_rows_sit_with_the_triggers_and_use_the_same_picker():
    html = (PKG / "templates/tabs/settings.html").read_text()
    trig = html.index('data-testid="trigger-target"')
    box = html[html.index('data-testid="ask-targets"'):]
    box = box[:box.index("<!-- ── Recent notifications")]
    assert html.index('data-testid="ask-targets"') > trig
    assert 'data-testid="ask-target"' in box and '<option value="device"' in box
    assert "flex-wrap" in box and "toggleAskDevice(key, a, d.id" in box
    js = (PKG / "static/js/settings_tab.js").read_text()
    assert "asks: { [key]: { target:" in js
