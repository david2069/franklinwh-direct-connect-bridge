"""#457 phase 1: trusted networks. Upgrades trust any network; new installs trust the
private ranges and loopback; HA ingress and /api/live are always allowed."""
import logging

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, db, environment, security
from franklinwh_direct_connect_bridge.db import MetricsStore

LAN, OUTSIDE = ("192.168.1.20", 5000), ("203.0.113.9", 5000)


@pytest.fixture
def store(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


def _client(store, monkeypatch, addr=LAN):
    monkeypatch.setattr(db, "get_store", lambda s: store)
    return TestClient(app_module.create_app(), client=addr)


# ── upgrade or new install ─────────────────────────────────────────────────────
def test_an_existing_install_is_an_upgrade_and_trusts_any_network(store, monkeypatch):
    store.set_config("install_date", "2026-10-01")
    c = _client(store, monkeypatch, OUTSIDE)
    assert c.get("/api/summary").status_code != 403
    body = c.get("/api/security").json()
    assert body["install"] == "upgrade" and body["trusted_networks"] == ["any"]


def test_a_new_install_trusts_private_ranges_and_loopback_only(store, monkeypatch):
    lan = _client(store, monkeypatch, LAN)
    body = lan.get("/api/security").json()
    assert body["install"] == "new" and body["trusted_networks"] == security.PRIVATE
    assert body["your_address"] == "192.168.1.20"
    out = TestClient(lan.app, client=OUTSIDE)
    r = out.get("/api/summary")
    assert r.status_code == 403 and "not trusted" in r.json()["detail"]
    assert out.get("/").status_code == 403                  # pages too, not only the API
    assert out.get("/api/live").status_code == 200          # the watchdog always gets in


def test_the_decision_is_kept_across_restarts(store, monkeypatch):
    _client(store, monkeypatch)                              # first start: new
    c = _client(store, monkeypatch)                          # install_date now set
    assert c.get("/api/security").json()["install"] == "new"


# ── the rules ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("host,ok", [
    ("10.1.2.3", True), ("172.20.0.1", True), ("192.168.0.9", True), ("127.0.0.1", True),
    ("::1", True), ("fd00::5", True), ("::ffff:192.168.1.4", True),
    ("8.8.8.8", False), ("100.64.1.1", False), ("2001:db8::1", False),
    (None, True), ("testclient", True),        # no IP address: a Unix socket or local test
])
def test_private_ranges(host, ok):
    assert security.is_trusted(host, security.PRIVATE) is ok


def test_ha_ingress_is_always_allowed_on_the_add_on(monkeypatch):
    nets = ["192.168.5.0/24"]
    hdr = {"X-Ingress-Path": "/api/hassio_ingress/abc"}
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    assert security.allowed("172.30.32.2", "/api/summary", hdr, nets)
    assert not security.allowed("172.30.32.2", "/api/summary", {}, nets)    # no header
    assert not security.allowed("172.30.32.3", "/api/summary", hdr, nets)   # other address
    monkeypatch.setattr(environment, "IS_HA_ADDON", False)
    assert not security.allowed("172.30.32.2", "/api/summary", hdr, nets)   # not the add-on


def test_a_refusal_is_logged_once_per_address_per_10_minutes(caplog):
    security._last_logged.clear()
    with caplog.at_level(logging.WARNING, logger="franklinwh_direct_connect_bridge.security"):
        for t in (0, 10, 599):
            security.log_refused("203.0.113.9", "/api/x", now=1000 + t)
        security.log_refused("203.0.113.9", "/api/x", now=1000 + 600)
        security.log_refused("198.51.100.1", "/api/x", now=1001)
    lines = [r.getMessage() for r in caplog.records]
    assert sum("203.0.113.9" in m for m in lines) == 2 and sum("198.51.100.1" in m for m in lines) == 1
    assert "Settings → Admin → Security" in lines[0]


# ── saving the list ────────────────────────────────────────────────────────────
def test_save_normalises_and_refuses_bad_entries_and_lock_out(store, monkeypatch):
    c = _client(store, monkeypatch, LAN)
    r = c.put("/api/security/trusted-networks", json={"networks": ["192.168.1.7/24", "10.0.0.5", ""]})
    assert r.status_code == 200 and r.json()["trusted_networks"] == ["192.168.1.0/24", "10.0.0.5/32"]
    r = c.put("/api/security/trusted-networks", json={"networks": ["nope"]})
    assert r.status_code == 422 and "'nope' is not a network" in r.json()["detail"]
    r = c.put("/api/security/trusted-networks", json={"networks": ["10.0.0.0/8"]})
    assert r.status_code == 422 and "shut you out" in r.json()["detail"]
    assert c.get("/api/security").json()["trusted_networks"] == ["192.168.1.0/24", "10.0.0.5/32"]
    r = c.put("/api/security/trusted-networks", json={"networks": ["any"]})
    assert r.json()["trusted_networks"] == ["any"]
    assert TestClient(c.app, client=OUTSIDE).get("/api/summary").status_code != 403


def test_settings_admin_has_a_security_section():
    from pathlib import Path
    html = (Path(app_module.__file__).parent / "templates/tabs/settings.html").read_text()
    sec = html[html.index('data-testid="security-section"'):]
    for s in ('data-testid="trusted-networks"', "saveTrustedNetworks()", "dialog_msg('security.msg')",
              "Any network", "Your address"):
        assert s in sec, s
