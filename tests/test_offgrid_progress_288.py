"""#288 (off-grid and reconnect): the dialog stays until the aGate confirms, refuses or
times out, and the result is shown inside it, not as a toast.

Checked in Chrome against a fake aGate that islands 5 s after the write: "done in 7 s";
a refused write shows "The aGate refused it: result 7."; reconnect "done in 6 s".
"""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
APP = (PKG / "static" / "js" / "app.js").read_text()
HTML = (PKG / "templates" / "index.html").read_text()


def set_offgrid():
    i = APP.index("async setOffgrid(on) {")
    return APP[i:APP.index("\n    },\n", i)]


def test_off_grid_and_reconnect_are_tracked_to_a_read_back():
    body = set_offgrid()
    assert "this.trackCommand({" in body
    assert "confirmed: () => on ? this.isOffGrid : !this.isOffGrid" in body


def test_their_result_is_in_the_dialog_not_a_toast():
    assert "this.toast(" not in set_offgrid()
    assert 'id="cmd-progress"' in HTML and 'data-role="result"' in HTML


def test_the_tracker_reports_refusal_and_a_time_limit():
    i = APP.index("async trackCommand(")
    body = APP[i:APP.index("closeCmdProgress()", i)]
    assert "The aGate refused it" in body
    assert re.search(r"limitS = \d+", body) and "No confirmation after" in body
    assert "await this.poll();" in body           # the read-back, not the write's reply
