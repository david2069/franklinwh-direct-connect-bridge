"""#393: in Safari a <select class="form-control"> was shorter than the text and number
fields beside it. Safari draws a native pop-up menu that ignores vertical padding. The
select now drops the native look (appearance: none) and draws its own chevron, so it
takes the same padding as inputs, matching the Modbus Bridge."""
import pathlib
import re

CSS = (pathlib.Path(__file__).resolve().parents[1]
       / "src/franklinwh_direct_connect_bridge/static/css/design-system.css").read_text()


def _rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_select_form_control_drops_native_look():
    body = _rule("select.form-control:not([multiple]):not([size])")
    assert "-webkit-appearance: none" in body and re.search(r"(?<!-)appearance: none", body)
    assert "background-image: var(--select-chevron)" in body
    assert "padding-right" in body


def test_chevron_defined_for_both_themes():
    for theme in (':root, [data-theme="dark"]', '[data-theme="light"]'):
        assert "--select-chevron:" in _rule(theme), theme
