# Changelog

All notable changes to `franklinwh-direct-connect-bridge` are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/); this project uses
[Semantic Versioning](https://semver.org/).

> **This file starts on 2026-10-15.** It did not exist before then, so earlier releases are
> not reconstructed here — inventing entries from git history would put unverified claims in
> a public file. `git log` and the merged pull requests remain the record for anything
> before this point. Everything from 2026-10-14 onward is recorded because it is first-hand.

## [Unreleased]

### Changed

- **Guide opens this bridge's published docs** (#257). The sidebar, the More sheet and
  Settings → Help link straight to **Docs** and **User Guide** on the bridge's own site, in a
  new window. The in-app panel that said the docs weren't bundled, and pointed at the
  library's site, is gone.
- **Logs show a short source name** (#239): `poller` instead of
  `franklinwh_direct_connect_bridge.poller`. The full name is the tooltip and the filter
  value, and the column now shows on phones.

### Fixed

- **Every notification is also in the app log** (Logs tab), as a warning. With no companion
  devices set up, the notifications were recorded only in Settings → Notifications and
  delivered nowhere. In that list the time now comes first.
- **A schedule with unknown fields is refused** (#269). `POST`/`PUT /api/schedules` ignored
  fields it didn't recognise, so a mis-shaped request saved a schedule built from defaults.
  It now answers 422 and names the field.
- **The first-use disclaimer fits a phone screen** (#231). Its text scrolls and its Continue
  button stays in view; Documentation opens the published guide instead of a page that was
  not found.
- **The wizard's "Yes" to Home Assistant works on the add-on** (#264). It was disabled
  whenever MQTT was already on, the add-on's default, so the wizard's gateway was never
  published.
- **No connection warnings before a gateway is set up** (#265). A fresh install logged
  "Name does not resolve" on every page load.
- **Editing a schedule through the API no longer switches it back on** (#168). A
  `PUT /api/schedules/{id}` that left out `enabled` turned a disabled schedule on; it now keeps
  its on/off state unless `enabled` is sent.
- **The scheduler sensor `grid.connected` follows the off-grid state** (#206). It was worked
  out from grid power and read 0 (disconnected) whenever grid power was exactly 0 W while on
  grid. It now reads 1 on grid and 0 off grid, and has no value when the off-grid state is
  not known.
- **A stale AEMO NEM price is no longer used forever** (#207). When AEMO could not be reached,
  `tariff.spot_price` (and a dynamic NEM tariff) kept the last price however old it was, so a
  price-gated schedule could act on a price from hours earlier. The last price is now kept for
  30 minutes, as on the Modbus Bridge, and then the sensor has no value until AEMO answers.
- **Next fire is right for Every N minutes of 24 hours or more** (#208). The card showed the
  anchor plus N, but the schedule runs daily at the anchor; it now shows the next anchor. The
  same applies to the last slot of a day when N does not divide 24 hours.
- **A force charge or discharge with no power set is refused** (#209). Sent through the API
  with an empty `power`, it ran as a 0 W force; it is now skipped with the reason "no power
  set". **Always** and zero-duration schedules no longer give a failed write only 1 second to
  retry: they use the normal retry time limit.
- **An Always schedule fires every time its conditions start to hold** (#190). It fired once,
  ever: its single stored run stayed finished, across restarts, so every later rising edge
  sent nothing. Each rising edge is now its own run. The release on the falling edge is
  unchanged.
- **A schedule with its key setting missing no longer fires every day** (#198). **Weekly** with
  no days, **Monthly** with no day of the month and **One-off** with no date now never fire, and
  a **Recurring window** whose start equals its end is empty instead of open all day. Saving or
  importing one of these is refused with the reason (HTTP 422 on save); schedules already
  saved this way stop firing.
- **Schedules are checked when they are saved or imported** (#202). A schedule whose action,
  Home Assistant actions, conditions, cron expression, interval, days, months, day of the month
  or dates the engine cannot use is refused with the reason (HTTP 422 on save; listed as an
  error per entry on import), instead of failing or being skipped when it runs. Import also
  warns about a condition on a sensor this bridge does not know, or on a Home Assistant entity
  that is not exposed. An imported Modbus Bridge entry whose Home Assistant action this bridge
  cannot run is now reported as an error rather than saved.
- **Scheduler history names the gateway** (#205). Each row written by a gateway's scheduler run
  now records that gateway, and History shows its name beside the schedule, so the rows of a
  rule that runs on every gateway can be told apart. `GET /api/schedules/log` returns it as
  `gateway_id`. The history table gains a `gateway_id` column; older rows have none.
- **Next fire, the timeline and Test follow the site's clock** (#161). They used the bridge
  container's clock while schedules fire on the aGate's, so when the two zones differed the
  card's **Next:**, **● active**, the timeline and **Test** were off by the difference. They now
  use the clock of the schedule's gateway (the default gateway for an unbound schedule), and
  **Test** evaluates that gateway's values instead of always the default gateway's. When the
  aGate's clock cannot be read, the scheduler keeps using the zone it last read, and logs it,
  instead of silently switching to the container's.

## [0.5.13] — 2026-10-21

Hotfix: the FranklinWH cloud can be connected from the add-on again, it signs in once instead of every 5 minutes, and a rejected password stops all sign-ins before the account can lock. Save mappings works.

### Changed

- **franklinwh-cloud is pinned to 0.6.0** (#254). It was an open range, so each new library
  release went into the image untested. 0.6.0 adds the library features the bridge now uses
  instead of its own: clear sign-in errors (no more `TypeError` on an unexpected reply), a
  distinct rate-limit error, `resolve_gateway()` (never guesses among several aGates), and
  closing each session properly.

### Fixed

- **Settings → Integrations → Save mappings works** (#247). It failed every time since the
  Mapping panel arrived (0.5.0), with an internal server error that Safari showed as "The
  string did not match the expected pattern". Errors that aren't JSON now show their HTTP
  status instead of the browser's parse message.
- **The FranklinWH Cloud API card can save your credentials** (#248). The email, password and
  serial you typed were never saved, and **Test** only checked what was already stored, so
  the cloud could not be connected from the add-on. **Save & test** now signs in with what you
  typed and stores it only if that works. The gateway serial is optional when your account
  has one aGate; with several, it lists them and asks you to choose, instead of quietly using
  the first.
- **One rejected cloud sign-in now stops all of them** (#248). FranklinWH locks the account,
  the FranklinWH app included, after a few wrong passwords, warning first ("you still have 2
  chances"). As soon as FranklinWH rejects a sign-in, the bridge puts cloud sign-in **on hold**:
  nothing is sent from any part of the bridge, whatever is typed, until you check the password
  in the FranklinWH app and press **Clear hold**. The card shows FranklinWH's exact reply.
- **Every cloud sign-in is in the Audit Trail** — where it came from (the card, the status
  check, a reserve write), the account (masked), and FranklinWH's reply; the password never.
  Cloud credential changes are audited too (which field, not its value).
- **The cloud card's fields are left-aligned**, the password can be shown, and the browser no
  longer fills it in with an unrelated saved password.
- **The cloud status check no longer signs in every 5 minutes** (#233). It signs in once and
  reuses the session (the library renews it when it expires). After a failed check it now
  waits longer each time, up to 30 minutes, instead of retrying every 45 seconds, so a
  rate-limited account is not polled harder.

## [0.5.12] — 2026-10-21

The add-on installs a prebuilt, tested image instead of building on your machine.

### Changed

- **The add-on now installs a prebuilt image instead of building on your machine** (#243).
  Home Assistant downloads `ghcr.io/david2069/{arch}-franklinwh-direct-connect-bridge`, built
  and tested before release, so installs and updates are faster and everyone runs the same
  build. GitHub's download count for the image also tells us roughly how many installs and
  updates there are; nothing else is collected.
- **Supported architectures are now aarch64 and amd64 only.** armhf, armv7 and i386 are no
  longer offered: they can't be tested here, and the image is not built for them.

## [0.5.11] — 2026-10-20

The Generator tab is always available, as in the FranklinWH app, and the bridge no longer changes the generator mode.

### Fixed

- **The Generator tab is always available, as in the FranklinWH app** (#238, #229). It was
  hidden unless the bridge guessed a generator was present, which also hid the switch to turn
  the generator feature on. The bridge can't know what is wired up; the tab now says what the
  aGate reports instead of "installed" or "not installed". Generator figures on the dashboard
  still appear only while the feature is on.
- **The generator mode can no longer be changed from the bridge** (#237). The Auto / Manual
  buttons wrote a field that the FranklinWH app's own traffic shows is a manual start/stop
  command, not the mode. The mode fields are now shown raw, and the mode endpoint refuses
  without writing. Use the FranklinWH app to change the mode.
- **No more Bad Gateway errors from the Generator before a gateway is set up** (#94). Opening
  the app before the setup wizard has added a gateway asked the generator endpoint for data,
  which answered 502 and put two errors in the browser console on every load. It now answers
  "No gateway is set up yet."

### Added

- A **Generator** page in the user guide.

## [0.5.10] — 2026-10-19

The Modbus library is pinned to the version this bridge was tested with.

### Changed

- **The franklinwh-modbus library is pinned to 0.9.6** (#219). The bridge used to accept any
  0.9 or later, so each new library release went into new installs and rebuilds before it was
  tested here — 0.9.6 and 0.10.0 both arrived that way within two days. 0.9.6 is the version
  0.5.9 was tested with on a real aGate. With it, failed Modbus status reads are logged as
  WARNING (rate-limited), not DEBUG.

## [0.5.9] — 2026-10-18

The Modbus client (this bridge) stops connecting to the aGate just to show a status, and is off by default on new installs.

### Changed

- **The Modbus client (this bridge) is off by default on a new install.** Turn it on under
  Control → Modbus client (this bridge) to use Battery Control's force commands and the
  battery ratings read. Some sites don't have the aGate's Modbus TCP Server (:502)
  switched on, on some gateways it misbehaves, and it serves only one client at a time,
  so the bridge no longer connects to it unless asked. An existing install keeps its
  setting, including one that was on only because that used to be the default (#88).
  Without the metrics store (no saved settings), the client is now off.

### Fixed

- **The bridge no longer connects to the aGate's Modbus TCP Server (:502) just to show a
  status.** The Modbus TCP Server serves one client at a time, and this bridge was a second
  client next to the Modbus Bridge: up to three connections on every poll to show "Modbus
  :502 Up" (#221), and a full Modbus session every 30 s for each open browser tab, to show
  whether Battery Control was available (#223). The Modbus status now shows the result of
  the bridge's last real connection (a force, a release, the hourly ratings read, or
  Control → Modbus client → Test), with its time. Battery Control re-checks when it is
  shown, at most once per 30 s, and otherwise hourly. A force still checks the
  connection itself before it runs.
- **A mock gateway is never contacted over Modbus.** A mock-only install logged
  `ERROR … Error scanning SunSpec base addresses` within seconds (#95). The bridge now
  reports "a mock gateway has no Modbus TCP Server to reach" without trying.
- **Release reports what the aGate says.** It reads the aGate back after releasing and
  reports "released" only if no force is still enabled; otherwise it says the release was
  sent but not confirmed. With the Modbus client switched off, a Release now explains that
  the force this bridge started is still active, and how to clear it (#174).

## [0.5.8] — 2026-10-17

Hotfix: connecting to the aGate over Modbus no longer writes to it.

### Fixed

- **Connecting to the aGate over Modbus no longer writes its operating mode and reserves.** The
  franklinwh-modbus library (0.9.5) tested whether the mode and reserve registers (15507–15509)
  were writable on every connect, by writing a test value and then the original back. This bridge
  connects for every force, release and availability check, so on a site where those registers
  are writable the mode and reserves could briefly change, or stay changed if the connection
  dropped in between. On the AU aGate tested so far those writes are discarded. The bridge now
  turns that test off. (#224)

## [0.5.7] — 2026-10-17

Analytics charts read in the selected gateway's time, on a real time axis.

### Fixed

- **Analytics shows the selected gateway's time, not another gateway's.** The time zone was read
  once at start-up, before the gateway list had loaded, so it came from the default gateway (a mock
  on one site, which put every label 10 hours out). It now follows the gateway you select. (#144)
- **The Analytics chart is drawn on a real time axis.** Spacing is proportional to time, a period
  with no samples shows as a gap, and lines are straight between samples instead of smoothed
  shapes that weren't readings. Axis labels are 24-hour HH:MM, with a short date ("16 Oct") on a
  second line where the day changes. (#145)
- **Custom range takes a date and a time, in the gateway's zone.** A day used to start at UTC
  midnight. The default is today 00:00 to now, and a **Today** button resets it. (#145)
- **The caption says what the chart shows:** points, bucket size, the first and last sample, the
  time zone, and "no data before …" when the history is shorter than the range. (#145)
- **Export CSV/JSON exports the range on screen,** including a custom range;
  `GET /api/admin/metrics/export` accepts `start` and `end`. (#145)

## [0.5.6] — 2026-10-17

Hotfix: a force above the battery's rated power keeps its direction.

### Fixed

- **A Force Charge above the battery's rated power no longer discharges it (and a Force Discharge
  above it no longer charges).** The request went to the franklinwh-modbus library unlimited, and
  that library's own limit (0.9.5) returns the rating with the opposite sign, so the battery ran
  the other way at full power. The bridge now limits the power to the rating itself, keeping the
  direction, and the result says when it did. Percentages are kept to 0–100. Applies to Battery
  Control, the battery command and scheduled forces. (#213)

## [0.5.5] — 2026-10-17

Hotfix: a schedule's Off now means off for smart circuits and the off-grid action.

### Fixed

- **A schedule set to turn a smart circuit Off no longer turns it On, and "reconnect to the grid"
  no longer takes the site off-grid.** The schedule form saved the choice as the text "false", which
  the scheduler read as on. On/Off is now read strictly and saved as true/false; a value that is
  neither is refused, with nothing sent to the gateway. Schedules saved before this release are read
  correctly without re-saving. **If you have a schedule with a smart-circuit or off-grid action,
  check what it did.** (#188)

## [0.5.4] — 2026-10-17

Hotfix: a Home Assistant sensor that is down no longer satisfies a schedule condition.

### Fixed

- **A Home Assistant sensor that is unavailable or unknown no longer counts as 0 in schedule
  conditions.** A condition such as *price < 10* was true while the price sensor was down, so a
  schedule could start a force charge or discharge. Such a sensor now has no reading, and every
  condition that uses it is false, as for a sensor that doesn't exist. (#167)

## [0.5.3] — 2026-10-17

The bridge no longer loses the aGate when it misses a few reads, and a new Link & load card shows why a link is slow.

### Added

- **Link & load diagnostics.** A *Link & load* card on Health, `GET /api/diagnostics/link` and
  `franklinwh-direct-connect-bridge ping [HOST]` show:
  - a timed ping and a timed connection to the aGate's Direct Connect port;
  - how many connections this bridge holds to the aGate: Direct Connect :9000, and the aGate
    Modbus TCP Server :502 used by this bridge's Modbus client;
  - the bridge's own CPU, memory, threads and open files.

  Read-only: the aGate Modbus TCP Server is counted, never opened. (#123)

### Fixed

- **The bridge no longer sweeps your whole network every time the aGate is slow to answer.**
  It searched all 254 addresses after every failed poll, once a minute while the aGate struggled,
  adding load exactly when the aGate could least take it. It now searches only after three failed
  polls **and** when the aGate's known address answers neither ping nor its port. It backs off from
  5 minutes to 60 while the aGate stays away.
- **The search no longer probes the aGate Modbus TCP Server (:502),** or port 502 on every other
  device on your network. It looks for Direct Connect (:9000) only. (#123)
- **"aGate moved" is announced only when the address actually changed.** (#123)

## [0.5.2] — 2026-10-16

Hotfix: turning a schedule on or off no longer wipes its settings.

### Fixed

- **Turning a schedule on or off no longer wipes its settings.** The on/off switch saved only a few
  fields and the rest were reset to defaults: the trigger type and windows, calendar days and months,
  exit conditions, hold time, priority, *If busy*, *restore on exit* and *all gateways*. Saving from
  the edit form likewise lost *restore on exit* and *all gateways*. A save now changes only what it
  sends. **If you switched a schedule on or off before this release, check its settings.** (#157)

## [0.5.1] — 2026-10-16

Home Assistant clean-up: a real Unpublish, network diagnostics, and a device page like the Modbus Bridge's.

### Added

- **Unpublish that stays unpublished.** *Clear HA* is now **Unpublish**. It turns publishing off for the
  selected gateway (kept across restarts), removes everything the bridge published for it (entities of
  every group, state and availability), checks the broker afterwards and tells you how many topics it
  removed. Before you confirm, it shows how many it will remove. *Republish* turns publishing back on.
  Other gateways and other FranklinWH software are not touched. (#119)
- **aGate network state in Home Assistant**, on the device's Diagnostic card:
  - network in use and networks available;
  - write safety and fallback;
  - Wi-Fi and 4G signal;
  - each interface's link;
  - cloud connection and endpoint.

  Read every 10 minutes, real gateways only. No MAC or IP addresses, Wi-Fi name or credentials are
  published. (#134)

### Changed

- **The HA Device info reads like the Modbus Bridge's:** the manufacturer is *FranklinWH Technologies
  Co., Ltd*, the model is the aGate's actual model (*aGate (mock)* for mocks), *Firmware* is the bridge
  version and *Hardware* is the aGate firmware. The device name, its identifiers and every entity are
  unchanged. (#140)
- **Diagnostic sensors are on the Diagnostic card:** latency, run status and ambient temperature, as
  on the Modbus Bridge. (#121)

### Fixed

- **A gateway with publishing off no longer appears in Home Assistant.** Mocks, which start with
  publishing off, were published anyway within one poll. The setup wizard's *Publish to Home
  Assistant? Yes* now turns publishing on for the gateways it added. (#98)
  **On update:** a gateway whose publishing is off has its leftover entities removed from Home
  Assistant when it starts. Its device disappears instead of sitting *unavailable*. Turn publishing
  on (Republish) to bring it back.

## [0.5.0] — 2026-10-16

Poller: editing a gateway keeps it running.

### Fixed

- **Editing a gateway no longer stops it for good.** Changing a gateway in Settings (for example turning
  *Publish to Home Assistant* on) restarts its poller. If the old poller was still finishing a read,
  the restart was refused and never retried. The gateway stopped updating and its Home Assistant
  entities went *unavailable* until the add-on was restarted. The restart now waits for the old
  poller to finish, and never runs two at once. (#82)

## [0.4.10] — 2026-10-16

Hotfix: history is recorded again on add-on installs.

### Fixed

- **Power History and the other charts fill again on add-on installs.** With MQTT publishing on, the add-on
  stopped recording history, assuming Home Assistant's recorder would keep it. But the bridge's own
  charts (dashboard Power History, Analytics, costs) read only the bridge's history, so they went empty.
  This hit every new add-on install since 0.3.3. History is now recorded unless you set
  `metrics_enabled: false`. The gap from before the update cannot be filled in. (#136)

## [0.4.9] — 2026-10-16

No more false worker failures in the log and audit trail.

### Fixed

- **No more false "worker_failed" entries.** The VPP monitor, the cloud-status check and the dispatch
  watchdog were reported as failed every few minutes, filling the audit trail and the log with errors,
  although nothing was wrong. They now report that they are alive. When one has nothing to do, it says
  *paused* with the reason (for example *no cloud credentials*, or *no force active*) instead of going
  quiet. A worker that really stops is still reported. (#93)

## [0.4.8] — 2026-10-16

Clearer Modbus labels.

### Changed

- **"Modbus" is always qualified in the UI.** The aGate's listener is *aGate Modbus TCP Server :502*.
  This bridge's own optional connection to it is *Modbus client (this bridge)*. The old labels
  ("Modbus :502", "Use Modbus from this bridge") made the bridge's switch read like a setting that
  turns off the aGate's Modbus service. Nothing changes in behaviour.

## [0.4.7] — 2026-10-16

Tidier numbers in Home Assistant, and no false "Connection Lost" at start-up.

### Fixed

- **State of Charge shows one decimal in Home Assistant**, not six (99.8 %, not 99.789474 %). Power
  shows whole watts, daily energy two decimals and temperature one. History keeps full precision.
  (#114)
- **"Connection Lost" no longer flashes after one slow answer.** Just after the add-on starts, the
  first page updates wait on a fresh reading from the aGate and can take longer than the page waits.
  The banner now needs two failures in a row. (#113)

## [0.4.6] — 2026-10-16

Security hotfix.

### Security

- **Taking the site off-grid always needs a confirmation.** One API route could switch the site off-grid
  or back without the confirmation the Off-grid control requires. It now requires it too.

## [0.4.5] — 2026-10-16

Smart Circuit switches in Home Assistant show their state.

### Fixed

- **Smart Circuit switches in Home Assistant show on or off.** They always read *unknown*: the bridge
  accepted on/off commands but never published the circuits' state. Each poll now reads it in the same
  session (one extra read, no extra login). (C1 in docs/MQTT_CONTROLS_PLAN.md, #96)

## [0.4.4] — 2026-10-16

The add-on keeps working with Home Assistant after it is updated.

### Fixed

- **The add-on keeps its link to Home Assistant after an update.** Home Assistant gives each updated
  add-on a new access token, but the bridge kept the one from its first start. After any update, the
  setup checks, Home Assistant entities in schedules, Home Assistant actions and the notification pickers
  failed with *"token rejected"*. The add-on now picks up the new token at start. Home Assistant
  instances you added yourself are not touched. (#99)

## [0.4.3] — 2026-10-16

Eight Home Assistant sensors that were always "Unknown" now show values.

### Fixed

- **Eight Home Assistant sensors show values instead of "Unknown".** These are the five daily totals (solar,
  grid import, grid export, battery charged and discharged), home load today, ambient temperature, and
  battery state. They read field names the bridge never published, so they stayed unknown on every
  install, real gateway or mock. Nothing about the entities changes: same names, same ids, same history.
  The three smart-circuit switches still show unknown. Their state needs a reading the poll doesn't make
  yet, which is tracked separately. (#96)

## [0.4.2] — 2026-10-16

The setup checks at the end of the wizard (and in Settings → Setup) report what is true.

### Fixed

- **"Bridge entities in Home Assistant" counts the right entities.** Since 0.4.0 it reported
  *"0 entities — plus N left over from removed gateways"* for a working install, and advised deleting live
  devices. It recognised entities by their name, which 0.4.0 changed. It now asks Home Assistant
  which entities belong to this bridge's devices. It also no longer counts other FranklinWH
  integrations' entities as this bridge's leftovers. (#83)
- **"MQTT broker connected" no longer fails when nothing is publishing yet.** It read only the first
  gateway's connection. With no gateway it always said *Not connected* and **Check again** could
  not change it. With a stopped first gateway it said the same while others were publishing.
  It now reports the gateways that publish. Before any gateway publishes it says *No gateway
  publishing yet*, which is not a failure. (#84)

## [0.4.1] — 2026-10-16

Hotfix: a fresh Home Assistant add-on install could not add any gateway, so setup could not finish.
It affected any add-on with MQTT publishing on and `metrics_enabled` unset, which has been the
default for new installs since 0.3.3. Docker and standalone installs were not affected.

### Fixed

- **A fresh add-on install can add a gateway again.** Since 0.3.3 the add-on publishes over MQTT by default,
  and with MQTT on the bridge turned its local database off. That database also holds the gateway list,
  so adding a gateway, real or mock, failed with *"metrics store is disabled; gateway roster needs it"*
  and setup could not finish. The database now always opens. `metrics_enabled` decides only whether
  power history is recorded, so an add-on that publishes to Home Assistant still leaves history to HA's
  recorder. If you set `metrics_enabled: true` as a workaround, you can leave it or remove it. (#81)

## [0.4.0] — 2026-10-15

Each gateway is now its own Home Assistant device, named after its serial — ten gateways
are ten distinguishable devices instead of ten identical ones. "Set up" opens the wizard.

### Changed

- **Each gateway is its own Home Assistant device, named after its serial.** The device was
  the fixed string "FranklinWH aGate (Local Bridge)", so ten gateways produced ten devices
  with the same name and the only way to tell them apart was to open each one. It now reads
  **FranklinWH Direct 24170091** — the last 8 characters of that gateway's serial. The
  device `identifiers` are untouched, so this is a rename, not a new device: entities,
  their ids and their history all survive. Entities published by earlier versions are still
  recognised as ours, so the orphan purge does not walk past its own leftovers.

### Fixed

- **"Set up" opens the wizard.** The dashboard banner jumped to Settings → Setup — the same
  information as a checklist, which is not what a button labelled *Set up* promises.
  Settings → Setup also gains a **Run the wizard** button, and the wizard can be reopened
  at any time: its state only governs whether it appears *unasked*.

## [0.3.3] — 2026-10-15

The add-on publishes to Home Assistant out of the box, like its sibling bridges; turning
publishing on takes effect immediately; notification targets are chosen from a real picker;
and the Guide links to the published documentation instead of showing a 404 body.

### Changed

- **The add-on publishes to Home Assistant out of the box.** `mqtt_enabled` now defaults
  to **true** for new installs: in the add-on the Supervisor supplies the broker, so
  publishing works without configuration — and an add-on whose entities never appear reads
  as broken. Existing installs keep whatever they have.

### Fixed

- **Turning publishing on takes effect immediately.** It said "restart the add-on", because
  enabling replaced the settings object while every running poller held the old one. The
  live object is mutated instead, and the poller's existing retry tick connects within the
  minute.

- **The broker is configured even while publishing is off.** Auto-configuration required
  `mqtt_enabled`, so flipping the switch found no broker set and the user had to go looking
  for one the Supervisor could have named all along.

### Added

- **Picking a notification target is a picker, not a search of 3804 entities.** Discover
  now asks the **chosen** Home Assistant instance rather than all of them — one bridge can
  read several, and a notification goes to exactly one. Each target shows Home Assistant's
  own friendly name (and fills the alias from it), when it was **last seen**, and whether
  it is a **duplicate** of another: HA re-registers a companion app as `notify.x_2` beside
  `notify.x` and gives no hint which is live, so last-seen — the only evidence there is —
  is shown instead of left to be hunted for.

- **A Home Assistant instance can be disabled without deleting it.** Its devices stop being
  offered and stop receiving, while their aliases and delivery history survive — for a
  holiday, a moved server, or a token that needs replacing. A device on a disabled instance
  says so rather than looking enabled and silently delivering nothing, and the delivery log
  records those as *skipped*, not *failed*: nothing went wrong, it was switched off.

- The add-on's own Home Assistant now reads as **"This Home Assistant (Supervisor)"** with
  an *auto-detected* badge, instead of showing `http://supervisor/core`.

### Fixed

- **The Guide no longer shows `{"detail":"Not Found"}`.** The documentation site is built
  from the sibling library checkout into `docs_site/`, which is gitignored — so the Home
  Assistant add-on, built from the repository, had no site to serve and the Guide panel
  rendered FastAPI's 404 body as the page. The bridge now reports whether the docs are
  bundled, and the panel links to the published documentation when they are not.

- **The add-device dialog no longer discards a half-filled form** on a click outside it —
  the same fix as the schedule editor.

## [0.3.2] — 2026-10-15

Mock gateways can be created again, and setup now ends on Home Assistant: four live checks
with their own remedies, and a plain yes/no about publishing.

### Fixed

- **Adding a mock gateway no longer fails with "Internal Server Error".** The Home
  Assistant add-on installs `franklinwh-direct-connect-api` from PyPI, which served 0.4.0 —
  a version without the emulator's `tz_offset_hours` parameter — so creating a mock raised
  `TypeError` and left a half-built roster row behind. The library is now pinned to
  **>=0.5** (released for this), and `mockgw` degrades to the seeded clock instead of
  failing if it ever meets an older one again.

### Added

- **The setup wizard ends on Home Assistant, with live checks and one question.** Four
  things decide whether this bridge shows up in Home Assistant, they fail independently,
  and each remedy is in a different place — so they are reported as four lines, not one
  verdict: our broker connection, our link *into* Home Assistant, Home Assistant's own MQTT
  integration, and whether the entities actually arrived (including ones left over from
  gateways that no longer exist, which nobody finds on their own). "Could not be checked"
  is a third state, shown as such rather than as a failure. Publishing is then a plain
  **Yes/No** — "No" changes nothing at all.

- **Discover says where its subnet came from**, and takes several. A prefilled value with
  no provenance cannot be told apart from a guess, and one of the sources *is* a guess:
  the box now reads "from the Home Assistant host network", "from a gateway you already
  have", or "a common default — check it matches your network". Comma-separated subnets are
  accepted, with a note that an aGate on a VPN, Tailscale or another VLAN needs its own
  network typed in — this bridge can only sweep what it can reach.

## [0.3.1] — 2026-10-15

Everything a first add-on install runs into: the dashboard now comes to life on its own,
Discover looks at the right network, the add-on configures what the Supervisor already
knows, and no dialog throws your work away.

### Fixed

- **The schedule editor no longer throws your work away.** Clicking outside it closed the
  dialog instantly — minutes of conditions, windows and HA actions gone, with no warning
  and no undo. The backdrop no longer closes it at all, and Cancel or Escape asks first
  whenever anything has changed (dirtiness is measured against a snapshot of the form as
  opened, not a flag someone has to remember to set).

- **Confirmation dialogs are the app's, not the browser's.** Five native `confirm()` boxes
  were still in use — unstyled white browser chrome in a dark UI — including the one that
  appears when saving a schedule that is running. They now use the themed dialog, and each
  one says what will actually happen.

- **The dashboard comes to life when a gateway appears.** Selecting a gateway has to
  REFETCH, and `loadGateways()` only assigned the id — so on a fresh install the first
  gateway was selected silently and the dashboard sat on its empty state until something
  else happened to poll. Picking the same gateway from the switcher worked, which is
  exactly the difference. The roster is also polled every 10s while there is no gateway
  (120s once there is one), instead of leaving a two-minute gap on the one screen that has
  nothing to show.

- **No more blank gateway row.** With nothing configured the roster invented a row from the
  unconfigured placeholder — no name, no host, disabled — which reads as a *broken* gateway
  rather than as "none yet". An empty roster is the honest answer. Creating a real gateway
  with no host is now refused outright (mocks are exempt; theirs is assigned when the
  emulator starts).

- **Discover scans the right network in the add-on.** It offered `172.30.33.0/24` — the
  Supervisor's internal docker network, where an aGate can never be — because the subnet
  was derived from the container's own interfaces. It now asks the Supervisor for the
  HOST's LAN, filters out docker ranges, and falls back to `192.168.0.0/24`.

### Added

- **The PV array size can come from the gateway.** The aGate reports it (1903 `solar_pv`),
  so the solar forecast's kWp no longer has to be typed from memory. Offered, never
  applied: a deliberately different number — a shaded array, a clipped inverter — is a real
  answer and is not overwritten, and the hint only appears when the two differ. "Could not
  read the gateway" stays distinct from "no solar".

- **The add-on configures what the Supervisor already knows.** It registers the Home
  Assistant it is installed in as an instance automatically (read-only, via the Supervisor
  token — no long-lived token to create, no URL to paste), only when no instance exists, so
  a user's own instances are never touched. For MQTT it goes one step less far on purpose:
  the broker is **offered** on the MQTT tab with a one-click adopt, because turning
  publishing on creates entities in the user's Home Assistant and that is a decision, not a
  startup side effect.

## [0.3.0] — 2026-10-15

The Home Assistant add-on works properly: the panel renders under ingress, the add-on has
its own icon, and setup asks where the site is. Battery dispatch is now gated on a Modbus
path that has been confirmed rather than merely configured.

### Fixed

- **The Home Assistant add-on panel renders properly.** Every asset and API call in the UI
  is relative and resolves against `<base href>`, which was hardcoded to `/` — so under
  ingress (`/api/hassio_ingress/<token>/`) they all resolved to the root of the Home
  Assistant host, outside ingress, and 404ed. The panel came up as unstyled HTML with
  oversized raw SVGs; the add-on log showed `GET /` and then not a single `/static/…`
  request. The base path is now read per request from the Supervisor's `X-Ingress-Path`
  header (the token rotates, so it can never be cached), and the standalone install is
  unchanged.

- **The add-on has its own icon, and a description that is not clipped.** It was showing
  the Supervisor's generic puzzle piece, and the store cut the description mid-phrase at
  "…over the Direct Connect". `icon.png` (128×128) and `logo.png` (250×150) are generated
  by `tools/make_addon_icons.py` from the same mark as the web UI's favicon.

- **The setup wizard no longer opens on a bridge that is already working.** Adding the
  site-timezone step as required made "something required is missing" true on every
  existing install, and that was what decided whether to prompt — so installs that had been
  running for weeks were offered first-run setup. The rule is now what the wizard always
  meant: it prompts only when **no real gateway is configured**. Completeness is still
  reported on Settings → Setup, where the user went looking for it.

### Added

- **Battery dispatch is gated on a CONFIRMED Modbus path, in four states.** `not_configured`
  / `unreachable` / `no_sunspec` / `ready`, because the remedy differs in each case and a
  single "unavailable" sends people to the network when the gateway's own SunSpec setting
  is what is off. Confirmation is a SunSpec read that returns — a socket that opens is not a
  dispatch path. The **API refuses** a force unless the state is `ready` (the UI disabling
  the buttons is not the gate), while **Release is never blocked**: refusing to stop a
  dispatch because the path looks unhealthy is the wrong way round. The Control tab now
  names the state and the fix instead of greying out.

- **The setup wizard offers the FranklinWH app account, optionally, and says why.** It is
  checked by SIGNING IN and stored only if that works — an unverified password means
  discovering months later that a reserve-SoC write has been failing. The step states what
  an account actually adds (the reserve SoC, which has no proven local write; naming a VPP
  dispatch the local channel reports as plain charging; cross-checking a grid-limit write),
  that credentials are stored in plain text in the bridge's settings file, and that
  skipping is fine.

- **A mock gateway no longer publishes to Home Assistant by default.** The Settings UI
  already sent `publish_ha: false` for mocks; the setup wizard did not, and the API
  defaulted to true — so three mock gateways created on a live install published three fake
  FranklinWH devices (63 entities, energy sensors included) to the owner's Home Assistant.
  The default is now decided server-side from `is_mock`, which fixes every caller. Passing
  `publish_ha: true` explicitly still works.

- **The gateway switcher shows each gateway's operating mode and battery direction.**
  SELF / TOU / EMGY, and an up or down arrow for charging or discharging, read from the
  same run-status enum as the top-bar pill. On a multi-gateway site the switcher is where
  you choose between gateways, so it is where the difference has to be visible. Unknown
  shows nothing — no reading is not "idle".

- **The wizard's last step reports every gateway, not one.** Solar, generator and backup
  wiring are per-gateway facts — one aGate can have 6.6 kWp of PV and another none — and a
  single profile at the end of setup silently claimed they were alike. Each gateway now gets
  its own card, with its solar stated plainly (including "No solar reported").

### Changed

- **The sidebar says "Direct Connect", not "Local Bridge".** The project was renamed; the
  dashboard's own name badge and the Network topology diagram were still on the old one.
  The Home Assistant device name is deliberately NOT renamed — it is identity, not a label
  (see `publish/entities.py`), and changing it would orphan every discovered entity.

### Documentation

- **`docs/HA_HISTORY.md` — keeping your Home Assistant history.** What is possible when you
  switch to this bridge or reinstall it: keep the entity id (recommended), start clean
  (also recommended), or merge series by hand (**discouraged**, with the reasons and the
  third-party tools named but not endorsed). Includes the four things that must match
  before any two series may be joined — the one that catches people is a *daily* counter
  against a *lifetime* one, which matching units will not reveal.

- **INSTALL.md now warns about reinstalling.** An upgrade keeps your Home Assistant
  entities; a remove-and-reinstall can leave Home Assistant holding the old entity id and
  give the newly discovered one a `_2` suffix, which restarts its history. The remedy —
  free the old id, rename the new entity to it, and Home Assistant carries history and
  long-term statistics across the rename — is written out, with the units/`state_class`
  caveat and the Developer Tools → Statistics fix for a jumped total.

### Added

- **The setup wizard asks where the site is, and every gateway uses that one zone.** Nothing
  on the Direct Connect channel supplies a timezone — the aGate reports an OFFSET and leaves
  `timezoneStr` empty — so it is asked, defaulting to the browser's zone. Mock gateways are
  started on it (the bridge owns their clock, so there the rule is enforced literally); a real
  gateway whose clock disagrees is **named** in the wizard's timezone step rather than
  silently corrected, because there is no verified write for the aGate's clock.

### Fixed

- **A gateway with a wrong clock no longer kills every scheduler tick.** The site offset is
  derived from the aGate's wall-clock minus UTC; a gateway answering with a stale date made
  that 571 days, `datetime.timezone()` refuses anything past ±24 h, and the exception took out
  the tick that was supposed to run the schedule. Offsets outside the real range (UTC-12:00 to
  UTC+14:00) are now refused — falling back to the gateway's reported base offset, or to
  "could not be established", which callers already handle.

- **The wizard builds the site you described.** Declaring 3 aGates created exactly one mock,
  every mock was called "Mock aGate" so the switcher could not tell them apart, and finishing
  left the UI on *Site · All Gateways*, where the per-gateway tabs (Battery, Device, Grid &
  Inverter) error against an empty host. It now creates one numbered mock per declared aGate,
  each with the declared aPower count, and selects a real gateway when it finishes.

- **A mock gateway can answer the grid and clock reads.** The emulator had no 1701
  `install_profile` or live 1201 `time_location`, so Grid & Inverter reported the gateway
  unreachable against a mock that was plainly online, and the site clock came from the
  reference capture's date. Both are now synthesised
  (`franklinwh-direct-connect-api`), with `fhpRatePower`/`genRatePower` left at 0 to mirror
  the real firmware.

- **Battery dispatch over the Modbus Bridge REST API now authenticates.** It never had: the
  Modbus Bridge requires a session with the `control` capability and we sent nothing, so this
  path could not have worked against any secured install — while reporting itself
  **available**, because availability was probed with an unauthenticated `/api/health` that a
  secured bridge answers `200`. New `modbus_bridge_username` / `modbus_bridge_password`
  settings (also in the add-on options), a cookie session that re-authenticates once on 401,
  and availability measured on **authorised access**. Four states are reported distinctly —
  `unreachable`, `unauthenticated`, `forbidden`, `ready` — because a `viewer` account signs in
  happily and still cannot dispatch, and no connectivity error would ever point at that
  remedy. (#56)

- **A simulated island and a real outage are no longer the same badge.** The top bar now
  reads **OFF-GRID · SIMULATED** when the island was requested (`1723 offgridSet = 1`) and
  **OFF-GRID · OUTAGE** when it was not — the same electrical state, completely different
  news. Unknown stays plain **OFF-GRID** rather than guessing. (#45)
- **Off-grid is detected again.** The bridge reported on-grid throughout a real island on
  2026-10-15: it decided from `1301 run_status in (5,6,7)` alone, and on this firmware that
  field never carries the off-grid codes. It now uses every signal — `1723 offgridState`
  (primary), `dspRunstatus`, `main_sw[0]` and the `1707` main relays — and reports **which**
  fired, plus whether they disagree. `1709 gridRelayOpen` is no longer consulted: it read 0
  for the whole island. (#45)

- **Schedules and tariff windows are evaluated on the site's clock, not the container's.**
  `docs/TIMEZONES.md` has always said a schedule rule is authored in gateway wall-clock; the
  scheduler used naive container-local time. Standalone Docker hid it by mounting
  `/etc/localtime`, so the two clocks agreed — but as a Home Assistant add-on nothing sets a
  timezone, and a gateway can sit in a different zone from the host in any case. Affects cron
  windows and `tariff.demand/bonus/charge_window_active`, which gate dispatch. (#41)

- **Modbus reachability is no longer reported as "Down" when it was never probed.** Two
  reachability paths opened TCP to the aGate's `:502` with no disable guard, so loading the
  Network tab made "Modbus is off" untrue; both now honour the switch. `None` means *not
  probed* and renders as **Not probed** across the dashboard, health, network and control
  views, instead of asserting the port is enabled and unreachable. (#30, #32, #34)
- **A clean clone can be built again.** `docker build .` failed at `COPY wheels/` for
  anyone who cloned the repository, including the Home Assistant add-on builder running on
  the user's own host, because that directory only existed on a developer's machine. The
  Direct Connect API library now resolves from PyPI like any other dependency, with no
  sibling checkouts. (#37)
- **An accepted reserve shows immediately.** The aGate takes ~8s to reflect a cloud reserve
  write, and until it did the row behind the modal still showed the old value beside a
  success message. (#39)

### Changed

- **A Mosquitto add-on installed after this one is now found.** MQTT auto-configuration ran
  once at startup; the poller's existing retry then reconnected to the same unset broker for
  ever. It re-asks the Supervisor before each attempt, so the broker is picked up without a
  restart. User-supplied credentials are still never overwritten. (FEAT-HA-ADDON-PARITY)
- **The add-on container takes the host's timezone**, read from the Supervisor in Python.
  Nothing set one before, so it ran UTC and every log line and rendered local time was hours
  out. Schedules are unaffected either way — since #41 those follow the aGate's clock.
  (FEAT-HA-ADDON-PARITY)

- Dependencies come from `pyproject.toml` alone. The Dockerfile used to repeat the list and
  install with `--no-deps`, so an end-user image could silently differ from a developer's. (#37)
- `README.md` separates **Run it yourself** from **Develop**. The old instructions required a
  sibling checkout and recommended `docker compose up --build`, which does nothing here. (#37)

### Added

- **First-run setup.** A dashboard prompt when required steps are outstanding, and a
  **Settings → Setup** view that is re-runnable by design: each step reports whether it is
  already satisfied, so a second pass is a review rather than a blank form. The install
  profile is **read from the gateway** and each field is marked `READ` or `SET BY YOU`, so a
  default is never presented as a measurement — and anything derived can be contradicted.
  Optional steps say "you can set this up later" and skipping disables nothing.
  (FEAT-SETUP-WIZARD)

- **A copy-paste Home Assistant dashboard card**, on Home Assistant → Published by bridge.
  Grouped or single layout, diagnostics opt-in, with a Copy button that falls back to
  selecting the text when `navigator.clipboard` is unavailable — which it is on HA ingress,
  because that is plain `http`. Shape agreed with the other FranklinWH integrations: plain
  core cards, no custom cards, no theme line. **Entity ids are never guessed**: each one is
  confirmed against Home Assistant, a `_2` collision suffix is followed, and anything that
  cannot be found is listed rather than written into the YAML. (FEAT-HA-DASHBOARD-YAML)

- `tools/dev.sh` builds the image, restarts the container and **proves** the container is
  running the current working tree, exiting non-zero if not. `GET /api/version` reports the
  same stamp as `source_sha`. A fix had been "verified" against a container that was never
  rebuilt. (#35)
- Working rules in `CLAUDE.md`, agreed across the FranklinWH repositories: evidence and
  citation, claims from other sessions, publishable evidence, testing, verification of
  critical changes, and defect tracking. With `tools/pii_check.py`, severity and nature
  labels, and a pull-request template. (#29, #31, #33)
- `test/mqtt-shared/run.sh` fails loudly when a harness container does not stay up. One had
  been crash-looping unnoticed for eight days. (#38)
- This file, and a rule in `CLAUDE.md` requiring it to be updated in the same commit as any
  user-facing change. The project had no changelog at all until now.
