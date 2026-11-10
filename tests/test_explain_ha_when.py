"""#335 / #336: the scheduler's Explain says when an HA action runs, and remembers its level.

An HA action runs at entry (`fire`), at exit, or both. Explain listed every one under DO, so
an On-exit notification read as if it ran when the schedule fired. The wording follows the
Modbus Bridge ("… when it ends") so the two schedulers read the same. The Min / Medium /
Full level is remembered per browser.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = (ROOT / "static/js/scheduler_tab.js").read_text()
HTML = (ROOT / "templates/tabs/scheduler.html").read_text()

# Loads scheduler_tab.js with a stub Alpine and an in-memory localStorage, then runs the
# component's own explain(). Shared by the node test and a browser run of the same script.
SCRIPT = """
var __factory = null, __mem = {};
var Alpine = {data: function (n, f) { if (n === 'schedulerTab') __factory = f; }};
var document = {addEventListener: function (ev, fn) { if (ev === 'alpine:init') fn(); }};
var localStorage = {getItem: function (k) { return k in __mem ? __mem[k] : null; },
                    setItem: function (k, v) { __mem[k] = String(v); }};
""" + JS + """
var c = __factory();
c.haNames = {'light.porch': 'Porch light'};
var s = {trigger_type: 'daily', fire_at: '16:00', days: [], conditions: [], exit_conditions: [],
         action: {kind: ''}, ha_actions: [
           {ha_kind: 'notify', when: 'fire'},
           {ha_kind: 'notify', when: 'exit'},
           {ha_kind: 'service', entity_id: 'light.porch', service: 'turn_on', when: 'both'}]};
var first = c.explainLevel;
c.setExplainLevel('full');
var __out = {first: first, min: c.explain(s, 'min'), again: __factory().explainLevel};
"""


def _check(out):
    assert out["first"] == "medium"
    m = out["min"]
    assert "notify a companion device, then notify a companion device when it ends" in m
    assert "turn on “Porch light” when it starts and when it ends" in m
    assert out["again"] == "full"                       # remembered per browser


def test_static_wiring():
    assert '@click="setExplainLevel(lv)"' in HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_explain_phrases_and_remembered_level():
    out = json.loads(subprocess.run(
        ["node", "-e", SCRIPT + "console.log(JSON.stringify(__out));"],
        capture_output=True, text=True, check=True).stdout)
    _check(out)
