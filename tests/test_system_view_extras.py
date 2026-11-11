"""System view extras (owner, 2026-11-11): today's energy and the gateway's open alerts go
to the overlay (franklinwh-system-view 0.3.0), which shows them, with voltage and frequency
and the power on each wire, when the user switches them on under Options."""
import pathlib

import pytest

from franklinwh_direct_connect_bridge import state, system_view
from franklinwh_direct_connect_bridge.db import MetricsStore

from test_system_view_428 import gw, us_summary

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    state.reset_gateways()
    yield
    state.reset_gateways()


def test_today_energy_maps_to_the_overlays_names():
    s = us_summary()
    s["energy_today"] = {"solar": 21.4, "grid_in": 3.2, "grid_out": 5.1, "charged": 8.1,
                         "discharged": 6.3, "home": 12.0, "generator": 0.0}
    assert system_view.gateway_payload(gw(summary=s))["energy_today"] == {
        "grid_import_kwh": 3.2, "grid_export_kwh": 5.1, "solar_kwh": 21.4, "home_kwh": 12.0,
        "battery_charge_kwh": 8.1, "battery_discharge_kwh": 6.3}


def test_energy_not_read_is_left_out():
    s = us_summary()
    s["energy_today"] = {"solar": None, "grid_in": None}
    assert "energy_today" not in system_view.gateway_payload(gw(summary=s))
    s.pop("energy_today")
    assert "energy_today" not in system_view.gateway_payload(gw(summary=s))


def test_open_alerts_are_the_gateways_alarms(tmp_path):
    st = MetricsStore(str(tmp_path / "m.db"))
    st.insert_alert(gateway_id="gw1", kind="condition", severity="critical",
                    code="GATEWAY_UNREACHABLE", title="aGate unreachable",
                    message="No answer for 5 min", opened_ts=100.0)
    st.insert_alert(gateway_id="gw1", kind="event", severity="warning",
                    code="EXTERNAL_SETPOINT", title="Setpoint changed outside the bridge",
                    message=None, opened_ts=101.0)
    st.insert_alert(gateway_id="other", kind="event", severity="critical", code="SCHEDULE_FAILED",
                    title="Scheduled action failed", message=None, opened_ts=102.0)
    g = system_view.gateway_payload(gw(summary=us_summary()), store=st)
    assert g["alarms"] == [
        {"target": "agate", "code": "EXTERNAL_SETPOINT", "level": "warn",
         "text": "Setpoint changed outside the bridge"},
        {"target": "agate", "code": "GATEWAY_UNREACHABLE", "level": "crit",
         "text": "aGate unreachable: No answer for 5 min"}]


def test_no_store_means_no_alarms_key():
    assert "alarms" not in system_view.gateway_payload(gw(summary=us_summary()))


def test_the_payload_builds_with_the_extras():
    import franklinwh_system_view as sv
    s = us_summary()
    s["energy_today"] = {"solar": 1.0, "grid_in": 2.0, "grid_out": 0.5, "charged": 1.0,
                         "discharged": 0.0, "home": 3.0}
    out = sv.build({"version": 1, "gateways": [system_view.gateway_payload(gw(summary=s))]})
    grid = next(n for n in out["gateways"][0]["scenes"]["landscape"]["nodes"] if n["id"] == "grid")
    assert {"k": "vhz", "t": "241.6 V · 60.00 Hz"} in grid["extra"]


def test_pins_the_overlay_with_the_extras():
    pin = (ROOT / "pyproject.toml").read_text()
    assert '"franklinwh-system-view==0.3.1"' in pin
