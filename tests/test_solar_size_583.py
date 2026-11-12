"""Solar size (#583): derived from the gateways by default, the user's number when they set
one (larger for a DC array or remote solar; smaller allowed, with a note). With neither,
nothing is assumed: no 5.0 kWp forecast, the field asks to confirm."""
import pathlib
from types import SimpleNamespace

import pytest

from franklinwh_direct_connect_bridge import config, pv_size, scheduler, state, system_setup

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "franklinwh_direct_connect_bridge"


@pytest.fixture(autouse=True)
def _gws(monkeypatch):
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "House")
    state.register_gateway("g2", "192.0.2.11", "Shed")
    sizes = {"192.0.2.10": 6.6, "192.0.2.11": 3.0}
    monkeypatch.setattr(system_setup, "reported_solar_kwp", lambda host: sizes.get(host))
    monkeypatch.setattr(system_setup, "values", lambda *a, **k: pytest.fail(
        "the tick never reads the gateway for the size"))
    yield sizes
    state.reset_gateways()


def test_no_default_size():
    assert config.Settings.model_fields["pv_kwp"].default is None


def test_derived_is_the_sum_of_the_gateways():
    assert pv_size.effective(SimpleNamespace(pv_kwp=None)) == {
        "kwp": 9.6, "source": "gateway", "derived": 9.6}


def test_the_users_number_wins():
    assert pv_size.effective(SimpleNamespace(pv_kwp=12.0)) == {
        "kwp": 12.0, "source": "you", "derived": 9.6}


def test_neither_is_none(_gws):
    _gws.clear()
    assert pv_size.effective(SimpleNamespace(pv_kwp=None)) == {
        "kwp": None, "source": None, "derived": None}


def test_the_forecast_uses_the_effective_size(monkeypatch):
    from franklinwh_direct_connect_bridge import solar_forecast
    got = []
    monkeypatch.setattr(solar_forecast, "forecast", lambda lat, lon, **k: got.append(k["kwp"]) or {})
    monkeypatch.setattr(solar_forecast, "sensors", lambda fc: {"solar_forecast.x": 1})
    s = SimpleNamespace(pv_latitude=-33.8, pv_longitude=151.2, pv_kwp=None, pv_tilt=20, pv_azimuth=0)
    assert scheduler.solar_snapshot(s) == {"solar_forecast.x": 1} and got == [9.6]


def test_no_size_no_forecast(monkeypatch, _gws):
    from franklinwh_direct_connect_bridge import solar_forecast
    _gws.clear()
    monkeypatch.setattr(solar_forecast, "forecast", lambda *a, **k: pytest.fail("no size, no forecast"))
    s = SimpleNamespace(pv_latitude=-33.8, pv_longitude=151.2, pv_kwp=None, pv_tilt=20, pv_azimuth=0)
    assert scheduler.solar_snapshot(s) == {}


def test_the_field_shows_both_and_asks_to_confirm():
    html = (PKG / "templates" / "tabs" / "settings.html").read_text()
    block = html[html.index('data-testid="pv-size"'):html.index("Tilt°")]
    for s in ('data-testid="pv-size"', "Use gateway", "Please confirm", "data-testid=\"pv-size-smaller\""):
        assert s in block, s
