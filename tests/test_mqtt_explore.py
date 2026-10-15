"""A read-only broker explorer.

Owner, 2026-10-16: FWHAI has an MQTT explorer; did we build anything like it? We had
broker DIAGNOSTICS (conflicts, orphans, what we publish) but no way to look at an
arbitrary topic — the sniffer behind those only ever subscribes to discovery configs and
discards anything without "franklinwh" in it.

The hazards this pins: it must never publish, must never subscribe to the whole broker,
and must distinguish "nothing retained" from "nothing happened while I watched".
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
from franklinwh_direct_connect_bridge.db import MetricsStore
from franklinwh_direct_connect_bridge.publish import mqtt_scan


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: MetricsStore(str(tmp_path / "m.db")))
    s = config.get_settings()
    s.mqtt_enabled = True
    return TestClient(app_module.create_app())


def test_the_whole_broker_is_refused(client):
    """On a shared broker '#' is every message from every integration — a denial of
    service against this bridge, not a diagnostic."""
    for bad in ("#", "/#", "+/#"):
        r = client.post("/api/mqtt/explore", json={"filter": bad})
        assert r.status_code == 422, bad
        assert "narrow" in r.json()["detail"]


def test_an_empty_filter_is_refused(client):
    r = client.post("/api/mqtt/explore", json={"filter": "   "})
    assert r.status_code == 422


def test_it_refuses_when_mqtt_is_off(client, monkeypatch):
    config.get_settings().mqtt_enabled = False
    r = client.post("/api/mqtt/explore", json={"filter": "franklinwh-local/#"})
    assert r.status_code == 409


def test_results_say_retained_or_live(client, monkeypatch):
    """"Nothing retained" and "nothing happened while I watched" are different answers."""
    def _fake(settings, f, *, seconds=2.0, limit=200):
        return {"ok": True, "filter": f, "seconds": seconds, "count": 2, "truncated": False,
                "retained": 1,
                "messages": [{"topic": "a/b", "payload": "1", "bytes": 1, "clipped": False,
                              "retain": True},
                             {"topic": "a/c", "payload": "2", "bytes": 1, "clipped": False,
                              "retain": False}]}
    monkeypatch.setattr(mqtt_scan, "explore", _fake)
    body = client.post("/api/mqtt/explore", json={"filter": "a/#"}).json()
    assert body["retained"] == 1 and body["count"] == 2
    assert [m["retain"] for m in body["messages"]] == [True, False]


def test_a_broker_error_is_reported_not_raised(client, monkeypatch):
    monkeypatch.setattr(mqtt_scan, "explore",
                        lambda s, f, **k: {"ok": False, "error": "ConnectionRefusedError"})
    r = client.post("/api/mqtt/explore", json={"filter": "a/#"})
    assert r.status_code == 502 and "ConnectionRefused" in r.json()["detail"]


def test_the_watch_window_and_result_count_are_bounded():
    """A broker can hold a very large retained set; a diagnostic that fetches all of it is
    a denial of service against the bridge it runs in."""
    assert mqtt_scan.EXPLORE_MAX_SECONDS <= 10
    assert mqtt_scan.EXPLORE_MAX_TOPICS <= 1000
    assert mqtt_scan.EXPLORE_MAX_PAYLOAD <= 8192


def test_the_explorer_never_publishes():
    """Read-only is the whole safety story: there must be no publish call in it."""
    import inspect
    src = inspect.getsource(mqtt_scan.explore)
    assert ".publish(" not in src
    assert "subscribe" in src


def test_suggestions_name_what_each_filter_answers(client):
    out = client.get("/api/mqtt/explore/suggestions").json()["suggestions"]
    assert out and all(s["filter"] and s["label"] for s in out)
    assert any("discovery" in s["label"].lower() for s in out)
