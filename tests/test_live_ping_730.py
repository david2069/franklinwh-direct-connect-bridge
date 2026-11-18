"""#730: Network → Latency test. Watch is a live ping until Stop: one round-trip a second
to the aGate's Local API, drop-outs marked with their start and length, running min / avg /
max / loss; it stops by itself after 15 min or when the page is left, one run at a time per
gateway. Next to it, the drop-outs of the last 24 h from the link history (no extra aGate
traffic). Never the Modbus TCP Server (aGate :502)."""
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, client as client_mod, config,
                                              db, environment, live_ping, state)
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
GW = "gw-lp"
G = f"gateway={GW}"


class _Fake:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self): pass
    def power_flow(self): return {}


@pytest.fixture
def env(tmp_path, monkeypatch):
    state.register_gateway(GW, "1.2.3.4", "Home")
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(client_mod, "_client", lambda s, host=None: _Fake())
    monkeypatch.setattr(live_ping, "_runs", {})
    yield TestClient(app_module.create_app()), st
    state.unregister_gateway(GW)


def test_one_live_run_per_gateway(env):
    c, _ = env
    assert c.get(f"/api/network/ping?count=1&run=a&{G}").status_code == 200
    r = c.get(f"/api/network/ping?count=1&run=b&{G}")
    assert r.status_code == 409 and "another" in r.json()["detail"].lower()
    c.post(f"/api/network/ping/stop?run=a&{G}")              # Stop frees it at once
    assert c.get(f"/api/network/ping?count=1&run=b&{G}").status_code == 200
    # a plain Ping aGate (no run) is never refused
    assert c.get(f"/api/network/ping?count=5&{G}").status_code == 200


def test_a_run_ends_by_itself_after_15_minutes_and_a_quiet_one_is_freed():
    runs = {}
    assert live_ping.claim(runs, GW, "a", now=0) == "ok"
    assert live_ping.claim(runs, GW, "a", now=live_ping.RUN_MAX_S + 1) == "expired"
    runs = {}
    live_ping.claim(runs, GW, "a", now=0)
    assert live_ping.claim(runs, GW, "b", now=1) == "busy"
    assert live_ping.claim(runs, GW, "b", now=live_ping.IDLE_S + 1) == "ok"   # a left the page
    assert live_ping.RUN_MAX_S == 15 * 60


def test_dropouts_of_the_last_24_hours_from_link_history(env):
    c, st = env
    now = time.time()
    with st._lock:
        st._conn.executemany(
            "INSERT INTO link_outages(gateway_id, leg, started_ts, ended_ts, attempts, last_error)"
            " VALUES (?,?,?,?,?,?)",
            [(GW, "local_9000", now - 3600, now - 3300, 4, "[Errno 113] Host is unreachable"),
             (GW, "local_9000", now - 2 * 86400, now - 2 * 86400 + 60, 3, "old"),
             (GW, "icmp", now - 600, now - 500, 3, "other leg"),
             (GW, "local_9000", now - 120, None, 5, "Connection refused")])
        st._conn.commit()
    d = c.get(f"/api/network/dropouts?{G}").json()
    assert d["hours"] == 24 and len(d["dropouts"]) == 2
    first, second = d["dropouts"]                              # newest first
    assert first["open"] is True and first["error"] == "Connection refused"
    assert second["duration_s"] == pytest.approx(300, abs=1)
    assert second["error"] == "[Errno 113] Host is unreachable"


def test_the_tab_shows_live_ping_and_dropouts():
    html = (PKG / "templates" / "tabs" / "network.html").read_text()
    js = (PKG / "static" / "js" / "network_tab.js").read_text()
    for tid in ("live-ping-stop", "live-ping-stats", "live-ping-drops", "dropouts-24h"):
        assert f'data-testid="{tid}"' in html, tid
    assert "Drop-outs in the last 24 h" in html
    assert "toggleWatch()" in html                             # Watch kept, now until Stop
    assert "api/network/ping/stop" in js and "api/network/dropouts" in js
    assert "502" not in js[js.index("toggleWatch()"):js.index("get watchMax")]
