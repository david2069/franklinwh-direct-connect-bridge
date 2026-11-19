"""#154: docker-compose.yml starts with no aGate (the setup wizard opens), MQTT is off
until it is configured, and its build command is the one INSTALL.md gives."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.yml").read_text()
INSTALL = (ROOT / "INSTALL.md").read_text()


def _env(name):
    for line in COMPOSE.splitlines():
        s = line.strip()
        if s.startswith(f"- {name}="):
            return s[len(f"- {name}="):]
    raise AssertionError(name)


def test_no_placeholder_agate_host():
    assert _env("FWH_HOST") == "${FWH_HOST:-}"


def test_mqtt_is_off_until_configured_and_not_the_dev_broker():
    assert _env("MQTT_ENABLED") == "${MQTT_ENABLED:-false}"
    assert "1884" not in COMPOSE and _env("MQTT_PORT") == "${MQTT_PORT:-1883}"


def test_one_build_command():
    cmd = "docker build -t franklinwh-direct-connect-bridge:dev ."
    assert cmd in INSTALL and cmd in COMPOSE
    assert "build_image.sh" not in COMPOSE
