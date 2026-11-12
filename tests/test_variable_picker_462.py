"""#462: a {x} variable picker beside every schedule text field that takes %sensor.id%.

`%battery.soc_pct%` is hard to remember (owner, 2026-11-04). Each field that the scheduler
substitutes values into — the Ask question, the notify title and message (the same fields
serve entry, exit and both), the raw service entity_id and data — gets a {x} button. It
opens one modal built from the condition picker's own sensor list (``pickerItems``), shows
each row's name, live value and small ``%id%`` code, and inserts ``%id%`` at the caret (or
the end), then puts focus back after it. On a phone the modal is a full-screen sheet.

These are static checks of the template and the tab's script, like the sensor-picker test.
"""
import re
from pathlib import Path

from franklinwh_direct_connect_bridge import scheduler

PKG = Path(scheduler.__file__).parent
HTML = (PKG / "templates/tabs/scheduler.html").read_text()
JS = (PKG / "static/js/scheduler_tab.js").read_text()


def _var_fields():
    """Every [data-var-field] wrapper: its target field and its {x} button."""
    return re.findall(r'<div\b[^>]*\bdata-var-field\b[^>]*>(.*?)</div>', HTML, re.S)


def _target_for(attr_text):
    for block in _var_fields():
        target = re.search(r"<(?:input|textarea)\b[^>]*\bdata-var-target\b[^>]*>", block, re.S)
        if target and attr_text in target.group(0):
            return block
    return None


def test_every_substituted_text_field_has_a_picker_button():
    # An Actionable notification's question is its row's message (#576)
    for field in ('x-model="ha.title"', 'x-model="ha.message"',
                  'x-model="ha.entity_id"', '@change="ha.data = $event.target.value"'):
        block = _target_for(field)
        assert block is not None, f"no {{x}} picker beside the field with {field}"
        assert 'data-testid="var-picker-btn"' in block and "openVarPicker($el)" in block
        # the caret is remembered when the field loses focus, before the modal opens
        assert re.search(r'@blur="noteCaret\(\$el\)"', block), field


def test_notify_fields_serve_entry_exit_and_both():
    # One notify block for every `when` (On entry / On exit / Entry & exit): no x-show on
    # ha.when hides the picker for an exit notify.
    notify = HTML[HTML.index("<!-- notify fields -->"):HTML.index("<!-- service GUIDED: domain-aware")]
    assert "ha.when" not in notify
    assert notify.count('data-testid="var-picker-btn"') == 2


def test_modal_uses_the_condition_pickers_catalogue_with_live_values():
    modal = HTML[HTML.index('data-testid="var-picker"'):]
    modal = modal[:modal.index("<!-- /var picker -->")]
    assert 'x-for="it in pickerItems(varPick.q)"' in modal       # same list, groups, labels
    assert 'x-model="varPick.q"' in modal                         # search box
    assert "insertVar(it.id)" in modal
    assert "'%' + it.id + '%'" in modal                           # the code, shown small
    assert "varLive(it.id)" in modal                              # the live value
    # phone: full-screen sheet; wider screens: a centred modal
    assert "w-full h-full sm:h-auto sm:max-w-md" in modal
    # Alpine 3.14.1: a string :style beside x-show undoes the hide (#459)
    for tag in re.findall(r"<(?:div|button|span)\b[^>]*>", modal):
        if "x-show=" in tag:
            style = re.search(r':style="([^"]*)"', tag)
            assert style is None or "{" in style.group(1), tag


def test_escape_closes_the_picker_not_the_editor():
    assert '@keydown.escape.window="varPick.open ? closeVarPicker() : closeForm()"' in HTML


def test_insert_goes_in_at_the_caret_and_updates_the_model():
    body = JS[JS.index("insertVar(id)"):]
    body = body[:body.index("\n    },")]
    assert "'%' + id + '%'" in body
    assert "selectionStart" in JS[JS.index("noteCaret(el)"):][:300]
    assert "dispatchEvent(new Event('input'" in body            # x-model hears it
    assert "setSelectionRange(pos, pos)" in body and ".focus()" in body
    assert "v.length" in body                                    # never focused: at the end


def test_live_values_come_from_the_existing_evaluate_endpoint():
    body = JS[JS.index("async loadVarLive()"):]
    body = body[:body.index("\n    },")]
    assert "api/schedules/evaluate" in body
