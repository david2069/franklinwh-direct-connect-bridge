"""#269: unknown fields on a schedule are refused, never ignored."""

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(app_module, "_guard_writes", lambda: None, raising=False)
    return TestClient(app_module.create_app())


BAD = {"name": "x", "enabled": False, "trigger": {"type": "weekly", "days": []},
       "actions": [{"type": "mode", "mode": "self"}]}


def test_post_with_unknown_fields_is_refused_and_creates_nothing(c):
    before = len(c.get("/api/schedules").json()["schedules"])
    r = c.post("/api/schedules", json=BAD)
    assert r.status_code == 422 and "trigger" in r.text
    assert len(c.get("/api/schedules").json()["schedules"]) == before


def test_put_with_unknown_fields_is_refused(c):
    sid = c.post("/api/schedules", json={"name": "ok", "enabled": False,
                                         "trigger_type": "daily", "fire_at": "10:00"}).json()["id"]
    assert c.put(f"/api/schedules/{sid}", json={"name": "ok", "bogus": 1}).status_code == 422
