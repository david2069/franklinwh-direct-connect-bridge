"""#202 — a schedule is checked when it is saved or imported, not when it fails at run time."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client as client_module
from franklinwh_direct_connect_bridge import scheduler as sch

BASE = {"name": "x", "fire_at": "18:00", "duration_min": 60}
SOC = {"sensor": "battery.soc_pct", "op": "<", "value": 20}


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app())


@pytest.mark.parametrize("extra, says", [
    ({"action": {"kind": "set_mode"}}, "needs a mode"),
    ({"action": {"kind": "smart_circuit", "on": "maybe"}}, "'on' must be"),
    ({"action": {"kind": "smart_circuit", "on": True}}, "circuit number"),
    ({"action": {"kind": "notify"}}, "needs a device"),
    ({"action": {"kind": "force", "direction": "sideways", "power": 50}}, "direction"),
    ({"action": {"kind": "force", "direction": "charge", "power": 150}}, "out of range"),
    ({"action": {"kind": "force", "direction": "charge", "unit": "w", "power": ""}}, "needs a power"),
    ({"action": {"kind": "force", "direction": "charge", "power": 50, "target_soc": 120}},
     "target_soc"),
    ({"action": {"kind": "smart_circuit_schedule"}}, "unknown action"),
    ({"ha_actions": [{"ha_kind": "notify", "device_id": ""}]}, "HA action 1: notify needs"),
    ({"ha_actions": [{"ha_kind": "service", "instance_id": "h", "domain": "switch"}]},
     "needs service"),
    ({"ha_actions": [{"ha_kind": "service", "instance_id": "h", "domain": "switch",
                      "service": "turn_on", "data": "{not json"}]}, "not valid JSON"),
    ({"trigger_type": "cron", "cron": "nonsense"}, "not a valid cron"),
    ({"trigger_type": "interval", "interval_min": 0}, "interval_min"),
    ({"trigger_type": "monthly", "day_of_month": 0}, "day of the month"),
    ({"trigger_type": "monthly", "day_of_month": 32}, "day_of_month must be 1 to 31"),
    ({"months": [13]}, "months must be 1 to 12"),
    ({"days": [7]}, "days must be 0"),
    ({"fire_at": "25:00"}, "not HH:MM"),
    ({"start_date": "2026-10-21", "end_date": "2026-10-01"}, "before start_date"),
    ({"conditions": [{**SOC, "op": "≈"}]}, "operator"),
    ({"conditions": [{"op": "<", "value": 20}]}, "no sensor"),
    ({"conditions": [{"match": "all", "conditions": [{**SOC, "op": "between"}]}]},
     "two values"),
    ({"exit_conditions": [{**SOC, "value_kind": "sensor"}]}, "looks up no sensor"),
])
def test_save_refuses_an_invalid_schedule(c, extra, says):
    if extra.get("trigger_type") == "cron" and not sch.cron_available():
        pytest.skip("croniter not installed")
    r = c.post("/api/schedules", json={**BASE, **extra})
    assert r.status_code == 422, r.text
    assert says in r.json()["detail"]
    assert c.get("/api/schedules").json()["schedules"] == []


def test_a_valid_schedule_still_saves(c):
    r = c.post("/api/schedules", json={**BASE, "conditions": [SOC], "action": {
        "kind": "force", "direction": "charge", "unit": "pct", "power": 80, "target_soc": 90},
        "ha_actions": [{"ha_kind": "notify", "device_id": "d1", "when": "both"}]})
    assert r.status_code == 201, r.text


def test_import_flags_unknown_sensors_and_unexposed_ha_entities():
    rep = sch.validate_import(
        {**BASE, "conditions": [{"sensor": "battery.socc", "op": "<", "value": 20},
                                {"sensor": "ha:h1:sensor.price", "op": "<", "value": 5}]},
        gateway_ids=set(), device_ids=set(), exposed_ha=set())
    assert rep["ok"] is True                     # flagged, not refused
    assert any("unknown sensor 'battery.socc'" in w for w in rep["warnings"])
    assert any("ha:h1:sensor.price" in w and "not exposed" in w for w in rep["warnings"])
    rep = sch.validate_import({**BASE, "conditions": [{**SOC, "op": "≈"}]},
                              gateway_ids=set(), device_ids=set())
    assert rep["ok"] is False and any("operator" in e for e in rep["errors"])
