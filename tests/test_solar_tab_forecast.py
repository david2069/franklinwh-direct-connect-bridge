"""Owner 2026-11-25: the Solar Forecast card on the Solar tab too, under the live metrics.
One card, one template: the dashboard and the Solar tab both use the same macro, and each
copy refreshes while its own tab is open."""
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "src/franklinwh_direct_connect_bridge"
T = PKG / "templates"


def test_both_tabs_use_the_one_card():
    dash = (T / "tabs/dashboard.html").read_text()
    solar = (T / "tabs/solar.html").read_text()
    part = (T / "partials/solar_forecast_card.html").read_text()
    assert "{% macro solar_forecast_card(" in part and "solarForecastCard('{{ tab }}')" in part
    assert "solar_forecast_card('dashboard'" in dash
    assert "solar_forecast_card('solar'" in solar
    assert 'x-data="solarForecastCard()"' not in dash        # not a second copy of the markup


def test_the_solar_tab_card_sits_under_the_live_metrics():
    solar = (T / "tabs/solar.html").read_text()
    assert solar.index("Generating now") < solar.index("solar_forecast_card('solar'") \
        < solar.index("Built-in AC PV")


def test_each_copy_refreshes_on_its_own_tab():
    js = (PKG / "static/js/solar_forecast_card.js").read_text()
    assert "function solarForecastCard(tab = 'dashboard')" in js
    assert "activeTab === 'dashboard'" not in js and "activeTab === tab" in js


def test_both_tabs_render(monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module
    html = TestClient(app_module.create_app()).get("/").text
    assert html.count("solarForecastCard('dashboard')") == 1
    assert html.count("solarForecastCard('solar')") == 1
