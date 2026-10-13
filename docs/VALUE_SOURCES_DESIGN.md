# Where a value comes from — constants, computed, and mapped

**Status: DESIGN for review. No code.** Written 2026-10-13.

Owner's observation, looking at the Automation Constants card: *"These could use defined
constant, computed fields or integration mapped fields."*

That is a generalisation of something the bridge **already does three times, three
different ways**, and it is the piece that makes `Settings → Integrations → Mapping`
load-bearing rather than diagnostic.

---

## 1. Three mechanisms already exist, and none of them says which it is

| Constant | How its value arrives today | Visible to the user as |
| --- | --- | --- |
| `min_discharge_soc` | typed by the owner | a number |
| `battery_capacity_kwh` | a **Fill** button: aPower model × count, copied **once** | a number, indistinguishable from a typed one |
| `battery_max_power_kw` | SunSpec **702 overrides it at runtime** when Modbus is enabled | a number, with the override explained only in prose underneath |

Three behaviours, three implementations, and **the field itself looks the same in all
three cases**. A reader cannot tell whether `27.2` was typed last March, filled once from
a model table, or is being overridden live by a device read. They also behave differently
when the source goes away: a *Fill* value persists silently, while the 702 override
silently stops overriding when Modbus is switched off — which, since Phase A, is a thing
the owner now does deliberately.

**That is the defect.** Not that the mechanisms exist, but that the value hides which one
produced it.

---

## 2. The model

Every constant gains a **source**, one of:

| Source | Means | Behaviour when unavailable |
| --- | --- | --- |
| `constant` | the owner typed it | always available |
| `computed` | derived from an expression over other values | falls back, and says so |
| `mapped` | read live from an integration (a probed field) | falls back to the declared constant, and says so |

A mapped value therefore has **two** numbers: the live reading and the fallback. Both
should be visible, because "5 kW" means something different when it is the fallback than
when it is the device's own rating.

### Why `mapped` is not simply "read it live"

The lesson from `cached_ratings`: Modbus can be switched off, unreachable, or absent, and
the system must keep working. So a mapped source is *preferred*, never *required* — the
declared constant remains the floor. This is the same `ok / failed / unknown / skipped`
discipline phase 3 brought to actions, applied to values.

---

## 3. What this buys

* **Provenance in the UI.** A field shows its source, its live value, and when it was
  last read. `const.*` sensors can carry the same, so a schedule's `Explain` can say
  *"max power 5 kW (fallback — Modbus off since 22:58)"* rather than just `5`.
* **One mechanism instead of three.** The *Fill* button becomes `computed`, the 702
  override becomes `mapped`, and typed values stay `constant`. Nothing new is invented;
  three special cases collapse.
* **The Probe is reused, not rebuilt.** A `mapped` source is exactly a mapping row, and
  the Mapping page already reads one live and shows the request that fetched it. The
  source picker becomes "choose a mapping", and testing it is the button that is already
  there.
* **Switching Modbus off stops being silent.** Today the 702 override just quietly stops.
  With a declared source, the field shows it has fallen back.

---

## 4. Shape

* **Spec, not hard-coding.** `constants.spec()` already describes each constant's bounds;
  it gains `sources` — which of the three are permitted for that constant, and the
  default. Not every constant should be mappable (`min_discharge_soc` is a *policy*, not
  a *reading*), and the spec is where that judgement belongs.
* **Resolution order is explicit and recorded**, not implied by whichever code path ran
  last. Resolve → `{value, source, live, fallback, as_of, stale}`.
* **Computed stays deliberately small.** A tiny arithmetic expression over named values
  (`model_kwh * count`), not a language. The moment it needs branching it has become
  automation, and the scheduler already exists for that.
* **Never guess the source.** An unmapped constant is `constant`. Inferring a source from
  whether a value happens to match a device reading would be the same class of error as
  inferring phase topology from voltage.

---

## 5. Risks, and the one that matters

**A mapped constant can change under a running schedule.** `battery_max_power_kw` feeds
the ETA/headroom derived sensors, which feed conditions. If a mapping starts reading a
different value mid-window, a rule's behaviour changes without the rule changing.

That is not an argument against mapping; it is an argument for **recording the value used
at the moment of a decision**, which the occurrence row already does for outcomes and
could do for inputs. Worth settling before mapping anything a scheduler reads.

Lesser risks: a mapped source adds a device read to a path that currently has none (use
the existing caches, not a fresh read per evaluation); and a `computed` expression over a
`mapped` input can fail in two places at once, so the fallback must be per-source rather
than per-field.

---

## 6. Open questions

1. **Which constants may be mapped at all?** `battery_capacity_kwh` and
   `battery_max_power_kw` are readings and clearly can. `min_discharge_soc` is a policy
   and clearly cannot. The rest need a judgement each.
2. **Does a mapped value re-read on a cadence, or only on demand?** Cadence costs device
   traffic — the thing this bridge has spent a week reducing.
3. **Should `Explain` show the source?** It is the place a user asks "why did this fire",
   and "because max power read 5 kW from a fallback" is often the answer.
