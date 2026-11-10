"""Alpine 3.14.1 applies a STRING :style by rewriting the whole style attribute, which
wipes the display:none that x-show sets on the same element, so a hidden element shows
again once the binding updates (#459: blank rows in the sensor picker). Every element
that has x-show must bind :style as an object."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
TAG = re.compile(r"<[a-zA-Z][^<>]*?>", re.S)
ATTR = re.compile(r'(?<![\w-]):style="([^"]*)"')
LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'")


def _css_text(expr: str) -> bool:
    """A quoted string literal holding 'prop:value' means the binding builds CSS text."""
    return any(":" in s for s in LITERAL.findall(expr))


def _offenders():
    for f in sorted((PKG / "templates").rglob("*.html")):
        text = f.read_text()
        for m in TAG.finditer(text):
            tag = m.group(0)
            if "x-show=" not in tag:
                continue
            for style in ATTR.findall(tag):
                if _css_text(style):
                    line = text.count("\n", 0, m.start()) + 1
                    yield f"{f.relative_to(PKG)}:{line}: {style[:70]}"


def test_no_x_show_element_binds_a_string_style():
    assert list(_offenders()) == []


def test_the_check_catches_a_string_style():
    assert _css_text("ok ? 'color:var(--ok)' : 'color:var(--danger)'")
    assert _css_text("'color:' + c")
    assert not _css_text("ok ? { color: 'var(--ok)' } : { color: 'var(--danger)' }")
