# What the local API can do that FWHAI and Modbus cannot

**Filed:** 2026-09-14 · Counts from `franklinwh_local.catalog` (70 commands), the
`franklinwh-cloud` source, and `modbus_capability.json` (44 points).

**Important distinction (corrected 2026-09-29):** *FWHAI* (the Home-Assistant integration) is **not**
the same as the **`franklinwh-cloud` API**. The cloud library implements much more than FWHAI surfaces —
a `sendMqtt` relay (211/311/315…), a `ForceMixin`, generator/power-control writes, and rich location
reads. So "FWHAI can't do X" does **not** imply "the cloud API can't." Claims below are scored against the
**cloud API** (the `franklinwh-cloud` package), and call out where the only gap is FWHAI's exposure.
Modbus is a separate, narrow control plane.

---

## 1. Installer-grade DER / grid-compliance control — the biggest gap

**`1205 der_comms`** — the **SunSpec Modbus** and **IEEE 2030.5 / CSIP** on-off toggles.
No cloud equivalent exists: grepping `franklinwh-cloud` for `sunsMdEn`, `sunspec` or
`2030` returns **nothing**. Modbus obviously cannot serve the switch that enables Modbus.
**Only the local API can turn Modbus TCP on or off**, which also makes it the thing the
Modbus bridge depends on but cannot provide for itself.

**~27 individually addressable compliance commands** — `1203`, `1211`–`1229`,
`1251`–`1277`: OV/OF trip points, fixed power factor, Q(V), P(V), P(f) droop, reconnect
ramp, DC injection, ride-through flags, battery grid-access mode, ES voltage window, ES
reconnect timing, constant-PF, constant-Q, PV/QP/QV curves, ramp rate, fast reconnect.

The catalog marks these as having a cloud equivalent, but that overstates it: the cloud
collapses the whole lot into one **read** (`get_grid_profile_info(requestType=2)`). Local
exposes each as its own command with its own fields. **Read granularity is far higher, and
per-setting writes are reachable here and nowhere else.**

## 2. Firmware OTA — `1501` / `1503`

`firmware_deliver` and `firmware_upgrade`. **No cloud equivalent** (no OTA methods in
`franklinwh-cloud`), none in Modbus. Writing pushes a firmware file / triggers an upgrade —
the most dangerous pair in the catalog, and untested here on purpose.

## 3. Generator configuration beyond mode — `1901`

Cloud offers `set_generator_mode()` (`manuSw` auto/manual) **and `set_generator_charge_schedule()`**
(the three `chargeN` operating windows via `POST updateIotGenerator` — `mixins/devices.py:1081`), which
matches the local block's `chargeNEn/StartTime/EndTime`. What is **genuinely local-only** is the rest of
the 1901 block (hardware-verified 2026-09-14): the **maintenance-exercise schedule** (`oilmanoEn/manoFre/
manoDate/manoStartTime/manoTime`) and the **auto start/stop SoC-threshold writes** (`genStartElec/
genCloseElec` — the cloud only *reads* these). Modbus has no generator surface at all.

## 4. Commissioning and device identity

Narrower than previously claimed — the cloud covers most of this:
- **Device enumeration** IS on the cloud: `get_accessories(option=3/4)` (`mixins/devices.py:84`),
  `get_apower_info()` (aPowers by serial), `get_site_and_device_info()` (`mixins/account.py:101`).
  Genuinely local-only is only the per-device commissioning **`checkResult`** flag (`devMap[].checkResult`)
  — grep of the cloud package for `checkResult`/`devMap` returns nothing.
- **`1123 agate_serial` is NOT local-only** — the serial IS the cloud `gatewayId` used by every call and
  is returned by `get_home_gateway_list()` (`mixins/account.py:13`) and `get_apower_info()`.
- **`1201 time_location` is largely covered by the cloud** — time + tz: `get_device_info()` `deviceTime`
  + `zoneInfo` (`mixins/devices.py:465`); DST + GPS: `get_equipment_location()` `dst` + coords
  (`mixins/account.py:147`); postcode: `get_device_detail()` `postCode` (`mixins/devices.py:1976`). The
  local edge is only that it returns them in one gateway-direct read.

## 5. Maintenance controls — `1721`

The local `1721` block carries `reboot`, `reset` and `update`. **`reboot` and `reset` are NOT local-only**
— the cloud's own `sendMqtt` cmdType **315** payload structurally exposes both (alongside
`cleanUnlockAlarm/cleanLockAlarm/cleanAlarmFlag`); both surfaces refuse to populate `reset` by policy, so
it is symmetric, not local-only. Only **`update`** is genuinely local-only (no cloud OTA/update method —
see §2). `reset` is almost certainly a factory reset, so it stays unexposed on both.

## 6. Deep telemetry FWHAI does not surface

- **`1705` per-cell BMS** — 16 cell voltages, per-cell temperatures. The cloud *can* reach
  this (211 type 2/3) but **FWHAI publishes no per-cell entities**; Modbus has none.
- **`1703` power electronics** — inverter/DC-bus detail, per device.
- **`1827` ibg_state`, `1835` device_states** — DSP/PE/BMS state machines.
- **`1829` event_block** — the gateway's own event log.
- **`1701` install_profile** — the **electrical install-profile** fields (electricSys/airSwitchCur/…) are
  genuinely uncovered. But the **grid power-plane limits** are NOT: `gridSoftLimit/gridHardLimit`
  (≈ `globalGridChargeMax/DischargeMax`) and `isPcsDischgEn` have cloud **read+write** via
  `get/set_power_control_settings` (`mixins/power.py:44,53`) and `update_system_settings` (`:2321`).
- **`1801` battery_inhibit** — charge-inhibit thresholds and the blackstart flag.
  *(Unreadable on this firmware: returns field positions, not values.)*

## 7. Five undecoded commands
`1207`, `1209`, `1821`, `1823`, `1825` — present locally, absent from every other surface,
purpose unknown. Recorded so they are not mistaken for something known.

---

## The other direction — what local CANNOT do

Worth stating so this reads as a comparison rather than a boast:

| capability | local | who has it |
| :--- | :--- | :--- |
| **Reserve SoC write** (Self / TOU) | ❌ no path at any opt | **Cloud** `updateSocV2` (REST); Modbus `15508` for Self if installer-unlocked |
| **Smart-circuit schedule write** | ❌ accepted and discarded | Cloud/app only |
| **Dispatch, storm hedging, tariff automation** | ❌ not device data | FWHAI's own engine |
| **WiFi/mobile signal, network state** | ❌ out-of-band locally | Cloud `317`/`341` |
| **SunSpec standardised DER control** | ❌ | Modbus models 701/702/704/710/713/714/715 |
| **Register-speed control loop** | ❌ | Modbus TCP |

## The short answer

The local API's genuinely unique territory (after the 2026-09-29 cloud-inventory re-check) is the
**installer / commissioning write surface**: the DER-comms (SunSpec / 2030.5) on-off toggle, **per-setting
grid-compliance writes** (the cloud only *reads* the profile), **firmware OTA**, the `1721 update`
(factory-reset-class) control, the per-device commissioning **`checkResult`**, the generator
**maintenance-exercise schedule + SoC-threshold writes**, and the **electrical install-profile** fields —
plus deep per-device telemetry that FWHAI doesn't publish. NOTE: device enumeration, the gateway serial,
gateway time/timezone/DST/GPS/postcode, generator charge-windows, reboot/reset, reserve SoC, schedules,
and the grid power-plane limits are all reachable via the **cloud API** (just not all via FWHAI). Modbus
owns **standardised, fast DER control**.

The single most consequential item is `1205`: **the local API is the only way to turn
SunSpec Modbus and IEEE 2030.5 on or off** — so it gates the existence of the Modbus
control plane itself.
