"""#312: 1701 grid limits are in W; the Grid & Inverter tab shows and takes them in kW.

Owner's screenshot, 2026-10-24: with kwRatePower = gridSoftLimit = 2000 stored, the card
read "Grid import 2000 kW". The modal's "Custom kW" box also wrote its number unchanged,
so 2 would have set 2 W. And the modal still said the write is "CONFIRMED IGNORED", which
was true only with Debug Mode off on earlier firmware (#260).
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
JS = (ROOT / "static/js/grid_tab.js").read_text()
HTML = (ROOT / "templates/tabs/grid.html").read_text()


def test_outdated_ignored_claim_is_gone():
    assert "CONFIRMED IGNORED" not in HTML
    assert "silently ignores" not in HTML
    assert "not yet tested" in HTML                      # enforcement is still unknown


def test_modal_converts_kw_inputs_to_w_and_back():
    # Static guard for machines without node; the node test below runs the real code.
    assert "Math.round(Number(kw) * 1000)" in JS
    for f in ("grid_soft_limit", "kw_rate_power", "grid_hard_limit"):
        assert f"gl.{f} / 1000" in JS, f"{f} seeds the kW input without converting from W"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_display_and_write_convert_between_kw_and_w():
    script = JS + """
const t = gridTab();
t.grid = {grid_limits: {grid_soft_limit: 2000, kw_rate_power: 2500, grid_hard_limit: -1}};
t.openModal();
const seeded = [t.f.impKw, t.f.chgKw, t.f.expKw];
t.f.imp = 'custom'; t.f.impKw = 2; t.f.chg = 'custom'; t.f.chgKw = '1.5';
t.f.exp = 'on_custom'; t.f.expKw = 3;
console.log(JSON.stringify({
  card: [t.limit(2000), t.limit(2500), t.limit(-1)],
  seeded, payload: t._payload(),
  label: [t.limLabel(2000), t.limLabel(-1), t.limLabel(0), t.limLabel(true)],
}));
"""
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                    check=True).stdout)
    assert out["card"] == ["2 kW", "2.5 kW", "Unlimited"]
    assert out["seeded"] == [2, 2.5, 3]
    assert out["payload"] == {"grid_soft_limit": 2000, "kw_rate_power": 1500,
                              "export_enable": True, "grid_hard_limit": 3000}
    assert out["label"] == ["2 kW", "Unlimited", "0 (off)", "true"]
