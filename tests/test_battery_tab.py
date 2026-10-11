"""Battery tab — endpoint contract + render/wiring.

The endpoint is the contract the tab depends on; the render assertions guard
against the markup or a controller member being renamed out from under it.
"""

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module


@pytest.fixture(scope="module")
def client():
    return TestClient(app_module.create_app())


# -- endpoint ----------------------------------------------------------------
def test_battery_endpoint_exists_and_is_documented(client):
    spec = client.get("/openapi.json").json()
    assert "/api/battery" in spec["paths"]
    doc = spec["paths"]["/api/battery"]["get"]["description"]
    assert "1705" in doc and "single" in doc.lower()


def test_battery_endpoint_takes_an_id_within_range(client):
    spec = client.get("/openapi.json").json()
    params = {p["name"]: p for p in spec["paths"]["/api/battery"]["get"]["parameters"]}
    assert params["id"]["schema"]["default"] == 1
    assert params["id"]["schema"]["minimum"] == 1
    assert client.get("/api/battery?id=0").status_code == 422   # rejected, not clamped
    assert client.get("/api/battery?id=99").status_code == 422


def test_battery_endpoint_returns_a_shape_even_with_no_device(client):
    """No aGate configured in tests — it must still answer, not 500."""
    r = client.get("/api/battery")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"]                       # says why
    assert body["id"] == 1


def test_partial_reads_do_not_fail_the_whole_view():
    """A marginal link should still yield whatever blocks came back."""
    import franklinwh_direct_connect_bridge.client as cl

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self): pass
        def battery_cells(self, i): return {"batVolt": [3300] * 16, "batSoc": 50.0}
        def power_electronics(self, i): raise TimeoutError("slow link")
        def device_states(self, i): return {"bmsState": 7}
        def device_firmware(self, i): return {"bms_ver": "V1"}
        def device_check(self): return {"devNum": 1}

    from franklinwh_direct_connect_bridge.config import Settings
    orig = cl._client
    cl._client = lambda s, h: FakeClient()
    try:
        out = cl.battery(Settings(), "1.2.3.4", 1)
    finally:
        cl._client = orig
    assert out["ok"] is True                   # cells arrived, so the view is usable
    assert out["cells"]["batSoc"] == 50.0
    assert out["electrical"] is None           # the one that failed
    assert "electrical" in out["errors"]
    assert "slow link" in out["errors"]["electrical"]


# -- UI wiring ---------------------------------------------------------------
def test_tab_is_registered_and_in_the_sidebar(client):
    """Both navs now render from one registry, so reachability lives in app.js."""
    import pathlib
    html = client.get("/").text
    assert "batteryTab()" in html
    assert "activeTab === 'battery'" in html
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    assert "key: 'battery'" in (root / "static/js/app.js").read_text()
    assert "$store.app.sidebarTabs" in (root / "templates/partials/sidebar.html").read_text()


def test_tab_renders_the_key_sections(client):
    html = client.get("/").text
    for fragment in ("Cell Telemetry", "State of Charge", "State of Health",
                     "Inverter &amp; Power Electronics", "Battery Management System"):
        assert fragment in html, fragment


def test_tab_offers_snapshot_auto_and_chart(client):
    html = client.get("/").text
    assert "Snapshot" in html
    assert "toggleAuto()" in html
    assert "toggleChart()" in html
    assert "changeInterval()" in html


def test_controller_defines_everything_the_template_calls(client):
    js = client.get("/static/js/battery_tab.js").text
    html = client.get("/").text
    for member in ("load", "toggleAuto", "toggleChart", "changeInterval",
                   "clearSamples", "exportCsv", "cellClass", "currentLabel",
                   "spreadClass", "stats", "fmt"):
        assert member in js, f"controller lost {member}"
        assert member in html, f"template no longer uses {member}"


def test_auto_refresh_stops_when_the_tab_is_hidden(client):
    """No point holding a device session open for a view nobody is looking at."""
    js = client.get("/static/js/battery_tab.js").text
    assert "visibilitychange" in js
    assert "stopAuto" in js
    assert "$watch('$store.app.activeTab'" in js


def test_samples_are_bounded(client):
    """An overnight auto-refresh must not grow the per-unit arrays without limit."""
    js = client.get("/static/js/battery_tab.js").text
    assert "maxSamples" in js
    # per-unit ring is bounded in record(): arr.length > maxSamples -> arr.shift()
    assert "arr.length > this.maxSamples" in js and "arr.shift()" in js


def test_multi_apower_chart_overlay(client):
    """Multi-battery sites can overlay aPowers: per-unit sample store, a units
    multi-select, and a draw() branch that plots one line per selected unit."""
    js = client.get("/static/js/battery_tab.js").text
    root = __import__("pathlib").Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/battery.html").read_text()
    for m in ("samplesByUnit", "chartUnits", "selectedUnits", "toggleChartUnit(", "_fetchUnit("):
        assert m in js, f"battery_tab.js missing {m}"
    assert "toggleChartUnit(u.id)" in html and "selectedUnits.length" in html


def test_a_failed_poll_keeps_the_last_reading(client):
    js = client.get("/static/js/battery_tab.js").text
    assert "showing the last good reading" in client.get("/").text
    assert "this.error = e.message" in js


def test_tab_states_the_local_limitation(client):
    html = client.get("/").text
    assert "not on the" in html and "local channel" in html


def test_no_bare_alpine_magics_in_tab_javascript():
    """`$store` / `$watch` are Alpine template magics — inside a component method they
    must be `this.$store`. A bare one throws "Can't find variable: $store" at runtime,
    which the render/wiring tests above cannot see (there is no JS engine here).

    Regression: battery_tab.js shipped with a bare `$store.app.selectedGateway`, so the
    tab rendered but every load() threw.
    """
    import pathlib
    import re

    js_dir = pathlib.Path(__file__).resolve().parents[1] / \
        "src/franklinwh_direct_connect_bridge/static/js"
    magic = re.compile(r"(?<![.\w'\"])\$(store|watch|nextTick|el|refs)\b")
    offenders = []
    for path in js_dir.glob("*_tab.js"):
        src = path.read_text()
        # Blank out /* ... */ blocks, keeping newlines so line numbers still line up.
        src = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), src,
                     flags=re.S)
        for n, line in enumerate(src.splitlines(), 1):
            code = line.split("//")[0]                      # and line comments
            if magic.search(code):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, "bare Alpine magic in component code:\n" + "\n".join(offenders)


# -- Charts sub-tab ----------------------------------------------------------
def test_charts_subtab_is_rendered(client):
    html = client.get("/").text
    for fragment in ("BMS Telemetry", "Recorded sessions", "Comparison (Δ)",
                     "cellChart", "New recording"):
        assert fragment in html, fragment


def test_charts_controller_members_exist(client):
    js = client.get("/static/js/battery_tab.js").text
    for m in ("loadSessions", "openSession", "deleteSession", "startRecording",
              "stopRecording", "pollRecording", "drawCells", "setChartView",
              "comparison", "sessionCsv", "cellColour"):
        assert m in js, f"controller lost {m}"


def test_recording_runs_server_side_not_in_the_browser(client):
    """The point of sessions over the in-page trend: closing the tab is safe."""
    html = client.get("/").text
    assert "Runs on the bridge, not in this browser" in html
    js = client.get("/static/js/battery_tab.js").text
    assert "api/battery/record" in js
    assert "api/battery/record/status" in js      # progress survives a reload


def test_topbar_titles_every_sidebar_tab(client):
    """The old ternary chain fell through to 'Health' for battery/device/logs."""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    tabs = {p.stem for p in (root / "templates/tabs").glob("*.html")}
    titles = (root / "static/js/app.js").read_text()
    block = re.search(r"tabTitles:\s*\{(.*?)\}", titles, re.S).group(1)
    named = set(re.findall(r"(\w+):\s*'", block))
    assert tabs <= named, f"topbar has no title for: {sorted(tabs - named)}"
    assert "tabTitle" in (root / "templates/partials/topbar.html").read_text()


def test_battery_tab_has_live_watch_modal():
    """The 'Watch live' realtime modal: button, modal, canvas, and the JS that
    drives its own poll and draws into its own chart."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/battery.html").read_text()
    js = (root / "static/js/battery_tab.js").read_text()
    assert 'openLive()' in html and 'Watch live' in html
    assert 'id="bmsLiveChart"' in html
    for m in ("openLive(", "closeLive(", "drawLive(", "changeLiveInterval("):
        assert m in js, f"battery_tab.js missing {m}"
    # Must be impossible to get stuck: a big corner ✕, tap-outside, and Escape —
    # not just a small header Close (there is no Escape key on a phone).
    assert 'title="Close live view"' in html, "live modal needs an always-visible corner close"
    assert '@click.self="closeLive()"' in html, "live modal must close on tap-outside"
    assert '@keydown.escape.window="closeLive()"' in html
    # its own canvas, not the Trend's — two Chart instances must not share an id
    assert 'bmsLiveChart' in js and '_liveChart' in js
    # ONE unified timer drives Auto + Chart + Watch-live (no separate _liveTimer)
    assert "_syncPoll(" in js and "_liveTimer" not in js
    # opening the chart must poll so it builds (the "Chart doesn't update" bug)
    assert "this._syncPoll();" in js


def test_cell_charts_have_average_median_series_toggle():
    """The 16 per-cell lines can be collapsed to an Average / Median aggregate
    (with a min–max band) via a series-mode toggle on the recorded-session charts."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/battery.html").read_text()
    js = (root / "static/js/battery_tab.js").read_text()
    assert "setSeriesMode(" in html and "All cells" in html and "Average" in html and "Median" in html
    for m in ("seriesMode", "setSeriesMode(", "Min–max range", "median"):
        assert m in js, f"battery_tab.js missing {m}"
    # the bare min helper line must be hidden from the legend
    assert "it.text !== '_min'" in js


def test_trend_chart_toggles_to_per_cell_metrics():
    """The originally-displayed Trend chart (spread/SoC/temp) can be switched to BMS
    per-cell voltages, or their average / median, via a mode toggle on the Trend card."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/battery.html").read_text()
    js = (root / "static/js/battery_tab.js").read_text()
    assert "setTrendMode(" in html and "Per-cell" in html and "Trend" in html
    for m in ("trendMode", "setTrendMode(", "'percell'", "volts: v.slice()"):
        assert m in js, f"battery_tab.js missing {m}"
    # Voltage / Temperature switch for the per-cell + aggregate modes
    assert "setTrendMetric(" in html and "Voltage" in html and "Temp" in html
    for m in ("trendMetric", "setTrendMetric(", "'temp'", "Temperature (°C)"):
        assert m in js, f"battery_tab.js missing {m}"


def test_dcdc_status_is_decoded_live_verified():
    """DCDCStatus (1703) is the charge-state field — live-verified 4/6/7 =
    Standby/Charging/Discharging. The bridge injects DCDCStatus_desc and the UI
    shows it; runMode/inverterStatus stay raw (not charge states)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    client_src = (root / "client.py").read_text()
    html = (root / "templates/tabs/battery.html").read_text()
    assert "DCDCStatus_desc" in client_src and "DCDC_STATE.get" in client_src
    assert "DCDCStatus_desc" in html, "UI must show the decoded DCDC state"
    # runMode / inverterStatus must NOT be decoded (unproven domains)
    assert "runMode_desc" not in client_src and "inverterStatus_desc" not in client_src


def test_apower_selector_uses_serials():
    """The aPower picker is labelled by serial (units.devMap[].devSN), not a bare
    index, and is a real chooser on a multi-battery site."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/battery.html").read_text()
    assert "u.devSN" in html and "data.units.devMap" in html
    assert "'aPower ' + u.id + ' · ' + u.devSN" in html


def test_legend_deselect_persists_across_redraw():
    """The Trend chart is destroyed+recreated each poll; a series the user hides
    from the legend must stay hidden (was being re-selected every refresh)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    js = (root / "static/js/battery_tab.js").read_text()
    assert "_hidden" in js
    assert "self._hidden[d.label]" in js and "d.hidden = true" in js  # re-applied on redraw
    assert "onClick(e, item, legend)" in js                          # records legend clicks


def test_apower_selector_gated_to_multi_unit():
    """The serial dropdown only shows for 2+ aPowers — a single-unit dropdown is
    redundant (serial is in the BMS card) and jammed the controls row."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/battery.html").read_text()
    assert "(data.units.devMap || []).length > 1" in html


def test_per_apower_table_for_multi_battery():
    """A 2+ aPower site shows a per-aPower table (one row per battery) instead of
    the single BMS identity card; load() gathers each unit's summary."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/battery.html").read_text()
    js = (root / "static/js/battery_tab.js").read_text()
    assert 'x-if="unitRows.length > 1"' in html      # table only for multi
    assert '!(unitRows.length > 1)' in html  # single BMS card hidden for multi (now &&-gated with bmsCards.header)
    assert "x-for=\"r in unitRows\"" in html
    assert "unitRows" in js and "_unitRow(" in js


def test_percell_stack_per_apower():
    """Per-cell mode with 2+ selected aPowers renders a STACK — one small per-cell
    chart per aPower — instead of one canvas."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    html = (root / "templates/tabs/battery.html").read_text()
    js = (root / "static/js/battery_tab.js").read_text()
    assert "bmsCellChart-" in html and 'x-show="showStack"' in html
    for m in ("get showStack(", "drawPerCellStack(", "_stackCharts", "_destroyStack(", "unitLabel("):
        assert m in js, f"battery_tab.js missing {m}"


def test_battery_reloads_on_gateway_switch():
    """Switching the topbar gateway must re-read the battery (it used to keep showing
    the previous gateway's data — the '4 aPowers didn't appear on Mock GW' bug)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
    js = (root / "static/js/battery_tab.js").read_text()
    assert "$store.app.selectedGateway" in js and "this.samplesByUnit = {}" in js
    # gateway param isn't doubled anymore
    assert "q.set('gateway'" not in js
