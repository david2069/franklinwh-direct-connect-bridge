"""Scheduled health check, phase 1: the daily snapshot and the daily bridge-health report
(owner 2026-11-15: as in the Modbus bridge's design, adapted to Direct Connect data)."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import alerts, health_report as hr, workers
from franklinwh_direct_connect_bridge.db import MetricsStore

GWS = [{"id": "gw1", "name": "Home"}]


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    hr.set_weekly(s, False)             # the weekly report has its own tests
    yield s
    s.close()


@pytest.fixture
def reg():
    r = workers.Registry()
    w = r.register(workers.Worker(name="poller", concern="poll", cadence_s=30.0,
                                  restart_class=workers.RestartClass.FREE, kind="task"))
    w.beat(state=workers.WorkerState.RUNNING)
    return r


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))
        return ""


def ts(day, hh=0, mm=0):
    return dt.datetime.strptime(f"{day} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M").timestamp()


def poll(soc, chg, di, sun, uin, uout, load):
    return {"power": {"soc": soc, "kwh_fhp_chg": chg, "kwh_fhp_di": di, "kwh_sun": sun,
                      "kwh_uti_in": uin, "kwh_uti_out": uout, "kwh_load": load}}


# ── log patterns ──────────────────────────────────────────────────────────────
def test_pattern_takes_out_numbers_and_addresses_and_redact_hides_secrets():
    a = hr.pattern("AEMO fetch failed: 500 from 10.0.0.5:443 after 3.2 s")
    b = hr.pattern("AEMO fetch failed: 502 from 192.168.1.9 after 12 s")
    assert a == b
    assert "hunter2" not in hr.redact("admin password: hunter2")
    assert "abc123" not in hr.redact("token=abc123 refused")


# ── the daily snapshot ────────────────────────────────────────────────────────
def test_snapshot_keeps_the_days_totals_and_counts_once(st):
    day = "2026-11-14"
    st.insert({"soc": 40}, int(ts(day, 0, 5)), "gw1", poll=poll(40, 0.1, 0, 0, 0.2, 0, 0.3))
    st.insert({"soc": 80}, int(ts(day, 23, 59)), "gw1",
              poll=poll(80, 9.5, 8.1, 20.0, 3.0, 4.5, 15.2))
    st.insert({"soc": 79}, int(ts("2026-11-15", 0, 1)), "gw1",
              poll=poll(79, 0, 0.1, 0, 0.1, 0, 0.1))     # next day: counters reset
    st.insert_alert(gateway_id="gw1", kind="event", severity="warning", code="X",
                    title="x", message="", opened_ts=ts(day, 9))
    st.log_line(ts(day, 10), "WARNING", 30, "fwh", "something odd")
    st.log_line(ts(day, 11), "ERROR", 40, "fwh", "something broke")
    n = hr.take_snapshot(st, day, ts(day), ts("2026-11-15"), ["gw1", "gw2"], now=ts("2026-11-15", 0, 2))
    assert n == 2                                         # gw1 and the bridge; gw2 had no poll
    rows = {r["gateway_id"]: r for r in st.health_snapshots(days=5)}
    g = rows["gw1"]
    assert (g["battery_charged_wh"], g["battery_discharged_wh"], g["solar_wh"]) == (9500, 8100, 20000)
    assert (g["grid_import_wh"], g["grid_export_wh"], g["load_wh"], g["soc"]) == (3000, 4500, 15200, 80)
    assert g["alerts"] == 1
    assert (rows[""]["log_warnings"], rows[""]["log_errors"], rows[""]["alerts"]) == (1, 1, 1)
    assert hr.take_snapshot(st, day, ts(day), ts("2026-11-15"), ["gw1"], now=ts("2026-11-15", 1)) == 0


# ── the daily report and its colour ───────────────────────────────────────────
def test_green_with_nothing_wrong(st, reg):
    r = hr.build_daily(st, ts("2026-11-15", 7), registry=reg, gateways=GWS)
    assert r["level"] == "green" and r["reasons"] == []
    assert r["headline"].startswith("Green: all 1 workers running")


def test_a_crashed_worker_or_an_active_critical_condition_is_red(st, reg):
    now = ts("2026-11-15", 7)
    w = reg.get("poller")
    w.state, w.last_error = workers.WorkerState.CRASHED, "boom"
    r = hr.build_daily(st, now, registry=reg, gateways=GWS)
    assert r["level"] == "red" and "worker poller crashed" in r["reasons"][0]

    reg2 = workers.Registry()
    aid = st.insert_alert(gateway_id="gw1", kind="condition", severity="critical",
                          code="GATEWAY_UNREACHABLE", title="aGate unreachable", message="",
                          opened_ts=now - 600)
    r = hr.build_daily(st, now, registry=reg2, gateways=GWS)
    assert r["level"] == "red" and r["reasons"][0].startswith("alert open: aGate unreachable")
    st.resolve_alert(aid, resolved_ts=now - 60)               # cleared, never acknowledged
    assert hr.build_daily(st, now, registry=reg2, gateways=GWS)["level"] == "green"


def test_an_error_in_the_log_or_a_failing_link_is_amber(st, reg):
    now = ts("2026-11-15", 7)
    st.log_line(now - 3600, "ERROR", 40, "fwh", "poll failed: timeout after 10 s")
    r = hr.build_daily(st, now, registry=reg, gateways=GWS)
    assert r["level"] == "amber" and "error: poll failed" in r["reasons"][0]
    assert r["logs"]["errors"] == 1

    st2 = MetricsStore(":memory:")
    for i in range(120):
        st2.record_link_probe("gw1", "failed" if i < 12 else "ok", now=now - 3600 + i)
    r = hr.build_daily(st2, now, registry=reg, gateways=GWS)
    assert r["level"] == "amber" and r["reasons"] == ["Home: 10% of polls failed"]
    assert r["link"][0]["probes"] == 120


def test_a_warning_pattern_counts_only_when_new_growing_or_all_day(st, reg):
    now = ts("2026-11-15", 7)
    for h in range(24):                                # every hour, never before: new, all day
        st.log_line(now - h * 3600 - 60, "WARNING", 30, "aemo", f"AEMO fetch failed: {500 + h}")
    r = hr.build_daily(st, now, registry=reg, gateways=GWS)
    p = r["logs"]["patterns"][0]
    assert p["count"] == 24 and p["flags"] == ["new", "all day"]
    assert r["level"] == "amber"


# ── the job: when it runs and where it goes ───────────────────────────────────
def test_tick_runs_once_after_seven_and_sends_to_ha(st, reg, monkeypatch):
    sent = []
    monkeypatch.setattr(hr, "_phones", lambda store, title, msg: sent.append(title))
    n = FakeNotifier()
    day = "2026-11-15"
    assert hr.tick(st, now=ts(day, 6, 59), registry=reg, gateways=GWS, notifier=n) is None
    out = hr.tick(st, now=ts(day, 7), registry=reg, gateways=GWS, notifier=n)
    assert out["level"] == "green"
    assert n.calls[0][:2] == ("persistent_notification", "create")
    assert n.calls[0][2]["notification_id"] == hr.NOTIFICATION_ID
    assert sent == []                                  # green stays off the phones
    assert hr.tick(st, now=ts(day, 9), registry=reg, gateways=GWS, notifier=n) is None
    assert st.latest_health_report("daily")["period"] == day


def test_amber_goes_to_the_phones_and_the_switch_stops_it(st, reg, monkeypatch):
    sent = []
    monkeypatch.setattr(hr, "_phones", lambda store, title, msg: sent.append(title))
    day = "2026-11-15"
    st.log_line(ts(day, 3), "ERROR", 40, "fwh", "broke")
    hr.tick(st, now=ts(day, 7), registry=reg, gateways=GWS, notifier=FakeNotifier())
    assert sent == ["FranklinWH bridge: health amber"]
    hr.set_daily(st, False)
    assert hr.tick(st, now=ts("2026-11-16", 7), registry=reg, gateways=GWS,
                   notifier=FakeNotifier()) is None


def test_the_snapshot_is_taken_on_the_first_pass_after_midnight(st, reg):
    st.insert({"soc": 50}, int(ts("2026-11-14", 22)), "gw1", poll=poll(50, 1, 1, 1, 1, 1, 1))
    hr.tick(st, now=ts("2026-11-15", 0, 1), registry=reg, gateways=GWS, notifier=FakeNotifier())
    assert {r["gateway_id"] for r in st.health_snapshots(days=3)} == {"gw1", ""}


# ── REST ──────────────────────────────────────────────────────────────────────
def test_api_runs_lists_and_reads_reports():
    from franklinwh_direct_connect_bridge import app as app_module, config, db
    alerts.reset()
    c = TestClient(app_module.create_app())
    store = db.get_store(config.get_settings())
    assert c.get("/api/health/report").json() == {"report": None, "daily": True, "weekly": True}
    made = c.post("/api/health/report/run").json()
    assert made["level"] in ("green", "amber", "red")
    got = c.get("/api/health/report").json()["report"]
    assert got["id"] == made["id"] and got["report"]["kind"] == "daily"
    assert c.get("/api/health/reports").json()["reports"][0]["id"] == made["id"]
    assert c.get(f"/api/health/report?id={made['id']}").json()["report"]["id"] == made["id"]
    assert c.put("/api/health/report/settings", json={"daily": False}).json()["daily"] is False
    assert store.get_config(hr.DAILY_KEY) == "off"
    c.put("/api/health/report/settings", json={"daily": True})
