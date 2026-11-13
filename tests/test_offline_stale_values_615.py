"""#615: while the aGate is offline the Dashboard marks the last-good values as stale.

Owner screenshot 2026-11-13: the aGate was Offline and the Dashboard still showed SoC 55 %,
Home 253 W and Battery 250 W discharging as if live. The poller kept the last-good summary
but nothing on screen said so. Now the summary says the values are last-good and when they
were read, and the SoC card, Power Flow (Now), the Battery card and the top-bar Charge and
SoC pills grey out, show "Last reading HH:MM (N min ago)" and call the battery
"Unknown (offline)" instead of Charging or Discharging.
"""
import json
import pathlib
import re
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import poller
from franklinwh_direct_connect_bridge import state as state_module

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = (ROOT / "static/js/app.js").read_text()
DASH = (ROOT / "templates/tabs/dashboard.html").read_text()
TOPBAR = (ROOT / "templates/partials/topbar.html").read_text()
CSS = (ROOT / "static/css/design-system.css").read_text()

GOOD = {"ok": True, "power": {"soc": 55, "load_w": 253, "battery_w": 250, "grid_w": 3,
                              "run_status": 2, "run_status_desc": "Discharging"},
        "battery": {"run_status": 2, "run_status_desc": "Discharging"}}


@pytest.fixture(autouse=True)
def _clean_registry():
    state_module.reset_gateways()
    yield
    state_module.reset_gateways()


# -- server: the poller's last-good cache and the summary payload --------------------

def test_a_failed_poll_keeps_the_values_and_says_they_are_last_good():
    gw = state_module.register_gateway("gw-home", "192.0.2.10", "Home")
    gw.state_ts = time.time() - 600          # the last poll that read the gateway
    poller._cache_summary(gw, dict(GOOD))
    poller._cache_summary(gw, {"ok": False, "error": "timed out"})
    s = gw.last_summary
    assert s["ok"] is False and s["stale"] is True and s["error"] == "timed out"
    assert s["last_good"] is True
    assert s["last_good_ts"] == pytest.approx(gw.state_ts)
    assert s["power"]["soc"] == 55           # values kept, not blanked


def test_the_summary_endpoint_serves_the_last_good_marking():
    gw = state_module.register_gateway("gw-home", "192.0.2.10", "Home")
    gw.state_ts = time.time() - 600
    poller._cache_summary(gw, dict(GOOD))
    poller._cache_summary(gw, {"ok": False, "error": "timed out"})
    d = TestClient(app_module.create_app()).get("/api/gateways/gw-home/summary").json()
    assert d["ok"] is False and d["last_good"] is True
    assert d["last_good_ts"] == pytest.approx(gw.state_ts)


def test_a_recovered_poll_is_live_again():
    gw = state_module.register_gateway("gw-home", "192.0.2.10", "Home")
    gw.state_ts = time.time()
    poller._cache_summary(gw, dict(GOOD))
    poller._cache_summary(gw, {"ok": False, "error": "timed out"})
    poller._cache_summary(gw, dict(GOOD))
    s = gw.last_summary
    assert s["ok"] is True and "last_good" not in s and "stale" not in s


def test_no_good_reading_yet_is_not_called_last_good():
    gw = state_module.register_gateway("gw-home", "192.0.2.10", "Home")
    poller._cache_summary(gw, {"ok": False, "error": "refused"})
    assert "last_good" not in gw.last_summary


# -- UI wiring ---------------------------------------------------------------------

def _card(marker):
    cards = re.compile(r'<div class="card[ "]')
    start = cards.search(DASH, DASH.index(marker)).start()
    return DASH[start:cards.search(DASH, start + 1).start()]


@pytest.mark.parametrize("marker", ["<!-- Battery State of Charge -->",
                                    "<!-- Power flow:",
                                    "<!-- Battery (real local fields"])
def test_each_live_card_greys_out_and_shows_the_last_reading(marker):
    card = _card(marker)
    assert "{'is-stale': $store.app.isLastGood}" in card
    assert 'x-text="$store.app.lastGoodText"' in card
    assert "stale-vals" in card


def test_the_battery_card_chip_uses_the_offline_aware_state():
    card = _card("<!-- Battery (real local fields")
    assert "$store.app.batteryChip" in card
    assert "$store.app.battery.run_status_desc || '--'" not in card


def test_the_top_bar_pills_grey_out_with_the_last_reading():
    charge = TOPBAR[TOPBAR.index("<!-- Charge / run status -->"):TOPBAR.index("<!-- SoC -->")]
    soc = TOPBAR[TOPBAR.index("<!-- SoC -->"):TOPBAR.index("<!-- Round-trip latency -->")]
    for pill in (charge, soc):
        assert "{'is-stale': $store.app.isLastGood}" in pill
        assert "$store.app.lastGoodText" in pill


def test_stale_styling_exists():
    assert re.search(r"\.is-stale[^{]*\{[^}]*grayscale", CSS)


def test_store_defines_the_offline_getters():
    for g in ("get isLastGood()", "get lastGoodText()", "get batteryChip()"):
        assert g in JS, g
    assert "'Unknown (offline)'" in JS
    assert "Last reading " in JS


# -- the store's real getters (node) ---------------------------------------------------

SCRIPT = """
var __store = null;
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
function view(summary) {
  __store.summary = summary;
  return {stale: __store.isLastGood, text: __store.lastGoodText,
          charge: __store.chargeState, run: __store.runStatusLabel, chip: __store.batteryChip,
          flow: __store.flowText('battery', summary.power.battery_w),
          grid: __store.flowText('grid', summary.power.grid_w)};
}
var good = %s;
var __out = {
  live: view(good),
  offline: view(Object.assign({}, good, {ok: false, stale: true, last_good: true,
                                         last_good_ts: Date.now() / 1000 - 600})),
};
""" % json.dumps(GOOD)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_real_getters_offline_and_live():
    out = json.loads(subprocess.run(
        ["node", "-e", SCRIPT + "console.log(JSON.stringify(__out));"],
        capture_output=True, text=True, check=True).stdout)
    live, off = out["live"], out["offline"]
    assert live["stale"] is False and live["text"] == ""
    assert live["charge"] == "Discharging" and live["flow"] == "Discharging"
    assert off["stale"] is True
    assert re.fullmatch(r"Last reading \d\d:\d\d \(10 min ago\)", off["text"])
    for k in ("charge", "run", "chip", "flow"):
        assert off[k] == "Unknown (offline)", k
    words = {"Charging", "Discharging", "Importing", "Exporting"}
    assert not words & {off["charge"], off["run"], off["chip"], off["flow"], off["grid"]}
