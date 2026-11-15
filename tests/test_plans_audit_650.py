"""#650: Plans & meters.

(c) The import preview's ``has_demand`` says whether peak demand is actually on, not
    whether the profile carries a demand window (every Modbus Bridge profile does).
(d) Adding, editing, deleting and importing tariffs, retailers, sites and meters, and a
    bill's Recalculate, are in the Audit Trail (and the bridge log), saying what changed.
(b) Export is offered wherever a saved tariff is shown.
"""
import copy
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, billing_page, config, environment, db
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(app_module.__file__).parent
PARTIAL = (PKG / "templates" / "partials" / "plans_meters.html").read_text()

# The owner's Modbus Bridge export, trimmed: peak demand off (has_peak_demand 0, rate 0),
# but its demand window kept, as every profile has one.
PROFILE = {
    "type": "franklinwh-bridge/tariff-profile", "version": 1,
    "profile": {
        "name": "Service 1", "retailer": "AGL Energy", "network": "Ausgrid", "plan_type": "tou",
        "country": "AU", "timezone": "Australia/Sydney", "has_tou": 1, "has_peak_demand": 0,
        "has_export_bonus": 1,
        "demand_window": {"months": [], "days": [], "start": "14:00", "end": "20:00"},
        "bonus_window": {"months": [], "days": [], "start": "17:00", "end": "21:00"},
        "pricing": {"billing_cycle_day": 2, "demand_rate": 0, "demand_interval_min": 30,
                    "seasons": [], "default_rate": {"buy": 0.25, "sell": 0.05}},
    },
}


@pytest.fixture
def c(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    client = TestClient(app_module.create_app())
    client.store = st
    return client


def _audit(c, action):
    return [r for r in c.store.control_log(limit=200) if r["action"] == action]


def test_preview_has_demand_follows_whether_demand_is_on(c):
    off = c.post("/api/tariffs/import?dry_run=true", json=PROFILE).json()["preview"]
    assert off["has_demand"] is False
    on = copy.deepcopy(PROFILE)
    on["profile"]["has_peak_demand"] = 1
    on["profile"]["pricing"]["demand_rate"] = 0.3949
    assert c.post("/api/tariffs/import?dry_run=true", json=on).json()["preview"]["has_demand"] is True
    # A rate with the flag off is still off; no flag (an older profile): the rate decides.
    on["profile"]["has_peak_demand"] = 0
    assert c.post("/api/tariffs/import?dry_run=true", json=on).json()["preview"]["has_demand"] is False
    del on["profile"]["has_peak_demand"]
    assert c.post("/api/tariffs/import?dry_run=true", json=on).json()["preview"]["has_demand"] is True


def test_sites_meters_retailers_tariffs_are_audited(c):
    s = c.post("/api/sites", json={"name": "Home", "is_default": True}).json()
    c.patch(f"/api/sites/{s['id']}", json={"region": "AU-NSW"})
    m = c.post("/api/meters", json={"site_id": s["id"], "name": "Meter 1", "is_default": True}).json()
    c.patch(f"/api/meters/{m['id']}", json={"meter_number": "4103"})
    u = c.post("/api/utilities", json={"name": "AGL Energy", "network_dnsp": "Ausgrid"}).json()
    c.patch(f"/api/utilities/{u['id']}", json={"export_note": "5 kW"})
    t = c.post("/api/tariffs", json={"utility_id": u["id"], "name": "AGL Home", "meter_id": m["id"],
                                     "effective_start": "2026-01-01"}).json()
    c.patch(f"/api/tariffs/{t['id']}", json={"billing_cycle_day": 2})
    imp = c.post("/api/tariffs/import", json={**PROFILE, "meter_id": m["id"]}).json()
    assert imp["ok"]

    def one(action):
        rows = _audit(c, action)
        assert len(rows) == 1, (action, rows)
        assert rows[0]["ok"] == 1 and rows[0]["source"] == "ui"
        return rows[0]["detail"]

    assert "Home" in one("site_add")
    assert "Home" in one("site_edit") and "region" in one("site_edit")
    assert "Meter 1" in one("meter_add") and "Home" in one("meter_add")
    assert "Meter 1" in one("meter_edit") and "meter_number" in one("meter_edit")
    assert "AGL Energy" in one("retailer_add")
    assert "AGL Energy" in one("retailer_edit") and "export_note" in one("retailer_edit")
    d = one("tariff_add")
    assert "AGL Home" in d and "AGL Energy" in d and "Meter 1" in d
    d = one("tariff_edit")
    assert "AGL Home" in d and "billing_cycle_day" in d and "Meter 1" in d
    d = one("tariff_import")
    assert "Service 1" in d and "AGL Energy" in d and "Meter 1" in d and "ends \"AGL Home\"" in d

    assert c.delete(f"/api/tariffs/{imp['tariff_id']}").status_code == 200
    # The import ended "AGL Home" yesterday: a recently retired plan needs its name to delete.
    assert c.delete(f"/api/tariffs/{t['id']}?confirm_name=AGL%20Home").status_code == 200
    assert c.delete(f"/api/utilities/{u['id']}").status_code == 200
    assert c.delete(f"/api/meters/{m['id']}").status_code == 200
    s2 = c.post("/api/sites", json={"name": "Shed"}).json()
    assert c.delete(f"/api/sites/{s2['id']}").status_code == 200
    names = [r["detail"] for r in _audit(c, "tariff_delete")]
    assert any("Service 1" in d and "Meter 1" in d for d in names) and any("AGL Home" in d for d in names)
    assert "AGL Energy" in one("retailer_delete")
    assert "Meter 1" in one("meter_delete")
    assert "Shed" in one("site_delete")
    # Each is in the bridge log too (the helper writes both).


def test_a_refused_change_is_not_audited(c):
    assert c.post("/api/tariffs", json={"utility_id": "nope", "name": "X"}).status_code == 422
    assert not _audit(c, "tariff_add")


def test_bill_recalculate_is_audited(c, monkeypatch):
    s = c.post("/api/sites", json={"name": "Home", "is_default": True}).json()
    m = c.post("/api/meters", json={"site_id": s["id"], "name": "Meter 1", "is_default": True}).json()
    old = {"id": "bill-1", "status": "final", "x-meter-id": m["id"],
           "x-start": 1793451600.0, "x-end": 1796130000.0}
    monkeypatch.setattr(c.store, "outus_bill", lambda bid: old if bid == "bill-1" else None)
    monkeypatch.setattr(billing_page, "recalculate", lambda st, bid, now: {"id": "bill-1b", "supersedes": bid})
    assert c.post("/api/billing/bills/bill-1/recalculate").json()["id"] == "bill-1b"
    rows = _audit(c, "bill_recalculate")
    assert len(rows) == 1
    assert "bill-1" in rows[0]["detail"] and "Meter 1" in rows[0]["detail"] and "bill-1b" in rows[0]["result"]


def test_export_is_offered_wherever_a_saved_tariff_is_shown():
    # Not on a meter: Export next to Use on meter / Edit.
    nm = PARTIAL[PARTIAL.index('data-testid="unassigned-tariffs"'):PARTIAL.index("unusedUtilities()\" :key")]
    assert "exportTariffProfile(t)" in nm
    # In the tariff editor, for a saved tariff (Edit / View).
    ed = PARTIAL[PARTIAL.index("<!-- tariff editor"):PARTIAL.index("<!-- Import tariff")]
    assert 'data-testid="tariff-export"' in ed and "exportTariffProfile(tariffEdit)" in ed
