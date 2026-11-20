"""The Push notifications switch follows Home Assistant (owner, 2026-11-21).

Before: it was on for a new install with no Home Assistant to send to, so the check said
"Pass" for a switch that could deliver nothing. Now it is off until a Home Assistant is
set up, turns on when the first one that connects is added, and turns off when the last
one is removed. A choice the user makes while one is set up is left alone.

Also: the Operating Mode card lists the modes in the FranklinWH app's order (Time-of-Use,
Self-Consumption, Emergency Backup), whatever order the gateway's 1726 list comes in.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, client, config, db,
                                              environment, ha_instances, notify)
from franklinwh_direct_connect_bridge.db import MetricsStore

HA = "http://127.0.0.1:9"


@pytest.fixture
def store(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.setattr(ha_instances, "probe", lambda url, token: {"ok": True})
    s = config.get_settings()
    s.ha_url = s.ha_token = ""
    s.allow_writes = True
    return st


def test_off_at_start_with_no_home_assistant(store):
    s = config.get_settings()
    assert s.ha_notify is True                   # the old default
    notify.push_default(s)
    assert s.ha_notify is False


def test_a_saved_choice_wins_at_start(store):
    config.save_override("ha_notify", True)
    s = config.get_settings()
    notify.push_default(s)
    assert s.ha_notify is True


def test_on_at_start_when_home_assistant_is_set_up(store):
    store.create_ha_instance(ha_id="home", name="Home", base_url=HA, token="t",
                             is_default=True)
    s = config.get_settings()
    notify.push_default(s)
    assert s.ha_notify is True


def test_the_first_instance_that_connects_turns_it_on(store):
    s = config.get_settings()
    notify.push_default(s)
    c = TestClient(app_module.create_app())
    assert c.post("/api/ha/instances", json={"name": "Home", "base_url": HA,
                                             "token": "t"}).status_code == 201
    assert s.ha_notify is True
    assert config.load_overrides()["ha_notify"] is True


def test_an_instance_that_does_not_connect_leaves_it_off(store, monkeypatch):
    monkeypatch.setattr(ha_instances, "probe",
                        lambda url, token: {"ok": False, "error": "token rejected"})
    s = config.get_settings()
    notify.push_default(s)
    c = TestClient(app_module.create_app())
    c.post("/api/ha/instances", json={"name": "Home", "base_url": HA, "token": "t"})
    assert s.ha_notify is False


def test_removing_the_last_instance_turns_it_off(store):
    s = config.get_settings()
    c = TestClient(app_module.create_app())
    hid = c.post("/api/ha/instances", json={"name": "Home", "base_url": HA,
                                            "token": "t"}).json()["id"]
    assert s.ha_notify is True
    assert c.delete(f"/api/ha/instances/{hid}").status_code == 200
    assert s.ha_notify is False
    assert config.load_overrides()["ha_notify"] is False


def test_disabling_the_only_instance_turns_it_off(store):
    s = config.get_settings()
    c = TestClient(app_module.create_app())
    hid = c.post("/api/ha/instances", json={"name": "Home", "base_url": HA,
                                            "token": "t"}).json()["id"]
    c.patch(f"/api/ha/instances/{hid}", json={"enabled": False})
    assert s.ha_notify is False
    c.patch(f"/api/ha/instances/{hid}", json={"enabled": True})
    assert s.ha_notify is True


def test_the_users_choice_is_kept_while_one_is_set_up(store):
    s = config.get_settings()
    c = TestClient(app_module.create_app())
    c.post("/api/ha/instances", json={"name": "Home", "base_url": HA, "token": "t"})
    c.put("/api/settings", json={"ha_notify": False})
    assert s.ha_notify is False
    hid = c.post("/api/ha/instances", json={"name": "Shed", "base_url": HA,
                                            "token": "t"}).json()["id"]
    c.delete(f"/api/ha/instances/{hid}")
    assert s.ha_notify is False


def test_modes_in_the_app_order():
    ml = {"current_id": "b", "list": [
        {"id": "b", "name": "Self", "scheduling_type": 2, "reserved_soc": 5},
        {"id": "a", "name": "My TOU", "scheduling_type": 1, "reserved_soc": 15},
        {"id": "c", "name": "Backup", "scheduling_type": 3, "reserved_soc": 100}]}
    modes = client.modes_from_list(ml)
    assert [m["name"] for m in modes] == ["Time-of-Use", "Self-Consumption",
                                          "Emergency Backup"]
    assert [m["active"] for m in modes] == [False, True, False]
    assert modes[0]["tariff"] == "My TOU"
