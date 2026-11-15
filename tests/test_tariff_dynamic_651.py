"""#651: in the tariff editor, Rate type "Dynamic (live)" did nothing when clicked.

Cause: the editor's fieldsets are ``:disabled="tariffEdit.locked"`` and a new tariff (+ Add
tariff / New plan) had no ``locked`` key. Alpine turns an undefined dotted path into "" for
x-bind, and "" keeps ``disabled`` on, so every control of a new tariff was disabled. The
browser check that clicks it is tools/ui_check_tariff_dynamic.py; this is the static guard
plus the save/export/import round trip of ``pricing.kind`` and ``pricing.dynamic``.
"""
import pathlib
import re

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(app_module.__file__).parent
PARTIAL = (PKG / "templates" / "partials" / "plans_meters.html").read_text()
JS = (PKG / "static" / "js" / "settings_tab.js").read_text()


def test_tariff_editor_fieldsets_bind_a_boolean():
    binds = re.findall(r'<fieldset[^>]*:disabled="([^"]*)"', PARTIAL)
    assert binds, "the tariff editor's fieldsets bind :disabled"
    # A bare `tariffEdit.locked` is "" (disabled) in Alpine when the key is missing.
    assert all(b == "!!tariffEdit.locked" for b in binds), binds


def test_a_new_tariff_starts_unlocked():
    body = JS[JS.index("newTariff(uid) {"):JS.index("editTariff(t) {")]
    assert "locked: false" in body
    # The dynamic fields' sources load for a new tariff too, not only on Edit.
    assert "loadNemSpot()" in body and "loadHaPriceOpts()" in body


def _client(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    st.create_site(sid="s1", name="Home", region="AU-NSW", is_default=True)
    st.create_meter(mid="m1", site_id="s1", name="Meter 1", is_default=True)
    st.create_meter(mid="m2", site_id="s1", name="Meter 2")
    st.create_utility(uid="u1", name="Amber Electric", network_dnsp="Ausgrid")
    return TestClient(app_module.create_app()), st


def test_dynamic_rate_type_saves_and_round_trips(tmp_path, monkeypatch):
    c, st = _client(tmp_path, monkeypatch)
    for dyn in ({"source": "nem", "region": "NSW1", "buy_entity": "", "feedin_entity": ""},
                {"source": "ha", "region": "", "buy_entity": "ha:i1:sensor.amber_general_price",
                 "feedin_entity": "ha:i1:sensor.amber_feed_in_price"}):
        pricing = {"kind": "dynamic", "dynamic": dyn, "seasons": [],
                   "default_rate": {"buy": None, "sell": None}}
        assert c.post("/api/tariffs/validate", json={"pricing": pricing}).json()["ok"]
        r = c.post("/api/tariffs", json={"utility_id": "u1", "name": "Amber " + dyn["source"],
                                         "meter_id": "m1", "effective_start": "2026-01-01",
                                         "pricing": pricing})
        assert r.status_code == 201, r.text
        tid = r.json()["id"]
        assert st.tariff(tid)["pricing"]["kind"] == "dynamic"
        assert st.tariff(tid)["pricing"]["dynamic"] == dyn
        exp = c.get(f"/api/tariffs/{tid}/export").json()
        assert exp["profile"]["pricing"]["kind"] == "dynamic"
        assert exp["profile"]["pricing"]["dynamic"] == dyn
        out = c.post("/api/tariffs/import", json={**exp, "meter_id": "m2"}).json()
        back = st.tariff(out["tariff_id"])["pricing"]
        assert back["kind"] == "dynamic" and back["dynamic"] == dyn
        c.delete(f"/api/tariffs/{out['tariff_id']}")
        c.delete(f"/api/tariffs/{tid}")
