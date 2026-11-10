# Suspending Modbus — plan

**Status: PLAN for review. No code.** Written 2026-10-12.

Context: `CONNECTION_DESIGN.md`. The owner asked whether Modbus can be switched off
globally while a new strategy is settled, keeping the code, and handling UI, API and
schedules that try to use it.

---

## 1. The switch already exists. It is incomplete, and the gap is the expensive one.

This is the main finding, and it changes the job from "build a kill switch" to
"finish one and fix what it silently breaks".

**What is already there and works:**

| Piece | Where |
| --- | --- |
| `set_enabled()` / `is_enabled()` / `available()` | `battery_control.py:262-276` |
| Persisted as `modbus_enabled` in app config, restored at startup | `app.py:785` |
| UI toggle on the Control tab | `control.html:435` |
| REST read + write of the flag | `app.py:3455`, `app.py:3475` |
| Honoured by `status()`, `cached_ratings()`, `execute()` | `battery_control.py:329, 374, 408` |
| Honoured by the VPP monitor loop | `app.py:854` |

So dispatch, ratings and VPP detection already stop. Good.

### Gap 1 — the probe ignores the switch, and it is most of the traffic

`client.summary()` line 801:

```
out["modbus_502"] = any(discover.port_open(_ph, 502, timeout=3.0) for _ in range(3))
```

It calls `discover` directly and never consults `battery_control`. So **with Modbus
"disabled" today, this bridge still opens TCP to :502 on every poll of every gateway,
mocks included** — 1 connect when the port answers, 3 × 3 s when it does not.

Turning the existing switch off therefore does **not** stop us touching the aGate's
Modbus port. Anyone who flipped it and then measured would conclude, wrongly, that
we were not the problem.

### Gap 2 — a disabled subsystem currently reports schedules as SUCCESSFUL

With Modbus off, a scheduled `force` action runs:

`_force_dispatch` → `battery_control.execute()` → `{"ok": False, "result": "Modbus
(SunSpec 502) is disabled in Control settings"}` → the action returns
`"force discharge: Modbus (SunSpec 502) is disabled in Control settings"`.

That string contains none of `failed`, `not confirmed`, `error` or ` skipped`, so both
the old substring test and phase 3's `_classify` read it as **OK**. The occurrence is
marked fired, `last_result` reads like a success, and the history shows a run that
never happened.

**This is pre-existing — phase 3 did not introduce it and did not fix it.** It matters
far more once the switch is actually used: suspending Modbus would quietly convert
every force schedule into a fake success. Fixing this is a precondition of suspending,
not a follow-up.

---

## 2. What "disabled" should mean, surface by surface

The principle, consistent with the rules already settled elsewhere in this bridge:
**absent with a reason, never silently degraded, and never a failure.** "Disabled" is
an operator decision, not a fault — it must not page anyone, must not retry, and must
not look like a device problem.

| Surface | Behaviour when disabled | Why |
| --- | --- | --- |
| Socket probe | **Not performed at all.** `modbus_502` becomes `None` | Same rule as phase 2b's never-measured legs: *not measured* ≠ *down* |
| Link history (`modbus_502` leg) | Leg recorded as **not measured**, existing history retained | An open outage must not keep accruing against a leg nobody is probing; the history is still worth keeping |
| Dispatch / force actions | `SKIPPED` with the reason, never `OK`, never retried | Gap 2 |
| UI controls (Battery Control, Release, dispatch) | Visible but disabled, with the reason inline and a link to the toggle | A vanished control invites a hunt; a disabled one with a reason does not. Same judgement as the Advanced-tools gate |
| REST endpoints | `503` with a machine-readable reason (`modbus_disabled`) | Distinguishable from `503 unreachable`; a caller must be able to tell "off" from "broken" |
| `cached_ratings` | Return `None`, fall back to the `battery_max_power_kw` constant | Already the documented fallback |
| Derived values that need ratings | Degrade to the constant and say so | They already fail closed |

**Deliberately NOT disabled:** the `modbus_bridge_url` dispatch provider. That is an
HTTP call to a separate Modbus Bridge service, not a socket to :502, and it is the one
path that still works when we stop talking Modbus ourselves. Conflating the two would
remove the obvious workaround at the moment it becomes most useful.

---

## 3. Scope — settled

**The switch is "Modbus TCP on/off": all TCP to :502 from this process, full stop.**
Not a per-activity switch, not a policy about Modbus as a concept. Off means this
container opens no socket to port 502 for any reason — no poll, no probe, no dispatch,
no on-demand read, no ratings.

That makes the acceptance test trivial to state and to check: **with the switch off,
the socket census shows zero connections to :502 from this container.**

Two things fall outside it, and should be said so they are not assumed either way:

* **`modbus_bridge_url` dispatch stays available.** That is an HTTP call to a separate
  Modbus Bridge service, not a socket to :502 from us. It is the path that still works
  when we stop speaking Modbus ourselves, and switching it off with the same flag would
  remove the obvious workaround at the moment it becomes most useful.
* **The other clients are unaffected.** The Modbus Bridge and Energipay keep their own
  connections. This switch only silences *us*.

### What is actually lost — measured, then fixed

This section said twice that suspending Modbus would blind the VPP badge. **It no longer
costs anything**, because VPP detection was moved to the local channel on 2026-10-12.

Measured on the reference aGate during a Modbus force discharge, with the mobile app
showing VPP Mode:

| Field | Not forced | During VPP |
| --- | --- | --- |
| 1301 `run_status` | 2 | **2** — unchanged |
| `name` | `Self-Consumption` | **`""`** |
| **1707 `ibgRunStatus`** | 85232 | **9** |

`ibgRunStatus` is the local equivalent of the cloud's `tou_mode` — a programme id where 9
means VPP, and where normal programmes use large arbitrary ids. `vpp_monitor` now reads
it from the poller's cached block and opens no Modbus connection at all. See
`RUN_STATUS_AND_MODE.md`.

**So, with Modbus TCP off, what is actually lost:**

| Capability | Lost? |
| --- | --- |
| VPP / external-control detection | **No** — local 1707 |
| Battery state, power, SoC, voltage, frequency | **No** — local 1301 / 1707 |
| Off-grid and Debug/support-session detection | **No** — local `run_status` |
| **Force dispatch and Release** | **Yes** — the only local force path |
| **Model-correct max charge/discharge ratings** | **Yes** — falls back to the `battery_max_power_kw` constant |
| Detection of *another* controller's M704 force specifically | Partly — `ibgRunStatus` 9 covers any external control, but not which register was written |

Two capabilities, both write-side or nice-to-have. That is a much cheaper suspension than
this document originally described.

## 4. Plan

**Phase A — make the switch honest (small, independent, do first)**
1. Gate the `:502` probe on `is_enabled()`, and skip it for mocks regardless.
2. `modbus_502` becomes tri-state: `True` / `False` / `None` (not measured).
3. Link history: `modbus_502` leg records *not measured* while disabled; close any open
   outage with that reason rather than leaving it running.

**Phase B — stop the silent success (precondition for using the switch)**
4. `battery_control` returns a distinguishable *disabled* result, not a generic
   `{"ok": False}` whose text happens to read as success.
5. `_classify` maps it to `SKIPPED`; `_fire_entry` records the occurrence as `skipped`
   with the reason, and does not mark the rule fired.
6. A test that asserts a `force` rule on a disabled Modbus is recorded as skipped —
   because this is exactly the class of bug that survived two implementations already.

**Phase C — say so in the UI**
7. Disable rather than hide the Modbus-dependent controls, with the reason inline and a
   link to the toggle; note the VPP-blindness beside the toggle itself.

**Phase D — measure**
8. Re-run the socket census with the switch off. **Acceptance: zero connections to :502
   from this container.** That is the whole point, and it is a number, not an
   impression.

Anything beyond this — scheduler pre-flight warnings, MQTT availability semantics — is
a separate concern and deliberately not in this plan.

Phases A and B are each small and worth doing whether or not Modbus is suspended.
B is a correctness fix that stands on its own.

---

## 5. Decisions needed

1. **Suspend now, or after Phase A+B?** Flipping the existing switch today stops
   dispatch and the VPP monitor but leaves the probe running and converts force
   schedules into fake successes. **Recommendation: do A and B first** — they are small,
   and suspending without them produces misleading data and a misleading history.
2. ~~Keep the VPP monitor running as an exception?~~ **Settled: no exception needed.**
   The VPP monitor no longer uses Modbus at all, so there is nothing to except. "Off"
   can mean off, and the acceptance test stays "zero connections to :502".
3. **Default for new installs** — unchanged (`on`), or off until the strategy is
   settled?
