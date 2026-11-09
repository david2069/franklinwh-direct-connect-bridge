"""Owner, 2026-11-09: one time span picker for Local and Cloud with Cloud's periods
(Day (5-min), Day (hourly), Week, Month, Year, Lifetime; no Custom), and one top row:
the time span, then Local | Cloud, Export ▾ (CSV, JSON) and Refresh."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (ROOT / "static" / "js" / "analytics_tab.js").read_text()
HTML = (ROOT / "templates" / "tabs" / "analytics.html").read_text()
TOP = HTML[:HTML.index('x-ref="cloud"')]


def test_one_time_span_picker_at_the_top_with_clouds_periods():
    assert HTML.count('aria-label="Time span"') == 1 and 'aria-label="Time span"' in TOP
    assert 'x-for="p in periods"' in TOP
    assert "FWHCloudAnalytics.PERIODS" in JS and "fwh-analytics-period" in JS
    assert 'value="custom"' not in HTML and 'type="datetime-local"' not in HTML
    assert "applyCustom" not in JS


def test_the_top_row_is_time_span_then_source_export_and_refresh():
    i = [TOP.index(s) for s in ('aria-label="Time span"', 'aria-label="Chart style"', 'aria-label="Source"',
                                 'aria-label="Export"', "@click=\"refresh()\"")]
    assert i == sorted(i)
    menu = TOP[TOP.index('aria-label="Export"'):][:1500]
    assert "exportData('csv')" in menu and "exportData('json')" in menu
    assert "@click.outside" in TOP


def test_one_chart_style_at_the_top_after_the_time_span_for_both_sources():
    # Owner, 2026-11-10: "the chart type on the top right after the time span".
    assert HTML.count("setBars(false)") == 1 and "setBars(false)" in TOP
    assert TOP.index('aria-label="Chart style"') > TOP.index('aria-label="Time span"')
    m = JS[JS.index("FWHCloudAnalytics.mount("):][:500]
    assert "styleControl: false" in m and "style: this.style" in m
    body = JS[JS.index("setChartType(t) {"):][:400]
    assert "this._cloud.setStyle(t)" in body


def test_the_cloud_panel_takes_the_shared_picker():
    m = JS[JS.index("FWHCloudAnalytics.mount("):][:400]
    assert "periodPicker: false" in m and "period: this.period" in m
    body = JS[JS.index("setPeriod(v) {"):][:500]
    assert "this.load()" in body                                    # load() hands Cloud its period
    assert "this._cloud.setPeriod(this.period, this.startDay)" in JS


def test_local_steps_by_calendar_period_on_the_sites_clock():
    # A day, a Monday-to-Sunday week, a month and a year in the site zone, as Cloud does.
    body = JS[JS.index("function analyticsPeriodWindow("):][:2000]
    for p in ("'day5'", "'week'", "'month'", "'year'", "'lifetime'"):   # dayhour: hourly
        assert p in body
    assert "getUTCDay()" in body                      # weeks start on Monday
    assert "bucket: 300" in body and "bucket: 3600" in body


def test_fewer_time_ticks_on_a_narrow_screen():
    # Owner's phone screenshot: 00:0003:0006:00… ran together at 390 px.
    assert "ticksFor(start, end, max = 8)" in JS and "clientWidth" in JS[JS.index("render() {"):][:600]
