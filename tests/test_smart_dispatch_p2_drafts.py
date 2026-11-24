"""Smart Dispatch phase 2, step 1: the plan as draft schedules (owner 2026-11-24, #612).

Runs of the same half-hour action become one-off scheduler tasks (force charge, discharge or
standby, auto-released at the window's end), split at midnight. They are only shown: nothing
is created and nothing is written. Clashes with the user's battery schedules, a gateway in
Time-of-Use and force being unavailable are said."""
import datetime as dt
import pathlib
from zoneinfo import ZoneInfo

from franklinwh_direct_connect_bridge import battery_control, scheduler, smart_dispatch

from test_smart_dispatch_p1 import NOW, seed_load, st, tariff  # noqa: F401  (fixture)

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
SYD = ZoneInfo("Australia/Sydney")
T0 = int(dt.datetime(2026, 11, 17, 22, 0, tzinfo=SYD).timestamp())


def row(i, action, kw, soc):
    return {"start": T0 + i * 1800, "duration_s": 1800, "action": action, "battery_kw": kw,
            "soc_pct": soc, "reason": f"why {action}"}


def drafts(steps, existing=(), **kw):
    return smart_dispatch.drafts({"steps": steps}, "gw1", SYD, existing=list(existing), **kw)


def test_runs_become_force_tasks_split_at_midnight():
    steps = [row(0, "self", 0.0, 20), row(1, "charge", 4.0, 35), row(2, "charge", 5.0, 50),
             row(3, "charge", 5.0, 65), row(4, "charge", 4.5, 80), row(5, "hold", 0.1, 80),
             row(6, "hold", -1.5, 75), row(7, "discharge", -5.0, 60)]
    out = drafts(steps)["tasks"]
    got = [(t["spec"]["start_date"], t["spec"]["fire_at"], t["spec"]["duration_min"],
            t["spec"]["action"]) for t in out]
    assert got == [
        ("2026-11-17", "22:30", 90, {"kind": "force", "direction": "charge", "unit": "kw",
                                     "power": 5.0, "target_soc": 65}),
        ("2026-11-18", "00:00", 30, {"kind": "force", "direction": "charge", "unit": "kw",
                                     "power": 4.5, "target_soc": 80}),
        ("2026-11-18", "00:30", 30, {"kind": "force", "direction": "standby", "unit": "kw"}),
        ("2026-11-18", "01:00", 30, {"kind": "force", "direction": "discharge", "unit": "kw",
                                     "power": 1.5, "target_soc": 75}),
        ("2026-11-18", "01:30", 30, {"kind": "force", "direction": "discharge", "unit": "kw",
                                     "power": 5.0, "target_soc": 60}),
    ]
    for t in out:
        s = t["spec"]
        assert s["trigger_type"] == "once" and s["end_date"] == s["start_date"]
        assert s["gateway_id"] == "gw1" and t["name"].startswith("Smart Dispatch: ")
        assert scheduler.validate_spec(s) == [], t
        assert t["reason"]
    assert out[0]["label"] == "Charge from grid" and out[2]["label"] == "Hold"


def test_self_consumption_alone_drafts_nothing():
    assert drafts([row(i, "self", 0.0, 50) for i in range(4)])["tasks"] == []


def test_clashes_with_the_users_battery_schedules_are_named():
    steps = [row(1, "charge", 4.0, 35)]                  # 22:30–23:00
    mine = {"id": "a", "name": "Evening TOU", "enabled": True, "gateway_id": "gw1",
            "fire_at": "22:00", "duration_min": 60, "action": {"kind": "set_mode", "mode": "tou"}}
    other_gw = {**mine, "id": "b", "name": "Other gateway", "gateway_id": "gw2"}
    notify = {**mine, "id": "c", "name": "Just a notice", "action": {}}
    off = {**mine, "id": "d", "name": "Disabled", "enabled": False}
    later = {**mine, "id": "e", "name": "Later", "fire_at": "23:00"}
    t = drafts(steps, [mine, other_gw, notify, off, later])["tasks"][0]
    assert t["clashes"] == ["Evening TOU"]


def test_tou_mode_and_force_unavailable_are_noted(monkeypatch):
    steps = [row(1, "charge", 4.0, 35)]
    notes = drafts(steps, mode="Time-of-Use", force=(False, "Modbus client is off"))["notes"]
    assert any("Time-of-Use" in n for n in notes)
    assert any("Modbus client is off" in n for n in notes)
    assert drafts(steps, mode="Self-Consumption", force=(True, ""))["notes"] == []


def test_the_view_shows_drafts_and_creates_nothing(st, monkeypatch):  # noqa: F811
    tariff(st)
    seed_load(st)
    monkeypatch.setattr(battery_control, "available", lambda: (True, ""))
    def boom(*a, **k):
        raise AssertionError("drafts must not write")
    monkeypatch.setattr(battery_control, "execute", boom)
    smart_dispatch.save(st, "gw1", {"objective": "lowest_cost", "grid_charge": "allowed"})
    r = smart_dispatch.view(st, None, "gw1", NOW, force=True)
    tasks = r["drafts"]["tasks"]
    assert tasks and any(t["spec"]["action"]["direction"] == "charge" for t in tasks)
    assert any("Time-of-Use" in n for n in r["drafts"]["notes"])     # the fixture's mode
    assert st.schedules() == []
    assert r["controls"] is False


def test_the_tab_has_the_drafts_card():
    html = (PKG / "templates" / "tabs" / "smart_dispatch.html").read_text()
    assert 'data-testid="sd-drafts"' in html


def test_a_hold_that_still_charges_from_solar_is_left_to_self_consumption():
    # Forcing a charge could take it from the grid; self-consumption stores the solar as it
    # comes, earlier than planned.
    assert drafts([row(0, "hold", 2.0, 30), row(1, "hold", 1.0, 35)])["tasks"] == []
