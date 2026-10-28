# Scheduler

Direct Connect Bridge. Mirrors the Modbus Bridge page
[Scheduler](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/) section for
section, so the two bridges can be compared page by page.

[Back to the guide index](../index.md)

The Scheduler is the bridge's automation engine. Each **schedule** says *when* its window
opens, *whether* conditions allow it to act, *what* to send, *which gateway* to send it to
and *when to stop*. The bridge checks every schedule every 15 seconds (by default), per
gateway, against the values the poller last read.

You find it on the **Scheduler** tab. It has three views: **Schedules** (the cards),
**Timeline** and **History**.

!!! warning "A force command takes the battery out of its own mode"
    **Force charge / discharge / standby** writes a SunSpec power setpoint through the Modbus
    client (this bridge) to the Modbus TCP Server (aGate :502). That overrides the aGate's
    own mode until the bridge releases it. The aGate does not end a force by itself: the
    bridge's timer and the window's end do (see [Exit and release](exit-and-conflicts.md)).

## Pages in this section

| Page | What it covers |
|---|---|
| [Concepts](concepts.md) | The model (trigger → conditions → action → gateway → exit → outcome), the tick, by time / by event / by sensor. **Start here.** |
| [Triggers](triggers.md) | Every trigger type, calendar restrictions, Next, what happens to a window that is missed. |
| [Conditions](conditions.md) | Operators, Value vs Lookup, groups (ALL/ANY), scope, hold, Test, every sensor. |
| [Actions](actions.md) | Battery actions, mode, reserve, off-grid and circuits, HA-only schedules, Home Assistant actions and notifications. |
| [Targets](targets.md) | Bound and unbound schedules, the default gateway, `gateway_scope` `all`. |
| [Exit and release](exit-and-conflicts.md) | How a window ends, End early when…, release, restore on exit. |
| [Priorities and conflicts](priorities.md) | Which schedule gets a resource, If busy, manual control. |
| [Outcomes and audit](outcomes.md) | History, runs, retries, the dispatch record, Run now, Stop, Pause and Resume. |
| [Restarts and the clock](restarts-and-clock.md) | What a restart does, the site clock, daylight saving. |
| [Dependencies and troubleshooting](dependencies.md) | What each condition and action needs; fixes for "never fires", "always false", "does nothing". |
| [Examples](examples.md) | Worked recipes. |

!!! note "What these pages are based on"
    The scheduler pages describe the code of this release. Many behaviours have no automated
    test yet; the [Scheduler test plan](../../dev/scheduler-test-plan.md) lists each one with
    its test status, the [Scheduler parity](../../dev/scheduler-parity.md) page compares
    each with the Modbus Bridge, and the pages flag the known problems in warning boxes.

## Your first schedule

This walkthrough discharges the battery on weekday evenings, but only if it has charge to
spare, and stops at your minimum discharge SoC.

!!! note "Force commands need the Modbus client (this bridge)"
    **Force charge / discharge / standby** goes through the Modbus client (this bridge) to
    the Modbus TCP Server (aGate :502). If the Modbus client (this bridge) is off, the action
    is listed as *unavailable*, with the reason. To try the Scheduler without it, use the
    **Set operating mode** action instead.

![Add schedule: trigger, battery action, priority, If busy, gateway, entry conditions, hold and exit conditions](../../images/scheduler/12-hold-and-conflicts.png)

!!! tip "Make the form bigger"
    **Default**, **Medium** and **Full** at the top right of the form size it, and its
    bottom-right corner drags to any size in between. The browser remembers the size you
    pick. A notification's message box can be dragged taller and grows as you type.

1. On the **Scheduler** tab, press **Add schedule**.
2. **Name:** `Evening discharge`.
3. **Trigger type:** **Weekly at time**. Under **Days**, tick **Mon** to **Fri** (none
   ticked means every day). Set **Fire at** to `17:00` and **Duration (min)** to `180`.
4. **Battery action:** **Force charge / discharge / standby**. Set **Direction** to
   **Force discharge**, **Power unit** to **% of inverter power**, and **Power** to `50`.
   Leave **Target SoC** empty.
5. Leave **Priority** at `0`, **If busy** at `override` and the gateway at
   **Default gateway** (the picker appears only with more than one gateway).
6. **Entry conditions (must hold to fire):** press **+ row**. Pick **Battery SoC (%)**,
   operator `>`, value `40`.
7. **End early when…:** press **+ row**. Pick **Battery SoC (%)**, operator `<=`, press
   **Lookup**, and pick **Const: min discharge SoC (%)**. Set that constant first under
   **Settings → Automation → Automation Constants**.
8. Press **Test** under each block. Each row is marked *pass*, *fail* or *no value* against
   the live data.
9. Untick **Enabled** while you try it, and press **Create Entry**. Tick it and **Save
   Changes** when you are happy.

What happens once it is enabled:

- At 17:00 on a weekday the bridge checks the SoC. Above 40 %, it starts the force
  discharge, with the window's 180 minutes as its time limit. Otherwise it logs *gated*
  (once a day) and checks again every tick until 20:00, so it can still start later.
- When the SoC falls to your minimum discharge SoC, the exit condition closes the window
  and the force is released. The schedule does not fire again until tomorrow's window.
- At 20:00 the window closes and the bridge sends a release.

!!! warning "For a force action, use a trigger with Fire at and Duration"
    A force stops after the schedule's **Duration (min)** (#160). A **Recurring windows**
    schedule still has that value, although the form hides it, and a new schedule starts
    with 90. So a force in a three-hour recurring window stops after 90 minutes. Use **Daily
    at time** or **Weekly at time** for force actions.

To check it before the window opens, open the card's **⋮** menu and choose **Test against
live**. It says *Would fire* or *Would not fire*, with the reason and each row's live value.

## The entry list

![The Schedules view: a schedule card with Explain, Edit, Turn on and the ⋮ menu](../../images/scheduler/18-using-schedules-from-ha.png)

Each schedule is a card. It shows the name; the Fire at time and duration, the recurrence
in words and the number of top-level conditions; **Next:** (see
[Triggers → Next fire](triggers.md#next-fire)); **● active** while its window is open and it
has fired; **On** or **Off**; the battery action (or *No gateway action*) and the number of
HA actions; and the last result with its occurrence.

| Control | What it does |
|---|---|
| **N active now** | Counts the cards showing **● active**. |
| **All / Enabled / Disabled** | Filters the cards. A note says how many are hidden. |
| **Explain** | A plain-language summary of the schedule, at three levels: **min**, **medium** and **full**. A Home Assistant action that runs on exit reads "… when it ends". The browser remembers the level you last chose. |
| **Edit** | Opens the form. If the schedule is **● active**, saving asks first. |
| **Turn on** / **Turn off** | Enables or disables the schedule. |
| **Stop** | Shown while **● active**. Releases the force this schedule started; the schedule stays enabled. See [Run now and Stop](outcomes.md#run-now-and-stop). |
| **⋮ → Test against live** | Evaluates the schedule against live values, without acting. |
| **⋮ → Run now** | Runs the actions now, ignoring the window and the entry conditions. Asks first. |
| **⋮ → Duplicate** | Opens a copy in the form, named "Copy of …", with **Enabled** unticked. It is saved as a new schedule. |
| **⋮ → Delete** | Removes the schedule, after asking. |

The list shows **all** schedules by default.
<!-- @b IDX-01 ;; src: static/js/scheduler_tab.js:20, static/js/scheduler_tab.js:500-507 ;; untested ;; write: no ;; b: The list shows all schedules by default; All/Enabled/Disabled filter it and a note counts the hidden ones ;; test: browser: load the tab with one disabled schedule; assert it is shown -->

**Duplicate** opens an unsaved copy named "Copy of <name>" with **Enabled** unticked; nothing
is written until you press **Create Entry**.
<!-- @b IDX-02 ;; src: static/js/scheduler_tab.js:309-315 ;; untested ;; write: no ;; b: Duplicate opens an unsaved form copy named 'Copy of …' with enabled false and no id ;; test: browser: duplicate, cancel; assert no new schedule -->

Saving a schedule that is **● active** asks "This schedule is running now — saving will apply
the changes to the window in progress." The change is read by the next tick. A force that is
already running is not re-sent: the schedule has fired this occurrence, so a changed power,
direction or target SoC takes effect at the next window.
<!-- @b IDX-03 ;; src: static/js/scheduler_tab.js:545-553, scheduler.py:538-541 ;; untested ;; write: yes ;; b: Saving an active schedule asks to confirm; the running force is not re-sent because the occurrence is already fired ;; test: unit: change power on a fired, open-window entry; assert no second Force this occurrence -->

**Turn on / Turn off** sends only part of the schedule; since 0.5.2 the bridge merges it into
the stored schedule, so nothing else changes (#157).
<!-- @b IDX-08 ;; src: static/js/scheduler_tab.js:578-592, app.py:3105-3134 ;; tested: tests/test_schedule_update_merge.py::test_the_toggle_body_changes_only_enabled ;; write: yes ;; b: The toggle's partial PUT changes only enabled; every other stored field is kept ;; test: -->

!!! warning "A PUT without `enabled` turns the schedule on"
    The form and the toggle always send `enabled`. An API call that does not, for example one
    that only renames a disabled schedule, turns it back **on**: `enabled` defaults to true
    in the request model. Issue #168.
<!-- @b IDX-09 ;; src: app.py:631, app.py:3124-3132 ;; unclear ;; write: yes ;; b: PUT without enabled re-enables a disabled schedule (request default True) ;; test: unit (API): PUT {name} on a disabled schedule; assert still disabled (fails today) -->

### Templates, export and import

![The built-in Templates](../../images/scheduler/17-working-with-schedules.png)

- **Templates** opens a list of presets. **Use** loads one into the form **unticked**, for
  review; nothing is saved until you press **Create Entry**. There is no prompt to enable it
  afterwards. Presets marked **Modbus** use a force action and need the Modbus client (this
  bridge).
  <!-- @b IDX-04 ;; src: static/js/scheduler_tab.js:157-179, templates/tabs/scheduler.html:312-342 ;; untested ;; write: yes ;; b: A template loads into the form with enabled false and is not saved until Create Entry ;; test: browser: Use a template, cancel; assert nothing created -->
- The presets: Self-Consumption all day, Time-of-Use in the evening, Emergency Backup
  (storm), Turn a circuit off overnight, Low battery alert (notify only), Peak window —
  notify start & end, Time-of-Use at peak (only if charged), and four force presets: Peak
  shaving, Battery Bonus export (evening), Solar sponge (charge midday) and Off-peak charge
  (overnight), each with an SoC condition and a target SoC.
  <!-- @b IDX-10 ;; src: scheduler.py:554-623 ;; tested: tests/test_scheduler.py::test_dispatch_presets_present_and_valid ;; write: yes ;; b: Eleven presets; the four force presets need Modbus, carry an SoC gate and a target SoC, and validate as imports ;; test: -->
- **Export ▾** downloads every schedule, as **This bridge** (`franklinwh-local-schedules`)
  or **Modbus bridge** (`franklinwh-automations`). Through the API,
  `GET /api/schedules/export?ids=<id>,<id>` exports some.
- **Import** takes a file. The bridge first validates it (a dry run) and shows, per entry,
  errors (a missing name, a Fire at that is not `HH:MM`, an unknown action) and warnings (a
  gateway or notify device that does not exist here). **Import valid** creates the valid
  entries **disabled**. An entry whose gateway does not exist here is pointed at the default
  gateway. Both bundle types are read; a Modbus bridge bundle is mapped field by field.
  <!-- @b IDX-05 ;; src: app.py:3251-3310, scheduler.py:631-861 ;; tested: tests/test_scheduler.py::test_import_maps_modbus_automations_bundle ;; write: no ;; b: Import is a dry run unless dry_run=false, creates valid entries disabled and maps a franklinwh-automations bundle field by field ;; test: -->

**Not in this bridge:** a per-entry **Export** in the card menu.

## Visual timeline

The **Timeline** view shows today, 00:00 to 24:00:

- a band along the top coloured by the operating mode the gateway actually ran;
- the battery SoC as a line;
- dashed markers where a schedule *fired*, *exit*ed, was *gated* or had an *error*;
- a line at the current time.

Below it, **Planned windows** lists each enabled schedule's windows for today as a bar
(*(+1d)* when a window wraps past midnight). Every N minutes, Custom cron and Always
schedules are not drawn, nor are schedules the calendar excludes today.
<!-- @b IDX-06 ;; src: scheduler.py:864-885, app.py:3328-3358 ;; tested: tests/test_scheduler.py::test_disabled_schedule_absent_from_timeline ;; write: no ;; b: Planned windows: enabled entries only, today's calendar only; interval, cron and always are not drawn ;; test: -->

A One-off schedule appears only on its date.
<!-- @b IDX-07 ;; src: scheduler.py:874-875 ;; untested ;; write: no ;; b: A one-off is drawn only when today is its date (calendar check) ;; test: unit: timeline_segments for a once entry on another date is empty -->

!!! warning "The Timeline is not per gateway, and uses the container's clock"
    The planned windows list every enabled schedule whatever its gateway, the markers come
    from every gateway's History, and "today" and "now" are the bridge container's clock, not
    the site's (#161).
<!-- @b IDX-11 ;; src: app.py:3328-3358 ;; untested ;; write: no ;; b: The timeline ignores the gateway for segments and markers and uses the container clock ;; test: unit (API): two gateways' schedules; ?gateway=gw2 still returns both -->

## Activity Log

Every decision the scheduler makes is written to **History**, newest first: created,
*fired*, *gated*, *waiting*, *deferred*, *exit*, *error*, *missed* and more. The status list
and filter chips are on [Outcomes and audit](outcomes.md#activity-log-results). Times are in
the bridge host's zone.

The **Monitor** card above it shows, tick by tick, why each schedule is or is not
running ([Monitor](outcomes.md#monitor)).

## Using schedules from Home Assistant (Direct Connect only)

Everything the Scheduler tab does is also a REST call. Home Assistant can make those calls
with `rest_command`, so automations and scripts can read, create, update, delete and run
schedules. Home Assistant entities for run, pause and state over MQTT are planned (#128).

**The address.** From Home Assistant, the add-on is reachable on its internal hostname. The
add-on's **Info** page shows it (for example `4a12892f-franklinwh-local-bridge`). Use
`http://<that hostname>:8101`. A Docker install uses its own host and port.

> The bridge's HTTP API has no login, and writes are not gated (`writes_enabled` always
> returns true). Anything that can reach it can do all of the below. Keep it on a trusted
> network.

```yaml
# configuration.yaml
rest_command:
  fwh_schedule_create:          # body: a full schedule (see "The fields" below)
    url: "http://<hostname>:8101/api/schedules"
    method: POST
    content_type: "application/json"
    payload: "{{ schedule | tojson }}"
  fwh_schedule_update:          # merges what you send (#157); always send name and enabled (#168)
    url: "http://<hostname>:8101/api/schedules/{{ id }}"
    method: PUT
    content_type: "application/json"
    payload: "{{ schedule | tojson }}"
  fwh_schedule_delete:
    url: "http://<hostname>:8101/api/schedules/{{ id }}"
    method: DELETE
  fwh_schedule_run:             # runs its actions NOW, ignoring the window and conditions
    url: "http://<hostname>:8101/api/schedules/{{ id }}/run"
    method: POST
  fwh_schedule_stop:            # releases this schedule's battery dispatch; stays enabled
    url: "http://<hostname>:8101/api/schedules/{{ id }}/stop"
    method: POST
```

**Update merges.** `PUT` changes only the fields you send (since 0.5.2, #157), but always
send `name` (required) and `enabled`: without `enabled` the schedule is switched **on**
(#168).

**Reading.** A `rest` sensor on `GET /api/schedules` lists every schedule with `enabled`,
`next_fire` and `active_now` (container clock, #161). `GET /api/schedules/runs` and
`GET /api/schedules/log` give what ran and why.

**Pause vs disable: they are different.**

| You want | Call |
|---|---|
| Release a **battery dispatch** this schedule started, and leave the rule enabled | `stop` |
| Stop the rule from **firing at all** until further notice | `PUT` with `"name"` and `"enabled": false` |
| Hold the current run and resume it later | `pause` / `resume` exist, but **do not work as intended**; see the warning |

!!! warning "Pause and Resume do not hold a run"
    `POST /api/schedules/{id}/pause` only finds a run that has **not yet succeeded** (pending
    or failed). For a force that is running it answers "no run is open for this schedule"
    and does nothing. For a failed run it marks it *paused*, but the next tick retries it
    anyway: the tick does not check for *paused*. Use `stop` or disable the schedule. Issue
    #200; see [Outcomes and audit](outcomes.md#run-now-and-stop).
<!-- @b IDX-12 ;; src: app.py:3169-3204, db.py:2133-2146, scheduler.py:2147-2156 ;; unclear ;; write: yes ;; b: Pause finds only pending/failed runs, and the tick does not skip a paused run, so pause neither holds a running force nor stops retries ;; test: unit: pause a failed run, tick inside the window; assert no attempt (fails today) -->

**Run means real actions.** `run` does what the schedule does: a mode change, a smart
circuit, off-grid, or a battery force. Test a new rule with `POST /api/schedules/{id}/test`
first: it evaluates the conditions and says what *would* happen, without acting.

**The fields** are those of the Scheduler tab's form. A minimal rule that switches to
Self-Consumption at midnight:

```json
{"name": "Self-Consumption all day", "enabled": true,
 "fire_at": "00:00", "duration_min": 0,
 "action": {"kind": "set_mode", "mode": "self"}}
```

For anything more involved, build it in the Scheduler tab and **export** it
(`GET /api/schedules/export`): each entry is the exact JSON the API accepts.

## Where the old sections went

The Scheduler used to be two pages. Their sections now live here:

| Old section | New place |
|---|---|
| <span id="concepts"></span>Concepts | [Concepts](concepts.md) |
| <span id="how-a-schedule-is-evaluated"></span>How a schedule is evaluated | [Concepts → The tick](concepts.md#the-tick) |
| Your first schedule | [above](#your-first-schedule) |
| <span id="the-schedule-list"></span>The schedule list | [The entry list](#the-entry-list) |
| <span id="timeline"></span>Timeline | [Visual timeline](#visual-timeline) |
| <span id="history"></span>History | [Outcomes → Activity Log results](outcomes.md#activity-log-results) |
| <span id="1-trigger-when-the-window-opens"></span>1. Trigger | [Triggers](triggers.md) |
| <span id="calendar-restrictions"></span>Calendar restrictions | [Triggers → Summary](triggers.md#summary) |
| <span id="how-fast-can-a-schedule-react"></span>How fast can a schedule react | [Concepts → The tick](concepts.md#the-tick) |
| <span id="which-clock"></span>Which clock | [Restarts and the clock → The clock](restarts-and-clock.md#the-clock) |
| <span id="2-conditions-the-gate"></span>2. Conditions | [Conditions](conditions.md) |
| <span id="operators"></span>Operators | [Conditions → Operators](conditions.md#operators) |
| <span id="value-or-lookup"></span>Value or Lookup | [Conditions → Value and Lookup](conditions.md#value-and-lookup) |
| <span id="all-any-and-nesting"></span>ALL / ANY, and nesting | [Conditions → Groups and items](conditions.md#groups-and-items-all-any) |
| <span id="the-rule-that-matters-most"></span>The rule that matters most | [Conditions → Rules for every condition](conditions.md#rules-for-every-condition) |
| <span id="what-you-can-gate-on"></span>What you can gate on | [Conditions → Every sensor in the picker](conditions.md#every-sensor-in-the-picker) |
| <span id="gating-on-home-assistant"></span>Gating on Home Assistant | [Conditions → Home Assistant entities](conditions.md#home-assistant-entities) |
| <span id="3-hold-and-conflict-resolution"></span>3. Hold, and conflict resolution | [Conditions → Hold for](conditions.md#hold-for-dwell), [Priorities and conflicts](priorities.md) |
| <span id="4-actions-what-the-rule-does"></span>4. Actions | [Actions](actions.md) |
| <span id="the-force-action-in-detail"></span>The force action in detail | [Actions → Force Charge and Force Discharge](actions.md#battery-actions-force-charge-and-force-discharge) |
| <span id="home-assistant-actions"></span>Home Assistant actions | [Actions → Home Assistant actions](actions.md#home-assistant-actions) |
| <span id="5-exit-ending-the-window"></span>5. Exit | [Exit and release](exit-and-conflicts.md) |
| <span id="6-working-with-schedules"></span>6. Working with schedules | [Templates, export and import](#templates-export-and-import), [Conditions → Test Verification](conditions.md#test-verification) |
| <span id="run-now-stop-pause-and-resume"></span>Run now, Stop, Pause and Resume | [Outcomes → Run now and Stop](outcomes.md#run-now-and-stop) |
| <span id="when-a-run-fails-is-missed-or-the-bridge-restarts"></span>When a run fails, is missed, or the bridge restarts | [Outcomes → Retries](outcomes.md#retries), [Restarts and the clock](restarts-and-clock.md) |
| <span id="not-available-in-this-bridge"></span>Not available in this bridge | the **Not in this bridge** notes on each page, and [Scheduler parity](../../dev/scheduler-parity.md) |
| <span id="7-using-schedules-from-home-assistant"></span>7. Using schedules from Home Assistant | [above](#using-schedules-from-home-assistant-direct-connect-only) |
| <span id="multi-gateway-behaviour"></span>Multi-gateway behaviour | [Targets](targets.md) |
