"""FEAT-BILLING-WHOLESALE: dynamic (wholesale) rate overrides the static tariff in billing."""

import datetime as dt
from franklinwh_local_bridge import billing


def test_rate_prefers_dynamic_over_static():
    cfg = {"pricing": {"default_rate": {"buy": 0.30, "sell": 0.05}}}
    now = dt.datetime(2026, 9, 30, 12, 0)
    # static path
    st = billing.BillingTracker._rate(cfg, now, 0.0)
    assert abs(st["buy"] - 0.30) < 1e-9
    # dynamic path (live wholesale $/kWh) overrides
    dyn = billing.BillingTracker._rate(cfg, now, 0.0, {"buy": 0.12, "sell": 0.06})
    assert abs(dyn["buy"] - 0.12) < 1e-9 and abs(dyn["sell"] - 0.06) < 1e-9
    assert dyn["reason"] == "dynamic" and dyn["billable"] is True
    # negative wholesale price -> not billable (import is a credit)
    neg = billing.BillingTracker._rate(cfg, now, 0.0, {"buy": -0.02, "sell": -0.02})
    assert neg["billable"] is False


def test_dynamic_import_cost_uses_live_rate():
    tr = billing.BillingTracker()
    cfg = {"pricing": {"default_rate": {"buy": 0.30, "sell": 0.05}}, "cycle_day": 1}
    t0 = dt.datetime(2026, 9, 30, 12, 0, 0)
    dyn = {"buy": 0.10, "sell": 0.05}   # live $/kWh
    tr.update(None, "g", 0.0, cfg, t0, dynamic_rate=dyn)          # prime last_ts
    tr.update(None, "g", 3600.0, cfg, t0 + dt.timedelta(hours=1), dynamic_rate=dyn)  # 3600W * 1h = 3.6 kWh
    # 3.6 kWh * $0.10 = $0.36 at the LIVE rate (not the $0.30 static)
    assert abs(tr._s["import_cost"] - 0.36) < 1e-6


def test_resolve_dynamic_price_nem(monkeypatch):
    from franklinwh_local_bridge import scheduler, aemo_nem
    monkeypatch.setattr(aemo_nem, "spot_price",
                        lambda r: {"price_c_kwh": 6.72} if r == "NSW1" else None)
    buy, sell = scheduler.resolve_dynamic_price({"source": "nem", "region": "NSW1"}, None)
    assert buy == 6.72 and sell == 6.72
    assert scheduler.resolve_dynamic_price({"source": "nem", "region": "ZZZ"}, None) == (None, None)


def test_resolve_dynamic_price_ha(monkeypatch):
    from franklinwh_local_bridge import scheduler
    monkeypatch.setattr(scheduler, "_ha_prices_c",
                        lambda store, ids: {"ha:h:sensor.buy": 12.4, "ha:h:sensor.sell": 5.5})
    buy, sell = scheduler.resolve_dynamic_price(
        {"source": "ha", "buy_entity": "ha:h:sensor.buy", "feedin_entity": "ha:h:sensor.sell"}, None)
    assert buy == 12.4 and sell == 5.5
    # sell falls back to buy when no feed-in
    monkeypatch.setattr(scheduler, "_ha_prices_c", lambda store, ids: {"ha:h:sensor.buy": 12.4})
    b2, s2 = scheduler.resolve_dynamic_price({"source": "ha", "buy_entity": "ha:h:sensor.buy"}, None)
    assert b2 == 12.4 and s2 == 12.4


def test_apply_dynamic_pricing_overrides_sensors(monkeypatch):
    from franklinwh_local_bridge import scheduler
    monkeypatch.setattr(scheduler, "tariff_dynamic_provider",
                        lambda store, gw: {"source": "nem", "region": "NSW1"})
    monkeypatch.setattr(scheduler, "resolve_dynamic_price", lambda dyn, store: (17.0, 8.0))
    snap = {"tariff.spot_price": 6.72, "tariff.buy_rate": 0.216}   # global values (get overridden)
    out = scheduler.apply_dynamic_pricing(snap, object(), None, "g")
    assert out == {"buy": 0.17, "sell": 0.08}
    assert snap["tariff.spot_price"] == 17.0 and snap["tariff.buy_rate"] == 0.17
    assert snap["tariff.feed_in_price"] == 8.0 and snap["tariff.sell_rate"] == 0.08
    # static tariff -> None, sensors untouched
    monkeypatch.setattr(scheduler, "tariff_dynamic_provider", lambda store, gw: None)
    snap2 = {"tariff.spot_price": 6.72}
    assert scheduler.apply_dynamic_pricing(snap2, object(), None, "g") is None
    assert snap2["tariff.spot_price"] == 6.72
