"""Solar disappears when there is none (owner, 2026-11-13): when the gateway's API reports
no AC PV ports and no remote solar, or System Setup says none (DC solar is set there).
Never on a guess: a gateway not read yet keeps Solar."""
import pathlib

import pytest

from franklinwh_direct_connect_bridge import system_setup

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (PKG / "static" / "js" / "app.js").read_text()


@pytest.mark.parametrize("vals,want", [
    ({"solar_type": "none", "_derived": {"solar_type": "none"}}, False),   # the API: none
    ({"solar_type": "ac", "_derived": {"solar_type": "ac"}}, True),
    ({"solar_type": "remote", "_derived": {"solar_type": "remote"}}, True),
    ({"solar_type": "dc", "_overridden": {"solar_type": True}, "_derived": {"solar_type": "none"}}, True),
    ({"solar_type": "none", "_overridden": {"solar_type": True}, "_derived": {}}, False),  # you: none
    ({"solar_type": "none", "_derived": {}}, None),                       # not read: unknown
])
def test_solar_installed(vals, want):
    assert system_setup.solar_installed(vals) is want


def test_the_ui_drops_solar_only_when_it_is_known_to_be_absent():
    assert "solarInstalled === false" in JS
    nav = JS[JS.index("get navAvailable()"):JS.index("navPrefs: [],")]
    assert "solar" in nav and "solarInstalled === false" in nav
    dash = (PKG / "templates" / "tabs" / "dashboard.html").read_text()
    i = dash.index('x-data="solarForecastCard()"')
    assert "$store.app.solarInstalled !== false" in dash[i:i + 300]
