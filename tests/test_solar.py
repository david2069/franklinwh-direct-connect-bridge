"""Solar view-model and endpoints.

Fixture is the real 1903/1301 pair captured 2026-09-14. The point of this module is
grouping: the firmware names solar fields inconsistently, so the tests pin the
groupings and the two scaling traps.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import solar
from franklinwh_direct_connect_bridge.app import create_app

CFG = {
    "remoteSolarEn": 0, "remoteSolarMode": 0, "solarRatedPower": 0,
    "installProximalsolar": 0, "installPV1port": 1, "installPV2port": 0,
    "PV1RatedPower": 66, "PV2RatedPower": 0,
    "loadSolarAmount": 0, "loadSolar1RatedPower": 0, "loadSolar2RatedPower": 0,
    "mainsSolarRatedPower": 0, "protectTime": 20, "reSolarSoc": 95,
    "solarPower": 21810, "solarRelayStat": 1, "loadRelay1Stat": 0, "loadRelay2Stat": 0,
    "solarPowerGen": 224, "grid_feed_max": -1, "threePhPvEnb": 0,
}
FLOW = {"p_sun": 2181, "kwh_sun": 22.4258,
        "diStatus": [0, 0, 0, 0], "doStatus": [0, 0, 0, 0]}


def test_rated_power_uses_the_100w_step():
    """PV1RatedPower 66 is 6.6 kW, not 66 kW and not 66 W."""
    v = solar.build(CFG, FLOW)
    assert v["inputs"]["ports"][0]["rated_kw"] == 6.6
    assert v["inputs"]["total_rated_kw"] == 6.6
    assert v["inputs"]["installed_count"] == 1


def test_solar_power_is_deciwatts_not_energy():
    """Measured twice on hardware: solarPower == p_sun * 10."""
    v = solar.build(CFG, FLOW)
    assert v["live"]["power_w_from_1903"] == 2181.0
    assert v["live"]["power_w"] == 2181
    assert v["live"]["sources_agree"] is True


def test_disagreement_between_the_two_power_sources_is_surfaced():
    v = solar.build({**CFG, "solarPower": 90000}, FLOW)
    assert v["live"]["sources_agree"] is False      # not silently averaged or hidden


def test_missing_live_flow_yields_none_not_zero():
    v = solar.build(CFG, None)
    assert v["live"]["power_w"] is None
    assert v["live"]["sources_agree"] is None
    assert v["inputs"]["ports"][0]["rated_kw"] == 6.6   # config still usable


def test_uninstalled_port_has_no_rating():
    p2 = solar.build(CFG, FLOW)["inputs"]["ports"][1]
    assert p2["installed"] is False and p2["rated_kw"] is None


RUN = {
    "solarRelayStatus": 1, "pvRelay2": 0,
    "loadRelay1Stat": 0, "loadRelay2Stat": 0,
    "smartRelay1Status": 0, "smartRelay2Status": 0, "smartRelay3Status": 0,
    "mainRelay1Status": 1, "mainRelay2Status": 0, "gridRelay2": 1,
    "blackStartRelay": 1,
}


def test_two_pairs_of_ac_pv_inputs_are_kept_apart():
    """Built-in AC PV (2) and remote-solar AC PV (2) are different hardware."""
    v = solar.build(CFG, {**FLOW, "main_sw": [1, 0, 1]}, RUN)
    assert len(v["inputs"]["ports"]) == 2
    assert len(v["remote_solar"]["inputs"]) == 2
    assert v["inputs"]["ports"][0]["rated_kw"] == 6.6          # built-in
    assert v["remote_solar"]["inputs"][0]["rated_kw"] is None  # remote, unconfigured


def test_builtin_relays_come_from_two_unrelated_field_names():
    """solarRelayStatus and pvRelay2 — the pair shares no naming at all."""
    ports = solar.build(CFG, FLOW, RUN)["inputs"]["ports"]
    assert ports[0]["relay"]["open"] is True     # solarRelayStatus
    assert ports[1]["relay"]["open"] is False    # pvRelay2


def test_raw_one_is_OPEN_not_closed():
    """FranklinWH inverts the usual convention: raw 1 = OPEN = conducting.

    Two sources agree — the site owner reports a connected grid and producing
    solar as "OPEN/ON", and AGENT_GROUND_TRUTH.md rules that writing
    "1=CLOSED (connected)" is the wrong way round for this vendor. A table in
    that same document says the opposite; the rule and the hardware win.
    """
    r = solar.build(CFG, FLOW, RUN)["inputs"]["ports"][0]["relay"]
    assert r["open"] is True and r["state"] == "open" and r["raw"] == 1
    off = solar.build(CFG, FLOW, RUN)["inputs"]["ports"][1]["relay"]
    assert off["open"] is False and off["state"] == "closed" and off["raw"] == 0


def test_no_flowing_alias_survives():
    """The previous wording was replaced, not layered — one vocabulary only."""
    r = solar.build(CFG, FLOW, RUN)["inputs"]["ports"][0]["relay"]
    assert set(r) == {"open", "state", "raw"}


def test_remote_solar_inputs_carry_their_own_relays():
    ins = solar.build(CFG, FLOW, RUN)["remote_solar"]["inputs"]
    assert [i["relay"]["open"] for i in ins] == [False, False]


def test_black_start_relay_is_readable():
    """Retracts part of OFFGRID_DESIGN §4 — the blackstart RELAY is readable in
    1707, even though the blackStartOnOff CONFIG flag in 1801 is not."""
    assert solar.build(CFG, FLOW, RUN)["system_relays"]["black_start"]["open"] is True


def test_smart_circuit_relays_exposed():
    sc = solar.build(CFG, FLOW, RUN)["system_relays"]["smart_circuits"]
    assert len(sc) == 3 and all(r["open"] is False for r in sc)


def test_main_sw_is_decoded_by_position():
    """cloud API_COOKBOOK.md:36 — main_sw duplicates grid/gen/solar relays."""
    m = solar.build(CFG, {**FLOW, "main_sw": [1, 0, 1]}, RUN)["system_relays"]["main_sw"]
    assert m == {"grid": 1, "generator": 0, "solar": 1}


def test_missing_1707_degrades_to_config_values():
    """1903 still carries solarRelayStat, so a failed 1707 is not fatal."""
    v = solar.build(CFG, FLOW, None)
    assert v["inputs"]["ports"][0]["relay"]["open"] is True     # from solarRelayStat
    assert v["system_relays"]["black_start"]["raw"] is None


def test_apbox_digital_io_is_grouped_with_remote_solar():
    rs = solar.build(CFG, FLOW)["remote_solar"]
    assert rs["enabled"] is False
    assert rs["digital_in"] == [0, 0, 0, 0] and rs["digital_out"] == [0, 0, 0, 0]


def test_export_unlimited_sentinel():
    v = solar.build(CFG, FLOW)
    assert v["export"]["unlimited"] is True and v["export"]["feed_max_w"] is None
    limited = solar.build({**CFG, "grid_feed_max": 5000}, FLOW)
    assert limited["export"]["feed_max_w"] == 5000 and limited["export"]["unlimited"] is False


def test_undecoded_field_is_labelled_not_guessed():
    """solarPowerGen held constant while power moved — config, not live output."""
    v = solar.build(CFG, FLOW)
    assert v["undecoded"]["solarPowerGen"] == 224
    assert "solarPowerGen" not in v["live"]


# ── endpoints ────────────────────────────────────────────────────────────────
def test_api_solar(monkeypatch):
    from franklinwh_direct_connect_bridge import client as c
    monkeypatch.setattr(c, "solar", lambda s, host=None: solar.build(CFG, FLOW))
    body = TestClient(create_app()).get("/api/solar").json()
    assert body["inputs"]["total_rated_kw"] == 6.6


def test_api_device_model_regression(monkeypatch):
    """Regression: client.device_model was deleted by a refactor and 500'd live.

    No test covered the endpoint, so the suite stayed green. This pins it.
    """
    from franklinwh_direct_connect_bridge import client as c
    assert hasattr(c, "device_model")
    monkeypatch.setattr(c, "device_model",
                        lambda s, host=None: {"known": True, "model": "aGate X-01-AU"})
    r = TestClient(create_app()).get("/api/device/model")
    assert r.status_code == 200 and r.json()["model"] == "aGate X-01-AU"
