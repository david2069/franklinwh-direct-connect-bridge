"""All gateways for rules that move no battery (#578): the gateway picker offers it when the
rule has no battery action, the list and Explain say so, and the engine already runs such a
rule on each gateway with its own values (BR-45)."""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client as client_module, state

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
JS = (PKG / "static" / "js" / "scheduler_tab.js").read_text()


def test_picker_offers_all_gateways_only_without_a_battery_action():
    sel = re.search(r'<select[^>]*data-testid="gateway-pick".*?</select>', HTML, re.S)
    assert sel, "the gateway picker has a test id"
    sel = sel.group(0)
    assert 'x-model="gwPick"' in sel
    opt = re.search(r'<option value="\*"[^>]*>All gateways</option>', sel)
    assert opt and "!form.action.kind" in opt.group(0)


def test_form_carries_the_scope():
    assert "gateway_scope: 'one'" in JS                       # a new rule: one gateway
    assert "gateway_scope: s.gateway_scope || 'one'" in JS    # an edit keeps what it has
    assert re.search(r"get gwPick\(\)", JS) and re.search(r"set gwPick\(v\)", JS)


def test_choosing_a_battery_action_goes_back_to_one_gateway():
    body = re.search(r"onActionKind\(\) \{(.*?)\n    \},", JS, re.S).group(1)
    assert "gateway_scope = 'one'" in body


def test_list_and_explain_say_all_gateways():
    assert "gatewayLabel(s)" in HTML
    assert re.search(r"gatewayLabel\(s\) \{.*?'All gateways'", JS, re.S)
    assert "ON     ${this.gatewayLabel(s)}" in JS


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "First")
    state.register_gateway("g2", "192.0.2.11", "Second")
    yield TestClient(app_module.create_app())
    state.reset_gateways()


RULE = {"name": "Low SoC", "fire_at": "00:00", "duration_min": 0, "trigger_type": "always",
        "conditions": [{"sensor": "battery.soc_pct", "op": "<", "value": 20}],
        "gateway_id": "g1", "action": {"kind": ""}, "ha_actions": []}


def test_an_all_gateways_rule_saves_and_goes_back_to_one(c):
    r = c.post("/api/schedules", json={**RULE, "gateway_scope": "all"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert c.get("/api/schedules").json()  # listed
    row = next(s for s in c.get("/api/schedules").json()["schedules"] if s["id"] == sid)
    assert row["gateway_scope"] == "all"
    r = c.put(f"/api/schedules/{sid}", json={**RULE, "gateway_scope": "one", "gateway_id": "g2"})
    assert r.status_code == 200, r.text
    row = next(s for s in c.get("/api/schedules").json()["schedules"] if s["id"] == sid)
    assert row["gateway_scope"] == "one" and row["gateway_id"] == "g2"
