"""Troubleshoot shows only what a fresh reading supports (owner 2026-11-18, #728).

On the owner's bridge the aGate stopped answering :9000 at 12:29. At 12:32 the panel's
Connection card still said "LAN: answering on :9000" (fewer failed probes than
LINK_STRIKES, so the link record was still "up"), while the Health check, probing afresh,
said :9000 refused. The 4G verdict came from the aGate's own 1118 report with no time
on it, and a cloud call that failed read "not asked"."""
import pathlib
import time

from franklinwh_direct_connect_bridge import cloud_status, troubleshoot

from test_troubleshoot_614 import G, _lan, env  # noqa: F401 — the shared fixture

PKG = pathlib.Path(troubleshoot.__file__).parent


def test_an_old_last_good_is_not_answering_even_before_the_link_is_marked_down(env):
    store = env["store"]
    t0 = time.time() - 180
    store.record_link_probe("gw-a", "ok", now=t0)
    store.record_link_probe("gw-a", "failed", now=t0 + 30)       # 1 strike: still "up"
    lan = troubleshoot.lan_state(store, "gw-a", poll_interval_s=30)
    assert lan["up"] is False and lan["state"] == "stale"
    # the card and the health check's "last good poll" use the one rule
    rows = troubleshoot.health({"ping": True, "local_api": False}, lan, 30)
    assert [r for r in rows if r["key"] == "last_good"][0]["ok"] is False
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["lan"]["up"] is False and d["lan"]["state"] == "stale"
    js = (PKG / "static" / "js" / "troubleshoot.js").read_text()
    assert "l.state === 'stale'" in js


def test_a_fresh_last_good_still_answers(env):
    _lan(env["store"], "ok")
    lan = troubleshoot.lan_state(env["store"], "gw-a", poll_interval_s=30)
    assert lan["up"] is True and lan["state"] == "up"


def test_the_agates_own_4g_report_carries_its_reading_time(env):
    """Cloud unavailable: the verdict comes from 1118, and says when it was read."""
    env["mp"].delenv("FWH_CLOUD_EMAIL")
    from franklinwh_direct_connect_bridge import config
    env["mp"].setattr(config, "_settings", None)
    _lan(env["store"], "ok")
    gw = env["gw"]
    gw.last_state = {"net_cloud_via": "4G"}
    gw.net_read_ts = time.time() - 120
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["verdict"]["code"] == "on_4g"
    assert d["verdict"]["source"] == "agate" and abs(d["verdict"]["as_of_ts"] - gw.net_read_ts) < 1
    js = (PKG / "static" / "js" / "troubleshoot.js").read_text()
    assert "verdictSource" in js
    html = (PKG / "templates" / "partials" / "troubleshoot.html").read_text()
    assert "$store.troubleshoot.verdictSource" in html


def test_a_4g_report_older_than_two_network_reads_is_not_used(env):
    env["mp"].delenv("FWH_CLOUD_EMAIL")
    from franklinwh_direct_connect_bridge import config, poller
    env["mp"].setattr(config, "_settings", None)
    _lan(env["store"], "ok")
    env["gw"].last_state = {"net_cloud_via": "4G"}
    env["gw"].net_read_ts = time.time() - 3 * poller.NET_EVERY_S
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["verdict"]["code"] == "online_lan"
    # and with no reading time at all
    env["gw"].net_read_ts = None
    assert env["c"].get("/api/troubleshoot/connectivity?" + G).json()["verdict"]["code"] == "online_lan"


def test_the_cloud_verdict_says_it_is_the_clouds_answer_now(env):
    _lan(env["store"], "ok")
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["verdict"]["code"] == "on_4g" and d["verdict"]["source"] == "cloud"


def test_a_cloud_call_that_failed_is_asked_not_not_asked(env):
    env["mp"].setattr(cloud_status, "read_connectivity", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("bad answer")))
    _lan(env["store"], "ok")
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["cloud"]["available"] is False and d["cloud"]["asked"] is True
    assert "RuntimeError" in d["cloud"]["reason"]
    js = (PKG / "static" / "js" / "troubleshoot.js").read_text()
    assert "c.asked" in js


def test_the_poller_records_when_it_read_the_network():
    src = (PKG / "poller.py").read_text()
    assert "gw.net_read_ts = time.time()" in src
