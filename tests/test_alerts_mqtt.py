"""Bridge problem (per gateway) and the bridge-level heartbeat over MQTT (#271, §6, §11)."""

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
def test_bridge_problem_is_always_discovered_and_the_heartbeat_is_not_per_gateway(groups):
    cfgs, avail = _cfgs(groups)
    prob = cfgs["homeassistant/binary_sensor/n1/bridge_problem/config"]
    assert prob["name"] == "Bridge problem" and prob["device_class"] == "problem"
    assert prob["state_topic"] == "franklinwh-local/n1/alerts"
    # Must stay readable while the aGate is unreachable — that IS a bridge problem.
    assert "availability_topic" not in prob
    assert prob["device"]["identifiers"] == ["franklinwh_n1"]
    assert prob["json_attributes_topic"] == "franklinwh-local/n1/alerts"
    assert not any("heartbeat" in t for t in cfgs)


def test_one_bridge_level_heartbeat_entity():
    topic, cfg = entities.heartbeat_config("franklinwh-local", "homeassistant")
    assert topic == "homeassistant/sensor/fwh_dc_bridge/heartbeat/config"
    assert cfg["name"] == "Bridge heartbeat" and cfg["device_class"] == "timestamp"
    assert cfg["state_topic"] == "franklinwh-local/fwh_dc_bridge/heartbeat"
    assert "availability_topic" not in cfg
    assert cfg["device"]["identifiers"] == ["franklinwh_fwh_dc_bridge"]
    # mqtt_scan decides ownership by this prefix, so the bridge device counts as ours.
    assert cfg["device"]["sw_version"].startswith("Direct Connect Bridge v")
    assert entities.heartbeat_payload(0.0) == "1970-01-01T00:00:00+00:00"


def test_payload_flags_only_this_gateway_and_bridge_wide_alerts():
    rows = [{"id": 1, "gateway_id": "gw1", "code": "GATEWAY_UNREACHABLE"},
            {"id": 2, "gateway_id": "", "code": "WORKER_STALLED"},
            {"id": 3, "gateway_id": "gw2", "code": "COMMAND_REFUSED"}]
    p = entities.alerts_payload({"level": "critical"}, rows, "gw1")
    assert p["problem"] is True and p["open"] == 2
    assert [a["id"] for a in p["alerts"]] == [1, 2]
    assert "heartbeat" not in p
    assert entities.alerts_payload({"level": "ok"}, [], "gw1")["problem"] is False
    json.dumps(p)                                          # publishable as-is


# ── the heartbeat: the alert monitor's, every 60 s, only when MQTT is up ─────────
class _HB:
    def __init__(self, connected=True, fail=False):
        self.connected, self.fail = connected, fail
        self.beats, self.started, self.stopped = [], 0, 0

    def start(self):
        if self.fail:
            raise OSError("connection refused")
        self.started += 1

    def is_connected(self): return self.connected
    def beat(self, now): self.beats.append(now)
    def stop(self): self.stopped += 1


def _monitor(mqtt_enabled, hb):
    class S:
        pass
    s = S()
    s.mqtt_enabled = mqtt_enabled
    return alerts.AlertMonitor(s, store_fn=lambda: None, notifier=None,
                               heartbeat_factory=lambda: hb)


def test_heartbeat_every_60_seconds_while_connected():
    hb = _HB()
    mon = _monitor(True, hb)
    for t in (0, 15, 30, 45, 60, 75, 120):
        mon.run_once(now=float(t))
    assert hb.beats == [0.0, 60.0, 120.0] and hb.started == 1


def test_no_heartbeat_with_mqtt_off_or_disconnected():
    hb = _HB()
    mon = _monitor(False, hb)
    mon.run_once(now=0.0)
    assert hb.started == 0 and hb.beats == []
    hb2 = _HB(connected=False)
    mon2 = _monitor(True, hb2)
    mon2.run_once(now=0.0)
    assert hb2.started == 1 and hb2.beats == []
    hb2.connected = True
    mon2.run_once(now=15.0)
    assert hb2.beats == [15.0]


def test_heartbeat_does_not_depend_on_any_gateway_and_survives_a_broker_failure():
    hb = _HB(fail=True)
    mon = _monitor(True, hb)
    mon.run_once(now=0.0)                                  # connect fails: no beat, no raise
    hb.fail = False
    mon.run_once(now=30.0)                                 # retry throttled to once a minute
    assert hb.started == 0
    mon.run_once(now=60.0)
    assert hb.started == 1 and hb.beats == [60.0]


def test_switching_mqtt_off_stops_the_heartbeat_connection():
    hb = _HB()
    mon = _monitor(True, hb)
    mon.run_once(now=0.0)
    mon.settings.mqtt_enabled = False
    mon.run_once(now=60.0)
    assert hb.stopped == 1 and hb.beats == [0.0]


def test_the_bridge_node_is_never_an_mqtt_orphan(monkeypatch):
    from fastapi.testclient import TestClient
    from franklinwh_direct_connect_bridge import app as app_module
    from franklinwh_direct_connect_bridge.publish import mqtt_scan
    seen = {}

    def spy(settings, live_nodes, **k):               # no broker is contacted
        seen["live"] = list(live_nodes)
        return {"ok": True}
    monkeypatch.setattr(config.get_settings(), "mqtt_enabled", True)
    monkeypatch.setattr(mqtt_scan, "scan_orphans", spy)
    TestClient(app_module.create_app()).get("/api/mqtt/orphans")
    assert entities.BRIDGE_NODE in seen["live"]


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


def test_poller_publishes_the_problem_state(monkeypatch):
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
