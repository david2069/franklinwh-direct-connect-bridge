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

- Dependencies come from `pyproject.toml` alone. The Dockerfile used to repeat the list and
  install with `--no-deps`, so an end-user image could silently differ from a developer's. (#37)
- `README.md` separates **Run it yourself** from **Develop**. The old instructions required a
  sibling checkout and recommended `docker compose up --build`, which does nothing here. (#37)

### Added

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
