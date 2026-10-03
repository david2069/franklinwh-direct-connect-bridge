# Metrics gap analysis — Local Bridge vs FWHAI vs Modbus Bridge

**Filed:** 2026-09-14 · Counts taken from the code, not the docs.

| surface | published entities | notes |
| :--- | ---: | :--- |
| **FWHAI** (`src/models/entities.py`) | **109** | 75 sensor · 10 binary_sensor · 10 number · 9 select · 5 switch |
| **Local Bridge** (`publish/entities.py`) | **8** | all read-only sensors |
| **Modbus Bridge** (`modbus_capability.json`) | 44 capability points | 9 SunSpec models + 5 FranklinWH extensions |

The 8 → 109 gap looks alarming and mostly is not. **Roughly 60 of FWHAI's entities are
already readable by this bridge today** — the data is polled, exposed over REST and drawn
in the UI; it simply is not published to MQTT. The genuinely-missing set is much smaller
than the headline, and a third of the gap is not device data at all.

---

## A. Already readable locally — publishing is the only work (~60)

These need **no new device interaction**. Every source below is a command this bridge
already reads.

### Energy — 5, all from one payload
`battery_charge_today_kwh` `battery_discharge_today_kwh` `energy_daily_grid_import`
`energy_daily_grid_export` `solar_today_kwh`
→ `1301` `kwh_fhp_chg` / `kwh_fhp_di` / `kwh_uti_in` / `kwh_uti_out` / `kwh_sun`.
**The cheapest win in the whole list** — five HA energy-dashboard sensors from fields
already in the poll.

### Power — 4 direct
`grid_power_kw` `home_load_kw` `generator_power_kw` `solar_power_kw`
→ `1301` `p_uti` / `p_load` / `p_gen` / `p_sun`.

### Relays — 7, all from the block found on 2026-09-14
`relay_grid1` `relay_grid2` `relay_solar` `relay_pv2` `relay_generator` `relay_black_start`
`relay_apbox` → `1707 ibg_run_status` (+ `main_sw` cross-check).
Publish as binary sensors using the **`1 = OPEN`** convention already settled.

### Smart circuits — 6
`smart_circuit_{1,2,3}_kw` and `…_energy_kwh` → `1411`, via the existing `circuits.py`
view-model. **Suppress absent circuits** using the `present` verdict rather than
publishing three regardless — FWHAI does this with `hw_requires`, and we have better
evidence than it does.

### Battery — 6–8
`battery_soc` `soh` `temp_c` `voltage` `battery_current_a` `battery_power_kw`
→ `1705` per-cell block + `1703` + `1301 p_fhp`. Cell spread and min/max cell mV are
**beyond FWHAI** — it has no per-cell entities at all.

### Device — 4
`device_firmware` `device_serial_number` `device_model` `device_cloud_software`
→ `1101` manifest (`IBG_VER`, `IBG_SN`, `AWS_VER`) + `devicedb.py` (`SyHdVersion` → model).

### Status — ~8
`grid_frequency_hz` `inverter_voltage_v` `operating_mode_sensor` `runtime_mode`
`status_battery_status` `grid_connection_state` `status_generator_enabled`
→ `1411 freq/volt`, `1726` mode list, `1301 run_status`, `1707` relays, `1901 genEn`.

### Solar — 3
`solar_remote_pv1_w` `solar_remote_pv2_w` (aPbox, `1903 loadSolar*`), plus PV port ratings.

### Integration — 7
`last_update_time` `status_mqtt` `integration_last_restart` etc. — **our own process
health**, no device involved. Trivial.

### Controls that are already proven writes — 3
`operating_mode` (select) · `off_grid_mode` (select) · `smart_circuit_{1,2,3}` (switch)
→ `set_mode`, `set_offgrid`, `set_smart_circuit` — all hardware-verified here.

---

## B. Readable but needs derivation or unconfirmed decoding (~12)

| entity | position |
| :--- | :--- |
| `grid_to_battery_kw`, `battery_to_grid_kw`, `solar_to_grid_kw`, `power_solar_to_battery` | **Derived flow splits.** Computable from `1301` signs, but the arithmetic is an *attribution model*, not a reading — FWHAI's numbers and ours could legitimately differ. Needs a stated rule before publishing. |
| `total_capacity_kwh`, `available_capacity_kwh`, `battery_count`, `batteries_online` | `1105 devMap` gives count and serials; capacity per pack is a **constant per model**, not a reading. Derivable, but the constant must be sourced. |
| `capacity_max_charge_kw`, `capacity_max_discharge_kw` | `1701 fhpRatePower` / `kwRatePower` — plausible, **not yet confirmed** as the same quantity. |
| `battery_heater_running`, `battery_heater_state` | Heater thresholds live in `1801`, which returns **field positions, not values** on this firmware. May exist in `1835`; unverified. |
| `grid_export_limit`, `grid_import_limit` (+ unlimited switches) | **Readable** (`1903 grid_feed_max`, `1701 gridSoftLimit/gridHardLimit`, `-1` = unlimited). **Writing is unproven** — and `DEF-EXPORT-LIMIT-ENFORCEMENT` is still open. |
| `status_grid_profile` | Likely the `1269` compliance block; not decoded. |
| `mppt_active_power_w`, `mppt_status` | MPPT belongs to DC-coupled aPower S. **This site has none**, so it cannot be verified here. |

---

## C. Reserve SoC — blocked on an open question (3)

`battery_backup_reserve_soc` · `battery_self_consumption_reserve_soc` ·
`battery_tou_reserved_soc`

**Reading is solved**: `1726 reserved_soc` matches the cloud exactly (100 / 11 / 15,
confirmed 2026-09-14). So these could ship as **read-only sensors immediately**.

**Writing is not**: `1405` accepts and discards. `RESEARCH-RESERVE-SOC` proposes `1725` as
the real path, untested. Until that resolves, publishing them as HA `number` entities would
offer a control that silently does nothing — worse than not shipping it.

---

## D. Not device data — out of scope for a *local protocol* bridge (~24)

FWHAI's `control` group is mostly **its own orchestration engine**, not gateway telemetry:

`dispatch_action` `dispatch_method` `dispatch_power` `dispatch_duration`
`dispatch_target_soc` `status_*_dispatch_*` (9 status entities) `tou_saved_dispatches`
`storm_hedge` `storm_decision_strategy` `storm_backup_lead_time`
`emergency_backup_duration*` `provider_mode` `update_available`

These exist because FWHAI *has a scheduler and a weather feed*. For this bridge they are
downstream of `SCHEDULE-AND-AUTOMATIONS`, which is not built. **Counting them as a "metrics
gap" overstates the gap by about a quarter.**

Likewise `wifi_signal_dbm` / `mobile_signal_dbm` / `network_connection`: the cloud reads
these via `317`/`341`; **no local equivalent has been found**, and the 101–1099 sweep
showed those codes are out-of-band locally. Treat as **not feasible** until proven
otherwise.

---

## E. Where the Local Bridge is already *ahead*

Worth stating, because the 8-vs-109 framing hides it:

- **Per-cell BMS telemetry** — 16 cell voltages, per-cell temps, spread, recorded sessions
  with charts. FWHAI has **no** per-cell entities.
- **Presence detection with evidence** — circuits report `present` with reasons;
  FWHAI uses a static `hw_requires` flag.
- **Gateway model identification** — `SyHdVersion` → model/SKU/region/expected circuits.
- **Hardware-verified generator config writes** (windows, exercise, SoC thresholds).
- **Solar grouping** — built-in AC PV vs aPbox remote PV as separate pairs, with relays.

---

## F. Recommended order

1. **Energy 5 + Power 4** — one payload, biggest user-visible payoff (HA energy dashboard).
2. **Relays 7 + Status 8** — `1707` is already read; pure publishing.
3. **Smart circuits 6 + Battery 6** — reuse the existing view-models, suppress absent hardware.
4. **Device 4 + Integration 7** — trivial, improves diagnosability.
5. **Reserve SoC as read-only sensors** (not numbers) while `RESEARCH-RESERVE-SOC` is open.
6. **Controls last**, and only the three proven writes.

That is roughly **55–60 entities without touching the device protocol** — closing most of
the gap with publishing work, not reverse-engineering.

**Deliberately not planned:** dispatch/storm/tariff orchestration (needs the scheduler),
network signal metrics (no local equivalent), MPPT (no hardware here to verify against).
