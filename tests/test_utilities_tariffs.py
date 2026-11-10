"""Utilities + Tariffs roster (Phase 2). DB CRUD + JSON pricing round-trip."""
import datetime as dt
from franklinwh_direct_connect_bridge.db import MetricsStore
from franklinwh_direct_connect_bridge import rate_model as rm

PRICING = {"seasons": [{"name": "All year", "months": [],
    "time_periods": {"on_peak": {"buy": 0.55, "sell": 0.05}, "off_peak": {"buy": 0.20, "sell": 0.05}},
    "blocks": [{"start": "15:00", "end": "21:00", "time_period": "on_peak"},
               {"start": "21:00", "end": "15:00", "time_period": "off_peak"}]}],
    "default_rate": {"buy": 0.30, "sell": 0.08}}


def test_utility_crud(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    u = st.create_utility(uid="u1", name="AGL", network_dnsp="Ausgrid", country="AU",
                          battery_export_allowed=0, export_limit_kw=5.0)
    assert u["name"] == "AGL" and u["battery_export_allowed"] == 0 and u["export_limit_kw"] == 5.0
    st.update_utility("u1", battery_export_allowed=True, plan_type="tou")
    assert st.utility("u1")["battery_export_allowed"] == 1 and st.utility("u1")["plan_type"] == "tou"
    assert st.delete_utility("u1") is True


def test_tariff_json_round_trip_and_resolve(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_utility(uid="u1", name="AGL")
    t = st.create_tariff(tid="t1", utility_id="u1", name="TOU", pricing=PRICING,
                         fixed_charges=[{"type": "supply", "frequency": "daily", "rate": 1.1}],
                         billing_cycle_day=15)
    assert isinstance(t["pricing"], dict) and len(t["pricing"]["seasons"]) == 1
    assert t["fixed_charges"][0]["rate"] == 1.1 and t["billing_cycle_day"] == 15
    # the stored pricing resolves correctly
    r = rm.resolve(t["pricing"]["seasons"], dt.datetime(2026, 9, 23, 16, 0),
                   default_rate=t["pricing"]["default_rate"])
    assert r["time_period"] == "on_peak" and r["buy"] == 0.55
    st.update_tariff("t1", name="TOU v2", billing_cycle_day=1)
    assert st.tariff("t1")["name"] == "TOU v2" and st.tariff("t1")["billing_cycle_day"] == 1
    assert [x["name"] for x in st.tariffs(utility_id="u1")] == ["TOU v2"]
    assert st.delete_tariff("t1") is True


TIERED = {"seasons": [{"name": "All year", "months": [],
    "time_periods": {"off_peak": {"buy": [{"up_to_kwh": 1000, "rate": 0.22}, {"rate": 0.28}], "sell": 0.05}},
    "blocks": [{"start": "00:00", "end": "24:00", "time_period": "off_peak"}]}],
    "default_rate": {"buy": [{"up_to_kwh": 500, "rate": 0.25}, {"rate": 0.31}], "sell": 0.08}}


def test_tiered_rates_persist_and_price_per_tier(tmp_path):
    """A tier ladder on a time period (and on the default rate) survives the JSON
    round-trip and prices by cumulative period kWh — the Modbus tiered contract."""
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_utility(uid="u1", name="AGL")
    t = st.create_tariff(tid="t1", utility_id="u1", name="Tiered", pricing=TIERED)
    tp = t["pricing"]["seasons"][0]["time_periods"]["off_peak"]
    assert isinstance(tp["buy"], list) and len(tp["buy"]) == 2          # ladder survived storage
    seasons, dr = t["pricing"]["seasons"], t["pricing"]["default_rate"]
    now = dt.datetime(2026, 9, 23, 2, 0)                                # 02:00 → off_peak
    lo = rm.resolve(seasons, now, 500, dr)
    hi = rm.resolve(seasons, now, 1500, dr)
    assert lo["buy"] == 0.22 and lo["tier"] == 1                        # under 1000 kWh → tier 1
    assert hi["buy"] == 0.28 and hi["tier"] == 2                        # over 1000 kWh → tier 2
    # the default (tariff-wide) rate is tiered too, priced when no season matches
    d = rm.resolve([], now, 800, dr)
    assert d["buy"] == 0.31 and d["tier"] == 2                          # 800 > 500 → tier 2


def test_tariff_snapshot_from_gateway_meter(tmp_path):
    from franklinwh_direct_connect_bridge import scheduler as sch
    st = MetricsStore(str(tmp_path / "m.db"))
    st.seed_gateways([("h", "gw")]); st.ensure_default_site_meter()
    st.create_utility(uid="u1", name="AGL", battery_export_allowed=0, export_limit_kw=5.0)
    st.create_tariff(tid="t1", utility_id="u1", name="TOU", pricing=PRICING)
    mid = st.meters()[0]["id"]
    st.update_meter(mid, utility_id="u1", tariff_id="t1")
    gid = st.gateways()[0]["id"]
    snap = sch.tariff_snapshot(st, gid, dt.datetime(2026, 9, 23, 16, 0))    # 16:00 → on_peak
    assert snap["tariff.time_period"] == "on_peak" and snap["tariff.buy_rate"] == 0.55
    assert snap["service.battery_export_allowed"] == 0 and snap["service.export_limit_kw"] == 5.0
    assert snap["service.export_allowed"] == 1
    # unconfigured meter → empty snapshot (sensors read None → gate fails closed)
    st.update_meter(mid, utility_id="", tariff_id="")
    assert sch.tariff_snapshot(st, gid, dt.datetime(2026, 9, 23, 16, 0)) == {}
