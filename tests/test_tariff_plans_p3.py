"""Tariff plans per meter, phase 3 (owner 2026-11-13, layout as the Modbus Bridge's
services): each meter card shows its tariff in force with New plan / Import / Edit /
Export and a collapsed history; the standalone Utilities & Tariffs list is gone, the
retailer is chosen in the tariff editor, and tariffs on no meter stay visible to assign."""
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
from franklinwh_direct_connect_bridge import tariff_plans
from franklinwh_direct_connect_bridge.db import MetricsStore
import datetime as dt

PKG = pathlib.Path(app_module.__file__).parent
HTML = (PKG / "templates" / "tabs" / "settings.html").read_text()
JS = (PKG / "static" / "js" / "settings_tab.js").read_text()


def test_meter_card_has_its_plans():
    for tid in ("meter-plan", "meter-plan-current", "meter-plan-new", "meter-plan-import",
                "meter-plan-history-toggle", "meter-plan-history", "tariff-retailer",
                "tariff-new-retailer", "unassigned-tariffs", "tariff-assign"):
        assert f'data-testid="{tid}"' in HTML, tid
    for fn in ("plansForMeter(", "planNow(", "planHistory(", "newPlanForMeter(",
               "assignTariff(", "openTariffImport("):
        assert fn in JS, fn


def test_standalone_utilities_list_is_gone():
    assert "<!-- utilities list -->" not in HTML
    assert 'x-for="u in utilities" :key="u.id">\n      <div class="rounded-lg border p-3' not in HTML
    # the meter editor no longer picks a tariff (plans are dated, on the meter card)
    assert "tariffsForUtility(meterEdit.utility_id)" not in HTML
    save = JS[JS.index("async saveMeter()"):JS.index("async deleteMeter(m)")]
    assert "tariff_id" not in save and "utility_id" not in save


def test_import_names_the_meter():
    code = JS[JS.index("openTariffImport("):JS.index("editUtility(u)")]
    assert "meter_id" in code


@pytest.fixture
def c(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(tariff_plans, "today", lambda: dt.date(2026, 11, 13))
    store.create_meter(mid="m1", site_id="s", is_default=True)
    store.create_utility(uid="u", name="AGL Energy")
    client = TestClient(app_module.create_app())
    client.store = store
    return client


def test_assigning_a_tariff_to_a_meter_checks_dates_and_repoints(c):
    c.post("/api/tariffs", json={"utility_id": "u", "name": "On meter", "meter_id": "m1",
                                 "effective_start": "2026-09-01"})
    loose = c.post("/api/tariffs", json={"utility_id": "u", "name": "Loose",
                                         "effective_start": "2026-10-01"}).json()
    r = c.patch(f"/api/tariffs/{loose['id']}", json={"meter_id": "m1"})
    assert r.status_code == 400 and "On meter" in r.json()["detail"]
    later = c.post("/api/tariffs", json={"utility_id": "u", "name": "Old", "effective_start": "2026-01-01",
                                         "effective_end": "2026-08-31"}).json()
    assert c.patch(f"/api/tariffs/{later['id']}", json={"meter_id": "m1"}).status_code == 200
    assert c.store.tariff(later["id"])["meter_id"] == "m1"
