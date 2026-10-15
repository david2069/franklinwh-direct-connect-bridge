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
| **B0** | **Authentication (#56)** — credentials, session, honest availability | the REST path can actually be used |
| **B1** | Confirm dispatch via `dispatch-outcomes`, never via `ok` | a dispatch that did not happen cannot read as success |
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

---

## 10. Review, 2026-10-15 — what measurement since changes

Reviewed before merge. The recommendation stands; three claims above are now out of date
against measurement and are corrected here rather than quietly edited, because the original
reasoning is part of the record.

### §3 overstates the connection benefit. The churn MOVES, it does not vanish.

§3 says delegation makes the bad connection behaviour "structurally zero … not merely
reduced", and names "no `CLOSE_WAIT` leak" among the things removed. That is true **of this
container** and false **of the system**.

Measured on 2026-10-15, 10:00–10:15 AEDT, sampling the Modbus Bridge's own socket table
every 2 s while it polled normally:

- **2–3 concurrent `ESTABLISHED`** to the aGate's `:502`, peak 3
- **6–7 `TIME_WAIT`** at essentially every sample — continuous churn, a connection per poll
- **one `CLOSE_WAIT`, persistent** from 10:02:29 to the end of the watch, same inode, remote
  closed and never closed locally

The `franklinwh-modbus-bridge` session traced the same pattern from inside its container and
filed the `CLOSE_WAIT` as **its #64 — real and unexplained**. The churn is partly inherent:
`franklinwh-modbus` does per-call TCP via `pysunspec2`, measured by that session
(reproduction check C2, 2026-10-13, in its PR #33), so "one Modbus client" still opens a
connection per read.

**This does not change the recommendation.** Zero sockets from this container is still the
right outcome, and one churning client beats two. But the honest claim is *"we stop
contributing to it"*, not *"it stops happening"* — and we would be delegating to a client
with an open connection defect of its own, which is worth knowing before depending on it.

### §3's two-masters argument is stronger than it was, with a caveat

A **third** potential writer to the aGate's Modbus server is now documented: FranklinWH's
AU & NZ Commissioning Guide (p. 25) commissions **Voltello LinkPro** against it for CSIP-AUS
export control — see `docs/MODBUS_EXPORT_CONTROL.md`. So consolidating our own writes is
more clearly right.

The caveat is the converse: **delegation does not make the Modbus Bridge the sole writer**
on a site with a LinkPro bound. "One process owns the register" holds for us and for that
bridge; it does not hold for the gateway. Nothing in our design can make it hold.

### §5's ratings question can be asked now, and §8 Phase B is the gate

Unchanged and still the one real unknown. The `franklinwh-modbus-bridge` session is active
and has answered harder questions than this today; Phase B is a message, not an
investigation.

### The design has no answer for AUTHENTICATION, and the REST path has never had one

Asked by the owner on review, and it is the largest gap found: **the Modbus Bridge requires
credentials and we send none.**

Their `/api/command` is gated — `_user: dict = Depends(_REQUIRE_CONTROL)`
(`franklinwh-modbus-bridge`, `api/ui.py:148`) — with a `POST /api/auth/login` session flow.
Our `_post_command` (`providers.py:137`) sends a bare JSON POST with no cookie, no token and
no login anywhere, and `config.py` has **only** `modbus_bridge_url` — there is no credential
setting to populate.

Worse, `available` is measured by an **unauthenticated** `GET /api/health`, which a properly
secured Modbus Bridge answers happily. So the provider reports **ready** for a path that
would 401 at the first command — which is the failure §4 explicitly forbids, arriving through
the availability check rather than the dispatch.

So §1's "for dispatch, REST is already the preferred and only implemented route" is accurate
about the code and misleading about reality: **implemented, never able to authenticate.**

Filed as **#56**. It is a prerequisite for Phase B, not a detail of Phase C: credentials in
config *and* in the add-on schema, a login session with re-auth on 401, availability probed
through something that actually requires authorisation, and "reachable but not authorised"
reported as its own state — a wrong password and a down host need different fixes.

### `ok` from `/api/command` is not a per-call result — and there is a better signal

Found while testing the authentication gap above, confirmed by the `franklinwh-modbus-bridge`
session and filed as **its #97**.

An authenticated POST with a **slug that does not exist** returns `{"ok": true, "result":
"Sent"}`. Their correction to my first reading of the mechanism, which was wrong: `ok` is not
inherited from the previous command. `handle_command` sets `last_success = True` as an
**optimistic default** at the start of every call, and only a handler that runs *and fails*
flips it. An unknown slug merely logs a warning, so `true` survives. `result` separately
**can** be stale text from an earlier call, falling back to the literal `"Sent"`.

They report the same for an unknown `battery_command` **action** (e.g. `"Force Fly"`), and
for `POST /api/gateways/{id}/command`.

**Their guidance, which we should follow: treat `ok` from `/api/command` as NOT a per-call
result.** The fix proposed in their #97 is exactly the shape we would want — unknown slug
`400`, a genuine per-call `{ok, result}`, and staging slugs returning `"Staged …"` to mean
*stored, not dispatched* — but it is unbuilt and is their owner's call.

#### What to use instead, today

`GET /api/gateways/{id}/dispatch-outcomes` — **one row per command**, with the bridge's own
read-back verification. Verified on `fwhbridge-app`, 2026-10-15:

```json
{"action": "Force Discharge", "requested_w": -5000, "actual_w": 4900.0,
 "state": "released", "verified_at": 1791961299.0, "requester": "schedule:sch_…",
 "reason": "reason=Release; Released"}
```

`state` is `verified` / `not_effective` / `failed` / `released`, with requested against actual
power. That is a far stronger confirmation than any command reply would be: it says whether
the battery *did the thing*, not whether the request was accepted.

**This improves the design rather than blocking it.** §4 demands that an unavailable provider
never read as a quiet no-op; `dispatch-outcomes` satisfies that demand better than `ok` ever
could, and it exists now. So the rule for Phase C is: **fire by command, confirm by outcome,
never trust `ok`.** Phase 3's `Outcome` vocabulary maps onto their states directly — which is
the mapping to build, not a workaround for a defect.

### What did not change

§4's availability reasoning, which is the part most likely to be challenged, is unaffected:
the REST dependency is another leg with existing vocabulary, not a new class of failure.
§6's provider shape and §7's conclusion on async are untouched by anything measured today.
