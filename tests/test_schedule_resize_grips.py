"""Schedule conditions on an iPad (owner, 2026-11-04): the sensor field can be widened and
the sensor drop list resized with a finger, as in the Modbus Bridge scheduler.

Checked in Chrome at 820x1180 with touch events: a finger drag on the grip took the field
from 227 px to 452 px (every row's field follows), and on the list corner from 240x270 to
440x470, the list still open afterwards.
"""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
HTML = (PKG / "templates" / "tabs" / "scheduler.html").read_text()
JS = (PKG / "static" / "js" / "scheduler_tab.js").read_text()
CSS = (PKG / "static" / "css" / "design-system.css").read_text()


def conditions_html():
    """Entry conditions through End early when…, groups included; not the actions."""
    i = HTML.index("entry conditions (nestable")
    return HTML[i:HTML.index("No exit conditions", i)]


def method(name):
    i = JS.index(f"    {name}(")
    return JS[i:JS.index("\n    },\n", i)]


def test_every_condition_sensor_field_has_a_column_grip():
    sec = conditions_html()
    # entry row and exit row (groups use the same row markup)
    assert sec.count('data-testid="cond-grip"') == 2
    assert sec.count('@pointerdown.prevent.stop="startCondResize($event)"') == 2
    assert sec.count(':style="condSensorStyle()"') == 2


def test_every_sensor_and_lookup_list_has_a_corner_grip():
    sec = conditions_html()
    # sensor + Lookup, entry + exit
    assert sec.count('data-testid="sensor-list" :style="condListStyle()"') == 4
    assert sec.count(':style="condListScrollStyle()"') == 4
    assert sec.count('data-testid="list-grip" @pointerdown.prevent.stop="startListResize($event)"') == 4


def test_grips_take_a_finger():
    for cls in ("\n.cond-grip {", "\n.list-grip {"):
        i = CSS.index(cls)
        assert "touch-action: none" in CSS[i:CSS.index("}", i)]
    for name in ("startCondResize", "startListResize"):
        body = method(name)
        assert "addEventListener('pointermove'" in body and "removeEventListener('pointerup'" in body


def test_column_width_is_bounded_and_remembered():
    body = method("startCondResize")
    assert re.search(r"Math\.min\(maxW, Math\.max\(minW,", body)
    assert "localStorage.setItem('fwh-sched-cond-w'" in body
    assert "localStorage.getItem('fwh-sched-cond-w')" in JS
    # undragged: the field fills the row as before
    assert "flex: '1 1 0%'" in method("condSensorStyle")


def test_list_size_is_bounded_kept_open_and_remembered():
    body = method("startListResize")
    assert "closest('[x-data^=\"dialogSize\"]')" in body          # never past the dialog
    assert "Math.min(maxW, Math.max(minW," in body and "Math.min(maxH, Math.max(minH," in body
    assert "window.addEventListener('click', eat, { capture: true, once: true })" in body
    assert "localStorage.setItem('fwh-sched-list-size'" in body
    assert "localStorage.getItem('fwh-sched-list-size')" in JS
