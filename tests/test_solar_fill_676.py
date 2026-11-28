"""#676 (owner 2026-11-16): the Solar Forecast card in the Energipays Bridge's layout, with
today's actual solar and the temperature (today's and the forecast) on the one chart, and a
warning, on the card and as a notification, when the solar left today won't fill the
battery to 100 %."""
import datetime as dt
import pathlib

import pytest

from franklinwh_direct_connect_bridge import notify_engine, solar_fill
from franklinwh_direct_connect_bridge.db import MetricsStore

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"
OFF = 11 * 3600                                   # AEDT


def fc(today_kw, tomorrow_kw=None):
    """A forecast like solar_forecast's: hourly kW for 2026-11-16 and 17, location-local."""
    hours = []
    for d, kws in (("2026-11-16", today_kw), ("2026-11-17", tomorrow_kw or [0] * 24)):
        for h, kw in enumerate(kws):
            hours.append({"time": f"{d}T{h:02d}:00", "kw": kw, "temp_c": 15 + h / 4})
    return {"hourly": hours, "utc_offset_seconds": OFF,
            "days": [{"date": "2026-11-16"}, {"date": "2026-11-17"}]}


def at(hh, mm=0):
    """Epoch seconds of 2026-11-16 hh:mm at the site (AEDT)."""
    return dt.datetime(2026, 11, 16, hh, mm, tzinfo=dt.timezone(dt.timedelta(seconds=OFF))).timestamp()


SUNNY = [0] * 6 + [0.5, 1, 2, 3, 4, 4, 4, 4, 3, 2, 1, 0.5] + [0] * 6     # 29 kWh


def test_what_is_left_today_against_what_the_battery_needs():
    a = solar_fill.assess(fc(SUNNY), soc=60, capacity_kwh=13.6, now_ts=at(12, 30))
    # 12:30: half of 12:00's 4 kW, then 13:00 to 17:00
    assert a["remaining_kwh"] == pytest.approx(2 + 4 + 3 + 2 + 1 + 0.5)
    assert a["needed_kwh"] == pytest.approx(5.44)
    assert a["will_fill"] is True and a["sun_left"] is True
    low = solar_fill.assess(fc(SUNNY), soc=20, capacity_kwh=13.6, now_ts=at(15))
    assert low["remaining_kwh"] == pytest.approx(3.5) and low["needed_kwh"] == pytest.approx(10.88)
    assert low["will_fill"] is False


def test_no_answer_without_a_capacity_or_soc_and_none_after_sunset():
    assert solar_fill.assess(fc(SUNNY), soc=50, capacity_kwh=None, now_ts=at(10))["needs"] == "battery capacity"
    assert solar_fill.assess(fc(SUNNY), soc=None, capacity_kwh=13.6, now_ts=at(10)) is None
    night = solar_fill.assess(fc(SUNNY), soc=20, capacity_kwh=13.6, now_ts=at(20))
    assert night["sun_left"] is False and night["remaining_kwh"] == 0


# ── the notification ─────────────────────────────────────────────────────────
@pytest.fixture
def st(tmp_path):
    s = MetricsStore(str(tmp_path / "m.db"))
    yield s
    s.close()


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(notify_engine, "fire", lambda store, ev, **kw: out.append((ev, kw)) or 1)
    return out


def test_it_notifies_once_a_day_while_solar_is_still_forecast(st, sent):
    f = fc(SUNNY)
    assert solar_fill.check(st, "gw1", "Home", f, soc=20, capacity_kwh=13.6, now_ts=at(15)) is True
    ev, kw = sent[0]
    assert ev == "solar_wont_fill" and kw["gateway"] == "Home"
    assert (kw["remaining"], kw["needed"], kw["soc"]) == ("3.5", "10.9", 20)
    assert solar_fill.check(st, "gw1", "Home", f, soc=19, capacity_kwh=13.6, now_ts=at(16)) is False
    assert len(sent) == 1                                        # once a day
    nxt = at(15) + 86400
    f2 = fc(SUNNY)
    for h in f2["hourly"]:
        h["time"] = h["time"].replace("2026-11-17", "2026-11-18").replace("2026-11-16", "2026-11-17")
    assert solar_fill.check(st, "gw1", "Home", f2, soc=20, capacity_kwh=13.6, now_ts=nxt) is True


def test_no_notification_when_it_will_fill_at_night_or_when_full(st, sent):
    f = fc(SUNNY)
    assert not solar_fill.check(st, "gw1", "Home", f, soc=90, capacity_kwh=13.6, now_ts=at(9))
    assert not solar_fill.check(st, "gw1", "Home", f, soc=20, capacity_kwh=13.6, now_ts=at(21))
    assert not solar_fill.check(st, "gw1", "Home", f, soc=100, capacity_kwh=13.6, now_ts=at(9))
    assert sent == []


def test_it_is_a_trigger_the_user_can_turn_off():
    assert notify_engine.DEFAULT_TRIGGERS["solar_wont_fill"]["enabled"] is True
    assert any(e.key == "solar_wont_fill" for e in notify_engine.EVENTS)


def test_the_poller_checks_it():
    src = (PKG / "poller.py").read_text()
    assert "solar_fill.check_gateway," in src


# ── the card ─────────────────────────────────────────────────────────────────
HTML = (PKG / "templates" / "partials" / "solar_forecast_card.html").read_text()   # both tabs
JS = (PKG / "static" / "js" / "solar_forecast_card.js").read_text()


def _card():
    a = HTML.index('x-data="solarForecastCard(')
    return HTML[a:HTML.index("{% endmacro %}", a)]


def test_the_card_has_actual_and_temp_on_one_chart_with_both_axes():
    card = _card()
    for tid in ("solar-toggle-actual", "solar-toggle-temp", "solar-axis-kw", "solar-axis-temp",
                "solar-line-actual", "solar-line-temp", "solar-now", "solar-tip", "solar-legend"):
        assert f'data-testid="{tid}"' in card, tid
    for kept in ("Actual so far", "battery charging", "← Today", "Tomorrow →", "Refresh"):
        assert kept in card, kept                                 # nothing taken away
    assert "solar_w" in JS and "temp_c" in JS


def test_the_card_warns_when_the_battery_wont_fill():
    card = _card()
    assert 'data-testid="solar-wont-fill"' in card and "fill.will_fill === false" in card
