# MQTT shared-broker collision test

Dev-only, local-machine harness (not CI). Answers: *do the Local and Modbus bridges
collide when they share one MQTT broker + the same `homeassistant` discovery prefix?*

Stands up an isolated stack (own compose project `fwh-mqtt-test`, own broker on host port
**1890**, own bridge ports **8110**/**8111**) — mock gateways only, no real serials, never
touches the real `:8101`/`:8100` stacks:

- a shared `eclipse-mosquitto:2` broker,
- the **Local bridge** (`franklinwh-direct-connect-bridge:dev`) with a seeded mock aGate, MQTT on,
- the **real Modbus bridge** image (`franklinwh-modbus-bridge-app:latest`), mock gateway
  registered post-boot via its API.

Then it enumerates the retained discovery + live state topics and prints a verdict.

## Prerequisites (local images + the modbus source)

- `franklinwh-direct-connect-bridge:dev` — build with `tools/build_image.sh`.
- `franklinwh-modbus-bridge-app:latest` — the Modbus bridge image.
- `MODBUS_SRC` — path to your `franklinwh-modbus-bridge/src` (the Modbus service live-mounts
  it for import parity). `run.sh` auto-detects `~/dev/Claude/Projects/franklinwh-modbus-bridge/src`
  and `~/dev/franklinwh-modbus-bridge/src`; otherwise export it yourself.

## Run

```sh
test/mqtt-shared/run.sh          # up + register the Modbus mock + analyze + print verdict
test/mqtt-shared/run.sh --down   # tear down
```

## Finding (2026-09-27)

**COEXIST, not collide.** The two bridges name the device node differently — Local uses the
full lowercased serial (`franklinwh_<serial>`), Modbus uses its gateway_id / short serial — so
zero shared `unique_id`/`state_topic`. Confirmed against a real HA registry: the same aGate
shows as **two device cards** whose identifiers differ only by serial CASE
(`…A02F24170091` vs `…a02f24170091`), with different names. The real-world effect is a
**duplicate HA device** (one per bridge), not a topic clash.

Two incidental findings: the Modbus bridge defaults MQTT publishing **off** in a fresh DB
(enable via `PATCH /api/mqtt/config` + `POST /api/mqtt/reconnect`), and it only publishes HA
discovery when its **default gateway is reachable** (`_run_loop` gates discovery on the default
`device_info`) — a mock-only setup with an unreachable default publishes state but no discovery.
