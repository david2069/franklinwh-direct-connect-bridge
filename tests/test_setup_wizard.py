"""FEAT-SETUP-WIZARD — first-run setup, and re-configuration later.

The behaviours here are the ones the backlog entry argues for, so they are pinned rather
than left to be re-litigated: derive first, stay correctable, be re-runnable, and never
conflate "this site does not have it" with "you may not use it".
"""
import pytest

from franklinwh_direct_connect_bridge import setup_wizard as w


class _Store:
    def __init__(self, cfg=None): self.cfg = dict(cfg or {})
    def get_config(self, k, default=None): return self.cfg.get(k, default)
    def set_config(self, k, v): self.cfg[k] = v


def _kw(**over):
    base = dict(gateways=[], profile_values={}, ha_configured=False,
                notifications_configured=False, tariff_configured=False,
                apowers_found=None)
    base.update(over)
    return base


class _GW:
    def __init__(self, mock=False, gw_id=""):
        self.is_mock = mock
        self.id = gw_id


# --- state ---------------------------------------------------------------------------------

def test_never_run_is_pending():
    assert w.state(_Store()) == "pending"


def test_unknown_stored_state_falls_back_to_pending():
    """A corrupt value must not lock the wizard into a state nobody can name."""
    assert w.state(_Store({w.STATE_KEY: "banana"})) == "pending"


def test_state_round_trips():
    s = _Store()
    w.set_state(s, "done")
    assert w.state(s) == "done"


def test_bad_state_is_refused():
    with pytest.raises(ValueError):
        w.set_state(_Store(), "finished")


# --- prompting -----------------------------------------------------------------------------

def test_prompts_when_nothing_is_set_up():
    assert w.summary(_Store(), **_kw())["should_prompt"] is True


def test_does_not_prompt_once_required_steps_are_satisfied():
    """A site that is already working must not be nagged, even if never formally 'done'.

    "Working" now includes the site timezone: a bridge that does not know where the site
    is cannot run a schedule on the site's clock, so it is not yet set up.
    """
    s = w.summary(_Store({w.SITE_TZ_KEY: "Australia/Sydney"}),
                  **_kw(gateways=[_GW()],
                        profile_values={"solar_kwp": 6.6, "_derived": {"solar_kwp": 6.6}}))
    assert s["required_satisfied"] is True and s["should_prompt"] is False


def test_skipping_stops_the_prompt_without_completing():
    s = _Store(); w.set_state(s, "skipped")
    out = w.summary(s, **_kw())
    assert out["should_prompt"] is False and out["complete"] is False


def test_a_mock_gateway_does_not_satisfy_the_gateway_step():
    """A demo gateway is not a configured site; counting it would skip real setup."""
    s = w.summary(_Store(), **_kw(gateways=[_GW(mock=True)]))
    step = next(x for x in s["steps"] if x["id"] == "gateway")
    assert step["satisfied"] is False


# --- re-runnable ----------------------------------------------------------------------------

def test_every_step_reports_whether_it_is_already_satisfied():
    """Re-configuration is the harder case: a second pass must show current state."""
    s = w.summary(_Store({w.STATE_KEY: "done"}),
                  **_kw(gateways=[_GW()], ha_configured=True, tariff_configured=True))
    by = {x["id"]: x for x in s["steps"]}
    assert by["home_assistant"]["satisfied"] is True
    assert by["billing"]["satisfied"] is True
    assert by["notifications"]["satisfied"] is False


def test_optional_steps_are_skippable_and_say_so():
    """A wizard that implies everything is mandatory is why people abandon them."""
    s = w.summary(_Store(), **_kw())
    for step in s["steps"]:
        if step["id"] in w.OPTIONAL_STEPS:
            assert step["skippable"] is True and step["required"] is False
            assert "later" in step["note"].lower()


# --- derived vs overridden -------------------------------------------------------------------

def test_derived_fields_are_distinguished_from_defaults():
    """A default must never be presented as something the gateway reported."""
    s = w.summary(_Store(), **_kw(profile_values={
        "solar_kwp": 6.6, "battery_label": "FranklinWH",
        "_derived": {"solar_kwp": 6.6}, "_overridden": {"solar_kwp": False}}))
    step = next(x for x in s["steps"] if x["id"] == "profile")
    assert step["derived"] == ["solar_kwp"]
    assert "battery_label" in step["values"] and "battery_label" not in step["derived"]


def test_overrides_are_reported_so_they_can_be_contradicted():
    s = w.summary(_Store(), **_kw(profile_values={
        "solar_kwp": 9.9, "_derived": {"solar_kwp": 6.6},
        "_overridden": {"solar_kwp": True, "generator_input": False}}))
    step = next(x for x in s["steps"] if x["id"] == "profile")
    assert step["overridden"] == ["solar_kwp"]


# --- capability gating ------------------------------------------------------------------------

def test_no_solar_hides_the_solar_tab():
    assert w.capability_tabs({}, generator_installed=False)["solar"] is False


def test_solar_present_shows_it():
    assert w.capability_tabs({"solar_kwp": 6.6}, generator_installed=True)["solar"] is True


def test_generator_follows_the_device_not_only_the_profile():
    """The existing rule — the tab is hidden when there is no generator — generalised."""
    assert w.capability_tabs({}, generator_installed=True)["generator"] is True
    assert w.capability_tabs({"generator_input": True}, generator_installed=False)["generator"] is True


def test_capability_gating_says_nothing_about_permission():
    """Capability and permission are different mechanisms (FEAT-USERS-RBAC) and must not
    be conflated: one says 'you do not have this', the other 'you may not use this'."""
    tabs = w.capability_tabs({"solar_kwp": 6.6}, generator_installed=False)
    assert set(tabs) == {"generator", "solar", "circuits"}
    assert all(isinstance(v, bool) for v in tabs.values())


# --- declared hardware counts ----------------------------------------------------------------

def test_counts_default_to_one_each():
    """Before anything is discovered there is nothing to derive from, so this is asked —
    and one of each is the overwhelmingly common install."""
    assert w.expected(_Store()) == {"agates": 1, "apowers": 1}


def test_counts_round_trip():
    s = _Store()
    w.set_expected(s, agates=2, apowers=5)
    assert w.expected(s) == {"agates": 2, "apowers": 5}


def test_one_count_can_be_set_without_disturbing_the_other():
    s = _Store()
    w.set_expected(s, apowers=3)
    assert w.expected(s) == {"agates": 1, "apowers": 3}


@pytest.mark.parametrize("bad", [0, -1, 999, "2", 1.5, True])
def test_out_of_range_is_refused_not_clamped(bad):
    """Storing something other than what was typed is how a wrong number survives."""
    with pytest.raises(ValueError):
        w.set_expected(_Store(), agates=bad)


def test_corrupt_stored_count_falls_back_to_the_default():
    assert w.expected(_Store({w.EXPECTED_AGATES_KEY: "lots"}))["agates"] == 1


def test_step_compares_declared_against_found():
    """'1 gateway configured' looks finished. '1 of 2' does not — that is the whole point."""
    s = _Store()
    w.set_expected(s, agates=2, apowers=4)
    out = w.summary(s, **_kw(gateways=[_GW()], apowers_found=1))
    step = next(x for x in out["steps"] if x["id"] == "expected")
    assert step["satisfied"] is False
    assert "1 of 2" in step["detail"] and "1 of 4" in step["detail"]


def test_step_is_satisfied_when_everything_declared_is_present():
    s = _Store()
    out = w.summary(s, **_kw(gateways=[_GW()], apowers_found=1))
    step = next(x for x in out["steps"] if x["id"] == "expected")
    assert step["satisfied"] is True


def test_finding_more_than_declared_is_not_incomplete():
    """A low declaration is a wrong declaration, not unfinished setup."""
    s = _Store()
    out = w.summary(s, **_kw(gateways=[_GW(), _GW()], apowers_found=3))
    step = next(x for x in out["steps"] if x["id"] == "expected")
    assert step["satisfied"] is True


def test_unknown_apower_count_does_not_block():
    """An unreadable gateway means unknown, and unknown must not read as missing."""
    s = _Store()
    out = w.summary(s, **_kw(gateways=[_GW()], apowers_found=None))
    step = next(x for x in out["steps"] if x["id"] == "expected")
    assert step["satisfied"] is True
    assert "aPower" not in step["detail"]


# --- the wizard's gateway payloads --------------------------------------------------------
#
# These are text assertions on the controller, which is weak — but the defect they pin was
# real and silent: the wizard posted `mock: true` where the roster field is `is_mock`, so
# "Explore with a mock gateway" created a REAL gateway with no host. It sat Offline for ever
# and looked like a broken mock rather than a wrong key.

def _wizard_js():
    from pathlib import Path
    return (Path(__file__).resolve().parents[1]
            / "src/franklinwh_direct_connect_bridge/static/js/setup_wizard.js").read_text()


def test_mock_creation_uses_the_roster_field_name():
    js = _wizard_js()
    assert "is_mock: true" in js
    # the wrong key, as an object property — not the substring inside `is_mock`
    assert "\n            mock: true" not in js and "{ mock: true" not in js


def test_real_gateway_creation_sends_host_and_port():
    """A gateway row with no port never connects; the Discover path in Settings sends both."""
    js = _wizard_js()
    assert "port: 9000" in js
    assert js.count("enabled: true") >= 2


def test_mock_gets_the_declared_apower_count():
    """The owner says how many aPowers they have; the mock should match that shape."""
    assert "mock_units" in _wizard_js()


def test_both_doors_ask_how_much_hardware():
    """Choosing the mock used to skip the question entirely — it routed straight to the
    demo step — so the counts were never asked of anyone exploring with a mock."""
    html = (__import__("pathlib").Path(__file__).resolve().parents[1]
            / "src/franklinwh_direct_connect_bridge/templates/partials/setup_wizard.html").read_text()
    intent = html[html.index("step === 'intent'"):html.index("step === 'hardware'")]
    # every door that leads onward goes to 'hardware' first; only "set it up myself" skips
    assert intent.count("go('hardware')") == 2
    assert "go('demo')" not in intent and "go('find')" not in intent


# --- site timezone -------------------------------------------------------------------------
# One zone for the whole site. Nothing on the local channel supplies one: the aGate reports
# an OFFSET and leaves `timezoneStr` empty, and an offset cannot distinguish UTC+10 standard
# from a UTC+10 daylight zone, which is the difference a schedule lives or dies by.

def test_timezone_is_unset_until_asked():
    assert w.site_timezone(_Store()) == ""
    step = next(s for s in w.steps(store=_Store(), **_kw()) if s["id"] == "timezone")
    assert step["required"] is True and step["satisfied"] is False


def test_setting_a_real_zone_sticks():
    st = _Store()
    assert w.set_site_timezone(st, "Australia/Sydney") == "Australia/Sydney"
    assert st.cfg[w.SITE_TZ_KEY] == "Australia/Sydney"
    assert w.site_timezone(st) == "Australia/Sydney"


def test_an_unknown_zone_is_refused_not_coerced():
    """Storing something unusable is how a schedule silently runs on the wrong clock."""
    st = _Store()
    with pytest.raises(ValueError):
        w.set_site_timezone(st, "Mars/Olympus_Mons")
    assert w.SITE_TZ_KEY not in st.cfg


def test_a_stored_junk_zone_reads_as_unset():
    assert w.site_timezone(_Store({w.SITE_TZ_KEY: "Mars/Olympus_Mons"})) == ""


def test_offset_is_derived_live_including_dst():
    import datetime as dt
    # Sydney is UTC+11 in January (daylight) and UTC+10 in July. A stored offset would be
    # wrong for half the year, which is why only the NAME is stored.
    jan = dt.datetime(2026, 1, 15, tzinfo=dt.timezone.utc)
    jul = dt.datetime(2026, 7, 15, tzinfo=dt.timezone.utc)
    assert w.tz_offset_minutes("Australia/Sydney", jan) == 660
    assert w.tz_offset_minutes("Australia/Sydney", jul) == 600
    assert w.tz_offset_minutes("Mars/Olympus_Mons") is None


def test_half_hour_zone_is_not_rounded():
    import datetime as dt
    assert w.tz_offset_minutes("Australia/Adelaide",
                               dt.datetime(2026, 7, 15, tzinfo=dt.timezone.utc)) == 570


def test_a_gateway_in_another_zone_is_named_not_hidden():
    """There is no verified write for the aGate's clock, so a mismatch is REPORTED."""
    st = _Store({w.SITE_TZ_KEY: "UTC"})
    gws = [_GW(gw_id="a"), _GW(gw_id="b")]
    step = next(s for s in w.steps(store=st, **_kw(gateways=gws,
                                                   gateway_offsets={"a": 0, "b": 600}))
                if s["id"] == "timezone")
    assert step["satisfied"] is False
    assert step["mismatched"] == ["b"]


def test_a_gateway_that_could_not_be_read_is_not_a_mismatch():
    """"Did not answer" must not look like "disagrees"."""
    st = _Store({w.SITE_TZ_KEY: "UTC"})
    gws = [_GW(gw_id="a"), _GW(gw_id="b")]
    step = next(s for s in w.steps(store=st, **_kw(gateways=gws, gateway_offsets={"a": 0}))
                if s["id"] == "timezone")
    assert step["satisfied"] is True and step["mismatched"] == []


def test_timezone_is_required_for_completion():
    st = _Store()
    s = w.summary(st, **_kw(gateways=[_GW(gw_id="a")]))
    assert s["required_satisfied"] is False
    assert any(x["id"] == "timezone" and not x["satisfied"] for x in s["steps"])


# --- the modal controller, after the 2026-10-15 demo run -------------------------------------
# Reported: "I asked for 3 aGates and 2 apowers got this" — two mocks, both called
# "Mock aGate", and the dashboard sitting on Site · All Gateways where the per-gateway tabs
# error against an empty host.

def test_mock_creation_loops_over_the_declared_agate_count():
    js = _wizard_js()
    body = js[js.index("async createMock()"):js.index("async loadProfile()")]
    assert "counts.agates" in body
    assert "for (" in body                       # N gateways, not one
    assert "mock_units" in body and "counts.apowers" in body


def test_multiple_mocks_are_numbered():
    """Several gateways all called "Mock aGate" cannot be told apart in the switcher."""
    body = _wizard_js()
    body = body[body.index("async createMock()"):body.index("async loadProfile()")]
    assert "${base} ${i}" in body


def test_finishing_selects_a_real_gateway():
    """Site mode has no host, so Battery/Device/Grid error there — never land on it."""
    js = _wizard_js()
    assert "_selectFirstGateway" in js
    assert "selectGateway" in js and "__site__" in js


def test_timezone_is_asked_before_any_gateway_is_created():
    """A mock created first would be born on the seeded clock and need restarting."""
    js = _wizard_js()
    assert "api/setup/timezone" in js
    # the counts step routes to the timezone step, which then routes to find/demo
    counts = js[js.index("async saveCounts()"):js.index("async saveTimezone()")]
    assert "this.go('timezone')" in counts
    tz = js[js.index("async saveTimezone()"):js.index("async scan()")]
    assert "demo" in tz and "find" in tz


def test_mocks_are_named_but_never_counted_as_agates():
    """A mock satisfying "find your hardware" would report a site that does not exist."""
    st = _Store({w.EXPECTED_AGATES_KEY: "3"})
    step = next(s for s in w.steps(store=st, **_kw(gateways=[_GW(mock=True, gw_id="m1"),
                                                             _GW(mock=True, gw_id="m2")]))
                if s["id"] == "expected")
    assert step["found"]["agates"] == 0 and step["found"]["mocks"] == 2
    assert "2 mock gateway(s)" in step["detail"]
    assert step["satisfied"] is False
