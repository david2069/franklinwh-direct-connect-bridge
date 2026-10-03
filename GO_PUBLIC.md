# Go-Public Runbook — `franklinwh-local-bridge`

Formal procedure to open-source the bridge with a hard requirement: **no PII in the
public repo — current tree *or* history.** Written 2026-09-20. Execute *after* the
pending updates/fixes are merged. Companion runbook (shared strategy) lives in the
`franklinwh-local` library repo.

> Keep the existing repo URL `github.com/david2069/franklinwh-local-bridge`.

## Audit summary (run 2026-09-20)

**Clean — verified:** no credentials were ever committed. The FranklinWH cloud
password, Home-Assistant long-lived tokens, `.env`, and the `data/` volume
(`metrics.db`, `overrides.json`) are all gitignored and absent from all history.

**Must be scrubbed before public (device-identifying PII):**
- Real **LAN IPs** (the home subnet, esp. the aGate's address) — in `README.md`,
  `docker-compose.yml` (the `FWH_HOST` default), `docs/SMART_CIRCUITS_DESIGN.md`, the
  Settings tab input placeholder, and several `tests/` fixtures.
- A real **Wi-Fi MAC** address in a cloud-compat test fixture.
- A **location / model hint** (country + model code) in a design doc.
- The real aGate **serial** in 2 history commits.
- **No LICENSE file** — add MIT (matching the library).

## Recommended approach

Squash to a single clean root commit in place (after scrubbing the tree), force-push,
verify zero PII across all blobs, then flip visibility — keeping the URL. The repo has
only ever been private (no forks/clones), so the only residual is GitHub's object cache
(purgeable via Support). `git filter-repo` is the history-preserving alternative.

## Checklist

- [ ] Add `LICENSE` (MIT).
- [ ] Scrub real LAN IPs → placeholders (RFC 5737 `192.0.2.x`, or the hotspot default
      `10.100.1.1`) in README, `docker-compose.yml`, the design doc, the Settings
      placeholder, and tests. Keep `127.0.0.1`.
- [ ] Scrub the real Wi-Fi MAC in the test fixture → a fake MAC.
- [ ] Generalise / remove the location+model hint in the design doc.
- [ ] Confirm `.env` and `data/` stay gitignored and untracked (verified).
- [ ] Squash to a clean baseline; run the verification sweep below.
- [ ] (Optional) add CI — free once public; reuse the library's trimmed workflows.

## Verification sweep (all must be zero before flipping)

Fill in your own real values locally; **do not commit them.**

```bash
git log --all -S '<REAL_AGATE_SERIAL>' --oneline | wc -l          # want 0
git log --all -S '<REAL_LAN_PREFIX>'   --oneline | wc -l          # want 0 (or doc-range only)
git log --all -S '<REAL_WIFI_MAC>'     --oneline | wc -l          # want 0
git log --all -S 'FWH_CLOUD_PASSWORD'  --oneline | wc -l          # want 0 (already)
git log --all --name-only --pretty=format: | grep -iE '(^|/)\.env$|(^|/)data/|\.db$' | sort -u   # want empty
git rev-list --all | while read c; do git grep -lE 'eyJ[A-Za-z0-9_-]{20,}' "$c" 2>/dev/null; done | sort -u  # want empty
```

## The flip

Settings → change visibility to Public (or `gh repo edit --visibility public
--accept-visibility-change-consequences`). Docs are served by the bridge at `/guide`, so
GitHub Pages is optional.

---

*This runbook contains no real serials, IPs, or MACs — placeholders only.*
