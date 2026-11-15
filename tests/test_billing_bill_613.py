"""#613 phase 2: the open period's bill is worked out by hems (the OUTUS engine) from the
meter's 5-minute ledger, built from its gateways' grid readings; each line has a formula."""
import datetime as dt
from zoneinfo import ZoneInfo

from franklinwh_direct_connect_bridge import billing_page
from franklinwh_direct_connect_bridge.db import MetricsStore

TZ = ZoneInfo("Australia/Sydney")
NOW = dt.datetime(2026, 11, 15, 12, 0, tzinfo=TZ)          # day 15 of a 1 Nov – 1 Dec period


def _store(tmp_path, gateways=("gwA",)):
    billing_page._LEDGERS.clear()
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="s1", name="Home", timezone="Australia/Sydney", is_default=True)
    st.create_meter(mid="m1", site_id="s1", name="Meter 1", is_default=True)
    for i, g in enumerate(gateways):
        st.create_gateway(gw_id=g, label=g, is_mock=True, is_default=(i == 0))
        st.update_gateway(g, meter_id="m1")
    st.create_utility(uid="u1", name="Example Energy", country="AU")
    st.create_tariff(tid="t1", utility_id="u1", name="Flat 30c", meter_id="m1",
                     effective_start="2026-01-01", billing_cycle_day=1,
                     pricing={"default_rate": {"buy": 0.30, "sell": 0.05}},
                     fixed_charges=[{"type": "supply", "frequency": "daily", "rate": 1.10}])
    return st


def _feed(st, gw, watts, start, minutes):
    t0 = int(start.timestamp())
    for i in range(0, minutes * 60 + 1, 30):                 # a poll every 30 s
        st.insert({"grid_w": watts}, t0 + i, gateway_id=gw)


def test_two_hours_at_one_kilowatt_bill_two_kwh(tmp_path):
    st = _store(tmp_path)
    _feed(st, "gwA", 1000, NOW - dt.timedelta(hours=3), 120)
    b = billing_page.bill(st, "m1", NOW)
    assert b["type"] == "outus/bill" and b["status"] == "provisional"
    energy = next(x for x in b["line_items"] if x.get("unit") == "kWh" and x["amount"] > 0)
    assert abs(energy["quantity"] - 2.0) < 0.02
    assert abs(energy["amount"] - 0.60) < 0.01
    assert energy["formula"]                                   # every line explains itself
    supply = next(x for x in b["line_items"] if "day" in (x.get("unit") or ""))
    assert abs(supply["amount"] - 1.10 * 14.5) < 0.05          # 14.5 days so far
    assert b["progress"]["days"] == 30


def test_export_is_credited(tmp_path):
    st = _store(tmp_path)
    _feed(st, "gwA", -2000, NOW - dt.timedelta(hours=2), 60)
    b = billing_page.bill(st, "m1", NOW)
    credit = next(x for x in b["line_items"] if x["amount"] < 0)
    assert abs(credit["quantity"] - 2.0) < 0.02 and abs(credit["amount"] + 0.10) < 0.01


def test_two_gateways_on_one_meter_add_up(tmp_path):
    """Each aGate's built-in CT measures its own part of the meter (#611)."""
    st = _store(tmp_path, gateways=("gwA", "gwB"))
    _feed(st, "gwA", 600, NOW - dt.timedelta(hours=2), 60)
    _feed(st, "gwB", 400, NOW - dt.timedelta(hours=2), 60)
    b = billing_page.bill(st, "m1", NOW)
    energy = next(x for x in b["line_items"] if x.get("unit") == "kWh" and x["amount"] > 0)
    assert abs(energy["quantity"] - 1.0) < 0.02


def test_no_tariff_in_force_gives_no_bill(tmp_path):
    st = _store(tmp_path)
    st.update_tariff("t1", effective_start="2027-01-01")
    assert billing_page.bill(st, "m1", NOW) is None


def test_later_readings_are_added_to_the_kept_ledger(tmp_path):
    st = _store(tmp_path)
    _feed(st, "gwA", 1000, NOW - dt.timedelta(hours=3), 60)
    first = billing_page.bill(st, "m1", NOW - dt.timedelta(hours=2))
    _feed(st, "gwA", 1000, NOW - dt.timedelta(hours=2) + dt.timedelta(seconds=30), 59)
    later = billing_page.bill(st, "m1", NOW)
    kwh = lambda b: sum(x["quantity"] for x in b["line_items"] if x.get("unit") == "kWh" and x["amount"] > 0)
    assert abs(kwh(first) - 1.0) < 0.02 and abs(kwh(later) - 2.0) < 0.03


def test_a_reading_written_late_is_not_lost(tmp_path):
    """A poll stamped just before a request but written after it still counts."""
    st = _store(tmp_path)
    _feed(st, "gwA", 1000, NOW - dt.timedelta(hours=1), 59)
    billing_page.bill(st, "m1", NOW)
    st.insert({"grid_w": 1000}, int(NOW.timestamp()) - 30, gateway_id="gwA")   # written late
    st.insert({"grid_w": 1000}, int(NOW.timestamp()) + 30, gateway_id="gwA")
    b = billing_page.bill(st, "m1", NOW + dt.timedelta(seconds=30))
    kwh = sum(x["quantity"] for x in b["line_items"] if x.get("unit") == "kWh" and x["amount"] > 0)
    assert abs(kwh - (1.0 + 1 / 60)) < 0.01


def test_the_bill_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, db, environment
    st = _store(tmp_path)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    r = TestClient(app_module.create_app()).get("/api/billing/bill?meter=m1").json()
    config._settings = None
    b = r["bill"]
    assert b["status"] == "provisional" and b["x-tariffs"]["general"]
    assert any(x["label"] for x in b["x-now-rates"])


def test_no_timezone_anywhere_bills_in_utc_and_says_so(tmp_path):
    st = _store(tmp_path)
    st.update_site("s1", timezone="")
    b = billing_page.bill(st, "m1", NOW)
    assert b["x-timezone"] == "UTC" and b["x-timezone-missing"] is True
    assert "x-timezone-missing" not in billing_page.bill(_store(tmp_path / "b"), "m1", NOW)
