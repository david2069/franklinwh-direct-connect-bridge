"""#313: the dashboard's Run status shows the state that matters, not only 1301.

Owner, 2026-10-24: with the aGate in Debug Mode the card read "Run status: Standby". 1301
`run_status` reads 0 in Debug Mode and keeps the battery direction during VPP, so the
card now shows the highest-priority state present: Debug Mode, then Off-grid, then VPP
(1707 programme id 9), then Reconnecting (the all-zero start-up frame, #309), then the
1301 text. A tooltip names the source.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = (ROOT / "static/js/app.js").read_text()
DASH = (ROOT / "templates/tabs/dashboard.html").read_text()
TOPBAR = (ROOT / "templates/partials/topbar.html").read_text()

# Loads app.js with a stub Alpine and runs the store's own getters. Shared by the node
# test and, where node is missing, by a browser run of the same script.
SCRIPT = """
var __store = null;
// Anything app.js touches at load (dataset, matchMedia, storage...) answers with an inert
// stand-in, so only the store's getters are exercised.
function __inert(over) {
  var f = function () { return p; };
  var p = new Proxy(f, {
    get: function (t, k) {
      if (over && k in over) return over[k];
      if (k === Symbol.toPrimitive) return function () { return ''; };
      if (k === 'then') return undefined;
      return p;
    },
    apply: function () { return p; },
  });
  return p;
}
var Alpine = {store: function (n, o) { if (n === 'app') __store = o; }, data: function () {}};
var document = __inert({addEventListener: function (ev, fn) { if (ev === 'alpine:init') fn(); }});
var window = __inert({});
var localStorage = __inert({getItem: function () { return null; }});
var sessionStorage = localStorage;
""" + JS + """
function label(power, battery) {
  __store.summary = {power: power, battery: battery || {}};
  return [__store.runStatusLabel, __store.runStatusSource, __store.chargeState];
}
var __out = {
  debug: label({run_status: 8, debug: true, run_status_desc: 'Debug'}),
  offgrid_over_vpp: label({off_grid: true, vpp: true, run_status: 2}),
  vpp_local: label({vpp: true, vpp_kind: 'remote', run_status: 2,
                    run_status_desc: 'Discharging'}),
  own_force: label({vpp: true, vpp_kind: 'force', vpp_label: 'Force dispatch', run_status: 2,
                    run_status_desc: 'Discharging'}),
  vpp_cloud: label({vpp: true, vpp_kind: 'vpp', vpp_label: 'VPP mode', vpp_programme: 'Prog A',
                    run_status: 2}),
  starting: label({agate_starting: true, run_status: 0, run_status_desc: null}),
  plain: label({run_status: 0, run_status_desc: 'Standby'}, {run_status_desc: 'Standby'}),
  none: label({}),
};
"""


def _check(out):
    assert out["debug"][0] == "Debug Mode" and "1301 run_status 8" in out["debug"][1]
    assert out["offgrid_over_vpp"][0] == "Off-grid"
    assert out["vpp_local"][0] == "VPP" and "1707 programme id 9" in out["vpp_local"][1]
    assert out["own_force"][0] == "Force" and "this bridge" in out["own_force"][1]
    assert out["vpp_cloud"][0] == "VPP mode · Prog A" and "cloud" in out["vpp_cloud"][1]
    assert out["starting"][0] == "Reconnecting" and "all zeros" in out["starting"][1]
    assert out["starting"][2] == "Reconnecting"            # the top-bar chip agrees
    assert out["plain"][0] == "Standby" and "1301" in out["plain"][1]
    assert out["none"][0] == "--"


def test_static_wiring():
    assert ':title="$store.app.runStatusSource"' in DASH
    assert "SUPPORT SESSION" not in TOPBAR and "DEBUG MODE" in TOPBAR
    # 1707 = 9 is VPP (owner); FORCE is only this bridge's own force (#333).
    assert "g.vpp_kind === 'force' && !g.off_grid" in TOPBAR
    assert "$store.app.isOwnForce && !$store.app.isOffGrid" in TOPBAR


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_priority_order_in_the_real_getters():
    out = json.loads(subprocess.run(
        ["node", "-e", SCRIPT + "console.log(JSON.stringify(__out));"],
        capture_output=True, text=True, check=True).stdout)
    _check(out)
