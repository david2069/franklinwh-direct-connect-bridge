"""Billing → Plans & meters worked out "today" in UTC: in the Australian morning a plan
starting today showed as future and the meter said "No tariff in force". The plan list
now uses the site's date (the aGate's offset, as Analytics), like the server's billing."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

JS = (pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
      / "static" / "js" / "settings_tab.js").read_text()


def _method(name):
    m = re.search(r"\n    " + name + r"\(\) \{\n(.*?)\n    \},", JS, re.S)
    assert m, name
    return m.group(1)


def test_plan_dates_use_the_site_day_not_utc():
    for fn in ("tariffStatus", "tariffRetired", "supersedeTariff"):
        body = re.search(r"\n    (?:async )?" + fn + r"\(.*?\n    \},", JS, re.S).group(0)
        assert "toISOString().slice(0, 10)" not in body, fn
        assert "this._siteToday()" in body, fn


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_site_today_at_7am_sydney_is_the_local_date():
    body = _method("_siteToday")
    script = f"""
      const RealDate = Date;
      const NOW = RealDate.UTC(2026, 10, 17, 20, 0, 0);          // 07:00 on the 18th in Sydney
      global.Date = class extends RealDate {{ constructor(...a) {{ super(...(a.length ? a : [NOW])); }}
                                             static now() {{ return NOW; }} }};
      const c = {{ $store: {{ app: {{ siteTzOffsetMin: 660 }} }}, _siteToday() {{ {body} }} }};
      const out = [c._siteToday()];
      c.$store.app.siteTzOffsetMin = -300;                         // US Eastern: still the 17th
      out.push(c._siteToday());
      console.log(JSON.stringify(out));
    """
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                    check=True).stdout)
    assert out == ["2026-11-18", "2026-11-17"]
