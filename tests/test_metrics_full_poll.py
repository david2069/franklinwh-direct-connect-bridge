"""Every number a poll reads is kept, not just the eight chart columns. The bridge read
~84 values per poll and stored 8; the rest (per-aPower battery, relays, today's energy,
comms) were shown live and thrown away, so nothing could be looked at afterwards."""
import pathlib
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, state
from franklinwh_direct_connect_bridge import db as db_module
from franklinwh_direct_connect_bridge.db import MetricsStore

GW = "gw-full"
SUMM = {
    "ok": True,
    "mode": "Self-Consumption",
    "power": {"grid_w": 120.0, "battery_w": -800, "gridVol1": 241.2},
    "battery": {"apowers": [{"soc": 55.0, "temp_c": 24}, {"soc": 56.0, "temp_c": 25}]},
    "relays": {"grid": True, "solar": False},
    "firmware": {"FHP_SN": ["SERIAL-NOT-STORED"], "PE_HW_VER": [2]},
    "note": "text is not a metric",
}


@pytest.fixture(autouse=True)
def _gateway():
    state.register_gateway(GW, "10.0.0.1", "Home")
    yield
    state.unregister_gateway(GW)


def test_every_number_in_the_poll_is_stored(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.insert({"soc": 55, "grid_w": 120, "mode": "Self-Consumption"}, 1000,
              gateway_id=GW, poll=SUMM)
    row = st.raw(0, 2000, gateway=GW)[0]
    assert row["poll"] == {
        "ok": 1, "power.grid_w": 120.0, "power.battery_w": -800, "power.gridVol1": 241.2,
        "battery.apowers[0].soc": 55.0, "battery.apowers[0].temp_c": 24,
        "battery.apowers[1].soc": 56.0, "battery.apowers[1].temp_c": 25,
        "relays.grid": 1, "relays.solar": 0,
        "firmware.PE_HW_VER[0]": 2,
    }
    assert "SERIAL-NOT-STORED" not in str(row)       # strings (serials) are never kept
    assert row["soc"] == 55 and row["grid_w"] == 120 and row["mode"] == "Self-Consumption"
    assert "grid_voltage_v" in row and "grid_freq_hz" in row


def test_a_row_without_a_poll_reads_back_empty(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.insert({"soc": 50}, 1000, gateway_id=GW)
    assert st.raw(0, 2000, gateway=GW)[0]["poll"] == {}


def test_an_existing_database_gains_the_column(tmp_path):
    p = str(tmp_path / "old.db")
    MetricsStore(p)
    con = sqlite3.connect(p)
    con.execute("ALTER TABLE metrics DROP COLUMN poll")
    con.commit()
    con.close()
    st = MetricsStore(p)
    st.insert({"soc": 1}, 5, gateway_id=GW, poll={"power": {"x": 1}})
    assert st.raw(0, 10, gateway=GW)[0]["poll"] == {"power.x": 1}


def test_the_poller_stores_the_whole_poll():
    src = (pathlib.Path(db_module.__file__).parent / "poller.py").read_text()
    assert 'summ.get("tou_tiers"), summ)' in src


def test_the_raw_api_returns_every_column_and_the_poll(monkeypatch, tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    now = int(time.time())
    st.insert({"soc": 55, "grid_voltage_v": 241.2}, now - 60, gateway_id=GW, poll=SUMM)
    monkeypatch.setattr(db_module, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    body = c.get(f"/api/metrics/raw?gateway={GW}&start={now - 120}&end={now}").json()
    assert body["count"] == 1
    row = body["rows"][0]
    assert row["grid_voltage_v"] == 241.2
    assert row["poll"]["battery.apowers[1].soc"] == 56.0


# Resolution steps down like Home Assistant's recorder: every poll for 10 days, then
# hourly mean/min/max (HA's long-term statistics) for the rest of the retention.
DAY = 86400


def test_after_ten_days_the_poll_becomes_hourly_mean_min_max(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    now = 100 * DAY
    hour = now - 12 * DAY - (now - 12 * DAY) % 3600
    for i, w in enumerate((100, 200, 600)):
        st.insert({"soc": 50, "grid_w": w}, hour + i * 30, gateway_id=GW,
                  poll={"power": {"grid_w": w}})
    st.insert({"soc": 50}, now - DAY, gateway_id=GW, poll={"power": {"grid_w": 7}})
    assert db_module.POLL_RAW_DAYS == 10
    st.prune(365, now)
    old = st.raw(hour, hour + 3600, gateway=GW)
    assert [r["grid_w"] for r in old] == [100, 200, 600]      # chart columns untouched
    assert all(r["poll"] == {} for r in old)                  # full poll rolled up
    assert st.raw(now - 2 * DAY, now, gateway=GW)[0]["poll"] == {"power.grid_w": 7}
    hourly = st.poll_hourly(0, now, gateway=GW)
    assert hourly == [{"ts": hour, "n": 3,
                       "stats": {"power.grid_w": {"mean": 300.0, "min": 100, "max": 600}}}]
    st.prune(365, now)                                        # idempotent
    assert len(st.poll_hourly(0, now, gateway=GW)) == 1


def test_hourly_rows_follow_the_retention(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    now = 500 * DAY
    st.insert({"soc": 1}, now - 400 * DAY, gateway_id=GW, poll={"x": 1})
    st.prune(450, now)
    assert len(st.poll_hourly(0, now, gateway=GW)) == 1
    st.prune(365, now)
    assert st.poll_hourly(0, now, gateway=GW) == []


def test_the_raw_api_also_returns_the_hourly_rows(monkeypatch, tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    now = int(time.time())
    st.insert({"soc": 1}, now - 20 * DAY, gateway_id=GW, poll={"x": 4})
    st.prune(365, now)
    monkeypatch.setattr(db_module, "get_store", lambda s: st)
    c = TestClient(app_module.create_app())
    body = c.get(f"/api/metrics/raw?gateway={GW}&start={now - 30 * DAY}&end={now}").json()
    assert body["hourly"][0]["stats"]["x"]["mean"] == 4
