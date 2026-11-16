"""#358 — the All gateways view's site SoC was a plain mean of the gateways' SoC. A full
aGate with two aPowers and an empty one with one aPower is two thirds full, not half: the
site SoC is weighted by each gateway's battery capacity (aPower count × usable kWh)."""
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import db, state, system_setup

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"


@pytest.fixture
def client(tmp_path, monkeypatch):
    state.reset_gateways()
    store = db.MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: store)
    monkeypatch.setattr(system_setup, "_derive_cache", {})
    yield TestClient(app_module.create_app())
    state.reset_gateways()


def _gw(gid, host, soc, models):
    g = state.register_gateway(gid, host, gid)
    g.last_summary = {"ok": True, "power": {"soc": soc, "battery_w": 0}}
    # what System Setup read from the gateway's login manifest (cached, no device I/O)
    system_setup._derive_cache[host] = (float("inf"), {"apower_model": "aPower X",
                                                       "_apower_models": models})
    return g


def test_site_soc_is_weighted_by_capacity(client):
    _gw("a1", "192.0.2.10", 100, ["aPower X-01-AU", "aPower X-01-AU"])
    _gw("b2", "192.0.2.20", 0, ["aPower X-01-AU"])
    site = client.get("/api/site/status").json()
    assert site["soc"] == pytest.approx(66.7, abs=0.1)
    assert site["soc_weighted"] is True


def test_unknown_capacity_falls_back_to_the_mean_and_says_so(client):
    _gw("a1", "192.0.2.10", 100, ["aPower X-01-AU", "aPower X-01-AU"])
    g = state.register_gateway("b2", "192.0.2.20", "b2")
    g.last_summary = {"ok": True, "power": {"soc": 0}}                 # no aPower read yet
    site = client.get("/api/site/status").json()
    assert site["soc"] == 50 and site["soc_weighted"] is False


def test_the_modal_shows_the_bridge_site_soc():
    js = (ROOT / "static/js/app.js").read_text()
    tpl = (ROOT / "templates/partials/all_gateways.html").read_text()
    assert "totals || {}).soc" in js
    assert "soc_weighted" in tpl
