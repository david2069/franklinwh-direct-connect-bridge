"""#50 and #161 (and #148): say whose value and which clock.

- The top bar shows the gateway's (site) time and, when it differs, the viewer's.
- Time axes say their zone.
- The Scheduler shows times on each schedule's gateway clock with the zone, and warns when
  gateways are in different zones; Next fire is no longer in the browser's zone.
- The dashboard's Modbus cards say their subject: this bridge's Modbus client (on/off first,
  the aGate's :502 reachability second) vs the aGate's own Modbus TCP Server setting.
"""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
T = PKG / "templates"
JS = PKG / "static" / "js"


def read(p):
    return p.read_text()


def test_the_top_bar_shows_site_time_and_the_viewers_when_different():
    top = read(T / "partials" / "topbar.html")
    assert 'data-testid="topbar-clock"' in top
    assert "topbarShow('clock')" in top and "topbarOrder('clock')" in top
    app = read(JS / "app.js")
    assert "{ id: 'clock', label: 'Gateway time and your time', on: true }" in app
    body = app[app.index("get clockText() {"):][:1200]
    assert "siteTzOffsetMin" in body and "your time" in body
    assert "clockNow" in app and re.search(r"clockNow = Date\.now\(\)", app)


def test_time_axes_say_their_zone():
    app = read(JS / "app.js")
    assert "timeAxisTitle(" in app
    hist = app[app.index("x: { ticks: { maxTicksLimit: 8, autoSkip: true }"):][:200]
    assert "timeAxisTitle()" in hist
    bat = read(JS / "battery_tab.js")
    assert bat.count("timeAxisTitle()") >= 3                    # cells, trend, live
    ana = read(JS / "analytics_tab.js")
    assert "title: { display: true, text: 'Time (' + self.zoneShort + ')'" in ana
    sd = read(JS / "smart_dispatch_tab.js")
    assert "x: { title: { display: true, text: 'Time (' + this.zoneShort + ')'" in sd


def test_scheduler_times_are_on_the_gateways_clock_with_the_zone():
    js = read(JS / "scheduler_tab.js")
    nf = js[js.index("nextFireLabel(s) {"):][:1600]
    assert "toLocaleTimeString" not in nf and "gwZone(" in nf
    assert "loadGatewayZones()" in js and "api/site/timezone?gateway=" in js
    html = read(T / "tabs" / "scheduler.html")
    for tid in ("sched-zone-warning", "sched-form-zone"):
        assert f'data-testid="{tid}"' in html, tid
    assert "zonesDiffer" in html and "zoneNote(" in html


def test_history_says_its_clock():
    html = read(T / "tabs" / "scheduler.html")
    assert 'data-testid="sched-history-zone"' in html and "hostTzLabel" in html


def test_the_modbus_cards_say_their_subject():
    d = read(T / "tabs" / "dashboard.html")
    assert "Modbus client (this bridge)" in d
    card = d[d.index("Modbus client (this bridge)"):][:1500]
    assert "$store.app.modbusEnabled" in card                  # on/off leads
    assert "aGate :" in card and "modbus_502" in card          # reachability second
    assert "Modbus TCP Server (aGate setting)" in d
