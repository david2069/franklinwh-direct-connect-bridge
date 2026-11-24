"""Smart Dispatch phase 2, step 3: Auto (owner 2026-11-24, #612).

Auto is Off, Shadow or On per gateway. About hourly the scheduler worker works the plan out
again: Shadow only logs what Create schedules would do; On does it. On is refused until Shadow
has run for a week. Identical tasks are kept, so an unchanged plan doesn't churn the
Scheduler, and the user's schedules are never touched."""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, battery_control, db,
                                              scheduler_worker, security, smart_dispatch)

from test_smart_dispatch_p1 import NOW, seed_load, st, tariff  # noqa: F401  (fixture)

WEEK = 7 * 86400


@pytest.fixture
def planned(st, monkeypatch):  # noqa: F811
    tariff(st)
    seed_load(st)
    monkeypatch.setattr(battery_control, "available", lambda: (True, ""))
    def boom(*a, **k):
        raise AssertionError("Auto must not write to the gateway itself")
    monkeypatch.setattr(battery_control, "execute", boom)
    smart_dispatch.save(st, "gw1", {"objective": "lowest_cost", "grid_charge": "allowed"})
    smart_dispatch._last_auto.clear()
    return st


def ours(st):
    return [e for e in st.schedules() if e.get("origin") == smart_dispatch.ORIGIN]


def test_auto_is_off_by_default_and_does_nothing(planned):
    assert smart_dispatch.auto(planned, "gw1")["mode"] == "off"
    assert smart_dispatch.auto_tick(planned, None, "gw1", NOW) is None
    assert ours(planned) == [] and smart_dispatch.auto(planned, "gw1")["log"] == []


def test_shadow_logs_what_it_would_create_hourly_and_creates_nothing(planned):
    smart_dispatch.set_auto(planned, "gw1", "shadow", NOW)
    e = smart_dispatch.auto_tick(planned, None, "gw1", NOW)
    assert e["mode"] == "shadow" and e["create"] and ours(planned) == []
    assert smart_dispatch.auto_tick(planned, None, "gw1", NOW + 600) is None     # not yet
    assert smart_dispatch.auto_tick(planned, None, "gw1", NOW + 3600)
    log = smart_dispatch.auto(planned, "gw1")["log"]
    assert len(log) == 2 and log[0]["ts"] == NOW + 3600                         # newest first


def test_on_needs_a_week_of_shadow(planned):
    with pytest.raises(ValueError, match="Shadow"):
        smart_dispatch.set_auto(planned, "gw1", "on", NOW)
    smart_dispatch.set_auto(planned, "gw1", "shadow", NOW)
    with pytest.raises(ValueError, match="7 day"):
        smart_dispatch.set_auto(planned, "gw1", "on", NOW + WEEK - 3600)
    assert smart_dispatch.set_auto(planned, "gw1", "on", NOW + WEEK)["mode"] == "on"
    # Off and back on keeps the week already done.
    smart_dispatch.set_auto(planned, "gw1", "off", NOW + WEEK)
    assert smart_dispatch.set_auto(planned, "gw1", "on", NOW + WEEK)["mode"] == "on"
    with pytest.raises(ValueError):
        smart_dispatch.set_auto(planned, "gw1", "sometimes", NOW)


def _on(st):
    smart_dispatch.set_auto(st, "gw1", "shadow", NOW - WEEK)
    smart_dispatch.set_auto(st, "gw1", "on", NOW)


def test_on_creates_the_tasks_and_an_unchanged_plan_keeps_them(planned):
    planned.create_schedule(sid="u1", name="Mine", enabled=True, spec={
        "gateway_id": "gw1", "fire_at": "06:00", "duration_min": 0,
        "action": {"kind": "smart_circuit", "circuit": 1, "on": True}})
    _on(planned)
    e = smart_dispatch.auto_tick(planned, None, "gw1", NOW)
    assert e["mode"] == "on" and e["create"]
    ids = {x["id"] for x in ours(planned)}
    assert ids
    smart_dispatch._cache.clear()
    e = smart_dispatch.auto_tick(planned, None, "gw1", NOW + 3600)
    assert e["create"] == [] and e["replace"] == []
    assert {x["id"] for x in ours(planned)} <= ids and planned.schedule("u1")


def test_on_without_force_logs_why_and_creates_nothing(planned, monkeypatch):
    _on(planned)
    monkeypatch.setattr(battery_control, "available", lambda: (False, "Modbus client is off"))
    e = smart_dispatch.auto_tick(planned, None, "gw1", NOW)
    assert "Modbus client is off" in e["error"] and ours(planned) == []


def test_the_worker_runs_it_for_each_fresh_gateway(planned, monkeypatch):
    seen = []
    monkeypatch.setattr(scheduler_worker, "get_store", lambda *a, **k: planned)
    monkeypatch.setattr(scheduler_worker, "eligible", lambda gw, s, now=None: (True, ""))
    monkeypatch.setattr(smart_dispatch, "auto_tick",
                        lambda store, settings, gid, now=None: seen.append(gid))
    scheduler_worker.smart_dispatch_tick(None)
    assert seen == ["gw1"]


def test_the_api_and_the_card(planned, monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda *a, **k: planned)
    c = TestClient(app_module.create_app())
    q = {"gateway": "gw1"}
    assert c.put("/api/schedules/smart-dispatch/auto", params=q, json={"mode": "on"}).status_code == 409
    assert c.put("/api/schedules/smart-dispatch/auto", params=q, json={"mode": "x"}).status_code == 422
    r = c.put("/api/schedules/smart-dispatch/auto", params=q, json={"mode": "shadow"})
    assert r.status_code == 200 and r.json()["auto"]["mode"] == "shadow"
    assert c.get("/api/smart-dispatch", params=q).json()["auto"]["mode"] == "shadow"
    assert security.required("PUT", "/api/schedules/smart-dispatch/auto") == ("admin", "user")
    import pathlib
    pkg = pathlib.Path(smart_dispatch.__file__).parent
    html = (pkg / "templates" / "tabs" / "smart_dispatch.html").read_text()
    for tid in ("sd-auto", "sd-auto-log"):
        assert f'data-testid="{tid}"' in html, tid
