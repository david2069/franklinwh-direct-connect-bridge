"""#269: unknown fields on a schedule are refused, never ignored."""

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, state


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(app_module, "_guard_writes", lambda: None, raising=False)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "first")    # a schedule names its gateway (#379)
    yield TestClient(app_module.create_app())
    state.reset_gateways()


BAD = {"name": "x", "enabled": False, "trigger": {"type": "weekly", "days": []},
       "actions": [{"type": "mode", "mode": "self"}]}


def test_post_with_unknown_fields_is_refused_and_creates_nothing(c):
    before = len(c.get("/api/schedules").json()["schedules"])
    r = c.post("/api/schedules", json=BAD)
    assert r.status_code == 422 and "trigger" in r.text
    assert len(c.get("/api/schedules").json()["schedules"]) == before


def test_put_with_unknown_fields_is_refused(c):
    sid = c.post("/api/schedules", json={"name": "ok", "enabled": False,
                                         "trigger_type": "daily", "fire_at": "10:00",
                                         "gateway_id": "g1"}).json()["id"]
    assert c.put(f"/api/schedules/{sid}", json={"name": "ok", "bogus": 1}).status_code == 422
