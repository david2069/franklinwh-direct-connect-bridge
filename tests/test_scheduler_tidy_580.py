"""Scheduler review, minor findings (#580): editor labels and what is shown when, hidden
trigger fields cleared, the editor's Test on the schedule's gateway, restore_on_exit in
the form, one snapshot builder for Test / Evaluate / Run now, and the automations export
defaulting to override and saying what it drops."""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client as client_module
from franklinwh_direct_connect_bridge import scheduler as sch, state

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
JS = (PKG / "static" / "js" / "scheduler_tab.js").read_text()


def test_the_action_box_is_the_gateway_action():
    assert ">Gateway action <a" in HTML and ">Battery action <a" not in HTML
    assert "No gateway action (HA only)" in HTML and "No battery action (HA only)" not in HTML


def test_priority_and_if_busy_only_where_they_act():
    pri = re.search(r'<label[^>]*title="Higher priority wins[^"]*"', HTML).group(0)
    busy = re.search(r'<label[^>]*title="If the battery is already[^"]*"', HTML).group(0)
    assert 'x-show="form.action.kind"' in pri
    assert "x-show=\"form.action.kind === 'force'\"" in busy


def test_hidden_trigger_fields_are_cleared():
    body = re.search(r"_clearHidden\(\) \{(.*?)\n    \},", JS, re.S).group(1)
    for f in ("days", "months", "day_of_month", "windows", "start_date", "end_date"):
        assert f in body, f
    assert re.search(r"onTriggerType\(\) \{[^}]*this\._clearHidden\(\)", JS, re.S)
    assert re.search(r"async save\(\) \{.*?this\._clearHidden\(\)", JS, re.S)


def test_a_one_off_has_no_time_windows():
    assert "get showWindows() { return this.form.trigger_type === 'window'; }" in JS


def test_the_editors_test_reads_the_schedules_gateway():
    assert "_formGwQuery()" in JS
    for m in re.finditer(r"fetch\('api/schedules/evaluate' \+ ([^,]+),", JS):
        assert "_formGwQuery()" in m.group(1), m.group(0)
    assert "api/schedules/${s.id}/test` + this.$store.app.gwQuery()" not in JS


def test_restore_on_exit_is_in_the_form():
    assert 'data-testid="restore-on-exit"' in HTML and 'x-model="form.restore_on_exit"' in HTML
    assert "restore_on_exit: false" in JS and "restore_on_exit: !!s.restore_on_exit" in JS


def test_repeat_pattern_not_quick_preset():
    assert "Repeat pattern" in HTML and "Quick preset" not in HTML


def test_no_banner_for_a_kind_the_form_never_offered():
    assert "Not available here" not in HTML


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "House")
    yield TestClient(app_module.create_app())
    state.reset_gateways()


def test_one_snapshot_builder_for_test_evaluate_and_run(c, monkeypatch):
    calls = []
    monkeypatch.setattr(sch, "build_snapshot", lambda *a, **k: calls.append(k.get("tick")) or {})
    sid = c.post("/api/schedules", json={"name": "n", "fire_at": "00:00", "duration_min": 0,
                                         "gateway_id": "g1", "action": {}}).json()["id"]
    c.post(f"/api/schedules/{sid}/test")
    c.post("/api/schedules/evaluate?gateway=g1", json={"match": "all", "conditions": []})
    c.post(f"/api/schedules/{sid}/run")
    assert calls == [False, False, False]


def test_the_automations_export_defaults_to_override_and_warns():
    e = {"name": "n", "trigger_type": "monthly", "months": [1], "day_of_month": 1,
         "gateway_scope": "all", "restore_on_exit": True, "start_date": "2026-01-01",
         "ha_actions": [{"actionable": True, "message": "q"}], "action": {}}
    assert sch.to_automations(e)["conflict"] == "override"
    w = " ".join(sch.automations_export_warnings(e))
    for word in ("months", "day of month", "All gateways", "restore", "dates",
                 "actionable"):
        assert word in w, word


def test_the_export_api_returns_the_warnings(c):
    c.post("/api/schedules", json={"name": "n", "fire_at": "00:00", "duration_min": 0,
                                   "gateway_id": "g1", "restore_on_exit": True, "action": {}})
    out = c.get("/api/schedules/export?fmt=automations").json()
    assert out["warnings"] and "restore" in out["warnings"][0]
