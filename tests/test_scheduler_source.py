"""Scheduler: where each schedule came from (owner 2026-11-24).

A schedule is the user's or Smart Dispatch's (its ``origin`` tag). The Scheduler shows a badge
and filters the list and its log by source; each log row records the source when it is
written, so a run of a Smart Dispatch task stays told apart after the task is gone."""
import pathlib
import sqlite3

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, db
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
SPEC = {"gateway_id": "gw1", "fire_at": "06:00", "duration_min": 0, "action": {}}


def test_each_log_row_records_its_schedules_source(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    s.create_schedule(sid="sd", name="Smart Dispatch: Hold", spec={**SPEC, "origin": "smart_dispatch"})
    s.create_schedule(sid="me", name="Mine", spec=SPEC)
    s.log_schedule_event("sd", "Smart Dispatch: Hold", "fired", "ok")
    s.log_schedule_event("me", "Mine", "fired", "ok")
    s.log_schedule_event("_batt", "battery", "dispatch-start", "x")
    s.delete_schedule("sd")                                   # its rows keep their source
    rows = {r["schedule_id"]: r["source"] for r in s.schedule_log()}
    assert rows == {"sd": "smart_dispatch", "me": "user", "_batt": "user"}
    assert [r["schedule_id"] for r in s.schedule_log(source="smart_dispatch")] == ["sd"]
    assert {r["schedule_id"] for r in s.schedule_log(source="user")} == {"me", "_batt"}
    s.close()


def test_rows_from_before_are_backfilled(tmp_path):
    path = str(tmp_path / "m.db")
    s = MetricsStore(path)
    s.create_schedule(sid="sd", name="Smart Dispatch: Hold", spec={**SPEC, "origin": "smart_dispatch"})
    s.close()
    c = sqlite3.connect(path)                                # a log from before the column
    c.execute("ALTER TABLE schedule_log DROP COLUMN source")
    c.executemany("INSERT INTO schedule_log(ts, schedule_id, name, status, result) VALUES (?,?,?,?,?)",
                  [(1.0, "sd", "Smart Dispatch: Hold", "fired", "ok"),
                   (2.0, "gone", "Smart Dispatch: Charge", "deleted", "replaced by Smart Dispatch"),
                   (3.0, "me", "Mine", "fired", "ok")])
    c.commit(); c.close()
    s = MetricsStore(path)
    assert {r["schedule_id"]: r["source"] for r in s.schedule_log()} == {
        "sd": "smart_dispatch", "gone": "smart_dispatch", "me": "user"}
    s.close()


def test_the_log_api_filters_by_source(tmp_path, monkeypatch):
    s = MetricsStore(str(tmp_path / "m.db"))
    s.create_schedule(sid="sd", name="SD", spec={**SPEC, "origin": "smart_dispatch"})
    s.log_schedule_event("sd", "SD", "fired", "ok")
    s.log_schedule_event("me", "Mine", "fired", "ok")
    monkeypatch.setattr(db, "get_store", lambda *a, **k: s)
    c = TestClient(app_module.create_app())
    got = c.get("/api/schedules/log", params={"source": "smart_dispatch"}).json()["events"]
    assert [e["schedule_id"] for e in got] == ["sd"]
    assert c.get("/api/schedules/log", params={"source": "nope"}).status_code == 422
    s.close()


def test_the_scheduler_shows_the_badge_and_the_source_filters():
    html = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
    for tid in ("sched-source-filter", "sched-source-badge", "sched-log-source"):
        assert f'data-testid="{tid}"' in html, tid
    js = (PKG / "static" / "js" / "scheduler_tab.js").read_text()
    assert "sourceFilter" in js and "logSource" in js
