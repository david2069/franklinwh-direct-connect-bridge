"""#540 — Local history: how long it is kept (90 days / 1 year / 2 years / Forever) and
switching it off from Settings, with an explicit env value still winning."""
import time

import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module
from franklinwh_direct_connect_bridge import config, db as db_module, environment
from franklinwh_direct_connect_bridge.db import MetricsStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    monkeypatch.delenv("METRICS_RETENTION_DAYS", raising=False)
    config._settings = None
    db_module.reset_store()
    yield tmp_path
    config._settings = None
    db_module.reset_store()


def _c():
    return TestClient(app_module.create_app())


def test_info_says_what_is_kept_and_what_is_locked(env):
    info = _c().get("/api/metrics/info").json()
    assert info["enabled"] is True and info["retention_days"] == 365
    assert info["retention_choices"] == [90, 365, 730, 0]          # 0 = forever
    assert info["locked"] == {"enabled": False, "retention_days": False}
    assert "db_bytes" in info and {"recent_mb_day", "older_mb_day"} <= set(info["growth"])


def test_retention_choice_applies_now_and_survives_a_restart(env):
    c = _c()
    r = c.put("/api/metrics/settings", json={"retention_days": 730})
    assert r.status_code == 200 and r.json()["retention_days"] == 730
    assert config.get_settings().metrics_retention_days == 730
    config._settings = None                                         # a restart
    assert config.get_settings().metrics_retention_days == 730


def test_only_the_offered_choices_are_accepted(env):
    assert _c().put("/api/metrics/settings", json={"retention_days": 12}).status_code == 422


def test_an_explicit_env_value_wins_and_is_locked(env, monkeypatch):
    config.save_override("metrics_retention_days", 90)             # from an earlier choice
    monkeypatch.setenv("METRICS_RETENTION_DAYS", "200")
    config._settings = None
    assert config.get_settings().metrics_retention_days == 200
    c = _c()
    assert c.get("/api/metrics/info").json()["locked"]["retention_days"] is True
    assert c.put("/api/metrics/settings", json={"retention_days": 730}).status_code == 409


def test_forever_never_deletes_old_samples(env):
    store = MetricsStore(str(env / "m.db"))
    old = int(time.time()) - 900 * 86400
    store.insert({"soc": 50, "grid_w": 0, "solar_w": 0, "battery_w": 0, "load_w": 1,
                  "generator_w": 0, "mode": "Self"}, old, gateway_id="g")
    assert store.prune(0, int(time.time())) == 0
    assert store.first_ts("g") == old
    assert store.prune(365, int(time.time())) == 1


def test_switching_off_stops_recording_and_on_starts_it_again(env):
    c = _c()
    r = c.put("/api/metrics/settings", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert config.metrics_active(config.get_settings()) is False
    config._settings = None
    assert config.metrics_active(config.get_settings()) is False   # kept across a restart
    assert c.put("/api/metrics/settings", json={"enabled": True}).json()["enabled"] is True


def test_metrics_enabled_from_env_is_locked(env, monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    config._settings = None
    c = _c()
    assert c.get("/api/metrics/info").json()["locked"]["enabled"] is True
    assert c.put("/api/metrics/settings", json={"enabled": False}).status_code == 409


def test_settings_card_offers_the_choice_confirms_off_and_explains_the_overlap():
    from pathlib import Path
    root = Path(app_module.__file__).parent
    html = (root / "templates" / "tabs" / "settings.html").read_text()
    js = (root / "static" / "js" / "settings_tab.js").read_text()
    card = html[html.index("<!-- ══ Metrics / history ══ -->"):][:6000]
    for label in ("90 days", "1 year", "2 years", "Forever"):
        assert label in card
    assert "history.confirmOff" in card and "Turn off" in card            # asks first
    assert "Dashboard power history, Analytics and Energy Costs" in card
    assert "recorder" in card and "history.info.is_ha_addon" in card      # the add-on overlap
    assert "dialog_msg('history.msg')" in card                            # result in the card
    assert "api/metrics/settings" in js and "api/metrics/info" in js
    # the stale add-on caption is gone (#136 made history on by default everywhere)
    assert "off in the add-on because Home Assistant stores history" not in js
