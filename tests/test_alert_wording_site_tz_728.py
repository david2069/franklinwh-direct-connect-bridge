"""#728 follow-up (owner 2026-11-18).

1. AGATE_ON_4G said "Wi-Fi has no internet". The aGate (1118) and the FranklinWH cloud only
   report which link is active: 4G active, Wi-Fi available on standby. The wording now says
   what is reported. Code, severity and behaviour are unchanged.
2. The bridge shows alert and Troubleshoot times in the site's zone without naming it, so a
   phone in another zone read 12:29 (site) as two hours old against its own 14:29. When the
   site's zone differs from the browser's, those times carry a small zone label; when they
   match nothing changes.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from franklinwh_direct_connect_bridge import alerts

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
APP_JS = (PKG / "static" / "js" / "app.js").read_text()
ALERTS_JS = (PKG / "static" / "js" / "alerts.js").read_text()
TS_JS = (PKG / "static" / "js" / "troubleshoot.js").read_text()

OVERCLAIM = ("no internet", "no route out")


def test_the_4g_alert_says_what_the_agate_reports():
    spec = alerts.CATALOGUE["AGATE_ON_4G"]
    assert spec["title"] == "aGate is using 4G — Wi-Fi is on standby"
    assert spec["severity"] == alerts.WARNING and spec["kind"] == alerts.CONDITION
    assert (spec["open_s"], spec["resolve_s"]) == (300, 120)


def test_the_4g_detail_and_verdict_do_not_claim_wifi_has_no_internet():
    src = (PKG / "troubleshoot.py").read_text()
    for phrase in OVERCLAIM:
        assert phrase not in src.lower(), phrase
    assert "aGate is using 4G — Wi-Fi is on standby." in src
    means = re.search(r"AGATE_ON_4G: \{\s*means: '([^']*)'", ALERTS_JS).group(1)
    for phrase in OVERCLAIM:
        assert phrase not in means.lower(), phrase


def test_one_shared_zone_tag_helper():
    assert re.search(r"\n    siteTzTag\(ts\) \{", APP_JS), "app store has siteTzTag(ts)"
    assert "siteTzShort" in APP_JS


def test_alert_and_troubleshoot_times_carry_the_tag():
    for fn in ("when", "short", "barText"):
        body = re.search(r"\n    " + fn + r"\(a\) \{.*?\n    \},", ALERTS_JS, re.S).group(0)
        assert "tzTag(" in body, fn
    assert re.search(r"\n    tzTag\(ts\) \{", ALERTS_JS)
    for getter in ("lanLine", "verdictSource"):
        body = re.search(r"\n    get " + getter + r"\(\) \{.*?\n    \},", TS_JS, re.S).group(0)
        assert "tzTag(" in body, getter


def _app_method(name):
    m = re.search(r"\n    " + name + r"\(ts\) \{\n(.*?)\n    \},", APP_JS, re.S)
    assert m, name
    return m.group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_tag_only_when_the_zones_differ():
    body = _app_method("siteTzTag")
    script = f"""
      process.env.TZ = 'Pacific/Auckland';
      const s = {{ siteTzOffsetMin: 660, siteTzShort: 'UTC+11', siteTzTag(ts) {{ {body} }} }};
      const ts = Date.UTC(2026, 10, 18, 1, 29) / 1000;
      const out = [s.siteTzTag(ts)];
      s.siteTzOffsetMin = 780; out.push(s.siteTzTag(ts));         // same as the browser
      s.siteTzOffsetMin = null; out.push(s.siteTzTag(ts));        // no site zone known
      console.log(JSON.stringify(out));
    """
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                    check=True, env={"TZ": "Pacific/Auckland"}).stdout)
    assert out == [" UTC+11", "", ""]
