"""Multi-gateway Phase 1 (reads/monitoring): config parse, registry, roster + summary
endpoints, and single-gateway parity of /api/summary."""

import pytest
from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module
from franklinwh_local_bridge import client as client_module
from franklinwh_local_bridge import state as state_module
from franklinwh_local_bridge.config import Settings, gateway_list


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with an empty registry (module-level) and leaves it empty."""
    state_module.reset_gateways()
    yield
    state_module.reset_gateways()


# -- config: fwh_hosts parsing --------------------------------------------------

def test_gateway_list_parses_hosts_and_labels():
    s = Settings(fwh_hosts="10.0.0.5=Home, 10.0.0.6=Shed")
    assert gateway_list(s) == [("10.0.0.5", "Home"), ("10.0.0.6", "Shed")]


def test_gateway_list_bare_host_labels_itself():
    s = Settings(fwh_hosts="10.0.0.5,10.0.0.6=Shed")
    assert gateway_list(s) == [("10.0.0.5", "10.0.0.5"), ("10.0.0.6", "Shed")]


def test_gateway_list_falls_back_to_fwh_host():
    s = Settings(fwh_host="10.0.0.9")
    assert gateway_list(s) == [("10.0.0.9", "10.0.0.9")]


def test_gateway_list_empty_when_nothing_set():
    assert gateway_list(Settings()) == []


# -- registry: register / get / default ----------------------------------------

def test_registry_register_get_default_order():
    a = state_module.register_gateway("10.0.0.5", "10.0.0.5", "Home")
    b = state_module.register_gateway("10.0.0.6", "10.0.0.6", "Shed")
    assert state_module.get_gateway("10.0.0.5") is a
    assert state_module.register_gateway("10.0.0.5", "10.0.0.5", "Home") is a  # idempotent
    assert state_module.gateways() == [a, b]                                   # insertion order
    assert state_module.default_gateway() is a                                 # first


def test_get_state_lazily_creates_default_when_empty():
    assert state_module.default_gateway() is None
    gw = state_module.get_state()
    assert gw is state_module.default_gateway()   # now registered


# -- /api/gateways roster + /api/gateways/{id}/summary -------------------------

def _seed_two_gateways():
    a = state_module.register_gateway("10.0.0.5", "10.0.0.5", "Home")
    a.serial, a.active_host = "SN-A", "10.0.0.55"
    a.last_summary = {"ok": True, "power": {"soc": 61, "mode": "Self-Consumption"},
                      "firmware": {"IBG_VER": "1.2.3", "IBG_SN": "SN-A"}}
    b = state_module.register_gateway("10.0.0.6", "10.0.0.6", "Shed")
    b.serial = "SN-B"
    b.last_summary = {"ok": True, "power": {"soc": 88, "mode": "Time-of-Use"},
                      "firmware": {"IBG_VER": "1.2.3", "IBG_SN": "SN-B"}}
    return a, b


def test_api_gateways_roster_shape():
    _seed_two_gateways()
    c = TestClient(app_module.create_app())
    rows = c.get("/api/gateways").json()
    assert [r["id"] for r in rows] == ["10.0.0.5", "10.0.0.6"]
    home = rows[0]
    assert home["label"] == "Home"
    assert home["host"] == "10.0.0.55"           # active_host (re-discovered) wins
    assert home["configured_host"] == "10.0.0.5"
    assert home["serial"] == "SN-A"
    assert home["firmware"] == "1.2.3"
    assert home["ok"] is True and home["stale"] is False
    assert home["soc"] == 61 and home["mode"] == "Self-Consumption"
    assert home["cached"] is True and home["updated"] is True
    assert {r["serial"] for r in rows} == {"SN-A", "SN-B"}   # distinct sites


def test_api_gateways_cold_cache_is_not_ok():
    state_module.register_gateway("10.0.0.5", "10.0.0.5", "Home")   # no last_summary
    c = TestClient(app_module.create_app())
    row = c.get("/api/gateways").json()[0]
    assert row["ok"] is False and row["soc"] is None
    assert row["cached"] is False and row["updated"] is False


def test_api_gateway_summary_cached_and_404(monkeypatch):
    _seed_two_gateways()

    def boom(s, host=None):
        raise AssertionError("must serve the cache, not read the device")

    monkeypatch.setattr(client_module, "summary", boom)
    c = TestClient(app_module.create_app())
    body = c.get("/api/gateways/10.0.0.5/summary").json()   # warm cache
    assert body["cached"] is True and body["power"]["soc"] == 61
    assert c.get("/api/gateways/nope/summary").status_code == 404   # unknown id


def test_api_gateway_summary_falls_back_to_device_when_cold(monkeypatch):
    state_module.register_gateway("10.0.0.5", "10.0.0.5", "Home")   # cold
    seen = {}

    def fake_summary(s, host=None):
        seen["host"] = host
        return {"ok": True, "power": {"soc": 42}, "fresh": True}

    monkeypatch.setattr(client_module, "summary", fake_summary)
    c = TestClient(app_module.create_app())
    body = c.get("/api/gateways/10.0.0.5/summary").json()
    assert body.get("fresh") is True and seen["host"] == "10.0.0.5"


# -- single-gateway parity: /api/summary unchanged -----------------------------

def test_single_gateway_summary_unchanged(monkeypatch):
    """With only the default gateway and a warm cache, /api/summary serves the default
    gateway's cache exactly as before (cached:True)."""
    gw = state_module.get_state()   # lazily creates the default
    gw.last_summary = {"ok": True, "power": {"soc": 55}, "mode": {"modes": []}}

    def boom(s, host=None):
        raise AssertionError("client.summary must not be called when the cache is warm")

    monkeypatch.setattr(client_module, "summary", boom)
    c = TestClient(app_module.create_app())
    body = c.get("/api/summary").json()
    assert body["cached"] is True and body["power"]["soc"] == 55
    # single-gateway roster is exactly one entry
    assert len(c.get("/api/gateways").json()) == 1


# -- Phase 2: gateway-scoped reads / writes route to the right host -------------

def test_read_routes_to_selected_and_default_host(monkeypatch):
    """A read with ?gateway=<id> must hit THAT gateway's active_host; no param hits the
    default's active_host (single-gateway back-compat)."""
    a, b = _seed_two_gateways()   # a active_host=10.0.0.55 (default), b active_host=10.0.0.6
    seen = {}

    def fake_power(s, host=None):
        seen["host"] = host
        return {"soc": 1, "p_load": 0}

    monkeypatch.setattr(client_module, "power", fake_power)
    c = TestClient(app_module.create_app())

    assert c.get("/api/power?gateway=10.0.0.6").status_code == 200
    assert seen["host"] == "10.0.0.6"                 # selected gateway's host
    assert c.get("/api/power").status_code == 200
    assert seen["host"] == "10.0.0.55"               # default gateway's active_host


def test_cmd_read_routes_via_read_host(monkeypatch):
    """/api/cmd/<name> threads the selected gateway host into client.read."""
    _seed_two_gateways()
    seen = {}

    def fake_read(s, name, host=None):
        seen["name"], seen["host"] = name, host
        return {"ok": True}

    # The /api/cmd handler now uses read_with_request so it can report the frame
    # it actually sent (X-FWH-Request); patch both to keep the host assertion honest.
    monkeypatch.setattr(client_module, "read", fake_read)
    monkeypatch.setattr(client_module, "read_with_request",
                        lambda s, name, host=None: (fake_read(s, name, host=host), None))
    c = TestClient(app_module.create_app())
    assert c.get("/api/cmd/power_flow?gateway=10.0.0.6").status_code == 200
    assert seen == {"name": "power_flow", "host": "10.0.0.6"}


def test_read_unknown_gateway_is_404(monkeypatch):
    _seed_two_gateways()
    monkeypatch.setattr(client_module, "power", lambda s, host=None: {"soc": 1})
    c = TestClient(app_module.create_app())
    assert c.get("/api/power?gateway=nope").status_code == 404
    assert c.get("/api/cmd/power_flow?gateway=nope").status_code == 404


def test_write_routes_to_selected_host(monkeypatch):
    """SAFETY: /api/mode?gateway=<id> must write to the SELECTED gateway's host, not the
    default — a user who selects 'Shed' must never actuate 'Home'."""
    _seed_two_gateways()
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    seen = {}

    def fake_set_mode(s, mode, host=None):
        seen["mode"], seen["host"] = mode, host
        return {"ok": True, "result": 0}

    monkeypatch.setattr(client_module, "set_mode", fake_set_mode)
    c = TestClient(app_module.create_app())
    r = c.post("/api/mode?gateway=10.0.0.6", json={"mode": "tou", "confirm": True})
    assert r.status_code == 200 and seen["host"] == "10.0.0.6" and seen["mode"] == "tou"


def test_site_status_aggregates_over_ok_gateways(monkeypatch):
    a, b = _seed_two_gateways()
    a.last_summary["power"].update({"grid_w": 100, "solar_w": 200, "battery_w": -50,
                                    "load_w": 250, "generator_w": 0})
    b.last_summary["power"].update({"grid_w": 10, "solar_w": 20, "battery_w": 5,
                                    "load_w": 35, "generator_w": 0})
    c = TestClient(app_module.create_app())
    site = c.get("/api/site/status").json()
    assert site["count"] == 2 and site["ok_count"] == 2
    assert site["totals"] == {"grid_w": 110, "solar_w": 220, "battery_w": -45,
                              "load_w": 285, "generator_w": 0}
    assert [g["id"] for g in site["gateways"]] == ["10.0.0.5", "10.0.0.6"]


def test_site_status_skips_cold_gateways_and_never_500s():
    a, b = _seed_two_gateways()
    b.last_summary = {}   # cold cache → not counted, contributes nothing
    a.last_summary["power"].update({"grid_w": 100, "solar_w": 0, "battery_w": 0,
                                    "load_w": 100, "generator_w": 0})
    c = TestClient(app_module.create_app())
    site = c.get("/api/site/status").json()
    assert site["count"] == 2 and site["ok_count"] == 1
    assert site["totals"]["grid_w"] == 100


def test_mqtt_republish_targets_selected_gateway(monkeypatch):
    a, b = _seed_two_gateways()
    monkeypatch.setattr(app_module, "get_settings",
                        lambda: Settings(mqtt_enabled=True))
    c = TestClient(app_module.create_app())
    r = c.post("/api/mqtt/republish?gateway=10.0.0.6")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert b.republish_requested is True and a.republish_requested is False


def test_mqtt_config_and_entities_scope_to_gateway():
    a, b = _seed_two_gateways()
    a.mqtt_connected, b.mqtt_connected = True, False
    a.node, b.node = "sn-a", "sn-b"
    c = TestClient(app_module.create_app())
    assert c.get("/api/mqtt/config?gateway=10.0.0.5").json()["connected"] is True
    assert c.get("/api/mqtt/config?gateway=10.0.0.6").json()["connected"] is False
    ents = c.get("/api/mqtt/entities?gateway=10.0.0.6").json()
    assert ents["node"] == "sn-b" and ents["publishing"] is False
    assert ents["entities"] and all("sn-b" in e["state_topic"] for e in ents["entities"])
