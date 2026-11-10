"""#134 — aGate network state for Home Assistant: same model as the Network tab, no
credentials, no MAC or IP, and never for a mock."""
from franklinwh_direct_connect_bridge.publish import entities, network

# The SHAPE of real reads (reference aGate, 2026-10-16), values masked where site data.
CONN = {"opt": 0, "result": 0, "reason": 0, "routerStatus": 0, "netStatus": 0, "awsStatus": 0,
        "EthConnectRouterStatus": 0, "wifiConnectRouterStatus": 1, "4GConnectBSStatus": 0,
        "WifiSignalStrength": 80, "4GSignalStrength": 19, "currentNetType": 3}
SW = {"opt": 0, "result": 0, "reason": 0, "ethernet0NetSwitch": 1, "ethernet1NetSwitch": 1,
      "wifiNetSwitch": 1, "4GNetSwitch": 1}
IFC = {"currentNetType": 3, "awsStatus": 1,
       "wifi": {"mac": "00:00:5E:00:53:01", "ip": "192.0.2.10", "dhcp": True},
       "eth0": {"mac": "00:00:5E:00:53:02", "ip": None}, "eth1": {"mac": "00:00:5E:00:53:03", "ip": None},
       "operator": {"mac": "00:00:5E:00:53:04", "ip": None}}
CLOUD = {"serverAddr": "example-ats.iot.us-east-2.amazonaws.com", "serverPort": 8883,
         "password": "secret-should-never-appear"}


def test_matches_what_the_network_tab_shows():
    n = network.network_state(CONN, IFC, SW, CLOUD)
    assert n["net_in_use"] == "WiFi"
    assert n["net_available"] == "WiFi, 4G"
    assert n["net_write_safety"] == "redundant" and n["net_fallback"] == "4G"
    assert n["net_if_wifi"] == "active" and n["net_if_4g"] == "available"
    assert n["net_if_eth0"] == "down"                  # switched on, no link, no address
    assert n["net_wifi_signal"] == 80 and n["net_4g_signal"] == 19
    assert n["net_cloud"] == "connected"               # 1118 awsStatus, the authoritative one
    assert n["net_cloud_endpoint"] == "example-ats.iot.us-east-2.amazonaws.com"


def test_never_publishes_addresses_or_credentials():
    blob = repr(network.network_state(CONN, IFC, SW, CLOUD))
    for secret in ("00:00:5E:00:53", "192.0.2.10", "secret-should-never-appear", "8883"):
        assert secret not in blob


def test_missing_reads_give_none_not_guesses():
    n = network.network_state(None, None, None, None)
    assert n["net_cloud"] is None and n["net_wifi_signal"] is None
    assert n["net_in_use"] == "none"


def test_every_network_entity_is_published_and_diagnostic():
    cfgs = {t.split("/")[-2]: c for t, c in entities.discovery_configs(
        "n1", entities.device_info("n1", "SN1"), "franklinwh-local", "homeassistant", None)[0]}
    n = network.network_state(CONN, IFC, SW, CLOUD)
    for k in entities.NETWORK_KEYS:
        assert k in n, k                                # the model produces every key
        assert cfgs[k]["entity_category"] == "diagnostic"


def test_a_mock_gets_no_network_entities():
    cfgs = entities.discovery_configs("m1", entities.device_info("m1", "MOCK1", is_mock=True),
                                      "franklinwh-local", "homeassistant", None,
                                      skip=entities.NETWORK_KEYS)[0]
    assert not [t for t, _ in cfgs if "/net_" in t]
