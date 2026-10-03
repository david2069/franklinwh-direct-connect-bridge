# REST API comparison — local-bridge vs Modbus Bridge vs FWHAI

**Date:** 2026-09-10 (previous revision 2026-08-06)
**Baseline:** the **local sendMqtt API** (this repo). Everything is scored by
*reachability over the local API* — what this bridge can do, could build, or
structurally cannot do because it needs another transport.

Refreshed against the running deployment. Two things changed the picture since the
2026-08-06 revision, and both collapse rows that used to read "—":

- **A cloud transport was added** for the capabilities the local API cannot reach
  (`franklinwh-cloud`, 14 `/api/cloud/*` routes, resolved per-capability in
  `providers.py`). **Reserve-SoC write is no longer a hard wall** — it moved from
  *impossible* to *cloud-only*.
- **Persistence landed** — SQLite metrics (84.9k rows / 30-day retention at time of
  writing), `/api/logs`, and settings-write. The whole "buildable but absent"
  persistence block is now built.

Still absent, and still by design: `franklinwh-hybrid` (this repo does its own
transport selection) and **Modbus** (`pymodbus` is not installed — see §1).

---

## The three tiers

| | **franklinwh-local-bridge** (baseline) | **Modbus Bridge** v0.1.0 | **FWHAI** v0.4.7 |
|---|---|---|---|
| REST endpoints | **71 paths / 73 ops** | ~96 paths | ~300 |
| Transport | Local sendMqtt (TCP/9000) **+ Cloud API** | Modbus TCP / SunSpec | FranklinWH **Cloud API** |

> Modbus is a **documented** SunSpec standard — FranklinWH's conformance is published by SunSpec: PICS + IEEE 1547 certificate (`SM-000028`). The Direct Connect (local) and cloud APIs are undocumented/reverse-engineered.
| Database | **SQLite** (metrics + logs) | SQLite (v24, ~25 tables) | SQLite (~55 tables) |
| Real-time | 5 s poll → UI | HTTP poll | 1 WebSocket (MQTT explorer) |

The baseline exposes the library's full cmdType surface: **29 `/api/cmd/*` live
reads** + generic `/api/call/{cmd}` + gated writes (mode, off-grid, der-comms,
reboot), and now **14 `/api/cloud/*`** routes for the cloud-only capabilities.

Note the baseline and the Modbus Bridge are **no longer disjoint on transport** —
the baseline reaches the cloud, so on capability it is closer to FWHAI than the
2026-08-06 revision implied. It still cannot speak Modbus.

Legend: **Y** built · **P** partial · **—** absent.

---

## Telemetry

| | local | Modbus | FWHAI | Local-API reachable? |
|---|---|---|---|---|
| Power flow (SoC / flows / mode / run_status) | Y | Y | Y | built |
| Per-module battery (SNs, count) | **Y** (`battery_modules`) | Y | Y (bms) | built |
| Battery inhibit / relay / IBG state | **Y** | Y | P | built |
| Smart circuits + live V/I/P/energy + EV | **Y** (`smart_circuits`,`_meter`) | — | Y | built |
| Solar PV / generator config | **Y** | P | Y | built |
| Inverter AC electricals (V/I/Hz/PF) | **P** (per-circuit meter, not inverter 701) | Y (regs) | Y (`live_power`) | **partial — register-level detail is Modbus** |

## Modes / config / grid

| | local | Modbus | FWHAI | Local reachable? |
|---|---|---|---|---|
| Mode config / list / TOU schedule (read) | **Y** | P | Y (cloud) | built |
| Reserve SoC **read** | **Y** (`mode_soc`) | Y | Y | built |
| Grid compliance profile (25 cmdTypes) | **Y** (`grid_profile`) | P (PICS) | Y (`get_grid_profile_info`) | **full local parity** |
| Install / device / network / wifi / cloud config | **Y** | P | Y | built |

## Controls

| Capability | local | Modbus | FWHAI | Local reachable? |
|---|---|---|---|---|
| Mode switch, Off-grid | **Y** (gated) | Y | Y | built |
| DER comms (SunSpec / 2030.5) write | **Y** (gated) | via seq | — | built |
| Smart-circuit write | **Y** (`POST /api/cloud/smart-circuit/state`, live-verified) | — | Y | built (state); schedule write hardware-tested in the local lib |
| Reserve-SoC **write** | **Y** (via cloud, `POST /api/cloud/reserve`) | Y (reg) | Y (cloud) | **NO locally — device discards it; served over cloud** |
| Force charge/discharge (W/%), target-SoC | **—** | Y (WSet) | Y (dispatch) | **No local setpoint cmdType** (1823/1825 unconfirmed) — cloud path EXISTS (`ForceMixin`), not yet wired into this bridge |
| Reboot / maintenance | **Y** (double-gated) | via seq | Y (restart) | built |

## Persistence / orchestration

| | local | Modbus | FWHAI | Local reachable? |
|---|---|---|---|---|
| Database | **Y** (SQLite) | Y | Y | **built** |
| Historical metrics / time-series | **Y** (`/api/metrics`, TTL prune) | Y (ranges, TTL, export) | Y (timeline, cloud hist) | **built** (no export yet) |
| Logs endpoint | **Y** (`/api/logs`) | Y | Y | **built** |
| Settings **write** | **Y** (`PUT /api/settings`, live-editable subset) | Y (`PUT /config`) | Y | **built** |
| Scheduling / automation | — | Y (timeline engine) | Y (scheduler + rulebooks + smart-dispatch) | **partly buildable** |
| Backups | — | Y | Y | buildable once DB exists |
| MQTT admin | Y (config/entities/republish/unpublish) | Y (+reconnect/test/detect) | Y (+WS explorer) | good parity |
| Health / diagnostics | Y (ping/:9000/:502/latency) | Y (+diagnose/detect-phases) | Y (+processes/restart) | mostly built |

## Out of scope (HA-integrator tier)

Pricing / tariffs / Amber, solar & weather forecasting, economic smart-dispatch,
automation rulebooks, security / users / TOTP. These belong to the cloud-backed
integrator, not a local-API bridge.

**Multi-gateway is no longer out of scope** — it shipped: `/api/gateways`,
`/api/gateways/{gw_id}/summary`, and `/api/site/status` (which aggregates
per-gateway totals). `tools/demo.sh` runs a second seeded mock aGate to exercise it.

---

## The gaps, sorted by meaning

### 1. Hard transport limits — the local API cannot do these
This is *why the other tiers exist*. Note the distinction that now matters: a
capability the **local transport** cannot reach is not necessarily one **this
bridge** cannot serve — it may hold a cloud path to it.
- **Reserve-SoC write** → Cloud API only (local write silently discarded; see
  `UNVERIFIED_WRITES.set_mode_soc` in the library). **Served here** via
  `POST /api/cloud/reserve` — a transport limit, no longer a product gap.
- **Battery power dispatch** — force charge/discharge (W/%), target-SoC watchdog
  → Modbus WSet registers (Modbus Bridge) or cloud dispatch (FWHAI). No local
  setpoint cmdType exists. (1823/1825 "power on/off/setpoint" are UNCONFIRMED —
  a *possible* but unverified local path; do not rely on them.)
- **Inverter register-level AC electricals** (V/I/Hz/PF/reactive) → Modbus/SunSpec.

### 2. Buildable on the local API — mostly now built
Transport-independent (see BACKLOG API-PARITY phases). Most of this section has
shipped since the last revision:

- ~~Local **DB + historical metrics + `/api/metrics`**~~ — **built** (SQLite,
  poll → store → prune, 30-day retention).
- ~~**Logs** endpoint~~, ~~**settings-write**~~ — **built** (`/api/logs`,
  `PUT /api/settings` over a live-editable key subset).

Still outstanding:
- **Basic scheduler** (mode / off-grid / smart-circuit on a timeline).
- **Dedicated smart-circuit write** endpoint — today it goes through the generic
  gated `/api/call`.
- **Metrics export** and **backups** — the DB exists now, so both are unblocked.

### 3. Out of scope by design — the integrator tier's job (see above).

---

## Bottom line

The baseline is **feature-complete for monitoring, config visibility, and every
write the local API physically permits** — and on *reads* it rivals the Modbus
Bridge and reaches **grid-profile parity with FWHAI's cloud**. Since the last
revision it also grew a **cloud transport** and **persistence**, which between
them retired most of what this document previously listed as missing.

What is actually left:

- **A wiring gap, not a hard wall.** *Battery power dispatch* (force charge/discharge
  W/%, target-SoC) has **no local cmdType**, but a **cloud path DOES exist** and is simply
  **not yet wired into this bridge**: `franklinwh-cloud`'s `ForceMixin` (`mixins/force.py`)
  offers `force_charge`/`force_discharge`/`force_standby` with `power_kw`/`min_soc`/`max_soc`/
  `grid_charge_max`, plus `set_power_control_settings(globalGridChargeMax/DischargeMax)`
  (`mixins/power.py`). Modbus `WSet` is *one* way to dispatch, not the only one. *Reserve-SoC
  write* is likewise served over cloud today.
- **Modbus is genuinely absent**, not merely unused: `pymodbus` is not installed,
  so `dispatch` resolves to `available: false, reason: "library not installed"`.
  The `modbus_502` health field and the `/api/der-comms` SunSpec toggle are
  **local-API** operations *about* Modbus — easy to misread as Modbus support.
- **A thinner backlog**: scheduler, dedicated smart-circuit write, metrics export,
  backups.

*Route inventories captured live from each app's OpenAPI on 2026-09-10.
Regenerate this repo's list with `curl -s localhost:8101/openapi.json`.*
