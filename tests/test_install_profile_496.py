"""#496 — the install profile in plain words: what the gateway reports is shown with where it
came from and a Confirm button; only what the local API can't tell is asked. One card per
gateway, in the setup wizard and in Settings → Setup."""
import re
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import client as client_mod
from franklinwh_direct_connect_bridge import install_profile as ip
from franklinwh_direct_connect_bridge import setup_wizard as sw
from franklinwh_direct_connect_bridge import system_setup as ss
from franklinwh_direct_connect_bridge.db import MetricsStore

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"


@pytest.fixture(autouse=True)
def _fresh_cache():
    ss._derive_cache.clear()
    yield
    ss._derive_cache.clear()


@pytest.fixture
def store(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


class FakeClient:
    def __init__(self, solar=None, gen=None, sc=None):
        self._solar, self._gen, self._sc = solar or {}, gen or {}, sc or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self):
        return {"SyHdVersion": 102}

    def solar_pv(self):
        return self._solar

    def generator(self):
        return self._gen

    def smart_circuits(self):
        return self._sc


def _fake(monkeypatch, **kw):
    monkeypatch.setattr(client_mod, "_client", lambda s, host=None: FakeClient(**kw))


# ── defects ──────────────────────────────────────────────────────────────────
def test_no_solar_is_not_solar():
    caps = sw.capability_tabs({"solar_type": "none", "solar_kwp": 0.0}, generator_installed=False)
    assert caps["solar"] is False
    assert sw.capability_tabs({"solar_type": "ac", "solar_kwp": 6.6},
                              generator_installed=False)["solar"] is True
    js = (ROOT / "static/js/setup_wizard.js").read_text()
    assert "!!(values.solar_kwp || values.solar_type)" not in js


def test_remote_solar_rating_uses_the_solar_tabs_units(monkeypatch):
    """solarRatedPower is in 100 W steps on the Solar tab; the profile must agree with it."""
    _fake(monkeypatch, solar={"remoteSolarEn": 1, "solarRatedPower": 66})
    d = ss._derive(object(), "h")
    assert d["solar_type"] == "remote" and d["solar_kwp"] == 6.6


def test_settings_save_sends_only_what_changed():
    js = (ROOT / "static/js/settings_tab.js").read_text()
    save = js[js.index("async saveSystemSetup()"):]
    save = save[:save.index("\n    },\n")]
    assert "generator_input: !!s.generator_input" not in save, "every field became an override"
    assert "sysChanged()" in save


# ── what the gateway reports, and where it came from ─────────────────────────
def test_sources_say_where_each_value_came_from(monkeypatch):
    _fake(monkeypatch,
          solar={"installPV1port": 1, "installPV2port": 1, "PV1RatedPower": 33, "PV2RatedPower": 33},
          gen={"genEn": 1, "genModel": "G-7", "genRatedPower": 7000},
          sc={"CarSwConsSupEnable": 1})
    d = ss._derive(object(), "h")
    assert d["solar_type"] == "ac" and d["solar_kwp"] == 6.6
    assert d["v2l"] is True
    src = d["_sources"]
    assert "PV port 1 (3.3 kW)" in src["solar"] and "PV port 2 (3.3 kW)" in src["solar"]
    assert "G-7" in src["generator_input"]
    assert "V2L" in src["v2l"]


def test_generator_enabled_without_evidence_says_so(monkeypatch):
    _fake(monkeypatch, gen={"genEn": 1})
    src = ss._derive(object(), "h")["_sources"]["generator_input"]
    assert "turned on" in src and "no model or rating" in src


# ── confirm, without turning the value into an override ─────────────────────
def test_confirm_records_without_overriding(store, monkeypatch):
    monkeypatch.setattr(ss, "_derive", lambda settings, host: {"solar_type": "ac", "solar_kwp": 6.6})
    ss.confirm(store, "g", ["solar", "grid"], {"solar": "ac 6.6", "grid": "on"})
    v = ss.values(store, object(), "g", "h")
    assert v["_overridden"]["solar_type"] is False
    assert v["_confirmed"] == {"solar": "ac 6.6", "grid": "on"}


def test_new_fields_are_in_the_spec_and_snapshot(store):
    spec = ss.spec()
    assert spec["apower_model"]["kind"] == "enum"
    assert "aPower S" in spec["apower_model"]["options"]
    assert spec["v2l"]["derived"] is True
    snap = ss.snapshot(store, None, "g", None)
    assert "system.apower_model" in snap and "system.v2l" in snap


# ── the card ─────────────────────────────────────────────────────────────────
def _values(**kw):
    base = {k: v["default"] for k, v in ss._FIELDS.items()}
    base.update({"solar_type": "ac", "solar_kwp": 6.6, "generator_input": False,
                 "load_shedding": True, "v2l": False})
    base.update(kw)
    base.setdefault("_sources", {"solar": "Read from the gateway's PV settings: PV port 1 (3.3 kW)"})
    base.setdefault("_confirmed", {})
    base.setdefault("_derived", {"solar_type": "ac"})
    return base


INFO = {"model": "aGate X-01-AU", "country": "AU", "apower_count": 1, "circuit_count": 3}


def test_card_shows_facts_in_plain_words():
    card = ip.card("gw1", "Home", INFO, _values(), modes=["Time of Use", "Self-Consumption"],
                   off_grid=False)
    facts = {f["key"]: f for f in card["facts"]}
    assert list(facts) == ["gateway", "batteries", "grid", "modes", "solar", "generator",
                           "smart_circuits", "v2l"]
    assert facts["gateway"]["value"] == "aGate X-01-AU (AU)"
    assert facts["batteries"]["value"] == "1 aPower"
    assert facts["grid"]["value"] == "Connected to the grid"
    assert facts["modes"]["value"] == "Time of Use, Self-Consumption"
    assert facts["solar"]["value"] == "AC-coupled solar, 6.6 kW"
    assert "PV port 1" in facts["solar"]["source"]
    for f in card["facts"]:
        assert "_" not in f["label"], f
        assert f["source"], f
        assert f["confirmed"] is False


def test_card_asks_only_what_cant_be_read():
    card = ip.card("gw1", "Home", INFO, _values(), modes=[], off_grid=False)
    assert [q["key"] for q in card["questions"]] == ["apower_model", "backup", "battery_label"]
    s = ip.card("gw1", "Home", INFO, _values(apower_model="aPower S"), modes=[], off_grid=False)
    assert [q["key"] for q in s["questions"]] == ["apower_model", "backup", "solar_dc",
                                                  "battery_label"]


def test_a_confirmed_fact_stays_confirmed_until_it_changes():
    v = _values()
    first = ip.card("gw1", "Home", INFO, v, modes=[], off_grid=False)
    solar = next(f for f in first["facts"] if f["key"] == "solar")
    v["_confirmed"] = {"solar": solar["value"]}
    again = ip.card("gw1", "Home", INFO, v, modes=[], off_grid=False)
    assert next(f for f in again["facts"] if f["key"] == "solar")["confirmed"] is True
    v["solar_kwp"] = 8.0
    changed = ip.card("gw1", "Home", INFO, v, modes=[], off_grid=False)
    assert next(f for f in changed["facts"] if f["key"] == "solar")["confirmed"] is False


def test_off_grid_and_unknowns_are_said_plainly():
    card = ip.card("gw1", "Home", {"model": None, "apower_count": None}, _values(),
                   modes=[], off_grid=True)
    facts = {f["key"]: f for f in card["facts"]}
    assert facts["grid"]["value"] == "Off-grid right now"
    assert facts["batteries"]["value"] == "Couldn't be read"
    assert facts["gateway"]["value"] == "Couldn't be read"


def test_backup_answer_writes_both_fields():
    assert ip.answer_updates("backup", "whole") == {"whole_home_backup": True,
                                                    "non_backup_loads": False}
    assert ip.answer_updates("backup", "panel") == {"whole_home_backup": False,
                                                    "non_backup_loads": True}
    assert ip.answer_updates("solar_dc", True) == {"solar_type": "dc"}
    assert ip.answer_updates("apower_model", "aPower 2") == {"apower_model": "aPower 2"}


# ── API ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def api(tmp_path, monkeypatch, store):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db, state
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(ss, "_derive", lambda settings, host: {"solar_type": "ac", "solar_kwp": 6.6})
    monkeypatch.setattr(client_mod, "cloud_reserves", lambda s, host=None: [{"workMode": 2}])
    c = TestClient(app_module.create_app())
    state.register_gateway("gw-a", "10.0.0.1", "House")
    state.register_gateway("gw-b", "10.0.0.2", "Shed")
    yield c
    state.unregister_gateway("gw-a")
    state.unregister_gateway("gw-b")


def test_api_lists_a_card_per_gateway(api):
    cards = api.get("/api/install-profile").json()["gateways"]
    ids = [c["gateway_id"] for c in cards]
    assert "gw-a" in ids and "gw-b" in ids


def test_api_confirm_and_answer(api):
    card = next(c for c in api.get("/api/install-profile").json()["gateways"]
                if c["gateway_id"] == "gw-a")
    solar = next(f for f in card["facts"] if f["key"] == "solar")
    r = api.post("/api/install-profile/confirm?gateway=gw-a", json={"keys": ["solar"]})
    assert r.status_code == 200
    card = next(c for c in r.json()["gateways"] if c["gateway_id"] == "gw-a")
    assert next(f for f in card["facts"] if f["key"] == "solar")["confirmed"] is True
    r = api.post("/api/install-profile/answer?gateway=gw-a",
                 json={"key": "backup", "value": "panel"})
    card = next(c for c in r.json()["gateways"] if c["gateway_id"] == "gw-a")
    assert next(q for q in card["questions"] if q["key"] == "backup")["value"] == "panel"
    # gw-b is untouched
    other = next(c for c in r.json()["gateways"] if c["gateway_id"] == "gw-b")
    assert next(f for f in other["facts"] if f["key"] == "solar")["confirmed"] is False
    assert solar["value"] == "AC-coupled solar, 6.6 kW"


# ── UI ───────────────────────────────────────────────────────────────────────
def test_one_shared_card_in_wizard_and_settings():
    part = (ROOT / "templates/partials/install_profile.html").read_text()
    assert 'x-for="card in cards"' in part
    assert "f.source" in part and "Confirm" in part
    wiz = (ROOT / "templates/partials/setup_wizard.html").read_text()
    st = (ROOT / "templates/tabs/settings.html").read_text()
    assert "partials/install_profile.html" in wiz
    assert "partials/install_profile.html" in st
    # The raw-key rendering is gone from both.
    assert 'x-text="k"' not in st[st.index("sub==='setup'"):st.index("sub==='general'")]
    confirm = wiz[wiz.index("step === 'confirm'"):wiz.index("step === 'publish'")]
    assert 'x-text="k"' not in confirm


# ── accessories read as installed, like Smart Circuits (owner, 2026-11-05) ───
def test_generator_and_v2l_read_as_installed():
    card = ip.card("gw1", "Home", INFO, _values(generator_input=True, v2l=True), modes=[],
                   off_grid=False)
    facts = {f["key"]: f for f in card["facts"]}
    assert facts["generator"]["value"] == "Installed"
    assert facts["v2l"]["value"] == "Installed"
    none = {f["key"]: f for f in ip.card("gw1", "Home", INFO, _values(), modes=[],
                                         off_grid=False)["facts"]}
    assert none["generator"]["value"] == "Not installed"
    assert none["v2l"]["value"] == "Not installed"


def test_a_generator_with_a_model_counts_as_installed(monkeypatch):
    _fake(monkeypatch, gen={"genEn": 0, "genModel": "G-7"})
    assert ss._derive(object(), "h")["generator_input"] is True


# ── the gateway row reads the poller's hardware id (owner, 2026-11-11) ───────
def test_gateway_row_names_the_model_from_the_hardware_id(api):
    """The summary's firmware block never carries SyHdVersion; the poller keeps it on the
    gateway (1101), as the gateway list does. Before, the row always said Couldn't be read."""
    from franklinwh_direct_connect_bridge import state
    state.get_gateway("gw-a").sy_hd_version = 102
    card = next(c for c in api.get("/api/install-profile").json()["gateways"]
                if c["gateway_id"] == "gw-a")
    gw = next(f for f in card["facts"] if f["key"] == "gateway")
    assert gw["value"] == "aGate X-01-AU (AU)"


# ── reported rows fold to one line, one open at a time (owner, 2026-11-11) ──
def test_reported_rows_are_folded_one_open_at_a_time():
    part = (ROOT / "templates/partials/install_profile.html").read_text()
    js = (ROOT / "static/js/install_profile.js").read_text()
    rows = part[part.index("What your gateway reports"):part.index("What only you can tell")]
    assert 'data-testid="install-fact"' in rows
    assert ":aria-expanded" in rows and "toggle(card, f.key)" in rows
    assert 'x-show="isOpen(card, f.key)"' in rows        # source + Confirm only when open
    assert "open: {}" in js                               # gateway id -> the one open row
    # The questions stay open: they need answers.
    asks = part[part.index("What only you can tell"):]
    assert "isOpen" not in asks
