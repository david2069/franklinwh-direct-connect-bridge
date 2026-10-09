# In-flight work — handover

**Updated:** 2026-10-09 (phase 2 complete) · **Session:** `01WCWytg6NQWQ5fPnCZiSAf5`

Written so this work survives a crashed session. If you are picking this up cold, read
§1 and §2, then §6 for the gotchas that cost time to learn. The design documents are the
source of truth; this file is only the map.

## 1 · Where things stand

### Documents — read in this order

| Doc | What it settles |
| --- | --- |
| [`RUNTIME_DESIGN.md`](RUNTIME_DESIGN.md) | **Accepted 2026-10-09.** Component model, supervision, five decisions settled in §6. The foundation everything else assumed. |
| [`BRIDGE_BASELINE.md`](BRIDGE_BASELINE.md) | 38 numbered requirements (`BR-n`) both bridges target. Honest conformance table including what we fail. |
| [`OBSERVABILITY_COVERAGE.md`](OBSERVABILITY_COVERAGE.md) | How a failure gets *noticed* — three layers, because most of these produce no event. |

The reason the design exists: fixes were being applied one discovery at a time on a runtime
that can die unobserved. The scheduler runs *inside* the gateway poll loop, `run_gateway`
has no `except`, and `/api/live` deliberately does no gateway I/O — so one exception stops
polling, metrics, MQTT and all scheduling for a gateway while the container reports healthy.

### Repositories

| Repo | State |
| --- | --- |
| `franklinwh-direct-connect-bridge` | this repo. Renamed from `franklinwh-local-bridge`; old URL redirects. |
| `franklinwh-direct-connect-api` | library. **0.4.0 published** to PyPI 2026-10-09 via trusted publishing on the `v0.4.0` tag. |
| `franklinwh-modbus-bridge` | PR #30 proposes `BRIDGE_BASELINE.md`. **Deliberately not refreshed** while runtime work is in flight. |

## 2 · Next action

`RUNTIME_DESIGN.md` is **FROZEN v1.3** — decisions settled (§7), questions closed (§10),
phase scope fixed (§8).

**Phase 0a ✅ (PR #16)** · **Phase 0b ✅ (PR #17)** — both merged. The supervisor recovers,
the zombie window is closed, aborts are confirmed rather than assumed.

**Phase 1 — built, in PR** on `feat/phase1-scheduler-worker`: the scheduler stops being a
passenger on the gateway poll loop and becomes its own worker on its own cadence, reading a
per-gateway snapshot. Copy the shape from
`franklinwh-modbus-bridge/src/franklinwh_bridge/gateway/scheduler.py` — own task, own
`_tick_s`, inner guard so a bad tick cannot kill the loop.

Done: `scheduler_worker.py` runs the tick on a fixed 15 s cadence (`scheduler_tick_s`),
registered and supervised like any other worker; the poller no longer calls it; `state_ts`
stamps each snapshot so freshness is measurable.

**Freshness guard matters here.** Decoupling created a hazard the coupled version could not
have: a scheduler outliving its poller would evaluate conditions against a snapshot that
stopped updating hours ago. A gateway whose snapshot is older than `max(90s, 3 × poll
interval)` is **skipped with a reason**, never evaluated.

Cadence is clamped to [5, 60] s. Windows are minute-resolution, so the shortest expressible
window is 60 s — the constraint belongs on the cadence, and a user cannot express an
unschedulable window at all. No per-schedule validation needed.

**Phase 1 is complete.**

## 2b · Phase 2 — complete, on `feat/phase2-occurrences`

Scope per §8 is finished. 842 tests pass. Not yet merged; the branch also carries an
unrelated batch of UI work (see §2c).

| Piece | Where | Note |
| --- | --- | --- |
| `occurrences` table (the execution queue) | `db.py` | `UNIQUE(schedule_id, occurrence_key, gateway_id)` **is** `max_instances`, enforced in the schema |
| `misfire_grace_time` | `scheduler_worker.MISFIRE_GRACE_S` | 120 s — the boundary between a late catch-up and `missed` |
| `coalesce` | `db.coalesce_occurrences` → `_claim_run` | a backlog left by downtime collapses into ONE run; older open runs close as `skipped` naming the run that absorbed them |
| Per-resource exclusivity (§6.6) | `scheduler.ACTION_RESOURCE`, `resource_for`, `resources_contend` | the starvation fix — see below |
| One-or-all targeting (BR-45) | `gateway_scope` | an all-scope rule claims **this tick's** gateway, not the one it is bound to |
| Priority + deterministic tie-break | `winner_key` | `(-priority, created_at, id)` — renaming a rule cannot change who wins |
| Symmetric entry/exit + restore (BR-50) | `capture_prior`, `_restore_prior`, `occurrences.prior_state` | opt-in via `restore_on_exit` |
| Templated notifications | `run_context` | `%run.*%` / `%schedule.*%` in the same namespace as the sensors |
| `schedule_log` split | `LOG_SEVERITY`, `LOG_CAP` | event / error / exception, **capped per class** |

### The three decisions worth not re-deriving

**Exclusivity is per resource, and an unknown action claims itself.** `force`, `set_mode`
and `reserve_soc` all claim `<gw>/battery` — they are one behaviour, and a mode change
during a force dispatch is a genuine fight. `offgrid` claims `<gw>/grid` (different
hardware), `smart_circuit` claims `<gw>/circuit:<id>` (so two circuits never contend), and
`notify` claims nothing. An **unrecognised** kind claims `<gw>/other:<kind>` rather than
defaulting to the battery: guessing wide is precisely what caused the Modbus Bridge's
starvation bug. A circuit write with no circuit named claims `circuit:*`, and those groups
are merged before a winner is picked — otherwise two rules that genuinely fight would each
win their own group and both dispatch.

**The prior state lives on the run, not in memory.** An override the bridge forgets across
a restart is an override that becomes permanent. It is captured on the **first attempt
only**: a retry would otherwise capture what the rule itself just set and "restore" the
override instead of undoing it. If the old value cannot be read, nothing is captured —
restoring to a guess looks deliberate and is worse than a visible override. Covers the
operating mode only; circuits and off-grid are not in the snapshot (`FEAT-RESTORE-CIRCUIT-OFFGRID`).

**The log cap is per class because the measurement said so.** Execution was 2.2% of rows
(9 of 405) and `gated` alone 76%. Under one shared 2000-row cap, routine chatter evicts
failures long before they age out. Budgets are now event 2000 / error 1000 / exception 500,
pruned only within the class that just grew.

## 2c · What is uncommitted

The working tree also carries UI work that is **not** phase 2 and should land separately:
dashboard card overflow + equal heights, the in-app Guide panel, the Advanced-tools gate
(Terminal + Reboot, default off), one shared nav registry driving both the sidebar and the
bottom bar, and the cog split into Theme / Navbar / Top bar.

Next: phase 3 — wire `resilience.call` into scheduler actions and bridge writes.

Then phase 2 (`occurrences`) and phase 3 (wire `resilience.call`) — that is where retry,
resume and `missed` become expressible. **Do not build those before phase 1** (§9).

## 3 · Branches and PRs

**Merged to `main` 2026-10-09** — the stack is gone, nothing is waiting:

| PR | What landed |
| --- | --- |
| #10 | package rename `franklinwh_local_bridge` → `franklinwh_direct_connect_bridge` |
| #14 | never publish discovery under the `agate` fallback node; single-source `__version__` (originally #11, auto-closed when its base branch was deleted — re-opened against `main`) |
| #12 | dry-run orphan scan + guarded purge |
| #15 | the four design documents + `resilience.py` |

In flight: `feat/phase0-worker-supervision` — see §2.

> Lesson for the next stack: merging a PR with `--delete-branch` **closes** any PR based on
> that branch rather than retargeting it, and a closed PR cannot be reopened once its base
> is gone. Retarget dependent PRs to `main` *before* merging their base.

## 4 · Known-failing requirements

From `BRIDGE_BASELINE.md`'s conformance table. These are *known*, not surprises:

* **BR-3 / BR-34** — `POST /api/dispatch` takes no gateway and resolves its host from
  global settings (`modbus_host or fwh_host`). In multi-gateway it dispatches the wrong
  battery, silently.
* **BR-16 / BR-18 / BR-19** — `_fire_entry` marks an occurrence fired even when the action
  failed, and `due()` then refuses to re-enter. A transient Wi-Fi blip burns the whole
  occurrence. Stop leaves `last_fired_day` set, so a stopped schedule can never resume.
* **BR-23 / BR-24 / BR-27** — `DELETE /api/gateways/{id}` never unpublishes, so deleting a
  gateway mints orphaned Home Assistant entities.
* **BR-35–43** — no supervision, no lifecycle, no joined health model. Phase 0 covers the
  first part only.
* **BR-40 — a real zombie window.** `supervisor.stop_poller` sets the stop Event and
  returns immediately, but the poll loop only checks it at the end of a cycle and can sit
  in `wait_for` for up to ~30 s. `is_running()` reads `_pollers`, already popped — so a
  quick disable→enable starts a **second poller for the same gateway**, both writing
  metrics and publishing MQTT for the same node. Phase 0's `unregister` hides the older
  one from `/api/health/workers` while it is still producing side effects. Fix is in
  `RUNTIME_DESIGN.md` §5.7: deregister only when the task has finished, and make the
  registry the authority on whether a name is in use.

## 5 · Outstanding operational items

* ~~The MQTT purge has never been run.~~ **Done 2026-10-09**: 21 stale `agate` configs
  cleared, 0 orphans remaining, 63 ours-live kept and all 383 foreign configs untouched —
  the ownership test held in production.
* **Two mock gateways are registered in the production roster** on :8101, publishing to the
  real broker. Probably unintended. Removing them from the roster is also what would make
  their 42 discovery configs purgeable.
* `franklinwh-modbus-bridge` PR #30 awaits the runtime work before being refreshed.

## 6 · Gotchas — learned the hard way

* **Never delete on PyPI.** Irreversible, burns the version number permanently, breaks pins
  and lockfiles. Yank is the mechanism. The library publishes on a `v*` tag via **trusted
  publishing (OIDC)** — *pushing the tag IS the release*; do not also run `twine upload`.
* **`franklinwh-local` and `franklinwh-local-api` on PyPI are not ours.** A retirement plan
  was written and abandoned for this reason; see `LOCAL_API_COMPARISON.md`. Do not retry it.
* **Do not rename the add-on `slug`** (`franklinwh_local_bridge`) or the MQTT identity
  strings (`"Local Bridge v…"`, `"FranklinWH aGate (Local Bridge)"`). They are identity, not
  labels: the slug is the add-on's identity to the Supervisor, and `mqtt_scan.is_self`
  matches that `sw_version` prefix to tell our entities from the Modbus bridge's and FWHAI's
  on a shared broker. Both carry comments saying so.
* **Do not free the old GitHub repo names.** They redirect; the redirect dies the moment
  another repo claims the name.
* **Tests must isolate `DATA_DIR`** — `./data` is mounted into the live container, and a
  non-isolated test once wiped real history. `conftest` handles it; do not undo that.
* **The dev venv drifts from `pyproject`.** `croniter` was missing and surfaced as a failing
  cron test rather than "your environment is incomplete". The planned drift panel
  (design §5.5) exists because of this.
* **The running container carries a library built from a branch** — `tools/build_image.sh`
  builds the wheel from the sibling checkout, whatever branch it is on. Today that is
  `franklinwh-direct-connect-api` **0.4.0**.
* **`except Exception` is 203 sites in this repo** against 23 mentions of retry. Apply the
  new pattern at boundaries only; the inner "never kill the poll loop" guards stay.

## 7 · Keeping this file honest

Update it when a phase lands, a PR merges, or a gotcha is learned. A handover that is
quietly out of date is worse than none, because it is believed.
