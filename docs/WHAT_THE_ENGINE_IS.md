# Scheduling, in plain English

Written because the vocabulary was getting in the way. "Tick", "occurrence" and "window
phase" mean something precise to whoever wrote them and nothing to anybody else — and worse,
calling this thing a *scheduler* sets the wrong expectation before a single line is read.

Shared by both FranklinWH bridges. Companion to `RUNTIME_DESIGN.md` and `BRIDGE_BASELINE.md`.

## The difference in one sentence

A **job scheduler** runs a thing at a time. **This runs the right thing for the conditions,
continuously.**

## Alarm clock, or thermostat

An ordinary job scheduler — cron, APScheduler, Windows Task Scheduler — is an **alarm
clock**. You give it a time; at that time it goes off. It knows nothing about the room. It
cannot tell whether getting up is a good idea. If you were away, it rang to an empty house,
and that is the end of it.

What these bridges have is a **thermostat**. You give it a target and the conditions under
which the target applies. It looks at the room, over and over, and closes the gap between
what is and what should be. It never really "goes off" — at every moment it is either
acting or deciding not to.

Both are reasonable machines. They are not the same machine, and most of the confusion
comes from expecting one and meeting the other.

## Four things that follow from being a thermostat

**1 · Missing a moment is not fatal.** An alarm clock that sleeps through 07:00 has failed;
the moment is gone. A thermostat that misses a reading simply reads again — the room is
still cold, so it still acts. That is why these bridges ask *"is this period open?"* rather
than *"is it 18:00 exactly?"*, and why a bridge restarted mid-period picks up where it left
off instead of waiting for tomorrow.

**2 · The decision can change while it is running.** An alarm cannot un-ring. A thermostat
turns itself off when the room warms up. So a rule needs conditions for *stopping*, not just
for starting, and stopping early is normal operation rather than a fault.

**3 · Two rules can want the same thing.** Only one can have it. "Charge the battery
because power is cheap" and "hold the battery because a storm is coming" cannot both win,
so something must decide — by priority, and predictably. An alarm clock never needs this,
because ringing twice harms nobody.

**4 · Doing it twice is a real risk.** This is the one with teeth. A thermostat that was
switched off for an hour does not heat the room five times to make up for five missed
readings. A bridge that reconnects after an outage must not replay every period it slept
through — especially when "acting" means moving several kilowatts in or out of a battery.

## The words, and what they actually mean

| We say | It means | Think |
| --- | --- | --- |
| tick | how often the engine looks at the world | how often the thermostat reads the room |
| check interval | the same thing, in plain English — **prefer this** | |
| window | the period a rule is meant to apply | "between 6pm and 9pm" |
| window phase | whether that period is `before` / `inside` / `after` right now | not yet · now · over |
| occurrence | one particular run of a rule — tonight's, as distinct from tomorrow's | tonight's heating session |
| run | the same thing, in plain English — **prefer this** | |
| fired | the rule ran | |
| gated | it did not run because writes are switched off | the thermostat is in "display only" |
| misfire grace | how late is still worth doing | arriving 10 minutes late is fine; 6 hours is not |
| coalesce | after an outage, catch up **once**, not once per missed period | |
| max instances | never start a second run while the first is going | |
| entry condition | what must be true to start | "battery below 40%" |
| exit condition | what makes it stop early | "battery reached 80%" |
| reconcile | compare what is happening to what should be, and close the gap | the thermostat's whole job |

Use the plain-English column in anything a user reads. Keep the left column for code.

## So what is it called?

**Not a scheduler.** It is an **automation engine**: it evaluates rules against live
conditions and keeps the system matching them.

Keep the word *schedule* for the thing a **user** creates — a rule with a time period
attached — because that is what they came to make. The component underneath should say what
it is, so nobody expects an alarm clock.

One genuine job-scheduler part does exist inside it: working out when a period starts, which
for cron-style rules is real date arithmetic, and which is why `croniter` is a dependency.
That is the alarm-clock piece. Everything around it is thermostat.

## For the FranklinWH Modbus Bridge

**No structural change is implied — it is already the same machine.** Its own engine
describes a cycle as *"evaluate every target once and reconcile dispatch to the winner"*,
and it resolves competing rules with a `winner()` by priority and age. That is reconciliation
with conflict resolution: a thermostat with more than one person setting it. It simply has
not been named either.

What is worth sharing:

* **The words above.** Two bridges describing the same machine differently is how two
  codebases end up solving the same problem twice — which has already happened here more
  than once.
* **The execution-queue idea.** Writing down each expected run *before* it happens is what
  makes a missed run detectable at all, because silence otherwise looks identical to
  success. The HA Integrator reached the same structure independently: *Automation Rules ·
  Execution Queue · History Log · Audit Ledger*.
* **Resume after stop.** Both bridges share the defect: stopping a run releases the hardware
  but leaves the "already ran today" mark set, so it can never restart within its period.
  Same fix on both sides.
* **Worth copying the other way:** the Modbus bridge's `winner()` — priority descending,
  oldest as tie-break, so a rule added later never displaces an established one — is a
  better-specified conflict policy than ours. Take it rather than reinvent it.
