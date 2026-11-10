"""REST for alerts (#271, shared spec v1 §4): GET /api/alerts, ack, GET /api/status."""

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import alerts, app as app_module, config, db


@pytest.fixture
def api():
    alerts.reset()
    store = db.get_store(config.get_settings())
    yield TestClient(app_module.create_app()), store
    alerts.reset()


def test_status_summary_follows_the_open_set(api):
    c, st = api
    assert c.get("/api/status").json()["alerts"] == {"level": "ok", "open": 0,
                                                     "latest_id": None, "changed_ts": None}
    a = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "Force rejected", now=1.0)
    body = c.get("/api/status").json()
    assert body["alerts"] == {"level": "critical", "open": 1, "latest_id": a,
                              "changed_ts": 1.0}
    # A monitor that is not running is DATA here, not a failed endpoint.
    assert body["alert_monitor"]["state"] in ("absent", "running", "stopped")
    assert c.get("/api/live").status_code == 200


def test_list_filters_and_delivery_record(api):
    c, st = api
    e = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=100.0)
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0.0)
    cond = alerts.evaluate(st, now=300.0)[0]["id"]
    rows = c.get("/api/alerts").json()["alerts"]
    assert [r["id"] for r in rows] == [e, cond]                   # newest first
    assert rows[0]["deliveries"][0]["channel"] == alerts.CH_HA_CREATE
    assert [r["id"] for r in c.get("/api/alerts?kind=condition").json()["alerts"]] == [cond]
    assert [r["id"] for r in c.get("/api/alerts?since=250").json()["alerts"]] == [cond]
    assert c.get("/api/alerts?kind=bogus").status_code == 422


def test_ack_closes_an_event_and_keeps_a_condition_open(api):
    c, st = api
    e = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=1.0)
    alerts.set_condition("gw1", "GATEWAY_UNREACHABLE", True, now=0.0)
    cond = alerts.evaluate(st, now=300.0)[0]["id"]

    r = c.post(f"/api/alerts/{e}/ack", json={"source": "ui"})
    assert r.status_code == 200 and r.json()["acked_by"] == "source:ui"
    r = c.post(f"/api/alerts/{cond}/ack")                         # no body: an API call
    assert r.json()["acked_by"] == "source:api"
    assert [x["id"] for x in c.get("/api/alerts?open=1").json()["alerts"]] == [cond]
    assert c.get("/api/status").json()["alerts"]["open"] == 1


def test_ack_errors(api):
    c, st = api
    e = alerts.raise_event(st, "gw1", "COMMAND_REFUSED", "x", now=1.0)
    assert c.post("/api/alerts/999/ack", json={"source": "ui"}).status_code == 404
    assert c.post(f"/api/alerts/{e}/ack", json={"source": "user:x"}).status_code == 400
    assert st.alert(e)["acked_ts"] is None


def test_app_start_runs_the_alert_monitor_as_a_worker(monkeypatch):
    """Registered and beating, and reported by /api/status (RUNTIME_DESIGN decision 4)."""
    import time
    from franklinwh_direct_connect_bridge import workers
    s = config.get_settings()
    monkeypatch.setattr(s, "fwh_cloud_email", "")
    monkeypatch.setattr(s, "fwh_cloud_password", "")
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with TestClient(app_module.create_app()) as c:
        deadline = time.time() + 5
        while time.time() < deadline and workers.registry.get(alerts.WORKER_NAME) is None:
            time.sleep(0.05)
        w = workers.registry.get(alerts.WORKER_NAME)
        assert w is not None and w.state is workers.WorkerState.RUNNING
        mon = c.get("/api/status").json()["alert_monitor"]
        assert mon["state"] == "running" and mon["stale"] is False
