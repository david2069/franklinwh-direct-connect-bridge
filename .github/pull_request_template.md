## What changed

<!-- One or two sentences. -->

## Issue and labels

<!-- "Refs #N", never Fixes/Closes: the issue is closed only after the post-release check.
     Label the PR as CLAUDE.md "Defect tracking and change management" says:
     a type (bug | enhancement | documentation | chore),
     a severity (sev:S1-blocker | sev:S2-high | sev:S3-medium | sev:S4-low)
     and an area (area:..., the TEST_POLICY §1 release areas).
     Optional nature: nature:code | design-risk | device | doc | test-gap. -->

Refs #

## Evidence

<!-- Per `CLAUDE.md`, "Ground every claim in evidence". Cite the source for every
     claim about what a field means or how the hardware behaves: a vendor document
     with its revision and date, a cookbook, a live read with its time and firmware,
     or the code. Say what is unverified. -->

## Mutation check

<!-- Required. "A test that passes with the fix disabled proves nothing."
     Disable the change, run the tests, and paste which ones failed: -->

Disabled the change; these tests failed:

## Verification

<!-- Tick what applies, and say what was NOT run.
  - [ ] Full test suite passes
  - [ ] Real hardware test on the reference aGate (say which clients were active,
        and verify any stop by socket count)
  - [ ] Approved emulator run — name the coverage-list version, the profile and the
        emulator commit, and say what that emulator does not model
  - [ ] Migration verified against a copy of the live database
  - [ ] Read-back verification done on hardware, not a simulator
-->

## Changelog

- [ ] `CHANGELOG.md` updated under `[Unreleased]`, or this change is not user-facing
      (internal refactor, tests, docs or policy only)

## Publishable evidence

- [ ] `python3 tools/pii_check.py` run — no new findings (no serials, MACs, LAN IPs,
      home paths, account identifiers or site captures; masked or `192.0.2.x`)
