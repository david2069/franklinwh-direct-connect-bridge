"""#763 (owner 2026-11-19): optional notifications when the operating mode changes, when
the aGate is on 4G, and every N minutes while off-grid (saying whether it was user
requested); a button on them to turn further ones off; and who gets them by role."""
import asyncio
import pathlib
from types import SimpleNamespace

import pytest

from franklinwh_direct_connect_bridge import actionable, auth, notify_buttons, notify_engine as ne
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(ne.__file__).parent
HTML = (PKG / "templates" / "tabs" / "settings.html").read_text()
JS = (PKG / "static" / "js" / "settings_tab.js").read_text()


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "t.db"))
    auth.ensure_tables(s)
    s.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123", token="t")
    for i, alias in (("d1", "Owner phone"), ("d2", "Partner phone"), ("d3", "Kid tablet")):
        s.create_notify_device(dev_id=i, alias=alias, instance_id="home",
                               service="notify.mobile_app_" + i)
    return s


@pytest.fixture
def sent(monkeypatch):
    """Every fire() delivery: (event, device_ids, values); buttons recorded separately."""
    out = {"plain": [], "asks": []}
    monkeypatch.setattr(actionable, "send", lambda store, event, gateway=None, device_ids=None, **v:
                        out["plain"].append((event, device_ids, v)) or SimpleNamespace(delivered=1))
    monkeypatch.setattr(notify_buttons, "ask_trigger",
                        lambda store, event, trigger, device_ids, gateway=None, gateway_id=None, **v:
                        out["asks"].append((event, trigger, device_ids, gateway_id, v)) or True)
    return out


def _on(st, *keys, **extra):
    ne.set_config(st, {"triggers": {k: {"enabled": True, **extra.get(k, {})} for k in keys}})
    return ne.config(st)


# ── the triggers ────────────────────────────────────────────────────────────────
def test_three_new_triggers_off_by_default():
    for k in ("mode_change", "agate_on_4g", "off_grid_reminder"):
        assert ne.DEFAULT_TRIGGERS[k]["enabled"] is False, k
    assert ne.DEFAULT_TRIGGERS["off_grid_reminder"]["interval_min"] == 15
    assert ne.TRIGGER["agate_on_wifi"] == "agate_on_4g"
    # the existing ones are unchanged
    assert ne.DEFAULT_TRIGGERS["off_grid"]["enabled"] is True


def test_reminder_interval_is_saved_and_kept_at_least_5_min(st):
    ne.set_config(st, {"triggers": {"off_grid_reminder": {"interval_min": 30}}})
    assert ne.config(st)["triggers"]["off_grid_reminder"]["interval_min"] == 30
    ne.set_config(st, {"triggers": {"off_grid_reminder": {"interval_min": 1}}})
    assert ne.config(st)["triggers"]["off_grid_reminder"]["interval_min"] == 5


def test_mode_change_from_the_summary(st):
    cfg = _on(st, "mode_change")
    prev = {"ok": True, "power": {"mode": "Self-Consumption"}}
    cur = {"ok": True, "power": {"mode": "Time-of-Use"}}
    assert ("mode_change", {"from": "Self-Consumption", "to": "Time-of-Use"}) in ne.evaluate(cur, prev, cfg)
    # not when it's off, unchanged, or a side unknown
    assert not [e for e in ne.evaluate(cur, prev, ne.config(None)) if e[0] == "mode_change"]
    assert not [e for e in ne.evaluate(cur, cur, cfg) if e[0] == "mode_change"]
    unknown = {"ok": False, "power": {}}
    assert not [e for e in ne.evaluate(cur, unknown, cfg) if e[0] == "mode_change"]
    assert not [e for e in ne.evaluate(unknown, cur, cfg) if e[0] == "mode_change"]


def test_the_messages():
    t = actionable.templates()
    _, m = t.render("mode_change", gateway="aGate", **{"from": "Self-Consumption", "to": "Time-of-Use"})
    assert m == "Operating mode changed [aGate]: Self-Consumption → Time-of-Use."
    _, m = t.render("agate_on_4g", gateway="aGate")
    assert "4G" in m and "[aGate]" in m
    _, m = t.render("off_grid_reminder", gateway="aGate", reason="user requested",
                    duration="15 min", metrics="SoC 80%")
    assert m == "Still OFF-GRID [aGate] (user requested) for 15 min — SoC 80%."


# ── aGate on 4G: from the existing alert, opened / resolved ─────────────────────
def test_4g_follows_the_alert(st, sent):
    _on(st, "agate_on_4g")
    ne.on_alert_changes(st, [{"id": 1, "code": "AGATE_ON_4G", "gateway_id": "g1", "change": "opened"},
                             {"id": 2, "code": "MQTT_DOWN", "gateway_id": "", "change": "opened"}])
    ne.on_alert_changes(st, [{"id": 1, "code": "AGATE_ON_4G", "gateway_id": "g1", "change": "resolved"}])
    assert [a[0] for a in sent["asks"]] == ["agate_on_4g", "agate_on_wifi"]
    assert all(a[3] == "g1" for a in sent["asks"])


def test_4g_off_by_default_sends_nothing(st, sent):
    ne.on_alert_changes(st, [{"id": 1, "code": "AGATE_ON_4G", "gateway_id": "g1", "change": "opened"}])
    assert sent["asks"] == [] and sent["plain"] == []


# ── off-grid reminders ──────────────────────────────────────────────────────────
OFF = {"ok": True, "power": {"off_grid": True, "off_grid_kind": "simulated", "soc": 80,
                             "battery_w": 1000, "load_w": 1000, "solar_w": 0}}
ON = {"ok": True, "power": {"off_grid": False, "soc": 80}}


def test_reminder_every_interval_while_off_grid(st, sent):
    cfg = _on(st, "off_grid_reminder")
    t0 = 1_000_000.0
    assert ne.offgrid_reminder(st, "g1", "aGate", OFF, cfg, None, t0) is False   # the off_grid event covers t0
    assert ne.offgrid_reminder(st, "g1", "aGate", OFF, cfg, None, t0 + 14 * 60) is False
    assert ne.offgrid_reminder(st, "g1", "aGate", OFF, cfg, None, t0 + 15 * 60) is True
    ev, trig, ids, gid, vals = sent["asks"][-1]
    assert ev == "off_grid_reminder" and gid == "g1"
    assert vals["reason"] == "user requested" and vals["duration"] == "15 min"
    assert ne.offgrid_reminder(st, "g1", "aGate", OFF, cfg, None, t0 + 20 * 60) is False
    assert ne.offgrid_reminder(st, "g1", "aGate", OFF, cfg, None, t0 + 30 * 60) is True
    # back on-grid: the count starts again next time
    ne.offgrid_reminder(st, "g1", "aGate", ON, cfg, None, t0 + 31 * 60)
    assert ne.offgrid_reminder(st, "g1", "aGate", OFF, cfg, None, t0 + 40 * 60) is False


def test_outage_says_grid_outage_and_unknown_reading_keeps_counting(st, sent):
    cfg = _on(st, "off_grid_reminder")
    out = {"ok": True, "power": {**OFF["power"], "off_grid_kind": "outage"}}
    t0 = 2_000_000.0
    ne.offgrid_reminder(st, "g2", "aGate", out, cfg, None, t0)
    ne.offgrid_reminder(st, "g2", "aGate", {"ok": False}, cfg, None, t0 + 5 * 60)   # no reading
    assert ne.offgrid_reminder(st, "g2", "aGate", out, cfg, None, t0 + 15 * 60) is True
    assert sent["asks"][-1][4]["reason"] == "grid outage"


def test_stop_reminders_until_this_off_grid_ends(st, sent):
    cfg = _on(st, "off_grid_reminder")
    t0 = 3_000_000.0
    ne.offgrid_reminder(st, "g3", "aGate", OFF, cfg, None, t0)
    ne.mute_reminders(st, "g3")
    assert ne.offgrid_reminder(st, "g3", "aGate", OFF, cfg, None, t0 + 15 * 60) is False
    ne.offgrid_reminder(st, "g3", "aGate", ON, cfg, None, t0 + 16 * 60)            # ends: unmuted
    assert not ne.reminders_muted(st, "g3")
    ne.offgrid_reminder(st, "g3", "aGate", OFF, cfg, None, t0 + 20 * 60)
    assert ne.offgrid_reminder(st, "g3", "aGate", OFF, cfg, None, t0 + 35 * 60) is True


# ── the buttons ─────────────────────────────────────────────────────────────────
def test_events_with_buttons_and_fallback_to_plain(st, sent, monkeypatch):
    _on(st, "mode_change")
    ne.fire(st, "mode_change", gateway="aGate", gateway_id="g1", **{"from": "A", "to": "B"})
    assert sent["asks"][-1][:2] == ("mode_change", "mode_change") and not sent["plain"]
    # the ask reached nobody: the plain one goes
    monkeypatch.setattr(notify_buttons, "ask_trigger", lambda *a, **k: False)
    ne.fire(st, "mode_change", gateway="aGate", gateway_id="g1", **{"from": "A", "to": "B"})
    assert sent["plain"][-1][0] == "mode_change"
    assert notify_buttons.TRIGGER_BUTTONS == {
        "mode_change": "Turn off", "agate_on_4g": "Turn off", "agate_on_wifi": "Turn off",
        "off_grid_reminder": "Stop reminders"}


def test_turn_off_tap_disables_the_trigger_and_says_so(st, monkeypatch):
    _on(st, "agate_on_4g")
    monkeypatch.setattr(notify_buttons, "_store", lambda: st)
    req = SimpleNamespace(meta={"trigger": "agate_on_4g", "gateway_id": "g1"})
    said = asyncio.run(notify_buttons._on_turn_off(req, SimpleNamespace(verb=notify_buttons.TURN_OFF)))
    t = ne.config(st)["triggers"]["agate_on_4g"]
    assert t["enabled"] is False and t["off_by_button"] and said == "turned off"
    # turning it on again in Settings clears the note
    _on(st, "agate_on_4g")
    assert not ne.config(st)["triggers"]["agate_on_4g"].get("off_by_button")


def test_stop_reminders_tap_mutes_that_gateway(st, monkeypatch):
    monkeypatch.setattr(notify_buttons, "_store", lambda: st)
    req = SimpleNamespace(meta={"trigger": "off_grid_reminder", "gateway_id": "g9"})
    said = asyncio.run(notify_buttons._on_stop_reminders(req, SimpleNamespace(verb=notify_buttons.STOP)))
    assert ne.reminders_muted(st, "g9") and said == "reminders stopped until back on-grid"


# ── who gets them: by role ──────────────────────────────────────────────────────
def test_role_target_sends_to_devices_whose_account_has_that_role(st, sent):
    a = auth.create_user(st, "owner", "pw12345678", "admin")
    u = auth.create_user(st, "partner", "pw12345678", "user")
    auth.create_user(st, "guest", "pw12345678", "viewer")
    st.update_notify_device("d1", user_id=str(a["id"]))
    st.update_notify_device("d2", user_id=str(u["id"]))
    assert ne.valid_target({"type": "role", "role": "user"}) == {"type": "role", "role": "user"}
    with pytest.raises(ValueError):
        ne.valid_target({"type": "role", "role": "api"})
    assert ne.target_ids(st, {"type": "role", "role": "admin"}) == ["d1"]
    assert ne.target_ids(st, {"type": "role", "role": "viewer"}) == []
    assert ne.target_ids(st, {"type": "all"}) is None
    ne.set_config(st, {"triggers": {"off_grid": {"target": {"type": "role", "role": "user"}}}})
    ne.fire(st, "on_grid", gateway="aGate")
    assert sent["plain"][-1][:2] == ("on_grid", ["d2"])
    # a switched-off device stays off
    st.update_notify_device("d2", enabled=False)
    assert ne.target_ids(st, {"type": "role", "role": "user"}) == []
    # notifications with buttons too
    ne.set_config(st, {"asks": {"alert": {"target": {"type": "role", "role": "admin"}}}})
    assert ne.send_to_ids(st, "alert") == ["d1"]


def test_device_account_is_saved_through_the_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
    s = MetricsStore(str(tmp_path / "m.db"))
    auth.ensure_tables(s)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda _s: s)
    c = TestClient(app_module.create_app())
    s.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123", token="t")
    s.create_notify_device(dev_id="d1", alias="Phone", instance_id="home", service="notify.mobile_app_x")
    a = auth.create_user(s, "owner2", "pw12345678", "user")
    api = auth.create_user(s, "script", "", "api")
    r = c.patch("/api/ha/notify-devices/d1", json={"user_id": str(a["id"])})
    assert r.status_code == 200 and r.json()["user_id"] == str(a["id"])
    assert c.patch("/api/ha/notify-devices/d1", json={"user_id": str(api["id"])}).status_code == 422
    assert c.patch("/api/ha/notify-devices/d1", json={"user_id": "999"}).status_code == 422
    assert c.patch("/api/ha/notify-devices/d1", json={"user_id": ""}).json()["user_id"] in ("", None)


def test_settings_ui():
    for tid in ("trigger-interval", "trigger-target-role", "trigger-off-by-button",
                "device-account", "ask-target-role"):
        assert f'data-testid="{tid}"' in HTML, tid
    assert '<option value="role"' in HTML
    assert "api/security/users" in JS


def test_poller_and_alert_monitor_wire_them():
    poller = (PKG / "poller.py").read_text()
    alerts = (PKG / "alerts.py").read_text()
    assert "notify_engine.offgrid_reminder, _st, gw.id" in poller and "gateway_id=gw.id" in poller
    assert "notify_engine.on_alert_changes(" in alerts


def test_a_restart_keeps_the_count(st, sent):
    """From #618: a restart mid off-grid neither restarts the count nor sends twice."""
    cfg = _on(st, "off_grid_reminder")
    t0 = 4_000_000.0
    ne.offgrid_reminder(st, "g4", "aGate", OFF, cfg, None, t0)
    assert ne.offgrid_reminder(st, "g4", "aGate", OFF, cfg, None, t0 + 15 * 60) is True
    ne._REMIND.clear()                                                # the bridge restarts
    assert ne.offgrid_reminder(st, "g4", "aGate", OFF, cfg, None, t0 + 16 * 60) is False
    assert ne.offgrid_reminder(st, "g4", "aGate", OFF, cfg, None, t0 + 30 * 60) is True
    assert sent["asks"][-1][4]["duration"] == "30 min"
