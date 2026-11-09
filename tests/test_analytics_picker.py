"""Owner, 2026-11-10: one styled date picker for Local, Cloud and Flow (the browser's own
was a different size on each card), and Stack beside Line | Area | Bars | Flow for both."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (SRC / "static" / "js" / "analytics_tab.js").read_text()
HTML = (SRC / "templates" / "tabs" / "analytics.html").read_text()
TOP = HTML[:HTML.index('x-ref="cloud"')]


def test_one_styled_picker_above_every_view_and_no_browser_date_input():
    assert 'type="date"' not in HTML
    assert HTML.count('aria-label="Pick a date"') == 2            # the button and its popover
    assert HTML.count("stepWindow(-1)") == 1 and HTML.count("goToday()") == 1
    assert TOP.index('aria-label="Pick a date"') > TOP.index('aria-label="Source"')
    for mode in ("pickerMode === 'days'", "pickerMode === 'months'", "pickerMode === 'years'"):
        assert mode in HTML
    assert "@click.outside" in HTML[HTML.index('aria-label="Pick a date"') - 400:][:600]


def test_the_picker_shows_the_period_and_offers_only_what_exists():
    label = JS[JS.index("get periodLabel()"):][:900]
    assert "Week of" in label and "month: 'long'" in label
    days = JS[JS.index("get pickerDays()"):][:1200]
    assert "this.today" in days and "minDay" in days                # no future, no day before history
    assert "pick(iso) {" in JS and "this.jumpTo(iso)" in JS[JS.index("pick(iso) {"):][:200]


def test_cloud_follows_the_shared_picker():
    mount = JS[JS.index("FWHCloudAnalytics.mount("):][:700]
    assert "navControl: false" in mount and "date: this.startDay" in mount
    assert "this._cloud.setPeriod(this.period, this.startDay)" in JS


def test_stack_beside_the_chart_styles_for_both_sources():
    seg = TOP[TOP.index('aria-label="Chart style"'):][:6000]
    assert 'aria-label="Stacked bars"' in seg and "chartType === 'bars'" in seg
    assert "fwh-analytics-stacked" in JS and "this._cloud.setStacked(" in JS
    mount = JS[JS.index("FWHCloudAnalytics.mount("):][:700]
    assert "stackControl: false" in mount and "stacked: this.stacked" in mount
    render = JS[JS.index("render() {"):][:7000]
    assert "stacked: stack" in render                              # Chart.js stacking on x and y


def test_one_chart_button_with_every_chart_type():
    # Owner, 2026-11-10: one Chart button holding all the chart types, remembered.
    seg = TOP[TOP.index('aria-label="Chart style"'):TOP.index('aria-label="Source"')]
    assert seg.count('aria-haspopup="menu"') == 1 and 'x-text="chartLabel"' in seg
    for call in ("setChartType('line')", "setChartType('area')", "setBars(false)", "setBars(true)", "setChartType('flow')"):
        assert call in seg
    assert seg.count('role="menuitemradio"') == 5
    label = JS[JS.index("get chartLabel()"):][:400]
    assert "'Bars stacked'" in label and "'Flow'" in label
    assert "fwh-analytics-style" in JS and "fwh-analytics-stacked" in JS   # remembered


def test_cloud_has_no_refresh_of_its_own_and_its_note_sits_under_the_chart():
    mount = JS[JS.index("FWHCloudAnalytics.mount("):][:900]
    assert "refreshControl: false" in mount and "statusBelow: true" in mount


def test_local_day_uses_clouds_colours():
    defs = JS[JS.index("metricDefs:"):][:900]
    for key, colour in (("grid_w", "#8a94a3"), ("solar_w", "#e8b100"), ("battery_w", "#2fae6b"), ("load_w", "#5b8def")):
        assert f"key: '{key}'" in defs and colour in defs[defs.index(f"key: '{key}'"):][:80]


def test_the_cloud_panel_takes_this_pages_theme():
    css = (SRC / "static" / "css" / "design-system.css").read_text()
    assert "html .fwhca {" in css and "--ca-menu-bg: var(--surface-1)" in css and "--ca-gridline" in css


def test_local_and_cloud_plots_line_up():
    # Owner, 2026-11-10: "the charts are still not aligning".
    mount = JS[JS.index("FWHCloudAnalytics.mount("):][:1100]
    assert "socAxis: 'always'" in mount                            # same plot width every period
    render = JS[JS.index("render() {"):][:3000]
    assert "slotTick" in render and "< 520 ? 4 : 8" in render       # Cloud's tick rule for kWh slots
    assert "this.edges = edges;" in JS and "slotTickLabel(start) {" in JS
    assert "offset: false" in render or "offset: false" in JS[JS.index("render() {"):][:6000]
