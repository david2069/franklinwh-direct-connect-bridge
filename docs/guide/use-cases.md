# Use cases: "I want to…"

[Back to the guide index](index.md) · [At a glance](../overview/index.md)

Find what you want to do, read the short how-to, then follow the links for the details.

| I want to… | Jump to |
|---|---|
| Get started | [developer](#im-a-developer) · [spare Mac](#i-have-a-spare-mac-laptop) · [Home Assistant OS](#i-use-home-assistant-os) · [try it first](#i-want-to-try-it-before-i-connect-my-agate) |
| See what is happening | [any screen](#see-my-agate-in-a-browser-on-a-phone-or-on-a-tablet) · [system overview](#see-a-detailed-system-overview) · [network map](#see-a-detailed-network-map-and-troubleshoot) · [energy history](#see-my-energy-history) · [health checks](#get-health-checks-and-reminders) |
| Control and automate | [battery dispatch](#schedule-battery-dispatch) · [EV charger on solar](#charge-my-car-only-when-solar-is-in-a-range) · [complex rules](#build-complex-rules-and-work-with-home-assistant) |
| Be told | [events](#get-notified-about-events-on-my-agate) · [automated notifications](#get-automated-notifications) |
| Make it mine | [customise the UI](#customise-the-ui-show-hide-or-move-things) |
| Share and connect | [view-only users](#let-other-people-view-but-not-control) · [other apps](#connect-other-apps-without-learning-the-battery-quirks) |
| Money | [costs and bill estimate](#track-my-energy-costs-and-estimated-bill) |

---

## Get started

### I'm a developer

The Bridge is a working example of the Direct Connect API, with a REST API and an OpenAPI
schema served by the Bridge itself (Swagger and ReDoc pages included). Run it from a
development checkout, point it at a mock gateway, and write against the API or MQTT.

- [API examples: OpenAPI and MQTT discovery](../developers/api-examples.md)
- [Developers Guide](../developers/index.md): [REST API and OpenAPI](../developers/rest-api.md),
  [endpoint reference](../developers/api-endpoints.md), [MQTT](../developers/mqtt.md)
- [INSTALL.md → Development](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/INSTALL.md)
- [Direct Connect API library](https://github.com/david2069/franklinwh-direct-connect-api)

### I have a spare Mac laptop

Run the Bridge on the Mac with **Docker** (Docker Desktop) or **Python 3.11+**, point it at
your aGate's address, and open the web UI in a browser. The Bridge only records history and
runs schedules while it is running, so keep the Mac plugged in and stop it from sleeping.
Give the aGate a fixed address on your router so the Bridge can always find it.

- [Quick install, route A](quick-install.md#a-spare-desktop-from-the-command-line): Windows, macOS or Linux, from the command line
- [Installing → Docker](installing.md#docker) and [Standalone](installing.md#standalone)
  (the screenshots there were taken on Linux; the steps are the same)
- [INSTALL.md](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/INSTALL.md)

### I use Home Assistant OS

Install the Bridge as a Home Assistant add-on: add this repository to the add-on store,
install **FranklinWH Direct Connect Bridge**, set your aGate's address and start it. It opens
from the Home Assistant sidebar, links itself to Home Assistant, and finds the Mosquitto
broker on its own, so your aGate shows up as a device with sensors and controls.

- [Quick install, routes B and C](quick-install.md#c-existing-home-assistant-os)
- [Installing → Home Assistant add-on](installing.md#home-assistant-add-on)
- [Home Assistant and MQTT](home-assistant.md)

### I want to try it before I connect my aGate

Add a **mock gateway** under **Settings → Gateways → Add mock**. It is a simulated aGate
inside the Bridge, with solar, battery and load that follow the time of day, so you can try
every screen and test a schedule without touching a real battery. Developers can also run
the two-gateway demo described in the README.

- [Multi-gateway → Mock gateways](multi-gateway.md#mock-gateways)

---

## See what is happening

### See my aGate in a browser, on a phone or on a tablet

The web UI works on desktop, tablet and phone. On a phone, add it to your home screen so it
opens like an app. To reach it away from home, use Home Assistant's remote access or a VPN.

- [Tour of the UI](tour.md)
- [Your phone, notifications and access from away](phone-and-remote-access.md)

### See a detailed system overview

Open **System view** from the top bar. It draws your site: grid, aGate, home, solar,
batteries and circuits, with power flowing between them. Under **Options** you can add
voltage and frequency, today's energy, the power on each wire, alarms, and solar forecast
against actual.

- [Tour of the UI → System view](tour.md#the-top-bar)

### See a detailed network map and troubleshoot

The **Network** tab shows the connection end to end: the local link to the aGate, the
Modbus client (this bridge), MQTT and the cloud, with latency, link history and missed polls.
The **Health** tab shows each gateway's connection, and **Logs** keeps the Bridge's own log,
searchable and with a live follow mode. To find where a value on screen comes from, use the
**Probe** under **Settings → Integrations → Mapping**.

- [Tour of the UI → The tabs](tour.md#the-tabs) and
  [Integration → Mapping, and the Probe](tour.md#integration-mapping-and-the-probe)
- [Home Assistant setup → Troubleshoot](ha-setup-and-notifications.md#troubleshoot)

### See my energy history

The Bridge keeps its own history, on by default. The Dashboard has Power History and the
energy-flow Sankey; **Analytics** has day, week, month, year and lifetime views, from the
Bridge's own record or the FranklinWH cloud, with **Explain** for trends and CSV or JSON
export. With MQTT on, Home Assistant keeps its own history of the same sensors.

- [History, costs and tariffs](energy-and-costs.md): what is stored and for how long,
  [Analytics](energy-and-costs.md#analytics)

### Get health checks and reminders

Every morning the Bridge checks itself and rates the day green, amber or red, with the
reason. Your phone is told only when it is amber or red. Every Monday it reports on each
battery: state of health, round-trip efficiency and cycles. While the site is off-grid it can
remind you at an interval you choose.

- [Health reports](health-report.md)
- [Home Assistant setup and notifications → What the bridge notifies you about](ha-setup-and-notifications.md#4-what-the-bridge-notifies-you-about)

---

## Control and automate

### Schedule battery dispatch

Leave the aGate in Self-Consumption or Emergency Backup, and let the **Scheduler** force
charge or discharge at the times you choose, with a power and a target SoC. Start from a
template such as *Off-peak charge (overnight)*. Force needs the Modbus client (this bridge)
switched on.

- [Battery dispatch: best practices](battery-dispatch.md)
- [Scheduler](scheduler/index.md) and its [examples](scheduler/examples.md)
- [Control and write safety](control.md)

### Charge my car only when solar is in a range

Expose your EV charger's on/off switch to the Bridge, then build two small Home Assistant–only
schedules that check the solar power every few minutes in your chosen hours: one turns the
charger on when solar is inside your range, the other turns it off when it leaves. A third
turns it off at the end of the period.

- [Scheduler examples → EV charger on solar](scheduler/examples.md#ev-charger-on-solar)
  (the full recipe, field by field)

### Build complex rules and work with Home Assistant

A schedule combines a **trigger** (recurring windows, daily, weekly, every N minutes, cron
or calendar), **conditions** on any sensor or Home Assistant entity (with ALL/ANY groups and
a hold time), **exit conditions** that end it early, **priorities** for clashes, and
**actions** on the battery and in Home Assistant (service calls and notifications).
**Explain** shows why a schedule did or did not run.

- [Scheduler](scheduler/index.md): [triggers](scheduler/triggers.md),
  [conditions](scheduler/conditions.md), [actions](scheduler/actions.md),
  [exit and release](scheduler/exit-and-conflicts.md), [priorities](scheduler/priorities.md)
- [Use case: integrating with the Scheduler](../developers/scheduler-integration.md)

---

## Be told

### Get notified about events on my aGate

Link Home Assistant, install the Home Assistant Companion app on your phone, and add the
phone as a notification device. Then choose the triggers: aGate offline or back, off-grid
started or ended, a battery dispatch the Bridge did not start (VPP), and SoC thresholds.
Some notifications have buttons you can answer from the phone.

- [Home Assistant setup and notifications](ha-setup-and-notifications.md):
  [add a notification device](ha-setup-and-notifications.md#3-add-a-notification-device),
  [what it notifies you about](ha-setup-and-notifications.md#4-what-the-bridge-notifies-you-about)

### Get automated notifications

Add a **notify** action to any schedule, sent when it starts, when it ends, or both, with live
values in the message (for example the battery SoC). Combine it with conditions for alerts
such as "battery below 20 % in the evening". The daily health report also notifies you on
its own when something is wrong.

- [Notifications from a schedule](ha-setup-and-notifications.md#5-notifications-from-a-schedule)
- [Scheduler examples → Low-battery alert](scheduler/examples.md#low-battery-alert)
- [Health reports](health-report.md)

---

## Make it mine

### Customise the UI: show, hide or move things

Open the cog in the top bar and choose **Customise**. It has three tabs, for the top bar,
the navigation bar and the Dashboard cards: tick to show or hide each one, and drag to move
it. **Reset** puts a tab back to its defaults. The cog also has the theme and accent colour,
and System view has its own **Customise diagram**.

- [Tour of the UI → Customise](tour.md#customise)

---

## Share and connect

### Let other people view but not control

Turn on **Security** and add an account with the **viewer** role. A viewer sees everything
and can change nothing: no battery, mode, schedule or setting writes. Home Assistant users in
the read-only group get the viewer role in the sidebar panel automatically.

- [Security → Roles](security.md#roles) and
  [Who gets in, and as what](security.md#who-gets-in-and-as-what)

### Connect other apps without learning the battery quirks

Call the Bridge's REST API instead of the aGate. The Bridge picks the path that works for each
capability (local, Modbus or cloud), says when one is unavailable rather than failing
silently, and keeps its own watchdog and release on a battery force. Give each app an
**api** account and its own token.

- [REST API and OpenAPI](../developers/rest-api.md), including
  [Write safety](../developers/rest-api.md#write-safety): read it before you automate a write
- [Security → API access: tokens](security.md#api-access-tokens)

---

## Money

### Track my energy costs and estimated bill

Under **Billing & Utilities**, follow the setup steps: site, meter, plan and tariffs (you can
import tariffs from FranklinWH). The Summary then shows this period's cost so far and the
projection to the end of the period. Closed periods are kept as bills you can open and export.
Analytics' **Explain** suggests what to change to lower the bill.

- [History, costs and tariffs → Billing & Utilities](energy-and-costs.md#billing-utilities)
  and [Tariffs](energy-and-costs.md#tariffs)
