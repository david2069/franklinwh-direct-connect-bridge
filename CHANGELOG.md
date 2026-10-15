# Changelog

All notable changes to `franklinwh-direct-connect-bridge` are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/); this project uses
[Semantic Versioning](https://semver.org/).

> **This file starts on 2026-10-15.** It did not exist before then, so earlier releases are
> not reconstructed here — inventing entries from git history would put unverified claims in
> a public file. `git log` and the merged pull requests remain the record for anything
> before this point. Everything from 2026-10-14 onward is recorded because it is first-hand.

## [Unreleased]

### Fixed

- **The inverter's rated power is no longer assumed to be 5 kW.** When Modbus could not be
  read, `battery_control` returned a hardcoded 5 kW that was indistinguishable from a real
  reading — and a force command given as a **percentage** is a percentage of that number,
  so on an aPower 2 (10 kW) every dispatch was half what was asked for, silently. The
  rating now comes from Modbus SunSpec 702, else the **aPower model** you record in System
  Setup times how many are reporting, else your own `battery_max_power_kw` constant, else
  5 kW **labelled as an assumption** with the remedy in the text. A percentage is refused
  outright when the rating is unknown; an explicit wattage still works.

- **New: the aPower model in Settings → System Setup.** The local API exposes no model
  register, so it is asked rather than derived — and it is what turns that assumption into
  a datasheet value.

### Changed

- **One Home Assistant device per integration per aGate.** The device identifier now names
  the integration — `franklinwh_direct_<serial>` — so this bridge can never merge with the
  Modbus Bridge or FWHAI into a single device. (That merge is real: two sibling
  integrations both published `franklinwh_<SERIAL>`, Home Assistant combined them into one
  device of 155 entities, their discovery configs overwrote each other and a mode command
  ran on both.) Entity ids are untouched, so this is a device rename and your history stays
  where it is.

- **The identity namespace can be switched to `fwh_dc`** (Settings → MQTT, confirm-gated).
  That one DOES re-create entities under new ids — the old ones keep your history — so it
  is an explicit choice, never automatic, and the API states the cost before you take it.

### Added

- **Browse the broker, read-only** (MQTT tab). Watch a topic filter for a few seconds and
  see what arrives, retained messages marked as such — the question "is anything actually
  on that topic" was otherwise unanswerable from inside the add-on without installing a
  separate MQTT client. It never publishes; `#` on its own is refused, because on a shared
  broker that is every message from every integration; and the window, result count and
  payload size are all capped.

### Fixed

- **Removing or disabling a gateway now takes its Home Assistant entities with it.** The
  poller stopped the publisher without clearing discovery, and a retained config outlives
  the bridge — so a deleted gateway's entities stayed in Home Assistant for ever, while the
  UI claimed disabling unpublished them. A normal restart still leaves entities alone, which
  is the case that must never clear them.

- **Commands are subscribed on the topic root they are advertised on.** The publisher built
  its subscription from `mqtt_prefix` while the discovery configs used the namespace root.
  Identical today, divergent after a namespace switch — and the failure would have been
  silent: every command accepted by Home Assistant and received by nobody.

Nothing yet.

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
