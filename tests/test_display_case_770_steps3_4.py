"""#770 steps 3 and 4 (owner 2026-11-20): the UI says Standby for a battery that is neither
charging nor discharging (as HA's battery_status and the aGate's run status do), and the
VPP badge says "VPP Mode", as the FranklinWH app does."""
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
APP_JS = (PKG / "static" / "js" / "app.js").read_text()
BAT_JS = (PKG / "static" / "js" / "battery_tab.js").read_text()
DASH = (PKG / "templates" / "tabs" / "dashboard.html").read_text()
APP_PY = (PKG / "app.py").read_text()


def test_the_battery_word_is_standby():
    i = APP_JS.index("flowText(kind, w) {")
    fn = APP_JS[i:APP_JS.index("\n    },", i)]
    assert "kind === 'battery' ? 'Standby' : 'Idle'" in fn
    assert "flowText('battery', $store.app.power.battery_w) === 'Standby'" in DASH
    assert "'Idle'" not in BAT_JS
    run = APP_JS[APP_JS.index("if (w > 0) return 'Discharging';"):][:80]
    assert "return 'Standby';" in run


def test_the_vpp_badge_says_vpp_mode():
    assert '(gw.cloud_mode or "VPP Mode")' in APP_PY and '"VPP mode")' not in APP_PY
