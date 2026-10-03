"""Environment detection + metrics_active resolver (A1 + A6)."""

import pytest

from franklinwh_local_bridge import environment as env
from franklinwh_local_bridge.config import Settings, metrics_active


def test_metrics_explicit_wins_over_auto(monkeypatch):
    # Explicit True/False always beats the auto rule, regardless of runtime.
    monkeypatch.setattr(env, "IS_HA_ADDON", True)
    assert metrics_active(Settings(metrics_enabled=True, mqtt_enabled=True)) is True
    assert metrics_active(Settings(metrics_enabled=False, mqtt_enabled=True)) is False


def test_metrics_auto_addon_with_mqtt_off(monkeypatch):
    # Auto + add-on + MQTT on → OFF (HA recorder covers history via MQTT).
    monkeypatch.setattr(env, "IS_HA_ADDON", True)
    assert metrics_active(Settings(metrics_enabled=None, mqtt_enabled=True)) is False


def test_metrics_auto_addon_without_mqtt_on(monkeypatch):
    # Auto + add-on + MQTT off → ON (nothing else stores history).
    monkeypatch.setattr(env, "IS_HA_ADDON", True)
    assert metrics_active(Settings(metrics_enabled=None, mqtt_enabled=False)) is True


def test_metrics_auto_dev_always_on(monkeypatch):
    # Auto + not an add-on → ON even with MQTT (standalone has no HA recorder).
    monkeypatch.setattr(env, "IS_HA_ADDON", False)
    assert metrics_active(Settings(metrics_enabled=None, mqtt_enabled=True)) is True
    assert metrics_active(Settings(metrics_enabled=None, mqtt_enabled=False)) is True


@pytest.mark.real_data_dir
def test_runtime_is_dev_in_test_env():
    # Running from a checkout — no /data/options.json, no /.dockerenv.
    assert env.RUNTIME in ("dev", "docker", "ha_addon")
    assert env.DATA_DIR in ("/data", "./data")
