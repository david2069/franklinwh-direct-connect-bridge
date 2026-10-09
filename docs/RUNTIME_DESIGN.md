# Runtime design — components, supervision and work

Status: **accepted 2026-10-09.** The five open decisions in §6 are settled; phase 0 is
ready to build. Not yet shared with the Modbus
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

## 6 · Decisions — settled 2026-10-09

| # | Decision | Consequence |
| --- | --- | --- |
| 1 | **Convert the daemon threads to supervised async workers.** One supervision model, not two — two models is how this started. | `vpp-monitor`, `cloud-status`, `dispatch-watchdog` and the BMS recorder become workers. The watchdog is the delicate one: it is `guarded` (§5.4), so its conversion must preserve re-adoption of an in-flight force, not just move the loop. |
| 2 | **Fixed scheduler cadence, configurable, default 15 s.** Predictable beats clever. | A new setting; scheduling resolution stops being an accident of `poll_interval`. Windows shorter than the cadence need a stated minimum rather than silently never firing. |
| 3 | **Crash-loop ceiling: 5 restarts in 10 minutes → `failed`**, needs a manual restart, notified loudly. | A worker that cannot stay up stops and says so. Deliberately not "keep trying slowly": a slow silent loop is the failure mode this whole document exists to remove. |
| 4 | **A failed worker does NOT fail the container.** Notify and surface instead. | `/api/live` stays exactly as it is — a liveness probe that does no gateway I/O — and must **not** be made worker-aware. Restarting the world hides the cause, and a crash loop at container level destroys the evidence. The worker monitor and notifications carry this instead. |
| 5 | **L2 covers schedules only for now.** | One `occurrences` table for scheduled work. Generalise to other deferred work only when a second real case appears, not in anticipation of one. |

Decision 4 is the one with the sharpest trade-off, so state it plainly: this bridge chooses
**visible degradation over automatic recovery**. A dead worker stays dead, loudly, until
someone looks. That is the right call for a system whose writes move a battery — an
automatic restart that silently re-arms a force is worse than an outage that is reported.

## 7 · Migration — each phase leaves a working system

| Phase | Change | Leaves behind |
| --- | --- | --- |
| 0 | Worker registry, heartbeat, supervisor, `/api/health/workers` + Process card with restart classes, `except` around `run_gateway`. Existing work is *registered*, not rewritten. | Nothing dies unnoticed; restarting cannot drop an in-flight force. |
| 1 | Scheduler becomes its own worker, reading per-gateway snapshots. | Scheduling survives a gateway failure; resolution no longer tied to poll interval. |
| 2 | Occurrences table; the scheduler claims and updates rows. | `missed`, retry-within-window and resume become expressible (BR-16/18/19). |
| 3 | Wire `resilience.call` into scheduler actions and bridge writes. | Outcomes structured; `unknown` surfaced (BR-6–13). |
| 4 | `selfcheck` worker + findings endpoint. | Standing conditions detected. |
| 5 | Health cards, `bridge_health` notifications, HA `problem` sensor. | Someone is told. |
| — | **Dependency + drift panel** in `/api/support-info`. Independent of L0; schedule it whenever. | "Which library is this actually running?" answerable without `docker exec`. |

Phase 0 is small and changes no behaviour. It is also the one that would have caught every
silent failure found so far.

## 8 · What this means for work in flight

The scheduler retry wiring is **paused until phase 1**. Retrying inside a component that
can die unobserved, on a cadence borrowed from a poll loop, would encode the coupling this
design removes. `resilience.py` stands — it is L1 and independent — but nothing else should
be built against the current runtime.

## 9 · Open questions

* ~~Does the Modbus bridge have the same passenger-scheduler shape?~~ **Answered (§1.1):**
  no — its scheduler is already a proper component. The supervision gap *is* shared, so
  L0 belongs beside `BRIDGE_BASELINE.md` as BR-35–38, while the scheduler decoupling is
  ours alone.
* Do any workers need to survive a bridge restart mid-action, beyond the dispatch
  reconcile that already exists?
* Is single-process still right, or does the dispatch watchdog belong somewhere that a
  bridge crash cannot take with it? This matters because the software watchdog is the only
  thing that ends a force.
