"""The FranklinWH TOU view in tables (owner 2026-11-18: "very hard to read"): today and
each season's day types are tables of Time | Dispatch | Band | Buy | Sell, scrolled
inside their own box on a phone. Every value shown before is still shown: a band with a
rate but no block today gets its own row."""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
JS = (PKG / "static" / "js" / "scheduler_tab.js").read_text()


def _table(testid):
    m = re.search(r'<table[^>]*data-testid="%s".*?</table>' % testid, HTML, re.S)
    assert m, testid
    return m.group(0)


def test_today_is_a_table_with_the_five_columns():
    t = _table("tou-today-table")
    heads = re.findall(r"<th[^>]*>([^<]*)</th>", t)
    assert heads[:5] == ["Time", "Dispatch", "Band", "Buy", "Sell"]
    assert "touColour(b.dispatch_id)" in t and 'data-testid="tou-rates"' in t
    assert "b.buy" in t and "b.sell" in t and "b.wave" in t
    assert 'data-testid="tou-bar"' in HTML and 'data-testid="tou-rate-unit"' in HTML


def test_each_season_day_type_is_a_table_and_the_rates_line_is_gone():
    t = _table("tou-season-table")
    heads = re.findall(r"<th[^>]*>([^<]*)</th>", t)
    assert heads[:5] == ["Time", "Dispatch", "Band", "Buy", "Sell"]
    assert "touDayRows(d)" in t
    assert "'Rates: '" not in HTML


def test_a_band_with_a_rate_but_no_block_still_shows():
    assert "touDayRows(d)" in JS
    body = JS[JS.index("touDayRows(d)"):][:900]
    assert "d.rates" in body and "d.blocks" in body


def test_the_tables_scroll_inside_their_box_on_a_phone():
    for tid in ("tou-today-table", "tou-season-table"):
        i = HTML.index('data-testid="%s"' % tid)
        assert "overflow-x-auto" in HTML[max(0, i - 400):i], tid
