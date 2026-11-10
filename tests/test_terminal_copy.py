"""The terminal has a Copy button that works without the async clipboard (plain-http ingress)."""

from pathlib import Path

from franklinwh_direct_connect_bridge import app as app_module

PKG = Path(app_module.__file__).parent


def test_terminal_has_a_copy_button():
    html = (PKG / "templates/partials/terminal.html").read_text()
    assert '@click="copyAll()"' in html


def test_copy_falls_back_when_the_clipboard_api_is_missing():
    js = (PKG / "static/js/terminal.js").read_text()
    body = js[js.index("async copyAll()"):js.index("// ── output helpers")]
    assert "window.isSecureContext" in body and "execCommand('copy')" in body
