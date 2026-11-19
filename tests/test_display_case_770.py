"""#770 step 1: values shown to people use Sentence case from one helper,
``$store.app.sentence(v)``; machine values (keys, API, MQTT) are unchanged. Applied to the
raw lower-case chips: scheduler log status and monitor state, alert severity and state,
health level, and the network link state."""
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
T = PKG / "templates"
APP_JS = (PKG / "static" / "js" / "app.js").read_text()


def test_one_helper():
    body = APP_JS.split("    sentence(v) {", 1)[1].split("\n    },", 1)[0]
    assert "toUpperCase()" in body and "slice(1)" in body
    assert "toLowerCase" not in body          # TOU, VPP and SoC keep their capitals


def _t(rel):
    return (T / rel).read_text()


def test_the_chips_use_it_and_keep_their_keys():
    sch = _t("tabs/scheduler.html")
    assert 'x-text="$store.app.sentence(l.state)"' in sch and 'monStateStyle(l.state)' in sch
    assert 'x-text="$store.app.sentence(e.status)"' in sch and 'statusStyle(e.status)' in sch
    al = _t("partials/alerts.html")
    assert 'x-text="$store.app.sentence(a.severity)"' in al
    assert 'x-text="$store.app.sentence($store.alerts.state(a))"' in al
    assert 'x-text="$store.app.sentence(cur.level)"' in _t("tabs/health.html")
    assert "$store.app.sentence(l.state)" in _t("tabs/network.html")
