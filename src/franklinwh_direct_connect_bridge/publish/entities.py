"""Home Assistant entity definitions + discovery-payload builders (pure functions).

One JSON state topic per device; each sensor's discovery config uses a value_template to
pull its field. Availability is a separate topic driven by the health round-trip / LWT.
"""

from __future__ import annotations

from typing import Any

# The manufacturer as the Modbus Bridge publishes it, so the two bridges' HA devices
# read the same (#140). Display only — not part of any identifier.
MANUFACTURER = "FranklinWH Technologies Co., Ltd"

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
    # aGate network (#134) — read every few minutes, not every poll. Diagnostic card.
    {"key": "net_in_use", "name": "Network In Use", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_available", "name": "Networks Available", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_write_safety", "name": "Network Write Safety", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_fallback", "name": "Network Fallback", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_wifi_signal", "name": "WiFi Signal", "unit": "%", "device_class": None, "state_class": "measurement", "group": "diagnostic"},
    {"key": "net_4g_signal", "name": "4G Signal", "unit": None, "device_class": None, "state_class": "measurement", "group": "diagnostic"},
    {"key": "net_if_eth0", "name": "Ethernet 0", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_if_eth1", "name": "Ethernet 1", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_if_wifi", "name": "WiFi Link", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_if_4g", "name": "4G Link", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_cloud", "name": "Cloud Connection", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    {"key": "net_cloud_endpoint", "name": "Cloud Endpoint", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    # From reads every poll already makes (#386 batch 1). Slugs follow the Modbus Bridge
    # where it has the entity, else FWHAI.
    {"key": "status_grid_status", "name": "Grid Status", "unit": None, "device_class": "enum", "state_class": None, "group": "core",
     "options": ["Connected", "SimulatedOffGrid", "Outage", "OffGrid"]},
    {"key": "active_reserve_pct", "name": "Active Reserve SOC", "unit": "%", "device_class": None, "state_class": "measurement", "group": "core"},
    {"key": "device_firmware", "name": "Firmware Version", "unit": None, "device_class": None, "state_class": None, "group": "diagnostic"},
    # 1707 relays. Named as the Solar tab names them: which physical relay FWHAI's cloud
    # "Grid Relay 1" is has not been checked, so its slugs are not borrowed.
    {"key": "relay_main1", "name": "Main Relay 1", "ha_type": "binary_sensor", "unit": None, "device_class": "power", "state_class": None, "group": "diagnostic"},
    {"key": "relay_main2", "name": "Main Relay 2", "ha_type": "binary_sensor", "unit": None, "device_class": "power", "state_class": None, "group": "diagnostic"},
    {"key": "relay_grid2", "name": "Grid Relay 2", "ha_type": "binary_sensor", "unit": None, "device_class": "power", "state_class": None, "group": "diagnostic"},
    {"key": "relay_black_start", "name": "Black Start Relay", "ha_type": "binary_sensor", "unit": None, "device_class": "power", "state_class": None, "group": "diagnostic"},
]

#: 1707 field -> relay entity key. raw 1 is FranklinWH's "OPEN", which is conducting
#: (solar.py _relay; mainRelay1Status read 0 through a real island, docs/OFFGRID_DESIGN.md).
RELAY_KEYS = {"mainRelay1Status": "relay_main1", "mainRelay2Status": "relay_main2",
              "gridRelay2": "relay_grid2", "blackStartRelay": "relay_black_start"}

#: off_grid_kind (client._off_grid_kind) -> Grid Status. FWHAI's values. "Outage" means
#: islanded with no request we know about; a real outage has not been measured yet
#: (docs/OFFGRID_DESIGN.md §3). "OffGrid" is islanded when 1723 could not be read.
GRID_STATUS = {"simulated": "SimulatedOffGrid", "outage": "Outage", None: "OffGrid"}

#: The three operating work modes. HA shows these names; the bridge maps the
#: chosen one to the stable `scheduling_type` alias, never to the site-specific
#: programme id or the tariff name.
MODE_OPTIONS = ["Time-of-Use", "Self-Consumption", "Emergency Backup"]
MODE_ALIAS = {"Time-of-Use": "tou", "Self-Consumption": "self",
              "Emergency Backup": "backup"}

#: WRITABLE entities. Only hardware-verified writes appear here — an HA control
#: that silently does nothing is worse than no control. Smart-circuit schedules are
#: deliberately absent: the gateway discards them. Reserve SoC is here only because it
#: is written through the cloud (C2), where it sticks.
CONTROLS: list[dict[str, Any]] = [
    {"key": "operating_mode", "name": "Operating Mode", "ha_type": "select",
     "options": MODE_OPTIONS, "state_key": "mode"},
    {"key": "smart_circuit_1", "name": "Smart Circuit 1", "ha_type": "switch",
     "state_key": "circuit_1_on", "circuit": 1},
    {"key": "smart_circuit_2", "name": "Smart Circuit 2", "ha_type": "switch",
     "state_key": "circuit_2_on", "circuit": 2},
    {"key": "smart_circuit_3", "name": "Smart Circuit 3", "ha_type": "switch",
     "state_key": "circuit_3_on", "circuit": 3},
    # Reserve SoC per mode (C2, docs/MQTT_CONTROLS_PLAN.md). The aGate discards a local
    # reserve write, so these write through the cloud provider and are published only
    # when it is set up for this gateway. Their state is the local 1726 read every poll
    # already makes. Names follow the Modbus Bridge's. No Emergency Backup number: that
    # mode's reserve is fixed at 100 % and can't be changed, so a control would do nothing.
    {"key": "reserve_soc_tou", "name": "TOU Reserve SOC", "ha_type": "number",
     "state_key": "reserve_tou_pct", "reserve_mode": "tou"},
    {"key": "reserve_soc_self", "name": "Self-Consumption Reserve SOC", "ha_type": "number",
     "state_key": "reserve_self_pct", "reserve_mode": "self"},
]

#: The reserve controls, left out of discovery unless the cloud can write this gateway.
RESERVE_KEYS = frozenset(c["key"] for c in CONTROLS if c.get("reserve_mode"))

#: 1726 scheduling_type (== cloud workMode) -> the reserve control's mode.
RESERVE_WORKMODE = {1: "tou", 2: "self"}

#: The bridge's own health (#271, shared alert spec §6). Published for every gateway
#: device whatever the groups, on its own topic, and WITHOUT the gateway's availability
#: topic: "Bridge problem" has to stay readable exactly when the aGate is unreachable.
BRIDGE_ENTITIES: list[dict[str, Any]] = [
    {"key": "bridge_problem", "name": "Bridge problem", "ha_type": "binary_sensor",
     "device_class": "problem"},
]

#: Seconds between heartbeats; also how often a gateway re-publishes its problem state.
HEARTBEAT_EVERY_S = 60

#: The BRIDGE's own Home Assistant node, apart from any gateway: one "Bridge heartbeat"
#: per bridge (spec §11 — it proves the process and its alert monitor are alive, so it
#: must not depend on a gateway or a poller). `fwh_dc` per the identity plan (#92).
BRIDGE_NODE = "fwh_dc_bridge"


def alerts_topic(node: str, prefix: str) -> str:
    return f"{prefix}/{node}/alerts"


def heartbeat_topic(prefix: str) -> str:
    return f"{prefix}/{BRIDGE_NODE}/heartbeat"


def bridge_device_info() -> dict[str, Any]:
    from .. import __version__
    # sw_version keeps the "Direct Connect Bridge" prefix: mqtt_scan decides ownership by it.
    return {"identifiers": [f"franklinwh_{BRIDGE_NODE}"],
            "name": "FranklinWH Direct Connect Bridge", "manufacturer": MANUFACTURER,
            "model": "Direct Connect Bridge",
            "sw_version": f"Direct Connect Bridge v{__version__}"}


def heartbeat_config(prefix: str, discovery_prefix: str) -> tuple[str, dict[str, Any]]:
    """(config_topic, payload) for the single bridge-level "Bridge heartbeat" sensor."""
    return (f"{discovery_prefix}/sensor/{BRIDGE_NODE}/heartbeat/config", {
        "name": "Bridge heartbeat",
        "unique_id": f"franklinwh_{BRIDGE_NODE}_heartbeat",
        "object_id": f"franklinwh_{BRIDGE_NODE}_heartbeat",
        "state_topic": heartbeat_topic(prefix),
        "device_class": "timestamp",
        "entity_category": "diagnostic",
        "device": bridge_device_info(),
    })


def bridge_problem_config(prefix: str, discovery_prefix: str) -> tuple[str, dict[str, Any]]:
    """(config_topic, payload) for the bridge-level "Bridge problem" (#286, spec v1.2): ALL
    open alerts, every gateway's included, on the bridge's own device. A gateway that
    never answered has no device of its own, so its alerts showed on no sensor."""
    topic = alerts_topic(BRIDGE_NODE, prefix)
    return (f"{discovery_prefix}/binary_sensor/{BRIDGE_NODE}/bridge_problem/config", {
        "name": "Bridge problem",
        "unique_id": f"franklinwh_{BRIDGE_NODE}_bridge_problem",
        "object_id": f"franklinwh_{BRIDGE_NODE}_bridge_problem",
        "state_topic": topic,
        "device_class": "problem",
        "entity_category": "diagnostic",
        "device": bridge_device_info(),
        "value_template": "{{ 'ON' if value_json.problem else 'OFF' }}",
        "json_attributes_topic": topic,
        "json_attributes_template": ("{{ {'level': value_json.level, 'open': value_json.open,"
                                     " 'alerts': value_json.alerts} | tojson }}"),
    })


def heartbeat_payload(now: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(now, _dt.timezone.utc).isoformat(timespec="seconds")


def alerts_payload(summary: dict, open_alerts: list[dict],
                   gateway_id: str | None = "") -> dict[str, Any]:
    """The JSON on alerts_topic: the problem flag and the open alerts (this gateway's
    and the bridge-wide ones) as the binary_sensor's attributes. ``gateway_id=None`` is
    the bridge-level sensor: every open alert (#286)."""
    mine = (list(open_alerts) if gateway_id is None
            else [a for a in open_alerts if a.get("gateway_id") in ("", gateway_id)])
    return {
        "problem": bool(mine),
        "level": summary.get("level", "ok"),
        "open": len(mine),
        "alerts": [{k: a.get(k) for k in ("id", "code", "severity", "kind", "title",
                                          "opened_ts", "resolved_ts", "acked_ts", "count")}
                   for a in mine],
    }


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


#: Raw poll key -> the key the Home Assistant entity's value_template reads.
_HA_KEYS = {
    "kwh_sun": "solar_today_kwh",
    "kwh_uti_in": "grid_import_today_kwh",
    "kwh_uti_out": "grid_export_today_kwh",
    "kwh_fhp_chg": "battery_charge_today_kwh",
    "kwh_fhp_di": "battery_discharge_today_kwh",
    "kwh_load": "load_today_kwh",
}


def state_payload(summary: dict) -> dict[str, Any]:
    """The MQTT state JSON the poller publishes, from one poll ``summary``.

    Every key an ENTITIES value_template reads must be in here. Before #96 the poller
    published the raw ``summary["power"]`` dict, while the templates read the names
    ``build_state`` produces, a function only the tests called. 8 of the 21 entities
    therefore never had a value. The raw keys stay: the bridge's own UI reads them back
    from ``gw.last_state``.
    """
    st = dict(summary.get("power") or {})
    st["latency_ms"] = summary.get("latency_ms")
    for raw, ha in _HA_KEYS.items():
        if raw in st:
            st[ha] = st[raw]
    t_amb = (summary.get("battery") or {}).get("t_amb")
    if t_amb is not None:
        st["ambient_temp_c"] = t_amb
    for n, on in (summary.get("circuits_on") or {}).items():
        st[f"circuit_{n}_on"] = bool(on)        # the switches' state_key (C1)
    og = st.get("off_grid")
    if og is not None:
        st["status_grid_status"] = (GRID_STATUS.get(st.get("off_grid_kind"), "OffGrid")
                                    if og else "Connected")
    active = next((m for m in (summary.get("mode") or {}).get("modes") or []
                   if m.get("active")), None)
    if active and active.get("reserved_soc") is not None:
        st["active_reserve_pct"] = active["reserved_soc"]
    for m in (summary.get("mode") or {}).get("modes") or []:
        mode = RESERVE_WORKMODE.get(m.get("workmode"))
        if mode and m.get("reserved_soc") is not None:
            st[f"reserve_{mode}_pct"] = m["reserved_soc"]
    fw = (summary.get("firmware") or {}).get("IBG_VER")
    if fw:
        st["device_firmware"] = fw
    for raw, key in RELAY_KEYS.items():
        v = (summary.get("relays") or {}).get(raw)
        if v is not None:
            st[key] = "ON" if int(v) == 1 else "OFF"
    bw = st.get("battery_w")
    if bw is not None:
        # Same convention as build_state: negative battery power is charging.
        st["battery_status"] = ("charging" if bw < 0 else "discharging" if bw > 0
                                else "standby")
    return st


def display_precision(e: dict) -> int | None:
    """Decimals HA should SHOW for a numeric sensor. A real aGate reports SoC as
    99.789474; HA displayed every digit (#114). None for text sensors."""
    unit = e.get("unit")
    if e["key"] == "soc" or unit == "°C":
        return 1
    if unit == "W" or unit == "ms":
        return 0
    if unit == "kWh":
        return 2
    return None


def device_name(serial: str) -> str:
    """The Home Assistant DEVICE name: ``FranklinWH Direct <last 8 of serial>``.

    The name used to be the fixed string "FranklinWH aGate (Local Bridge)", so on a
    multi-gateway site every gateway produced a device with the SAME name and the only
    way to tell them apart in Home Assistant was to open each one.

    Changing ``name`` is safe; changing ``identifiers`` is not. Home Assistant keys a
    device on its identifiers, so a renamed device is the same device with a new label —
    entities, their ids and their history all survive. (The identifiers are deliberately
    untouched below.)
    """
    tail = (serial or "")[-8:]
    return f"FranklinWH Direct {tail}" if tail else "FranklinWH Direct Connect"


def device_info(node: str, serial: str, firmware: str | None = None, *,
                model: str | None = None, is_mock: bool = False) -> dict[str, Any]:
    from .. import __version__
    # DO NOT change `identifiers`. They are Home Assistant's device IDENTITY: a new value
    # creates a SECOND device and orphans every entity already discovered. The `name`
    # beside it is only a label and is safe to change — see device_name().
    #
    # The other fields are labels too, laid out as the Modbus Bridge does (#140): the
    # BRIDGE's version as "Firmware" (sw_version) and the aGate's firmware as "Hardware"
    # (hw_version). sw_version still identifies THIS integration on a broker shared with
    # the Modbus bridge and FWHAI — mqtt_scan and the setup checks decide ownership from
    # its "Direct Connect Bridge" prefix — so the prefix must stay.
    d = {
        "identifiers": [f"franklinwh_{node}"],
        "name": device_name(serial),
        "manufacturer": MANUFACTURER,
        "model": "aGate (mock)" if is_mock else (model or "aGate"),
        "sw_version": f"Direct Connect Bridge v{__version__}",
    }
    if firmware:
        d["hw_version"] = f"aGate {firmware}"
    if serial:
        d["serial_number"] = serial
    return d


#: Keys that only a REAL gateway has a source for (the emulator models no network, #134).
NETWORK_KEYS = frozenset(e["key"] for e in ENTITIES if e["key"].startswith("net_"))
#: ...nor the 1707 relays (#386). A mock gateway publishes none of these.
MOCK_ABSENT_KEYS = NETWORK_KEYS | frozenset(RELAY_KEYS.values()) | RESERVE_KEYS


def discovery_configs(node: str, device: dict, prefix: str, discovery_prefix: str, groups=None,
                      *, skip: frozenset | set = frozenset()):
    """Return (list[(config_topic, config_payload)], state_topic, availability_topic)."""
    state_topic = f"{prefix}/{node}/state"
    avail_topic = f"{prefix}/{node}/availability"
    configs = []
    enabled = _enabled(groups)
    for e in ENTITIES:
        if e.get("group", "core") not in enabled or e["key"] in skip:
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
        if e.get("options"):
            cfg["options"] = e["options"]
        if e.get("group") == "diagnostic":
            # HA files these under the device page's "Diagnostic" card, as the Modbus
            # Bridge does (#121). A display category, not identity: ids are unchanged.
            cfg["entity_category"] = "diagnostic"
        prec = display_precision(e)
        if prec is not None:
            # Display only: HA keeps the full value in history and statistics (#114).
            cfg["suggested_display_precision"] = prec
        ha_type = e.get("ha_type", "sensor")
        configs.append((f"{discovery_prefix}/{ha_type}/{node}/{e['key']}/config", cfg))

    # Controls. Each gets its own command topic; the publisher subscribes to
    # `<prefix>/<node>/control/+/set` and routes by the key in the topic.
    for c in CONTROLS if "controls" in enabled else []:
        if c["key"] in skip:
            continue
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
        if c["ha_type"] == "number":
            cfg.update({"min": 0, "max": 100, "step": 1, "unit_of_measurement": "%",
                        "mode": "box"})
        if c["ha_type"] == "switch":
            # The state JSON carries a bool; HA needs the payloads spelled out.
            cfg["payload_on"] = "ON"
            cfg["payload_off"] = "OFF"
            cfg["state_on"] = "True"
            cfg["state_off"] = "False"
        configs.append(
            (f"{discovery_prefix}/{c['ha_type']}/{node}/{c['key']}/config", cfg))

    a_topic = alerts_topic(node, prefix)
    for b in BRIDGE_ENTITIES:
        if b["key"] in skip:
            continue
        cfg = {
            "name": b["name"],
            "unique_id": f"franklinwh_{node}_{b['key']}",
            "object_id": f"franklinwh_{node}_{b['key']}",
            "state_topic": a_topic,
            "device_class": b["device_class"],
            "entity_category": "diagnostic",
            "device": device,
        }
        cfg["value_template"] = "{{ 'ON' if value_json.problem else 'OFF' }}"
        cfg["json_attributes_topic"] = a_topic
        cfg["json_attributes_template"] = (
            "{{ {'level': value_json.level, 'open': value_json.open,"
            " 'alerts': value_json.alerts} | tojson }}")
        configs.append(
            (f"{discovery_prefix}/{b['ha_type']}/{node}/{b['key']}/config", cfg))

    return configs, state_topic, avail_topic


def command_topic_filter(node: str, prefix: str) -> str:
    """Wildcard the publisher subscribes to for inbound commands."""
    return f"{prefix}/{node}/control/+/set"


def key_from_command_topic(topic: str) -> str | None:
    """`…/control/<key>/set` -> `<key>`."""
    parts = topic.split("/")
    return parts[-2] if len(parts) >= 2 and parts[-1] == "set" else None
