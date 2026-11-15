"""#613/#629: the Billing & Utilities page. Its setup steps (site → meter → plan →
tariffs) come from hems, the OUTUS engine, so every place says the same thing; a meter's
plans export as OUTUS plans."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, billing_page, config, db, environment
from franklinwh_direct_connect_bridge.db import MetricsStore

TODAY = dt.date(2026, 11, 15)


def _store(tmp_path, *, site=True, meter=True, tariff=True, rates=True):
    st = MetricsStore(str(tmp_path / "m.db"))
    if site:
        st.create_site(sid="s1", name="Home", is_default=True)
    if site and meter:
        st.create_meter(mid="m1", site_id="s1", name="Meter 1", is_default=True)
        st.create_gateway(gw_id="gwA", label="A", is_mock=True, is_default=True)
        st.update_gateway("gwA", meter_id="m1")
    if meter and tariff:
        st.create_utility(uid="u1", name="AGL", network_dnsp="Ausgrid")
        pricing = {"default_rate": {"buy": 0.30, "sell": 0.05}} if rates else {}
        st.create_tariff(tid="t1", utility_id="u1", name="Flat 30c", meter_id="m1",
                         effective_start="2026-01-01", pricing=pricing)
        st.update_meter("m1", utility_id="u1", tariff_id="t1")
    return st


def _todo(steps):
    return [s["key"] for s in steps if not s["done"]]


def test_nothing_set_up_asks_for_the_site_first(tmp_path):
    st = _store(tmp_path, site=False)
    page = billing_page.page(st, None, TODAY)
    assert _todo(page["steps"]) == ["site", "meter", "plan", "tariffs"]
    assert page["steps"][0]["blocked"] is False and page["steps"][1]["blocked"] is True
    assert page["complete"] is False


def test_a_meter_with_no_tariff_asks_for_the_plan(tmp_path):
    st = _store(tmp_path, tariff=False)
    page = billing_page.page(st, "m1", TODAY)
    assert _todo(page["steps"]) == ["plan", "tariffs"]
    assert page["meter"]["id"] == "m1" and page["meter"]["gateway_ids"] == ["gwA"]


def test_a_tariff_in_force_completes_setup(tmp_path):
    st = _store(tmp_path)
    page = billing_page.page(st, None, TODAY)            # no meter given: the default meter
    assert page["meter"]["id"] == "m1"
    assert page["complete"] is True
    assert [m["id"] for m in page["meters"]] == ["m1"]


def test_a_tariff_that_has_not_started_is_not_in_force(tmp_path):
    st = _store(tmp_path)
    st.update_tariff("t1", effective_start="2027-01-01")
    assert _todo(billing_page.page(st, "m1", TODAY)["steps"]) == ["plan", "tariffs"]


def test_a_meter_plan_is_an_outus_plan(tmp_path):
    st = _store(tmp_path)
    plan = billing_page.outus_plan(st, "t1")
    assert plan["type"] == "outus/plan" and plan["version"] == 1
    assert plan["effective_start"] == "2026-01-01"
    assert any(t["applies_to"] == "general" for t in plan["tariffs"])


@pytest.fixture
def client(tmp_path, monkeypatch):
    st = _store(tmp_path)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    yield TestClient(app_module.create_app())
    st.close()
    config._settings = None


def test_the_page_api_and_the_outus_export(client):
    r = client.get("/api/billing/page?meter=m1").json()
    assert r["complete"] is True and r["meter"]["id"] == "m1"
    p = client.get("/api/tariffs/t1/export?format=outus").json()
    assert p["type"] == "outus/plan"


def test_the_page_has_its_four_sub_tabs_and_object_styles():
    """Summary, Bill detail, History, Plans & meters (OUTUS §9 order); the progress bar lost
    its colour to a string :style, so the page binds styles as objects."""
    from pathlib import Path
    root = Path(billing_page.__file__).parent
    html = (root / "templates/tabs/energy_costs.html").read_text()
    js = (root / "static/js/energy_costs_tab.js").read_text()
    order = [js.index(f"label: '{t}'") for t in ("Summary", "Bill detail", "History", "Plans & meters")]
    assert order == sorted(order)
    assert ':style="\'' not in html
    assert 'x-data="settingsTab({ embedded: true })"' in html
    assert '{% include "partials/plans_meters.html" %}' in html
