"""The site timezone over the API, and the mock gateways that must inherit it.

Reported 2026-10-15 on the demo stack: three mocks, three different times of day, and the
scheduler dying every tick on the offset derived from one of them. The fix is one zone for
the site, applied to the emulators the bridge itself owns.
"""
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, config, db, environment,
                                              mockgw, setup_wizard, site_time)
from franklinwh_direct_connect_bridge.db import MetricsStore


def _client(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    return TestClient(app_module.create_app()), st


def test_set_and_read_back_the_site_timezone(tmp_path, monkeypatch):
    c, st = _client(tmp_path, monkeypatch)
    r = c.post("/api/setup/timezone", json={"timezone": "Australia/Sydney"})
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "Australia/Sydney"
    assert r.json()["offset_minutes"] in (600, 660)        # AEST or AEDT, whichever today is
    assert c.get("/api/setup/timezone").json()["timezone"] == "Australia/Sydney"


def test_an_unknown_zone_is_rejected_with_422(tmp_path, monkeypatch):
    c, st = _client(tmp_path, monkeypatch)
    r = c.post("/api/setup/timezone", json={"timezone": "Mars/Olympus_Mons"})
    assert r.status_code == 422
    assert setup_wizard.site_timezone(st) == ""            # nothing stored


def test_setting_the_zone_drops_the_cached_offsets(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(site_time, "reset_cache", lambda: calls.append(1))
    c.post("/api/setup/timezone", json={"timezone": "UTC"})
    assert calls, "offsets cached against the old zone would survive the change"


def test_mock_emulators_are_started_on_the_site_clock(tmp_path, monkeypatch):
    """The bridge owns the mock's clock, so here 'force the same timezone' is literal."""
    c, st = _client(tmp_path, monkeypatch)
    setup_wizard.set_site_timezone(st, "Australia/Adelaide")      # UTC+9:30 — a half-hour zone
    seen = {}

    def _fake_start(gw_id, *, seed, units, tz_offset_hours=None):
        seen[gw_id] = tz_offset_hours
        return "127.0.0.1:9999"
    monkeypatch.setattr(mockgw, "start_mock", _fake_start)
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)

    r = c.post("/api/gateways", json={"label": "Mock aGate 1", "is_mock": True,
                                      "enabled": True, "mock_units": 2})
    assert r.status_code == 201, r.text
    assert seen, "the mock was never started"
    off = next(iter(seen.values()))
    assert off in (9.5, 10.5)                  # Adelaide: ACST or ACDT, not the seeded zone


def test_mocks_without_a_site_timezone_keep_their_seeded_clock(tmp_path, monkeypatch):
    """Unset is not UTC. Nobody has said where the site is, so nothing is forced."""
    c, _ = _client(tmp_path, monkeypatch)
    seen = {}

    def _fake_start(gw_id, *, seed, units, tz_offset_hours=None):
        seen[gw_id] = tz_offset_hours
        return "127.0.0.1:9999"
    monkeypatch.setattr(mockgw, "start_mock", _fake_start)
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)

    c.post("/api/gateways", json={"label": "Mock aGate", "is_mock": True, "enabled": True})
    assert seen and next(iter(seen.values())) is None
