"""#739: a notify added in the editor (addHa) lacked the fields a saved row gets from
_haToForm — actionable, choices, send_to, timeout_min, if_no_reply and data — so ticking
Actionable threw "Cannot read properties of undefined" (choices.length, send_to.to …)."""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


def _body(js, name):
    m = re.search(rf"^    {name}\(\) \{{\n(.*?)^    \}},", js, re.S | re.M)
    assert m, name
    return m.group(1)


def test_a_new_notify_has_the_same_fields_as_a_loaded_one():
    js = (PKG / "static" / "js" / "scheduler_tab.js").read_text()
    body = _body(js, "addHa")
    assert "actionable: false" in body
    assert "this._actionableToForm(null)" in body          # choices, send_to, timeout, no-reply
    assert re.search(r"data: ''", body)                     # as _haToForm gives a notify row
