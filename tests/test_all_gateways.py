"""#383 — the default is a designation, the page shows ONE gateway, and "Site (All
Gateways)" is gone: a read-only All gateways modal replaces it."""
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import client as client_module
from franklinwh_direct_connect_bridge import db, mockgw, state, supervisor

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = ROOT / "static/js"
TPL = ROOT / "templates"


@pytest.fixture(autouse=True)
def _clean_registry():
    state.reset_gateways()
    yield
    state.reset_gateways()


@pytest.fixture
def roster(tmp_path, monkeypatch):
    store = db.MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: store)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(supervisor, "start_poller", _noop)
    monkeypatch.setattr(supervisor, "stop_poller", _noop)
    monkeypatch.setattr(supervisor, "is_running", lambda gid: True)
    monkeypatch.setattr(mockgw, "stop_mock", lambda gid: None)
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    return TestClient(app_module.create_app()), store


def test_site_view_is_gone_from_the_ui():
    for f in list(JS.glob("*.js")) + list(TPL.rglob("*.html")):
        if f.name.endswith(".min.js"):
            continue
        src = f.read_text()
        for word in ("__site__", "siteMode", "siteWriteNote", "writeQuery", "_pollSite"):
            assert word not in src, f"{f.name}: {word}"


def test_the_picker_opens_a_read_only_all_gateways_modal():
    top = (TPL / "partials/topbar.html").read_text()
    assert "$store.app.openAllGateways()" in top and "All gateways…" in top
    assert '{% include "partials/all_gateways.html" %}' in (TPL / "index.html").read_text()
    modal = (TPL / "partials/all_gateways.html").read_text()
    for label in ("Registered", "Polling active", "Unavailable", "Stopped", "Site total"):
        assert label in modal, label
    assert "$store.app.pickFromAll(r)" in modal
    for write in ("method:", "fetch(", "btn-primary"):          # display only: no controls
        assert write not in modal, write


def test_the_page_opens_on_the_default_gateway_not_a_remembered_one():
    app = (JS / "app.js").read_text()
    body = app[app.index("    async loadGateways() {"):]
    body = body[:body.index("    _tuneGatewayPoll() {")]
    assert "localStorage" not in body and "g.is_default && g.enabled !== false" in body
    assert "fwh-gateway" not in app


def test_the_default_becomes_active_when_the_active_one_is_disabled_offline_or_stopped():
    """Owner rule, 2026-10-29: at start-up, and whenever the active gateway is disabled or
    offline, the default gateway becomes the active one."""
    app = (JS / "app.js").read_text()
    body = app[app.index("    async loadGateways() {"):]
    body = body[:body.index("    _tuneGatewayPoll() {")]
    assert ("const usable = g => g && g.enabled !== false && g.link_state !== 'down' "
            "&& !g.identity_error;") in body
    assert "usable(this.gateways.find(g => g.id === prev)) ? prev : ((pick && pick.id) || '')" in body


def test_the_active_gateway_shows_even_when_it_is_the_only_one_and_disabled_ones_are_not_offered():
    top = (TPL / "partials/topbar.html").read_text()
    assert 'x-show="$store.app.gateways.length"' in top
    assert 'x-for="g in $store.app.gateways.filter(x => x.enabled !== false)"' in top


def test_roster_rows_say_whether_the_link_is_down(roster):
    c, store = roster
    store.create_gateway(gw_id="a1", label="Alpha", host="192.0.2.10")
    gw = state.register_gateway("a1", "192.0.2.10", "Alpha")
    gw.link_state = "down"
    assert {g["id"]: g for g in c.get("/api/gateways").json()}["a1"]["link_state"] == "down"


def test_the_default_is_listed_first(roster):
    c, store = roster
    store.create_gateway(gw_id="a1", label="Alpha", host="192.0.2.10")
    store.create_gateway(gw_id="z9", label="Zulu", host="192.0.2.20", is_default=True)
    assert [g["id"] for g in c.get("/api/gateways").json()] == ["z9", "a1"]


def test_deleting_the_default_promotes_the_next_now(roster):
    c, store = roster
    store.create_gateway(gw_id="a1", label="Alpha", host="192.0.2.10", is_default=True,
                         enabled=False)
    store.create_gateway(gw_id="b2", label="Bravo", host="192.0.2.20")
    state.register_gateway("b2", "192.0.2.20", "Bravo")
    state.set_default("a1")
    assert c.delete("/api/gateways/a1").status_code == 200
    assert store.gateway("b2")["is_default"] == 1
    assert state.default_gateway().id == "b2"


def test_roster_rows_carry_what_the_modal_shows(roster):
    c, store = roster
    store.create_gateway(gw_id="a1", label="Alpha", host="192.0.2.10")
    store.create_gateway(gw_id="b2", label="Bravo", host="192.0.2.20")
    store.create_gateway(gw_id="d3", label="Delta", host="192.0.2.30", enabled=False)
    a = state.register_gateway("a1", "192.0.2.10", "Alpha")
    a.last_summary = {"ok": True, "power": {"soc": 60, "battery_w": -500, "grid_w": 20,
                                            "solar_w": 900, "load_w": 420}}
    a.state_ts = 1793000000.0
    b = state.register_gateway("b2", "192.0.2.20", "Bravo")
    b.identity_error = "aGate SN-A at 192.0.2.20 already belongs to gateway a1."
    rows = {g["id"]: g for g in c.get("/api/gateways").json()}
    assert rows["a1"]["poll_status"] == "ok"
    assert rows["a1"]["power"] == {"battery_w": -500, "grid_w": 20, "solar_w": 900, "load_w": 420}
    assert rows["a1"]["last_poll_ts"] == 1793000000.0
    assert rows["b2"]["poll_status"] == "stopped" and "belongs to gateway a1" in rows["b2"]["identity_error"]
    assert rows["d3"]["poll_status"] == "stopped"


def test_site_status_never_reports_the_default_when_nothing_is_registered(roster):
    c, _ = roster
    site = c.get("/api/site/status").json()
    assert site["count"] == 0 and site["gateways"] == []
