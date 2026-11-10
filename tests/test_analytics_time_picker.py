"""Owner, 2026-11-10: the Day views take a start and an end time ("i really [want] a start n
end time"): From and To beside the date, each from the styled time grid (5-minute steps on
Day (5-min), hours on Day (hourly)). The chart, Local or Cloud, and Flow show just that
stretch, which may run into the next day; Clear goes back to the whole day. (This replaced
the single Time that only moved the readout.)"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "franklinwh_direct_connect_bridge"
JS = (SRC / "static" / "js" / "analytics_tab.js").read_text()
HTML = (SRC / "templates" / "tabs" / "analytics.html").read_text()


def test_from_and_to_beside_the_date_on_the_day_views():
    body = JS[JS.index("get timeMode()"):][:200]
    assert "'day5'" in body and "'dayhour'" in body and "'flow'" not in body   # Flow follows it too
    assert 'aria-label="Start time"' in HTML and 'aria-label="End time"' in HTML
    assert "openDayTime('from')" in HTML and "openDayTime('to')" in HTML
    assert "atTime" not in JS and "showAt(" not in JS and 'aria-label="Pick a time"' not in HTML


def test_the_grid_snaps_to_the_views_slots():
    assert "i * 5" in JS[JS.index("get pickerMinutes()"):][:200]
    body = JS[JS.index("get gridMinutes()"):][:200]
    assert "this.period === 'day5'" in body
    assert 'aria-label="Hour"' in HTML and 'aria-label="Minute"' in HTML and 'x-show="gridMinutes"' in HTML


def test_the_stretch_can_run_into_the_next_day_and_clear_goes_back():
    body = JS[JS.index("get dayRange()"):][:900]
    assert "this.dayTo > (this.dayFrom || '00:00')" in body and "next" in body
    assert "clearDayTimes()" in HTML


def test_local_cloud_and_flow_show_the_stretch():
    win = JS[JS.index("get window() {"):][:1600]
    assert "this.dayRange" in win
    load = JS[JS.index("async load() {"):][:1200]
    assert "this._cloud.setRange(r.from, r.to, this.period === 'dayhour' ? 'hour' : '5min')" in load
    flow = JS[JS.index("async loadFlow(refresh) {"):][:1200]
    assert "this.dayRange" in flow


def test_the_cloud_extra_takes_a_ranges_slots():
    assert "franklinwh-ha-cloud-analytics==0.1.24" in (ROOT / "pyproject.toml").read_text()
