"""Owner, 2026-11-10: a custom From-To date and time range, any length, on Local and Cloud,
times picked from a styled grid (not the browser's lists). Slots get coarser as the range
grows, the same on both: 5-minute power to 2 days, hourly kWh to 31 days, daily to a year,
monthly beyond (franklinwh-ha-cloud-analytics fetch_range)."""
import datetime as dt
import pathlib
import re

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import cloud_status

from test_cloud_analytics import env  # noqa: F401 — the cloud route's fixture

PKG = pathlib.Path(app_module.__file__).parent
JS = (PKG / "static" / "js" / "analytics_tab.js").read_text()
HTML = (PKG / "templates" / "tabs" / "analytics.html").read_text()


def test_the_cloud_route_reads_a_custom_range(env):  # noqa: F811
    seen = []

    def read_range(email, password, serial, start, end, today, refresh=False):
        seen.append((serial, start, end, today, refresh))
        return {"source": "cloud", "period": "custom", "series": []}

    env["mp"].setattr(cloud_status, "read_range", read_range)
    c = TestClient(app_module.create_app())
    r = c.get("/api/analytics/cloud?period=custom&from=2026-11-05T22:00&to=2026-11-06T02:00&gateway=gw-a")
    assert r.status_code == 200 and r.json()["period"] == "custom"
    assert seen == [("seriala", dt.datetime(2026, 11, 5, 22, 0), dt.datetime(2026, 11, 6, 2, 0),
                     dt.date(2026, 11, 9), False)]
    for q in ("from=2026-11-06T02:00&to=2026-11-05T22:00", "from=nonsense&to=2026-11-06T02:00", "to=2026-11-06T02:00"):
        assert c.get(f"/api/analytics/cloud?period=custom&{q}&gateway=gw-a").status_code == 400


def test_read_range_uses_the_packages_range_read_and_cache(monkeypatch):
    got = {}

    class Fake:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def client_for(email, password, gateway, source="status"):
        return Fake()

    async def fetch_range(client, start, end, *, today, cache, key, now=None):
        got.update(start=start, end=end, today=today, cache=cache, key=key)
        return {"period": "custom"}

    import franklinwh_ha_cloud_analytics as ca
    monkeypatch.setattr(cloud_status, "_client_for", client_for)
    monkeypatch.setattr(ca, "fetch_range", fetch_range)
    cloud_status._ENERGY_CACHE = None
    out = cloud_status.read_range("a@b.c", "x", "seriala", dt.datetime(2026, 11, 5, 22), dt.datetime(2026, 11, 6, 2),
                                  dt.date(2026, 11, 9))
    assert out["period"] == "custom" and got["key"] == "SERIALA" and got["cache"] is cloud_status._ENERGY_CACHE


def test_custom_is_a_time_span_with_the_same_slots_as_cloud():
    assert "['custom', 'Custom']" in JS
    body = JS[JS.index("function analyticsRangeKind("):][:500]
    assert re.search(r"<= 2 \* 86400\) return 'day5'", body)
    assert re.search(r"<= 31 \* 86400\) return 'dayhour'", body)
    assert re.search(r"<= 366 \* 86400\) return 'month'", body)
    assert "return 'year'" in body
    # every slot choice reads the kind, so Custom draws like the period it matches
    assert "get energyMode() { return this.kind !== 'day5'; }" in JS
    assert "analyticsSlotEdges(this.kind," in JS
    assert "slotTickLabel(start) {\n      if (this.kind === 'dayhour')" in JS


def test_the_range_is_remembered_and_reaches_cloud():
    assert "'fwh-analytics-range'" in JS
    load = JS[JS.index("async load() {"):][:900]
    assert "this._cloud.setRange(this.range.from, this.range.to)" in load
    mount = JS[JS.index("FWHCloudAnalytics.mount("):][:1400]
    assert "...this.cloudRange," in mount
    assert "if (this.period === 'custom') return { range: this.rangeOrDefault };" in JS
    flow = JS[JS.index("async loadFlow(refresh) {"):][:900]
    assert "period=custom&from=" in flow


def test_from_and_to_buttons_open_a_calendar_with_a_styled_time_grid():
    assert 'aria-label="From"' in HTML and 'aria-label="To"' in HTML
    assert "x-show=\"period === 'custom'\"" in HTML
    assert 'role="group" aria-label="Hour"' in HTML and 'role="group" aria-label="Minute"' in HTML
    assert "<select" not in HTML[HTML.index('aria-label="Pick a date"'):HTML.index("<!-- Cloud:")]   # no browser lists
    assert "Apply" in HTML and "rangeErr" in HTML


def test_the_cloud_extra_has_custom_ranges():
    assert "franklinwh-ha-cloud-analytics==0.1.26" in (PKG.parents[1] / "pyproject.toml").read_text()


def test_hourly_slots_start_at_the_ranges_own_hour():
    # a range from 22:00 has its first hourly slot at 22:00, not at that day's midnight
    body = JS[JS.index("function analyticsSlotEdges("):][:900]
    assert "f.getUTCHours()" in body and "at(y, m, d, h0 + i)" in body
