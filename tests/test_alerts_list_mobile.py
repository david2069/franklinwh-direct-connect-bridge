"""Open alerts on a phone (owner, 2026-11-15 screenshot): a long timestamp in a fixed
column squeezed the message into one word per line. Each alert is now lines: severity,
a short time and its state, Acknowledge; then the title; then the message."""
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates/partials/alerts.html").read_text()
JS = (PKG / "static/js/alerts.js").read_text()


def test_each_alert_is_stacked_lines_with_a_short_time():
    lst = HTML[HTML.index("<!-- Open alerts"):]
    row = lst[lst.index('x-for="a in $store.alerts.list"'):]
    assert "w-40" not in row                          # no fixed time column
    assert "$store.alerts.short(a)" in row and "$store.alerts.state(a)" in row
    assert 'data-testid="alert-row"' in row
    short = JS[JS.index("    short(a) {"):]
    assert "month: 'short'" in short[:short.index("\n    },")]
