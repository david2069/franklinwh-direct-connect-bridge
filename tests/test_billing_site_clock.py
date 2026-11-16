"""The scheduler runs on the site clock, a timezone-aware "now" (#43), but the billing
tracker rebuilt its period start from a stored timestamp as a naive time. With a meter on
a tariff and a period under way, every tick raised "can't subtract offset-naive and
offset-aware datetimes": on the owner's bridge 5,025 times a day per gateway, so no
schedule ran (daily health report, 2026-11-16)."""
import datetime as dt

from franklinwh_direct_connect_bridge import billing, config, scheduler
from franklinwh_direct_connect_bridge.db import MetricsStore

AEDT = dt.timezone(dt.timedelta(hours=11))


def _setup(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="s1", name="Home", is_default=True)
    st.create_utility(uid="u1", name="AGL")
    st.create_tariff(tid="t1", utility_id="u1", name="Flat 30c", billing_cycle_day=2,
                     pricing={"default_rate": {"buy": 0.30, "sell": 0.05}})
    st.create_meter(mid="m1", site_id="s1", utility_id="u1", tariff_id="t1", is_default=True)
    st.create_gateway(gw_id="gw1", label="Home", host="192.0.2.1")
    st.update_gateway("gw1", meter_id="m1")
    billing._TRACKERS.clear()
    return st


def test_billing_ticks_on_the_site_clock(tmp_path):
    st = _setup(tmp_path)
    billing.billing_tick(st, "gw1", 1000.0, now=dt.datetime(2026, 11, 16, 12, 0, tzinfo=AEDT))
    pts = billing.billing_tick(st, "gw1", 1000.0, now=dt.datetime(2026, 11, 16, 13, 0, tzinfo=AEDT))
    assert pts["energy.period_import_kwh"] > 0
    # the period start is on the same clock: the 2nd (cycle day) at midnight, site time
    tr = billing._TRACKERS[next(iter(billing._TRACKERS))]
    assert billing._at(tr._s["period_start"], dt.datetime(2026, 11, 16, tzinfo=AEDT)) == \
        dt.datetime(2026, 11, 2, tzinfo=AEDT)


def test_a_scheduler_tick_with_a_tariff_runs(tmp_path, monkeypatch):
    st = _setup(tmp_path)
    st.create_schedule(sid="s1", name="Low battery", spec={"trigger_type": "daily", "fire_at": "00:00",
                       "duration_min": 1439, "gateway_id": "gw1", "action": {}}, enabled=True)

    class Client:
        def __getattr__(self, n):
            return lambda *a, **k: {}
    state = {"soc": 27, "mode": "Self-Consumption", "grid_w": 1000, "battery_w": 0}
    s = config.get_settings()
    for now in (dt.datetime(2026, 11, 16, 12, 0, tzinfo=AEDT), dt.datetime(2026, 11, 16, 12, 1, tzinfo=AEDT)):
        scheduler.tick(settings=s, client=Client(), store=st, state=state, host=None,
                       gateway_id="gw1", now=now)          # raised TypeError on the 2nd tick
