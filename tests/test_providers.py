"""HYBRID-CAPABILITIES Phase 1 (detection) + Phase 2 (dispatch actuation)."""

import pytest
from fastapi.testclient import TestClient

from franklinwh_local_bridge import app as app_module
from franklinwh_local_bridge import config, environment, providers
from franklinwh_local_bridge.config import Settings


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


def test_dispatch_prefers_reachable_modbus_bridge(monkeypatch):
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
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
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: False)  # sibling down
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
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: False)
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
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
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
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
    calls = []
    monkeypatch.setattr(providers, "_post_command",
                        lambda base, slug, value, **k: calls.append((slug, value)) or {})
    providers.dispatch(_s(modbus_bridge_url="http://mb:8101"), "release")
    assert calls == [("battery_command", "Release")]


def test_dispatch_pct_path(monkeypatch):
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
    calls = []
    monkeypatch.setattr(providers, "_post_command",
                        lambda base, slug, value, **k: calls.append((slug, value)) or {})
    providers.dispatch(_s(modbus_bridge_url="http://mb:8101"), "discharge", power_pct=50)
    assert calls == [("battery_command_power_pct", 50), ("battery_command", "Force Discharge")]


def test_dispatch_unavailable_raises(monkeypatch):
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: False)
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    try:
        providers.dispatch(_s(), "charge")
        assert False, "expected DispatchUnavailable"
    except providers.DispatchUnavailable:
        pass


def test_dispatch_invalid_action_raises(monkeypatch):
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
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


def test_dispatch_endpoint_503_no_provider(writes_on, monkeypatch):
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: False)
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    c = TestClient(app_module.create_app())
    r = c.post("/api/dispatch", json={"action": "release"})
    assert r.status_code == 503


def test_dispatch_endpoint_422_bad_action(writes_on, monkeypatch):
    monkeypatch.setenv("MODBUS_BRIDGE_URL", "http://mb:8101")
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
    config._settings = None  # re-read env with the sibling URL now set
    c = TestClient(app_module.create_app())
    r = c.post("/api/dispatch", json={"action": "explode"})
    assert r.status_code == 422


# ── Phase 3: reserve write (cloud-owned) ──────────────────────────────────────
def test_set_reserve_uses_cloud_lib(monkeypatch):
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    calls = {}
    monkeypatch.setattr(providers, "_cloud_set_reserve",
                        lambda email, pw, gw, wm, soc: calls.update(
                            email=email, gw=gw, wm=wm, soc=soc) or {"cloud": {"result": 0}, "prior": {"soc": 8}})
    out = providers.set_reserve(_s(fwh_cloud_email="a@b.c", fwh_cloud_password="x",
                                   fwh_cloud_gateway="GW1"), "self", 12)
    assert out["ok"] and out["mode"] == "self" and out["workMode"] == 2 and out["requested_soc"] == 12
    assert calls == {"email": "a@b.c", "gw": "GW1", "wm": 2, "soc": 12}  # Self → workMode 2


def test_set_reserve_maps_modes_by_name(monkeypatch):
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    seen = {}
    def _fake(email, pw, gw, wm, soc):
        seen["wm"] = wm
        return {"cloud": {}, "prior": None}
    monkeypatch.setattr(providers, "_cloud_set_reserve", _fake)
    providers.set_reserve(_s(fwh_cloud_email="a@b.c", fwh_cloud_password="x"), "tou", 20)
    assert seen["wm"] == 1  # TOU → workMode 1 (resolve by NAME, not index)


def test_set_reserve_bad_mode_and_soc(monkeypatch):
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    s = _s(fwh_cloud_email="a@b.c", fwh_cloud_password="x")
    for bad in ("explode", ""):
        try:
            providers.set_reserve(s, bad, 10); assert False
        except ValueError:
            pass
    for soc in (-1, 101):
        try:
            providers.set_reserve(s, "self", soc); assert False
        except ValueError:
            pass


def test_set_reserve_unavailable(monkeypatch):
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: False)
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    try:
        providers.set_reserve(_s(), "self", 10); assert False
    except providers.ReserveUnavailable:
        pass


def test_set_reserve_fwhai_only_not_wired(monkeypatch):
    # FWHAI reachable but no cloud lib/creds → the write path isn't wired.
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: True)
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    try:
        providers.set_reserve(_s(fwhai_url="http://fwhai:8099"), "self", 10); assert False
    except NotImplementedError:
        pass


def test_reserve_endpoint_gated_and_no_provider(writes_on, monkeypatch):
    monkeypatch.setattr(providers, "_probe_url", lambda base, *a, **k: False)
    monkeypatch.setattr(providers, "_lib_available", lambda m: False)
    c = TestClient(app_module.create_app())
    assert c.post("/api/cloud/reserve", json={"mode": "self", "soc": 10}).status_code == 503
    assert c.post("/api/cloud/reserve", json={"soc": 10}).status_code == 422  # missing mode

