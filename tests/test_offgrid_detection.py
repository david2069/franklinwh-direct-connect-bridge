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
