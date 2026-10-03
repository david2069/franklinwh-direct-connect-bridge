"""Unit tests for the cached-summary enrichment (client._battery_from_power_flow /
_energy_today_from_power_flow) — pure extraction from a single power_flow (1301) payload.
No device I/O: the helpers take a raw dict fixture."""

from franklinwh_local_bridge import client


# A representative real-aGate power_flow (1301) payload subset — the fields the
# dashboard-parity blocks read (per-module arrays + daily kWh + t_amb/run_status).
SAMPLE_PF = {
    "soc": 62,
    "run_status": 2,               # Discharging
    "t_amb": 11.6,
    "name": "Self-Consumption",
    "devNum": 2,
    "fhpSn": ["FHP-AAA111", "FHP-BBB222"],
    "fhpSoc": [61, 63],
    "fhpPower": [-0.42, -0.40],    # kW (per module)
    "kwh_sun": 12.345,
    "kwh_gen": 0.0,
    "kwh_uti_in": 3.201,
    "kwh_uti_out": 1.109,
    "kwh_fhp_chg": 8.5,
    "kwh_fhp_di": 7.25,
    "kwh_load": 15.0,
}


def test_battery_extraction_full_payload():
    b = client._battery_from_power_flow(SAMPLE_PF)
    assert b["soc"] == 62
    assert b["run_status"] == 2
    assert b["run_status_desc"] == "Discharging"
    assert b["t_amb"] == 11.6
    assert b["count"] == 2
    assert len(b["modules"]) == 2
    assert b["modules"][0] == {"sn": "FHP-AAA111", "soc": 61, "power_kw": -0.42}
    assert b["modules"][1] == {"sn": "FHP-BBB222", "soc": 63, "power_kw": -0.40}


def test_battery_extraction_count_falls_back_to_module_len():
    pf = {"soc": 50, "run_status": 1, "fhpSn": ["A", "B", "C"], "fhpSoc": [1, 2, 3]}
    b = client._battery_from_power_flow(pf)
    assert b["count"] == 3
    assert b["run_status_desc"] == "Charging"
    # fhpPower missing → per-module power is None (guarded, no IndexError)
    assert b["modules"][0]["power_kw"] is None


def test_battery_extraction_empty_and_none_safe():
    for pf in ({}, None, {"fhpSn": [], "fhpSoc": [], "fhpPower": []}):
        b = client._battery_from_power_flow(pf)
        assert b["modules"] == []
        assert b["count"] is None
        assert b["run_status_desc"] is None   # run_status absent → no bogus label


def test_energy_today_extraction_rounds_and_maps():
    e = client._energy_today_from_power_flow(SAMPLE_PF)
    assert e == {
        "solar": 12.35, "grid_in": 3.2, "grid_out": 1.11,
        "charged": 8.5, "discharged": 7.25, "home": 15.0, "generator": 0.0,
    }


def test_energy_today_missing_keys_are_none():
    e = client._energy_today_from_power_flow({})
    assert all(v is None for v in e.values())
    assert set(e) == {"solar", "grid_in", "grid_out", "charged",
                      "discharged", "home", "generator"}
