"""The schedule editor's sensor picker: no blank rows under group headings.

Each picker row holds a heading and a sensor button, one of them hidden by ``x-show``. The
button's highlight was a *string* ``:style``, which Alpine applies with
``setAttribute('style', …)``: whenever the chosen sensor changed it wiped the
``display: none`` that ``x-show`` had set, so every heading row showed an empty button —
a blank row under "Ask before continuing", and "Automation Constants" looking empty
(owner, iPad, 2026-11-04). An object ``:style`` sets only its own properties."""
import re
from pathlib import Path

from franklinwh_direct_connect_bridge import scheduler

HTML = (Path(scheduler.__file__).parent / "templates/tabs/scheduler.html").read_text()


def _picker_blocks():
    blocks = re.findall(r'<template x-for="it in pickerItems\(q\)".*?</template>', HTML, re.S)
    assert len(blocks) >= 6
    return blocks


def test_a_hidden_picker_row_part_keeps_its_display_none():
    for block in _picker_blocks():
        for tag in re.findall(r"<(?:div|button)\b[^>]*>", block):
            if "x-show=" not in tag:
                continue
            style = re.search(r':style="([^"]*)"', tag)
            assert style is None or "{" in style.group(1), (
                "a string :style replaces the style attribute and undoes x-show: " + tag)


def test_the_chosen_sensor_is_still_highlighted():
    for block in _picker_blocks():
        assert "fontWeight: '600'" in block and "color: 'var(--accent)'" in block
