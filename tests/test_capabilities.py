"""Cloud features exist only while the cloud is connected."""
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import providers
from franklinwh_direct_connect_bridge.app import create_app


def test_local_features_are_always_available():
    """Mode switching is the baseline battery operation and needs no cloud."""
    caps = TestClient(create_app()).get("/api/capabilities").json()
    assert caps["local"]["set_mode"] is True
    assert caps["local"]["smart_circuit_switch"] is True


def test_cloud_features_follow_the_auth_state(monkeypatch):
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "unconfigured"})
    caps = TestClient(create_app()).get("/api/capabilities").json()
    assert caps["cloud"]["connected"] is False
    assert caps["cloud"]["reserve_soc"] is False
    assert "No cloud credentials" in caps["cloud"]["reason"]

    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "valid"})
    caps = TestClient(create_app()).get("/api/capabilities").json()
    assert caps["cloud"]["connected"] is True and caps["cloud"]["reserve_soc"] is True
    assert caps["cloud"]["reason"] is None


def test_what_is_impossible_locally_is_stated_with_the_evidence():
    """Probed, not assumed — each entry names how it was established."""
    caps = TestClient(create_app()).get("/api/capabilities").json()
    u = caps["unavailable_locally"]
    assert "discard" in u["reserve_soc"] and "discard" in u["tou_schedule"]
    assert "no dispatchId" in u["force_charge_discharge"]


def test_cloud_write_refused_with_a_clear_reason_when_not_connected(monkeypatch):
    """A missing credential must read as 'not connected', not a transport error."""
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "unconfigured"})
    r = TestClient(create_app()).post("/api/cloud/reserve", json={"mode": "self", "soc": 20})
    assert r.status_code == 503
    assert "Cloud not connected" in r.json()["detail"]


def test_locked_state_explains_how_to_clear_it(monkeypatch):
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "writes_enabled", lambda s: True)
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "locked"})
    r = TestClient(create_app()).post("/api/cloud/reserve", json={"mode": "self", "soc": 20})
    assert "re-enter the credentials" in r.json()["detail"]


def test_settings_exposes_cloud_credentials_with_a_test_button():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/settings.html").read_text()
    assert "FranklinWH Cloud API" in html
    assert "testCloud()" in html
    assert "fwh_cloud_password" in html
    # the password must never be echoed back into the field
    assert "leave blank to keep" in html
