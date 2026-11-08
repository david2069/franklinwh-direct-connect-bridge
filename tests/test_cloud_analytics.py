"""Analytics → Cloud (#215 phase 1): the route, the shared panel, and the Local | Cloud switch."""
import asyncio
import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import cloud_status, config, providers, site_time, state

PKG = pathlib.Path(app_module.__file__).parent
TAB = (PKG / "templates" / "tabs" / "analytics.html").read_text()
JS = (PKG / "static" / "js" / "analytics_tab.js").read_text()
INDEX = (PKG / "templates" / "index.html").read_text()


@pytest.fixture
def env(monkeypatch):
    state.reset_gateways()
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    monkeypatch.setenv("FWH_CLOUD_EMAIL", "a@b.c")
    monkeypatch.setenv("FWH_CLOUD_PASSWORD", "x")
    monkeypatch.delenv("FWH_CLOUD_GATEWAY", raising=False)
    monkeypatch.setattr(config, "_settings", None)
    gw = state.register_gateway("gw-a", "10.0.0.1", "A")
    gw.serial, gw.serial_locked = "seriala", True
    calls = []

    def read(email, password, serial, period, on, today, refresh=False):
        calls.append((serial, period, on, today, refresh))
        return {"source": "cloud", "period": period, "date": on.isoformat(), "series": []}

    monkeypatch.setattr(cloud_status, "read_energy", read)
    monkeypatch.setattr(site_time, "now_known",
                        lambda host=None: dt.datetime(2026, 11, 9, 8, 0,
                                                      tzinfo=dt.timezone(dt.timedelta(hours=11))))
    yield {"calls": calls, "gw": gw, "mp": monkeypatch}
    monkeypatch.setattr(config, "_settings", None)
    state.reset_gateways()


def _get(q):
    return TestClient(app_module.create_app()).get("/api/analytics/cloud" + q)


def test_reads_the_viewed_gateway_on_the_sites_calendar(env):
    r = _get("?gateway=gw-a&period=month&date=2026-11-05")
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "cloud"
    assert env["calls"] == [("seriala", "month", dt.date(2026, 11, 5), dt.date(2026, 11, 9), False)]
    _get("?gateway=gw-a&period=day5&refresh=1")              # no date: the site's today
    assert env["calls"][-1] == ("seriala", "day5", dt.date(2026, 11, 9), dt.date(2026, 11, 9), True)


def test_says_why_when_there_is_no_cloud_account(env):
    env["mp"].delenv("FWH_CLOUD_EMAIL")
    env["mp"].setattr(config, "_settings", None)
    r = _get("?gateway=gw-a&period=month")
    assert r.status_code == 200 and "cloud account" in r.json()["error"]
    assert env["calls"] == []


def test_a_mock_gateway_has_no_cloud_data(env):
    env["gw"].is_mock = True
    r = _get("?gateway=gw-a&period=month")
    assert "mock" in r.json()["error"].lower() and env["calls"] == []


def test_a_bad_period_or_date_is_a_400(env):
    assert _get("?gateway=gw-a&period=ytd").status_code == 400
    assert _get("?gateway=gw-a&period=month&date=5/11/2026").status_code == 400


def test_a_cloud_failure_is_shown_not_raised(env):
    def boom(*a, **k):
        raise RuntimeError("code 429")
    env["mp"].setattr(cloud_status, "read_energy", boom)
    r = _get("?gateway=gw-a&period=month")
    assert r.status_code == 200 and "429" in r.json()["error"]


def test_read_energy_makes_one_library_call_and_caches_per_gateway(monkeypatch):
    calls = []

    class Fake:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get_power_details(self, type, timeperiod):
            calls.append((type, timeperiod))
            return {"deviceTimeArray": ["2026-11-01"], "kwhLoadArray": [1.0]}

    async def client_for(email, password, gateway, source="status"):
        assert source == "analytics"
        return Fake()

    monkeypatch.setattr(cloud_status, "_client_for", client_for)
    cloud_status._ENERGY_CACHE = None
    one = lambda refresh=False: cloud_status.read_energy(
        "a@b.c", "x", "SERIALA", "month", dt.date(2026, 10, 5), dt.date(2026, 11, 9), refresh)
    p = one()
    one()
    assert calls == [(3, "2026-10-01")] and p["chart"] == "bars"
    one(refresh=True)
    assert len(calls) == 2


def test_the_panel_is_served_from_the_shared_package():
    c = TestClient(app_module.create_app())
    assert c.get("/cloud-analytics/cloud-analytics.js").status_code == 200
    assert 'cloud-analytics/cloud-analytics.css' in INDEX and 'cloud-analytics/cloud-analytics.js' in INDEX


def test_analytics_has_a_local_cloud_switch_that_mounts_the_panel():
    assert "setSource('local')" in TAB and "setSource('cloud')" in TAB
    assert 'x-ref="cloud"' in TAB
    assert "FWHCloudAnalytics.mount(" in JS and "fwh-analytics-source" in JS
    assert "selectedGateway" in JS[JS.index("FWHCloudAnalytics.mount("):][:300]


SETTINGS = (PKG / "templates" / "tabs" / "settings.html").read_text()


def test_the_cloud_view_links_to_the_cloud_account_card():
    # Owner, 2026-11-09: the cloud view needs a link to where the credentials go.
    assert "openCloudSettings()" in TAB
    body = JS[JS.index("openCloudSettings()"):][:400]
    assert "setActiveTab('settings')" in body and "fwh-open-settings" in body
    assert 'id="settings-cloud-api"' in SETTINGS
    assert "@fwh-open-settings.window" in SETTINGS


def test_the_local_cloud_switch_is_its_own_row_and_full_size():
    # Owner, 2026-11-09: the switch was too small and lost in the middle of the header.
    sw = TAB[TAB.index('aria-label="Source"') - 300:][:1200]
    assert "text-xs" not in sw and "text-sm" in sw
    assert TAB.index('aria-label="Source"') > TAB.index("</h1>")
