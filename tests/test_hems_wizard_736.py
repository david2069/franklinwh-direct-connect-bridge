"""#736 phase 2 (owner 2026-11-18): "Set up HEMS" in the setup list, under Advanced, answered
in the wizard. Steps: opt in → site & solar (a link to Location & Solar; the wizard doesn't ask
for those fields) → battery warranty → home usage → heavy loads → Check, then Save. It saves
through the existing APIs only (bridge settings; never the aGate or the cloud), and results
show in the dialog, not as toasts."""
import re
from pathlib import Path

import pytest

from franklinwh_direct_connect_bridge import hems_setup, setup_wizard, state
from franklinwh_direct_connect_bridge.db import MetricsStore

ROOT = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = (ROOT / "static/js/setup_wizard.js").read_text()
HTML = (ROOT / "templates/partials/setup_wizard.html").read_text()


def _hems_block(src: str) -> str:
    m = re.search(r"<template x-if=\"step === 'hems'\">(.*?)<!-- /hems -->", src, re.S)
    assert m, "no hems step in the wizard"
    return m.group(1)


def test_hems_is_an_advanced_task_answered_in_the_wizard():
    t = {x["id"]: x for x in setup_wizard.tasks()}
    assert t["hems"]["group"] == "advanced"
    assert t["hems"]["inline"] == "hems"
    assert t["hems"]["title"] == "Energy planning (HEMS)"
    adv = [x["id"] for x in setup_wizard.tasks() if x["group"] == "advanced"]
    assert adv[-2:] == ["emulator", "modbus"]           # the existing order is kept


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    state.reset_gateways()
    yield s
    state.reset_gateways()
    s.close()


def test_done_once_a_gateway_is_opted_in(st):
    state.register_gateway("gw1", "192.0.2.10", "gw1")
    assert hems_setup.configured(st) is False
    hems_setup.save(st, "gw1", {"opted_in": False})
    assert hems_setup.configured(st) is False
    hems_setup.save(st, "gw1", {"opted_in": True})
    assert hems_setup.configured(st) is True


def test_the_setup_list_reports_hems(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
    s = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda _s: s)
    state.reset_gateways()
    try:
        c = TestClient(app_module.create_app())
        hems = next(x for x in c.get("/api/setup").json()["tasks"] if x["id"] == "hems")
        assert hems["satisfied"] is False
    finally:
        state.reset_gateways()


def test_the_steps_in_order():
    m = re.search(r"HEMS_STEPS\s*[:=]\s*\[([^\]]*)\]", JS)
    assert m, "no HEMS_STEPS"
    assert re.findall(r"'(\w+)'", m.group(1)) == ["optin", "solar", "warranty", "usage", "loads",
                                                  "check"]
    assert "if (t.inline === 'hems') this.loadHems()" in JS


def test_site_and_solar_is_a_link_not_fields():
    block = _hems_block(HTML)
    assert 'data-testid="hems-wiz-solar"' in block
    assert "openLocationSolar()" in block
    for f in ("pv_latitude", "pv_longitude", "pv_kwp", "pv_tilt", "pv_azimuth"):
        assert f not in block, f
    assert "card: 'settings-location'" in JS or 'card: "settings-location"' in JS


def test_each_step_has_its_panel_and_skip():
    block = _hems_block(HTML)
    for k in ("optin", "solar", "warranty", "usage", "loads", "check"):
        assert f'data-testid="hems-wiz-{k}"' in block, k
    assert "Planning is only as accurate as your answers." not in block   # from the API, not hard-coded
    assert "hems.view.notice" in block
    assert 'data-testid="hems-wiz-no-loads"' in block                     # "None" for heavy loads
    assert 'data-testid="hems-wiz-skip-warranty"' in block


def test_it_saves_through_the_existing_apis_only_and_shows_the_result_in_the_dialog():
    m = re.search(r"async saveHemsWizard\(\)\s*\{(.*?)\n    \},", JS, re.S)
    assert m, "no saveHemsWizard"
    body = m.group(1)
    assert "'api/wear'" in body and "'api/hems/setup'" in body
    assert "method: 'PUT'" in body
    assert "toast" not in body
    for bad in ("api/gateways", "api/modbus", "api/cloud", "api/control", "api/mode"):
        assert bad not in body, bad
    assert 'data-testid="hems-wiz-result"' in _hems_block(HTML)


def test_choice_lists_show_plain_words():
    labels = re.search(r"HEMS_LABELS\s*[:=]\s*\{(.*?)\n    \},", JS, re.S)
    assert labels, "no HEMS_LABELS"
    for raw in ("ha_power", "ha_energy", "nameplate", "smart_circuit", "controlled_load",
                "general", "deferrable", "sheddable", "soak"):
        assert re.search(rf"\b{raw}:\s*'", labels.group(1)), raw
    assert "hemsLabel(" in _hems_block(HTML)


def test_the_cards_offer_the_wizard():
    html = (ROOT / "templates/tabs/settings.html").read_text()
    assert html.count('data-testid="run-hems-wizard"') == 2
    assert "fwh:open-setup-task" in html or "openHemsWizard()" in html
