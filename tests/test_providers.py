"""HYBRID-CAPABILITIES Phase 1 (detection) + Phase 2 (dispatch actuation)."""

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import config, environment, providers, state
from franklinwh_direct_connect_bridge.config import Settings


def _s(**kw):
    return Settings(**kw)


@pytest.fixture
def writes_on(tmp_path, monkeypatch):
    """Isolate the overrides file + config singleton, with allow_writes enabled — so the
    gated /api/dispatch endpoint is reachable in the endpoint tests below."""
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    config._settings = None
    config.save_override("allow_writes", True)
    yield tmp_path
    config._settings = None


@pytest.fixture
def gw():
    """The gateway a device route names (#379)."""
    state.register_gateway("gw-prov", "10.0.0.1", "Home")
    yield "gw-prov"
    state.unregister_gateway("gw-prov")


def test_dispatch_prefers_reachable_modbus_bridge(monkeypatch):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "ready", "reason": None,
                                         "capabilities": ["control"]})
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    r = providers.dispatch_provider(_s(modbus_bridge_url="http://mb:8101", modbus_host="10.0.0.9"))
    assert r["available"] is True
    assert r["active"]["kind"] == "modbus-bridge" and r["active"]["via"] == "rest"


def test_dispatch_falls_back_to_library(monkeypatch):
    # No sibling URL; library present + an aGate host → modbus-lib.
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    r = providers.dispatch_provider(_s(modbus_host="10.0.0.9"))
    assert r["available"] is True and r["active"]["kind"] == "modbus-lib"


def test_dispatch_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    r = providers.dispatch_provider(_s())  # no url, no lib, no host
    assert r["available"] is False and r["active"] is None
    assert r["candidates"][-1]["reason"]  # explains why the lib candidate is unavailable


def test_dispatch_url_unreachable_not_available(monkeypatch):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "unreachable",
                                         "reason": "sibling down", "capabilities": []})
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    r = providers.dispatch_provider(_s(modbus_bridge_url="http://mb:8101"))
    assert r["available"] is False
    assert r["candidates"][0]["kind"] == "modbus-bridge" and r["candidates"][0]["available"] is False


def test_reserve_prefers_fwhai_then_cloud_lib(monkeypatch):
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    r = providers.reserve_provider(_s(fwhai_url="http://fwhai:8099"))
    assert r["active"]["kind"] == "fwhai"
    # no fwhai, but cloud lib + creds → cloud-lib
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: False)
    r2 = providers.reserve_provider(_s(fwh_cloud_email="a@b.c", fwh_cloud_password="x"))
    assert r2["active"]["kind"] == "cloud-lib"


def test_capabilities_and_endpoint(monkeypatch):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "unreachable",
                                         "reason": "sibling down", "capabilities": []})
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    caps = providers.capabilities(_s())
    assert set(caps) == {"dispatch", "reserve"}
    c = TestClient(app_module.create_app())
    body = c.get("/api/providers").json()
    assert body["dispatch"]["capability"] == "dispatch"
    assert body["reserve"]["available"] is False


# ── Phase 2: dispatch (actuate) ───────────────────────────────────────────────
def test_dispatch_sequences_modbus_bridge_commands(monkeypatch):
    """A force-charge with staged params must POST power → duration → target-SoC, then the
    action LAST (the Bridge command model is stateful)."""
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "ready", "reason": None,
                                         "capabilities": ["control"]})
    calls = []
    monkeypatch.setattr(providers, "_post_command",
                        lambda base, slug, value, **k: calls.append((slug, value)) or {"ok": True})
    out = providers.dispatch(_s(modbus_bridge_url="http://mb:8101"), "charge",
                             power_w=5000, duration_s=1800, target_soc=90)
    assert out["ok"] is True and out["action"] == "charge"
    assert out["provider"]["kind"] == "modbus-bridge"
    assert calls == [
        ("battery_command_power", 5000),
        ("battery_command_duration", 1800),
        ("battery_command_target_soc", 90),
        ("battery_command", "Force Charge"),
    ]


def test_dispatch_release_is_bare_action(monkeypatch):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "ready", "reason": None,
                                         "capabilities": ["control"]})
    calls = []
    monkeypatch.setattr(providers, "_post_command",
                        lambda base, slug, value, **k: calls.append((slug, value)) or {})
    providers.dispatch(_s(modbus_bridge_url="http://mb:8101"), "release")
    assert calls == [("battery_command", "Release")]


def test_dispatch_pct_path(monkeypatch):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "ready", "reason": None,
                                         "capabilities": ["control"]})
    calls = []
    monkeypatch.setattr(providers, "_post_command",
                        lambda base, slug, value, **k: calls.append((slug, value)) or {})
    providers.dispatch(_s(modbus_bridge_url="http://mb:8101"), "discharge", power_pct=50)
    assert calls == [("battery_command_power_pct", 50), ("battery_command", "Force Discharge")]


def test_dispatch_unavailable_raises(monkeypatch):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "unreachable",
                                         "reason": "sibling down", "capabilities": []})
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    try:
        providers.dispatch(_s(), "charge")
        assert False, "expected DispatchUnavailable"
    except providers.DispatchUnavailable:
        pass


def test_dispatch_invalid_action_raises(monkeypatch):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "ready", "reason": None,
                                         "capabilities": ["control"]})
    try:
        providers.dispatch(_s(modbus_bridge_url="http://mb:8101"), "explode")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_dispatch_library_path_not_wired(monkeypatch):
    """No sibling URL, but library + host → resolves modbus-lib, which must refuse (no
    watchdog). It should raise NotImplementedError, not silently no-op."""
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    try:
        providers.dispatch(_s(modbus_host="10.0.0.9"), "charge")
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass


def test_dispatch_endpoint_503_no_provider(writes_on, monkeypatch, gw):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "unreachable",
                                         "reason": "sibling down", "capabilities": []})
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    c = TestClient(app_module.create_app())
    r = c.post("/api/dispatch", json={"action": "release", "gateway_id": gw})
    assert r.status_code == 503


def test_dispatch_endpoint_422_bad_action(writes_on, monkeypatch, gw):
    monkeypatch.setenv("MODBUS_BRIDGE_URL", "http://mb:8101")
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "ready", "reason": None,
                                         "capabilities": ["control"]})
    config._settings = None  # re-read env with the sibling URL now set
    c = TestClient(app_module.create_app())
    r = c.post("/api/dispatch", json={"action": "explode", "gateway_id": gw})
    assert r.status_code == 422


# ── Phase 3: reserve write (cloud-owned) ──────────────────────────────────────
def test_set_reserve_uses_cloud_lib(monkeypatch):
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    calls = {}
    monkeypatch.setattr(providers, "_cloud_set_reserve",
                        lambda email, pw, gw, wm, soc: calls.update(
                            email=email, gw=gw, wm=wm, soc=soc) or {"cloud": {"result": 0}, "prior": {"soc": 8}})
    out = providers.set_reserve(_s(fwh_cloud_email="a@b.c", fwh_cloud_password="x",
                                   fwh_cloud_gateway="GW1"), "self", 12, serial="GW1")
    assert out["ok"] and out["mode"] == "self" and out["workMode"] == 2 and out["requested_soc"] == 12
    assert calls == {"email": "a@b.c", "gw": "GW1", "wm": 2, "soc": 12}  # Self → workMode 2


def test_set_reserve_maps_modes_by_name(monkeypatch):
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    seen = {}
    def _fake(email, pw, gw, wm, soc):
        seen["wm"] = wm
        return {"cloud": {}, "prior": None}
    monkeypatch.setattr(providers, "_cloud_set_reserve", _fake)
    providers.set_reserve(_s(fwh_cloud_email="a@b.c", fwh_cloud_password="x"), "tou", 20, serial="SN1")
    assert seen["wm"] == 1  # TOU → workMode 1 (resolve by NAME, not index)


def test_set_reserve_bad_mode_and_soc(monkeypatch):
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    s = _s(fwh_cloud_email="a@b.c", fwh_cloud_password="x")
    for bad in ("explode", ""):
        try:
            providers.set_reserve(s, bad, 10, serial="SN1"); assert False
        except ValueError:
            pass
    for soc in (-1, 101):
        try:
            providers.set_reserve(s, "self", soc, serial="SN1"); assert False
        except ValueError:
            pass


def test_set_reserve_unavailable(monkeypatch):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "unreachable",
                                         "reason": "sibling down", "capabilities": []})
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    try:
        providers.set_reserve(_s(), "self", 10, serial="SN1"); assert False
    except providers.ReserveUnavailable:
        pass


def test_set_reserve_fwhai_only_not_wired(monkeypatch):
    # FWHAI reachable but no cloud lib/creds → the write path isn't wired.
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    try:
        providers.set_reserve(_s(fwhai_url="http://fwhai:8099"), "self", 10, serial="SN1"); assert False
    except NotImplementedError:
        pass


def test_reserve_endpoint_gated_and_no_provider(writes_on, monkeypatch, gw):
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "unreachable",
                                         "reason": "sibling down", "capabilities": []})
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    # Cloud sign-in checked and good, so the answer is about the provider, not the sign-in
    # (it used to depend on an earlier test leaving that state behind).
    real = providers.cloud_auth_status
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {**real(), "state": "valid"})
    c = TestClient(app_module.create_app())
    assert c.post(f"/api/cloud/reserve?gateway={gw}", json={"mode": "self", "soc": 10}).status_code == 503
    assert c.post(f"/api/cloud/reserve?gateway={gw}", json={"soc": 10}).status_code == 422  # missing mode



def test_set_reserve_needs_the_gateways_serial(monkeypatch):
    """There is no configured-gateway fallback any more (#379), and no sign-in without one."""
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    monkeypatch.setattr(providers, "_cloud_set_reserve",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("signed in")))
    s = _s(fwh_cloud_email="a@b.c", fwh_cloud_password="x", fwh_cloud_gateway="SNCFG")
    for blank in ("", "  "):
        try:
            providers.set_reserve(s, "self", 10, serial=blank); assert False
        except ValueError as e:
            assert "serial" in str(e)


# ── #365: a named gateway the Modbus Bridge cannot address is refused ────────
def test_dispatch_refuses_a_gateway_the_bridge_cannot_target(monkeypatch):
    """#365: the Modbus Bridge's /api/command has no gateway selector and this bridge
    cannot verify which aGate it polls. Naming a different gateway must be refused, not
    silently dispatched to the wrong battery."""
    from types import SimpleNamespace

    from franklinwh_direct_connect_bridge import state as state_mod

    def _must_not_probe(*a, **k):
        raise AssertionError("a refused gateway must not sign in to the Bridge")

    monkeypatch.setattr(providers.modbus_bridge, "status", _must_not_probe)
    monkeypatch.setattr(state_mod, "default_gateway",
                        lambda: SimpleNamespace(id="gw-a"))

    def _must_not_dispatch(*a, **k):
        raise AssertionError("a refused gateway must not reach the Bridge")

    monkeypatch.setattr(providers, "_post_command", _must_not_dispatch)

    with pytest.raises(providers.GatewayNotTargetable) as exc:
        providers.dispatch(_s(modbus_bridge_url="http://mb:8101"), "charge", gateway_id="gw-b")
    assert "gw-b" in str(exc.value) and "gw-a" in str(exc.value)


def test_dispatch_default_gateway_is_honoured_and_echoed(monkeypatch):
    from types import SimpleNamespace

    from franklinwh_direct_connect_bridge import state as state_mod

    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "ready", "reason": None,
                                         "capabilities": ["control"]})
    monkeypatch.setattr(state_mod, "default_gateway",
                        lambda: SimpleNamespace(id="gw-a"))
    monkeypatch.setattr(providers, "_post_command",
                        lambda base, slug, value, **k: {"ok": True})
    out = providers.dispatch(_s(modbus_bridge_url="http://mb:8101"), "release",
                             gateway_id="gw-a")
    assert out["ok"] is True and out["gateway_id"] == "gw-a"


@pytest.fixture
def two_gateways():
    """gw-a (the stored default) and gw-b, registered for the endpoint contract test."""
    state.register_gateway("gw-a", "10.0.0.11", "A")
    state.register_gateway("gw-b", "10.0.0.12", "B")
    state.set_default("gw-a")
    yield ("gw-a", "gw-b")
    state.set_default(None)
    state.unregister_gateway("gw-a")
    state.unregister_gateway("gw-b")


def test_dispatch_endpoint_refuses_the_wrong_gateway_before_provider_io(
        writes_on, monkeypatch, two_gateways):
    """#365 (endpoint contract): 409, and before the provider probe signs in to the Bridge.
    gateway_id is required since #385, so the request names gw-b explicitly."""
    def _must_not_probe(*a, **k):
        raise AssertionError("a refused gateway must not sign in to the Bridge")

    monkeypatch.setattr(providers.modbus_bridge, "status", _must_not_probe)
    monkeypatch.setenv("MODBUS_BRIDGE_URL", "http://mb:8101")
    config._settings = None

    c = TestClient(app_module.create_app())
    r = c.post("/api/dispatch", json={"action": "charge", "gateway_id": "gw-b"})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "gw-b" in detail and "gw-a" in detail


def test_dispatch_endpoint_dispatches_the_default_gateway(
        writes_on, monkeypatch, two_gateways):
    """The other case stands: naming the stored default is dispatched and echoed."""
    monkeypatch.setattr(providers.modbus_bridge, "status",
                        lambda *a, **k: {"state": "ready", "reason": None,
                                         "capabilities": ["control"]})
    calls = []
    monkeypatch.setattr(providers, "_post_command",
                        lambda base, slug, value, **k:
                        calls.append((slug, value)) or {"ok": True})
    monkeypatch.setenv("MODBUS_BRIDGE_URL", "http://mb:8101")
    config._settings = None

    c = TestClient(app_module.create_app())
    r = c.post("/api/dispatch", json={"action": "release", "gateway_id": "gw-a"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["gateway_id"] == "gw-a"
    assert calls == [("battery_command", "Release")]
