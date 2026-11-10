"""#263: the Setup step reads the site's offset and location from a real aGate and offers the
matching zones; only a demo (mocks only) is simply asked; the Setup card can set it."""

import datetime as dt
from pathlib import Path
from types import SimpleNamespace

from franklinwh_direct_connect_bridge import setup_wizard as sw

JAN = dt.datetime(2026, 1, 15, tzinfo=dt.timezone.utc)      # southern-hemisphere summer


def test_zone_candidates_match_the_offset_now():
    c = sw.zone_candidates(11 * 60, JAN)
    assert "Australia/Sydney" in c and "Australia/Melbourne" in c
    assert "Australia/Brisbane" not in c                      # +10 all year: no DST
    assert all(sw.tz_offset_minutes(z, JAN) == 660 for z in c)
    assert sw.zone_candidates(None) == []


def _step(**kw):
    gws = [SimpleNamespace(id="real"), SimpleNamespace(id="mock")]
    return sw._timezone_step(None, gws, kw.pop("offsets"), **kw)


def test_a_real_aGate_is_read_and_its_zones_offered():
    st = _step(offsets={"real": 660, "mock": 780}, real_gateway_ids=["real"],
               gateway_location={"latitude": -1.0, "longitude": 2.0, "postcode": "0000"})
    assert st["satisfied"] is False
    assert "your aGate reports UTC+11:00" in st["detail"]
    assert st["read"]["offset_minutes"] == 660
    assert st["read"]["candidates"] == sw.zone_candidates(660)
    assert st["read"]["location"]["postcode"] == "0000"


def test_mocks_only_are_asked_with_nothing_read():
    st = _step(offsets={"mock": 780}, real_gateway_ids=[])
    assert st["read"] is None
    assert st["detail"].startswith("Not set — schedules need")


def test_the_setup_card_has_its_own_timezone_control():
    html = (Path(sw.__file__).parent / "templates/tabs/settings.html").read_text()
    block = html[html.index("st.id === 'timezone'"):html.index("st.id === 'profile'")]
    assert "saveSetupTimezone()" in block and "READ" in block and "st.read.candidates" in block
