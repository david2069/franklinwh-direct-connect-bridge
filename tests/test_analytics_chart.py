"""#144 / #145 — guards for the Analytics chart (behaviour checked in a browser; see PR).

These pin the decisions that a refactor could quietly undo: a real time axis, no
smoothing, gaps kept, a date-and-time custom range, an export of the shown window, and a
site zone that follows the selected gateway."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (ROOT / "static" / "js" / "analytics_tab.js").read_text()
APP = (ROOT / "static" / "js" / "app.js").read_text()
HTML = (ROOT / "templates" / "tabs" / "analytics.html").read_text()


def test_time_axis_not_category():
    assert "type: 'linear'" in JS and "labels," not in JS


def test_no_smoothing_and_gaps_kept():
    assert "tension: 0," in JS and "spanGaps: false" in JS


def test_custom_range_takes_date_and_time():
    # the custom range is date-and-time; the one date input is the day picker (owner 2026-11-09)
    assert HTML.count('type="datetime-local"') == 2 and HTML.count('type="date"') == 1


def test_export_uses_the_shown_window():
    assert "metrics/export?fmt=${fmt}&start=${w.start}&end=${w.end}" in JS


def test_site_zone_follows_the_selected_gateway():
    sel = APP[APP.index("selectGateway(id) {"):]
    assert "this.loadSiteTz();" in sel[:sel.index("},")]
    assert "this._siteTzFor !== this._siteTzKey()" in APP


def test_steps_back_and_forward_by_the_shown_span_and_has_today():
    # Owner, 2026-11-09: ‹ › stepping and Today, as on the Cloud view.
    assert "stepWindow(-1)" in HTML and "stepWindow(1)" in HTML and "goToday()" in HTML
    assert "atToday" in HTML and "atOldest" in HTML


def test_stepping_stops_at_the_oldest_stored_sample():
    assert "this.firstTs = (d && d.first_ts) || null;" in JS
    body = JS[JS.index("get atOldest()"):][:200]
    assert "this.firstTs" in body and "this.window.start" in body
    assert "history from" in HTML or "history from" in JS



LOCAL = HTML[HTML.index("x-show=\"source === 'local'\""):]


def test_local_uses_the_cloud_views_layout():
    # Owner, 2026-11-09: Local and Cloud share one layout (Cloud's): a period dropdown,
    # ‹ day › Today on the right, chips and Line | Area under the chart.
    assert '<select' in LOCAL and 'aria-label="Period"' in LOCAL and 'x-for="r in ranges"' not in LOCAL
    for v in ("24h", "3d", "7d", "30d", "custom"):
        assert f'<option value="{v}"' in LOCAL
    assert 'type="date"' in LOCAL and 'jumpTo($event.target.value)' in LOCAL
    assert LOCAL.index("toggleMetric(") > LOCAL.index('x-ref="canvas"')
    assert LOCAL.index("chartType = 'area'") > LOCAL.index('x-ref="canvas"')
    assert "fwh-analytics-range" in JS


def test_local_dates_follow_the_browsers_own_format():
    body = JS[JS.index("dayLabel(ts, year) {"):][:200]
    assert "Intl.DateTimeFormat(undefined" in body and "timeZone: 'UTC'" in body
