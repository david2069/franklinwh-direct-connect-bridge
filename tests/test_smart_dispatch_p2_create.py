"""Smart Dispatch phase 2, step 2: Create schedules (owner 2026-11-24, #612).

The drafts are added to the Scheduler as one-off tasks tagged Smart Dispatch, only while
writes are allowed. Creating again replaces its own tasks that haven't started; it never
touches the user's schedules, skips a draft that clashes with one, and leaves its own running
task be. Nothing is written to the gateway here: the Scheduler runs the tasks."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, battery_control, client, db,
                                              scheduler, security, smart_dispatch)

from test_smart_dispatch_p1 import NOW, seed_load, st, tariff  # noqa: F401  (fixture)


@pytest.fixture
def planned(st, monkeypatch):  # noqa: F811
    tariff(st)
    seed_load(st)
    monkeypatch.setattr(battery_control, "available", lambda: (True, ""))
    def boom(*a, **k):
        raise AssertionError("creating schedules must not write to the gateway")
    monkeypatch.setattr(battery_control, "execute", boom)
    smart_dispatch.save(st, "gw1", {"objective": "lowest_cost", "grid_charge": "allowed"})
    return st


def ours(st):
    return [e for e in st.schedules() if e.get("origin") == smart_dispatch.ORIGIN]


def test_create_adds_the_drafts_as_tagged_tasks(planned):
    drafts = smart_dispatch.view(planned, None, "gw1", NOW)["drafts"]["tasks"]
    out = smart_dispatch.create(planned, None, "gw1", NOW)
    mine = ours(planned)
    assert len(out["created"]) == len(mine) == len([t for t in drafts if t["end"] > NOW]) > 0
    for e in mine:
        assert e["enabled"] and e["gateway_id"] == "gw1" and e["trigger_type"] == "once"
        assert e["name"].startswith("Smart Dispatch: ")
        assert scheduler.validate_spec(e) == []
        # Shaped as the Scheduler saves one: its card reads these lists.
        assert e["conditions"] == [] and e["exit_conditions"] == [] and e["ha_actions"] == []
    assert any(l["status"] == "created" for l in planned.schedule_log(limit=50))


def test_creating_again_keeps_identical_tasks_and_replaces_changed_ones_only(planned):
    planned.create_schedule(sid="u1", name="My evening", enabled=True, spec={
        "gateway_id": "gw1", "fire_at": "06:00", "duration_min": 0,
        "action": {"kind": "smart_circuit", "circuit": 1, "on": True}})
    smart_dispatch.create(planned, None, "gw1", NOW)
    first = {e["id"]: e for e in ours(planned)}
    out = smart_dispatch.create(planned, None, "gw1", NOW)          # same plan: no churn
    assert set(first) == {e["id"] for e in ours(planned)}
    assert out["created"] == [] and out["replaced"] == [] and out["kept"] == len(first)
    # A future task that no longer matches the plan is replaced.
    tz = smart_dispatch._site_zone(planned)
    sid, e = next((i, e) for i, e in first.items() if smart_dispatch._window(e, tz)[0] > NOW)
    spec = {k: e[k] for k in ("trigger_type", "start_date", "end_date", "fire_at", "gateway_id",
                              "action", "origin")}
    planned.update_schedule(sid, spec={**spec, "duration_min": e["duration_min"] + 30})
    out = smart_dispatch.create(planned, None, "gw1", NOW)
    assert out["replaced"] == [e["name"]] and out["created"] == [e["name"]]
    assert planned.schedule(sid) is None and planned.schedule("u1") is not None


def _running(st):
    tz = smart_dispatch._site_zone(st)
    return {e["id"] for e in ours(st) if smart_dispatch._window(e, tz)[0] <= NOW}


def test_a_draft_that_clashes_with_a_users_schedule_is_skipped(planned):
    tasks = smart_dispatch.view(planned, None, "gw1", NOW)["drafts"]["tasks"]
    t = tasks[0]
    planned.create_schedule(sid="u2", name="My mode", enabled=True, spec={
        "gateway_id": "gw1", "trigger_type": "once", "start_date": t["spec"]["start_date"],
        "end_date": t["spec"]["start_date"], "fire_at": t["spec"]["fire_at"],
        "duration_min": t["spec"]["duration_min"], "action": {"kind": "set_mode", "mode": "self"}})
    smart_dispatch._cache.clear()
    out = smart_dispatch.create(planned, None, "gw1", NOW)
    assert [s["name"] for s in out["skipped"]] == [t["name"]]
    assert "My mode" in out["skipped"][0]["why"]
    assert t["name"] not in [e["name"] for e in ours(planned)]


def test_its_own_tasks_are_not_clashes(planned):
    smart_dispatch.create(planned, None, "gw1", NOW)
    smart_dispatch._cache.clear()
    v = smart_dispatch.view(planned, None, "gw1", NOW)
    assert all(not t["clashes"] for t in v["drafts"]["tasks"])
    assert v["drafts"]["in_scheduler"] == len(ours(planned))


def test_without_force_nothing_is_created(planned, monkeypatch):
    monkeypatch.setattr(battery_control, "available", lambda: (False, "Modbus client is off"))
    with pytest.raises(ValueError, match="Modbus client is off"):
        smart_dispatch.create(planned, None, "gw1", NOW)
    assert ours(planned) == []


def test_without_a_plan_nothing_is_created(st):  # noqa: F811
    with pytest.raises(ValueError):
        smart_dispatch.create(st, None, "gw1", NOW)


def test_the_api_needs_writes_and_is_a_schedules_action(planned, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda *a, **k: planned)
    c = TestClient(app_module.create_app())
    q = {"gateway": "gw1"}
    monkeypatch.setattr(client, "writes_enabled", lambda *a, **k: False)
    assert c.post("/api/schedules/smart-dispatch", params=q).status_code == 403
    assert ours(planned) == []
    monkeypatch.setattr(client, "writes_enabled", lambda *a, **k: True)
    r = c.post("/api/schedules/smart-dispatch", params=q)
    assert r.status_code == 200 and r.json()["created"]
    assert security.required("POST", "/api/schedules/smart-dispatch") == ("admin", "user")
    monkeypatch.setattr(battery_control, "available", lambda: (False, "off"))
    assert c.post("/api/schedules/smart-dispatch", params=q).status_code == 409


def test_the_card_has_the_create_button():
    import pathlib
    pkg = pathlib.Path(smart_dispatch.__file__).parent
    html = (pkg / "templates" / "tabs" / "smart_dispatch.html").read_text()
    assert 'data-testid="sd-create"' in html
    js = (pkg / "static" / "js" / "smart_dispatch_tab.js").read_text()
    assert "api/schedules/smart-dispatch" in js
