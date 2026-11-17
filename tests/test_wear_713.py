"""#713 step 4 (owner 2026-11-17): battery wear from hems. The warranty inputs are setup
fields in System Setup, pre-filled from the FranklinWH cloud's warrantyInfo when signed in
(please confirm); SoH from the aPower reads the bridge already makes; each poll goes into
hems's dispatch tracker, with the events kept in the bridge's DB; round-trip efficiency from
SoC-matched cycles on the aGate's own charge and discharge counters."""
import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import db, providers, state, wear
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
CLOUD = {"expirationTime": "2036-03-01", "throughput": 43.2, "remainThroughput": 41000,
         "installerCompany": "Someone Pty Ltd", "installerCompanyEmail": "x@example.com"}


@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    wear._trackers.clear()
    yield s
    s.close()


def test_the_fields_are_hems_setup_fields_and_the_cloud_only_prefills(st):
    f = wear.fields(st, "gw1", cloud=wear.cloud_subset(CLOUD))
    assert list(f) == ["warranty_end", "warranted_throughput_mwh", "end_soh_pct",
                       "install_date", "replacement_value", "end_value"]
    assert f["warranty_end"] == {"value": "2036-03-01", "source": "cloud", "confirm": True}
    assert f["warranted_throughput_mwh"]["value"] == 43.2
    wear.save(st, "gw1", {"warranted_throughput_mwh": 40.0, "replacement_value": 15000,
                          "end_soh_pct": 70})
    f = wear.fields(st, "gw1", cloud=wear.cloud_subset(CLOUD))
    assert f["warranted_throughput_mwh"] == {"value": 40.0, "source": "user", "confirm": False}
    # null clears a field back to the pre-fill
    wear.save(st, "gw1", {"warranted_throughput_mwh": None})
    assert wear.fields(st, "gw1", cloud=wear.cloud_subset(CLOUD))["warranted_throughput_mwh"]["source"] == "cloud"


def test_only_the_warranty_figures_are_kept_from_the_cloud_no_installer_details():
    sub = wear.cloud_subset(CLOUD)
    assert sub == {"expirationTime": "2036-03-01", "throughput": 43.2, "remainThroughput": 41000}


def test_the_cloud_is_read_once_a_day_and_only_when_signed_in(st, monkeypatch):
    calls = []
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "unconfigured"})
    assert wear.cloud(st, None, "gw1", "SERIAL", 1e9, read=lambda *a: calls.append(a) or CLOUD) is None
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "valid"})
    a = wear.cloud(st, None, "gw1", "SERIAL", 1e9, read=lambda *a: calls.append(a) or CLOUD)
    b = wear.cloud(st, None, "gw1", "SERIAL", 1e9 + 3600, read=lambda *a: calls.append(a) or CLOUD)
    assert a == b == wear.cloud_subset(CLOUD) and len(calls) == 1
    # a failed read keeps the last good one
    c = wear.cloud(st, None, "gw1", "SERIAL", 1e9 + 2 * 86400, read=lambda *a: 1 / 0)
    assert c == wear.cloud_subset(CLOUD)


def test_each_poll_feeds_the_tracker_and_closed_events_are_stored(st):
    t = 1_800_000_000
    for i in range(12):                       # an hour discharging at 2 kW
        wear.observe(st, "gw1", t + i * 300, {"battery_w": 2000, "soc": 80 - i,
                                               "kwh_fhp_chg": 0.0, "kwh_fhp_di": i * 0.167,
                                               "t_amb": 21.0, "vpp": False})
    for i in range(12, 15):                   # then idle long enough to close it
        wear.observe(st, "gw1", t + i * 300, {"battery_w": 0, "soc": 68, "kwh_fhp_chg": 0.0,
                                               "kwh_fhp_di": 1.84, "t_amb": 21.0})
    ev = st.wear_events("gw1")
    assert len(ev) == 1 and ev[0]["direction"] == "discharge"
    assert ev[0]["energy_out_kwh"] == pytest.approx(2.0, abs=0.05)   # 12 five-minute steps at 2 kW
    assert ev[0]["soc_start"] == 80 and ev[0]["ambient_temp_c"] == 21.0
    # samples for efficiency: every 5 minutes at most
    assert len(st.wear_samples("gw1", 0)) == 15


def test_vpp_events_are_marked_vpp(st):
    t = 1_800_000_000
    for i in range(4):
        wear.observe(st, "gw1", t + i * 300, {"battery_w": 3000, "soc": 90 - i, "vpp": True})
    for i in range(4, 7):
        wear.observe(st, "gw1", t + i * 300, {"battery_w": 0, "soc": 86})
    assert st.wear_events("gw1")[0]["source"] == "vpp"


def test_efficiency_comes_from_the_agates_daily_counters_made_cumulative(st):
    """The counters reset at midnight; the cycles need them running on."""
    rows = []
    t0 = 1_800_000_000
    # day 1: charge 10 kWh from 20 % to 90 %; day 2 (counters reset): discharge 9 back to 20 %
    rows += [{"ts": t0, "soc": 20, "chg": 0.0, "dis": 0.0}, {"ts": t0 + 3600, "soc": 90, "chg": 10.0, "dis": 0.0}]
    rows += [{"ts": t0 + 86400, "soc": 90, "chg": 0.0, "dis": 0.0},
             {"ts": t0 + 90000, "soc": 20, "chg": 0.0, "dis": 9.0}]
    for r in rows:
        st.wear_sample_add("gw1", r["ts"], soc=r["soc"], chg_kwh=r["chg"], dis_kwh=r["dis"],
                           power_w=None, temp_c=None)
    cum = wear.cumulative(st.wear_samples("gw1", 0))
    assert [round(x["charged_kwh"], 1) for x in cum] == [0, 10, 10, 10]
    assert [round(x["discharged_kwh"], 1) for x in cum] == [0, 0, 0, 9]
    eff = wear.efficiency(st, "gw1", t0 + 90000)
    assert eff["median"] == pytest.approx(0.9) and eff["n"] == 1


def test_the_report_has_cost_pace_soh_and_usable(st, monkeypatch):
    state.reset_gateways()
    gw = state.register_gateway("gw1", "192.0.2.10", "gw1")
    gw.apower_soh = {"1": 96.0, "2": 94.0}
    wear.save(st, "gw1", {"replacement_value": 15000, "end_soh_pct": 70,
                          "warranted_throughput_mwh": 43.2, "warranty_end": "2036-03-01",
                          "install_date": "2026-03-01"})
    for d, wh in (("2026-11-10", 5000), ("2026-11-11", 7000)):
        st.save_health_snapshot({"gateway_id": "gw1", "day": d, "ts": 0,
                                 "battery_discharged_wh": wh})
    now = dt.datetime(2026, 11, 17, 12).timestamp()
    r = wear.report(st, None, "gw1", now, cloud_fn=lambda *a: None)
    assert r["cost"]["per_kwh"] == pytest.approx((15000 - 10500) / 43200, abs=1e-5)
    assert r["cost"]["end_value"]["derived"] is True
    assert r["used_kwh"] == pytest.approx(12.0)
    assert r["remaining_kwh"] == pytest.approx(43200 - 12)
    assert r["pace"]["daily_kwh"] > 0
    assert r["soh_pct"] == pytest.approx(95.0)
    state.reset_gateways()


def test_the_api_reads_and_saves(tmp_path, monkeypatch):
    state.reset_gateways()
    s = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda *a, **k: s)
    state.register_gateway("gw1", "192.0.2.10", "gw1")
    monkeypatch.setattr(wear, "cloud", lambda *a, **k: wear.cloud_subset(CLOUD))
    c = TestClient(app_module.create_app())
    r = c.get("/api/wear", params={"gateway": "gw1"}).json()
    assert r["fields"]["warranty_end"]["confirm"] is True
    r = c.put("/api/wear", params={"gateway": "gw1"}, json={"warranty_end": "2036-03-01"}).json()
    assert r["fields"]["warranty_end"] == {"value": "2036-03-01", "source": "user", "confirm": False}
    assert c.put("/api/wear", params={"gateway": "gw1"}, json={"nope": 1}).status_code == 422
    state.reset_gateways()


def test_the_poller_feeds_it_and_system_setup_shows_it():
    assert "wear.observe(" in (PKG / "poller.py").read_text()
    html = (PKG / "templates" / "tabs" / "settings.html").read_text()
    assert 'data-testid="wear-setup"' in html and "Please confirm" in html
    for f in ("warranty_end", "warranted_throughput_mwh", "end_soh_pct", "install_date",
              "replacement_value", "end_value"):
        assert f in html, f
