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
    assert HTML.count('type="datetime-local"') == 2 and 'type="date"' not in HTML


def test_export_uses_the_shown_window():
    assert "metrics/export?fmt=${fmt}&start=${w.start}&end=${w.end}" in JS


def test_site_zone_follows_the_selected_gateway():
    sel = APP[APP.index("selectGateway(id) {"):]
    assert "this.loadSiteTz();" in sel[:sel.index("},")]
    assert "this._siteTzFor !== this._siteTzKey()" in APP
