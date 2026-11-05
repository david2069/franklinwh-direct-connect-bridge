"""#496 — the aPower model is read, not asked: each aPower's Direct Connect ``PE_HW_VER`` code
indexes franklinwh-cloud's ``apower_models`` catalogue (code 2 = aPower X-01-AU, measured on
the reference site), the same way the aGate's ``SyHdVersion`` indexes ``agate_models``."""
import sys
import types

import pytest

from franklinwh_direct_connect_bridge import client as client_mod
from franklinwh_direct_connect_bridge import devicedb
from franklinwh_direct_connect_bridge import install_profile as ip
from franklinwh_direct_connect_bridge import system_setup as ss

CAT = {
    "countries": {"2": {"code": "US"}, "3": {"code": "AU"}},
    "agate_models": {},
    "apower_models": {
        "2": {"name": "aPower X", "sku": "APR-05K13V1-AU", "model": "aPower X-01-AU",
              "country_id": 3, "has_mppt": False},
        "4": {"name": "aPower S", "sku": "APRS-10K15V1-US", "model": "aPower S-10",
              "country_id": 2, "has_mppt": True},
    },
}


@pytest.fixture
def catalog(monkeypatch):
    mod = types.ModuleType("franklinwh_cloud.discovery")
    mod.get_catalog = lambda: CAT
    monkeypatch.setitem(sys.modules, "franklinwh_cloud.discovery", mod)


@pytest.fixture(autouse=True)
def _fresh_cache():
    ss._derive_cache.clear()
    yield
    ss._derive_cache.clear()


def test_the_code_names_the_apower(catalog):
    a = devicedb.apower(2)
    assert a == {"code": 2, "model": "aPower X-01-AU", "family": "aPower X",
                 "sku": "APR-05K13V1-AU", "country": "AU", "has_mppt": False}
    assert devicedb.apower("4")["family"] == "aPower S"
    assert devicedb.apower(99) is None and devicedb.apower(None) is None


def test_one_entry_per_apower_in_the_manifest(catalog):
    rows = devicedb.apowers({"PE_HW_VER": [2, 2]})
    assert [r["model"] for r in rows] == ["aPower X-01-AU", "aPower X-01-AU"]
    assert devicedb.apowers({}) == []
    assert devicedb.apowers({"PE_HW_VER": [99]}) == [None]


def test_without_the_cloud_library_nothing_is_guessed(monkeypatch):
    monkeypatch.setitem(sys.modules, "franklinwh_cloud.discovery", None)
    assert devicedb.apower(2) is None


def test_the_pinned_catalogue_knows_the_reference_site():
    discovery = pytest.importorskip("franklinwh_cloud.discovery")
    row = discovery.get_catalog()["apower_models"]["2"]
    assert (row["name"], row["model"]) == ("aPower X", "aPower X-01-AU")
    for row in discovery.get_catalog()["apower_models"].values():
        assert row["name"] in devicedb.APOWER_SPECS, row      # capacity is known for each


class FakeClient:
    def __init__(self, manifest):
        self._m = manifest

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self):
        return self._m

    def solar_pv(self):
        return {}

    def generator(self):
        return {}

    def smart_circuits(self):
        return {}


def test_derived_from_the_login_reply(catalog, monkeypatch):
    monkeypatch.setattr(client_mod, "_client",
                        lambda s, host=None: FakeClient({"SyHdVersion": 102, "PE_HW_VER": [2]}))
    d = ss._derive(object(), "h")
    assert d["apower_model"] == "aPower X"
    assert d["_apower_models"] == ["aPower X-01-AU"]
    assert "model code 2" in d["_sources"]["apower"]


def test_mixed_or_unknown_codes_are_not_collapsed(catalog, monkeypatch):
    monkeypatch.setattr(client_mod, "_client",
                        lambda s, host=None: FakeClient({"PE_HW_VER": [2, 4]}))
    d = ss._derive(object(), "h")
    assert "apower_model" not in d
    assert d["_apower_models"] == ["aPower X-01-AU", "aPower S-10"]
    ss._derive_cache.clear()
    monkeypatch.setattr(client_mod, "_client",
                        lambda s, host=None: FakeClient({"PE_HW_VER": [99]}))
    d = ss._derive(object(), "h")
    assert "apower_model" not in d and d["_apower_models"] == [None]


def _values(**kw):
    base = {k: v["default"] for k, v in ss._FIELDS.items()}
    base.update({"_sources": {}, "_confirmed": {}, "_derived": {}, "_overridden": {}})
    base.update(kw)
    return base


INFO = {"model": "aGate X-01-AU", "country": "AU", "apower_count": 1}


def test_the_card_shows_the_model_and_does_not_ask():
    v = _values(apower_model="aPower X", _apower_models=["aPower X-01-AU"],
                _derived={"apower_model": "aPower X"},
                _sources={"apower": "Read from the gateway's list of aPowers (model code 2)"})
    card = ip.card("g", "G", INFO, v, modes=[], off_grid=False)
    bat = next(f for f in card["facts"] if f["key"] == "batteries")
    assert bat["value"] == "1 aPower X-01-AU"
    assert "model code 2" in bat["source"]
    assert "apower_model" not in [q["key"] for q in card["questions"]]


def test_mixed_models_are_listed():
    v = _values(_apower_models=["aPower X-01-AU", "aPower S-10", "aPower S-10"])
    card = ip.card("g", "G", {**INFO, "apower_count": 3}, v, modes=[], off_grid=False)
    bat = next(f for f in card["facts"] if f["key"] == "batteries")
    assert bat["value"] == "1 aPower X-01-AU, 2 aPower S-10"
    assert "apower_model" not in [q["key"] for q in card["questions"]]


def test_an_unknown_code_is_still_asked():
    v = _values(_apower_models=[None])
    card = ip.card("g", "G", INFO, v, modes=[], off_grid=False)
    assert "apower_model" in [q["key"] for q in card["questions"]]
    assert next(f for f in card["facts"] if f["key"] == "batteries")["value"] == "1 aPower"


def test_an_aps_site_asks_about_dc_solar_without_asking_the_model():
    v = _values(apower_model="aPower S", _apower_models=["aPower S-10"],
                _derived={"apower_model": "aPower S"})
    keys = [q["key"] for q in ip.card("g", "G", INFO, v, modes=[], off_grid=False)["questions"]]
    assert keys == ["backup", "solar_dc", "battery_label"]


def test_capacity_helper_and_support_info_use_the_read_model(catalog, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db, state
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    g = state.register_gateway("gw-ap", "10.0.0.1", "House")
    g.last_summary = {"firmware": {"FHP_SN": ["a"], "PE_HW_VER": [2]}}
    try:
        d = c.get("/api/apower-specs?gateway=gw-ap").json()
        assert d["apower_model"] == "aPower X" and d["apower_count"] == 1
    finally:
        state.unregister_gateway("gw-ap")
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    js = (root / "static/js/settings_tab.js").read_text()
    assert "d.apower_model" in js and "g.apower_models" in js
    assert "can't read it" not in (root / "templates/tabs/settings.html").read_text()
