# Connection design — sessions, staleness and failure, for both channels

**Status: DRAFT for review. No code until this is agreed.**
Written 2026-10-12. Measurements are from the running bridge against the reference
aGate at 192.168.0.110, read-only.

Companion: the Modbus Bridge's `docs/dispatch-reliability-design.md`
(david2069/franklinwh-modbus-bridge PR #57). Its §5.2 reaches the same conclusion on
connection ownership from a different starting point. Where this document agrees, it
says so rather than re-deriving; where our situation differs, it says why.

---

## 1. The problem, measured

This bridge opens a new TCP connection for almost every interaction with the gateway,
on **both** channels, and closes it again immediately.

### 1.1 What the sockets say

Sampled from the container's own network namespace, to 192.168.0.110:502:

| State | Count |
| --- | ---: |
| `TIME_WAIT` | **38** |
| `CLOSE_WAIT` | **4** |
| `ESTABLISHED` | **0** |

`TIME_WAIT` lasts 60 s, so that is roughly **38 connections opened and closed in the
preceding minute** — by us alone — while holding **no** live connection at all. The
peer's independent sample over 60 s saw "at least 9" from this container; the
difference is sampling (theirs was every 2 s and misses short-lived sockets), and the
socket table is the more complete count.

**`CLOSE_WAIT` is a separate defect.** It means the gateway closed and *we have not*.
Four sockets are sitting in a state only our process can clear. That is a leak, not
churn, and it is invisible in any log.

### 1.2 What the logs say

8 × `franklinwh_modbus.controller: Connection failed: Response timeout` in 30 minutes,
1–4 minutes apart. The Modbus Bridge logs the same error 1,249–2,289 times a day
against the same device.

### 1.3 Why the count is so much higher than the call count

Our own call sites are few:

| Caller | Cadence |
| --- | --- |
| ~~VPP monitor → `battery_control.status()`~~ | ~~60 s~~ — **removed 2026-10-12**: VPP is read locally (1707 programme id), so this path opens no socket |
| Poller `summary()` → `port_open(host, 502)` | every poll (30 s) |
| `cached_ratings()` | 1 h TTL |
| `/api/battery/control/status` | on demand |

The VPP monitor has since been moved to the local channel and no longer opens a
socket at all, which removes roughly one connection per minute per gateway from
the figures below.

Three or four calls a minute cannot produce 38 connections — so the multiplier is
**inside the library**. The fwh-modbus session established why, and then corrected its
own first answer: this is verified in the **deployed pysunspec2 1.3.6**
(`ModbusClientTCP.read`: `local_connect` → `disconnect`), and it applies to **writes as
well as reads** — one `send_command` is about **7 TCP opens**:

* `connect()` builds the device and runs a full `scan()`, which opens one connection
  for the scan **and closes it at the end**. The session is left with no socket.
* Thereafter **every `model.read()` opens a TCP connection, reads, and closes it in a
  `finally`.** `read_control_status()` is M704 + M715, so ~2 connections. A full status
  pass is 6–8.
* `is_connected()` is itself a register read — so *checking* the connection opens one.
* `reconnect()` discards the device, sleeps 1 s, and performs a **full rescan** (17
  models on this aGate) before retrying.

So one `status()` call is not one connection; it is a scan plus several reads, each its
own socket. And a *failure* costs more than a success, because the retry path rescans.

**The consequence for this design, stated plainly: connections-per-minute is mostly a
measure of REQUEST COUNT, not of reconnects.** We are not leaking connections through
bad lifecycle management on the Modbus side — we are making a normal number of requests
through a library that spends a socket on each one. That changes what a fix looks like
(§4.1a).

One more library behaviour worth recording: it treats **any exception whose message
contains "modbus" as a dead link**, so a device *exception reply* — a legitimate
protocol answer — triggers a reconnect and a full rescan. Whether that materially
inflates reconnect rates is an open hypothesis, not a finding.

**We also make it worse ourselves, twice:**

1. The liveness probe is `any(port_open(host, 502, timeout=3.0) for _ in range(3))`.
   `port_open` is a real `socket.create_connection`. A healthy gateway costs 1; an
   unreachable one costs **3 connects × 3 s, every 30 s**. The bridge probes hardest
   exactly when the device is least able to answer.
2. That probe runs for **mock gateways too** — `summary()` does it unconditionally, so
   each in-process mock tries `127.0.0.1:502` every poll. Pointless, and it makes
   `modbus_502` meaningless for mocks rather than absent.

### 1.4 The local channel has the same shape, less visibly

`client.py` has **32 `_client(s, host)` call sites**. Each is
`with _client(...) as c: c.login()` — a new TCP connection to :9000 **and a fresh
login** per call. The poller's `summary()` at least batches its reads into one session,
which is why it was written that way; every other REST endpoint does not.

This channel has not shown symptoms, so it is **not** the urgent half. It is in scope
because the same design should cover it, and because adding the grid-voltage read
(phase 3) put one more read inside that session rather than another session — the right
instinct, worth making a rule.

---

## 2. What we do not know, and must not guess

Taken from the Modbus Bridge's unknowns, because they apply identically to us and
neither of us should answer them twice.

| # | Unknown | Why it decides something |
| --- | --- | --- |
| U1 | The aGate's concurrent-connection limit on :502, and its behaviour when exceeded (refuse? drop the oldest? slow everything?) | Decides whether **one** connection is a preference or a hard requirement |
| U2 | Response-time distribution with a single quiet client | Separates "slow device" from "contention", and sets timeouts |
| U3 | Cost of a full model scan, and whether reconnect-with-rescan is itself a cause of timeouts | Decides whether reconnect may skip the rescan |
| U4 | Whether churn (many short connections) behaves differently from a few long-lived ones | Decides whether this design is a fix or merely tidier |
| L1 | Whether our `CLOSE_WAIT` sockets are a library leak or ours | Ours to answer; see §6 |
| L2 | Whether the library's "any exception containing *modbus* means dead link" rule inflates our reconnect and rescan rate | Decides whether request reduction alone helps |

*(Numbered `L*` so they do not collide with the Modbus Bridge's `U*` list, which is shared between both repos and has its own U9.)*

**Explicitly: nobody should discover U1 by exhausting it on the live site.** Both
bridges have agreed that.

There is one thing we *can* state now: with three independent clients (this bridge, the
Modbus Bridge, Energipay) each churning connections, the device's socket table is
driven by **turnover**, not by concurrency — and `TIME_WAIT` entries occupy it after the
conversation has ended. A limit expressed in concurrent sockets can still be reached by
three processes that are each "only using one at a time".

---

## 3. Goals

1. **Stop the churn.** One owned connection per gateway per channel, reused.
2. **Never probe with a throwaway socket.** Liveness is a property of the owned
   connection's recent history, not a separate connect.
3. **Make a stale value say so.** A cached reading served after a failed read must be
   labelled stale with its age, never presented as current.
4. **Fail honestly** — reuse the phase 3 `Outcome{ok|failed|unknown|skipped}` rather
   than inventing a second vocabulary for the same distinctions.
5. **Mocks cost nothing.** A mock gateway must not open, probe, or account for any
   Modbus socket.
6. **Measurable before and after.** Per-gateway counters, so the claim "this reduced
   churn" is checkable rather than asserted.

**Non-goal: a connection *pool*.** The question asked for pooling; the answer is that
pooling is the wrong shape here. A pool exists to serve concurrent callers from several
sockets. Against a device whose connection limit is unknown and probably small, more
sockets is the failure mode, not the remedy. What we want is the opposite: **exactly one
connection per gateway, with callers queued behind it.** That is also what the Modbus
Bridge concluded (§5.2) and what Home Assistant's `ModbusHub` does — one client per hub,
every call serialised through one lock, a failed call logged and returning `None`
*without* tearing the connection down.

---

## 4. Design

### 4.1 One session object per gateway, per channel

A `GatewaySession` owns the connection for one gateway on one channel
(`local` :9000, `modbus` :502). It is created on demand, holds the socket, and
serialises every caller through a single lock. Nothing else opens a socket to that
gateway.

Keyed by `(gateway_id, channel)` in the existing gateway registry — not global, because
two gateways are genuinely independent and must not queue behind each other.

**Why a lock and not a pool:** the device is the scarce resource, not our CPU. Queuing
two callers behind one socket is correct behaviour against a device that may only
tolerate one. Latency under contention is the price, and it is visible (§4.6) rather
than hidden.

### 4.1a The Modbus half of §4.1 is blocked on a library change

This must not be glossed. A `GatewaySession` that owns a socket achieves **nothing** on
the Modbus channel while `pysunspec2` opens and closes its own connection per read and
per write. Holding our socket open underneath that simply adds an idle socket to the
device's table.

So the Modbus side of this design splits in two:

| Part | Owner | Available now? |
| --- | --- | --- |
| Stop making unnecessary *requests* (delete the probe, skip mocks, de-duplicate status calls) | us | **yes** — and it is the only Modbus-side lever we hold |
| Hold one connection across requests | `franklinwh-modbus` / `pysunspec2` | **no** — needs their change |

That is an argument for sequencing, not for waiting: request reduction is worth doing on
its own, is independently measurable, and does not depend on anyone else's schedule. The
session object should be built for the **local** channel first, where we own the whole
path, and extended to Modbus when the library can keep a socket.

### 4.2 Connection lifetime and liveness

* **Opened lazily**, on first use, not at boot. A gateway nobody reads costs nothing.
* **Kept open** across calls. No close-per-read.
* **Liveness is inferred, never probed.** The session already knows when it last
  succeeded; that answers "is this up" without a socket. This deletes the
  `port_open × 3` probe outright, and with it the "hammer a dead device harder"
  behaviour.
* **Idle close** after a configurable idle period, so an untouched gateway does not
  hold a socket on the device indefinitely. Default proposed: 10 minutes. The right
  value depends on U1; stated here so it is a decision, not an accident.
* **Reconnect is bounded by backoff**, and a failed reconnect does not immediately try
  again — a reconnect storm is how a brief outage becomes a sustained one.

### 4.3 Where staleness lives

Phase 2b already records per-leg link history: first/last success, consecutive
failures, outage rows, and a 3-strike debounce before a link is called down. **The
session reports into that, rather than growing its own parallel notion of health.**

Served values carry `{value, as_of, stale}`. `stale` is set when the last read failed
and a cached value is being used. The Modbus Bridge found the same defect from the
other side (its C8: "Derived 4 battery key(s) from M713 model cache" published as
current). A cached number presented as live is worse than a gap, because nothing
downstream can tell.

### 4.4 Timeouts, retries and outcomes

No new retry machinery. Phase 3's `resilience.call` already provides deadline, retry
classification, and the `ok / failed / unknown / skipped` verdict — including the rule
that **an ambiguous write is never retried**. The session wraps its I/O in that.

What the session adds is the **connection-level** distinction `resilience` cannot see:

| Situation | Verdict | Connection action |
| --- | --- | --- |
| Read succeeded | `ok` | keep |
| Read failed, socket healthy (device said no) | `failed` | **keep** — do not tear down over a refusal |
| Transport error / timeout | `failed` | mark suspect; reconnect on next use, with backoff |
| **Write** timed out after sending | `unknown` | **keep**, never auto-retry, report loudly |

"Do not tear the connection down over a failed call" is taken from `ModbusHub` and is
the opposite of what we do today, where any exception discards the client and the next
call pays for a full rescan.

### 4.5 Mocks

A mock gateway (`is_mock`) gets **no Modbus session at all** — not a failed one, not a
probe. `modbus_502` becomes `None` ("not applicable") rather than `False` ("tried and
failed"), consistent with the rule established in phase 2b that a leg which was never
measured is reported as *not measured* rather than omitted or failed.

Mocks keep a local-channel session, because that is what they emulate and the emulator
is the only way to test the session logic without touching the live aGate.

### 4.6 Observability

Per gateway, per channel: connections opened, reads, read failures, timeouts,
reconnects, failed reconnects, time spent waiting on the lock, and current socket age.
Surfaced on the Network tab beside the existing Link history card.

The lock-wait counter is the one that matters for this design: it is how we find out
whether serialising callers behind one socket costs anything in practice.

---

## 5. What this does not fix

* **Other clients.** We cannot stop the Modbus Bridge or Energipay opening connections,
  and should not try. We can count ours honestly and show other visible connections for
  correlation — the Modbus Bridge's §5.3 takes the same position.
* **The library's per-read connect/close.** Our session can hold a socket, but if
  `pysunspec2` opens its own per `model.read()`, holding ours achieves nothing on that
  path. **This is the part that needs fwh-modbus, and it is the single biggest lever.**
  Until it changes, our Modbus-side gain is limited to deleting the probe and the
  duplicate status calls.
* **Whether any of this is the cause of the timeouts.** It is a plausible contributor.
  U1–U4 decide it. Shipping the design and *then* finding the timeouts unchanged would
  still leave us better off, but we should not claim a cure we have not measured.

---

## 6. Proof, before and after

**Measure first, and for long enough.** The Modbus Bridge added a §5.4 "Measurement
(Phase 0b)" that ships *before* any fix and requires **at least 7 days of baseline**
before anything changes. Adopted here, and the reason is worth stating: without it,
"this reduced churn" is a claim about a number nobody wrote down. Seven days also
covers a weekday/weekend cycle and at least one of the daily timeout peaks.

What to record per gateway per hour, for both channels — the same shape they are
using, so the two bridges' numbers can be compared rather than merely coexisting:

* requests ok / timeout / error, **with the exception class**;
* latency p50 / p95 / max;
* connections opened, per path;
* reconnects, failed reconnects, rescans;
* data freshness (age of the newest good value).

Phase 2b's link history already records a subset of this per leg. This extends it
rather than starting a second table.

1. **Baseline, now:** socket-state census and timeout counts per hour, with the three
   clients running as they are. Partly captured above; needs **7 days**, not 24 h.
2. **Answer L1 ourselves:** find what leaves sockets in `CLOSE_WAIT`. This is our bug
   regardless of the rest of the design, and it is the cheapest thing here.
3. **Emulator first.** Exercise session reuse, idle close, reconnect backoff and
   staleness against the in-process mock. No live aGate.
4. **Coordinated live window** for U1–U4, run jointly with the Modbus Bridge session —
   their experiments E0–E4 answer our unknowns too, and running them twice against one
   device would itself be contention.
5. **After:** repeat the census. The acceptance test is a drop in connections opened per
   minute, with no increase in failed reads.

---

## 7. Decisions needed from the owner

1. **Should this bridge use Modbus on the reference aGate at all?** It is a *secondary*
   channel for us — it provides the battery ratings, the VPP/force truth, and the
   dispatch path. The local API cannot replace the VPP truth. But if contention is
   hurting the Modbus Bridge, which is the primary controller, the cheapest fix
   available today is for us to poll it less or not at all. That is a priority call
   between two of your own systems, not a technical one.
2. **Idle-close timeout** (proposed 10 minutes) and whether a gateway should hold a
   socket when nothing is reading it.
3. **Sequencing.** §4.5 (mocks) and deleting the `port_open × 3` probe are small,
   independent and reduce churn immediately. The session object is larger. They need
   not land together.
4. **Coordinating the library change** with fwh-modbus (§5), which is where the largest
   reduction is, and which is not ours to make.

---

## 8. Separately: a latent breakage found while reading this code

Not part of this design; recorded because it will bite.

`src/` imports `franklinwh_local` in **23 places** and the new name in **none**. The
library renamed itself in 0.4.0, and the shim says: *"will be removed in 0.5.0"*. The
bridge runs on a deprecation shim that is scheduled for deletion by a package we
ourselves publish. It emits a `DeprecationWarning` on every import today and will be a
hard `ImportError` at 0.5.0.
