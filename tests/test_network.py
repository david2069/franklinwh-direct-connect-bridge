"""FEAT-DIAG-CLI-PARITY — the /api/network diagnostics endpoint.

The aGate reads are mocked (no hardware in tests); this covers the bridge's job: translate the
raw interfaces into the cloud get_network_info shape, and REDACT cloud credentials.
"""
import pytest
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client as client_mod, config, environment, db, state
from franklinwh_direct_connect_bridge.db import MetricsStore

FIXTURE = {
    "host": "1.2.3.4",
    "reachability": {"host": "1.2.3.4", "ping": True, "sendmqtt_9000": True,
                     "latency_ms": 42.0, "modbus_502": True, "ok": True},
    "connectivity": {"result": {"routerStatus": 1, "netStatus": 1, "awsStatus": 1}},
    "interfaces_raw": {"commSetPara": {"currentNetType": 1, "wifiMAC": "aa:bb:cc",
                                       "wifiStaticIP": "192.168.0.5", "awsStatus": 1,
                                       "operatorRSSI": -71}},
    "switches": {"result": {"eth0": 1, "wifi": 0, "net4G": 1}},
    "cloud": {"serverAddr": "abc.iot.ap-southeast-2.amazonaws.com", "serverPort": 8883,
              "region": "ap-southeast-2", "mqttPassword": "SECRET", "clientKey": "PRIVATEKEY", "psk": ""},
}

GW = "gw-net"
G = f"gateway={GW}"     # every device route names its gateway (#379)


@pytest.fixture(autouse=True)
def _gateway():
    state.register_gateway(GW, "1.2.3.4", "Home")
    yield
    state.unregister_gateway(GW)


def _client(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(client_mod, "network_bundle", lambda s, host=None: dict(FIXTURE))
    return TestClient(app_module.create_app())


def test_network_endpoint_translates_and_redacts(tmp_path, monkeypatch):
    out = _client(tmp_path, monkeypatch).get("/api/network?" + G).json()
    # reachability passes through
    assert out["reachability"]["ok"] is True and out["reachability"]["latency_ms"] == 42.0
    # raw interfaces → cloud get_network_info shape
    assert out["interfaces"]["currentNetType"] == 1
    assert out["interfaces"]["wifi"]["ip"] == "192.168.0.5" and out["interfaces"]["wifi"]["mac"] == "aa:bb:cc"
    assert out["interfaces"]["operator"]["rssi"] == -71
    assert "interfaces_raw" not in out                          # raw is consumed, not leaked
    # cloud endpoint/region kept; SECRETS redacted to a present-marker
    assert out["cloud"]["serverAddr"].endswith("amazonaws.com") and out["cloud"]["region"] == "ap-southeast-2"
    assert out["cloud"]["mqttPassword"] == "***set***" and out["cloud"]["clientKey"] == "***set***"
    assert out["cloud"]["psk"] is None                          # empty secret → None, never the value
    assert "SECRET" not in str(out) and "PRIVATEKEY" not in str(out)
    # topology block for the diagram
    t = out["topology"]
    assert t["agate"]["ports"]["local_api_9000"] is True and t["agate"]["ports"]["modbus_502"] is True
    assert t["iot"]["connected"] is True and t["iot"]["endpoint"].endswith("amazonaws.com")
    assert t["iot"]["port"] == 8883
    assert t["bridge"]["uptime_s"] >= 0 and t["bridge"]["http_port"] == 8101
    assert t["browser"]["ip"]                                   # TestClient supplies a client host
    assert "host" in t["mqtt"]
    # Home Assistant node — none configured in the default fixture
    assert t["home_assistant"]["configured"] is False and t["home_assistant"]["count"] == 0
    assert t["home_assistant"]["instances"] == []
    assert isinstance(t["home_assistant"]["via_mqtt"], bool)


class _FakeClient:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self): pass
    def power_flow(self): return {}


def test_ping_endpoint(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(client_mod, "_client", lambda s, host=None: _FakeClient())
    out = c.get("/api/network/ping?count=3&" + G).json()
    assert out["count"] == 3 and len(out["samples"]) == 3
    assert out["loss_pct"] == 0.0 and out["avg"] is not None and out["min"] is not None
    # the live Watch loop polls count=1 each tick and reads samples[0] — that shape must hold
    one = c.get("/api/network/ping?count=1&" + G).json()
    assert one["count"] == 1 and len(one["samples"]) == 1


def test_network_endpoint_handles_absent_blocks(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(client_mod, "network_bundle",
                        lambda s, host=None: {"host": "x", "reachability": {"ok": False},
                                              "connectivity": None, "interfaces_raw": None,
                                              "switches": None, "cloud": None})
    out = c.get("/api/network?" + G).json()
    assert out["interfaces"] is None and out["cloud"] is None and out["reachability"]["ok"] is False


def test_network_topology_home_assistant_node(tmp_path, monkeypatch):
    """When an HA instance is rostered, the topology carries a populated home_assistant node."""
    st = MetricsStore(str(tmp_path / "m.db"))
    st.create_ha_instance(ha_id="ha1", name="Home", base_url="http://homeassistant.local:8123",
                          token="SEKRET", is_default=True, enabled=True)
    st.create_ha_instance(ha_id="ha2", name="Cabin", base_url="http://10.0.0.9:8123",
                          token="x", enabled=True)
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(client_mod, "network_bundle", lambda s, host=None: dict(FIXTURE))
    out = TestClient(app_module.create_app()).get("/api/network?" + G).json()
    ha = out["topology"]["home_assistant"]
    assert ha["configured"] is True and ha["count"] == 2
    hosts = {i["host"] for i in ha["instances"]}
    assert "homeassistant.local:8123" in hosts and "10.0.0.9:8123" in hosts
    # the token must never leak into the diagram payload
    assert "SEKRET" not in str(out)
    assert all("token" not in i for i in ha["instances"])
    # exposed-entity count (what the bridge publishes to HA via MQTT discovery)
    assert isinstance(ha["published_entities"], int) and ha["published_entities"] > 0



def test_network_topology_preserves_not_probed(tmp_path, monkeypatch):
    """None must survive to the client as None (#30).

    bool() here would turn "we did not look" into a confident "down" on the topology
    diagram, which is the whole defect.
    """
    fx = dict(FIXTURE)
    fx["reachability"] = dict(FIXTURE["reachability"], modbus_502=None)
    monkeypatch.setattr(client_mod, "network_bundle", lambda s, host=None: dict(fx))
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(client_mod, "network_bundle", lambda s, host=None: dict(fx))
    ports = c.get("/api/network?" + G).json()["topology"]["agate"]["ports"]
    assert ports["modbus_502"] is None, f"not-probed was flattened to {ports['modbus_502']!r}"


# ---- #617: the :502 edge must not stay green on a result older than the link -----------
# The bridge never probes :502 (#221), so the diagram can only judge the Modbus client's
# last real result by its timestamp against the time the aGate's LAN link last came up.

T_UP = 10_000.0     # the :9000 link came back up here, after an outage


def _outage_then_up(st):
    """A recorded :9000 outage that ended at T_UP — what the poller logs as RECOVERED."""
    for i in range(st.LINK_STRIKES):
        st.record_link_probe(GW, "failed", leg="local_9000", now=T_UP - 300 + 30 * i)
    st.record_link_probe(GW, "ok", leg="local_9000", now=T_UP)


def _get_502(tmp_path, monkeypatch, reach, *, outage=True, down=False):
    fx = dict(FIXTURE, reachability=dict(FIXTURE["reachability"], **reach))
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(client_mod, "network_bundle", lambda s, host=None: dict(fx))
    if outage:
        _outage_then_up(st)
    if down:
        for i in range(st.LINK_STRIKES):
            st.record_link_probe(GW, "failed", leg="local_9000", now=T_UP + 600 + 30 * i)
    out = TestClient(app_module.create_app()).get("/api/network?" + G).json()
    return out["topology"]["agate"]["ports"], out["reachability"]


def test_502_unknown_while_link_down(tmp_path, monkeypatch):
    """Link down + an old success: unknown (grey), never green — the outage screenshot."""
    ports, reach = _get_502(tmp_path, monkeypatch,
                            {"modbus_502": True, "modbus_502_at": T_UP + 60,
                             "sendmqtt_9000": False, "ok": False}, down=True)
    assert ports["modbus_502_state"] == "unknown"
    assert ports["modbus_502_at"] == T_UP + 60          # for "last OK HH:MM"
    assert reach["modbus_502_state"] == "unknown"


def test_502_up_after_link_came_up(tmp_path, monkeypatch):
    ports, reach = _get_502(tmp_path, monkeypatch,
                            {"modbus_502": True, "modbus_502_at": T_UP + 60})
    assert ports["modbus_502_state"] == "up" and reach["modbus_502_state"] == "up"


def test_502_unknown_when_success_predates_outage(tmp_path, monkeypatch):
    ports, reach = _get_502(tmp_path, monkeypatch,
                            {"modbus_502": True, "modbus_502_at": T_UP - 3600})
    assert ports["modbus_502_state"] == "unknown" and reach["modbus_502_state"] == "unknown"


def test_502_down_when_last_attempt_failed(tmp_path, monkeypatch):
    ports, reach = _get_502(tmp_path, monkeypatch,
                            {"modbus_502": False, "modbus_502_at": T_UP + 60})
    assert ports["modbus_502_state"] == "down" and reach["modbus_502_state"] == "down"


def test_502_not_probed_stays_none(tmp_path, monkeypatch):
    ports, _ = _get_502(tmp_path, monkeypatch, {"modbus_502": None}, outage=False)
    assert ports["modbus_502_state"] is None


def test_502_up_with_no_recorded_outage(tmp_path, monkeypatch):
    """No outage on record: the link has been up all along, so a success counts."""
    ports, _ = _get_502(tmp_path, monkeypatch,
                        {"modbus_502": True, "modbus_502_at": 500.0}, outage=False)
    assert ports["modbus_502_state"] == "up"


def test_network_bundle_carries_502_timestamp(monkeypatch):
    """The reachability block needs the result's time, not just its value, and still
    opens no :502 socket (#221)."""
    monkeypatch.setattr(client_mod, "_modbus_last",
                        lambda h, mock=False: {"reachable": True, "ts": 123.0, "source": "force"})
    monkeypatch.setattr(client_mod.discover, "ping", lambda h, timeout=1.0: False)

    class _Boom:
        def __enter__(self):
            raise OSError("unreachable")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(client_mod, "_client", lambda s, host: _Boom())
    reach = client_mod.network_bundle(config.Settings(), host="127.0.0.1:1")["reachability"]
    assert reach["modbus_502"] is True and reach["modbus_502_at"] == 123.0
