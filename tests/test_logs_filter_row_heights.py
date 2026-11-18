"""Owner 2026-11-19 (iPad): the Logs filter row's search box and drop-downs were taller
than its buttons. Every control in the row is the compact size and stretches to one
height."""
import pathlib
import re

LOGS = (pathlib.Path(__file__).resolve().parents[1]
        / "src/franklinwh_direct_connect_bridge/templates/tabs/logs.html").read_text()


def _controls_row() -> str:
    start = LOGS.index("<!-- Controls -->")
    return LOGS[start:LOGS.index("Export", start)]


def test_the_row_stretches_its_controls_to_one_height():
    row = _controls_row()
    assert re.search(r'<div class="flex items-stretch gap-2 flex-wrap">', row)


def test_the_search_box_and_drop_downs_are_the_compact_size_like_the_buttons():
    row = _controls_row()
    fields = re.findall(r'<(?:input|select)[^>]*class="([^"]*)"', row)
    assert len(fields) == 4
    assert all("form-control-sm" in c for c in fields), fields
