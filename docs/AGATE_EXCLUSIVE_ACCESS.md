# Sharing the aGate with the other bridges

Several projects talk to the same physical aGate: this bridge, the FranklinWH Modbus
Bridge, FWHAI, the Modbus library sessions and the cloud tools. The device tolerates a
limited number of concurrent clients, and a test that assumes it has the device to itself
will quietly measure someone else's traffic — or be measured as part of it.

## The protocol

Relayed from the owner on 2026-10-30, via the `franklinwh-modbus` sessions. The owner's
words:

> "each repo agent should communicate with each other when they need exclusive access to
> the aGate for testing. Ask current state, scheduled testing or any scheduler jobs active
> and their operating window."

Before a live test against the aGate, ask every other repo session three things:

1. **Current state** — are you connected, polling or writing right now?
2. **Scheduled testing** — anything planned, with its window and what it does?
3. **Scheduler jobs** — active cron, loops, wakeups or pollers that touch the aGate, with
   their interval and operating window.

Do not start while anything overlaps. **Silence is not agreement** — an unanswered session
is an unknown, not a yes.

## What this bridge has to say when asked

Unlike a test harness, this bridge **polls continuously by design**: a login plus several
Direct Connect reads roughly every `poll_interval` seconds per gateway, and a Modbus
SunSpec read for battery ratings when the Modbus client is enabled. So "are you connected"
is normally **yes** whenever the bridge is running, and that is the product working rather
than a test.

The useful answer is therefore not yes/no but: *name the window and we will stop for it.*
Either is reversible:

- **Disable the gateway** (Settings → Gateways) — stops that gateway's poller only.
- **Stop the container** — stops everything, including the scheduler worker, so no
  schedule rule can fire during someone else's test.

Say which was done, and confirm when it is back.

## Answering honestly

Check, do not recall. Container state, what is actually listening, and `CronList` are all
cheap to read, and a stale "nothing is running" is worse than no answer — it is the one
that gets believed.
