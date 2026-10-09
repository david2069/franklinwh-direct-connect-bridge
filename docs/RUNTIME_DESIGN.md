# Runtime design — components, supervision and work

Status: **FROZEN v1.7, 2026-10-09.** (v1.7 adds §6.6b — provenance for every cross-bridge claim, after several were taken from screenshots rather than source. v1.6 adds §6.7 — rule authoring, history and sharing, measured against the Modbus Bridge's screen; most already exists, four things do not. v1.5 adds §6.6, the orchestration model adopted from the Modbus Bridge, and widens phase 2 to carry it. v1.4 records §6.5 — why not APScheduler, and the misfire/coalesce vocabulary phase 2 adopts. v1.3 moves the Process card from phase 0b to phase 6,
where it becomes part of a whole Monitoring section rather than a card built twice. v1.2
redefined `zombie`; v1.1 added `aborted`.) (v1.1 added the `aborted` state and the transition
rules. v1.2 redefines `zombie` as *uncontrollable* rather than *superseded*, and adds the
control verbs with deadlines — because a cancel is a request, not an outcome, and an abort
that is never confirmed is a zombie wearing an abort's name. Both amendments are scoped to
§5.6.) Decisions settled (§7), questions closed (§10), scope
fixed (§8). Implementation follows the phase order; discovering work inside a phase is
expected, but moving work between phases or adding one needs a v1.1 with a note saying what
changed and why. The point of a freeze is that the next surprise gets absorbed by the plan
instead of restarting it. Not yet shared with the Modbus
bridge — the supervision requirements (BR-35–38) apply to both, but there is no point
syncing a design that is still moving. Tell them once phases 0–1 have landed and survived
contact. `BRIDGE_BASELINE.md` states *what*
must hold; `OBSERVABILITY_COVERAGE.md` states how we *notice* when it stops. Neither can
stand up until the runtime underneath them can be observed and restarted. This is that
runtime.

## 1 · The problem, from evidence

The bridge has no runtime architecture. It has a web application with background work
attached in three unrelated ways, none of which has an owner:

| Work | Mechanism | Lifecycle | Supervised | Observable |
| --- | --- | --- | --- | --- |
| Gateway poll — **and the scheduler, metrics, billing, MQTT publish** | one `asyncio` task per gateway | started at boot, stopped on delete | `is_running()` exists; nothing calls it | a `running` flag |
| VPP monitor | daemon thread | started at boot | no | no |
| Cloud status | daemon thread | started at boot | no | no |
| Dispatch watchdog | daemon thread | per dispatch | no | indirectly |
| BMS recorder | daemon thread | per session | no | session row |
| MQTT publisher | paho thread | per gateway | self-heals, 60 s | `mqtt_connected` |

Three consequences, all observed:

1. **`scheduler.tick` runs inside the gateway poll loop** (`poller.py:243`). The scheduler
   is not a component; it is a passenger. It inherits the poll interval as its resolution,
   and it dies when its host dies.
2. **`run_gateway` has `try:` … `finally:` with no `except`.** One unhandled exception ends
   the task. Nothing inspects `task.exception()`. Polling, metrics, MQTT publishing and all
   scheduling for that gateway stop together, permanently, in silence.
3. **The container watchdog cannot see it.** It probes `/api/live`, which deliberately does
   no gateway I/O so an unreachable aGate will not cause restarts. Correct for its purpose,
   and precisely why it reports a healthy add-on whose every worker is dead.

### 1.1 · How the Modbus bridge compares

Checked 2026-10-09 against `franklinwh-modbus-bridge@main`. The shapes differ, the gap
does not:

| | Direct Connect Bridge | Modbus Bridge |
| --- | --- | --- |
| Scheduler is its own component | **no** — passenger on the gateway poll loop | **yes** — `gateway/scheduler.py:637` owns its task and tick interval |
| Scheduler survives a bad cycle | n/a — its host can die | **yes** — inner guard, *"never let one bad tick kill the loop"* |
| Worker registry / heartbeat | no | no |
| Exception retrieved when a worker exits | no | no |
| Restart policy for dead work | no | no |
| Worker state observable | no | no |
| Long-running loops that guard themselves | — | **3 of 5**; `gateway/health.py` and `publish/mqtt_publisher.py` do not |

So the **passenger problem is ours alone**, and the Modbus bridge is the reference for
fixing it — phase 1 below is "become what it already is". The **supervision gap is shared**:
~15 `create_task` sites there, none watched.

And its safety is by convention rather than construction. Two of five loops can die on an
unhandled exception with nobody noticing — including, pointedly, the health component. That
is the argument for a worker model in one line: every author remembering `try/except` is a
streak, not an architecture, and the streak has already broken.

This is also why the same defects appeared independently in both bridges. They are not
coding mistakes. They are the absence of a component model.

## 2 · Why the work so far is not enough

`resilience.py` makes a *call* fail honestly. The occurrence table would make *work* fail
honestly. Neither helps if the thing that was going to make the call is gone. A retry
policy inside a dead task retries nothing, and a self-check that runs inside the component
it is checking reports nothing.

So the order has to be: **runtime, then work, then outcomes, then detection, then
surfacing.** The pieces already written are layers 1, 3 and 4 of a five-layer stack whose
layer 0 does not exist.

## 3 · Principles

1. **Everything that runs has a name, an owner and a heartbeat.** If it can stop, it must
   be able to say it stopped.
2. **Liveness is proven, not assumed.** "The task object is not done" is not liveness — a
   task can be alive and wedged. A worker proves liveness by beating.
3. **Silence is a failure state.** The absence of an expected event is itself an event.
4. **One concern per worker.** The scheduler must not die because a gateway read failed.
5. **Degrade, don't vanish.** A failed component reduces capability visibly; it never
   removes capability silently.
6. **Observability cannot live inside the thing it observes.**

## 4 · The layer model

```
L4  Surfacing        logs · health cards · notifications · HA entities
L3  Detection        self-check findings, each tied to a BR requirement
L2  Work state       occurrences, dispatches — expected work, durably recorded
L1  Boundary calls   deadline · classify · Outcome{ok|failed|unknown}    [resilience.py]
L0  Runtime          workers · registry · heartbeat · supervisor · restart policy
```

Each layer may only depend downward. L3 must observe L0–L2 from outside.

## 5 · L0 — the component model

### 5.1 Worker

A worker is a named unit of background work with one concern:

```
Worker:
  name          stable identity, e.g. "poller:10060006a02f24170091", "scheduler"
  scope         global | gateway:<id>
  concern       one sentence; if it needs two, it is two workers
  cadence       the interval it intends to run at
  start()/stop()
  beat()        called each cycle; stamps last_beat_ts
  restart_policy  always | on_failure | never, with backoff and a crash-loop ceiling
```

State is `starting · running · degraded · stopped · failed`. **`degraded` is deliberate:**
a poller that cannot reach its aGate is not failed — it is working correctly and reporting
a device problem. Conflating the two is how "gateway unreachable" and "poller crashed"
became the same silence.

### 5.2 The worker set after this change

| Worker | Scope | Concern |
| --- | --- | --- |
| `poller:<gw>` | gateway | read the device, record metrics, publish state |
| `scheduler` | global | evaluate occurrences and run due work |
| `dispatch-watchdog` | global | end forces at their deadline |
| `vpp-monitor` | global | track VPP/force state |
| `cloud-status` | global | cloud witness and breaker |
| `selfcheck` | global | produce findings (L3) |
| `maintenance` | global | pruning, retention, billing rollover |

**The scheduler leaves the poller.** It becomes a global worker on its own cadence, reading
a snapshot per gateway rather than being hosted by one. This is the single most important
change in this document: it decouples scheduling resolution from poll interval, and stops
one gateway's failure from stopping all scheduling.

Do not design this fresh — `franklinwh-modbus-bridge/src/franklinwh_bridge/gateway/scheduler.py`
is a working implementation of exactly this shape: own task, own `_tick_s`, inner guard so a
bad tick cannot kill the loop. Read it first.

### 5.3 Supervisor

One loop, itself a worker, that every few seconds:

* reaps finished tasks and **retrieves the exception** — a worker never exits unreported;
* restarts per policy with exponential backoff;
* flags a stale heartbeat as failed even when the task object looks alive;
* refuses to restart faster than the crash-loop ceiling, marking `failed` instead — a
  silent restart loop is worse than a stopped worker;
* records every transition.

### 5.4 Observable surface — the worker monitor

`GET /api/health/workers` → name, scope, state, uptime, last beat, restarts, last error.
A Process card renders it with per-worker actions. The FranklinWH HA Integrator's Process
Control Center is the reference for what this is *for*; two things we do differently, both
deliberate.

**List declared workers, not discovered tasks.** FWHAI's panel enumerates raw asyncio
tasks, so it carries two rows of
`starlette.middleware.base.BaseHTTPMiddleware.__call__.<locals>.call_next.<locals>.coro`
beside the real ones. Framework plumbing drowns the signal, and a reader cannot tell which
rows matter. BR-35 says *registered*, not *discovered*, precisely so this cannot happen:
if it is not a declared worker it does not appear, and if it does background work and is
not declared, that is the bug.

**Restart is not uniformly safe.** A Restart button on every row is wrong here, because
restarting the dispatch watchdog removes the only thing that ends an active force — this
firmware's hardware revert timer is cosmetic. So each worker declares a restart class:

| Class | Workers | Behaviour |
| --- | --- | --- |
| `free` | `selfcheck`, `maintenance`, `cloud-status`, `vpp-monitor` | restart any time |
| `handoff` | `poller:<gw>`, mqtt publisher | restart, then re-publish current state so consumers are not left stale |
| `guarded` | `dispatch-watchdog` | **refuse** while a force is in flight, unless the restart re-adopts it |

`guarded` is not a special case to invent: `battery_control.reconcile_interrupted` already
re-adopts active dispatch rows on boot, against a stated policy. A restart must go through
that same path rather than starting clean, so the watchdog resumes owning the force it was
already responsible for. A restart that silently drops an in-flight force is a safety
regression wearing a convenience button.

The UI shows the class, so "why can I not restart this right now" is answerable without
reading source.

**Order by attention, not by activity.** FWHAI sorts the active worker to the top, which
is reaching for the right thing and misses it: when everything is running — the normal
case — "active first" is just an arbitrary order that shuffles between refreshes, and a
list that reorders under you is one you stop trusting. Sort into bands instead:

```
zombie · crashed · unresponsive   →  degraded · stopping  →  running · ready  →  paused · stopped
```

and stay alphabetical **within** a band. Stable while healthy, and whatever needs a human
is already at the top when it is not.

**Group by family, do not flatten.** FWHAI shows `gateway-24170091` next to
`ha_event_listener` and `ha_event_listener:Home Assistant (this instance)` — a parent and
its per-instance child, side by side as peers. We have the same shape (`poller:<gw>` per
gateway, one HA listener per configured instance), and `scope` already carries it. Render
the family once with its instances nested under it, so "three pollers, one degraded" reads
at a glance instead of as three unrelated rows that happen to share a prefix.

### 5.5 Dependency and drift panel — related, and deliberately separate

Different question, different layer: **what is actually installed in this container?**
Nothing to do with liveness, so it does not belong in the worker monitor and does not block
on L0 — it can land independently.

`/api/support-info` already carries configuration (gateways, billing, integration, solar)
and `meta.software_version`. It gains:

* Python version and platform;
* installed distributions with versions;
* **declared-versus-installed drift** for the pinned few — `franklinwh-direct-connect-api`,
  `franklinwh-modbus`, `franklinwh-cloud`, `croniter`, `paho-mqtt`.

The drift line is the part with teeth, and two things from 2026-10-09 argue for it:

1. The running container carries `franklinwh-direct-connect-api` **0.4.0 built from an
   unreleased branch wheel** — correct for a dev rebuild, and invisible everywhere in the
   UI. "Which library is this actually running?" should not require `docker exec`.
2. `croniter` is a declared core dependency that was **missing from the dev venv**, which
   surfaced as a failing cron test rather than as "your environment is incomplete".

Drift becomes a `selfcheck` finding (L3), so it is reported rather than merely available.


### 5.6 Lifecycle — the state machine

Every state here exists because it implies a **different remedy**. That is the admission
test: if two states would be handled identically by both the supervisor and the operator,
they are one state wearing two names.

#### States

| State | Means | Beats? | Terminal? | Remedy |
| --- | --- | --- | --- | --- |
| `init` | registered; dependencies not resolved, not yet started | no | no | wait; a worker that never leaves `init` is itself a finding |
| `ready` | started and able to work, not yet working | no | no | none — this is the healthy idle of a triggered worker |
| `running` | steady state, doing its work | **yes** | no | none |
| `degraded` | doing its work; a dependency is unavailable | **yes** | no | **do not restart** — fix the dependency; surface the reason |
| `paused` | deliberately idle, state retained, resumable | no | no | resume when the reason clears |
| `stopping` | stop requested, winding down | no | no | time it; escalate if it overruns |
| `stopped` | stopped **cleanly**; name free; restartable | no | yes | restart if wanted |
| `aborted` | stop **forced** — cancelled, did not wind down cleanly | no | yes | restart, **and check for state it never got to release** |
| `unresponsive` | alive, not beating — wedged | no | no | **cancel first**, then restart |
| `crashed` | exited with an exception | no | yes | restart per policy; read `last_error` |
| `zombie` | **uncontrollable** — failed a control verb within its deadline, typically survived `abort`; still executing | no | yes | nothing from inside the process: restart the bridge |

#### Transitions

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
   (register) → init ──→ ready ──→ running ⇄ degraded          │
                    │       │         │  │       │             │
                    │       │         │  └───────┴──→ paused ──┘   (resume)
                    │       │         │
                    │       └─────────┴──→ stopping ──→ stopped ──→ (restart) → init
                    │                         │
                    │                         └── overruns ──→ unresponsive
                    │                                              │
                    │                                    cancel ───┴──→ aborted
                    │                                                      │
                    └──────────────── crashed ←── raised                   │
                                         │                                 │
                                         └──→ (restart per policy) → init ←┘

   any state ──→ zombie   (fails a control verb within its deadline: abort did not
                           kill it, or it was superseded and is now unaddressable)
```

#### The rules that are not obvious from the diagram

* **`stopped` and `aborted` are both terminal, and the difference matters.** `stopped` wound
  down cleanly and released what it held. `aborted` was cancelled mid-flight, so anything it
  owned — a force, an open session, a half-written row — may never have been released. The
  operator needs to know which happened; collapsing them loses the only evidence that a
  cleanup was skipped.
* **`unresponsive` is not terminal.** It is a *diagnosis*, and the remedy has two steps:
  cancel, which moves it to `aborted`, then restart. Restarting without cancelling leaves
  the wedged task running and produces a `zombie`.
* **`degraded` never triggers a restart.** The worker is fine; its dependency is not.
  Restarting it cannot reach the aGate that is offline, and doing so repeatedly turns a
  device outage into a crash loop.
* **`zombie` is reachable from any state** and is always terminal. It is not a failure of
  the worker's *work* but of its *controllability* — and it is the only state whose remedy
  lies outside the runtime.
* **A restart is a new lifecycle**, re-entering at `init`. It is not a transition back to
  `running`, because the start may itself fail.
* `init → stopping` is legal: a worker can be stopped before it ever runs.

#### Control verbs, and what `zombie` actually means

A worker is controllable or it is not, and that is the sharpest health signal there is.
Six verbs, each with a deadline, each **verified rather than assumed**:

| Verb | Means | Deadline | Success |
| --- | --- | --- | --- |
| `status` | report your state | 1 s | a current answer |
| `start` | begin work | 30 s | reaches `ready`/`running` |
| `pause` | stop working, keep state | 10 s | reaches `paused` |
| `resume` | work again | 10 s | reaches `running` |
| `stop` | **graceful** — finish the cycle, release what you hold, exit | 35 s | reaches `stopped` |
| `abort` | **ungraceful** — terminate now, cleanup not guaranteed | 10 s | reaches `aborted` |

**`zombie` is the state of a worker that fails to answer a control verb within its
deadline — canonically, one that survives `abort`.** That is the honest definition,
because abort is the last resort: if it does not work, nothing else will. The worker keeps
consuming resources and producing side effects, and the process can no longer do anything
about it.

So the pair is exact:

* **`aborted`** — we forced it and it died. Ungraceful, cleanup possibly skipped, but it
  is gone and its name is free.
* **`zombie`** — we forced it and it did not die. Still running, uncontrollable, name
  **never** reusable while it lives.

And the implementation rule that follows, which is easy to get wrong: **a cancel is a
request, not an outcome.** `task.cancel()` returns immediately and guarantees nothing — a
task that catches `CancelledError`, or sits in a thread or a non-cancellable call, survives
it. Every abort must therefore be *confirmed* within its deadline, and an unconfirmed abort
is a zombie, not an abort.

Being superseded while still running (§5.7) is a *path into* zombie rather than a separate
condition: the old worker is no longer addressable, so no verb can ever reach it again.

**What an operator does about one:** nothing, from inside the process — that is the whole
point. A zombie means the bridge must be restarted to clear it, and it is reported that
loudly. It is the one state whose remedy is outside the runtime.

#### Cadence by kind

Beating means different things, and the supervisor must not impose one meaning:

| Kind | Beats | Example |
| --- | --- | --- |
| cyclic | once per cycle | `poller:<gw>` — per poll |
| ticking | once per tick | `scheduler` — per evaluation |
| triggered | "alive and waiting", on its own idle interval | `dispatch-watchdog` — mostly idle by design |

Without that distinction every idle triggered worker reads as stale, and the first thing
the operator learns is to ignore the panel.

### 5.7 Zombies are not hypothetical here

`supervisor.stop_poller` pops the gateway from `_pollers`, sets the stop Event and
**returns immediately** — correct, since a disable toggle must not hang the HTTP response.
But the poll loop only checks `stop.wait()` at the end of its cycle; mid-cycle it is inside
`wait_for(..., timeout=max(10, min(poll_interval, 30)))`. The old task therefore keeps
running for up to ~30 s after the stop returns.

Meanwhile `is_running()` reads `_pollers`, which no longer holds the entry. So a quick
disable→enable starts a **second poller for the same gateway while the first is still
polling, writing metrics rows and publishing MQTT state for the same node**. Phase 0 makes
it less visible, not more: `unregister` removes the old worker from
`/api/health/workers` while it is still producing side effects.

The fix is a property of the model, not a patch: a worker is removed from the registry
**only when its task has actually finished**, and `start` refuses — or waits — while a
predecessor of the same name is still `stopping`. The registry, not a dict of tasks,
becomes the authority on whether a name is in use.

## 6 · Health model — mechanism, capability, impact

There are three health endpoints today and nothing joins them: `/api/health` (is the device
reachable), `/api/providers` (is a capability available), `/api/health/workers` (is a
mechanism alive). None answers the question an operator actually has, which is **"will my
EV charging schedule fire tonight?"**

These are not detail tiers. They are different questions, and each is derived from the one
below it:

| Level | Question | Audience |
| --- | --- | --- |
| **Impact** | what does this mean for the things I configured? | the owner |
| **Capability** | what can the bridge do right now? | the UI, HA, automations |
| **Mechanism** | is this worker alive? | the supervisor, a maintainer |

### 6.1 Criticality is derived, never declared

It is tempting to flag a worker `critical: true`. Do not — the same worker failing means
different things depending on the architecture around it.

Today, `poller:gw1` dying stops **scheduling** for that gateway, because the scheduler is
its passenger. After phase 1 the identical failure means gw1's **data goes stale while the
scheduler keeps evaluating against it** — a schedule firing on a three-hour-old SoC, which
is arguably worse. A hardcoded criticality label would start lying the moment phase 1 lands.

So impact is computed from a declared dependency graph:

```
capability "run scheduled dispatch on gateway X" requires:
    scheduler worker     alive
    poller:X             FRESH        — not merely alive
    modbus transport     reachable
    write gate           enabled
```

Severity follows from **which capabilities a failure removes**, which is the correlation
that is missing today. And which capabilities *matter* is the user's to declare: plenty of
installs never dispatch, and a capability nobody relies on should not page anyone.

### 6.2 Freshness is not liveness

A worker can beat happily while every poll inside it fails — `degraded`, with a rising
`fail_streak` and data hours old. "Worker alive" hides that completely, and a schedule
evaluating conditions on stale data is dangerous in a way the worker list cannot show.

Capability health therefore carries **data age**, not just worker state, and a capability
whose inputs are stale is `degraded` even when every component is `running`.

### 6.3 Schedules get a pre-flight

Each schedule's runnability is computable *before* its window, from things already known:
its target gateway's freshness, the transport its action needs (local write, Modbus
dispatch, cloud reserve, HA notify — each with its own availability and reason), the write
gate, and the scheduler's own liveness.

That turns "it did not fire, here is one log line" into "this will not fire, because X" —
in advance. It also gives the occurrence a correct terminal state: a pre-flight failure is
`skipped` **with a reason**, which is a different thing from `failed`, and must not be
retried as though it were transient.

### 6.4 One rollup, not a fourth endpoint

`/api/health` becomes `summary` → `capabilities` → `components`, folding in what
`/api/providers` and `/api/health/workers` report rather than adding another partial view.
The existing endpoints stay as the detailed drill-downs they already are.

## 6.5 · Why not APScheduler — and what to take from it anyway

> Plain-English version of this section, for anyone who does not live in the code:
> [`WHAT_THE_ENGINE_IS.md`](WHAT_THE_ENGINE_IS.md). Short version — a job scheduler is an
> alarm clock, this is a thermostat.


Asked, fairly, after spotting APScheduler installed in the FranklinWH HA Integrator.

**Decision: keep ours, for one reason — it is not a scheduler.** `scheduler.py` is 1,916
lines and 68 functions, and the bulk of them (`_coerce_number`, `_as_ranges`, `_like`,
`_apply_op`, `substitute`, `_eval_tree`, `evaluate`) are a **condition expression
evaluator**. APScheduler answers "run this job at this time". Ours answers "is this window
open, and do the conditions hold *right now*".

| We have | APScheduler |
| --- | --- |
| **windows** — start + duration, `inside`/`before`/`after`, midnight wrap | fires at a point in time |
| entry conditions over live telemetry, re-evaluated each tick | — |
| exit conditions that close a window early | — |
| priority / conflict policy between competing schedules | — |
| per-gateway targeting, dispatch reconciliation | — |

Adopting it would replace the ~30-line tick loop and none of the other 1,900 lines. We are
also not pure-NIH: `croniter` already does the cron date maths, which is the part genuinely
worth not writing.

The honest gap is that this was never *stated*. When phase 1 decoupled the tick, "should
APScheduler own the cadence?" was a legitimate question and went unasked. The answer is
still no — the tick must be a supervised worker with a heartbeat (BR-35/36), which
APScheduler does not provide, and trading a dependency for thirty lines of loop is a poor
deal — but it should have been a decision rather than a default.

**What to take anyway.** APScheduler has settled vocabulary for exactly what phase 2 is
about to build, and the names are already widely understood:

| Borrow | Means | Phase 2 use |
| --- | --- | --- |
| `misfire_grace_time` | how late is still worth running | the boundary between a late catch-up and `missed` |
| `coalesce` | missed five runs → do one, not five | a reconnecting bridge must not replay a backlog of windows |
| `max_instances` | never overlap with yourself | one occurrence per schedule in flight |

Use those names rather than inventing synonyms.

### The Execution Queue, independently confirmed

The HA Integrator's Automations screen splits into **Automation Rules · Execution Queue ·
History Log · Audit Ledger** — which is the phase 2 model reached independently. Its
*Execution Queue* is the `occurrences` table: work materialised **before** it runs, which is
what makes "missed" detectable at all.

Its History/Audit split is also the fix for a measured problem here. Our `schedule_log` is
one undifferentiated stream in which **execution history is 2.2% of rows** (9 of 405);
`gated` alone is 76%, and the 2000-row FIFO cap will evict real history long before it ages
out. Phase 2 separates them: occurrences carry execution, `schedule_log` reverts to CRUD and
operator actions.

## 6.6 · Orchestration — what transfers from the Modbus Bridge

Phase 2 adopts the Modbus Bridge's orchestration model rather than inventing one. It is
further along, and more importantly it has already been wrong once in a way worth not
repeating.

### Exclusivity is per RESOURCE, not per gateway

The subtle part, and the reason to copy rather than re-derive. From its own comment:

> *"Only a battery command is exclusive — one gateway can run one setpoint at a time — so
> only those entries contend for the target. HA-actions-only entries command other devices
> entirely … Before this split, an 'always evaluate' HA-only entry held the target
> permanently and **starved every schedule on that gateway while dispatching nothing
> itself**."*

So a rule claims the **resource it actually drives**, not the gateway. The battery setpoint
is exclusive — one at a time, genuinely contended. A rule that only sends a notification or
pokes a solar inverter contends for nothing and must never hold the gateway. Lock the
gateway instead and a notify-only rule evaluating constantly starves everything on it while
doing no work at all.

Lanes for us: **battery setpoint** (exclusive) · **operating mode** (exclusive) ·
**notify / HA actions** (not exclusive) · **off-grid** (exclusive).

### Targeting: one gateway, or all of them

`(target_type, target_id) -> [(gateway_id, handler)]`. A `gateway` target yields one pair; a
`site`/`service` target fans out to every member gateway. Ownership is keyed on
`gateway_id`, so it stays stable when the member set changes — a gateway joining a site does
not silently transfer someone else's claim.

### Priority, and a deterministic tie-break

`winner()`: priority descending, `created_at` ascending as tie-break, so **a rule added
later never displaces an established one at equal priority**. Deterministic matters more
than clever: the same inputs must always pick the same winner, or a conflict becomes a
coin-toss nobody can reproduce.

Losers are *recorded* as skipped-with-reason, not silently dropped — "why didn't mine run"
must be answerable.

### Entry and exit, for both conditions and actions

We already have entry/exit *conditions* and `_fire_ha_phase(entry, "fire" | "exit")` for HA
actions. Phase 2 makes the pair symmetric and explicit: a rule may act **on entry** and
**on exit**, and the exit action runs even when the window is cut short by a stop, a losing
conflict, or an exception. An exit action that only runs on the happy path is worse than
none, because it is trusted.

### Notifications: templated from the same vocabulary as conditions

Its `_render` substitutes `%sensor.id%` from the live snapshot, and the principle is the
one to copy:

> *"the SAME sensor ids conditions use … One vocabulary: whatever you can gate a rule on,
> you can quote in its message, and there is no alias table to drift out of step with the
> catalog."*

And the failure rule, which is right: an unknown sensor renders `?` rather than failing the
send — *"a notification is what you reach for when something has gone wrong; a message with
a gap still beats no message."*

Static text stays valid; templating is opt-in by writing a placeholder.

### Logging: event, error and exception are three different things

* **event** — it ran, it was skipped, it lost a conflict, it was stopped. Expected, and the
  history people read.
* **error** — it tried and failed. Actionable.
* **exception** — the engine itself misbehaved. A bug, not a user problem, and it must never
  be filed where a user is expected to interpret it.

Today all three land in one `schedule_log` stream where execution history is 2.2% of rows.
Phase 2 separates them.

### One independent confirmation

The Modbus Bridge sets `DEFAULT_TICK_S = 15  # window resolution is per-minute; 15s keeps
latency low` — the same cadence, from the same reasoning, reached separately. That is the
strongest evidence available that the minute-resolution argument in decision 2 is right.

## 6.6b · Provenance — a screenshot is not evidence

Several claims in §6.6 and §6.7 were taken from screenshots of the Modbus Bridge's UI. A
painted control is not a working feature, and designing against one risks citing vapour as
prior art. Every cross-bridge claim below was therefore re-checked **in source**, and our
own claims by **exercising the endpoint**. Verified 2026-10-09.

| Claim | How it was checked | Verdict |
| --- | --- | --- |
| our dwell (`entry_hold_s`) | `_dwell_since` start/reset/clear in the tick | real |
| our `Lookup` operands | `scheduler.py:214` — compare to another sensor's live value | real |
| our test verification | **exercised** — returns per-row `actual` + `passes` against live data | real |
| our presets, export | **exercised** — 11 presets; `{type, version, entries}` | real |
| our timeline | **exercised** — `segments` + `soc`; **planned only, no "actually ran"** | partial |
| their per-rule missed policy | `_missed_fire_time()`, `catchup()`, `missed_policy`, `late_fire_remaining`, `catchup_duration_s` | real |
| their restore-prior-mode | `release_policy`; native mode snapshotted at dispatch | real |
| their lanes / `winner()` / `_render` | read in source | real |
| **`coalesce`** | **zero hits in either bridge** | **absent everywhere** — borrowed from APScheduler (§6.5), not prior art |

**Rule going forward: cite the code, not the screen.** Where a design claim rests only on a
UI, say so, and treat it as a requirement to be built rather than a feature to be copied.

### One UI idea worth taking, now that it is confirmed working

Their condition editor renders the verification result **inline, per row** — `live: 99 ✓
passes now`, `live: false ✗ fails now` — with the row outlined green, red, or **amber when
there is no value at all, so it cannot be evaluated**. That third state is the good part:
"no reading" is a different problem from "false", and a user debugging a rule that will not
fire needs to tell them apart. We already return everything needed for this from
`/api/schedules/{sid}/test`; it is a rendering change, not new capability.

## 6.7 · Rule authoring, history and sharing — what we have, what is missing

Measured against the Modbus Bridge's Schedule & Automations screen, which is the reference.
Most of this already exists here; recording it stops us rebuilding what we have.

### Already present

| Capability | Where |
| --- | --- |
| Entry **and** exit conditions, nested groups, `ALL`/`ANY` | `scheduler.evaluate` |
| **Dwell** — "conditions must hold continuously for N before firing" | present |
| **Lookup** operands — compare a sensor to another sensor, not only a literal | present |
| **Test verification** — evaluate the conditions now and show the result before saving | `POST /api/schedules/{sid}/test`, `/evaluate` |
| Templates / presets | `GET /api/schedules/presets` |
| **Export / import** for sharing rules between installs | `/api/schedules/export`, `/import` |
| Activity history | `/api/schedules/log` |
| Timeline | `/api/schedules/timeline` |
| Priority, conflict policy fields | `priority`, `conflict` |
| Entry/exit HA actions with `%sensor.id%` templating | `_fire_ha_phase`, phase 2 adds the renderer |

### Genuinely missing

**1 · Per-rule outage policy.** Their editor has *"If missed during an outage: resume if
window still open, else log missed"* as a field on the rule. We have no `missed` concept at
all — grep returns zero. This is the single most important gap, because it is the thing the
owner originally complained about, and making it **per rule** is right: "catch up if you
can" is correct for a discharge window and wrong for a one-shot notification.

**2 · Exit release semantics.** Theirs has *"On exit / release: restore prior mode"*. We
release but do not restore — grep for `restore_prior` returns zero. A rule that overrode
Self-Consumption should hand it back, not leave the gateway wherever the override left it.

**3 · `coalesce`.** Zero references **in either bridge** — this one is not prior art, it is
borrowed vocabulary (§6.5). After an outage spanning several windows, nothing stops a
backlog being replayed, here or there.

**4 · Planned versus actually-ran.** Their timeline draws *Planned*, *Actually ran* and
*Automation fire* as separate layers over *Actual mode* and SoC. Ours can only draw what was
planned, because nothing records what was *expected* — which is the same gap the occurrences
table closes. The visualisation is a consequence of the data model, not a separate feature.

**5 · Log separation.** Their activity log filters by `fired · executed · ha action · gated ·
waiting · missed · exit condition met`, which makes one stream usable. Ours has the same
mixing without the filters, and 2.2% signal.

### Template content is a deliverable, not a stub

Theirs ships *Peak-demand shaving*, *Battery export bonus*, **Ausgrid — Evening discharge
(4–9pm)** and **Ausgrid — Solar sponge (10am–3pm)** — named for a real network, with the
window and the caveat ("check your retailer") written in. A template that encodes local
tariff knowledge is worth more than the editor it fills, because it is the part a user
cannot derive. Our presets should carry the same specificity rather than generic examples.

### Sharing

Export/import already exists both ways, and `FEAT-SCHED-IMPORT-INTEROP` already maps the
Modbus bridge's bundle to our schema. Phase 2 must not break that: an occurrence is runtime
state and **must not** be exported — a shared rule carries its definition, never its history.

## 7 · Decisions — settled 2026-10-09

| # | Decision | Consequence |
| --- | --- | --- |
| 1 | **Convert the daemon threads to supervised async workers.** One supervision model, not two — two models is how this started. | `vpp-monitor`, `cloud-status`, `dispatch-watchdog` and the BMS recorder become workers. The watchdog is the delicate one: it is `guarded` (§5.4), so its conversion must preserve re-adoption of an in-flight force, not just move the loop. |
| 2 | **Fixed scheduler cadence, configurable, default 15 s.** Predictable beats clever. | A new setting; scheduling resolution stops being an accident of `poll_interval`. **Refined while building phase 1:** windows are minute-resolution (`_window_phase` compares `hour*60+minute`, and a zero duration means that single minute), so the shortest expressible window is 60 s and the constraint belongs on the **cadence**, not on each schedule. `scheduler_tick_s` is clamped to [5, 60] and a misconfiguration is corrected loudly. A user then cannot express an unschedulable window at all, which is better than validating one they could. |
| 3 | **Crash-loop ceiling: 5 restarts in 10 minutes → `failed`**, needs a manual restart, notified loudly. | A worker that cannot stay up stops and says so. Deliberately not "keep trying slowly": a slow silent loop is the failure mode this whole document exists to remove. |
| 4 | **A failed worker does NOT fail the container.** Notify and surface instead. | `/api/live` stays exactly as it is — a liveness probe that does no gateway I/O — and must **not** be made worker-aware. Restarting the world hides the cause, and a crash loop at container level destroys the evidence. The worker monitor and notifications carry this instead. |
| 5 | **L2 covers schedules only for now.** | One `occurrences` table for scheduled work. Generalise to other deferred work only when a second real case appears, not in anticipation of one. |

Decision 4 is the one with the sharpest trade-off, so state it plainly: this bridge chooses
**visible degradation over automatic recovery**. A dead worker stays dead, loudly, until
someone looks. That is the right call for a system whose writes move a battery — an
automatic restart that silently re-arms a force is worse than an outage that is reported.

## 8 · Migration — each phase leaves a working system

**Frozen 2026-10-09.** Scope below is the whole of it. Changing a phase's *contents* needs
a new revision of this document and a note saying what moved and why; discovering work
*inside* a phase is normal and does not.

| Phase | Change | Requirements | Leaves behind |
| --- | --- | --- | --- |
| **0a** ✅ | Worker registry, heartbeat, supervisor, `/api/health/workers`, `except` around `run_gateway` | BR-35, 36, 37, 38 | nothing dies unnoticed |
| **0b** ✅ | Full lifecycle states; deregister only when work has ended; `start` refuses a name still `stopping` (the zombie fix); confirmed aborts; restart actions with `free`/`handoff`/`guarded`, `guarded` going through `reconcile_interrupted`; banded ordering and family grouping in the API | BR-39, 40 | the supervisor **recovers**, not just reports; two pollers can no longer run for one gateway |
| **1** | Scheduler becomes its own worker on its own cadence, reading per-gateway snapshots. Copy `franklinwh-modbus-bridge/gateway/scheduler.py` | BR-35 | scheduling survives a gateway failure; resolution untied from `poll_interval` |
| **2** | `occurrences` table (the "execution queue") with `misfire_grace`/`coalesce`/`max_instances` semantics; **orchestration per §6.6** — per-resource exclusivity, one-or-all targeting, priority with deterministic tie-break, symmetric entry/exit actions, templated notifications; `schedule_log` split into event / error / exception. | BR-15–19, 44–48 | `missed`, retry and resume become expressible; two rules can no longer fight over a battery; "why didn't mine run" is answerable |
| **3** | Wire `resilience.call` into scheduler actions and bridge writes; `POST /api/dispatch` takes a gateway | BR-3, 6–13, 34 | outcomes structured; `unknown` surfaced; dispatch targets the right battery |
| **4** | Capability + impact health: dependency graph, freshness, schedule pre-flight, `/api/health` rollup | BR-41, 42, 43 | "will my schedule fire tonight" is answerable |
| **5** | `selfcheck` worker + findings endpoint | BR-14, 26, 28 | standing conditions detected |
| **6** | **The Monitoring section, whole** — Overview (impact), Capabilities, Processes — plus `bridge_health` notifications and the HA `problem` sensor. Renames today's Health tab to **Connectivity**, which is what it has always been. | BR-29, 30, 38 | someone is told, and can see why |
| **7** | Unpublish on gateway delete; pre-uninstall flow; mock isolation | BR-23, 24, 27 | deleting a gateway stops minting orphans |
| **—** | Dependency + drift panel in `/api/support-info`. Independent of L0 | — | "which library is this actually running?" |

Phases 0a–3 are the spine: supervision, then a scheduler that is a component, then work
that exists as rows, then calls that fail honestly. Phases 4–7 are what make it visible.
The drift panel is unordered because nothing depends on it.

### Why Monitoring, and why not "Health"

`/api/health` returns `{host, ping, sendmqtt_9000, modbus_502, latency_ms, ok}` — that is
**device reachability**, which is one input to health, not health itself. The name has been
writing cheques the endpoint cannot cash, so phase 6 renames it **Connectivity** and gives
the section the three views the model actually describes:

| View | Answers | Source |
| --- | --- | --- |
| Overview | is anything wrong, and what does it affect? | impact (phase 4) |
| Capabilities | what can the bridge do right now, and why not? | providers + freshness (phase 4) |
| Processes | which workers are alive, and can I restart them? | `/api/health/workers` (phase 0a) |

**Monitoring** rather than **Health** on purpose: "health" invites a single green/red
verdict, and a single verdict is exactly the oversimplification that let a dead worker sit
behind a healthy container. "Monitoring" implies looking at the thing.

## 9 · What this means for work in flight

The scheduler retry wiring is **paused until phase 1**. Retrying inside a component that
can die unobserved, on a cadence borrowed from a poll loop, would encode the coupling this
design removes. `resilience.py` stands — it is L1 and independent — but nothing else should
be built against the current runtime.

## 10 · Questions — closed 2026-10-09

* ~~Does the Modbus bridge have the same passenger-scheduler shape?~~ **No** (§1.1). Its
  scheduler is already a proper component, so the decoupling is ours alone; the supervision
  gap is shared and became BR-35–43.

* ~~Do any workers need to survive a bridge restart mid-action?~~ **No — durable state
  does, not workers.** The only genuinely in-flight state is a force dispatch (already
  recorded in `dispatches`) and, after phase 2, an occurrence. Both are rows, so a restart
  **reconciles from the database** rather than resuming anything in memory. Keeping worker
  state across restarts would add a second source of truth next to the rows that already
  hold it. Rule: *if work must survive a restart, it must exist as a row before it starts.*

* ~~Should the dispatch watchdog live outside this process?~~ **No — accept the exposure,
  bound it, and make it visible.** The software watchdog is the only thing that ends a
  force, so a bridge crash leaves the battery dispatched until the bridge returns. The
  alternatives are worse: a device-side timer is unavailable (`WSetRvrtTms` is cosmetic on
  this firmware), and a second process needs its own supervision, deployment and failure
  mode — solving a rare failure by adding a permanent one.

  So the exposure is managed rather than removed:
  * the window is **restart time + reconcile time**, so `reconcile_interrupted` runs
    **early** in startup, before anything slower;
  * every force is written to `dispatches` with its window **before** it is applied, so a
    crash between write and apply fails safe — reconcile sees a force that may exist and
    checks the device rather than assuming;
  * `duration_s` is bounded by policy, because the exposure is bounded by the force itself;
  * a force found outstanding at boot is reported at `error` and notified, never released
    silently — the operator learns it happened.

  **This is a deliberate accepted risk, recorded here so it is re-decided rather than
  rediscovered.** Revisit if a crash ever strands a force in practice.
