"""Owner, 2026-11-10: "where [is the] custom date time picker. where is the legend color
picker" — both were inside menus. The legend (Local and Cloud) has a Colours button, and
the Day views show a Time button beside the date."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (SRC / "templates" / "tabs" / "analytics.html").read_text()


def test_both_legends_open_the_colours_dialog():
    assert HTML.count('aria-label="Legend colours"') == 2
    local = HTML[HTML.index('toggleMetric(m.key)'):][:1200]
    assert 'aria-label="Legend colours"' in local
    cloud = HTML[HTML.index('x-ref="cloud"'):][:600]
    assert 'aria-label="Legend colours"' in cloud


def test_the_day_views_show_a_time_button_beside_the_date():
    row = HTML[HTML.index('aria-label="Pick a date"'):][:9000]
    assert 'aria-label="Pick a time"' in row
    btn = HTML[HTML.index('aria-label="Pick a time"') - 400:][:900]
    assert 'x-show="timeMode"' in btn and "openPicker()" in btn and "atTime || 'Time'" in btn
