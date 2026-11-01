"""#161 — next fire, the timeline and Test use the schedule's gateway's SITE clock, the clock
the tick fires on, not the container's. Every test puts the two clocks apart on purpose."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client as client_module
from franklinwh_direct_connect_bridge import site_time, state

_CONTAINER = dt.datetime.now().astimezone().utcoffset() // dt.timedelta(minutes=1)
SITE_OFF = 14 * 60 if _CONTAINER != 14 * 60 else -12 * 60          # never the container's
OTHER_OFF = -12 * 60 if SITE_OFF != -12 * 60 else 13 * 60


@pytest.fixture
def c(monkeypatch):
    site_time.reset_cache()
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "first")
    state.register_gateway("g2", "192.0.2.11", "second")
    site_time._last.update({"192.0.2.10": SITE_OFF, "192.0.2.11": OTHER_OFF})
    monkeypatch.setattr(client_module, "writes_enabled", lambda s: True)
    yield TestClient(app_module.create_app())
    state.reset_gateways()
    site_time.reset_cache()


def _site_now(off):
    return dt.datetime.now(dt.timezone(dt.timedelta(minutes=off)))


def _expected_next(off, hhmm="18:00"):
    now = _site_now(off)
    h, m = map(int, hhmm.split(":"))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return (t if t + dt.timedelta(minutes=60) > now else t + dt.timedelta(days=1)).timestamp()


def test_next_fire_is_on_the_site_clock_of_the_schedules_gateway(c):
    # Every schedule names its gateway (#379), and next fire is on that gateway's clock.
    r = c.post("/api/schedules", json={"name": "on g1", "fire_at": "18:00", "duration_min": 60,
                                       "gateway_id": "g1"})
    assert r.status_code == 201
    c.post("/api/schedules", json={"name": "on g2", "fire_at": "18:00", "duration_min": 60,
                                   "gateway_id": "g2"})
    by = {s["name"]: s for s in c.get("/api/schedules").json()["schedules"]}
    assert by["on g1"]["next_fire"] == _expected_next(SITE_OFF)
    assert by["on g2"]["next_fire"] == _expected_next(OTHER_OFF)


def test_timeline_and_test_use_the_site_clock(c, monkeypatch):
    from franklinwh_direct_connect_bridge import scheduler, system_setup
    # Test reads the gateway's ratings and setup; these hosts are documentation addresses,
    # so answer locally rather than wait on a connection that never comes.
    monkeypatch.setattr(scheduler, "ratings_snapshot", lambda host: {})
    monkeypatch.setattr(system_setup, "snapshot", lambda *a, **k: {})
    now = _site_now(SITE_OFF)
    assert abs(c.get("/api/schedules/timeline?gateway=g1").json()["now_min"]
               - (now.hour * 60 + now.minute)) <= 1
    start = (now - dt.timedelta(minutes=5)).strftime("%H:%M")
    sid = c.post("/api/schedules", json={"name": "open now", "fire_at": start,
                                         "duration_min": 30, "gateway_id": "g1"}).json()["id"]
    assert c.post(f"/api/schedules/{sid}/test?gateway=g1").json()["window"] == "inside"


def test_an_unreadable_site_clock_keeps_the_last_known_offset(monkeypatch):
    site_time.reset_cache()
    site_time._last["h"] = SITE_OFF

    def _boom(settings, name, host=None):
        raise OSError("gateway unreachable")
    monkeypatch.setattr(client_module, "read", _boom)
    now, off = site_time.now_site(None, "h")
    assert off == SITE_OFF and now.utcoffset() == dt.timedelta(minutes=SITE_OFF)
    site_time.reset_cache()
