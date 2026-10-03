"""Home Assistant entity definitions + discovery-payload builders (pure functions).

One JSON state topic per device; each sensor's discovery config uses a value_template to
pull its field. Availability is a separate topic driven by the health round-trip / LWT.
"""

from __future__ import annotations

from typing import Any

MANUFACTURER = "FranklinWH"

# key -> HA sensor descriptor. `key` is both the state-JSON field and the discovery id.
ENTITIES: list[dict[str, Any]] = [
    {"key": "soc", "name": "State of Charge", "unit": "%", "device_class": "battery", "state_class": "measurement", "group": "core"},
    {"key": "grid_w", "name": "Grid Power", "unit": "W", "device_class": "power", "state_class": "measurement", "group": "power"},
    {"key": "solar_w", "name": "Solar Power", "unit": "W", "device_class": "power", "state_class": "measurement", "group": "power"},
    {"key": "battery_w", "name": "Battery Power", "unit": "W", "device_class": "power", "state_class": "measurement", "group": "power"},
    {"key": "load_w", "name": "Load Power", "unit": "W", "device_class": "power", "state_class": "measurement", "group": "power"},
    {"key": "generator_w", "name": "Generator Power", "unit": "W", "device_class": "power", "state_class": "measurement", "group": "power"},
    {"key": "mode", "name": "Operating Mode", "unit": None, "device_class": None, "state_class": None, "group": "core"},
    {"key": "latency_ms", "name": "Round-trip Latency", "unit": "ms", "device_class": None, "state_class": "measurement", "group": "diagnostic"},
    # Daily energy counters — all five come from the same 1301 payload the poll
    # already fetches, so these cost nothing extra and feed the HA energy dashboard.
    {"key": "solar_today_kwh", "name": "Solar Today", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "group": "energy"},
    {"key": "grid_import_today_kwh", "name": "Grid Import Today", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "group": "energy"},
    {"key": "grid_export_today_kwh", "name": "Grid Export Today", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "group": "energy"},
    {"key": "battery_charge_today_kwh", "name": "Battery Charged Today", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "group": "energy"},
    {"key": "battery_discharge_today_kwh", "name": "Battery Discharged Today", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "group": "energy"},
    {"key": "load_today_kwh", "name": "Home Load Today", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "group": "energy"},
    {"key": "ambient_temp_c", "name": "Ambient Temperature", "unit": "°C", "device_class": "temperature", "state_class": "measurement", "group": "diagnostic"},
    {"key": "run_status", "name": "Run Status", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "battery_status", "name": "Battery State", "unit": None, "device_class": None, "state_class": None, "group": "power"},
]

#: The three operating work modes. HA shows these names; the bridge maps the
#: chosen one to the stable `scheduling_type` alias, never to the site-specific
#: programme id or the tariff name.
MODE_OPTIONS = ["Time-of-Use", "Self-Consumption", "Emergency Backup"]
MODE_ALIAS = {"Time-of-Use": "tou", "Self-Consumption": "self",
              "Emergency Backup": "backup"}

#: WRITABLE entities. Only hardware-verified writes appear here — an HA control
#: that silently does nothing is worse than no control. Reserve SoC and
#: smart-circuit schedules are deliberately absent: the gateway discards both.
CONTROLS: list[dict[str, Any]] = [
    {"key": "operating_mode", "name": "Operating Mode", "ha_type": "select",
     "options": MODE_OPTIONS, "state_key": "mode"},
    {"key": "smart_circuit_1", "name": "Smart Circuit 1", "ha_type": "switch",
     "state_key": "circuit_1_on", "circuit": 1},
    {"key": "smart_circuit_2", "name": "Smart Circuit 2", "ha_type": "switch",
     "state_key": "circuit_2_on", "circuit": 2},
    {"key": "smart_circuit_3", "name": "Smart Circuit 3", "ha_type": "switch",
     "state_key": "circuit_3_on", "circuit": 3},
]

#: Publishable groups. Users can opt groups in/out (heavy ones default off) — the
#: differentiator vs a plain filtered viewer. Controls are the writable entities.
GROUPS: dict[str, dict] = {
    "core":       {"label": "Core (SoC / mode)",     "default": True},
    "power":      {"label": "Power flows",           "default": True},
    "energy":     {"label": "Energy (today, kWh)",   "default": True},
    "diagnostic": {"label": "Diagnostic",            "default": True},
    "controls":   {"label": "Controls (writable)",   "default": True},
}


def default_groups() -> list[str]:
    return [g for g, v in GROUPS.items() if v["default"]]


def _enabled(groups) -> set:
    return set(groups) if groups is not None else set(default_groups())


def enabled_from_store(store) -> list:
    """Enabled groups from the metrics store's app_config (global preference), or the
    defaults when unset/unavailable."""
    if store is None:
        return default_groups()
    try:
        import json as _json
        raw = store.get_config("mqtt_groups")
        g = _json.loads(raw) if raw else None
        return [x for x in g if x in GROUPS] if isinstance(g, list) else default_groups()
    except Exception:  # noqa: BLE001
        return default_groups()


def build_state(power: dict, health: dict) -> dict[str, Any]:
    """Flatten a power_flow (1301) + health read into the published state JSON."""
    return {
        "soc": power.get("soc"),
        "grid_w": power.get("p_uti"),
        "solar_w": power.get("p_sun"),
        "battery_w": power.get("p_fhp"),
        "load_w": power.get("p_load"),
        "generator_w": power.get("p_gen"),
        "mode": power.get("name") or power.get("mode"),
        "latency_ms": health.get("latency_ms"),
        "solar_today_kwh": power.get("kwh_sun"),
        "grid_import_today_kwh": power.get("kwh_uti_in"),
        "grid_export_today_kwh": power.get("kwh_uti_out"),
        "battery_charge_today_kwh": power.get("kwh_fhp_chg"),
        "battery_discharge_today_kwh": power.get("kwh_fhp_di"),
        "load_today_kwh": power.get("kwh_load"),
        "ambient_temp_c": power.get("t_amb"),
        "run_status": power.get("run_status"),
        "battery_status": ("charging" if (power.get("p_fhp") or 0) < 0
                           else "discharging" if (power.get("p_fhp") or 0) > 0 else "standby"),
    }


def device_info(node: str, serial: str, firmware: str | None = None) -> dict[str, Any]:
    from .. import __version__
    # sw_version clearly identifies THIS integration ("Local Bridge vX.Y.Z") so its HA
    # device is distinguishable from the Modbus bridge's on a shared broker; the aGate's
    # own firmware is appended when known.
    bridge = f"Local Bridge v{__version__}"
    d = {
        "identifiers": [f"franklinwh_{node}"],
        "name": "FranklinWH aGate (Local Bridge)",
        "manufacturer": MANUFACTURER,
        "model": "aGate",
        "sw_version": f"{bridge} · aGate {firmware}" if firmware else bridge,
    }
    if serial:
        d["serial_number"] = serial
    return d


def discovery_configs(node: str, device: dict, prefix: str, discovery_prefix: str, groups=None):
    """Return (list[(config_topic, config_payload)], state_topic, availability_topic)."""
    state_topic = f"{prefix}/{node}/state"
    avail_topic = f"{prefix}/{node}/availability"
    configs = []
    enabled = _enabled(groups)
    for e in ENTITIES:
        if e.get("group", "core") not in enabled:
            continue
        cfg = {
            "name": e["name"],
            "unique_id": f"franklinwh_{node}_{e['key']}",
            "object_id": f"franklinwh_{node}_{e['key']}",
            "state_topic": state_topic,
            "value_template": "{{ value_json.%s }}" % e["key"],
            "availability_topic": avail_topic,
            "device": device,
        }
        if e["unit"]:
            cfg["unit_of_measurement"] = e["unit"]
        if e["device_class"]:
            cfg["device_class"] = e["device_class"]
        if e["state_class"]:
            cfg["state_class"] = e["state_class"]
        configs.append((f"{discovery_prefix}/sensor/{node}/{e['key']}/config", cfg))

    # Controls. Each gets its own command topic; the publisher subscribes to
    # `<prefix>/<node>/control/+/set` and routes by the key in the topic.
    for c in CONTROLS if "controls" in enabled else []:
        cmd_topic = f"{prefix}/{node}/control/{c['key']}/set"
        cfg = {
            "name": c["name"],
            "unique_id": f"franklinwh_{node}_{c['key']}",
            "object_id": f"franklinwh_{node}_{c['key']}",
            "state_topic": state_topic,
            "value_template": "{{ value_json.%s }}" % c["state_key"],
            "command_topic": cmd_topic,
            "availability_topic": avail_topic,
            "device": device,
        }
        if c["ha_type"] == "select":
            cfg["options"] = c["options"]
        if c["ha_type"] == "switch":
            # The state JSON carries a bool; HA needs the payloads spelled out.
            cfg["payload_on"] = "ON"
            cfg["payload_off"] = "OFF"
            cfg["state_on"] = "True"
            cfg["state_off"] = "False"
        configs.append(
            (f"{discovery_prefix}/{c['ha_type']}/{node}/{c['key']}/config", cfg))

    return configs, state_topic, avail_topic


def command_topic_filter(node: str, prefix: str) -> str:
    """Wildcard the publisher subscribes to for inbound commands."""
    return f"{prefix}/{node}/control/+/set"


def key_from_command_topic(topic: str) -> str | None:
    """`…/control/<key>/set` -> `<key>`."""
    parts = topic.split("/")
    return parts[-2] if len(parts) >= 2 and parts[-1] == "set" else None
