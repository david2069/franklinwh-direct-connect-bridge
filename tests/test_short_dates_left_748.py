"""#748 (owner 2026-11-18): short dates always on the left, in a fixed-width tabular column.

1. Scheduler → activity log: "11/18/2026, 6:01:18 PM" took half the row on a phone. The
   first column now shows "18 Nov 18:01"; the full timestamp is its title (hover/tap).
2. Network → PoP distribution: a table with column headers (PoP | share | Requests),
   numbers right-aligned without a "req" on every row.
3. Network → Recent edge transitions: a table, short date first, then From → To.

One helper, ``app.shortWhen(ts, zone)``, makes the short form; ``app.fullWhen`` the full
one with the site's zone label (#728) when it differs from the browser's.
"""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
APP_JS = (PKG / "static" / "js" / "app.js").read_text()
SCHED = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
NET = (PKG / "templates" / "tabs" / "network.html").read_text()
CSS = (PKG / "static" / "css" / "design-system.css").read_text()


def test_one_shared_short_date_helper():
    assert "shortWhen(ts, zone)" in APP_JS and "fullWhen(ts, zone)" in APP_JS
    # day month 24-hour time: "18 Nov 18:01"
    body = APP_JS.split("shortWhen(ts, zone)", 1)[1].split("\n    },", 1)[0]
    assert "day: 'numeric'" in body and "month: 'short'" in body and "hourCycle: 'h23'" in body
    assert ".when-col" in CSS and "tabular-nums" in CSS.split(".when-col", 1)[1].split("}", 1)[0]


def test_the_scheduler_log_shows_a_short_date_on_the_left_with_the_full_one_as_title():
    row = SCHED.split('x-for="(e, i) in filteredLog"', 1)[1].split("</tr>", 1)[0]
    first = row.split("<td", 2)[1]
    assert "when-col" in first
    assert "shortWhen(e.ts, 'host')" in first and ":title=\"$store.app.fullWhen(e.ts, 'host')\"" in first
    assert 'x-text="when(e.ts)"' not in SCHED            # the long form is the title now


def test_pop_distribution_is_a_table_with_headers_and_no_req_suffix():
    sec = NET.split("PoP distribution", 1)[1].split("Recent edge transitions", 1)[0]
    assert "<table" in sec and "<thead" in sec
    heads = re.findall(r"<th[^>]*>([^<]+)</th>", sec)
    assert [h.strip() for h in heads] == ["PoP", "Share", "Requests"]
    assert "' req'" not in sec and "tabular-nums" in sec


def test_edge_transitions_are_a_table_with_the_short_date_first():
    sec = NET.split("Recent edge transitions", 1)[1].split("</table>", 1)[0]
    assert "<table" in sec
    heads = [h.strip() for h in re.findall(r"<th[^>]*>([^<]+)</th>", sec)]
    assert heads == ["When", "From", "To"]
    row = sec.split('x-for="(t, i) in pop.transitions"', 1)[1]
    first = row.split("<td", 2)[1]
    assert "when-col" in first and "shortWhen(t.at, 'local')" in first
    assert "fullWhen(t.at, 'local')" in first
    assert "toLocaleString()" not in sec
