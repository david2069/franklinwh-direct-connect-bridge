# Exit and release

Direct Connect Bridge. Mirrors the Modbus Bridge page
[Exit and release](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/exit-and-conflicts/)
section for section.

How a schedule's window closes, and what the bridge does to the gateway when it does.
Everything here is **per gateway**: a schedule with gateway scope `all` closes its window
on each gateway on that gateway's own tick (see [Targets](targets.md)).

What happens when two schedules, or you and a schedule, want the same battery is on
[Priorities and conflicts](priorities.md). Run now, Stop and the History view are on
[Outcomes and audit](outcomes.md).

## How a run ends

![End early when Battery SoC <= 20](../../images/scheduler/16-exit-conditions.png)

This bridge has no "run" that the engine owns. It tracks one thing per schedule and
gateway: whether the schedule's **window** was open on the last tick. When the window
closes, for any reason, the bridge runs the **exit steps** once:

1. it runs the exit-tagged Home Assistant actions (**On exit** and **Entry & exit**),
   each only if its guard holds;
2. if **restore on exit** is set, it puts the operating mode back (see
   [Release policy](#release-policy));
3. if the schedule's battery action is **Force charge / discharge / standby** and this
   schedule **holds the force** on that gateway, it sends a **Release** and closes the
   dispatch record. Otherwise it sends nothing and the exit row says "no release: this
   schedule did not hold the force";
4. it logs an *exit* row in the History view: "exit condition met" or "window closed",
   followed by what each step returned.

A force command can also end **inside** the window, without these steps, when the bridge's
own watchdog releases it. The ways a force ends:

| End | How it shows | Fires again… |
|---|---|---|
| **Window closes** (window end, or fire time + Duration (min)) | *exit* — "window closed: force release: …" | at the next occurrence |
| **Exit conditions** become true | *exit* — "exit condition met: …" | at the next occurrence |
| **Duration reached** (the watchdog's time limit, taken from **Duration (min)**) | *dispatch-end* — "released — duration Ns reached" (under the **battery** chip) | at the next occurrence |
| **Target SoC** reached | *dispatch-end* — "released — target reached (SoC …)" | at the next occurrence |
| **Stop** on the card | *stopped* — "dispatch released by user" | at the next occurrence |
| Schedule **disabled** | *exit* — "window closed: force release: …", on the next tick | when enabled, at the next occurrence |
| Schedule **deleted** | *deleted* — "removed; force released: …" | never |
| **Bridge shuts down** | application log only | see [Bridge shutdown](#bridge-shutdown) |

<!-- @b EXT-01 ;; src: scheduler.py:2286-2294, scheduler.py:2093-2101 ;; tested: tests/test_force_ownership.py::test_window_end_still_releases_its_own_force ;; write: yes ;; b: When a force entry's window closes and it holds the active dispatch row on that host, the exit edge sends a Release, closes the row and logs exit 'window closed' -->

"Fires again at the next occurrence" means this: a schedule that ran successfully is
marked as fired for the occurrence (the day for daily-family triggers, the window for a
second or third time window, the slot for interval and cron). It does not fire again until
a new occurrence opens. <!-- @b EXT-02 ;; src: scheduler.py:538-541, scheduler.py:2453-2458 ;; tested: tests/test_scheduler.py::test_exit_condition_ends_window_early_and_releases ;; write: yes ;; b: After a run ends inside its window (here by an exit condition) the entry does not fire again in that occurrence, because the occurrence is marked fired -->
<!-- @b EXT-03 ;; src: scheduler.py:369-392 ;; tested: tests/test_scheduler.py::test_trigger_window_multiple_windows ;; write: yes ;; b: Each occurrence has its own key (date, date#n for later windows, slot or cron timestamp), so a fired mark for one occurrence does not block the next -->

Disabling a schedule while its window is open closes the window on the next tick, so the
exit steps run and a force is released. Turning it back on inside the same window does not
fire it again: the occurrence is already marked fired.
<!-- @b EXT-04 ;; src: scheduler.py:1997-2014, scheduler.py:2030-2033 ;; untested ;; write: yes ;; b: Disabling an entry makes time_inside false, so the next tick runs the exit edge and releases a force; re-enabling in the same occurrence does not re-fire ;; test: unit: fire a force, set enabled false, tick, assert Release and an exit row; re-enable, tick, assert nothing is sent -->

**Deleting a running schedule releases its force** first, on the aGate it was sent to, then
removes the schedule (#195). The History row reads "removed; force released: …". If the
Release fails the schedule is still deleted, and the force stays recorded so a restart's
reconcile still sees it; release it from the top bar.
<!-- @b EXT-21 ;; src: app.py:3244-3268 ;; tested: tests/test_force_ownership.py::test_deleting_a_running_schedule_releases_its_force ;; write: yes ;; b: DELETE releases the schedule's active dispatch on the row's host, closes the row as stopped only if the release succeeded, then removes the schedule (see also test_deleting_an_idle_schedule_sends_nothing) -->

**A window end releases only this schedule's own force** (#189). A schedule holds the force
from the moment its force is sent until it is released or a newer force on the same aGate
replaces it. So no Release is sent at the window end when:

- the schedule was **gated for its whole window**, or its force was refused;
- another schedule took over (*If busy = override*), or **Run now** or the **Battery
  Control** widget forced the same aGate since.

The bridge cannot see a force sent by another Modbus client of the Modbus TCP Server
(aGate :502), such as the Modbus Bridge. If one replaced this schedule's force, the window
end still sends a Release.

Exit-tagged Home Assistant actions still run at every window close, fired or not; that is by
design (see [Actions](actions.md#home-assistant-actions)).
<!-- @b EXT-05 ;; src: scheduler.py:2286-2294, scheduler.py:2093-2101, db.py:2234-2252 ;; tested: tests/test_force_ownership.py::test_window_end_does_not_release_a_force_it_never_started ;; write: yes ;; b: The exit edge releases only when the entry's dispatch row is the active one on that host; a gated entry, or one superseded by another schedule or Battery Control, logs 'no release' (see also test_window_end_does_not_release_a_force_another_rule_took_over, test_window_end_does_not_release_a_battery_control_force_on_its_gateway) -->

!!! warning "Exit conditions that flap repeat the exit steps"
    If exit conditions turn true, then false, then true again inside one window, every
    closing edge runs the exit steps again: the exit HA actions run again. The force is
    released only on the first edge; after that the schedule no longer holds it, so later
    edges log "no release". The schedule does not fire again in between, because the
    occurrence is already marked fired. From a code read; not tested.
    <!-- @b EXT-24 ;; src: scheduler.py:2259-2302 ;; unclear ;; write: yes ;; b: effective_inside goes true again when exit conditions stop holding, so each later true edge re-runs the exit steps; the Release is sent only while the entry holds the dispatch row ;; test: unit: force fired, exit true, exit false, exit true; assert one Release only -->

!!! warning "Duration (min) also limits the force (#160)"
    The force's watchdog time limit is the schedule's **Duration (min)**, in every trigger
    type. A **Recurring windows** schedule hides that field, and a new schedule starts with
    90. So a force in a three-hour recurring window stops after 90 minutes. Measured with a
    mock on 2026-10-17: a 17:00–20:00 window armed the watchdog with 5400 s. For force
    actions, use **Daily at time** or **Weekly at time**, or set `duration_min` through the
    API. [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160)
    <!-- @b EXT-25 ;; src: scheduler.py:2409-2413, scheduler.py:1577-1581, static/js/scheduler_tab.js:244 ;; unclear ;; write: yes ;; b: The watchdog duration_s is duration_min*60 for every trigger type; a window trigger keeps the hidden form default of 90 min ;; test: unit: window 17:00-20:00 with duration_min 90, assert duration_s 10800 (fails today, #160) -->

The watchdog checks every 5 seconds. It releases when the duration is reached, and, when a
**Target SoC** is set, when a charge reaches SoC ≥ target or a discharge reaches
SoC ≤ target. The SoC comes from the gateway's last poll.
<!-- @b EXT-26 ;; src: battery_control.py:92-110, scheduler.py:1560-1565 ;; untested ;; write: yes ;; b: The watchdog releases at duration_s or when SoC crosses target_soc in the force's direction, checked every 5 s from the poller's cached SoC ;; test: unit: arm the watchdog with a fake connect and soc_getter, assert release on duration and on target -->

!!! note "A restart forgets which windows were open"
    Whether a window was open is kept in memory. After a restart the first tick sees no
    open window, so a window that closes while the bridge is down, or the first close after
    a restart mid-window, may not run the exit steps. A force interrupted by a restart is
    handled by the interrupted-dispatch policy instead: see
    [Restarts and the clock](restarts-and-clock.md).

## Exit conditions

"End early when…" holds the exit conditions. They use the same sensors, operators, ALL/ANY
and groups as the entry conditions ([Conditions](conditions.md)), and the block has its
own **Test** button.

- They are checked on **every tick while the window is open**, for **every** kind of
  battery action and for HA-only schedules, whether or not the schedule has fired. A true
  exit condition closes the window at once and runs the exit steps above.
  <!-- @b EXT-09 ;; src: scheduler.py:2006-2009 ;; untested ;; write: yes ;; b: Exit conditions are evaluated whenever the window is time-inside, for every action kind (also set_mode and HA-only), not only for a running force ;; test: unit: a set_mode entry with an exit tree; fire, make exit true, assert an exit row 'exit condition met' -->
- If they already hold when the window opens, the schedule does not start. *Test against
  live* then says "exit condition already holds".
  <!-- @b EXT-07 ;; src: scheduler.py:2045-2048 ;; tested: tests/test_scheduler.py::test_exit_condition_blocks_firing_when_already_true ;; write: yes ;; b: A schedule whose exit conditions already hold in an open window is not started (reason 'exit condition already holds') -->
- When they become true after the schedule fired, the force is released, the exit row
  says "exit condition met", and the schedule does not fire again in that occurrence.
  <!-- @b EXT-08 ;; src: scheduler.py:2014-2038 ;; tested: tests/test_scheduler.py::test_exit_condition_ends_window_early_and_releases ;; write: yes ;; b: Exit conditions becoming true run the exit edge: Release for a force, an exit row with 'exit condition met', and no re-fire in that occurrence -->
- Nested ALL/ANY groups work in exit conditions too.
  <!-- @b EXT-22 ;; src: scheduler.py:2007-2008, scheduler.py:207-262 ;; tested: tests/test_scheduler.py::test_exit_condition_nested_group_ends_window ;; write: yes ;; b: An exit tree with a nested group is evaluated like an entry tree and its true edge releases the force -->

The *exit* row's detail is "exit condition met" plus what each exit step returned. It does
not list which condition rows were true or false.
<!-- @b EXT-10 ;; src: scheduler.py:2034-2038 ;; tested: tests/test_scheduler.py::test_exit_condition_ends_window_early_and_releases ;; write: no ;; b: The exit row reads 'exit condition met' or 'window closed' plus the exit steps' results; it names no condition rows -->

**Not in this bridge:** exit conditions tied to a running command. The Modbus Bridge checks
exit conditions only while its entry owns a force command, and not for one-shot or HA-only
entries. Here they apply to every schedule, as a second way to close its window.

Typical exits: `battery.soc_pct <= const.min_discharge_soc` (with **Lookup**) for a
discharge, `battery.soc_pct >= const.max_charge_soc` for a charge.

## Release policy

**Not in this bridge.** There is no release policy (*release → native*,
*restore_prior_mode*, *set_operating_mode:<Mode>*). A force always ends with a plain
Release. A Release action does not exist either: see [Actions](actions.md).

### Restore on exit (Direct Connect only)

**Direct Connect only.** `restore_on_exit` (API only, default off) puts back what the
schedule overrode when its window closes. Today it covers one thing: the **operating mode**
of a **Set operating mode** schedule.

- Before the first attempt of a run, the bridge records the mode the gateway is in, from
  the live snapshot. A retry does not record it again, so it never "restores" the value the
  schedule itself set. If the old mode cannot be read, nothing is recorded and nothing is
  restored.
  <!-- @b EXT-27 ;; src: scheduler.py:2157-2167, scheduler.py:2237-2254, db.py:1883-1889 ;; tested: tests/test_scheduler.py::test_capture_reads_the_mode_that_is_about_to_be_replaced ;; write: yes ;; b: With restore_on_exit, the current mode.name is captured before the first attempt and stored once per occurrence; nothing is captured when it cannot be read (see also test_a_retry_cannot_overwrite_the_captured_prior_state) -->
- At the window's close (time, exit conditions or disabling), the bridge sends **Set
  operating mode** with the recorded mode, unless the gateway is already in it, and adds
  "restored mode.name -> …" to the *exit* row.
  <!-- @b EXT-12 ;; src: scheduler.py:2023-2029, scheduler.py:2257-2280 ;; untested ;; write: yes ;; b: At the exit edge restore_on_exit writes the captured mode back with set_mode unless the snapshot already shows it ;; test: unit: set_mode entry with restore_on_exit, capture Self-Consumption, fire TOU, close the window, assert set_mode('Self-Consumption') -->
- **Stop** does not restore. Neither does a force: it releases instead.
- The form has no control for it, and since 0.5.2 saving from the form keeps it
  ([#157](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/157)).
  Before 0.5.2 the form turned it off.
  <!-- @b EXT-28 ;; src: app.py:3111-3127 ;; tested: tests/test_schedule_update_merge.py::test_a_form_save_keeps_api_only_fields ;; write: yes ;; b: A PUT without restore_on_exit keeps the stored value (merge, #157) -->

!!! warning "The restore sends the mode name as the poller read it"
    The recorded value is `mode.name` from the snapshot (a display name such as
    "Self-Consumption", or a tariff name). It is sent to the gateway as the mode. Whether the
    gateway accepts every such name is **unverified**; and a rejected mode write is not
    reported as a failure (see [Outcomes](outcomes.md#retries)).

### What a release does on the gateway

A Release goes through the Modbus client (this bridge) to the Modbus TCP Server
(aGate :502). The bridge calls the library's `reset_control_state()`, forgets the force it
was holding in memory, and logs *dispatch-end* if it was holding one. It does not read the
setpoint back: it reports "released" without checking
([#174](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/174)). With the
Modbus client (this bridge) switched off, a Release is refused.
<!-- @b EXT-17 ;; src: battery_control.py:496-517 ;; untested ;; write: yes ;; b: Release calls reset_control_state, clears the in-memory dispatch, fires dispatch-end if one was held, never reads back, and is refused when the Modbus client is off ;; test: unit: fake controller; assert reset_control_state called and the result; available() false returns ok false (#174) -->

## Hold instead of release (API only)

**Not in this bridge.** There is no *hold* option: at the window's end a force is released,
never switched to Force Standby. To hold the battery between windows, add a schedule with
**Force standby (hold)** for that time.

## Bridge shutdown

On a graceful shutdown the bridge stops the scheduler, then releases every force it is
holding in memory, each on the aGate it was sent to (#192), and logs "battery force:
releasing … on … (shutdown)" in the application log. No History row is written, and exit HA
actions do not run.
<!-- @b EXT-20 ;; src: app.py:1253, battery_control.py:304-310 ;; tested: tests/test_multigw_force.py::test_shutdown_releases_every_held_gateway ;; write: yes ;; b: On shutdown every held force is released on its own host -->

A crash or power loss releases nothing. What happens to an interrupted force at the next
start depends on the interrupted-dispatch policy: see
[Restarts and the clock](restarts-and-clock.md) and
[After a bridge restart mid-dispatch](../control.md#after-a-bridge-restart-mid-dispatch).
