# Use case: integrating with the Scheduler

[Developers Guide](index.md) · User guide: [Scheduler](../guide/scheduler/index.md)

This page follows one integration from end to end. A Home Assistant electricity price
sensor decides whether the battery charges overnight. The schedule is created over the
REST API, the bridge evaluates it on its own clock, and the result comes back to Home
Assistant as a notification, an `input_boolean`, and the battery's own MQTT entities.

Read from the code on `main` (0.5.2). Paths are relative to
`src/franklinwh_direct_connect_bridge/`. The request body below was checked against that
code: it was posted to a local copy of the app (FastAPI `TestClient`, empty database,
no gateway), returned **201**, and its conditions were evaluated with
`scheduler.evaluate()`. It was **not** run against a gateway, so the force itself was
not exercised.

!!! warning "This schedule moves your battery"
    A `force` action charges the battery from the grid for up to five hours. It needs
    the Modbus client (this bridge) switched on, and it writes to the Modbus TCP Server
    (aGate :502). Read [Control and write safety](../guide/control.md) and
    [Battery dispatch: best practices](../guide/battery-dispatch.md) first. Creating it
    over the API asks for no confirmation.

---

## 1. Make the Home Assistant entity visible to the Scheduler

You need a Home Assistant instance linked to the bridge. As an add-on this is automatic.
See [Home Assistant setup and notifications](../guide/ha-setup-and-notifications.md).
Find the instance id:

```bash
curl -s http://<bridge-host>:8101/api/ha/instances
```

Then expose the price entity. Only exposed entities are read
([Reading Home Assistant](reading-home-assistant.md#entity-values-for-the-scheduler)):

```bash
curl -s -X POST http://<bridge-host>:8101/api/ha/entities/expose \
  -H 'Content-Type: application/json' \
  -d '{"instance_id": "<instance_id>", "entity_id": "sensor.electricity_price", "exposed": true}'
```

The entity is now the Scheduler sensor `ha:<instance_id>:sensor.electricity_price`
(`scheduler.ha_sensor_id()`). `GET /api/schedules` lists it under `sensors`. Use your own
price entity's id, and the price units it reports; the bridge compares the number as it
is.

---

## 2. Create the schedule

The rule: every night from 01:00 for five hours, if the price is under 10 and the
battery is under 80 %, force-charge at the full rated rate to 90 %. End early if the
price rises above 20. Tell me when it starts and ends, and turn an `input_boolean` on
for the duration.

```bash
curl -s -X POST http://<bridge-host>:8101/api/schedules \
  -H 'Content-Type: application/json' \
  -d @cheap-charge.json
```

`cheap-charge.json`:

```json
{
  "name": "Cheap overnight charge",
  "enabled": true,
  "trigger_type": "daily",
  "fire_at": "01:00",
  "duration_min": 300,
  "match": "all",
  "conditions": [
    {"sensor": "ha:<instance_id>:sensor.electricity_price", "op": "<", "value": 10},
    {"sensor": "battery.soc_pct", "op": "<", "value": 80}
  ],
  "exit_conditions": [
    {"sensor": "ha:<instance_id>:sensor.electricity_price", "op": ">", "value": 20}
  ],
  "exit_match": "all",
  "action": {"kind": "force", "direction": "charge", "unit": "pct", "power": 100, "target_soc": 90},
  "ha_actions": [
    {"ha_kind": "notify", "device_id": "<notify_device_id>", "when": "both",
     "title": "Battery: %schedule.name%",
     "message": "%run.phase% at %run.at%: SoC %battery.soc_pct%%"},
    {"ha_kind": "service", "when": "fire", "instance_id": "<instance_id>",
     "domain": "input_boolean", "service": "turn_on",
     "entity_id": "input_boolean.battery_cheap_charge", "data": {}},
    {"ha_kind": "service", "when": "exit", "instance_id": "<instance_id>",
     "domain": "input_boolean", "service": "turn_off",
     "entity_id": "input_boolean.battery_cheap_charge", "data": {}}
  ]
}
```

The response is **201** with the stored row, including its `id`.

### The fields

The request model is `ScheduleReq` in `app.py`. Only `name` is required. The shapes
inside `conditions`, `action` and `ha_actions` are free-form in the model and are
interpreted by `scheduler.py`:

| Field | Here | Meaning, and where it is read |
|---|---|---|
| `trigger_type` | `daily` | One of `window`, `once`, `daily`, `weekly`, `interval`, `monthly`, `cron`, `always` (`TRIGGER_TYPES`). |
| `fire_at`, `duration_min` | `01:00`, `300` | The window is 01:00 to 06:00, in **site** time. For a force, `duration_min` is also the watchdog's time limit (below). |
| `conditions`, `match` | two leaves, `all` | Each leaf is `{sensor, op, value}`. Operators are in `OPERATORS`. Groups nest as `{match, conditions}`. |
| `exit_conditions`, `exit_match` | one leaf | Checked while the window is open; when true, the window closes early. |
| `action` | `force` | `kind` is one of `set_mode`, `smart_circuit`, `offgrid`, `reserve_soc`, `notify`, `force` (`ACTIONS`). For `force`: `direction` (`charge`, `discharge`, `standby`), `unit` (`pct`, `w` or `kw`), `power`, `target_soc`. |
| `ha_actions` | three | `ha_kind` `notify` or `service`; `when` `fire`, `exit` or `both`; optional `guard`. |
| `days`, `months`, `start_date`, `end_date`, `day_of_month` | omitted | Calendar restrictions. Empty means no restriction (`_calendar_ok()`). |
| `priority`, `conflict` | omitted | Which rule wins a contested gateway. |
| `gateway_id`, `gateway_scope` | omitted | Empty runs on the default gateway only; `gateway_scope: "all"` runs on each gateway. |

Why `daily` and not a recurring window (`window`): see
[the pitfalls](#known-issues-and-pitfalls).

### Check it before it runs

`POST /api/schedules/evaluate` evaluates a condition tree against the live values,
without saving anything, and returns the result for each leaf:

```bash
curl -s -X POST http://<bridge-host>:8101/api/schedules/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"conditions": [{"sensor": "ha:<instance_id>:sensor.electricity_price", "op": "<", "value": 10}], "match": "all"}'
```

`POST /api/schedules/{id}/test` evaluates a saved schedule without firing anything. It
returns `would_fire`, the reason, the window state, each condition's live value and
result, and the whole snapshot (`api_schedule_test()`). It works out the window with the
container's clock, like the timeline (#161 below).

`POST /api/schedules/{id}/run` runs its actions **now**, ignoring the window
(`api_schedule_run()`). With this schedule that means a real force charge.

### Updating it

`PUT /api/schedules/{id}` **merges** what you send into the stored schedule (#157). Send
`name` every time, because it is required, and send `enabled` every time, because it is
not merged:

```bash
curl -s -X PUT http://<bridge-host>:8101/api/schedules/<id> \
  -H 'Content-Type: application/json' \
  -d '{"name": "Cheap overnight charge", "enabled": false}'
```

That disables the schedule and keeps everything else. A `PUT` **without** `enabled`
re-enables it: `ScheduleReq` defaults `enabled` to `true`, and
`api_schedule_update()` uses `req.enabled` as it is. This was checked on the local copy:
after `{"name": ..., "enabled": false}`, a `PUT` of `{"name": ...}` returned
`enabled: true`.

---

## 3. What happens on each tick

The Scheduler runs as its own worker (`scheduler_worker.py`), every `scheduler_tick_s`
seconds: 15 by default, clamped to 5–60. Each tick, for each gateway:

1. **Freshness.** `eligible()` skips a gateway whose last poll is older than
   `max(90 s, 3 × poll_interval)`, with the reason "snapshot is Ns old". Nothing is
   evaluated on stale data.
2. **Snapshot.** `scheduler.tick()` builds one dictionary of every sensor: the
   gateway's last poll (`battery.soc_pct` and the rest), then a fresh
   `GET /api/states` from Home Assistant for the exposed entities, then weather, prices,
   tariff, constants and derived battery values.
3. **The window.** `window_now()` works out, in site time, whether 01:00–06:00 is open
   today. `_calendar_ok()` applies any calendar restrictions.
4. **Exit check.** While the window is open, the exit conditions are evaluated. If the
   price is above 20, the window counts as closed from this tick.
5. **Entry.** `due()` fires the schedule if the window is open, it has not fired for
   this occurrence yet, and the conditions are true. If the price is 12 at 01:00 and 8
   at 03:10, it fires at 03:10, on the first tick where the conditions hold.
6. **Fire.** `_fire_entry()` runs the action, then the `fire` and `both` Home Assistant
   actions:
    - the force goes through `battery_control.execute()`, with a watchdog of
      `duration_min × 60` seconds from now and the target SoC. The watchdog checks
      every 5 seconds and releases when the time is up or the battery reaches 90 %;
    - the notification is sent and `input_boolean.battery_cheap_charge` is turned on.
7. **Exit edge.** On the first tick after the window closes, at 06:00 or when the price
   passes 20, the `exit` and `both` Home Assistant actions run, and the force is
   **released** as a safety net, even if the watchdog has already ended it.

Two consequences:

- A force that fires late in the window still stops at the window's end, because of the
  exit-edge release in step 7. That release needs the bridge to be running at 06:00.
  If it is not, the watchdog's 300 minutes from the fire time apply, and the
  restart policy (`dispatch_interrupt_policy`) decides what happens on boot.
- Conditions gate the **start** only. Once the force is running, the price and SoC
  conditions are not checked again. Use `exit_conditions` and `target_soc` to end it.

What happened is recorded. `GET /api/schedules/runs?sid=<id>` and
`GET /api/schedules/log?schedule_id=<id>` return each run's outcome text, such as
`force charge: ...`, `notify 'Phone': sent` and `service input_boolean.turn_on: ok`.

---

## 4. How the result comes back to Home Assistant

There is no MQTT entity for the schedule itself yet (#128, below). The result reaches
Home Assistant in three ways:

| Path | What you see | Source |
|---|---|---|
| The schedule's `ha_actions` | The notification on your phone; `input_boolean.battery_cheap_charge` on for the window. | `run_action()`, `ha_instances.call_service()` and `send_notification()` |
| The gateway's MQTT state | **Battery Power** goes negative, **Battery State** reads `charging`, and **State of Charge** rises, on the next poll. | `state_payload()` in `publish/entities.py` |
| The bridge's REST API | A `rest` sensor on `GET /api/schedules` gives `enabled`, `next_fire` and `active_now` for each schedule. | `api_schedules()` in `app.py` |

The `input_boolean` is the cleanest signal for your own automations, because it says
"the schedule fired", not just "the battery is charging". Create it in Home Assistant
first; the service call fails with "service/domain not found" otherwise.

---

## Calling a Home Assistant service as an action

Any Home Assistant service can be an action, with `ha_kind: "service"`. `run_action()` in
`scheduler.py`, kind `ha_service`:

- needs `instance_id`, `domain` and `service`;
- takes `entity_id`, which it adds to `data` unless `data` already has one;
- takes `data` as an object, or as a JSON string;
- replaces `%sensor.id%` placeholders in `entity_id` and in each string value of `data`;
- posts to `/api/services/<domain>/<service>` (`ha_instances.call_service()`).

A schedule can be Home Assistant-only. Leave the battery action empty (`"action":
{"kind": ""}`) and only the `ha_actions` run. Schedules with no battery action never
compete for the gateway (User Guide, [Priorities and conflicts](../guide/scheduler/priorities.md)).

For example, start the pool pump at the solar peak, but only when the battery is nearly
full:

```json
{
  "name": "Pool pump on solar",
  "trigger_type": "daily",
  "fire_at": "11:00",
  "duration_min": 180,
  "conditions": [{"sensor": "battery.soc_pct", "op": ">=", "value": 90}],
  "action": {"kind": ""},
  "ha_actions": [
    {"ha_kind": "service", "when": "fire", "instance_id": "<instance_id>",
     "domain": "switch", "service": "turn_on", "entity_id": "switch.pool_pump", "data": {}},
    {"ha_kind": "service", "when": "exit", "instance_id": "<instance_id>",
     "domain": "switch", "service": "turn_off", "entity_id": "switch.pool_pump", "data": {}}
  ]
}
```

### Message placeholders

`substitute()` in `scheduler.py` replaces `%name%` with the live value, or `?` when
there is none. The name may contain only letters, digits, `_` and `.`: the pattern is
`%([a-zA-Z0-9_.]+)%`. So these work:

- gateway sensors, such as `%battery.soc_pct%` and `%grid.power_w%`;
- the run's own values from `run_context()`: `%schedule.name%`, `%schedule.id%`,
  `%schedule.action%`, `%gateway.id%`, `%run.phase%` (`fire` or `exit`),
  `%run.at%`, `%run.attempt%`.

**A Home Assistant sensor cannot be put in a message.** Its id, `ha:<instance>:<entity>`,
contains colons, which the pattern does not match, so the placeholder is left in the
text as written. Checked on the local copy. Write `%%` for a literal `%`.

---

## Known issues and pitfalls

Checked with `gh issue view` on 2026-10-17. All four are open.

- **#160: a force in a Recurring-windows schedule stops early.** For
  `trigger_type: "window"` the editor hides **Duration**, but `_force_dispatch()` still
  sets the watchdog from `duration_min`, which a new schedule gets as 90 from the form's
  defaults (`blank()` in `scheduler_tab.js`). The window's real end is passed as
  `window_end_ts`, which is used for the restart record and the retry deadline but does
  not set the watchdog. So a three-hour recurring window releases after 90 minutes.
  **Use `daily` or `weekly` with `fire_at` and `duration_min`**, as above, where the
  duration is the window.
- **#161: the timeline uses the container's clock.** `api_schedules()` computes
  `next_fire` and `active_now` with `datetime.now()`, the container's local time, and
  `/api/schedules/timeline` and `/api/schedules/{id}/test` do the same, while `tick()` uses the site's time
  (`site_time.now_site()`). If the container's time zone differs from the site's,
  `next_fire` and the Timeline are off by the difference. The schedule itself fires at
  the right site time.
- **#129: `reserve_soc` is always skipped.** `run_action()` returns "reserve_soc skipped:
  no local write path exists ... needs a cloud provider" without checking for one, even
  with cloud credentials configured. Do not build on a `reserve_soc` action yet.
- **#128: the Scheduler in Home Assistant.** The REST half (create, update, delete, run,
  test, stop, pause, resume) exists, and the user guide has `rest_command` examples
  ([Using schedules from Home Assistant](../guide/scheduler/index.md#using-schedules-from-home-assistant-direct-connect-only)).
  The MQTT half, with a switch, buttons and sensors per schedule, is planned and not
  built.

Also worth knowing:

- **An unavailable price has no value.** From 0.5.4, `_coerce()` returns no reading for
  `unavailable` and `unknown`, and `ha_snapshot()` leaves the entity out, so every condition
  on it is false. Before 0.5.4 they read as `0`, which made `price < 10` true while the price
  sensor was down (#167, fixed in 0.5.4).
- **Home Assistant unreachable means no fire.** If the `GET /api/states` fails, the
  Home Assistant sensors are missing for that tick, and a missing sensor is false.
- **The tick is 15 seconds, the data is a poll old.** Gateway values are as fresh as the
  last poll (30 s by default). Home Assistant values are read on each tick.
