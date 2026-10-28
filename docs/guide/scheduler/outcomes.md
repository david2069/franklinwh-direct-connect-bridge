# Outcomes and audit

Direct Connect Bridge. Mirrors the Modbus Bridge page
[Outcomes and audit](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/outcomes/)
section for section.

How you find out what a schedule did: the History view, the run queue, the dispatch
record and notifications. Also the controls that act outside the schedule: **Run now**,
**Stop**, and the API-only **Pause** and **Resume**.

## Where to look

| Where | What |
|---|---|
| **Scheduler → History** | every decision the scheduler made and every change to a schedule, newest first (`GET /api/schedules/log`) |
| **Run queue** (`GET /api/schedules/runs`, `GET /api/schedules/stats`) | one row per run the scheduler expected: pending, running, ok, failed, missed, skipped, unknown, paused, stopped. No view in the UI. |
| **Card** on the Schedules view | the last result with its date, **Next:**, **● active** |
| **Logs** tab | the application log: each fired schedule (info) and each missed run (warning) |
| **Control-log** (`GET /api/control-log`) | Pause and Resume calls |

**Not in this bridge:** a per-command control log with requester and hardware state
before and after, and a dispatch-outcomes record (see [below](#the-dispatch-record)).

## Monitor

The **Monitor** card at the top of **History** shows why each schedule is, or is not,
running. Open it and it adds one line per enabled schedule per gateway after every
scheduler tick (every 15 s by default). Tap or hover a line to see each condition with its live
value and result. The bridge keeps the last 500 lines in memory only: they are not saved,
and a restart empties them. The card asks for new lines every 5 s, only while it is open.

| State | Meaning |
|---|---|
| idle | outside its window, or the calendar excludes today |
| blocked | the entry conditions fail (up to two failing rows with live values), or an exit condition already holds |
| holding | conditions met; the hold is counting down |
| ready | conditions met this tick |
| running | fired this occurrence and the window is still open |
| skipped | another rule held the target this occurrence; names the winner on the tick it lost |
| deferred | another dispatch holds the battery (*If busy = defer* or *wait*) |
| retrying | the action failed; attempts, the last reason and the next try |
| done | finished this occurrence |

**Pause** stops new lines arriving; **Resume** catches up. **Clear** empties the card
only, not the bridge. **Copy** copies the lines and their conditions.

## Activity Log results

The **History** view is this bridge's activity log. It loads the latest 200 rows. Times
are in bridge-host time. The chips at the top filter by status (one chip per status
present); **battery** shows the rows written by the force path and the VPP monitor.
<!-- @b OUT-03 ;; src: static/js/scheduler_tab.js:71-100 ;; untested ;; write: no ;; b: The History view fetches 200 rows, offers one chip per status present plus a battery chip for _batt and _vpp rows ;; test: browser: load History with mixed rows, assert the chips and the battery filter -->

| Status | Meaning |
|---|---|
| created, updated, enabled, disabled, deleted | a change to the schedule ("created enabled", "settings changed", "toggled", "removed") |
| fired | the action and the on-entry HA actions ran and were judged a success; the detail is what each returned, or "nothing to do" |
| gated | the window was open but the entry conditions failed; up to two failing rows with live values; once a day per schedule and gateway |
| waiting | conditions met and the hold is counting, or *If busy = wait* |
| deferred | lost a same-tick contest, or *If busy = defer* |
| exit | the window closed: "exit condition met" or "window closed" |
| error | the action failed; with the attempt number and the next retry |
| unknown | the outcome could not be told; not retried (see [Retries](#retries)) |
| missed | the window closed with no successful run |
| coalesced | an open run left by downtime was folded into the current one |
| manual | **Run now** |
| stopped, paused, resumed | **Stop**, or the Pause and Resume API calls |
| dispatch-start, dispatch-end | a force started or ended (also the watchdog's duration and target-SoC releases); under **battery** |
| vpp-start, vpp-stop, orphan | the VPP monitor; under **battery** |
| exception | the scheduler tick itself raised an error (a bug, not a rule) |

Changes to a schedule are logged with a short word only; the detail does not list which
fields changed. Import creates schedules without a *created* row.
<!-- @b OUT-01 ;; src: app.py:3095-3103, app.py:3124-3132, app.py:3140-3144, app.py:3295-3309 ;; untested ;; write: no ;; b: Create logs created, update logs enabled/disabled ('toggled') or updated ('settings changed'), delete logs deleted; import logs nothing; no field list ;; test: unit (API): create, toggle, edit, delete, import; assert the rows and that import writes none -->

Through the API, `GET /api/schedules/log` filters by `schedule_id`, `status` and
`severity`, newest first, `limit` 1–500.
<!-- @b OUT-02 ;; src: app.py:3311-3325, db.py:1025-1043 ;; tested: tests/test_scheduler.py::test_fire_history_is_logged_and_filterable ;; write: no ;; b: The schedule log is newest first and filters by schedule_id and status (store level) -->

Each row has a severity class: **error** for *error*, *failed*, *missed* and *unknown*;
**exception** for *exception*; **event** for everything else. Each class has its own cap
(2000, 1000 and 500 rows), so routine *gated* rows cannot push a failure out.
<!-- @b OUT-40 ;; src: db.py:991-1022 ;; tested: tests/test_occurrences.py::test_routine_chatter_can_no_longer_evict_a_failure ;; write: no ;; b: Log rows are classed event/error/exception from the status and capped per class, so the event cap cannot evict an error -->

A run that did nothing still leaves a row: an HA-only schedule with no HA actions logs
*fired* — "nothing to do".
<!-- @b OUT-41 ;; src: scheduler.py:2417, scheduler.py:2453-2458 ;; tested: tests/test_scheduler.py::test_a_fire_that_did_nothing_still_logs_why ;; write: no ;; b: An entry with no action and no HA actions logs fired 'nothing to do' -->

### The run queue (Direct Connect only)

**Direct Connect only.** Before it acts, the scheduler writes the run it expects into the
`occurrences` table: one row per schedule, gateway and occurrence. The row records attempts,
the outcome and the reason. `GET /api/schedules/runs` lists the rows, newest first;
`GET /api/schedules/stats` counts runs, ok, missed, failed, skipped, stopped and paused per
schedule, with the first, last and last failure. Finished rows are kept 90 days.
<!-- @b OUT-39 ;; src: scheduler.py:2142-2156, scheduler.py:2317-2350, db.py:2162-2211, app.py:3231-3242 ;; tested: tests/test_occurrences.py::test_stats_answer_runs_first_last_and_last_failure ;; write: no ;; b: Each run is claimed in occurrences before it is attempted; stats count runs, ok, missed and failed with first, last and last failure (store level) ;; test: unit (API): GET /api/schedules/runs and /stats return the rows, incl. skipped/stopped/paused counts -->

If several runs of one schedule on one gateway are still open, for example after downtime,
the older ones are closed as *skipped* — "coalesced into the run for …" and logged
*coalesced*. Only the newest proceeds; a backlog is never replayed.
<!-- @b OUT-30 ;; src: scheduler.py:2330-2346, db.py:1964-2000 ;; tested: tests/test_occurrences.py::test_an_older_open_run_is_collapsed_into_the_newer_one ;; write: no ;; b: Older open runs of the same schedule and gateway are closed skipped as coalesced into the newer one -->

## Retries

A failed action does not use up the occurrence. The run is left open and tried again
while the window is open:

- **Between ticks.** After *N* failed attempts the next try waits 30 s × 2^(N−1), capped at
  10 minutes: 30 s, 60 s, 2 min, 4 min, 8 min, then every 10 min. Each failure logs
  *error* — "… — attempt N; retrying in 60s while the window is open".
  <!-- @b OUT-04 ;; src: scheduler.py:2353-2372, scheduler.py:2151-2153 ;; tested: tests/test_occurrences.py::test_backoff_grows_and_is_capped ;; write: yes ;; b: A failed run is retried after 30 s doubling to a 600 s cap while its window is open -->
  <!-- @b OUT-42 ;; src: scheduler.py:2459-2466 ;; tested: tests/test_fire_entry_outcomes.py::test_a_failure_is_logged_with_the_retry_interval ;; write: yes ;; b: A failed attempt is not marked fired, the run is finished failed, and an error row names the attempt and the retry delay (see also test_a_failed_action_does_NOT_mark_fired) -->
- **Within one tick.** A device write (force, mode, smart circuit, off-grid) is also
  retried inside the call: up to 5 attempts for a force (waits of about 5, 10, 20 and 40 s)
  and 2 for the others, cut off at the window's end.
  <!-- @b OUT-33 ;; src: scheduler.py:1648-1679, resilience.py:97-109, resilience.py:160-211 ;; unclear ;; write: yes ;; b: A failing device write is retried inside resilience.call (DISPATCH 5 attempts, WRITE 2) with sleeps, inside the scheduler's tick thread ;; test: unit: run_action fails every time for a force with a 10-minute window; assert attempts and total time; assert other gateways still tick -->
- A success after failures logs *fired* and closes the run as ok. There is no
  "recovered after N attempts" wording.
  <!-- @b OUT-05 ;; src: scheduler.py:2453-2458 ;; tested: tests/test_fire_entry_outcomes.py::test_success_marks_fired_and_closes_the_run ;; write: yes ;; b: A successful attempt marks the occurrence fired, closes the run ok and logs fired -->
- A run that is retrying and then loses a same-tick priority contest is closed as
  *skipped*. <!-- @b OUT-06 ;; src: scheduler.py:2296-2314 ;; untested ;; write: yes ;; b: A loser's open run (pending or failed) is finished skipped with the winner named ;; test: unit: a failed run, next tick a higher-priority entry ready together; assert the run becomes skipped -->

!!! warning "A long in-tick retry holds up every gateway"
    The in-call retries run inside the scheduler's tick. A force that keeps failing can hold
    the tick for over a minute, and no gateway is evaluated meanwhile. Whether this caused
    the missed heartbeat in
    [#183](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/183) is
    **unverified**.

!!! danger "Some failures are recorded as *fired*"
    The scheduler decides success by reading the action's result text. A result counts as a
    failure only if it contains "failed", "error" or "not confirmed". So:

    - a **force** refused because the Modbus client (this bridge) is off, the
      Modbus TCP Server (aGate :502) does not answer, or SunSpec does not respond, is logged
      *fired* and the occurrence is used up ("force charge: This bridge's Modbus client is
      off …");
    - a **Set operating mode** or **Go off-grid** that the aGate answers with a non-zero
      result is logged *fired* ("mode -> tou: {'ok': False, 'result': 3}").

    Measured with mocks on 2026-10-17. Read the detail of a *fired* row, not just its status.
    Issue #191.
    <!-- @b OUT-34 ;; src: scheduler.py:1632-1646, scheduler.py:1598, scheduler.py:1785-1799, battery_control.py:496-508 ;; unclear ;; write: yes ;; b: _classify reads OK unless the text contains failed/error/not confirmed, so a force refused for capability and a mode/offgrid with a non-zero result are logged fired ;; test: unit: run_action_outcome for a force with the Modbus client off, and set_mode returning ok False; assert FAILED (fails today) -->

**An unknown outcome is not retried**: if the scheduler is told the outcome is *unknown*
(the write may have landed), it logs *unknown*, closes the run and does not send again.
<!-- @b OUT-31 ;; src: scheduler.py:2437-2452 ;; tested: tests/test_fire_entry_outcomes.py::test_an_unknown_write_is_never_retried_and_settles_the_run ;; write: yes ;; b: An UNKNOWN outcome settles the run as unknown, marks it fired, logs unknown and is not retried -->

!!! warning "In practice the scheduler never reports *unknown*"
    The action code never raises; a failure comes back as text, which the scheduler turns
    into a connection error that counts as "never arrived". So a failed write is always
    *error* and retried, never *unknown*. The test above reaches *unknown* only through a
    stand-in. From a code read. Issue #201.
    <!-- @b OUT-32 ;; src: scheduler.py:1655-1667, resilience.py:70-80, scheduler.py:1854-1855 ;; unclear ;; write: yes ;; b: run_action never raises and _attempt raises ConnectionError, which _arrived treats as not arrived, so UNKNOWN cannot come out of the scheduler's action path ;; test: unit: make the force write time out after sending; assert verdict UNKNOWN (fails today) -->

!!! warning "The per-attempt audit rows are never written"
    The retry helper calls its audit hook in a form the scheduler's hook does not accept.
    The error is swallowed, so no per-attempt row reaches the History view; only the
    scheduler's own *fired* / *error* row does. From a code read. Issue #201.
    <!-- @b OUT-35 ;; src: resilience.py:237-241, scheduler.py:1699-1714 ;; unclear ;; write: no ;; b: resilience calls audit(action, detail=, result=, ok=) but _audit(**kw) takes no positional, so the TypeError is swallowed and nothing is logged ;; test: unit: call the sink as resilience does; assert a schedule_log row (fails today) -->

**A window that closes without success is recorded as missed.** On every tick the
scheduler closes runs still pending, running or failed whose window ended more than
2 minutes ago, and logs *missed* — "window closed with N attempt(s) and no success". There
is no catch-up: a missed run is never fired late.
<!-- @b OUT-29 ;; src: scheduler_worker.py:39, scheduler_worker.py:119-145, db.py:2102-2131 ;; tested: tests/test_occurrences.py::test_grace_lets_a_late_run_still_catch_up ;; write: no ;; b: Runs whose window ended more than 120 s ago while pending/running/failed are swept to missed and logged missed (store level; the worker's log row is untested) -->

**Not in this bridge:** failure and recovery notifications for retries (see
[Notifications](#notifications)).

## Supervision of a running command

**Not in this bridge.** After a force is accepted, the bridge does not check that the
setpoint stays enabled, does not check that the battery moves, and never re-sends. The only
watch on a running force is the watchdog's duration and target SoC (see
[Exit and release](exit-and-conflicts.md#how-a-run-ends)). Tracked in
[#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162).

## The dispatch record

**Not in this bridge** as a per-command outcome record. The closest thing is the
`dispatches` table: one row per force the bridge sends successfully, from a schedule, from
**Run now** or from the Battery Control widget. It records the direction, power, target SoC
and window, and a status:

| Status | Meaning |
|---|---|
| `active` | running, as far as the bridge knows |
| `ended` | released by the watchdog, by a window-end or exit Release, or by the widget's Release |
| `superseded` | a newer force was recorded for the same gateway and host |
| `stopped`, `paused` | **Stop** or **Pause** |
| `interrupted`, `released`, `resumed` | handled by the boot reconcile after a restart |

<!-- @b OUT-13 ;; src: db.py:2214-2266 ;; tested: tests/test_dispatch_reconcile.py::test_widget_force_is_persisted_and_release_closes_it ;; write: no ;; b: A widget force writes an active dispatches row with direction, signed power, mode, target SoC and window; the widget Release closes it -->
<!-- @b OUT-26 ;; src: scheduler.py:1582-1597 ;; untested ;; write: no ;; b: A scheduled or Run now force that returns ok writes an active dispatches row (signed watts or percent, window end) ;; test: unit: fire a force entry with a real store, assert one active row with schedule_id and window_end_ts -->

A refused or failed force writes no row.
<!-- @b OUT-15 ;; src: scheduler.py:1582-1583 ;; untested ;; write: no ;; b: record_dispatch runs only when execute returned ok, so a refused force leaves no row ;; test: unit: execute returns ok False; assert no row -->

There is no REST endpoint for this table and no dispatch-outcomes endpoint
(`GET /api/gateways/{gw}/dispatch-outcomes` does not exist here). It is used by
**If busy**, **Stop**, **Pause** and the boot reconcile.

## Overshoot guard

**Not in this bridge.** A force is not released because the battery ran faster than
requested. Tracked in
[#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162).

## Notifications

**Not in this bridge** for scheduled actions. A failed, missed or unknown scheduled action
sends **no** notification: the scheduler passes no notifier to its retry helper
([#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172)). To be
told, add a **Notify** HA action to the schedule; note it runs after the battery action on
every attempt, whatever the outcome (see [Actions](actions.md#home-assistant-actions)).
<!-- @b OUT-18 ;; src: scheduler.py:2409-2413, resilience.py:243-249 ;; unclear ;; write: no ;; b: run_action_outcome is called without a notifier, so failures and unknowns of scheduled actions notify nobody ;; test: unit: a failing force with a notifier in place; assert one 'action failed' notification (fails today, #172) -->

**Direct Connect only.** After a restart that interrupted a scheduled force, the boot
reconcile notifies your enabled notification devices ("FranklinWH — scheduled dispatch
…") under the default policy *notify*. See [Restarts and the clock](restarts-and-clock.md).

## Run now and Stop

![The schedule list; Run now and Stop are also REST calls](../../images/scheduler/18-using-schedules-from-ha.png)

| Control | Shown | What it does |
|---|---|---|
| **⋮ → Run now** | always (asks first) | Runs the battery action and the on-entry HA actions now. `POST /api/schedules/{id}/run` |
| **Stop** | while the card shows **● active** | Releases the force this schedule started. `POST /api/schedules/{id}/stop` |
| **Pause**, **Resume** | API only | See [Pause and Resume](#pause-and-resume-direct-connect-only). |

**● active** (and so **Stop**) shows when the schedule is enabled, its window is open on
the **container's** clock, and it has already fired in this occurrence
([#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161)). An
*Always* schedule never shows it.
<!-- @b OUT-19 ;; src: scheduler.py:509-520, app.py:3033-3038, templates/tabs/scheduler.html:171-173 ;; untested ;; write: no ;; b: Stop is shown when active_now: enabled, inside the window on the container clock and fired this occurrence; never for always ;; test: browser: a fired entry inside its window shows Stop; a gated one does not -->

### Run now

1. Open the card's **⋮** menu and choose **Run now**. Confirm.
2. The bridge runs the action now. It ignores the window, the calendar **and the entry
   conditions**; each HA action's own guard still applies, and only **On entry** and
   **Entry & exit** HA actions run. It logs *manual* with what each step returned.
<!-- @b OUT-20 ;; src: app.py:3424-3455 ;; untested ;; write: yes ;; b: Run now sends the battery action and the fire-phase HA actions (guards honoured) without checking the window or entry conditions, and logs manual ;; test: unit (API): an entry whose conditions fail; POST /run; assert the action is sent and a manual row is written -->
<!-- @b OUT-23 ;; src: app.py:3424-3455 ;; untested ;; write: yes ;; b: Run now ignores the trigger window, the calendar and the fired mark, and works on a disabled entry ;; test: unit (API): disabled entry outside its window; POST /run sends -->

A Run now command differs from a scheduled run:

- A force runs for the schedule's **Duration (min)**; with 0 it has no time limit and runs
  until it is released or reaches its target SoC. A **Recurring windows** schedule has the
  hidden value (90 for a new schedule).
  <!-- @b OUT-21 ;; src: app.py:3441-3448 ;; untested ;; write: yes ;; b: Run now passes duration_min as the force's time limit, 0 meaning none ;; test: unit (API): duration_min 0 and 30; assert duration_s 0 and 1800 -->
- It ignores **If busy**: it replaces a running force.
  <!-- @b OUT-22 ;; src: app.py:3424-3455 ;; untested ;; write: yes ;; b: Run now does not check active dispatches; it supersedes another force ;; test: unit (API): an active _widget row; POST /run; assert the force is sent -->
- It is not retried, has no exit conditions and no exit steps, and does not change the
  card's last result.
- A force it sends is recorded under the schedule's id, so **Stop** can release it, and
  other schedules' **If busy** sees it.
  <!-- @b OUT-27 ;; src: app.py:3441-3448, scheduler.py:1582-1597, app.py:3157 ;; untested ;; write: yes ;; b: A Run now force records a dispatches row with the schedule's id, so Stop and If busy see it ;; test: unit (API): POST /run then POST /stop; assert stopped true -->
- Message placeholders read only the gateway's values and Home Assistant entities: tariff,
  weather and other sensors, and `%run.*%`, print `?`.
  <!-- @b OUT-43 ;; src: app.py:3436-3439 ;; untested ;; write: no ;; b: Run now builds its snapshot from the gateway state and HA entities only, so other placeholders render '?' ;; test: unit (API): notify with %tariff.buy_rate%; assert '?' -->

!!! warning "Run now acts on the gateway selected in the top bar"
    With more than one gateway and one picked in the top bar, the **Run now** menu item sends
    that gateway with the request, and the bridge uses it instead of the schedule's own
    gateway. With *Site* selected, or one gateway, the schedule's gateway is used. From a
    code read; not tested in a browser. Issue #193.
    <!-- @b OUT-28 ;; src: static/js/scheduler_tab.js:616-631, static/js/app.js:880-885, app.py:3435-3436 ;; unclear ;; write: yes ;; b: The UI appends the top-bar gateway to /run and the endpoint prefers it over the entry's gateway_id ;; test: unit (API): entry bound to gw2, POST /run?gateway=gw1, assert it runs on gw2 (fails today) -->

!!! warning "Run now acts for real"
    Run now does exactly what the schedule does: a mode change, a smart circuit, off-grid,
    or a battery force. Use **⋮ → Test against live** first.

### Stop

1. Press **Stop** on the card. Confirm.
2. If the `dispatches` table has an active force recorded for this schedule, the bridge
   sends a Release, marks the rows *stopped* and logs *stopped* — "dispatch released by
   user". The schedule stays enabled.
3. If not, it logs *stopped* — "no active dispatch to stop" and changes nothing.

<!-- @b OUT-24 ;; src: app.py:3147-3167 ;; unclear ;; write: yes ;; b: Stop releases via the default gateway's Modbus host when the schedule has an active dispatches row, ends the rows stopped and logs stopped; no exit HA actions, no restore ;; test: unit (API): active row for the entry on gw2; POST /stop; assert the Release goes to gw2's host (fails today on multi-gateway) -->
<!-- @b OUT-25 ;; src: app.py:3165-3167 ;; untested ;; write: no ;; b: Stop with no active row logs stopped 'no active dispatch to stop' and does not block the rest of the window ;; test: unit (API): gated entry, POST /stop, then conditions pass, assert it fires -->

Stop does not run the exit HA actions, does not restore the mode, and does not stop the
schedule firing again: it fires at its next occurrence. A schedule that had **not** fired
yet in this window (nothing to stop) can still fire later in the same window. To stop a
schedule from firing at all, disable it: **Turn off** on the card.

!!! warning "On a multi-gateway site Stop releases the default gateway"
    Stop sends the Release to `FWH_MODBUS_HOST` or the default gateway's host, not to the
    host recorded for the schedule's force. For a schedule bound to another gateway, Stop
    releases the wrong gateway and leaves its own force running. Pause has the same problem.
    From a code read; not tested. Issue #192.

### Pause and Resume (Direct Connect only)

**Direct Connect only**, API only (`POST /api/schedules/{id}/pause` and `/resume`).

- **Pause** finds this schedule's open run (pending or failed, window still open), releases
  its recorded force if any, marks the run *paused* and logs *paused*.
- **Resume** returns a paused run to pending, but only while its window is open; after
  that it answers 409 "window has closed — resume is only valid inside it".
- A run still paused when the bridge restarts becomes *stopped*.

<!-- @b OUT-37 ;; src: app.py:3205-3229, db.py:2055-2078 ;; tested: tests/test_occurrences.py::test_resume_refuses_once_the_window_has_closed ;; write: no ;; b: Resume re-opens a paused run only while its window is open, else refuses (store level) -->
<!-- @b OUT-38 ;; src: scheduler_worker.py:190-200, db.py:2080-2100 ;; tested: tests/test_occurrences.py::test_a_restart_while_paused_resolves_to_terminal ;; write: no ;; b: At worker start every paused run is resolved to stopped -->

!!! danger "Pause does not hold a run"
    - A run that **succeeded** is not "open", so Pause on a schedule whose force is running
      answers "no run is open for this schedule" and releases nothing.
    - A run that **failed** can be paused, but the scheduler does not check for *paused*: on
      its next attempt it runs the action again and the run becomes *failed* or *ok*.

    Measured with a mock on 2026-10-17. Use **Stop** to release a schedule's force, and
    disable the schedule to keep it from firing. Issue #200.
    <!-- @b OUT-36 ;; src: app.py:3169-3203, db.py:2133-2146, scheduler.py:2147-2156 ;; unclear ;; write: yes ;; b: Pause only finds pending/failed runs (never a succeeded one) and the tick does not skip paused runs, so a paused run is attempted again ;; test: unit: pause a failed run, tick inside the window, assert no attempt (fails today); pause after a successful force, assert it is released (fails today) -->
