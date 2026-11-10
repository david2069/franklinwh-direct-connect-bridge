# Sending data to Home Assistant over MQTT

[Developers Guide](index.md) · User guide: [Home Assistant and MQTT](../guide/home-assistant.md)

The bridge publishes each aGate to Home Assistant with
[MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery). There is
no custom integration. This page is the developer's view: the exact topics, the payloads,
the identity, and when things are published and removed. For setting it up and for the
list of entities, read the user guide's
[Home Assistant and MQTT](../guide/home-assistant.md) page. It is not repeated here.

Read from the code on `main` (0.5.2). Paths are relative to
`src/franklinwh_direct_connect_bridge/`. The sample payloads below were produced by
running `publish/entities.py` against the built-in mock gateway, with the serial
replaced.

---

## Settings

From `Settings` in `config.py`. The environment variable is the field name in upper
case.

| Setting | Default | Notes |
|---|---|---|
| `MQTT_ENABLED` | `false` | The add-on's `config.yaml` defaults it to `true` for new installs. |
| `MQTT_HOST`, `MQTT_PORT` | `core-mosquitto`, `1883` | As an add-on, `ha_supervisor.apply_supervisor_mqtt()` fills unset broker details from the Supervisor. |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | empty | |
| `MQTT_PREFIX` | `franklinwh-local` | The base of the state, availability and command topics. Needs a restart to change. |
| `HA_DISCOVERY_PREFIX` | `homeassistant` | Needs a restart to change. |

**`publish_ha` is per gateway.** It is a field of the gateway (`state.py`, stored with a
database default of on). A gateway created over the API as a mock defaults to off
(`app.py`, gateway create). With `publish_ha` off, the gateway is still polled and
recorded, but its poller never starts a publisher (`run_gateway()` in `poller.py`).

**One MQTT client per gateway.** `MqttPublisher` in `publish/mqtt_publisher.py` uses the
client id `franklinwh-direct-connect-bridge-<node>`.

---

## Topic layout

All topics come from `discovery_configs()` and `command_topic_filter()` in
`publish/entities.py`. `<node>` is the node id (next section).

| Purpose | Topic | Retained | Payload |
|---|---|---|---|
| Discovery, sensors | `homeassistant/sensor/<node>/<key>/config` | yes | JSON config |
| Discovery, controls | `homeassistant/<select\|switch>/<node>/<key>/config` | yes | JSON config |
| State | `franklinwh-local/<node>/state` | yes | One JSON object, every entity's value |
| Availability | `franklinwh-local/<node>/availability` | yes | `online` or `offline` |
| Commands in | `franklinwh-local/<node>/control/<key>/set` | — | `ON`/`OFF`, or a mode name |

There is **one state topic per gateway**. Each entity's discovery config picks its own
field out with `value_template: "{{ value_json.<key> }}"`.

**Availability is per gateway.** There is no bridge-wide availability topic.

- The publisher sets a last will of `offline`, retained (`will_set` in
  `MqttPublisher.__init__`), so a lost connection marks the gateway unavailable.
- It publishes `online` on start.
- After each poll it publishes `online` if the poll succeeded and `offline` if not
  (`publish_availability(bool(summ.get("ok")))` in `poller.py`).
- On a clean stop it publishes `offline`.
- The discovery configs do not set `payload_available` or `payload_not_available`, so
  Home Assistant's defaults (`online`/`offline`) apply.

**QoS.** The publisher passes no QoS, so paho's default of 0 applies. The purge (below)
uses QoS 1.

---

## Identity

**The node id is the gateway's serial, lower-cased.** `_resolve_identity()` in
`poller.py` reads the firmware manifest and sets `node = (serial or "agate").lower()`.
Discovery waits until the serial is known; nothing is published under `agate`, because
that would leave an orphan device (comment in `run_gateway()`).

From the node id:

| Field | Value | Source |
|---|---|---|
| `unique_id`, `object_id` | `franklinwh_<node>_<key>` | `discovery_configs()` |
| `device.identifiers` | `["franklinwh_<node>"]` | `device_info()` |
| `device.name` | `FranklinWH Direct <last 8 characters of the serial>` | `device_name()` |
| `device.manufacturer` | `FranklinWH Technologies Co., Ltd` | `MANUFACTURER` |
| `device.model` | the model from the device database, else `aGate`; `aGate (mock)` for a mock | `device_info()` |
| `device.sw_version` | `Direct Connect Bridge v<bridge version>` | `device_info()` |
| `device.hw_version` | `aGate <firmware>`, when known | `device_info()` |
| `device.serial_number` | the serial, when known | `device_info()` |

`identifiers` is Home Assistant's identity for the device. The code warns against
changing it: a new value creates a second device and orphans every entity. The `name` is
a label and is safe to change. The `Direct Connect Bridge` prefix of `sw_version` is how
the bridge recognises its own entities on a broker it shares with other FranklinWH
software (`mqtt_scan.py`, and the setup checks).

!!! note "Planned: `fwh_dc` identity (#92)"
    Moving the MQTT prefix, device identifiers and `unique_id`s to an `fwh_dc` prefix is
    decided but not built (#92, open). It will ship as its own release with a migration.
    Until then, the `franklinwh_` and `franklinwh-local` forms above are current.

---

## Sample payloads

Discovery config for State of Charge, on
`homeassistant/sensor/<serial>/soc/config`:

```json
{
  "name": "State of Charge",
  "unique_id": "franklinwh_<serial>_soc",
  "object_id": "franklinwh_<serial>_soc",
  "state_topic": "franklinwh-local/<serial>/state",
  "value_template": "{{ value_json.soc }}",
  "availability_topic": "franklinwh-local/<serial>/availability",
  "device": {
    "identifiers": ["franklinwh_<serial>"],
    "name": "FranklinWH Direct <SERIAL_LAST8>",
    "manufacturer": "FranklinWH Technologies Co., Ltd",
    "model": "aGate",
    "sw_version": "Direct Connect Bridge v0.5.2",
    "hw_version": "aGate <FIRMWARE>",
    "serial_number": "<SERIAL>"
  },
  "unit_of_measurement": "%",
  "device_class": "battery",
  "state_class": "measurement",
  "suggested_display_precision": 1
}
```

Discovery config for the Operating Mode select, on
`homeassistant/select/<serial>/operating_mode/config`. The `device` block is the same as
above:

```json
{
  "name": "Operating Mode",
  "unique_id": "franklinwh_<serial>_operating_mode",
  "object_id": "franklinwh_<serial>_operating_mode",
  "state_topic": "franklinwh-local/<serial>/state",
  "value_template": "{{ value_json.mode }}",
  "command_topic": "franklinwh-local/<serial>/control/operating_mode/set",
  "availability_topic": "franklinwh-local/<serial>/availability",
  "device": { "...": "as above" },
  "options": ["Time-of-Use", "Self-Consumption", "Emergency Backup"]
}
```

State, on `franklinwh-local/<serial>/state`. This is from the mock gateway; the values
are synthetic, and some keys are left out for length:

```json
{
  "soc": 82.1,
  "grid_w": -1742.9,
  "solar_w": 4372.2,
  "battery_w": -2042.7,
  "load_w": 586.6,
  "generator_w": 0.0,
  "mode": "Self-Consumption",
  "run_status": 1,
  "run_status_desc": "Charging",
  "off_grid": false,
  "latency_ms": 0.5,
  "solar_today_kwh": 6.54,
  "grid_import_today_kwh": 0.0,
  "grid_export_today_kwh": 0.0,
  "battery_charge_today_kwh": 2.94,
  "battery_discharge_today_kwh": 2.43,
  "load_today_kwh": 6.94,
  "ambient_temp_c": 23.3,
  "circuit_1_on": true,
  "circuit_2_on": true,
  "circuit_3_on": false,
  "battery_status": "charging",
  "kwh_sun": 6.54
}
```

`state_payload()` in `publish/entities.py` starts from the poll's raw `power` dict and
adds the names the discovery templates read. So the payload carries more keys than there
are entities. Raw keys such as `kwh_sun` sit beside their entity-named copies such as
`solar_today_kwh`. The bridge's own UI reads the raw ones back. On a real aGate the
`net_*` diagnostic keys are merged in too. They are read every 600 seconds, not every
poll (`NET_EVERY_S` in `poller.py`), and never for a mock.

`battery_status` is derived: negative `battery_w` is `charging`, positive is
`discharging`, zero is `standby`.

---

## When things are published

- **Discovery:** on publisher start, every enabled entity's config, retained
  (`MqttPublisher.start()` → `publish_discovery()`).
- **State and availability:** after **every poll**, changed or not, every
  `poll_interval` seconds (30 by default; `poller.py`).
- **On a failed poll:** the state is still published, built from the failed poll's
  summary, and then availability goes `offline`. Home Assistant shows the entities as
  unavailable, so the stale payload is not displayed. This is read from `poller.py` and
  was not observed live.

---

## Entity groups

`GROUPS` in `publish/entities.py` has five groups, all on by default: `core`, `power`,
`energy`, `diagnostic` and `controls`. The setting is **one list for all gateways**,
stored as `mqtt_groups` in the bridge's config.

`PUT /api/mqtt/groups` changes it and asks every gateway to republish. The poller then
calls `rebuild_discovery()`, which first publishes an empty retained payload to each old
config topic and then publishes the new set. A disabled group's entities therefore
disappear from Home Assistant.

`ENTITIES` lists 29 sensors and `CONTROLS` lists 4 controls (one select, three
switches). A mock gateway skips the 12 `net_*` network sensors, which leaves 21.
Entities in the `diagnostic` group carry `entity_category: diagnostic`.

---

## Command topics

The publisher subscribes to `franklinwh-local/<node>/control/+/set` on **every**
connect, not only the first (`_on_connect` in `mqtt_publisher.py`). The key is the
second-to-last topic segment (`key_from_command_topic()`).

`_on_control()` in `poller.py` passes the command to `publish.handle_command()`:

- `operating_mode`: the payload is a mode name from `MODE_OPTIONS`, mapped through
  `MODE_ALIAS` (`Self-Consumption` → `self`) and written with `client.set_mode()`.
- `smart_circuit_<n>`: `ON` switches the circuit on and anything else switches it off,
  with `client.set_smart_circuit()`.

!!! warning "No confirm on MQTT"
    `_on_control()` checks `client.writes_enabled()`, which always returns `True` (see
    [REST API: write safety](rest-api.md#write-safety)). The REST route for a mode change
    needs `confirm=true`; the MQTT route has no equivalent. Anything that can publish to
    your broker can change the operating mode and the smart circuits.

---

## Removing what was published

Retained messages stay on the broker until something replaces them with an empty
payload. The bridge does this in four places:

| Trigger | What runs | What it clears |
|---|---|---|
| Group disabled | `MqttPublisher.rebuild_discovery()` → `clear_discovery()` | The old configs, then republishes the rest. QoS 0, not verified. |
| **Clear HA** in the UI | `clear_discovery()` | The current configs. QoS 0, not verified. |
| `POST /api/mqtt/unpublish` | sets `publish_ha` off, stops the poller, then `publish/purge.py` `purge()` | Every topic the node could own. Verified. |
| Gateway restarts with `publish_ha` off | `purge()` from `run_gateway()` | The same. Verified. |

`purge()` in `publish/purge.py` is the careful one. `topics_for()` builds the full list
of topics for the node from the bridge's own entity table, every group's discovery
configs plus the state and availability topics, never from a broker wildcard. `purge()`
then:

1. reads back which of them hold a retained message;
2. publishes an empty retained payload, QoS 1, to each one;
3. reads back again, and returns `{ok, found, removed, left}`. `dry_run` is supported.

**Deleting a gateway does not purge it.** `DELETE /api/gateways/{id}` leaves its
retained topics. They become orphans, which `GET /api/mqtt/orphans` finds and
`POST /api/mqtt/orphans/purge?expect=N&confirm=true` removes (`mqtt_scan.purge_orphans`).
Unpublish first if you mean to delete a gateway.

I found no code that purges anything when MQTT is switched off globally. This is not
confirmed; check before relying on it.

---

## `publish/network.py`

Not a separate device. `network_state()` turns the aGate's connectivity, interface,
switch and cloud reads into the `net_*` keys, which are merged into the same gateway's
state payload. Its docstring says it deliberately publishes no MAC address, IP address,
SSID or credentials.
