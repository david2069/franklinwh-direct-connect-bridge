"""Network → Cloud requests (owner 2026-11-18, FWHAI's API Metrics as the target).

The franklinwh-cloud ``get_metrics()`` snapshot each cloud poll already takes carries the
call counters: total_api_calls, calls_by_method, total_errors, errors_by_type (timeout,
auth_401, server_5xx, network, parse), retry_count, token_refresh_count, login_count. Each
poll uses a fresh Client, so a snapshot is that poll's counts; they are kept with the PoP
sample and summed over the chosen period. No extra cloud traffic.
"""
import pathlib
import time

from franklinwh_direct_connect_bridge import cloud_pop, cloud_status
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


def _edge(pop="SYD62-P1", api=None):
    e = {"current_pop": pop, "total_cf_requests": 3, "cache_hits": 0, "cache_misses": 3,
         "last_cf_trace_id": "t=="}
    if api is not None:
        e["api"] = api
    return e


def _api(get=2, post=1, net=0, a401=0, retries=0, refresh=0, logins=0):
    return {"total_api_calls": get + post, "calls_by_method": {"GET": get, "POST": post},
            "total_errors": net + a401,
            "errors_by_type": {"timeout": 0, "auth_401": a401, "server_5xx": 0,
                               "network": net, "parse": 0},
            "retry_count": retries, "token_refresh_count": refresh, "login_count": logins}


def test_api_counters_are_kept_and_summed(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    cloud_pop.ingest(st, _edge(api=_api(get=2, post=1)))
    cloud_pop.ingest(st, _edge(api=_api(get=3, post=0, net=2, a401=1, retries=1, refresh=1)))
    cloud_pop.ingest(st, _edge())                      # an older poll without counters
    api = cloud_pop.summary(st)["api"]
    assert api["samples"] == 2
    assert api["total_api_calls"] == 6
    assert api["calls_by_method"] == {"GET": 5, "POST": 1}
    assert api["total_errors"] == 3
    assert api["errors_by_type"] == {"timeout": 0, "auth_401": 1, "server_5xx": 0,
                                     "network": 2, "parse": 0}
    assert api["retry_count"] == 1 and api["token_refresh_count"] == 1
    assert api["login_count"] == 0


def test_no_counters_yet_is_none(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    cloud_pop.ingest(st, _edge())
    assert cloud_pop.summary(st)["api"] is None


def test_period_today_counts_only_since_midnight(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    cloud_pop.ingest(st, _edge(api=_api(get=4, post=0)))
    with st._lock:                                       # one sample from two days ago
        st._conn.execute("UPDATE cloud_pop_samples SET ts = ts - 2*86400")
        st._conn.commit()
    cloud_pop.ingest(st, _edge(api=_api(get=1, post=0)))
    assert cloud_pop.summary(st, period="today")["api"]["total_api_calls"] == 1
    assert cloud_pop.summary(st, period="7d")["api"]["total_api_calls"] == 5
    assert cloud_pop.summary(st, period="today")["period"] == "today"


def test_the_poll_passes_the_counters_with_the_edge(monkeypatch):
    class FakeCloud:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get_stats(self):
            class S: current = {}
            return S()
        async def get_programme_info(self): return []
        async def get_gateway_alarm(self): return []
        def get_metrics(self):
            return {**_api(get=2, post=1), "uptime_s": 1.0, "edge": _edge()}

    async def fake_client_for(*a, **k): return FakeCloud()
    monkeypatch.setattr(cloud_status, "_client_for", fake_client_for)
    _cur, _prog, edge, _al = cloud_status._read_sync("a@example.com", "pw", None)
    assert edge["current_pop"] == "SYD62-P1"
    assert edge["api"]["calls_by_method"] == {"GET": 2, "POST": 1}
    assert edge["api"]["errors_by_type"]["network"] == 0
    assert "uptime_s" not in edge["api"]                 # only the counters are kept


def test_the_network_card_has_the_tables():
    html = (PKG / "templates" / "tabs" / "network.html").read_text()
    for tid in ('data-testid="cloud-requests"', 'data-testid="cloud-errors"',
                'data-testid="pop-period"'):
        assert tid in html, tid
    assert ">Metric<" in html and ">Count<" in html and ">Category<" in html
    js = (PKG / "static" / "js" / "network_tab.js").read_text()
    assert "api/cloud/pop?period=" in js


# ── PoP map and time on each PoP (owner 2026-11-18, FWHAI's map as the target) ──────────

def test_all_period_and_the_stay_on_each_pop(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    for pop in ["SYD62-P1", "BNE50-P3", "SYD62-P1"]:
        cloud_pop.ingest(st, _edge(pop))
    with st._lock:                                       # 0 s, 30 s, 90 s after the first
        ids = [r[0] for r in st._conn.execute("SELECT id FROM cloud_pop_samples ORDER BY id")]
        t0 = time.time() - 600
        for i, off in zip(ids, (0, 30, 90)):
            st._conn.execute("UPDATE cloud_pop_samples SET ts=? WHERE id=?", (t0 + off, i))
        st._conn.commit()
    s = cloud_pop.summary(st, period="all")
    assert s["period"] == "all"
    newest, oldest = s["transitions"]
    assert (newest["from"], newest["to"]) == ("BNE50-P3", "SYD62-P1")
    assert newest["stay_s"] == 60                        # BNE50-P3 from 30 s to 90 s
    assert oldest["stay_s"] is None                      # its start is before the window


def test_pops_are_placed_at_their_city_and_unknown_ones_are_listed_only(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    for pop in ["SYD62-P1", "SYD62-P1", "LAX50-P5", "ZZZ9-P1"]:
        cloud_pop.ingest(st, _edge(pop))
    loc = cloud_pop.summary(st)["locations"]
    assert loc["SYD62-P1"]["city"] == "Sydney" and -35 < loc["SYD62-P1"]["lat"] < -33
    assert loc["LAX50-P5"]["city"] == "Los Angeles"
    assert loc["ZZZ9-P1"] is None                        # listed in the table, not plotted
    for code in ("SYD", "BNE", "MEL", "PER", "ADL", "AKL", "LAX", "SFO", "SEA", "MIA",
                 "IAD", "JFK", "ORD", "DFW", "SIN", "NRT", "HKG", "LHR", "FRA"):
        assert code in cloud_pop.POP_CITIES, code


def test_the_map_dialog_is_wired_and_says_when_offline():
    html = (PKG / "templates" / "tabs" / "network.html").read_text()
    for tid in ('data-testid="pop-map-open"', 'data-testid="pop-map-dialog"',
                'data-testid="pop-map-offline"', 'data-testid="pop-map-transitions"'):
        assert tid in html, tid
    assert (PKG / "static" / "js" / "leaflet-1.9.4.min.js").exists()
    assert (PKG / "static" / "css" / "leaflet-1.9.4.css").exists()
    js = (PKG / "static" / "js" / "network_tab.js").read_text()
    assert "leaflet-1.9.4.min.js" in js and "tileerror" in js
    assert "openstreetmap.org/copyright" in js           # tile attribution shown
