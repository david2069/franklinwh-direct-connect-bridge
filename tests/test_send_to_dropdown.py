"""Send to → Chosen devices is one multi-select drop-down everywhere (owner, iPad, 2026-11-04)."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
MACRO = PKG / "templates/partials/device_multiselect.html"


def test_the_drop_down_opens_from_one_field_and_closes_on_outside_tap_or_escape():
    m = MACRO.read_text()
    assert "{% macro device_multiselect(" in m and "{{ caller() }}" in m
    assert 'data-testid="device-multiselect"' in m and ':aria-expanded="msOpen"' in m
    assert '@click.outside="msOpen = false"' in m
    assert "@keydown.escape.stop" in m                      # never closes the dialog behind it
    assert "Choose devices" in m                            # nothing ticked yet
    assert "max-sm:static" in m                             # a phone opens it in place, above the bottom nav


def _calls(html: str) -> int:
    return len(re.findall(r"\{% call device_multiselect\(", html))


def test_every_send_to_picker_uses_it():
    sch = (PKG / "templates/tabs/scheduler.html").read_text()
    box = sch[sch.index('data-testid="ask-send-to"'):sch.index("<!-- entry conditions")]
    assert _calls(box) == 1
    st = (PKG / "templates/tabs/settings.html").read_text()
    for start, end in (('data-testid="trigger-target-devices"', "</template>\n      <!-- Notifications with buttons"),
                       ('data-testid="ask-targets"', 'data-testid="triggers-save-error"'),
                       ('data-testid="notify-test-dialog"', "<!-- Broadcast modal -->")):
        assert _calls(st[st.index(start):st.index(end)]) == 1, start
    for page in ("scheduler", "settings"):
        html = (PKG / f"templates/tabs/{page}.html").read_text()
        assert '{% from "partials/device_multiselect.html" import device_multiselect %}' in html
