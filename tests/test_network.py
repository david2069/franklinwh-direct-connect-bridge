"""FEAT-DIAG-CLI-PARITY — the /api/network diagnostics endpoint.

The aGate reads are mocked (no hardware in tests); this covers the bridge's job: translate the
raw interfaces into the cloud get_network_info shape, and REDACT cloud credentials.
"""
from fastapi.testclient import TestClient

from franklinwh_direct_connect_bridge import app as app_module, client as client_mod, config, environment, db
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


def _client(tmp_path, monkeypatch):
    st = MetricsStore(str(tmp_path / "m.db"))
    monkeypatch.setattr(environment, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "get_store", lambda s: st)
    monkeypatch.setattr(client_mod, "network_bundle", lambda s, host=None: dict(FIXTURE))
    return TestClient(app_module.create_app())


def test_network_endpoint_translates_and_redacts(tmp_path, monkeypatch):
    out = _client(tmp_path, monkeypatch).get("/api/network").json()
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
    out = c.get("/api/network/ping?count=3").json()
    assert out["count"] == 3 and len(out["samples"]) == 3
    assert out["loss_pct"] == 0.0 and out["avg"] is not None and out["min"] is not None
    # the live Watch loop polls count=1 each tick and reads samples[0] — that shape must hold
    one = c.get("/api/network/ping?count=1").json()
    assert one["count"] == 1 and len(one["samples"]) == 1


def test_network_endpoint_handles_absent_blocks(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(client_mod, "network_bundle",
                        lambda s, host=None: {"host": "x", "reachability": {"ok": False},
                                              "connectivity": None, "interfaces_raw": None,
                                              "switches": None, "cloud": None})
    out = c.get("/api/network").json()
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
    out = TestClient(app_module.create_app()).get("/api/network").json()
    ha = out["topology"]["home_assistant"]
    assert ha["configured"] is True and ha["count"] == 2
    hosts = {i["host"] for i in ha["instances"]}
    assert "homeassistant.local:8123" in hosts and "10.0.0.9:8123" in hosts
    # the token must never leak into the diagram payload
    assert "SEKRET" not in str(out)
    assert all("token" not in i for i in ha["instances"])
    # exposed-entity count (what the bridge publishes to HA via MQTT discovery)
    assert isinstance(ha["published_entities"], int) and ha["published_entities"] > 0

