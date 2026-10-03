# FranklinWH Local Bridge — User Guide

How to navigate and use the bridge's web UI. This covers every tab and the
everyday tasks; for installation and configuration see the
[README](../README.md).

> **Open the UI** at `http://<bridge-host>:8101` (the port you mapped — `8101`
> by default). As a Home Assistant add-on, open it from the add-on's **Open Web
> UI** button (or the sidebar panel).

---

## Contents

- [How the bridge talks to your aGate](#how-the-bridge-talks-to-your-agate)
- [Getting around](#getting-around)
- [Monitoring](#monitoring) — Dashboard · Battery · Solar · Smart Circuits · Generator · Analytics · Energy Costs
- [Control](#control) — Control tab · Scheduler · Grid
- [Integrations](#integrations) — Home Assistant · MQTT · Network
- [Operations](#operations) — Settings · Logs · Device · Health · Terminal · Guide
- [Common tasks](#common-tasks)
- [Good to know](#good-to-know)

---

## How the bridge talks to your aGate

The UI can reach your aGate three different ways, and many controls are marked
with a small badge showing which one they use:

| Badge | Path | What it powers |
|-------|------|----------------|
| **Local** | Direct Connect (`sendMqtt` over TCP/9000) | Most reads, operating-mode switch, off-grid, reboot |
| **Modbus** | SunSpec Modbus TCP (port 502) | Battery **force** charge/discharge/standby, inverter ratings |
| **Cloud** | FranklinWH cloud API | **Reserve SoC**, and the authoritative VPP / run-status truth |

A feature marked **Cloud** needs FranklinWH cloud credentials configured; a
feature marked **Modbus** needs the aGate's Modbus interface reachable. If the
path isn't available, the control says so plainly instead of pretending to work.

**Read-only by default.** Control writes (mode switch, off-grid, force, reboot)
are disabled unless `ALLOW_WRITES=true`. When off, those controls are hidden or
greyed with a note; everything monitoring-related still works.

---

## Getting around

- **Navigation** — a **sidebar** on desktop; a **bottom bar** on mobile with a
  **More** menu for the overflow tabs.
- **Gateway selector** (top of the screen) — when you have more than one
  gateway, every tab is scoped to the **selected** gateway. Single-gateway
  setups don't show it.
- **Topbar status** — connection (Online/Offline), current **operating mode**,
  **SoC %**, and a **VPP/FORCE** badge when a dispatch is active. A pulsing red
  **Release** button appears here whenever a battery force is running, so you can
  stop it from anywhere.
- **Theme toggle** (moon/sun) — light/dark.
- **Raw-key toggle** (`</>`) — reveals the underlying `cmdType` source of each
  value, for the curious or for debugging.

---

## Monitoring

### Dashboard
Your at-a-glance home screen:
- **State-of-charge ring** with the reserve floor marked.
- **Power flow** — live Grid / Solar / Battery / Load in watts (battery negative
  = charging).
- **Operating Mode & Reserves** — the active mode (LED), each mode's reserve %,
  and a **Set** button to change a reserve (opens a modal that stays open through
  the cloud write — saving → success/failure → retry).
- **Energy flow (Sankey)** — where today's energy came from and went.
- **Battery** summary, and an optional **Diagnostics** strip.

Cards can be shown/hidden and reordered from the card-customisation controls.

### Battery
Deep BMS view for a selected aPower: **per-cell voltages**, temperatures, pack
SoC/SoH, and electrical/state readings. Use the aPower selector if you have more
than one. You can also start a short **recording session** to chart cells over
time.

### Solar
Solar production and, if configured, an **hourly forecast** overlay. (Panels of
this tab depend on what your system reports.)

### Smart Circuits
The aGate's controllable circuits — current state and (with writes enabled)
on/off control, plus any schedules. *Not synthesised in mock mode.*

### Generator
Generator status and metrics. **This tab only appears when a generator is
installed/configured** — it stays hidden otherwise so it never shows empty.

### Analytics
Longer-horizon charts built from the bridge's local history (power, battery,
energy). Pick a time range to explore trends.

### Energy Costs
Your electricity **cost** over time, derived from power samples and your tariff.
This is where **tariffs** are applied — flat, time-of-use, tiered, or
**Dynamic (live)** pricing (AEMO NEM spot or a Home Assistant price entity),
assigned per utility/tariff. *An estimate, not a revenue-grade meter.*

---

## Control

### Control tab
Everything you can *do* to the gateway, in one place (scoped to the selected
gateway):

- **Battery Control (Modbus)** — directly drive the battery over SunSpec `WSet`:
  **Force Charge / Force Discharge / Force Standby / Release**. Pick power as
  **Watts or %** (one segmented toggle — they're mutually exclusive; the W max is
  the live inverter nameplate from Modbus M702), a **duration** (`hh:mm:ss` or
  the slider, 0 = until released), and an optional **Target SoC**. Tap-able tick
  presets make common values one click. Choosing a Force command asks for a
  **styled confirmation** first — it moves the real battery.
- **Operating Mode** — switch between **Self-Consumption**, **Time-of-Use**, and
  **Emergency Backup** (tap a card; confirm).
- **Reserve SoC** — set the per-mode reserve floor (Cloud-owned; editable only
  when cloud credentials are configured). Each row saves with inline
  progress/retry.
- **Off-grid** — manually island the gateway (run on battery) or reconnect, with
  a restore-SoC floor. Use with care.
- **Modbus (SunSpec 502)** — enable the Modbus path and, if needed, override the
  host/port, with a **Test** button.
- **Gateway** — **Reboot** the aGate.
- **Audit trail** — every consequential action you took here (and its result),
  newest first, in bridge-host time.

### Scheduler
Create time-based automations — e.g. charge/discharge windows or mode changes —
on **hourly / weekday / quarterly / annual** patterns. Entries can be enabled,
duplicated, and run now. (Schedule rules are authored in the **gateway's** local
time.)

### Grid
The grid power-plane limits (the PCS modal): import/export enables and soft/hard
limits (1701). Includes a cloud **witness** read of the global caps when cloud
creds are present. Treat these as advanced settings.

---

## Integrations

### Home Assistant
Publish the aGate to Home Assistant over **MQTT discovery**, so it appears as
native HA entities (sensors + controls). Manage HA instances/notification
settings here. (In the HA add-on, the supervisor wires this up for you.)

### MQTT
The MQTT broker connection used for HA publishing — status and what the bridge
publishes. Distinct from the **Home Assistant** tab (which manages the HA side).

### Network
The connection picture: **round-trip latency**, **Modbus :502** reachability,
**SunSpec** and **MQTT** status, the count of **published entities**, and the
CloudFront **PoP** your gateway reaches (when cloud is active). Good first stop
when something seems slow or offline.

---

## Operations

### Settings
The configuration hub:
- **Gateways** — add/remove/enable gateways, run a **scan** to discover aGates,
  or add an in-app **mock** gateway (a built-in emulator — great for trying the
  UI with no hardware; HA publishing defaults off for mocks).
- **Cloud** — FranklinWH cloud credentials, with a **Test** button that reports
  connected / rejected / locked.
- **Modbus** — host/port override and test.
- **Energy rates / Tariffs** — build utilities, meters, and tariffs, including
  Dynamic (live) pricing and its provider (AEMO NEM or an HA price entity).
- **Backups** — back up / restore / vacuum the local database.
- **Support info** — a redacted diagnostics bundle (model, amps, uptime,
  versions) for troubleshooting.
- Plus display preferences (theme, bottom-nav, raw keys), log level, and the
  legal disclaimer.

### Logs
The bridge's application log — **durable (stored in the database), searchable,
and paginated**, with level and source filters and a **Live** follow mode. This
is where control actions, cloud calls, and connection events show up
(host-local time). **Export** to download.

### Device
Device identity and raw readings — model, firmware, serial (redacted in
exports), and a browser for individual `cmdType` reads. For deep inspection.

### Health
Per-gateway health/diagnostics — connection checks and a forced health probe.

### Terminal
A built-in command console for power users (the bridge's CLI-style operations in
the browser).

### Guide
The bundled **Direct Connect API** documentation (the underlying library's
MkDocs site), served locally so the protocol/catalog reference is always at hand.

---

## Common tasks

**Switch operating mode** → Dashboard or Control → tap the mode → confirm.
(Needs writes enabled.)

**Set a reserve SoC** → Dashboard **Set** (or Control → Reserve SoC) → enter % →
Save. Applies via the cloud and syncs to the aGate in ~8 s. (Needs cloud creds.)

**Force charge / discharge the battery** → Control → Battery Control → pick
Force Charge/Discharge, set W-or-%, duration, optional Target SoC → confirm.
Stop any time with the topbar **Release**. (Needs Modbus + writes.)

**Add a real gateway** → Settings → Gateways → **Add** (host + label), or
**Scan** to discover it on your subnet.

**Try it with no hardware** → Settings → Gateways → add a **Mock** gateway
(choose an aPower count). It polls and renders like a real one. (Energy-flow and
Smart-Circuits views are empty for mocks.)

**Set up dynamic pricing** → Settings → Energy rates → create/edit a tariff →
rate type **Dynamic (live)** → pick the provider (AEMO NEM region or an HA price
entity) → save. See the cost on the **Energy Costs** tab.

**Connect to Home Assistant** → Settings (MQTT broker) → the **Home Assistant**
tab publishes discovery; entities appear in HA automatically.

**Go off-grid / reconnect** → Control → Off-grid → set the restore-SoC floor →
toggle. (Needs writes; use with care.)

**Back up the database** → Settings → Backups → Back up (download), Restore, or
Vacuum.

---

## Good to know

- **Three control planes.** Reads and mode/off-grid are **local**; battery
  **force** is **Modbus**; **reserve SoC** and VPP truth are **cloud**. A control
  only appears/acts when its path is available.
- **Read-only mode** (`ALLOW_WRITES=false`, the default) hides or disables every
  write; monitoring is unaffected.
- **Mock gateways** are perfect for exploring the UI, but don't synthesise energy
  history or smart circuits — those views are empty for them.
- **Timezones.** Gateway metrics and schedule *rules* are shown in the **site**
  (aGate) time; the audit trail and logs are in the **bridge-host** time; "x ago"
  and pickers use **your browser's** time. Each surface labels which clock it's
  using.
- **Unofficial software.** Not affiliated with or endorsed by FranklinWH;
  provided as-is. See the README disclaimer.
