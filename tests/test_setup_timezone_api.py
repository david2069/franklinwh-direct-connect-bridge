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


# --- a mock must not reach Home Assistant ----------------------------------------------------
# 2026-10-15: the setup wizard created mocks on a LIVE bridge with publish_ha defaulting to
# True, so three fake FranklinWH devices were published to the owner's Home Assistant —
# complete with energy sensors that accrue long-term statistics.

def test_a_mock_does_not_publish_to_home_assistant_by_default(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(mockgw, "start_mock",
                        lambda gid, *, seed, units, tz_offset_hours=None: "127.0.0.1:9999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    r = c.post("/api/gateways", json={"label": "Mock aGate 1", "is_mock": True,
                                      "enabled": True})
    assert r.status_code == 201, r.text
    assert r.json()["publish_ha"] is False


def test_a_real_gateway_still_publishes_by_default(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    r = c.post("/api/gateways", json={"label": "aGate", "host": "192.0.2.110",
                                      "enabled": True})
    assert r.status_code == 201, r.text
    assert r.json()["publish_ha"] is True


def test_publishing_a_mock_is_possible_when_asked_for(tmp_path, monkeypatch):
    """Explicit is explicit — this is a default, not a prohibition."""
    c, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(mockgw, "start_mock",
                        lambda gid, *, seed, units, tz_offset_hours=None: "127.0.0.1:9999")
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    r = c.post("/api/gateways", json={"label": "Mock", "is_mock": True, "enabled": True,
                                      "publish_ha": True})
    assert r.json()["publish_ha"] is True


# --- optional cloud credentials --------------------------------------------------------------
# Owner, 2026-10-15: offer the FranklinWH app account in the wizard, test it, and say why we
# want it. The "test it" part is the point — storing an unverified password means finding
# out months later that a reserve write has been failing.

def test_bad_credentials_are_not_stored(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import cloud_status
    c, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(cloud_status, "verify_credentials",
                        lambda e, p, g=None: {"ok": False, "detail": "AuthError: nope"})
    saved = []
    monkeypatch.setattr(app_module, "save_override", lambda k, v: saved.append(k))
    r = c.post("/api/setup/cloud", json={"email": "a@example.com", "password": "wrong"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["saved"] is False
    assert saved == []                       # nothing written
    assert "nope" in body["detail"]          # the real reason, not a generic failure


def test_good_credentials_are_stored_once_proven(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import cloud_status
    c, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(cloud_status, "verify_credentials",
                        lambda e, p, g=None: {"ok": True, "detail": "Signed in.",
                                              "gateways": ["SN1"]})
    saved = {}
    monkeypatch.setattr(app_module, "save_override", lambda k, v: saved.__setitem__(k, v))
    r = c.post("/api/setup/cloud", json={"email": "a@example.com", "password": "right"})
    body = r.json()
    assert body["ok"] is True and body["saved"] is True
    assert saved["fwh_cloud_email"] == "a@example.com"
    assert saved["fwh_cloud_password"] == "right"


def test_the_password_is_never_echoed_back(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge import cloud_status
    c, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(cloud_status, "verify_credentials",
                        lambda e, p, g=None: {"ok": True, "detail": "Signed in."})
    monkeypatch.setattr(app_module, "save_override", lambda k, v: None)
    r = c.post("/api/setup/cloud", json={"email": "a@example.com", "password": "s3cret"})
    assert "s3cret" not in r.text


def test_verify_credentials_never_raises():
    """A wrong password, an unreachable cloud and a missing library are all ANSWERS."""
    from franklinwh_direct_connect_bridge import cloud_status
    assert cloud_status.verify_credentials("", "")["ok"] is False
    out = cloud_status.verify_credentials("a@example.com", "definitely-not-a-password")
    assert out["ok"] is False and out["detail"]
