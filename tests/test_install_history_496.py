"""#496 — history is evidence: power that has flowed through a path proves the path exists.
The metrics store's per-gateway samples (kept up to a year) and the V2L lifetime meter add a
"Your history" line to each fact, and make a generator or V2L that has carried power
"Installed"."""
import pytest

from franklinwh_direct_connect_bridge import client as client_mod
from franklinwh_direct_connect_bridge import install_profile as ip
from franklinwh_direct_connect_bridge import system_setup as ss
from franklinwh_direct_connect_bridge.db import MetricsStore

DAY = 86400
T0 = 1_780_000_000


@pytest.fixture
def store(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


def test_power_history_peaks_and_last_seen(store):
    store.insert({"solar_w": 5800, "grid_w": -300, "generator_w": 0, "battery_w": 2000}, T0,
                 gateway_id="g")
    store.insert({"solar_w": 20, "grid_w": 0, "generator_w": 4200}, T0 + DAY, gateway_id="g")
    store.insert({"solar_w": 9000}, T0, gateway_id="other")
    h = store.power_history("g", since=T0 - DAY)
    assert h["solar"] == {"peak_w": 5800.0, "last_ts": T0}          # 20 W is noise
    assert h["generator"] == {"peak_w": 4200.0, "last_ts": T0 + DAY}
    assert h["grid"]["last_ts"] == T0
    assert h["first_ts"] == T0
    assert store.power_history("g", since=T0 + 2 * DAY)["solar"] is None


def _values(**kw):
    base = {k: v["default"] for k, v in ss._FIELDS.items()}
    base.update({"_sources": {}, "_confirmed": {}, "_derived": {}, "_overridden": {}})
    base.update(kw)
    return base


INFO = {"model": "aGate X-01-AU", "country": "AU", "apower_count": 1}


def _facts(values, history):
    card = ip.card("g", "G", INFO, values, modes=[], off_grid=False, history=history)
    return {f["key"]: f for f in card["facts"]}


def test_history_lines_on_the_facts():
    hist = {"first_ts": T0, "solar": {"peak_w": 5800.0, "last_ts": T0},
            "generator": None, "grid": {"peak_w": 3000.0, "last_ts": T0}, "battery": None}
    f = _facts(_values(solar_type="ac", solar_kwp=6.6), hist)
    assert "Your history" in f["solar"]["source"] and "5.8 kW" in f["solar"]["source"]
    assert "Your history" in f["grid"]["source"]
    assert "Your history" not in f["generator"]["source"]


def test_a_generator_that_ran_is_installed():
    hist = {"first_ts": T0, "solar": None, "grid": None, "battery": None,
            "generator": {"peak_w": 4200.0, "last_ts": T0}}
    f = _facts(_values(generator_input=False), hist)
    assert f["generator"]["value"] == "Installed"
    assert "4.2 kW" in f["generator"]["source"]


def test_solar_in_history_but_not_in_the_pv_settings_is_shown():
    """e.g. DC solar on an aPower S, which the aGate's PV settings don't cover."""
    hist = {"first_ts": T0, "solar": {"peak_w": 5800.0, "last_ts": T0}, "generator": None,
            "grid": None, "battery": None}
    f = _facts(_values(solar_type="none"), hist)
    assert f["solar"]["value"] == "Solar seen in your history"
    assert "not in the gateway's PV settings" in f["solar"]["source"]


def test_no_history_changes_nothing():
    f = _facts(_values(solar_type="none"), None)
    assert f["solar"]["value"] == "No solar"
    assert f["generator"]["value"] == "Not installed"


class FakeClient:
    def __init__(self, meter):
        self._meter = meter

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self):
        return {}

    def solar_pv(self):
        return {}

    def generator(self):
        return {}

    def smart_circuits(self):
        return {}

    def smart_circuit_meter(self):
        return self._meter


def test_v2l_that_carried_energy_is_installed(monkeypatch):
    ss._derive_cache.clear()
    monkeypatch.setattr(client_mod, "_client",
                        lambda s, host=None: FakeClient({"CarSWExpEnergy": 1250,
                                                         "CarSWImpEnergy": 0}))
    d = ss._derive(object(), "h")
    ss._derive_cache.clear()
    assert d["v2l"] is True
    assert "12.5 kWh" in d["_sources"]["v2l"]


def test_the_api_card_carries_the_history(store, tmp_path, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db, state
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(ss, "_derive", lambda settings, host: {})
    monkeypatch.setattr(client_mod, "cloud_reserves", lambda s, host=None: [])
    store.insert({"generator_w": 4200}, int(time.time()) - DAY, gateway_id="gw-h")
    c = TestClient(app_module.create_app())
    state.register_gateway("gw-h", "10.0.0.1", "House")
    try:
        card = next(x for x in c.get("/api/install-profile").json()["gateways"]
                    if x["gateway_id"] == "gw-h")
    finally:
        state.unregister_gateway("gw-h")
    gen = next(f for f in card["facts"] if f["key"] == "generator")
    assert gen["value"] == "Installed" and "4.2 kW" in gen["source"]


# ── the support info carries the same summary, concisely (owner, 2026-11-06) ─
def test_summary_lines_from_the_card():
    v = _values(solar_type="ac", solar_kwp=6.6, load_shedding=True, apower_model="aPower X",
                _apower_models=["aPower X-01-AU"], whole_home_backup=True,
                _overridden={"whole_home_backup": True})
    card = ip.card("g", "G", {**INFO, "circuit_count": 3}, v,
                   modes=["Time-of-Use", "Self-Consumption"], off_grid=False)
    lines = ip.summary(card)
    assert lines[0] == ("install: aGate X-01-AU (AU) · 1 aPower X-01-AU · Connected to the grid · "
                        "AC-coupled solar, 6.6 kW · generator Not installed · "
                        "Smart Circuits 3 circuits · V2L Not installed")
    assert lines[1] == "modes: Time-of-Use, Self-Consumption"
    assert lines[2] == "answers: backup The whole home · battery name FranklinWH"
    assert lines[3] == "checked: 0 of 8 confirmed"


def test_support_info_shows_the_summary():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    js = (root / "static/js/settings_tab.js").read_text()
    assert "g.install" in js
    app = (root / "app.py").read_text()
    assert 'row["install"]' in app
