> **Superseded by [PARITY_GAP.md](PARITY_GAP.md)** (2026-10-16), which compares the full REST APIs (OpenAPI) as well as the MQTT entities of all three bridges. This file covered HA controls only.

# Home Assistant control gap: Direct Connect REST vs Direct MQTT vs FWHAI vs Modbus Bridge

**Scope.** Written 2026-10-16. Compares FranklinWH Direct Connect Bridge **0.4.5** (`main` at the
`docs(backlog): RESEARCH-HA-CONTROL-GAP` commit), FWHAI **0.6.80** and the Modbus Bridge **0.2.6**.
Direct REST is every `@app.get/post/put/patch/delete("/api/...")` in `src/franklinwh_direct_connect_bridge/app.py`
(195 decorated routes: 103 GET, 62 POST, 13 PUT, 7 PATCH, 10 DELETE, plus the `/api/cmd/{name}` GET reads
registered in a loop at runtime). Direct MQTT is `publish/entities.py` (`ENTITIES`, `CONTROLS`). Device limits
come from `docs/API_COMPARISON.md`, `docs/LOCAL_ONLY_CAPABILITIES.md`, `docs/METRICS_GAP_ANALYSIS.md`,
`docs/OFFGRID_DESIGN.md`. The agreed direction is `docs/MQTT_CONTROLS_PLAN.md` (C1 shipped in 0.4.5; C2
reserve via cloud; C3 grid limits not in HA; C4 battery command; off-grid not in HA). FWHAI and Modbus Bridge
entities come from Home Assistant MQTT diagnostics exports for one AU aGate (one site, one firmware), taken
from `discovery_data.payload` and `device.entities`. Producers were separated by `device.sw_version`
(`… (FHAI: v0.6.80)` vs `Modbus Bridge v0.2.6`). **Source caveat:** the export named for this task
(`mqtt-…-FranklinWH Cloud <SERIAL>-…-2.json`, 14:20) contains **90 entities, all FWHAI. It has no Modbus Bridge
entities.** The Modbus Bridge 0.2.6 entities (65) are taken from the sibling export of the same HA device at
13:10 the same day. That export's FWHAI 90-entity set is identical to the -2 file. Only names, domains and
discovery shape are used here. No states, serials or addresses.

Legend. **R** read · **W** write (needs `allow_writes`, 403 otherwise) · **W+confirm** also needs `confirm=true`
(`_guard_consequential`, 428 otherwise) · **W via cloud** needs cloud credentials (`_require_cloud`, 503 without
them) · **W via Modbus** goes over SunSpec Modbus, not the local sendMqtt API. Most `/api/cloud/*` routes are
**local reads re-shaped to cloud JSON** (`cloud_compat`). They do not need the cloud. Only `POST /api/cloud/reserve`
does.

## §1 Capability matrix

| Capability | Direct REST | Direct MQTT | FWHAI MQTT (name, domain) | Modbus Bridge MQTT | Local channel can do it? | Proposed home |
|---|---|---|---|---|---|---|
| **Monitoring sensors** | | | | | | |
| SoC, grid/solar/battery/load W | R (`/api/power`, `/api/cloud/stats`, `/api/energy/flow`) | yes (5 power sensors + SoC) | Not in the 0.6.80 export. The 0.6.76 export (15 Oct) had State of Charge, Grid Power, Solar Power, Battery Power, Home Load (sensor) | State of Charge, Grid Power, Solar Power, Battery Power, Home Load, PV Total Power (sensor) | yes, 1301 | shipped |
| Daily energy (solar, grid in/out, battery chg/dis, load) | R (`/api/power`) | yes (6, `total_increasing`) | Daily Solar Energy, Daily Grid Import/Export, Daily Battery Charge/Discharge (sensor). No daily load | Grid Import/Export Energy, Battery Energy Charged/Discharged, Solar Energy Total/Proximal (lifetime, inferred from names) | yes, 1301 | shipped |
| Generator power | R (`/api/generator`, `/api/power`) | yes | Generator Power (sensor) | — | yes | shipped |
| Run status / battery state | R (`run_status_desc` in poll) | yes, but `run_status` is the **raw number** | Battery Run Status (enum sensor), Runtime Mode | Battery State, Inverter State | yes | C1 planned the text, but 0.4.5 still publishes the raw value (open) |
| Ambient temperature | R | yes | Not in 0.6.80 export (0.6.76: Ambient Temperature) | Ambient Temperature, Cabinet Temperature | yes | shipped |
| Relays (grid 1/2, PV 1/2, generator, black start, aPbox) | R (`/api/solar`, `/api/cloud/power-info` from 1710) | no | Grid Relay 1/2, Solar PV Relay 1/2, Generator Relay, Black Start Relay, aPowerBox Relay (binary_sensor) | — | yes, 1710 / 1707 | new item (read-only sensors) |
| Grid connection status | R (`/api/grid`) | no | Grid Status (enum: Connected / Outage / SimulatedOffGrid / NotGridTied) | Grid Connection | yes | new item (read-only sensor) |
| **Operating mode and reserves** | | | | | | |
| Operating mode set | W+confirm (`POST /api/mode`, `POST /api/cloud/set-mode`) | **yes** (select Operating Mode, no confirm) | Not in the 0.6.80 export (0.6.76: select Operating Mode, 3 options) | Operating Mode (select: Emergency Backup / Self-Consumption / TOU) | yes, 1727, hardware-verified (METRICS_GAP_ANALYSIS) | shipped. The HA select bypasses confirm (see §3) |
| Reserve SoC read (per mode) | R (`/api/cloud/reserves`, `/api/cloud/mode`, local 1405/mode_soc) | no | Emergency Backup Reserved SOC (sensor) | Active Reserve SOC (sensor) | yes (read) | C2 (state source) |
| Reserve SoC write, Self / TOU | W via cloud (`POST /api/cloud/reserve`, provider FWHAI REST, then the `franklinwh-cloud` lib) | no | Battery Self-Consumption SOC, Battery TOU Reserved SOC (number 0–100 %, step 1) | Self-Consumption Reserve SOC, TOU Reserve SOC (number 0–100 %, step 1) | **discarded**: 1405 is accepted and dropped (API_COMPARISON, LOCAL_ONLY). Modbus 15508 "for Self if installer-unlocked" (LOCAL_ONLY) | **C2**, only when the cloud provider is configured |
| **Smart circuits** | | | | | | |
| Circuit on/off with state | W (`POST /api/circuits/{n}/power`, `POST /api/cloud/smart-circuit/state`) | **yes** (switch Smart Circuit 1–3, state from 1409 since 0.4.5) | Circuit 1, `<circuit name>` (switch; one per configured circuit) | — | yes, 1409, live-verified 2026-08-08 | shipped (C1) |
| Circuit power / daily energy | R (`/api/circuits`, `/api/circuits/meter` 1411) | no | Circuit 1 Power, Circuit 1 Daily Energy, plus the same pair per named circuit (sensor) | — | yes, 1411 | new item (read-only sensors) |
| Circuit schedule | W (`PUT /api/circuits/{n}/schedule`, returns `discarded: true`) | no | — | — | **discarded** (live-tested 2026-09-14, three payload shapes) | not possible locally |
| **Battery command / dispatch** | | | | | | |
| Force charge / discharge / standby / release, power W/%, duration, target SoC | W via Modbus (`POST /api/battery/command`: staged slugs plus `battery_command`; `POST /api/dispatch` delegates to Modbus Bridge REST or the `franklinwh-modbus` lib). Status via `GET /api/battery/command` | no | Dispatch Action (select: Idle / Charge / Discharge / Stop), Dispatch Method (select: Cloud TOU), Dispatch Power (number 0.1–5.0 kW, 0.1), Dispatch Duration (number 5–480 min, 5), Dispatch Target SOC (number 20–100 %, 5) | Battery Command (select: Not Active / Force Charge / Force Discharge / Force Standby / Release), Command Power (number 0–5000 W, 100), Command Power % (0–100, 5), Command Duration (0–7200 s, 60), Target SoC (0–100 %, 5) | **no local cmdType**. 1823/1825 undecoded, UNCONFIRMED (API_COMPARISON). Possible over Modbus WSet (704) or cloud `ForceMixin` (not wired) | **C4** |
| Dispatch feedback | R (`GET /api/battery/command`: active, remaining_s, state, max W) | no | Active Dispatch, Dispatch Status (enum: Idle / Charging / Discharging / Stopping / Error), Dispatch Start / End / Remaining (sensor) | Last Command Result, Command Elapsed Time, Power Setpoint, Power Setpoint %, WSet Mode, WSet Enabled (binary_sensor), HW Revert Timer / Remaining, SW Watchdog Remaining, Control Mode | n/a (bridge state plus Modbus reads) | **C4** (status, active command, last result) |
| Max charge / discharge rate | R (`/api/grid`, from Modbus SunSpec 702) | no | Max Charge Power, Max Discharge Power (sensor, kW) | Max Charge Rate, Max Discharge Rate (sensor, kW) | 1701 `fhpRatePower` reads 0 on this firmware (`/api/grid` docstring). Modbus 702 needed | C4 (sizing the power number) |
| TOU preset dispatches / tariff now/next | R (`/api/cloud/tou` from 1726/1408). Bridge-side `/api/schedules*` engine | no | TOU Preset Dispatches (select, 11 options), TOU Dispatch Now / Next / Next Start / Next End / Remaining, TOU Dispatch Tariff Now / Next (enum) | — | TOU schedule read yes. FWHAI presets are its own engine (METRICS_GAP_ANALYSIS §D) | not in plan (new item if wanted, read-only) |
| **Grid limits** | | | | | | |
| Grid import / export limit, export enable, PCS discharge | W+confirm (`POST /api/grid/limits`, 1701 RMW, docstring "**UNVERIFIED** local write", `dry_run` supported). Read via `GET /api/grid` | no | Grid Import Limit, Grid Export Limit (number 0–100 kW, 0.1), Grid Import Unlimited, Grid Export Unlimited (switch) | — | **unknown**: unverified local write. Cloud read+write exists (`set_power_control_settings`, LOCAL_ONLY §6) | **not in HA per owner** (C3 dropped). Read-only limit sensors would be a new item |
| **Off-grid** | | | | | | |
| Go off-grid / reconnect | W+confirm (`POST /api/offgrid`, 1723). `POST /api/cloud/grid-status` needs confirm too since 0.4.6 (GHSA-7jmj-vj3g-q2m3) | no | Off-Grid Mode (select: On-Grid / Off-Grid) | — | yes, 1723. Requested-island measured live 2026-10-15 (OFFGRID_DESIGN) | **not in HA per owner** |
| **Generator** | | | | | | |
| Generator enable / mode / windows / exercise / SoC thresholds | W (`PUT /api/generator/enable`, `POST /api/generator/mode` [409 if no generator; "unexercised on real generator hardware"], `PUT /api/generator/window/{n}`, `/exercise`, `/soc`). R `/api/generator`, `/raw` | no | Generator Enabled (binary_sensor, read only) | — | yes. Windows, exercise and SoC thresholds hardware-verified 2026-09-14 (LOCAL_ONLY §3). Mode write not exercised with a generator | new item (no plan). Read-only enable sensor would be cheap |
| **Storm / emergency backup** | | | | | | |
| Emergency backup duration / resume mode | — (`/api/cloud/set-mode` accepts `reqbackupForeverFlag`, `reqnextWorkMode`, `reqdurationMinutes` but reports them in `not_applied_locally`) | no | Emergency Backup Duration (number 30–4320 min, 30), Emergency Backup Duration Type (select: Indefinite / 1–3 Days / Customize), Emergency Backup Resume Mode (select) | — | **no**: cloud-only per the `set-mode` docstring | not possible locally |
| Storm hedge | — | no | Storm Hedge (select: Disabled / Enabled), Storm Decision Strategy (select), Storm Backup Lead Time (number 0–330 min, 30) | — | no: FWHAI's own engine plus a weather feed (LOCAL_ONLY, METRICS_GAP_ANALYSIS §D) | not possible locally |
| **Locks / other** | | | | | | |
| Control locks | — (nearest: `allow_writes` setting plus per-call `confirm`) | no | Control Lock, Lock Battery Dispatch, Lock Grid Disconnect, Lock Operating Mode (switch, config) | — | n/a. These appear to be FWHAI-side software interlocks (**inferred** from names only) | new item (consider a single HA "controls enabled" switch for C4) |
| Reboot | W, no confirm decorator but 400 without `confirm=true` (`POST /api/reboot`) | no | — | — | yes, 1721 | not in HA (consequential; none of the three publish it) |
| **Modbus TCP Server (aGate :502) on/off** (DER comms: SunSpec / 2030.5) | W (`POST /api/der-comms`, 409 to disable without confirm). R `GET /api/der-comms` | no | — | WSet Enabled is related but different (inferred) | yes, 1205, local-only (LOCAL_ONLY §1) | not in HA (gateway-wide outage risk) |
| Raw / generic command | W+confirm for writes (`POST /api/raw`, 428). `POST /api/call/{cmd}` W with **no confirm** | no | — | — | yes | not in HA |

Bridge-admin routes (gateways, sites, meters, utilities, tariffs, billing, schedules, HA instances,
notify, MQTT admin, settings, backups, metrics) are bridge state, not device control, and are out of scope
here. `POST /api/admin/backup/{name}/restore` is the only other `_guard_consequential` route.

## §2 Sensors FWHAI or the Modbus Bridge publish that Direct MQTT lacks

Direct publishes 18 sensors (`ENTITIES`). Many of the rows below are already **R** in Direct REST. The gap
is in publishing, not in reading.

- **Relays** (FWHAI): Grid Relay 1/2, Solar PV Relay 1/2, Generator Relay, Black Start Relay, aPowerBox Relay, Battery Heater (binary_sensor).
- **Grid** : Grid Status (FWHAI, enum), Grid Connection (MB), Grid Voltage, Grid Current, Frequency (MB), Voltage (FWHAI).
- **AC electricals** (MB, SunSpec): Apparent Power (+L1), Reactive Power (+L1), Power Factor (+L1), Power L1, Current L1, Voltage L1.
- **Battery** : Battery Current, Battery Temperature, Battery 1 Power / Voltage / Temperature, State of Health, Battery Health, Available Capacity, Total Capacity (MB). Battery Count, Batteries Online (FWHAI).
- **Flow breakdown** (FWHAI): Battery Export to Grid, Solar Export to Grid, Solar Charging Battery, Grid Charging Battery.
- **Solar** : Remote Solar PV1/PV2 (FWHAI), Solar Remote 1/2, Solar Proximal, PV Total Power (MB), MPPT Active Power, MPPT Status (FWHAI).
- **Smart circuits** : per-circuit Power and Daily Energy (FWHAI).
- **Reserve** : Active Reserve SOC (MB), Emergency Backup Reserved SOC (FWHAI).
- **Limits** : Max Charge/Discharge Power or Rate (both).
- **Device / integration** (FWHAI): Firmware Version, Model, Serial Number, Software Version (Cloud), Update Available, Grid Compliance Profile, Site Timezone, Last Restart, Startup Time, Integration Startup Time, MQTT Status, Data Provider, Control Source, Cloud Stale-Window Drops. Home Load Source, Operating Mode (diagnostic sensor), Control Mode, Inverter State (MB).
- **Network** (FWHAI): WiFi Signal, Mobile Signal (dBm), Network Connection. METRICS_GAP_ANALYSIS: no local equivalent for signal strength found. Treat as not feasible locally.
- **Unconfirmed** (MB): `Ext 15016 (unconfirmed)`.

## §3 Open questions (unverified)

1. **FWHAI 0.6.80 export has no SoC / power / mode entities.** The 15 Oct 0.6.76 export of the same HA device had 13 more (State of Charge, Grid/Solar/Battery Power, Home Load, Operating Mode select and sensor, Ambient Temperature, Battery Current, Frequency, Available/Total Capacity, Grid Connection Status). Whether 0.6.80 dropped them, moved them to another HA device, or suppresses them when a Modbus Bridge is present (its "Data Provider" and "Control Source" sensors suggest provider selection) is **unverified**.
2. **The HA Operating Mode select bypasses `confirm`.** REST `POST /api/mode` needs `confirm=true`, but the MQTT select writes with no confirm. That fits the owner rule only if mode change is not counted as "consequential". The code calls it consequential (`_guard_consequential`). This needs an owner decision. Read from code: `publish/__init__.py:handle_command` calls `client.set_mode` directly. It has no confirm and no `_audit` entry, so HA mode changes are missing from the Audit Trail. Whether `client.set_mode` itself enforces `allow_writes` was not checked.
3. ~~`POST /api/cloud/grid-status` drove off-grid without `confirm`~~: **fixed in 0.4.6** (GHSA-7jmj-vj3g-q2m3).
4. **Reserve-SoC write over Modbus** (register 15508, "Self only, installer-unlocked") is a LOCAL_ONLY claim. It is not verified here, and the Modbus Bridge publishes both Self and TOU reserve numbers. Whether its TOU number actually applies is **unverified**.
5. **C4 power bounds.** Modbus Bridge's Command Power max is 5000 W and FWHAI's Dispatch Power max is 5.0 kW. The plan requires sizing from the **measured** rating (`/api/grid` from SunSpec 702). Not checked whether either value matches this site's inverter.
6. **C4 coexistence.** The Modbus Bridge and the Direct bridge would both drive WSet ("last command wins", owner decision). How either reports being overridden is **unverified** on hardware.
7. **Grid-limit local write (1701)** is marked UNVERIFIED in code. Whether the aGate honours or discards it is unknown.
8. **Generator mode write** is unexercised on generator hardware (409 guard).
9. **1823 / 1825** (possible local power setpoint) are undecoded. No claim is made that they work.
10. **FWHAI lock switches**: their semantics (software interlock in FWHAI vs a device setting) are **inferred from names only**.
11. Every FWHAI and Modbus Bridge observation comes from **one AU site, one firmware, one export pair**. Treat them as candidates, not mappings.
