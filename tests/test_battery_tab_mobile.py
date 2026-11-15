"""Battery tab on a phone (owner, 2026-11-15 screenshots): a read that took over 20 s
showed "Fetch is aborted — showing the last good reading" with no reading; Recording gets
its own tab; the sessions list collapses so the chart has the width; what to chart is a
drop-down on a phone."""
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates/tabs/battery.html").read_text()
JS = (PKG / "static/js/battery_tab.js").read_text()


def test_a_slow_read_says_so_and_never_claims_a_reading_it_has_not():
    load = JS[JS.index("    async load() {"):JS.index("    async _fetchUnit(")]
    assert "60000" in load and "AbortError" in load            # waits longer, names a timeout
    i = HTML.index("showing the last good reading")
    assert 'x-show="data"' in HTML[HTML.rfind("<span", 0, i):i]   # only when there is one
    assert "data-testid=\"bms-retry\"" in HTML


def test_recording_has_its_own_tab():
    for v in ("telemetry", "recording", "charts"):
        assert f"setView('{v}')" in HTML
    rec = HTML[HTML.index("<!-- Recording:"):HTML.index("<!-- Charts:")]
    assert "New recording" in rec and 'data-testid="bms-schedules"' in rec


def test_sessions_collapse_and_the_chart_choice_is_a_dropdown_on_a_phone():
    charts = HTML[HTML.index("<!-- Charts:"):]
    assert "sessionsOpen" in charts and 'data-testid="bms-sessions-toggle"' in charts
    assert 'data-testid="bms-chart-view"' in charts and 'data-testid="bms-series-mode"' in charts
    assert "sm:hidden" in charts                               # the drop-downs, phone only
    assert "sessionsOpen" in JS
