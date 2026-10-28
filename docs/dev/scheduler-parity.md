# Scheduler parity: Modbus Bridge vs Direct Connect

The two bridges' schedulers, compared behaviour by behaviour, so they can be aligned.

| | Behaviours | Tested | Untested | Unclear |
|---|---|---|---|---|
| **Modbus Bridge** ([scheduler pages](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/concepts/), test plan at its `main` f2e9134, PR #217) | 238 | 130 | 93 | 15 |
| **Direct Connect** ([Scheduler](../guide/scheduler/index.md), [test plan](scheduler-test-plan.md), 0.5.5) | 266 | 106 | 119 | 41 |

Of the Modbus Bridge's 238 behaviours, this bridge has **74 the same**, **121 that differ**
and is **missing 55**. It has **83 of its own** (Direct Connect only). 13 more rows compare

!!! warning "Corrections from the Modbus Bridge's code check (2026-10-17)"
    This page read the Modbus Bridge side from its doc markers. That bridge's session has
    since checked them against its code (franklinwh-modbus-bridge PR #233):

    - **28 of the 83 "Direct Connect only" rows exist there too**: 17 undocumented, 11
      documented under other ids. Treat them as *same* or *differs*, not missing there.
    - Rows TRG-06, TRG-13, TRG-23, HAA-01 and PRI-01 described the Modbus Bridge wrongly; each
      row carries a note.
    - TRG-19 (next fire for long intervals) is the **same** bug in both (our #208).

    The counts on this page have **not** been rebased on those corrections yet.
whole sections of the dependencies and examples pages, which carry no markers.

**How it was built.** Each row is one behaviour id. Ids are shared: where this bridge's page
documents the counterpart of a Modbus Bridge behaviour, it uses the same id, even when the
behaviour differs. *Has / tested* for the Modbus Bridge comes from its test plan; for this
bridge from the markers in the [Scheduler](../guide/scheduler/index.md) pages. The *gap* is a
short note written while reading both bridges' code. The Modbus Bridge's claims are taken
from its docs and were **not** re-verified against its code here; this bridge's side was read
from its code, and the less obvious defects were reproduced with a mock (no hardware).

| Column | Meaning |
|---|---|
| **#** | Behaviour id. "—" for a section-level comparison (no marker). |
| **Page · heading** | This bridge's page and the heading both bridges share. |
| **Modbus Bridge** / **Direct Connect** | `yes / tested`, `yes / untested`, `yes / unclear` or `no`. |
| **Gap** | **same**, **differs**, **missing here** (Modbus Bridge only) or **Direct Connect only**, then the difference. |
| **Why missing** | *Missing here* rows only: **Not ported**, **Depends on**, **Transport limit**, **Design choice** or **Unknown**, then the source. See [Gap reasons and classes](#gap-reasons-and-classes). |
| **Class** | *Differs* rows only: **behavioural** (with what it writes) or variance, then why. |
| **Issue** | The issue in this repository. Issues opened from this review are listed under [Issues filed from this review](#issues-filed-from-this-review). |

## Gap reasons and classes

Added to the table below: **Why missing** for the 55 *missing here* rows and
**Class** for the 121 *differs* rows. Each was assigned from the code and docs cited in
the row, the [BACKLOG][bl-index] and the issues; nothing was run against a gateway or an
emulator.

### Why missing (55 rows)

| Reason | Rows | What it means |
|---|---|---|
| Not ported | 24 | Not built here yet, and recorded as wanted (BACKLOG or an issue). |
| Depends on | 23 | Needs another missing piece first (named in the row): mostly catch-up, release policy, ownership, supervision. |
| Unknown | 8 | No record of why. Questions below. |
| Transport limit | 0 | None. Every missing behaviour can be built on the transports this bridge already uses: the force path is the same WSet model 704 on the Modbus TCP Server (aGate :502) through the Modbus client (this bridge) (`battery_control.py:1-7`), and the reserve and mode reads it needs are local ([PROTOCOL.md][dca-proto]). The two transport limits found sit in *differs* rows (dependency matrix): Direct Connect (:9000) has no battery force, and reserve (1405) is cloud-only. |
| Design choice | 0 | None recorded for a *missing* row. Run now ignoring conditions is recorded as by design in [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162), but that row is a *differs* row (OUT-20). |

### Differs (121 rows)

| Class | Rows |
|---|---|
| Behavioural: battery write | 68 |
| Behavioural: other device or HA write | 7 |
| Behavioural: recorded outcome or notification | 18 |
| Behavioural: display only (timeline, Next, Test, buttons) | 11 |
| Implementation variance | 16 |
| Needs owner | 1 |

**Rule used.** Variance means the same intent gives the same trigger, conditions, action,
target, exit and recorded result by different code. Anything that could change a battery
write, another device write or a recorded outcome is behavioural. Display-only rows that
misstate when or where something runs are behavioural, ranked last.

### Behavioural differences, ranked by risk

Battery writes first, then other device and HA writes, then the record, then display. Within
a group, the order is a judgement of likelihood times effect, not a measurement.

| Rank | Row | Writes | Difference | Issue |
|---|---|---|---|---|
| 1 | EXT-01 | battery | window close releases a force it never sent or does not own | [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) (fixed, unreleased) |
| 2 | EXT-05 | battery | never hands over; releases another's force | [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) (fixed, unreleased) |
| 3 | § 5. Peak-demand window | battery | overlapping force schedules release each other (#189) | [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) (fixed, unreleased) |
| 4 | RST-01 | battery | restart releases only the in-memory force, to the first gateway's host | [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) (fixed, unreleased) |
| 5 | OUT-24 | battery | Stop releases via the first gateway's host; no exit HA actions | [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) (fixed, unreleased) |
| 6 | EXT-20 | battery | shutdown releases to the first gateway's host | [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) (fixed, unreleased) |
| 7 | TGT-09 | battery | Run now forces the top-bar gateway, not the schedule's | [#193](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/193) (fixed, unreleased) |
| 8 | RST-02 | battery | start-up default is notify: a force left by a crash keeps running (there: released) | [#199](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/199) (fixed, unreleased) |
| 9 | RST-04 | battery | `release_stale()` never called | [#199](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/199) (fixed, unreleased) |
| 10 | ACT-13 | battery | a refused force is logged fired and never retried | [#191](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/191) (fixed, unreleased) |
| 11 | § An action is refused or does nothing | battery | refused writes logged fired (#191) | [#191](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/191) (fixed, unreleased) |
| 12 | PRI-03 | battery | a later-ready force overrides a running one whatever the priority | [#196](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/196) (fixed, unreleased) |
| 13 | EXT-04 | battery | delete does not release the running force | [#195](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/195) (fixed, unreleased) |
| 14 | TRG-34 | battery | hidden 90 min duration cuts a window force short | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| 15 | ACT-17 | battery | time limit = duration_min x 60, hidden 90 min in windows | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| 16 | § 1. Evening top-up | battery | hidden duration ends the force (#160) | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| 17 | § 2. Evening peak discharge until the minimum SoC | battery | workaround for #160 changes the window | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| 18 | TRG-16 | battery | weekly with no days fires every day (Modbus Bridge: never) | [#198](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/198) |
| 19 | TRG-23 | battery | monthly with no day fires every day | [#198](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/198) |
| 20 | TRG-09 | battery | start = end is open all day: a force runs 24 h | [#198](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/198) |
| 21 | ACT-04 | battery | empty power is a 0 W force | [#209](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/209) |
| 22 | TRG-28 | battery | Always fires once ever, but releases on every falling edge | [#190](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/190) |
| 23 | § An entry never fires | battery | Always fires once ever (#190) | [#190](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/190) |
| 24 | TRG-27 | battery | Always fires on the rising edge, not continuously | [#190](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/190) |
| 25 | TRG-29 | battery | stored occurrence never pruned keeps Always from firing again | [#190](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/190) |
| 26 | TGT-10 | battery | unbound = first registered gateway, which moves | [#182](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/182) |
| 27 | EXT-17 | battery | Release refused when the Modbus client (this bridge) is off; no read-back | [#174](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/174) |
| 28 | § Dependency matrix | battery | force needs the Modbus client (this bridge): :9000 has no battery force (transport limit, [HYBRID-CAPABILITIES][bl-hybrid]); reserve write never runs (#129): 1405 is cloud-only ([PROTOCOL.md][dca-proto]) | [#129](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/129) |
| 29 | CON-02 | battery | name order, priority only within a tick: decides which force runs | [#196](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/196) (fixed, unreleased) |
| 30 | PRI-02 | battery | contest only within a tick, per resource | [#196](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/196) (fixed, unreleased) |
| 31 | PRI-01 | battery | default If busy = override (there: defer); unknown values act as override |  |
| 32 | SEN-10 | battery | stale NEM price kept: price-gated forces run on old prices | [#207](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/207) |
| 33 | SEN-04 | battery | `grid.connected` reads 0 at exactly 0 W: a grid gate can fire a force | [#206](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/206) |
| 34 | § A condition is always true when it should not be | battery | conditions can pass when they should not (#206) | [#206](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/206) |
| 35 | ACT-14 | battery | no WSetEna read-back check: a force can be recorded as sent when it did not take | [#139](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/139) |
| 36 | ACT-03 | battery | % sized on 702 or a 5000 W fallback, no trusted rating: different watts written |  |
| 37 | ACT-10 | battery | W/kW not capped by the bridge at 702 |  |
| 38 | PRI-07 | battery | busy = only dispatch rows of schedules or the widget; mode entries unchecked |  |
| 39 | PRI-08 | battery | defer gives up for the day; wait retries each tick | [#204](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/204) |
| 40 | PRI-10 | battery | after a manual command ends, a deferred entry does not run |  |
| 41 | OUT-04 | battery | retry 30 s doubling to 600 s (there: 15, 30, 60 s); no notification | [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) |
| 42 | ACT-02 | battery | invalid actions saved; fail only at run | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| 43 | OUT-20 | battery | Run now ignores conditions (by design per #162) | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| 44 | ACT-05 | battery | percent accepted; any unknown unit is read as percent |  |
| 45 | TRG-30 | battery | falling edge sends Release (the Modbus Bridge does not re-check) |  |
| 46 | CND-27 | battery | a retry waits the whole hold again, delaying the force | [#203](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/203) |
| 47 | SEN-08 | battery | undefined window is None (fails closed) not False: `== 0` gates differ |  |
| 48 | TRG-22 | battery | no range check; day 0 = every day, so an invalid entry fires | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| 49 | TRG-08 | battery | the after-midnight part follows the opening day's calendar: a force may run on a day the Modbus Bridge skips |  |
| 50 | CND-22 | battery | multi-gateway: tariff/billing sensors from each gateway's own meter, so conditions can differ |  |
| 51 | CND-06 | battery | case-insensitive text: a condition can pass that fails there |  |
| 52 | CND-08 | battery | bracketed lists and text members parse differently: condition result can differ |  |
| 53 | CLK-01 | battery | each gateway's aGate clock: fire times differ when the container clock is not site time |  |
| 54 | CND-20 | battery | an empty ALL exit group stops the schedule ever starting |  |
| 55 | TRG-13 | battery | an overnight one-off keeps forcing past midnight |  |
| 56 | IDX-03 | battery | an edited power or action is not re-sent to a running force until the next window |  |
| 57 | TRG-11 | battery | stored days still restrict a one-off, so it may not fire |  |
| 58 | TGT-01 | battery | a stale or disabled gateway's schedules are not evaluated |  |
| 59 | TGT-11 | battery | unbound and bound contend as one group (two groups there) |  |
| 60 | ACT-19 | battery | form save keeps API-only keys (the Modbus Bridge drops `target_soc`): different force end |  |
| 61 | TRG-10 | battery | an unparsable window falls back to Fire at + duration instead of 00:00 |  |
| 62 | ACT-15 | battery | WSetRvrtTms not written (the library writes WSetEna/WSetMod/WSetPct only); PICS Issue 4 calls it cosmetic |  |
| 63 | CLK-04 | battery | DST change applies up to 10 min late |  |
| 64 | EXT-07 | battery | exit already true: no start here; a brief force there |  |
| 65 | PRI-06 | battery | a loser does not fire again that occurrence |  |
| 66 | RST-03 | battery | stored occurrence: no re-fire after restart (there: re-dispatches) |  |
| 67 | PRI-13 | battery | claims per gateway, not per target |  |
| 68 | OUT-25 | battery | Stop with nothing running does not block the window; the entry can still fire |  |
| 69 | HAA-06 | device/HA | exit HA actions run at every window close, even if never fired | by design (kept when #189 was fixed) |
| 70 | HAA-07 | device/HA | on-entry HA actions repeat on every retry | [#203](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/203) |
| 71 | ACT-28 | device/HA | Run now runs HA actions of HA-only schedules |  |
| 72 | EXT-09 | device/HA | exit evaluated for every action kind (mode, HA-only) |  |
| 73 | EXT-12 | device/HA | `restore_on_exit` writes the mode back (the Modbus Bridge only audits) | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| 74 | ACT-23 | device/HA | missing mode accepted, fails and retries at run | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| 75 | HAA-01 | device/HA | invalid HA actions saved; skipped at run | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| 76 | OUT-18 | record | no failure notifications | [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) |
| 77 | OUT-13 | record | dispatch record holds successful forces only | [#139](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/139) |
| 78 | TRG-40 | record | missed rows come from stale claims, not outages |  |
| 79 | TRG-41 | record | a window no tick saw leaves no missed row |  |
| 80 | CND-29 | record | gated logged once a day, two leaves |  |
| 81 | HAA-08 | record | guard skip leaves no log row |  |
| 82 | HAA-12 | record | HA failures folded into the run row; rarely fail the run |  |
| 83 | TGT-06 | record | History rows do not name the gateway | [#205](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/205) |
| 84 | EXT-10 | record | exit row names no condition |  |
| 85 | PRI-14 | record | requester only in the dispatches table |  |
| 86 | OUT-01 | record | config changes logged as one word; import not logged |  |
| 87 | OUT-05 | record | recovery logged as plain fired; no notification | [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) |
| 88 | TRG-24 | record | invalid cron saved instead of rejected; never fires in either | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| 89 | CND-02 | record | import accepts unknown sensors silently | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| 90 | CND-26 | record | hold over 86400 s accepted |  |
| 91 | CND-35 | record | no warning for an unexposed HA entity | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| 92 | HAA-02 | record | incomplete rows kept and skipped at run with a reason |  |
| 93 | HAA-10 | record | `%ha:…%` placeholders not substituted | [#169](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/169) |
| 94 | IDX-06 | display | timeline omits interval schedules and ignores the gateway | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| 95 | TRG-19 | display | Next shows a time the engine does not fire at | [#208](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/208) |
| 96 | TRG-32 | display | Next uses the container clock | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| 97 | IDX-07 | display | one-off drawn only on its date (the Modbus Bridge draws it every week) |  |
| 98 | TRG-33 | display | `active_now` also needs a fire; changes Stop/Run now |  |
| 99 | CND-30 | display | editor Test evaluates the top-bar gateway, not the schedule's |  |
| 100 | CND-31 | display | Test against live: default gateway, container clock, top-level rows only | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| 101 | TGT-02 | display | site fan-out only through the API | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| 102 | TGT-15 | display | timeline is one list, not per gateway | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| 103 | OUT-19 | display | Stop shown on a different rule, container clock | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| 104 | CLK-02 | display | previews on the container clock | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |

### Questions for the owner

**Unknown (missing here, no record of why):**

1. **Legacy format (CON-07, ACT-07, ACT-08, ACT-09; also EXT-16).** These describe the Modbus
   Bridge's legacy / v2 split and legacy `power_pct` entries. This bridge never had either.
   Mark them *not applicable* and drop them from the parity count?
2. **API `oneoff` trigger (TRG-35).** The Modbus Bridge has an API-only `oneoff` type with an
   ISO `fire_at`; here a one-off is a date window. Wanted, or not applicable?
3. **Rating trust model (ACT-11, and ACT-12, OUT-17 that build on it).** No record says whether
   a calibrated / peak-confirmed rating gate is wanted here. [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) lists the overshoot
   guard but not the trust model. Port it?
4. **Power staging (ACT-16).** The Modbus Bridge stages power and re-sends the active command;
   here a force is one `BatteryCommand`. Not applicable?
5. **Mock warning in the form (TGT-13).** Wanted?

**Needs owner (differs):**

6. **Storm example (§ 4. Storm forecast).** Is `weather.condition` matching `*thunder*`
   right, or should the example use `weather.code in 95, 96, 99` (and should `weather.code`
   be in the picker)?

[bl-index]: https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/BACKLOG.md
[bl-orch]: https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/BACKLOG.md#feat-scheduler-orchestration-priority-conflict-policy-release-policy-missed-window-catch-up-siteservice-targets-phase-1-done
[bl-sens]: https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/BACKLOG.md#feat-sched-sensor-parity-close-the-entry-condition-sensor-gap-vs-modbus-61-missing-2-buckets
[bl-sched]: https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/BACKLOG.md#schedule-and-automations-clone-the-modbus-bridge-schedule-orchestration-the-schedule
[bl-hybrid]: https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/BACKLOG.md#hybrid-capabilities-fill-the-local-hard-walls-via-modbus-cloud-providers
[bl-auth]: https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/BACKLOG.md
[dca-proto]: https://github.com/david2069/franklinwh-direct-connect-api/blob/main/docs/PROTOCOL.md

## Behaviours

| # | Page · heading | Modbus Bridge | Direct Connect | Gap | Why missing | Class | Issue |
|---|---|---|---|---|---|---|---|
| IDX-01 | [index](../guide/scheduler/index.md) · The entry list | yes / untested | yes / untested | **differs**: DC shows all by default |  | variance: list filter default only |  |
| IDX-02 | [index](../guide/scheduler/index.md) · The entry list | yes / untested | yes / untested | **differs**: DC opens an unsaved 'Copy of' form, disabled |  | variance: both end with a disabled copy; only the save step differs |  |
| IDX-03 | [index](../guide/scheduler/index.md) · The entry list | yes / tested | yes / untested | **differs**: DC confirms but does not re-send a running force; change applies next window |  | **behavioural** (battery): an edited power or action is not re-sent to a running force until the next window |  |
| IDX-04 | [index](../guide/scheduler/index.md) · Templates, export and import | yes / untested | yes / untested | **differs**: DC loads disabled, no enable prompt |  | variance: templates load disabled in both |  |
| IDX-05 | [index](../guide/scheduler/index.md) · Templates, export and import | yes / tested | yes / tested | same: DC also exports/imports its own franklinwh-local-schedules |  |  |  |
| IDX-06 | [index](../guide/scheduler/index.md) · Visual timeline | yes / tested | yes / tested | **differs**: DC: one list, interval/cron/always not drawn, not per gateway |  | **behavioural** (display): timeline omits interval schedules and ignores the gateway | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| IDX-07 | [index](../guide/scheduler/index.md) · Visual timeline | yes / tested | yes / untested | **differs**: DC draws a one-off only on its date |  | **behavioural** (display): one-off drawn only on its date (the Modbus Bridge draws it every week) |  |
| IDX-08 | [index](../guide/scheduler/index.md) · The entry list | no | yes / tested | Direct Connect only: Turn on/off partial PUT merged (fixed 0.5.2) |  |  | [#157](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/157) |
| IDX-09 | [index](../guide/scheduler/index.md) · The entry list | no | yes / unclear | Direct Connect only: PUT without enabled re-enables |  |  | [#168](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/168) |
| IDX-10 | [index](../guide/scheduler/index.md) · Templates, export and import | no | yes / tested | Direct Connect only: eleven presets incl. four force presets (MB has four different templates) |  |  |  |
| IDX-11 | [index](../guide/scheduler/index.md) · Visual timeline | no | yes / untested | Direct Connect only: timeline ignores gateway and uses container clock |  |  | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| IDX-12 | [index](../guide/scheduler/index.md) · Using schedules from Home Assistant (Direct Connect only) | no | yes / unclear | Direct Connect only: Pause/Resume API ineffective (does not hold a run, tick ignores paused) |  |  | [#200](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/200) |
| CON-01 | [concepts](../guide/scheduler/concepts.md) · The tick | yes / untested | yes / tested | same: DC cadence configurable 5-60 s |  |  |  |
| CON-02 | [concepts](../guide/scheduler/concepts.md) · The tick | yes / tested | yes / untested | **differs**: DC reads all by name; priority only in a same-tick contest |  | **behavioural** (battery): name order, priority only within a tick: decides which force runs |  |
| CON-03 | [concepts](../guide/scheduler/concepts.md) · The tick | yes / tested | yes / tested | same: none |  |  |  |
| CON-04 | [concepts](../guide/scheduler/concepts.md) · The tick | yes / tested | yes / tested | same: DC: per-resource claims (battery, grid, circuit) |  |  |  |
| CON-05 | [concepts](../guide/scheduler/concepts.md) · The tick | yes / untested | yes / untested | **differs**: DC waits for the next tick (<=15 s) |  | variance: same write, up to one tick (<=15 s) later |  |
| CON-06 | [concepts](../guide/scheduler/concepts.md) · The tick | yes / unclear | yes / untested | **differs**: DC has no module switch |  | variance: the Modbus Bridge switch hides routes but the engine still runs: same writes |  |
| CON-07 | [concepts](../guide/scheduler/concepts.md) · Legacy and v2 entries | yes / untested | no | **missing here**: DC has one format | **Unknown**: none found; the page states one format, not why |  |  |
| CON-08 | [concepts](../guide/scheduler/concepts.md) · The tick | no | yes / tested | Direct Connect only: stale/disabled/never-polled gateway skipped (max(90 s, 3 polls)) |  |  |  |
| CON-09 | [concepts](../guide/scheduler/concepts.md) · Window, activation and run | no | yes / tested | Direct Connect only: stored occurrences: fire once per occurrence, retry while failed |  |  |  |
| CON-10 | [concepts](../guide/scheduler/concepts.md) · What the engine remembers | no | yes / untested | Direct Connect only: last fired occurrence, runs and dispatches survive restart |  |  |  |
| TRG-01 | [triggers](../guide/scheduler/triggers.md) · Fire-based triggers: the active window | yes / tested | yes / tested | same: none |  |  |  |
| TRG-02 | [triggers](../guide/scheduler/triggers.md) · Fire-based triggers: the active window | yes / untested | yes / untested | **differs**: DC: the one Fire at minute; force has no own timer, released at next tick after |  | variance: both release about a minute after a zero-duration fire |  |
| TRG-03 | [triggers](../guide/scheduler/triggers.md) · Fire-based triggers: the active window | yes / tested | yes / untested | same: none |  |  |  |
| TRG-04 | [triggers](../guide/scheduler/triggers.md) · Recurring windows | yes / tested | yes / untested | same: untested in DC |  |  |  |
| TRG-05 | [triggers](../guide/scheduler/triggers.md) · Recurring windows | yes / tested | yes / tested | same: none |  |  |  |
| TRG-06 | [triggers](../guide/scheduler/triggers.md) · Recurring windows | yes / untested | yes / tested | **differs**: DC: each window is its own occurrence (fires once per window) Modbus Bridge check (their PR #233): separate windows each fire there too; only back-to-back windows merge. |  | variance: both fire once per window |  |
| TRG-07 | [triggers](../guide/scheduler/triggers.md) · Recurring windows | yes / tested | yes / untested | same: DC: end <= start wraps |  |  |  |
| TRG-08 | [triggers](../guide/scheduler/triggers.md) · Recurring windows | yes / untested | yes / untested | **differs**: DC attributes the after-midnight part to the day it opened |  | **behavioural** (battery): the after-midnight part follows the opening day's calendar: a force may run on a day the Modbus Bridge skips |  |
| TRG-09 | [triggers](../guide/scheduler/triggers.md) · Recurring windows | yes / tested | yes / unclear | **differs**: DC: start == end is a 24-hour window |  | **behavioural** (battery): start = end is open all day: a force runs 24 h | [#198](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/198) |
| TRG-10 | [triggers](../guide/scheduler/triggers.md) · Recurring windows | yes / untested | yes / untested | **differs**: DC: 24:00 = end of day; unparsable window dropped, empty list falls back to fire_at |  | **behavioural** (battery): an unparsable window falls back to Fire at + duration instead of 00:00 |  |
| TRG-11 | [triggers](../guide/scheduler/triggers.md) · One-off date window | yes / tested | yes / tested | **differs**: DC: stored days still restrict; form shows windows that are ignored |  | **behavioural** (battery): stored days still restrict a one-off, so it may not fire |  |
| TRG-12 | [triggers](../guide/scheduler/triggers.md) · One-off date window | yes / tested | yes / tested | same: DC card has no 'passed' label |  |  |  |
| TRG-13 | [triggers](../guide/scheduler/triggers.md) · One-off date window | yes / untested | yes / untested | **differs**: DC runs past midnight into the next date Modbus Bridge check (their PR #233): an overnight one-off there also runs from 00:00 on its own date. |  | **behavioural** (battery): an overnight one-off keeps forcing past midnight |  |
| TRG-14 | [triggers](../guide/scheduler/triggers.md) · Daily at time | yes / tested | yes / tested | same: none |  |  |  |
| TRG-15 | [triggers](../guide/scheduler/triggers.md) · Daily at time | yes / untested | yes / untested | same: form max 1440 |  |  |  |
| TRG-16 | [triggers](../guide/scheduler/triggers.md) · Weekly at time | yes / tested | yes / tested | **differs**: DC: no days = every day |  | **behavioural** (battery): weekly with no days fires every day (Modbus Bridge: never) |  |
| TRG-17 | [triggers](../guide/scheduler/triggers.md) · Every N minutes | yes / tested | yes / tested | same: none |  |  |  |
| TRG-18 | [triggers](../guide/scheduler/triggers.md) · Every N minutes | yes / untested | yes / untested | same: untested in DC |  |  |  |
| TRG-19 | [triggers](../guide/scheduler/triggers.md) · Every N minutes | yes / untested | yes / unclear | **differs**: DC next_fire disagrees with the window |  | **behavioural** (display): Next shows a time the engine does not fire at | [#208](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/208) |
| TRG-20 | [triggers](../guide/scheduler/triggers.md) · Every N minutes | yes / tested | yes / untested | same: none |  |  |  |
| TRG-21 | [triggers](../guide/scheduler/triggers.md) · Monthly / calendar | yes / tested | yes / tested | same: none |  |  |  |
| TRG-22 | [triggers](../guide/scheduler/triggers.md) · Monthly / calendar | yes / tested | yes / untested | **differs**: DC does not validate; day 0/None = no restriction |  | **behavioural** (battery): no range check; day 0 = every day, so an invalid entry fires |  |
| TRG-23 | [triggers](../guide/scheduler/triggers.md) · Monthly / calendar | yes / untested | yes / untested | **differs**: DC: no day of month = fires every day Modbus Bridge check (their PR #233): monthly with no day fires on the 1st there. |  | **behavioural** (battery): monthly with no day fires every day | [#198](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/198) |
| TRG-24 | [triggers](../guide/scheduler/triggers.md) · Custom cron | yes / tested | yes / untested | **differs**: DC accepts it; never fires |  | **behavioural** (record): invalid cron saved instead of rejected; never fires in either |  |
| TRG-25 | [triggers](../guide/scheduler/triggers.md) · Custom cron | yes / untested | yes / untested | same: untested in DC |  |  |  |
| TRG-26 | [triggers](../guide/scheduler/triggers.md) · Custom cron | yes / tested | yes / tested | same: none |  |  |  |
| TRG-27 | [triggers](../guide/scheduler/triggers.md) · Always evaluate | yes / tested | yes / tested | **differs**: DC: window = conditions; fires on rising edge |  | **behavioural** (battery): Always fires on the rising edge, not continuously |  |
| TRG-28 | [triggers](../guide/scheduler/triggers.md) · Always evaluate | yes / untested | yes / unclear | **differs**: DC: once EVER (stored occurrence, survives restart); falling edges still release |  | **behavioural** (battery): Always fires once ever, but releases on every falling edge | [#190](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/190) |
| TRG-29 | [triggers](../guide/scheduler/triggers.md) · Always evaluate | yes / unclear | yes / unclear | **differs**: DC: stored occurrence row, never pruned |  | **behavioural** (battery): stored occurrence never pruned keeps Always from firing again | [#190](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/190) |
| TRG-30 | [triggers](../guide/scheduler/triggers.md) · Always evaluate | yes / untested | yes / tested | **differs**: DC does release on the falling edge |  | **behavioural** (battery): falling edge sends Release (the Modbus Bridge does not re-check) |  |
| TRG-31 | [triggers](../guide/scheduler/triggers.md) · Quick presets | yes / untested | yes / untested | same: DC preset list differs |  |  |  |
| TRG-32 | [triggers](../guide/scheduler/triggers.md) · Next fire | yes / tested | yes / tested | **differs**: DC searches 366 days; container clock |  | **behavioural** (display): Next uses the container clock | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| TRG-33 | [triggers](../guide/scheduler/triggers.md) · Next fire | yes / untested | yes / tested | **differs**: DC: inside window AND fired this occurrence |  | **behavioural** (display): `active_now` also needs a fire; changes Stop/Run now |  |
| TRG-34 | [triggers](../guide/scheduler/triggers.md) · Editing a trigger in the form | yes / untested | yes / unclear | **differs**: DC: hidden duration_min (default 90) also limits a scheduled force |  | **behavioural** (battery): hidden 90 min duration cuts a window force short | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| TRG-35 | [triggers](../guide/scheduler/triggers.md) · Editing a trigger in the form | yes / untested | no | **missing here**: DC has no API oneoff type | **Unknown**: none found; no API `oneoff` type here |  |  |
| TRG-36 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / tested | no | **missing here**: DC: stale gateway skipped; no outage record | **Not ported**: [ORCH 2b][bl-orch] (catch-up on outage); [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-37 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / tested | no | **missing here**: no catch-up | **Not ported**: [ORCH 2b][bl-orch] (catch-up); [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-38 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / tested | no | **missing here**: no catch-up | **Not ported**: [ORCH 2b][bl-orch] (catch-up after restart); [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-39 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / tested | no | **missing here**: no catch-up | **Depends on**: catch-up (TRG-37) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-40 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / tested | yes / tested | **differs**: DC: claimed runs whose window ended >120 s ago marked missed |  | **behavioural** (record): missed rows come from stale claims, not outages |  |
| TRG-41 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / untested | yes / untested | **differs**: DC: an unclaimed window leaves no missed row |  | **behavioural** (record): a window no tick saw leaves no missed row |  |
| TRG-42 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / untested | no | **missing here**: no missed policy | **Depends on**: catch-up missed policy (TRG-37) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-43 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / tested | no | **missing here**: no late fire | **Depends on**: catch-up (TRG-37) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-44 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / untested | no | **missing here**: no late fire | **Depends on**: catch-up (TRG-37) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-45 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / untested | no | **missing here**: no late fire | **Depends on**: catch-up (TRG-37) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-46 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / untested | no | **missing here**: no late fire | **Depends on**: catch-up (TRG-37) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-47 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / untested | no | **missing here**: no catch-up | **Depends on**: catch-up (TRG-37) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-48 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | yes / untested | no | **missing here**: no missed policy | **Depends on**: catch-up (TRG-37) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-49 | [triggers](../guide/scheduler/triggers.md) · Summary | no | yes / untested | Direct Connect only: calendar restrictions apply to every trigger type |  |  |  |
| TRG-50 | [triggers](../guide/scheduler/triggers.md) · Recurring windows | no | yes / tested | Direct Connect only: start/end date range restriction with a reason |  |  |  |
| TRG-51 | [triggers](../guide/scheduler/triggers.md) · One-off date window | no | yes / unclear | Direct Connect only: One-off ignores its Time windows; no date = every day |  |  | [#198](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/198) |
| TRG-52 | [triggers](../guide/scheduler/triggers.md) · Next fire | no | yes / unclear | Direct Connect only: next_fire/active_now on container clock |  |  | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| TRG-53 | [triggers](../guide/scheduler/triggers.md) · Editing a trigger in the form | no | yes / untested | Direct Connect only: trigger type change seeds defaults |  |  |  |
| TRG-54 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | no | yes / untested | Direct Connect only: no late fire ever |  |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TRG-55 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | no | yes / tested | Direct Connect only: stale snapshot skips evaluation |  |  |  |
| TRG-56 | [triggers](../guide/scheduler/triggers.md) · After an outage or a restart (catch-up) | no | yes / tested | Direct Connect only: older open runs coalesced |  |  |  |
| CND-01 | [conditions](../guide/scheduler/conditions.md) · Rules for every condition | yes / tested | yes / tested | same: none |  |  |  |
| CND-02 | [conditions](../guide/scheduler/conditions.md) · Rules for every condition | yes / tested | yes / untested | **differs**: import does not warn about unknown sensors |  | **behavioural** (record): import accepts unknown sensors silently | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| CND-03 | [conditions](../guide/scheduler/conditions.md) · Rules for every condition | yes / tested | yes / untested | **differs**: same idea, but every gateway tick also fetches each HA instance's whole /api/states |  | variance: one snapshot per gateway per tick in both; HA read differs |  |
| CND-04 | [conditions](../guide/scheduler/conditions.md) · Rules for every condition | yes / untested | yes / untested | same: none; on/off sensors are stored as int 1/0 |  |  |  |
| CND-05 | [conditions](../guide/scheduler/conditions.md) · Operators | yes / tested | yes / tested | same: none |  |  |  |
| CND-06 | [conditions](../guide/scheduler/conditions.md) · Operators | yes / tested | yes / untested | **differs**: DC compares text case-insensitively; untested |  | **behavioural** (battery): case-insensitive text: a condition can pass that fails there |  |
| CND-07 | [conditions](../guide/scheduler/conditions.md) · Operators | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-08 | [conditions](../guide/scheduler/conditions.md) · Operators | yes / tested | yes / untested | **differs**: brackets not stripped; untested here |  | **behavioural** (battery): bracketed lists and text members parse differently: condition result can differ |  |
| CND-09 | [conditions](../guide/scheduler/conditions.md) · Operators | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-10 | [conditions](../guide/scheduler/conditions.md) · Operators | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-11 | [conditions](../guide/scheduler/conditions.md) · Operators | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-12 | [conditions](../guide/scheduler/conditions.md) · Operators | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-13 | [conditions](../guide/scheduler/conditions.md) · Value and Lookup | yes / untested | yes / untested | same: none |  |  |  |
| CND-14 | [conditions](../guide/scheduler/conditions.md) · Value and Lookup | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-15 | [conditions](../guide/scheduler/conditions.md) · Value and Lookup | yes / untested | yes / untested | **differs**: Explain prints the Lookup label; Test against live prints an empty RHS |  | variance: display text of a Lookup only; evaluation is the same |  |
| CND-16 | [conditions](../guide/scheduler/conditions.md) · Groups and items: ALL / ANY | yes / tested | yes / tested | same: empty top-level block is true even with match any |  |  |  |
| CND-17 | [conditions](../guide/scheduler/conditions.md) · Groups and items: ALL / ANY | yes / tested | yes / tested | same: none |  |  |  |
| CND-18 | [conditions](../guide/scheduler/conditions.md) · Groups and items: ALL / ANY | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-19 | [conditions](../guide/scheduler/conditions.md) · Groups and items: ALL / ANY | yes / untested | yes / untested | **differs**: empty block saved as [] (same effect) |  | variance: [] and null have the same effect |  |
| CND-20 | [conditions](../guide/scheduler/conditions.md) · Groups and items: ALL / ANY | yes / untested | yes / untested | **differs**: an empty ALL exit group blocks the schedule from starting (exit condition already holds) |  | **behavioural** (battery): an empty ALL exit group stops the schedule ever starting |  |
| CND-21 | [conditions](../guide/scheduler/conditions.md) · Scope: which gateway's values | yes / untested | yes / untested | same: applies to gateway_scope all; untested |  |  |  |
| CND-22 | [conditions](../guide/scheduler/conditions.md) · Scope: which gateway's values | yes / untested | yes / tested | **differs**: DC measures each gateway against its own meter (better) |  | **behavioural** (battery): multi-gateway: tariff/billing sensors from each gateway's own meter, so conditions can differ |  |
| CND-23 | [conditions](../guide/scheduler/conditions.md) · Hold for (dwell) | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-24 | [conditions](../guide/scheduler/conditions.md) · Hold for (dwell) | yes / tested | yes / untested | same: untested here |  |  |  |
| CND-25 | [conditions](../guide/scheduler/conditions.md) · Hold for (dwell) | yes / untested | yes / untested | same: none |  |  |  |
| CND-26 | [conditions](../guide/scheduler/conditions.md) · Hold for (dwell) | yes / tested | yes / untested | **differs**: no maximum; untested here |  | **behavioural** (record): hold over 86400 s accepted |  |
| CND-27 | [conditions](../guide/scheduler/conditions.md) · Hold for (dwell) | yes / untested | yes / untested | **differs**: a retry waits the whole hold again |  | **behavioural** (battery): a retry waits the whole hold again, delaying the force | [#203](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/203) |
| CND-28 | [conditions](../guide/scheduler/conditions.md) · When conditions are evaluated | yes / tested | yes / untested | same: none |  |  |  |
| CND-29 | [conditions](../guide/scheduler/conditions.md) · When conditions are evaluated | yes / tested | yes / untested | **differs**: once per calendar day per gateway, up to two leaves; untested |  | **behavioural** (record): gated logged once a day, two leaves |  |
| CND-30 | [conditions](../guide/scheduler/conditions.md) · Test Verification | yes / tested | yes / tested | **differs**: editor Test uses the top-bar gateway, not the schedule's |  | **behavioural** (display): editor Test evaluates the top-bar gateway, not the schedule's |  |
| CND-31 | [conditions](../guide/scheduler/conditions.md) · Test Verification | yes / untested | yes / unclear | **differs**: Test against live reads the default gateway and container clock, top-level rows only, no exit/hold/conflict check |  | **behavioural** (display): Test against live: default gateway, container clock, top-level rows only | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| CND-32 | [conditions](../guide/scheduler/conditions.md) · Test Verification | yes / untested | yes / untested | **differs**: no login on this bridge's HTTP API |  | variance: no login anywhere on this bridge (LAN trust, [BACKLOG][bl-auth]); evaluate writes nothing |  |
| CND-33 | [conditions](../guide/scheduler/conditions.md) · Home Assistant entities | yes / tested | yes / tested | same: since 0.5.4 unavailable/unknown are no reading, as in the Modbus Bridge; before 0.5.4 they read 0 |  |  | [#167](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/167) (fixed in 0.5.4) |
| CND-34 | [conditions](../guide/scheduler/conditions.md) · Home Assistant entities | yes / tested | yes / tested | **differs**: REST /api/states (whole list) every tick of every gateway; no WebSocket |  | variance: REST each tick vs WebSocket: same values per tick |  |
| CND-35 | [conditions](../guide/scheduler/conditions.md) · Home Assistant entities | yes / tested | yes / untested | **differs**: no such warning |  | **behavioural** (record): no warning for an unexposed HA entity | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| CND-36 | [conditions](../guide/scheduler/conditions.md) · Conditions (intro) | no | yes / untested | Direct Connect only: DC evaluates exit conditions for every action kind while the window is open |  |  |  |
| CND-37 | [conditions](../guide/scheduler/conditions.md) · Home Assistant entities | no | yes / tested | Direct Connect only: DC auto-scales $/kWh to c/kWh (tested) |  |  |  |
| SEN-01 | [conditions](../guide/scheduler/conditions.md) · Notes on some sensors | yes / tested | no | **missing here**: no time.* sensors; use calendar restrictions | **Not ported**: [SENSOR-PARITY §A][bl-sens] `time.*` |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| SEN-02 | [conditions](../guide/scheduler/conditions.md) · Notes on some sensors | yes / tested | no | **missing here**: no time.* sensors | **Not ported**: [SENSOR-PARITY §A][bl-sens] `time.*` |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| SEN-03 | [conditions](../guide/scheduler/conditions.md) · Notes on some sensors | yes / tested | yes / tested | same: none |  |  |  |
| SEN-04 | [conditions](../guide/scheduler/conditions.md) · Grid | yes / tested | yes / tested | **differs**: DC derives it from grid power != 0, so it reads 0 at exactly 0 W while on grid |  | **behavioural** (battery): `grid.connected` reads 0 at exactly 0 W: a grid gate can fire a force | [#206](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/206) |
| SEN-05 | [conditions](../guide/scheduler/conditions.md) · Battery | yes / tested | no | **missing here**: no reserve sensors | **Not ported**: [SENSOR-PARITY §A][bl-sens] `battery.reserve_*`; reserve is readable locally as 1726 `reserved_soc` ([PROTOCOL.md][dca-proto]), so not a transport limit |  |  |
| SEN-06 | [conditions](../guide/scheduler/conditions.md) · Notes on some sensors | yes / tested | yes / tested | same: capacity is a user constant (no local capacity register); rate falls back to a constant |  |  |  |
| SEN-07 | [conditions](../guide/scheduler/conditions.md) · Constants | yes / tested | yes / tested | same: DC adds default operating mode; capacity/max power not in the picker |  |  |  |
| SEN-08 | [conditions](../guide/scheduler/conditions.md) · Tariff | yes / tested | yes / tested | **differs**: from the gateway's meter; None when undefined (fails closed) |  | **behavioural** (battery): undefined window is None (fails closed) not False: `== 0` gates differ |  |
| SEN-09 | [conditions](../guide/scheduler/conditions.md) · Tariff | yes / tested | yes / untested | same: untested here |  |  |  |
| SEN-10 | [conditions](../guide/scheduler/conditions.md) · Tariff | yes / tested | yes / tested | **differs**: last good NEM price kept however old |  | **behavioural** (battery): stale NEM price kept: price-gated forces run on old prices | [#207](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/207) |
| SEN-11 | [conditions](../guide/scheduler/conditions.md) · Utility Plan | yes / tested | yes / tested | same: none |  |  |  |
| SEN-12 | [conditions](../guide/scheduler/conditions.md) · Utility Plan | yes / tested | no | **missing here**: no such sensor | **Not ported**: [SENSOR-PARITY §A][bl-sens] `service.tz_matches_clock` |  |  |
| SEN-13 | [conditions](../guide/scheduler/conditions.md) · Weather | yes / tested | yes / untested | same: untested here; weather.code not in the picker |  |  |  |
| SEN-14 | [conditions](../guide/scheduler/conditions.md) · Gateway identity | yes / untested | no | **missing here**: no gateway.* sensors; system.* describe the install | **Not ported**: [SENSOR-PARITY §A][bl-sens] `gateway.*` |  |  |
| SEN-15 | [conditions](../guide/scheduler/conditions.md) · Other | yes / tested | no | **missing here**: no dispatch.* sensors | **Not ported**: [SENSOR-PARITY §A][bl-sens] `dispatch.*` |  |  |
| SEN-16 | [conditions](../guide/scheduler/conditions.md) · Other | yes / unclear | no | **missing here**: no dispatch.* sensors | **Depends on**: `dispatch.*` sensors (SEN-15) |  |  |
| SEN-17 | [conditions](../guide/scheduler/conditions.md) · Energy | yes / tested | no | **missing here**: only billing-period import/export cost sensors | **Depends on**: FEAT-BILLING-SERVICE, per [SENSOR-PARITY §B][bl-sens] |  |  |
| SEN-18 | [conditions](../guide/scheduler/conditions.md) · Every sensor in the picker | no | yes / tested | Direct Connect only: different groups (Gateway, Derived Battery, …, one per HA instance) |  |  |  |
| SEN-19 | [conditions](../guide/scheduler/conditions.md) · Tariff | no | yes / untested | Direct Connect only: DC keeps the last good NEM price with no age limit |  |  | [#207](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/207) |
| ACT-01 | [actions](../guide/scheduler/actions.md) · Summary | yes / untested | yes / tested | same: none |  |  |  |
| ACT-02 | [actions](../guide/scheduler/actions.md) · Summary | yes / untested | yes / untested | **differs**: DC validates no action at save; failures appear only at run |  | **behavioural** (battery): invalid actions saved; fail only at run | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| ACT-03 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / tested | yes / untested | **differs**: DC sizes pct against the 702 rating or a 5000 W fallback; no trusted rating |  | **behavioural** (battery): % sized on 702 or a 5000 W fallback, no trusted rating: different watts written |  |
| ACT-04 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / tested | yes / unclear | **differs**: DC empty power = 0 W; form seeds 100 % |  | **behavioural** (battery): empty power is a 0 W force | [#209](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/209) |
| ACT-05 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / untested | yes / untested | **differs**: DC offers % and kW in the form, W via API |  | **behavioural** (battery): percent accepted; any unknown unit is read as percent |  |
| ACT-06 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / untested | no | **missing here**: DC has no params validation at all (see ACT-02) | **Depends on**: save-time validation [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |  |  |
| ACT-07 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / tested | no | **missing here**: no legacy format here | **Unknown**: none found; legacy `power_pct` format never existed here |  |  |
| ACT-08 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / untested | no | **missing here**: n/a | **Unknown**: none found; legacy format |  |  |
| ACT-09 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / untested | no | **missing here**: n/a | **Unknown**: none found; legacy format |  |  |
| ACT-10 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / unclear | yes / unclear | **differs**: DC does not cap W/kW (library behaviour unverified) |  | **behavioural** (battery): W/kW not capped by the bridge at 702 |  |
| ACT-11 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / tested | no | **missing here**: no trust model | **Unknown**: none found; [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) does not list a rating trust model |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| ACT-12 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / tested | no | **missing here**: DC refuses only when the Modbus client is not ready (ACT-30) | **Depends on**: trusted rating (ACT-11) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| ACT-13 | [actions](../guide/scheduler/actions.md) · Power and sizing | yes / tested | yes / unclear | **differs**: DC classifies a capability refusal as OK: logged fired, not retried |  | **behavioural** (battery): a refused force is logged fired and never retried | [#191](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/191) (fixed, unreleased) |
| ACT-14 | [actions](../guide/scheduler/actions.md) · What is written | yes / tested | yes / untested | **differs**: DC sends one BatteryCommand via the library and trusts its return; no read-back |  | **behavioural** (battery): no WSetEna read-back check: a force can be recorded as sent when it did not take |  |
| ACT-15 | [actions](../guide/scheduler/actions.md) · What is written | yes / untested | yes / untested | **differs**: DC: bridge watchdog releases; hardware timer called cosmetic in a code comment (unverified) |  | **behavioural** (battery): WSetRvrtTms not written (the library writes WSetEna/WSetMod/WSetPct only); PICS Issue 4 calls it cosmetic |  |
| ACT-16 | [actions](../guide/scheduler/actions.md) · What is written | yes / unclear | no | **missing here**: no staging in the scheduler path | **Unknown**: none found; the force here is one `BatteryCommand` (`battery_control.py:534`), no staging |  |  |
| ACT-17 | [actions](../guide/scheduler/actions.md) · Parameters you can set only through the API | yes / tested | yes / untested | **differs**: DC time limit is always duration_min x 60; hidden 90 min in Recurring windows |  | **behavioural** (battery): time limit = duration_min x 60, hidden 90 min in windows | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| ACT-18 | [actions](../guide/scheduler/actions.md) · Parameters you can set only through the API | yes / untested | yes / untested | **differs**: DC target SoC is in the form; checked every 5 s from the poller |  | variance: same release rule at the same 5 s cadence; target in the form here |  |
| ACT-19 | [actions](../guide/scheduler/actions.md) · Parameters you can set only through the API | yes / untested | yes / untested | **differs**: DC form keeps the whole action object |  | **behavioural** (battery): form save keeps API-only keys (the Modbus Bridge drops `target_soc`): different force end |  |
| ACT-20 | [actions](../guide/scheduler/actions.md) · Battery actions: Force Standby | yes / tested | yes / untested | same: DC still needs a ready Modbus client (this bridge) |  |  |  |
| ACT-21 | [actions](../guide/scheduler/actions.md) · Battery actions: Release | yes / untested | no | **missing here**: no Release action | **Not ported**: [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) ("a Release action"); [SCHEDULE-AND-AUTOMATIONS][bl-sched] |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| ACT-22 | [actions](../guide/scheduler/actions.md) · Non-battery actions: Reserve and Operating Mode | yes / tested | yes / tested | same: DC picker tou/self/backup from gateway work modes |  |  |  |
| ACT-23 | [actions](../guide/scheduler/actions.md) · Non-battery actions: Reserve and Operating Mode | yes / untested | yes / untested | **differs**: DC checks nothing; missing mode fails at run |  | **behavioural** (device/HA): missing mode accepted, fails and retries at run |  |
| ACT-24 | [actions](../guide/scheduler/actions.md) · Non-battery actions: Reserve and Operating Mode | yes / untested | yes / unclear | same: DC also logs a rejected mode or off-grid write as fired |  |  | [#191](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/191) (fixed, unreleased) |
| ACT-25 | [actions](../guide/scheduler/actions.md) · Non-battery actions: Reserve and Operating Mode | yes / tested | no | **missing here**: no write-lock tracking | **Depends on**: read-back of command results [#139](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/139): a 1727 write can be accepted (`result:0`) and not applied ([PROTOCOL.md][dca-proto]) |  |  |
| ACT-26 | [actions](../guide/scheduler/actions.md) · Non-battery actions: Reserve and Operating Mode | yes / untested | yes / untested | same: DC: If busy is force-only; same-tick priority still applies |  |  |  |
| ACT-27 | [actions](../guide/scheduler/actions.md) · No battery action (HA only) | yes / tested | yes / tested | same: none |  |  |  |
| ACT-28 | [actions](../guide/scheduler/actions.md) · No battery action (HA only) | yes / untested | yes / untested | **differs**: DC Run now runs the fire-phase HA actions |  | **behavioural** (device/HA): Run now runs HA actions of HA-only schedules |  |
| ACT-29 | [actions](../guide/scheduler/actions.md) · Summary | no | yes / tested | Direct Connect only: Unknown action kind at run is skipped and logged fired |  |  |  |
| ACT-30 | [actions](../guide/scheduler/actions.md) · Battery actions: Force Charge and Force Discharge | no | yes / untested | Direct Connect only: Force refused unless a SunSpec read through the Modbus client (this bridge) succeeds |  |  |  |
| ACT-31 | [actions](../guide/scheduler/actions.md) · Battery actions: Force Charge and Force Discharge | no | yes / tested | Direct Connect only: No host: force skipped |  |  |  |
| ACT-32 | [actions](../guide/scheduler/actions.md) · Non-battery actions: Reserve and Operating Mode | no | yes / tested | Direct Connect only: reserve_soc always skipped, logged fired |  |  | [#129](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/129) |
| ACT-33 | [actions](../guide/scheduler/actions.md) · Smart circuits, off-grid and notify (Direct Connect only) | no | yes / tested | Direct Connect only: Smart circuit write with read-back; NOT confirmed retried |  |  |  |
| ACT-34 | [actions](../guide/scheduler/actions.md) · Smart circuits, off-grid and notify (Direct Connect only) | no | yes / tested | Direct Connect only: On/Off read strictly since 0.5.5; before it, Off ran as on |  |  | [#188](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/188) (fixed in 0.5.5) |
| ACT-35 | [actions](../guide/scheduler/actions.md) · Smart circuits, off-grid and notify (Direct Connect only) | no | yes / untested | Direct Connect only: Off-grid action with SoC, no confirm |  |  |  |
| ACT-37 | [actions](../guide/scheduler/actions.md) · Summary | no | yes / tested | Direct Connect only: smart_circuit_schedule listed unavailable with reason |  |  |  |
| ACT-38 | [actions](../guide/scheduler/actions.md) · Battery actions: Force Charge and Force Discharge | no | yes / untested | Direct Connect only: Force disabled in the form with the reason when the Modbus client (this bridge) is unavailable |  |  |  |
| ACT-39 | [actions](../guide/scheduler/actions.md) · What is written | no | yes / unclear | Direct Connect only: One in-memory force for the whole bridge; a second gateway's force drops the first's watchdog |  |  | [#194](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/194) (fixed, unreleased) |
| ACT-40 | [actions](../guide/scheduler/actions.md) · What is written | no | yes / untested | Direct Connect only: Up to 5 attempts with sleeps inside one tick; blocks all gateways |  |  | [#197](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/197) (fixed, unreleased) |
| ACT-41 | [actions](../guide/scheduler/actions.md) · What is written | no | yes / unclear | Direct Connect only: UNKNOWN verdict unreachable for scheduler actions |  |  | [#201](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/201) |
| ACT-42 | [actions](../guide/scheduler/actions.md) · What is written | no | yes / unclear | Direct Connect only: Retry deadline falls to 1 s for Always and zero-duration windows |  |  | [#209](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/209) |
| HAA-01 | [actions](../guide/scheduler/actions.md) · Home Assistant actions | yes / untested | yes / tested | **differs**: DC saves anything; skips with a reason at run Modbus Bridge check (their PR #233): its import skips validation too (their #232), so invalid actions can be saved there as well. |  | **behavioural** (device/HA): invalid HA actions saved; skipped at run | [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) |
| HAA-02 | [actions](../guide/scheduler/actions.md) · Home Assistant actions | yes / untested | yes / untested | **differs**: DC form saves incomplete rows |  | **behavioural** (record): incomplete rows kept and skipped at run with a reason |  |
| HAA-03 | [actions](../guide/scheduler/actions.md) · When they run | yes / tested | yes / untested | same: DC: after the battery action whatever its result (HAA-07) |  |  |  |
| HAA-04 | [actions](../guide/scheduler/actions.md) · When they run | yes / tested | yes / untested | same: none |  |  |  |
| HAA-05 | [actions](../guide/scheduler/actions.md) · When they run | yes / tested | yes / untested | same: none |  |  |  |
| HAA-06 | [actions](../guide/scheduler/actions.md) · When they run | yes / tested | yes / unclear | **differs**: DC: at every closing edge of the window, even if never fired; not on Stop or an in-window end |  | **behavioural** (device/HA): exit HA actions run at every window close, even if never fired | by design (kept when #189 was fixed) |
| HAA-07 | [actions](../guide/scheduler/actions.md) · When they run | yes / untested | yes / unclear | **differs**: DC runs them on every attempt |  | **behavioural** (device/HA): on-entry HA actions repeat on every retry | [#203](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/203) |
| HAA-08 | [actions](../guide/scheduler/actions.md) · Guards | yes / tested | yes / untested | **differs**: DC skips silently, no log; API also accepts a tree |  | **behavioural** (record): guard skip leaves no log row |  |
| HAA-09 | [actions](../guide/scheduler/actions.md) · Placeholders in notifications | yes / tested | yes / tested | same: DC prints numbers as stored (no .0 trimming) |  |  |  |
| HAA-10 | [actions](../guide/scheduler/actions.md) · Placeholders in notifications | yes / untested | yes / untested | **differs**: DC: dotted ids work, ha: ids do not |  | **behavioural** (record): `%ha:…%` placeholders not substituted | [#169](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/169) |
| HAA-11 | [actions](../guide/scheduler/actions.md) · Failure alerts | yes / tested | no | **missing here**: no failure notifications | **Not ported**: [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) (notifier not passed to the outcome path) |  | [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) |
| HAA-12 | [actions](../guide/scheduler/actions.md) · What is logged | yes / tested | yes / untested | **differs**: DC folds results into the fired/exit/manual row; failures rarely fail the run |  | **behavioural** (record): HA failures folded into the run row; rarely fail the run |  |
| HAA-13 | [actions](../guide/scheduler/actions.md) · Failure alerts | no | yes / untested | Direct Connect only: run_action_outcome called without notifier |  |  | [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) |
| HAA-14 | [actions](../guide/scheduler/actions.md) · Placeholders in notifications | no | yes / tested | Direct Connect only: Placeholders also in service entity_id and data |  |  |  |
| HAA-15 | [actions](../guide/scheduler/actions.md) · Home Assistant actions | no | yes / tested | Direct Connect only: Raw service with bad JSON is skipped with the reason |  |  |  |
| HAA-16 | [actions](../guide/scheduler/actions.md) · Home Assistant actions | no | yes / tested | Direct Connect only: Guided entity action calls domain.service with entity and data |  |  |  |
| HAA-17 | [actions](../guide/scheduler/actions.md) · Placeholders in notifications | no | yes / tested | Direct Connect only: %run.*%, %schedule.*%, %gateway.id% variables |  |  |  |
| HAA-18 | [actions](../guide/scheduler/actions.md) · Home Assistant actions | no | yes / untested | Direct Connect only: Notify as a battery action kind |  |  |  |
| TGT-01 | [targets](../guide/scheduler/targets.md) · Pick a target | yes / untested | yes / tested | **differs**: DC: bound schedule only on its gateway's tick; not evaluated while stale/disabled |  | **behavioural** (battery): a stale or disabled gateway's schedules are not evaluated |  |
| TGT-02 | [targets](../guide/scheduler/targets.md) · Pick a target | yes / untested | yes / untested | **differs**: DC: API-only gateway_scope all; no Site target in the form |  | **behavioural** (display): site fan-out only through the API | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TGT-03 | [targets](../guide/scheduler/targets.md) · Pick a target | yes / untested | no | **missing here**: no utility-service target | **Not ported**: [ORCH 2b][bl-orch] (Target = Service); [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| TGT-04 | [targets](../guide/scheduler/targets.md) · How a fan-out works | yes / tested | yes / tested | same: DC: occurrence and resource claim per gateway |  |  |  |
| TGT-05 | [targets](../guide/scheduler/targets.md) · How a fan-out works | yes / tested | yes / untested | same: DC: per gateway:entry; but see TGT-20 and ACT-39 |  |  |  |
| TGT-06 | [targets](../guide/scheduler/targets.md) · How a fan-out works | yes / tested | yes / untested | **differs**: History rows do not name the gateway |  | **behavioural** (record): History rows do not name the gateway | [#205](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/205) |
| TGT-07 | [targets](../guide/scheduler/targets.md) · How a fan-out works | yes / untested | yes / unclear | same: DC: a stale/disabled gateway gets no window-end release either |  |  |  |
| TGT-08 | [targets](../guide/scheduler/targets.md) · How a fan-out works | yes / untested | yes / tested | same: DC: stale/disabled gateway skipped with a debug log only |  |  |  |
| TGT-09 | [targets](../guide/scheduler/targets.md) · How a fan-out works | yes / untested | yes / unclear | **differs**: DC Run now: one gateway, and the top-bar gateway overrides the bound one |  | **behavioural** (battery): Run now forces the top-bar gateway, not the schedule's | [#193](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/193) (fixed, unreleased) |
| TGT-10 | [targets](../guide/scheduler/targets.md) · Entries with no target id | yes / untested | yes / untested | same: DC unbound = the stored default gateway |  |  | [#182](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/182) (fixed, unreleased) |
| TGT-11 | [targets](../guide/scheduler/targets.md) · Entries with no target id | yes / unclear | yes / untested | **differs**: DC: unbound claims the tick gateway, same group as bound |  | **behavioural** (battery): unbound and bound contend as one group (two groups there) |  |
| TGT-12 | [targets](../guide/scheduler/targets.md) · In the form | yes / unclear | no | **missing here**: no service select | **Depends on**: service target (TGT-03) |  |  |
| TGT-13 | [targets](../guide/scheduler/targets.md) · In the form | yes / untested | no | **missing here**: no mock warning in the form | **Unknown**: none found |  |  |
| TGT-14 | [targets](../guide/scheduler/targets.md) · In the form | yes / tested | yes / tested | same: none |  |  |  |
| TGT-15 | [targets](../guide/scheduler/targets.md) · On the timeline | yes / untested | yes / untested | **differs**: DC timeline ignores gateway; one list |  | **behavioural** (display): timeline is one list, not per gateway | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| TGT-16 | [targets](../guide/scheduler/targets.md) · How a fan-out works | yes / unclear | no | **missing here**: n/a; see TGT-07 | **Depends on**: run ownership (EXT-06, [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189)) and site/service targets |  |  |
| TGT-17 | [targets](../guide/scheduler/targets.md) · Entries with no target id | no | yes / unclear | Direct Connect only: Disabled first gateway: unbound schedules run nowhere |  |  | [#182](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/182) |
| TGT-18 | [targets](../guide/scheduler/targets.md) · In the form | no | yes / tested | Direct Connect only: Mock gateways skip the 702 ratings read |  |  |  |
| TGT-19 | [targets](../guide/scheduler/targets.md) · In the form | no | yes / untested | Direct Connect only: Test against live always uses the default gateway |  |  |  |
| TGT-20 | [targets](../guide/scheduler/targets.md) · How a fan-out works | no | yes / unclear | Direct Connect only: Stop, Pause, shutdown and boot reconcile use the default gateway's host |  |  | [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) (fixed, unreleased) |
| TGT-21 | [targets](../guide/scheduler/targets.md) · Pick a target | no | yes / untested | Direct Connect only: Gateway select only with >1 gateway; Default gateway = empty id |  |  |  |
| TGT-22 | [targets](../guide/scheduler/targets.md) · Pick a target | no | yes / untested | Direct Connect only: Schedule bound to an unknown gateway id never runs, silently |  |  |  |
| TGT-23 | [targets](../guide/scheduler/targets.md) · Pick a target | no | yes / tested | Direct Connect only: gateway_scope survives a form save (#157 fix) |  |  | [#157](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/157) |
| EXT-01 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | yes / tested | yes / tested | **differs**: DC releases at every force entry's window close, owned or not; logged exit 'window closed' |  | **behavioural** (battery): window close releases a force it never sent or does not own | [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) (fixed, unreleased) |
| EXT-02 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | yes / tested | yes / tested | same: none; DC marks the occurrence fired |  |  |  |
| EXT-03 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | yes / tested | yes / tested | **differs**: DC uses per-occurrence keys instead of clearing a mark |  | variance: per-occurrence keys vs clearing a mark: both fire again next window |  |
| EXT-04 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | yes / tested | yes / untested | **differs**: DC: disable releases on next tick; delete does not release |  | **behavioural** (battery): delete does not release the running force | [#195](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/195) (fixed, unreleased) |
| EXT-05 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | yes / unclear | yes / unclear | **differs**: DC never hands over; it always releases, even another's force |  | **behavioural** (battery): never hands over; releases another's force | [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) (fixed, unreleased) |
| EXT-06 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | yes / unclear | no | **missing here**: no ownership hand-over in DC | **Not ported**: [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) (no ownership: window end releases a force it does not own) |  |  |
| EXT-07 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Exit conditions | yes / tested | yes / tested | **differs**: DC does not start when exit already holds |  | **behavioural** (battery): exit already true: no start here; a brief force there |  |
| EXT-08 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Exit conditions | yes / tested | yes / tested | same: none (DC plain release) |  |  |  |
| EXT-09 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Exit conditions | yes / untested | yes / untested | **differs**: DC evaluates exit for every action kind while the window is open |  | **behavioural** (device/HA): exit evaluated for every action kind (mode, HA-only) |  |
| EXT-10 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Exit conditions | yes / untested | yes / tested | **differs**: DC detail names no rows |  | **behavioural** (record): exit row names no condition |  |
| EXT-11 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Release policy | yes / tested | no | **missing here**: no release policies; always plain release | **Not ported**: [ORCH 2b][bl-orch] (on-exit release policy); [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| EXT-12 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Release policy | yes / tested | yes / untested | **differs**: DC restore_on_exit (API only) writes the captured mode back, set_mode schedules only; end-to-end untested |  | **behavioural** (device/HA): `restore_on_exit` writes the mode back (the Modbus Bridge only audits) | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| EXT-13 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Release policy | yes / tested | no | **missing here**: not in DC | **Not ported**: [ORCH 2b][bl-orch] (release policy); [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| EXT-14 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Release policy | yes / tested | no | **missing here**: no policies; DC Stop never restores | **Not ported**: [ORCH 2b][bl-orch] (release policy); [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| EXT-15 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Release policy | yes / untested | no | **missing here**: no field | **Depends on**: release policy (EXT-11) |  |  |
| EXT-16 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Release policy | yes / untested | no | **missing here**: no such migration | **Depends on**: release policy (EXT-11); the migration is the Modbus Bridge's own |  |  |
| EXT-17 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · What a release does on the gateway | yes / tested | yes / untested | **differs**: DC release has no read-back; refused when Modbus client off |  | **behavioural** (battery): Release refused when the Modbus client (this bridge) is off; no read-back | [#174](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/174) |
| EXT-18 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Hold instead of release (API only) | yes / tested | no | **missing here**: no hold | **Not ported**: [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) ("hold instead of release") |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| EXT-19 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Hold instead of release (API only) | yes / unclear | no | **missing here**: no hold | **Depends on**: hold (EXT-18) |  |  |
| EXT-20 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Bridge shutdown | yes / untested | yes / unclear | **differs**: DC releases the in-memory force to the first gateway's host, not the force's host |  | **behavioural** (battery): shutdown releases to the first gateway's host | [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) (fixed, unreleased) |
| EXT-21 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | no | yes / unclear | Direct Connect only: DC: deleting a running schedule does not release its force |  |  | [#195](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/195) (fixed, unreleased) |
| EXT-22 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Exit conditions | no | yes / tested | Direct Connect only: nested exit groups (MB also supports; tested here) |  |  |  |
| EXT-24 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | no | yes / unclear | Direct Connect only: flapping exit conditions repeat Release and exit HA actions |  |  | [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) (fixed, unreleased) |
| EXT-25 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | no | yes / unclear | Direct Connect only: force watchdog uses hidden duration_min in Recurring windows |  |  | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| EXT-26 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · How a run ends | no | yes / untested | Direct Connect only: bridge watchdog enforces duration and target SoC every 5 s |  |  |  |
| EXT-27 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Release policy | no | yes / tested | Direct Connect only: restore_on_exit captures mode before first attempt |  |  |  |
| EXT-28 | [exit-and-conflicts](../guide/scheduler/exit-and-conflicts.md) · Release policy | no | yes / tested | Direct Connect only: PUT merge keeps restore_on_exit |  |  | [#157](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/157) |
| PRI-01 | [priorities](../guide/scheduler/priorities.md) · Priorities and conflicts | yes / untested | yes / untested | **differs**: DC: any integer, free-text conflict (unknown = override), default override Modbus Bridge check (their PR #233): its import skips validation (their #232); the default and unknown-value handling are as their code, not their old markers. |  | **behavioural** (battery): default If busy = override (there: defer); unknown values act as override |  |
| PRI-02 | [priorities](../guide/scheduler/priorities.md) · Entries on the same target | yes / tested | yes / tested | **differs**: DC: contest only among entries ready on the same tick, per resource |  | **behavioural** (battery): contest only within a tick, per resource |  |
| PRI-03 | [priorities](../guide/scheduler/priorities.md) · Entries on the same target | yes / untested | yes / untested | **differs**: DC: later-ready entries judged only by If busy; override (default) pre-empts regardless of priority; mode entries never checked |  | **behavioural** (battery): a later-ready force overrides a running one whatever the priority | [#196](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/196) (fixed, unreleased) |
| PRI-04 | [priorities](../guide/scheduler/priorities.md) · Entries on the same target | yes / untested | yes / untested | same: none (untested in both) |  |  |  |
| PRI-05 | [priorities](../guide/scheduler/priorities.md) · Entries on the same target | yes / untested | yes / tested | same: DC: mode only claims on its fire tick |  |  |  |
| PRI-06 | [priorities](../guide/scheduler/priorities.md) · Entries on the same target | yes / tested | yes / tested | **differs**: DC logs deferred, settles the occurrence skipped, no re-fire that occurrence |  | **behavioural** (battery): a loser does not fire again that occurrence |  |
| PRI-07 | [priorities](../guide/scheduler/priorities.md) · Manual control | yes / tested | yes / tested | **differs**: DC: active dispatches rows of another schedule or _widget; force winners only |  | **behavioural** (battery): busy = only dispatch rows of schedules or the widget; mode entries unchecked |  |
| PRI-08 | [priorities](../guide/scheduler/priorities.md) · Manual control | yes / tested | yes / tested | **differs**: DC defer marks the day done; wait logs every tick and retries |  | **behavioural** (battery): defer gives up for the day; wait retries each tick |  |
| PRI-09 | [priorities](../guide/scheduler/priorities.md) · Manual control | yes / tested | yes / tested | same: none |  |  |  |
| PRI-10 | [priorities](../guide/scheduler/priorities.md) · Manual control | yes / untested | yes / untested | **differs**: DC: only wait does; defer gave up for the day |  | **behavioural** (battery): after a manual command ends, a deferred entry does not run |  |
| PRI-11 | [priorities](../guide/scheduler/priorities.md) · What the bridge cannot see | yes / untested | yes / untested | same: none (both dispatch over it) |  |  |  |
| PRI-12 | [priorities](../guide/scheduler/priorities.md) · What the bridge cannot see | yes / unclear | no | **missing here**: no ownership in DC | **Depends on**: run ownership (EXT-06, [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189)) |  |  |
| PRI-13 | [priorities](../guide/scheduler/priorities.md) · Entries on different targets | yes / unclear | yes / tested | **differs**: DC has gateway binding and scope all; claims per gateway on its tick |  | **behavioural** (battery): claims per gateway, not per target |  |
| PRI-14 | [priorities](../guide/scheduler/priorities.md) · Who sent what (requester) | yes / tested | yes / tested | **differs**: DC records schedule id or _widget in the dispatches table only; no control-log requester |  | **behavioural** (record): requester only in the dispatches table |  |
| PRI-15 | [priorities](../guide/scheduler/priorities.md) · What the bridge cannot see | yes / unclear | no | **missing here**: no supervision in DC | **Depends on**: supervision (OUT-07 to OUT-11) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| PRI-16 | [priorities](../guide/scheduler/priorities.md) · Manual control | no | yes / tested | Direct Connect only: wait retries every tick (MB: wait = defer) |  |  |  |
| PRI-17 | [priorities](../guide/scheduler/priorities.md) · Entries on the same target | no | yes / tested | Direct Connect only: per-resource claims: grid, per-circuit, wildcard merge, unknown kind |  |  |  |
| PRI-18 | [priorities](../guide/scheduler/priorities.md) · Entries on the same target | no | yes / tested | Direct Connect only: notify/none claims nothing (MB: own lane, equivalent) |  |  |  |
| PRI-19 | [priorities](../guide/scheduler/priorities.md) · Manual control | no | yes / unclear | Direct Connect only: defer marks the date, so interval/cron/window#n entries defer and log every tick |  |  | [#204](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/204) |
| OUT-01 | [outcomes](../guide/scheduler/outcomes.md) · Activity Log results | yes / tested | yes / untested | **differs**: DC logs a word only; import writes no row |  | **behavioural** (record): config changes logged as one word; import not logged |  |
| OUT-02 | [outcomes](../guide/scheduler/outcomes.md) · Activity Log results | yes / tested | yes / tested | same: DC also filters severity |  |  |  |
| OUT-03 | [outcomes](../guide/scheduler/outcomes.md) · Activity Log results | yes / untested | yes / untested | **differs**: DC History loads 200 rows, chips per status present; fired is used |  | variance: History view length and chips only |  |
| OUT-04 | [outcomes](../guide/scheduler/outcomes.md) · Retries | yes / tested | yes / tested | **differs**: DC 30 s doubling to 600 s, plus in-tick resilience retries; no notification |  | **behavioural** (battery): retry 30 s doubling to 600 s (there: 15, 30, 60 s); no notification | [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) |
| OUT-05 | [outcomes](../guide/scheduler/outcomes.md) · Retries | yes / tested | yes / tested | **differs**: DC logs plain fired; no notification |  | **behavioural** (record): recovery logged as plain fired; no notification | [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) |
| OUT-06 | [outcomes](../guide/scheduler/outcomes.md) · Retries | yes / untested | yes / untested | same: DC settles it skipped |  |  |  |
| OUT-07 | [outcomes](../guide/scheduler/outcomes.md) · Supervision of a running command | yes / tested | no | **missing here**: no supervision | **Not ported**: [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) ("dispatch verification and re-send") |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-08 | [outcomes](../guide/scheduler/outcomes.md) · Supervision of a running command | yes / tested | no | **missing here**: no supervision | **Not ported**: [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162); the force uses the same WSet model 704 on the Modbus TCP Server (aGate :502) (`battery_control.py:1-7`), so not a transport limit |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-09 | [outcomes](../guide/scheduler/outcomes.md) · Supervision of a running command | yes / tested | no | **missing here**: no supervision | **Not ported**: [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-10 | [outcomes](../guide/scheduler/outcomes.md) · Supervision of a running command | yes / tested | no | **missing here**: no supervision | **Not ported**: [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-11 | [outcomes](../guide/scheduler/outcomes.md) · Supervision of a running command | yes / tested | no | **missing here**: no supervision | **Not ported**: [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-12 | [outcomes](../guide/scheduler/outcomes.md) · Supervision of a running command | yes / untested | no | **missing here**: no supervision | **Depends on**: supervision (OUT-07) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-13 | [outcomes](../guide/scheduler/outcomes.md) · The dispatch record | yes / tested | yes / tested | **differs**: DC dispatches table: successful forces only (schedule, Run now, widget) |  | **behavioural** (record): dispatch record holds successful forces only | [#139](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/139) |
| OUT-14 | [outcomes](../guide/scheduler/outcomes.md) · The dispatch record | yes / untested | no | **missing here**: no verification states | **Depends on**: supervision (OUT-07) and an outcome record [#139](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/139) |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-15 | [outcomes](../guide/scheduler/outcomes.md) · The dispatch record | yes / untested | yes / untested | same: none |  |  |  |
| OUT-16 | [outcomes](../guide/scheduler/outcomes.md) · The dispatch record | yes / tested | no | **missing here**: no REST read of dispatches | **Not ported**: [#139](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/139) |  | [#139](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/139) |
| OUT-17 | [outcomes](../guide/scheduler/outcomes.md) · Overshoot guard | yes / tested | no | **missing here**: no overshoot guard | **Not ported**: [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) ("an overshoot guard") |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-18 | [outcomes](../guide/scheduler/outcomes.md) · Notifications | yes / tested | yes / unclear | **differs**: no scheduler failure notifications; only boot reconcile notify |  | **behavioural** (record): no failure notifications | [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) |
| OUT-19 | [outcomes](../guide/scheduler/outcomes.md) · Run now and Stop | yes / untested | yes / untested | **differs**: DC active_now also needs fired this occurrence; container clock |  | **behavioural** (display): Stop shown on a different rule, container clock | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| OUT-20 | [outcomes](../guide/scheduler/outcomes.md) · Run now | yes / tested | yes / untested | **differs**: DC Run now ignores conditions entirely |  | **behavioural** (battery): Run now ignores conditions (by design per #162) | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| OUT-21 | [outcomes](../guide/scheduler/outcomes.md) · Run now | yes / untested | yes / untested | same: DC uses duration_min (hidden 90 for windows) |  |  | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| OUT-22 | [outcomes](../guide/scheduler/outcomes.md) · Run now | yes / untested | yes / untested | same: none |  |  |  |
| OUT-23 | [outcomes](../guide/scheduler/outcomes.md) · Run now | yes / untested | yes / untested | same: DC also runs disabled entries |  |  |  |
| OUT-24 | [outcomes](../guide/scheduler/outcomes.md) · Stop | yes / tested | yes / unclear | **differs**: DC Stop: plain Release via default gateway host, no exit HA actions, no block needed |  | **behavioural** (battery): Stop releases via the first gateway's host; no exit HA actions | [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) (fixed, unreleased) |
| OUT-25 | [outcomes](../guide/scheduler/outcomes.md) · Stop | yes / untested | yes / untested | **differs**: DC Stop with nothing changes nothing; entry may still fire |  | **behavioural** (battery): Stop with nothing running does not block the window; the entry can still fire |  |
| OUT-26 | [outcomes](../guide/scheduler/outcomes.md) · The dispatch record | no | yes / untested | Direct Connect only: scheduled/Run now force writes a dispatches row |  |  |  |
| OUT-27 | [outcomes](../guide/scheduler/outcomes.md) · Run now | no | yes / untested | Direct Connect only: Run now force recorded, so Stop and If busy see it (MB: Stop does not see Run now) |  |  |  |
| OUT-28 | [outcomes](../guide/scheduler/outcomes.md) · Run now | no | yes / unclear | Direct Connect only: UI Run now uses the top-bar gateway over the bound one |  |  | [#193](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/193) (fixed, unreleased) |
| OUT-29 | [outcomes](../guide/scheduler/outcomes.md) · Retries | no | yes / tested | Direct Connect only: missed sweep after 120 s grace (MB: catch-up instead) |  |  |  |
| OUT-30 | [outcomes](../guide/scheduler/outcomes.md) · Activity Log results | no | yes / tested | Direct Connect only: coalesced backlog runs |  |  |  |
| OUT-31 | [outcomes](../guide/scheduler/outcomes.md) · Retries | no | yes / tested | Direct Connect only: unknown outcome settles, not retried |  |  |  |
| OUT-32 | [outcomes](../guide/scheduler/outcomes.md) · Retries | no | yes / unclear | Direct Connect only: unknown is unreachable from the action path |  |  | [#201](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/201) |
| OUT-33 | [outcomes](../guide/scheduler/outcomes.md) · Retries | no | yes / unclear | Direct Connect only: in-tick resilience retries blocked the scheduler thread; one attempt per tick since #197 (fixed, unreleased) |  |  | [#183](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/183) |
| OUT-34 | [outcomes](../guide/scheduler/outcomes.md) · Retries | no | yes / unclear | Direct Connect only: refused force / rejected mode logged fired (text classification) |  |  | [#191](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/191) (fixed, unreleased) |
| OUT-35 | [outcomes](../guide/scheduler/outcomes.md) · Retries | no | yes / unclear | Direct Connect only: per-attempt audit sink signature mismatch |  |  | [#201](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/201) |
| OUT-36 | [outcomes](../guide/scheduler/outcomes.md) · Run now and Stop | no | yes / unclear | Direct Connect only: Pause ineffective |  |  | [#200](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/200) |
| OUT-37 | [outcomes](../guide/scheduler/outcomes.md) · Run now and Stop | no | yes / tested | Direct Connect only: Resume only inside the window |  |  |  |
| OUT-38 | [outcomes](../guide/scheduler/outcomes.md) · Run now and Stop | no | yes / tested | Direct Connect only: paused runs become stopped at restart |  |  |  |
| OUT-39 | [outcomes](../guide/scheduler/outcomes.md) · Where to look | no | yes / tested | Direct Connect only: run queue /runs and /stats |  |  |  |
| OUT-40 | [outcomes](../guide/scheduler/outcomes.md) · Activity Log results | no | yes / tested | Direct Connect only: log severity classes with per-class caps |  |  |  |
| OUT-41 | [outcomes](../guide/scheduler/outcomes.md) · Activity Log results | no | yes / tested | Direct Connect only: 'nothing to do' still logged |  |  |  |
| OUT-42 | [outcomes](../guide/scheduler/outcomes.md) · Retries | no | yes / tested | Direct Connect only: error row names attempt and retry delay |  |  |  |
| OUT-43 | [outcomes](../guide/scheduler/outcomes.md) · Run now | no | yes / untested | Direct Connect only: Run now placeholders limited to gateway + HA values |  |  |  |
| CLK-01 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · The clock | yes / untested | yes / tested | **differs**: DC: each gateway's aGate clock (site time) |  | **behavioural** (battery): each gateway's aGate clock: fire times differ when the container clock is not site time |  |
| CLK-02 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · The clock | yes / untested | yes / unclear | **differs**: DC: previews on container clock, tick on site clock |  | **behavioural** (display): previews on the container clock | [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) |
| CLK-03 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · The clock | yes / tested | yes / tested | **differs**: DC: site timezone setting for mocks; no install check |  | variance: the tick here uses the aGate clock, so the install timezone check has nothing to guard |  |
| CLK-04 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Daylight saving | yes / unclear | yes / unclear | **differs**: DC: fixed offset re-read every 10 min; late by up to 10 min |  | **behavioural** (battery): DST change applies up to 10 min late |  |
| CLK-05 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · The clock | no | yes / tested | Direct Connect only: unreadable gateway falls back to container clock, not UTC |  |  |  |
| CLK-06 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · The clock | no | yes / tested | Direct Connect only: implausible aGate clock refused |  |  |  |
| RST-01 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Bridge restart | yes / tested | yes / untested | **differs**: DC releases only the in-memory force, to the first gateway's host |  | **behavioural** (battery): restart releases only the in-memory force, to the first gateway's host | [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) (fixed, unreleased) |
| RST-02 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Bridge restart | yes / untested | yes / tested | **differs**: DC: reconcile policy, default notify (battery untouched) |  | **behavioural** (battery): start-up default is notify: a force left by a crash keeps running (there: released) |  |
| RST-03 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Bridge restart | yes / tested | yes / tested | **differs**: DC: a fired occurrence is stored, no re-fire |  | **behavioural** (battery): stored occurrence: no re-fire after restart (there: re-dispatches) |  |
| RST-04 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Bridge restart | yes / untested | yes / unclear | **differs**: DC: release_stale never called; no catch-up |  | **behavioural** (battery): `release_stale()` never called | [#199](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/199) (fixed, unreleased) |
| RST-05 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Bridge restart | no | yes / tested | Direct Connect only: paused runs resolved to stopped at start-up |  |  |  |
| RST-06 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Bridge restart | no | yes / tested | Direct Connect only: release/resume policies re-arm or re-force |  |  |  |
| RST-07 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Bridge restart | no | yes / untested | Direct Connect only: with notify a force outlives a restart; timer lost |  |  |  |
| RST-08 | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) · Bridge restart | no | yes / unclear | Direct Connect only: reconcile and shutdown handle only the first gateway |  |  | [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) (fixed, unreleased) |
| DEP-01 | [dependencies](../guide/scheduler/dependencies.md) · Dependency matrix → Actions | no | yes / untested | same: none (untested here) |  |  | [#128](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/128) |
| — | [dependencies](../guide/scheduler/dependencies.md) · A Home Assistant action did not run | no | section | Direct Connect only: kept from the old troubleshooting page |  |  | [#169](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/169) [#171](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/171) |
| — | [dependencies](../guide/scheduler/dependencies.md) · A condition is always true when it should not be | section | section | **differs**: DC: tariff windows read None when unconfigured; grid.connected reads 0 at 0 W; before 0.5.4 an unavailable HA entity read 0 (#167) |  | **behavioural** (battery): conditions can pass when they should not (#206) | [#206](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/206) |
| — | [dependencies](../guide/scheduler/dependencies.md) · An action is refused or does nothing | section | section | **differs**: a force refused by the Modbus client path, and a mode/off-grid write with a non-zero result, are logged fired |  | **behavioural** (battery): refused writes logged fired (#191) | [#191](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/191) (fixed, unreleased) |
| — | [dependencies](../guide/scheduler/dependencies.md) · An entry never fires | section | section | **differs**: DC Always runs once ever (occurrence stays done across restarts) |  | **behavioural** (battery): Always fires once ever (#190) | [#190](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/190) |
| — | [dependencies](../guide/scheduler/dependencies.md) · Dependency matrix | section | section | **differs**: DC: force needs the Modbus client (this bridge); reserve never runs (#129); no trusted-rating gate |  | **behavioural** (battery): force needs the Modbus client (this bridge): :9000 has no battery force (transport limit, [HYBRID-CAPABILITIES][bl-hybrid]); reserve write never runs (#129): 1405 is cloud-only ([PROTOCOL.md][dca-proto]) | [#129](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/129) |
| — | [examples](../guide/scheduler/examples.md) · 1. Evening top-up | section | section | **differs**: weekly fire-at+duration (#160); power in % or kW (W API only); target SoC field |  | **behavioural** (battery): hidden duration ends the force (#160) | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| — | [examples](../guide/scheduler/examples.md) · 2. Evening peak discharge until the minimum SoC | section | section | **differs**: daily 17:00 + 240 min because of #160 |  | **behavioural** (battery): workaround for #160 changes the window | [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) |
| — | [examples](../guide/scheduler/examples.md) · 3. Charge from the grid when the NEM spot price is low | section | section | same: stale NEM price kept forever |  |  | [#207](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/207) |
| — | [examples](../guide/scheduler/examples.md) · 4. Storm forecast: fill the battery | section | section | **differs**: weather.code not in the picker; condition text unverified |  | **needs owner**: needs owner: is `weather.condition` text "thunder" right, or should the example use `weather.code`? |  |
| — | [examples](../guide/scheduler/examples.md) · 5. Peak-demand window | section | section | **differs**: window flag None when undefined; overlapping force schedules release each other |  | **behavioural** (battery): overlapping force schedules release each other (#189) | [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) (fixed, unreleased) |
| — | [examples](../guide/scheduler/examples.md) · 6. Weekend export, unless Home Assistant says you are away | section | section | same: since 0.5.4 an unavailable entity has no value, as in the Modbus Bridge |  |  | [#167](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/167) (fixed in 0.5.4) |
| — | [examples](../guide/scheduler/examples.md) · 7. Full by 07:00, starting as late as possible | section | no | **missing here**: no time.* sensors; one cron schedule per rung instead | **Depends on**: `time.*` sensors (SEN-01), [SENSOR-PARITY §A][bl-sens] |  | [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) |
| — | [examples](../guide/scheduler/examples.md) · More examples (Direct Connect only) | no | section | Direct Connect only: template-based recipes moved from the old troubleshooting page |  |  |  |

## Existing issues this page touches

| Issue | Where |
|---|---|
| [#157](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/157) Turning a schedule on/off wiped its settings | Fixed in 0.5.2: a PUT merges what it sends into the stored schedule ([index](../guide/scheduler/index.md)). |
| [#160](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/160) A force in a Recurring window stops at the hidden duration | [triggers](../guide/scheduler/triggers.md), [actions](../guide/scheduler/actions.md), [exit](../guide/scheduler/exit-and-conflicts.md) |
| [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161) Timeline, next fire and Test use the container clock | [restarts-and-clock](../guide/scheduler/restarts-and-clock.md) |
| [#162](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/162) Scheduler parity with the Modbus Bridge | most *missing here* rows |
| [#167](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/167) An unavailable HA entity read 0 | Fixed in 0.5.4: it now has no value ([conditions](../guide/scheduler/conditions.md)). |
| [#168](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/168) PUT without `enabled` re-enables | [index](../guide/scheduler/index.md) |
| [#169](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/169) `%ha:…%` placeholders are not substituted | [actions](../guide/scheduler/actions.md) |
| [#129](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/129) reserve_soc is always skipped | [actions](../guide/scheduler/actions.md) |
| [#172](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/172) No failure notification | [outcomes](../guide/scheduler/outcomes.md) |
| [#182](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/182) The default gateway is the first registered and moves (fixed, unreleased) | [targets](../guide/scheduler/targets.md) |
| [#165](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/165), [#171](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/171), [#173](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/173), [#174](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/174), [#175](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/175), [#183](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/183) | release button, notification switch, dispatch notifications, Release read-back, worker restart guard, scheduler heartbeat |

## Issues filed from this review

Each was found while writing the Scheduler pages, from a code read; the ones marked
*reproduced* were confirmed by driving `scheduler.tick` with a temporary store and a
monkeypatched `battery_control.execute` (no hardware, no emulator, so not evidence of what an
aGate does). The Test against live point (it reads the default gateway's values) was added
to [#161](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/161).

| Issue | Title | Evidence | Rows |
|---|---|---|---|
| [#188](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/188) | Scheduler on/off picker stores "false" as text, which runs as on: smart circuit turns ON, Go off-grid / reconnect goes OFF-GRID (fixed in 0.5.5) | reproduced in the engine; the form path is a code read | ACT-34 |
| [#189](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/189) | A force schedule's window end sends Release even if it never fired, or after another schedule or the Battery Control widget took the battery; exit HA actions run too; flapping exit conditions repeat both (fixed, unreleased: the Release; exit HA actions at every close are kept by design) | reproduced | HAA-06, EXT-01, EXT-05, EXT-24 |
| [#190](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/190) | An Always schedule fires only once, ever (its single stored run stays finished), yet keeps sending Release on every falling edge | reproduced | TRG-28, TRG-29 |
| [#191](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/191) | A force refused by the Modbus client (this bridge), and a mode or off-grid write the aGate rejects, are logged "fired" and never retried (fixed, unreleased) | reproduced | ACT-13, ACT-24, OUT-34 |
| [#192](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/192) | Stop, Pause, the shutdown release and the boot reconcile use the first gateway's host, not the host the force was recorded on (fixed, unreleased) | code read | TGT-20, EXT-20, OUT-24, RST-01, RST-08 |
| [#193](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/193) | Run now from the UI acts on the top-bar gateway, not the schedule's own gateway (fixed, unreleased) | code read | TGT-09, OUT-28 |
| [#194](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/194) | battery_control supervises one force per process: a second gateway's force drops the first one's time limit and target SoC (fixed, unreleased) | code read | ACT-39 |
| [#195](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/195) | Deleting a running schedule does not release its force (fixed, unreleased) | reproduced | EXT-04, EXT-21 |
| [#196](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/196) | Priority only counts on the same tick: a force that becomes ready later overrides a running one whatever their priorities (default If busy = override) (fixed, unreleased) | reproduced | PRI-03 |
| [#200](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/200) | Pause does not hold a run: the tick re-attempts paused runs, and a run that already succeeded is not found | reproduced | IDX-12, OUT-36 |
| [#197](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/197) | Force retries sleep inside the scheduler tick and stall every gateway (cf. #183) (fixed, unreleased) | code read | ACT-40 |
| [#201](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/201) | The scheduler can never record an UNKNOWN outcome, and its resilience audit hook never writes (signature mismatch) | reproduced | ACT-41, OUT-32, OUT-35 |
| [#198](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/198) | Weekly with no days, Monthly with no day of month, and One-off with no date fire every day; a Recurring window with start = end is open all day | reproduced | TRG-09, TRG-23, TRG-51 |
| [#202](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/202) | Validate actions, HA actions, cron, day of month and months when a schedule is saved; import should flag unknown sensors and operators | code read | CND-02, CND-35, ACT-02, HAA-01 |
| [#203](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/203) | On-entry HA actions repeat on every retry, and a retry waits the whole hold again | code read | CND-27, HAA-07 |
| [#204](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/204) | If busy = defer re-defers and logs every tick for interval, cron and second-window schedules | code read | PRI-19 |
| [#205](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/205) | History rows should name the gateway (gateway scope "all" rows cannot be told apart) | code read | TGT-06 |
| [#206](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/206) | grid.connected reads 0 whenever grid power is exactly 0 W | code read | SEN-04 |
| [#207](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/207) | A stale AEMO NEM price is kept forever when the fetch fails | code read | SEN-10, SEN-19 |
| [#208](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/208) | Every N minutes of 24 h or more: Next shows anchor + N, the engine fires at the anchor | reproduced | TRG-19 |
| [#199](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/199) | battery_control.release_stale() is never called; start-up relies on the reconcile policy alone (fixed, unreleased) | code read | RST-04 |
| [#209](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/209) | An empty power sent through the API is a 0 W force; Always and zero-duration schedules get a 1-second retry deadline | code read | ACT-04, ACT-42 |

