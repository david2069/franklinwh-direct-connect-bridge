# Working rules

## Ground every claim in evidence

**Do not speculate.** A statement about what a field means, what an API does, or what the
hardware reports is a claim, and it needs a source:

1. **Vendor documentation** — the FranklinWH Commissioning Guides, the Modbus PICS, the
   SunSpec model definitions. These are in the repos and on the GitHub Pages sites.
2. **The API Cookbooks** — `franklinwh-cloud`, `franklinwh-modbus`,
   `franklinwh-direct-connect-api`.
3. **A live read** — `Settings → Integrations → Mapping` has a **Probe**: give it a field
   name and it finds the frame, returns the value, and shows the exact request sent.
4. **The code**, read — not inferred from a name, a neighbouring field, or a comment.

**Cite the source.** "1707 `ibgRunStatus` reads 9 during VPP (measured, 2026-10-13)" is a
finding. "`isThreePhaseInstall` is the grid phase" was a guess that was wrong.

**Say what is unverified.** Mark it, rather than letting a reasonable-sounding sentence
pass as established. One observation of an enum is not a mapping.

**A field's name is not its meaning.** Neither is its position in a payload, nor what a
comment claims. Check before writing it down, and especially before telling anyone else.

## Test thoroughly

- Every code change ships with tests, and the full suite must pass.
- **A test that passes with the fix disabled proves nothing.** Verify the test fails
  without the change; the cheapest way is to break the change deliberately and watch.
- Test the **failure** paths, not only the happy one — unavailable, timeout, ambiguous,
  disabled, not-measured.
- Prefer an emulator for anything exercising device behaviour.

## Critical changes need real verification

Anything that **writes to hardware, changes dispatch, alters safety behaviour, or
migrates a schema** is critical. It needs either:

- a **real hardware test** on the reference aGate, coordinated with the owner and with
  other clients quiesced where contention matters; or
- an **approved emulator** run that genuinely covers the path. Approved means the
  **FranklinWH Gateway Emulator** or the library's in-process `Emulator` — not a mock
  written for the test in hand, which proves only that the test agrees with itself.

A passing unit test is not evidence that a device behaves as assumed.

**Confirm a measurement rather than assume a build.** "It built" is not "it works" —
check the database, the socket table, or the live endpoint, and report the number.

## Defect tracking and change management

The detailed policy lives in `franklinwh-modbus` at
`.agents/policies/change_management.md` (effective 2026-03-18) and is the source; this is
its Direct Connect reading.

**Queue first; fix in batches.** A defect or request is written down before it is worked
on — `BACKLOG.md` for new items, `docs/IN_FLIGHT.md` for work already underway. Only an S1
is fixed the moment it is reported. If asked to fix a non-S1 immediately, say it is queued,
offer to group it with the related items, and ask whether it is in fact a blocker.

| Severity | Definition | Response |
|---|---|---|
| **S1 — Blocker** | System down, data loss, security hole, hardware safety, cannot proceed | Fix now, with a brief plan first |
| **S2 — High** | Broken but a workaround exists | Queue → next planned batch |
| **S3 — Medium** | Cosmetic, UX, non-functional | Queue → group by area |
| **S4 — Low** | Nice-to-have, cleanup, future work | Queue → backlog review |

**Group → plan → execute → verify.** Group queued items by functional area (client /
transport, poller, scheduler, store and migrations, HTTP API, UI, MQTT, Modbus) before
touching code. Each batch gets a written plan first, one verification pass at the end, and
one version bump — not one per fix.

**Do not chain fixes.** If a fix causes a new defect, stop and queue the new defect; do not
keep patching. If a fix in a batch breaks a test, review the whole batch, not just the
failing test. When a change has cascaded, go back to the last good state rather than piling
on more fixes.

**State the regression risk** before a change: low, medium or high, and what it touches.

## Say so when something is not done

Report outcomes plainly: what was verified, what was assumed, what was skipped and why.
If a check was not run, say that rather than implying it was.
