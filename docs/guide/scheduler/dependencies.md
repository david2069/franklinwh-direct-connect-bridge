# Dependencies and troubleshooting

Direct Connect Bridge. Mirrors the Modbus Bridge page
[Dependencies and troubleshooting](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/dependencies/)
section for section. It replaces the old *Scheduler: troubleshooting and examples* page; the
examples are now on [Examples](examples.md).

## Dependency matrix

✔ = required for a meaningful value or for the action to work. ◐ = optional, changes the
result. Blank = not needed.

### Conditions

A condition whose sensor has no value is **false**, for every operator. So a sensor that
depends on something you have not set up makes its condition fail. The sensors are listed on
[Conditions](conditions.md#every-sensor-in-the-picker).

| Sensors | Gateway poll | Modbus client (this bridge) | Constants | Meter + utility + tariff | NEM region / HA price entity | PV location | HA instance + exposed entity |
|---|---|---|---|---|---|---|---|
| `battery.soc_pct`, `battery.power_w`, `grid.*`, `solar.power_w`, `load.power_w`, `generator.power_w`, `mode.name`, `status.*`, `bridge.latency_ms` | ✔ | | | | | | |
| `battery.status` | ✔ | | | | | | |
| `battery.capacity_kwh`, `stored_kwh`, `remaining_kwh` | ✔ | | ✔ (battery capacity; 0 = unset) | | | | |
| `battery.time_to_*_now_min` | ✔ | | ✔ (capacity, SoC targets) | | | | |
| `battery.time_to_charge_min`, `time_to_discharge_min` (at max rate) | ✔ | ◐ (Model 702 rating, else the max power constant) | ✔ | | | | |
| `solar_forecast.day_pct`, `vs_expected_pct` | ✔ (today's solar) | | | | | ✔ | |
| `weather.*`, `solar_forecast.*` | | | | | | ✔ (+ kWp, tilt, azimuth) | |
| `solar.today_kwh` | ✔ | | | | | | |
| `tariff.buy_rate`, `sell_rate`, `season`, `time_period`, `tier`, `import_billable` | | | | ✔ | ◐ (dynamic tariff) | | |
| `tariff.*_window_active` | | | | ✔ (the window defined on the tariff) | | | |
| `tariff.spot_price`, `feed_in_price` | | | | ◐ (dynamic tariff) | ✔ | | ◐ (HA price entity) |
| `demand.*`, `bonus.*`, `energy.*`, `tariff.export_charge_*` | ✔ (grid power, each tick) | | | ✔ (those charges and windows) | ◐ (dynamic tariff) | | |
| `fixed.*` | | | | ✔ (fixed charges) | | | |
| `service.*` | | | | ✔ (utility; unset permissions read 1) | | | |
| `system.*` | ◐ (derived from the aGate) | | | | | | |
| `const.*` | | | ✔ (defaults exist) | | | | |
| `ha:<instance>:<entity>` | | | | | | | ✔ |

Where to set each one:

| Dependency | Where |
|---|---|
| Gateway poll | **Settings → Gateways** (host, enabled). A gateway whose last poll is older than three poll intervals (at least 90 s) is not evaluated at all. |
| Modbus client (this bridge) | **Control → Modbus client**: on, with the aGate's Modbus TCP Server (aGate :502) reachable and answering SunSpec. |
| Constants | **Settings → Automation → Automation Constants** |
| Meter, utility, tariff | **Energy & costs** (meters, utilities, tariffs); see [Energy and costs](../energy-and-costs.md) |
| NEM region, HA price entities, PV location | **Settings → Integrations** |
| HA instance and exposed entities | **Settings → Integrations** (instance) and the **Home Assistant** tab (expose) |
| Site timezone | **Settings → Setup → Where is this site?** |

### Actions

| Battery action | Gateway reachable (local) | Modbus client (this bridge) ready | Cloud credentials | HA instance | Notification device |
|---|---|---|---|---|---|
| **Set operating mode** | ✔ | | | | |
| **Smart circuit on/off** | ✔ | | | | |
| **Go off-grid / reconnect** | ✔ | | | | |
| **Set reserve SoC** | — never runs (#129) | | (listed as needed, not used) | | |
| **Notify (Home Assistant)** | | | | ✔ | ✔ (enabled) |
| **Force charge / discharge / standby** | | ✔ (on, library installed, a host, a SunSpec read that succeeds) | | | |
| No battery action (HA only) | | | | | |

| Home Assistant action | Needs |
|---|---|
| **+ notify** | a notification device. The button is disabled until you add one. |
| **+ entity** | a Home Assistant instance. The guided picker lists only exposed, controllable entities; **Advanced (raw service)…** takes any domain, service and entity. |

**The scheduler does not use MQTT.** Neither the engine nor its worker publishes or reads
MQTT; schedules run without a broker. MQTT entities for schedules are planned (#128).
<!-- @b DEP-01 ;; src: scheduler.py:1-30, scheduler_worker.py:20-30 ;; untested ;; write: no ;; b: scheduler.py and scheduler_worker.py import nothing from MQTT; schedules run with MQTT off ;; test: unit: run tick_once with mqtt_enabled false and no broker; assert an entry fires -->

The **Force** item in the **Battery action** list is disabled, with the reason, while the
Modbus client (this bridge) is not available. A schedule saved earlier with a force action
still runs; see the next section for what that does.

## Troubleshooting

Start with two tools on the Scheduler tab:

- **⋮ → Test against live** on the card. It says *Would fire* or *Would not fire*, with the
  reason ("outside its window", "not one of its days of the week", "already fired this
  occurrence", "entry conditions not met", …) and each top-level condition row with its live
  value. It reads the **default gateway** and the container's clock; see
  [Conditions → Test Verification](conditions.md#test-verification).
- The **History** view. Filter by *gated*, *error*, *missed* or *deferred* to see what the
  scheduler decided, and why.

### A condition is always false

| Cause | How to tell | Fix |
|---|---|---|
| The sensor has no value | the editor's **Test** marks the row amber, *no value*; Test against live shows "—" | Set up what the sensor needs (matrix above). |
| A Lookup sensor has no value | the row fails | Set that sensor up, or use a Value. |
| Wrong unit | `tariff.buy_rate` is $/kWh; `tariff.spot_price` is c/kWh | Check the sensor's label in the picker and the live value. |
| `in` used on text | text never matches a number list | Use **matchlist** for names. |
| `!=` on a missing value | `!=` is false with no value | Use a positive test, such as `status.vpp == 0`. |
| The text does not match | `==` ignores case, but the words must match | Use `like` with `*` for a partial match. |
| The tariff window is not defined | a window flag reads None when the tariff has no such window | Define the window on the tariff. |
| Second gateway | its tariff sensors come from its own meter, else the default meter | Connect the gateway to the right meter. |
| Tested on the wrong gateway | **Test** uses the top-bar gateway; Test against live always the default gateway | Pick the schedule's gateway in the top bar before **Test**. |

### A condition is always true when it should not be

| Cause | Fix |
|---|---|
| Before 0.5.4, a Home Assistant entity that was `unavailable` or `unknown` read **0**, so `price < 10` passed (#167, fixed in 0.5.4) | Update. Since 0.5.4 such an entity has no value and the condition is false. |
| `grid.connected` is derived from grid power being non-zero: `grid.connected == 0` is true whenever the grid power is exactly 0 W | Use `status.off_grid == 1` for an outage. |
| `service.*` permissions read 1 (allowed) when not set on the utility | Set them on the utility. |
| An empty `not_in` list is true | Fill the list. |
| An exit block sent through the API as an empty ALL group is true at once | Send an empty list for "no exit conditions". |

### An action is refused or does nothing

| Symptom | Cause | Fix |
|---|---|---|
| **Force** is greyed *unavailable* in the list | The Modbus client (this bridge) is off, not installed, or cannot read SunSpec from the Modbus TCP Server (aGate :502) | Fix it under **Control → Modbus client**. The reason is shown under the list. |
| History shows *error* — "force charge failed: …" | The Modbus client (this bridge) path refused the force: client off, "could not connect…", or SunSpec not answering. It is retried while the window is open | Fix it under **Control → Modbus client**. Check the **Logs** tab. |
| History shows *error* — "mode -> tou: failed: …" | The aGate rejected the mode or off-grid write. It is retried while the window is open | Read the result in the row. |
| **Set reserve SoC** shows *fired* but nothing changed | The action is always skipped, even with cloud credentials (#129) | Set the reserve in the FranklinWH app, or from **Control**. |
| A smart circuit turned **on** when the schedule said **Off**, or the gateway went **off-grid** when it said reconnect | Before 0.5.5 the form saved **Off** as text that ran as on (#188, fixed in 0.5.5) | Update, then check what such schedules did in **History**. Since 0.5.5 an On/Off value the bridge cannot read is refused, with no write. |
| The mode did not change back | A mode change is not undone at the end of the window, unless **restore on exit** is set (API only) | Add a second schedule, or set `restore_on_exit`. See [Exit and release](exit-and-conflicts.md). |
| A force stopped early | Its **Target SoC**, or its **Duration (min)**: a **Recurring windows** schedule still has the hidden duration (90 for a new one), and the force stops after it (#160) | Use **Daily at time** or **Weekly at time** for a force. |
| A force stopped when another schedule's window ended | That schedule had taken over the battery (*If busy = override*), and its window end released its own force; the replaced force does not come back | Do not overlap force schedules on one gateway. |
| History shows *exit* — "no release: this schedule did not hold the force" | The schedule never fired in its window, or another force replaced it | Nothing to do: the bridge did not release a force it did not start. |
| History shows *error* | The action failed; the bridge retries while the window is open, waiting 30 s, then doubling up to 10 minutes | If the window closes first, the run is logged as *missed*. |
| History shows *deferred* | Another schedule won the gateway on the same tick, a higher-priority schedule's force is running, or **If busy** = *defer* and another force is running | Change priorities, or **If busy**. |
| History shows *waiting* — "battery busy with another dispatch" | **If busy** = *wait* | It retries every tick while the window is open. |

### An entry never fires

| Cause | How to tell | Fix |
|---|---|---|
| Disabled | the card shows **Off**, **Next:** *disabled* | Turn it on. Imported and duplicated schedules start disabled. A `PUT` without `enabled` turns it **on** (#168). |
| Outside its window or calendar | Test against live: "outside its window", "not one of its days of the week", "before start date …" | Check the trigger and its restrictions. |
| Already fired this occurrence | Test against live: "already fired this occurrence" | It fires at most once per window. |
| Gate never passes | *gated* rows in History (once a day) with the failing values | Fix the conditions; use **Test**. |
| Hold too long | *waiting* row but no fire | Shorten the hold, or check the gate is not flickering. |
| Another schedule wins | *deferred* — "'<name>' (priority N) holds battery this occurrence" | Priority. |
| Exit condition already true | Test against live may still say *Would fire*; the engine logs nothing and does not start | Check **End early when…** with its **Test**. |
| An **Always** schedule ran once | nothing after its first run, ever | An Always schedule fires once and never again (#190). Use a repeating trigger. |
| Wrong gateway | a schedule on **Default gateway** runs only on the first-registered gateway; if that gateway is disabled, it runs nowhere (#182) | Bind the schedule to a gateway. See [Targets](targets.md). |
| Stale gateway data | the gateway has not polled for three poll intervals (at least 90 s); its schedules are skipped silently | Check the **Network** and **Health** tabs. |
| The window was short | the scheduler ticks every 15 s by default; a one-minute window is always seen | — |
| Paused | `pause` does not hold a run: the next tick tries it again (#200) | Disable the schedule instead. |

### A Home Assistant action did not run

**Direct Connect only** (from the old troubleshooting page, checked against the code):

- Check its **when**: **On entry**, **On exit** or **Entry & exit**.
- Check its guard. An action whose guard is false at that moment is skipped without a
  History row of its own.
- A value in the message that cannot be read shows as `?`; the message is still sent.
  `%ha:…%` placeholders are not replaced (#169).
- A notify device that is switched off, or whose instance is gone, is skipped: the fired
  row's text says "notify skipped: …".
- The **Push notifications** switch does not stop schedule notifications (#171).

## Where the old sections went

The old *Scheduler: troubleshooting and examples* page now redirects here. Its sections:

| Old section | Now |
|---|---|
| <span id="what-each-condition-needs"></span>What each condition needs | [Dependency matrix → Conditions](#conditions) |
| <span id="what-each-action-needs"></span>What each action needs | [Dependency matrix → Actions](#actions) |
| Troubleshooting | [Troubleshooting](#troubleshooting) |
| <span id="a-schedule-never-fires"></span>A schedule never fires | [An entry never fires](#an-entry-never-fires) |
| A condition is always false | [A condition is always false](#a-condition-is-always-false) |
| An action is refused or does nothing | [An action is refused or does nothing](#an-action-is-refused-or-does-nothing) |
| A Home Assistant action did not run | [A Home Assistant action did not run](#a-home-assistant-action-did-not-run) |
| <span id="examples"></span>Examples | [Examples](examples.md) |
| <span id="troubleshooting-and-examples"></span>(whole page) | this page and [Examples](examples.md) |
| <span id="1-low-battery-alert"></span>1. Low-battery alert | [Examples → Low-battery alert](examples.md#low-battery-alert) |
| <span id="2-notify-at-the-start-and-end-of-the-peak-window"></span>2. Notify at the start and end of the peak window | [Examples → Notify at the start and end of the peak window](examples.md#notify-at-the-start-and-end-of-the-peak-window) |
| <span id="3-overnight-off-peak-charge"></span>3. Overnight off-peak charge | [Examples → Overnight off-peak charge](examples.md#overnight-off-peak-charge) |
| <span id="4-time-of-use-at-peak-then-back-to-self-consumption"></span>4. Time-of-Use at peak, then back to Self-Consumption | [Examples → Time-of-Use at peak, then back to Self-Consumption](examples.md#time-of-use-at-peak-then-back-to-self-consumption) |
| <span id="5-only-when-home-assistant-says-so"></span>5. Only when Home Assistant says so | [Examples → 6. Weekend export, unless Home Assistant says you are away](examples.md#6-weekend-export-unless-home-assistant-says-you-are-away) |
