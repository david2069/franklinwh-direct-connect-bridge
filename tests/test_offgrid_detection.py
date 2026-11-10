"""#45 — off-grid is decided from every signal, because the obvious one does not work.

Fixtures are the values MEASURED during the owner's island on 2026-10-15 (aGate X-01-AU,
firmware V12R02B30D06), not invented ones. A fixture with run_status=5 would prove nothing:
that is the path that already worked and is not the path that failed.
"""
from franklinwh_direct_connect_bridge.client import _apply_off_grid


def _islanded():
    """Exactly what the gateway reported, sampled every 15s from 07:21 to 08:10 AEDT."""
    return {"power": {"run_status": 0, "dsp_run_status": 5, "offgrid_state": 1,
                      "main_sw": [0, 0, 1]},
            "relays": {"mainRelay1Status": 0, "mainRelay2Status": 0}}


def _on_grid():
    return {"power": {"run_status": 2, "dsp_run_status": 2, "offgrid_state": 0,
                      "main_sw": [1, 0, 1]},
            "relays": {"mainRelay1Status": 1, "mainRelay2Status": 1}}


def test_real_island_is_detected_although_run_status_says_otherwise():
    out = _islanded()
    _apply_off_grid(out)
    assert out["power"]["off_grid"] is True
    # the signal the old implementation relied on, still false — that IS the defect
    assert out["power"]["off_grid_signals"]["run_status"] is False


def test_on_grid_stays_off_grid_false():
    out = _on_grid()
    _apply_off_grid(out)
    assert out["power"]["off_grid"] is False
    assert not any(out["power"]["off_grid_signals"].values())


def test_disagreement_is_surfaced_not_averaged_away():
    """docs/OFFGRID_DESIGN.md §2: 'Disagreement is itself diagnostic and must not be
    averaged away into a single boolean.'"""
    out = _islanded()
    _apply_off_grid(out)
    assert out["power"]["off_grid_disagreement"] is True
    assert out["power"]["off_grid_signals"] == {
        "offgrid_state": True, "run_status": False, "dsp_run_status": True,
        "grid_relay": True, "main_relays": True,
    }


def test_agreement_is_not_reported_as_disagreement():
    out = _on_grid()
    _apply_off_grid(out)
    assert out["power"]["off_grid_disagreement"] is False


def test_offgrid_state_alone_is_enough():
    """1723 was the only signal that was simply correct. It must not need corroboration."""
    out = {"power": {"offgrid_state": 1}}
    _apply_off_grid(out)
    assert out["power"]["off_grid"] is True


def test_missing_signals_are_absent_not_assumed_false():
    """A read that failed must not vote 'on-grid'."""
    out = {"power": {"run_status": 2}}
    _apply_off_grid(out)
    assert set(out["power"]["off_grid_signals"]) == {"run_status"}


def test_grid_relay_open_is_not_used():
    """1709 gridRelayOpen read 0 for the whole island, so it is evidence of nothing.

    docs/OFFGRID_DESIGN.md called it 'the truth about copper'. It was not.
    """
    out = _islanded()
    out["relays"]["gridRelayOpen"] = 0
    _apply_off_grid(out)
    assert "grid_relay_open" not in out["power"]["off_grid_signals"]
    assert out["power"]["off_grid"] is True


# --- simulated vs outage (docs/OFFGRID_DESIGN.md §3) --------------------------------------

def test_requested_island_is_simulated():
    out = _islanded()
    out["power"]["offgrid_requested"] = 1      # measured during the 2026-10-15 test
    _apply_off_grid(out)
    assert out["power"]["off_grid_kind"] == "simulated"


def test_unrequested_island_is_an_outage():
    """The (offgridSet 0, offgridState 1) row. Still unconfirmed on hardware — it needs the
    grid to actually fail — so this pins the LOGIC, not the device behaviour."""
    out = _islanded()
    out["power"]["offgrid_requested"] = 0
    _apply_off_grid(out)
    assert out["power"]["off_grid_kind"] == "outage"


def test_kind_is_none_when_1723_could_not_be_read():
    """Saying 'outage' because a read failed would raise an alarm out of a missing field."""
    out = _islanded()
    out["power"].pop("offgrid_requested", None)
    _apply_off_grid(out)
    assert out["power"]["off_grid_kind"] is None
    assert out["power"]["off_grid"] is True


def test_on_grid_has_no_kind():
    out = _on_grid()
    out["power"]["offgrid_requested"] = 0
    _apply_off_grid(out)
    assert out["power"]["off_grid_kind"] is None


# --- grid presence: the physical discriminator -------------------------------------------

def test_grid_present_during_a_requested_island():
    """Measured 2026-10-15: both legs ~120 V at ~0 A for two hours with the relay open.

    The utility never left. That is what makes 34 s a floor for the reconnect and not a
    general figure — the grid had been qualifiable the whole time.
    """
    from franklinwh_direct_connect_bridge.client import grid_present
    assert grid_present({"grid_leg_v": [120.2, 120.2]}) is True


def test_grid_absent_reads_as_no_grid():
    from franklinwh_direct_connect_bridge.client import grid_present
    assert grid_present({"grid_leg_v": [0.0, 0.0]}) is False


def test_one_live_leg_still_counts_as_grid_present():
    """A single lost leg is not a full outage, and must not be reported as one."""
    from franklinwh_direct_connect_bridge.client import grid_present
    assert grid_present({"grid_leg_v": [120.1, 0.0]}) is True


def test_grid_presence_unknown_when_not_measured():
    from franklinwh_direct_connect_bridge.client import grid_present
    assert grid_present({}) is None


# --- the start-up frame after a reboot (#288, HA Live 2026-10-21) -------------------------

def _starting_frame():
    """What the aGate reported about a minute after a reboot: every 1301 value 0, while the
    aPower said 99% and the grid voltage was present."""
    return {"power": {"soc": 0, "grid_w": 0, "solar_w": 0, "battery_w": 0, "load_w": 0,
                      "run_status": 0, "dsp_run_status": 0, "main_sw": [0, 0, 0]},
            "relays": {"mainRelay1Status": 0, "mainRelay2Status": 0}}


def test_a_start_up_frame_is_not_off_grid_and_not_an_empty_battery():
    out = _starting_frame()
    _apply_off_grid(out)
    p = out["power"]
    assert p["off_grid"] is False and p["agate_starting"] is True and p["soc"] is None
    assert p["off_grid_signals"]["grid_relay"] is True      # still recorded, for diagnosis


def test_offgrid_state_decides_over_open_relays():
    out = _starting_frame()
    out["power"].update(soc=55, offgrid_state=0)
    _apply_off_grid(out)
    assert out["power"]["off_grid"] is False
    assert out["power"]["off_grid_disagreement"] is True


def test_relays_alone_need_both_to_agree_without_1723():
    out = {"power": {"soc": 60, "grid_w": 0, "main_sw": [0, 0, 1]},
           "relays": {"mainRelay1Status": 1, "mainRelay2Status": 1}}
    _apply_off_grid(out)
    assert out["power"]["off_grid"] is False
