# Test and release policy: FranklinWH bridges

Applies to **franklinwh-direct-connect-bridge** and **franklinwh-modbus-bridge**: every change that
reaches a user as a Home Assistant add-on, a Docker image or a PyPI package.

Written 2026-10-16, after 0.3.3 and 0.4.0 of the Direct Connect bridge shipped to the add-on store
unable to add a gateway on a fresh install (#81). What went wrong:

- Three feature changes went into two releases within a day.
- No release was installed fresh on Home Assistant OS before it shipped.
- The roster tests stubbed the very function that failed (`db.get_store`), so the suite passed.
- Nothing recorded what the UI showed, what the browser logged or what the add-on logged, so
  there was no trace to compare against when users reported the failure.

The install and update lifecycle (fresh install, update, reinstall, uninstall, Docker, coexistence)
and its effect on HA devices, entities and retained MQTT topics is defined in
franklinwh-modbus-bridge `docs/install-lifecycle.md` (draft: david2069/franklinwh-modbus-bridge#141). This policy says **what must be tested and
recorded**. That document says **which lifecycle paths exist and what each must do**. The G1 matrix
below runs that document's paths.

Reviewed by the franklinwh-modbus-bridge session on 2026-10-16. Its review is folded in.

## 1. Release size

- **One release, one functional area.** Areas:
  - store/migrations
  - poller
  - MQTT/HA identity
  - MQTT/HA lifecycle and clean-up (artefacts, purge)
  - setup wizard/UI
  - HTTP API
  - Modbus
  - scheduler/dispatch
  - packaging
- **A hotfix contains the fix and nothing else.** No feature rides along with a fix.
- **A release PR contains only the version bump and the CHANGELOG section.** The changes it releases
  were merged and gated before it. A version bump touches every place the version lives, together:
  - Direct Connect: `config.yaml`, `pyproject.toml`
  - Modbus bridge: `pyproject.toml`, `__init__.py`, `addon/config.yaml`, `addon/Dockerfile` `BRIDGE_REF`, `addon/CHANGELOG.md`
- **Anything that changes how HA identifies things** (device identifiers, `unique_id`, device or entity
  naming, MQTT topics, add-on slug) is **released alone**. Its notes say exactly what users will see change.
- **Up to two releases a day** (owner, 2026-10-31; it was one). Each passes its own gates, G1
  included, and is published and merged on its own. A release that changes how HA identifies
  things is the only release that day. A hotfix for a release doesn't count toward the two.

## 2. Gates

Every change passes the gates its risk requires. A release passes all of them.

| Gate | What | Required for |
|---|---|---|
| **G0 Suite** | Full suite green **on the pinned dependency set the image uses**. Modbus bridge: `pytest -m "not hardware"` with `constraints.txt`, plus `ruff check src/ tests/`. Each fix has a regression test **seen failing without the fix**. A test must not stub the component it is testing; stub only its edges (network, device, clock). | every PR |
| **G0 Install smoke** | `.github/workflows/install-smoke.yml`, green: the two standalone installs INSTALL.md offers (Docker Compose; pip into a fresh venv), each with and without a broker. Jobs `docker-mqtt`, `docker-nomqtt`, `python-mqtt`, `python-nomqtt` run `tools/install_smoke.py`: health, a mock gateway added and polling, its discovery configs retained (with a broker), no ERROR or Traceback in the log. Follows the shared fwh-tools "install-smoke" spec (#409). | every PR (CI) |
| **G1 HAOS acceptance** | Scripted run on the HAOS test VM, with a trace (§3). | every release; any PR touching setup, store, MQTT/HA identity or lifecycle, add-on config or packaging |
| **G2 Real hardware** | Reference aGate, under §4. | device I/O, dispatch, writes, Modbus, anything "critical" in CLAUDE.md |
| **G3 Sign-off** | When G0–G2 have passed, the **agent advises the owner that the merge will happen**. It names the PRs, the order and the gate results, then merges. The owner does not merge, and can stop it. Before merging, the agent checks the PR is still open and mergeable; afterwards it checks `main` (version, CHANGELOG). A failed or skipped gate is stated in the advice; the agent does not merge past it without the owner's word. | every release |

A **failed or skipped gate is stated in the PR**. It is never left out.

**A check that passes only on retry is a failure**, and it gets an issue.

## 3. G1: HAOS acceptance run

### Environment

- HAOS `generic-aarch64` under QEMU (`~/dev/haos-qemu`, `start.sh`), current stable HAOS.
- **Record the HAOS, Core and Supervisor versions in every run.**
- Mosquitto add-on installed, and the HA MQTT integration accepted.
- HA is served on guest **:80** in HAOS 18.x; guest :8123 only redirects. Forward :80.
- **The test VM must not use host port 8123**, because the owner's HA Live (VirtualBox) listens there.
  Bridges coexisting on one VM use distinct host ports.
- Browser automation: HA 2026.10's ingress iframe is not listed in Playwright's `page.frames`. Reach
  it with `page.frame_locator("iframe").first` and wait on its content. Or drive the add-on's own
  port and screenshot the panel.

### Prove the build is the code under test

Installing from `repo#branch` builds whatever the Dockerfile builds. **Before judging a run, prove the
running code is the branch.** If you can't, the run tested something else and does not count.

- **Direct Connect bridge:** the Dockerfile builds the checked-out repository. `/api/live` must report
  the branch's version. (A source commit in `/api/version` is still to come.)
- **Modbus bridge:** a store install from `repo#branch` builds the **last release tag** (pinned
  `BRIDGE_REF`, its #140), so it does not count. Until its build provenance ships, prove the build
  with a local add-on built with `BRIDGE_REF=<commit>` plus the `Bridge started (env=ha_addon, v…)`
  log line.

### Gateways for G1

- **Mock/demo gateway**: the fresh-install wizard path.
- Some lifecycle paths need **a gateway that isn't a mock**: clean-up that skips mocks by design, and
  identity migration, which needs a real serial. Proposed for both repos: a **Modbus TCP and Direct
  Connect simulator** replaying a captured, **masked** aGate map. It gives real-gateway code paths with no
  single-client conflict. Until it exists, those paths need G2.

### Matrix (each a fresh run with its own trace)

1. **Fresh install, default options**, through the setup wizard's mock/demo path in a real browser.
2. **Update in place** from the previous release with a configured gateway: devices, entities and
   history survive with no orphans and no duplicates (see install-lifecycle.md).
3. **Reinstall keeping data** and **uninstall + purge**: the outcomes install-lifecycle.md specifies.
   Measured by the Modbus bridge session on HAOS 18.3 / Supervisor 2026.10.2, not yet verified for the
   Direct Connect bridge:
   - the Supervisor deletes `/data` on **every** uninstall, "keep data" included;
   - only the mapped `addon_config` folder survives a keep-data uninstall;
   - the slug, and so the data folder, includes a hash of the repository URL, so installing from
     another URL or branch is a new install.

   A store in `/data` therefore has no "reinstall keeping data" path. Test what the bridge actually does.
4. **Coexistence**: both bridges installed in one HA, with no clash of devices, entities or topics.
5. **Docker update in place**: the previous release's image built and run by Docker Compose with a gateway, then this one
   on the same `./data` volume. The store migrates, and the gateway and its retained topics survive with no duplicates.
   Runs on the Debian VM (`~/dev/debian-qemu-g1d`) until it is scripted in CI (#409).

### The trace (every run, kept per run)

`results/runs/<UTC stamp>_<slug>_<version>/`:

- `summary.md` / `summary.json`: versions, pass/fail per check, notes
- `screenshots/`: **every wizard screen**, the add-on page, its Configuration tab with defaults, the
  ingress panel, the dashboard after setup, and the HA device page
- `addon.log`: the add-on log **for this run only**. The Supervisor keeps an add-on's log across
  reinstalls, so filter it by the run's start time.
- `browser-console.log`: console errors/warnings and uncaught page errors (Modbus bridge: plus
  `tools/console_gate.py` output, which its CLAUDE.md requires after any JS/HTML change)
- `http-failures.log`: every request from the UI that answered ≥ 400 or failed. Requests the browser
  cancelled during navigation are not failures.
- `api/*.json`: the raw API answers the checks were judged on
- `api/inventory-before.json` / `api/inventory-after.json`: retained MQTT topics under
  `homeassistant/` and every reserved prefix (`fwh_mb`, `franklinwh`, `fwh_dc`, `franklinwh-local`,
  `fwhai`, …), plus HA's device and entity registries and states

### Pass criteria

- The wizard completes with **no error banner**.
- A gateway is added, polls, and appears in HA as one device whose entities are available. Check
  **only the run's own device**: HA keeps devices from earlier installs.
- The setup checks are all true.
- **No ERROR or Traceback** in the add-on log, **no console errors**, **no failed UI calls**.
- **Inventory diff:**
  - the run's own devices and topics match what the lifecycle path requires;
  - **everything else is byte-for-byte unchanged**. That catches a bridge touching another producer's records.
- **Every port the add-on exposes refuses unauthenticated admin calls.**

**Every check must be shown to fail on a known-bad build before it is trusted.** Run the new check
against the previous broken release, or against the fix reverted. A check that has never failed can
pass falsely. The first G1 script's "no error banner" check reported PASS on Direct Connect 0.4.0
while the banner was on screen, because its selector missed the element. Known-bad baselines:
- Direct Connect 0.4.0 (setup)
- Modbus bridge 0.2.5 (Power History above 15 kW)

**Baseline failures:**
- Running the same matrix on the previous release gives the baseline.
- A failure that is **new** compared with the baseline blocks the release.
- A failure that also exists in the baseline may be accepted only if:
  - it is listed in the PR with its open issue number, **and**
  - it is **outside the area being released**.

  Otherwise a release could accept the very defect it was meant to fix.

### Evidence that may be published

The PR body carries `summary.md` and selected screenshots **from mock/demo runs only**. Real-hardware
runs stay local; quote masked output inline. No serials, LAN IPs or site data, per CLAUDE.md.
Security findings (for example an unauthenticated port) go to a private advisory, not into a public PR.

## 4. G2: Real-aGate access

### Every test

- **Read-only by default.** Writes, mode changes and dispatch need the owner's go-ahead **in that
  session**. An approval relayed by another session does not count.
- Record which other clients were active (Direct Connect :9000 and Modbus :502) during the test.

### Modbus :502 (single client)

- **The aGate's Modbus :502 serves one client.** Never open :502 while another client is polling it.
- **Probes are clients too.** A wizard Search or Test, or the library's discovery, opens :502.
- A Direct Connect test **switches the bridge's Modbus path off before adding the real gateway**.
- **Clients sit on different hosts.** Counting sockets on one host proves nothing about the others.
  List every known client host and check each one:
  - the Mac mini (Docker)
  - HA Live (VirtualBox)
  - the QEMU test VM, which is NATed, so its connections show as the laptop's sockets
  - any other Docker host
- When :502 is needed:
  1. coordinate, and stop the other client;
  2. **verify the stop on every client host**;
  3. test;
  4. restart the other client;
  5. record the downtime.

### Writes and dispatch

- **A written plan comes first:** the register(s) or command, the expected effect, how it is reverted,
  and the hardware revert timer.
- **Measure the result, not just the acknowledgement.** Read back the commanded value **and** measure
  the effect (for example battery W against the command). "Command accepted" misses defects like
  "Force Discharge goes to 100%".
- **Restore the starting state.** Record mode and SoC before and after, and put the prior mode back.
- **Never between 17:30 and 20:00** (peak).

### Deploying to the owner's live bridges

A deploy is a **restart**. It releases active battery commands and re-fires schedules whose window is
open. Deploy per the repo's restart practice (Modbus bridge: `docs/restarts-and-shutdown.md`):
- no active command or schedule;
- outside 17:30–20:00;
- check the connect line in the log afterwards.

## 5. Shared identity rules (both bridges in one Home Assistant)

Each bridge owns its own namespace. No identifier may be produced by both.

| | Direct Connect bridge (current) | Modbus bridge (v0.2.6, as reported by that repo's session, 2026-10-16) |
|---|---|---|
| Add-on slug | `franklinwh_local_bridge` (never rename) | `franklinwh_modbus_bridge` |
| Ports | 8101 | ingress 8099; direct port off by default |
| MQTT state prefix | `franklinwh-local/<node>/…` | `fwh_mb/<short_id>/…` (legacy installs: `franklinwh/…`) |
| HA device `identifiers` | `franklinwh_<node>` (node = **full** serial, lower case) | `<prefix>_modbus_<SERIAL>`; before 0.2.4: `franklinwh_<SERIAL>` (upper case) |
| `unique_id` | `franklinwh_<node>_<key>` | `<prefix>_<short_id>_<slug>` (short_id = last 8 of the serial); legacy `franklinwh_<serial8>_<slug>` |
| Device name | `FranklinWH Direct <last 8 of serial>` | `FranklinWH Modbus <last 8 of serial>`; mocks `… (mock)` |

**Reserved prefixes:**
- **Today, in Modbus bridge code:** `fwhai`, `fwh_ai`, `fwh_lb`.
- **Pending** (install-lifecycle remediation plan, needs the owner's approval): `fwh_dc` and `franklinwh-local`, for the Direct Connect bridge.

**Known near-collision:** the Direct Connect bridge's device identifier `franklinwh_<serial>` and the
Modbus bridge's pre-0.2.4 `franklinwh_<SERIAL>` differ **only by case**. If either side ever
normalises case, the two bridges' devices merge. The `unique_id`s do not collide today: the Direct
Connect bridge uses the full serial and the Modbus bridge the last 8 characters.

HA 2026.10 does not use the published `object_id`: entity IDs are derived from the device name
(`sensor.franklinwh_direct_<serial8>_…`). **Renaming a device therefore changes the entity IDs of
new installs.**

- **Decided for the Direct Connect bridge (owner, 2026-10-16):** move to the `fwh_dc` prefix for MQTT
  topics, device identifiers and `unique_id`s, as a release of its own with a migration (#92).
  Device names and entity_ids stay.
- **Background:** `franklinwh_<serial>` is a generic prefix that more than one producer has used
  (Direct Connect, the Modbus bridge before 0.2.4, FWHAI). Each bridge should carry a bridge-specific
  prefix. Changing one is an identity change (§1): released alone, with a migration that leaves no orphans.
- Changing an identifier, a `unique_id` or the device naming is a **breaking change for HA history**.
  It needs a migration or a documented rename, and G1 matrix item 2.

## 6. Sign-off checklist (release PR)

- [ ] One functional area; the PR has only the version bump and CHANGELOG
- [ ] Every version location bumped together (Modbus bridge: add-on `version` == `BRIDGE_REF` tag == the tag being pushed)
- [ ] G0: suite count on the pinned dependency set, plus the regression tests named
- [ ] G1: `summary.md` of every matrix run pasted, with baseline differences listed
- [ ] Build proven to be the branch (§3)
- [ ] Every new check seen failing on a known-bad build
- [ ] Known failures each linked to an open issue, and outside the area released
- [ ] G2 done, or "not needed because …"
- [ ] No site data in the PR, the CHANGELOG or the commits
- [ ] Deploy to the owner's live bridges per §4, if any
- [ ] Merge advised to the owner (PRs, order, gate results); the agent merges and checks `main` afterwards (G3)
