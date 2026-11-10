"""#327: Copy must work over plain http (HA ingress), where navigator.clipboard is absent,
and must say "Copied" only when it was. The store's copyText() falls back to execCommand,
as ha_tab.js copyDash() and terminal.js copyAll() already do."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
APP = (ROOT / "static/js/app.js").read_text()
SETTINGS = (ROOT / "static/js/settings_tab.js").read_text()
DEVICE = (ROOT / "static/js/device_tab.js").read_text()


def _body(js, name):
    i = js.index(name)
    return js[i:js.index("\n    },", i)]


def test_store_copy_has_an_http_fallback():
    body = _body(APP, "async copyText(text)")
    assert "window.isSecureContext" in body and "execCommand('copy')" in body


def test_support_copy_uses_it_and_reports_failure():
    body = _body(SETTINGS, "async copySupport()")
    assert "copyText(" in body and "navigator.clipboard" not in body
    assert "blocked" in body                          # the reason, next to the button


def test_console_copy_says_copied_only_when_it_was():
    body = _body(DEVICE, "async conCopy()")
    assert "copyText(" in body and "toast(" not in body
