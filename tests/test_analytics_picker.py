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


def test_line_and_bars_are_dropdowns_with_their_variants():
    # Owner, 2026-11-10: Stack wrapped the row; "Bars stacked" under Bars, Area under Line.
    seg = TOP[TOP.index('aria-label="Chart style"'):][:6000]
    assert 'aria-label="Line chart"' in seg and 'aria-label="Bar chart"' in seg
    assert "setChartType('line')" in seg and "setChartType('area')" in seg
    assert "setBars(false)" in seg and "setBars(true)" in seg and ">Bars stacked<" in seg
    assert "setChartType('flow')" in seg
    assert '@click="setStacked(!stacked)"' not in HTML                # no separate Stack button


def test_local_day_uses_clouds_colours():
    defs = JS[JS.index("metricDefs:"):][:900]
    for key, colour in (("grid_w", "#8a94a3"), ("solar_w", "#e8b100"), ("battery_w", "#2fae6b"), ("load_w", "#5b8def")):
        assert f"key: '{key}'" in defs and colour in defs[defs.index(f"key: '{key}'"):][:80]


def test_the_cloud_panel_takes_this_pages_theme():
    css = (SRC / "static" / "css" / "design-system.css").read_text()
    assert "html .fwhca {" in css and "--ca-menu-bg: var(--surface-1)" in css and "--ca-gridline" in css
