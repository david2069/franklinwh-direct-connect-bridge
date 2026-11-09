"""#543 (owner, 2026-11-09/10): the Dashboard's Energy Flow card says where its data comes
from. Signed in to the cloud: Cloud data and a cloud icon. Not signed in: Local data, a
slashed cloud and "Local · N days of data", without pushing Cloud. A link opens the same
period in Analytics → Flow, and Week/Month/Year show the period's first day, not the
anchor day."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
DASH = (SRC / "templates" / "tabs" / "dashboard.html").read_text()
CARD = DASH[DASH.index('x-data="energyFlowCard()"'):][:9000]
JS = (SRC / "static" / "js" / "energy_flow_card.js").read_text()
TAB = (SRC / "static" / "js" / "analytics_tab.js").read_text()


def test_the_card_shows_its_source_with_a_cloud_or_slashed_cloud():
    assert "source === 'cloud'" in CARD and 'aria-label="Cloud data"' in CARD
    assert 'aria-label="Local data; cloud not set up"' in CARD
    assert "localDays" in CARD and "Local ·" in CARD


def test_cloud_data_when_signed_in_from_the_clouds_own_breakdown():
    assert "$store.app.cloudAvailable" in JS
    assert "$watch('$store.app.cloudAvailable'" in JS              # known only after the caps arrive
    body = JS[JS.index("async load() {"):][:2500]
    assert "api/analytics/cloud?period=" in body and ".flows" in body
    assert "day: 'day5'" in JS                                   # the card's Day is Cloud's day
    assert "first_ts" in body                                    # Local: how many days stored


def test_a_link_opens_the_period_in_analytics_flow():
    assert "openInAnalytics()" in CARD
    assert "fwh-analytics-flow" in JS and "fwh-analytics-flow" in TAB


def test_week_month_and_year_show_the_periods_first_day():
    assert 'x-model="day"' not in CARD and ':value="startDay"' in CARD
