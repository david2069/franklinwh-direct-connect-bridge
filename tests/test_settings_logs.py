"""P6 (logs endpoint/buffer) + P7 (live settings-write) tests.

Runtime overrides are a singleton + on-disk file, so every P7 test uses a tmp DATA_DIR
and resets the config singleton / logger level so nothing leaks between tests.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import config, environment, logbuffer

BRIDGE_LOGGER = "franklinwh_direct_connect_bridge"


# -- P6: logs endpoint + ring buffer ----------------------------------------

def test_logs_endpoint_returns_entries_and_shape():
    c = TestClient(app_module.create_app())   # installs the ring-buffer handler
    logbuffer.clear()
    logging.getLogger(BRIDGE_LOGGER).info("hello logs %d", 42)
    r = c.get("/api/logs?limit=5")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) >= 1
    top = entries[0]                          # newest-first
    assert {"ts", "level", "name", "message"} <= set(top)
    assert top["message"] == "hello logs 42"  # formatted
    assert top["level"] == "INFO"
    assert top["name"] == BRIDGE_LOGGER
    assert isinstance(top["ts"], (int, float))


def test_logs_endpoint_respects_limit_and_order():
    c = TestClient(app_module.create_app())
    logbuffer.clear()
    log = logging.getLogger(BRIDGE_LOGGER)
    for i in range(10):
        log.info("line %d", i)
    r = c.get("/api/logs?limit=3")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 3
    assert entries[0]["message"] == "line 9"   # newest-first
    assert entries[2]["message"] == "line 7"


def test_logs_endpoint_level_filter():
    c = TestClient(app_module.create_app())
    logbuffer.clear()
    log = logging.getLogger(BRIDGE_LOGGER)
    log.info("an info line")
    log.error("an error line")
    r = c.get("/api/logs?level=error")
    assert r.status_code == 200
    msgs = [e["message"] for e in r.json()["entries"]]
    assert "an error line" in msgs
    assert "an info line" not in msgs


def test_logs_persist_across_restart(tmp_path):
    """Lines persist across a 'restart' via the DB (not a rewritten file) — the durable
    Logs history. Uses an explicit tmp store so it never touches real data."""
    from franklinwh_direct_connect_bridge import db as _db
    store = _db.MetricsStore(str(tmp_path / "m.db"))
    logbuffer.install(BRIDGE_LOGGER)
    logbuffer.set_store(store)
    logbuffer.clear()
    log = logging.getLogger(BRIDGE_LOGGER)
    log.info("persisted line A")
    log.warning("persisted line B")
    # Simulate a restart: drop the in-memory buffer, then re-hydrate from the DB.
    logbuffer._BUFFER.clear()
    assert logbuffer.get_logs() == []
    logbuffer.hydrate_from_store()
    msgs = [e["message"] for e in logbuffer.get_logs()]
    assert "persisted line A" in msgs and "persisted line B" in msgs


# -- P7: live settings-write ------------------------------------------------

@pytest.fixture
def tmp_overrides(tmp_path, monkeypatch):
    """Isolate the overrides file + config singleton + bridge logger level per test."""
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    config._settings = None
    yield tmp_path
    config._settings = None
    logging.getLogger(BRIDGE_LOGGER).setLevel(logging.INFO)


def test_override_roundtrip(tmp_overrides):
    assert config.load_overrides() == {}
    config.save_override("allow_writes", True)
    config.save_override("not_whitelisted", 1)   # ignored — not in _OVERRIDE_KEYS
    assert config.load_overrides() == {"allow_writes": True}
    s = config.Settings()
    assert s.allow_writes is False
    config.apply_overrides(s)
    assert s.allow_writes is True


def test_load_overrides_safe_on_bad_file(tmp_overrides):
    config.overrides_path().write_text("{ not json")
    assert config.load_overrides() == {}   # never raises


def test_get_settings_applies_persisted_overrides(tmp_overrides):
    config.save_override("log_level", "debug")
    config.save_override("ha_notify", False)
    s = config.get_settings()
    assert s.log_level == "debug"
    assert s.ha_notify is False


def test_put_settings_allow_writes_is_live(tmp_overrides, monkeypatch):
    # FEAT-WRITE-CONFIRM: allow_writes no longer gates (writes are open; consequential
    # actions confirm instead), but the setting still persists live via PUT /api/settings.
    c = TestClient(app_module.create_app())
    r = c.put("/api/settings", json={"allow_writes": True})
    assert r.status_code == 200
    assert config.load_overrides().get("allow_writes") is True


def test_put_settings_unknown_key_422(tmp_overrides):
    c = TestClient(app_module.create_app())
    r = c.put("/api/settings", json={"poll_interval": 10})
    assert r.status_code == 422
    assert "live-editable" in r.json()["detail"].lower()


def test_put_settings_log_level_sets_logger(tmp_overrides):
    c = TestClient(app_module.create_app())
    r = c.put("/api/settings", json={"log_level": "error"})
    assert r.status_code == 200
    assert r.json()["control"]["log_level"] == "error"
    assert logging.getLogger(BRIDGE_LOGGER).level == logging.ERROR
    assert config.load_overrides().get("log_level") == "error"
    # An invalid level is rejected, not applied.
    assert c.put("/api/settings", json={"log_level": "bogus"}).status_code == 422


def test_put_ha_url_and_token(monkeypatch, tmp_path):
    """Standalone HA target is now UI-editable: PUT ha_url + ha_token persists, /api/settings
    exposes ha_url + ha_token_set (never the token itself)."""
    from franklinwh_direct_connect_bridge import config as config_module
    monkeypatch.setattr(config_module, "overrides_path", lambda: tmp_path / "overrides.json")
    # fresh settings singleton so overrides apply cleanly
    config_module._settings = None
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module
    c = TestClient(app_module.create_app())
    r = c.put("/api/settings", json={"ha_url": "http://ha.local:8123", "ha_token": "secret-xyz"})
    assert r.status_code == 200
    view = c.get("/api/settings").json()["notifications"]
    assert view["ha_url"] == "http://ha.local:8123"
    assert view["ha_token_set"] is True
    assert "ha_token" not in view and "secret-xyz" not in str(view)   # token never returned
    # persisted to the overrides file
    import json
    saved = json.loads((tmp_path / "overrides.json").read_text())
    assert saved["ha_url"] == "http://ha.local:8123" and saved["ha_token"] == "secret-xyz"
    config_module._settings = None


def test_logs_since_filter_and_pagination(tmp_path):
    """DB-backed logs: `since` bounds the window, and offset pagination returns totals —
    newest-first. Explicit tmp store, so real data is never touched."""
    import time
    from franklinwh_direct_connect_bridge import db as _db
    store = _db.MetricsStore(str(tmp_path / "m.db"))
    logbuffer.install(BRIDGE_LOGGER)
    logbuffer.set_store(store)
    logbuffer.clear()
    log = logging.getLogger(BRIDGE_LOGGER)
    log.info("old line")
    time.sleep(0.02)
    cutoff = time.time()
    time.sleep(0.02)
    log.info("new line")
    log.info("third line")
    # since filter
    msgs = [r["message"] for r in store.logs(since=cutoff)]
    assert "new line" in msgs and "old line" not in msgs
    # pagination: total count + offset, newest-first
    assert store.logs_count() >= 3
    p1 = store.logs(limit=1, offset=0)
    p2 = store.logs(limit=1, offset=1)
    assert p1 and p2 and p1[0]["ts"] >= p2[0]["ts"]
