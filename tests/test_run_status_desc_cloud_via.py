"""Run Status Description and Cloud Connection Via for Home Assistant.

Run Status stays the number. The description is the cloud's wording for the battery's run
status, except VPP: that is the 1707 programme id 9, never run_status (run_status keeps
reporting the battery's direction under VPP; docs/RUN_STATUS_AND_MODE.md).
Cloud Connection Via is 1118 currentNetType, the link the aGate is using now.
"""
import pytest

from franklinwh_direct_connect_bridge.publish import entities, network

from test_network_entities import CLOUD, CONN, IFC, SW


def state(**power):
    return entities.build_state(power, {})


@pytest.mark.parametrize("rs,desc", [(0, "Standby"), (1, "Charging"), (2, "Discharging"),
                                     (5, "Off-Grid Standby"), (6, "Off-Grid Charging"),
                                     (7, "Off-Grid Discharging")])
def test_the_description_names_the_run_status(rs, desc):
    s = state(run_status=rs, run_status_desc=desc, vpp=False)
    assert (s["run_status"], s["run_status_desc"]) == (rs, desc)


def test_vpp_comes_from_the_programme_not_the_run_status():
    assert state(run_status=2, run_status_desc="Discharging", vpp=True)["run_status_desc"] == "VPP Mode"
    assert state(run_status=2, run_status_desc="Discharging", vpp=None)["run_status_desc"] == "Discharging"


def test_both_are_published_as_diagnostic_entities():
    keys = {e["key"]: e for e in entities.ENTITIES}
    assert keys["run_status_desc"]["name"] == "Run Status Description"
    assert keys["net_cloud_via"]["name"] == "Cloud Connection Via"
    assert keys["run_status_desc"]["group"] == keys["net_cloud_via"]["group"] == "diagnostic"


@pytest.mark.parametrize("code,via", [(1, "Ethernet 0"), (2, "Ethernet 1"), (3, "WiFi"), (4, "4G"),
                                      ("4", "4G"), (0, None), (None, None)])
def test_cloud_connection_via_is_the_link_in_use(code, via):
    assert network.network_state(CONN, dict(IFC, currentNetType=code), SW, CLOUD)["net_cloud_via"] == via
