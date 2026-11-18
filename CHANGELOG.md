# Changelog

All notable changes to `franklinwh-direct-connect-bridge` are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/); this project uses
[Semantic Versioning](https://semver.org/).

> **This file starts on 2026-10-15.** It did not exist before then, so earlier releases are
> not reconstructed here — inventing entries from git history would put unverified claims in
> a public file. `git log` and the merged pull requests remain the record for anything
> before this point. Everything from 2026-10-14 onward is recorded because it is first-hand.

## [Unreleased]

### Added

- **Battery warranty & wear compares your use with the allowance** (#746). The card now
  shows throughput used from each source (the FranklinWH warranty's warranted − remaining,
  the cloud's discharge total since its first day with data, the bridge's snapshots), your
  kWh a day since the install date against **Pace**, SoH against the guaranteed end SoH, and
  each unit's warranty end with its serial masked. A blank install date is **estimated**
  from the first day with data in the FranklinWH cloud (observed on one site), marked
  please confirm ([guide](docs/guide/hems/battery-wear.md)).
- **Set up HEMS in the setup wizard** (#736). **Energy planning (HEMS)**, under Advanced in
  the setup list, walks through opting in, the site's location and array (it links to
  Location & Solar rather than asking again), the battery warranty, your home's usage and
  heavy loads, then a **Check** of what will be saved, with each load checked against what
  this bridge can control. **Save** writes the Battery warranty & wear and HEMS setup cards'
  settings, never the aGate or the cloud, and the result shows in the dialog. Both cards have
  a **Set up HEMS** link, and the setup list shows it Done once HEMS setup is on. The loads'
  choice lists read in plain words ([guide](docs/guide/hems/getting-started.md#the-set-up-hems-wizard)).

### Changed

- **Import opens a window first: Choose file…, Paste JSON, Cancel** (#752). On Android the
  file picker is the system's full-screen file browser with no Cancel, so Scheduler →
  Import now opens the bridge's own window; pasted JSON goes through the same import as a
  file, and errors show in the window. The tariff import window gains a **Cancel** button.
  Validation and the dry-run report are unchanged
  ([guide](docs/guide/scheduler/index.md)).

- **Short dates on the left** (#748). The Scheduler's activity log shows each time as
  "18 Nov 18:01" in a narrow fixed-width column, with the full date and seconds on hover or
  tap, so the message gets the row on a phone. Network → **PoP distribution** is a table
  with PoP, Share and Requests headers (no "req" on every row), and **Recent edge
  transitions** is a table with the short date first, then From → To
  ([guide](docs/guide/scheduler/outcomes.md#activity-log-results)).

- **HEMS has its own section in the guide** (#736). Nine pages under *HEMS (energy
  planning)*: what HEMS does and doesn't do yet, getting started, the solar forecast and its
  calibration, the load forecast and its backtest (with HAEO), battery warranty and wear,
  loads and what this bridge can control, the scheduler sensors with examples, the Home
  Assistant entity, and troubleshooting. The HEMS setup, battery wear and Load Forecast texts
  moved there; their old places keep a summary and a link, and the cards' **Guide** links
  open the new pages ([guide](docs/guide/hems/index.md)).

- **Setup: Automatic, Mock and Custom at the top of the setup list** (#741). Once a
  gateway exists the wizard opens on the setup list, and the first-run choices were only
  behind "Start again from the first steps". Three cards now head the list: **Automatic**
  (the guided path for one aGate and its aPower), **Mock** (a simulated gateway, never
  published) and **Custom** (the list itself, unchanged) ([guide](docs/guide/tour.md)).
- **Setup: Automatic asks for the rest in turn** (#741). After the aGate is found and
  confirmed, Automatic asks only for what is not done yet, each with a Skip: link Home
  Assistant (address and token, asked early), sign in to the FranklinWH cloud, turn on the
  Modbus client, publish to Home Assistant. It ends on a summary of what is set up, says
  when more than one aGate or aPower was found, and links to Custom for the rest
  ([guide](docs/guide/tour.md)).
- **Setup: existing Home Assistant entities** (#741). Before anything is published,
  Automatic and the setup list show the FranklinWH entities Home Assistant already has: from
  the broker's retained discovery messages and, when Home Assistant is linked, its registry
  (including true `_2` duplicates). This bridge's own leftovers can be removed after a
  second click; other integrations' entities are only reported. When another integration
  publishes the same aGate, Publish suggests No and the Modbus step warns of a second
  Modbus writer. With richo's FranklinWH integration loaded, an optional note says both can
  run side by side and lists what the bridge adds; **Keep both** hides it for good
  ([guide](docs/guide/tour.md)).

### Fixed

- **On a phone, Edit schedule's Save and Cancel were under the bottom nav** (#734). The
  schedule form and seven other dialogs (scheduler presets, imports and TOU import, smart
  circuits, generator, Home Assistant, Modbus history import) sat below the bottom nav, so
  on an iPhone a tap on Save hit a nav tab. Every dialog now opens above the nav; the
  schedule form never grows past the screen, keeps clear of the iPhone's home bar, and its
  body scrolls.

- **"aGate is using 4G — Wi-Fi has no internet" claimed more than the aGate reports**
  (#728). The aGate and the FranklinWH cloud only say 4G is the active link and Wi-Fi is
  on standby; the alert, its help and the Troubleshoot verdict now read "aGate is using 4G —
  Wi-Fi is on standby". Its code, severity and timing are unchanged. Alert and Troubleshoot
  times, which are in the site's time, now name the site's zone (e.g. "UTC+11") when your
  device is in another zone, so a time is not misread as hours old
  ([guide](docs/guide/ha-setup-and-notifications.md)).
- **The alert bar under the top bar could not be closed** (#727). After an alert such as
  "aGate is using 4G" was acknowledged, its bar stayed until the fault cleared, cut off on
  a phone and naming the gateway by its id. The bar now has **×** and the alert list has
  **Dismiss**, which hide it for everyone until the condition clears (a new occurrence
  shows again); the bar wraps its full text and names the gateway
  ([guide](docs/guide/ha-setup-and-notifications.md#alerts)).

- **Troubleshoot showed the LAN answering while :9000 refused, and the 4G verdict without its
  reading time** (#728). The Connection card took the link record, which stays "up" until three
  failed probes, so for a few minutes it said "answering on :9000" while the Health check,
  probing afresh, said refused; both now use one rule, and a link with no good poll lately
  reads "not answering lately". The verdict says whose reading it is: the FranklinWH cloud
  just now, or the aGate's own report and the time it was read (an aGate report older than
  two network reads is not used). A cloud call that failed reads "asked, no answer", not
  "not asked" ([guide](docs/guide/ha-setup-and-notifications.md#troubleshoot)).

## Releases

Full notes for each release are on the [docs site](https://david2069.github.io/franklinwh-direct-connect-bridge) and in [`docs/changelog/`](https://github.com/david2069/franklinwh-direct-connect-bridge/tree/main/docs/changelog). One entry per release below: counts, then highlights.

## 2026-11-18

### [0.5.52](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.52.md)

Added 11 · Changed 5 · Fixed 3

- Energy planning (hems 0.2.0): a solar forecast that learns from your system, a Home…
- FranklinWH TOU and tariffs: buy and sell rates per day type, Import from FranklinWH into…
- Home Assistant: Battery Command controls, Bridge Version, VPP, off-grid, smart circuit…
- System view: several aPowers show as one battery with the count, each aPower in the hover…
- Fixes: the setup wizard's Yes no longer errors on a mock

## 2026-11-17

### [0.5.50](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.50.md)

Added 2 · Changed 3 · Fixed 5

- Scheduler: Smart Circuits, Generator and V2L sensor groups (on/off, power, energy…
- Home Assistant: the Dashboard card uses Home Assistant's real entity ids
- Dashboard: the State of Charge and Energy cards reflow instead of cutting text off
- All gateways: the site SoC is weighted by battery capacity
- Troubleshoot: Reconnect to Wi-Fi runs when pressed

## 2026-11-16

### [0.5.49](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.49.md)

Added 2 · Changed 1 · Fixed 2

- Scheduler: schedules run again on a gateway whose meter has a tariff (every tick had…
- Prices: generic dynamic-pricing attributes (forecasts, descriptors, renewables, spike…
- Solar Forecast: the Energipays Bridge layout with actual solar and temperature, and a…
- FranklinWH TOU: a clash is only a Force that contradicts the TOU block, shown as a table

### [0.5.48](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.48.md)

Added 2 · Fixed 3

- Scheduler: a FranklinWH TOU view: a dated copy of the TOU schedule from the cloud, the…
- Location & Solar: each site has its own location and solar array
- Settings: the Billing & Utilities sub-tab is back
- Analytics: Line and Area can be picked again
- Reliability: a shutdown just after a gateway edit no longer floods the log and stops the…

### [0.5.47](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.47.md)

Added 4 · Changed 2 · Fixed 8

- Billing & Utilities: new tariffs can be entered again (+ Add tariff was all disabled…
- Health: a weekly battery report (SoH, efficiency, cycles, the week's energy) and…
- System view: one diagram for all gateways of a site
- Reliability: shutdown survives a cancelled poller and aborts the right one
- Changelog: each release links to its notes on GitHub

### [0.5.46](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.46.md)

Added 1 · Changed 5 · Fixed 4

- Health: a daily health report at 07:00: green, amber or red with the reason, on Health →…
- Analytics: Explain reads clearly, links to Billing & Utilities and gives the grid effect…
- Billing & Utilities: Import tariff says what it added and has Done
- Changelog and README: the release index has its own heading in HA's update dialog

## 2026-11-15

### [0.5.45](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.45.md)

Added 4 · Changed 4 · Fixed 10

- Billing & Utilities: a page of its own (Summary, Bill detail, History, Plans & meters)…
- Battery: a slow BMS read waits 60 s and says so
- Alerts: the open-alerts list is lines, not columns, with a short time
- Setup: Settings → Setup is the one setup list, and every task opens where it is set up
- Gateways: search takes a port, list or range (Emulator labelled)
- Prices and dates: the price Filter searches all of Home Assistant

### [0.5.44](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.44.md)

Added 1 · Fixed 5

- Billing: two gateways on one meter share one bill (one set of fixed charges, demand from…
- Retailers: Provider from / until dates and the export note save
- Date boxes: an empty date box stays blank in Safari and the HA app
- Explain: points to Settings → Sites & Billing → your meter → + Add tariff
- Battery recordings: survive the aGate dropping off, and show why they ended and who…

## 2026-11-14

### [0.5.43](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.43.md)

Added 3 · Changed 3 · Fixed 5

- Connectivity: Troubleshoot for an unreachable aGate or one on 4G, with Health check and…
- Offline values: Dashboard and top bar grey out last-good values while the aGate is offline
- Network tab: the :502 line is no longer green on a result older than the link
- Watchdog: cloud-status back-off no longer raises `WORKER_STALLED`
- Tariffs and billing: tariffs live on the meter, billing by date, retired tariffs locked…
- Logs: the time range shows the range in use

## 2026-11-13

### [0.5.42](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.42.md)

Added 18 · Changed 13 · Fixed 6

- Off-grid: the notification gives stored kWh and time left at the current usage
- Scheduler: All gateways for rules that move no battery
- Prices, tariffs and solar: prices in one place under Sites & Billing (price spike, HA
- Analytics: more cards on Local and Cloud, and Explain (trends and what to change)
- Setup and support: the setup list (FranklinWH Gateway Emulator, Modbus TCP), confirm
- Battery: Record on the live trend, scheduled recordings, recordings purged after 90

### [0.5.41](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.41.md)

Changed 1 · Fixed 3

- Ask before continuing names who it asks, and doesn't clash with notify actions
- System view: smart circuits by their aGate names, and Customise one gateway at a time
- Analytics: Local's SoC on Lifetime, and "Home load" on both sources
- The Audit trail moved to Logs, and is easier to read

## 2026-11-12

### [0.5.40](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.40.md)

Added 2

- System view: voltage & frequency, today's energy, power on wires and alarms
- System view → Alarms from the devices

## 2026-11-11

### [0.5.39](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.39.md)

Added 10 · Changed 10 · Fixed 3

- Local history: how long it is kept, and an off switch, in Settings
- Local history keeps full resolution for 10 days, then 5-minute rows
- Analytics → Cloud
- Analytics → Local steps through history
- Energy flow: hover or tap a flow to see what it carried
- Analytics: a time in the date picker on the Day views

## 2026-11-10

### [0.5.38](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.38.md)

Added 1 · Changed 1

- Notifications when the bridge starts, restarts or stops
- The off-grid notification says why

## 2026-11-09

### [0.5.36](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.36.md)

Changed 1 · Fixed 2

- Metrics export leaves mock gateways out
- The metrics export says which gateway each row is from
- Every number each poll reads is kept, not just the chart values

## 2026-11-08

### [0.5.35](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.35.md)

Changed 4 · Fixed 11

- An empty gap could sit between the top bar and System view when it opened while…
- `POST /api/reboot` description no longer says it is gated by `allow_writes`
- Control and Circuits no longer say "Set ALLOW_WRITES=true"
- Each tab sets itself up once, not twice
- Health → Rediscovered is per gateway
- Generator → Operating windows looks unavailable while the generator feature is off

### [0.5.34](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.34.md)

Changed 1 · Fixed 8

- A late Release tap no longer releases a different force
- Release on a VPP found at start-up checks the VPP
- A restart just after a schedule asks no longer sends the question twice
- The notifications' own database connection is closed when the bridge stops…
- Notifications guide corrections
- Version reported from a source checkout matches pyproject.toml

## 2026-11-07

### [0.5.33](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.33.md)

Changed 2 · Fixed 6 · Docs 3

- The aPower model is read from the gateway
- History counts as evidence
- Support info lists what's installed
- A site without solar no longer counts as having solar
- Saving System Setup keeps the gateway's readings
- Remote solar size matches the Solar tab

## 2026-11-05

### [0.5.32](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.32.md)

Added 6 · Fixed 2

- API tokens and the api role
- Home Assistant users get the role of their HA group
- Accounts, sign-in, roles and the Security switch
- The HTTPS port
- Trusted networks
- Guide: Security

## 2026-11-04

### [0.5.30](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.30.md)

Changed 2

- Send to → Chosen devices is a drop-down
- Guide: Home Assistant setup and notifications brought up to date

### [0.5.29](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.29.md)

Added 5 · Changed 1 · Fixed 6

- Notifications check and Test critical alert
- Send to for critical alerts and Release / Keep
- Ask templates and two off-grid sensors
- Send to: all enabled devices or the devices you choose
- Schedule editor: a {x} button to insert values
- Critical alerts reach Home Assistant and phones on Docker and pip

### [0.5.28](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.28.md)

Added 2 · Fixed 3

- Ask before continuing: your own buttons, a text reply, and the answer passed on
- **Schedule conditions
- The Ask before continuing question now fills in `%sensor.id%` values, like…
- Logs on a phone
- Companion devices on a phone or a narrow iPad

## 2026-11-03

### [0.5.27](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.27.md)

Added 7 · Changed 5 · Fixed 3

- Notification targets
- Buttons on notifications
- Schedules can ask before they run
- Groundwork for notifications with buttons
- Home Assistant: Run Status Description
- Home Assistant: Cloud Connection Via

### [0.5.26](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.26.md)

Changed 1 · Fixed 1

- Demo mode's mock aGates start again
- franklinwh-modbus 0.10.1 → 0.13.0

### [0.5.25](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.25.md)

Fixed 1

- A dispatch naming a gateway the Modbus Bridge cannot address is refused

## 2026-11-02

### [0.5.24](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.24.md)

Fixed 5

- System view and the top bar's gateway picker show the same gateway
- System view is in the phone's More sheet, by name
- When the top bar wraps to two rows, the sidebar's logo row grows with it
- `franklinwh-system-view` 0.2.3 (was 0.2.0)
- On a phone, tapping an object in System view left its hover box over the details

## 2026-11-01

### [0.5.23](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.23.md)

Added 1 · Fixed 1

- System view: Customise diagram, place name and weather
- System view

### [0.5.22](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.22.md)

Added 1 · Fixed 1 · Testing 1

- System view
- A pip install starts again
- Every PR now installs the bridge the two standalone ways INSTALL.md offers

## 2026-10-31

### [0.5.21](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.21.md)

Added 2

- Home Assistant gets Grid Voltage and Grid Frequency
- Reserve SoC in Home Assistant

### [0.5.20](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.20.md)

Added 1 · Security 1 · Docs 1

- **Home Assistant gets Grid Status, Active Reserve SOC, Firmware Version and…
- Home Assistant controls stop working when the Controls group is off
- Up to two releases a day

### [0.5.19](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.19.md)

Breaking 2 · Docs 1

- Every schedule names its gateway
- No call falls back to the default gateway's address
- The README no longer credits the library with the force watchdog

## 2026-10-30

### [0.5.18](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.18.md)

Added 1 · Changed 5 · Fixed 27 · Breaking 2

- Scheduler Monitor
- The VPP monitor watches every gateway
- Each gateway is locked to one aGate serial
- Re-discovery adopts only this gateway's own aGate
- Site view no longer writes to the default gateway
- The reserve SoC is written to the gateway on screen

## 2026-10-27

### [0.5.17](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.17.md)

Fixed 2

- Dashboard Run status shows the state that matters
- After a reconnect, the aGate's all-zero answers no longer show or record as 0 W

## 2026-10-26

### [0.5.16](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.16.md)

Added 1 · Fixed 6

- User guide: shorter names in Home Assistant
- Network tab: missing link data reads "not reported"
- Grid & Inverter: the limits are shown and entered in kW
- The worker-restart guard for an active force works
- The Battery tab's charts refresh again
- **Battery Control forces through the Modbus client (this bridge) use…

## 2026-10-24

### [0.5.15](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.15.md)

Added 1 · Changed 1 · Fixed 1 · Security 1

- Guide opens the page for the tab you're on
- The unofficial-software disclaimer is asked once per installation
- The battery dispatch (VPP) log lines and notifications say what the site was doing
- franklinwh-cloud is pinned to 0.6.4

## 2026-10-23

### [0.5.14](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.14.md)

Added 9 · Changed 3 · Fixed 19 · Security 1

- A bridge-wide "Bridge problem" sensor in Home Assistant
- The terminal has a Copy button,
- Alerts are stored records
- Alert API
- What raises an alert
- Critical alerts reach Home Assistant even with no phone set up

## 2026-10-21

### [0.5.13](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.13.md)

Changed 1 · Fixed 6

- Settings → Integrations → Save mappings works
- The FranklinWH Cloud API card can save your credentials
- One rejected cloud sign-in now stops all of them
- Every cloud sign-in is in the Audit Trail
- The cloud card's fields are left-aligned
- The cloud status check no longer signs in every 5 minutes

### [0.5.12](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.12.md)

Changed 2

- The add-on now installs a prebuilt image instead of building on your machine
- Supported architectures are now aarch64 and amd64 only

## 2026-10-20

### [0.5.11](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.11.md)

Added 1 · Fixed 3

- A **Generator** page in the user guide
- The Generator tab is always available, as in the FranklinWH app
- The generator mode can no longer be changed from the bridge
- No more Bad Gateway errors from the Generator before a gateway is set up

## 2026-10-19

### [0.5.10](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.10.md)

Changed 1

- The franklinwh-modbus library is pinned to 0.9.6

## 2026-10-18

### [0.5.9](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.9.md)

Changed 1 · Fixed 3

- **The bridge no longer connects to the aGate's Modbus TCP Server (:502) just to…
- A mock gateway is never contacted over Modbus
- Release reports what the aGate says
- The Modbus client (this bridge) is off by default on a new install

## 2026-10-17

### [0.5.8](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.8.md)

Fixed 1

- Connecting to the aGate over Modbus no longer writes its operating mode and reserves

### [0.5.7](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.7.md)

Fixed 5

- Analytics shows the selected gateway's time, not another gateway's
- The Analytics chart is drawn on a real time axis
- Custom range takes a date and a time, in the gateway's zone
- The caption says what the chart shows
- Export CSV/JSON exports the range on screen,

### [0.5.6](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.6.md)

Fixed 1

- **A Force Charge above the battery's rated power no longer discharges it (and a…

### [0.5.5](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.5.md)

Fixed 1

- **A schedule set to turn a smart circuit Off no longer turns it On, and…

### [0.5.4](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.4.md)

Fixed 1

- **A Home Assistant sensor that is unavailable or unknown no longer counts as 0…

### [0.5.3](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.3.md)

Added 1 · Fixed 3

- Link & load diagnostics
- The bridge no longer sweeps your whole network every time the aGate is slow to answer
- The search no longer probes the aGate Modbus TCP Server (:502),
- "aGate moved" is announced only when the address actually changed

## 2026-10-16

### [0.5.2](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.2.md)

Fixed 1

- Turning a schedule on or off no longer wipes its settings

### [0.5.1](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.1.md)

Added 2 · Changed 2 · Fixed 1

- Unpublish that stays unpublished
- aGate network state in Home Assistant
- A gateway with publishing off no longer appears in Home Assistant
- The HA Device info reads like the Modbus Bridge's
- Diagnostic sensors are on the Diagnostic card

### [0.5.0](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.5.0.md)

Fixed 1

- Editing a gateway no longer stops it for good

### [0.4.10](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.10.md)

Fixed 1

- Power History and the other charts fill again on add-on installs

### [0.4.9](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.9.md)

Fixed 1

- No more false "worker_failed" entries

### [0.4.8](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.8.md)

Changed 1

- "Modbus" is always qualified in the UI

### [0.4.7](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.7.md)

Fixed 2

- State of Charge shows one decimal in Home Assistant
- "Connection Lost" no longer flashes after one slow answer

### [0.4.6](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.6.md)

Security 1

- Taking the site off-grid always needs a confirmation

### [0.4.5](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.5.md)

Fixed 1

- Smart Circuit switches in Home Assistant show on or off

### [0.4.4](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.4.md)

Fixed 1

- The add-on keeps its link to Home Assistant after an update

### [0.4.3](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.3.md)

Fixed 1

- Eight Home Assistant sensors show values instead of "Unknown"

### [0.4.2](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.2.md)

Fixed 2

- "Bridge entities in Home Assistant" counts the right entities
- "MQTT broker connected" no longer fails when nothing is publishing yet

### [0.4.1](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.1.md)

Fixed 1

- A fresh add-on install can add a gateway again

## 2026-10-15

### [0.4.0](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.4.0.md)

Changed 1 · Fixed 1

- "Set up" opens the wizard
- Each gateway is its own Home Assistant device, named after its serial

### [0.3.3](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.3.3.md)

Added 3 · Changed 1 · Fixed 4

- Picking a notification target is a picker, not a search of 3804 entities
- A Home Assistant instance can be disabled without deleting it
- The add-on's own Home Assistant now reads as **"This Home Assistant…
- Turning publishing on takes effect immediately
- The broker is configured even while publishing is off
- The Guide no longer shows `{"detail":"Not Found"}`

### [0.3.2](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.3.2.md)

Added 2 · Fixed 1

- The setup wizard ends on Home Assistant, with live checks and one question
- Discover says where its subnet came from
- Adding a mock gateway no longer fails with "Internal Server Error"

### [0.3.1](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.3.1.md)

Added 2 · Fixed 5

- The PV array size can come from the gateway
- The add-on configures what the Supervisor already knows
- The schedule editor no longer throws your work away
- Confirmation dialogs are the app's, not the browser's
- The dashboard comes to life when a gateway appears
- No more blank gateway row

### [0.3.0](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/changelog/0.3.0.md)

Added 12 · Changed 5 · Fixed 13 · Documentation 2

- Battery dispatch is gated on a CONFIRMED Modbus path, in four states
- The setup wizard offers the FranklinWH app account, optionally, and says why
- A mock gateway no longer publishes to Home Assistant by default
- The gateway switcher shows each gateway's operating mode and battery direction
- The wizard's last step reports every gateway, not one
- The setup wizard asks where the site is, and every gateway uses that one zone
