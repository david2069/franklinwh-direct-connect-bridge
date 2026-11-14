"""Tariff plans per meter, phase 2 (owner 2026-11-13, aligned with the Modbus Bridge):
billing by date. Every reader prices with the tariff in force on that day, so a dated
plan takes over at midnight without anyone re-pointing the meter. A period closed by a
switch is stamped with the tariff that was in force, ends at the switch, and carries that
tariff's fixed charges for its own days."""
import datetime as dt

import pytest

from franklinwh_direct_connect_bridge import billing, scheduler, tariff_plans
from franklinwh_direct_connect_bridge.db import MetricsStore

SUPPLY = [{"type": "supply", "frequency": "daily", "rate": 1.0, "tax_rate": 0}]


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    s.create_utility(uid="u", name="AGL Energy", network_dnsp="Ausgrid")
    s.create_tariff(tid="t1", utility_id="u", name="Old plan", meter_id="m1",
                    effective_end="2026-11-15", billing_cycle_day=1, fixed_charges=SUPPLY,
                    pricing={"default_rate": {"buy": 0.20, "sell": 0.05}})
    s.create_tariff(tid="t2", utility_id="u", name="New plan", meter_id="m1",
                    effective_start="2026-11-16", billing_cycle_day=1, fixed_charges=SUPPLY,
                    pricing={"default_rate": {"buy": 0.50, "sell": 0.10}})
    s.create_meter(mid="m1", site_id="s", tariff_id="t1", utility_id="u", is_default=True)
    billing._TRACKERS.clear()
    return s


def test_tariff_for_follows_the_dates(st):
    m = st.meter("m1")
    assert tariff_plans.tariff_for(st, m, dt.date(2026, 11, 15))["id"] == "t1"
    assert tariff_plans.tariff_for(st, m, dt.date(2026, 11, 16))["id"] == "t2"


def test_undated_meter_keeps_its_tariff(tmp_path):
    s = MetricsStore(str(tmp_path / "x.db"))
    s.create_tariff(tid="loose", utility_id="u", name="Loose")
    s.create_meter(mid="mm", site_id="s", tariff_id="loose", is_default=True)
    s._conn.execute("UPDATE tariffs SET meter_id=NULL"); s._conn.commit()
    assert tariff_plans.tariff_for(s, s.meter("mm"))["id"] == "loose"


def test_billing_switches_at_midnight_and_closes_the_old_plan(st):
    t = dt.datetime(2026, 11, 15, 23, 0)
    for minutes in (0, 30, 59):                       # 1 kW import, priced at 0.20
        billing.billing_tick(st, "gw1", grid_w=1000, now=t + dt.timedelta(minutes=minutes))
    pts = billing.billing_tick(st, "gw1", grid_w=1000, now=dt.datetime(2026, 11, 16, 0, 1))
    closed = st.billing_periods(gateway_id="gw1")
    assert len(closed) == 1
    p = closed[0]
    assert p["tariff_id"] == "t1" and p["tariff_name"] == "Old plan"
    assert p["period_end"] == dt.datetime(2026, 11, 16, 0, 1).timestamp()
    assert p["import_cost"] == pytest.approx(p["import_kwh"] * 0.20, abs=0.01)
    assert p["fixed_total"] == pytest.approx(15.0, abs=0.05)   # 1 Nov → 16 Nov 00:01, $1/day
    assert st.meter("m1")["tariff_id"] == "t2"                  # the meter follows
    assert billing._TRACKERS["meter:m1"]._s["tariff_id"] == "t2"   # one tracker per meter (#611)
    assert pts is not None


def test_scheduler_reads_the_tariff_in_force(st):
    snap = scheduler.tariff_snapshot(st, "gw1", now=dt.datetime(2026, 11, 20, 12, 0).astimezone())
    assert snap.get("tariff.buy_rate") == 0.50
