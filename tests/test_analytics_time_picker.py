"""Owner, 2026-11-10: the custom date picker takes a time on Day (5-min) and Day (hourly),
snapped to the 5-minute or hourly slot; the chart then opens with its readout at that time,
on Local and on Cloud (the package's showAt)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "franklinwh_direct_connect_bridge"
JS = (SRC / "static" / "js" / "analytics_tab.js").read_text()
HTML = (SRC / "templates" / "tabs" / "analytics.html").read_text()


def test_the_picker_has_a_time_row_on_the_day_views_only():
    assert "get timeMode()" in JS
    body = JS[JS.index("get timeMode()"):][:200]
    assert "'day5'" in body and "'dayhour'" in body and "'flow'" in body
    assert 'x-show="timeMode"' in HTML
    assert 'aria-label="Hour"' in HTML and 'aria-label="Minute"' in HTML
    assert "pickerMinutes" in HTML and 'x-show="gridMinutes"' in HTML        # a styled grid since the custom range
    assert "this.period === 'day5'" in JS[JS.index('get gridMinutes()'):][:200]


def test_minutes_snap_to_the_five_minute_slots():
    body = JS[JS.index("get pickerMinutes()"):][:200]
    assert "i * 5" in body


def test_the_time_shows_on_the_date_button_and_opens_both_readouts():
    assert "this.atTime" not in JS[JS.index("get periodLabel()"):][:700]   # on the Time button now
    assert "showAt(" in JS and "showLocalAt()" in JS
    body = JS[JS.index("showLocalAt() {"):][:1500]
    assert "tooltip.setActiveElements" in body and "setActiveElements" in body


def test_the_cloud_extra_has_show_at():
    assert "franklinwh-ha-cloud-analytics==0.1.22" in (ROOT / "pyproject.toml").read_text()
