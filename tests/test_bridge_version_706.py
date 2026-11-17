"""#706 — a "Bridge Version" entity on the bridge's own Home Assistant device: the
version as its state; platform, install type, integrations and the FranklinWH / shared
library versions as attributes. No PII."""
import json
import pathlib
import tomllib

from franklinwh_direct_connect_bridge import __version__, alerts, install_identity, state
from franklinwh_direct_connect_bridge.publish import entities

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _S:
    mqtt_enabled = True
    mqtt_prefix = "franklinwh"
    ha_discovery_prefix = "homeassistant"
    fwh_cloud_email = "someone@example.com"
    fwh_cloud_password = "secret-pw"
    fwh_cloud_gateway = "10060006A02F99999999"
    mqtt_username = ""


class _Store:
    def ha_instances(self):
        return [{"id": "a", "enabled": True, "base_url": "http://192.0.2.5:8123", "token": "tok"},
                {"id": "b", "enabled": False, "base_url": "http://192.0.2.6:8123", "token": "t2"}]

    def get_config(self, k):
        return None


def _shared_deps():
    """The FranklinWH / shared packages pyproject names, base and extras."""
    p = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    deps = list(p["dependencies"]) + [d for v in p["optional-dependencies"].values() for d in v]
    names = []
    for d in deps:
        n = d.split(";")[0].split("[")[0]
        for op in ("==", ">=", "<=", "~=", ">", "<", "!="):
            n = n.split(op)[0]
        names.append(n.strip().lower())
    return {n for n in names if n.startswith("franklinwh-") or n == "hems"}


def test_discovery_is_a_diagnostic_sensor_on_the_bridge_device():
    topic, cfg = entities.bridge_version_config("franklinwh", "homeassistant")
    assert topic == "homeassistant/sensor/fwh_dc_bridge/bridge_version/config"
    assert cfg["name"] == "Bridge Version"
    assert cfg["entity_category"] == "diagnostic"
    assert cfg["device"]["identifiers"] == ["franklinwh_fwh_dc_bridge"]
    assert cfg["state_topic"] == cfg["json_attributes_topic"] == "franklinwh/fwh_dc_bridge/version"
    assert cfg["value_template"] == "{{ value_json.version }}"
    assert "json_attributes_template" in cfg and "version" not in cfg["json_attributes_template"]


def test_payload_has_version_platform_install_type_integrations_and_libraries(monkeypatch):
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "House")
    state.register_gateway("g2", "192.0.2.11", "Shed")
    monkeypatch.setattr(install_identity, "install_type", lambda: "docker")
    monkeypatch.setattr(install_identity, "_install_cache", {})
    from franklinwh_direct_connect_bridge import battery_control, providers
    monkeypatch.setattr(battery_control, "is_enabled", lambda: True)
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "valid"})
    try:
        p = install_identity.bridge_version(_S(), _Store())
    finally:
        state.reset_gateways()
    assert p["version"] == __version__
    assert p["install_type"] == "docker"
    for k in ("os", "arch", "python"):
        assert p["platform"][k]
    ints = p["integrations"]
    assert ints["local"] == {"on": True, "gateways": 2}
    assert ints["cloud"] == {"signed_in": True, "state": "valid"}
    assert ints["modbus"] == {"on": True}
    assert ints["mqtt"] == {"on": True}
    assert ints["ha_instances"] == 1                      # enabled ones
    # every FranklinWH / shared dependency pyproject names, and nothing else
    assert set(p["libraries"]) == _shared_deps()
    assert "franklinwh-direct-connect-api" in p["libraries"]
    assert "fastapi" not in p["libraries"]
    json.dumps(p)


def test_payload_carries_no_pii(monkeypatch):
    state.reset_gateways()
    state.register_gateway("g1", "192.0.2.10", "House")
    from franklinwh_direct_connect_bridge import providers
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "invalid"})
    try:
        text = json.dumps(install_identity.bridge_version(_S(), _Store()))
    finally:
        state.reset_gateways()
    for secret in ("someone@example.com", "secret-pw", "10060006A02F99999999", "192.0.2.",
                   "tok", "install_id"):
        assert secret not in text, secret
    assert '"signed_in": false' in text


def test_cloud_without_credentials_is_not_signed_in(monkeypatch):
    s = _S()
    s.fwh_cloud_email = s.fwh_cloud_password = ""
    from franklinwh_direct_connect_bridge import providers
    monkeypatch.setattr(providers, "cloud_auth_status", lambda: {"state": "unconfigured"})
    assert install_identity.bridge_version(s, None)["integrations"]["cloud"]["signed_in"] is False


class _HB:
    def __init__(self):
        self.versions, self.beats, self.started = [], [], 0

    def start(self): self.started += 1
    def is_connected(self): return True
    def beat(self, now): self.beats.append(now)
    def publish_problem(self, payload): pass
    def publish_version(self, payload): self.versions.append(payload)
    def stop(self): pass


def test_published_with_each_heartbeat_and_when_it_changes(monkeypatch):
    facts = {"version": "1", "integrations": {"modbus": {"on": False}}}
    monkeypatch.setattr(install_identity, "bridge_version", lambda s, st: dict(facts))
    hb = _HB()
    mon = alerts.AlertMonitor(_S(), store_fn=lambda: None, notifier=None,
                              heartbeat_factory=lambda: hb)
    mon.heartbeat_once(now=0.0)
    assert mon.version_once(None, now=0.0)                # first: published
    assert not mon.version_once(None, now=15.0)           # unchanged between heartbeats
    facts["integrations"] = {"modbus": {"on": True}}
    assert mon.version_once(None, now=30.0)               # changed: published at once
    mon.heartbeat_once(now=60.0)
    assert mon.version_once(None, now=60.0)               # with the heartbeat
    assert len(hb.versions) == 3


def test_run_once_publishes_it(monkeypatch):
    monkeypatch.setattr(install_identity, "bridge_version", lambda s, st: {"version": "x"})
    hb = _HB()
    mon = alerts.AlertMonitor(_S(), store_fn=lambda: None, notifier=None,
                              heartbeat_factory=lambda: hb)
    mon.run_once(now=0.0)
    assert hb.versions == [{"version": "x"}]


def test_discovery_is_sent_on_connect():
    from franklinwh_direct_connect_bridge.publish import mqtt_publisher

    class C:
        def __init__(self): self.sent = []
        def publish(self, topic, payload, retain=False): self.sent.append(topic)

    hb = mqtt_publisher.BridgeHeartbeat(_S())             # builds a client; connects nothing
    c = C()
    hb._on_connect(c, None, None, 0)
    assert "homeassistant/sensor/fwh_dc_bridge/bridge_version/config" in c.sent
