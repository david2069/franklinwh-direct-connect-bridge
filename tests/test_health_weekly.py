"""Scheduled health check, phase 2: the weekly battery report (owner 2026-11-15; the
Modbus bridge's design, from this bridge's data). SoH comes from the cell reads the alarm
pass already makes; energy from the daily snapshot."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import client, health_report as hr, workers
from franklinwh_direct_connect_bridge.db import MetricsStore

GWS = [{"id": "gw1", "name": "Home"}]


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    yield s
    s.close()


@pytest.fixture
def reg():
    return workers.Registry()


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def call_service(self, domain, service, data):
        self.calls.append((domain, service, data))
        return ""


def ts(day, hh=0, mm=0):
    return dt.datetime.strptime(f"{day} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M").timestamp()


def day_row(st, day, *, soh=None, soc=50, chg=10.0, di=9.0, sun=20.0, uin=2.0, uout=8.0, load=14.0):
    st.save_health_snapshot({"gateway_id": "gw1", "day": day, "ts": ts(day, 23), "soh": soh,
                             "soc": soc, "battery_charged_wh": chg * 1000,
                             "battery_discharged_wh": di * 1000, "solar_wh": sun * 1000,
                             "grid_import_wh": uin * 1000, "grid_export_wh": uout * 1000,
                             "load_wh": load * 1000, "alerts": 0})


# ── SoH from the reads already made ──────────────────────────────────────────
class _Dev:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self):
        self.calls.append("login")

    def device_ids(self):
        return [1, 2]

    def battery_cells(self, dev_id=1):
        self.calls.append(("cells", dev_id))
        return {"alarmLevel": 0, "batSoh": {1: 96.5, 2: 95.5}[dev_id]}


def test_the_alarm_pass_returns_each_apowers_soh_without_another_read(monkeypatch):
    dev = _Dev()
    monkeypatch.setattr(client, "_client", lambda s, host=None: dev)
    out = client.device_alarms(None, "h", events=False)
    assert out["soh"] == {1: 96.5, 2: 95.5}
    assert dev.calls == ["login", ("cells", 1), ("cells", 2)]


def test_the_snapshot_keeps_the_average_soh_of_the_apowers(st):
    st.insert({"soc": 50}, int(ts("2026-11-14", 22)), "gw1",
              poll={"power": {"kwh_fhp_chg": 1, "kwh_fhp_di": 1}})
    hr.take_snapshot(st, "2026-11-14", ts("2026-11-14"), ts("2026-11-15"), ["gw1"],
                     now=ts("2026-11-15", 0, 1), soh_fn=lambda gw: {1: 96.5, 2: 95.5})
    row = [r for r in st.health_snapshots(days=2) if r["gateway_id"] == "gw1"][0]
    assert row["soh"] == 96.0


# ── the figures ──────────────────────────────────────────────────────────────
def test_efficiency_is_out_over_in_between_days_ending_at_a_similar_soc():
    rows = [{"day": f"2026-11-{d:02d}", "soc": soc, "battery_charged_wh": 10000.0,
             "battery_discharged_wh": 9000.0} for d, soc in ((9, 40), (10, 70), (11, 42))]
    e = hr.efficiency(rows)
    assert e["pct"] == 90.0 and e["from"] == "2026-11-09" and e["to"] == "2026-11-11"
    assert e["in_kwh"] == 20.0 and e["out_kwh"] == 18.0       # the days after the first
    assert hr.efficiency(rows[:2]) is None                        # 40 % vs 70 %: no span


def test_the_weekly_report_has_soh_efficiency_cycles_and_the_weeks_energy(st, reg):
    hr.set_capacity_fn(lambda store: 13.6)
    for i, d in enumerate(range(8, 17)):                         # Sun 8 .. Mon 16 Nov
        day_row(st, f"2026-11-{d:02d}", soh=96.0 - i * 0.05, soc=50)
    r = hr.build_weekly(st, ts("2026-11-16", 7), gateways=GWS)
    g = r["gateways"][0]
    assert r["week"] == {"from": "2026-11-09", "to": "2026-11-15"}
    assert g["energy"]["battery_in_kwh"] == 70.0 and g["energy"]["solar_kwh"] == 140.0
    assert g["efficiency"]["pct"] == 90.0
    assert g["full_cycles"]["week"] == round(63.0 / 13.6, 2)   # discharged ÷ capacity
    assert g["soh"]["now"] == pytest.approx(95.65)
    assert r["level"] == "info" and r["headline"].startswith("Week of 9 Nov: SoH 95.7%")


def test_without_a_capacity_the_cycles_say_so(st):
    hr.set_capacity_fn(lambda store: None)
    for d in range(8, 17):
        day_row(st, f"2026-11-{d:02d}")
    g = hr.build_weekly(st, ts("2026-11-16", 7), gateways=GWS)["gateways"][0]
    assert g["full_cycles"]["week"] is None and g["full_cycles"]["needs"] == "battery capacity"


def test_cycles_by_depth_from_the_soc_series():
    c = hr.soc_cycles([20, 80, 20, 80, 20, 60, 50, 60])
    assert c["cycles"] >= 2 and c["bands"]["50 to 80"] >= 2


# ── the job ──────────────────────────────────────────────────────────────────
def test_monday_seven_runs_the_weekly_once_to_ha_not_the_phones(st, reg, monkeypatch):
    sent = []
    monkeypatch.setattr(hr, "_phones", lambda store, title, msg: sent.append(title))
    hr.set_capacity_fn(lambda store: 13.6)
    for d in range(8, 17):
        day_row(st, f"2026-11-{d:02d}", soh=95.0)
    n = FakeNotifier()
    hr.tick(st, now=ts("2026-11-16", 7), registry=reg, gateways=GWS, notifier=n)
    weekly = st.latest_health_report("weekly")
    assert weekly["period"] == "2026-11-09"
    ids = [c[2]["notification_id"] for c in n.calls]
    assert hr.WEEKLY_NOTIFICATION_ID in ids and sent == []
    hr.tick(st, now=ts("2026-11-16", 9), registry=reg, gateways=GWS, notifier=n)
    assert len([r for r in st.health_reports("weekly")]) == 1
    hr.set_weekly(st, False)
    hr.tick(st, now=ts("2026-11-23", 7), registry=reg, gateways=GWS, notifier=n)
    assert len(st.health_reports("weekly")) == 1


def test_api_reads_and_runs_the_weekly_report():
    from franklinwh_direct_connect_bridge import app as app_module
    c = TestClient(app_module.create_app())
    assert c.get("/api/health/report?kind=weekly").json()["report"] is None
    made = c.post("/api/health/report/run?kind=weekly").json()
    assert made["level"] == "info"
    assert c.get("/api/health/report?kind=weekly").json()["report"]["id"] == made["id"]
    assert c.get("/api/health/reports?kind=weekly").json()["reports"][0]["id"] == made["id"]
    assert c.put("/api/health/report/settings", json={"weekly": False}).json()["weekly"] is False
    c.put("/api/health/report/settings", json={"weekly": True})
