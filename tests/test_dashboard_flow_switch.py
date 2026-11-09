"""Owner, 2026-11-10: the Dashboard's Energy Flow card gets Analytics' Local | Cloud switch,
one choice shared with Analytics (Cloud when signed in, until one is picked; greyed out with
a sign-in hint when not), and Analytics' styled date picker instead of the browser's date box
and the repeated "November 2026" chip. One calendar serves both (partials/calendar.html,
fwh_calendar.js)."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
DASH = (SRC / "templates" / "tabs" / "dashboard.html").read_text()
CARD = DASH[DASH.index('x-data="energyFlowCard()"'):][:9000]
JS = (SRC / "static" / "js" / "energy_flow_card.js").read_text()
TAB = (SRC / "static" / "js" / "analytics_tab.js").read_text()
ATAB = (SRC / "templates" / "tabs" / "analytics.html").read_text()
CAL = (SRC / "templates" / "partials" / "calendar.html").read_text()
CALJS = (SRC / "static" / "js" / "fwh_calendar.js").read_text()
INDEX = (SRC / "templates" / "index.html").read_text()


def test_the_card_has_a_local_cloud_switch():
    assert 'role="tablist" aria-label="Source"' in CARD
    assert "setSource('local')" in CARD and "setSource('cloud')" in CARD
    assert ':disabled="!$store.app.cloudAvailable"' in CARD
    assert "Sign in to the FranklinWH cloud" in CARD


def test_one_choice_shared_with_analytics():
    assert "'fwh-analytics-source'" in JS
    assert "fwh-source" in JS and "fwh-source" in TAB             # each tells the other
    body = JS[JS.index("get wanted()"):][:400]
    assert "$store.app.cloudAvailable" in body                   # Cloud until one is picked


def test_a_cloud_that_fails_says_so_and_shows_local():
    body = JS[JS.index("async load() {"):][:3000]
    assert "cloudErr" in body and "this.source = 'local'" in body
    assert "cloudErr" in CARD


def test_the_styled_calendar_replaces_the_date_box_and_chip():
    assert 'type="date"' not in CARD and "spanLabel" not in CARD
    assert '{% include "partials/calendar.html" %}' in CARD and '{% include "partials/calendar.html" %}' in ATAB
    assert 'aria-label="Pick a date"' in CARD and "periodLabel" in CARD
    for f in ("FWHCalendar.days(", "FWHCalendar.months(", "FWHCalendar.years("):
        assert f in JS and f in TAB
    assert "window.FWHCalendar" in CALJS and "fwh_calendar.js" in INDEX
    assert "pickerDays" in CAL and "pickerMonths" in CAL and "pickerYears" in CAL
