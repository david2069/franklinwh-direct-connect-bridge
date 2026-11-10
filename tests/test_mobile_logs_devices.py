"""Phone layout: the log list swipes sideways; companion device rows wrap (owner, 2026-11-04)."""

from pathlib import Path

TPL = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge/templates"


def _logs():
    return (TPL / "tabs/logs.html").read_text()


def _devices():
    t = (TPL / "tabs/settings.html").read_text()
    return t[t.index("<!-- ── Companion Devices ── -->"):t.index("<!-- Add-device modal")]


def test_a_log_line_stays_on_one_row_on_a_phone_and_the_list_scrolls_sideways():
    t = _logs()
    scroller = t[t.index('data-testid="log-scroller"') - 200:]
    assert 'overflow-auto' in scroller[:300]
    assert "whitespace-pre sm:whitespace-pre-wrap sm:break-all" in t   # no letter-by-letter wrap
    assert "break-all whitespace-pre-wrap\" x-text=\"e.message\"" not in t
    # Header and rows share one wrapper as wide as the widest line.
    assert '<div class="min-w-max sm:min-w-0" data-testid="log-rows">' in t
    w = t.index('data-testid="log-rows"')
    assert w < t.index(">Message</span>") < t.index('x-for="(e, i) in filtered()"')


def test_the_log_header_scrolls_with_the_columns():
    t = _logs()
    s = t.index('data-testid="log-scroller"')
    assert s < t.index(">Message</span>")                                # header inside the scroller
    assert "sticky top-0" in t[s:t.index(">Message</span>")]


def test_the_device_row_and_header_wrap_on_a_phone():
    d = _devices()
    assert 'flex flex-wrap items-center justify-between gap-2" data-testid="companion-header"' in d
    row = d[d.index('data-testid="companion-device"') - 200:]
    assert "flex flex-wrap" in row[:250]


def test_the_test_result_has_its_own_full_width_line():
    d = _devices()
    rt = d[d.index('data-testid="notify-rt"') - 120:d.index('data-testid="notify-rt"')]
    assert "basis-full" in rt
    # After the buttons, not inside the name column that the buttons squeeze.
    assert d.index('data-testid="notify-rt"') > d.index("Test with buttons</button>")
