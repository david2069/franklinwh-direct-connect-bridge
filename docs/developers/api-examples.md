# Worked examples: the OpenAPI schema and MQTT discovery

[Developers Guide](index.md) · [REST API and OpenAPI](rest-api.md) · [MQTT](mqtt.md)

Two ways for another program to work with the Bridge, end to end:

1. **[REST, from the OpenAPI schema](#1-rest-from-the-openapi-schema):** discover what the
   API offers, then read and control your aGate with plain HTTP.
2. **[MQTT, through Home Assistant discovery](#2-mqtt-through-home-assistant-discovery):**
   read the aGate's values and send commands on a broker, the same way Home Assistant does.

!!! info "Where the output on this page came from"
    Every command and response below was run on 2026-11-19 against Bridge **0.5.53**
    (`/api/version` reported `source_sha` `unknown`, a build from a `git archive` of the
    `docs/use-cases` branch). It ran as a fresh pip install on macOS, with Security on as for
    any new install, pointed at the library's emulator
    (`franklinwh-direct-connect emulate --seed 7`) and a throwaway MQTT broker, all on
    loopback. **The values are synthetic.** The emulator stores a mode write and reads it back,
    so a read-back here does not prove what a real aGate does. That the aGate applies a
    local mode write is recorded as hardware-verified in the README. Hosts, serials and
    tokens are replaced with placeholders.

---

## 1. REST, from the OpenAPI schema

### Before you start: a token and the certificate

A new install has Security on. API calls then go to the **HTTPS port** with a token; the
plain port redirects there (`307`). As an admin, in **Settings → Admin → Security**:

1. **Accounts → add** an account with the role **api** (no password). It can read
   everything and send battery commands.
2. **API tokens → + New token** for that account. Copy the token (it starts `fwhdc_`); it
   is shown once.
3. **Download certificate**, so your client can check the Bridge's self-signed certificate
   rather than skip the check.

To read the schema, also make a token for a **viewer** account (it needs a password of 8
characters or more). See the warning below.

```bash
export BRIDGE=https://<bridge-host>:8102
export TOKEN=fwhdc_…            # the api account's token
export VIEW_TOKEN=fwhdc_…       # a viewer account's token, for the schema
export CA=franklinwh-bridge.crt # the downloaded certificate
```

!!! warning "An api token can't read the schema yet"
    `GET /openapi.json`, `/docs` and `/redoc` answer **403** "Your role (api) can't do
    this." to an **api** token ([#781](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/781)). The role rules treat every path outside `/api/` as a web
    page, and api accounts have no pages (`security.required()`). A **viewer** token, or a
    signed-in browser, gets them. Use a viewer token to fetch the schema and the api
    token for everything else.

With Security off (an upgraded install), leave out the token and the certificate and use
the plain port: `export BRIDGE=http://<bridge-host>:8101`.

### Step 1: fetch the schema

```bash
curl -s --cacert "$CA" -H "Authorization: Bearer $VIEW_TOKEN" \
     "$BRIDGE/openapi.json" -o openapi.json

jq '{title: .info.title, version: .info.version, openapi,
     paths: (.paths | length),
     operations: ([.paths[] | keys[] | select(. != "parameters")] | length)}' openapi.json
```

```json
{
  "title": "franklinwh-direct-connect-bridge",
  "version": "0.5.53",
  "openapi": "3.1.0",
  "paths": 277,
  "operations": 315
}
```

The same token opens **Swagger UI** at `$BRIDGE/docs` and **ReDoc** at `$BRIDGE/redoc` in a
browser that is signed in.

### Step 2: find an endpoint and what it takes

Search the paths:

```bash
jq -r '.paths | to_entries[] | select(.key | test("summary")) | .key as $p
       | .value | to_entries[] | "\(.key | ascii_upcase) \($p)  \(.value.summary)"' openapi.json
```

```text
GET /api/summary  Api Summary
GET /api/gateways/{gw_id}/summary  Api Gateway Summary
```

Look at what a write needs, here the operating mode:

```bash
jq '.paths["/api/mode"].post | {parameters: [.parameters[] | {name, in, required}],
     body: .requestBody.content["application/json"].schema}' openapi.json
jq -c '.components.schemas.ModeReq' openapi.json
```

```json
{
  "parameters": [{ "name": "gateway", "in": "query", "required": false }],
  "body": { "$ref": "#/components/schemas/ModeReq" }
}
{"properties":{"mode":{"type":"string","title":"Mode"},"confirm":{"type":"boolean","title":"Confirm","default":false}},"type":"object","required":["mode"],"title":"ModeReq"}
```

Any OpenAPI 3.1 tool can read the same file, for example to generate a client.

### Step 3: find your gateway and read it

```bash
curl -s --cacert "$CA" -H "Authorization: Bearer $TOKEN" "$BRIDGE/api/gateways" \
  | jq -c '.[] | {id, label, is_default, publish_ha}'
```

```json
{"id":"<gateway-id>","label":"<label>","is_default":true,"publish_ha":true}
```

```bash
export GW=<gateway-id>
curl -s --cacert "$CA" -H "Authorization: Bearer $TOKEN" "$BRIDGE/api/summary?gateway=$GW" \
  | jq '{ok, cached, soc: .power.soc, solar_w: .power.solar_w, battery_w: .power.battery_w,
         grid_w: .power.grid_w, load_w: .power.load_w,
         mode: (.mode.modes[] | select(.active) | .name), latency_ms}'
```

```json
{
  "ok": true,
  "cached": true,
  "soc": 26.6,
  "solar_w": 0.0,
  "battery_w": 828.3,
  "grid_w": 276.1,
  "load_w": 1104.4,
  "mode": "Time-of-Use",
  "latency_ms": 1.2
}
```

`/api/summary` is the poller's cached copy (`"cached": true`), so reading it costs the aGate
nothing. Name the gateway on every call that acts on an aGate.

### Step 4: change something, safely

A write that changes the gateway needs `"confirm": true`. Without it the Bridge refuses:

```bash
curl -s --cacert "$CA" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
     -d '{"mode":"Self-Consumption"}' "$BRIDGE/api/mode?gateway=$GW"
```

```text
HTTP 428  {"detail":"'set operating mode' changes the physical gateway — re-send with confirm=true."}
```

```bash
curl -s --cacert "$CA" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
     -d '{"mode":"Self-Consumption","confirm":true}' "$BRIDGE/api/mode?gateway=$GW"
```

```text
HTTP 200  {"ok":true,"result":0,"current_id_before":29287,"current_id_after":85232}
```

The summary showed the new mode after the next poll, about 20 seconds later here.

!!! warning "Not every write asks for confirm"
    Battery force and release (`POST /api/battery/command`), `POST /api/dispatch`, smart
    circuits, reserve SoC and creating a schedule are **not** confirm-gated. Read
    [Write safety](rest-api.md#write-safety) before you automate a write.

### What a refusal looks like

All observed in the same run:

| Request | Answer |
|---|---|
| A wrong or expired token | `401` "Invalid or expired API token." |
| A viewer token sending a mode change | `403` "Your role (viewer) can't do this." |
| An unknown gateway id | `404` "unknown gateway 'nope'" |
| A mode change without `confirm` | `428`, as above |

### The same in Python

Standard library only, run against the same Bridge:

```python
"""Read the Bridge's live summary with an API token (standard library only)."""
import json, os, ssl, urllib.request

BRIDGE = os.environ["BRIDGE"]             # e.g. https://bridge.local:8102
TOKEN = os.environ["BRIDGE_TOKEN"]        # fwhdc_…
CA = os.environ.get("BRIDGE_CA", "franklinwh-bridge.crt")

ctx = ssl.create_default_context(cafile=CA)

def get(path):
    req = urllib.request.Request(BRIDGE + path, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, context=ctx) as r:
        return json.load(r)

for gw in get("/api/gateways"):
    s = get(f"/api/summary?gateway={gw['id']}")
    p = s["power"]
    mode = next(m["name"] for m in s["mode"]["modes"] if m["active"])
    print(f"{gw['label']}: SoC {p['soc']}%  solar {p['solar_w']} W  "
          f"battery {p['battery_w']} W  grid {p['grid_w']} W  mode {mode}")
```

```text
<label>: SoC 26.5%  solar 0.0 W  battery 793.3 W  grid 264.4 W  mode Time-of-Use
```

---

## 2. MQTT, through Home Assistant discovery

With MQTT on, the Bridge publishes each aGate to the broker as a Home Assistant device.
Home Assistant builds the device from the **discovery** messages; any other MQTT client can
read the same topics and send the same commands. No token is involved: access is whatever
your broker allows.

### Step 1: see what is published

```bash
mosquitto_sub -h <broker> -u <user> -P <password> -v -t 'homeassistant/#' -t 'franklinwh-local/#'
```

In the run, the broker held **66 discovery configs** (53 sensors, 8 binary sensors, 1
select, 4 switches) and these other topics. `<node>` is the gateway's serial, lower-cased:

| Topic | Retained | What it carries |
|---|---|---|
| `franklinwh-local/<node>/state` | yes | One JSON object with every value (75 keys in the run) |
| `franklinwh-local/<node>/availability` | yes | `online` or `offline` |
| `franklinwh-local/<node>/alerts` | yes | `{"problem":false,"level":"ok","open":0,"alerts":[]}` |
| `franklinwh-local/<node>/control/<key>/set` | no | Commands **to** the Bridge |
| `franklinwh-local/fwh_dc_bridge/heartbeat` | yes | The Bridge's last heartbeat time |
| `franklinwh-local/fwh_dc_bridge/version` | yes | The Bridge version, install type and library versions |
| `franklinwh-local/fwh_dc_bridge/alerts` | yes | Bridge-wide alerts, same shape as above |

The controls are the **Operating Mode** select, **Go Off-Grid**, and one switch per smart
circuit.

### Step 2: read a discovery config and the state

The discovery config for State of Charge, on `homeassistant/sensor/<node>/soc/config`:

```json
{
  "name": "State of Charge",
  "unique_id": "franklinwh_<node>_soc",
  "object_id": "franklinwh_<node>_soc",
  "state_topic": "franklinwh-local/<node>/state",
  "value_template": "{{ value_json.soc }}",
  "availability_topic": "franklinwh-local/<node>/availability",
  "device": {
    "identifiers": ["franklinwh_<node>"],
    "name": "FranklinWH Direct <last 8 of serial>",
    "manufacturer": "FranklinWH Technologies Co., Ltd",
    "model": "aGate",
    "sw_version": "Direct Connect Bridge v0.5.53",
    "hw_version": "aGate <firmware>",
    "serial_number": "<serial>"
  },
  "unit_of_measurement": "%",
  "device_class": "battery",
  "state_class": "measurement",
  "suggested_display_precision": 1
}
```

Each config points at the shared state topic and picks its own field with
`value_template`. A few fields of the state, on `franklinwh-local/<node>/state`:

```json
{
  "soc": 26.7,
  "solar_w": 0.0,
  "battery_w": 829.5,
  "grid_w": 276.5,
  "load_w": 1106.0,
  "mode": "Self-Consumption",
  "run_status_desc": "Discharging",
  "off_grid": false,
  "battery_status": "discharging",
  "solar_today_kwh": 12.93,
  "load_today_kwh": 12.03,
  "circuit_1_on": true
}
```

To follow one value from a script, subscribe to the state topic and read the key:

```bash
mosquitto_sub -h <broker> -u <user> -P <password> -t 'franklinwh-local/<node>/state' \
  | jq --unbuffered '{soc, solar_w, mode}'
```

### Step 3: send a command

The Operating Mode select's config names its command topic and the options it accepts:

```json
{"name":"Operating Mode",
 "command_topic":"franklinwh-local/<node>/control/operating_mode/set",
 "options":["Time-of-Use","Self-Consumption","Emergency Backup"],
 "value_template":"{{ value_json.mode }}"}
```

Publish one of the options to it:

```bash
mosquitto_pub -h <broker> -u <user> -P <password> \
  -t 'franklinwh-local/<node>/control/operating_mode/set' -m 'Time-of-Use'
```

In the run, the state topic showed `"mode": "Time-of-Use"` about 10 seconds later. The smart
circuit and **Go Off-Grid** switches take `ON` and `OFF`.

!!! danger "MQTT commands have no confirm step"
    Unlike `POST /api/mode`, a command on MQTT is carried out at once. Anything that can
    publish to your broker can change the mode, switch circuits and take the site off-grid.
    Give the broker a username and password, and don't expose it outside your network.

### Step 4: use it in Home Assistant

Home Assistant creates the device and its entities from the discovery configs, with no
YAML. Use them like any other entity. This automation puts the aGate in Self-Consumption
at 21:00. Replace the entity id with yours, from **Settings → Devices & services →
MQTT → FranklinWH Direct …**:

```yaml
automation:
  - alias: "aGate: Self-Consumption at night"
    triggers:
      - trigger: time
        at: "21:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.franklinwh_direct_operating_mode   # replace with yours
        data:
          option: "Self-Consumption"
```

This automation was not run in Home Assistant for this page. The select publishes the
option to the command topic above, as in Step 3.

---

## Which one to use

| | REST | MQTT |
|---|---|---|
| Discover what exists | The OpenAPI schema | The discovery configs |
| Read | Any time, on request | Every poll, pushed to you |
| Access control | Accounts, roles and tokens | Your broker's own users |
| Write safety | `confirm` on consequential writes | None |
| Covers | Everything the UI does (315 operations) | The published entities and four controls |
