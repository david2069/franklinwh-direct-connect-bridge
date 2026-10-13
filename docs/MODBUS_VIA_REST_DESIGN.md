# Retiring direct Modbus TCP — delegate to the Modbus Bridge REST API

**Status: DESIGN for review. No code.** Written 2026-10-13.

Owner's direction: retire this bridge's **direct** Modbus TCP and reach the same
capabilities through the **Modbus Bridge's REST API**. Interim, pending FranklinWH's
**Modbus API 2.0**, which will be built on an async Modbus connection library.

Companions: `CONNECTION_DESIGN.md` (which this largely supersedes for the Modbus half),
`MODBUS_SUSPEND_PLAN.md` (whose Phase A shipped and makes the switch real).

---

## 1. Most of this already exists

`providers.py` was built for exactly this and is further along than the phrasing
"replace our Modbus" suggests:

* `dispatch_provider()` already resolves **Modbus Bridge REST → franklinwh-modbus
  library**, in that order of preference.
* `_dispatch_via_modbus_bridge()` already stages power / duration / target-SoC and
  fires `battery_command` over REST.
* The library path is already `NotImplementedError` — *"dispatch via the
  franklinwh-modbus library isn't wired yet; install a Modbus Bridge, its software
  watchdog is what makes force charge/discharge safe"*.

So for **dispatch**, REST is already the preferred and only implemented route. The work
is not "build a REST client"; it is to make REST the *sole* path and remove the direct
TCP that remains for everything else.

---

## 2. What direct Modbus is still used for

| Capability | Where | Replaceable over REST? |
| --- | --- | --- |
| Force dispatch + Release | `battery_control.execute` | **Already is** — `providers.dispatch` prefers REST |
| Max charge / discharge ratings | `cached_ratings` → SunSpec M702 | **Needs an endpoint** — see §5 |
| `:502` reachability probe | `client.summary` | **Delete** — it exists to tell us whether *our* direct path works |
| VPP / external-control detection | — | **Gone already.** Moved to local cmdType 1707 on 2026-10-12 |
| Boot reconcile of an interrupted dispatch | `battery_control.reconcile_interrupted` | Follows dispatch |

Three capabilities, one of which is already delegated and one of which stops being a
question once we no longer have a direct path to probe.

---

## 3. Why this is the right interim, not a workaround

**It fixes the two-masters problem by construction.** Today two processes write M704 on
the same aGate with no coordination between them — the Modbus Bridge's own
connection-behaviour notes confirm it holds no lease, no lock and makes no exclusivity
assumption. Delegating means **one process owns the register**, and its watchdog becomes
authoritative rather than racing ours. That is the correct topology, not a compromise.

**It removes our worst connection behaviour outright.** No `pysunspec2` opening a socket
per model read, no full rescan on reconnect, no `CLOSE_WAIT` leak. Measured before Phase
A: 38 `TIME_WAIT` + 4 `CLOSE_WAIT` to `:502` in one minute, with zero ESTABLISHED. After
delegation that is structurally zero, not merely reduced.

**It makes `CONNECTION_DESIGN.md` §4.1a moot for us.** That section records the Modbus
half of the session design as *blocked on a library change we do not own*. Delegation
removes the dependency rather than waiting on it.

---

## 4. Availability — the same failure mode we already have

The obvious objection is "then we depend on the Modbus Bridge being up". The owner's
point, and it is correct: **that is no different from the gateway not being connectable.**

The bridge already has a complete vocabulary for *this capability is unreachable right
now*:

* `providers.DispatchUnavailable` → **503** with a reason;
* phase 2b's link history records outages per leg with a debounce, so the REST
  dependency becomes another leg rather than a new concept;
* phase 3's `Outcome{ok|failed|unknown|skipped}` already distinguishes "it did not
  happen" from "we do not know";
* ratings already fall back to the `battery_max_power_kw` constant.

So this is **not a new class of failure**. It is an existing one with a different host,
and every mechanism for reporting it is already built. The honest framing: the set of
things that can make force dispatch unavailable grows by one member; the *behaviour*
when it is unavailable does not change.

What must not happen is a silent degradation — an unavailable REST provider must read as
unavailable, never as a quiet no-op. Phase 3 already enforces that for scheduler
actions: a disabled or unreachable subsystem is `SKIPPED` with a reason, not `OK`.

---

## 5. The one real gap: ratings

`cached_ratings` reads **SunSpec M702** for the model-correct max charge/discharge. That
is a **read**, and the Modbus Bridge's REST surface we use today is command-oriented
(`battery_command*`). Whether it exposes ratings is **not established** — it must be
asked, not assumed.

Three options, in order of preference:

1. **An endpoint on the Modbus Bridge.** It already holds the SunSpec model data; it is
   one read it is making anyway. Costs us nothing and keeps one Modbus client.
2. **The declared constant.** `battery_max_power_kw` already exists as the fallback and
   is what we use when Modbus is unavailable today. Loses model-correctness for
   mixed-hardware sites.
3. **Keep a direct read purely for ratings**, hourly, behind the switch. Defeats the
   point — one TCP connect an hour is small, but it reintroduces the thing being
   retired, and "small" is how the current churn started.

**Recommend 1, with 2 as the fallback.** This needs asking the Modbus Bridge session
before anything is planned around it.

---

## 6. Design shape

**Keep the provider abstraction and widen it.** `providers.py` already treats dispatch as
a capability with ranked candidates. The same shape covers ratings, and will cover
**Modbus API 2.0** when it arrives — which is the point of designing it this way rather
than hard-wiring REST:

```
capability "battery.dispatch" :  [modbus-bridge REST] → (future: Modbus API 2.0)
capability "battery.ratings"  :  [modbus-bridge REST] → [declared constant]
```

**Retire by disabling, not deleting.** The direct-Modbus code stays behind the switch
Phase A just made real. If REST disappoints, flipping back is a toggle rather than an
archaeology exercise. Delete only once the REST route has survived a few weeks and the
owner says so.

**The switch changes meaning.** Today "use Modbus from this bridge" means *our direct
TCP*. Afterwards it should mean *our direct TCP fallback*, with REST independent of it —
otherwise switching Modbus off would also disable dispatch, which is the opposite of the
intent. Worth getting right in the UI wording at the same time.

---

## 7. The future: Modbus API 2.0, and async

FranklinWH's **Modbus API 2.0** will be based on an **async** Modbus connection library.
That matters for two decisions taken earlier:

* **It confirms the provider abstraction is right.** API 2.0 becomes a third candidate
  behind the same capability, not a rewrite of every call site.
* **It is the first real argument for async in this codebase.** The earlier conclusion —
  that async buys nothing while device I/O is deliberately serialised behind one
  connection — still holds for *today's* sync library. An async-native upstream changes
  the calculus, because the cost of bridging (`asyncio.to_thread` at every boundary)
  inverts: it becomes the async client that is awkward to call from sync code.

**What follows for now:** do not convert anything to async pre-emptively. Do keep the
provider boundary clean, because that boundary is where an async client will be adapted,
and a tidy seam there is the whole difference between adopting API 2.0 and rewriting for
it.

---

## 8. Phasing

| Phase | Change | Leaves behind |
| --- | --- | --- |
| **A** ✅ | The Modbus switch actually stops our TCP (shipped) | "off" means off, and the footprint is measurable |
| **B** | Ask the Modbus Bridge about a ratings endpoint (§5) | the one unknown closed before design hardens |
| **C** | Route ratings through the provider; constant as fallback | the last *read* leaves direct Modbus |
| **D** | Default the direct path OFF; REST becomes the normal route | zero `:502` sockets from this container in normal operation |
| **E** | Delete the `:502` probe | one less thing that can mislead a contention measurement |
| **—** | Delete direct Modbus entirely | **only on the owner's word**, after REST has proven itself |

B and C are small. D is a default change, not code. E is a deletion. Nothing here is
large, which is itself an argument for doing it: the expensive part — the REST dispatch
client — was written months ago.

---

## 9. Decisions needed

1. **Ratings route** (§5) — endpoint, constant, or keep one hourly direct read?
2. **Does the Modbus switch keep governing REST, or only the direct path?** (§6).
   Recommendation: only the direct path.
3. **When does direct Modbus get deleted rather than disabled?** Recommendation: not on
   a date, but after the REST route has carried a real force dispatch and a real
   failure, with both visible in the audit trail.
