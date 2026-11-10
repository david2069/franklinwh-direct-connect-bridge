"""Owner, 2026-11-10: hovering (or tapping) a Sankey flow shows what it carried, e.g.
"Solar → Battery 321.7 kWh". An SVG <title> alone never shows on a touch screen."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (SRC / "static" / "js" / "sankey.js").read_text()
CSS = (SRC / "static" / "css" / "design-system.css").read_text()


def test_a_flow_shows_its_label_on_hover_tap_and_focus():
    assert "sankey-tip" in JS
    for ev in ("pointerenter", "pointerdown", "focus", "pointerleave", "blur"):
        assert f"'{ev}'" in JS
    assert "`${a.src.label} → ${a.dst.label}`" in JS     # the flow's name, then its kWh


def test_the_label_floats_over_the_diagram_in_the_theme():
    assert ".sankey-tip {" in CSS and "var(--surface-1)" in CSS[CSS.index(".sankey-tip {"):][:400]
    assert ".sankey-svg.has-active .sankey-arc:not(.is-active)" in CSS   # other flows dim
