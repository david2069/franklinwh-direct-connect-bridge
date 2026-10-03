"""/api/metrics + /api/metrics/info endpoint tests (store is monkeypatched)."""

import time

from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module
from franklinwh_local_bridge import db as db_module
from franklinwh_local_bridge.db import MetricsStore


def _app():
    return TestClient(app_module.create_app())


def _seeded_store(tmp_path):
    store = MetricsStore(str(tmp_path / "metrics.db"))
    now = int(time.time())
    for i in range(10):
        store.insert(
            {"soc": 50 + i, "grid_w": i * 10, "solar_w": 0,
             "battery_w": -i, "load_w": 100, "generator_w": 0, "mode": "Self"},
            now - 600 + i * 60,
        )
    return store


def test_metrics_returns_series(monkeypatch, tmp_path):
    store = _seeded_store(tmp_path)
    monkeypatch.setattr(db_module, "get_store", lambda s: store)
    c = _app()
    r = c.get("/api/metrics?range=24h")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["count"] > 0
    assert len(body["series"]) > 0


def test_metrics_info_has_count(monkeypatch, tmp_path):
    store = _seeded_store(tmp_path)
    monkeypatch.setattr(db_module, "get_store", lambda s: store)
    c = _app()
    r = c.get("/api/metrics/info")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["count"] == 10
    assert "retention_days" in body


def test_metrics_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(db_module, "get_store", lambda s: None)
    c = _app()
    r = c.get("/api/metrics?range=6h")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["series"] == []
    assert body["count"] == 0


def test_metrics_12h_range_resolves(monkeypatch, tmp_path):
    """The new 12h Power-History window is a known range → 200 with a resolved bucket."""
    assert app_module.RANGE_SECONDS["12h"] == 43200
    store = _seeded_store(tmp_path)
    monkeypatch.setattr(db_module, "get_store", lambda s: store)
    c = _app()
    r = c.get("/api/metrics?range=12h")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["range"] == "12h"
    assert body["bucket_s"] == app_module._DEFAULT_BUCKETS["12h"]


def test_metrics_explicit_bucket_and_window(monkeypatch, tmp_path):
    store = _seeded_store(tmp_path)
    monkeypatch.setattr(db_module, "get_store", lambda s: store)
    c = _app()
    now = int(time.time())
    r = c.get(f"/api/metrics?start={now - 3600}&end={now}&bucket=300")
    assert r.status_code == 200
    body = r.json()
    assert body["bucket_s"] == 300
    assert body["enabled"] is True
