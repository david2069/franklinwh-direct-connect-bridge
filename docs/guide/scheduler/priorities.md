# Priorities and conflicts

Direct Connect Bridge. Mirrors the Modbus Bridge page
[Priorities and conflicts](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/priorities/)
section for section.

Two schedules can want the same battery at once, or a schedule can open while a force from
the **Battery Control** widget is running. This page says which one acts.

![Priority, If busy (override / defer / wait) and Hold](../../images/scheduler/12-hold-and-conflicts.png)

| Setting | Values | Default |
|---|---|---|
| **Priority** | any whole number; higher wins | 0 |
| **If busy** | override, defer, wait | override |

Both sit in the **Battery action** box of the form. The API accepts any integer for
`priority` and any text for `conflict`; a value that is not `defer` or `wait` behaves as
**override**.
<!-- @b PRI-01 ;; src: app.py:660-665, scheduler.py:2129-2139, templates/tabs/scheduler.html:528-541 ;; untested ;; write: no ;; b: priority is any integer (default 0) and conflict is free text (default override); anything other than defer or wait acts as override ;; test: unit (API): POST conflict 'xyz' and priority -5, assert accepted; tick with a busy battery, assert it takes control -->

## Entries on the same target

Schedules compete for a **resource**, not for a whole gateway. Each battery action claims
one:

| Battery action | Resource it claims |
|---|---|
| Force charge / discharge / standby, Set operating mode, Set reserve SoC | the gateway's **battery** |
| Go off-grid / reconnect | the gateway's **grid** connection |
| Smart circuit on/off | that **circuit**; with no circuit set, every circuit on the gateway |
| Notify (Home Assistant), No battery action (HA only) | nothing: never competes |

<!-- @b PRI-05 ;; src: scheduler.py:2183-2212 ;; tested: tests/test_scheduler.py::test_force_and_mode_claim_the_same_battery ;; write: yes ;; b: force, set_mode and reserve_soc claim the same '<gw>/battery' resource, so a mode entry and a force entry contend -->
<!-- @b PRI-17 ;; src: scheduler.py:2183-2228, scheduler.py:2095-2101 ;; tested: tests/test_scheduler.py::test_an_unscoped_circuit_write_claims_every_circuit ;; write: no ;; b: offgrid claims 'grid', each smart circuit its own circuit, a circuit with no number claims circuit:* which is merged with every specific circuit before a winner is picked; an unknown kind claims only itself (see also test_two_circuits_on_one_gateway_do_not_contend, test_offgrid_is_different_hardware_from_the_battery, test_an_unknown_action_contends_with_itself_not_the_battery) -->
<!-- @b PRI-18 ;; src: scheduler.py:2189, scheduler.py:2200-2204, scheduler.py:2093-2094 ;; tested: tests/test_scheduler.py::test_a_notify_rule_claims_nothing ;; write: no ;; b: A notify or no-action entry claims no resource and always fires -->

On each tick, among the schedules that are **ready to fire on that tick** (window open,
entry conditions true, hold passed, not fired yet this occurrence):

1. Schedules that claim the same resource on the same gateway are put in one group.
2. In each group the **highest priority** wins. Ties go to the **oldest** schedule
   (created first), so renaming a schedule never changes the winner.
3. Every other schedule in the group is **deferred for the rest of its occurrence**: the
   History view logs *deferred* — "'<winner>' (priority N) holds battery this occurrence;
   this rule is priority M", the card's last result reads *deferred*, and the run is
   recorded as skipped. It does not fire later in the same window, even after the winner
   has finished.

<!-- @b PRI-02 ;; src: scheduler.py:2078-2118 ;; tested: tests/test_scheduler.py::test_priority_resolution_defers_lower_on_same_target ;; write: yes ;; b: Among entries ready on the same tick and claiming the same resource, the highest priority fires and only the winner touches the battery -->
<!-- @b PRI-04 ;; src: scheduler.py:2283-2293 ;; untested ;; write: yes ;; b: Ties are broken by created_at ascending (then id), not by name ;; test: unit: two equal-priority force entries ready on one tick, the older created_at wins; rename one, same winner -->
<!-- @b PRI-06 ;; src: scheduler.py:2104-2118, scheduler.py:2296-2314 ;; tested: tests/test_scheduler.py::test_priority_resolution_defers_lower_on_same_target ;; write: yes ;; b: A loser is logged deferred naming the winner, its occurrence is settled skipped and it is marked fired 'deferred', so it does not fire again in that occurrence -->

**Priority also counts against a running force** (#196). A force schedule that becomes
ready **later**, while another schedule's force is running on the same battery, does not
take it over if the running schedule has a **higher** priority. It is deferred for the
occurrence and logs *deferred* — "deferred — '<name>' (priority N) is running a force on
this battery; this rule is priority M". With equal or higher priority, its **If busy**
setting decides (see below): with *override* it takes the battery, with *defer* it gives
way even if its priority is higher.

!!! warning "Some things priority does not cover"
    A force from the **Battery Control** widget has no priority: *override* still replaces
    it. And a **Set operating mode** schedule is never checked against a running force: the
    mode is written while the force runs.
    <!-- @b PRI-03 ;; src: scheduler.py:2396-2430 ;; tested: tests/test_force_ownership.py::test_a_lower_priority_force_does_not_override_a_running_one ;; write: yes ;; b: A later-ready force entry is deferred when a running force's schedule has a higher priority; with equal or higher priority If busy decides; widget forces and non-force entries are not judged by priority (see also test_a_higher_priority_force_still_overrides) -->

!!! tip "Give one-shot schedules a short window"
    A **Set operating mode** schedule claims the battery only on the tick it fires, so it
    does not block a force schedule for its whole window. It can still beat a force schedule
    that becomes ready on the **same** tick, which is then deferred for its whole occurrence.
    Give mode schedules a different start time from force schedules.

### Example

| Schedule | Priority | Window | Entry conditions |
|---|---|---|---|
| Evening discharge | 10 | 17:00 for 240 min | SoC > 20 % |
| Peak-demand shave | 20 | 17:00 for 30 min, every day | `tariff.demand_window_active == 1` |

At 17:00 both open. If the demand gate passes, *Peak-demand shave* fires (20 > 10) and
*Evening discharge* is deferred **until tomorrow**. If the demand gate fails, *Evening
discharge* fires; when *Peak-demand shave* becomes ready a few ticks later its priority
(20 > 10) lets its **If busy** decide: with *override* it takes the battery. When its 30
minutes end, its window close releases its own force. The evening discharge is not resumed:
it was replaced, so its own window end later sends nothing (see
[Exit and release](exit-and-conflicts.md#how-a-run-ends)). Avoid overlapping force
schedules on one gateway.

## Manual control

**If busy** applies only to a schedule whose action is **Force charge / discharge /
standby**. It looks at the force commands the bridge has **recorded** as running on that
gateway's host (the `dispatches` table), and ignores the schedule's own:

- a force started by **another schedule** (including one started by **Run now**);
- a force started from the **Battery Control** widget on the Control tab (recorded as
  `_widget`).

<!-- @b PRI-07 ;; src: scheduler.py:2119-2140, db.py:2257-2266, app.py:3570-3574 ;; tested: tests/test_scheduler.py::test_conflict_defer_skips_when_battery_busy ;; write: yes ;; b: If busy is applied only to force winners, against active dispatches rows on the host whose schedule_id is another schedule or _widget -->

| If busy | API `conflict` | What happens |
|---|---|---|
| **override** (default) | `override` | Sends its own force, which replaces the running one, unless the running one's schedule has a higher priority. |
| **defer** | `defer` | Does not send. Logs *deferred* — "the battery is already under another dispatch (conflict=defer)" and marks the day as done: it does not try again later that day. |
| **wait** | `wait` | Does not send. Logs *waiting* — "battery busy with another dispatch (conflict=wait); will retry", and tries again on the next tick while the window is open. |

<!-- @b PRI-08 ;; src: scheduler.py:2130-2134 ;; tested: tests/test_scheduler.py::test_conflict_defer_skips_when_battery_busy ;; write: yes ;; b: defer does not touch the battery, logs deferred and marks the entry fired 'deferred' for today's date -->
<!-- @b PRI-09 ;; src: scheduler.py:2139-2140 ;; tested: tests/test_scheduler.py::test_conflict_override_takes_control ;; write: yes ;; b: override sends its own force over another schedule's running dispatch -->
<!-- @b PRI-16 ;; src: scheduler.py:2135-2138 ;; tested: tests/test_scheduler.py::test_conflict_wait_retries_not_fired ;; write: yes ;; b: wait does not mark the entry fired, logs waiting and retries on the next tick -->

After a deferred schedule's day is marked done, it does not take over when the other force
ends. A *wait* schedule does: it fires on the first tick after the other force's record is
closed, if its window is still open.
<!-- @b PRI-10 ;; src: scheduler.py:2130-2138 ;; untested ;; write: yes ;; b: defer gives up for the day; wait re-tries every tick and fires once the other dispatch row is closed ;; test: unit: busy row, wait entry ticks waiting, close the row, next tick sends -->

!!! warning "*wait* logs every tick; *defer* can repeat on interval, cron and second windows"
    *wait* writes a *waiting* row on every tick (every 15 s) while the battery is busy.
    *defer* marks today's **date** as done, but the occurrence of an *Every N minutes*,
    *Custom cron* or second-or-later *Recurring windows* window is not a date, so such a
    schedule is deferred, and logged, again on every tick. From a code read; not tested.
    Issue #204.
    <!-- @b PRI-19 ;; src: scheduler.py:2131, scheduler.py:540 ;; unclear ;; write: no ;; b: defer marks last_fired_day with the date, which matches only date-keyed occurrences, so interval, cron and window #n entries are deferred and logged every tick ;; test: unit: interval force entry with defer and a busy row, two ticks, assert one deferred row (fails today) -->

### What the bridge cannot see

- **A force from anything else**: the Modbus Bridge or another Modbus client of the
  Modbus TCP Server (aGate :502), the FranklinWH app, or a VPP. None of these is in the
  bridge's `dispatches` table, so a schedule dispatches over them, whatever its **If busy**.
  The History view's **battery** chip shows *vpp-start* / *vpp-stop* when the VPP monitor
  notices external control.
  <!-- @b PRI-11 ;; src: scheduler.py:2121-2128 ;; untested ;; write: yes ;; b: Only rows in the bridge's own dispatches table count as busy; a force from another Modbus client or a VPP does not, so entries dispatch over it ;; test: unit: no dispatch row but the battery reports a force, assert a defer entry still sends (documents today's behaviour) -->
- **A record that was never closed.** The check reads the `dispatches` table, not the
  aGate. A row stays *active* until the bridge releases that force or the boot reconcile
  closes it. While a stale row is active, *defer* and *wait* schedules keep giving way.
  **Unverified** how often this happens in practice.

**Not in this bridge:** ownership matching by action label, and supervision that re-sends a
command over a manual one. This bridge does not supervise a running force (see
[Outcomes](outcomes.md#supervision-of-a-running-command)).

## Entries on different targets

A schedule has no target type here, only a gateway (see [Targets](targets.md)), so the
Modbus Bridge's "different targets" case does not arise in the same way:

- An **unbound** schedule (Default gateway) and a schedule **bound** to that same gateway
  claim the same resource and are compared by priority on the same tick.
- A schedule with gateway scope `all` claims each gateway's resource **on that gateway's
  own tick**, so it competes separately on each gateway.

<!-- @b PRI-13 ;; src: scheduler.py:2084-2092 ;; tested: tests/test_scheduler.py::test_an_all_scope_rule_claims_each_gateway_separately ;; write: yes ;; b: The claim uses the tick's gateway for scope all and for unbound entries, so all-scope rules contend per gateway and an unbound entry contends with one bound to the default gateway -->

## Who sent what (requester)

Each force the bridge sends is recorded in the `dispatches` table with who started it:
the schedule's id for a scheduled run or **Run now**, `_widget` for the Battery Control
widget. That record is what **If busy** reads, what **Stop** looks for, and what the boot
reconcile acts on. There is no REST endpoint that lists it.
<!-- @b PRI-14 ;; src: scheduler.py:1582-1597, app.py:3562-3574, db.py:2214-2232 ;; tested: tests/test_dispatch_reconcile.py::test_widget_force_is_persisted_and_release_closes_it ;; write: no ;; b: A successful force writes a dispatches row with schedule_id = the schedule id (scheduled or Run now) or _widget, and a Release from the widget closes it -->

**Not in this bridge:** a per-command requester in the control log
(`— by schedule:<id>`). See [Outcomes and audit](outcomes.md).
