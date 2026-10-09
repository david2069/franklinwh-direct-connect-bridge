"""Schedule engine: windows, conditions, variables, and honest action limits."""
import datetime as dt

import pytest

from franklinwh_direct_connect_bridge import scheduler as sch

SNAP = {"battery.soc_pct": 62, "grid.connected": 1, "mode.name": "Self-Consumption"}


# ── message variables ────────────────────────────────────────────────────────
def test_variables_are_substituted_from_live_values():
    assert sch.substitute("SoC %battery.soc_pct%%", SNAP) == "SoC 62%"


def test_unreadable_variable_renders_as_question_mark_not_a_failure():
    """A notification missing one field beats one that never arrives."""
    assert sch.substitute("x=%nope.sensor%", SNAP) == "x=?"


# ── conditions ───────────────────────────────────────────────────────────────
def test_missing_sensor_never_counts_as_true():
    """An absent reading must not be able to fire an action."""
    assert sch.evaluate([{"sensor": "nope", "op": "==", "value": 1}], SNAP) is False


def test_match_all_and_any():
    rows = [{"sensor": "battery.soc_pct", "op": ">=", "value": 50},
            {"sensor": "grid.connected", "op": "==", "value": 0}]
    assert sch.evaluate(rows, SNAP, "all") is False
    assert sch.evaluate(rows, SNAP, "any") is True


def test_numeric_comparison_handles_string_values():
    assert sch.evaluate([{"sensor": "battery.soc_pct", "op": ">", "value": "50"}], SNAP)


def test_no_conditions_means_always_true():
    assert sch.evaluate([], SNAP) is True


# ── windows ──────────────────────────────────────────────────────────────────
def test_window_inside_and_outside():
    e = {"fire_at": "18:00", "duration_min": 90}
    assert sch.window_state(e, dt.datetime(2026, 9, 15, 18, 30)) == "inside"
    assert sch.window_state(e, dt.datetime(2026, 9, 15, 17, 59)) == "before"
    assert sch.window_state(e, dt.datetime(2026, 9, 15, 19, 31)) == "after"


def test_window_crossing_midnight():
    """22:00 for 300 minutes is still inside at 01:00 — a naive start<=now<end
    comparison gets this wrong."""
    e = {"fire_at": "22:00", "duration_min": 300}
    assert sch.window_state(e, dt.datetime(2026, 9, 15, 1, 0)) == "inside"
    assert sch.window_state(e, dt.datetime(2026, 9, 15, 23, 0)) == "inside"
    assert sch.window_state(e, dt.datetime(2026, 9, 15, 12, 0)) == "before"


# ── due() explains itself ────────────────────────────────────────────────────
def test_due_reports_why_it_did_not_fire():
    e = {"enabled": 1, "fire_at": "18:00", "duration_min": 90,
         "conditions": [{"sensor": "battery.soc_pct", "op": ">", "value": 90}]}
    at = dt.datetime(2026, 9, 15, 18, 30)
    assert sch.due(e, at, SNAP, None) == (False, "entry conditions not met")
    assert sch.due({**e, "enabled": 0}, at, SNAP, None)[1] == "disabled"
    assert sch.due(e, dt.datetime(2026, 9, 15, 3, 0), SNAP, None)[1] == "outside its window"


def test_fires_once_per_day():
    e = {"enabled": 1, "fire_at": "18:00", "duration_min": 90}
    at = dt.datetime(2026, 9, 15, 18, 30)
    assert sch.due(e, at, SNAP, None)[0] is True
    assert sch.due(e, at, SNAP, "2026-09-15") == (False, "already fired this occurrence")


# ── what the local channel genuinely cannot do ───────────────────────────────
def test_force_is_now_offered_via_direct_modbus():
    """Force charge/discharge/standby are offered through the direct-Modbus path
    (battery_control) — one `force` action with a direction, gated on Modbus at
    the API. The old per-direction UNAVAILABLE stubs are gone."""
    assert "force" in sch.ACTIONS
    assert sch.ACTIONS["force"].get("requires") == "modbus"
    for p in ("direction", "power", "unit", "target_soc"):
        assert p in sch.ACTIONS["force"]["params"]
    for kind in ("force_charge", "force_discharge", "force_standby"):
        assert kind not in sch.UNAVAILABLE


def test_unavailable_action_reports_the_reason_when_run():
    # A still-unavailable action (schedule writes the gateway discards) reports why.
    out = sch.run_action({"kind": "smart_circuit_schedule"}, settings=None, client=None,
                         store=None, snapshot={})
    assert "skipped" in out and "discards" in out
    # An unknown action names itself rather than firing blind.
    out2 = sch.run_action({"kind": "nonsense"}, settings=None, client=None,
                          store=None, snapshot={})
    assert "unknown action 'nonsense'" in out2


def test_force_without_dispatch_path_skips_safely():
    # With no gateway host reachable, force reports a skip instead of raising.
    out = sch.run_action({"kind": "force", "direction": "discharge", "power": 50,
                          "unit": "pct"}, settings=None, client=None, store=None,
                         snapshot={}, host=None, window_min=60, gateway_id=None)
    assert "force skipped" in out and "Modbus" in out


def test_reserve_soc_says_it_needs_a_provider():
    out = sch.run_action({"kind": "reserve_soc"}, settings=None, client=None,
                         store=None, snapshot={})
    assert "no local write path" in out


def test_smart_circuit_schedule_is_not_offered():
    assert "smart_circuit_schedule" in sch.UNAVAILABLE
    assert "discards" in sch.UNAVAILABLE["smart_circuit_schedule"]


def test_action_failure_is_captured_not_raised():
    """One bad step must not kill the rest of the run."""
    class Boom:
        def set_mode(self, *a, **k): raise RuntimeError("gateway offline")
    out = sch.run_action({"kind": "set_mode", "mode": "tou"}, settings=None,
                         client=Boom(), store=None, snapshot={})
    assert "failed" in out and "gateway offline" in out


def test_snapshot_marks_derived_values():
    snap = sch.snapshot_from_state({"soc": 50, "grid_w": 0})
    assert snap["battery.soc_pct"] == 50
    assert snap["grid.connected"] == 0, "derived from grid power, not a device field"


def test_operating_mode_is_a_picker_not_a_text_box():
    """The operating work modes are a fixed set of three — Time-of-Use,
    Self-Consumption and Emergency Backup. A free-text box let meaningless values
    like 0 be typed in; there is no mode 0 (run_status 0 is Standby, a STATUS)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    js = (root / "static/js/scheduler_tab.js").read_text()
    assert "modeOptions" in js and "paramChoices" in js
    assert "'Time-of-Use'" in js and "'Self-Consumption'" in js and "'Emergency Backup'" in js
    # workmode is the stable alias; id is a site GUID and name can be a tariff
    assert "workmode" in js
    html = (root / "templates/tabs/scheduler.html").read_text()
    assert "paramChoices(p)" in html
    assert "tou | self | backup" not in html, "the free-text placeholder was the bug"


# ── exposed HA entities as scheduler conditions ──────────────────────────────
def _store_with_exposed(tmp_path):
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "t.db"))
    st.create_ha_instance(ha_id="i1", name="HA Live", base_url="http://x", token="t")
    st.set_ha_exposed("i1", "sensor.amber_price", True)
    st.set_ha_exposed("i1", "binary_sensor.export_window", True)
    return st


def test_exposed_ha_entities_appear_as_scheduler_sensors(tmp_path):
    """Only exposed entities become conditions — the whole point of the checkbox."""
    st = _store_with_exposed(tmp_path)
    opts = sch.ha_sensor_options(st)
    ids = {o["id"] for o in opts}
    assert "ha:i1:sensor.amber_price" in ids
    assert all(o["group"] == "HA Live" for o in opts), "grouped by instance"


def test_only_exposed_entities_are_read_not_the_whole_instance(tmp_path, monkeypatch):
    """A tick that pulled all thousands of entities would hammer HA."""
    st = _store_with_exposed(tmp_path)
    seen = {}

    def fake_states(base, token):
        seen["called"] = True
        return [
            {"entity_id": "sensor.amber_price", "state": "12.5"},
            {"entity_id": "sensor.not_exposed", "state": "1"},
            {"entity_id": "binary_sensor.export_window", "state": "on"},
        ]
    monkeypatch.setattr(sch.ha_instances, "states", fake_states)
    snap = sch.ha_snapshot(st)
    assert snap == {"ha:i1:sensor.amber_price": 12.5,
                    "ha:i1:binary_sensor.export_window": 1}
    assert "ha:i1:sensor.not_exposed" not in snap


def test_ha_binary_state_coerces_for_numeric_conditions():
    assert sch._coerce("on") == 1 and sch._coerce("off") == 0
    assert sch._coerce("unavailable") == 0
    assert sch._coerce("42.5") == 42.5
    assert sch._coerce("Self-Consumption") == "Self-Consumption"


def test_no_exposed_entities_means_no_ha_reads(tmp_path, monkeypatch):
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "t.db"))
    called = {"n": 0}
    monkeypatch.setattr(sch.ha_instances, "states",
                        lambda b, t: called.__setitem__("n", called["n"] + 1) or [])
    assert sch.ha_snapshot(st) == {} and called["n"] == 0


def test_schedule_carries_a_gateway_binding(tmp_path):
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "t.db"))
    st.create_schedule(sid="s1", name="Shed evening",
                       spec={"gateway_id": "gw-shed", "fire_at": "18:00"})
    assert st.schedule("s1")["gateway_id"] == "gw-shed"


def test_bound_schedule_fires_only_on_its_gateway(tmp_path, monkeypatch):
    """A battery action must target the aGate it was bound to, not whichever
    gateway's poll tick happens to run it."""
    import datetime as dt
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "t.db"))
    st.create_schedule(sid="s1", name="Shed",
                       spec={"gateway_id": "gw-shed", "fire_at": "18:00",
                             "duration_min": 90, "conditions": [], "action": {},
                             "ha_actions": []})
    monkeypatch.setattr(sch, "ha_snapshot", lambda store: {})
    at = dt.datetime(2026, 9, 15, 18, 30)
    # the OTHER gateway's tick must skip it
    assert sch.tick(settings=None, client=None, store=st, state={},
                    gateway_id="gw-home", now=at) == []
    # its own gateway's tick fires it
    fired = sch.tick(settings=None, client=None, store=st, state={},
                     gateway_id="gw-shed", now=at)
    assert len(fired) == 1 and fired[0]["id"] == "s1"


def test_gateway_roster_uses_real_gatewaystate_fields():
    """Regression: the roster used g.name, which GatewayState does not have, so
    /api/schedules 500'd. GatewayState has label/serial/id — never name."""
    from franklinwh_direct_connect_bridge.state import GatewayState
    g = GatewayState(id="10.0.0.5", label="Shed", configured_host="10.0.0.5")
    # the exact expression the endpoint builds
    row = {"id": g.id, "name": g.label or g.serial or g.id,
           "host": g.active_host or g.configured_host}
    assert row == {"id": "10.0.0.5", "name": "Shed", "host": "10.0.0.5"}
    assert not hasattr(g, "name"), "if this ever gains .name, simplify the roster"


# ── presets / export / import ────────────────────────────────────────────────
def test_presets_use_only_available_actions():
    """No force-charge preset — the local channel cannot do it."""
    kinds = {p["spec"].get("action", {}).get("kind") for p in sch.PRESETS}
    assert kinds <= set(sch.ACTIONS) | {"", None}
    assert not (kinds & set(sch.UNAVAILABLE))


def test_portable_drops_ids_and_runtime_state():
    entry = {"id": "x", "name": "n", "fire_at": "18:00", "action": {"kind": "set_mode"},
             "last_fired_day": "2026-09-15", "last_result": "ok"}
    p = sch.portable(entry)
    assert "id" not in p and "last_fired_day" not in p
    assert p["name"] == "n" and p["fire_at"] == "18:00"


def test_import_validation_catches_bad_and_warns_on_missing_refs():
    bad = sch.validate_import(
        {"name": "b", "fire_at": "99:99", "action": {"kind": "smart_circuit_schedule"},
         "gateway_id": "ghost", "ha_actions": [{"device_id": "gone"}]},
        gateway_ids=set(), device_ids=set())
    assert bad["ok"] is False
    assert any("HH:MM" in e for e in bad["errors"])
    assert any("discards" in e for e in bad["errors"])        # unavailable action named
    assert any("default gateway" in w for w in bad["warnings"])
    assert any("device" in w for w in bad["warnings"])


def test_export_import_round_trip(tmp_path):
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "t.db"))
    st.create_schedule(sid="s1", name="Evening",
                       spec={"fire_at": "18:00", "action": {"kind": "set_mode", "mode": "tou"}})
    bundle = {"type": sch.EXPORT_TYPE, "version": sch.EXPORT_VERSION,
              "entries": [sch.portable(st.schedule("s1"))]}
    rep = sch.validate_import(bundle["entries"][0], gateway_ids=set(), device_ids=set())
    assert rep["ok"] is True


# ── log + timeline ───────────────────────────────────────────────────────────
def test_fire_history_is_logged_and_filterable(tmp_path):
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "t.db"))
    st.log_schedule_event("s1", "Evening", "fired", "mode -> tou: ok", now=100)
    st.log_schedule_event("s1", "Evening", "error", "circuit 2: NOT confirmed", now=200)
    st.log_schedule_event("s2", "Alert", "fired", "notify: sent", now=300)
    events = st.schedule_log()
    assert events[0]["name"] == "Alert" and events[0]["ts"] == 300   # newest first
    assert len(st.schedule_log(schedule_id="s1")) == 2
    assert st.schedule_log(status="error")[0]["result"] == "circuit 2: NOT confirmed"


def test_log_is_capped(tmp_path):
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "t.db"))
    for i in range(2100):
        st.log_schedule_event("s", "x", "fired", str(i), now=float(i))
    assert len(st.schedule_log(limit=500)) == 500
    # oldest were pruned: the 2000-cap keeps only the newest
    all_ts = {e["ts"] for e in st.schedule_log(limit=500)}
    assert min(all_ts) >= 1600.0


def test_a_fire_that_did_nothing_still_logs_why(tmp_path, monkeypatch):
    import datetime as dt
    from franklinwh_direct_connect_bridge.db import MetricsStore
    st = MetricsStore(str(tmp_path / "t.db"))
    st.create_schedule(sid="s1", name="Empty",
                       spec={"fire_at": "18:00", "duration_min": 90,
                             "conditions": [], "action": {}, "ha_actions": []})
    monkeypatch.setattr(sch, "ha_snapshot", lambda store: {})
    sch.tick(settings=None, client=None, store=st, state={},
             gateway_id=None, now=dt.datetime(2026, 9, 16, 18, 30))
    log = st.schedule_log()
    assert log and log[0]["result"] == "nothing to do" and log[0]["status"] == "fired"


def test_timeline_wrapping_window_flagged():
    import datetime as dt
    tl = sch.timeline_segments(
        [{"id": "a", "name": "Overnight", "enabled": True, "fire_at": "22:00",
          "duration_min": 300, "action": {"kind": "set_mode"}}],
        dt.datetime(2026, 9, 16, 1, 0))
    seg = tl["segments"][0]
    assert seg["start_min"] == 1320 and seg["wraps_midnight"] is True
    assert tl["now_min"] == 60


def test_disabled_schedule_absent_from_timeline():
    import datetime as dt
    tl = sch.timeline_segments(
        [{"id": "a", "name": "off", "enabled": False, "fire_at": "12:00"}],
        dt.datetime(2026, 9, 16, 1, 0))
    assert tl["segments"] == []


def test_exit_condition_ends_window_early_and_releases(tmp_path, monkeypatch):
    """An exit-condition tree closes the window early: it fires the exit edge, RELEASES a
    force dispatch, logs 'exit condition met', and does not re-fire the same day."""
    import datetime as dt
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore

    seen = []
    monkeypatch.setattr(bc, "execute",
                        lambda cmd, **kw: (seen.append(cmd),
                                           {"ok": True, "result": "ok",
                                            "active": cmd if cmd not in ("Release", "Not Active") else "Not Active"})[1])
    monkeypatch.setattr(bc, "current", lambda: {"active": "Force Discharge"})

    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="x1", name="Peak w/ early stop", spec={
        "fire_at": "13:50", "duration_min": 60, "enabled": True,
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50},
        "exit_conditions": [{"sensor": "battery.soc_pct", "op": "<=", "value": 20}],
        "exit_match": "all"})
    sch._window_inside.clear(); sch._dwell_since.clear(); sch._gated_day.clear()

    now = dt.datetime(2026, 9, 22, 14, 0, 0)                     # inside 13:50–14:50
    fired = sch.tick(settings=None, client=None, store=st, state={"soc": 50},
                     host="h", gateway_id=None, now=now)
    assert any(f["id"] == "x1" for f in fired) and "Force Discharge" in seen

    seen.clear()
    sch.tick(settings=None, client=None, store=st, state={"soc": 15},   # SoC hits the floor
             host="h", gateway_id=None, now=now + dt.timedelta(minutes=5))
    assert "Release" in seen                                     # released early
    logs = st.schedule_log(schedule_id="x1")
    assert any(l["status"] == "exit" and "exit condition" in (l["result"] or "") for l in logs)

    seen.clear()
    sch.tick(settings=None, client=None, store=st, state={"soc": 50},   # recovers — must not re-fire
             host="h", gateway_id=None, now=now + dt.timedelta(minutes=10))
    assert "Force Discharge" not in seen


def test_exit_condition_blocks_firing_when_already_true(tmp_path, monkeypatch):
    """If the exit condition already holds when the window opens, the dispatch never starts."""
    import datetime as dt
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore
    seen = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (seen.append(cmd), {"ok": True, "result": "ok", "active": "x"})[1])
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="x2", name="blocked", spec={
        "fire_at": "13:50", "duration_min": 60, "enabled": True,
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50},
        "exit_conditions": [{"sensor": "battery.soc_pct", "op": "<=", "value": 20}]})
    sch._window_inside.clear(); sch._dwell_since.clear(); sch._gated_day.clear()
    fired = sch.tick(settings=None, client=None, store=st, state={"soc": 10},
                     host="h", gateway_id=None, now=dt.datetime(2026, 9, 22, 14, 0, 0))
    assert not fired and "Force Discharge" not in seen


def test_schedule_req_model_carries_exit_conditions():
    """Regression guard: the create/update model must declare exit_conditions/exit_match,
    or the API silently drops them (as it first did)."""
    from franklinwh_direct_connect_bridge.app import ScheduleReq
    r = ScheduleReq(name="x", exit_conditions=[{"sensor": "battery.soc_pct", "op": "<=", "value": 20}],
                    exit_match="any")
    dumped = r.model_dump()
    assert dumped["exit_conditions"] == [{"sensor": "battery.soc_pct", "op": "<=", "value": 20}]
    assert dumped["exit_match"] == "any"
    # and they travel in a portable export
    assert "exit_conditions" in sch._PORTABLE_KEYS and "exit_match" in sch._PORTABLE_KEYS


# ── HA service actions (not just notify) ──────────────────────────────────────
class _InstStore:
    def __init__(self, inst=None): self._inst = inst
    def ha_instance(self, iid):
        if self._inst is None:
            return None
        return {**self._inst, "id": iid}


def test_ha_service_action_calls_the_service(monkeypatch):
    from franklinwh_direct_connect_bridge import ha_instances
    cap = {}
    monkeypatch.setattr(ha_instances, "call_service",
                        lambda base, token, domain, service, data: (cap.update(
                            base=base, token=token, domain=domain, service=service, data=data),
                            {"ok": True})[1])
    out = sch.run_action(
        {"kind": "ha_service", "instance_id": "ha1", "domain": "switch", "service": "turn_on",
         "entity_id": "switch.%mode.name%",
         "data": '{"brightness": 180, "note": "soc %battery.soc_pct%"}'},
        settings=None, client=None, store=_InstStore({"base_url": "http://ha", "token": "T"}),
        snapshot={"mode.name": "backup", "battery.soc_pct": 42}, host=None)
    assert "service switch.turn_on: ok" in out
    assert cap["domain"] == "switch" and cap["service"] == "turn_on"
    assert cap["data"]["entity_id"] == "switch.backup"          # %sensor% substituted in entity
    assert cap["data"]["brightness"] == 180
    assert cap["data"]["note"] == "soc 42"                      # substituted in a string value


def test_ha_service_bad_json_is_reported():
    out = sch.run_action({"kind": "ha_service", "instance_id": "x", "domain": "switch",
                          "service": "turn_on", "data": "{not json"}, settings=None,
                          client=None, store=_InstStore({"base_url": "http://ha", "token": "T"}),
                          snapshot={}, host=None)
    assert "not valid JSON" in out


def test_ha_service_requires_instance_and_fields():
    assert "no HA instance" in sch.run_action(
        {"kind": "ha_service", "instance_id": "gone"}, settings=None, client=None,
        store=_InstStore(None), snapshot={}, host=None)
    assert "domain and service are required" in sch.run_action(
        {"kind": "ha_service", "instance_id": "x", "domain": "switch"}, settings=None,
        client=None, store=_InstStore({"base_url": "http://ha", "token": "T"}),
        snapshot={}, host=None)


def test_fire_ha_phase_dispatches_service_kind(monkeypatch):
    from franklinwh_direct_connect_bridge import ha_instances
    calls = []
    monkeypatch.setattr(ha_instances, "call_service", lambda *a, **k: (calls.append(a), {"ok": True})[1])
    entry = {"ha_actions": [{"ha_kind": "service", "when": "fire", "instance_id": "x",
                             "domain": "scene", "service": "turn_on", "entity_id": "scene.evening"}]}
    res = sch._fire_ha_phase(entry, "fire", settings=None, client=None,
                             store=_InstStore({"base_url": "http://ha", "token": "T"}),
                             snapshot={}, host=None)
    assert calls and res and "scene.turn_on" in res[0]


# ── calendar recurrence (Phase A) ─────────────────────────────────────────────
import datetime as _dtr


def test_recurrence_empty_fires_every_day():
    for wd in range(7):
        d = _dtr.date(2026, 9, 21) + _dtr.timedelta(days=wd)   # 2026-09-21 is a Monday
        assert sch._calendar_ok({}, d)[0] is True


def test_recurrence_days_of_week():
    e = {"days": [0, 2, 4]}                                     # Mon/Wed/Fri
    assert sch._calendar_ok(e, _dtr.date(2026, 9, 21))[0] is True    # Mon
    assert sch._calendar_ok(e, _dtr.date(2026, 9, 22))[0] is False   # Tue
    ok, why = sch._calendar_ok(e, _dtr.date(2026, 9, 22))
    assert "days of the week" in why


def test_recurrence_months_and_day_of_month_with_clamp():
    e = {"months": [1, 4, 7, 10], "day_of_month": 31}
    assert sch._calendar_ok(e, _dtr.date(2026, 1, 31))[0] is True    # Jan 31
    assert sch._calendar_ok(e, _dtr.date(2026, 2, 28))[0] is False   # not a listed month
    # April has 30 days → 31 clamps to the 30th
    assert sch._calendar_ok({"day_of_month": 31}, _dtr.date(2026, 4, 30))[0] is True
    assert sch._calendar_ok({"day_of_month": 31}, _dtr.date(2026, 4, 29))[0] is False


def test_recurrence_date_range_and_one_off():
    e = {"start_date": "2026-09-20", "end_date": "2026-09-22"}
    assert sch._calendar_ok(e, _dtr.date(2026, 9, 19))[0] is False   # before
    assert sch._calendar_ok(e, _dtr.date(2026, 9, 21))[0] is True    # inside
    assert sch._calendar_ok(e, _dtr.date(2026, 9, 23))[0] is False   # after
    one = {"start_date": "2026-12-25", "end_date": "2026-12-25"}
    assert sch._calendar_ok(one, _dtr.date(2026, 12, 25))[0] is True
    assert sch._calendar_ok(one, _dtr.date(2026, 12, 26))[0] is False


def test_window_anchor_date_handles_midnight_wrap():
    e = {"fire_at": "22:00", "duration_min": 300}               # 22:00 → 03:00 next day
    # At 01:00 the window is in its post-midnight tail → anchor is the PREVIOUS day.
    assert sch._window_anchor_date(e, _dtr.datetime(2026, 9, 22, 1, 0)) == _dtr.date(2026, 9, 21)
    # At 22:30 the same evening → anchor is that day.
    assert sch._window_anchor_date(e, _dtr.datetime(2026, 9, 21, 22, 30)) == _dtr.date(2026, 9, 21)


def test_due_reports_recurrence_reason():
    e = {"enabled": True, "fire_at": "14:00", "duration_min": 60, "days": [0]}   # Mon only
    ok, reason = sch.due(e, _dtr.datetime(2026, 9, 22, 14, 30), {}, None)        # Tue
    assert ok is False and "days of the week" in reason
    ok2, _ = sch.due(e, _dtr.datetime(2026, 9, 21, 14, 30), {}, None)            # Mon, in window
    assert ok2 is True


def test_schedule_req_model_carries_recurrence():
    """Regression guard: the create/update model must declare the recurrence fields."""
    from franklinwh_direct_connect_bridge.app import ScheduleReq
    r = ScheduleReq(name="x", days=[0, 2, 4], months=[1, 7], day_of_month=15,
                    start_date="2026-01-01", end_date="2026-12-31")
    d = r.model_dump()
    assert d["days"] == [0, 2, 4] and d["months"] == [1, 7] and d["day_of_month"] == 15
    assert d["start_date"] == "2026-01-01" and d["end_date"] == "2026-12-31"
    for k in ("days", "months", "day_of_month", "start_date", "end_date"):
        assert k in sch._PORTABLE_KEYS


def test_next_fire_and_active_now():
    now = _dtr.datetime(2026, 9, 22, 10, 0)                     # Tue 10:00
    e = {"enabled": True, "fire_at": "14:00", "duration_min": 60}
    # not fired yet today → today 14:00
    nf = sch.next_fire_ts(e, now, None)
    assert dt_from(nf) == _dtr.datetime(2026, 9, 22, 14, 0)
    # already fired today → tomorrow 14:00
    nf2 = sch.next_fire_ts(e, now, "2026-09-22")
    assert dt_from(nf2) == _dtr.datetime(2026, 9, 23, 14, 0)
    # Mon-only → next Monday
    mon = {"enabled": True, "fire_at": "14:00", "duration_min": 60, "days": [0]}
    assert dt_from(sch.next_fire_ts(mon, now, None)) == _dtr.datetime(2026, 9, 28, 14, 0)
    # disabled → None
    assert sch.next_fire_ts({**e, "enabled": False}, now, None) is None
    # active_now: inside window + fired today
    inside = _dtr.datetime(2026, 9, 22, 14, 30)
    assert sch.active_now(e, inside, "2026-09-22") is True
    assert sch.active_now(e, inside, None) is False             # not fired yet
    assert sch.active_now(e, now, "2026-09-22") is False        # not inside window


def dt_from(ts):
    return _dtr.datetime.fromtimestamp(ts)


def test_priority_resolution_defers_lower_on_same_target(tmp_path, monkeypatch):
    """Two schedules firing the same tick for the same gateway: the higher priority runs,
    the lower is deferred for the day (marked fired + logged 'deferred')."""
    import datetime as _d
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore
    ran = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (ran.append(cmd), {"ok": True, "result": "ok", "active": cmd})[1])
    monkeypatch.setattr(bc, "current", lambda: {"active": "Not Active"})
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="lo", name="Low prio charge", spec={
        "fire_at": "14:00", "duration_min": 60, "enabled": True, "priority": 1,
        "action": {"kind": "force", "direction": "charge", "unit": "pct", "power": 50}})
    st.create_schedule(sid="hi", name="High prio discharge", spec={
        "fire_at": "14:00", "duration_min": 60, "enabled": True, "priority": 10,
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}})
    sch._window_inside.clear(); sch._dwell_since.clear(); sch._gated_day.clear()
    fired = sch.tick(settings=None, client=None, store=st, state={"soc": 50},
                     host="h", gateway_id=None, now=_d.datetime(2026, 9, 22, 14, 30))
    names = {f["name"]: f["result"] for f in fired}
    assert "High prio discharge" in names                      # winner ran
    assert ran == ["Force Discharge"]                          # only the winner touched the battery
    # loser marked fired='deferred' and logged 'deferred'
    assert st.schedule("lo")["last_result"] == "deferred"
    assert any(e["status"] == "deferred" for e in st.schedule_log(schedule_id="lo"))


def test_priority_single_entry_unaffected(tmp_path, monkeypatch):
    """A lone gateway action fires normally (no behaviour change without contention)."""
    import datetime as _d
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: {"ok": True, "result": "ok", "active": cmd})
    monkeypatch.setattr(bc, "current", lambda: {"active": "Not Active"})
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="one", name="Solo", spec={
        "fire_at": "14:00", "duration_min": 60, "enabled": True,
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}})
    sch._window_inside.clear(); sch._dwell_since.clear()
    fired = sch.tick(settings=None, client=None, store=st, state={"soc": 50},
                     host="h", gateway_id=None, now=_d.datetime(2026, 9, 22, 14, 30))
    assert [f["name"] for f in fired] == ["Solo"]


def _mk_force_sched(st, sid, name, conflict="override", prio=0):
    st.create_schedule(sid=sid, name=name, spec={
        "fire_at": "14:00", "duration_min": 300, "enabled": True,
        "priority": prio, "conflict": conflict,
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}})


def test_conflict_defer_skips_when_battery_busy(tmp_path, monkeypatch):
    import datetime as _d
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore
    ran = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (ran.append(cmd), {"ok": True, "result": "ok", "active": cmd})[1])
    monkeypatch.setattr(bc, "current", lambda: {"active": "Not Active"})
    st = MetricsStore(str(tmp_path / "m.db"))
    # A dispatch already held by schedule "A".
    st.record_dispatch(schedule_id="A", name="A", gateway_id=None, host="h", direction="discharge",
                       watts=-2000, power_mode="w", target_soc=0, window_start_ts=1, window_end_ts=9e18)
    _mk_force_sched(st, "B", "B defer", conflict="defer")
    sch._window_inside.clear(); sch._dwell_since.clear()
    fired = sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
                     gateway_id=None, now=_d.datetime(2026, 9, 22, 14, 30))
    assert ran == []                                           # B never touched the battery
    assert st.schedule("B")["last_result"] == "deferred"
    assert any(e["status"] == "deferred" for e in st.schedule_log(schedule_id="B"))


def test_conflict_override_takes_control(tmp_path, monkeypatch):
    import datetime as _d
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore
    ran = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (ran.append(cmd), {"ok": True, "result": "ok", "active": cmd})[1])
    monkeypatch.setattr(bc, "current", lambda: {"active": "Not Active"})
    st = MetricsStore(str(tmp_path / "m.db"))
    st.record_dispatch(schedule_id="A", name="A", gateway_id=None, host="h", direction="discharge",
                       watts=-2000, power_mode="w", target_soc=0, window_start_ts=1, window_end_ts=9e18)
    _mk_force_sched(st, "B", "B override", conflict="override")
    sch._window_inside.clear(); sch._dwell_since.clear()
    fired = sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
                     gateway_id=None, now=_d.datetime(2026, 9, 22, 14, 30))
    assert "Force Discharge" in ran                            # B took control
    assert [f["name"] for f in fired] == ["B override"]


def test_conflict_wait_retries_not_fired(tmp_path, monkeypatch):
    import datetime as _d
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: {"ok": True, "result": "ok", "active": cmd})
    monkeypatch.setattr(bc, "current", lambda: {"active": "Not Active"})
    st = MetricsStore(str(tmp_path / "m.db"))
    st.record_dispatch(schedule_id="A", name="A", gateway_id=None, host="h", direction="discharge",
                       watts=-2000, power_mode="w", target_soc=0, window_start_ts=1, window_end_ts=9e18)
    _mk_force_sched(st, "B", "B wait", conflict="wait")
    sch._window_inside.clear(); sch._dwell_since.clear()
    sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h",
             gateway_id=None, now=_d.datetime(2026, 9, 22, 14, 30))
    # wait does NOT mark fired -> stays retry-able
    assert st.schedule("B")["last_fired_day"] in (None, "")
    assert any(e["status"] == "waiting" for e in st.schedule_log(schedule_id="B"))


def test_exit_condition_nested_group_ends_window(tmp_path, monkeypatch):
    """Exit conditions now support nested ALL/ANY groups (same builder as entry)."""
    import datetime as _d
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore
    seen = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (seen.append(cmd), {"ok": True, "result": "ok", "active": cmd})[1])
    monkeypatch.setattr(bc, "current", lambda: {"active": "Force Discharge"})
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="n1", name="nested exit", spec={
        "fire_at": "13:50", "duration_min": 60, "enabled": True,
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50},
        "exit_match": "any",
        "exit_conditions": [{"match": "all", "conditions": [
            {"sensor": "battery.soc_pct", "op": "<=", "value": 20},
            {"sensor": "grid.connected", "op": "==", "value": 1}]}]})
    sch._window_inside.clear(); sch._dwell_since.clear()
    now = _d.datetime(2026, 9, 22, 14, 0)
    sch.tick(settings=None, client=None, store=st, state={"soc": 50, "grid_w": 100}, host="h",
             gateway_id=None, now=now)                          # fires (group false: soc high)
    seen.clear()
    # SoC≤20 AND grid connected → nested group true → exit
    sch.tick(settings=None, client=None, store=st, state={"soc": 15, "grid_w": 100}, host="h",
             gateway_id=None, now=now + _d.timedelta(minutes=5))
    assert "Release" in seen


# ── trigger types (Phase B) ───────────────────────────────────────────────────
def test_trigger_window_multiple_windows():
    e = {"enabled": True, "trigger_type": "window",
         "windows": [{"start": "06:00", "end": "09:00"}, {"start": "17:00", "end": "21:00"}]}
    st, key, _e, _d = sch.window_now(e, _dtr.datetime(2026, 9, 22, 7, 0))
    assert st == "inside" and key == "2026-09-22"           # window 0 → legacy date key
    st2, key2, _e2, _d2 = sch.window_now(e, _dtr.datetime(2026, 9, 22, 18, 0))
    assert st2 == "inside" and key2 == "2026-09-22#1"       # window 1 → distinct key
    assert sch.window_now(e, _dtr.datetime(2026, 9, 22, 12, 0))[0] == "outside"
    # fires once PER window (different keys), so both fire the same day
    assert sch.due(e, _dtr.datetime(2026, 9, 22, 7, 0), {}, None)[0] is True
    assert sch.due(e, _dtr.datetime(2026, 9, 22, 18, 0), {}, "2026-09-22")[0] is True   # window 1 not fired
    assert sch.due(e, _dtr.datetime(2026, 9, 22, 18, 0), {}, "2026-09-22#1")[0] is False


def test_trigger_interval():
    e = {"enabled": True, "trigger_type": "interval", "interval_min": 30,
         "anchor": "00:00", "duration_min": 5}
    st, key, _e, _d = sch.window_now(e, _dtr.datetime(2026, 9, 22, 14, 2))   # 2 min into the 14:00 slot
    assert st == "inside"
    assert sch.window_now(e, _dtr.datetime(2026, 9, 22, 14, 20))[0] == "outside"   # past the 5-min window
    # next fire is the next 30-min slot
    nf = sch.next_fire_ts(e, _dtr.datetime(2026, 9, 22, 14, 10))
    assert _dtr.datetime.fromtimestamp(nf) == _dtr.datetime(2026, 9, 22, 14, 30)


def test_trigger_cron():
    e = {"enabled": True, "trigger_type": "cron", "cron": "0 3 * * *", "duration_min": 10}
    assert sch.window_now(e, _dtr.datetime(2026, 9, 22, 3, 5))[0] == "inside"     # within 10 min of 03:00
    assert sch.window_now(e, _dtr.datetime(2026, 9, 22, 3, 30))[0] == "outside"
    nf = sch.next_fire_ts(e, _dtr.datetime(2026, 9, 22, 4, 0))
    assert _dtr.datetime.fromtimestamp(nf) == _dtr.datetime(2026, 9, 23, 3, 0)    # tomorrow 03:00


def test_trigger_always_fires_on_rising_edge(tmp_path, monkeypatch):
    """'always' dispatches when entry conditions become true and releases when false —
    firing once on the rising edge, not every tick."""
    import datetime as _d
    from franklinwh_direct_connect_bridge import battery_control as bc
    from franklinwh_direct_connect_bridge.db import MetricsStore
    seen = []
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: (seen.append(cmd), {"ok": True, "result": "ok", "active": cmd})[1])
    monkeypatch.setattr(bc, "current", lambda: {"active": "Force Discharge"})
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_schedule(sid="al", name="always high soc", spec={
        "trigger_type": "always", "enabled": True,
        "conditions": [{"sensor": "battery.soc_pct", "op": ">=", "value": 90}],
        "action": {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}})
    sch._window_inside.clear(); sch._dwell_since.clear()
    now = _d.datetime(2026, 9, 22, 12, 0)
    # conditions false → no fire
    sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h", gateway_id=None, now=now)
    assert seen == []
    # rising edge (soc≥90) → fire once
    sch.tick(settings=None, client=None, store=st, state={"soc": 95}, host="h", gateway_id=None, now=now + _d.timedelta(minutes=1))
    assert seen == ["Force Discharge"]
    seen.clear()
    # still true next tick → do NOT re-fire
    sch.tick(settings=None, client=None, store=st, state={"soc": 95}, host="h", gateway_id=None, now=now + _d.timedelta(minutes=2))
    assert seen == []
    # falling edge → release
    sch.tick(settings=None, client=None, store=st, state={"soc": 50}, host="h", gateway_id=None, now=now + _d.timedelta(minutes=3))
    assert "Release" in seen


def test_ha_guided_entity_action_calls_domain_service(monkeypatch):
    """A guided entity action (data as an object) executes exactly like the Modbus
    bridge: POST /api/services/<domain>/<service> with {entity_id, **data}."""
    from franklinwh_direct_connect_bridge import ha_instances
    cap = {}
    monkeypatch.setattr(ha_instances, "call_service",
                        lambda base, token, domain, service, data: (cap.update(
                            domain=domain, service=service, data=data), {"ok": True})[1])
    out = sch.run_action(
        {"kind": "ha_service", "instance_id": "ha1", "domain": "select",
         "service": "select_option", "entity_id": "select.sunamp_boost_state",
         "data": {"option": "On"}},
        settings=None, client=None, store=_InstStore({"base_url": "http://ha", "token": "T"}),
        snapshot={}, host=None)
    assert "service select.select_option: ok" in out
    assert cap["domain"] == "select" and cap["service"] == "select_option"
    assert cap["data"] == {"option": "On", "entity_id": "select.sunamp_boost_state"}


def test_import_only_rejects_truly_unknown_types(tmp_path, monkeypatch):
    """The Modbus 'franklinwh-automations' bundle is now accepted (mapped); only an
    unrecognised type is rejected, with a message naming both supported types."""
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    from franklinwh_direct_connect_bridge.db import MetricsStore
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    c = TestClient(app_module.create_app())
    bad = c.post("/api/schedules/import?dry_run=true",
                 json={"type": "some-other-app", "version": 1, "entries": []})
    assert bad.status_code == 400
    detail = bad.json()["detail"]
    assert sch.EXPORT_TYPE in detail and sch.IMPORT_TYPE_AUTOMATIONS in detail
    # A native bundle dry-run reports count + importable (what the dialog reads).
    good = c.post("/api/schedules/import?dry_run=true",
                  json={"type": sch.EXPORT_TYPE, "version": sch.EXPORT_VERSION,
                        "entries": [{"name": "x", "fire_at": "06:00", "action": {"kind": ""}}]})
    assert good.json()["count"] == 1 and "importable" in good.json()


def test_import_maps_modbus_automations_bundle(tmp_path, monkeypatch):
    """A real 'franklinwh-automations' entry is mapped to our schema: force_charge →
    {kind:force,direction:charge}, trigger_spec→fire_at, duration_s→min, nested conditions,
    HA actions passed through — and it validates + imports (disabled for review)."""
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    from franklinwh_direct_connect_bridge.db import MetricsStore
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    c = TestClient(app_module.create_app())
    bundle = {"type": "franklinwh-automations", "version": 1, "entries": [{
        "name": "Charge at 6am if low", "action": "force_charge", "params": {"power_pct": 100},
        "target_type": "gateway", "target_id": "default", "enabled": False,
        "trigger_kind": "daily", "trigger_spec": {"time_of_day": "06:00"},
        "entry_conditions": {"match": "ALL", "conditions": [
            {"sensor": "battery.soc_pct", "op": "<", "value": 20},
            {"match": "ANY", "conditions": [{"sensor": "grid.connected", "op": "==", "value": 1}]},
        ]},
        "exit_conditions": None, "duration_s": 3600,
        "ha_actions": [{"instance_id": "ha_x", "entity_id": "switch.pv", "service": "turn_on",
                        "data": {}, "when": "fire"}],
    }]}

    # unit-level mapping
    mapped = sch.import_entries("franklinwh-automations", bundle["entries"])[0]
    assert mapped["action"] == {"kind": "force", "direction": "charge", "unit": "pct",
                                "power": 100, "target_soc": 0}
    assert mapped["trigger_type"] == "daily" and mapped["fire_at"] == "06:00"
    assert mapped["duration_min"] == 60 and mapped["match"] == "all"
    assert mapped["conditions"][1] == {"match": "any", "conditions": [
        {"sensor": "grid.connected", "op": "==", "value": 1}]}
    assert mapped["ha_actions"][0]["entity_id"] == "switch.pv"
    assert mapped["gateway_id"] == ""      # "default" → our default gateway

    # end-to-end: dry-run importable, then create disabled
    dry = c.post("/api/schedules/import?dry_run=true", json=bundle).json()
    assert dry["count"] == 1 and dry["importable"] == 1 and dry["mapped_from"] == "franklinwh-automations"
    done = c.post("/api/schedules/import?dry_run=false", json=bundle).json()
    assert len(done["created"]) == 1
    row = store.schedule(done["created"][0])
    assert row["enabled"] == 0 and (row.get("action") or {}).get("direction") == "charge"


def test_dispatch_presets_present_and_valid():
    """The ported Modbus dispatch templates (force charge/discharge) exist, are marked
    modbus-requiring, carry the right action shape, and pass import validation."""
    by_id = {p["id"]: p for p in sch.PRESETS}
    for pid in ("peak_shave", "export_bonus", "solar_sponge", "offpeak_charge"):
        p = by_id[pid]
        assert p.get("requires") == "modbus"
        act = p["spec"]["action"]
        assert act["kind"] == "force" and act["direction"] in ("charge", "discharge")
        assert act["unit"] == "pct" and 0 <= act["target_soc"] <= 100
        # a preset spec, given a name, validates as an importable entry
        rep = sch.validate_import({"name": p["name"], **p["spec"]},
                                  gateway_ids=set(), device_ids=set())
        assert rep["ok"], rep["errors"]
    # peak_shave discharges, solar_sponge charges
    assert by_id["peak_shave"]["spec"]["action"]["direction"] == "discharge"
    assert by_id["solar_sponge"]["spec"]["action"]["direction"] == "charge"


def test_export_to_automations_and_roundtrip():
    """OUR schedule → franklinwh-automations → back to OURS survives a round-trip
    (force action, trigger, duration, nested conditions, HA actions, gateway)."""
    entry = {"name": "Peak", "enabled": True, "trigger_type": "daily", "fire_at": "16:00",
             "duration_min": 300, "match": "all",
             "conditions": [{"sensor": "battery.soc_pct", "op": ">", "value": 30},
                            {"match": "any", "conditions": [
                                {"sensor": "grid.connected", "op": "==", "value": 1}]}],
             "action": {"kind": "force", "direction": "discharge", "unit": "pct",
                        "power": 100, "target_soc": 20},
             "gateway_id": "",
             "ha_actions": [{"instance_id": "h", "entity_id": "switch.x",
                             "service": "turn_on", "when": "fire"}]}
    a = sch.to_automations(entry)
    assert a["action"] == "force_discharge" and a["params"]["power_pct"] == 100
    assert a["params"]["target_soc"] == 20 and a["duration_s"] == 18000
    assert a["trigger_kind"] == "daily" and a["trigger_spec"]["time_of_day"] == "16:00"
    assert a["entry_conditions"]["match"] == "ALL"
    assert a["entry_conditions"]["conditions"][1] == {
        "match": "ANY", "conditions": [{"sensor": "grid.connected", "op": "==", "value": 1}]}
    assert a["target_id"] == "default"

    back = sch.import_entries("franklinwh-automations", [a])[0]
    assert back["action"] == {"kind": "force", "direction": "discharge", "unit": "pct",
                              "power": 100, "target_soc": 20}
    assert back["fire_at"] == "16:00" and back["duration_min"] == 300
    assert back["conditions"][1] == {"match": "any",
                                     "conditions": [{"sensor": "grid.connected", "op": "==", "value": 1}]}
    assert back["ha_actions"][0]["entity_id"] == "switch.x"


# ── per-resource exclusivity (RUNTIME_DESIGN §6.6) ───────────────────────────
def test_a_notify_rule_claims_nothing():
    """The starvation bug: an entry commanding nothing must not hold the gateway."""
    assert sch.resource_for({"kind": "notify"}, "gw1") == ""
    assert sch.resource_for({}, "gw1") == ""
    assert sch.resource_for(None, "gw1") == ""


def test_force_and_mode_claim_the_same_battery():
    """A mode change during a force dispatch is one fight, not two rules passing."""
    a = sch.resource_for({"kind": "force"}, "gw1")
    b = sch.resource_for({"kind": "set_mode"}, "gw1")
    assert a == b == "gw1/battery"
    assert sch.resources_contend(a, b)


def test_offgrid_is_different_hardware_from_the_battery():
    assert not sch.resources_contend(
        sch.resource_for({"kind": "offgrid"}, "gw1"),
        sch.resource_for({"kind": "force"}, "gw1"))


def test_two_circuits_on_one_gateway_do_not_contend():
    assert not sch.resources_contend(
        sch.resource_for({"kind": "smart_circuit", "circuit": 1}, "gw1"),
        sch.resource_for({"kind": "smart_circuit", "circuit": 2}, "gw1"))


def test_an_unscoped_circuit_write_claims_every_circuit():
    """Cannot tell which one, so claim them all — the broader claim is the safe one."""
    wild = sch.resource_for({"kind": "smart_circuit"}, "gw1")
    assert wild == "gw1/circuit:*"
    assert sch.resources_contend(
        wild, sch.resource_for({"kind": "smart_circuit", "circuit": 3}, "gw1"))


def test_the_same_resource_on_two_gateways_is_two_resources():
    assert not sch.resources_contend(
        sch.resource_for({"kind": "force"}, "gw1"),
        sch.resource_for({"kind": "force"}, "gw2"))


def test_an_unknown_action_contends_with_itself_not_the_battery():
    """Guessing wide is what caused the starvation; a new kind blocks only its own."""
    novel = sch.resource_for({"kind": "future_thing"}, "gw1")
    assert novel == "gw1/other:future_thing"
    assert not sch.resources_contend(novel, sch.resource_for({"kind": "force"}, "gw1"))
    assert sch.resources_contend(novel, sch.resource_for({"kind": "future_thing"}, "gw1"))


# ── one-or-all gateway targeting (BR-45) ─────────────────────────────────────
def test_gateway_scope_travels_across_export_and_import():
    out = sch.portable({"name": "n", "gateway_scope": "all", "gateway_id": "gw1"})
    assert out["gateway_scope"] == "all"


def test_an_all_scope_rule_claims_each_gateway_separately():
    """One rule across a site is one rule, not N contending for one resource."""
    a = sch.resource_for({"kind": "force"}, "gw1")
    b = sch.resource_for({"kind": "force"}, "gw2")
    assert a != b and not sch.resources_contend(a, b)


# ── BR-50: capture before the override ───────────────────────────────────────
def test_capture_reads_the_mode_that_is_about_to_be_replaced():
    prior = sch.capture_prior({"kind": "set_mode", "mode": "Time-of-Use"},
                              {"mode.name": "Self-Consumption"})
    assert prior == {"kind": "set_mode", "key": "mode.name",
                     "value": "Self-Consumption"}


def test_nothing_is_captured_when_the_old_value_cannot_be_read():
    """A guessed restore looks deliberate and is worse than leaving the override."""
    assert sch.capture_prior({"kind": "set_mode"}, {"mode.name": None}) is None
    assert sch.capture_prior({"kind": "set_mode"}, {}) is None


def test_force_captures_nothing_because_it_releases_itself():
    assert sch.capture_prior({"kind": "force", "direction": "charge"},
                             {"mode.name": "Self-Consumption"}) is None


# ── templated notifications: the run, not just the sensors ───────────────────
def _ctx(**kw):
    import datetime as _dt
    entry = {"id": "s1", "name": "Overnight charge", "priority": 5,
             "action": {"kind": "force"}, "_wkey": "2026-10-09",
             "_occ_attempts": 3, "_resource": "gw1/battery", **kw}
    return sch.run_context(entry, gateway_id="gw1",
                           now=_dt.datetime(2026, 10, 9, 23, 30), phase="fire")


def test_a_message_can_name_the_run_that_sent_it():
    c = _ctx()
    assert c["schedule.name"] == "Overnight charge"
    assert c["run.attempt"] == 3 and c["run.occurrence"] == "2026-10-09"
    assert c["run.resource"] == "battery" and c["run.phase"] == "fire"


def test_run_variables_substitute_in_the_same_namespace_as_sensors():
    """One syntax, not two — a message mixes live values and run context freely."""
    snap = {"battery.soc_pct": 38, **_ctx()}
    assert sch.substitute(
        "%schedule.name% attempt %run.attempt%: SoC %battery.soc_pct%%", snap
    ) == "Overnight charge attempt 3: SoC 38%"


def test_an_unknown_variable_renders_as_a_question_mark_not_a_failure():
    assert sch.substitute("%run.nonsense%", _ctx()) == "?"
