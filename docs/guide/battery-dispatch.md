# Battery dispatch: best practices

[Back to the guide index](index.md) · [Control and write safety](control.md) · [Scheduler](scheduler/index.md)

A **force** command (Force Charge, Force Discharge or Force Standby) tells the battery
exactly what to do, overriding the aGate's own operating mode until it is released. This
page is about using it well: which mode to leave the aGate in, how to time a force, how
to tell one is running, and how to end it.

The behaviour described here was read from the bridge's code on `main` (release 0.5.2)
on 2026-10-17, unless it says otherwise. It was not exercised on a gateway for this
page.

!!! danger "A force moves real power"
    A force charges from the grid or discharges into it at up to the battery's rated
    rate. Keep your system within the settings your installer configured and within
    your grid and VPP obligations.

---

## The two rules

### 1. Leave the aGate in Self-Consumption or Emergency Backup

Leave the aGate in its default operating mode, **Self-Consumption** or **Emergency
Backup**. Do not use the aGate's **Time-of-Use** (TOU) mode to time charging and
discharging. Use the bridge's [Scheduler](scheduler/index.md) instead: a **force** action in a
window, with conditions that decide whether it starts and exit conditions and a target
SoC that end it.

This is the owner's recommendation for this bridge. The reasons, from the code:

- The Scheduler can gate a force on live data, such as SoC, a price or a Home Assistant
  entity, and can end it early. See [Scheduler](scheduler/index.md).
- The aGate's TOU schedule cannot be written locally. `GET /api/capabilities` lists it
  as cloud-only ("1407 accepts the write and discards it"; see the
  [guide index](index.md#the-one-thing-to-understand-first)).
- When a force ends, the battery goes back to whatever the aGate's mode does. In
  Self-Consumption that is predictable. Releasing a force does not change or restore the
  operating mode: `battery_control` writes only the SunSpec power setpoint, and nothing
  in it writes the mode.

### 2. "VPP Mode" in the FranklinWH app is expected

!!! note "Observed by the owner, not documented by FranklinWH"
    On the owner's aGate in Australia (firmware V12R02B30D06), while a force from this
    bridge is active, the **FranklinWH app shows "VPP Mode"**, and the app cannot
    override it. To end it, release it from the bridge (below).

    This is one observation on one site and one firmware. It is not documented
    FranklinWH behaviour. The bridge's own code records a related measurement: during a
    force, the aGate's local run status (1707 `ibgRunStatus`) read 9 (comment in
    `vpp_monitor.py`, measured 2026-10-12).

So if you open the FranklinWH app during a scheduled charge and see VPP Mode, nothing is
wrong. Do not try to fix it from the app. Release it from the bridge if you want it to
end.

---

## What a force needs

**The Modbus client (this bridge) must be on.** Force commands go from the Modbus client
(this bridge) to the Modbus TCP Server (aGate :502). The client is **off on a new
install** (from 0.5.9); turn it on under **Control → Modbus client (this bridge)**. While it is off, the Battery Control card is
disabled and shows why: "This bridge's Modbus client is off (Control → Modbus client);
the aGate's Modbus TCP Server is not affected" (`battery_control.available()`).

Before each force the bridge checks that it can actually read the aGate over SunSpec
(`battery_control.capability()`). It reports one of **not configured**, **unreachable**,
**no SunSpec** or **ready**, and sends nothing unless the answer is ready.

The Modbus TCP Server (aGate :502) itself is an aGate setting. This bridge does not
change it, and you should not need to.

---

## Starting a force

| From | How |
|---|---|
| **Control → Battery Control** | Pick **Force Charge**, **Force Discharge** or **Force Standby** from **Command**, with power (watts or percent of the rated rate), a duration and an optional target SoC. It asks for confirmation. |
| **A schedule** | A `force` action. It starts when the window opens and the conditions hold. See [Scheduler → The force action in detail](scheduler/actions.md#battery-actions-force-charge-and-force-discharge). |
| **The API** | `POST /api/battery/command`. Not confirm-gated; see [Control](control.md#which-gate-applies-to-what). |

### Time the window with Daily or Weekly, not Recurring windows

For a scheduled force, use the **Daily** or **Weekly** trigger with a **Fire at** time and
a **Duration (min)** that is the window. Avoid **Recurring windows** for a force for now.

The reason is an open defect, **#160**. The force's watchdog takes its time limit from
the schedule's duration (`_force_dispatch()` in `scheduler.py`). The Recurring-windows
form hides the Duration field, and a new schedule gets 90 minutes from the form's
defaults. So a force in a three-hour recurring window releases after 90 minutes. With
Daily or Weekly, the duration you type **is** the window, and the two agree.

---

## How to tell a force is running

| Where | What you see | Source |
|---|---|---|
| Top bar | A **FORCE** chip, when the aGate reports a dispatch holding the battery. Its tooltip: "A force dispatch is holding the battery. The local/Modbus API can't confirm whether it's a VPP — that needs the Cloud API." A **VPP** chip instead when the cloud confirms a VPP. | `topbar.html`; `isForced` in `app.js` (local run status 9, or a VPP flag) |
| Top bar | A red, pulsing **Release** button, while this bridge holds a force. Hover it to see the command and the seconds left. | `topbar.html`; polled from `GET /api/battery/command` every 15 s |
| Dashboard | The **Run status** row, coloured, with a source chip. | `dashboard.html` |
| Control → Battery Control | The **Active** row shows the command. | `control.html` |
| FranklinWH app | "VPP Mode" (the owner's observation above). | — |

The FORCE chip and the Release button come from different places, so they do not
always agree:

- The **FORCE chip** comes from what the aGate reports on each poll. It shows for any
  force, whoever started it: this bridge, a Modbus Bridge, a utility VPP programme.
- The **Release button** shows only while **this bridge** holds a force in its own
  memory (`battery_control.current()`). A force started by something else shows FORCE
  but no Release button.

The Control tab's **Active** row is read when the tab loads and after each command. It
may not change by itself when the watchdog ends a force; reload to be sure. This is read
from the code and was not tested.

---

## Releasing a force

There are four ways, and they are not quite the same.

| Where | Label | What it does |
|---|---|---|
| **Top bar** | **Release** (red, pulsing) | Asks "Release force dispatch", then sends `Release` (`releaseBattery()` in `app.js` → `POST /api/battery/command`). Shown only while this bridge holds a force, and only if the **Release** item is switched on in the top-bar preferences. |
| **Control → Battery Control** | **Command → Release** (or **Not Active**) | Sends `Release` at once, without asking, because releasing is the safe direction (`battery_control.js`). |
| **Scheduler → a schedule card** | **Stop** | Shown while the schedule is active. Asks "Stop this schedule?", then `POST /api/schedules/{id}/stop`. Acts only if this schedule started a dispatch that is still running; then it releases, and marks the run stopped. The schedule stays enabled and does not fire again in the same window. |
| **API only** | — | `POST /api/schedules/{id}/pause` releases and keeps the run, so `POST /api/schedules/{id}/resume` can re-enter it while the window is open. There is no Pause button in the UI. |

There is no release item in any menu. The "use the Release button" wording in the
bridge's own messages (`vpp_monitor.py`) means the top-bar button.

What a release does: `battery_control.execute("Release")` tells the Modbus TCP Server
(aGate :502) to stop following the setpoint (`reset_control_state()` in the
`franklinwh-modbus` library), clears the bridge's record of the force, and closes the
saved dispatch record.

Things to know:

- **A release is global.** It clears whatever force the aGate is following, including
  one a schedule card's **Stop** did not start. Stop checks that its own schedule
  started a dispatch, but the release it sends is the same one.
- **A release needs the Modbus client (this bridge) on.** If you switch the client off
  while a force is running, the release is refused with the "Modbus client is off"
  reason, even though the code's comment says a release is always allowed. Switch the
  client back on, then release. (Read from `battery_control.execute()`; not tested.)
- **"Released" is reported without checking.** The library reads the setpoint back,
  but the bridge ignores the result and always reports `released`. Check the FORCE chip
  on the next poll.

!!! note "Planned: an always-visible Release"
    A Release button that is always visible, as in the Modbus Bridge, is planned in
    #165. It is not available yet.

---

## How a force ends on its own

| Event | What happens | Source |
|---|---|---|
| Its duration runs out | The bridge's watchdog releases it. It checks every 5 seconds. A duration of 0 means no time limit. | `_watch()` in `battery_control.py` |
| It reaches the target SoC | Charging stops at SoC ≥ target, discharging at SoC ≤ target, from the gateway's last poll. | `_watch()` |
| A schedule's window closes, or its exit conditions become true | On the first tick after, the schedule releases the force as a safety net, even if the watchdog already did. | `tick()` in `scheduler.py` |
| A newer force | The new command replaces the old one. | `battery_control` |
| The bridge shuts down cleanly | It releases a force it holds. | `lifespan` in `app.py` |
| The bridge restarts mid-force | `dispatch_interrupt_policy` decides. The default, `notify`, sends you a notification and does **not** touch the battery. | `reconcile_interrupted()` in `battery_control.py`; see [Control](control.md#after-a-bridge-restart-mid-dispatch) |

The aGate's own revert timer is not relied on. The code calls it "cosmetic" on this
firmware, so the bridge's watchdog is what ends a force. **If the bridge stops
unexpectedly, a force can keep running** until something releases it.

A schedule's **Restore on exit** option does nothing for a force. It applies only to
mode changes (`RESTORABLE` in `scheduler.py`); a force auto-releases.

---

## Known issues

Checked with `gh issue view` on 2026-10-17. All are open.

- **#160:** a force in a Recurring-windows schedule stops after the hidden duration
  (default 90 minutes), not at the window's end. Use Daily or Weekly (above).
- **#162:** the Scheduler has no **Release** action, no release policies, and no "hold
  instead of release". A force ends by its window, exit conditions, target SoC or
  duration.
- **#129:** a schedule's `reserve_soc` action is always skipped, even with cloud
  credentials. Do not rely on a schedule to set the reserve.
- **#122:** Home Assistant controls for the battery command (a select, staged
  parameters and status) are planned. Today Home Assistant can change the operating mode
  and smart circuits over MQTT, but cannot start or release a force.
- **#124:** detecting VPP through the cloud and through the Modbus client (this bridge)
  is to be retired in favour of the aGate's local run status. Until then, the VPP chip's
  wording may change.
