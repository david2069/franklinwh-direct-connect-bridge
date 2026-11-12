"""A schedule's notify rows name the gateway the schedule ran on (#577): they named the
first (default) gateway, because the HA-action phase never passed the gateway along."""
import datetime as dt
from types import SimpleNamespace

import pytest

from franklinwh_direct_connect_bridge import actionable, state
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge.db import MetricsStore

NOW = dt.datetime(2026, 11, 13, 18, 0)


@pytest.fixture
def st(tmp_path, monkeypatch):
    s = MetricsStore(str(tmp_path / "t.db"))
    s.create_ha_instance(ha_id="home", name="Home", base_url="http://ha.test:8123", token="t")
    s.create_notify_device(dev_id="d1", alias="Phone", instance_id="home",
                           service="notify.mobile_app_phone")
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "First")
    state.register_gateway("g2", "192.0.2.11", "Second")
    sent = []
    monkeypatch.setattr(actionable, "send", lambda store, event, gateway=None, **k:
                        sent.append(gateway) or SimpleNamespace(total=1, delivered=1, deliveries=[]))
    yield s, sent
    state.reset_gateways()


def _entry(when):
    return {"id": "s1", "name": "Low SoC", "action": {}, "duration_min": 60,
            "_wkey": "2026-11-13", "_occ_attempts": 1,
            "ha_actions": [{"device_id": "d1", "when": when, "title": "t", "message": "m"}]}


def test_on_entry_names_the_gateway_that_ran(st):
    store, sent = st
    sch._fire_entry(_entry("fire"), settings=None, client=None, store=store, snapshot={},
                    host=None, gateway_id="g2", now=NOW)
    assert sent == ["Second"]


def test_on_exit_names_the_gateway_that_ran(st):
    store, sent = st
    out = sch._fire_ha_phase(_entry("exit"), "exit", settings=None, client=None, store=store,
                             snapshot={}, host=None, gateway_id="g2")
    assert sent == ["Second"] and out


def test_run_now_names_the_gateway_it_ran_on(st, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, db
    store, sent = st
    monkeypatch.setattr(app_module, "_guard_writes", lambda: None, raising=False)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    store.create_schedule(sid="s1", name="Low SoC", spec={
        "gateway_id": "g2", "fire_at": "18:00", "duration_min": 60, "conditions": [],
        "action": {}, "ha_actions": [{"device_id": "d1", "when": "fire", "title": "t",
                                      "message": "m"}]})
    r = TestClient(app_module.create_app()).post("/api/schedules/s1/run")
    assert r.status_code == 200, r.text
    assert sent == ["Second"]
