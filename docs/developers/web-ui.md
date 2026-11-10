# How the web UI uses the API

[Developers Guide](index.md) · [REST API](rest-api.md)

The bridge's web UI has no private back door. Every number it shows and every button it
offers is a call to the same REST API described in [REST API and OpenAPI](rest-api.md).
If you want to know which endpoint gives you something, find it in the UI and look at
what that tab fetches. This page explains how the UI is put together so you can do that.

Everything here is read from the code on `main` (0.5.2). Paths are relative to
`src/franklinwh_direct_connect_bridge/`.

---

## One page, server-rendered once

There is one HTML page. `index()` in `app.py` serves `/` by rendering
`templates/index.html` with Jinja2 (`_TEMPLATES`). It passes four values: `version`,
`base_path`, `cache_bust` and `host`. The response carries
`Cache-Control: no-store, must-revalidate`, because the page holds the hashed asset URLs.

`index.html` then pulls everything else in at render time:

- `partials/sidebar.html` and `partials/topbar.html`;
- every tab, each wrapped as
  `<div x-show="$store.app.activeTab === 'health'" x-cloak>{% include "tabs/health.html" %}</div>`;
- `partials/setup_wizard.html`, `partials/terminal.html` and `partials/bottom-nav.html`.

All tabs are in the page from the start. Switching tabs only changes which one is shown
(`x-show`, not `x-if`).

After that, the server sends no more HTML. Everything else is JSON from `/api/...`.

### Relative URLs and Home Assistant ingress

`index.html` sets `<base href="{{ base_path }}/">`. `_base_path()` in `app.py` fills it
from the `X-Ingress-Path` header, per request, because the ingress token rotates. Every
script, stylesheet and API call in the UI is a **relative** URL, such as
`fetch('api/summary')` or `src="static/js/app.js"`, so they all resolve inside the
ingress path. There is no JavaScript variable for the API base. If you add a call, keep
it relative, with no leading `/`.

### Scripts

Static files are mounted at `/static` (`app.mount("/static", StaticFiles(...))`). The
page loads Tailwind and Chart.js first, then the app scripts, each with
`?v={{ cache_bust }}`, and Alpine.js last with `defer`. The app scripts have to register
their components before Alpine starts; `index.html` notes this ("App JS — must load
before Alpine").

---

## Alpine.js: one store, one component per tab

The UI uses [Alpine.js](https://alpinejs.dev/) 3.14.1, vendored as
`static/js/alpinejs-3.14.1.min.js`.

**One global store**, `Alpine.store('app', {...})` in `static/js/app.js`. It holds what
every tab shares:

| In the store | What it is |
|---|---|
| `summary` | The latest gateway summary, from the 10-second poll below. |
| `activeTab` | Which tab is shown. Saved in `localStorage` as `fwh-tab`. |
| `gateways`, `selectedGateway` | The roster and the top-bar selection. |
| `gwQuery(sep)` | Returns `?gateway=<id>` when more than one gateway exists, otherwise `''`. |
| `fetchTimeout(url, ms, opts)` | `fetch` with an abort timer (15 s by default). |
| `toast()`, `confirmDialog()` | The notification and confirm UI that every tab uses. |
| `conn` | The offline banner state. |

**One component per tab.** Two styles exist side by side:

- registered with `Alpine.data`, used as `x-data="healthTab"`: `healthTab`,
  `schedulerTab`, `circuitsTab`, `generatorTab`, `haTab`, `solarTab`;
- a global factory function, used as `x-data="networkTab()" x-init="init()"`: the
  network, MQTT, battery, grid, energy costs, analytics, logs, settings, integrations and
  device tabs, plus `batteryControl()`, `energyFlowCard()`, `solarForecastCard()`,
  `setupWizard()` and `terminalConsole()`.

There is **no shared API client**. Each component calls `fetch()` itself and uses the
same few lines to turn an error into a message:

```js
if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
```

The message then goes to the component's own `error` field or to
`$store.app.toast(...)`. `fetchErrorText()` in `app.js` rewrites the browser's bare
"Failed to fetch" or "Load failed" into plain words.

### Tabs load when first shown

`lazyTab(cmp, key, loader)` in `app.js` runs a tab's loader the first time that tab
becomes active, and gives back a `reload()` for later. The analytics, grid, energy
costs, network, MQTT and settings tabs use it. The health and scheduler tabs do the same
thing with their own `$watch('$store.app.activeTab', ...)`. Some components load at
start-up regardless; `logsTab` is one.

The URL takes no part in this. There is no `?tab=` parameter. `setActiveTab()` in
`app.js` sets `activeTab` and writes it to `localStorage`. The sidebar and the bottom
nav both call it.

---

## What the browser polls

There is no WebSocket and no server-sent events. The UI polls. These are the timers in
`static/js`:

| Where | Endpoint | Every | When |
|---|---|---|---|
| `app.js`, `_dashTick` → `poll()` | `api/summary`, or `api/gateways/{id}/summary` for a selected gateway | 10 s | On every tab. Paused while the browser tab is hidden. |
| `app.js` | `api/gateways` | 120 s, or 10 s while there are no gateways | While visible. |
| `app.js` | `api/battery/command` | 15 s | While visible. Drives the top bar's **Release** button. |
| `app.js`, `checkBuild` | `api/version` | 60 s | Always. Tells you when the bridge was updated under you. |
| `app.js`, offline | `poll()` | backs off 2, 2, 5, 5, 10, 15, 30 s | Only while offline. |
| `network_tab.js` | `api/health/link` | 15 s | While the Network tab is shown. |
| `network_tab.js`, watch mode | `api/network/ping?count=1`, and `api/cloud/pop` every 5th tick | about 6 s | Only when you switch **watch** on. |
| `settings_tab.js` | gateways, sites and meters, tariffs | 15 s | While the Settings tab is shown. |
| `logs_tab.js` | `api/logs?...` | 10 s | From start-up until paused. |
| `battery_tab.js` | `api/battery?...` | 5 s | Only with Auto, Chart or Live on. |
| `circuits_tab.js`, `solar_tab.js` | `api/circuits/meter`, `api/solar` | 5 s, 10 s | Only with Auto on. |
| `energy_flow_card.js` | energy flow | 120 s | While the Dashboard is shown. |
| `solar_forecast_card.js` | `api/solar/forecast`, `api/energy/flow`, `api/metrics` | 15 min, 120 s | While the Dashboard is shown. |

The 10-second summary poll does not reach the aGate. `/api/summary` returns the copy the
gateway's poller cached on its last read (comment in `poller.py`: "Cache the full summary
for /api/summary ... so the dashboard reads the poller's copy instead of a fresh device
session on every browser poll"). The poller reads the gateway every `poll_interval`
seconds (30 by default). Polling the summary faster than that gives you the same numbers
again.

!!! tip "For your own client"
    Do the same. Poll `GET /api/summary` (or `/api/gateways/{id}/summary`) for the
    current state, no faster than the poll interval. Leave the endpoints that probe the
    device, such as `/api/network/ping` and `/api/health`, for when you need them: each
    one opens a session to the aGate.

---

## Worked example A: a read-only card

The **Link history** card on the **Network** tab shows, for each path to the gateway,
whether it is up, for how long, and its recent outages.

**The component.** `networkTab()` in `static/js/network_tab.js`:

```js
init() {
  const t = lazyTab(this, 'network', () => this.load());
  this.$watch('$store.app.selectedGateway', () => t.reload());
  setInterval(() => { if (this.$store.app.activeTab === 'network') this.loadLink(); }, 15000);
},

async loadLink() {
  try {
    const url = 'api/health/link' + this.$store.app.gwQuery();
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.statusText);
    this.link = await r.json();
    this.linkError = '';
  } catch (e) { /* sets this.linkError */ }
},
```

**The markup.** `templates/tabs/network.html` shows the card when there is data or an
error (`x-show="link || linkError"`). It loops over the legs with
`<template x-for="lg in (link ? link.legs : [])" :key="lg.leg">`, reading `verdict`,
`down_for_s`, `consecutive_failures`, `outages` and similar fields from each leg.

**The server.** `api_health_link(gateway, limit=20)` in `app.py` serves
`GET /api/health/link`. It reads the bridge's own link-health history from its database.
It does not probe the device, which is why the UI can refresh it on a timer.

To get the same thing from your own code:

```bash
curl -s "http://<bridge-host>:8101/api/health/link"
```

!!! note "Link & load (from 0.5.3)"
    0.5.3 (PR #164) added a **Link & load** card to the
    **Health** tab, served by `GET /api/diagnostics/link`. It shows a timed ping, a timed
    connect to port 9000, how many connections this bridge holds to the aGate on :9000
    and to the Modbus TCP Server (aGate :502) (counted from existing sockets, never
    opened), and the bridge's CPU, memory, threads and open files. On that branch the
    card is an inline component: `x-data="{ d: null, busy: false, err: '', async load()
    {...} }"`, calling `fetch('api/diagnostics/link' + $store.app.gwQuery('?'))`. It loads
    only when you press **Check**, with no timer. On the test VM (0.5.3) it reported a
    mock as "not probed" and showed the bridge's CPU and memory.

---

## Worked example B: saving a schedule

The schedule editor on the **Scheduler** tab creates and updates schedules.

**Building the body.** `save()` in `static/js/scheduler_tab.js` starts from the form,
converts the condition rows and the Home Assistant actions into the shape the API stores,
and removes the id:

```js
const body = { ...this.form,
  conditions: this._buildTree(this.form.conditions, false),
  exit_conditions: this._buildTree(this.form.exit_conditions, false),
  exit_match: this.form.exit_match || 'all',
  entry_hold_s: Number(this.form.entry_hold_s) || 0,
  ha_actions: this._haFromForm(this.form.ha_actions) };
delete body.id;
const url = this.form.id ? `api/schedules/${this.form.id}` : 'api/schedules';
const r = await fetch(url, {
  method: this.form.id ? 'PUT' : 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});
const out = await r.json();
if (!r.ok) throw new Error(out.detail || r.statusText);
```

If the schedule is running, `save()` asks first: "This schedule is running now — saving
will apply the changes to the window in progress." On success it shows "Schedule saved"
and reloads the list. On failure it shows `Save failed: <detail>`.

**The server.** Both routes take the `ScheduleReq` model in `app.py`:

- `api_schedule_create()` serves `POST /api/schedules` and returns **201** with the new
  row. The id is 12 hex characters from `uuid4`.
- `api_schedule_update(sid, req)` serves `PUT /api/schedules/{sid}`. An unknown id is
  **404**. Since #157 it **merges** what you send into the stored definition: fields you
  send replace their values, and fields you leave out keep them. To clear a field, send
  it empty.

The **enable** switch on a schedule card uses the same `PUT` with a smaller body
(`toggle()` in `scheduler_tab.js`).

!!! warning "Two things to know about this PUT"
    - `name` is required on every `PUT`, and `enabled` is not merged: `ScheduleReq`
      defaults it to `true`, and the handler applies `req.enabled` whether you sent it
      or not. A `PUT` that leaves out `enabled` **enables** the schedule. Send
      `enabled` every time.
    - The request model types `conditions`, `action` and `ha_actions` as free-form
      objects, so the server does not check what is inside them. A misspelt action
      kind is saved, and fails later at run time with "unknown action". The editor
      and `POST /api/schedules/evaluate` are the only checks before then.

    A validation error (422) has a `detail` that is a list. `save()` passes it to
    `new Error(...)` as it is, so the toast probably reads `Save failed: [object Object]`.
    That is read from the code and was not tested.
