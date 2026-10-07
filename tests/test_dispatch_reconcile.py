"""Boot reconcile of interrupted scheduled dispatches — the safety-critical policy
logic. Modbus is monkeypatched so nothing touches real hardware; a fake store records
the DB transitions."""
import time
import pytest
from franklinwh_direct_connect_bridge import battery_control as bc


class FakeStore:
    def __init__(self, rows):
        self._rows = rows
        self.ended = []            # (id, status)
        self.recorded = []         # kwargs of new active rows
        self.logs = []             # (sid, name, status, detail)
    def active_dispatches(self, *, host=None):
        return list(self._rows)
    def end_dispatch(self, did, *, status="ended", now=None):
        self.ended.append((did, status))
    def end_active_dispatches(self, *, host=None, status="ended", now=None):
        return 0
    def record_dispatch(self, **kw):
        self.recorded.append(kw); return 999
    def log_schedule_event(self, sid, name, status, detail, now=None):
        self.logs.append((sid, name, status, detail))


@pytest.fixture
def modbus(monkeypatch):
    """Record execute()/_arm_watchdog() calls; status() is controllable per-test."""
    calls = {"execute": [], "arm": [], "status": {"available": True, "vpp_active": True}}
    monkeypatch.setattr(bc, "status", lambda host: dict(calls["status"]))
    def _exec(cmd, **kw):
        calls["execute"].append((cmd, kw)); return {"ok": True, "result": "ok"}
    monkeypatch.setattr(bc, "execute", _exec)
    monkeypatch.setattr(bc, "_arm_watchdog", lambda *a, **k: calls["arm"].append((a, k)))
    monkeypatch.setattr(bc, "current", lambda: {"active": "Force Discharge"})
    return calls


def _row(**over):
    base = dict(id=1, schedule_id="s1", name="Peak discharge", gateway_id="", host="h",
                direction="discharge", watts=-2000, power_mode="w", target_soc=20,
                window_start_ts=time.time() - 3600,
                window_end_ts=time.time() + 1800)   # 30 min left by default
    base.update(over); return base


def test_no_active_rows_is_a_noop(modbus):
    st = FakeStore([])
    out = bc.reconcile_interrupted(st, "h", "resume")
    assert out == [] and not modbus["execute"] and not modbus["arm"]


def test_notify_never_touches_battery(modbus):
    st = FakeStore([_row()])
    notes = []
    out = bc.reconcile_interrupted(st, "h", "notify", notify=lambda t, m: notes.append((t, m)))
    assert not modbus["execute"] and not modbus["arm"]        # battery untouched
    assert st.ended == [(1, "interrupted")]
    assert notes and "interrupted" in notes[0][1]
    assert out[0]["action"] == "notified"


def test_none_is_silent(modbus):
    st = FakeStore([_row()])
    notes = []
    bc.reconcile_interrupted(st, "h", "none", notify=lambda t, m: notes.append(1))
    assert not modbus["execute"] and not modbus["arm"] and not notes
    assert st.ended == [(1, "interrupted")]


def test_release_when_window_ended_and_forced_releases(modbus):
    modbus["status"] = {"available": True, "vpp_active": True}
    st = FakeStore([_row(window_end_ts=time.time() - 60)])   # window already ended
    bc.reconcile_interrupted(st, "h", "release")
    assert modbus["execute"] and modbus["execute"][0][0] == "Release"
    assert (1, "released") in st.ended


def test_release_inside_window_rearms_without_reforcing(modbus):
    modbus["status"] = {"available": True, "vpp_active": True}
    st = FakeStore([_row(window_end_ts=time.time() + 600)])  # 10 min left
    bc.reconcile_interrupted(st, "h", "release")
    assert modbus["arm"] and not modbus["execute"]           # re-armed, no re-force
    assert st.recorded and st.recorded[0]["window_end_ts"] > time.time()


def test_resume_reforces_when_battery_dropped_inside_window(modbus):
    modbus["status"] = {"available": True, "vpp_active": False}   # not forced anymore
    st = FakeStore([_row(direction="discharge", watts=-3000, window_end_ts=time.time() + 900)])
    bc.reconcile_interrupted(st, "h", "resume")
    assert modbus["execute"] and modbus["execute"][0][0] == "Force Discharge"
    assert (1, "resumed") in st.ended


def test_release_does_not_reforce_when_battery_dropped(modbus):
    modbus["status"] = {"available": True, "vpp_active": False}   # not forced
    st = FakeStore([_row(window_end_ts=time.time() + 900)])
    bc.reconcile_interrupted(st, "h", "release")
    assert not modbus["execute"] and not modbus["arm"]           # release never re-forces
    assert (1, "interrupted") in st.ended


# ── widget-initiated dispatches are persisted too (covered by the reconcile) ──
def test_widget_force_is_persisted_and_release_closes_it(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module, config, environment, db
    from franklinwh_direct_connect_bridge.db import MetricsStore
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: store)
    config.save_override("allow_writes", True)
    monkeypatch.setenv("FWH_MODBUS_HOST", "testhost")
    # No real Modbus: execute() reports success + the active command.
    monkeypatch.setattr(bc, "execute",
                        lambda cmd, **kw: {"ok": True, "result": "ok",
                                           "active": cmd if cmd not in ("Release", "Not Active") else "Not Active"})
    monkeypatch.setattr(bc, "current", lambda: {"active": "Not Active"})

    client = TestClient(app_module.create_app())

    client.post("/api/battery/command", json={"slug": "battery_command_power", "value": "2500"})
    client.post("/api/battery/command", json={"slug": "battery_command_duration", "value": "600"})
    client.post("/api/battery/command", json={"slug": "battery_command_target_soc", "value": "30"})
    r = client.post("/api/battery/command", json={"slug": "battery_command", "value": "Force Discharge"})
    assert r.status_code == 200 and r.json().get("ok")

    rows = store.active_dispatches(host="testhost")
    assert len(rows) == 1
    d = rows[0]
    assert d["schedule_id"] == "_widget" and d["direction"] == "discharge"
    assert d["watts"] == -2500 and d["power_mode"] == "w" and d["target_soc"] == 30
    assert d["window_end_ts"] and d["window_end_ts"] > d["window_start_ts"]

    client.post("/api/battery/command", json={"slug": "battery_command", "value": "Release"})
    assert store.active_dispatches(host="testhost") == []
    config._settings = None
