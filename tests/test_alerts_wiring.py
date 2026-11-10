"""Where alerts come from (#271, spec v1 §9): the poller, the audit trail, the scheduler."""

import asyncio
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (alerts, app as app_module, config, db, poller,
                                              providers, scheduler as SCH,
                                              scheduler_worker, workers)
from franklinwh_direct_connect_bridge.state import GatewayState


@pytest.fixture(autouse=True)
def _fresh():
    alerts.reset()
    yield
    alerts.reset()


# ── poller facts ──────────────────────────────────────────────────────────────
class _Pub:
    connected = True

    def __init__(self, *a, **k):
        self.configs = []

    def start(self): pass
    def stop(self): pass
    def is_connected(self): return _Pub.connected
    def publish_state(self, st): pass
    def publish_availability(self, online): pass
    def publish_alerts(self, payload): pass


def _poll(monkeypatch, summ: dict, *, host="127.0.0.1:1", mqtt=False, publish_ha=True,
          connected=True) -> dict:
    s = config.get_settings()
    monkeypatch.setattr(s, "mqtt_enabled", mqtt)
    monkeypatch.setattr(s, "poll_interval", 1)
    _Pub.connected = connected
    monkeypatch.setattr(poller, "MqttPublisher", _Pub)
    monkeypatch.setattr(poller.client, "firmware",
                        lambda *a, **k: {"IBG_SN": "SN271", "IBG_VER": "V1"})
    monkeypatch.setattr(poller.client, "summary", lambda *a, **k: dict(summ))
    import franklinwh_direct_connect_bridge.ha_supervisor as hs
    monkeypatch.setattr(hs, "apply_supervisor_mqtt", lambda *a, **k: None)
    gw = GatewayState(id="g271", label="test", is_mock=True, publish_ha=publish_ha,
                      configured_host=host, active_host=host)

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(0.5)
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    return {k[1]: v for k, v in alerts.facts().items() if k[0] == "g271"}


def test_unreachable_gateway_is_unreachable_not_also_missing_data(monkeypatch):
    # One fault, one alert (G1, 2026-10-21): live data missing means it ANSWERS but has none.
    f = _poll(monkeypatch, {"ok": False, "error": "connection refused"})
    assert f["GATEWAY_UNREACHABLE"]["bad"] and not f["LIVE_DATA_MISSING"]["bad"]
    assert "connection refused" in f["GATEWAY_UNREACHABLE"]["detail"]


def test_reachable_without_live_data_is_only_missing_data(monkeypatch):
    f = _poll(monkeypatch, {"ok": True})
    assert f["GATEWAY_UNREACHABLE"]["bad"] is False
    assert f["LIVE_DATA_MISSING"]["bad"] is True


def test_a_good_poll_is_good(monkeypatch):
    f = _poll(monkeypatch, {"ok": True, "power": {"soc": 50}})
    assert not f["GATEWAY_UNREACHABLE"]["bad"] and not f["LIVE_DATA_MISSING"]["bad"]
    assert f["MQTT_DOWN"]["bad"] is False                 # MQTT off is not MQTT down


def test_no_gateway_address_reports_nothing(monkeypatch):
    """A fresh install with no gateway set up (#265) is not an outage."""
    f = _poll(monkeypatch, {"ok": False, "error": "no gateway configured"}, host="")
    assert "GATEWAY_UNREACHABLE" not in f and "LIVE_DATA_MISSING" not in f


def test_mqtt_down_only_where_publishing_is_wanted(monkeypatch):
    ok = {"ok": True, "power": {"soc": 50}}
    assert _poll(monkeypatch, ok, mqtt=True, connected=False)["MQTT_DOWN"]["bad"] is True
    alerts.reset()
    assert _poll(monkeypatch, ok, mqtt=True, connected=True)["MQTT_DOWN"]["bad"] is False
    alerts.reset()
    assert _poll(monkeypatch, ok, mqtt=True, connected=False,
                 publish_ha=False)["MQTT_DOWN"]["bad"] is False


# ── COMMAND_REFUSED from control_log ok=0 ─────────────────────────────────────
def test_a_refused_control_raises_command_refused():
    store = db.get_store(config.get_settings())
    w = workers.registry.register(workers.Worker(
        name="alerts-test-thread", concern="t", cadence_s=5.0, kind="thread"))
    try:
        r = TestClient(app_module.create_app()).post(
            "/api/health/workers/alerts-test-thread/restart")
        assert r.status_code == 409
    finally:
        workers.registry.unregister(w.name)
    rows = store.alerts(open_only=True)
    assert [(x["code"], x["severity"]) for x in rows] == [("COMMAND_REFUSED", "critical")]
    assert "worker_restart" in rows[0]["message"] and "refused" in rows[0]["message"]
    assert store.control_log()[0]["ok"] == 0             # the source row it came from


def test_cloud_sign_in_failures_and_worker_deaths_are_not_commands():
    store = db.get_store(config.get_settings())
    TestClient(app_module.create_app())                    # installs providers.AUDIT
    providers.audit_cloud("cloud_login", detail="x", result="rejected", ok=False)
    assert store.control_log()[0]["action"] == "cloud_login"
    assert store.alerts() == []


# ── SCHEDULE_FAILED ───────────────────────────────────────────────────────────
def test_a_failed_scheduled_action_raises_schedule_failed(monkeypatch):
    store = db.get_store(config.get_settings())
    monkeypatch.setattr(SCH, "run_action", lambda *a, **k: "force charge: failed — refused")
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    entry = {"id": "s1", "name": "nightly", "action": {"kind": "set_mode"},
             "_wkey": "2026-10-09", "_wend": None, "_occ_id": None,
             "_occ_attempts": 1, "duration_min": 60}
    for _ in range(2):                                     # a retry merges into one
        SCH._fire_entry(entry, settings=None, client=None, store=store, snapshot={},
                        host="h", gateway_id="gw1", now=dt.datetime(2026, 10, 9, 18, 0))
    rows = store.alerts()
    assert [(r["code"], r["gateway_id"], r["count"]) for r in rows] == \
        [("SCHEDULE_FAILED", "gw1", 2)]
    assert "nightly" in rows[0]["message"]


def test_a_successful_scheduled_action_raises_nothing(monkeypatch):
    store = db.get_store(config.get_settings())
    monkeypatch.setattr(SCH, "run_action", lambda *a, **k: "mode -> self: ok")
    monkeypatch.setattr(SCH, "_fire_ha_phase", lambda *a, **k: [])
    entry = {"id": "s1", "name": "nightly", "action": {"kind": "set_mode"},
             "_wkey": "2026-10-09", "_wend": None, "_occ_id": None,
             "_occ_attempts": 1, "duration_min": 60}
    SCH._fire_entry(entry, settings=None, client=None, store=store, snapshot={},
                    host="h", gateway_id="gw1", now=dt.datetime(2026, 10, 9, 18, 0))
    assert store.alerts() == []


def test_a_missed_window_raises_schedule_failed(monkeypatch):
    s = config.get_settings()
    store = db.get_store(s)
    monkeypatch.setattr(store, "sweep_missed", lambda **k: [
        {"schedule_id": "s1", "name": "nightly", "gateway_id": "gw1", "attempts": 3}])
    scheduler_worker.sweep(s)
    rows = store.alerts()
    assert [(r["code"], r["gateway_id"]) for r in rows] == [("SCHEDULE_FAILED", "gw1")]
    assert "missed its window" in rows[0]["message"]
