# Runtime design — components, supervision and work

Status: **draft for decision.** Supersedes nothing yet. `BRIDGE_BASELINE.md` states *what*
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

### 5.3 Supervisor

One loop, itself a worker, that every few seconds:

* reaps finished tasks and **retrieves the exception** — a worker never exits unreported;
* restarts per policy with exponential backoff;
* flags a stale heartbeat as failed even when the task object looks alive;
* refuses to restart faster than the crash-loop ceiling, marking `failed` instead — a
  silent restart loop is worse than a stopped worker;
* records every transition.

### 5.4 Observable surface

`GET /api/health/workers` → name, scope, state, uptime, last beat, restarts, last error.
A Process card renders it with per-worker Restart. The FranklinWH HA Integrator's Process
Control Center is the reference for what "good" looks like here.

## 6 · Decisions needed — these are yours, not mine

1. **Threads → tasks.** Convert the four daemon threads to supervised async workers, or
   wrap them in a thread-aware supervisor? *Recommendation: convert.* One supervision model
   is the point; two is how this started.
2. **Scheduler cadence.** Fixed 10 s tick, or derived from the finest window in use?
   *Recommendation: fixed, configurable, default 15 s.* Predictable beats clever.
3. **Crash-loop ceiling.** What counts as a loop — 5 restarts in 10 minutes? And then:
   stay failed, or keep trying slowly? *Recommendation: 5 in 10 min → `failed`, needs a
   manual restart, loudly notified.*
4. **Does a failed worker fail the container?** Should `/api/live` go unhealthy when a
   critical worker is `failed`, so the Supervisor restarts the add-on? *Recommendation:
   no — restarting the world hides the cause. Notify and surface instead.*
5. **Scope of L2 now.** Occurrences for schedules only, or all deferred work?
   *Recommendation: schedules only; generalise later if a second case appears.*

## 7 · Migration — each phase leaves a working system

| Phase | Change | Leaves behind |
| --- | --- | --- |
| 0 | Worker registry, heartbeat, supervisor, `/api/health/workers`, `except` around `run_gateway`. Existing work is *registered*, not rewritten. | Nothing dies unnoticed. |
| 1 | Scheduler becomes its own worker, reading per-gateway snapshots. | Scheduling survives a gateway failure; resolution no longer tied to poll interval. |
| 2 | Occurrences table; the scheduler claims and updates rows. | `missed`, retry-within-window and resume become expressible (BR-16/18/19). |
| 3 | Wire `resilience.call` into scheduler actions and bridge writes. | Outcomes structured; `unknown` surfaced (BR-6–13). |
| 4 | `selfcheck` worker + findings endpoint. | Standing conditions detected. |
| 5 | Health cards, `bridge_health` notifications, HA `problem` sensor. | Someone is told. |

Phase 0 is small and changes no behaviour. It is also the one that would have caught every
silent failure found so far.

## 8 · What this means for work in flight

The scheduler retry wiring is **paused until phase 1**. Retrying inside a component that
can die unobserved, on a cadence borrowed from a poll loop, would encode the coupling this
design removes. `resilience.py` stands — it is L1 and independent — but nothing else should
be built against the current runtime.

## 9 · Open questions

* Does the Modbus bridge have the same passenger-scheduler shape? If so this design is
  shared, and belongs beside `BRIDGE_BASELINE.md` rather than in one repo.
* Do any workers need to survive a bridge restart mid-action, beyond the dispatch
  reconcile that already exists?
* Is single-process still right, or does the dispatch watchdog belong somewhere that a
  bridge crash cannot take with it? This matters because the software watchdog is the only
  thing that ends a force.
