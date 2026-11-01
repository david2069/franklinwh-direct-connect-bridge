"""#41 — schedules are evaluated on the SITE's clock, not the container's.

`docs/TIMEZONES.md` line 83: the rule ("charge at 2 PM") is gateway-zone wall-clock. The
scheduler used naive `datetime.now()`, which is the container's. Nothing caught it because
the standalone compose file mounts /etc/localtime, so the two clocks agreed and every test
agreed with itself.

Every test here therefore puts the two clocks DELIBERATELY APART. One where they match
would pass against the defect.
"""
import datetime as dt

import pytest

from franklinwh_direct_connect_bridge import client as client_mod
from franklinwh_direct_connect_bridge import scheduler as sch
from franklinwh_direct_connect_bridge import site_time
from franklinwh_direct_connect_bridge.db import MetricsStore


@pytest.fixture(autouse=True)
def _clear_offset_cache():
    site_time.reset_cache()
    yield
    site_time.reset_cache()


def _agate_at(offset_hours: float):
    """A time_location (1201) reading for a site `offset_hours` from UTC."""
    def _read(settings, name, host=None):
        assert name == "time_location"
        local = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(hours=offset_hours)
        return {"time": local.strftime("%Y-%m-%d %H:%M:%S"), "timezone": int(offset_hours),
                "timezoneStr": "", "DST": 0}
    return _read


# ── the offset itself ────────────────────────────────────────────────────────
def test_now_site_follows_the_agate_not_the_container(monkeypatch):
    monkeypatch.setattr(client_mod, "read", _agate_at(10))       # Sydney-ish
    now, off = site_time.now_site(settings=None)
    assert off == 600
    assert now.utcoffset() == dt.timedelta(hours=10)
    # and it really is 10h ahead of UTC, not merely labelled so
    drift = abs((now.replace(tzinfo=None) - (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                                             + dt.timedelta(hours=10))).total_seconds())
    assert drift < 5


def test_unreadable_gateway_is_not_reported_as_utc(monkeypatch):
    """None, never 0 — "could not ask" must stay distinguishable from "the site is at UTC"."""
    def _boom(settings, name, host=None):
        raise OSError("gateway unreachable")
    monkeypatch.setattr(client_mod, "read", _boom)
    assert site_time.offset_minutes(settings=None) is None
    now, off = site_time.now_site(settings=None)
    assert off is None and now.tzinfo is not None     # still aware, so .timestamp() is safe


def test_offset_is_cached_so_a_tick_does_not_re_read_the_gateway(monkeypatch):
    calls = []
    inner = _agate_at(10)

    def _counting(settings, name, host=None):
        calls.append(name)
        return inner(settings, name, host)

    monkeypatch.setattr(client_mod, "read", _counting)
    site_time.offset_minutes(settings=None)
    site_time.offset_minutes(settings=None)
    site_time.offset_minutes(settings=None)
    assert len(calls) == 1, "the scheduler would re-read 1201 on every tick"


# ── what it was actually getting wrong ───────────────────────────────────────
def test_tick_derives_the_site_clock_and_fires_on_it(tmp_path, monkeypatch):
    """End to end, through the path the poller actually uses.

    `now` is NOT passed: tick must derive it. The site is put at UTC-5 — a zone this host
    can never be in, which matters, because an earlier version of this test used UTC+10 and
    silently agreed with the host's own AEST offset. It passed against the defect.
    """
    SITE_OFFSET_H = -5
    st = MetricsStore(str(tmp_path / "t.db"))
    monkeypatch.setattr(sch, "ha_snapshot", lambda store: {})
    monkeypatch.setattr(client_mod, "read", _agate_at(SITE_OFFSET_H))

    site_now = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                + dt.timedelta(hours=SITE_OFFSET_H))
    container_now = dt.datetime.now()
    assert site_now.hour != container_now.hour, "fixture broken: the clocks must disagree"

    # A window that opened 10 minutes ago ON SITE and runs for an hour.
    fire_at = (site_now - dt.timedelta(minutes=10)).strftime("%H:%M")
    st.create_schedule(sid="s1", name="Site window",
                       spec={"gateway_id": "gw-h", "fire_at": fire_at, "duration_min": 60,
                             "conditions": [], "action": {}, "ha_actions": []})

    fired = sch.tick(settings=None, client=None, store=st, state={}, gateway_id="gw-h")
    assert [f["id"] for f in fired] == ["s1"], (
        f"site window {fire_at} (+60m) did not fire; the container clock reads "
        f"{container_now:%H:%M} and the site reads {site_now:%H:%M}"
    )


def test_tick_on_the_container_clock_would_miss_it(tmp_path, monkeypatch):
    """The other half: the same window must be invisible on the container's clock.

    Without this, the test above could pass for the wrong reason — a window wide enough to
    cover both clocks proves nothing.
    """
    SITE_OFFSET_H = -5
    st = MetricsStore(str(tmp_path / "t.db"))
    monkeypatch.setattr(sch, "ha_snapshot", lambda store: {})
    monkeypatch.setattr(client_mod, "read", _agate_at(SITE_OFFSET_H))

    site_now = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                + dt.timedelta(hours=SITE_OFFSET_H))
    fire_at = (site_now - dt.timedelta(minutes=10)).strftime("%H:%M")
    st.create_schedule(sid="s1", name="Site window",
                       spec={"fire_at": fire_at, "duration_min": 60,
                             "conditions": [], "action": {}, "ha_actions": []})

    assert sch.tick(settings=None, client=None, store=st, state={}, gateway_id=None,
                    now=dt.datetime.now().astimezone()) == []


def test_window_end_epoch_is_not_shifted_by_the_offset():
    """The trap: a dozen `.timestamp()` calls on datetimes derived from `now`.

    If `now` carried site wall-clock while staying naive, every one of them would resolve
    against the CONTAINER's zone and the window-close epochs would move by the offset —
    trading a visible bug for a quieter one. UTC-5 again, so the host can never match it.
    """
    tz = dt.timezone(dt.timedelta(hours=-5))
    now = dt.datetime(2026, 9, 15, 19, 0, tzinfo=tz)
    entry = {"trigger_type": "daily", "fire_at": "18:00", "duration_min": 90}

    state, _key, end_ts, _d = sch.window_now(entry, now)
    assert state == "inside"
    # 19:30 at UTC-5 == 00:30 UTC the next day
    closes = dt.datetime.fromtimestamp(end_ts, dt.timezone.utc)
    assert (closes.hour, closes.minute) == (0, 30), f"window closes at {closes:%H:%M} UTC"


# ── a wrong clock is not a timezone ──────────────────────────────────────────
# Measured 2026-10-15 on the demo stack: a mock gateway answered 1202 from the emulator's
# canned fallback, whose `time` is the reference capture's date. The derived offset was
# -571 days, `dt.timezone()` refused it, and EVERY scheduler tick died with
# "offset must be a timedelta strictly between -timedelta(hours=24) and timedelta(hours=24)".
def test_a_stale_clock_does_not_become_an_offset(monkeypatch):
    def _stale(settings, name, host=None):
        return {"time": "2025-03-24 01:15:51", "timezone": 10, "timezoneStr": ""}
    monkeypatch.setattr(client_mod, "read", _stale)
    # It falls back to the gateway's own base offset rather than inventing one from a
    # clock that is plainly wrong.
    assert site_time.offset_minutes(settings=None) == 600


def test_an_impossible_offset_is_refused_outright(monkeypatch):
    def _nonsense(settings, name, host=None):
        return {"time": "2025-03-24 01:15:51", "timezone": 400}
    monkeypatch.setattr(client_mod, "read", _nonsense)
    # No real place is UTC+400. None means "could not be established", which the caller
    # already knows how to handle — unlike a number that blows up on use.
    assert site_time.offset_minutes(settings=None) is None


def test_now_site_survives_a_wrong_gateway_clock(monkeypatch):
    def _stale(settings, name, host=None):
        return {"time": "2025-03-24 01:15:51", "timezone": 999}
    monkeypatch.setattr(client_mod, "read", _stale)
    now, off = site_time.now_site(settings=None)      # must not raise
    assert off is None
    assert now.utcoffset() is not None                # still aware, as the contract says


def test_the_edges_of_the_real_range_are_kept(monkeypatch):
    # UTC+14 (Kiritimati) and UTC-12 (Baker Island) exist; the guard must not clip them.
    for hours, want in ((14, 840), (-12, -720)):
        site_time.reset_cache()
        monkeypatch.setattr(client_mod, "read", _agate_at(hours))
        assert site_time.offset_minutes(settings=None) == want
