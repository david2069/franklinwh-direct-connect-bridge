"""#337: the schedule form sizes to Default / Medium / Full, drags, and stays clear of the
phone's bottom nav; the notification message is a text box that grows as you type."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = (ROOT / "static/js/app.js").read_text()
HTML = (ROOT / "templates/tabs/scheduler.html").read_text()


def test_editor_uses_dialog_size():
    assert "Alpine.data('dialogSize'" in JS
    assert "x-data=\"dialogSize('fwh-dlg-schedule-edit')\"" in HTML
    assert "@click=\"setSize(sz[0])\"" in HTML


def test_never_taller_than_before():
    # Taller than 90dvh puts Create Entry under the bottom nav on a phone.
    assert "maxHeight: '90dvh'" in JS


def test_message_box_grows():
    i = HTML.index('x-model="ha.message"')
    tag = HTML[HTML.rindex("<", 0, i):HTML.index("</textarea>", i)]
    assert tag.startswith("<textarea") and "fitTextarea($el)" in tag
