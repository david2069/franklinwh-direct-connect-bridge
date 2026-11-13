"""Retired tariffs are locked (owner 2026-11-13): a plan whose end date has passed keeps
its rates and charges visible, so past bills can be reconciled. Changing it needs an
unlock; deleting one that ended under 13 months ago needs the typed plan name (after two
warnings in the UI). Older than 13 months: a normal delete."""
import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
from franklinwh_direct_connect_bridge import tariff_plans
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(app_module.__file__).parent
TODAY = dt.date(2026, 11, 13)


def test_lock_rules():
    t = lambda end: {"effective_end": end}
    assert not tariff_plans.retired(t(None), TODAY)
    assert not tariff_plans.retired(t("2026-11-13"), TODAY)        # its last day is today
    assert tariff_plans.retired(t("2026-11-12"), TODAY)
    assert tariff_plans.recently_retired(t("2025-10-14"), TODAY)   # under 13 months
    assert not tariff_plans.recently_retired(t("2025-10-13"), TODAY)


@pytest.fixture
def c(tmp_path, monkeypatch):
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    monkeypatch.setattr(tariff_plans, "today", lambda: TODAY)
    store.create_meter(mid="m1", site_id="s", is_default=True)
    store.create_utility(uid="u", name="AGL Energy")
    store.create_tariff(tid="recent", utility_id="u", name="Old plan", meter_id="m1",
                        effective_start="2026-01-01", effective_end="2026-10-31")
    store.create_tariff(tid="ancient", utility_id="u", name="Ancient", meter_id="m1",
                        effective_start="2024-01-01", effective_end="2025-06-30")
    client = TestClient(app_module.create_app())
    client.store = store
    return client


def test_a_retired_plan_is_locked_until_unlocked(c):
    r = c.patch("/api/tariffs/recent", json={"name": "Renamed"})
    assert r.status_code == 409 and "ended" in r.json()["detail"]
    assert c.patch("/api/tariffs/recent", json={"name": "Renamed", "unlock": True}).status_code == 200
    assert c.store.tariff("recent")["name"] == "Renamed"
    assert c.patch("/api/tariffs/ancient", json={"meter_id": "m1"}).status_code == 200   # a move is no edit


def test_deleting_a_recently_retired_plan_needs_its_name(c):
    assert c.delete("/api/tariffs/recent").status_code == 409
    assert c.delete("/api/tariffs/recent?confirm_name=old").status_code == 409
    assert c.delete("/api/tariffs/recent?confirm_name=Old%20plan").status_code == 200
    assert c.delete("/api/tariffs/ancient").status_code == 200       # over 13 months


def test_ui_views_locked_plans_and_warns_before_unlock_or_delete():
    js = (PKG / "static" / "js" / "settings_tab.js").read_text()
    html = (PKG / "templates" / "tabs" / "settings.html").read_text()
    app = (PKG / "static" / "js" / "app.js").read_text()
    assert "confirmTyped(" in app
    assert "tariffEdit.locked" in html and 'data-testid="tariff-unlock"' in html
    assert '<fieldset :disabled="tariffEdit.locked"' in html
    d = js[js.index("async deleteTariff(t)"):js.index("async saveEditGateway()")]
    assert "_retiredWarnings(t, 'delete')" in d and "confirm_name=" in d
    w = js[js.index("async _retiredWarnings("):js.index("async unlockTariff()")]
    assert "confirmTyped(" in w and "Warning 2 of 2" in w
    assert "unlock: true" in js[js.index("async saveTariff()"):js.index("async deleteTariff(t)")]
