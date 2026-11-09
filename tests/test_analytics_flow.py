"""#543 (owner, 2026-11-09/10): the Energy Flow Sankey in Analytics, as a fourth chart type
(Line | Area | Bars | Flow) beside the time span, for Local (this bridge's samples, an
estimate) and Cloud (the cloud's own breakdown), with the period's totals as the export."""
import time
from pathlib import Path

from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, db, state

SRC = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
JS = (SRC / "static" / "js" / "analytics_tab.js").read_text()
HTML = (SRC / "templates" / "tabs" / "analytics.html").read_text()
TOP = HTML[:HTML.index('x-ref="cloud"')]


def test_flow_is_a_fourth_chart_type_in_the_top_row():
    seg = TOP[TOP.index('aria-label="Chart style"'):][:1500]
    assert "setChartType('flow')" in seg and ">Flow<" in seg
    assert "['line', 'area', 'bars', 'flow']" in JS               # remembered like the others


def test_the_flow_card_replaces_both_charts_and_steps_like_them():
    card = HTML[HTML.index("<!-- Flow (#543)"):HTML.index("x-show=\"source === 'local' && chartType !== 'flow'\"")]
    assert "chartType === 'flow'" in card                           # dates: the shared picker above
    assert "x-show=\"source === 'cloud' && chartType !== 'flow'\"" in HTML
    assert "x-show=\"source === 'local' && chartType !== 'flow'\"" in HTML
    assert "flowNote" in card                                       # says where the flows come from


def test_flows_come_from_this_bridge_or_the_cloud():
    body = JS[JS.index("async loadFlow("):][:2500]
    assert "api/energy/flow?start=" in body                          # Local: the estimate
    assert "api/analytics/cloud?period=" in body and ".flows" in body   # Cloud: metered
    assert "FWHSankey.render(" in JS and "height: 380" in JS[JS.index("drawFlow() {"):][:400]
    assert "if (this.chartType === 'flow') return this.loadFlow(" in JS


def test_export_in_flow_is_the_periods_totals():
    assert "if (this.chartType === 'flow') return this.exportFlow(fmt);" in JS
    assert "fwh-flow-" in JS[JS.index("exportFlow(fmt) {"):][:600]


def test_the_local_flow_endpoint_takes_a_lifetime_and_says_where_history_starts(monkeypatch):
    monkeypatch.setattr(db, "get_store", lambda *a, **k: None)
    monkeypatch.setitem(state._gateways, "gw-fl", state.GatewayState(
        id="gw-fl", label="Home", configured_host="10.0.0.3", active_host="10.0.0.3"))
    c = TestClient(app_module.create_app())
    now = int(time.time())
    r = c.get(f"/api/energy/flow?start={now - 800 * 86400}&end={now}&gateway=gw-fl")
    assert r.status_code == 200 and "first_ts" in r.json()
