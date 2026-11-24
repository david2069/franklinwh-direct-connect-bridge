"""Scheduler list: smaller cards, plus Compact and Table views (owner 2026-11-24).

Each schedule shows only Explain, Edit and the ⋮ menu on one line; Turn on/off, Stop (while
running), Test against live, Run now, Duplicate and Delete are in the menu. A toggle picks
Cards, Compact or Table, remembered by the browser."""
import pathlib
import re

from jinja2 import Environment, FileSystemLoader

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
JS = (PKG / "static" / "js" / "scheduler_tab.js").read_text()


def rendered():
    env = Environment(loader=FileSystemLoader(str(PKG / "templates")))
    return env.get_template("tabs/scheduler.html").render()


def test_the_view_toggle_and_the_three_views():
    out = rendered()
    for tid in ("sched-view-toggle", "sched-cards", "sched-compact", "sched-table"):
        assert f'data-testid="{tid}"' in out, tid
    assert "['cards','Cards'],['compact','Compact'],['table','Table']" in out
    assert re.search(r"listView:\s*\(\(\) => \{\s*try", JS)          # remembered, safely
    assert "fwh-sched-view" in JS


def test_each_view_has_only_explain_edit_and_the_menu_as_buttons():
    out = rendered()
    rows = re.findall(r'<div class="sched-actions[^"]*"[^>]*>(.*?)<!-- /sched-actions -->', out, re.S)
    assert len(rows) == 3                                           # cards, compact, table
    for r in rows:
        buttons = re.findall(r"<button[^>]*>(.*?)</button>", r, re.S)
        labels = [re.sub(r"<[^>]+>|\s+", " ", b).strip() for b in buttons]
        top = [l for l in labels if l in ("Edit", "") or "Explain" in l or "explanation" in l]
        assert any("Edit" == l for l in labels)
        menu = r[r.index('data-testid="sched-menu"'):]
        for item in ("toggle(s)", "stopEntry(s)", "verify(s)", "runNow(s)", "duplicate(s)", "remove(s)"):
            assert item in menu, item                                # all in the ⋮ menu
            assert item not in r[:r.index('data-testid="sched-menu"')], item
        assert top
