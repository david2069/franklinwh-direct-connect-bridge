"""#302: an aGate answer with no network fields is "not reported", not off / no / down.

Seen with the library Emulator, which answers 1113/1118 with no fields: the tab showed
every link as off, every interface as Enabled no / Link down, and Write safety as
"single link". Absence is not evidence; Write safety must be "unknown" then.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = (ROOT / "static/js/network_tab.js").read_text()
HTML = (ROOT / "templates/tabs/network.html").read_text()


def test_interface_cells_and_write_safety_have_a_not_reported_state():
    assert "yesNo(r.enabled, 'yes', 'no')" in HTML
    assert "yesNo(r.link, 'up', 'down')" in HTML
    assert "r.reported ? 'off' : 'not reported'" in HTML
    assert "!diag.reported ? 'unknown'" in HTML
    assert "'not reported'" in JS


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_empty_answer_reads_not_reported_and_real_values_are_unchanged():
    script = JS + """
const t = networkTab(), view = () => ({links: t.links.map(l => l.state),
  rows: t.diag.rows.map(r => [t.yesNo(r.enabled, 'yes', 'no'), t.yesNo(r.link, 'up', 'down')]),
  reported: t.diag.reported, redundant: t.diag.redundant});
t.net = {connectivity: {opt: 0, result: 0}, interfaces: {}, switches: {opt: 0, result: 0}};
const empty = view();
t.net = {connectivity: {wifiConnectRouterStatus: 0, EthConnectRouterStatus: 1, '4GConnectBSStatus': 0},
         interfaces: {eth0: {ip: '10.0.0.5'}},
         switches: {wifiNetSwitch: 0, ethernet0NetSwitch: 1, ethernet1NetSwitch: 0, '4GNetSwitch': 1}};
console.log(JSON.stringify({empty, real: view()}));
"""
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                    check=True).stdout)
    nr = "not reported"
    assert out["empty"] == {"links": [nr] * 3, "rows": [[nr, nr]] * 4,
                            "reported": False, "redundant": False}
    assert out["real"]["links"] == ["off", "active", "available"]
    assert out["real"]["rows"] == [["yes", "up"], ["no", "up"], ["no", "down"], ["yes", "down"]]
    assert out["real"]["reported"] is True
