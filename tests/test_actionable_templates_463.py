"""#463: the off-grid sensors (grid.offgrid_reason, grid.offgrid_min) and the six Ask
templates built on them and on the tariff sensors. No device or Home Assistant is touched:
the Ask step and the force are replaced by recorders."""
import datetime as dt

import pytest

from franklinwh_direct_connect_bridge import scheduler as sch

T0 = 1_800_000_000.0


# ── sensors ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("state, reason", [
    ({"off_grid": True, "off_grid_kind": "simulated"}, "user requested"),
    ({"off_grid": True, "off_grid_kind": "outage"}, "grid outage"),
    ({"off_grid": True, "off_grid_kind": None}, "unknown"),
    ({"off_grid": False, "off_grid_kind": None}, None),
    ({}, None),
])
def test_offgrid_reason_from_snapshot(state, reason):
    assert sch.snapshot_from_state(state)["grid.offgrid_reason"] == reason


def test_offgrid_min_counts_from_the_period_start():
    st = {"off_grid": True, "off_grid_kind": "simulated", "off_grid_since": T0}
    assert sch.snapshot_from_state(st, now_ts=T0)["grid.offgrid_min"] == 0
    assert sch.snapshot_from_state(st, now_ts=T0 + 29 * 60 + 59)["grid.offgrid_min"] == 29
    assert sch.snapshot_from_state(st, now_ts=T0 + 30 * 60)["grid.offgrid_min"] == 30
    # On grid there is no value, even with a stale start time.
    assert sch.snapshot_from_state({**st, "off_grid": False},
                                   now_ts=T0 + 3600)["grid.offgrid_min"] is None
    # Off-grid with no recorded start is no reading, never a guess.
    assert sch.snapshot_from_state({"off_grid": True},
                                   now_ts=T0)["grid.offgrid_min"] is None


def test_off_grid_since_tracks_transitions_and_restart():
    since = sch.off_grid_since(None, False, T0)
    assert since is None
    since = sch.off_grid_since(since, True, T0 + 60)        # goes off-grid
    assert since == T0 + 60
    since = sch.off_grid_since(since, True, T0 + 600)       # still off-grid: kept
    assert since == T0 + 60
    since = sch.off_grid_since(since, None, T0 + 660)       # no reading: kept
    assert since == T0 + 60
    assert sch.off_grid_since(since, False, T0 + 700) is None   # back on grid
    # Restart while already off-grid: no memory, so counting starts at the first reading.
    assert sch.off_grid_since(None, True, T0 + 5000) == T0 + 5000


def test_offgrid_sensors_in_the_gateway_catalogue():
    ids = dict(sch.SENSORS)
    assert "grid.offgrid_reason" in ids and "grid.offgrid_min" in ids
    assert "restart" in ids["grid.offgrid_min"]
    assert {"grid.offgrid_reason", "grid.offgrid_min"} <= sch.known_sensor_ids()


# ── templates ──────────────────────────────────────────────────────────────────
ASK_TEMPLATES = {
    # id: (action kind/direction, requires, buttons, (true snapshot, false snapshot))
    "offgrid_user_ask": (("offgrid", None), None, ["Go back on-grid", "Stay off-grid"],
                         ({"grid.offgrid_reason": "user requested", "grid.offgrid_min": 30},
                          {"grid.offgrid_reason": "user requested", "grid.offgrid_min": 29})),
    "offgrid_outage_ask": (("", None), None, ["Acknowledge", "Dismiss"],
                           ({"grid.offgrid_reason": "grid outage", "grid.offgrid_min": 45},
                            {"grid.offgrid_reason": "user requested", "grid.offgrid_min": 45})),
    "spot_low_charge_ask": (("force", "charge"), "modbus", ["Charge", "Not now"],
                            ({"tariff.spot_price": 5}, {"tariff.spot_price": 5.01})),
    "tariff_low_charge_ask": (("force", "charge"), "modbus", ["Charge", "Not now"],
                              ({"tariff.buy_rate": 0.05}, {"tariff.buy_rate": 0.051})),
    # High price exports only at or above the min-discharge SoC constant.
    "spot_high_export_ask": (("force", "discharge"), "modbus", ["Export", "Hold"],
                             ({"tariff.spot_price": 50, "battery.soc_pct": 20,
                               "const.min_discharge_soc": 20},
                              {"tariff.spot_price": 50, "battery.soc_pct": 19,
                               "const.min_discharge_soc": 20})),
    "tariff_high_export_ask": (("force", "discharge"), "modbus", ["Export", "Hold"],
                               ({"tariff.sell_rate": 0.5, "battery.soc_pct": 60,
                                 "const.min_discharge_soc": 20},
                                {"tariff.sell_rate": 0.49, "battery.soc_pct": 60,
                                 "const.min_discharge_soc": 20})),
    # Demand window stops grid charging only at or above the demand-charge min SoC.
    "demand_window_ask": (("force", "standby"), "modbus", ["No grid charging", "Leave it"],
                          ({"tariff.demand_window_active": 1, "battery.soc_pct": 30,
                            "const.demand_charge_min_soc": 30},
                           {"tariff.demand_window_active": 1, "battery.soc_pct": 29,
                            "const.demand_charge_min_soc": 30})),
    "bonus_window_ask": (("force", "discharge"), "modbus", ["Export", "Hold"],
                         ({"tariff.bonus_window_active": 1},
                          {"tariff.bonus_window_active": 0})),
}


@pytest.mark.parametrize("pid", sorted(ASK_TEMPLATES))
def test_ask_template_shape_and_validation(pid):
    (kind, direction), requires, buttons, _ = ASK_TEMPLATES[pid]
    p = sch.preset(pid)
    assert p is not None, f"template {pid} missing"
    spec = p["spec"]
    assert p.get("requires") == requires
    assert spec["trigger_type"] == "always"
    assert spec["action"]["kind"] == kind
    if direction:
        assert spec["action"]["direction"] == direction
    ask = spec["ask"]
    assert ask["timeout_min"] == 5 and ask["if_no_reply"] == "skip"
    assert "%" in ask["question"]
    assert [c["label"] for c in ask["choices"]] == buttons
    assert ask["choices"][0]["then"] == "run"
    assert sch.validate_spec(spec) == []
    rep = sch.validate_import({"name": p["name"], **spec}, gateway_ids=set(), device_ids=set())
    assert rep["ok"], rep["errors"]
    assert not rep["warnings"], rep["warnings"]


@pytest.mark.parametrize("pid", sorted(ASK_TEMPLATES))
def test_ask_template_conditions_match_at_threshold(pid):
    spec = sch.preset(pid)["spec"]
    yes, no = ASK_TEMPLATES[pid][3]
    assert sch.evaluate(spec["conditions"], yes, spec["match"]) is True
    assert sch.evaluate(spec["conditions"], no, spec["match"]) is False
    assert sch.evaluate(spec["conditions"], {}, spec["match"]) is False


def test_eight_ask_templates():
    assert len([p for p in sch.PRESETS if (p["spec"].get("ask") or {})]) == 8


def test_price_gates_fail_closed_on_the_other_condition():
    """High price alone does not export below the min SoC; the demand window alone does not
    stop charging below the demand-charge min SoC; and the cheap/high price is checked too."""
    for pid in ("spot_high_export_ask", "tariff_high_export_ask"):
        spec = sch.preset(pid)["spec"]
        price = spec["conditions"][0]
        snap = {price["sensor"]: price["value"], "battery.soc_pct": 90,
                "const.min_discharge_soc": 20}
        assert sch.evaluate(spec["conditions"], snap, "all") is True
        assert sch.evaluate(spec["conditions"], {**snap, "battery.soc_pct": 10}, "all") is False
    spec = sch.preset("demand_window_ask")["spec"]
    snap = {"tariff.demand_window_active": 0, "battery.soc_pct": 90,
            "const.demand_charge_min_soc": 30}
    assert sch.evaluate(spec["conditions"], snap, "all") is False


def test_offgrid_templates_match_the_live_sensor_text():
    """The template's text must match what snapshot_from_state actually produces."""
    for pid, kind in (("offgrid_user_ask", "simulated"), ("offgrid_outage_ask", "outage")):
        spec = sch.preset(pid)["spec"]
        snap = sch.snapshot_from_state({"off_grid": True, "off_grid_kind": kind,
                                        "off_grid_since": T0}, now_ts=T0 + 31 * 60)
        assert sch.evaluate(spec["conditions"], snap, spec["match"]) is True
        snap = sch.snapshot_from_state({"off_grid": False, "off_grid_kind": None,
                                        "off_grid_since": T0}, now_ts=T0 + 31 * 60)
        assert sch.evaluate(spec["conditions"], snap, spec["match"]) is False


def test_offgrid_user_template_asks_once_per_period(tmp_path, monkeypatch):
    """Through the real tick: the Ask fires once when 30 min is reached, not every tick,
    and again only for the next off-grid period."""
    from franklinwh_direct_connect_bridge.db import MetricsStore
    asked = []

    def fake_step(entry, *, store, gateway_id, now, snapshot=None):
        asked.append((now, snapshot.get("grid.offgrid_min")))
        return "skip", "test: Stay off-grid"

    monkeypatch.setattr(sch, "_ask_step", fake_step)
    monkeypatch.setattr(sch, "ha_snapshot", lambda store: {})
    p = sch.preset("offgrid_user_ask")
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="og", name=p["name"],
                       spec={**p["spec"], "gateway_id": "gw-o", "enabled": True})
    sch._window_inside.clear(); sch._window_key.clear(); sch._dwell_since.clear()
    start = dt.datetime(2026, 11, 4, 12, 0)

    def tick(minute, off_grid=True):
        now = start + dt.timedelta(minutes=minute)
        state = {"soc": 60, "off_grid": off_grid,
                 "off_grid_kind": "simulated" if off_grid else None,
                 "off_grid_since": start.timestamp() if off_grid else None}
        sch.tick(settings=None, client=None, store=st, state=state, host="",
                 gateway_id="gw-o", now=now, modbus_host="")

    for m in (10, 29, 30, 31, 45):
        tick(m)
    assert [a[1] for a in asked] == [30]
    tick(50, off_grid=False)
    assert len(asked) == 1
