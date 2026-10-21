"""Bridge problem + heartbeat over MQTT (#271, shared alert spec §6)."""

import asyncio
import json

import pytest

from franklinwh_direct_connect_bridge import alerts, config, db, poller
from franklinwh_direct_connect_bridge.publish import entities
from franklinwh_direct_connect_bridge.state import GatewayState


@pytest.fixture(autouse=True)
def _fresh():
    alerts.reset()
    yield
    alerts.reset()


def _cfgs(groups=None):
    cfgs, _, avail = entities.discovery_configs(
        "n1", entities.device_info("n1", "SN1"), "franklinwh-local", "homeassistant", groups)
    return {t: c for t, c in cfgs}, avail


@pytest.mark.parametrize("groups", [None, ["core"], ["power"]])
def test_bridge_problem_and_heartbeat_are_always_discovered(groups):
    cfgs, avail = _cfgs(groups)
    prob = cfgs["homeassistant/binary_sensor/n1/bridge_problem/config"]
    beat = cfgs["homeassistant/sensor/n1/bridge_heartbeat/config"]
    assert prob["name"] == "Bridge problem" and prob["device_class"] == "problem"
    assert beat["device_class"] == "timestamp"
    for c in (prob, beat):
        assert c["state_topic"] == "franklinwh-local/n1/alerts"
        # Must stay readable while the aGate is unreachable — that IS a bridge problem.
        assert "availability_topic" not in c
        assert c["device"]["identifiers"] == ["franklinwh_n1"]
    assert prob["json_attributes_topic"] == "franklinwh-local/n1/alerts"


def test_payload_flags_only_this_gateway_and_bridge_wide_alerts():
    rows = [{"id": 1, "gateway_id": "gw1", "code": "GATEWAY_UNREACHABLE"},
            {"id": 2, "gateway_id": "", "code": "WORKER_STALLED"},
            {"id": 3, "gateway_id": "gw2", "code": "COMMAND_REFUSED"}]
    p = entities.alerts_payload({"level": "critical"}, rows, 0.0, "gw1")
    assert p["problem"] is True and p["open"] == 2
    assert [a["id"] for a in p["alerts"]] == [1, 2]
    assert p["heartbeat"] == "1970-01-01T00:00:00+00:00"
    assert entities.alerts_payload({"level": "ok"}, [], 0.0, "gw1")["problem"] is False
    json.dumps(p)                                          # publishable as-is


class _Pub:
    sent: list = []

    def __init__(self, *a, **k):
        self.configs = []

    def start(self): pass
    def stop(self): pass
    def is_connected(self): return True
    def publish_state(self, st): pass
    def publish_availability(self, online): pass
    def publish_alerts(self, payload): _Pub.sent.append(payload)


def test_poller_publishes_the_problem_state_and_heartbeat(monkeypatch):
    s = config.get_settings()
    store = db.get_store(s)
    alerts.raise_event(store, "g271", "COMMAND_REFUSED", "Force rejected")
    _Pub.sent = []
    monkeypatch.setattr(s, "mqtt_enabled", True)
    monkeypatch.setattr(s, "poll_interval", 1)
    monkeypatch.setattr(poller, "MqttPublisher", _Pub)
    monkeypatch.setattr(poller.client, "firmware",
                        lambda *a, **k: {"IBG_SN": "SN271", "IBG_VER": "V1"})
    monkeypatch.setattr(poller.client, "summary",
                        lambda *a, **k: {"ok": True, "power": {"soc": 50}})
    import franklinwh_direct_connect_bridge.ha_supervisor as hs
    monkeypatch.setattr(hs, "apply_supervisor_mqtt", lambda *a, **k: None)
    gw = GatewayState(id="g271", label="t", publish_ha=True,
                      configured_host="127.0.0.1:1", active_host="127.0.0.1:1")

    async def go():
        stop = asyncio.Event()
        t = asyncio.create_task(poller.run_gateway(s, gw, stop))
        await asyncio.sleep(1.6)                           # two cycles, one change
        stop.set()
        await asyncio.wait_for(t, timeout=10)
    asyncio.run(go())
    assert _Pub.sent, "nothing published"
    assert _Pub.sent[0]["problem"] is True
    assert _Pub.sent[0]["alerts"][0]["code"] == "COMMAND_REFUSED"
    assert len(_Pub.sent) == 1, "unchanged summary inside the heartbeat interval: no repeat"
