"""Scheduler timeline: a lane per gateway (#579, as the Modbus Bridge). Each lane has its
own planned windows, mode band, SoC line and fire markers; All gateways rules sit on a
Site row; interval, cron and always rules are drawn; segment keys are unique."""
import datetime as dt
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import (app as app_module, client as client_module, config,
                                              db, scheduler as sch, state)

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
NOW = dt.datetime(2026, 11, 13, 9, 0)


def _e(sid, **kw):
    return {"id": sid, "name": f"Rule {sid}", "enabled": True, "fire_at": "18:00",
            "duration_min": 60, "action": {"kind": "set_mode"}, **kw}


def test_a_gateways_lane_has_its_own_rules_and_the_site_row_the_all_gateways_ones():
    entries = [_e("a", gateway_id="g1"), _e("b", gateway_id="g2"),
               _e("c", gateway_id="g1", gateway_scope="all", action={})]
    tl = sch.timeline_segments(entries, NOW, gateway_id="g1")
    assert [s["schedule_id"] for s in tl["segments"]] == ["a"]
    assert [s["schedule_id"] for s in tl["site"]] == ["c"]


def test_keys_are_unique_per_window():
    tl = sch.timeline_segments([_e("w", trigger_type="window", windows=[
        {"start": "06:00", "end": "07:00"}, {"start": "18:00", "end": "19:00"}])], NOW)
    assert [s["key"] for s in tl["segments"]] == ["w#0", "w#1"]


def test_interval_cron_and_always_are_drawn():
    tl = sch.timeline_segments([
        _e("i", trigger_type="interval", interval_min=120, duration_min=30, anchor="00:00"),
        _e("k", trigger_type="cron", cron="0 6,18 * * *", duration_min=60),
        _e("x", trigger_type="always", duration_min=0)], NOW)
    by = {s["schedule_id"]: s for s in tl["segments"]}
    assert len(by["i"]["blocks"]) == 12 and by["i"]["blocks"][1] == [120, 150]
    if sch.cron_available():
        assert by["k"]["blocks"] == [[360, 420], [1080, 1140]]
    assert by["x"]["blocks"] == [[0, 1440]] and by["x"]["conditional"] is True


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "House")
    state.register_gateway("g2", "192.0.2.11", "Garage")
    yield TestClient(app_module.create_app())
    state.reset_gateways()


def test_the_api_gives_a_lane_per_gateway_with_its_own_fires(c):
    st = db.get_store(config.get_settings())
    for sid, gw in (("a", "g1"), ("b", "g2")):
        st.create_schedule(sid=sid, name=f"Rule {sid}", spec={
            "gateway_id": gw, "fire_at": "00:00", "duration_min": 1439, "action": {}})
        st.log_schedule_event(sid, f"Rule {sid}", "fired", "ok", gateway_id=gw)
    st.create_schedule(sid="s", name="Everywhere", spec={
        "gateway_id": "g1", "gateway_scope": "all", "fire_at": "00:00", "duration_min": 1439,
        "action": {}})
    one = c.get("/api/schedules/timeline?gateway=g1").json()
    assert [l["gateway_id"] for l in one["lanes"]] == ["g1"]
    lane = one["lanes"][0]
    assert lane["name"] == "House"
    assert [s["schedule_id"] for s in lane["segments"]] == ["a"]
    assert {f["name"] for f in lane["fires"]} == {"Rule a"}
    assert [s["schedule_id"] for s in one["site"]] == ["s"]
    both = c.get("/api/schedules/timeline?all=true").json()
    assert [l["gateway_id"] for l in both["lanes"]] == ["g1", "g2"]
    assert {f["name"] for f in both["lanes"][1]["fires"]} == {"Rule b"}


def test_the_tab_draws_lanes_with_a_gateway_picker():
    html = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
    js = (PKG / "static" / "js" / "scheduler_tab.js").read_text()
    assert 'data-testid="timeline-gateway"' in html
    assert re.search(r'x-for="lane in timeline\.lanes"\s+:key="lane\.gateway_id"', html)
    assert ':key="seg.key"' in html and ':key="seg.schedule_id"' not in html
    assert 'data-testid="timeline-site"' in html
    assert "all=true" in js
