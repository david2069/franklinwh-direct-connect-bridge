"""#399: HA controls are obeyed over MQTT only while the Controls group is published.

Turning Controls off removed the mode select and circuit switches from HA, but the
publisher stayed subscribed to ``<prefix>/<node>/control/+/set`` and passed every message
on, so anyone who could publish to the broker could still change the mode.
"""
from types import SimpleNamespace as NS

from franklinwh_direct_connect_bridge.config import Settings
from franklinwh_direct_connect_bridge.publish import entities
from franklinwh_direct_connect_bridge.publish.mqtt_publisher import MqttPublisher

ALL = entities.default_groups()
NO_CONTROLS = [g for g in ALL if g != "controls"]


class _Client:
    def __init__(self):
        self.subs, self.unsubs = [], []

    def subscribe(self, t):
        self.subs.append(t)

    def unsubscribe(self, t):
        self.unsubs.append(t)

    def publish(self, *a, **k):
        pass


def _pub(groups):
    calls = []
    p = MqttPublisher(Settings(), "node1", {"identifiers": ["x"]},
                      command_handler=lambda k, v: calls.append((k, v)), groups=groups)
    p.client = _Client()
    return p, calls


def _send(p, key="mode", payload="Self-Consumption"):
    p._on_message(p.client, None, NS(topic=f"{p.s.mqtt_prefix}/node1/control/{key}/set",
                                     payload=payload.encode()))


def test_controls_on_subscribes_and_obeys():
    p, calls = _pub(ALL)
    p._on_connect(p.client, None, None, 0)
    _send(p)
    assert p.client.subs == [p.cmd_filter] and calls == [("mode", "Self-Consumption")]


def test_controls_off_does_not_subscribe_and_refuses():
    p, calls = _pub(NO_CONTROLS)
    p._on_connect(p.client, None, None, 0)
    _send(p)
    assert p.client.subs == [] and calls == []


def test_switching_controls_off_unsubscribes_and_refuses_in_flight():
    p, calls = _pub(ALL)
    p.rebuild_discovery(NO_CONTROLS)
    _send(p)
    assert p.client.unsubs == [p.cmd_filter] and calls == []


def test_switching_controls_back_on_subscribes_again():
    p, calls = _pub(NO_CONTROLS)
    p.rebuild_discovery(ALL)
    _send(p)
    assert p.client.subs == [p.cmd_filter] and calls == [("mode", "Self-Consumption")]
