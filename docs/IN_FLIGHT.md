# In-flight work — handover

**Updated:** 2026-10-09 (phase 0 started) · **Session:** `01WCWytg6NQWQ5fPnCZiSAf5`

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

**Phase 0 is part-done** on `feat/phase0-worker-supervision`. What landed:

* `workers.py` — `Worker`, `Registry`, heartbeat, crash-loop ceiling, `_supervise_once`
  (BR-35/36/37). 21 tests.
* Pollers registered by `supervisor.start_poller`; the three daemon threads registered at
  startup as `kind="thread"`.
* **`except` added around `run_gateway`'s loop** — the silent-death hole is closed. A crash
  now logs "polling, metrics and publishing have STOPPED for this gateway" and marks the
  worker FAILED.
* Heartbeat per poll cycle, `DEGRADED` while `fail_streak` is non-zero (BR-38).
* Supervisor loop in the app lifespan, auditing every worker transition.
* `GET /api/health/workers` (BR-38). Verified live: 7 workers running.

**What is left in phase 0:**

1. **Restart actions.** Every worker currently reports `restartable: false`, which is
   truthful — no worker has a `factory` yet, so there is nothing to restart *with*. Wiring
   it for pollers is small (`supervisor.start_poller` already is the restart path); the
   `guarded` class must refuse while a force is in flight, or re-adopt it through
   `battery_control.reconcile_interrupted`.
2. **The Process card** in the UI over that endpoint.
3. The supervisor detects and reports failures but does **not yet restart** anything.

Then **phase 1**: the scheduler leaves the poller. Copy
`franklinwh-modbus-bridge/src/franklinwh_bridge/gateway/scheduler.py`, which is already the
right shape — own task, own tick interval, inner guard.

**Do not** build scheduler retry/resume before phase 1 — see `RUNTIME_DESIGN.md` §8.

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

* **The MQTT purge has never been run.** 21 stale `agate` discovery configs remain — a
  duplicate HA device for the real gateway. `GET /api/mqtt/orphans` is a safe dry run;
  `POST /api/mqtt/orphans/purge?expect=21&confirm=true` clears them. Needs the owner's say-so.
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
