"""#360 and the rest of the container-clock group (#161): the billing routes, the billing
page, the read-only snapshot and a smart circuit's schedule day use the gateway's site
clock, the one the scheduler ticks on, not the bridge container's. They differ when the
container's zone isn't the site's (Docker in UTC, or a Home Assistant host set to another
zone)."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, billing, billing_page, client,
                                              config, db, environment, scheduler, setup_wizard,
                                              site_time, state)
from franklinwh_direct_connect_bridge.db import MetricsStore

# 00:30 on the 1st at the site (UTC+11) is still the last day of the month in UTC.
SITE_NOW = dt.datetime(2026, 12, 1, 0, 30, tzinfo=dt.timezone(dt.timedelta(hours=11)))


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_site(sid="s1", name="Home", is_default=True)
    st.create_utility(uid="u1", name="AGL")
    st.create_tariff(tid="t1", utility_id="u1", name="Flat 30c", billing_cycle_day=1,
                     pricing={"default_rate": {"buy": 0.30, "sell": 0.05}})
    st.create_meter(mid="m1", site_id="s1", utility_id="u1", tariff_id="t1", is_default=True)
    st.create_gateway(gw_id="gwX", label="Home", host="192.0.2.9")
    st.update_gateway("gwX", meter_id="m1")
    billing._TRACKERS.clear()
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(site_time, "now_known", lambda host=None: SITE_NOW)
    state.reset_gateways()
    state.register_gateway("gwX", "192.0.2.9", "Home")
    yield st
    state.reset_gateways()


def _capture(monkeypatch, mod, name, seen, ret):
    real = getattr(mod, name)
    def spy(*a, **k):
        seen[name] = k.get("now", a[2] if len(a) > 2 else None)
        return ret(real, *a, **k)
    monkeypatch.setattr(mod, name, spy)


def test_the_overview_reads_on_the_site_clock(ctx, monkeypatch):
    seen = {}
    for n in ("billing_read", "fixed_snapshot"):
        _capture(monkeypatch, billing, n, seen, lambda real, *a, **k: real(*a, **k))
    ov = TestClient(app_module.create_app()).get("/api/billing/overview?gateway=gwX").json()
    assert seen == {"billing_read": SITE_NOW, "fixed_snapshot": SITE_NOW}
    # Cycle day 1: at the site the period started 30 minutes ago (in UTC it's a month old).
    assert ov["days_elapsed"] == round(30 / 1440, 2)


def test_close_period_uses_the_site_clock(ctx, monkeypatch):
    seen = {}
    _capture(monkeypatch, billing, "force_close_current", seen,
             lambda real, *a, **k: {"ok": False, "reason": "spy"})
    TestClient(app_module.create_app()).post("/api/billing/close?gateway=gwX")
    assert seen["force_close_current"] == SITE_NOW


def test_the_history_csv_says_whose_period_it_is(ctx):
    ctx.record_billing_period(gateway_id="gwX", retailer="AGL", period_start=1.0,
                              period_end=2.0, import_kwh=1, import_cost=0.3, net_total=0.3)
    csv = TestClient(app_module.create_app()).get("/api/billing/history?fmt=csv&gateway=gwX").text
    head, row = csv.splitlines()[:2]
    assert head.startswith("period_start,period_end,retailer") and head.endswith(",gateway_id")
    assert row.endswith(",gwX")


def test_the_billing_page_uses_the_sites_date(ctx, monkeypatch):
    from zoneinfo import ZoneInfo
    setup_wizard.set_site_timezone(ctx, "Pacific/Kiritimati")          # UTC+14
    seen = {}
    real = billing_page.page
    monkeypatch.setattr(billing_page, "page",
                        lambda st, meter, today: seen.update(today=today) or real(st, meter, today))
    TestClient(app_module.create_app()).get("/api/billing/page")
    assert seen["today"] == dt.datetime.now(ZoneInfo("Pacific/Kiritimati")).date()


def test_site_today_follows_the_site_timezone(ctx):
    from zoneinfo import ZoneInfo
    setup_wizard.set_site_timezone(ctx, "Pacific/Kiritimati")          # UTC+14
    assert app_module._site_today(ctx) == dt.datetime.now(ZoneInfo("Pacific/Kiritimati")).date()


def test_the_read_only_snapshot_reads_billing_on_the_given_clock(ctx, monkeypatch):
    seen = {}
    _capture(monkeypatch, billing, "billing_read", seen, lambda real, *a, **k: {})
    scheduler.build_snapshot(config.get_settings(), ctx, {}, host=None, gateway_id="gwX",
                             now=SITE_NOW, tick=False)
    assert seen["billing_read"] == SITE_NOW


def test_a_circuit_schedule_is_dated_on_the_site_clock(ctx, monkeypatch):
    seen = {}
    monkeypatch.setattr(client, "set_circuit_schedule",
                        lambda s, circuit, windows, today, host=None: seen.update(today=today) or {"ok": True})
    r = TestClient(app_module.create_app()).put(
        "/api/circuits/1/schedule?gateway=gwX",
        json={"windows": [{"enabled": True, "start": "01:00", "end": "02:00"}]})
    assert r.status_code < 500, r.text
    assert seen.get("today") == "2026-12-01"
