# Coverage plan — making these failures impossible to miss

Companion to [`BRIDGE_BASELINE.md`](BRIDGE_BASELINE.md). The baseline says what a bridge
must *do*; this says how we *find out* when it stops doing it. Requirement numbers below
are the baseline's `BR-n`.

## The problem this has to solve

Every failure found on 2026-10-09 had already happened, silently, for weeks:

* 21 orphaned Home Assistant discovery configs — a duplicate device for the real gateway,
  published under the `agate` fallback node. Nothing raised, nothing logged, nobody knew.
* `sw_version` reporting `0.1.0` while the package was `0.2.0`, so every HA device showed
  the wrong version. No event, no error.
* A scheduled occurrence burned by a transient failure writes **one** log line and moves on.
* `smoke` had been failing in CI since the repo went public.

**So notifications alone cannot cover this.** Notifications are event-driven, and these
are *standing conditions* — nothing happens, and that is the bug. Worse, every trigger the
bridge has today (`offline`, `off_grid`, `dispatch`, `soc_low`, `soc_full`) is about the
**battery**. Not one is about the bridge's own health.

Coverage therefore needs three layers, not one:

| Layer | Answers | Good for |
| --- | --- | --- |
| **Outcome reporting** | "this call just went wrong" | events, at the moment they happen |
| **Periodic self-check** | "something is wrong and has been for a while" | standing conditions that raise nothing |
| **Surfacing** | "a human, or an automation, actually saw it" | both |

## Layer 1 · Outcome reporting (events)

Already built in `resilience.py`; wiring in progress. Every boundary call yields an
`Outcome`, and `_report()` is the single place severity is decided:

| Verdict | Log level | Audit | Notify |
| --- | --- | --- | --- |
| `OK`, first attempt | debug | writes only | no |
| `OK`, after retries | **info** — "recovered after retry" | writes only | no |
| `FAILED` | **warning** | writes only | writes only |
| `UNKNOWN` | **error** — "UNKNOWN OUTCOME" | always | **always, own title** |
| `SKIPPED` | debug | no | no |

`UNKNOWN` is deliberately the loudest: it means a write may have landed and nobody knows
(BR-8). It is the one state a human must resolve, so it bypasses every throttle below.

## Layer 2 · Periodic self-check (standing conditions)

**New.** A scheduled audit — hourly, plus on startup — that actively looks for the
conditions nothing else reports. Each check returns findings of
`{id, severity, br, summary, detail, count, first_seen}`.

| Check | BR | Severity | What it catches |
| --- | --- | --- | --- |
| `orphaned_entities` | BR-23, BR-26 | warning | retained discovery configs for nodes we no longer publish. Reuses the existing dry-run scan; **reports, never purges** |
| `gateway_identity_deferred` | BR-5 | warning after 15 min | a gateway whose serial never read, so it publishes nothing |
| `mock_in_production_roster` | BR-27 | info | mock gateways registered on a non-demo instance |
| `version_drift` | BR-28 | warning | `__version__` vs `pyproject` vs `config.yaml` disagree |
| `occurrence_burned` | BR-16 | warning | a schedule window that closed without its action succeeding |
| `schedule_stalled` | BR-18 | info | a schedule stopped mid-window and never resumed |
| `poll_fail_streak` | BR-14 | warning at 3, error at 10 | consecutive failed polls per gateway |
| `mqtt_publisher_down` | BR-25 | warning after 5 min | MQTT enabled but no publisher for a live gateway |
| `foreign_producer_collision` | BR-4 | warning | another integration publishing under our device identifier |
| `writes_unavailable` | BR-33 | info | a control is exposed but its transport is unreachable |
| `dispatch_unknown_outstanding` | BR-9 | **error** | an UNKNOWN dispatch nobody has acknowledged |

Checks are pure functions over current state, so each is unit-testable without a broker,
a gateway or a clock.

## Layer 3 · Surfacing

A finding is worthless if it only exists in a JSON endpoint.

1. **App Logs** — every finding writes to the bridge's own log stream at its severity,
   tagged `source=selfcheck` and attributed to a gateway where it has one, so the Logs tab
   can filter to exactly these (BR-29).
2. **Health card** — `GET /api/health/findings` drives a card that is **always visible**,
   showing "no issues" when clean. A surface that only appears when broken is a surface
   nobody learns to look at.
3. **Notifications** — a new `bridge_health` trigger family alongside the existing
   battery ones, so this is user-configurable like everything else.
4. **Home Assistant entities** — a `problem` binary_sensor plus an issue-count sensor, so
   HA automations can act on bridge health rather than a human remembering to look. This
   is the one that makes coverage real for an unattended install.

### Notification policy — the part that decides whether this works

Over-notifying is how alerts get ignored, which fails the goal as surely as silence:

* **Notify on transition**, when a finding appears — never per tick while it persists.
* **Re-notify after 6 hours** if still outstanding, so a real problem does not fade away.
* **One daily digest** listing everything still open, or nothing if clean.
* **Clearing notifies too** — "resolved" closes the loop, so a silent recovery is not
  mistaken for an unresolved problem.
* **`UNKNOWN` outcomes ignore all of the above** and notify immediately, every time, until
  acknowledged. Safety outranks tidiness (BR-9).
* Honour the existing master switch and per-trigger enables.

## Test coverage — the plan is not done until each is proven

Detection that nobody tests is the same as no detection. Each check needs three tests:

1. **fires** — given the bad state, the finding is produced with the right severity and BR;
2. **stays quiet** — given a healthy state, nothing is produced (the false-positive guard,
   which matters most for `orphaned_entities`, where a wrong answer deletes another
   integration's entities);
3. **surfaces** — the finding reaches the log, the endpoint, and the notifier, with
   throttling applied.

Plus two regression tests for issues that already shipped silently: `version_drift` (now
covered) and `orphaned_entities` (validated against a real 467-config broker capture).

## Phasing

| Phase | Delivers | Closes |
| --- | --- | --- |
| 1 | wire `resilience.call` into the scheduler and the bridge's writes | BR-6–13, BR-16 |
| 2 | self-check engine + `GET /api/health/findings` + app-log emission | BR-14, BR-26, BR-28 |
| 3 | Health card + `bridge_health` notification family + throttling | BR-29, BR-30 |
| 4 | HA `problem` binary_sensor + issue-count sensor | unattended coverage |
| 5 | remaining checks, each with its three tests | the rest of the table |

**Phase 2 is the one that matters most**, and it is the one that would have caught every
silent failure in this list. Phase 1 only covers things that actively go wrong while
someone is watching.

## Explicitly out of scope

Not metrics-grade monitoring, not Prometheus, not an SLA. The bar is: a condition this
bridge can detect about itself should be visible without reading source or querying
SQLite, and should reach a human or an automation once — not zero times, and not hourly.
