"""#198 — a trigger whose restriction is missing never fires, and is refused on save.

Weekly with no days, Monthly with no day of month and One-off with no date had no
restriction, so they fired every day; a Recurring window with start = end was open all day."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client as client_module
from franklinwh_direct_connect_bridge import scheduler as sch

NOW = dt.datetime(2026, 10, 21, 18, 30)            # a Wednesday, inside 18:00 + 90


@pytest.mark.parametrize("entry", [
    {"trigger_type": "weekly", "days": []},
    {"trigger_type": "monthly", "day_of_month": None},
    {"trigger_type": "once"},
])
def test_a_missing_restriction_never_fires(entry):
    e = {"enabled": True, "fire_at": "18:00", "duration_min": 90, **entry}
    ok, why = sch.due(e, NOW, {}, None)
    assert ok is False and "no" in why
    assert sch.next_fire_ts(e, NOW) is None


def test_a_window_with_start_equal_to_end_is_empty():
    e = {"enabled": True, "trigger_type": "window", "fire_at": "18:00", "duration_min": 90,
         "windows": [{"start": "18:00", "end": "18:00"}]}
    assert sch.window_now(e, NOW)[0] == "outside"
    assert sch.window_now(e, NOW.replace(hour=18, minute=0))[0] == "outside"
    assert sch.next_fire_ts(e, NOW) is None
    # a real window beside it still works
    e["windows"].append({"start": "18:00", "end": "19:00"})
    assert sch.window_now(e, NOW)[0] == "inside"


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app())


@pytest.mark.parametrize("body, says", [
    ({"trigger_type": "weekly", "days": []}, "day of the week"),
    ({"trigger_type": "monthly"}, "day of the month"),
    ({"trigger_type": "once"}, "needs a date"),
    ({"trigger_type": "window", "windows": [{"start": "18:00", "end": "18:00"}]}, "same time"),
    ({"trigger_type": "window", "windows": []}, "at least one window"),
])
def test_save_refuses_it_with_a_reason(c, body, says):
    r = c.post("/api/schedules", json={"name": "x", "fire_at": "18:00", **body})
    assert r.status_code == 422 and says in r.json()["detail"]
    assert c.get("/api/schedules").json()["schedules"] == []
    # and an edit that would make a saved schedule invalid is refused too
    sid = c.post("/api/schedules", json={"name": "ok", "fire_at": "18:00"}).json()["id"]
    r = c.put(f"/api/schedules/{sid}", json={"name": "ok", **body})
    assert r.status_code == 422 and says in r.json()["detail"]


def test_import_reports_it_as_an_error():
    rep = sch.validate_import({"name": "w", "fire_at": "18:00", "trigger_type": "weekly"},
                              gateway_ids=set(), device_ids=set())
    assert rep["ok"] is False and any("day of the week" in e for e in rep["errors"])
