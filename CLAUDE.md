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

## Say so when something is not done

Report outcomes plainly: what was verified, what was assumed, what was skipped and why.
If a check was not run, say that rather than implying it was.
