# Smart Dispatch

[Back to HEMS](index.md)

The **Smart Dispatch** tab plans the next 24 hours of your battery, half hour by half hour,
from your utility plan's prices, the solar forecast, your home's load forecast and the
battery's charge. It shows what it would do now and why.

**It is a plan only.** It doesn't charge, discharge or change the mode: nothing is written to
the aGate or the FranklinWH cloud, and no schedule is created. Acting on the plan comes in a
later phase.

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
- **Each half hour:** the action and why. The actions are relative to self-consumption:

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
of the same action is one task, split at midnight. **Preview only:** the tasks are not
created.

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
