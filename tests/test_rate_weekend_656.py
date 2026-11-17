"""A band's weekend rate (#656, owner 2026-11-18: keep both rates). A time period may hold an
optional ``weekend: {buy, sell}`` beside its own buy and sell: the FranklinWH app prices a
band per day type (weekdays, and weekends and holidays), so Saturday and Sunday use the
weekend rate and the other days the band's own. A tariff without one prices exactly as
before. Billing prices each day by its day type."""
import datetime as dt

from franklinwh_direct_connect_bridge import billing, rate_model, tariff_io
from franklinwh_direct_connect_bridge.db import MetricsStore

AEDT = dt.timezone(dt.timedelta(hours=11))
MON, SAT, SUN = dt.datetime(2026, 11, 16, 1, 0), dt.datetime(2026, 11, 21, 1, 0), dt.datetime(2026, 11, 22, 1, 0)


def seasons(weekend=True):
    off = {"buy": 0.20, "sell": 0.0}
    if weekend:
        off["weekend"] = {"buy": 0.18, "sell": 0.04}
    return [{"id": "s1", "name": "Summer", "months": list(range(1, 13)),
             "blocks": [{"start": "00:00", "end": "24:00", "time_period": "off_peak"}],
             "time_periods": {"off_peak": off}}]


def test_saturday_and_sunday_use_the_weekend_rate():
    s = seasons()
    assert rate_model.resolve(s, MON, 0)["buy"] == 0.20 and rate_model.resolve(s, MON, 0)["sell"] == 0.0
    for day in (SAT, SUN):
        r = rate_model.resolve(s, day, 0)
        assert (r["buy"], r["sell"], r["time_period"]) == (0.18, 0.04, "off_peak")
    assert not rate_model.validate(s, None)


def test_a_tariff_without_a_weekend_rate_prices_as_before():
    s = seasons(weekend=False)
    for day in (MON, SAT, SUN):
        assert rate_model.resolve(s, day, 0)["buy"] == 0.20


def test_a_weekend_side_left_out_falls_back_to_the_bands_own():
    s = seasons()
    del s[0]["time_periods"]["off_peak"]["weekend"]["sell"]
    r = rate_model.resolve(s, SAT, 0)
    assert r["buy"] == 0.18 and r["sell"] == 0.0


def test_a_weekend_tier_ladder_is_checked_like_any_other():
    s = seasons()
    s[0]["time_periods"]["off_peak"]["weekend"]["buy"] = [{"up_to_kwh": 10, "rate": 0.1}]
    assert any("tiers stop at" in p for p in rate_model.validate(s, None))


def test_the_tariff_profile_carries_it_both_ways():
    prof = {"name": "TOU", "retailer": "R", "pricing": {"seasons": seasons()}}
    _u, tar, _tz = tariff_io.to_local(prof)
    assert tar["pricing"]["seasons"][0]["time_periods"]["off_peak"]["weekend"] == {"buy": 0.18, "sell": 0.04}
    out = tariff_io.from_local({"name": "R"}, {"name": "TOU", "pricing": tar["pricing"]})
    assert out["profile"]["pricing"]["seasons"][0]["time_periods"]["off_peak"]["weekend"]["buy"] == 0.18


def _tracker(tmp_path, weekend=True):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="s1", name="Home", is_default=True)
    st.create_utility(uid="u1", name="R")
    st.create_tariff(tid="t1", utility_id="u1", name="TOU", billing_cycle_day=1,
                     pricing={"seasons": seasons(weekend)})
    st.create_meter(mid="m1", site_id="s1", utility_id="u1", tariff_id="t1", is_default=True)
    st.create_gateway(gw_id="gw1", label="Home", host="192.0.2.1")
    st.update_gateway("gw1", meter_id="m1")
    billing._TRACKERS.clear()
    return st


def _cost_of_an_hour(st, start):
    billing.billing_tick(st, "gw1", 1000.0, now=start.replace(tzinfo=AEDT))
    before = billing.billing_tick(st, "gw1", 1000.0, now=start.replace(tzinfo=AEDT, minute=1))
    after = billing.billing_tick(st, "gw1", 1000.0, now=start.replace(tzinfo=AEDT, hour=2, minute=1))
    return round(after["energy.import_cost"] - before["energy.import_cost"], 4)


def test_billing_prices_a_weekday_and_a_weekend_day_by_their_rates(tmp_path):
    st = _tracker(tmp_path)
    assert _cost_of_an_hour(st, MON) == 0.20          # 1 kWh on Monday at 0.20
    assert _cost_of_an_hour(st, SAT) == 0.18          # 1 kWh on Saturday at 0.18
    st.close()


def test_billing_without_a_weekend_rate_is_unchanged(tmp_path):
    st = _tracker(tmp_path, weekend=False)
    assert _cost_of_an_hour(st, MON) == 0.20
    assert _cost_of_an_hour(st, SAT) == 0.20
    st.close()
