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
    def __init__(self, mock=False): self.is_mock = mock


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
    """A site that is already working must not be nagged, even if never formally 'done'."""
    s = w.summary(_Store(), **_kw(gateways=[_GW()],
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
