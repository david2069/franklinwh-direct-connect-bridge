# Smart Dispatch

[Back to HEMS](index.md)

The **Smart Dispatch** tab plans the next 24 hours of your battery, half hour by half hour,
from your utility plan's prices, the solar forecast, your home's load forecast and the
battery's charge. It shows what it would do now and why.

**The tab itself never controls the battery.** Nothing it does writes to the aGate or the
FranklinWH cloud. With **Create schedules** it adds the plan to the **Scheduler** as one-off
tasks, and the Scheduler runs them (see [Draft schedules](#draft-schedules)). With
[Auto](#auto) On, it does that every hour on its own.

## What it needs

| Needed | Where to set it |
|---|---|
| Your utility plan (tariff) | **Billing & Utilities → Plans & meters** |
| Battery capacity | **Settings → Gateways → System setup** (aPower model), or your constants |
| A first reading from the gateway | Automatic |
| Solar forecast (optional) | **Settings → Location & Prices → Location & Solar** (location and solar size) |
| Load forecast (automatic) | Learnt from the bridge's history; with less than a few days it plans with what it has and says so |

While something is missing, the tab lists it under **Needed for a plan**, with **Open** to go
there.

## Your target and your utility's limits

Once a utility plan is entered, the tab asks what you want the battery to do and what your
utility allows. Pre-filled answers are marked **Please confirm**. Only the questions that fit
your plan and site are asked.

| Question | Choices |
|---|---|
| What should the battery optimise for? | **Emergency Backup only** (keep it charged; never discharge for savings) · **Follow my time-of-use rates** · **Lowest bill, including demand charges** · **Self-consumption** (use your own solar and battery first; ignores prices) · **Most export earnings, with low grid charges** |
| Lowest charge to keep (reserve) | % (never planned below) |
| Highest charge to plan to | % |
| Solar size | Shown from Settings; change it there |
| Charging the battery from the grid | Allowed · Limited to a size (kW) · Prohibited |
| Exporting to the grid | Allowed · Limited to a size (kW) · Prohibited (asked when you have solar or an export tariff) |
| Export from the battery | Yes / no (only *Most export earnings* starts at yes) |
| Shave peaks in demand-charge windows | Yes / no (asked when your plan has a demand charge) |
| Export penalties | A note when your plan charges for some export or its export price can go negative |

**Check** works the plan out with your answers without saving them; **Save** keeps them.

## The plan

- **Now:** the action, why, until when, and the charge it aims for.
- **Planned cost** against **self-consumption alone** (what the aGate does without a plan),
  the **saving** (counting the value of the energy left in the battery at the end), and the
  **value of 10 % charge**.
- **Next 24 hours:** planned SoC, battery kW, and import and export prices.
  - **Tariff shading** (owner 2026-11-25): the chart shades your tariff's windows, each with
    its own filter, shown only when your plan has it: **TOU bands** (off-peak green, shoulder
    amber, peak red), **Demand charge** (when a demand charge applies), **Export bonus** (when
    export pays more than its lowest rate in these 24 hours) and **Export penalty** (when
    exporting costs money). Where two overlap, the penalty, then demand, then bonus, then the
    band is shown.
  - **Tariff** (beside **Chart**) shows the same as bands, like the FranklinWH emulator's TOU
    schedule: the plan's action, the tariff band, and demand and export windows when there are
    any. Hover a band for its name and times.
  - **Actuals** adds what the battery did from the site's midnight to now, from the bridge's
    own history: actual SoC and battery kW (+ charging) on the chart, and earlier half hours
    above the plan in the table, with **Actual kW** and **Actual SoC** columns. The half hour
    under way shows both.
- **Each half hour:** the action, the tariff band (and *demand* inside a demand-charge
  window), the prices and why. The actions are relative to self-consumption:

| Action | Means |
|---|---|
| Self-consumption | Nothing to do: the battery follows the home and solar |
| Charge from grid | Charge from the grid now (only when you allow grid charging) |
| Export from battery | Sell from the battery now (only when you allow battery export) |
| Hold | Keep the battery's energy for later, or let solar export now and store later |

Below the table are the assumptions behind the plan: battery size, power, round trip, wear
cost, and which forecasts were used. The plan is worked out again every 15 minutes when the
tab is open, or straight away with **Re-evaluate**.

## Draft schedules

Below the plan, **Draft schedules** shows the plan as one-off **Scheduler** tasks: each run
of the same action is one task, split at midnight.

| Plan action | Task |
|---|---|
| Charge from grid | Force charge at the run's highest kW, to the SoC the plan reaches at its end |
| Export from battery | Force discharge at the run's highest kW, to the SoC the plan reaches at its end |
| Hold, battery idle | Force standby |
| Hold, battery discharging less | Force discharge at the run's highest kW (for example to keep a demand peak down) |
| Hold, battery still charging from solar | No task: self-consumption stores the solar as it comes, earlier than planned (forcing a charge could take it from the grid) |
| Self-consumption | No task |

A forced task ends at its window's end, as any force schedule does.

- **Clashes with:** names your enabled schedules on this gateway that drive the battery
  (force, mode or reserve) in the same window.
- **The gateway is in Time-of-Use:** outside the tasks' windows, its schedule in the
  FranklinWH app still charges and discharges.
- **Force charge and discharge need the Modbus client:** shown when this bridge's Modbus
  client is off (**Control → Modbus client**).

### Create schedules

**Create schedules** adds the drafts to the Scheduler as one-off tasks named
*Smart Dispatch: …*, enabled, on this gateway. It needs an admin or user account (custom
roles: the **Schedules** action).

- **Creating again** keeps the Smart Dispatch tasks that haven't started and are still in the
  plan, and replaces the rest. A task already running is left to finish, and a draft over it
  is not created.
- **Your own schedules are never changed.** A draft that clashes with one is not created; the
  card says which and why.
- **Edit a task in the Scheduler and it is yours:** Smart Dispatch no longer replaces it.
- **Force unavailable:** with the Modbus client off, nothing is created.

The card shows how many Smart Dispatch tasks are in the Scheduler, with **Open** to go there.
In the Scheduler they carry a **Smart Dispatch** badge, and the list and History can be
filtered by source (**Yours** / **Smart Dispatch**).
The Scheduler's log records each task created or replaced.

### Auto

**Auto** works the plan out again about every hour, while the gateway's readings are fresh:

| Auto | Every hour |
|---|---|
| Off | Nothing (the default) |
| Shadow | Logs what **Create schedules** would do: create, replace, keep, skip. Nothing is created |
| On | Does it: the same rules as **Create schedules** |

- **On needs a week of Shadow first.** The card shows when Shadow started and from when On is
  allowed. Turning Auto off keeps the week already done.
- **An unchanged plan changes nothing:** tasks still in the plan are kept, so the Scheduler isn't
  rewritten every hour.
- **The log** under the selector shows the last 24 runs, and any reason a run did nothing (no
  plan yet, Modbus client off). A week and a day of runs are kept.
- **Turning Auto off** leaves the tasks already created; delete them in the Scheduler if you
  don't want them.

## How it plans

The plan comes from hems (`hems.dispatch`): dynamic programming over the battery's charge in
1 % steps, each half hour costed for your target (import less export at that half hour's
prices, battery wear per kWh, the demand charge on the window's peak), keeping inside your
SoC range and your utility's limits. If the plan would cost more than self-consumption,
self-consumption is the plan. Off grid, there are no grid actions.

Limits of this phase:

- Prices come from your tariff; live dynamic prices (Amber and the like) are not used yet.
- Battery power is the **Max continuous power (kW) — fallback** constant in Settings.
- An export charge's free allowance is ignored, so its penalty is counted on all export in
  its window.
