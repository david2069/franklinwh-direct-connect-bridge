"""#293: while a dialog is open, its results show inside it, not in a toast behind it.

Owner, 2026-10-22: a toast shows behind the dialog where nobody is looking, and it fades.
So in each dialog handler a toast may only follow the statement that closes the dialog;
errors, validation and "not confirmed" outcomes go to the dialog's own message.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = ROOT / "static/js"
TPL = ROOT / "templates"

# (js file, handler, the statement that closes its dialog, the dialog's message, template)
DIALOGS = [
    ("scheduler_tab.js", "async confirmImport()", "this.importReport = null", "importMsg", "tabs/scheduler.html"),
    ("scheduler_tab.js", "async save()", "this.closeForm(true)", "formMsg", "tabs/scheduler.html"),
    ("scheduler_tab.js", "async testExit()", None, "formMsg", "tabs/scheduler.html"),
    ("scheduler_tab.js", "async testVerify()", None, "formMsg", "tabs/scheduler.html"),
    ("grid_tab.js", "async doPreview()", None, "modalMsg", "tabs/grid.html"),
    ("grid_tab.js", "async doWrite()", None, "modalMsg", "tabs/grid.html"),
    ("grid_tab.js", "async restore()", None, "modalMsg", "tabs/grid.html"),
    ("energy_costs_tab.js", "async doModbusFetch(dry)", "m.open = false", "modbusImport.msg", "tabs/energy_costs.html"),
    ("circuits_tab.js", "async saveSchedule()", "this.closeEditor()", "editMsg", "tabs/circuits.html"),
    ("generator_tab.js", "async save(url, body)", "this.closeEdit()", "editMsg", "tabs/generator.html"),
    ("generator_tab.js", "saveSoc()", None, "editMsg", "tabs/generator.html"),
    ("settings_tab.js", "async saveInstance()", "this.notif.addInst = null", "notif.instMsg", "tabs/settings.html"),
    ("settings_tab.js", "async sendBroadcast()", "this.notif.bc = null", "notif.bc?.msg", "tabs/settings.html"),
    ("ha_tab.js", "async saveInstance()", "this.closeForm()", "formMsg", "tabs/ha.html"),
    ("alerts.js", "async _ack(ids)", None, "$store.alerts.ackMsg", "partials/alerts.html"),
    ("app.js", "async applyCustomRange()", "this.histCustomOpen = false", "$store.app.histCustomMsg", "tabs/dashboard.html"),
]


def _body(src, sig):
    i = src.index("    " + sig)
    j = src.find("\n    },", i)
    return src[i:j]


@pytest.mark.parametrize("js,sig,close,msg,tpl", DIALOGS, ids=[f"{d[0]}:{d[1]}" for d in DIALOGS])
def test_no_toast_while_the_dialog_is_open(js, sig, close, msg, tpl):
    body = _body((JS / js).read_text(), sig)
    for m in re.finditer(r"toast\(", body):
        before = body[:m.start()]
        assert close and close in before, f"{sig} toasts before closing its dialog"
        # ...and on the same branch: the last close precedes it with no catch in between.
        tail = before[before.rindex(close):]
        assert "catch" not in tail and "else" not in tail, f"{sig} toasts on a branch that stays open"


@pytest.mark.parametrize("tpl,msg", sorted({(d[4], d[3]) for d in DIALOGS}))
def test_the_dialog_shows_its_message(tpl, msg):
    assert f"dialog_msg('{msg}')" in (TPL / tpl).read_text()
