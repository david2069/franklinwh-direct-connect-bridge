# FranklinWH Direct Connect Bridge

This integration is a proof-of-concept demonstration of how to integrate with a FranklinWH aGate gateway over the (undocumented, unofficial) FranklinWH Direct Connect local API.

> **On the names.** **Direct Connect** is FranklinWH's own term for the gateway's local
> protocol, implemented by the library
> [`franklinwh-direct-connect-api`](https://github.com/david2069/franklinwh-direct-connect-api).
> **This** is the application built on top of it. The repo, the Python package and the CLI are
> still called `franklinwh-local-bridge`, and the Home Assistant add-on slug is still
> `franklinwh_local_bridge` — renaming those would break existing installs, so only the
> display names changed.

It is not intended for production use, and there is no guarantee it is compatible with your FranklinWH gateway(s), aPower(s) or connectivity — now or in the future. FranklinWH may block or deprecate this interface at any time. It has been tested on a local area network against my own single aGate X and aPower X.

Point it at your own gateway, or add one or more **emulated (mock) gateways** and see the
whole thing work before you connect real hardware.

## Running it

- As a **Home Assistant add-on** (served through ingress, MQTT auto-configured)
- In **Docker**, or any container runtime
- **Standalone** in a Python virtual environment, on any platform with Python 3.11+

## Interfaces

- A **web UI** — responsive for desktop, tablet and phone, with show/hide and reorder on
  the dashboard cards and the topbar
- The built-in **REST API** (`/docs` for the live OpenAPI inventory)
- **MQTT**, as Home Assistant entities via discovery

## What it does

**Monitor**
- Discovers gateways on the LAN and runs **several at once** from one install
- Live power flow, state of charge, operating mode and run status
- **Per-cell BMS telemetry** — cell voltages and temperatures per aPower, with recorded
  sessions you can replay and compare
- Local history in a SQLite store, with charts for both real-time and historical views,
  an Analytics tab and CSV export

**Control** — all writes gated off until you enable them
- Operating mode, off-grid / reconnect, reboot
- **Generator**: enable, mode, exercise schedule, start SoC
- **Smart circuits**: switch a circuit, set its schedule
- **Battery dispatch**: force charge or discharge at a given power, with an optional
  target SoC (over Modbus — see [Transports](#transports))
- Reserved SoC (over the Cloud API, which is the only path that works — see
  [Transports](#transports))

**Automate**
- A **scheduler** with daily, interval and cron triggers; entry and exit conditions over
  any sensor; priority and conflict policy; templates; and an explain view for why a
  window did or did not fire
- **Home Assistant actions** — fire a notification or call a service
- **Solar forecast** and weather from Open-Meteo, including forecast-vs-actual

**Account for it** (optional)
- Sites, meters, utilities and tariffs as first-class records, with effective dates
- Billing periods with cost tracking, and tariff import/export shared with the Modbus
  bridge. Informational only — it does not bill anyone

**Administer**
- Database backup, restore and storage metrics
- An audit trail of every control write
- Home Assistant notifications on events

This integration requires the unofficial FranklinWH Direct Connect API library:
[`franklinwh-direct-connect-api`](https://github.com/david2069/franklinwh-direct-connect-api) 

The integration has been modelled on [`energipays-bridge`](https://github.com/david2069/energipays-bridge): dual-target
Dockerfile (slim standalone / alpine HA base), ingress web UI, `mqtt:want` broker
auto-discovery, `read_only` by default.

> **Status: in service.** 180 REST paths (206 operations), the full UI, MQTT / Home Assistant
> discovery, and a SQLite metrics store are all live and running against real hardware.
> See [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) for the UI walkthrough and
> [`docs/API_COMPARISON.md`](docs/API_COMPARISON.md) for how the three transports compare.

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
3. Find **FranklinWH Direct Connect Bridge** in the store and click **Install**.
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
pip install -e ../franklinwh-direct-connect-api   # the local API library (editable)
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

**180 paths / 206 operations**, as served by the running app. `/docs` (OpenAPI) is the live
inventory — prefer it over this table, which is a snapshot. The shape:

| Group | Paths | What |
|---|---|---|
| `/api/cmd/*` | 36 | the library's local cmdType read surface, registered 1:1 from it |
| `/api/cloud/*` | 16 | cloud reads + the cloud-only writes (reserve, mode, smart-circuit) |
| `/api/ha/*` | 11 | Home Assistant topology, entities and WebSocket status |
| `/api/schedules/*` | 11 | the automation engine: CRUD, templates, explain, import/export |
| `/api/generator/*` | 7 | generator config and metrics (hidden when none is installed) |
| `/api/battery/*` | 7 | BMS telemetry, recorder sessions, direct-Modbus dispatch |
| `/api/mqtt/*` | 7 | config, entities, discovery, republish / unpublish, broker scan |
| `/api/admin/*` | 7 | backup / restore, storage metrics, vacuum, exports |
| `/api/gateways/*`, `/api/tariffs/*`, `/api/billing/*`, `/api/circuits/*` | 5 each | multi-gateway roster, tariffs, billing periods, smart circuits |
| rest | 58 | `/api/health`, `/api/power`, `/api/summary`, `/api/site/status`, `/api/settings`, `/api/der-comms`, `/api/firmware`, `/api/providers`, `/api/dispatch`, `/api/modbus`, `/api/sites`, `/api/meters`, `/api/utilities`, `/api/solar`, `/api/notify`, `/api/constants`, `/api/metrics`, `/api/logs`, `/api/call/{cmd}`, … |

Plus `/` (UI) and `/api/live` (the watchdog probe that does no gateway I/O).

## Transports

All three are wired, each used only where it is the right one.

- **Local sendMqtt (TCP/9000)** — the baseline. Everything under `/api/cmd/*`, plus the
  hardware-verified mode / off-grid / der-comms / reboot writes. Gated **off by default**
  (`read_only: true`).
- **Cloud API** — used only where the local transport physically cannot reach: **reserve-SoC
  write** (the aGate silently discards the local write) and the cloud-native mode /
  smart-circuit setters. `GET /api/providers` reports, per capability, which transport is
  active and why.
- **Modbus TCP (SunSpec)** — used for the one thing neither of the others can do:
  **battery power dispatch**. `battery_control.py` drives the aGate's WSet setpoint
  (SunSpec Model 704) over TCP/502 through the `franklinwh-modbus` library, so force
  charge/discharge with a power and an optional target-SoC runs from this bridge
  (`POST /api/dispatch`) — it does *not* require the separate Modbus Bridge service.
  Gated behind a master switch in Settings, with reachability reported as `modbus_502` in
  `/api/health` and testable at `/api/modbus/test`.

  > **Force writes move the battery.** On this firmware the hardware revert timer
  > (`WSetRvrtTms`) is cosmetic, so the library's software `duration_s` watchdog is the only
  > safety — always release when done. The bridge holds its own watchdog and a global
  > Release so a dropped connection cannot leave the battery dispatched.

  The SunSpec **enable toggle** (`/api/der-comms`, cmd 1205) is a separate thing and rides
  the *local* API, not Modbus. See [`docs/API_COMPARISON.md`](docs/API_COMPARISON.md).
