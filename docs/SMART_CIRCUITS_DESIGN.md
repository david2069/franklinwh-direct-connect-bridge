# Smart Circuits — local API & UI design evaluation

**Status:** design, not implemented · **Filed:** 2026-09-13
**Evidence:** live reads of 1409 / 1411 / 1401 from a reference aGate,
2026-09-13; `franklinwh-cloud/docs/`; FWHAI Smart Circuits screenshot.

---

## 1. What the local channel actually exposes

Three cmdTypes. All three were read live; the results decide the design.

| cmd | name | verdict |
| :--- | :--- | :--- |
| `1409` | `smart_circuits` | **The source of truth.** Names, mode, SoC cutoff, protected-load flag *and* the schedule. |
| `1411` | `smart_circuit_meter` | Live V / I / P + cumulative energy per channel. |
| `1401` | `smart_circuit_schedule` | **Do not use — see §1.2.** |

### 1.1 `1409` carries the schedule, in the modern format

Real response from Circuit 1:

```json
"Sw1Name": "Circuit 1", "Sw1Mode": 0, "Sw1ProLoad": 0,
"Sw1SocLowSet": 53, "Sw1AtuoEn": 0, "Sw1Freq": 0,
"Sw1TimeEn":  [1, 1, 0, 0],
"Sw1TimeSet": [1, 0, 1, 0],
"Sw1Time":    ["2026-06-19 16:02", "2026-06-19 17:03",
               "2026-06-19 20:11", "2026-06-19 20:12"]
```

Four schedule slots per circuit: `TimeEn` = slot enabled, `Time` = the datetime as a
**V2 string**, `TimeSet` = per-slot flag (open/close pairing — slots read as
on/off/on/off, matching `[1,0,1,0]`).

> ### ⚠️ RETRACTED 2026-09-14 — see §11
>
> The claim below ("local schedule writing is reachable here and is not reachable from
> the cloud library") was the headline of this document and it is **wrong**. Live testing
> proved the aGate accepts 1409 schedule writes and silently discards them. Schedules are
> **readable** locally, not writable. The paragraph is kept for the record.

`franklinwh-cloud/docs/API_COOKBOOK.md:1607` states the cloud library *cannot write
these*:

> "Until the exact V2 payload constructor is fully mapped natively, schedules should only
> be modified manually or toggled dynamically using boolean switches…"

The local channel hands us the whole block as plain JSON, and we already have a proven
full-block read-modify-write against 1409 (`set_smart_circuit`, cmd 1409 `opt:1`). So
**local schedule writing is reachable here and is not reachable from the cloud library** —
the strongest argument for building this in the bridge rather than deferring to Automations.

### 1.2 `1401` is a decoy — do not build on it

The catalog describes 1401 as the per-switch schedule. The live read says otherwise: every
`sw1`–`sw3` field is zero or empty while 1409 shows a real, populated schedule, and the
response carries a fourth block that is plainly uninitialised memory:

```json
"sw4Mode": 5, "sw4AtuoEn": 2, "sw4Freq": 809119792,
"sw4TimeEn": [859451440, 809120816, 16, 822083584],
"sw4Time": [":0", ":0", "0", "3"]
```

Those integers are ASCII bytes reinterpreted as `int32`. 1401 parses a 4-switch struct the
firmware never fills. Reading it is harmless; **writing to it is not something to attempt**.

*Action:* the `catalog.py` entry for 1401 oversells it and should be corrected to name 1409
as the schedule source and mark 1401 unimplemented.

### 1.3 `1411` metering, and what "energy metrics" really means

```json
"Sw1Volt": 1020, "SW1Curr": 0, "SW1ExpPower": 0, "SW1ExpEnergy": 0,
"Sw2Volt": 0,    "SW2Curr": 0, "SW2ExpPower": 0, "SW2ExpEnergy": 0,
"CarSWCurr": 1,  "CarSWPower": -3,
"CarSWExpEnergy": 10077, "CarSWImpEnergy": 15458,
"freq": 499
```

- Per-circuit **power** (`ExpPower`) and **cumulative energy** (`ExpEnergy`) exist — so
  "Current draw / Energy today" in the FWHAI card is reproducible, **except** that these are
  lifetime counters, not daily. A daily figure needs the bridge to **difference the counter
  across midnight** — which is exactly what the bridge's metrics DB is for. Do not claim
  "today" from a raw read.
- `freq: 499` → 49.9 Hz confirms the ÷10 scaling. But `Sw1Volt: 1020` → 102.0 V does **not**
  match AU 230 V mains. Both circuits are currently OFF, so this is unverified: **confirm the
  voltage scale with a circuit switched on** before showing volts in the UI.

---

## 2. The region question: 3 circuits (US) vs 2 (AU)

Cloud `CAPABILITY_RESOLUTION_SPEC.md` Rule 2 is explicit: `country_id == 3` (AU) ⇒
`circuit_count = 2`, "Channel 3 controls are ignored or hidden". Rule 1 forces
`has_v2l = False` for AU.

**The local channel gives no clean discriminator.** Two problems:

1. **1409 always returns three blocks.** This AU gateway reports `Sw3Name: "Circuits 3"`,
   `Sw3SocLowSet: 20`, `Sw3Freq: 15`, with `Sw3Time` all `"2000-01-01 …"` — factory defaults
   for a channel that was never configured. Presence of `Sw3*` proves nothing.
2. **The cloud's discriminator is missing locally.** Cloud reads `modeChoose` from 311
   (`modeChoose: 3` ⇒ 3-circuit). Our 1409 response has **no `modeChoose`** — only
   `SwMerge: 0` (the US multi-aGate merge flag).

And the obvious local fallback — "count the metering channels in 1411" — is a trap:
`GENERATOR_V2L_API.md:215` states **the CarSW port *is* Sw3** in the 311 payload. So 1411's
three channels are `SW1`, `SW2`, `CarSW(=Sw3)` — the third circuit is metered under the
`CarSW` name, not `SW3`. Counting `SW<n>` keys yields 2 on any unit, US or AU.

Worse, this AU unit reports `CarSWExpEnergy: 10077` / `CarSWImpEnergy: 15458` — non-zero
lifetime counters on a channel AU is supposed not to have. Stale registers or a wired
channel; **one device cannot tell us**.

### Recommendation

Do **not** auto-detect from the payload shape. Instead:

1. **Config-first:** a `SMART_CIRCUIT_COUNT` setting (`auto` | `2` | `3`), default `auto`.
2. **`auto` = a stated heuristic, not a guess dressed as a fact:** treat circuit 3 as absent
   when its schedule is entirely factory-default (`Sw3Time` all `2000-01-01`) **and** it has
   never been renamed from the default. Surface it in the UI as *"Circuit 3 — not detected
   (override in Settings)"* rather than hiding it silently.
3. **Never hide the raw data.** `/api/cloud/smart_circuits_info` keeps returning all three
   blocks verbatim; region logic belongs in the presentation layer only.

> **Defect filed against `franklinwh-cloud`** — [issue #7](https://github.com/david2069/franklinwh-cloud/issues/7): `API_COOKBOOK.md:1610` claims *"AU grids
> standardise on 3 physical outputs per aGate with V2L"*. That contradicts
> `CAPABILITY_RESOLUTION_SPEC.md` Rules 1 and 2 (AU = 2 circuits, no V2L) and
> `DISCOVER_IMPLEMENTATION_PLAN.md:102` (AU SC 302 has no V2L port). The spec and the
> hardware agree; the cookbook prose is wrong and should be corrected.

---

## 3. Where the bridge stands today

Already built:

- `client.read(…, "smart_circuits")` → 1409, and `set_smart_circuit(circuit, on)` (full-block
  RMW + read-back verify).
- `cloud_compat.smart_circuit_detail()` — already maps the **V2 schedule arrays**
  (`time_enabled` / `time_schedules` / `time_set`). The data is reaching the API today.
- `/api/cloud/smart_circuits` and `/api/cloud/smart_circuits_info`.

Gaps:

| gap | note |
| :--- | :--- |
| `smart_circuits_map()` hardcodes `range(1, 4)` | Emits a phantom circuit 3 on AU. First thing to fix. |
| No 1411 metering anywhere | No power or energy per circuit. |
| Writes limited to on/off | No schedule, no SoC cutoff, no load limit. |
| **No UI at all** | Smart Circuits has no tab. |

---

## 4. Proposed API

Noun-scoped, matching the cloud CLI convention we settled on for `EPIC-CLI-ALIGN`.

```
GET    /api/circuits                  → [{id, name, on, mode, pro_load, soc_cutoff{…},
                                          power_w, energy_kwh, volts, amps, present}]
GET    /api/circuits/{id}             → one circuit, incl. schedule slots
POST   /api/circuits/{id}/power       {on: bool}            # exists as set_smart_circuit
PUT    /api/circuits/{id}/schedule    {slots: [{enabled, start, end}]}
PUT    /api/circuits/{id}/soc_cutoff  {enabled: bool, soc: int}
```

Design rules, all of them consequences of §1:

- **One 1409 read + one 1411 read per refresh, in a single aGate session** — the same pattern
  as `battery()`. Never one session per circuit.
- **Every write is a full-block RMW on 1409 with read-back verification**, reusing the proven
  `set_smart_circuit` path. There is no partial write to 1409.
- **Slot model:** expose 4 slots as 2 on/off *pairs* (`TimeSet` `[1,0,1,0]`), not 4 opaque
  datetimes. Validate before writing — the firmware will happily accept an end before a start.
- **Energy is a lifetime counter.** `energy_kwh` is reported as such; a "today" figure is
  derived by the bridge from stored samples, and is `null` until there is a midnight baseline.
- **Schedule writes are the risky half.** They must land behind the same confirm-and-verify
  treatment as other writes, and the first hardware test should use circuit 2 ("Test Switch"),
  not the live Circuit 1.

---

## 5. Proposed UI

A **Smart Circuits** tab in the sidebar, between Control and Battery (mirroring FWHAI's
ordering), with per-circuit cards:

```
● Circuit 1                                   [ ON ]
  CURRENT DRAW            ENERGY (TODAY)
  0 W                     0.00 kWh
  ────────────────────────────────────────────────
  Circuit Power                          (toggle)
  Mode: Schedule · SoC cutoff 53%          [Edit]
```

Beyond FWHAI — and the reason to build it rather than defer to Automations:

- **Schedule editor** on the card's `Edit`: two on/off windows per circuit, enable toggles,
  a read-back confirmation. This is the capability the cloud library documents itself as
  lacking, and FWHAI deliberately omits.
- **SoC-cutoff control** (`SocLowSet` + `AtuoEn`) — cloud parity with
  `set_smart_circuit_soc_cutoff`.
- **Absent circuit shown, not hidden** — per §2, a greyed "not detected" card with a Settings
  override, so an AU user sees *why* there are two.

### Relationship to the Schedule engine

`SCHEDULE-AND-AUTOMATIONS` is the bridge's own scheduler and does not exist yet. The 1409
schedule is different in kind: it runs **on the gateway**, so it keeps working when the bridge
is down. These are complementary, and the UI must not blur them —

> "Schedules set here run on the aGate itself and continue if the bridge stops. Bridge
> Automations are more flexible but require the bridge to be running."

When the engine lands, a circuit driven by a bridge automation should show that on the card so
two schedulers fighting over one relay is visible rather than mysterious.

---

## 6. Open questions

1. **Voltage scale** (§1.3) — resolve with a circuit switched ON.
2. **`Sw1Freq` / `Sw3Freq`** (0 and 15) — unexplained. Not "frequency" in the 49.9 Hz sense.
3. **US 3-circuit shape** — unverifiable without US hardware. The region heuristic must stay
   overridable for that reason alone.
4. **`SwMerge`** — US merged circuits across chained aGates. Out of scope; read-only for now.
5. **`Sw1MsgType`** — written as the RMW target flag; its read meaning is unconfirmed.

---

## 7. Phasing

| phase | scope | risk |
| :--- | :--- | :--- |
| **1** | Fix `range(1, 4)`; add 1411 to the read; `GET /api/circuits`; read-only UI cards with power + on/off (toggle reuses the proven write). | low |
| **2** | SoC cutoff write; energy-today from the metrics DB. | medium |
| **3** | Schedule editor + `PUT …/schedule`. Hardware-test on circuit 2 first. | **high — first unproven write** |
| **4** | Automations integration (`FEAT-BMS-SESSIONS-SCHEDULED` pattern): circuit actions in the schedule engine, with gateway-vs-bridge ownership shown on the card. | after engine |

---

## 8. CarSW — working hypothesis (2026-09-14)

**User hypothesis:** `CarSW` refers to US Smart Circuits where switch 1 and switch 2
(120 V) are **merged**, giving a V2L *input* mode — and only when the **Generator
module is also installed**.

Partly corroborated by this repo's own docs. `CLI_SUPPORT_INFO.md:359` derives V2L from
*"Country + SC version + Generator presence"* and states:

> `AU=no port; V2 SC=built-in; V1+Gen=CarSW`

So **CarSW is the V2L path on V1 Smart Circuits *with* the Generator module** — the
generator dependency in the hypothesis is documented. `GENERATOR_V2L_API.md:215` adds
that on such a system `modeChoose=3` reports a 3-circuit layout (Sw1 + Sw2 + Sw3/CarSW).

The **merge** half is plausible but *not* documented: `SwMerge` exists in 1409 (0 on this
AU gateway) and the cloud describes merged circuits as a US feature, but nothing ties
merging to the CarSW port. Recorded as a hypothesis, not a fact.

Either way it reinforces the phase-1 decision to surface CarSW as its own channel rather
than folding it into circuit 3: on this AU gateway `SwMerge=0`, no generator is installed
(`genEn=0`, `genModel=""`, cmd 1901) and V2L is region-disabled — yet the CarSW counters
are non-zero and still climbing (100.77 → 100.81 kWh out across a day). Whatever is
feeding them, it is not a V2L port that the documented rules say cannot exist here.
**Unresolved**; needs a US V1+Generator system to settle.


---

## 9. Vendor documentation check (2026-09-14)

Read against FranklinWH's own support pages
([Smart Circuits](https://www.franklinwh.com/au/support/overview/smart-circuits),
[Generator](https://www.franklinwh.com/au/support/overview/generator)).

**Confirms:**

- Scheduling exists as a first-class mode — *"Customize the time period or electricity
  consumption to automatically turn the circuit on or off"* — matching the on/off slot
  pairs in 1409.
- **Merging is real and load-based:** three circuits *"can be controlled independently or
  **merged if they share electrical infrastructure**"*. That is direct support for the
  CarSW/merge hypothesis in §8, and gives `SwMerge` a concrete meaning.
- **SoC auto cut-off is an OFF-GRID feature**, not a general one: it *"automatically
  disconnect[s] circuits in sequence based on battery SOC **during a grid outage**"*. This
  explains `SwXSocLowSet` (53% on circuit 1 here) and ties the smart-circuit surface to
  `docs/OFFGRID_DESIGN.md` — the cutoff only bites when islanded, so the UI should say so
  rather than implying it applies on grid.
- **Overload protection** disconnects circuits when load exceeds panel capacity. No local
  field for this has been identified; a circuit may therefore switch off for reasons the
  bridge cannot see.

**Does not settle the region question.** The **AU** page says *"three configurable
circuits"*, contradicting `CAPABILITY_RESOLUTION_SPEC.md` (AU = 2) and this AU gateway,
which physically has two. The page appears region-agnostic marketing served under `/au/`.
Hardware and the capability spec agree with each other, so the evidence-based detection in
§2 stands — this is exactly why `SMART_CIRCUIT_COUNT` must remain overridable, and why
`present` is reported with its reasoning rather than as a bare count.

**Corrects our generator reading.** The generator page states the generator supports
*"up to 3 non-overlapping operating periods (00:00-23:59) with minimum 1-minute intervals
between them"* — which is exactly the `charge1..3` trio in 1901. Those are the
**generator's operating windows**, not the grid-charge windows the catalog guessed at, and
not the uninterpretable block this repo previously called them. The maintenance mapping is
confirmed too: *"exercise duration and interval period, specific day of week and start
time"* ↔ `manoTime` / `manoFre` / `manoDate` / `manoStartTime`.


---

## 10. `SyHdVersion` — the discriminator §2 said did not exist (2026-09-14)

§2 concluded the local channel has no clean way to tell a 2-circuit gateway from a
3-circuit one. **That was wrong.** The 1101 login manifest carries:

```json
"SyHdVersion": 102
```

This is FWHAI's `sysHdVersionInt`, and `102` is `aGate X-01-AU` (SKU `AGT-R1V1-AU`,
100 A). It arrives with **every** login, so every session already had the answer.

Detection now takes the model's channel count as a **prior with one-way force**: the
model can rule a circuit *out*, and can settle an `unknown`, but it can never rule one
*in* — a gateway that supports three circuits may have no enclosure fitted at all. So
`installed: false` remains reachable on a 3-circuit model, and `SMART_CIRCUIT_COUNT`
still overrides everything. `source` reports which decided it: `detected`,
`model+detected`, or `setting`.

This also reconciles the old service-amps argument: FWHAI's 100 A is the **model's**
rated capacity (a device-class fact), while the site's install profile reads 63. Two
different quantities, not a contradiction.

### Vendor "Backwards Compatibility Statement" (rev US V1.0, 21 July 2026)

Authoritative for SKU ↔ model naming and accessory fit — with one large caveat: it is
the **US/Canada** revision and contains **no AU models whatsoever**, so it cannot settle
the AU circuit count. What it does give:

| SKU | vendor name | accessory generation |
| :--- | :--- | :--- |
| `AGT-R1V1-US` | aGate X **1.1** | `ACCY-GENV1-US`, `ACCY-SCV1-US` fit 1.0/1.1 |
| `AGT-R1V2-US` | aGate X **1.3** | `ACCY-GENV2-US`, `ACCY-SCV2-US` fit 1.3/1.3.1 |
| `AGT-R1V3-US` / `-CAN` | aGate X 1.3/1.3.1 | — |

- **Naming mismatch:** FWHAI labels these "aGate X-10 / X-20"; FranklinWH calls them
  "aGate X 1.1 / 1.3". Both are kept (`model` = FWHAI's, `vendor_model` = the vendor's)
  so the two projects can be cross-read without either being silently "corrected".
- **Discrepancy recorded, not resolved:** FWHAI lists `ACCY-SCV2-US` as compatible with
  gateway 102 (AU), while the vendor document scopes SCV2 to "aGate X 1.3/1.3.1". Since
  the document covers no AU hardware, neither source settles it — so the row carries a
  note rather than a silent edit.
- `ACCY-SCV1-US` remark: *"pre-assembled smart circuit, not support aPower S"*.
- Fleet limits captured: 15 aPowers per aGate (8 when mixing aPower X with aPower 2;
  up to 8 aPower S on 1.3/1.3.1), 4 on MAC 1.


---

## 11. Live test of the schedule write — it is discarded (2026-09-14)

Tested on circuit 2 ("Test Switch") with the user's authorisation. **The write does not
work, and §1.1's headline claim is retracted.**

| # | payload | reply | read-back |
| :--- | :--- | :--- | :--- |
| 1 | two windows, `enabled: false` | `result: 0` | unchanged |
| 2 | same, with `SwXMsgType` target selector set (all 0, target 1) | `result: 0` | unchanged |
| 3 | window 1 `enabled: true` | `result: 0` | unchanged |

**The control rules out the transport.** Immediately after attempt 3, an **on/off** write
on the *same command, same circuit, same session shape* flipped `Sw2Mode` 0→1→0 with the
read-back confirming both directions. So 1409 writes are being applied — the schedule
fields specifically are ignored.

This is the signature already documented for `1405 mode_soc`: *"writes are accepted
(result:0) then silently discarded — reserve is cloud-owned."* Schedules appear to be
cloud-owned in the same way, which also explains why the cloud library declines to write
them (`API_COOKBOOK.md:1607`) — that is a vendor-side constraint, not a gap we could
route around locally.

**No collateral damage.** The full block is echoed on every attempt, and a field-by-field
diff of all 39 fields against the pre-test capture showed **no change whatsoever** after
six writes. The read-back safety net did exactly its job: every attempt reported
`ok: false` rather than trusting `result: 0`.

**Consequences**
- The API keeps `PUT /api/circuits/{id}/schedule` — harmless, self-verifying, and it may
  be honoured on other firmware — but the response now carries **`discarded: true`** for
  the accepted-and-ignored case so `result: 0` can never read as success.
- The UI's schedule **editor is removed**; schedules render read-only with the finding
  and a pointer to the FranklinWH app.
- **Phase 3 of §7 is not achievable on this firmware.** Re-test after any gateway
  firmware update — the whole finding is firmware-specific.
- The lesson generalises: on this device an `opt:1` ack means *"frame parsed"*, not
  *"setting applied"*. Every write needs a read-back, and any future write surface should
  assume discard until a re-read proves otherwise.


---

## 12. CarSW resolved — the Generator Module *is* the V2L port, and doubles as a circuit

**Source:** FranklinWH *"Generator Module as Smart Circuit Operations Guide"* (12 pp).

> "The FranklinWH System provides integration for third-party standby generators /
> **Vehicle-to-Load (V2L)** through its optional **Generator Module**. The module **also
> functions as a Smart Circuit** for a large load…"
> "The maximum capacity of the Smart Circuit is up to **160 A**."
> "**Once the generator module is configured for Smart Circuit use, it cannot be used for**
> [generator]."

This closes §8's open question. The Generator Module is a **single physical port with three
mutually exclusive roles** — generator input, V2L input, or a (large, up to 160 A) smart
circuit. That explains every loose end at once:

- why `CarSw*` (V2L) fields sit inside **1409**, the *smart-circuit* command, next to
  generator fields;
- why the cloud documents *"the CarSW port **is** Sw3"*;
- why `CLI_SUPPORT_INFO.md:359` reads `V1+Gen=CarSW` — V2L exists only when the Generator
  Module is fitted, because the module *is* the port;
- why the user's original instinct ("V2L input only if the Generator Module is installed
  as well") was right about the dependency.

**The mutual exclusion is vendor-stated, not inferred.** `OFFGRID_DESIGN.md` §6 proposed
that the bridge enforce a generator/V2L interlock in software "and not claim the device
does". That proposal stands, and now has an explicit justification: the vendor says the
configuration is one-or-the-other, so a UI offering both simultaneously is offering
something the hardware cannot do.

**Not resolved:** why this AU gateway's `CarSw*` export/import counters keep climbing with
`SwMerge = 0`, no generator (`genEn 0`, `genModel ""`) and V2L region-disabled. The port's
*identity* is now explained; the *counters* are not.
