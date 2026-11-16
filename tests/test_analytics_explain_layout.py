"""Owner reports, 2026-11-15, on Analytics: the Explain dialog's "For a fuller answer" opens
the tariff page; its headings and sections read apart; a suggestion's number and words
agree; the History card shows the period in the chart; and a chart type that draws nothing
for a span is not offered (no empty SoC axis)."""
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import analytics_insights as ai
from franklinwh_direct_connect_bridge import app as app_module, state
from franklinwh_direct_connect_bridge import db as db_module
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = Path(app_module.__file__).parent
JS = (PKG / "static/js/analytics_tab.js").read_text()
HTML = (PKG / "templates/tabs/analytics.html").read_text()
GW = "gw-exl"


def _dialog():
    a = HTML.index('data-testid="explain-dialog"')
    return HTML[a:HTML.index("<!-- Colours", a)]


def _fn(name, n=1500):
    return JS[JS.index(name):][:n]


@pytest.fixture
def client(monkeypatch, tmp_path):
    state.register_gateway(GW, "10.0.0.1", "Home")
    monkeypatch.setattr(ai, "mode_and_reserve", lambda gw, host: ("self", 20))
    store = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(db_module, "get_store", lambda s: store)
    yield TestClient(app_module.create_app()), store
    state.unregister_gateway(GW)


# 1 — "For a fuller answer" opens Billing & Utilities → Plans & meters
def test_missing_tariff_opens_plans_and_meters(client):
    c, store = client
    end = (int(time.time()) // 3600 - 1) * 3600
    for i in range(120):
        store.insert({"soc": 60, "grid_w": 500, "solar_w": 1000, "battery_w": 200,
                      "load_w": 1700, "generator_w": 0, "mode": "Self"},
                     end - 2 * 3600 + i * 60, gateway_id=GW)
    b = c.get("/api/analytics/insights", params={"source": "local", "start": end - 7200,
                                                 "end": end, "gateway": GW}).json()
    tariff = next(m for m in b["missing"] if m["id"] == "tariff")
    assert tariff["open"] == {"tab": "energy_costs", "billing": "plans"}
    assert tariff["link"] == "Open Billing & Utilities (Plans & meters)"


def test_missing_items_have_a_button_like_the_suggestions():
    d = _dialog()
    sec = d[d.index('data-testid="explain-missing"'):]
    assert 'x-text="m.link"' in sec and "openMissing(m)" in sec
    fn = _fn("openMissing(m)", 500)
    assert "explainOpen = false" in fn and "fwh:open-setup-task" in fn and "open: m.open" in fn


# 2 — clear headings, sections apart, items with room
def test_section_headings_stand_out():
    d = _dialog()
    heads = re.findall(r'<h5 class="([^"]*)" style="([^"]*)"[^>]*>([^<]+)</h5>', d)
    assert [h[2] for h in heads] == ["Trends", "What it shows", "For your objectives",
                                     "For a fuller answer"]
    for cls, style, _ in heads:
        assert "text-xs" not in cls and "text-base" in cls and "font-semibold" in cls
        assert "var(--text-primary)" in style


def test_sections_are_divided_and_spaced():
    d = _dialog()
    for part in ("explain-findings", "explain-suggestions", "explain-missing"):
        at = d.index(f'data-testid="{part}"')
        tag = d[d.rindex("<section", 0, at):d.index(">", at)]
        assert "border-t" in tag and "pt-4" in tag, part
    assert 'class="space-y-1"' not in d and 'class="space-y-1.5"' not in d
    assert "leading-relaxed" in d


def test_x_show_with_style_uses_an_object():
    # a string :style on an x-show element overwrites x-show's display:none
    for tag in re.findall(r"<[a-z0-9]+[^>]*x-show=[^>]*>", _dialog()):
        m = re.search(r':style="([^"]*)"', tag)
        if m:
            assert m.group(1).lstrip().startswith("{"), tag


# 3 — a negative number never says "more"
def test_effect_says_less_or_more_from_the_grid():
    fn = _fn("explainEffect(e) {", 1000)
    assert "less from the grid" in fn and "more from the grid" in fn
    assert "'≈ −'" not in fn and "'≈ −$'" not in fn
    assert "saved" in fn and "more on the bill" in fn


# 4 — History shows the period in the chart, the whole span below it
def test_history_card_shows_the_period_in_view():
    fn = _fn("get historyCard() {", 1200)
    assert "value: this.shownRange" in fn
    assert "analyticsSpan(" in fn and "since" in fn
    rng = _fn("get shownRange() {", 1500)
    assert "formatRange" in rng and "lifetime" in rng and "cloudSince" in rng


# 5 — no empty SoC axis; a type that can't draw the span isn't offered
def test_no_empty_soc_axis():
    mount = _fn("FWHCloudAnalytics.mount(", 1100)
    assert "socAxis: 'always'" not in mount and "socAxis: 'auto'" in mount
    render = _fn("render() {", 6000)
    assert "const socShown" in render and "display: socShown" in render


def test_line_and_area_not_offered_for_lifetime():
    fn = _fn("chartBlocked(t) {", 500)
    assert "lifetime" in fn and "'line'" in fn and "'area'" in fn
    ct = _fn("get chartType() {", 300)
    assert "chartBlocked(" in ct
    for t in ("line", "area"):
        btn = HTML[HTML.index(f":aria-checked=\"chartType === '{t}'\"") - 200:][:900]
        # A reason ('' when offered) bound as is kept them disabled in every period: Alpine
        # drops a boolean attribute only for false, null or undefined, not ''.
        assert f":disabled=\"!!chartBlocked('{t}')\"" in btn and f"chartBlocked('{t}')" in btn
    assert "this._cloud.setStyle(this.cloudStyle)" in JS and "style: this.cloudStyle" in JS
