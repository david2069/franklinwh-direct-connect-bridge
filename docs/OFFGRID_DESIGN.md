# Off-grid mode — design evaluation

**Status:** design, not implemented · **Filed:** 2026-09-14
**Evidence:** live reads of 1723 / 1801 / 1709 / 1301 / 1827 / 1901 / 1409 from the AU
aGate, 2026-09-14, **while grid-connected** — so every off-grid value below is the
idle/default case. Nothing here has been observed during an actual islanding event.

---

## 1. The request

> An off-grid mode which, when solar PV goes off then back on, can start the generator if
> installed; smart circuits can be configured for V2L input in lieu of generator input
> (only one can be active). It only appears when off-grid (simulated or real — a reason
> code should tell us which). Also blackstart, and whether the gateway is in standby.

Five separate questions. Four are answerable locally; one is blocked by firmware.

---

## 2. Am I off-grid? — four independent signals

> **Corrected 2026-10-15 by a real island.** The table and recommendation below were
> rewritten after measuring an owner-initiated off-grid event (aGate X-01-AU, firmware
> V12R02B30D06, sampled every 15s for ~80 minutes). The previous text named `run_status` as
> primary and `gridRelayOpen` as "the truth about copper"; **both were wrong on this
> firmware**, and implementing the old recommendation literally produced defect #45.

| source | field | islanded | on-grid | verdict |
| :--- | :--- | :--- | :--- | :--- |
| `1723` offgrid | `offgridState` | **1** | 0 | **PRIMARY** — the only signal that was simply correct |
| `1707` ibg_run_status | `dspRunstatus` | **5** = Off-Grid Standby | run-state | correct, and absent from the original table |
| `1301` power_flow | `main_sw[0]` | **0** (open) | 1 | physical corroboration |
| `1707` ibg_run_status | `mainRelay1/2Status` | **0 / 0** | 1 / 1 | physical corroboration |
| `1301` power_flow | `run_status` | **0, 1, 2** — never 5/6/7 | 0/1/2 | **does not discriminate** on this firmware |
| `1709` relay_status | `gridRelayOpen` | **0** | 0 | **not evidence** — unchanged through a real island |
| `1301` power_flow | `elecnet_state` | 0 | 0 | still undecoded; unchanged, so not a candidate |

The `RUN_STATUS` enum itself is not in doubt — `5/6/7` are real codes and the cloud uses
them. What is disproved is the assumption that **`1301 run_status` carries them**. It is
kept as a disjunct because a different firmware may well emit them; it is simply not
sufficient alone, and on this firmware it never fires.

`gridRelayOpen` is removed as a corroborator rather than demoted. A field that reads `0`
both on-grid and through an island carries no information about islanding, whatever its
name says.

**Recommendation (current):** off-grid is `offgridState == 1 or dspRunstatus in (5,6,7) or
main_sw[0] == 0 or mainRelay1/2Status == 0 or run_status in (5,6,7)`, and the surface
reports **which** signals fired. Disagreement is itself diagnostic and must not be averaged
away into a single boolean — that part of the original recommendation was right and is why
`off_grid_signals` and `off_grid_disagreement` exist.

### The return to grid, 2026-10-15 09:00 AEDT

Written from this bridge (`1723 opt:1, offgridSet:0`) and captured at 5 s. The island's
*start* was missed by ~53 s; this is the transition with a baseline on both sides.

| time | what changed |
| :--- | :--- |
| 09:00:01 | write issued → `{"ok": true, "result": 0}` |
| 09:00:02 | `offgridState` **1 → 2**, `offgridSet` **1 → 0** — the command lands in ~1 s |
| 09:00:25 | `dspRunstatus` **5 → 4**, `ibgRunStatus` **7 → 85232**, `p_uti` 0 → 9 W |
| 09:00:35 | `mainRelay1Status` **0 → 1**, `main_sw` **[0,0,1] → [1,0,1]**, `p_uti` −848 W |

**34 seconds, in three stages**: command accepted, programme and run state change, then the
physical relay closes. Nothing about the write is instantaneous, and a check made in the
first 30 s would see a site that had accepted the command and not yet acted on it.

> ⚠️ **Do not read 34 s as "how long a reconnect takes".** FranklinWH documents that
> reconnection is contingent on the gateway being satisfied the grid is STABLE. Through this
> entire island the utility was present and nominal on the grid side of the open relay —
> `gridVol1` and `gridVol2` held ~120 V each with `gridCurr` ~0 A for two hours. The grid had
> therefore been continuously qualifiable before the release command was even sent.
>
> After a **real** outage the stability clock can only start when the utility actually
> returns, and grid-support standards normally require a sustained qualification period
> (IEEE 1547's default reconnect delay is minutes, not seconds). So 34 s is the floor for a
> requested island with a healthy grid behind it, and says nothing about outage recovery.

### Grid presence is an independent discriminator

`gridVol1` / `gridVol2` are measured on the **utility side** of the main relay. Through the
requested island they read ~120 V each at ~0 A: *the grid was there; we were not connected to
it.* In a real outage they should collapse.

That is a second, physical answer to "simulated or real", owing nothing to whether anyone set
a flag:

| | `offgridSet` | grid legs |
| :--- | :---: | :--- |
| requested island, healthy grid | 1 | **live** — measured 2026-10-15 |
| real outage | 0 | **dead** — expected, unconfirmed |
| requested island during an outage | 1 | dead |

Exposed as `power.grid_present` (True / False / null when unmeasured) alongside
`off_grid_kind`. It also answers a question the owner raised: whether the gateway itself can
tell the two apart. It need not have a flag for it — **its inputs differ**. A software-driven
disconnect leaves full voltage and frequency on the grid terminals; a real outage leaves
none. Any stability check therefore behaves differently in the two cases without needing to
know which it is. That is an inference from the measured inputs, not something read from the
device.

#### `offgridState` is at least tri-state, and the channels disagree about it

It settled at **2**, not 0. Local `1723` read 2 while the site exported 848 W. Any test of
`offgridState != 0` — the obvious spelling — would call this site islanded while it is
exporting. Testing `== 1` is the correct form and is what the implementation uses.

The cloud does **not** agree: `selectOffgrid` at 09:04:18 returned `offgridState: 0` for the
same site, same moment. So this field differs between channels — the cloud either collapses
the "returned" state or does not carry it. Reported by the `franklinwh-cloud` session;
recorded as a cross-channel difference, not as one of them being wrong.

#### `ibgRunStatus` is a programme id — settled on two channels

`7` while islanded, `85232` on return, which is this gateway's mode id for Self-Consumption
in `1726`. The cloud's `runtimeData.mode` read `7` in 71/71 island polls and `85232`
afterwards, and showed `9` for a Modbus dispatch on 2026-10-14. Same field, two channels,
and it identifies the **programme**, never the run state.

`dspRunstatus` is the run state: `5` islanded, `4` after the return. Our catalog has `4` as
"Reserved 4", so that enum is incomplete for this register.

#### Cloud `offgridreason`

`1` through the island, **0** at 09:00:21 — about 20 s after the write and *before* the
relay closed — then the key disappeared entirely once on grid. A field that is absent rather
than 0 when inactive; worth knowing before testing it for falsiness.

### Evidence

Measured 07:21–08:10 AEDT 2026-10-15, constant throughout: `offgridState` 1, `offgridSet` 1,
`offgridSoc` 5, `run_status` 0/1, `dspRunstatus` 5, `ibgRunStatus` 7, `main_sw` [0,0,1],
`mainRelay1Status` 0, `mainRelay2Status` 0, `gridRelayOpen` 0, `p_uti` 0 with the site
running on solar. Corroborated independently on the Modbus channel, which recorded
`DERMeasureAC.DERMode = Grid Forming` from 06:51:40 — **two seconds before** the Direct
Connect capture began, which is why that capture has no on-grid baseline.

One site, one firmware, one event: [[one site is a hypothesis]]. What is not hypothetical is
that the previous text asserted the opposite of what was measured.

---

## 3. Simulated vs real — the discriminator exists, but it is not a reason code

There is no reason field. There is something better: **two flags whose divergence is the
answer.** `1723` returns both a *command* and a *state*:

```json
{"offgridSet": 0, "offgridSoc": 5, "offgridState": 0}
```

- `offgridSet` — the **requested** state (this is what `set_offgrid` writes; cloud maps it
  to `updateOffgrid`).
- `offgridState` — the **actual** state (cloud `selectOffgrid` / `get_grid_status()`).

So:

| `offgridSet` | `offgridState` | meaning |
| :---: | :---: | :--- |
| 0 | 0 | on grid |
| **1** | **1** | **user-requested / simulated** off-grid |
| **0** | **1** | **real outage** — islanded without being asked |
| 1 | 0 | requested but not yet islanded (transition, or refused) |

That is exactly the distinction asked for, and it falls out of the field pair rather than
needing a reason code.

> **Half confirmed, 2026-10-15.** The `(1, 1)` row is now measured, not inferred: through a
> deliberate island, `1723` read `offgridSet: 1, offgridState: 1` continuously, and the write
> that ended it took `offgridSet` to 0 one second later. So "requested ⇒ simulated" holds.
>
> The `(0, 1)` row — a real outage — is **still unconfirmed**, and confirming it means the
> grid actually failing, which is not something to arrange. The UI therefore says
> **OFF-GRID · OUTAGE** for that case meaning *"islanded with no request we know about"*,
> not *"a positively identified outage"*. And if `1723` cannot be read, the badge stays the
> plain **OFF-GRID**: inferring an outage from a failed read would raise an alarm out of a
> missing field.
>
> Also measured: `offgridState` returns **2**, not 0, after a requested island ends — so the
> state is at least tri-state and `!= 0` is the wrong test. The cloud's `selectOffgrid`
> reported `0` for the same site at the same time, so the two channels differ on this field.

**Implemented** as `power.off_grid_kind` — `simulated` | `outage` | `null` — surfaced in the
top bar as a distinct badge per case, with the raw flags available alongside, as this section
required.

---

## 4. Blackstart — blocked by firmware (PARTLY RETRACTED — see §11)

`blackStartOnOff` lives in `1801 battery_inhibit`, alongside `startGenSoc` / `stopGenSoc`.
That block is **unreadable on this firmware**:

```json
{"topSoc": 0, "inhSocNormal": 1, "inhSocCold": 2, ..., "blackStartOnOff": 11,
 "startGenSoc": 12, "stopGenSoc": 13, "InhUseFlag": 14}
```

Every value equals its **field position**, 0–14. This is an unpopulated struct being
serialised by index, not data — the catalog already warns about it, and the live read
confirms it. `blackStartOnOff: 11` is not "blackstart is 11"; it is the eleventh field.

**Consequence: blackstart state cannot be read locally.** Do not display it. Showing
`11` — or a boolean derived from it — would be fabricating a safety-relevant value. The
honest surface is "not available on this firmware" with the reason.

Generator start/stop thresholds survive this, because `1901` carries readable equivalents
(`genStartElec: 20`, `genCloseElec: 80`) independent of the broken block.

---

## 5. Standby

`run_status 0` = Standby, `5` = Off-Grid Standby — both from the same cloud-aligned enum,
so standby is available and unambiguous.

`1827 ibg_state` adds `ibgDspState: 4`, `peState: [8]`, `bmsState: [5]`. These are DSP /
power-electronics / BMS state machines with **no local enum** and no cloud mapping we can
cite. Show them raw and labelled as undecoded, or not at all — do not invent labels.

---

## 6. V2L input *in lieu of* generator input

The strongest local candidate for "V2L as an input source" is in `1409`:

```json
"CarSwConsSupEnable": 0, "CarSwConsSupEnerge": 0,
"CarSwConsSupStartTime": "2026-06-19 16:07"
```

Read as **CarSW Consumption Supply** — the CarSW port *supplying* consumption, which is
precisely V2L-as-input, with an energy counter and a start timestamp beside it. `1411`
carries the matching `CarSwConsSupExpEnerge`.

Mutual exclusion with the generator is plausible and matches the request, but note what
we actually have: `1901 genEn` (generator enable) and `1409 CarSwConsSupEnable` are
*separate flags in separate commands*, and **nothing observed enforces that only one is
set**. `1709` has `genRelayOpen` and `genRelayAdhesion`, implying one generator input
relay — consistent with a shared input path, not proof of it.

**VENDOR-CONFIRMED 2026-09-14.** The *"Generator Module as Smart Circuit Operations
Guide"* states the Generator Module provides generator **and V2L** integration, also
functions as a Smart Circuit, and that *"once the generator module is configured for Smart
Circuit use, it cannot be used for"* the generator. So the roles are one physical port,
three mutually exclusive uses — the interlock is real hardware behaviour, not a guess.

**Recommendation (unchanged):** the bridge enforces the interlock in software (refuse to
enable one while the other is on, and say why), and does **not** claim the device enforces
it — the vendor documents the configuration as exclusive, which is not the same as the
firmware rejecting a conflicting write. See
`DEF-EXPORT-LIMIT-ENFORCEMENT` for why an unverified assumption about device-side
enforcement is a trap worth avoiding twice.

This also bears on `docs/SMART_CIRCUITS_DESIGN.md` §8: `CarSwConsSupEnable: 0` on a
gateway whose CarSW export/import counters keep climbing deepens that open question.

---

## 7. "Solar drops, then returns → start generator"

Nothing local implements this. The device's generator automation is **SoC-based only**
(`genStartElec` / `genCloseElec`), with a `startDelTime` of 1800 s. There is no
PV-loss trigger in any observed payload.

So this is **bridge-side orchestration**, and it belongs to `SCHEDULE-AND-AUTOMATIONS`
(not yet built) rather than to a new one-off engine:

- trigger: `p_sun` falls below a threshold for N samples **while off-grid**
- re-arm: `p_sun` recovers — the "off then back on" the request describes
- action: generator on (if installed) **or** V2L input (if configured), never both
- guard: only while off-grid; irrelevant on grid

Two cautions. The poller drops samples on the known flaky wifi, so a PV-loss trigger must
require **N consecutive** confirmations rather than a single missing reading — a dropped
poll must never start a generator. And during a real outage the bridge itself may be
unpowered; anything depending on it is best-effort, whereas the gateway's own SoC
thresholds keep working. Say so in the UI rather than implying the automation is a
reliable backstop.

---

## 8. Proposed surface

**API** — `GET /api/offgrid`:

```json
{
  "off_grid": false,
  "signals": {"run_status": 0, "offgrid_state": 0, "grid_relay_open": 0},
  "agreement": true,
  "cause": null,                       // "requested" | "outage" | null
  "cause_confidence": "inferred",
  "requested": false,
  "floor_soc": 5,
  "standby": true,
  "blackstart": {"available": false,
                 "reason": "1801 returns field positions, not values, on this firmware"},
  "sources": {"generator": {...}, "v2l": {...}, "interlock": "software"}
}
```

**UI** — a conditional panel, per the request that it *only appears when off-grid*:

- Hidden on grid, except a single line in Health: *"On grid · off-grid panel hidden"*, so
  its absence is legible rather than looking like a missing feature.
- When off-grid: cause badge (**Requested** / **Outage** / **Disagreement**) with the raw
  flags beside it, floor SoC, elapsed time, and the two input sources with the software
  interlock.
- Blackstart renders as "unavailable on this firmware" with the reason — never a value.

**Writes** — `set_offgrid` already exists (1723, `offgridSet`/`offgridSoc`). Deliberately
islanding a house is the most consequential write in this repo: it must keep the existing
confirm gate, and should additionally refuse when SoC is below the floor.

---

## 9. Phasing

| phase | scope | risk |
| :--- | :--- | :--- |
| **1** | `GET /api/offgrid` + read-only panel + standby. Safe now, all four signals readable while on grid. | low |
| **2** | V2L/generator source display + software interlock (needs a system with either fitted). | medium |
| **3** | PV-loss→restore automation, once `SCHEDULE-AND-AUTOMATIONS` exists. | medium |
| **4** | Off-grid trigger write hardening. **Needs a planned test**, not an opportunistic one. | **high** |

## 10. Open questions

1. `elecnet_state` — undecoded; may be a cleaner grid-presence flag than the relay.
2. The §3 table is unconfirmed until an off-grid event is observed.
3. `ibgDspState` / `peState` / `bmsState` — no enum.
4. Whether the device enforces generator/V2L exclusion, or only the app does.
5. Whether `blackStartOnOff` becomes readable on newer firmware — worth re-reading 1801
   after any update, since the whole block is currently dead.


---

## 11. Corrections from the 1707 relay block (2026-09-14)

`1707 ibg_run_status` turned out to carry a full per-relay block that this document
missed. Two consequences.

### Blackstart is partly readable — §4 overstated

```json
"blackStartRelay": 1
```

§4 said blackstart "cannot be read locally". That is true of the **config flag**
(`blackStartOnOff` in the broken 1801 block) but **not** of the relay: 1707 reports
`blackStartRelay` directly. So the surface can show *the blackstart relay state* — it
still cannot show whether blackstart is *enabled* in configuration. Those are different
claims and the UI must not merge them.

### The off-grid signal list gains a fourth corroborator

1707 also carries `mainRelay1Status`, `mainRelay2Status`, `gridRelay2`,
`solarRelayStatus`, `pvRelay2`, `loadRelay1Stat`, `loadRelay2Stat` and
`smartRelay1..3Status`. `main_sw` in 1301 duplicates the grid/generator/solar relays
(cloud `API_COOKBOOK.md:36`), so §2's table can be cross-checked against physical relay
state rather than inferred state alone.

`smartRelay1..3Status` is also a **third presence signal for smart circuits**, independent
of the 1409 config and the 1411 meter — worth folding into `circuits.evaluate()`.

---

## 12. Generator availability is off-grid-only (2026-09-14, user)

> "Generator enable can only happen if the gateway is off-grid — not sure. The generator
> module is unavailable whilst on grid, but you can configure it."

Consistent with everything else observed: FranklinWH's generator page frames SoC
start/stop as *"in off-grid mode with Schedule enabled"*, and the Smart Circuits page
frames SoC cut-off as *"during a grid outage"*. Configuration is writable on grid —
**proven**, since every 1901 write in this repo was made while grid-connected — but
whether the generator would *run*, and whether `genEn` even takes effect on grid, is
**untested and untestable without islanding**.

The UI therefore states it as a limitation rather than a guess: the enable dialog says
the generator is only available off-grid and will not run until the gateway islands. No
claim is made about whether `genEn` itself behaves differently on grid.
