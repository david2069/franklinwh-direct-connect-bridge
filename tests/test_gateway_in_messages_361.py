"""#361: on a site with several aGates, each notification names the gateway it is about."""
from franklinwh_direct_connect_bridge import alerts, battery_control, notify, state


def setup_function():
    state.reset_gateways()
    state.register_gateway("gw-shed", "10.0.0.7", "Shed")


def teardown_function():
    state.reset_gateways()


def test_reachability_and_modbus_changes_name_the_gateway():
    msgs = [m for _, m in notify.transitions({"ok": True, "modbus_502": True},
                                             {"ok": False, "modbus_502": False}, "Shed")]
    assert msgs and all(m.startswith("Shed: ") for m in msgs)


def test_label_of_prefers_the_label():
    assert state.label_of("gw-shed") == "Shed"
    assert state.label_of("gone") == "gone" and state.label_of(None) is None


def test_the_reconcile_message_names_the_gateway_at_that_host():
    assert battery_control._label_for_host("10.0.0.7:502") == "Shed"
    assert battery_control._label_for_host("10.0.0.99") is None


def test_ha_alert_text_uses_the_label_not_the_id():
    text = alerts._ha_message({"message": "M", "code": "MQTT_DOWN", "gateway_id": "gw-shed"})
    assert "gateway Shed" in text and "gw-shed" not in text


def test_schedule_failed_names_the_gateway(monkeypatch):
    import datetime as dt
    from franklinwh_direct_connect_bridge import config, db, scheduler as SCH
    store = db.get_store(config.get_settings())
    monkeypatch.setattr(SCH, "run_action", lambda *a, **k: "force charge: failed — refused")
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    entry = {"id": "s1", "name": "nightly", "action": {"kind": "set_mode"},
             "_wkey": "2026-10-09", "_wend": None, "_occ_id": None,
             "_occ_attempts": 1, "duration_min": 60}
    SCH._fire_entry(entry, settings=None, client=None, store=store, snapshot={},
                    host="h", gateway_id="gw-shed", now=dt.datetime(2026, 10, 9, 18, 0))
    assert "Schedule 'nightly' on Shed failed" in store.alerts()[0]["message"]
