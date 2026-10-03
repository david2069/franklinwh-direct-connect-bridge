# franklinwh-local-bridge

This integration is designed as proof-of-concept demonstration on how to integrate to a FranklinWH aGate gateway via their Direct Connect local API.

You can connect to your own FranklinWH Gateway or you can optionally simply add emulated (mock) gateway to try it

It can be installed and run as follows:
- As Home Assistant Add-on
- Under Docker (or similar environments) in a container
- Run standalone in virtual Python environment

You interactively via a number of interfaces:
- A built web browser interface via rich customisable dynamic desktop, table mobile dashboards
- REST API
- MQTT Home Assistant Entities

These interfaces expose:
- Discover FranklinWH Gateways
- Emulate (or mock) a FrankinWH Gateway
- Gateway metrics
- Gateway accessories
- Gateway controls
- Gateway local historical data
- Automation Schedules - with large built-in rich functions
- Built-in integration to Weather (Open Metro)
- Optional: utility billing and tariff setup for informational tracking
- Optional Home Assistant Entities access
- Optional Home Assistant Notifications for events
- Various charting options for historical and real-time monitoring
- Optional: integration to Gateway via Modbus TCP and/or FranklinWH Cloud API in order to:
- Set reserved state-of-charge (SoC) via Cloud API
- Force charge or dischange (with optional parameters) via Modbus TCP
- Get metrics and controls not available by any of the local APIs (Cloud API)

This integration requires the FranklinWH Direct Connect API library:
[`franklinwh-direct-connect-api`](https://github.com/david2069/franklinwh-direct-connect-api) 

Modelled on [`energipays-bridge`](https://github.com/david2069/energipays-bridge): dual-target
Dockerfile (slim standalone / alpine HA base), ingress web UI, `mqtt:want` broker
auto-discovery, `read_only` by default.

> **Status: in service.** 71 REST paths (73 operations), the full UI, MQTT / Home Assistant
> discovery, and a SQLite metrics store are all live and running against real hardware.
> See `PLAN` in the library repo (`PLAN_docker.md`) and `docs/API_COMPARISON.md`.

## ⚖️ Disclaimer

> **UNOFFICIAL SOFTWARE — NOT AFFILIATED WITH OR ENDORSED BY FRANKLINWH.**
>
> This bridge talks to FranklinWH's undocumented **Direct Connect** (local) API and its **cloud** API —
> technically the **same private API the official FranklinWH mobile app** uses (FleetView, the installer
> portal, runs on the same backend), intended for those apps and not for third-party use — plus the
> standard **SunSpec Modbus TCP** API (with undocumented FranklinWH extensions). Any of these may change,
> break, or become unavailable without notice. It is provided **AS-IS**, without warranty of any kind,
> express or implied — use entirely at your own risk. The authors accept no liability for service
> interruptions, data loss, equipment damage, or any other consequences of using this software.
>
> **Do NOT contact FranklinWH support** about this app. Raise issues, defects, or feature requests on
> GitHub instead: <https://github.com/david2069/franklinwh-local-bridge/issues>
>
> **MIT License.** The disclaimer is also logged once at startup and shown as a one-time
> acknowledgement modal on first connection (recorded for the audit trail).

### Compliance & anti-circumvention

> You agree to keep your gateway and battery settings, controls, and operation compliant with the
> configuration set through the official FranklinWH Mobile App and the installer/support FleetView portal.
>
> FranklinWH-managed settings may exist to, among other things: protect the **safety and longevity** of the
> battery and gateway; apply **automatic software updates** and restrict your ability to view or change
> battery, grid-import, or grid-export controls; enforce your **local grid profile** and any import/export
> limits or prohibitions; and enforce restrictions tied to **contractual incentives, subsidies, or VPP/grid
> programmes**.
>
> If you use this software to bypass or override any such control, restriction, or compliance measure —
> deliberately or inadvertently — you do so **entirely at your own risk**. This is neither condoned nor
> encouraged by the authors or any other party.
>
> This software is provided for **informational and educational purposes**, **AS-IS**, with no warranty of
> fitness for any purpose. Any use — personal or commercial — is permitted under the MIT Licence and is
> entirely at your own risk.
>
> As the MIT Licence requires, the copyright notice and this notice (including the Additional Terms) should
> be included in copies or substantial portions of the software — in forks, derivatives, and AI-assisted
> works alike, so the unofficial-app and compliance context travels with the code. See [`LICENSE`](LICENSE)
> (Additional Terms) for the authoritative text.

**SunSpec Modbus conformance.** Unlike FranklinWH's Direct Connect and cloud APIs, the Modbus TCP surface
is a documented open standard. FranklinWH's implementation is published by the SunSpec Alliance:
- [Modbus PICS](https://sunspec.org/wp-content/uploads/2009/03/UPDATED_FranklinWH_Modbus_PICS_SM-000028.xlsx)
  (Protocol Implementation Conformance Statement, SM-000028)
- [IEEE 1547 certificate](https://sunspec.org/wp-content/uploads/2009/03/UPDATED_FranklinWH_Modbus_1547_Certificate_SM-000028.pdf)

(FranklinWH layers some **undocumented** registers on top of the standard — those extensions are not in the PICS.)

## Install as a Home Assistant add-on

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. Open the **⋮** menu (top-right) → **Repositories**, add
   `https://github.com/david2069/franklinwh-local-bridge`, then close.
3. Find **FranklinWH Local Bridge** in the store and click **Install**.
4. On the **Configuration** tab set `fwh_host` to your aGate's IP, and enable
   `mqtt_enabled` to publish the battery as Home Assistant entities. **Save.**
5. **Start** the add-on, then open its sidebar panel (served over HA ingress).

Notes:

- **MQTT** auto-configures from the official **Mosquitto** add-on — no host/credentials
  needed (the Supervisor provides them; the `mqtt:want` service discovers the broker).
- **Local history** (the SQLite metrics store) is **off by default** in the add-on when
  MQTT is on — Home Assistant's own recorder already stores the published MQTT entities,
  so a second copy is redundant. Set `metrics_enabled: true` to force it on.
- The Supervisor **watchdog** restarts the add-on if the web app stops serving (it probes
  `/api/live`, which does no gateway I/O, so a down aGate never triggers a restart).
- Control writes (mode / off-grid) stay **off** until you enable `allow_writes`; you can
  flip it live from the **Settings** tab in the UI.

## Layout

```
config.yaml build.yaml repository.json   # HA add-on manifest + arch bases
Dockerfile docker-entrypoint.sh docker-compose.yml
src/franklinwh_local_bridge/
  app.py cli.py config.py client.py ha_options.py
  templates/  static/
tests/
```

## Run (standalone, dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ../franklinwh-local        # the local API library (editable)
pip install -e ".[test,cloud]"            # cloud extra = the cloud transport
FWH_HOST=192.0.2.110 franklinwh-local-bridge run   # → http://localhost:8101
```

> **Note:** the cloud transport is an **optional extra**. Install without `cloud` and the app
> still runs, but every cloud-backed capability — including reserve-SoC write — degrades to
> `available: false, reason: "library not installed"` (check `GET /api/providers`). That is
> the same mechanism by which Modbus dispatch reports unavailable, so don't read one as
> evidence of the other. The Docker image installs it from a bundled wheel in `wheels/`.

Or `docker compose up --build` (mounts the sibling library for dev).

## Demo / no-hardware mode

Run the whole UI with **live-looking data and no aGate** — handy for a demo, screenshots,
or UI work:

```bash
tools/demo.sh            # build image + start; then open http://localhost:8102
tools/demo.sh --down     # tear it down
```

It starts **two seeded mock aGates** (the `franklinwh-local emulate --seed N` emulator
bundled in the image — each a distinct virtual device with a solar/battery/load curve that
follows the time of day) plus a bridge pointed at mock-1. Values move between polls, control
buttons are enabled against the mock, and it is fully isolated from the real deployment
(own port `8102`, own `./data-demo` volume, MQTT off — the real container on `8101` is
untouched). `mock-agate-2` is already running and ready for **multi-gateway** testing.

## Endpoints

**71 paths / 73 operations.** `/docs` (OpenAPI) is the live inventory; the shape is:

| Group | Count | What |
|---|---|---|
| `/api/cmd/*` | 29 | the library's full local cmdType read surface |
| `/api/cloud/*` | 14 | cloud reads + the cloud-only writes (reserve, mode, smart-circuit) |
| `/api/mqtt/*` | 5 | config, entities, discovery, republish / unpublish |
| `/api/metrics`, `/api/logs` | 3 | SQLite time-series + log tail |
| `/api/call/{cmd}` | 1 | generic escape hatch onto any catalogued cmdType |
| rest | ~19 | `/api/health`, `/api/power`, `/api/summary`, `/api/site/status`, `/api/settings`, `/api/der-comms`, `/api/firmware`, `/api/providers`, … |

Plus `/` (UI) and `/api/live` (the watchdog probe that does no gateway I/O).

## Transports

Two are wired; the third is deliberately someone else's job.

- **Local sendMqtt (TCP/9000)** — the baseline. Everything under `/api/cmd/*`, plus the
  hardware-verified mode / off-grid / der-comms / reboot writes. Gated **off by default**
  (`read_only: true`).
- **Cloud API** — used only where the local transport physically cannot reach: **reserve-SoC
  write** (the aGate silently discards the local write) and the cloud-native mode /
  smart-circuit setters. `GET /api/providers` reports, per capability, which transport is
  active and why.
- **Modbus / SunSpec — not a transport here.** `pymodbus` is not installed. What exists is
  reachability (`modbus_502` in `/api/health`) and the SunSpec **enable toggle**
  (`/api/der-comms`, cmd 1205) — and both of those ride the *local* API, not Modbus. So
  battery power dispatch (force charge/discharge, W/%) resolves to `available: false`
  here; it belongs to the separate **Modbus Bridge**. See `docs/API_COMPARISON.md`.
