"""#614: aGate unreachable or on 4G — the cloud connectivity check, the Troubleshoot panel's
health check, Reconnect to Wi-Fi, and the banner's recovery states. The FranklinWH cloud is
always a fake here: no login, no aGate."""
import logging
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (alerts, app as app_module, client as client_mod,
                                               cloud_status, config, db, environment, logbuffer,
                                               providers, security, state, tls, troubleshoot)

PKG = pathlib.Path(app_module.__file__).parent
SECRET = "S3cretWifiPassw0rd"
G = "gateway=gw-a"


def _net(active: str) -> dict:
    """The library's get_network_state() shape, as much of it as the bridge reads."""
    ids = {"eth0": 1, "wifi": 3, "4g": 4}
    return {"active": {"id": ids[active], "key": active, "label": active},
            "interfaces": [{"id": 3, "key": "wifi", "link": active == "wifi",
                            "ip": None if active == "4g" else "192.0.2.10"}],
            "available_transports": [active],
            "cloud": {"gateway_reachable": True, "aws_connected": True, "internet": True}}


class FakeCloud:
    """franklinwh-cloud's Client, faked: the aGate's stored Wi-Fi password is in its 337
    answer, as on the real thing, so a leak anywhere downstream would show."""

    def __init__(self, active="4g", offline=False, switch=None, ssid="HomeNet"):
        self.active, self.offline, self.switch, self.ssid = active, offline, switch, ssid
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_network_state(self):
        if self.offline:
            from franklinwh_cloud.exceptions import GatewayOfflineException
            raise GatewayOfflineException("Device offline")
        return _net(self.active)

    async def get_connectivity_overview(self, deep_scan: bool = False):
        # deep_scan=True pings the Modbus TCP Server (aGate :502): never allowed (#614).
        self.calls.append({"overview_deep_scan": deep_scan})
        assert deep_scan is False, "deep_scan=True probes the aGate's :502"
        return {"primary": {"id": 4, "name": "4G Mobile"}, "cloud_connected": True}

    async def get_wifi_config(self):
        return {"wifi_ssid": self.ssid, "wifi_password": SECRET, "ap_ssid": "FWH-AP",
                "ap_password": "ap-" + SECRET}

    async def switch_to_wifi(self, ssid, password=None, *, confirm=False, **kw):
        self.calls.append({"ssid": ssid, "password": password, "confirm": confirm, **kw})
        if isinstance(self.switch, Exception):
            raise self.switch
        return self.switch


@pytest.fixture
def env(monkeypatch):
    state.reset_gateways()
    alerts.reset()
    troubleshoot.reset()
    monkeypatch.setattr(providers, "_lib_available", lambda m: True)
    monkeypatch.setenv("FWH_CLOUD_EMAIL", "a@b.c")
    monkeypatch.setenv("FWH_CLOUD_PASSWORD", "x")
    monkeypatch.delenv("FWH_CLOUD_GATEWAY", raising=False)
    monkeypatch.setattr(config, "_settings", None)
    s = config.get_settings()
    gw = state.register_gateway("gw-a", "10.0.0.1", "A")
    gw.serial, gw.serial_locked = "SERIALA", True
    fake = FakeCloud()

    async def client_for(email, password, gateway, source="status"):
        assert gateway == "SERIALA"
        return fake

    monkeypatch.setattr(cloud_status, "_client_for", client_for)
    store = db.get_store(s)
    logbuffer.set_store(store)
    yield {"gw": gw, "cloud": fake, "store": store, "mp": monkeypatch,
           "c": TestClient(app_module.create_app())}
    alerts.reset()
    troubleshoot.reset()
    monkeypatch.setattr(config, "_settings", None)
    state.reset_gateways()


def _lan(store, outcome, now=None):
    for _ in range(store.LINK_STRIKES if outcome != "ok" else 1):
        store.record_link_probe("gw-a", outcome, now=now)


# ── 1. the connectivity verdict ──────────────────────────────────────────────
def test_cloud_says_4g_while_the_lan_works_is_a_warning(env):
    _lan(env["store"], "ok")
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["lan"]["up"] is True
    assert d["cloud"]["available"] is True and d["cloud"]["connection"] == "4g"
    assert d["verdict"]["code"] == "on_4g" and d["verdict"]["severity"] == "warning"
    assert "using 4G" in d["verdict"]["text"]
    assert d["stored_ssid"] == "HomeNet" and d["can_reconnect"] is True
    # The same fact the poller's local read publishes; the monitor opens it after open_s.
    f = alerts.facts()[("gw-a", "AGATE_ON_4G")]
    assert f["bad"] is True
    spec = alerts.CATALOGUE["AGATE_ON_4G"]
    assert spec["severity"] == alerts.WARNING and spec["kind"] == alerts.CONDITION
    assert spec["title"] == "aGate is using 4G — Wi-Fi has no internet"
    opened = alerts.evaluate(env["store"], now=f["since"] + spec["open_s"])
    assert [(x["code"], x["change"]) for x in opened] == [("AGATE_ON_4G", "opened")]


def test_lan_up_and_on_wifi_raises_nothing(env):
    env["cloud"].active = "wifi"
    _lan(env["store"], "ok")
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["verdict"]["code"] == "online" and d["verdict"]["severity"] == "ok"
    assert d["can_reconnect"] is False and d["stored_ssid"] is None
    assert alerts.facts()[("gw-a", "AGATE_ON_4G")]["bad"] is False


def test_on_4g_while_the_lan_is_down_says_it_left_wifi(env):
    _lan(env["store"], "failed")
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["lan"]["up"] is False
    assert d["verdict"]["code"] == "left_wifi" and "4G" in d["verdict"]["text"]
    assert d["can_reconnect"] is True
    # Not "on 4G while the LAN works": unreachable is GATEWAY_UNREACHABLE's alone.
    assert alerts.facts().get(("gw-a", "AGATE_ON_4G"), {"bad": False})["bad"] is False


def test_offline_everywhere(env):
    env["cloud"].offline = True
    _lan(env["store"], "failed")
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["cloud"]["available"] is True and d["cloud"]["reachable"] is False
    assert d["verdict"]["code"] == "offline" and d["verdict"]["severity"] == "critical"
    assert "power" in d["verdict"]["text"] and d["can_reconnect"] is False


def test_without_a_cloud_account_the_verdict_is_the_lans(env):
    env["mp"].delenv("FWH_CLOUD_EMAIL")
    env["mp"].setattr(config, "_settings", None)
    _lan(env["store"], "failed")
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["cloud"]["available"] is False and "cloud account" in d["cloud"]["reason"]
    assert d["verdict"]["code"] == "unreachable" and d["can_reconnect"] is False
    assert env["cloud"].calls == []


def test_a_mock_gateway_never_asks_the_cloud(env):
    env["gw"].is_mock = True
    d = env["c"].get("/api/troubleshoot/connectivity?" + G).json()
    assert d["cloud"]["available"] is False and "mock" in d["cloud"]["reason"].lower()


def test_the_pollers_local_read_raises_the_same_warning():
    """1118 currentNetType = 4G while the poll answers: the LAN works, the internet is 4G."""
    alerts.reset()
    troubleshoot.note_local_network("gw-x", True, {"net_cloud_via": "4G"}, now=10.0)
    assert alerts.facts()[("gw-x", "AGATE_ON_4G")] == {
        "bad": True, "since": 10.0, "detail": alerts.facts()[("gw-x", "AGATE_ON_4G")]["detail"]}
    troubleshoot.note_local_network("gw-x", True, {"net_cloud_via": "WiFi"}, now=20.0)
    assert alerts.facts()[("gw-x", "AGATE_ON_4G")]["bad"] is False
    troubleshoot.note_local_network("gw-x", True, {"net_cloud_via": "4G"}, now=30.0)
    troubleshoot.note_local_network("gw-x", False, {"net_cloud_via": "4G"}, now=40.0)
    assert alerts.facts()[("gw-x", "AGATE_ON_4G")]["bad"] is False   # LAN down: not this alert
    alerts.reset()


# ── 2. the health check: LAN, :9000, the cloud link, last good — never :502 ──
class _Local:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self): pass
    def network_interfaces(self): return {"result": {"commSetPara": {"awsStatus": 1, "currentNetType": 3}}}


def test_health_check_never_probes_502(env):
    def no_502(*a, **k):
        raise AssertionError(":502 must not be probed")

    env["mp"].setattr(client_mod, "_probe_modbus", no_502)
    env["mp"].setattr(client_mod, "_modbus_last", no_502)
    env["mp"].setattr(client_mod, "_client", lambda s, host=None: _Local())
    env["mp"].setattr(client_mod.discover, "ping", lambda host, timeout=1.0: True)
    _lan(env["store"], "ok")
    d = env["c"].get("/api/troubleshoot/health?" + G).json()
    assert [x["key"] for x in d["checks"]] == ["lan", "local_api", "cloud_link", "last_good"]
    assert all(x["ok"] is True for x in d["checks"]), d
    assert "502" not in str(d)


def test_health_check_fails_each_leg_on_a_dead_agate(env):
    class Dead(_Local):
        def login(self): raise OSError("connect to 10.0.0.1:9000 failed")

    env["mp"].setattr(client_mod, "_client", lambda s, host=None: Dead())
    env["mp"].setattr(client_mod.discover, "ping", lambda host, timeout=1.0: False)
    d = env["c"].get("/api/troubleshoot/health?" + G).json()
    by = {x["key"]: x for x in d["checks"]}
    assert by["lan"]["ok"] is False and by["local_api"]["ok"] is False
    assert "9000" in by["local_api"]["detail"]
    assert by["cloud_link"]["ok"] is None          # not read: unknown, not a fail
    assert by["last_good"]["ok"] is False


# ── 3. the banner's recovery state ───────────────────────────────────────────
def test_recovery_inside_the_confirm_window_and_the_drop_count(env):
    st, now = env["store"], time.time()
    # Two drops: 25 min ago and 10 min ago, the link back 30 s ago.
    for t0, t1 in ((now - 1500, now - 1200), (now - 600, now - 30)):
        for i in range(st.LINK_STRIKES):
            st.record_link_probe("gw-a", "failed", now=t0 + i)
        st.record_link_probe("gw-a", "ok", now=t1)
    alerts.set_condition("gw-a", "GATEWAY_UNREACHABLE", True, now=now - 1500)
    aid = alerts.evaluate(st, now=now - 1100)[0]["id"]
    alerts.set_condition("gw-a", "GATEWAY_UNREACHABLE", False, now=now - 30)
    row = next(r for r in env["c"].get("/api/alerts?open=1").json()["alerts"] if r["id"] == aid)
    rec = row["recovering"]
    resolve_s = alerts.CATALOGUE["GATEWAY_UNREACHABLE"]["resolve_s"]
    assert resolve_s - 32 <= rec["resolves_in_s"] <= resolve_s - 29
    assert row["drops"]["count"] == 2 and 24 * 60 <= row["drops"]["window_s"] <= 26 * 60
    # Past the window it resolves: no longer "confirming", and no drop count.
    alerts.evaluate(st, now=now - 30 + resolve_s)
    row = next(r for r in env["c"].get("/api/alerts").json()["alerts"] if r["id"] == aid)
    assert row["resolved_ts"] and row["recovering"] is None and "drops" not in row


def test_a_still_bad_condition_is_not_recovering(env):
    st = env["store"]
    alerts.set_condition("gw-a", "GATEWAY_UNREACHABLE", True, now=time.time() - 400)
    alerts.evaluate(st)
    row = env["c"].get("/api/alerts?open=1").json()["alerts"][0]
    assert row.get("recovering") is None


def test_the_bar_says_reconnecting_and_opens_troubleshoot():
    js = (PKG / "static/js/alerts.js").read_text()
    idx = (PKG / "templates/index.html").read_text()
    assert "'Reconnecting'" in js and "— confirming (resolves in ${a.recovering.resolves_in_s} s)" in js
    assert "dropped ${" in js and "× in ${" in js
    bar = idx[idx.index("Red bar (#271)"):idx.index("── Content")]
    assert "$store.alerts.barClick(a)" in bar
    assert "Alpine.store('troubleshoot').open(a.gateway_id)" in js
    # The list is re-read while a condition is open, so the countdown moves.
    assert "openConditions" in js


# ── 4. Reconnect to Wi-Fi ────────────────────────────────────────────────────
def _connected():
    return {"requested": {"ssid": "HomeNet", "password_source": "stored"},
            "preflight": {"passed": True, "reasons": []}, "write_ack": {"accepted": True},
            "verification": {"state": "connected", "elapsed_s": 42.0,
                             "after": {"type_id": 3, "type": "wifi", "ip": "192.0.2.10"}}}


def _run(c, body):
    r = c.post("/api/troubleshoot/reconnect-wifi?" + G, json=body)
    if r.status_code != 202:
        return r, None
    for _ in range(200):
        d = c.get("/api/troubleshoot/reconnect-wifi?" + G).json()
        if d["state"] == "done":
            return r, d["result"]
        time.sleep(0.02)
    raise AssertionError("reconnect never finished")


def test_reconnect_success(env):
    env["cloud"].switch = _connected()
    r, res = _run(env["c"], {"ssid": "HomeNet", "confirm": True})
    assert r.status_code == 202
    assert res["ok"] is True and res["outcome"] == "connected"
    call = env["cloud"].calls[0]
    assert call["ssid"] == "HomeNet" and call["password"] is None and call["confirm"] is True
    assert "allow_no_fallback" not in call                 # never overridden


def test_reconnect_failure_falls_back_to_the_app(env):
    env["cloud"].switch = {**_connected(), "verification": {
        "state": "timeout", "elapsed_s": 180.0, "recovery_hint": "not confirmed"}}
    _, res = _run(env["c"], {"ssid": "HomeNet", "confirm": True})
    assert res["ok"] is False and res["outcome"] == "timeout" and res["use_app"] is True


def test_reconnect_refused_with_no_fallback(env):
    env["cloud"].switch = {**_connected(), "write_ack": None,
                           "preflight": {"passed": False,
                                         "reasons": ["no fallback transport would remain"]},
                           "verification": {"state": "skipped", "reason": "preflight refused"}}
    _, res = _run(env["c"], {"ssid": "HomeNet", "confirm": True})
    assert res["ok"] is False and res["outcome"] == "refused" and res["use_app"] is True
    assert res["reasons"] == ["no fallback transport would remain"]


def test_reconnect_when_the_stored_ssid_changed(env):
    env["cloud"].switch = ValueError("no password given for SSID Ho***")
    _, res = _run(env["c"], {"ssid": "HomeNet", "confirm": True})
    assert res["ok"] is False and res["outcome"] == "ssid_changed" and res["use_app"] is True


def test_reconnect_needs_confirm_and_a_cloud_account(env):
    r = env["c"].post("/api/troubleshoot/reconnect-wifi?" + G, json={"ssid": "HomeNet"})
    assert r.status_code == 428
    env["mp"].delenv("FWH_CLOUD_EMAIL")
    env["mp"].setattr(config, "_settings", None)
    r = env["c"].post("/api/troubleshoot/reconnect-wifi?" + G,
                      json={"ssid": "HomeNet", "confirm": True})
    assert r.status_code == 409 and "cloud account" in r.json()["detail"]
    assert env["cloud"].calls == []


def test_no_password_in_any_response_or_log(env, caplog):
    caplog.set_level(logging.DEBUG)
    env["cloud"].switch = _connected()
    _lan(env["store"], "ok")
    c = env["c"]
    bodies = [c.get("/api/troubleshoot/connectivity?" + G).text]
    r, res = _run(c, {"ssid": "HomeNet", "confirm": True})
    bodies += [r.text, str(res), c.get("/api/troubleshoot/reconnect-wifi?" + G).text,
               c.get("/api/logs").text, c.get("/api/control-log").text]
    for b in bodies:
        assert SECRET not in b
    assert SECRET not in caplog.text
    assert all(SECRET not in str(e) for e in logbuffer.get_logs(limit=5000))


# ── 5. admin only ────────────────────────────────────────────────────────────
ING = {"X-Ingress-Path": "/api/hassio_ingress/x", "X-Remote-User-Name": "dana"}


@pytest.mark.security_on
@pytest.mark.parametrize("group", ["system-users", "system-read-only"])
def test_a_non_admin_cannot_reconnect(env, group, monkeypatch):
    monkeypatch.setattr(environment, "IS_HA_ADDON", True)
    monkeypatch.setattr(tls, "running", lambda: True)
    security.set_enabled(env["store"], True)
    c = TestClient(app_module.create_app(), client=("172.30.32.2", 5000))
    h = dict(ING, **{"X-Remote-User-Groups": group})
    r = c.post("/api/troubleshoot/reconnect-wifi?" + G, json={"ssid": "HomeNet", "confirm": True},
               headers=h)
    assert r.status_code == 403 and env["cloud"].calls == []
    # Reading the verdict is for everyone; it says this viewer can't reconnect.
    d = c.get("/api/troubleshoot/connectivity?" + G, headers=h).json()
    assert d["admin"] is False
    admin = dict(ING, **{"X-Remote-User-Groups": "system-admin"})
    assert c.get("/api/troubleshoot/connectivity?" + G, headers=admin).json()["admin"] is True


# ── 6. the panel ─────────────────────────────────────────────────────────────
def test_the_panel_has_verdict_health_network_steps_and_app_fallback():
    html = (PKG / "templates/partials/troubleshoot.html").read_text()
    js = (PKG / "static/js/troubleshoot.js").read_text()
    idx = (PKG / "templates/index.html").read_text()
    assert '{% include "partials/troubleshoot.html" %}' in idx
    assert "static/js/troubleshoot.js" in idx
    for needle in ("Health check", "Open Network", "Reconnect to Wi-Fi", "Use the FranklinWH app",
                   "dialog_msg("):
        assert needle in html, needle
    # One platform at a time.
    assert "platform === 'ios'" in html and "platform === 'android'" in html
    for step in ("Settings", "Network", "Wifi", "Configure", "choose your network",
                 "enter the password", "5 minutes"):
        assert step in js, step
    assert "confirmTyped(" in js                      # typed confirmation
    # The request names the stored network only: no password is ever sent.
    assert "JSON.stringify({ ssid: d.stored_ssid, confirm: true })" in js
    assert "wifi_password" not in js and "password:" not in js


def test_logs_range_select_shows_the_range_in_use():
    """Logs → 'Last 1h' showed entries from hours earlier (#614): the options are made by
    x-for after x-model ran, so the select displayed its FIRST option, 'Last 1h', while the
    range loaded was the default 24 h. Each option now says whether it is the one in use."""
    html = (PKG / "templates/tabs/logs.html").read_text()
    sel = html[html.index('x-model="range"'):]
    sel = sel[:sel.index("</select>")]
    assert ':selected="r.v === range"' in sel


def test_logs_since_filter_is_applied(env):
    st, now = env["store"], time.time()
    st.log_line(now - 7 * 3600, "INFO", 20, "franklinwh_direct_connect_bridge.poller", "old")
    st.log_line(now - 600, "INFO", 20, "franklinwh_direct_connect_bridge.poller", "recent")
    got = env["c"].get(f"/api/logs?since={int(now - 3600)}").json()["entries"]
    assert [e["message"] for e in got if e["name"].endswith("poller")] == ["recent"]


def test_never_a_deep_scan_that_probes_502(env):
    """franklinwh-cloud get_connectivity_overview(deep_scan=True) pings the Modbus TCP Server
    (aGate :502). The bridge passes no deep_scan anywhere, and its connectivity check never
    makes a call that does."""
    import re
    for f in (PKG).rglob("*.py"):
        src = f.read_text()
        assert not re.search(r"deep_scan\s*=\s*True", src), f
        for m in re.finditer(r"get_connectivity_overview\(([^)]*)\)", src):
            assert m.group(1).strip() in ("", "deep_scan=False"), (f, m.group(0))
    _lan(env["store"], "ok")
    env["c"].get("/api/troubleshoot/connectivity?" + G)
    assert all(c.get("overview_deep_scan", False) is False for c in env["cloud"].calls)
