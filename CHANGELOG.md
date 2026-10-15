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

- **The sidebar says "Direct Connect", not "Local Bridge".** The project was renamed; the
  dashboard's own name badge and the Network topology diagram were still on the old one.
  The Home Assistant device name is deliberately NOT renamed — it is identity, not a label
  (see `publish/entities.py`), and changing it would orphan every discovered entity.

### Documentation

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
