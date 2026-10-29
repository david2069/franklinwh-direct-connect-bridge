"""#379 — a serial given to a cloud setting or call is validated like ?gateway=: it must be
locked to one of this bridge's gateways (#381). Cloud calls for a gateway use its own serial,
never the configured one on its behalf, and nothing falls back to the default gateway."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, cloud_status, config, environment, state


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    config._settings = None
    config.save_override("allow_writes", True)
    mine = state.GatewayState(id="gw-a", label="A", configured_host="192.0.2.1",
                              active_host="192.0.2.1", serial="SNMINE", serial_locked=True)
    seen = state.GatewayState(id="gw-b", label="B", configured_host="192.0.2.2",
                              active_host="192.0.2.2", serial="SNSEEN")      # never locked
    monkeypatch.setitem(state._gateways, "gw-a", mine)
    monkeypatch.setitem(state._gateways, "gw-b", seen)
    signins = []
    monkeypatch.setattr(cloud_status, "verify_credentials",
                        lambda e, p, g: signins.append(g) or {"ok": True, "gateway": g or "SNOTHER",
                                                               "gateways": [g or "SNOTHER"]})
    yield TestClient(app_module.create_app()), signins
    config._settings = None


@pytest.mark.parametrize("serial,code", [("SNNOPE", 404), ("SNSEEN", 404), ("bad serial;", 422)])
def test_setup_cloud_refuses_a_serial_that_is_not_ours_before_signing_in(api, serial, code):
    c, signins = api
    r = c.post("/api/setup/cloud", json={"email": "a@b.c", "password": "x", "gateway": serial})
    assert r.status_code == code and signins == []


def test_setup_cloud_signs_in_for_one_of_ours(api):
    c, signins = api
    r = c.post("/api/setup/cloud", json={"email": "a@b.c", "password": "x",
                                         "gateway": "snmine", "save": False})
    assert r.status_code == 200 and r.json()["ok"] and signins == ["SNMINE"]


def test_the_accounts_only_agate_must_be_one_of_ours_too(api):
    c, signins = api
    r = c.post("/api/setup/cloud", json={"email": "a@b.c", "password": "x"})
    d = r.json()
    assert d["ok"] is False and d["saved"] is False and "SNOTHER" in d["detail"]
    assert config.get_settings().fwh_cloud_gateway in (None, "")


@pytest.mark.parametrize("serial,code", [("SNNOPE", 404), ("bad serial;", 422)])
def test_the_cloud_serial_setting_is_validated(api, serial, code):
    c, _ = api
    r = c.put("/api/settings", json={"fwh_cloud_gateway": serial})
    assert r.status_code == code
    assert config.get_settings().fwh_cloud_gateway in (None, "")
    assert c.put("/api/settings", json={"fwh_cloud_gateway": "snmine"}).status_code == 200
    assert config.get_settings().fwh_cloud_gateway == "SNMINE"
    assert c.put("/api/settings", json={"fwh_cloud_gateway": ""}).status_code == 200   # cleared


def test_the_grid_limit_witness_reads_this_gateways_serial_only(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(config.get_settings(), "fwh_cloud_email", "a@b.c")
    monkeypatch.setattr(config.get_settings(), "fwh_cloud_password", "x")
    monkeypatch.setattr(config.get_settings(), "fwh_cloud_gateway", "SNMINE")
    read = []
    monkeypatch.setattr(cloud_status, "read_power_control",
                        lambda e, p, serial: read.append(serial) or {"ok": 1})
    from franklinwh_direct_connect_bridge import client
    monkeypatch.setattr(client, "set_grid_limits", lambda *a, **k: {"ok": True, "dry_run": True})
    for gw, expect in (("gw-a", ["SNMINE"]), ("gw-b", [])):
        read.clear()
        r = c.post(f"/api/grid/limits?gateway={gw}", json={"grid_soft_limit": 5, "dry_run": True})
        assert read == expect, (gw, r.status_code, r.text[:200])


def test_a_serial_names_a_gateway_only_once_it_is_locked(monkeypatch):
    locked = state.GatewayState(id="gw-l", serial="SNL", serial_locked=True)
    seen = state.GatewayState(id="gw-s", serial="SNS")
    monkeypatch.setitem(state._gateways, "gw-l", locked)
    monkeypatch.setitem(state._gateways, "gw-s", seen)
    assert state.gateway_by_serial("snl") is locked
    assert state.gateway_by_serial("SNS") is None and state.gateway_by_serial("") is None


def test_the_cloud_status_worker_never_lands_on_the_default_gateway():
    import inspect
    src = inspect.getsource(app_module.create_app)
    body = src[src.index("data = cloud_status.poll(get_settings())"):]
    body = body[:body.index("target.cloud_ts")]
    assert "state.gateway_by_serial(want)" in body and "default_gateway()" not in body
