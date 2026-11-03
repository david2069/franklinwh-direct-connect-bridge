"""aGate network state for Home Assistant (#134) — a port of the Network tab's interface
model (static/js/network_tab.js `diag`), so HA and the UI say the same thing.

Inputs are the raw local reads: connectivity (1113), network_interfaces (1118, already
translated by cloud_compat.network_from_interfaces), switches (1119) and the cloud endpoint
(1121, ``serverAddr`` only). Nothing here publishes a MAC, an IP address, a credential or
the Wi-Fi name: the SSID lives in wifi_config, which also carries the password, and is
deliberately not read.
"""
from __future__ import annotations

from typing import Any


def _ok(v: Any) -> bool:
    return v is True or v == 1 or v in ("1", "online", "connected", "ok")


def _dig(o: Any, key: str) -> Any:
    if not isinstance(o, dict):
        return None
    if key in o:
        return o[key]
    for w in ("result", "commSetPara"):
        if isinstance(o.get(w), dict):
            v = _dig(o[w], key)
            if v is not None:
                return v
    return None


def network_state(connectivity: dict | None, interfaces: dict | None,
                  switches: dict | None, cloud: dict | None) -> dict[str, Any]:
    """The ``net_*`` keys published in the gateway's MQTT state."""
    c, ifc = connectivity or {}, interfaces or {}
    s = switches or {}
    sw = s.get("result") if isinstance(s.get("result"), dict) else s
    if isinstance(sw, dict) and isinstance(sw.get("commSetPara"), dict):
        sw = sw["commSetPara"]
    specs = [  # name, enable switches, link key, translated interface block
        ("eth0", ["ethernet0NetSwitch"], "EthConnectRouterStatus", ifc.get("eth0")),
        ("eth1", ["ethernet1NetSwitch"], "EthConnectRouterStatus", ifc.get("eth1")),
        ("wifi", ["wifiNetSwitch"], "wifiConnectRouterStatus", ifc.get("wifi")),
        ("4g", ["4GNetSwitch"], "4GConnectBSStatus", ifc.get("operator")),
    ]
    out: dict[str, Any] = {}
    carrying, available = [], []
    for name, en, link_key, o in specs:
        enabled = any(_ok((sw or {}).get(k)) for k in en)
        link = _ok(_dig(c, link_key))
        ip = (o or {}).get("ip") if isinstance(o, dict) else None
        has_addr = bool(ip and ip != "0.0.0.0")
        # 4G holds no IP while idle and SIM status isn't exposed locally: enabled ≈ available.
        avail = enabled if name == "4g" else (enabled and (link or has_addr))
        out[f"net_if_{name}"] = ("active" if link else "available" if avail
                                 else "off" if not enabled else "down")
        if link:
            carrying.append(name)
        if avail:
            available.append(name)
    label = {"eth0": "Ethernet 0", "eth1": "Ethernet 1", "wifi": "WiFi", "4g": "4G"}
    out["net_in_use"] = ", ".join(label[n] for n in carrying) or "none"
    out["net_available"] = ", ".join(label[n] for n in available) or "none"
    fallback = [label[n] for n in available if n not in carrying]
    out["net_write_safety"] = "redundant" if len(available) > 1 else "single path"
    out["net_fallback"] = ", ".join(fallback) or "none"
    w, g = _dig(c, "WifiSignalStrength"), _dig(c, "4GSignalStrength")
    out["net_wifi_signal"] = w if isinstance(w, (int, float)) else None
    out["net_4g_signal"] = g if isinstance(g, (int, float)) else None
    # 1118 awsStatus is the authoritative one (the 1113 self-report has contradicted reality).
    aws = ifc.get("awsStatus")
    out["net_cloud"] = None if aws is None else ("connected" if _ok(aws) else "not connected")
    addr = _dig(cloud, "serverAddr") if cloud else None
    out["net_cloud_endpoint"] = addr if isinstance(addr, str) and addr else None
    # 1118 currentNetType: the link the aGate is using now (1 Eth0, 2 Eth1, 3 WiFi, 4 4G). It
    # roams on its own, so this is observed state, not a setting.
    via = {1: "Ethernet 0", 2: "Ethernet 1", 3: "WiFi", 4: "4G"}
    cur = ifc.get("currentNetType")
    out["net_cloud_via"] = via.get(int(cur)) if isinstance(cur, (int, str)) and str(cur).isdigit() else None
    return out
