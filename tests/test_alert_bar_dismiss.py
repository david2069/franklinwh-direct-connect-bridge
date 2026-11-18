"""The alert bar (#727): an acknowledged condition that is still active kept a bar under
the top bar with no way to close it, its text cut off on a phone, naming the gateway by
its raw id. Dismiss hides it until the condition clears; a new occurrence (a new alert)
shows again."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import alerts, app as app_module, config, db

PKG = Path(app_module.__file__).parent
JS = (PKG / "static/js/alerts.js").read_text()
INDEX = (PKG / "templates/index.html").read_text()
PARTIAL = (PKG / "templates/partials/alerts.html").read_text()


@pytest.fixture
def api():
    alerts.reset()
    store = db.get_store(config.get_settings())
    yield TestClient(app_module.create_app()), store
    alerts.reset()


def _on_4g(st, now=300.0):
    alerts.set_condition("gw1", "AGATE_ON_4G", True, now=0.0)
    return alerts.evaluate(st, now=now)[0]["id"]


def test_dismiss_records_it_for_everyone_and_keeps_the_condition_open(api):
    c, st = api
    a = _on_4g(st)
    c.post(f"/api/alerts/{a}/ack", json={"source": "ui"})
    r = c.post(f"/api/alerts/{a}/dismiss", json={"source": "ui"})
    assert r.status_code == 200
    row = r.json()
    assert row["dismissed_ts"] and row["dismissed_by"] == "source:ui"
    # still open and still listed: dismissing hides the bar, it does not resolve anything
    assert [x["id"] for x in c.get("/api/alerts?open=1").json()["alerts"]] == [a]
    assert c.post("/api/alerts/999/dismiss", json={"source": "ui"}).status_code == 404
    assert c.post(f"/api/alerts/{a}/dismiss", json={"source": "user:x"}).status_code == 400


def test_dismiss_also_acknowledges(api):
    c, st = api
    a = _on_4g(st)
    row = c.post(f"/api/alerts/{a}/dismiss", json={"source": "ui"}).json()
    assert row["acked_ts"] and row["acked_by"] == "source:ui"


def test_a_new_occurrence_is_not_dismissed(api):
    c, st = api
    a = _on_4g(st)
    c.post(f"/api/alerts/{a}/dismiss", json={"source": "ui"})
    alerts.set_condition("gw1", "AGATE_ON_4G", False, now=400.0)
    alerts.evaluate(st, now=600.0)                          # resolved
    alerts.set_condition("gw1", "AGATE_ON_4G", True, now=700.0)
    b = alerts.evaluate(st, now=1100.0)[0]["id"]
    assert b != a and st.alert(b)["dismissed_ts"] is None


def test_the_bar_leaves_out_dismissed_alerts_and_has_a_dismiss_button():
    acked = JS[JS.index("get activeAcked()"):JS.index("get openConditions()")]
    assert "!a.dismissed_ts" in acked
    bar = INDEX[INDEX.index("$store.alerts.activeAcked"):INDEX.index("── Content")]
    assert 'data-testid="alert-bar-dismiss"' in bar
    assert "@click.stop=\"$store.alerts.dismiss(a.id)\"" in bar
    assert "api/alerts/${id}/dismiss" in JS


def test_the_bar_wraps_its_full_text():
    bar = INDEX[INDEX.index("$store.alerts.activeAcked"):INDEX.index("── Content")]
    assert "truncate" not in bar


def test_the_list_can_dismiss_an_active_condition():
    assert 'data-testid="alert-dismiss"' in PARTIAL
    assert "$store.alerts.canDismiss(a)" in PARTIAL


def test_user_text_names_the_gateway_not_its_id():
    bar_text = JS[JS.index("barText(a)"):JS.index("recoveryText(a)")]
    assert "this.gwName(a.gateway_id)" in bar_text and "a.gateway_id})" not in bar_text
    assert "gwName(id)" in JS and "g.label || g.host" in JS     # as the gateway picker
    assert "$store.alerts.gwName(a.gateway_id)" in PARTIAL      # the modal's heading
