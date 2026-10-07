"""Connection-loss UI: banner + details modal must be served and wired.

Before this, app.js swallowed poll failures with a console.warn, so if the bridge
went away the UI silently served stale data with no indication. These are
render/wiring assertions — no JS runtime here — so they guard against the markup
or a store member being removed or renamed out from under the template.
"""

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module


@pytest.fixture(scope="module")
def client():
    return TestClient(app_module.create_app())


def test_index_renders_the_connection_banner(client):
    html = client.get("/").text
    assert "Connection Lost" in html
    assert "click for details" in html


def test_index_renders_the_details_modal(client):
    html = client.get("/").text
    for fragment in ("System Status", "Offline since", "Retry Now"):
        assert fragment in html, fragment


def test_modal_shows_attempt_and_countdown(client):
    """Without these the user cannot tell a stalled retry from a working one."""
    html = client.get("/").text
    assert "conn.attempt" in html
    assert "conn.nextRetryIn" in html


def test_modal_iterates_per_component_checks(client):
    html = client.get("/").text
    assert "conn.checks" in html


def test_template_only_calls_store_members_that_exist(client):
    """The template and store are edited separately — pin the contract."""
    html = client.get("/").text
    js = client.get("/static/js/app.js").text
    for member in ("retryNow", "dismissConnBanner", "connOfflineFor",
                   "connOfflineSinceLabel"):
        assert member in html, f"template no longer uses {member}"
        assert member in js, f"store no longer defines {member}"


def test_store_defines_the_connection_state_machine(client):
    js = client.get("/static/js/app.js").text
    for fn in ("_noteConnOk", "_noteConnFail", "_scheduleRetry", "_clearRetry"):
        assert fn in js, fn


def test_poll_loop_is_paused_while_offline(client):
    """Leaving the 5s loop running alongside the backoff timer would double-poll,
    inflate the attempt count and make the countdown wrong."""
    js = client.get("/static/js/app.js").text
    assert "_pausePoll" in js and "_resumePoll" in js
    assert "this._pausePoll()" in js      # actually called on going offline
    assert "this._resumePoll()" in js     # and on recovery


def test_poll_records_both_outcomes(client):
    js = client.get("/static/js/app.js").text
    assert "this._noteConnOk(d)" in js
    assert "this._noteConnFail(e)" in js
