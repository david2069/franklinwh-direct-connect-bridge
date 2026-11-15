"""#613 phase 3: each closed billing period gets its bill worked out by hems (final, with
its lines), kept, and listed newest first; a recalculation supersedes it; bills and usage
export as OUTUS documents."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from franklinwh_direct_connect_bridge import billing_page
from franklinwh_direct_connect_bridge.db import MetricsStore

TZ = ZoneInfo("Australia/Sydney")
NOW = dt.datetime(2026, 11, 15, 12, 0, tzinfo=TZ)


def _store(tmp_path):
    billing_page._LEDGERS.clear()
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="s1", name="Home", timezone="Australia/Sydney", is_default=True)
    st.create_meter(mid="m1", site_id="s1", name="Meter 1", is_default=True)
    st.create_gateway(gw_id="gwA", label="A", is_mock=True, is_default=True)
    st.update_gateway("gwA", meter_id="m1")
    st.create_utility(uid="u1", name="Example Energy", country="AU")
    st.create_tariff(tid="t1", utility_id="u1", name="Flat 30c", meter_id="m1",
                     effective_start="2026-01-01", billing_cycle_day=1,
                     pricing={"default_rate": {"buy": 0.30, "sell": 0.05}},
                     fixed_charges=[{"type": "supply", "frequency": "daily", "rate": 1.00}])
    return st


def _feed(st, watts, start, minutes, step=60):
    t0 = int(start.timestamp())
    st._conn.executemany("INSERT INTO metrics(ts, gateway_id, grid_w) VALUES (?,?,?)",
                         [(t0 + i, "gwA", watts) for i in range(0, minutes * 60 + 1, step)])
    st._conn.commit()


def test_closed_periods_get_final_bills_newest_first(tmp_path):
    st = _store(tmp_path)
    _feed(st, 1000, dt.datetime(2026, 10, 10, 12, tzinfo=TZ), 120)    # October: 2 kWh
    _feed(st, 1000, dt.datetime(2026, 9, 20, 12, tzinfo=TZ), 60)      # September: 1 kWh
    bills = billing_page.closed_bills(st, "m1", NOW)
    assert [b["period_start"][:10] for b in bills] == ["2026-09-30", "2026-08-31"]   # UTC of 1 Oct / 1 Sep local
    oct_ = bills[0]
    assert oct_["status"] == "final" and oct_["type"] == "outus/bill"
    energy = next(x for x in oct_["line_items"] if x.get("unit") == "kWh" and x["amount"] > 0)
    assert energy["quantity"] == pytest.approx(2.0, abs=0.02)
    supply = next(x for x in oct_["line_items"] if x.get("unit") == "day")
    assert supply["quantity"] == pytest.approx(31, abs=0.05)          # the whole of October


def test_a_closed_bill_is_kept_not_recalculated(tmp_path):
    st = _store(tmp_path)
    _feed(st, 1000, dt.datetime(2026, 10, 10, 12, tzinfo=TZ), 60)
    first = billing_page.closed_bills(st, "m1", NOW)[0]
    st.update_tariff("t1", pricing={"default_rate": {"buy": 0.50, "sell": 0.05}})
    again = billing_page.closed_bills(st, "m1", NOW)[0]
    assert again["id"] == first["id"] and again["net_total"] == first["net_total"]


def test_recalculate_supersedes(tmp_path):
    st = _store(tmp_path)
    _feed(st, 1000, dt.datetime(2026, 10, 10, 12, tzinfo=TZ), 60)
    old = billing_page.closed_bills(st, "m1", NOW)[0]
    st.update_tariff("t1", pricing={"default_rate": {"buy": 0.50, "sell": 0.05}})
    new = billing_page.recalculate(st, old["id"], NOW)
    assert new["supersedes"] == old["id"] and new["id"] != old["id"]
    listed = billing_page.closed_bills(st, "m1", NOW, include_superseded=True)
    assert [b["status"] for b in listed[:2]] == ["final", "superseded"]
    assert billing_page.closed_bills(st, "m1", NOW)[0]["id"] == new["id"]


def test_no_readings_no_bills(tmp_path):
    assert billing_page.closed_bills(_store(tmp_path), "m1", NOW) == []


def test_usage_exports_as_outus(tmp_path):
    st = _store(tmp_path)
    _feed(st, 1200, dt.datetime(2026, 10, 10, 12, tzinfo=TZ), 30)
    doc = billing_page.usage(st, "m1", dt.datetime(2026, 10, 10, tzinfo=TZ), dt.datetime(2026, 10, 11, tzinfo=TZ))
    assert doc["type"] == "outus/usage" and doc["channels"][0]["channel"] == "general"
    ivs = doc["channels"][0]["intervals"]
    assert ivs[0]["start"].endswith("Z") and sum(i["quantity_in"] for i in ivs) == pytest.approx(0.6, abs=0.01)


def test_the_bills_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
    st = _store(tmp_path)
    _feed(st, 1000, dt.datetime.now(TZ) - dt.timedelta(days=40), 60)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    bills = c.get("/api/billing/bills?meter=m1").json()["bills"]
    assert bills and bills[-1]["status"] == "final"
    b = bills[-1]
    r = c.get("/api/billing/bills/" + b["id"])
    assert r.json()["type"] == "outus/bill" and "attachment" in r.headers["content-disposition"]
    u = c.get(f"/api/billing/usage?meter=m1&start={b['period_start']}&end={b['period_end']}").json()
    assert u["type"] == "outus/usage"
    config._settings = None
