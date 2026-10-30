"""A failed Release keeps the force visible (#366); shutdown waits for a running tick
before releasing (#367)."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import battery_control as bc
from franklinwh_direct_connect_bridge import db, scheduler_worker
from franklinwh_direct_connect_bridge.db import MetricsStore

FORCE = {"kind": "force", "direction": "discharge", "unit": "pct", "power": 50}


@pytest.fixture
def st(tmp_path, monkeypatch):
    s = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db, "get_store", lambda _s: s)
    s.create_schedule(sid="b", name="on b", spec={"gateway_id": "gw-b", "fire_at": "14:00",
                                                 "duration_min": 60, "action": dict(FORCE)})
    s.record_dispatch(schedule_id="b", name="on b", gateway_id="gw-b", host="10.0.0.2",
                      direction="discharge", watts=-50, power_mode="pct", target_soc=0,
                      window_start_ts=1, window_end_ts=None)
    return s


@pytest.fixture
def release_fails(monkeypatch):
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: {
        "ok": False, "result": "aGate unreachable", "active": None})


def _mine(st):
    return [d for d in st.active_dispatches() if d.get("schedule_id") == "b"]


# ── #366 ─────────────────────────────────────────────────────────────────────

def test_a_failed_stop_keeps_the_dispatch_row_active(st, release_fails):
    out = TestClient(app_module.create_app()).post("/api/schedules/b/stop").json()
    assert out["stopped"] is False and out["failed"] is True
    assert "aGate unreachable" in out["result"]
    assert len(_mine(st)) == 1, "the force may still be running; reconcile must see it"


def test_a_failed_pause_keeps_the_run_and_the_row(st, release_fails):
    now = time.time()
    occ = st.claim_occurrence(schedule_id="b", name="on b", gateway_id="gw-b",
                              occurrence_key="k", due_ts=now - 60, window_end_ts=now + 3600,
                              now=now - 60)
    out = TestClient(app_module.create_app()).post("/api/schedules/b/pause").json()
    assert out["paused"] is False and "aGate unreachable" in out["detail"]
    assert len(_mine(st)) == 1
    assert [o["id"] for o in st.due_occurrences()] == [occ["id"]], "not paused"


def test_a_successful_stop_still_ends_the_row(st, monkeypatch):
    monkeypatch.setattr(bc, "execute", lambda cmd, **kw: {"ok": True, "result": "ok"})
    out = TestClient(app_module.create_app()).post("/api/schedules/b/stop").json()
    assert out["stopped"] is True and _mine(st) == []


# ── #367 ─────────────────────────────────────────────────────────────────────

def test_shutdown_releases_after_the_running_tick_finishes(monkeypatch):
    order = []

    async def slow_worker(settings, stop, *, client):
        await stop.wait()
        await asyncio.sleep(0.3)          # a tick still in its thread when stop is set
        order.append("tick finished")

    monkeypatch.setattr(scheduler_worker, "run", slow_worker)
    monkeypatch.setattr(bc, "release_held", lambda reason: order.append("release"))
    with TestClient(app_module.create_app()):
        pass
    assert order == ["tick finished", "release"]
