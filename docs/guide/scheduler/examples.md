# Examples

Direct Connect Bridge. Mirrors the Modbus Bridge page
[Examples](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/examples/)
section for section: the same seven recipes, built with this bridge's form. Field names are
the ones in the **Add schedule** dialog. There are no screenshots of these recipes yet.

!!! tip "Before you start"
    - Force charge / discharge / standby needs the **Modbus client (this bridge)** switched
      on and the aGate's Modbus TCP Server (aGate :502) answering. Otherwise **Force** is
      greyed *unavailable* in the **Battery action** list.
    - Set the [constants](conditions.md#constants) first: several recipes compare against
      them with **Lookup**. The ETA sensors also need the battery capacity constant.
    - Untick **Enabled** while you try things out, and press **Test** under each condition
      block.
    - For a force, use **Daily at time**, **Weekly at time**, **Every N minutes** or **Custom
      cron**, with a **Duration (min)**. A force in a **Recurring windows** schedule stops
      after the hidden duration, not at the window's end (#160).
    - Avoid force schedules whose windows overlap on one gateway. A force that replaces
      another is not undone: when it ends, the earlier schedule's force does not come back.
      A window end releases only that schedule's own force. See
      [Exit and release](exit-and-conflicts.md).

## 1. Evening top-up

Force charge on weekday afternoons if SoC is below 80 %, up to 90 %.

| Field | Value |
|---|---|
| Trigger type | **Weekly at time**, Days **Mon**–**Fri**, Fire at `16:00`, Duration (min) `60` |
| Battery action | **Force charge / discharge / standby**: Direction **Force charge**, Power unit **kW**, Power `2`, Target SoC `90` |
| Entry conditions (Match ALL) | Battery SoC (%) `<` `80` |

How it behaves:

- At 16:00 on a weekday the bridge checks SoC. Below 80 %, it starts the force charge at
  2 kW. Otherwise it logs *gated* (once a day) and checks again every tick until 17:00.
- The **Target SoC** stops the charge at 90 %: the bridge's own watchdog checks the last
  polled SoC every 5 seconds. An **End early when…** row `Battery SoC (%) >= 90` does the
  same through the scheduler.
- At 17:00 the window closes and the bridge releases the force if it is still running.
- The form offers **% of inverter power** and **kW**. Watts are API only (`"unit": "w"`).

## 2. Evening peak discharge until the minimum SoC

Discharge through the evening peak, stop at your floor, and never export the battery if
your plan forbids it.

| Field | Value |
|---|---|
| Trigger type | **Daily at time**, Fire at `17:00`, Duration (min) `240` |
| Battery action | **Force charge / discharge / standby**: **Force discharge**, **kW**, Power `5` |
| Entry conditions (Match ALL) | Battery SoC (%) `>` **Lookup** Const: min discharge SoC (%) |
| | Utility: battery export allowed `==` `1` |
| End early when… (Match ANY) | Battery SoC (%) `<=` **Lookup** Const: min discharge SoC (%) |
| Priority | `10` |

How it behaves:

- At 17:00 the bridge discharges at 5 kW if SoC is above the constant and the utility
  allows battery export. **Utility: battery export allowed** reads `1` when the utility does
  not set it, and has **no value** when the gateway's meter has no utility, which fails the
  gate.
- When SoC reaches the constant, the exit closes the window: the force is released and the
  schedule does not fire again until tomorrow.
- At 21:00 the window closes and the force is released if it is still running.
- The aGate's own reserve still applies.
- *Recurring windows* `17:00 → 21:00` would read more naturally, but a force in it stops after
  the hidden duration (#160).

## 3. Charge from the grid when the NEM spot price is low

Charge when the AEMO wholesale price drops below 5 c/kWh; stop when it rises to 8 c/kWh or
the battery is full.

Needs: a NEM region (or a Home Assistant price entity) under **Settings → Integrations**.

| Field | Value |
|---|---|
| Trigger type | **Custom cron** `*/30 * * * *`, Duration (min) `29` |
| Battery action | **Force charge**, **% of inverter power**, Power `60` |
| Entry conditions (Match ALL) | Wholesale spot price (AEMO NEM or HA entity, c/kWh) `<` `5` |
| | Battery SoC (%) `<` **Lookup** Const: max charge SoC (%) |
| Hold (HH:MM:SS) | `00:02:00` |
| End early when… (Match ANY) | Wholesale spot price `>=` `8` |
| | Battery SoC (%) `>=` **Lookup** Const: max charge SoC (%) |

How it behaves:

- Every half hour the schedule opens for 29 minutes. Each half hour is its own occurrence, so
  after an exit it can charge again in the next one.
- Within a window it fires once the price has been below 5 c/kWh for two minutes in a row.
- 5 and 8 c/kWh are two thresholds on purpose: one would start and stop on every small
  price move.
- **Custom cron** needs the `croniter` package; the trigger list says *Custom cron —
  unavailable* without it.
- Without a region the gate fails. **With a region, the last good price is kept however old
  it is** if the bridge cannot reach AEMO; the Modbus Bridge drops a price after 30 minutes.

!!! note "Why not *Always (sensor-driven)*?"
    An Always schedule fires once and then never again: its single occurrence is recorded
    as done (#190). See [Triggers](triggers.md#always-evaluate).

## 4. Storm forecast: fill the battery

Top the battery up when Open-Meteo reports a thunderstorm.

Needs: a location under **Settings → Integrations → Location & Solar** (**Sync from gateway**
reads it from the aGate).

| Field | Value |
|---|---|
| Trigger type | **Custom cron** `0 * * * *`, Duration (min) `59` |
| Battery action | **Force charge**, **% of inverter power**, Power `60`, Target SoC `95` |
| Entry conditions (Match ALL) | Battery SoC (%) `<` `95` |
| | Weather: condition `like` `*thunder*` |

How it behaves:

- Each hour the schedule is open for 59 minutes. If the current weather is a thunderstorm and
  SoC is below 95 %, it charges to 95 %.
- `weather.condition` is the **current** weather, refreshed with the forecast cache (about
  15 minutes). The exact wording of the condition text is not documented here
  (**unverified**): press **Test** on a stormy day, or read the live value, before relying on
  `*thunder*`.
- The WMO weather code is in the snapshot as `weather.code` but **not in the picker**; through
  the API a row `weather.code in 95, 96, 99` works.
- To keep the charge afterwards, add a second schedule with **Force standby** and the same
  weather gate. **Set reserve SoC** does not help: it never runs (#129).

## 5. Peak-demand window: shave imports using the Demand-Charge Min SoC

During the network's peak-demand window, discharge when the house imports more than 1 kW,
but keep the battery above the demand-charge minimum.

Needs: a tariff with a **demand window** on the gateway's meter, and the demand-charge min
SoC constant.

| Field | Value |
|---|---|
| Trigger type | **Custom cron** `*/30 * * * *`, Duration (min) `29` |
| Battery action | **Force discharge**, **kW**, Power `2.5` |
| Entry conditions (Match ALL) | Tariff: in peak-demand window `==` `1` |
| | Grid power (W) `>` `1000` |
| | Battery SoC (%) `>` **Lookup** Const: demand-charge min SoC (%) |
| Hold (HH:MM:SS) | `00:01:00` |
| End early when… (Match ANY) | Tariff: in peak-demand window `==` `0` |
| | Battery SoC (%) `<=` **Lookup** Const: demand-charge min SoC (%) |
| Priority | `20` |
| If busy | `override` |

How it behaves:

- The one-minute hold ignores short load spikes.
- **Tariff: in peak-demand window** has **no value** when the tariff defines no demand
  window, so the gate fails and the schedule does nothing (on the Modbus Bridge it reads 0).
- If recipe 2 is already discharging, priority is compared first: this one (20) is higher, so
  **If busy** decides: `override` takes the battery, `defer` skips this half hour, `wait`
  retries each tick.
- **Do not combine this with recipe 2 on one gateway.** Once this one takes over, recipe 2's
  discharge is replaced, not paused: this half hour's window end releases this force, and
  recipe 2's discharge does not come back (its own window end then sends nothing).
- `grid.power_w` is positive when importing. Once the battery discharges, import drops, but
  the run continues: the gate is not checked again until the next half hour.

The Modbus Bridge's *Peak-demand shaving* template is **not in this bridge**; its
**Templates** include *Peak shaving (discharge at peak)*, a 16:00–21:00 force discharge with
an SoC gate.

## 6. Weekend export, unless Home Assistant says you are away

Export the battery on Saturday and Sunday evenings, except when a Home Assistant helper says
you are away.

Needs: a Home Assistant instance, with the helper **exposed** on the **Home Assistant** tab.

| Field | Value |
|---|---|
| Trigger type | **Weekly at time**, Days **Sat**, **Sun**, Fire at `18:00`, Duration (min) `120` |
| Battery action | **Force discharge**, **kW**, Power `3` |
| Entry conditions (Match ALL) | *your HA instance*: `input_boolean.home_mode` `==` `1` |
| | Battery SoC (%) `>` `50` |
| End early when… (Match ANY) | Battery SoC (%) `<=` **Lookup** Const: min discharge SoC (%) |

How it behaves:

- On/off helpers read `1` (on) and `0` (off). Compare with `1` or `0`, not `true`.
- **Prefer a helper that is on when it is safe to act** (`home_mode == 1`) over
  `away_mode == 0`: the rule then reads as what must be true before the battery moves. An
  entity that is `unavailable` or `unknown`, or an instance that cannot be reached, has no
  value, so the gate fails either way (before 0.5.4 an unavailable entity read 0, #167).
- To tell yourself, add a **+ notify** Home Assistant action with the message
  `Weekend export started at %battery.soc_pct%%`.

## 7. Full by 07:00, starting as late as possible

Charge overnight so the battery is full at 07:00, but start only when the time left is about
the time needed.

**Not in this bridge as written.** The Modbus Bridge's recipe gates on the hour of day
(`time.hour`); this bridge has no `time.*` sensors. Build the ladder from one schedule per
rung instead, each with its own cron hour:

| Schedule | Trigger | Entry condition |
|---|---|---|
| Rung 06 | **Custom cron** `*/15 6 * * *`, Duration (min) `14` | ETA to max-charge SoC at max rate (min) `>` `0` |
| Rung 05 | **Custom cron** `*/15 5 * * *`, Duration (min) `14` | ETA to max-charge SoC at max rate (min) `>=` `60` |
| Rung 04 | **Custom cron** `*/15 4 * * *`, Duration (min) `14` | ETA to max-charge SoC at max rate (min) `>=` `120` |
| Rung 00–03 | **Custom cron** `*/15 0-3 * * *`, Duration (min) `14` | ETA to max-charge SoC at max rate (min) `>=` `180` |

Each with **Force charge** and **End early when…** Battery SoC (%) `>=` **Lookup** Const: max
charge SoC (%).

How it behaves:

- Each 14-minute window ends with a release, and the next one re-checks a minute later.
- `battery.time_to_charge_min` needs the **battery capacity** constant, and uses the Modbus
  client (this bridge)'s Model 702 rating, else the battery max power constant (default
  5 kW). If you set a lower power, add margin.
- The rungs never overlap in time, so the release at each window end does not cut another
  rung's force. A schedule from another recipe on the same gateway could still be cut.

## More ideas

| Goal | Sketch |
|---|---|
| Solar sponge | **Templates → Solar sponge (charge midday)**: 11:00 for 240 minutes, force charge to 100 % while SoC is below 80 %. |
| Export bonus | **Templates → Battery Bonus export (evening)**, or gate on `Tariff: in battery-export-bonus window == 1`. |
| Free-import window | Force charge with the gate `Tariff: import billable == 0`. |
| Alert on a timezone change | **Not in this bridge**: there is no `time.tz_ok` sensor. The schedules run on the site's clock read from the aGate; see [Restarts and the clock](restarts-and-clock.md). |
| Do nothing on a collar | **Not in this bridge**: there is no `gateway.battery_capable` sensor. Bind battery schedules to battery gateways. |
| Respect the plan | Add `Utility: battery export allowed == 1` to every discharge schedule. |
| Hold during a VPP event | Gate force schedules on `Under external control / VPP mode == 0`. |

## More examples (Direct Connect only)

These came from the old troubleshooting page and use this bridge's **Templates**.

### Low-battery alert

Tell me when the battery drops below 20 %. No battery action.

1. **Templates → Low battery alert (notify only) → Use**.
2. Under **Home Assistant actions**, pick your notification device.
3. Tick **Enabled** and press **Create Entry**.

It is a **Daily at time** window from 00:00 for 1439 minutes, so it fires at most once a
day, the first time SoC is below 20 %. The message uses `%battery.soc_pct%` for the live
value. Between 23:59 and 00:00 the window is closed.

### Notify at the start and end of the peak window

1. **Templates → Peak window — notify start & end → Use**.
2. Pick your notification device. The action's **when** is **Entry & exit**, so you get one
   message at 16:00 and one at 21:00.

The exit message is sent when the window closes whether or not the entry message went out;
that is by design.

### Overnight off-peak charge

Charge overnight on the cheap rate, only if the battery is below 50 %, up to 90 %. Needs the
Modbus client (this bridge).

1. **Templates → Off-peak charge (overnight) → Use**.
2. Check the window: **Fire at** `01:00`, **Duration (min)** `300`.
3. Check the action: **Force charge**, `100` **% of inverter power**, **Target SoC** `90`.
4. Tick **Enabled** and press **Create Entry**.

The force stops at 90 % or at 06:00, whichever comes first.

### Time-of-Use at peak, then back to Self-Consumption

A mode change stays until something changes it, so this takes two schedules.

1. **Templates → Time-of-Use at peak (only if charged) → Use**. It switches to Time-of-Use at
   16:00, only if SoC is above 50 %. Save it.
2. **Add schedule**. **Trigger type:** **Daily at time**, **Fire at** `21:00`, **Duration
   (min)** `0`. **Battery action:** **Set operating mode**, Self-Consumption. Save it.

A duration of 0 is a one-minute window. Alternatively give the first schedule a duration to
21:00 and set `"restore_on_exit": true` through the API: at the window's end the bridge puts
back the mode it replaced. See [Exit and release](exit-and-conflicts.md).

!!! note "On/off actions saved before 0.5.5"
    Before 0.5.5 **Off** in the form ran as on: the circuit turned **on**, or the site went
    **off-grid** instead of reconnecting (#188, fixed in 0.5.5). If you had such a schedule,
    check what it did in **History**.
