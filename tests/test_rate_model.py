"""Rate model — the seasonal TOU/tiered resolver (ported from the Modbus bridge)."""
import datetime as dt
from franklinwh_direct_connect_bridge import rate_model as rm


def test_flat_tariff_from_default_rate():
    r = rm.resolve([], dt.datetime(2026, 9, 23, 14, 0), default_rate={"buy": 0.30, "sell": 0.08})
    assert r["buy"] == 0.30 and r["sell"] == 0.08 and r["reason"] == "default_rate"
    assert r["billable"] is True


def test_not_configured():
    r = rm.resolve([], dt.datetime(2026, 9, 23, 14, 0))
    assert r["reason"] == "not_configured" and r["buy"] is None


def test_tou_resolves_by_time():
    seasons = [{
        "name": "All year", "months": [],
        "time_periods": {"on_peak": {"buy": 0.55, "sell": 0.05},
                         "off_peak": {"buy": 0.20, "sell": 0.05}},
        "blocks": [{"start": "15:00", "end": "21:00", "time_period": "on_peak"},
                   {"start": "21:00", "end": "15:00", "time_period": "off_peak"}],  # wraps midnight
    }]
    peak = rm.resolve(seasons, dt.datetime(2026, 9, 23, 16, 0))
    assert peak["time_period"] == "on_peak" and peak["buy"] == 0.55
    off = rm.resolve(seasons, dt.datetime(2026, 9, 23, 2, 0))          # 02:00 → off-peak (wrapped)
    assert off["time_period"] == "off_peak" and off["buy"] == 0.20


def test_tiered_prices_by_cumulative_use():
    dr = {"buy": [{"up_to_kwh": 1000, "rate": 0.22}, {"rate": 0.28}]}
    lo = rm.resolve([], dt.datetime(2026, 9, 23, 12, 0), used_kwh=500, default_rate=dr)
    hi = rm.resolve([], dt.datetime(2026, 9, 23, 12, 0), used_kwh=1500, default_rate=dr)
    assert lo["buy"] == 0.22 and lo["tier"] == 1
    assert hi["buy"] == 0.28 and hi["tier"] == 2


def test_seasonal_selection():
    seasons = [
        {"name": "Summer", "months": [12, 1, 2], "time_periods": {"flat": {"buy": 0.40}},
         "blocks": [{"start": "00:00", "end": "24:00", "time_period": "flat"}]},
        {"name": "Winter", "months": [6, 7, 8], "time_periods": {"flat": {"buy": 0.25}},
         "blocks": [{"start": "00:00", "end": "24:00", "time_period": "flat"}]},
    ]
    # 'flat' isn't a canonical TIME_PERIOD but resolve() still prices what the block names.
    assert rm.resolve(seasons, dt.datetime(2026, 1, 15, 12, 0))["buy"] == 0.40   # Jan → Summer
    assert rm.resolve(seasons, dt.datetime(2026, 7, 15, 12, 0))["buy"] == 0.25   # Jul → Winter
    assert rm.resolve(seasons, dt.datetime(2026, 4, 15, 12, 0))["reason"] == "no_season_for_month"


def test_validate_flags_coverage_gap_and_passes_flat():
    assert rm.validate([], default_rate={"buy": 0.3}) == []          # flat is complete
    # a block 00:00→24:00 covers the full day → no coverage gap
    full = [{"name": "X", "months": [], "time_periods": {"op": {"buy": 0.2}},
             "blocks": [{"start": "00:00", "end": "24:00", "time_period": "op"}]}]
    assert all("prices no rate" not in p for p in rm.validate(full))
    gap = [{"name": "Y", "months": [], "time_periods": {"op": {"buy": 0.2}},
            "blocks": [{"start": "06:00", "end": "22:00", "time_period": "op"}]}]   # 22:00-06:00 uncovered
    probs = rm.validate(gap)
    assert any("prices no rate" in p for p in probs)
