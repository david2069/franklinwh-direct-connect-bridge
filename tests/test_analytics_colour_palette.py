"""Owner, 2026-11-10 (iPad): "cant exit once colour modal opens - no close icon or
exit/confirm buttons after selecting". The browser's own colour picker (input type=color)
covered the dialog on iPadOS. Each series now opens a styled palette inside the dialog, with
a hex field, and the dialog ends in Done."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (SRC / "static" / "js" / "analytics_tab.js").read_text()
HTML = (SRC / "templates" / "tabs" / "analytics.html").read_text()
DLG = HTML[HTML.index('aria-label="Chart colours"'):]


def test_no_browser_colour_picker():
    assert 'type="color"' not in HTML


def test_each_series_opens_a_palette_and_a_hex_field_in_the_dialog():
    assert "colourEdit" in DLG and "colourPalette" in DLG
    assert 'role="group" :aria-label="\'Colours for \' + r[1]"' in DLG
    assert "setColourHex(" in DLG and 'inputmode="text"' in DLG
    pal = JS[JS.index("const ANALYTICS_PALETTE"):][:600]
    assert pal.count("'#") >= 20
    body = JS[JS.index("setColourHex("):][:300]
    assert "/^#[0-9a-f]{6}$/i" in body


def test_the_dialog_ends_in_done_and_keeps_its_close():
    assert '>Done</button>' in DLG and 'aria-label="Close"' in DLG
