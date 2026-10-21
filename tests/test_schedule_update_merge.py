"""#157 — saving part of a schedule must not wipe the rest of it.

The Scheduler's on/off toggle sent a partial PUT and the endpoint replaced the whole
definition with defaults: trigger, windows, calendar, exit conditions, hold, priority…
were silently lost. The edit form likewise dropped restore_on_exit and gateway_scope."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client as client_module

FULL = {
    "name": "Evening peak", "enabled": True, "fire_at": "17:00", "duration_min": 180,
    "match": "any", "entry_hold_s": 120, "gateway_id": "", "gateway_scope": "all",
    "restore_on_exit": True, "conditions": [{"sensor": "battery.soc_pct", "op": ">", "value": 50}],
    "exit_conditions": [{"sensor": "battery.soc_pct", "op": "<", "value": 20}], "exit_match": "any",
    "days": [0, 1, 2, 3, 4], "months": [6, 7, 8], "priority": 5, "conflict": "defer",
    "trigger_type": "window", "windows": [{"start": "17:00", "end": "20:00"}],
    "action": {"kind": "set_mode", "mode": "self"}, "ha_actions": [],
}
KEEP = ["entry_hold_s", "gateway_scope", "restore_on_exit", "exit_conditions", "exit_match",
        "days", "months", "priority", "conflict", "trigger_type", "windows", "match"]


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app())


def _create(c):
    r = c.post("/api/schedules", json=FULL)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _get(c, sid):
    return next(x for x in c.get("/api/schedules").json()["schedules"] if x["id"] == sid)


def test_the_toggle_body_changes_only_enabled(c):
    sid = _create(c)
    s = _get(c, sid)
    toggle = {"name": s["name"], "enabled": False, "fire_at": s["fire_at"],
              "duration_min": s["duration_min"], "match": s["match"], "gateway_id": "",
              "conditions": s["conditions"], "action": s["action"], "ha_actions": []}
    assert c.put(f"/api/schedules/{sid}", json=toggle).status_code == 200
    after = _get(c, sid)
    assert after["enabled"] is False
    for k in KEEP:
        assert after[k] == FULL[k], k


def test_a_form_save_keeps_api_only_fields(c):
    sid = _create(c)
    form = {k: v for k, v in FULL.items() if k not in ("restore_on_exit", "gateway_scope")}
    form["name"] = "Evening peak (renamed)"
    c.put(f"/api/schedules/{sid}", json=form)
    after = _get(c, sid)
    assert after["name"] == "Evening peak (renamed)"
    assert after["restore_on_exit"] is True and after["gateway_scope"] == "all"


def test_a_field_that_is_sent_still_changes(c):
    sid = _create(c)
    # (Not `windows`: a Recurring-windows schedule with none is refused since #198.)
    c.put(f"/api/schedules/{sid}", json={"name": "Evening peak", "months": [], "priority": 0})
    after = _get(c, sid)
    assert after["months"] == [] and after["priority"] == 0
    assert after["days"] == FULL["days"]          # untouched fields stay


def test_a_put_without_enabled_keeps_a_disabled_schedule_off(c):
    """#168: `enabled` left out of a PUT is not "turn it on"."""
    sid = _create(c)
    assert c.put(f"/api/schedules/{sid}", json={"name": "Evening peak", "enabled": False}
                 ).status_code == 200
    assert c.put(f"/api/schedules/{sid}", json={"name": "Renamed"}).status_code == 200
    after = _get(c, sid)
    assert after["name"] == "Renamed" and after["enabled"] is False
