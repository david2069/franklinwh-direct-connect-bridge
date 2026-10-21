# Home Assistant setup and notifications

[Back to the guide index](index.md) · [Home Assistant and MQTT](home-assistant.md)

This page covers the bridge's link **into** Home Assistant: how to connect it, how to
check the connection, how to add your phone as a notification device, and what the
bridge will notify you about. Publishing the aGate's entities **to** Home Assistant over
MQTT is a separate thing, covered in [Home Assistant and MQTT](home-assistant.md).

Everything here was read from the bridge's code on `main` (release 0.5.2) on
2026-10-17. It was not exercised against a running Home Assistant for this page. File
and function names are given so you can check them.

---

## 1. Link the bridge to Home Assistant

The bridge keeps a list of **Home Assistant instances**. Each one is a base URL and a
token. The bridge uses an instance to read entity states for the Scheduler, to find
notification services, to send notifications, and to call services from schedules. It
talks to Home Assistant's REST API; see
[Reading Home Assistant](../developers/reading-home-assistant.md) for the details.

### As a Home Assistant add-on: automatic

The add-on asks Home Assistant for API access (`homeassistant_api: true` in
`config.yaml`). When it starts with an empty instance list, it adds one for you
(`_seed_self_ha_instance()` in `app.py`):

- named **Home Assistant (this add-on)**;
- at `http://supervisor/core`, the Supervisor's proxy to Home Assistant;
- with the token the Supervisor gives the add-on;
- marked as the default.

You do not need a long-lived token. After an add-on update the Supervisor issues a new
token, and the bridge copies it into that instance on start-up (fixed in #99). It never
changes instances you added yourself.

### Docker or standalone: URL and token

1. In Home Assistant, open your profile, then **Security → Long-lived access tokens →
   Create token**. Copy it.
2. In the bridge, open the **Home Assistant** tab → **Instances** → **Add instance**.
3. Fill in **Name**, **Base URL** (for example `http://192.0.2.20:8123`) and
   **Long-lived token**. Tick **Default** if this is your main Home Assistant, and leave
   **Enabled** on.
4. Press **Test**. It calls Home Assistant's `/api/` with the token, and reports "token
   rejected" for a 401 or 403 (`ha_instances.probe()`).
5. Press **Save**.

The same list is also under **Settings → Integrations → HA Instances → + Add instance**.

The token is **write-only**. The bridge never sends it back to the browser: the list
shows **Token set** or **No token — reads will fail**, and an edit form shows the token
field as unchanged. It is stored in the bridge's database in plain text.

From the API: `POST /api/ha/instances`, `PATCH /api/ha/instances/{id}`,
`DELETE /api/ha/instances/{id}`, and `POST /api/ha/test`.

---

## 2. Check the connection: the four setup checks

`GET /api/setup/ha-checks` (`api_setup_ha_checks()` in `app.py`) measures the four
things that decide whether the bridge works with Home Assistant. They fail
independently, and each has a different fix. Each check is **pass**, **fail**, or
**could not be determined**. The last is not shown as a failure.

| Check | Title shown | What it tests | Fix when it fails |
|---|---|---|---|
| `mqtt_broker` | MQTT broker connected | Publishing is on, and at least one gateway that publishes is connected to the broker. With publishing on but no publishing gateway yet, the result is "No gateway publishing yet", undetermined. | Turn publishing on from the **MQTT** tab, or install the Mosquitto broker add-on. |
| `ha_linked` | Home Assistant connected to the bridge | The **first enabled** instance answers `/api/` with its token. Shows "This Home Assistant" for the add-on's own instance. | "Add one under Home Assistant → Instances." |
| `ha_mqtt` | Home Assistant's MQTT integration set up | `mqtt` is among Home Assistant's loaded components (`/api/config`). | In Home Assistant: **Settings → Devices & services → Add integration → MQTT**. |
| `entities` | Bridge entities in Home Assistant | How many of this bridge's entities Home Assistant has, matched by device identity, plus any left over from removed gateways. | Remove leftover devices in Home Assistant. |

The checks appear in the **setup wizard**, at the **Home Assistant** step. That step
also asks "Publish this gateway's entities to Home Assistant?", and has a **Check again**
button (`templates/partials/setup_wizard.html`, `loadHaChecks()` in
`static/js/setup_wizard.js`).

There is no check for notifications.

---

## 3. Add a notification device

A **notification device** is a name for one of Home Assistant's `notify` services on
one instance. A phone with the
[Home Assistant Companion app](https://companion.home-assistant.io/) has a service
called `notify.mobile_app_<device>`. That is the usual choice.
Step by step, and how to reach it away from home: [Your phone, notifications and access
from away](phone-and-remote-access.md).

1. Open **Settings → Integrations**, and scroll to **Notifications → Companion Devices**.
2. Press **+ Add device**. It is disabled until you have an instance ("Add an HA
   instance first").
3. Fill in an **Alias**, such as "Phone".
4. Pick the **HA instance**.
5. Press **Discover** next to **Notify service**. The bridge asks that Home Assistant for
   its services (`GET /api/services`) and lists every `notify.*` one
   (`ha_instances.notify_targets()`; `GET /api/ha/notify-targets`). Each row shows the
   friendly name, the service, and when Home Assistant last saw it. A `_2` service that
   duplicates another is marked "duplicate of …"; pick the one without the suffix
   unless you know you need it. Use **filter services…** to find yours.
6. Press **Send test** to check that the phone receives it.
7. Press **Save**.

Each saved device has a mute switch, **Edit**, **Test** and remove. **Broadcast** sends
one message to every enabled device.

The list shows all `notify.*` services, not only phones. Any of them works as a device.

From the API: `GET`/`POST /api/ha/notify-devices`,
`PATCH`/`DELETE /api/ha/notify-devices/{id}`, `POST /api/ha/notify-devices/test` and
`POST /api/ha/notify-devices/broadcast`. A new device needs `alias`, `instance_id` and
`service`.

---

## 4. What the bridge notifies you about

There are **two separate channels**, and they behave differently.

### Push to your notification devices

These go to **every enabled notification device**. Set them under **Settings →
Integrations → Notifications → Auto-notify triggers** (`notify_engine.py`). Each has a
switch; the two SoC triggers also have a threshold.

| Trigger | Default | Sent when | Message |
|---|---|---|---|
| aGate offline / online | on | The gateway stops or starts answering polls. | "aGate is UNREACHABLE [gateway] — check network / WiFi / power." / "aGate is reachable again [gateway]." |
| Off-grid started / ended | on | The off-grid flag changes. | "Gateway went OFF-GRID [gateway] — running on battery." / "Gateway is back ON-GRID [gateway]." |
| Battery dispatch (VPP / force) started / ended | on | A dispatch is found active at start-up, or one starts that **this bridge did not start** (`vpp_monitor.py`). | "FranklinWH — VPP dispatch active at startup" / "FranklinWH — battery dispatch started (VPP)" |
| Battery SoC drops below | off, 20 % | SoC crosses the threshold downward. | "Battery SoC dropped below 20% [gateway] (now N%)." |
| Battery SoC reaches | off, 100 % | SoC crosses the threshold upward. | "Battery SoC reached 100% [gateway] (now N%)." |

A trigger fires on a **change** between one poll and the next, not on every poll. There
is no other rate limit.

Also sent to every enabled device: after a restart that interrupted a **scheduled
dispatch**, if `dispatch_interrupt_policy` is `notify` (the default), a message titled
"FranklinWH — scheduled dispatch …" (`reconcile_interrupted()` in `battery_control.py`).
See [Control → After a bridge restart mid-dispatch](control.md#after-a-bridge-restart-mid-dispatch).

**Recent notifications**, on the same page, lists each delivery (`GET /api/notify/log`;
the last 2,000 are kept).

### Home Assistant persistent notifications

These appear in Home Assistant's own notification panel, not on your phone
(`Notifier` in `notify.py`, posting to `persistent_notification.create`). They go to the
add-on's own Home Assistant, or, outside the add-on, to the `HA_URL` and `HA_TOKEN`
settings. They are sent only while `ha_notify` is on (the default). From `poller.py`:

| Event | Title | Message |
|---|---|---|
| The aGate stops or starts answering | FranklinWH aGate | "aGate is UNREACHABLE (check network / WiFi / power)." / "aGate is reachable again." |
| The Modbus TCP Server (aGate :502) stops or starts answering this bridge's probe | FranklinWH Modbus | "Modbus :502 is DOWN." / "Modbus :502 is back up." |
| Cloud credentials become invalid or locked | FranklinWH cloud credentials rejected | — |
| The firmware version changes | FranklinWH firmware updated | old → new |
| The aGate is found again at a new address | FranklinWH aGate moved | "Re-discovered on the LAN at <address>." |

There is no per-event switch for these.

!!! warning "The Push notifications switch does not stop pushes"
    The **Push notifications** switch at the top of the Notifications card says "Off —
    no notifications are sent". It sets `ha_notify`, which controls only the persistent
    notifications above. The pushes to your devices, from the triggers, from the
    dispatch reconcile and from schedules, do not check it. To stop pushes, switch the
    triggers off, or mute the devices.

---

## 5. Notifications from a schedule

A schedule can send to a notification device, either as its main action or as one of its
**Home Assistant actions**. Home Assistant actions run on entry, on exit, or both, and
each can have its own condition (**guard**). See
[Scheduler → Home Assistant actions](scheduler/actions.md#home-assistant-actions).

In the schedule editor: **Home Assistant actions (optional) → + notify**, then pick the
device, and set a title and a message. `%sensor.id%` in the text is replaced with the
live value, or `?` when there is none. Some useful ones: `%battery.soc_pct%`,
`%grid.power_w%`, `%schedule.name%`, `%run.phase%` (`fire` or `exit`) and `%run.at%`.
Write `%%` for a literal `%`.

### Worked example: tell me about the evening peak

The built-in template **Peak window — notify start & end** does this
(`peak_window_notify` in `scheduler.py`). As a request body:

```json
{
  "name": "Peak window",
  "trigger_type": "daily",
  "fire_at": "16:00",
  "duration_min": 300,
  "action": {"kind": ""},
  "ha_actions": [
    {"ha_kind": "notify", "device_id": "<notify-device-id>", "when": "both",
     "title": "Peak window",
     "message": "%run.phase%: SoC %battery.soc_pct%%, grid %grid.power_w%W"}
  ]
}
```

At 16:00 your phone gets "fire: SoC 74.2%, grid -350W", and at 21:00 "exit: …". The
schedule has no battery action, so it never competes with another schedule for the
gateway.

To be told only when the battery is low at the start of the peak, add a guard to the
action:

```json
"guard": {"sensor": "battery.soc_pct", "op": "<", "value": 50}
```

A notify step that cannot be sent is skipped, and the schedule's log says why: "device
no longer exists", "'Phone' is switched off", or "has no HA instance".

---

## Not yet available

Checked against the code on `main` (0.5.2). These do not exist today:

- **No notification when a scheduled action fails.** The code has a "FranklinWH — action
  failed" report (`resilience._report()`), but the Scheduler never connects it: it calls
  `run_action_outcome()` without a notifier. A schedule that fails is recorded in its
  log only.
- **No "dispatch ended" notification**, although the trigger is labelled "started /
  ended". `vpp_monitor.py` logs the end and sends nothing. A dispatch that this bridge
  started itself is not notified at its start either.
- **No push for** the Modbus TCP Server (aGate :502) going down, a firmware change, the
  aGate moving, or rejected cloud credentials. These are persistent notifications only,
  with no switch.
- **No per-device routing.** Every enabled device gets every triggered event.
- **No quiet hours, cooldown or rate limit.**
- **No filter for phones.** The service list shows every `notify.*` service, not only
  `mobile_app_*`.
- **No actionable notifications** (buttons in the notification). `notify.py` says so.
- **No setup check for notifications.**
- **No UI** for the persistent-notification target outside the add-on (`HA_URL`,
  `HA_TOKEN`; set them in the environment), and no button for the persistent-notification
  test (`POST /api/notify/test`).

### Known defect

**Disable or Enable on an instance under Settings → Integrations → HA Instances** shows
"Could not change it: …" even when the change worked. `toggleInstance()` in
`static/js/settings_tab.js` calls `this.loadNotif()`, and the method is named
`loadNotify()`. Reload the page to see the real state. The **Home Assistant** tab's
**Instances** list does not have this problem (read from the code, not tested).
