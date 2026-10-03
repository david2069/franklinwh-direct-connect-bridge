# Backlog — franklinwh-local-bridge

Planned work. Newest first. Design lives in the library repo's `PLAN_docker.md`.

---

## FEAT-DESIGN-SYSTEM — consolidate typography/spacing into one theme (kill ad-hoc sizes)

**Status:** base theme CONSISTENT 2026-09-21 (metric tiles + page titles + card headers all on the Modbus model). Ad-hoc text-* migration + optional style-guide queued.
**Filed:** 2026-09-21

Symptom (user, battery tab): "some fonts are bigger than others… small cards have too
much white space." Root cause: a PARTIAL design system — `.card`/`.card-label`/
`.card-value`/`.card-sub`/`.chip` are defined and consistent, but `.metric-label`/
`.metric-value` were UNDEFINED (fell back to the 16px browser default), and ~400 ad-hoc
Tailwind `text-*` usages across templates let the same element drift place to place.

### Done (step 1)
Defined `.metric-label` / `.metric-value` / `.metric-sub` in `design-system.css` as a
compact tile sharing the `.card-label`/`.card-value` scale — fixes every tile that
already uses those classes (battery), zero template edits.

### Rollout (queued)
1. **One documented type scale** in `design-system.css`: label .7rem uppercase muted,
   value ~1.6-2rem bold, sub .72-.75rem, body .85rem, heading sizes. The single source
   of truth for these roles.
2. **Compact metric tiles everywhere** — apply the `.metric` pattern to the dashboard
   status cards (latency / Modbus / MQTT / firmware) and any other key/value tiles so
   they read identically to the battery tiles.
3. **Migrate ad-hoc → semantic** opportunistically, tab by tab: replace scattered
   `text-sm font-semibold` labels with `.card-label`, values with `.card-value`/
   `.metric-value`, etc. Low-risk, incremental; the cascade already helps before it's done.
4. Optionally a short **UI style guide** doc (the class vocabulary + when to use each) so
   new tabs stay on-theme.

Principle: fix it in the shared theme layer, never per-tab — that's what keeps it
consistent "throughout".
---

## FEAT-ENERGY-FLOW-ANIMATED — animated node-flow energy diagram (Energipay-style)

**Status:** queued (own phase)
**Filed:** 2026-09-21
**Reference:** Energipay / PowerDiverter home diagram (nodes + animated dashed flow lines)
**Related:** complements the existing Sankey ([[FEAT-ENERGY-SANKEY]], done) — a live "now"
view vs the Sankey's day integral.

Clone a live **animated energy-flow node diagram**: icon nodes for **Grid, Solar,
Battery (with SoC %), Home Loads** (+ optional device nodes: generator, smart circuits),
connected by **dashed lines that animate in the direction of power flow**, with
speed/opacity/colour scaled by magnitude (e.g. green = self-supply/charge, orange =
draw, red = grid import). A node glows/greys when idle.

### Feasibility — data already exists
The dashboard already has live `$store.app.power` (`grid_w`, `solar_w`, `battery_w`,
`load_w`, `gen_w`) with sign conventions, plus battery SoC. That's everything the diagram
needs; no new backend.

### Implementation sketch (self-contained, no heavy deps)
- Inline **SVG**: fixed node positions, connector `<path>`s between them.
- Animate with a moving `stroke-dashoffset` (CSS keyframes) toggled per-connector by the
  sign of the corresponding power value; hide/grey a connector when its |power| ~ 0.
- Direction = sign of the flow (e.g. battery >0 discharge → arrow toward Home; <0 charge →
  arrow from Solar/Grid). Speed ∝ |kW|. Reuse the dashboard's power colours.
- Ship as its own dashboard card (toggle via the Cards show/hide already built), or a
  compact always-on header widget.

Scope note: keep it lightweight (SVG + CSS), not a physics/particle engine — the value is
a clear at-a-glance "where is the power going right now".

---

## FEAT-MOBILE-UI — mobile-friendly UX (bottom nav, touch targets) like Energipay

**Status:** bottom nav DONE 2026-09-21; touch-targets + polish queued
**Filed:** 2026-09-21
**Reference:** Energipay / PowerDiverter app (bottom tab bar on phones, big touch targets, single-column cards)

Make the bridge feel native on a phone/tablet. Our topbar already wraps + hides chips
responsively and cards stack (`grid-cols-1`); the gap is navigation + touch ergonomics.

Prioritised (biggest impact first):
1. **Bottom tab bar on mobile (the key change).** On `< lg`, hide the left icon-rail
   sidebar and show a fixed bottom nav with the 4-5 top tabs + a "More" sheet for the
   rest. Thumb-reachable, native-app feel. Additive: sidebar stays for tablet/desktop.
   Add `padding-bottom: env(safe-area-inset-bottom)` for the iPhone home indicator.
2. **Touch targets ≥44px on mobile** — buttons/toggles/chips/sub-tab pills are ~32px
   (`btn-sm`) today; bump min-height under a mobile breakpoint.
3. **Layout polish** — slightly larger base font on small screens; make horizontal
   sub-tab rows (e.g. Battery telemetry/charts) scroll instead of overflow.
4. **Compact topbar on phones** — show just Live-status + gateway picker + avatar; SoC/
   mode already live in the dashboard cards.

Explicitly NOT chasing full visual parity with the commercial app (flow-diagram styling,
gradient rings) — items 1-4 get ~90% of the "feels native" for a fraction of the effort.

---

## FEAT-NAV-REORDER — user-orderable sidebar / bottom-nav (precedence = overflow order) (queued)

**Status:** queued — **Filed:** 2026-09-29 (user).

**Ask:** let the user reorder the navigation tabs, the same way the dashboard cards reorder now
(FEAT touch row). The tab ORDER is the **precedence for the dynamic bottom nav bar**: as many tabs
as fit the width render as buttons in order, the rest spill into **More**. So reordering decides
which tabs are primary bar buttons vs. under More.

**Rules (user):**
- **Home/Main (`dashboard`) is always first and cannot be moved or removed** — pin it at index 0.
- **Settings cannot be removed** (may be reordered, but never hidden/removed).
- Everything else: reorderable, and (optionally) hideable from the bar/More.

**Where:** the ordered registry is `app.js` `navTabs` (fixed today) → `barMax` (how many fit) →
`barTabs` = first `barMax-1`, `overflowTabs` = the rest under More (`bottom-nav.html`). Persist a
user order (localStorage, like `fwh-dash-cards`) and apply it to `navTabs` at load, keeping
`dashboard` pinned first and `settings` always present. The sidebar (`sidebar.html`) should honour
the same order.

**UI:** a reorder panel like the dashboard "Cards — show & reorder" row we just made touch-friendly
(toggle left / label / up-down arrows right, ~34px targets). Likely lives in Settings (or a
long-press/edit affordance on the nav). Reuse `moveDashCard`/`resetDashCards` as the pattern.

**Note:** "dynamic bottom navbar buttons" = the width-driven bar in `bottom-nav.html`; there isn't a
fancier name — the order simply feeds `barTabs`/`overflowTabs`.

## DOC-SESSION-CHANGES — document the 2026-09-29 batch (bridge user docs) (queued)

**Status:** queued — **Filed:** 2026-09-29 (user: "we do need to document when finish all these changes").
**Note:** the bundled `/guide` is the **library's** mkdocs (from sibling `franklinwh-local`), NOT the
bridge — so bridge features have no user docs yet. This item = write them (README + a bridge user-guide
section + OpenAPI `description`s), and keep the design docs (`docs/*.md`) current.

### Shipped this session — to document (checklist)
- [ ] **AusNEM wholesale pricing** — `tariff.spot_price` sensor, `GET /api/tariff/spot`, NEM region in
      Settings. (built)
- [ ] **HA price-entity provider** — dynamic tariff from an HA entity → `tariff.spot_price` /
      `tariff.feed_in_price` (c/kWh, $/kWh auto-scaled); Settings "Dynamic price (wholesale)" card;
      how the two providers compose (HA wins over NEM). (built)
- [ ] **Modbus connection setup** — Control tab: resolved target + host/port override + Test;
      `/api/modbus` GET/PUT + `/api/modbus/test`; override applies to ALL Modbus paths. (built)
- [ ] **Logs now in the SQLite DB** — durable, paginated (`/api/logs` offset + filters); JSONL retired;
      the data-loss/clobber fix + test isolation (conftest). Document the storage + retention (50k). (built)
- [ ] **Generator gating** — hide generator energy/metrics when no genset (1901 installed). (built)
- [ ] **Navigation layout** — Settings > General > Navigation: Auto / Sidebar only (no bottom bar) /
      Bottom bar only. (built)
- [ ] **Dashboard card show/reorder** (touch UI) + the `:style`-object fix note. (built)
- [ ] **Docs reachability** — Guide link in the mobile More sheet + Settings > Admin. (built)
- [ ] **Timezones** — already in `docs/TIMEZONES.md`; link it from user docs. (existing)

### Also pending doc items from other backlog
- Legal disclaimer + GH issues + unofficial notice → see [[FEAT-LEGAL-DISCLAIMER]] (docs + startup log).
- Security model (LAN/VPN vs exposed; reverse proxy) → see FEAT-SECURE-API.

### Targets
- `README.md` (bridge) — features overview + quickstart.
- A **bridge user guide** (own mkdocs section or docs/USER_GUIDE.md), separate from the library guide.
- FastAPI OpenAPI `description`s on the new endpoints (`/api/modbus*`, `/api/tariff/spot`, `/api/logs`).
- Keep `docs/*.md` design docs updated as features land.

## FEAT-USERS-RBAC — optional users, profiles & role-based access (login-gated) (queued)

**Status:** queued — **Filed:** 2026-09-30 (owner). **Initial model:** the **Modbus Bridge's** user
function (clone as the baseline). **Depends on / pairs with:** [[FEAT-SECURE-API]] (native token/session
auth) — login needs a session layer.

**Ask:** optional **users + user profiles** with role-based access. When **enabled**, a user must **log in
first**; when disabled, behaviour is exactly as today (open on LAN/VPN — back-compat default OFF).

**Roles (initial set):**
- **Admin** — all access (users, settings, every gateway + tab + control).
- **Gateway admin** — admin of the assigned gateway(s)' functions (not global settings/users).
- **User (advanced)** — control + scheduling + viewing.
- **User (basic, control)** — view + control (no scheduling/admin).
- **User (basic, view)** — view only.

**Per-profile grants (admin-configurable):**
- Assign **which tabs** a profile can see and **which controls** it can use (checkbox matrix per role).
- Assign **which gateways** a user can access.
- Optional **per-profile dashboard view** (different default cards/layout per role) — reuse the
  dashboard card show/reorder prefs, but stored per-user/role.
- Admin grants/limits each user's view + control "as the admin sees fit".

**Mechanics:**
- Users table (id, name, hash, role, allowed_gateways, allowed_tabs, allowed_controls, dashboard_prefs)
  in the DB (mirror the ha_instances/gateways CRUD pattern). Session/login gate in front of the app when
  users are enabled; API enforces role on each mutating endpoint (ties to the write-gate + `allow_writes`).
- Settings UI: Users admin (add/edit/remove, role + grant matrix), like the Modbus Bridge.
- Login screen when enabled; "remember me"; logout.

**Phasing:** v1 = the simple role model above (Modbus-bridge-style). **Future (separate, more complex):**
FWHAI-style security (finer permissions, SSO/OAuth, audit per-user) — a later, bigger model; don't scope
it into v1.

**Notes:** every control/mutation already flows through a small set of endpoints (mode, reserve, grid,
modbus, schedules, gateways) — enforce role there. Audit trail should record the acting user once users
exist. Keep OFF by default so single-user LAN installs are unaffected.

## FEAT-SECURE-API — HTTPS + auth (tokens / mTLS): reverse-proxy first, native token auth in-app (queued)

**Status:** queued — **Filed:** 2026-09-29 (user).

**Today's posture (verified):** the bridge serves **plain HTTP** via uvicorn (`cli.py` — no
`ssl_keyfile`/`ssl_certfile`) and has **no app-level authentication** on its own endpoints. Security is
**network-trust** (LAN / VPN — the user runs it over VPN) with `allow_writes` as the only write gate. In
the HA add-on context, **ingress already provides TLS + auth**; standalone Docker does not.

**User's question:** add an HTTPS listener + various auth (mutual TLS, long-lived tokens) *in the app*, or
do it via a **reverse proxy** as best practice?

### Recommendation (answering the question)
Split it by concern — this is the standard best practice:
- **TLS termination, certificates, and mTLS → REVERSE PROXY (recommended, documented), NOT in-app.**
  Put Caddy / nginx / Traefik in front: it owns HTTPS (Let's Encrypt/ACME auto-renew), HTTP/2, and
  **mutual-TLS client-cert verification**, then forwards the verified client identity to the bridge as a
  header (e.g. `X-Client-Cert-CN`). Don't reimplement cert lifecycle / mTLS in Python — proxies do it far
  better and it keeps the app simple. The bridge stays HTTP on an internal/loopback bind.
  - Deliverable: a documented **reference reverse-proxy setup** (Caddyfile + compose example) in docs.
- **App-level auth → ADD NATIVELY (small), because a proxy is not always present.** Standalone Docker
  users (no ingress, no proxy) still need auth. Add:
  - **Long-lived API tokens** (bearer / `Authorization: Bearer` or `X-API-Key`), created/revoked in
    Settings, stored **hashed** in the DB (the durable store). Per-client tokens with a label + last-used.
    Gate the API behind them when auth is enabled (default off / LAN-trust preserved for back-compat).
  - **Trust-proxy mode**: honour `X-Forwarded-For/Proto` and a configurable **verified-client-cert header**
    from the proxy, so mTLS identity established at the proxy maps to a bridge principal — only when a
    `trusted_proxies` allowlist is set (never trust these headers by default).
  - Keep `allow_writes` as an orthogonal write master-switch; auth answers "who", allow_writes "whether".
- **Optional native HTTPS** (uvicorn `ssl_keyfile`/`ssl_certfile`) as a *convenience* for users who won't
  run a proxy — supported but documented as the lesser option (no auto-renew, self-managed certs).

### Work
- Auth middleware/dependency: token verify (hashed compare), 401 on missing/invalid when auth enabled;
  exempt `/`, `/guide`, health, and static as configured.
- DB: `api_tokens` table (id, label, hash, created, last_used, enabled). Settings UI to mint/revoke.
- Config: `auth_enabled`, `trusted_proxies`, `client_cert_header`, optional `tls_cert`/`tls_key`.
- Docs: the reverse-proxy reference (Caddy mTLS + Bearer), and a "security model" page (LAN/VPN vs
  exposed; never expose write endpoints to the internet without auth). Ties to [[grid-1701-write-unverified]]
  and FEAT-LEGAL-DISCLAIMER (exposure warnings).
- **Decision to confirm before building:** default posture (LAN-trust stays default; auth opt-in), and
  whether mTLS is proxy-only (recommended) or also native.

## FEAT-LEGAL-DISCLAIMER — unofficial-app disclaimer (startup log + first-connect + docs + GH links) (CORE DONE 2026-09-29)

> **CORE DONE 2026-09-29:** startup log line (`DISCLAIMER_LINE`, logged once, lands in the durable log); first-connection **modal** with the unofficial/AS-IS/no-warranty/‘do NOT contact FranklinWH support’ text + Documentation (`guide/`) + **GitHub Issues** links; an **‘I have read and agree’ checkbox** that, when ticked, persists agreement to the DB (`disclaimer_acks`, keyed by a per-browser client_id — the authoritative don’t-show-again, survives a localStorage clear) and writes the agreement to the log. Issues URL = `github.com/david2069/franklinwh-local-bridge/issues` (owner will make the repo public). REMAINING: add the disclaimer to the FastAPI OpenAPI `description` (`/docs`) + README; optional server-side ‘first UI connection’ line; consider upstreaming the ‘do-not-contact-support’ wording to franklinwh-cloud.

**Status:** queued — **Filed:** 2026-09-29 (user). **Source of truth:** copy from franklinwh-cloud
(README "Disclaimer" + `franklinwh_cloud/metrics.py::DISCLAIMER`, logged once at Client init via
`client.py` `_disclaimer_logged`). The **local bridge currently has NO disclaimer anywhere** (grep: only
third-party lib files mention github).

**Ask (user):** on integration startup AND first web-browser connection, present a legal disclaimer that
this is an **unofficial** app; log it in the **API and bridge log**; copy the disclaimer from the
FranklinWH Cloud API docs into **our API + bridge docs**; and — if not already stated — add **"Do NOT
call FranklinWH support about issues/defects/feature requests for this app — use GitHub issues instead"**,
with links to the **issues** and **docs** in the UI. Docs link: https://david2069.github.io/franklinwh-cloud/

### Deliverables
1. **Startup log (API + bridge), once per process** — mirror the cloud lib's pattern: a module-level
   `DISCLAIMER` constant + a `_disclaimer_logged` guard, `log.info(DISCLAIMER)` at app startup (in the
   bridge's lifespan/create_app, alongside the existing startup lines). It then also lands in the durable
   Logs DB (audit trail) automatically. Bridge-flavoured one-liner, e.g.:
   > `franklinwh-local-bridge vX.Y | UNOFFICIAL · NOT AFFILIATED WITH FRANKLINWH | NO WARRANTY · AS-IS ·
   > USE AT YOUR OWN RISK | May break without notice from upstream API/firmware changes | Do NOT contact
   > FranklinWH support for this app — file issues on GitHub | MIT — see LICENSE.`
2. **First-connection disclaimer (UI)** — a modal/banner shown on the first web connection (persist
   "acknowledged" in localStorage + optionally the DB so it is once-per-browser/once-per-install), with
   Acknowledge + links to Docs and GitHub Issues. Not blocking after first ack.
3. **Docs** — add the verbatim disclaimer block (below) to the bridge README + docs index AND the API
   (FastAPI OpenAPI `description`, so it shows in `/docs` / `/openapi.json`).
4. **UI links (currently absent)** — an About/footer (or Settings → About) with: Docs
   (https://david2069.github.io/franklinwh-cloud/) and **GitHub Issues**. NB confirm the correct issues
   repo for THIS app — the local bridge/local API is a separate project from franklinwh-cloud; issues for
   the bridge should point at the bridge's own repo (franklinwh-local-bridge / franklinwh-local), not the
   cloud repo. Decide: one funnel (the given cloud docs URL) vs per-repo issues.
5. **"Do NOT call FranklinWH support" line** — not present in the cloud disclaimer today; add it here (and
   consider upstreaming it to franklinwh-cloud for consistency).

### Verbatim disclaimer to copy (from franklinwh-cloud README) — adapt the name to franklinwh-local-bridge
> **UNOFFICIAL SOFTWARE — NOT AFFILIATED WITH FRANKLINWH**
>
> By using this software, you confirm that you have read and understood the LICENSE and its Additional Terms.
>
> This software is provided **AS-IS**, without warranty of any kind, express or implied, including but not
> limited to the warranties of merchantability, fitness for a particular purpose, and non-infringement.
> Use entirely at your own risk.
>
> This software interacts with FranklinWH's undocumented local/cloud APIs, which may change, break, or
> become unavailable without notice. The authors accept no liability for service interruptions, data loss,
> equipment damage, or any other consequences arising from the use of this software.
>
> **Do NOT contact FranklinWH support** about issues, defects, or feature requests for this app — file
> them on GitHub instead.
>
> **MIT License** — see LICENSE for details.

**Note:** ISSUES.md in franklinwh-cloud is a good template to port (bug-report fields + a REDACT-ALL-
CREDENTIALS warning). Ties to the durable Logs DB (the startup line is now audit-persisted).

## DEF-ADDGW-DEFAULT-REAL — Add Gateway: real gateway is the default, mock is the optional/advanced path (queued)

**Status:** queued — **Filed:** 2026-09-29 (user). **Scope:** UI ordering/emphasis in the Gateways
settings, no backend change.

**Now (wrong emphasis):** the Add-Gateway panel leads with **"ADD MOCK GATEWAY (TESTING)"** — the mock
Name/aPowers/Seed form is primary and expanded, with a long mock explainer — while **"Add real gateway
manually (advanced)"** is a collapsed disclosure below. A mock is the testing/edge case; a real gateway is
the normal thing a user adds.

**Want:** flip the emphasis.
- **Real gateway = the default, primary path** — Name / Host / Port shown first (or the top action after
  Discover), not behind an "advanced" collapse. Discover-gateways stays the easiest route.
- **Mock = optional, secondary** — move the mock form behind a **"Add a mock gateway (testing)"** disclosure
  (collapsed by default), keeping its explainer + Publish-to-HA-off default.
- Keep Discover as the recommended first action; manual real-add second; mock last/opt-in.

**Where:** the Gateways section in `templates/tabs/settings.html` (the `sub==='gateways'` block) — reorder
the mock vs manual-real subforms + their headings/disclosures. `gateways_tab`/settings JS holds the form
state; no endpoint change (POST /api/gateways already takes real + mock).

## FEAT-DASH-MODEL-DETAILS — show gateway/battery model on the main dashboard (queued)

**Status:** queued — **Filed:** 2026-09-30 (user). **Data exists:** `devicedb.gateway(SyHdVersion)` maps
the model (e.g. **aGate X-01-AU**, 100A, 2 circuits); `/api/support-info` already resolves it.

**Ask:** put model details on the main dashboard (gateway model, and battery/aPower model if available).

**Gap:** `/api/gateways` `model` is generic ("aGate") — it doesn't carry `SyHdVersion`, so it can't show
the specific devicedb model. Plan:
- Cache `SyHdVersion` in `GatewayState` when the poller reads firmware (1101 login carries it free), then
  enrich the roster `model` via `devicedb.gateway()` → "aGate X-01-AU".
- Show it on the SoC/Battery dashboard card (small line: model · country · service amps · aPowers).
- aPower/battery model is **cloud-only** (local has no SKU) — show when cloud creds resolve it, else the
  count + firmware. Reuse the support-info resolution.

## FEAT-SOC-RING-RESERVE-MARKER — mark the active mode's reserved SoC on the SoC ring (DONE 2026-09-30)

**Status:** queued — **Filed:** 2026-09-30 (user).

**Ask:** the SoC ring should show a marker (tick/line) at the **reserved SoC** for the **current operating
mode**, so you can see how close SoC is to the reserve floor.

**Data:** per-mode reserve % comes from `client.cloud_reserves` (cloud, creds-gated) — e.g. Self-Consumption
5%, TOU 15%, Emergency Backup 100% (see the Operating Mode & Reserves card). Draw a radial tick on the ring
at `reserve_pct` for the active mode; gate to when cloud reserves are available (else no marker). Ties to
the operating-mode card redesign (FEAT-DASHBOARD-MODE-CARD).

## FEAT-DOCS-DISCLAIMER — disclaimer on the docs home page, like the FranklinWH Cloud docs (DONE 2026-09-30)

**Status:** queued — **Filed:** 2026-09-30 (owner). **Cross-repo:** the bundled Guide (`/guide`) is the
**`franklinwh-local` library's** mkdocs (sibling repo `~/dev/franklinwh-local`), NOT this bridge — so the
edit lands in **`franklinwh-local/docs/index.md`**, and rebuilds into the image via `tools/build_image.sh`.

**Ask:** the docs **home page** should carry a prominent disclaimer box like the **franklinwh-cloud** docs
(`david2069.github.io/franklinwh-cloud`) do — currently the local library's home only shows a "Status:
alpha" admonition, no disclaimer. Owner requested this earlier; it was missed because the Guide is a
separate repo.

**Do:** add an **"Important Disclaimer"** admonition + a short **"About This Library"** section to
`franklinwh-local/docs/index.md`, mirroring the cloud docs' format:
- UNOFFICIAL · not endorsed/supported/affiliated with FranklinWH · AS-IS · no warranty · educational/
  informational · use at your own risk · respect rate limits · excessive use can impact the official app.
- "By using this you acknowledge…" bullet list (accessing an API not intended for you; may change/vanish;
  you assume all risk; use responsibly).
- Keep it consistent with THIS bridge's disclaimer set (Direct Connect/FleetView/SunSpec wording, the
  compliance/anti-circumvention terms, do-not-contact-FranklinWH-support, GitHub issues) — see
  [[FEAT-LEGAL-DISCLAIMER]]. Same for the bridge's OWN docs if/when it gets a dedicated guide
  ([[FEAT-HELP-TAB]] / DOC-SESSION-CHANGES).

## FEAT-HELP-TAB — promote "Guide" to a "Help" landing page (Guide + Support) (queued · optional)

**Status:** queued, OPTIONAL — **Filed:** 2026-09-30 (user: "that's enough changes, backlog as optional").

**Now (works, shipped):** the Support-info bundle + Guide link live in **Settings → Admin → Help &
documentation** (preview + Copy/JSON/CSV; `/api/support-info`). The Guide link is also in the mobile More
sheet. This is sufficient.

**Optional future:** rename the sidebar **"Guide" → "Help"** and make it a real **landing-page tab** with
two sections — **Guide** (open docs) and **Support** (the bundle, moved/mirrored from Settings) — plus the
GitHub Issues link, disclaimer, and version/uptime footer. Recommended over a second sidebar item (avoids
nav clutter). Reuse the existing `/api/support-info` + the Settings panel markup. Keep (or link) the
Settings → Admin panel too. Nav model: `_navTabsAll` in app.js (the Guide entry is currently an external
`<a href="guide/">`, not a tab — this would make it a tab). Ties to FEAT-LEGAL-DISCLAIMER (issues/docs
links) and the support bundle.

## FEAT-PARAM-SOLAR-SOURCE — consolidate solar-source parameters (export-only / non-CT solar) (queued · maybe too obscure)

**Status:** queued, LOW priority — **Filed:** 2026-09-29 (user; flagged possibly too obscure to build).

Solar is now derived from the local API — either **directly measured** (Gateway CTs) or **remotely
connected** (an inverter the aGate sees indirectly). A consolidated "solar source" parameter could
model the edge case where **solar is NOT measured by the Gateway CTs** yet still **affects the utility
meter for export** (e.g. AC-coupled PV downstream of the CTs / behind-the-meter but not gateway-metered).
Today the bridge treats solar as what the gateway reports; such solar would be invisible to our numbers
but real at the utility meter, skewing export/billing.

**Possible shape:** a per-site/meter flag "solar measured by gateway CTs? (yes/no)" + an optional
external solar source (a value or an HA entity), so export/billing math can account for un-metered PV.
Ties to the Site/Meter model ([[site-meter-utility-tariff-model]]) + the HA-entity provider pattern.

**User's own caveat:** "edge case might be too obscure." Keep deferred unless a real install needs it.

## DEF-GENERATOR-CARDS-WHEN-ABSENT — hide Generator energy/metrics when no generator installed/configured (DONE)

**Status:** FIXED 2026-09-29 — store flag `generatorInstalled` (from `/api/generator` `installed` = 1901 genEn OR configured; per-gateway, reloaded on gateway change). Gates the Power-Flow **GENERATOR** column (`x-show`, was a permanent 0 W), the sidebar Generator button, and the `generator` entry in the `navTabs` registry (so it drops from the bottom bar / More too); a now-hidden Generator tab redirects to the dashboard. Verified `installed:false` on the real gateway. Left intentionally: the system-setup **Generator input** toggle (a config control, not a metric) and the 1707 relay-state readout. **Filed:** 2026-09-29 (user). **Scope:** presentation gate, no data change.

**Ask:** Generator energy / metrics (the Generator tab content, the GENERATOR column in Power Flow,
any generator series/cards) must NOT be shown when a generator is **not installed or configured** —
right now it shows a flat `0 W` / empty generator surface on sites with no genset, which reads as a
broken/irrelevant card.

**Detect "has a generator":** derive from the gateway — 1901 genEn / rated-power (the Generator
capability read) and/or a persisted "generator configured" flag; on the mock, generator is NOT
synthesised, so it should read absent there too. A site with genEn off / rated 0 / no 1901 → treat as
no generator.

**Apply the gate to:**
- Generator **tab** (hide the nav entry + tab, or show a single "No generator configured" empty-state).
- Power-Flow **GENERATOR** column (drop it when absent, rather than a permanent `0 W`).
- Any generator **card / series** on Dashboard / Analytics / Energy.
- Same principle generalises: only surface a device's energy/metrics when that device is present
  (ties to the mock's known-absent Generator/V2L — see [[mock-emulator-capabilities]]).

**Note:** a real generator surface must still show when genEn is on but currently idle (0 W) — the
gate is "installed/configured", not "currently producing".

## DEF-BATTERY-REALTIME-CHARTS-GONE — battery tab shows no content / charts (cards all off)

**Status:** FIXED 2026-09-22 — root cause: saved card prefs had ALL cards toggled off (+ Chart toggle off), leaving the tab empty with no recovery (defaults are correctly all-on; fresh loads are fine). Added an empty-state in the BMS Telemetry view when nothing is visible, with one-click 'Show all cards' (resetBmsCards) + 'Show live chart' (toggleChart) recovery. ORIGINAL — **Filed:** 2026-09-22 (user, mobile screenshot)

**Symptom:** on the Battery tab (mobile) the realtime charts / BMS content are gone. In the
screenshot the **VISIBLE CARDS panel has ALL cards UNCHECKED** (BMS Header, Pack Metrics,
Cell Telemetry, Inverter & Power), so the whole BMS Telemetry body is empty except the
"Local only…" note; the **Chart** toggle is also off (Auto is on).

**Investigate:**
- Are the `bmsCards` visibility prefs defaulting/resetting to all-OFF (should default all ON)?
  Check `_loadBmsCards()` / the `fwh-battery-cards` localStorage default and `resetBmsCards()`.
- Is the realtime chart (the Chart toggle / Cell Telemetry trend) actually rendering when a
  card + Chart are enabled on THIS device? (We added `fwh-bat-chart` persistence in 7870a21 —
  confirm it restores and the canvas sizes, esp. on mobile width.)
- Prior related fix: 7870a21 (persist Chart/Auto). This is a distinct "all cards hidden" case.

## FEAT-DEVICE-MOBILE-MODAL — Device tab: open command detail in a modal on mobile + expand/collapse-all

**Status:** DONE 2026-09-22 — mobile (narrow) opens the selected command's detail as a full-screen modal (backdrop + × Close) instead of stacking far below the list; desktop keeps the two-column inline layout. Added Expand all / Collapse all for the group list. — **Filed:** 2026-09-22 (user, mobile screenshot)

On the Device tab (the command explorer), the group list (LIVE & STATUS, BATTERY, ENERGY &
CIRCUITS, MODES & TOU, GRID COMPLIANCE, DEVICE & NETWORK) is long, and the **selected
command's detail (power_flow · Raw JSON/JSON/CSV) renders FAR BELOW** the whole list — a big
scroll on a phone.

**Enhancement:**
- **Mobile:** open the selected command's detail in a **modal** (the best view on a phone)
  instead of rendering it far down the page. Desktop can keep the inline/side layout.
- **Groups:** make them expandable **cards with expand-all / collapse-all** so the user can
  fold the list down to find a command quickly.
- Doable: the groups + detail already exist; add a mobile-modal presentation (reuse
  `$store.app.narrow`) + an expand/collapse-all control.
---

## DEF-BOTTOM-NAV-ALWAYS-ON — bottom nav shown at desktop widths (breakpoint not firing)

**Status:** FIXED 2026-09-21 (verify pending rebuild)
**Reported:** 2026-09-21 (user: "bottom nav bar appears to be permanently on? energipay's
measure window size precisely to invoke in that context")

**Symptom:** the mobile bottom nav (Home/Battery/Solar/Schedule/More) stayed visible on
wide windows / iPad where the sidebar should take over. Two side-by-side windows: the wide
one still showed the bottom nav instead of the sidebar.

**Root cause:** visibility rode on Tailwind CSS breakpoint classes (`lg:hidden` on the nav,
`hidden lg:flex` on the sidebar). Those are generated by the runtime Tailwind CDN and were
not reliably applied (esp. inside Jinja includes / on iPad Safari), so the breakpoint never
switched.

**Fix:** measure the viewport precisely in JS (the same `matchMedia('(max-width:1023px)')`
the sidebar already uses) and expose a reactive `$store.app.narrow`. Sidebar =
`x-show="!narrow"`, bottom nav = `x-show="narrow"`, More sheet = `x-show="moreOpen && narrow"`,
main padding `:class narrow ? 'p-4 pb-24' : 'p-6'`. No dependence on Tailwind breakpoint
generation — matches Energipay's "measure window size precisely" approach.
---

## FEAT-HA-ADDON-PARITY — port Modbus bridge's HA add-on changes (timezone, Supervisor API, actionable notifications) (queued)

**Status:** queued — **Filed:** 2026-09-22 (user)

Port the HA add-on improvements the Modbus bridge made:
- **Timezone:** honor the HA add-on / Supervisor timezone so schedule triggers, TOU
  windows and timestamps fire/display in the user's local time (not container UTC).
  (The scheduler already assumes local time — verify it uses the add-on TZ.)
- **HA Supervisor API:** use the Supervisor token + API when running as an add-on —
  for config/ingress/services (and the notify path already auto-injects the Supervisor
  token in add-on mode; extend to whatever the Modbus bridge added).
- **Actionable notifications:** support HA actionable notifications (notification action
  buttons) — e.g. an orphaned-dispatch alert with a "Release" action button, a schedule
  alert with confirm/dismiss. Extends the notify-devices / VPP-monitor alerts to carry
  actions HA can render as buttons that call back into the bridge.

### Notes / reuse
- Cross-check the Modbus bridge's add-on config + Supervisor integration + its notify
  action payloads to port faithfully (clone = full depth: config, Supervisor calls, the
  action callback route, and the UI).
- Ties to FEAT-NOTIFICATIONS-SETTINGS (P3 per-event toggles) and the VPP monitor alerts.
---

## FEAT-WEATHER-SOLAR-OPENMETEO — Open-Meteo weather + Solar Forecast + PV setup (like Energipay)

**Status:** DONE 2026-09-22 — P1 backend (solar_forecast.py + /api/solar/forecast + weather.*/solar_forecast.* scheduler sensors), P2 Dashboard Solar Forecast card (weather chip, today/tomorrow totals+peak, hourly bar chart with NOW marker), P3 Location & PV settings (lat/lon/kWp/tilt/azimuth, auto-save). Matches the reference app closely. Follow-ups: Actual-vs-forecast overlay, 'Sync location from cloud'. ORIGINAL: queued — **Filed:** 2026-09-22 (user, Energipay/Sunamp screenshots)

Add weather + a solar-production forecast from **Open-Meteo** (free, no key), modelled on
Energipay's Solar Forecast card + PV setup.

### 1. Weather (Open-Meteo) — also scheduler-accessible
- Current conditions + temp (e.g. "15.8°C Drizzle") and a short forecast from Open-Meteo
  for the site lat/lon.
- Expose as **scheduler sensors/constants** (weather.temp_c, weather.condition,
  solar_forecast.today_kwh, .peak_kw, .remaining_kwh, etc.) so gates/templates can use them
  (same grouped picker as battery.soc_pct). The Modbus bridge's HA-Live "Solar production
  forecast" sensors are the reference set.

### 2. Solar Forecast card (Dashboard)
- Today / Tomorrow forecast: TOTAL kWh + PEAK kW @ time, an hourly bar chart with a NOW
  marker, Actual-vs-forecast overlay, and a Refresh. (Energipay layout.)

### 3. PV system setup (scales the forecast to the real array)
- Settings: **Latitude / Longitude** (+ "Sync location from cloud" — we have cloud compat),
  and **PV system**: Azimuth° (Open-Meteo convention: 0=south, ±180=north), Tilt°, Size (kWp).
- Feed lat/lon/azimuth/tilt/kWp into the Open-Meteo solar endpoint to scale the forecast.

### Notes / reuse
- Open-Meteo has both a weather and a solar-radiation/forecast endpoint; PV kWp + tilt/azimuth
  scale GHI/POA to kWh. Cross-check Energipay's Open-Meteo usage to port faithfully.
- Ties to FEAT-UTILITY-BILLING (pricing) and FEAT-CUSTOM-CARDS (the forecast as a card).

## FEAT-DASHBOARD-CUSTOMIZE — full dashboard customisation + config modal (like Energipay "Customize Dashboard") (queued)

**Status:** queued — **Filed:** 2026-09-22 (user)

A dedicated **Customize Dashboard** entry (a button at the bottom of the Dashboard) that
opens a **modal** to configure the dashboard: which cards show, their **order** (up/down,
touch-friendly), and per-card options. Supersedes/absorbs the lighter FEAT-CUSTOM-CARDS
(show/hide + reorder) into one modal-driven customisation surface, matching Energipay's
"Customize Dashboard" pattern. Persist per-browser first (localStorage), DB-per-user later.
- Reuse the existing dashCards show/hide + the up/down reorder pattern; wrap in a modal
  reachable from a bottom "Customize Dashboard" button.

---

## FEAT-UTILITY-BILLING — port Modbus constants + utility/tariff/billing into one tab (queued)

**Status:** queued — **Filed:** 2026-09-22 (user)

Port the Modbus bridge's constants + utility/billing model to the local bridge, and
give it a single combined tab.

### 1. Constants (accessible to the scheduler)
- Port the Modbus bridge's user-defined **constants** — named values usable in schedule
  conditions/templates alongside the sensor namespace (e.g. billing rates, thresholds,
  demand limits). They should appear in the scheduler's grouped sensor/value picker
  (same place battery.soc_pct etc. live) so gates and `%…%` templates can reference them.

### 1b. NEM wholesale pricing (Australia only)
- The **NEM Region** field (NSW/VIC/QLD/SA/TAS) is **Australia-only**: it queries the
  **National Energy Market (NEM)** API by region code to get **state-based wholesale
  spot pricing** (e.g. "$73/MWh · 7.3c/kWh · NSW" in the Energipay header). Gate this UI
  to AU installs (or when a NEM region is set); it feeds live spot price into billing +
  the scheduler (a `tariff.spot_price` sensor). Non-AU users use the tariff periods below.

### 2. Utility + tariff + billing settings
- Port the Modbus **utility rate / tariff** model (TOU periods & prices, demand charges,
  fixed charges, export/feed-in) and **billing** functionality (cost estimation from the
  metrics/energy series).
- Settings to configure the tariff (periods, seasons, day-types, prices) and utility.

### 3. One combined tab (multiple sub-tabs)
- Combine **Costs** and **Tariff** into a **single tab with sub-tabs** (e.g. Tariff /
  Costs / Demand / Billing) rather than separate tabs — the user's preferred layout.

### Notes / reuse
- Sensor/constant picker already exists (scheduler `/api/schedules` grouped sensors) —
  extend it with a Constants group.
- Cost series source: the metrics store (`/api/metrics`) + energy flow already built.
- Cross-check the Modbus bridge's tariff/billing/demand modules for the data model to
  port faithfully (constants, tariff periods, demand.peak_kw etc.).
- Ties to FEAT-CLOUD-TOU-SCHEDULE (cloud TOU import) and FEAT-SCHEDULER-* (constants in gates).
---

## FEAT-ENERGY-SANKEY-RANGES — match Modbus energy flow: Day/Week/Month/Year + date picker (DONE)

**Status:** queued — **Filed:** 2026-09-22 (user, Modbus dashboard screenshot)

Bring the Dashboard's **Energy Flow (Sankey)** to parity with the Modbus bridge's:
- **Range presets:** Day / Week / Month / Year toggle (segmented control).
- **Date picker / stepper:** ‹ prev · the selected date/period label · next › · **Today** —
  so the user can walk back through history and jump to now.
- The Sankey totals (Solar / Battery / Grid → Home / Battery / Export) recompute for the
  selected range. Keep the honesty note ("Derived from power samples; lifetime totals are
  metered.").

### Notes
- We already have a Sankey on the Dashboard + the metrics store (`/api/metrics`,
  `/api/energy/flow`) — this adds the range selector + date navigation and makes the flow
  query honor the chosen period, matching the Modbus layout (Day/Week/Month/Year + ‹ date ›
  · Today).
- Reuse the timeline/metrics bucketing already built for the scheduler timeline.
---

## FEAT-CUSTOM-CARDS — user-added sensor cards + reorderable dashboards (queued)

**Status:** queued — **Filed:** 2026-09-22 (user)

Let the user compose the Dashboard (and Battery) from their own cards, and reorder them.

### 1. Add-your-own card widget
- A user can **add a card for any sensor** — an HA sensor (from the HA instances /
  notify plumbing's entity list) OR a built-in bridge sensor (the same `sensor.id`
  namespace the scheduler conditions use: battery.soc_pct, grid.power_w, mode.name, …).
- Card can be a **value tile** OR, if they choose, a **mini chart / sparkline timeline**
  (reuse the metrics store series for built-ins; HA history for HA sensors).
- Persist the user's card set (localStorage first, like the existing dashCards/bmsCards;
  a DB-backed per-user set later once accounts exist).

### 2. Reorder (simple, touch-friendly)
- On the **main Dashboard AND Battery**, let the user **reorder cards** with a simple
  control: select a single card, move it **up / down** with arrows (no HTML5 drag — it
  doesn't work on iPad touch; this was the lesson from FEAT-DASHBOARD-CARDS Phase 2).
- Builds on the existing show/hide card system (dashCards / bmsCards) — add an order array
  + up/down that swaps neighbours, persisted alongside the visibility prefs.

### Notes
- Reuse proven patterns: the show/hide "Cards" panels already exist on Dashboard + Battery;
  this extends them with order + a "＋ Add card" that picks a sensor and a render style.
- Sensor list source already exists: `/api/schedules` returns the grouped sensor namespace
  (Gateway + HA instances); the mini-chart series source is the metrics store (`/api/metrics`).
---

## FEAT-NOTIFICATIONS-SETTINGS — Energipay-style notifications management in Settings

**Status:** Phase 1 DONE 2026-09-21. Legacy HA-tab notify panel RETIRED 2026-09-21 (Settings is the sole notify UI). P3 (per-event toggles) DEFERRED — reframed for FWH battery/integration states.
**Filed:** 2026-09-21
**Reference:** Energipay (Settings → HA Instances + Companion Devices + Push Notifications +
broadcasts). NOT the Modbus Bridge — it lacks the individual-device/broadcast management.

User: our notify setup "is not setup in settings like Energipay's, which lets [you] see
individual devices [and] send notification broadcasts". We already have the plumbing but
it's buried in the HA tab and missing the broadcast + per-event pieces.

### What we ALREADY have (reuse, don't rebuild)
- `notify_devices` table: id, alias, instance_id, service, enabled.
- `GET /api/ha/notify-devices` → `{master_enabled (ha_notify), devices:[{alias,service,
  enabled,instance,...}]}`; POST/PATCH/DELETE; `POST /api/ha/notify-devices/test`.
- `GET /api/ha/notify-targets` (Discover — the HA `notify.*` services).
- HA-tab add-device flow: Discover → filterable picker → Test-before-save.
- Scheduler already supports per-entry HA actions (device + title + message).

### Gaps (the actual work)
1. **Surface it in Settings** — a "Notifications" section (like the HA-Instances card):
   HA Instances list + Companion Devices list (alias · service · instance · On/Off · Edit
   · Delete) + master Push toggle (Enable All / Disable All, = `ha_notify`).
2. **Broadcast send** — a "Send notification" action: custom title+message to one device or
   ALL enabled devices, on demand. New `POST /api/notify/broadcast` reusing the notify
   send path (the test endpoint is 90% of it).
3. **Add Companion Device modal** in Settings (reuse Discover picker + Test-before-save).
4. **Per-event push toggles** (Energipay's "Device online/offline status" etc.) — a small
   table of event types each independently on/off, gating which system events notify.

### Phasing
- **P1:** ✅ DONE 2026-09-21 — Settings Notifications section: master push toggle (live
  PUT ha_notify), HA Instances (list + Add + Delete), Companion Devices (mute toggle,
  Test, Delete, Add-with-Discover+Test), Broadcast-to-all (new POST
  /api/ha/notify-devices/broadcast). Verified headless, 0 console errors.
- **P2:** ✅ mostly DONE — Add-device + Add-instance flows are in Settings (Discover +
  Test-before-save). Remaining: move/retire the now-duplicate HA-tab notify UI.
- **P3:** DEFERRED (not now, per user 2026-09-21). Per-event push toggles — but reframed
  around **FranklinWH states, not Energipay's generic list**: independent on/off per event
  for **major battery states** (e.g. SoC crosses low/full thresholds, charging↔discharging
  transitions, battery fault/over-temp) and **integration states** (gateway online/offline,
  cloud connect/disconnect, MQTT up/down, poller stale). Needs: an event catalogue + a
  per-event enable table (new settings/db), an evaluator that fires the broadcast on a
  qualifying transition, and per-event target selection (which devices). Build on P1's
  broadcast path.
- **Also:** debug any Discover/notify failure against the real HA (user reported it may be
  broken — needs the actual error/behaviour).
---

## FEAT-DASHBOARD-CARDS — customisable main dashboard (show/hide + reorder cards)

**Status:** Phase 1 (show/hide) DONE 2026-09-21. Phase 2 (reorder) DROPPED 2026-09-21 — HTML5 drag doesn't work on the iPad (touch), and reorder needs the multi-row/col-span grid flattened into one container; effort/complexity not worth it over show/hide. Reopen only if a touch up/down control is wanted.
**Filed:** 2026-09-21
**Reference:** the Modbus Bridge's **"Cards"** control (clone it for parity)

The main dashboard has grown cluttered — every card is always shown, in a fixed
order. Add per-card **show/hide** and **reorder**, so users tailor it to what they
care about. Mirror the FranklinWH **Modbus Bridge** dashboard's "Cards" feature:

### What the Modbus Bridge does (to copy)
`dashboard_tab.js` + `dashboard.html` there:
- A **"Cards" dropdown** listing every card with a checkbox (`cardVisible[key]`,
  `toggleCard(key)`), plus a **Reset to defaults**. Persisted to
  `localStorage['fwh-dashboard-cards']`.
- **Drag-to-reorder**: each card is `draggable="true"` with
  `:style="`order:${cardOrder.indexOf(key)}`"` and `dragstart/dragover/dragend`
  handlers; `cardOrder` persisted to `localStorage['fwh-dashboard-order']`.
- `DEFAULT_CARDS` sets initial visibility (some hidden by default); on load, the
  saved order is kept and any **new** card keys are appended (forward-compatible).

### Our dashboard cards (give each a stable key)
`batterySoc` (State of Charge ring), `powerFlow`, `battery` (pack summary),
`energy` (today totals), `energyFlow` (Sankey + date picker), `operatingMode`
(Mode & Reserves), `latency` (round-trip), `modbus` (:502 status) — plus any
added later. Keys must be stable (persistence + merge rely on them).

### Implementation notes
- Wrap each card `<div class="card">` with `x-show="cardVisible[key]"`,
  `draggable="true"`, and `:style="`order:${cardOrder.indexOf('<key>')}`"`; the
  grid container needs `display:flex/grid` with a defined order flow so CSS
  `order` takes effect (the current `grid-cols` layout may need a wrapper per
  card or a flex row — check the Sankey/Power-Flow `lg:col-span-2` cards keep
  their width when reordered).
- A `dashboardTab`-style Alpine block (the dashboard is currently store-driven —
  `$store.app` — so the card state can live on the store or a small component).
- Card state is **per-browser** (localStorage), like the real-time caps and the
  gateway selection.
- Nice-to-have: a compact/density toggle, and remembering per-gateway layouts
  (defer — start with a single global layout).

Scope: UI-only, no backend. The heavy lift is threading the visibility/order
bindings through the existing dashboard markup without breaking the responsive
grid.

---

## FEAT-MULTI-GATEWAY — finish multi-gateway (most of it already exists)

**Status:** queued — **audit + finish**, not a from-scratch build
**Filed:** 2026-09-13

**Already implemented** — worth knowing before starting:
- config parses a gateway list (host + label), with fallback to `fwh_host`
- `state.py` registry keeps gateways in insertion order; the poller runs per-gateway
  (`gw.id`, `gw.serial`, `gw.active_host`) and tags samples
- `metrics.gateway_id` column + idempotent migration; `query(gateway=…)` filters
- `GET /api/gateways`, `GET /api/gateways/{id}/summary`, `…/command`
- **topbar switcher exists** (`partials/topbar.html`), auto-hidden for a single gateway
- `tests/test_gateways.py`

**What is actually left:**
1. **Per-tab audit.** Confirm every tab honours `$store.app.selectedGateway`. Dashboard and
   Battery pass it; Device / Health / Control / MQTT need checking — a tab that silently
   reads the *default* gateway while the switcher says otherwise is worse than no switcher.
2. **Switcher parity with FWHAI / Modbus Bridge.** Ours is a bare `<select>`; theirs shows
   name + live status (online, mode, SoC) so you can see which gateway is unhappy without
   switching to it.
3. **Poller concurrency.** Check whether gateways poll in parallel or in series. In series,
   one slow/unreachable gateway delays every other — and given a cycle is unbounded
   ([[DEF-POLLER-STALL]]) that turns one bad link into a site-wide recording gap.
4. **Per-gateway MQTT/HA identity** — distinct node ids and device entries so HA does not
   merge two gateways into one device.
5. **Retention/stats per gateway** in `/api/health` and the metrics info panel.

### Target model: mirror the Modbus Bridge's gateway record
Our gateways are parsed from a config string — no CRUD, no per-gateway settings. The Modbus
Bridge treats them as **persisted records**, and that is the model to adopt:

```
id · name · description · host · port · unit_id
enabled · autostart · display_order
poll_interval          <- PER GATEWAY, not one global interval
serial · model · firmware · ac_type · last_connected_at
mock                   <- simulated gateway
service_id             <- link to a Utility service
phase · phase_view     <- three-phase support
```

with per-gateway lifecycle endpoints: `start` · `stop` · `restart` · `test` · `diagnose` ·
`healthcheck` · `detect-phases` · `points` · `command`.

**`mock` gateways** — we are well placed for this: the library already ships an in-process
emulator (`franklinwh-local emulate`, `franklinwh_local.emulator`) with a synthetic
per-seed site. A mock gateway can point at it, giving demo data and UI development with no
hardware. Note `data-demo/` already exists, so some of this intent is present.

**`service_id` → Utility service.** The Modbus Bridge holds a service record:
```
name · meter_number · account · ac_service · rated_amps (63 here)
has_tou · has_peak_demand · has_export_bonus · min_monthly_bill · pricing_api
demand_window {months, days, start, end}    bonus_window {months, days, start, end}
```
This is what gates its scheduler — `tariff.bonus_window_active` comes from `bonus_window`.
Any local Scheduler ([[FEAT-UI-PARITY]]) needs the same concept, so the service model is a
**prerequisite**, not a nicety. Mirroring the shape also means one service can be shared
across bridges rather than redefined per tool.

**Per-gateway `poll_interval` matters here** — combined with [[DEF-POLLER-STALL]]'s
unbounded cycle, a single global interval means one slow gateway degrades all of them.

---

## FEAT-UI-PARITY — tabs and controls matching FWHAI / Modbus Bridge

**Status:** queued
**Filed:** 2026-09-13
**Related:** [[EPIC-LOCAL-ORCHESTRATION]] (library) — prerequisite for the Scheduler

Bring the sidebar closer to FWHAI / the Modbus Bridge. Candidates, with what the local
channel can actually back:

| tab | local backing | notes |
|---|---|---|
| **Smart Circuits** | `1409` (config) + `1411` (per-circuit V/I/P/energy) | `set_smart_circuit` exists in `catalog.WRITES` but is **not hardware-verified** — verify before exposing a toggle |
| **Generator** | `1901` (genEn, rated power, start/stop, charge windows) | read-only locally; no write is exposed |
| **Schedule / Scheduler** | — | **the big one.** The Modbus Bridge's scheduler is what actually drives this site. A local equivalent needs verified write primitives first — see `EPIC-LOCAL-ORCHESTRATION` |
| **Solar** | `1903` | incl. `grid_feed_max`, PV port config |
| **Grid profile** | `1203` + `1211–1229` + `1251–1277` | 25 cmdTypes; slow fan-out, on-demand only |

**Do not start the Scheduler first.** Without verified writes it can only show a schedule it
cannot enact. The read-only tabs (Generator, Solar, Smart Circuits view) are independently
useful and cheap.

---

## FEAT-HA-ENTITIES — expand HA entity coverage

**Status:** queued
**Filed:** 2026-09-13

Publish more of the now-catalogued telemetry as HA entities, in the spirit of FWHAI / the
Modbus Bridge. Newly available since the 2026-09-11 sweep:

- **Battery/BMS** (`1705`): SoH, pack voltage, pack current, cell **spread**, min/max cell
  voltage, max cell temperature, alarm level
- **Electrical** (`1703`): grid/inverter L1+L2, DC bus rails, buck-boost current
- **States** (`1835`/`1827`): BMS / DSP / PE state
- **Energy** (`1301` tiers): per-tariff daily energy — a genuine differentiator, the cloud
  does not expose it
- **Firmware** (`1833`): `bms_ver`, PE/BMS serials as diagnostic attributes

**Design constraints to settle first:**
1. **Do not publish 32 per-cell entities.** 16 voltages + 16 temperatures would swamp the
   device page for little value. Publish the *derived* signals (spread, min/max, hottest
   cell) and keep the per-cell array as an attribute or leave it to the Battery tab.
2. **Entity category** — diagnostics belong under `entity_category: diagnostic` so they do
   not clutter the main card.
3. **Availability** must follow the poller, not the bridge: entities should go
   `unavailable` when the aGate is unreachable rather than freezing on a stale value.
4. **Naming/uniqueness** must be per-gateway — see [[FEAT-MULTI-GATEWAY]] (4).

---

## FEAT-SCHEDULER-TEMPLATES — rename presets → templates, import Modbus set, duplicate-to-edit (DONE 2026-09-21)

**Status:** queued — **Filed:** 2026-09-17 (user, Modbus-bridge "Templates ▾" screenshot)

Bring the Scheduler's preset system up to the Modbus Bridge's "Templates" model.

### Asks (verbatim intent)
- **Rename our "Presets" → "Templates"** everywhere in the Scheduler UI (button,
  modal, code comments, the `PRESETS`/`/api/schedules/presets` naming where user-facing).
- **Import / translate the Modbus Bridge's templates.** From the screenshot the
  Modbus set includes: *Peak-demand shaving* (discharge to cap grid import in the peak
  window), *Battery export bonus* (discharge to grid during export-bonus window),
  *Ausgrid — Evening discharge (4–9pm)* (network 16:00–21:00 — check retailer),
  *Ausgrid — Solar sponge (10am–3pm)* (charge from solar to self-consume + avoid the
  export charge). Translate each to the LOCAL scheduler's action vocabulary.
- **Duplicate-to-edit.** Applying a template should create an EDITABLE COPY (a normal
  schedule entry), leaving the original template intact — "so [the] user [can] modify
  n keep [the] original". Add a "Duplicate" affordance on existing entries too.

### Honesty constraint (important — don't ship a lie)
The Modbus templates lean on **Force Discharge / Force Charge** (the screenshot's entry
is "Force Discharge", and the log shows dispatched force-discharge). On the LOCAL
channel those have **no path** — force charge/discharge are cloud/Modbus-only (see
`scheduler.py` UNAVAILABLE, and RESEARCH/ANALYSIS-LOCAL-ONLY). So a "Peak-demand
shaving = force discharge" template can't actually run locally.
Options to resolve before/while building:
  1. Import them but mark force-charge/discharge templates **UNAVAILABLE (cloud/Modbus
     only)** with the reason, same as the scheduler already does for those actions —
     honest, and useful to anyone who later wires a cloud provider.
  2. Translate to the nearest LOCAL-capable action where one exists (e.g. Emergency
     Backup ≈ force-charge-to-100; mode switches; smart-circuit on/off) and label the
     approximation.
  3. If/when a cloud force provider (FWHAI-style TOU manipulation) is added, the
     force-* templates light up for real.
Recommend (1)+(2): import the full set for parity, run what the local channel can,
clearly flag what it can't. Never present a force-* template as working locally when it
is silently discarded.

### Notes
- Templates should carry a `gateway`/retailer note field (the Ausgrid ones are
  network-specific — keep the "check your retailer" caveat visible).
- Ties to `FEAT-SCHEDULER` (v1 DONE) — this extends its preset system.

---

## FEAT-ENERGY-SANKEY — energy-flow Sankey + date picker (v1 DONE)

**Status:** **v1 DONE 2026-09-17** (Dashboard Sankey + day picker) — **Filed:** 2026-09-17
(user, Modbus-bridge Energy-Flow screenshot)

### v1 shipped
Ported the Modbus Bridge's renderer + decomposition verbatim; adapted the data source.
`energy_flow.py` (merit-order split), `sankey.js` (SVG), `GET /api/energy/flow` (integrates
the metrics store), `energy_flow_card.js` + a Dashboard card with the ‹ / day / › / Today
picker, per-node day totals and an honest caption. Live: coverage 99.9%, residual
0.001 kWh, node totals match the gateway's metered daily counters. Sign conventions were
verified on live data first. **Still open (v2):** the **Lifetime Energy (MWh)** card — the
local aGate meters *daily* kWh only (`kwh_*` reset at midnight), not lifetime, so that card
needs either a bridge-side accumulator table or is simply N/A locally; and week/month/year
period views (backend already accepts start/end spans).

Match the Modbus Bridge's Energy dashboard: a **Sankey** of the day's energy flow
(Solar → Home / Battery / Export, Battery → Home / Export, Grid → Home / Battery) with
a **date picker** (‹ ›, "Today") for historical days, plus the **Lifetime Energy** card.

### Data source — settled (user asked "DB metrics or gateway local metrics?")
**Both, split by role** — mirrors the Modbus Bridge ("Derived from power samples;
lifetime totals are metered"):
- **Sankey daily flows → the bridge SQLite metrics store.** `metrics(ts, soc, grid_w,
  solar_w, battery_w, load_w, generator_w, mode)` already samples instantaneous power at
  the 5 s poll. Integrating a day's samples gives kWh, and the **decomposition** (how much
  solar went to home vs battery vs export) can only come from per-timestep power — the
  gateway's scalar counters can't express flow splits.
- **Lifetime Energy totals → gateway metered accumulators** (1301: `kwh_sun`,
  `kwh_uti_in`/`kwh_uti_out`, `kwh_fhp_chg`/`kwh_fhp_di`; already published as HA
  sensors in `publish/entities.py`). Metered + lifetime — more accurate than integrating
  months of samples, and not bounded by when the bridge started.

### Build sketch
1. **Backend `GET /api/energy/flow?date=YYYY-MM-DD`** — read that day's `metrics` rows,
   integrate each channel (∫ P dt over the sample intervals → Wh), then run a per-timestep
   **flow decomposition** to split Solar/Battery/Grid into their destinations. Return the
   node/link totals for the Sankey + the day's channel kWh.
2. **`GET /api/energy/lifetime`** — the gateway accumulators (already read for the HA
   sensors) for the Lifetime Energy card.
3. **Dashboard UI** — a Sankey (Chart.js has no native Sankey; either a small
   self-contained SVG renderer or the `chartjs-chart-sankey` plugin bundled locally — no
   CDN) + the ‹ / date / › / Today picker, and the Lifetime card.

### Honesty constraints (don't overclaim)
- **History only goes back to when the bridge started sampling** — older days have no
  `metrics` rows. Show "no data before <first sample date>" rather than a blank/zero day.
- **Sample gaps** (bridge offline, VPN down — cf. the "Can't reach the bridge" banner in
  the same screenshot) leave holes; integration must handle gaps (skip, don't extrapolate)
  and ideally flag a day as partial.
- **The flow split is a heuristic** — the gateway does not meter per-path flows, so the
  Sankey is a reasoned estimate from signed power, not metered truth. Say so under the
  chart, exactly like the Modbus Bridge's "Derived from power samples" caption.
- **Sign conventions** must be pinned first (battery_w +charge/−discharge? grid_w
  +import/−export?) from `metrics` before decomposing — get these wrong and the Sankey
  reverses.

### Ties
- `ANALYSIS-METRICS-GAP` (what the store holds) and the energy HA sensors already added.

---

## FEAT-SCHEDULER-FORCE-VIA-MODBUS — force charge/discharge/standby via DIRECT Modbus to the aGate (DONE)

**Status:** DONE 2026-09-22 — one `force` scheduler action (direction charge|discharge|standby;
power kW _or_ % of inverter; optional Target SoC), gated on the direct-Modbus path
(`battery_control`) being reachable — same engine as the dashboard widget, independent of the
modbus-bridge service. Dispatch runs for the schedule WINDOW; the bridge watchdog auto-releases
at window end + enforces Target SoC; the window's exit edge also releases as a safety net.
Verified on the real aGate in dry-run (3kW → WSetPct=600; standby → 0W; release → released; no
battery moved). — **Filed:** 2026-09-21 (user)
**Depends on:** FEAT-SCHEDULER-FULL-PARITY (scheduler shell + action vocabulary).

The local sendMqtt channel **cannot** force charge / force discharge / force standby or set
a VPP power setpoint — the aGate accepts and discards those writes (see `scheduler.py`
UNAVAILABLE, RESEARCH/ANALYSIS-LOCAL-ONLY). The **aGate's Modbus interface CAN**: drive its
**WSet VPP setpoint** over Modbus (M704 registers `WSetEna` / `WSetPct` (% of inverter power)
or `WSet` (W) / `WSetRvrtTms` to hold VPP mode). So make these actions **available only when a
Modbus bridge is reachable**, by having the local bridge call it.

### Behaviour
- **Actions:** `force_charge`, `force_discharge`, `force_standby` — currently shown greyed as
  UNAVAILABLE. When Modbus is enabled+reachable, promote them to real, offerable actions;
  otherwise keep the greyed "(Modbus/cloud only)" reason. So the same catalogue, gated on a
  live capability probe.
- **Parameter:** power as **kW _or_ % of available inverter power** (matches the Modbus WSet
  model: `WSetPct` = %, `WSet` = W; charge = one sign, discharge = the other). Standby =
  `WSetEna` on with 0 setpoint (hold), or the bridge's standby command.
- **Duration/hold:** WSet needs `WSetRvrtTms > 0` to stay in VPP mode; a local scheduler
  window's duration maps to that revert timer. On window end / disable, RELEASE (clear
  WSetEna + zero WSetRvrtTms) so the aGate returns to its work mode — never leave it pinned.

### Wiring — DIRECT Modbus to the aGate (NOT via the modbus-bridge service)
> **User decision 2026-09-21:** the local bridge stays **independent** of the separate
> `franklinwh-modbus-bridge` project. Do NOT call that service. Speak **Modbus TCP directly
> to the aGate** and write the WSet registers ourselves.
- Add a small **Modbus TCP client** to the local bridge/library (e.g. pymodbus) that connects
  to the aGate's Modbus interface (the same interface the modbus-bridge uses; typically TCP
  502) and writes the **M704 WSet** registers: `WSetEna` (enable), `WSetPct` (% of inverter
  power) or `WSet` (W), `WSetRvrtTms` (VPP hold timer). Sign selects charge vs discharge;
  standby = enable with 0 setpoint.
- **Port the sequence** from the modbus-bridge repo's `command_handler.py`
  (`activate`/`hold`/`release` around `WSetRvrtTms`) and its register map for reference — but
  ship it self-contained; no runtime dependency on that service.
- **Config:** an aGate **Modbus host/port** setting (default the gateway host : 502) + a live
  **capability probe** (can we read/write M704?) that flips the force actions available;
  greyed with the reason otherwise.
- **Caveat:** two Modbus masters must not fight — if the user also runs the modbus-bridge
  against the same aGate, document that force should be driven from one place at a time.

### Honesty constraints
- Only promote the actions when the Modbus path is actually reachable — a live probe, not a
  static flag. If the probe fails at fire time, log the schedule event as gated with the
  reason, don't silently no-op.
- **Always release** on window end/crash/restart (mirror the Modbus bridge's crash-safety:
  it zeroes WSetRvrtTms/WSetEna to exit VPP). A pinned VPP setpoint is a battery-safety issue.
- This also unlocks the Visual Timeline's **VPP-override band** (FEAT-SCHEDULER-FULL-PARITY §1),
  which is only meaningful once a force provider exists.

---

## FEAT-SCHEDULER-FULL-PARITY — clone the Modbus Bridge Scheduler + HA Entities + Settings, exactly (queued)

**Status:** ✅ Phases A–E DONE 2026-09-21 (condition gate + Test Verification;
templated HA actions; Activity Log filters; Visual Timeline chart; Templates rename +
duplicate). Follow-ups: force-via-Modbus (own item), per-gateway timeline rows,
planned-vs-ran shading, Trigger Types/Power(%|W) in the modal.
> Card actions decluttered 2026-09-21 — Edit + Turn on/off inline, the rest (Test /
> Run now / Duplicate / Delete) in a ⋮ overflow menu (Modbus Edit/⋮ pattern). — **Filed:** 2026-09-18 (user, Modbus-bridge Scheduler
screenshots) — a large epic; supersedes/extends `FEAT-SCHEDULER` (v1 DONE) and
`FEAT-SCHEDULER-TEMPLATES`.

Goal: reach **exact functional parity** with the Modbus Bridge's Scheduler and its
neighbours — same tab views, the visual timeline chart, the rich Edit-Entry modal, the
audit trail, HA Entities, and de-static-ify Settings. Adapt (don't copy) where the local
sendMqtt channel genuinely can't do a thing.

### 1. Scheduler tab — full layout (Modbus "Schedule & Automations")
- **Header:** entry count, **Export / Import / Templates ▾ / + Add Entry** (Templates =
  the `FEAT-SCHEDULER-TEMPLATES` set).
- **VISUAL TIMELINE** ✅ DONE 2026-09-21 — SVG chart: real **work-mode band** (dominant
  mode per 10-min bucket, so the flapping Self/TOU reads read as a clean band), **SoC %
  line** over the day, **fire markers** (from the activity log, coloured by status), now
  marker, hour axis, legend; the planned schedule windows sit below. Per the honesty
  constraint there is **no VPP-override band** (no local force provider yet). Backend:
  timeline endpoint returns soc/modes/fires; `db.mode_segments()` buckets+coalesces.
  TODO later: per-gateway rows, planned-vs-ran shading, alarm/outage ticks, range picker.
- **ENTRIES table:** Name (+AUTO badge), When, Action, Conditions (gate·exit summary),
  Target (gateway), Next Fire, Actions (**Edit / Run(▶) / ⋮**), an "Enabled only ▾" filter
  and an "N hidden" count.
- **ACTIVITY LOG** ✅ DONE 2026-09-21 — status **filter chips** (colour-coded, with
  counts) + rich detail: gated lines name the failing leaf with its live value
  (`battery.soc_pct between 50..100 (live=27.05)`), plus fired/exit/waiting/error. New
  statuses emitted: `gated` (once/day while a window is open but conditions block it),
  `waiting` (dwell), `exit` (window close). ORIGINAL SPEC: time · entry · status · detail, with status
  **filter chips** (fired · executed · ha action · gated · waiting · missed · exit
  condition met). Detail strings show the gate that gated ("battery.soc_pct between 50..100
  (live=None)"), dispatch lines, and HA-action fire/exit lines with rendered templates.

### 2. Edit-Entry modal — the big one
> **✅ Phase A DONE 2026-09-21:** the ENTRY CONDITIONS gate is fully ported —
> recursive evaluator + 13 operators (incl between/in/matchlist/like) with Modbus's
> exact fail-closed semantics; nestable ALL/ANY groups; Value|Lookup (sensor-vs-sensor);
> Test Verification (POST /api/schedules/evaluate → per-row green/red/amber + overall
> PASS/FAIL); Duration-hold (entry_hold_s, HH:MM:SS) enforced in tick with a dwell timer
> that resets on gate failure.
>
> **✅ Phase B DONE 2026-09-21:** HA actions gained `when` (On entry / On exit / Entry &
> exit) fired per window edge, an optional per-action guard (single condition reusing the
> gate controls incl between/Lookup), and `%sensor.id%` templated title/body (substituted
> at fire time). Engine tracks the window inside/exit edge (_window_inside) to fire exit
> actions once on close; manual Run fires the entry phase honouring guards.
>
> Still TODO in this modal: Trigger Types (Daily/interval/sensor) / Quick Preset / Power(%|W).
- Name; **Trigger Type** (Daily at time / interval / sensor / …); **Quick Preset** (fills
  fields); Fire At; **Duration (min)** (0 = brief, bound by an exit condition); Action +
  **Power (% or W)**.
- **ENTRY CONDITIONS** = a **gate**: MATCH ALL/ANY, nestable **groups** (+row / +group /
  remove group, per-group ALL/ANY), each row = sensor (grouped, filterable picker) ·
  operator (==, between, <, …) · **Value | Lookup** toggle (Lookup = compare to another
  sensor) · value input(s).
- **Test Verification**: evaluate the gate against live values — per-row **green
  outline=passes / red=fails / amber=no value**, a `live: <v> ✓ passes now / ✗ fails now`
  tag per row, and an overall "conditions currently PASS/FAIL".
- **DURATION (HH:MM:SS)** — conditions must hold continuously this long before firing.
- **HA ACTIONS** (repeatable): Notify · **entry & exit / entry / exit** · target (HA Live
  notify service) · **+guard** conditions · title + **templated body** with `%sensor.id%`
  live substitution (unreadable → `?`, never blocks).
- Enabled toggle · Cancel · Save Changes.

### 3. HA Entities tab — parity
Match the Modbus HA-entities browser fully (totals, domain filter, topics, exposed-only,
expose toggles, per-entity detail). Cross-check against what our current `FEAT-HA-*` work
already covers and close the gaps.

### 4. Settings — de-static-ify ("fix static in Settings")
The Modbus Settings is largely **editable** (broker/host/poll/etc. with inputs + save);
ours is mostly read-only display. Make the equivalent fields editable where safe, matching
the Modbus layout/behaviour. (The Gateways card is already done.)

### 5. "All others"
Sweep the remaining Modbus tabs (Dashboard widgets, Energy Costs, Sequencer, SunSpec
Explorer equivalents where meaningful for local) for parity gaps and file/close each.

### Honesty constraints (critical — do NOT ship a lie)
- The Modbus Scheduler's core action is **Force Discharge / Force Charge** and a **WSet
  VPP setpoint** that overrides the work mode. On the LOCAL sendMqtt channel these have
  **no path** (see `scheduler.py` UNAVAILABLE, RESEARCH/ANALYSIS-LOCAL-ONLY). So:
  - Import the UI/actions for parity but mark force-*/VPP **UNAVAILABLE (cloud/Modbus
    only)** with the reason, OR map to the nearest local-capable action (set_mode,
    smart-circuit on/off, Emergency-Backup≈force-charge), clearly labelled.
  - The **Visual Timeline's "VPP override" band** is only meaningful once a cloud force
    provider exists; until then show the real work-mode band + SoC, and omit/grey the
    override lane.
- Sensor **Lookup** and live gate evaluation must reuse the existing `scheduler.py`
  `substitute()` / `evaluate()` (missing sensor = FALSE, `%id%` → `?`).

### Build note
Large — do it in phases (timeline chart → rich condition-group editor + Test Verification →
audit-trail filters → HA-entities gaps → Settings editable), each committed + verified,
ideally against the mock gateway so multi-gateway timeline/targets are testable.

---

## FEAT-CLOUD-SCHED-CONFLICT — detect LOCAL schedules that conflict with active Cloud schedules (queued)

**Status:** queued — **Filed:** 2026-09-30 (owner). **Do not start.** Cross-links:
[[FEAT-CLOUD-STORM-HEDGE]], [[FEAT-CLOUD-TOU-SCHEDULE]], [[vpp-not-in-local-run_status]].

**Purpose:** surface when a **LOCAL** schedule (this bridge's Scheduler) directly conflicts with or
overlaps a **CLOUD-owned** schedule that is currently active — so the user isn't fighting the cloud.

**What counts as an active cloud schedule (time-specific, NOT date):**
- **Emergency Backup** mode active — the battery is held; local dispatch/discharge schedules conflict.
- **Time-of-Use** mode active — the cloud TOU windows drive charge/discharge; local force windows overlap.
- **Storm Hedge** ON — cloud pre-charges ahead of weather; local discharge/export schedules conflict.
  (Check the **Cloud API docs** for the Storm-Hedge read — `franklinwh-cloud` storm methods; is it a
  mode/flag + windows? Detect "on" + its active window.)
- **Reports NOTHING** when the operating mode is **Self-Consumption** and Storm Hedge is off — no cloud
  schedule is steering the battery then, so there's nothing to conflict with.

**Detect:** for each enabled local schedule window, check overlap (by TIME-OF-DAY, not date) against the
active cloud schedule's windows/mode. "Direct conflict" = opposing battery action in the same window
(e.g. local force-charge vs cloud Emergency-Backup-hold, or local discharge vs cloud TOU-charge window);
"overlap" = same window, same direction (benign, note only).

**Surface (owner: any/all of these):**
- **Notification** to the user's enabled HA notify devices when a conflict is detected.
- **UI**: clear indicator with details — on the **Scheduler Timeline** (overlay the cloud windows +
  flag conflicts) and/or a **modal** listing conflicts.
- **App log** line (now durable in the DB) for the audit trail.

**Data sources:** operating mode (1301/1727 + cloud), reserves (`cloud_reserves`), cloud TOU schedule
(`franklinwh-cloud` TOU read), Storm-Hedge read (cloud). Cloud-gated: only runs when cloud creds are
valid; degrades to "unknown" (not a false "no conflict") when the cloud is unreachable.

## FEAT-CLOUD-TOU-EDITOR — TOU schedule viewer + editor (FWHAI-style), cloud-gated (queued)

**Status:** queued — **Filed:** 2026-09-30 (owner). **Do not start.** **May be STAGED** to manage
complexity (view -> presets -> full edit/submit). Supersedes/absorbs the view-only slice of
[[FEAT-CLOUD-TOU-SCHEDULE]]; relates to [[FEAT-CLOUD-TOU-IMPORT]] and [[FEAT-BILLING-WHOLESALE]].

**Ask:** a **Time-of-Use schedule viewer AND editor**, cloned in summary from **FWHAI's TOU UI**
(edit + submit, and/or **load presets**) — **exposed only when Cloud credentials are present and the
connection is valid** (TOU write is cloud-owned). Surfaces:
- **In the Time-of-Use switch** (mode card / Control): a **button** to view/edit the TOU schedule.
- **A main-dashboard card** for **Time-of-Use Schedules** — clearly marked **Cloud-only**, and only
  meaningful when **TOU mode is active** (otherwise it does nothing / shows "TOU not active").

**Scope:** summary clone of FWHAI's TOU schedule **view / edit / submission** if feasible — read the
current cloud TOU windows/prices, edit them (or apply a preset), submit via the cloud (`set_tou_*` /
the TOU schedule write in `franklinwh-cloud`), with gap-fill + validation (the cloud lib already has
TOU read/write/verify with gap-fill). Read-only view first, editor + presets next, full submit last.

**Gating & safety:** hidden entirely without valid cloud creds; a clear "Cloud-only · TOU active"
badge; confirm-on-submit (writes the real TOU schedule). Ties to the reserve/mode cloud-gating already
in the app (`caps.cloud_*`).

### FWHAI TOU editor — reference layout (from owner screenshot 2026-09-30)
Model the editor on FWHAI's **Schedule Editor** ("Manage TOU time blocks, strategies, and presets"):
- **Header actions:** Refresh · **Pricing** ($ per-tier prices) · **Save to Gateway** (the submit) · Usage Type.
- **Preset bar:** shows the loaded preset (e.g. `Custom (Multi-Period)`) + a dirty indicator ("No changes
  since preset was loaded"). **Load Preset / Save Preset** at the bottom.
- **Season context:** editing a **season** (e.g. "Shoulder season · Active now · 5 blocks", months
  `Apr, May, Sep, Oct`) with **Manage seasons**. TOU is season- AND day-type-scoped (see Table View).
- **Quick Add Block:** Start · End · Name · **Dispatch** (dropdown) · Add.
- **Visual 24h timeline:** coloured bands per dispatch — legend: **Home Loads · Standby · Solar Charging ·
  Self Consumption · Grid Export · Grid Charge** — with a "now" marker + **Energy Forecast Preview / Live
  Simulation**.
- **Block table:** columns **START · END · NAME · DISPATCH** (per-block dropdown: Home Loads—Export Solar
  to Grid / Solar Charging—Charge from Solar / Self Consumption—Use your own energy first / Grid Export—
  Sell stored energy / Grid Charge—Buy energy to store) · **WAVE** (rate tier: Super Off-Peak / Off-Peak /
  On-Peak) · **PRICE** (buy + sell, e.g. `$0.54 / $0.03 sell`) · delete.
- **Bottom actions:** Add Time Block · Show Prices · **History** · **Optimise** · **Validate** · Save/Load
  Preset · Advanced · **Table View** (all seasons & day-types).

**Cloud API surface (verified in `franklinwh-cloud/franklinwh_cloud/mixins/tou.py` + docs
`TOU_SCHEDULE_GUIDE` / `TOU_TARIFF_REFERENCE`):**
- **Availability check FIRST:** `get_entrance_info()` — not all sites have TOU configured; guard before any TOU call.
- **Reads:** `get_gateway_tou_list()`, `get_tou_info(option)`, `get_tou_dispatch_detail()` (current blocks +
  waveType + prices). `_build_block_info` shows the block shape (dispatch + `waveType` + `eleticRate*`).
- **Writes:** `set_tou_schedule(...)` (targets the season owning today, or a `month=`),
  `set_tou_schedule_multi(strategy_list)` (multi-season / full restore), `save_tou_dispatch(payload)`.
  `reset_tou_mode(...)` to clear. Dispatch codes: **GRID_CHARGE=8, GRID_EXPORT=7** (+ self/solar/home).
- **Presets/backups:** `backup_tou_schedule()`, `tou_backup_save/restore/list/delete` — this is the
  "Load/Save Preset" workflow.
- **Two setup paths (docs):** Template-Based (mirrors the mobile-app wizard) and Direct Dispatch (what
  `franklinwh-cli tou --set` uses). `waveType` = rate tier; `eleticRate*`/`eleticSell*` = per-tier buy/sell.
- The cloud lib already does TOU read/write/verify with gap-fill + validation — port the shape. The dispatch enum + wave/rate tiers + season/day-type
model align with our `rate_model` ([[FEAT-BILLING-WHOLESALE]] / [[FEAT-UTILITY-BILLING]]). **Staging:**
(1) read-only view (timeline + table) · (2) Load Preset + Validate · (3) block edit + Quick Add ·
(4) Optimise + Save to Gateway (the real cloud write, confirm-gated).

## FEAT-CLOUD-STORM-HEDGE — Storm Hedge tab + Scheduler hooks, cloud-gated w/ status icon (queued)

**Status:** queued — **Filed:** 2026-09-18 (user, Storm Hedge modal screenshot)

**Storm Hedge = FranklinWH's automatic outage protection** (pre-charge the battery ahead
of a forecast storm). It is **cloud-only** (weather + settings live in the cloud REST API,
not the local sendMqtt channel), so everything here is gated on valid cloud credentials.

### 1. Cloud-gating + status icon (applies to ALL cloud functions)
- When cloud credentials are **present AND a live cloud connection validates**, enable the
  cloud-only features (Storm Hedge sidebar tab, reserve-SoC writes, force charge/discharge
  if/when added, etc.). Otherwise keep them hidden/disabled.
- Every cloud-backed function shows a **cloud icon**: **green = cloud connected/available**,
  **red = unavailable/invalid**. One shared indicator (topbar + per-feature), driven by a
  periodic cloud health check. Reuse the existing `_require_cloud()` gate + the Settings
  cloud-credentials Test button as the source of truth.

### 2. Storm Hedge sidebar tab (mirrors the app modal)
- **System protection** on/off; **advance backup time** slider (hours — the modal shows
  1h…5.5h, default 2h); **decision strategy** Auto-Active vs Ask-Each-Time; current +
  progressing storms and brief weather; Apply Settings.
- Cloud API (from `franklinwh-cloud` `mixins/storm.py`, base `hes-gateway/terminal/weather/`):
  - `getStormSetting` → current settings (enabled, advance time, notice, strategy).
  - `switchStorm` {equipNo, stormEn} → enable/disable protection.
  - advance-backup-time setter (`set_storm_settings(setAdvanceBackupTime/advanceTime)`).
  - `getCurrentBriefWeather`, `getStormList`, `getProgressingStormList` → weather + active
    storm state for the UI + Scheduler sensors.
  - NB: mode writes also carry `stormEn`/`stromEn` (see cloud `client.py`/`modes.py`) — keep
    consistent so a mode change doesn't silently clear storm protection.

### 3. Scheduler integration
- **As condition sensors** (usable in gate expressions + templates, via `scheduler.py`
  `ha_sensor_options()`/`substitute()`): `storm.protection_enabled` (0/1),
  `storm.active` (a progressing storm now), `storm.advance_hours`, `storm.next_eta`.
- **As actions** (execute changes): enable/disable Storm Hedge, set advance-backup hours,
  set strategy — each a cloud write, so behind the cloud gate + UNAVAILABLE when offline
  (same honesty pattern as force-charge).

### Constraints
- Cloud-only — no local fallback; when the cloud is down the tab + sensors + actions show
  the red icon and read UNAVAILABLE (never fabricate weather/storm state).
- All cloud writes stay behind `allow_writes` + `_require_cloud()`.

### Ties
- `FEAT-SCHEDULER-FULL-PARITY` (Scheduler shell), existing cloud-compat + Settings cloud
  credentials + `_require_cloud()`.

---

## FEAT-CLOUD-TOU-SCHEDULE — view Cloud TOU schedule/prices; import as Scheduler basis (queued)

**Status:** queued — **Filed:** 2026-09-18 (user) — cloud-only; ties to the cloud gate +
status icon in `FEAT-CLOUD-STORM-HEDGE`.

Surface the site's **TOU (Time-of-Use) schedule** — and tariff periods — from the Cloud
API, read-only first; later **import the schedule/periods as a basis for Scheduler rules**.

### Phase A — view (read-only)
- Cloud API (`franklinwh-cloud` `mixins/tou.py`, base `hes-gateway/terminal/tou/`):
  - `getGatewayTouListV2` (showType=1) → the TOU program: dispatch blocks with
    `dispatchId` (HOME/STANDBY/SOLAR/SELF/GRID_EXPORT/GRID_CHARGE) + `waveType`
    (0=OffPeak,1=MidPeak,2=OnPeak,4=SuperOffPeak) + per-block gridChargeMax/DischargeMax
    (W), maxChargeSoc, minDischargeSoc, rampTime, windows; also supported modes + SoC cfg.
  - `getTouDispatchDetail` → per-block detail; `get_charge_power_details` → charge caps.
- A **TOU Schedule tab/card**: a 24h/weekly band of the tariff **periods** (Off/Mid/On/
  Super-Off peak) + the dispatch blocks (charge/discharge windows, SoC caps). Cloud-gated
  (green/red cloud icon); shows UNAVAILABLE when the cloud is down — never fabricates.
- **Full editor parity** with the Modbus Bridge's TOU editor (screenshots): a per-block
  table **START · END · NAME · DISPATCH (Standby/Self-Consumption/Grid-Export/Grid-Charge/
  Solar-Charging/Home-Loads) · WAVE (Off/Super-Off/Mid/On-Peak) · PRICE (buy/sell $)** with
  **Add Time Block**, **Show Prices**, **History**, **Optimise**, **Validate**, **Save/Load
  Preset**, **Advanced**; plus **Energy Forecast Preview / Live Simulation**, a **Table View
  — all seasons & day-types**, **Full Schedule — All Seasons**, and **Copy TSV**. Writing it
  back is `saveTouDispatch` (destructive full overwrite) — confirm-gated (Phase B).

### Prices — the Cloud API DOES carry them (corrected 2026-09-18)
Ref: https://david2069.github.io/franklinwh-cloud/TOU_TARIFF_REFERENCE/ — each
`dayTypeVoList` entry carries per-tier **buy** and **sell** rate fields (in $/kWh), mapped
to `waveType`:
- **Buy (grid import cost):** `eleticRateValley`=0 Off-Peak, `eleticRateShoulder`=1 Mid-Peak,
  `eleticRatePeak`=2 On-Peak, `eleticRateSuperOffPeak`=4 Super-Off-Peak, `eleticRateSharp`
  (Sharp), `eleticRateGridFee` (fixed grid/demand charge, all tiers).
- **Sell (grid export credit):** `eleticSellValley`/`eleticSellShoulder`/`eleticSellPeak`/
  `eleticSellSuperOffPeak` (same waveType map).
- So the TOU view shows **real per-block $ buy/sell prices** from the cloud (see the Modbus
  Bridge's PRICE column: e.g. $0.22 buy / $0.03 sell off-peak, $0.28 sell mid-peak).
- The doc also has the **dispatch code reference** (touDispatchList), tariff types, day-type
  codes, and season structure — use `RATE_FIELD_MAP` from the docs for the programmatic
  mapping. (Local 1301 `sharp/peak/flat/valley` tiers remain only a "which period now"
  projection — keep the cloud rates as the price source.)

### Phase B — import into the Scheduler (future)
- Import the cloud TOU schedule so Scheduler rules can key off it:
  - **Condition sensors**: `tou.period` (offpeak/mid/onpeak/superoff), `tou.dispatch`
    (current dispatchId), `tou.grid_export_window` (bool), etc. — via
    `scheduler.ha_sensor_options()`/`substitute()`.
  - **Rule basis / presets**: generate schedule entries from the imported TOU windows
    (e.g. "discharge during OnPeak", "charge during SuperOffPeak") — the honest local
    version of `FEAT-SCHEDULER-TEMPLATES`, using set_mode/smart-circuit where force-* is
    unavailable locally.
- Writing TOU back (`saveTouDispatch`) is **destructive (full overwrite)** — treat as a
  separate, carefully-gated action; not part of view/import.

### Constraints
- Cloud-only, behind the cloud gate; `getGatewayTouListV2` has NO tier/$ fields — don't
  invent prices. Any TOU write is `allow_writes` + `_require_cloud()` + a confirm (it
  overwrites the whole program).

---

## FEAT-MODBUS-FORCE-CONTROL — force charge/discharge/standby + release via Modbus TCP (queued)

**Status:** queued (FUTURE) — **Filed:** 2026-09-18 (user) — the second, non-cloud route to
force control (the local sendMqtt channel has NO force path; the cloud route is
FWHAI/TOU-manipulation). This adds a **direct Modbus/SunSpec TCP** path, mirroring the
FranklinWH **Modbus Bridge**.

### What
Give the local bridge the ability to **force charge / force discharge / force standby** and
**release** back to native TOU, by talking **Modbus TCP (SunSpec) to the aGate on port
502** — the same lever the Modbus Bridge uses. This finally makes the Scheduler's force-*
actions (currently UNAVAILABLE locally) real, without needing the cloud.

### How (from the Modbus Bridge + SunSpec)
- **SunSpec model 704** (DER active-power control) is the lever — active-power **setpoint
  `WSet`** (± % of WMax or W) with enable + a revert timer:
  - `m704.WSet` = the dispatch power (Modbus Bridge: gateway/instance.py, scheduler.py).
  - `WSetEna` / `WSetRvrtTms` / `WSetEnaRvrt` — enable + auto-revert (instance.py:361-362).
- **Semantics** (Modbus Bridge `gateway/scheduler.py`):
  - **force_charge** = negative WSet setpoint; **force_discharge** = positive setpoint;
    **force_standby** = 0 W VPP hold; **release** = disable the setpoint → hands back to
    native TOU. VPP override needs **no mode switch** — dispatch is the normal command path;
    the lever is the release/gap behaviour on window exit (`release` vs `hold` a 0 W standby).
  - "sustained" actions (force_charge/discharge/standby) get an auto-release on window exit.
- Needs a **Modbus/SunSpec client** in/beside the bridge (pymodbus / pysunspec2) + the
  aGate's 704 register map. The bridge already knows the gateway host; add a per-gateway
  Modbus port (502) alongside the sendMqtt 9000. Cross-ref the Modbus Bridge repo
  (`~/dev/Claude/Projects/franklinwh-modbus-bridge`) and its Modbus/SunSpec API docs for
  the exact register offsets, scaling, and the release/standby sequence
  (`sequences/release_control.json`).

### Wire-up
- Flip `scheduler.py` UNAVAILABLE force_charge/discharge/standby → available **when a
  Modbus link to that gateway is present** (else keep UNAVAILABLE with the reason).
- New actions honoured by the Scheduler + a manual control (topbar/Control tab): Force
  Charge/Discharge/Standby (with power %/W) and Release.
- Health/status: show whether the Modbus (502) link is up per gateway (the roster already
  has a modbus_502 probe field).

### Constraints / cautions
- **Modbus writes are direct hardware control** — behind `allow_writes`, confirm, and an
  auto-revert timer so a crashed bridge can't hold the battery forced indefinitely
  (`WSetRvrtTms`).
- Verify against real hardware before shipping — SunSpec register maps/scaling vary by
  firmware; treat the Modbus Bridge's map as the reference, not gospel.
- Independent of the cloud force route — this is the LAN/Modbus alternative.

### Ties
- `FEAT-SCHEDULER-FULL-PARITY` (force-* actions + VPP timeline lane become real once this
  lands), `ANALYSIS-LOCAL-ONLY` (why sendMqtt can't do it).

---

## DEF-BROWSER-MEMORY — Safari reloads the tab after long sessions ("significant memory")

**Status:** open (defect) — **Filed:** 2026-09-18 (user, seen 3×, incl. across a full day)

Safari periodically reloads the dashboard tab with "This webpage was reloaded because it
was using significant memory." after the tab has been open a long time (hours→days). The
reload also drops any unsaved in-browser state (Trend samples) and — until fixed — the
gateway selection (now persisted).

### What I checked (NOT the cause)
- Chart.js instances DO dispose: `app.js renderChart` and `battery_tab.js draw/drawLive/
  drawPerCellStack/_renderTrend` all `destroy()` before `new Chart()`.
- History series + in-browser sample rings are bounded (`loadHistory` replaces; battery
  `samplesByUnit` capped at `maxSamples=720`/unit).
- So there is no obvious single leak from static reading — needs a real heap profile.

### Real suspects (to verify with Safari/Chrome heap snapshots over a long run)
1. **Chart churn**: the Battery Trend + per-cell stack `destroy()`+`new Chart()` EVERY poll
   (2 s). For 4 aPowers that's ~2 chart create/destroys per second → heavy GC/canvas-buffer
   churn over hours. Fix: update charts **in place** (like `drawLive`) instead of recreate.
2. **Hidden-tab charts retained**: leaving the Battery tab keeps its Trend/stack/live Chart
   instances (retina canvases) allocated. Fix: destroy battery charts on tab-switch-away,
   rebuild on return.
3. Retina canvas backing stores accumulating; Alpine listener/DOM accumulation on the
   long-lived dashboard; the Sankey SVG re-render (`host.innerHTML=''`) churn.

### Applied 2026-09-30 (background-tab pause)
- **Pause on tab background (visibilitychange):** a hidden tab kept the 10s poll, 90s history,
  15s battery + gateway intervals AND the Power History chart running — exactly Safari's
  "background tab using significant memory" trigger. Now on `document.hidden`: pause the poll,
  destroy the Power History canvas, and skip history/battery/gateway interval work; on return:
  resume + refresh (respecting the idle-cap). Hidden-tab churn ≈ zero. **Still open** for the
  definitive leak — that wants a real heap-snapshot diff over a long run.

### Applied 2026-09-28 (safe churn reduction)
- **Battery Trend + per-cell stack now update IN PLACE** (was `destroy()`+`new Chart()` EVERY
  ~2 s poll — the heaviest churn). Mirrors the proven `drawLive()`; recreates only on a real
  structure change (metric/mode/unit). ~2 chart create/destroys per second eliminated.
- **Dispose battery charts on tab-switch-away** (`_disposeCharts`), rebuild on return — frees
  retained retina canvas buffers while the tab is not shown (suspect #2, for the battery tab).
- **NOT touched: the dashboard `renderChart` (Power History).** Its own comment documents that
  in-place reassignment CRASHED that dual-axis chart before ("fullSize/y undefined, stack
  overflow"; reassigning options → hover crash). Left as destroy+recreate (60 s) deliberately —
  do not repeat that mistake without on-device testing.

### Plan
- Profile: leave the dashboard + battery tabs open, take heap snapshots ~1h apart, diff.
- Then apply the fix the profile points to (likely #1 in-place chart updates + #2 dispose
  on tab-hide). Consider hard caps on total in-browser samples and a lighter idle poll.
- Cheap interim: the gateway selection now survives the reload (done).

---

## FEAT-REALTIME-WATCH — live streaming chart you watch as it fills (v1 DONE)

**Status:** **v1 DONE 2026-09-16** (Battery tab, full-screen modal) — **Filed:**
2026-09-16 (user, Battery-tab screenshot: "is it possible [to] have a realtime chart
option like the one for recording bms data? then u watch real time")

### v1 built — "Watch live" modal (user picked modal overlay)
- Battery-tab header **Watch live** button (red pulse dot while open).
- Full-screen modal (`#bmsLiveChart`) streaming **spread / SoC / max-cell-temp** on a
  rolling window (`liveWindow=120`, ~10 min at 5 s), updated **in place** each poll.
- Live readouts row (SoC / Spread / Max temp / Current / sample count) + interval
  picker + Clear + **Export CSV** (shares the Trend's `samples` ring) + Close/Escape.
- Drives its **own** poll timer only when Auto isn't already running (no double-read of
  the slow device); tears down chart + timer on close, tab-switch and tab-hide.
- If a bridge-side recording is active, a **● Recording · N saved** chip shows in the
  modal header — the honest tie to `FEAT-BMS-SESSIONS`.
- Honest caveat in the footer: realtime **to the poll** — the gateway is the clock.
- Verified headless (webkit): open → chart+timer created, samples accrue at poll
  cadence, canvas visible; close → chart+timer destroyed; zero page errors.

### Still open (v2 ideas from the original sketch)
- **Live-view an in-progress persisted recording** (stream the `Recorder` session, not
  just the in-browser ring) — needs `/record/status` to return a sample tail.
- **SSE/WebSocket push** so multiple viewers share one stream (v1 is per-browser poll).
- **Generalise beyond BMS** — a metric picker for grid/inverter volts, DC bus, currents.

**Short answer: yes, feasible.** Two live-ish pieces already exist and this ties them
together into a proper "watch it live" mode.

### What exists today
- **In-page Trend** (`battery_tab.js`, memory-only): with **Auto** on it re-`load()`s on
  the poll interval and pushes `{t, soc, spread, vmin, vmax, tmax, current}`, caps at
  `maxSamples`, draws spread/SoC/tmax, Export CSV / Clear. This is the chart in the shot.
  Limits: **per-browser** (dies with the tab, not shared, not persisted), **BMS-only**
  series, and it reacts **no faster than the poll** (same tick as everything else).
- **Persisted recording** (`bms_record.py` `Recorder`): runs **on the bridge**, survives
  the browser, `MIN_INTERVAL_S=5`, `MAX_SAMPLES=500` — but is charted **only afterwards**
  from the saved session, not live.

### The gap the user is asking for
Watch a **server-side recording** update **live** on a chart, instead of only opening it
after it finishes — and ideally not just BMS spread/SoC/temp but the other live numbers
too (grid/inverter L1/L2, DC-bus rails, load/inverter/buck-boost currents, run/inverter/
DCDC states — everything already on screen in "Inverter & Power Electronics").

### Sketch (smallest → largest)
1. **Live view of a recording in progress** — while `Recorder` runs, poll
   `/api/battery/record/status` (already exists) for the latest samples and append to the
   chart as they land. Small change: have status return the tail of samples since a
   cursor, and let the Charts sub-tab render the *active* session live. Gets "watch it
   fill" with what's already built. Still poll-cadence.
2. **Push instead of poll (SSE/WebSocket)** — the bridge already reads the gateway on a
   loop; broadcast each fresh reading over Server-Sent Events. Every open tab shares one
   stream, no per-browser timers, and a phone that sleeps just reconnects. Still bounded
   by the gateway poll — **cannot** stream faster than the bridge reads (same honest
   caveat as the Scheduler banner).
3. **Generalise the trend to any metric** — a metric picker (BMS spread/SoC/temp **or**
   grid/inverter volts, DC bus, currents) over the same live series, so the "realtime
   watch" isn't BMS-only.

### Constraints to keep honest
- **No faster than the poll.** The gateway is the clock; a "realtime" chart is
  realtime-to-the-poll, not sub-second. Say so in the UI (reuse the Scheduler wording).
- **Thermal/balancing/MOS-fan-heater stay absent locally** — they are cloud-only (the
  footnote already on the Battery tab); a live BMS watch shows the same fields the local
  channel actually has.
- **Persistence is opt-in.** The memory trend should stay memory-only + Export CSV; the
  persisted path is the `Recorder`. Don't silently write every poll to SQLite.

### Recommendation
Start at **(1)** — live-view an in-progress recording — it reuses `Recorder` + the
existing session charts and delivers "watch it in real time" with the least new surface.
Promote to **(2)** SSE only if multiple simultaneous viewers or phone-sleep reconnects
become a real annoyance.

---

## FEAT-APOWER-UNIT-INFO — per-aPower firmware dialog, like FWHAI's

**Status:** queued — **Filed:** 2026-09-14 (user, FWHAI screenshot)

FWHAI has an **aPower Unit Information** dialog: serial, a decoded status
("Normal Active"), then a FIRMWARE / SOFTWARE table — BMS Version, DCDC Version,
Inverter Ver., FPGA Version, Bootloader, Thermal Board.

The bridge has all of this (`/api/firmware/all` gives per-battery firmware from 1833; the
1101 manifest carries the FPGA/DCDC/INV/BL/TH arrays, one entry per aPower), but it is not
presented as a per-unit view.

**Done already (2026-09-14):** the raw tags now have labels — `FPGA_VER` → "FPGA",
`DCDC_VER` → "DC-DC converter", `TH_VER` → "Thermal board", `BL_VER` → "Bootloader" and so
on — so the Device firmware view is no longer a wall of four-letter codes. `SL_VER` is
labelled "(undecoded)" rather than given an invented meaning.

**Done 2026-09-14:** Health is now the firmware **detail** view and the Device tab is
deliberately left alone. Health loads `/api/firmware/all` on demand and shows 13 gateway
firmware rows, 4 serials and a **per-aPower section** — each with a plain-word label and
the raw tag beside it, so a value can still be traced back to the protocol field.

**Still wanted**
- The dialog *presentation* FWHAI uses, opened from the Battery page — Health now has the
  data, but someone looking at a battery still has to leave the page to see its firmware.
- Decoded unit **status** beside the serial, as FWHAI does. `bmsState`/`peState` now decode
  ("Discharging", "Online / Running"), so the pieces exist.
- Reached from the Battery page, since that is where someone is already looking at the unit.

**Related:** a user asked whether Health or Device is the "detailed" firmware page. Health
had the friendlier labels while Device had the complete data — the labels above close that
gap, but the two surfaces should still be reviewed together so one is clearly the detail
view and the other clearly a summary.

---

## FEAT-SCHEDULER — schedule engine with HA actions (v1 DONE)

**Status:** v1 DONE 2026-09-15 (user) — modelled on the Modbus Bridge's
Schedule & Automations page.

**The honest difference, recorded up front:** the Modbus Bridge can **force charge,
force discharge and force standby**. This bridge **cannot** — those are SunSpec/Modbus
controls with no local-protocol equivalent. They are listed in the UI as *unavailable
with the reason* rather than hidden, because someone arriving from the Modbus Bridge will
look for them.

### What the local channel can actually do (all hardware-verified)
`set_mode` (1727) · `smart_circuit` on/off (1409, read-back confirmed) · `offgrid` (1723)
· `notify` via a configured notification device. `reserve_soc` is offered but reports that
**no local write path exists** — see `RESEARCH-RESERVE-SOC`; it needs a cloud provider.

### Built
- `scheduler.py` — conditions, windows, variable substitution, action runner.
- `schedules` table; CRUD at `/api/schedules`.
- **`POST /api/schedules/{id}/test`** — evaluates against live values **without firing**,
  returning each row's *actual* value. This is the "Test verification" from the Modbus UI.
- **`POST /api/schedules/{id}/run`** — runs the actions now, ignoring the window, behind
  the write gate and a confirm.
- Runs on the **poll tick**, so a schedule reacts no faster than the bridge reads the
  gateway — stated in the UI rather than left to be discovered.

### Decisions worth keeping
- **A missing sensor counts as FALSE, never true.** An absent reading must not be able to
  fire an action.
- **Windows crossing midnight** are handled — 22:00 for 300 min is inside at 01:00, which
  a naive `start <= now < end` gets wrong.
- **`%sensor.id%` variables** render an unreadable value as `?` rather than blocking the
  message: a notification missing one field beats one that never arrives.
- **Failures are captured, not raised** — one bad action records why and the rest of the
  run continues; `last_result` is shown on the card so a schedule that did nothing says so.
- `set_smart_circuit` reports **"confirmed" vs "NOT confirmed"** from the read-back, never
  treating `result:0` as success.

### Not done
- Exit conditions (first-true ends the window), recurring/one-time trigger types beyond
  daily, priority and if-already-controlled arbitration between entries — all in
  `SCHEDULE-AND-AUTOMATIONS`.
- HA **entity** actions (service calls on an `entity_id`); only notify is wired.

---

## FEAT-HA-MULTI-INSTANCE — match the Modbus Bridge / Energipays HA integration

**Status:** parts 2 and 3 **DONE 2026-09-15**; part 1 (token flow) still open —
**Filed:** 2026-09-14 (user)

### Done
- **Multiple HA instances.** `ha_instances` table (id, name, base_url, token, is_default,
  enabled) with CRUD at `/api/ha/instances`, replacing the single `HA_URL`/`HA_TOKEN` pair
  that could only ever describe one. **Tokens are never returned to a client** — the API
  reports `has_token` only, and a blank token on edit keeps the stored one. A test asserts
  the secret cannot appear in a response.
- **`/api/ha/test`** probes a connection and *returns* the outcome rather than raising, so
  a wrong URL and a rejected token read differently. When editing, it falls back to the
  stored token instead of testing unauthenticated and reporting a bogus 401.
- **Notification devices** (2026-09-15, modelled on the Energipays UI) — named targets
  (`alias` + instance + `notify.*` service) in a `notify_devices` table, each with its own
  **on/off that does not require deleting**: pausing a device for a week must not cost its
  configuration. Plus a **master switch** (`ha_notify`), reported alongside the per-device
  state so neither masquerades as the other — a device can read "On" while notifications
  as a whole are off.
- **Discover and Test** — the add/edit dialog lists the services on the chosen instance,
  and sends a test **before saving**, which is when you want to know: a service name that
  does not exist fails silently later, when you are relying on the alert. Testing an
  unsaved device works by passing instance + service instead of an id.
- **`/api/ha/notify-targets`** enumerates `notify.*` services per instance. These are
  **services, not entities**, so they never appear in an entity list — which is why a
  notification setting that only says "on" cannot tell you where anything went.
- **HA tab** with four views: Instances (add/edit/remove/test), Browse entities
  (filter by instance/domain/search), Notify targets, and **Published by bridge** — the
  last kept separate on purpose, because "what we send to HA" and "what we read from HA"
  are the two directions people conflate.
- One unreachable instance reports its error **alongside** the others' results rather than
  failing the whole call.

### Still open
- **Part 1 — copy the Modbus Bridge's token flow.** Today a token is pasted in. The Modbus
  Bridge has a fuller flow worth reusing, including the co-hosted-addon case where the
  Supervisor token is used instead of a long-lived one (`token = NULL` in its schema).
- Nothing yet *consumes* HA entities: the Modbus Bridge exposes them as
  `ha:<instance>:<entity>` automation-condition sensors, which needs
  `SCHEDULE-AND-AUTOMATIONS` here first.

**Filed:** 2026-09-14 (user)

Three things the Modbus Bridge does that this bridge does not. (The active code is
`~/dev/Claude/Projects/franklinwh-modbus-bridge`, co-hosted with Energipays —
**not** the dormant `franklinwh-energy-manager`.)

### 1. Copy the HA token flow from the Modbus Bridge
The Modbus Bridge already solves obtaining and storing a Home Assistant long-lived token.
Reuse that flow rather than inventing one — same UX, same storage discipline, same
redaction on display.

### 2. Multiple HA instances
Today `HA_URL` / `HA_TOKEN` are single-valued. The user asked for multiple **deliberately**:
one bridge feeding more than one Home Assistant (e.g. a main instance and a secondary or
test one). Wanted: a list of instances, each with its own URL, token and enabled flag, with
notifications and discovery published to each.

### 3. Notification devices — scan for eligible targets
Energipays scans the HA instance for devices that can receive notifications
(`notify.*` services: companion apps, phones, speakers) and lets you pick which ones to
use. Today this bridge has `HA_NOTIFY` as a single on/off with no idea what it is notifying.

Wanted: enumerate `notify.*` services per instance, present them as a pick-list, and send
only to the selected targets.

**Why it matters here:** the bridge already has the notification paths
(`notify.py`, `ha_supervisor.py`, `/api/notify/test`) but no way to choose a destination,
so a user cannot tell where a test notification went — or whether it went anywhere.

**Look at first:** `~/dev/Claude/Projects/franklinwh-modbus-bridge` — it already has all
three: `api/ha_api.py` ("Multi-HA REST — manage Home Assistant instances the Bridge reads
entities from") with token redaction on display, and `api/schedules_api.py` whose schedule
actions target HA directly. `notify.py` and `ha_options.py` here are where instances would
plug in.

**Its schedule actions are the model to copy** — two kinds:
- `entity` — a service call on an `entity_id` (turn_on, select_option …), rejected at
  validation time if the entity is missing rather than being silently skipped by the engine;
- `notify` — a one-way message through an HA `notify.*` service, with `{sensor.id}`
  placeholders substituted from the live snapshot when it fires.

Each action names an `instance_id`, so a single schedule can drive more than one Home
Assistant, and an optional `guard` leaf (`{sensor, op, value}`) makes it conditional.

---

## DEF-CLOUD-CREDS-OPAQUE — cloud credentials are invisible in the UI

**Status:** RESOLVED — Settings now has a **Cloud API** section (Email / Password / Gateway,
x-model=fwh_cloud*), so the three creds are surfaced + editable. **Filed:** 2026-09-14 (user)

Three settings exist in `config.py` and **appear nowhere in the UI**:
`FWH_CLOUD_EMAIL`, `FWH_CLOUD_PASSWORD`, `FWH_CLOUD_GATEWAY`. They are environment-only,
and the Settings tab does not mention them.

**What they change:** they enable the cloud provider, which is what makes the Reserve SoC
control on the Control tab writable — the card's "cloud provider" chip is the only hint
anywhere that they exist. Without them the reserve fields are read-only, and nothing tells
you why.

**Wanted**
- A Settings section showing whether cloud credentials are configured, which account, and
  which gateway — never echoing the password back.
- The Reserve SoC card should say *why* it is read-only when they are absent, and where to
  set them.
- `/api/providers` already reports resolution; surface it.

---

## FEAT-RESERVE-SOC-NATIVE — offer the native (local) reserve path as an option

**Status:** blocked on a working local write — **Filed:** 2026-09-14 (user)

Reserve SoC is written through the cloud today. The user wants a **native** option
alongside it, accepting that the local write does not work yet.

**Current position:** no local write path is known. Reserve values read correctly from
`1726`, but writing was tried across `1405`, `1725`, `1727` and `1403` — including
cloud-shaped list entries, bounds-first sequences and the active mode — and none applied.
The cloud sets it via REST (`tou/updateSocV2`), so there is no cmdType to call. Details in
`RESEARCH-RESERVE-SOC`.

**Shape when it becomes possible:** a provider choice on the Reserve SoC card —
`cloud` (works now) or `native` (local) — defaulting to cloud, with native shown as
unavailable and the reason given rather than hidden. `HYBRID-CAPABILITIES` already models
provider selection, so this is that pattern applied to reserve.

**Unblocks if** a firmware update changes the behaviour, or a capture from the official app
shows a cmdType nobody has found. Worth re-testing `1405`/`1725` after any gateway
firmware update.

---

## FEAT-DER-COMMS-UI — expose the SunSpec / IEEE 2030.5 toggles in the bridge

**Status:** queued — **Filed:** 2026-09-14 (user)

Command `1205` carries two installer settings: **SunSpec Modbus** (field `sunsMdEn`),
which decides whether the gateway accepts Modbus connections on TCP port 502, and
**IEEE 2030.5 / CSIP** (field `enable`). The bridge already reads both — they appear in
`/api/summary` as `der_comms {sunsMdEn, sep2}` — and `client.set_der_comms` exists and is
catalogued as a proven write. **There is no UI.**

This is the single most consequential local-only capability
(`ANALYSIS-LOCAL-ONLY`): no cloud equivalent exists, and Modbus cannot serve the switch
that enables Modbus. Turning SunSpec off from here would **disable the Modbus bridge's
entire control plane** — which is exactly why it needs more than a toggle.

### Requirements that are not optional
- **The change is not immediate, so do not judge it by one read.** On this firmware,
  switching SunSpec on or off makes the gateway open or close TCP port 502 a few seconds
  later, without needing a reboot. On older firmware, switching off took effect at once
  but switching on did nothing until the gateway was rebooted. The UI must therefore keep
  checking port 502 for several seconds before reporting success — a single read-back
  taken straight after the write will show the old state and look like a failure.
- **Say what will break, in the confirmation dialog itself.** Turning SunSpec off stops
  the Modbus bridge working entirely. Turning IEEE 2030.5 on hands dispatch control to a
  DERMS. Neither belongs in a tooltip.
- **Show whether the gateway is actually accepting Modbus connections**, not just the
  value of the setting. Trying to connect to port 502 is the honest test, and it is what
  separates "the setting was written" from "the setting took effect".
- Require `ALLOW_WRITES`, and treat this as an installer-level control rather than a
  day-to-day switch.

**Suggested home:** the Device tab (installer surface) or a new Settings section — *not*
Control, which is day-to-day operation.

---

## FEAT-EVENT-LOG — gateway event log viewer (BLOCKED: nothing to display yet)

**Status:** blocked — **Filed:** 2026-09-14 (user: *"do we have something that displays
the event log?"*)

**No, and there is currently nothing to display.** `1829 event_block` is readable through
the Device tab, but on this gateway it returns exactly:

```json
{"opt": 0, "result": 0, "reason": 0, "num": 0}
```

`num` is the stored-event count and it is **0** — a healthy site with no events. The
`data`/`level`/`startTime` fields the catalog mentions never appear.

**The fetch shape is unknown.** Six request shapes were probed 2026-09-14 — plain,
`num:1`, `num:10`, `index:0`, `id:0`, and no dataArea at all — and every one returned
`num: 0` with `result: 0`. So how an individual entry is requested cannot be determined
while the log is empty, and building a viewer against a guessed payload would produce a
component that has never rendered a real row.

**Note the naming trap:** the bridge's existing **Logs** tab is the *bridge's own* log.
The gateway's event log is a different thing entirely, and a viewer must not be filed
under the same name.

**Unblocks when** a gateway reports `num > 0` — then probe the entry shape against real
data and build from there. Worth re-reading opportunistically after any fault or firmware
update, since that is when events are most likely to exist.

---

## ANALYSIS-LOCAL-ONLY — capabilities FWHAI and Modbus do not have

**Status:** analysis done 2026-09-14 (user) — see
[`docs/LOCAL_ONLY_CAPABILITIES.md`](docs/LOCAL_ONLY_CAPABILITIES.md)

Of 70 catalogued commands, **17 have no cloud equivalent at all** — and since FWHAI is a
cloud client, that means FWHAI cannot reach them either.

**The headline: `1205 der_comms`.** Grepping `franklinwh-cloud` for `sunsMdEn`, `sunspec`
or `2030` returns **nothing**, and Modbus cannot serve the switch that enables Modbus. So
the local API is **the only way to turn SunSpec Modbus and IEEE 2030.5 on or off** — it
gates the existence of the Modbus control plane itself.

**Also local-only:** firmware OTA (`1501`/`1503`, no cloud methods exist); commissioning
(`1103`/`1105`/`1123`); gateway time/timezone/DST/lat/long/postcode (`1201` — the cloud has
only `zoneInfo`); `reset` and `update` in `1721` (cloud's 315 is reboot-only); the event log
(`1829`); install profile (`1701`); and five undecoded commands (`1207`, `1209`, `1821`,
`1823`, `1825`).

**Understated by the catalog:** the ~27 grid-compliance commands (`1203`, `1211`–`1229`,
`1251`–`1277`) are marked as having a cloud equivalent, but the cloud collapses all of them
into a single **read** (`get_grid_profile_info`). Locally each is its own command with its
own fields, so read granularity is far higher and per-setting writes are reachable only here.

**Beyond cloud parity:** `1901` writes the whole generator block (windows, exercise
schedule, SoC thresholds — hardware-verified), where the cloud offers only
`set_generator_mode`. And `1705` per-cell BMS is reachable by the cloud but **FWHAI
publishes no per-cell entities**.

**The other direction is recorded too**, so this reads as a comparison rather than a boast:
local cannot write reserve SoC (cloud REST / Modbus 15508), cannot write smart-circuit
schedules, has no dispatch or storm engine, cannot read wifi/mobile signal, and has no
SunSpec standardised DER control or register-speed loop.

---

## ANALYSIS-METRICS-GAP — Local Bridge vs FWHAI vs Modbus

**Status:** analysis done 2026-09-14 (user) — see
[`docs/METRICS_GAP_ANALYSIS.md`](docs/METRICS_GAP_ANALYSIS.md)

**Counts from the code:** FWHAI **109** entities (75 sensor / 10 binary / 10 number /
9 select / 5 switch) · Local Bridge **8** (all read-only sensors) · Modbus **44**
capability points (9 SunSpec models + 5 FranklinWH extensions).

**The 8 → 109 gap is mostly publishing work, not capability.** ~60 of FWHAI's entities are
**already readable here** — polled, exposed over REST, drawn in the UI, just never
published to MQTT. Notably the five energy counters (`kwh_fhp_chg` / `kwh_fhp_di` /
`kwh_uti_in` / `kwh_uti_out` / `kwh_sun`) all sit in a single `1301` payload already in
every poll — the cheapest win available.

**~24 of the gap is not device data at all**: FWHAI's dispatch / storm / tariff / saved-
dispatch entities exist because FWHAI has a scheduler and a weather feed. For this bridge
they are downstream of `SCHEDULE-AND-AUTOMATIONS`. Counting them as a metrics gap
overstates it by about a quarter.

**Genuinely not feasible locally:** wifi/mobile signal and network state (cloud reads these
via 317/341; those codes are out-of-band on the local broker), and MPPT (DC-coupled
aPower S — no such hardware here to verify against).

**Blocked, not missing:** the three reserve-SoC controls. *Reading* is solved (`1726`
matches the cloud exactly); *writing* is not (`1405` discards; `1725` untested). They
should ship as **read-only sensors**, never as HA `number` entities, until
`RESEARCH-RESERVE-SOC` resolves — a number that silently does nothing is worse than no
entity.

**Where this bridge already leads:** per-cell BMS telemetry with recorded sessions (FWHAI
has no per-cell entities at all), evidence-based presence detection, `SyHdVersion` model
identification, hardware-verified generator config writes, and built-in-vs-aPbox solar
grouping.

**Order:** energy+power → relays+status → circuits+battery → device+integration → reserve
SoC read-only → the three proven controls. ~55–60 entities without touching the protocol.

---

## DEF-MOBILE-RESPONSIVE — the UI is not built for phones

**Status:** Device tab FIXED 2026-09-16; broader sweep open — **Filed:** 2026-09-16 (user)

**Fixed:** the Device tab was a plain `flex` master/detail at every width, so on a phone
the detail panel sat off-screen to the right — no scroll hint, and mangled when you found
it. Now `flex-col` (list, then detail below) on mobile and a sticky two-column only at
`lg+`. The collapsed-sidebar expand button was `text-slate-600`, tiny and unlabelled (read
as broken); it is now a full-size bordered button with a tooltip.

**Still open — a proper responsive pass over the rest:**
- The fixed sidebar (`w-14`/`w-56`, `h-screen`) is always present on mobile and eats width;
  it should become an overlay/drawer below `lg`.
- Other tabs' multi-column cards (`minmax(280px,1fr)` etc.) mostly wrap, but the header
  control rows do not — see field sizing below.
- Audit every tab at 390px width; the app was clearly built desktop-first.

### Header control alignment/sizing (was DEF-UI-FIELD-SIZING)
The interval dropdown ("2s") and similar stretch full-width instead of sitting in the
toolbar — `.form-control` defaults to `width:100%`. Wanted: header controls (Refresh /
Snapshot / Auto / interval / Chart) on one wrapping row, selects sized to content. Sweep
the tabs added this session for the same issue.

## PLAN-MULTI-GATEWAY-HA — state of play + phased plan

**Status:** plan written 2026-09-14 (user) — see
[`docs/MULTI_GATEWAY_AND_HA_PLAN.md`](docs/MULTI_GATEWAY_AND_HA_PLAN.md)

**Multi-gateway is already ~70% built**, not greenfield: `FWH_HOSTS` config, `GatewayState`
registry, **one poller task per gateway**, per-node MQTT topics and discovery (distinct
serial → distinct HA device), serial-tagged metrics, `/api/gateways`, a topbar picker, and
`?gateway=` on **47 of 67** endpoints.

**HA entities are minimal**: 8 read-only sensors, nothing from any surface added since
(circuits, solar, generator, battery).

**🔴 Defect found while surveying:** `circuits`, `generator`, `solar` and `battery` tabs
fetch **without `?gateway=`**, so on a multi-gateway site they show the default gateway
while the topbar says otherwise. Latent here (single gateway), which is why nothing caught
it. Mine — the `gwq` pattern existed and I missed it four times.

**Phase 0 — DONE 2026-09-14.** All 14 device call sites across the four tabs now append
`this.$store.app.gwQuery()` (or `gwQuery('&')` where a query string already exists), and
`tests/test_gateway_scoping.py` scans every `*_tab.js` and fails on an unscoped `api/`
call. The guard was **verified by reintroducing the bug** — removing one `gwQuery()` makes
it fail with the offending endpoint named — then restored.

Writing the guard found a false positive worth keeping: `mqtt_tab.js` scopes correctly via
a local (`const gwq = …gwQuery('?')`), which a naive scan reads as unscoped. So the check
accepts a `gwq` local **and** separately asserts that any such local is genuinely assigned
from `gwQuery()` — otherwise the exemption would be a hole. Four endpoints are exempt with
stated reasons (`api/logs`, `api/mqtt/discover`, `api/notify/test`, `api/settings`): none
takes a gateway parameter, because none reaches a device.

345 tests pass; single-gateway behaviour is unchanged because `gwQuery()` returns `''`
below two gateways — which is exactly why the original bug was invisible.

**Remaining phases** (each ships independently) · **1** `?gateway=` on the remaining ~20
endpoints, enforced by a route-walking test (**S–M**) · **2** additive HA sensors from
reads already polled — solar, circuits, battery, generator, relays (**M**) · **3** writable
HA entities for *hardware-verified* writes only, excluding discarded schedules and unproven
reserve SoC (**M–L**) · **4** gateway lifecycle, mock gateways, per-gateway poll interval,
Utility service link (**L**) · **5** UI polish (**S–M**).

**Recommendation:** Phase 0 now regardless; then Phase 2 ahead of Phase 1 (entities are
what gets used daily); Phase 4 only once a second real gateway exists — building CRUD
against one gateway risks exactly the §2 class of bug.

---

## RESEARCH-AHUB — find the aHub commands (BLOCKED: needs an aHub owner)

**Status:** hypothesis **CONFIRMED by the vendor manual**; protocol capture still blocked
on hardware — **Filed:** 2026-09-14 (user)

> "Need a user with aHub. But I suspect it is just a bigger Smart Circuits with Generator,
> V2L, Remote Solar (aPbox) Solar PV inputs."

### ✅ Confirmed — *aHub Installation and Operations Manual* (49 pp), 2026-09-14

The user's guess was right, near enough verbatim. The aHub is a **multi-function port
block**:

| port | roles |
| :--- | :--- |
| Port 1 | Smart Circuit |
| Port 2 | **PV** / Smart Circuit |
| Port 3 | **PV** / Smart Circuit |
| Port 4 | **Generator / V2L / PV** / Smart Circuit |

> "**Smart Circuit Management**: Configurable circuit architecture supports up to
> **4×240 V or 8×120 V circuits** with programmable scheduling and remote control."
> "**Solar Optimization**: Accommodates up to **three AC-coupled PV arrays with 24 kW
> total**." · Generator: 240 V standby and portable · V2L capable.

Rated current: main 100 A (125 A OCPD); ports 48/48/48/80 A. Controlled by the **Meter
Adapter Controller**, communicating over **CAN**.

So it is exactly "a bigger Smart Circuits that also takes generator, V2L and PV" — and
**up to 8 circuits**, which retires any assumption that three is the ceiling.

**This also validates the structural prediction below**: a protocol capped at
`Sw1`/`Sw2`/`Sw3` named fields cannot express 8 circuits, which is why the V2 schema moved
to a `smartSwitch[]` array. The array is not incidental — it is what the aHub requires.

### What is still unknown (and still needs hardware)
The **capability** question is answered; the **protocol** question is not. Nothing here
tells us whether the aHub extends existing commands or adds new ones, nor how a
multi-function port reports its current role. The capture request below stands unchanged.

### The hypothesis, and why it is more than a guess

The vendor's Backwards Compatibility Statement describes **aHub** (`ACCY-AHUBV1-US`) as
connecting *"generators, V2L, PV and Smart Circuits"* — i.e. exactly the four things this
protocol currently reads from **four separate blocks**: `1409` smart circuits, `1901`
generator, `1903` solar / remote solar, and the `CarSw*` fields for V2L. "One bigger
Smart Circuits that swallows the rest" is a coherent reading of that sentence.

**The strongest structural evidence is the V2 schema change.** The captured SCV2 protocol
(cloud `387`, see `RESEARCH-SC-387`) replaced 1409's **fixed named fields** —
`Sw1Name`/`Sw2Name`/`Sw3Name`, hard-capped at three — with an **array**:
`smartSwitch[].openAction`, plus `merge: [1,2]`. Moving from fixed keys to a list is
exactly the change you make when the number of circuits stops being three. That is a real
argument that the V2 line was built to grow, and the aHub is the obvious reason to grow it.

### Two shapes to distinguish (this is what the hunt must decide)

1. **aHub extends existing commands** — more entries in the `smartSwitch[]` array, more
   `loadSolarN` inputs, a populated `CarSw*` block. Cheap to confirm: a payload diff.
2. **aHub has its own cmdTypes** — new codes entirely, like 387/389 were.

The two are easy to tell apart from one good capture, and the answer changes where all
later effort goes.

### A hint that favours neither but constrains both

FWHAI's Device DB lists aHub (internal id 253) with **`api_type: null` — detected by
feature flag, not `accessoryType`**. The vendor API returns a type only for generator (3)
and smart circuits (4), and the jkt628 fork's `AccessoryType` enum has exactly those two
and no aHub. So **aHub presence is a flag, not a declared device**, everywhere we have
looked. Whatever the hunt finds, presence detection will be inference again — there is no
accessory serial or firmware anywhere in the local protocol (see
`FEAT-MOCK-ACCESSORIES`).

### What to ask an aHub owner for

Read-only, no writes, nothing that touches their system:

1. `franklinwh-local --host <ip> catalog --json` plus a full read of every catalogued
   command — the baseline to diff against a non-aHub site.
2. `franklinwh-local --host <ip> probe --json` — the sweep already has reconnect handling
   for out-of-band codes, so it is safe to run end to end.
3. `SyHdVersion` from the login manifest, to place the gateway in `devicedb.py`.
4. Their `1409`, `1903` and `1901` payloads specifically — the four blocks the aHub is
   claimed to absorb.

**Diffing 1 and 4 against this AU site answers the question immediately**, without needing
to reverse anything: either the existing blocks grew, or they did not and new codes exist.

### Not a blocker for anything currently built
Nothing depends on this. It is recorded because the vendor sentence and the V2 array change
point the same way, and that is worth not losing.

---

## RESEARCH-SC-387 — newer smart-circuit path (cloud cmdType 387/389, SCV2)

**Status:** investigated 2026-09-14, **does not apply to this hardware** — keep for when
newer gear appears. **Source:** user →
[`jkt628/franklinwh-python`](https://github.com/jkt628/franklinwh-python/tree/main/franklinwh),
captured from the **Android** official app.

That fork uses two cmdTypes absent from this repo's catalog:

| cmd | use | payload |
| :--- | :--- | :--- |
| **387** | smart-circuit **config** | read `{"opt":0}`; **write** = full block + `"opt":1` |
| **389** | smart-circuit **status** | read `{"opt":0}` |

The schema is nothing like the one we speak: `smartSwitch[].openAction`, `merge: [1,2]`,
and a per-circuit **`schedule`** dict — versus `SwXName` / `SwXMode` / `SwXTime` in 1409.
The fork links the **ACCY-SCV2-US** install guide, so this is the SCV2 module generation.
(User: *"I think this is for the NEW gateway hardware and firmware revisions, not my older
model — Smart Circuits specifically, most likely V2."* The evidence agrees.)

**Why it does not reopen `FEAT-SMART-CIRCUITS` phase 3:**

1. **The local broker does not implement it.** Probed 385–391 on FW `V12R02B30D06`: every
   code **closes the connection** — out-of-band, the same behaviour the old 101–1099 sweep
   hit. These are cloud cmdTypes relayed by `sendMqtt`, not local broker codes.
2. **Nobody writes the schedule, even there.** The fork *reads* `schedule` and never writes
   it — `grep` finds it exactly twice, both reads. Its only 387 writes are `openAction`
   (on/off) and `merge`. So schedule writing is still undemonstrated everywhere; 387 only
   makes it *plausible*, because `schedule` sits inside a block that is writable as a whole.

### Refined 2026-09-14 (user): SCV2 yes, aHub separately — and 387 is *not* the aHub

> "This is likely for the new US-only Smart Circuits V2 and/or the aHub, which has more
> Smart Circuits which can be V2L or Solar PV inputs."

Checked both halves against the fork and the vendor Backwards Compatibility Statement.

**SCV2 — strongly supported.** The fork's `AccessoryType` docstring links the
**`ACCY-SCV2-US`** smart-circuit install guide and the **`ACCY-GENV2-US`** generator guide
by name. It is unambiguously the V2 generation.

**US-only — consistent, unproven.** Every SKU the fork references is `-US`; no AU SCV2
appears in any source we hold; and the vendor statement is the **US/Canada** revision
(`US V1.0`), which cannot speak to AU either way.

**aHub — the concept is vendor-confirmed, but 387 is not it.** The statement attributes to
**aHub** (`ACCY-AHUBV1-US`):

> "Managed by the FranklinWH aGate and Meter Adapter Controller, enabling advanced energy
> dispatch strategies and intelligent resource management through its ability to connect to
> **generators, V2L, PV and Smart Circuits**."

That is exactly the role described — one device aggregating generator, V2L, PV and smart
circuits. **But the captured 387 protocol is not aHub-shaped:**

- its `AccessoryType` enum has only `GENERATOR_MODULE (3)` and `SMART_CIRCUITS_MODULE (4)`
  — **no aHub type at all**;
- its `SmartCircuits` model is a **fixed three circuits** (keys 1, 2, 3, with 1 and 2
  mergeable), not an expandable set;
- `grep` finds **no** aHub, V2L, PV or aPbox handling anywhere in the 1,263-line client.

So 387/389 is the **SCV2 module**. If the aHub exposes more circuits — or circuits that can
be V2L or PV inputs — it does so through commands **nobody has captured yet**, and that is
the thing to look for next, not 387.

*(Unrelated but adjacent, from the same table: `aPbox` = `ACCY-RCV1-US`, remarked simply
"Control and metering" — a different device from the aHub, and the one the Solar tab's
remote-solar / digital-I/O card correctly represents.)*

**Worth doing if SCV2 hardware ever appears:** read 387, patch one circuit's `schedule`,
write the full block back with `opt:1`, re-read to verify — the same recipe that works for
1409 on/off and 1901 generator config. That would be the first demonstration anywhere of a
schedule write.

**Incidental corroboration:** the fork's generator mode write is
`{"manuSw": 1 + int(enabled), "opt": 1}` — matching the `manuSw` 1 = Auto-schedule /
2 = Manual mapping already used here, from an independent capture.

---

## FEAT-MOCK-ACCESSORIES — emulator profiles for absent/present accessories

**Status:** planned — **Filed:** 2026-09-14 (user)

> "we need a mock that simply includes the fact it is not installed — does a serial
> number or firmware number get returned? likewise for smart circuits"

**Answered: no.** There is **no serial and no firmware version for any accessory** in the
local protocol. Checked 2026-09-14:

| source | what it carries |
| :--- | :--- |
| `1105` `devMap` | only the aPower (`devSN 10050013A00X…`) — no accessories |
| `1833` device_firmware | `fhp_sn`/`ibg_sn`/`pe_sn`/`bms_sn` — gateway + battery only |
| `1101` login manifest | same four families, plus `SyHdVersion` |
| `1901` generator | `genModel` — **empty string** when absent; the only identity field |
| `1409` smart circuits | `SwXName` — a *user-editable label* with a factory default |

So an accessory can never be identified, only **inferred** — which is exactly why
`circuits.evaluate()` and `generator.installed()` are evidence-based, and why
`SyHdVersion` (gateway-level) was such a find. A mock cannot fake an accessory serial
because the real protocol has none.

**And the sharp edge this exposes:** generator config writes (1901) **succeed on a site
with no generator module fitted** — windows, exercise schedule and SoC thresholds all
persist. The gateway stores generator settings regardless of hardware. So "the write
worked" proves nothing about a generator existing, and any UI must keep those two claims
separate.

**Proposal — profiles on the existing emulator** (`franklinwh_local/emulator.py`, which
today replays a capture plus a dynamic seed and has no accessory concept):

- `--profile au-bare` — `SyHdVersion 102`, `genEn 0`/`genModel ""`, Sw3 factory
  placeholders. **The current site** — the regression case for "absent" detection.
- `--profile au-sc` — two configured circuits with live metering.
- `--profile us-gen-sc` — `SyHdVersion 103`, generator fitted (`genEn 1`, model, rated
  power, `genStat` cycling), three circuits. The case **no one can test on this
  hardware**, and the reason to build this at all.
- `--profile no-accessories` — everything absent, for the `installed: false` paths.

Each profile drives 1409/1411/1901/1101 coherently, so the bridge's detection, the
"not detected" cards and the generator tab can all be exercised in CI. Profiles must
reproduce the **discard** behaviour too (1409 schedule accepted-and-ignored, 1401
refused with `result:1 reason:-2`), otherwise tests would pass against a mock that is
more permissive than the hardware — the worst kind of green.

---

## FEAT-GEN-WRITES — generator config IS writable locally (library-level)

**Status:** library DONE, bridge API DONE, **UI deliberately not built yet** —
**Filed/landed:** 2026-09-14 (user: *"get the base local API correct and tested first.
lean the UI until we get it working"*)

**Layering correction.** The schedule write was built in the *bridge* client, bypassing
the library — wrong layer, since the proven `set_smart_circuit` recipe and the catalog
both live in `franklinwh-local`. The protocol write now lives in
`franklinwh_local.client`; the bridge only maps its editor shape to firmware slots.

**1901 generator writes APPLY** (hardware-verified 2026-09-14, FW V12R02B30D06):
`set_generator()` full-block RMW + read-back, plus `set_generator_window/_exercise/_soc`.
Operating windows, exercise schedule and SoC thresholds all persist — **verified on a
site with no generator module fitted**, so the config is writable independently of the
hardware being present. Live: window 2 → 02:15–03:45 confirmed, then restored; window 1,
SoC and exercise untouched throughout.

**1409 smart-circuit schedule writes DO NOT** — five payload shapes, all `result:0`,
none applied; **1401 refuses outright** (`result:1 reason:-2`). Recorded in the new
`catalog.DISCARDED_WRITES`, and 1401's catalog description corrected (it is *not* the
schedule source). See `FEAT-SMART-CIRCUITS` and `SMART_CIRCUITS_DESIGN.md` §11.

**The asymmetry is the finding** and the tests pin both halves so neither is generalised
to the other: the same gateway, minutes apart, applies generator config and discards
circuit schedules.

**UI — DONE 2026-09-14** (user asked once the writes were proven): the Generator tab's
operating windows, maintenance run and start/stop SoC are now editable, each behind
`writes_enabled` and each reporting the device's own read-back (`ok` is never true
without a confirming re-read). Live-verified through the endpoint: window 3 →
`04:00–05:15` confirmed, then restored. Smart Circuits also gained the **Raw JSON**
button Generator already had (`GET /api/circuits/raw`).

**Editing gated on `genEn` — 2026-09-14** (user: *"not installed or enabled more
correctly — should not allow editing"*). Three states are now distinct, because the
protocol treats them as distinct:

| field | meaning |
| :--- | :--- |
| `enabled` | `genEn` — the **feature flag**. Gates editing. |
| `configured` | model / rated power / run state — the only *evidence* of real hardware. |
| `editable` | `enabled` — config edits are blocked while the feature is off. |

`installed` is retained as the broad "show me something" signal, but it is **no longer
what gates writes**: the gateway accepts generator config either way, so letting a user
edit a disabled generator would imply an effect that does not exist.

**Opt-in mirrors the official app** (user: *"the official mobile app allows you to install
it and toggle things on and off — just like you can"*). `PUT /api/generator/enable` sets
`genEn`, and the UI offers **Enable generator** with a confirm that warns plainly: with no
hardware reported, the setting will save and **nothing will happen**. Once enabled but
still unconfigured, a standing amber banner repeats that, with a Disable button.

Deliberately, `set_generator_enabled` does **not** refuse when nothing is fitted — unlike
`set_generator_mode`. Refusing would block a genuine install, which is exactly the case
the button exists for. A test pins that asymmetry.

### Not done — on purpose
- **What the writes prove is narrow.** Settings persist on a site with no generator
  fitted; that is not evidence a generator would act on them. The UI says so rather than
  implying a working schedule.
- **Generator is off-grid-only** (user, 2026-09-14): *"the generator module is
  unavailable whilst on grid, but you can configure it."* Consistent with the vendor docs
  framing generator SoC start/stop as off-grid behaviour, and with every 1901 write in
  this repo succeeding while grid-connected. Whether `genEn` itself takes effect on grid
  is **untested and untestable without islanding**, so the enable dialog states the
  limitation ("only available off-grid; will not run until the gateway islands") and
  claims nothing about the flag's on-grid behaviour. See `OFFGRID_DESIGN.md` §12.
- **`genEn` was not flipped on the live gateway.** Enabling a generator feature on a
  system with nothing attached could change off-grid or dispatch behaviour in ways not
  worth discovering by accident. The endpoint is covered by tests; the live toggle is the
  user's call.
- `manuSw` (Auto/Manual mode) still untested — it is the one 1901 field that would act on
  real hardware, so it keeps its 409-when-absent guard.

---

## FEAT-OFFGRID — off-grid mode surface (designed, unimplemented)

**Status:** designed — **Filed:** 2026-09-14 (user) — full evaluation in
[`docs/OFFGRID_DESIGN.md`](docs/OFFGRID_DESIGN.md)

Live reads while **grid-connected** (so all off-grid values are idle defaults) settled
five questions:

1. **Off-grid detection has four independent signals** — `1301 run_status` (5/6/7, the
   same enum as the cloud), `1723 offgridState`, `1709 gridRelayOpen`, and the undecoded
   `elecnet_state`. Report which fired; disagreement is diagnostic, not noise to average.
2. **Simulated vs real: no reason code, but a better discriminator.** `1723` returns both
   `offgridSet` (requested) and `offgridState` (actual). `Set=1,State=1` = user-requested;
   **`Set=0,State=1` = real outage**. Inferred from the field pair and the cloud's
   read/write split — **unconfirmed until an actual event**, so the UI must show the raw
   flags next to the interpretation.
3. **Blackstart is NOT readable.** `blackStartOnOff` lives in `1801`, which returns
   **field positions 0–14 instead of values** on this firmware (live-confirmed:
   `blackStartOnOff: 11` is the eleventh field). Displaying it would fabricate a
   safety-relevant value. Generator SoC thresholds survive via `1901` instead.
4. **Standby** is available from `run_status` (0 Standby / 5 Off-Grid Standby).
   `ibgDspState`/`peState`/`bmsState` have no enum — show raw or not at all.
5. **V2L-as-input candidate found:** `1409 CarSwConsSupEnable` (+ `CarSwConsSupEnerge`,
   `CarSwConsSupStartTime`) reads as *CarSW Consumption Supply*. Mutual exclusion with the
   generator is plausible but **nothing observed enforces it** — the bridge should enforce
   the interlock in software and not claim the device does.

**"PV drops then returns → start generator" is bridge-side orchestration** — the device's
generator automation is SoC-based only, with no PV-loss trigger. Belongs to
`SCHEDULE-AND-AUTOMATIONS`. Must require N consecutive confirmations (a dropped poll on
the flaky wifi must never start a generator), and the UI must be honest that the bridge
may itself be unpowered during an outage, whereas the gateway's own thresholds keep working.

**Phasing:** (1) `GET /api/offgrid` + read-only panel — safe and buildable now ·
(2) source display + software interlock · (3) PV automation · (4) off-grid trigger write
hardening, which needs a *planned* test.

---

## FEAT-SMART-CIRCUITS — Smart Circuits API + UI (design done, unimplemented)

**Status:** designed — **Filed:** 2026-09-13 (user) — full evaluation in
[`docs/SMART_CIRCUITS_DESIGN.md`](docs/SMART_CIRCUITS_DESIGN.md)

Live reads of 1409/1411/1401 on the AU gateway settled four things:

1. **1409 carries the schedule**, in the V2 string format (`"2026-06-19 16:02"`), four slots
   per circuit as two on/off pairs — and the cloud library documents itself as **unable to
   write these** (`API_COOKBOOK.md:1607`). Local can. That is the case for building it here
   rather than deferring to Automations, and it is what FWHAI omits.
2. **1401 is a decoy** — all-zero switch blocks plus an uninitialised `sw4` block whose
   integers are ASCII bytes read as int32. Never write to it. `catalog.py`'s 1401 entry
   oversells it and needs correcting.
3. **Circuit count is not detectable from the payload.** 1409 always returns three blocks
   (this AU unit reports a factory-default `"Circuits 3"`); the cloud's `modeChoose`
   discriminator is absent locally; and counting 1411 meter channels fails because the third
   circuit is metered as **`CarSW`**, not `SW3`. Recommendation: a `SMART_CIRCUIT_COUNT`
   setting (`auto|2|3`) with a *stated* heuristic and a visible "not detected" card — never a
   silent hide.
4. **Per-circuit energy is a lifetime counter**, so "Energy (today)" must be differenced by
   the bridge across midnight, not read off the device.

**Bridge gaps:** `cloud_compat.smart_circuits_map()` hardcodes `range(1, 4)` and emits a
phantom circuit 3 on AU (fix first); 1411 metering is unused; writes are on/off only; there is
no UI tab.

**Phase 1 — DONE 2026-09-13.** `circuits.py` (pure detection), `client.circuits()`
(1409+1411 in ONE session, metering best-effort), `GET /api/circuits`,
`POST /api/circuits/{id}/power`, and a Smart Circuits tab. Live on the AU gateway:
2 circuits detected, circuit 3 correctly rejected with its reasons shown. 261 tests.

Decisions taken during phase 1 that amend the design doc:
- **`cloud_compat.smart_circuits_map()`'s `range(1,4)` was left alone.** It backs
  `/api/cloud/*`, whose contract is byte-parity with the cloud library — detection
  belongs in the native `/api/circuits`, not in a parity shim. A test pins it at 3 keys.
- **"Not installed" is now a first-class state**, separate from region count (user:
  cloud's confusion came from *assuming circuits were installed at all*). `installed:
  false` renders a "No smart circuits detected" card rather than an empty grid.
- **CarSW is surfaced as its own channel**, not folded into circuit 3 — 1409 carries
  `CarSwConsSup*` alongside a full `Sw3` block, so locally they are distinct.
- **Absent ≠ zero.** A missing meter channel reports `null`, never `0 W`.
- The on/off write was already hardware-verified (2026-08-08); the design doc's "not
  yet verified" was copied from a stale catalog note.

**Monitoring sub-view — DONE 2026-09-14** (user). Circuits / Monitoring sub-tabs; the
Monitoring view polls `GET /api/circuits/meter` (raw 1411) with snapshot + auto-refresh
(2/5/10/30 s), grouped Switch 1 · Switch 2 · V2L/CarSW · Gateway. CarSW is labelled
**V2L** to match the Device tab and `fieldschema.py`. The shared `power/curr/volt/freq`
keys are grouped as *"Gateway (shared, not per-circuit)"* because they appear identically
in 1901 — presenting them as circuit metrics would be wrong. Auto-refresh stops when the
tab is hidden.

**Phase 3 (schedule editing) — BUILT 2026-09-14, NOT YET FIRED AT HARDWARE.**
`circuits.build_schedule_write()` + `client.set_circuit_schedule()` +
`PUT /api/circuits/{id}/schedule` + a two-window editor on each card. Validates what the
firmware will not: HH:MM range, end strictly after start, and no overlap between *enabled*
windows. The date component of each slot is **preserved**, never regenerated — a schedule
dated months ago still reports active, so the date looks like "when it was written", and
rewriting it could turn a recurring window into a one-shot. A never-written slot gets
today's date instead of the `2000-01-01` placeholder. The full block is echoed so the
other circuit's schedule survives. 11 new tests.

🔴 **TESTED 2026-09-14 — THE WRITE IS SILENTLY DISCARDED.** Three payload shapes on
circuit 2 (windows disabled; with the `SwXMsgType` target selector set exactly as the
proven on/off write does; window enabled) all returned `result: 0` and changed nothing.
**Control:** an on/off write on the same command and circuit, moments later, flipped
`Sw2Mode` 0→1→0 with read-back confirmation — so the transport is fine and the schedule
fields specifically are ignored. Same signature as `1405 mode_soc` ("accepted then
silently discarded; cloud-owned"), and consistent with the cloud library also declining
to write schedules — a vendor constraint, not a local gap.

**No collateral damage:** all 39 fields byte-identical to the pre-test capture after six
writes. The endpoint stays (harmless, self-verifying, may work on other firmware) but now
returns **`discarded: true`**; the UI editor was removed and schedules are read-only with
the finding shown. **This retracts the headline of `SMART_CIRCUITS_DESIGN.md` §1.1** —
schedules are readable locally, not writable. Re-test after any firmware update.

**Generalised lesson:** an `opt:1` ack on this device means "frame parsed", not "setting
applied". Assume discard until a read-back proves otherwise.

**Vendor doc check (2026-09-14)** — see `docs/SMART_CIRCUITS_DESIGN.md` §9. Confirms
scheduling, confirms **merge is load-based** (*"merged if they share electrical
infrastructure"* — supports the CarSW hypothesis), and establishes that **SoC cut-off is
an off-grid-only feature**, which links this surface to `FEAT-OFFGRID`. Also flags
**overload protection**, for which no local field is known — a circuit can switch off for
reasons the bridge cannot observe. The AU page's "three circuits" claim conflicts with
both the capability spec and this AU hardware; detection + override stands.

**Phasing:** (1) ✅ read-only cards + power toggle + monitoring · (2) SoC cutoff + energy-today ·
(3) schedule editor — **first unproven write, test on circuit 2 "Test Switch"** ·
(4) automations integration once `SCHEDULE-AND-AUTOMATIONS` exists.

**Cross-repo defect** ([franklinwh-cloud#7](https://github.com/david2069/franklinwh-cloud/issues/7)): `API_COOKBOOK.md:1610` claims AU has 3 outputs
with V2L, contradicting `CAPABILITY_RESOLUTION_SPEC.md` Rules 1–2 and
`DISCOVER_IMPLEMENTATION_PLAN.md:102`. Spec and hardware agree; the cookbook is wrong.

---

## FEAT-BMS-SESSIONS-SCHEDULED — let Automations schedule BMS recordings

**Status:** planned — **Filed:** 2026-09-13 (user) — **depends on**
`SCHEDULE-AND-AUTOMATIONS`

> "FWHAI allow Automations to schedule running the BMS metrics records and data recorded
> for displaying as chart of the cell metrics"

`FEAT-BMS-SESSIONS` can only be started by hand from the Battery tab. FWHAI can drive it
from an automation, which is what makes cell-level data actually useful: the interesting
windows (a deep discharge, a full absorb, a cold morning) are exactly the ones nobody is
sitting at the UI for.

**Wanted**
- A **`record_bms` action** in the schedule/automation engine: samples, interval, optional
  label, target gateway + aPower.
- Recordings started this way are ordinary sessions — same table, same charts — but
  **tagged with their source** (`trigger`: manual | schedule | automation, plus the entry
  id) so the sessions list can show *why* a recording exists.
- **Condition-gated** capture, the real prize: record while `soc < 20` or
  `battery_power < -3000`, i.e. capture the cell spread under load rather than at rest.
- Respect the one-at-a-time rule: an automation firing while a manual run is active must
  **defer or skip**, not silently kill it — reuse the schedule's *if-already-controlled*
  arbitration rather than inventing a second policy.
- Retention matters more here than for manual runs: unattended recording is what makes
  the missing policy above bite. Pair this with a cap or an age-out.

**Note:** the engine does not exist yet — `SCHEDULE-AND-AUTOMATIONS` is still planned. This
is a consumer of it, so it should land as one of the first actions once that engine is in
place, not before.

---

## INFO-CONTAINER-TZ — containers are UTC, the host is AEST; mostly harmless

**Status:** explained (2026-09-12) — includes a correction to a wrong diagnosis
**Filed:** 2026-09-12

**Docker containers do not inherit the host timezone.** They default to UTC unless given a
`TZ=` env var or a mounted `/etc/localtime`. Running on the same machine changes nothing —
each container has its own clock view. Observed:

| | timezone | started |
|---|---|---|
| host | **host-local zone** | — |
| `franklinwh-local-bridge` | **UTC** | 2026-08-29 |
| `fwhbridge-app` (Modbus Bridge) | **UTC** | 2026-09-04 |
| `fwhhai-app` (FWHAI) | **host-local** | 2026-09-12 |

FWHAI is the only one on local time despite having no `TZ=` env, so it sets it another way
(image default, a mounted localtime, or in-app config). Worth copying if consistency is
wanted.

**Does it matter for this bridge? Almost no.** Metrics are stored as **epoch**, which is
timezone-agnostic, and the REST layer hands out epochs for the client to render. The only
effect is that container log lines read UTC while the UI reads local — cosmetic, though it
cost real time during the `DEF-POLLER-STALL` investigation, so setting `TZ` to your local zone
in compose is a cheap quality-of-life win.

### ⚠️⚠️ The retraction below was ITSELF wrong (2026-09-13)
The owner confirms it **was** a container-timezone problem, and the schedule fired correctly
at 18:00 local once fixed. So the original diagnosis was right and the retraction was the
error.

How I got it wrong twice: I retracted on the strength of one inference — the container had
been UTC since 2026-09-04, yet the schedule fired at 18:00 local on 09-11, therefore the
scheduler "must" resolve its own timezone. That single data point was not the proof I
treated it as (the schedule had been edited around 09-10, among other possibilities). Both
the claim and the retraction were stated with more confidence than the evidence carried.
The honest position at the time was "the timeline endpoint disagrees with wall clock, cause
unconfirmed".

### ⚠️ Original correction (now superseded — the diagnosis it retracted was correct)
While investigating a missing export window I claimed the Modbus Bridge's scheduler had
"lost its timezone", on the strength of `/api/schedules/timeline` reporting
`now_min: 622` (10:22 UTC) against a local 20:23, and advised fixing the TZ before expecting
another window. **That was wrong.** The container has been UTC since **2026-09-04**, yet the
schedule fired at **18:00 local** on 2026-09-11 — so the scheduler resolves its configured
timezone correctly and only the *timeline endpoint* reports `now_min` in UTC. An endpoint
inconsistency, not a scheduling fault.

**Why the window did not fire on 2026-09-12 is still unresolved.** Not timezone. Entry
conditions are `soc 50–100` (was 97.6 %, ✅), `grid.connected` (✅) and
`tariff.bonus_window_active == 1` — the remaining candidate, and not readable from the API
endpoints tried (`/api/points/latest`, `/api/automation/constants`). The schedule log has no
entry for that day (newest is the prior day's `exit_condition_met`), so it genuinely never
dispatched.

Note also that even had it dispatched after 18:32, [[DEF-POLLER-STALL]] would have missed
it — the recording gap covers 18:32–20:15, which is most of the window.

---

## DEF-POLLER-STALL — a failed poll is SILENT, and one cycle is unbounded

**Status:** FIXED 2026-09-30 (fixes 1+2 only, per owner scope — log failed polls + bound the cycle; NO watchdog/backfill). Was: diagnosed 2026-09-12, LOW PRIORITY
**Filed:** 2026-09-12

> **Priority call (owner, 2026-09-13):** not a priority. This is a home energy setup, not a
> utility, hospital or data centre — occasional gaps are acceptable and **gaps are preferred
> over carry-forward filling**. Do not build the watchdog/backfill machinery. If anything is
> done here, do only fix 1 (log failed polls) and fix 2 (bound the cycle) — both are a few
> lines and make the next outage self-evident rather than a two-hour investigation.

### What was observed
`metrics.db` had **no row between 18:32 and 20:15 local (103 min)**, then 12 rows at ~30 s
spacing, then nothing for a further 75 s. Throughout: container `healthy`, `/api/health`
answering, `/api/summary` returning `ok: true`, aGate at 143 ms.

### Diagnosis — and a correction
First written up as "not the ordinary wifi flakiness". **That was probably wrong.** Reading
the loop, this is most likely a genuinely long aGate outage, rendered invisible by two design
weaknesses rather than by a novel failure:

**1. A failed poll logs nothing at all.** The loop does:

```python
summ = await asyncio.to_thread(client.summary, settings, gw.active_host)
...
if summ.get("ok"):        # insert only on success
    ...store.insert(...)
```

and on failure only mutates the cached summary (`ok: False`, `stale: True`). **No log line, no
insert, no counter.** That is exactly why the logs showed nothing — there was nothing to find.
The recording simply stops, and the dashboard keeps rendering the last-good cache.

**2. One cycle has no time bound.** `asyncio.to_thread(client.summary, …)` is awaited with no
timeout, and `client.summary` is a full device session: `ping(1 s)` +
`port_open(502, 3 s) × 3` + login + ~6 reads, each at `timeout=20, retries=2`. So an
unreachable aGate costs **~70 s minimum per cycle** — ping 1 s, Modbus probes 9 s, login
3 × 20 s — against a 30 s interval. The loop cannot keep cadence, and 103 min is ~90 such
cycles.

Note the 10 s of `ping` + triple Modbus probing is paid **every 30 s even when healthy**,
purely to populate two health fields.

### Why it is worse than a plain outage
Nothing surfaces it. The container is healthy, the API is healthy, the UI polls
`/api/summary` and gets served the cache — so the numbers on screen look live while nothing
is being recorded. It is only discoverable by going to look at history, which is how it was
found. The `CONN-LOSS-UX` banner does **not** catch it either: the bridge is up; the
background loop is the casualty.

### Fixes (specced)
1. **Log failed polls** — throttled warning with the error and a consecutive-failure count.
   One line would have made this self-evident.
2. **Bound the cycle** — `asyncio.wait_for` around the summary (~25–30 s), so a slow device
   cannot hold the loop hostage. Same pattern already applied to the cloud revalidation.
3. **Surface "recording stopped"** — `stale: True` is already on the cached summary and the
   new `conn.checks.poller` row reads it; also expose "last successful insert" in
   `/api/health` so it is visible without opening a chart.
4. **Stop probing every cycle** — move `ping` + the 3× Modbus probe onto a slower cadence
   (say 5 min). Saves up to 10 s per cycle and most of the failure latency.
5. Optionally a **watchdog**: if no insert has succeeded for N intervals, log loudly and/or
   restart the loop.

**Related:** this is the strongest argument yet for `1303` as an independent auditor
(`FEAT-ANALYTICS-TAB`) — the gateway's metered totals were complete for exactly the period
the poller missed.

---

## FEAT-ANALYTICS-TAB — unified Local + Cloud analytics (Energipays-style)

**Status:** planned — design first, **not started**
**Filed:** 2026-09-12
**Related:** library `DEF-1303-PLOAD-DUP`, `FEAT-LOCAL-ROLLUPS`, `DEF-1303-TIER-BASIS`

An Analytics tab modelled on the Energipays Bridge: a **Local / Cloud source toggle**, date
navigation (‹ date ›), resolution selector, aggregation mode, line/bar toggle, Export, and
a multi-series legend — one UI over both datasets.

### The hard part: there are THREE datasets, not two

| | **Local poller** (`metrics.db`) | **Gateway history** (cmdType 1303) | **Cloud** |
|---|---|---|---|
| resolution | **30 s** (`poll_interval`) | 15 min (96/day, fixed) | 5-min / hourly / daily |
| retention | **30 d** (`metrics_retention_days`) | **~105 d** rolling | years |
| grid | ✅ `grid_w` | ✅ `p_uti` | ✅ `kwhUtiIn/OutArray` |
| battery | ✅ `battery_w` | ✅ `p_fhp` | ✅ `kwhFhpChg/DiArray` |
| generator | ✅ `generator_w` | ✅ `p_gen` | ✅ `kwhGenArray` |
| **solar** | ✅ `solar_w` | ❌ **no series at all** | ✅ `kwhSuArray` |
| **home load** | ✅ `load_w` | ❌ **series duplicates `p_fhp`** | ✅ `kwhLoadArray` |
| SoC | ✅ | ❌ | ✅ |
| tariff-tier splits | ✅ (new `tiers` column) | ✅ sharp/peak/flat/valley | ❌ |
| rollups (wk/mo/yr) | via `energy.rollup()` | ❌ | ✅ native |
| units | **watts** (power) | watts + daily kWh | **kWh** (energy) |

So "Local" is itself two sources with different capabilities, and the choice is not free:

- **Solar and home load before the poller started do not exist locally at all** — 1303
  cannot supply them (library `DEF-1303-PLOAD-DUP`). Local solar/load history begins the day
  the poller began, not 105 days back.
- **Tariff-tier splits are local-only** — the cloud does not expose them. A genuine
  differentiator worth surfacing rather than hiding behind a source toggle.

### Design decisions to settle before building

1. **Source selector: two options or three?** "Local / Cloud" is the cleaner UI but hides
   that local-30 d-full-fidelity and local-105 d-partial are different things.
   Suggested: **Local / Cloud** in the toggle, and inside Local prefer the poller where it
   has coverage, falling back to 1303 beyond it — with the series that cannot be back-filled
   (solar, load, SoC) visibly truncated rather than silently zero. **Never zero-fill a gap**;
   a flat line reads as "no solar", not "no data".
2. **Power vs energy.** Local is instantaneous watts; cloud is kWh per interval. Plotting
   them on one axis is wrong. Either convert local → kWh per bucket (`energy.integrate()`
   already does this correctly, skipping gaps) or label the axis per source and never mix.
3. **They will not match, and that is expected.** Measured on 2026-09-10: integrating the
   local 30 s grid series gives **10.9885 kWh** export vs the gateway's metered
   **10.9994 kWh** — 0.1 % apart. Different method (sampled integration vs internal meter).
   State the tolerance in the UI or users will file it as a bug.
4. **Cloud calls are rate-limited.** `franklinwh-cloud` enforces 60/min and its
   `RATE_LIMITING.md` warns that unusual volumes risk account action. A date-stepper that
   refetches on every ‹ › press is exactly the wrong pattern — **cache per (source, date,
   resolution)** and make Refresh explicit.
5. **Day boundaries.** Local timestamps are epoch/local-time; cloud takes `dayTime` as
   `YYYY-MM-DD`. The gateway's own day rolls at local midnight (its tier accumulators reset
   there). Pick one basis and convert at the edges.
6. **Cloud requires credentials.** The Analytics Cloud tab must degrade cleanly when the
   cloud provider is unconfigured or the auth breaker is `locked` — reuse
   `providers.reserve_provider()`'s `auth`/`validated` signalling rather than erroring.

### ✅ DECIDED (2026-09-12): the poller is primary; the gateway is fallback + auditor

`metrics_retention_days` raised **30 → 365** (~130 MB at 30 s; measured 0.35 MB/day, ~0.67
with the `tiers` column). That removes the only reason the gateway's ~105-day record looked
longer — its retention advantage was an artefact of a conservative default, not a real
constraint.

The asymmetry that decides the rest:

> the **poller** is better at **shape** — 30 s, all channels, SoC
> the **gateway** is better at **truth** — metered totals, tier attribution

So `1303` is **not** a third peer in the source toggle. It gets three jobs:
1. **Gap fallback** — surfaced only where the poller has no rows, never silently.
2. **Independent auditor** — the *highest*-value use. Every other number in the bridge comes
   from the bridge's own polling, so a sign error or wrong-field bug would be *consistently*
   wrong with nothing to catch it. `1303` is metered by the device: different code path,
   different method. This was used for real on 2026-09-10 — integrating the local 30 s grid
   series gave 10.9885 kWh vs the gateway's metered 10.9994 kWh, and that 0.1 % agreement is
   what validated the poller.
3. **Promoted where it is genuinely better** — metered daily `kwh_*` and tier splits as their
   own panel, not a degraded copy of the chart.

### Gap filling — measured, and smaller than expected

Actual local coverage over the 30-day window: **98.3 %** — 84,906 of an expected 86,402
samples. 30 gaps over 90 s, totalling **2.2 h (0.30 %)**:

| gap length | count |
|---|---|
| 90 s – 5 min | **28** |
| 5–15 min | 1 |
| 15–60 min | 0 |
| 1–6 h | 1 (63 min, 2026-08-28 04:19) |

**This calibrates the design down.** 28 of 30 gaps are under 5 minutes — shorter than
`1303`'s own 15-minute bucket, so backfilling them from the gateway cannot add detail the
gap lacks. Only the single 63-minute outage is worth filling for shape.

And for **energy totals the answer is not backfill at all** — take the metered `kwh_*` from
`1303`, which is complete regardless of poller gaps. That sidesteps the hardest part
(boundary double-counting when splicing integrated and metered energy) entirely, and it
falls straight out of the shape/truth split above.

So the gap policy is:
- **Totals** → always the gateway's metered `kwh_*`. No splicing.
- **Shape** → poller only. Gaps stay visible as gaps; `energy.integrate()` already skips
  them rather than straight-lining, so integrals under-report by ~0.3 % instead of inventing
  energy.
- **Backfill only gaps > 15 min**, only for the channels the source actually has, and always
  provenance-tagged in the UI.
- **Solar / home load / SoC gaps can only come from the cloud** — `1303` has no `p_sun`
  series and its `p_load` duplicates `p_fhp`, so it cannot fill those at any length.

### Suggested phasing
- **P1 — Local only.** Reuse the existing `/api/metrics` + `_resolve_bucket`; add date
  navigation, line/bar, CSV export, and a source-aware legend. Ships value with no new
  dependency and no cloud traffic.
- **P2 — Gateway history.** Surface 1303 for the 30–105 d window, with the missing-series
  truncation from (1) and the tier splits as their own view.
- **P3 — Cloud.** Add the toggle, per-key caching, and native week/month/year rollups.
- **P4 — Reconciliation view** (optional, and the most interesting): same day from two
  sources side by side, with the expected-tolerance note from (3). This is also how
  `DEF-1303-TIER-BASIS` would finally be checked against real tariff data.

### Explicitly out of scope for now
The mobile bottom-nav shell from the Energipays screenshots is a **separate** layout job
(`index.html` + `sidebar.html` restructure), not part of this. Filed separately if wanted —
the current responsive story is one CSS rule (`.metrics-grid` → 2 columns under 768 px).

---

## RAW-CMDTYPE-ON-DASHBOARD — the `</>` toggle only annotates Live Points + Device tab

**Status:** DONE (2026-08-13). The `</>` toggle now annotates every main Dashboard card with
`rawkey · cmdType` via `$store.app.srcTag(key, cmd)`: Battery-SoC (name/p_fhp/run_status·1301),
Power Flow (p_uti/p_sun/p_fhp/p_load/p_gen·1301), Battery (t_amb/fhpSn/fhpSoc·1301), Today's
Energy (kwh_*·1301), Operating Mode & Reserves (list·1726), SunSpec (sunsMdEn·1205), Firmware
(IBG_VER·1101). Topbar chips left un-annotated (space-tight; the SoC card carries it). Verified
live: 20 tags render, no JS errors.
**Filed:** 2026-08-11 (user)  ·  ORIGINAL DEFECT BELOW:

The topbar `</>` "show raw keys / cmdTypes" toggle (`$store.app.showRawKeys`) only reveals
raw keys in the collapsible **Live Points** section (`dashboard.html:348`) and the **Device
tab** (labels + `cmd NNNN` in the panel header). It does **nothing** on the main Dashboard
cards — Power Flow (GRID/SOLAR/BATTERY/LOAD/GENERATOR), Battery, Today's Energy, Operating
Mode & Reserves — or the topbar status chips (mode/run-status/SoC). So toggling it while
looking at those cards appears broken.

**Want:** Modbus-Bridge "show sources" parity — every displayed value shows its source next
to it when toggled (raw key + the sendMqtt cmdType, e.g. `p_fhp · 1301`). Wire `showRawKeys`
annotations into each dashboard card + the status chips, sourcing the cmdType from
`/api/catalog` and the raw key from the field it renders. Sizeable template pass across
`dashboard.html` (and `topbar.html` chips).

## DEVICE-READ-RESILIENCE — slow reads + transient "Load failed"

**Status:** MOSTLY FIXED 2026-08-11 — **Filed:** 2026-08-11 (user)

`connectivity` (router/net/AWS probe) is a genuinely slow device read (~6s); `grid_profile`
is ~25 reads. A click during a container restart surfaces as Safari's "TypeError: Load
failed". Fixed: `connectivity` marked **slow**, `fetchCmd` got a 35s AbortController timeout
+ a friendly error message + a **Retry** button. Remaining (inherent): a read fired while the
bridge is mid-restart will still fail transiently — that's expected, Retry recovers it.

---

## HYBRID-CAPABILITIES — fill the local hard walls via Modbus + Cloud providers

**Status:** planned — **Priority: HIGH (strategic)** — big, phase it
**Filed:** 2026-08-09 (user)

Give the Local Bridge the two capabilities the local sendMqtt API **physically cannot do**
(the hard walls in `docs/API_COMPARISON.md`) by reaching across to the other tiers:
- **Battery dispatch** — force **charge / discharge / standby / release**, target-SoC —
  via **Modbus**.
- **Cloud-only writes** — **Set Reserved SoC**, grid power limits, mode-with-SoC, etc. —
  via the **Cloud**.

**Provider pattern (per capability): prefer an INSTALLED sibling's REST API; else the
library.** Reusing a running sibling reuses its connection/creds AND its proven safety —
important for dispatch.
- **Dispatch → Modbus provider:**
  1. If a **Modbus Bridge** is installed/reachable → call its REST (`POST /api/command`:
     `battery_command` charge/discharge/standby/release, `battery_command_power[_pct]`,
     `battery_command_duration`, `battery_command_target_soc`). **Preferred — its software
     watchdog + safety are proven.**
  2. Else load the **`franklinwh-modbus`** library in-process (Modbus TCP :502, WSet +
     replicate the watchdog). Note the SPAN/Lumin write-lock gate + `der_comms` sunsMdEn.
- **Cloud-only → Cloud provider:**
  1. If **FWHAI** is installed/reachable → call its REST (`POST /api/gateways/{id}/control`,
     `PATCH .../mode/reserve`, mode/set) — mirrors what our cloud-aligned facade already
     shapes.
  2. Else load the **`franklinwh-cloud`** library (needs cloud creds; `update_soc` /
     `set_mode` / grid power settings).

**Detection / config:** `modbus_bridge_url`, `fwhai_url` settings (+ health probe); optional
`franklinwh-modbus` / `franklinwh-cloud` as **optional extras** for the library fallback;
optional cloud creds + Modbus host. Later: auto-detect sibling HA add-ons / LAN.

**Surface:** the Control tab + the cloud-aligned write endpoints gain force
charge/discharge/standby/release + target-SoC + **reserve-SoC write**, each **gated
(allow_writes)** and **tagged with the provider used** (local / modbus-bridge / modbus-lib /
fwhai / cloud-lib) and whether it's a delegated vs in-process call. The current
`/api/cloud/reserve` **501** becomes "reserve via the cloud provider" when one is
configured (still 501/again if none).

**This is the "hybrid" concept previously deferred** ("Hybrid is a future repo — not this
one"). Decision reversed by the user: fold it into the Local Bridge as **optional capability
providers**, not a separate repo. Phasing:
- **(1) provider abstraction + config + detection: DONE (2026-08-10).** `providers.py`
  (`capabilities()`, `dispatch_provider`/`reserve_provider` — Modbus-Bridge-REST→
  franklinwh-modbus-lib / FWHAI-REST→franklinwh-cloud-lib, `_probe_url`/`_lib_available`),
  config (`modbus_bridge_url`/`fwhai_url`/`modbus_host`/`fwh_cloud_*`), `GET /api/providers`.
  Live-verified against the real Modbus Bridge (:8100 → `modbus-bridge via rest`).
- **(2) Modbus dispatch provider: DONE (2026-08-10).** `providers.dispatch(action,
  power_w/power_pct, duration_s, target_soc)` delegates to the Modbus Bridge's stateful
  `POST /api/command` — stages `battery_command_power`/`_pct`/`_duration`/`_target_soc`
  then triggers `battery_command` (Force Charge/Discharge/Standby/Release). `POST /api/dispatch`
  (gated by allow_writes): 503 no-provider · 501 library path (deferred — the Bridge owns the
  watchdog) · 422 bad action · 502 provider unreachable. Live-verified 503/422 (no destructive
  write sent); library path intentionally raises NotImplementedError (dispatch without a
  watchdog is unsafe). Tests in `tests/test_providers.py`.
- **(3) Cloud provider for reserve-SoC WRITE: DONE (2026-08-15).** `providers.set_reserve(s,
  mode, soc)` routes to the franklinwh-cloud lib `updateSocV2` (`update_soc(requestedSOC,
  workMode, electricityType)`; workMode Self=2/TOU=1/Backup=3 by NAME), snapshotting the
  prior per-mode reserve first. `POST /api/cloud/reserve {mode, soc}`: 503 no-provider · 501
  FWHAI-not-wired · 422 bad mode/soc · 502 cloud error. UI: reserve editors on the Control
  tab (new "Reserve SoC" card) + the Dashboard "Operating Mode & Reserves" panel (inline
  input+Set), shown only when `/api/providers` reserve.available; read-only note + active-mode
  highlight otherwise. Config `FWH_CLOUD_EMAIL/PASSWORD/GATEWAY` (docker-compose). Verified:
  503/422 live (no creds), UI states render, no JS errors. Live cloud write pending user's
  creds + supervised test (production battery change). FWHAI-REST reserve path = Phase 3b.
- (4) UI provider badges (which capability is filled by what) — still pending.

**Safety:** dispatch is destructive + watchdog-gated — **delegate to the Modbus Bridge's
watchdog when available**; if using the library directly, replicate the software watchdog
(hardware revert is cosmetic — see the modbus bridge battery-control-ux doc). Reserve write
MUST go via the cloud provider (the local device silently discards 1405 — see the reserve
memory). Mode indices differ per channel — resolve by NAME (see the mode-index memory).
**Cross-ref:** API_COMPARISON hard walls, CLOUD-ALIGNED-API, RATERUDDER (another dispatch
consumer), MULTI-GATEWAY (providers are per-gateway).

---

## SCHEDULE-AND-AUTOMATIONS — clone the Modbus Bridge Schedule (orchestration = the schedule)

**Status:** planned — **Priority: HIGH** — **supersedes API-PARITY P8**; **absorbs the old
"DISPATCH-ORCHESTRATION"** (user: in the Modbus Bridge orchestration IS done by the schedule
— priority + if-already-controlled — with a FWHAI-Automations *subset* for conditions).
**Filed:** 2026-08-09 (user)
**Model:** the Modbus Bridge **Schedule & Automations** page (screenshots 2026-08-09) —
`gateway/scheduler.py` (`ScheduleEngine`), `scheduler_triggers.py` + `scheduler_conditions.py`,
`api/schedules_api.py` (CRUD / `/log` / `/timeline` / `/actions`).

Clone the whole page — scheduling + condition scripting + **orchestration in one engine**:
- **Entry (from the Edit-Entry screen):** name · **trigger type** (Recurring windows /
  One-time date) · quick-preset · date · **time windows** (multiple, `+ add window`) ·
  **ACTION** (Force Charge / Force Discharge / Force Standby / Release / Self Reserve % /
  TOU Reserve % / Operating Mode) with **power W / %** · **ENTRY CONDITIONS** (gate — must
  hold to fire; Match ALL/ANY; rows + groups) · **EXIT CONDITIONS** (first true ends the
  window) · **TARGET** (gateway / service / site) + gateway · **ON EXIT / RELEASE** (restore
  prior mode / …) · **IF ALREADY CONTROLLED** (defer / override / wait) · **PRIORITY** ·
  enabled.
- **Orchestration = the engine**, not a separate layer: `priority` + `if-already-controlled`
  (defer/override/wait) + `on-exit/release` arbitrate between entries (and other brains). No
  standalone "who's in charge" module — the schedule owns it.
- **Conditions = a FWHAI-Automations *subset*** — a live-evaluated language over device
  state, e.g. `battery.soc_pct<30`, `grid.connected==1`, `time.hour>=18`,
  `pv.is_generating==False` (as seen in the activity log's `entry gated:` lines). Entry gates
  + exit criteria; port `scheduler_conditions`/`scheduler_triggers`.
- **Page**: **24-hour visual timeline** (colour per action + Native TOU/mode + automation-fire
  markers, day tabs) · connection/outage strip · **Entries** table (name / when / action /
  conditions / target / next-fire / run·edit·delete) · **Activity Log** (fired / executed /
  gated / missed / exit-condition-met, with the gate expression + live values).
- **Actions dispatch via the providers:** Force Charge/Discharge/Standby/Release + target-SoC
  → **HYBRID-CAPABILITIES** Modbus provider; Self/TOU Reserve % → Cloud provider; Operating
  Mode / off-grid / smart-circuit → local sendMqtt; plus **PAUSE/RESUME RateRudder / FWHAI
  Smart Dispatch** as scheduled/conditional actions (coordinate the external brains from
  within the schedule).
- **Multi-gateway** (target gateway/service/site) + persist to the P5 SQLite
  `schedules`/`schedule_log`; hot-reload; REST CRUD/log/timeline.

Coordinate with the modbus-bridge owner (shared engine / possibly a shared scheduler lib).
Depends on HYBRID-CAPABILITIES (actuation) + RATERUDDER (pause/resume).

---

## DASHBOARD-PERF — operating-mode section flickers + dashboard slow to load (DEFECT)

**Status:** DONE (2026-08-08). Poller now caches the full last-good summary
(`BridgeState.last_summary`, last-good values + current ok/stale); `/api/summary`
serves it (`cached` flag) instead of a fresh device session per browser poll; frontend
keeps last-good mode/power. Result: `/api/summary` ~5–7 ms (was seconds), mode section
never blanks (no flicker), connectivity still shown via ok/stale. Values refresh at
`poll_interval` (30 s) cadence. 88 tests; verified on demo mock + real container.
**Priority was: HIGH.**
**Filed:** 2026-08-08 (user-reported)

**Symptom:** the "Operating Mode & Reserves" section keeps refreshing/disappearing
(flicker), and the whole dashboard is slow to load.

**Root cause (diagnosed, read-only):** `GET /api/summary` does a FULL fresh device
session on **every browser poll** — `client.summary()` = login + power_flow (1301) +
mode_list (1726) + der_comms (1205) + firmware, sequential round-trips — and the
dashboard polls it **every 5 s** (`app.js` `setInterval(poll, 5000)`). Over the
aGate's flaky wifi these are slow / time out / return `ok:false`. When a poll is
slow or `ok:false`, `summary.mode` is missing so the mode table renders empty →
**blanks then repopulates → flicker**; the first load is a cold multi-round-trip →
**slow**. The poller ALREADY reads the device every `poll_interval` (30 s) and caches
`state.last_state`, but `/api/summary` ignores that cache and re-hits the device — so
there's redundant per-5 s device thrash.

**Fix (do NOT implement yet):**
- Cache the **full last-good summary** in the poller: add `BridgeState.last_summary`
  (updated every `poll_interval`), and serve `/api/summary` from it — **instant**, no
  per-request device hit. Seed it once at startup; fall back to a fresh read only when
  the poller isn't running (metrics+mqtt both off). This removes the thrash and makes
  the dashboard load instantly once the poller is warm.
- Frontend **keep-last-good**: never blank the mode table / cards on `ok:false` or a
  missing `summary.mode` — retain the previous values and show a subtle "reconnecting"
  hint (the energipays restyle did this; the family-shell rewrite regressed it).
- Optional: decouple the slow-changing mode/reserve table from the 5 s tick (it
  changes rarely) and/or align the browser poll to the poller cadence.
- Ties into MULTI-GATEWAY (per-gateway cached summary) and R2 (poller lifecycle).

---

## REFRESH-SETTINGS — configurable polling + dashboard refresh rates

**Status:** planned — **Priority: MEDIUM**
**Filed:** 2026-08-08 (user request)

Two distinct rates, one already a setting, one hardcoded — expose both and make the
relationship clear (esp. after the DASHBOARD-PERF cache fix):

- **Device poll cadence (`poll_interval`, server-side): already exists** (env
  `POLL_INTERVAL` / HA option, default 30 s) but is NOT shown in the Settings UI and
  needs a restart. Since `/api/summary` now serves the poller's cache, `poll_interval`
  IS the effective **data-freshness** knob (how often values actually change). Surface
  it in the Settings tab (read now via `/api/settings`; making it live-editable is
  P7 / A6 settings-write) and note "restart to apply".
- **Dashboard/browser refresh rate: hardcoded** — `app.js` `setInterval(poll, 5000)`
  (summary) + `60000` (history). Make configurable. Because the summary poll now just
  reads a cheap cache, a faster browser refresh is low-cost; it only controls how
  quickly the UI picks up cache updates + connectivity (ok/stale). Best as a
  **client-side localStorage preference** (live, no restart) with a Settings control;
  optionally a server default too. Add a separate history-refresh control.

Design note: browser refresh faster than `poll_interval` just re-reads the same cached
summary — so the UI should make clear that *freshness* = `poll_interval` and *refresh
rate* = how often the browser re-checks. Pairs with UNITS-DISPLAY + the Settings-write
work (P7/A6). Guard sane bounds (e.g. poll_interval ≥ 5 s; browser refresh ≥ 2 s).

---

## SETTINGS-RICHNESS — bring Settings up to the Modbus Bridge's depth

**Status:** planned — **Priority: MEDIUM**
**Filed:** 2026-08-09 (user: "Modbus settings are extensive and rich")
**Reference:** the Modbus Bridge Settings page (screenshots 2026-08-09).

Our Settings is a read-only summary + a small live-edit whitelist. The Modbus Bridge's
is a full control surface. Bring ours toward it (respecting local hard walls):
- **Gateways table + CRUD** — name/host/serial/model/enabled-toggle/last-poll + Add/Test/
  Edit/Enable per row. = **MULTI-GATEWAY Phase 3** (already backlogged) — this is the home
  for it.
- **Publishing Groups** — control which MQTT entities are published (+ New Group,
  enable/disable, membership). NEW: an MQTT entity-grouping layer over `publish/entities`.
- **Entities browser** — table of published entities (slug/name/**source raw key**/type/
  value, filter, topics toggle). We have `/api/mqtt/entities` (8) in the MQTT tab; enrich to
  this depth (source raw key via the field schema, filter).
- **MQTT Broker card** — connection/host/port/user/TLS/prefix/discovery/**messages sent**/
  discovery-published/entity-count + Edit/**Republish/Unpublish**. Mostly have; add
  messages-sent + Edit.
- **Modbus/sendMqtt Poller status** — status/**polls completed**/last poll/last error.
  NEW: track poll stats in the poller + expose (also feeds the dashboard Bridge-Status
  card idea).
- **Metrics Storage config** — editable **retention (days)** + **raw full-resolution
  (days)** + **Archive Now**. We have P5 metrics + read-only retention; make editable
  (P7 settings-write) + add a raw→archive window + Archive-now (extends P5's single-table
  model toward raw+archive).
- **Database Storage** — per-table **rows + span + size**. NEW: a `/api/db/stats`
  endpoint over the SQLite metrics DB + a card.
- **System Setup** (Whole-Home Backup / Grid-Forming / Generator / Load-Shedding / Solar
  type) — PARTIAL locally via `install_profile` (1701: electricSys, gridPhase*, solar*,
  fhpRatePower) + `generator` (1901); surface what local exposes.
- **Electricity Utility Service(s)** (meter/account/AC-service/amperage/tariff) — largely a
  cloud/portal feature; local has only `install_profile` bits (airSwitchCur, electricSys).
  Mostly OUT OF SCOPE (see CLOUD-ALIGNED / hard walls) — don't fake tariff/account data.

---

## UI-PARITY — Modbus Bridge for LOOK, FWHAI for CONTROLS/functionality

**Model split (clarified by user 2026-08-08):** keep the **Modbus Bridge** as the model
for the **UI shell / look & feel** (done — sidebar/topbar/soc-ring/design-system, green),
BUT model **Controls and functionality on FWHAI** — it has closer parity (FWHAI is the
cloud FranklinWH control app; its mode-cards / quick-access / battery-status UX matches
what the local API can actually do, unlike the Modbus register control surface).

**Dashboard parity pass DONE (2026-08-09):** Battery card (run status, ambient temp,
per-module SoC/power from power_flow fhpSn/fhpSoc/fhpPower), Today's Energy card (daily
kwh_*), Live Points collapsible panel (on-demand `/api/cmd/power_flow`), kW/W + °C/°F/both
display units (Settings → Display), history 12h+30d + Export CSV + Expand. Only
local-exposed fields — SoH/cabinet temp/kWh nameplate/max-charge deliberately NOT shown.

**Remaining (Priority: MEDIUM):**
- **CONTROLS → FWHAI model.** Align the Control tab + functionality with the FWHAI
  Control page (mode-cards + Quick-Access shortcuts + Battery-Status-with-reserves +
  the local-capable actions: mode / off-grid / smart-circuit). NOT the Modbus dispatch
  card (force charge/discharge/target-SoC = hard wall). Reserve display is read-only
  (cloud-owned).
- **Overlays / Events** on Power History — deferred (no local event data source).

**Filed:** 2026-08-08 (user request)
**Reference:** the Modbus Bridge dashboard (screenshot 2026-08-08, dark theme):
- Richer **Battery** card — DC power, SoC, **SoH**, **Available / Rated kWh** nameplate,
  **Max Charge / Max Discharge W**, **Ambient / Cabinet temps**.
- **Live Points** collapsible panel (raw point list).
- **Power History** with `12h/…` range, **Export / Overlays / Events / Expand**, kW axis.
- Optional register/point annotations (e.g. `713.SoC`, `ext.15507`) — Modbus-specific.

**Caveat (hard walls — see CLOUD-ALIGNED-API / API-PARITY):** several Modbus-Bridge
dashboard features are **not reachable over the local API** and must NOT be cloned as
fake UI — the Battery Control card (force charge/discharge W/%, target-SoC), the kWh
nameplate + SunSpec register point refs, and inverter register-level electricals are
Modbus/SunSpec-only. Parity here = **layout/UX + the fields local CAN serve**
(battery SoH/temps IF a local cmdType exposes them — e.g. ibg_state/battery_inhibit;
Live-Points-style raw view over `/api/cmd/*`; the Export/Overlays/Events history
affordances), NOT the register control surface.

---

## DEVICE-TAB-REWORK — make the Device tab actually useful (details + export)

**Status:** DONE (2026-08-11/13). Two-pane master/detail (list left, sticky scrollable
output right); schema-labelled + grouped rows from `fieldschema.py` (`/api/schema`) with a
raw-key `</>` toggle + `cmd NNNN`; JSON/CSV export per reading + Export-snapshot; array-of-
objects (mode_list/devMap) and nested objects (grid_profile compliance sections) render as a
recursive breadcrumb hierarchy (nothing squished); explicit empty/error states + Retry;
slow reads marked + 35s timeout; digital IO (doStatus/diStatus) labelled per line.
**Filed:** 2026-08-09 (user feedback)

The Device tab today is **pointless as-is** — it's just grouped buttons that dump raw
JSON on click; it shows nothing useful about what each endpoint is or its data.

**Rework:**
- For each `/api/cmd/<name>` entry, show **what it is** (the description/purpose from the
  library `catalog` — the CmdInfo name + description) so the list is self-explanatory
  before clicking.
- **On click, show the details** properly — parsed/labelled key-values (not a raw JSON
  blob), grouped/readable, with units where known; keep a "raw JSON" toggle for power
  users.
- **Export option** per endpoint (download the response as JSON, and CSV where tabular)
  — and/or an "export all" for a device snapshot.
- Consider surfacing the catalog descriptions via a small `/api/catalog` endpoint (name
  + description + read/write) so the UI can label endpoints without hardcoding.
- Keep it on-demand + gateway-scoped (`?gateway=`), as now.

**Model + reusable resource (user-provided 2026-08-09): `franklinwh-cli schema --live`.**
The FWHAI/cloud CLI renders every field as **Python attr · raw API key · source · units ·
live value**, grouped into sections (Power Flow / Grid State / Mode / Battery Packs /
Environment / Relays / Connectivity / TOU Window / Smart Circuits / Totals …). That is the
exact display the Device tab should mimic.
- **The metadata table already exists**: `franklinwh-cloud/franklinwh_cloud/cli_commands/
  schema.py` — `CURRENT_SCHEMA` / `TOTALS_SCHEMA` / `MODE_SCHEMA` / `TOU_SCHEMA` /
  `GRID_LIMITS_SCHEMA`, each `field → (raw_key, source, units, group)`
  (e.g. `"battery_use": ("p_fhp","203/runtimeData","kW","Power Flow")`).
- **Its raw keys == the local `power_flow` (1301) keys** (`p_sun/p_fhp/p_uti/p_load/soc/
  fhpSn/fhpSoc/fhpPower/t_amb/main_sw/pro_load/kwh_*` …). So port (or ship as data) that
  raw-key → (label, units, group) map and drive the Device tab / Live Points: render each
  local cmdType response **grouped + labelled + unit-aware** (respecting the kW/°F prefs),
  with the raw key shown too and a JSON toggle + export. For cmdTypes outside the schema
  (network/wifi/grid_profile/install_profile…), fall back to the library `catalog`
  cmdType description + raw field display.
- Bonus: the same map cleanly labels the dashboard **Live Points** panel and could back a
  `/api/schema` endpoint. Note the cloud schema is a **superset** (adds 211 electrical /
  311 smart-circuit / get_tou_info / power-control fields the local API may not expose) —
  label what local returns, don't invent the rest.

---

## POWER-HISTORY-CHART — distinct colours + friendly labels (align to Modbus/FWHAI)

**Status:** DONE (2026-08-09). Battery cyan / Grid red / Solar amber / Home violet /
SoC green (all distinct — soc & battery_w were both green), labels Battery/Grid/Solar/
Home/SoC %. `renderChart` `dsPower(label,key,color)`.
**Filed:** 2026-08-09 (user)

The Power History chart legend uses raw keys and duplicate colours: `soc` and
`battery_w` are BOTH green (`#22c55e`), `grid_w`/`load_w` are near-identical — the lines
are indistinguishable.
- **Distinct colours per series** (align to the Modbus Bridge / FWHAI legend): Battery
  cyan (`--live #06b6d4`), Grid red (`--danger`), Solar amber (`--solar`), Home/Load
  violet (`--load`), SoC green (`--ok`, on the right axis). No two the same.
- **Friendly English labels** instead of raw keys: `battery_w`→"Battery", `grid_w`→"Grid",
  `solar_w`→"Solar", `load_w`→"Home", `soc`→"SoC %" — matching Modbus Bridge (Battery/
  Grid/Solar/Home) + FWHAI. (Fix in `app.js` `renderChart` `ds()` labels + colours.)

---

## SMART-CIRCUITS-TAB — FWHAI-style Smart Circuits sidebar tab

**Status:** planned — **Priority: MEDIUM**
**Filed:** 2026-08-09 (user). **Local API fully supports this (confirmed).**

Add a **Smart Circuits** sidebar tab modelled on FWHAI's. The local sendMqtt API has the
full surface (mirrors the cloud's 310/311):
- **State + config** — `smart_circuits` (1409): per-switch `SwXName`, on/off `SwXMode`,
  SoC cutoff `SwXSocLowSet`, auto `SwXAtuoEn`, `SwXProLoad`, `SwMerge`, and the schedule
  (`SwXTimeEn[]`/`SwXTime[]`/`SwXTimeSet[]`, `SwXFreq`). 3 switches (Sw1–3) + EV (`CarSw*`).
- **Live metering** — `smart_circuit_meter` (1411): per-switch V/I/power/energy.
- **Schedule** — `smart_circuit_schedule` (1401) + the SwXTime* fields.
- **Writes (gated)** — `set_smart_circuit` toggle on/off (1409 opt:1 RMW — **already
  live-verified**); SoC-cutoff + schedule modify are the same full-block RMW (extend the
  library `set_smart_circuit` / add helpers).

Build: a tab with per-circuit cards (name, on/off toggle, live power/energy, SoC cutoff,
schedule view/edit), gateway-scoped + `allow_writes`-gated, mode-cards/quick-access UX per
FWHAI. Reuse the cloud-aligned `/api/cloud/smart-circuits` (read) + a gated write endpoint
(promote the generic call — see API-PARITY P9). Retrieve/display/modify schedules.

---

## TOU-TABLE — render the TOU tariff-period energy arrays as a table

**Status:** planned — **Priority: LOW**
**Filed:** 2026-08-09 (user)

The `sharp`/`peak`/`flat`/`valley` TOU-period energy fields are 7-element arrays (shown
today as raw arrays in the Live Points "TOU" group). Render them as a **table**: rows =
tariff tiers (Sharp/Peak/Flat/Valley), columns = the 7 energy categories (likely grid-in/
grid-out/solar/gen/batt-discharge/batt-charge/home — confirm the index meaning against a
live aGate / the app). Much more readable than raw arrays. Small, display-only.

---

## UNITS-DISPLAY — kW/W toggle + °F/°C temperature display

**Status:** planned — **Priority: MEDIUM**
**Filed:** 2026-08-08 (user request)

A user preference (persist in localStorage + a Settings option) for:
- **Power units:** kW instead of W (÷1000, ~2–3 sig figs) across the power-flow cards,
  the history chart Y-axis + legend, and any W fields. Default W; kW opt-in.
- **Temperature:** for US users, show °F (convert `°C×9/5+32`) or **dual-display
  °C/°F**. Applies to any temp fields surfaced (ambient/cabinet — via a local cmdType
  such as ibg_state / power_flow t_amb, once shown). Default °C; °F opt-in.
Pairs with UI-PARITY-MODBUS (whose Battery card would carry the temps) and the
Settings-write work (A6/P7) for persisting the preference server-side too.

---

## CLOUD-ALIGNED-API — local endpoints FWHAI can call first, cloud as fallback

**Status:** Phase 1 + 2 + WRITES DONE (2026-08-08). Shipped 9 `/api/cloud/*` reads
(stats, smart-circuits(+/info), reserves, tou, runtime, power-info, device-info,
network) + 4 aligned writes (set-mode, grid-status, smart-circuit/state,
reserve→501). Remaining:
- `get_mode` (aggregates composite 203 + TOU — several local reads).
- **Live-verify the smart-circuit write** on a real aGate (built + read-back-safe,
  but `hardware_verified:false` — the aGate was offline). The runtime read-back
  refuses to claim success unless confirmed; may be delayed-apply like der_comms.
- Confirm 1301 daily-kWh keys for `Stats.totals`; power-info electrical + runtime
  temps are local hard-gaps (defaulted, not faked).
- Then the FWHAI-side local-first/cloud-fallback wiring (separate repo).

> **Mode-index correctness rule (do not violate):** cloud `workMode` is
> **TOU=1 / Self=2 / Backup=3**; the local API's `oldIndex` is Modbus-style
> **Backup=1 / Self=2 / TOU=3** (only Self matches). ALWAYS resolve modes by NAME /
> `scheduling_type` (== cloud workMode), never reuse a number as a local index — else
> a set-mode switches to the WRONG mode. Guard test:
> `test_cloud_set_mode_uses_cloud_numbering_not_oldindex`.
**Filed:** 2026-08-07
**Shipped (Phase 1):** `cloud_compat.py` + `GET /api/cloud/{stats,smart-circuits,
smart-circuits/info}`. `Stats` shape from `power_flow` (1301) with core live fields
mapped + extended fields defaulted; smart circuits a faithful replica of
`SmartCircuitDetail.from_api_payload` from `smart_circuits` (1409). Fidelity is
TESTED against the real `franklinwh-cloud` dataclasses (Current 89-key / Totals
17-key parity + SmartCircuitDetail exact equality). 502-on-miss = the fallback
signal for FWHAI. **Follow-up:** confirm 1301 daily-kWh raw key names on a live
aGate to fill `Stats.totals` (defaulted 0 today).
**Foundation:** `franklinwh-local/docs/CLOUD_MAPPING.md` already maps every local
cmdType ↔ cloud API method/REST code — it IS the spec for this. Cloud contract =
`franklinwh-cloud` (`~/dev/franklinwh-cloud`, `franklinwh_cloud/client.py`).

**Goal:** expose a **cloud-aligned REST facade** on the bridge so FWHAI (and any
`franklinwh-cloud` consumer) can call the **local bridge first** and **fall back to
the Cloud API** on miss/failure. Local-first wins: lower latency, no cloud
rate-limits (the FranklinWH cloud is throttled — FWHAI actively manages that),
works on the LAN when the internet/cloud is down, cuts cloud dependency.

**Design (bridge side, this repo):**
- A `/api/cloud/*` compatibility layer whose **response shapes mirror the
  `franklinwh-cloud` client methods**, each translating a local cmdType read into
  the cloud's field names (per CLOUD_MAPPING.md). Start with the user's named set:
  - `get_stats` / composite (cloud cmdType 203) ← local `power_flow` 1301
  - **smart circuits** `get_smart_circuits_info` (310/311) ← local `smart_circuits`
    1409 + `smart_circuit_meter` 1411
  - then: `get_runtime_data` ← 1707, `get_power_info` ← 1709, `get_mode` ← 1403,
    `get_all_mode_soc` / reserves ← 1405 (read), `get_gateway_tou_list` ← 1407,
    `get_device_info` ← 1115, `get_grid_profile_info` ← 1203/1211-1229/1251-1277,
    `get_bms_info` ← 1831 + `battery_modules`, `get_network_info` ← 1117.
- **Writes:** align the ones the local API can actually do (`set_mode` ← 1727,
  off-grid ← 1723, smart-circuit ← 1409) and route them local. **Reserve-SoC write
  must NOT pretend to be local** — it's cloud-owned (device discards the local
  write); a cloud-aligned reserve write has to pass through to the cloud fallback.
  See the hard-walls note under API-PARITY.
- **Fidelity testing:** assert the facade's output matches `franklinwh-cloud`
  response shapes using that repo's fixtures/schemas; the new **dynamic emulator**
  lets this run hardware-free.

**Consumer side (FWHAI repo — separate, note only):** add a "local bridge primary,
cloud fallback" path to FWHAI's cloud client — try the bridge (health-gated /
short timeout) and fall back to the Cloud API on any miss. That switch lives in
FWHAI, not here; this repo's job is to offer the aligned contract.

**Effort:** moderate–large. Per-endpoint field translation is mechanical, but
needs shape fidelity vs the real cloud responses. Sequence: (1) `get_stats` +
smart circuits (named priorities) → (2) runtime/power/mode/reserves/tou reads →
(3) aligned writes (mode/off-grid/smart-circuit) → (4) FWHAI local-first wiring.
Pairs well with MULTI-GATEWAY (FWHAI targets a gateway) and MOCK-SIMULATOR (test
the shapes without hardware).

---

## MOCK-SIMULATOR — dynamic fake aGate(s) for dev, demo, and multi-gateway testing

**Status:** core DONE (2026-08-07) — dynamic emulator + demo mode shipped;
remaining below.
**Filed:** 2026-08-06

**Remaining / demo :8102 gaps (user-reported 2026-08-09):** the emulator only
simulates `power_flow` (1301, and only the basic flow keys) + `mode_list`/`login`
dynamically — everything else returns `{opt:0, result:0}`. So on the demo the
Battery card shows "Modules —" / "No per-module detail", the Today's-Energy card is
all `—`, and Device-tab endpoints like `device_info`/`relay_status`/`solar_pv`/
`battery_modules` render nothing (and JSON export of them writes an essentially-empty
file — "did not seem to work"). To make the demo represent the real UI:
- Extend `SyntheticSite` (library) to emit the RICH `power_flow` fields the real aGate
  has — `t_amb`, per-module `fhpSn`/`fhpSoc`/`fhpPower`, daily `kwh_*`, `main_sw`,
  `pro_load`, `sharp/peak/flat/valley` — so Battery/Energy/Live-Points populate.
- Simulate the other read cmdTypes: `device_info` (1115), `relay_status` (1709),
  `battery_modules` (1831), `solar_pv` (1903), `smart_circuits` (1409),
  `smart_circuit_meter` (1411), `ibg_state` (1827), `mode_soc` (1405), `tou_schedule`
  (1407) — believable values so the Device tab + Battery card are fully populated.
- **"Insane" chart fix (root-caused 2026-08-09):** `SyntheticSite.__init__` sets
  `tz_offset_hours = rng.randint(-11, 12)` — a RANDOM ±12 h offset per seed — and
  `local_hour()` is pure epoch math, so each mock's solar/mode day lands at a random
  wall-clock time (solar producing 2600 W at 9:30 PM). Fix: align the synthetic day to
  the VIEWER's local time — set `tz_offset_hours = 0` (small deterministic ±1–2 h jitter
  at most for multi-gateway variety) and derive the hour from LOCAL time (container `TZ` /
  `datetime.fromtimestamp`), giving the demo containers the host TZ (compose `TZ` env).
  Demo-only cosmetic — the real aGate history is real.
- Also an emulator-boot integration test + the N-mock roster demo once MULTI-GATEWAY.
- Minor UX: Device-tab export/render should toast "nothing to export / empty response"
  when a cmdType returns only `{opt,result}` (empty), instead of silently writing an
  empty file with no on-screen feedback.
**Model:** the Modbus Bridge's `gateway/mock_gateway.py` (`synthetic_points()`) —
dynamic, per-gateway-seeded, time-of-day simulation.

**What exists now:** the **library** already ships a fake sendMqtt broker —
`franklinwh-local emulate` → `franklinwh_local/emulator.py` — a real TCP/9000
broker the bridge talks to unchanged (`FWH_HOST=127.0.0.1`). But its replies are
**static/canned** (soc frozen ~66.5, fixed flows), so it proves the protocol but
makes a lifeless demo and can't exercise charge/discharge/mode transitions.

**The gap — make it dynamic (library work, `franklinwh-local`):** port the
Modbus Bridge's `synthetic_points()` model into the emulator so a mock aGate emits
believable, moving data: solar half-sine (dawn→dusk + slow cloud ripple), battery
charging on solar surplus / discharging in the evening, SOC integrated across the
day, temp drift, operating-mode blocks (Self-Consumption day / TOU evening /
Emergency Backup overnight), grid following/forming. **Per-instance seed** (by
port or a `--seed`/`--serial` arg) so multiple mocks read as distinct sites with
unique `IBG_SN`. Keep the static/pcap mode as a fallback.

**Bridge side (this repo):**
- A **demo / mock mode**: a `docker-compose` profile (or a compose override) that
  launches N emulator instances on different ports + the bridge pointed at them —
  so the whole UI (Dashboard/History/Control/Device) shows live-looking data with
  **zero hardware**. Great for screenshots, onboarding, and UI work.
- This is the **enabler for MULTI-GATEWAY testing** — spin up 2–3 seeded mocks and
  exercise the roster / selector / per-gateway poller / metrics `gateway_id`
  without owning multiple aGates. Build the dynamic emulator before (or alongside)
  MULTI-GATEWAY Phase 1. See [[MULTI-GATEWAY]] below.
- Optionally an integration test that boots an emulator and asserts the bridge's
  reads/writes round-trip (CI without hardware).

**Effort:** moderate. The dynamic-simulation core is ~1 function ported from
`mock_gateway.py` into the library emulator; the bridge side is compose plumbing.
**Split:** dynamic emulator = `franklinwh-local` repo; demo mode/compose + tests =
this repo.

---

## MULTI-GATEWAY — support users with more than one aGate

**Status:** Phase 1 DONE (2026-08-08) — reads/monitoring. Registry (`GatewayState` +
ordered registry, `get_state()` = default), `fwh_hosts` config, one poller per gateway
(own host/serial/MQTT node + last-good cache + metrics `gateway_id`), `GET /api/gateways`
roster + `GET /api/gateways/{id}/summary`, topbar selector (hidden when ≤1). Single-gateway
unchanged. 99 tests; verified against 2 seeded mocks (Home/Shed, distinct serials/SoC/mode).
**Phase 2 DONE (2026-08-08):** every device read/write scopes via `?gateway=<id>`
(`_gw_host`/`_gw_or_404`; host threaded through all client fns); UI tabs
(Control/Device/MQTT/History) scope to the selected gateway (Control writes = safety);
`GET /api/site/status` aggregates. 107 tests; verified live on 2 mocks incl. write-routing
(set-mode?gateway=Shed hit Shed, not the default). Single-gateway unchanged.
**Remaining — Phase 3:** runtime add/remove/restart CRUD + persist the roster to SQLite
(`gateways`/`gateway_state` tables) + discovery-assisted onboarding UI. (Also: no UI caller
yet for the scoped cloud set-mode/grid-status/smart-circuit endpoints — wire if wanted.)
**Filed:** 2026-08-06
**Model — adopt the Modbus Bridge's proven design** (`~/dev/Claude/Projects/
franklinwh-modbus-bridge`, `gateway/registry.py`, `gateway/instance.py`,
`gateway/aggregator.py`, `api/gateways_api.py`, `store/db.py`). It already does
exactly this; port the shape to the local API.

Today the bridge is hard single-gateway: one `fwh_host`, one `run_poller` loop, one
`BridgeState`, one MQTT node. A user with two aGates (two properties, or paralleled
systems) can only see one.

Good news — the MQTT/HA side already namespaces cleanly: the node id is derived
from the aGate serial (`IBG_SN`, unique + stable), so multiple gateways publish as
distinct HA devices with no collision. Most of the work is on the bridge side.

**Architecture (mirrors the Modbus Bridge):**
- **`GatewayRegistry`** (their `gateway/registry.py`) — DB-backed manager with
  `start_gateway(id)` / `stop_gateway(id)` / `start_all()` / `stop_all()`, holding a
  live `GatewayInstance` per gateway. Brought up in the FastAPI lifespan (their
  `main.py::_bring_up_gateways` iterates `get_gateways(db)` and starts each).
- **`GatewayInstance`** (their `gateway/instance.py`) — our current `run_poller`
  refactored to **one instance per gateway**: its own poll loop, MQTT publisher
  (node = serial), re-discovery, and last-state. `start()`/`stop()` so gateways can
  be added/removed at runtime without restarting the app.
- **Registry state → SQLite** (their `store/db.py`): a `gateways(id, name, host,
  port, enabled, created_at)` table + `gateway_state(gateway_id, conn_state,
  last_ok_ts, last_error)`. Key by a stable `id`; **adopt the serial as identity**
  once logged in (host drifts on DHCP — per-gateway re-discovery handles it, which
  we already have). Every data row carries `gateway_id`.
- **Scoped REST** (their `api/gateways_api.py`): `GET/POST /api/gateways`,
  `GET/PATCH/DELETE /api/gateways/{id}`, lifecycle `POST .../{start,stop,restart}`,
  `POST .../test`, and scoped reads/writes `/api/gateways/{id}/{summary,power,
  cmd/*,mode,offgrid,...}`. Keep the current unscoped endpoints as an alias for the
  **primary/default** gateway so the single-gateway case stays zero-friction.
- **Site aggregation** (their `gateway/aggregator.py` + `GET /api/site/status`) —
  one roll-up across all gateways for the roster view.
- **Metrics (touches P5).** Add a `gateway_id` column to the `metrics` table + a
  `?gateway=` filter on `/api/metrics`. **Do this migration early** — cheap now,
  annoying after a lot of single-gateway rows accumulate.
- **Config / onboarding.** Add gateways via `POST /api/gateways` (host + label);
  `discover.scan()` already finds every aGate on the subnet → discovery-assisted
  onboarding. Keep `fwh_host` as the single-gateway shorthand that seeds one row.
- **UI.** Topbar gateway selector (their family shell has it; FWHAI's "GATEWAY FHP"
  dropdown) — Dashboard/Control/Device/History scoped to the selection; a roster/
  site view for all gateways.
- **Writes.** Gateway-scoped and still `allow_writes`-gated.

**Suggested phasing:** (1) `gateways` table + `GatewayRegistry`/`GatewayInstance`
refactor of `run_poller` + `/api/gateways` roster + topbar selector for **reads**;
(2) gateway-scoped **writes** + metrics `gateway_id` column + `/api/site/status`;
(3) lifecycle (add/remove/restart at runtime) + discovery-assisted onboarding UI.

**Dependency:** best built on P5's SQLite (the registry + gateway_state want to
persist). **Effort:** significant — this is the single biggest architectural change
on the roadmap. Single-gateway stays the default and must remain friction-free.

---

## RATERUDDER-INTERFACE — interface to the RateRudder third-party cloud scheduler

**Status:** planned (research-first) — **Priority: LOW–MEDIUM**
**Filed:** 2026-08-08 (user request)
**Ref:** https://github.com/raterudder/raterudder
**API captured (2026-08-09):** real HAR of raterudder.com decoded — the endpoint contract,
response shapes, and the Apple/Google-SSO→session-cookie auth are documented, plus a
**shared `raterudder` client-library plan (to build in coop with the modbus bridge)**, in
`docs/RATERUDDER_LIBRARY_PLAN.md`. Auth is the hard part: SSO ID-token → `/api/auth/login`
→ cookie; v1 = user-supplied session, v2 = interactive OAuth via the public clientIDs.
RateRudder actuates via the **FranklinWH cloud** and **stores the user's FranklinWH cloud
credentials** — so a bridge integration is read-first (forecast/history/settings); local
execution of its plan is modbus-bridge territory (dispatch = hard wall locally).

**Scope (user, 2026-08-09):** RateRudder is **smarter than the native FranklinWH TOU
scheduler**, so:
- **Expose it** — query forecast/plan + actions/$-savings + settings and publish as **HA
  sensors / metrics + automation inputs** (read-first).
- **Auth via long-lived API token** — requested from the author; once available it's the
  PRIMARY auth (no SSO dance). Design the lib's auth backend pluggable (token→cookie→OAuth).
- **PAUSE/RESUME orchestration** — `pause()`/`resume()` via `settings.pause` so the bridge's
  automations run in concert (pause RateRudder, act, resume). Part of DISPATCH-ORCHESTRATION.

**What RateRudder is:** a cloud energy-optimizer (Go 1.25 + React, GCP Cloud Run +
Firestore + Terraform) that optimizes battery charge/discharge for FranklinWH / Tesla
Powerwall against **real-time + TOU electricity pricing** and **weather forecasts**
(Open-Meteo; 25+ utilities: ComEd/Ameren/PJM/MISO). Cloud-Scheduler-driven: periodic
`POST /api/update` runs its ESS-control decision logic, then actuates the battery
(today via the FranklinWH **Cloud API**). HTTP API on :8080, OIDC/IAP auth.

**The value + the honest limit:** RateRudder's core action is **battery dispatch**
(charge/discharge to a price signal) — which the **local API cannot do** (hard wall:
force charge/discharge W/% + target-SoC are Modbus/cloud only; reserve-SoC write is
cloud-owned). So a bridge↔RateRudder interface is real but **partial**: the bridge can
serve RateRudder fast **local reads** and the **local-capable writes** (mode switch /
off-grid / smart-circuit), but the price-driven dispatch itself still needs the cloud
path. Don't promise full local dispatch.

**Integration options (needs a spike to nail RateRudder's actual control contract —
read its `controller` module + `/api/*`):**
- **A — Bridge as RateRudder's local data source.** Point RateRudder at the bridge's
  **cloud-aligned facade** (`/api/cloud/stats|runtime|reserves|mode|...`) instead of the
  FranklinWH Cloud API for live state — faster, no cloud rate-limits, works on the LAN.
  Cheapest win; builds directly on CLOUD-ALIGNED-API. May need a thin shape/auth adapter
  to match what RateRudder expects.
- **B — Bridge as a (partial) actuator.** Accept RateRudder's decisions and apply the
  **local-capable subset** (mode/off-grid/smart-circuit via the gated cloud-aligned
  writes); **pass dispatch + reserve through to the cloud** (same 501/fallback pattern as
  the reserve write) since local can't. Requires mapping RateRudder's action vocabulary
  → bridge endpoints.
- **C — Bridge consumes RateRudder's schedule.** Read RateRudder's computed plan and
  apply the local-capable actions on our own scheduler (ties into API-PARITY P8).

**Dependencies / notes:** builds on CLOUD-ALIGNED-API (facade) and the hard-wall reality
(see that entry + the mode-index memory). Auth (OIDC/IAP) and running RateRudder's GCP
stack are prerequisites for real testing — the dynamic emulator + demo mode can stand in
for the FranklinWH side. Start with a **spike**: read RateRudder's control API contract,
decide A vs B/C, and confirm which of its actions map to local-capable writes vs
cloud-only dispatch.

---

## HA-ADDON — install, Supervisor auto-config, MQTT integration, notifications

**Status:** planned (partial scaffolding exists)
**Filed:** 2026-08-06
**Model:** the **energipays-bridge** HA setup (`~/dev/Claude/Projects/energipays-bridge`)
— its `config.yaml`, `environment.py`, `ha_supervisor.py`, `api/mqtt_api.py`
(`discover_broker`), `docker-entrypoint.sh`. Same add-on shape, simple version.

Goal: install as an HA Supervisor add-on that configures itself — MQTT broker and
notifications with **zero typed credentials** — plus HA notifications now and
actionable notifications later.

**Already in place (do not redo):** `config.yaml` (ingress 8101, `hassio_api: true`,
`services: [mqtt:want]`, `homeassistant_api: true`, `map: [data:rw]`, options+schema),
`build.yaml`, `repository.json`, `docker-entrypoint.sh` → `ha_options.py`
(`/data/options.json` → env for pydantic-settings), and `notify.py` (non-actionable
notifications via `SUPERVISOR_TOKEN` → `http://supervisor/core/api`, zero config).

**The gaps to build:**

- **A1 — Environment detection.** Add an `environment.py` (`IS_HA_ADDON` from
  `/data/options.json`; `docker` from `/.dockerenv`; else `dev`; data dir `/data`
  vs `./data`). Mirrors energipays `environment.py`. Everything below keys off this.
- **A2 — MQTT auto-config from the Supervisor (the real gap).** `config.yaml`
  already grants `hassio_api` + `mqtt:want`, but nothing reads them — the user
  still types `mqtt_host/port/username/password`. Add a helper that GETs
  `http://supervisor/services/mqtt` with `SUPERVISOR_TOKEN` → `{host, port,
  username, password, ssl}` (energipays `discover_broker`). Wire it two ways:
  (a) **startup auto-fill** — in add-on mode, when `mqtt_enabled` and creds are
  blank, populate them from the Supervisor before the poller starts; (b) a
  **"Detect broker"** button + status on the Settings/MQTT tab (`GET
  /api/mqtt/discover`). Docker/dev falls back to probing common hosts
  (`core-mosquitto:1883`, `host.docker.internal:1883/1884`) with no creds.
- **A3 — Install / repository polish: DONE (2026-08-08).** README "Install as a
  Home Assistant add-on" section (repo-add → configure → ingress; notes Mosquitto
  auto-config, metrics-off-in-addon, watchdog, live allow_writes). Manifest
  verified: `build.yaml` arch bases, `config.yaml` options↔schema consistent,
  `repository.json`. With A1/A2/A4/A6 done, HA-ADDON is complete **except A5**
  (actionable notifications — deliberately deferred / future).
- **A4 — HA Notifications (verify + document).** `notify.py` works; confirm
  end-to-end inside a real add-on (persistent_notification for aGate-moved / OTA /
  connectivity transitions). Keep it non-actionable for now (scope guard).
- **A5 — Actionable HA Notifications (future).** persistent_notification can't
  carry actions. Later: send via the HA mobile-app notify service
  (`notify.mobile_app_*`) with `data.actions`, and receive the tapped action via
  an HA event subscription (WS) or a webhook route, mapping actions → **gated**
  bridge commands (e.g. "aGate moved → re-discover", "firmware changed →
  re-verify"). Needs a notify-target picker + an action-callback route. Deferred
  to avoid setup complexity (matches the no-actionable scope guard); note the
  dependency on a mobile-app notify target.

- **A6 — Local metrics vs HA history toggle (add-on installs only).** In add-on
  mode the MQTT→HA discovery already gives HA's **recorder** full entity history,
  so the bridge's local SQLite metrics (P5) is *duplicative*. Decision to build:
  when running as an HA add-on, the user must **nominate** whether to also keep
  local metrics — a `metrics_enabled` toggle that runs **in conjunction with** HA
  (both, if the user wants a self-contained history independent of HA's recorder).
  Defaults: **add-on + MQTT on → local metrics OFF** (HA covers it); **standalone/
  docker → local metrics ON** (no HA recorder). Surface the interplay in the
  Settings tab + the add-on option description so the choice is explicit, not
  surprising. (`metrics_enabled` option already exists — this is defaulting +
  copy + the env-aware default, not a new field.)

### Scope guards (carried)
- Local API only. No actionable notifications until A5 (keep setup simple).
- Auto-config must degrade gracefully: no Supervisor / no broker / no token must
  never crash startup — fall back to manual options + a clear status message.

---

## RESILIENCE — startup / shutdown / gateway-unreachable hardening

**Status:** planned (2 small gaps; the core story is already solid)
**Filed:** 2026-08-08

Reviewed the bridge's behaviour when the aGate is unreachable. **The foundation is
good and needs no work:** transport does `fwh_retries` (2 → 3 attempts) ×
`fwh_timeout` (20 s) with linear backoff + auto re-login per request; startup
degrades gracefully (firmware-read + MQTT-connect failures log and continue — API/UI
come up regardless); the poll loop retries every `poll_interval` (30 s), publishes
MQTT-offline on failure, and re-discovers the aGate if it moved IP; shutdown is
graceful (asyncio.Event → `stop.set()`+`await task`; loop wakes immediately via
`wait_for(stop.wait())`; MQTT publishes offline + clean disconnect). Only two gaps:

- **R1 — Docker `HEALTHCHECK` (Priority: MEDIUM): DONE (2026-08-08).** Added
  `GET /api/live` (liveness, no device I/O) + a Dockerfile `HEALTHCHECK` (stdlib
  python, honours `HTTP_PORT`) + `config.yaml` `watchdog`, all targeting `/api/live`
  so a down aGate never flaps the container / triggers a Supervisor restart.
  `/api/health` stays the gateway-reachability probe. Verified: container 'healthy'
  with the aGate offline; `test_live_endpoint_no_device_io` guards the no-I/O rule.

- **R2 — Graceful SQLite close on shutdown (Priority: LOW).** The poller's `finally`
  stops MQTT but never calls `store.close()`. **No data risk** — WAL + per-insert
  commit is crash-safe — so this is a tidiness/graceful-close nicety only. Add
  `store.close()` (via `db.reset_store()`) to the poller `finally` after `pub.stop`.
  *Ranked lower: no correctness or data-loss impact; purely graceful teardown.*

**Ranking rationale:** R1 changes observable operational behaviour (health surfacing
+ potential auto-recovery of a wedged process) and lands in the shipped add-on; R2
is invisible in practice because WAL already guarantees durability. Do R1 with the
HA-ADDON polish; R2 is a one-line cleanup whenever the poller is next touched.

---

## API-PARITY — close the buildable gaps (from the 3-way REST comparison)

**Status:** planned
**Filed:** 2026-08-06
**Context:** `docs/API_COMPARISON.md` — three-way REST comparison (local-bridge vs
Modbus Bridge vs FWHAI). The bridge now exposes the full local cmdType surface
(44 routes: 29 `/api/cmd/*` reads + generic `/api/call` + gated writes). The
remaining gaps split into two hard walls (below, do not attempt) and this
buildable backlog. All of the following are reachable over the local sendMqtt
API — absent only because not built yet. Sequenced by value.

- **P5 — Local persistence + historical metrics: DONE (2026-08-06).** `db.py`
  `MetricsStore` (stdlib sqlite3, WAL, single lock) under `/data/metrics.db`; the
  poller now runs on `metrics_enabled` alone (MQTT optional) and records a sample
  each ok poll (guarded — a DB error never kills the loop); opportunistic TTL
  prune (default 30 d). `GET /api/metrics` (range 1h/6h/24h/7d/30d or start/end,
  query-time bucket AVG, ~100–300 pts) + `GET /api/metrics/info`. Dashboard
  "Power History" chart (vendored Chart.js 4.4.7). 27 tests. Live-verified
  accumulating real samples. Single table + query-time bucketing (leaner than the
  Modbus Bridge's raw+archive split; adequate at this volume).
- **P6 — Logs endpoint: DONE (2026-08-08).** `logbuffer.RingBufferHandler` →
  `deque(500)`; `GET /api/logs?limit=&level=` (newest-first) + a Logs nav tab
  (level filter, 10s refresh).
- **P7 — Settings write: DONE (scoped, 2026-08-08).** Live-editable overrides for
  the runtime-applicable keys only — `allow_writes` (a live control-safety toggle),
  `log_level`, `ha_notify` — persisted to `{DATA_DIR}/overrides.json` (loaded in
  `get_settings()`, wins over env for those keys). `PUT /api/settings`; Settings tab
  Save button. Restart-only fields (broker/host/poll_interval/metrics) stay
  read-only → 422 with a clear message. *Remaining (optional): live-edit the
  restart-required fields with a proper restart/persist path (bigger; add-on config
  is Supervisor-owned).*
- **P8 — Scheduler: SUPERSEDED by the top-level `SCHEDULER` entry** (clone the Modbus
  Bridge ScheduleEngine + native automations scripting + multi-gateway, not just a basic
  timer). With HYBRID-CAPABILITIES, dispatch/target-SoC actions ARE now in scope (via the
  Modbus provider) — the old "mode/off-grid/circuit only" limit no longer applies.
- **P9 — Dedicated smart-circuit write endpoint.** Promote the generic
  `/api/call 1409 opt:1` into a typed, full-block RMW `POST /api/smart-circuit`
  (per-switch on/off + SoC/schedule), gated. Add `set_smart_circuit` to the
  library first (it's in `catalog.WRITES` but has no client method yet).
- **P10 — Backups.** Once P5 gives a DB: `POST /api/backup/create` + list +
  restore (online-backup, atomic swap). Complements the repo-level git/iCloud
  backups (OPS-BACKUP), which cover code, not runtime data.

### Hard walls — NOT buildable over the local API (do not attempt locally)
Documented so this isn't re-litigated. These require another transport tier.
- **Reserve-SoC write** — the device silently discards the local 1405 write
  (result:0 but not persisted). Cloud-owned. See the library
  `UNVERIFIED_WRITES.set_mode_soc` and the reserve-write-quirks memory.
- **Battery power dispatch** — force charge/discharge (W/%) + target-SoC
  watchdog. No local setpoint cmdType (1823/1825 are unconfirmed). Needs Modbus
  WSet registers (modbus bridge) or cloud dispatch (FWHAI/hybrid).
- **Inverter register-level AC electricals** (V/I/Hz/PF) — Modbus/SunSpec only.

### Out of scope (HA-integrator tier)
Pricing/tariffs/Amber, solar & weather forecasting, economic smart-dispatch,
automation rulebooks, security/users, multi-gateway.

---

## OPS-BACKUP — back up regularly so nothing is lost

**Status:** ongoing practice (GitHub live; iCloud to set up)
**Filed:** 2026-08-02

Applies to all FranklinWH repos (`franklinwh-local`, `franklinwh-local-bridge`,
`franklinwh-hybrid`, the modbus/cloud bridges).

- **Primary — GitHub (private):** commit + `git push origin main` after every meaningful
  change (not just at the end). This repo now has a private origin. Don't leave work
  uncommitted/unpushed for long — a lost laptop = lost work otherwise.
- **Secondary — iCloud: DONE (2026-08-02).** `tools/backup_dev_to_icloud.sh` bundles **every
  git repo under `~/dev` individually** (per-repo folders — traceable/restorable) into
  `~/Library/Mobile Documents/com~apple~CloudDocs/backups/dev/`, plus a `.dirty.tgz` of
  uncommitted work and a manifest of each repo's branch/HEAD/dirty state; keeps last 4 runs.
  Scheduled **weekly (Sun 03:00)** via `tools/com.david2069.dev-icloud-backup.plist`
  (installed to `~/Library/LaunchAgents/`, loaded). Restore: `git clone <slug>-<stamp>.bundle`.
  Run manually anytime: `bash tools/backup_dev_to_icloud.sh`.

---

## Roadmap (from PLAN_docker.md)

- **Phase 1 — live dashboard: DONE (2026-08-02).** `client.summary()` = all reads in one
  login session; `/api/summary`; `dashboard.html` self-contained auto-refreshing UI (SoC +
  power-flow cards, mode/reserves table, status row), dark-mode aware, ingress-friendly.
  Live-verified. Remaining Phase 1 polish (optional): power-flow diagram, history/charts,
  more reads toward the FWHAI+cloud parity floor.
- **Phase 2 — MQTT + HA discovery: CODE DONE (2026-08-02).** `publish/entities.py`
  (8 sensors: SoC, grid/solar/battery/load/generator W, mode, latency), `publish/
  mqtt_publisher.py` (paho, HA discovery configs + retained state + availability/LWT),
  `poller.py` (async loop, reads via the library in threads), wired into the FastAPI
  lifespan (starts when `mqtt_enabled`). 7 pytest pass.
  **LIVE-VERIFIED (2026-08-02)** against `fwhbridge-mosquitto` (:1886) + the real aGate:
  discovery config + real state (`soc 87.7, grid/solar/battery/load W, mode, latency`) +
  availability all received by a subscriber; retained test topics cleaned up. Dev brokers
  available: fwhbridge-mosquitto :1886, fwhhai-mosquitto :1885, fwh-dev-mosquitto :1884; HA
  dev instances on :18123/:18124/:18125/:8124.
  TODO next in Phase 2: HA notifications (non-actionable) via `homeassistant_api`.
- **Phase 3 — DONE (2026-08-05).** Shared runtime `state.py` (active host / serial /
  firmware); `client.rediscover()` scans the subnet and adopts the aGate's new IP (prefers
  the serial match); poller re-discovers on read failure + fires OTA-change / aGate-moved
  notifications; structured logging. 13 tests pass; live-verified. Also this phase:
  canonical mode labels (Time-of-Use + tariff) like the cloud API, on the dashboard + MQTT.
- **Phase 4** — (optional) gated verified writes (mode / off-grid) per existing FWHAI + cloud
  conventions; `read_only`/`allow_writes` guards. Reserve stays cloud-owned (not here).

### Scope guards
- Local API only (no `franklinwh-hybrid` — future). No new mode/off-grid conventions.
- No actionable notifications (avoid setup complexity / feature creep).

---

## Done — archive

Shipped items (details in git history):

- FEAT-BATTERY-TAB — Battery tab: BMS telemetry, auto-refresh, chart (DONE)
- FEAT-BMS-SESSIONS — persisted recordings + Voltage/Temperature/Comparison charts (DONE)
- FEAT-MULTI-APOWER-CHARTS — split BMS charts per aPower (DONE)
- FEAT-PERCELL-MULTI-APOWER — per-cell trends for every aPower, stacked (DONE)
- RESEARCH-RESERVE-SOC — RESOLVED: reserve SoC has no local write path
- RESEARCH-RESERVE-SOC-HISTORY — the original investigation (superseded)
- FEAT-SOLAR-TAB — dedicated Solar tab (DONE)
- FEAT-DEVICE-DB — gateway hardware registry (SyHdVersion) (DONE)
- FEAT-GENERATOR — Generator tab (read-only + mode toggle) (DONE)
- DEF-NOTIFIER-ATTR — `/api/notify/test` returned 500 (DONE)
- CONN-LOSS-UX — connection-lost banner + details modal (DONE)
- CLOUD-AUTH-LIFECYCLE — wire up the breaker, persist it, re-check periodically (DONE)
- TIER-ACCUMULATORS — record the 1301 tariff-tier arrays (DONE)
- READ-METHODS-DRIFT — `READ_METHODS` was hand-maintained and fell behind (DONE)
- LIBRARY-0.2.0 — re-vendor the local API wheel (DONE)

## FEAT-SCHEDULER-HA-SERVICE-ACTIONS — HA actions should call services, not only notify (DONE)

**Status:** DONE 2026-09-22 — HA actions now carry a type (Notify | Call service). A service
action calls any HA `domain.service` (switch.turn_on, climate.set_temperature, scene.turn_on, …)
on a chosen instance, with an optional entity_id + JSON data, both `%sensor.id%`-templated. Fires
on the same entry/exit/both edges, each still guarded. `ha_instances.call_service()` mirrors
send_notification; `run_action` gains an `ha_service` branch; `_fire_ha_phase` dispatches by the
action's `ha_kind`. Verified: 6 unit tests (branch + call_service URL/guards) + live 200 against
the real HA (persistent_notification create/dismiss) + editor round-trip. **Filed:** 2026-09-22 (user)

**Follow-up (optional):** a "Test" button per service action (like notify's), and a service/entity
autocomplete from the instance's `/api/services` + entity registry.
**Depends on:** FEAT-SCHEDULER-FULL-PARITY.

Gap vs the Modbus bridge: the scheduler's "Home Assistant actions" can **only send
notifications**. `scheduler._fire_ha_phase()` hardcodes `run_action({**ha, "kind": "notify"})`
(scheduler.py ~729), so entry/exit HA actions are notify-only. The Modbus bridge can perform
**arbitrary HA service calls** (e.g. `switch.turn_on`, `climate.set_temperature`,
`scene.turn_on`) with a target entity + data.

### Behaviour
- Extend HA actions with a **service-call** type: pick an HA instance + `domain.service` +
  target entity_id(s) + optional data (JSON / templated with `%sensor.id%` like notify does).
- Keep notify as a first-class shortcut (it's `notify.<service>` under the hood).
- Fire on the same entry/exit/both edges, each still guarded by its own guard condition.
- Validate service existence against the instance where feasible; report unknowns rather
  than firing blind (same honesty rule as local actions).

### Wiring
- New `run_action` branch `kind == "ha_service"` → `ha_instances.call_service(base_url, token,
  domain, service, {entity_id, **data})` (add to ha_instances.py; mirror `send_notification`).
- `_fire_ha_phase` dispatches by the action's own kind instead of forcing "notify".
- Editor UI: a type toggle (Notify | Call service), service/entity pickers (reuse the HA
  entity list already fetched for conditions), data field.

## FEAT-SCHEDULER-EXIT-CONDITIONS — exit conditions to close a window early / gate the exit (DONE)

**Status:** DONE 2026-09-22 — an optional "End early when…" condition list closes the window
early when it becomes true: fires the exit-tagged HA actions and RELEASES a force dispatch, then
does not re-fire that day. Also blocks a dispatch from starting if the exit condition already
holds at the window open. Backend folds `exit_now` into the effective window in `tick()`;
`exit_conditions`/`exit_match` persist (portable + ScheduleReq model). UI: a flat exit-row editor
(sensor/op/value, ALL/ANY — no nested groups, the common case) reusing the entry-row widgets.
Verified: 3 unit/contract tests + live API round-trip + headless editor. **Filed:** 2026-09-22 (user)
**Depends on:** FEAT-SCHEDULER-FULL-PARITY.

Gap vs the Modbus bridge: schedules have **entry conditions only**. The window closes purely on
time (`window_state` = fire_at + duration_min). There is no way to **end a window early when a
condition becomes true** (e.g. "force discharge during peak, BUT stop early if SoC ≤ 20%"), nor
to gate the exit action on a condition.

### Behaviour
- Add an **exit condition tree** (same operator vocabulary + editor as entry conditions). When
  it evaluates true inside an open window, treat it as the window's exit edge: fire exit HA
  actions and (for a force dispatch) RELEASE — the same exit-edge path already built.
- Interaction with `entry_hold_s` / re-fire: once exited early, do not re-fire the same day
  (respects `last_fired_day`), matching entry semantics.
- Optional: a separate exit **guard** so the exit action itself can be conditional.

### Wiring
- `tick()`: after the time-based `window_state`, also compute `exit_now = bool(exit_conditions)
  and evaluate(exit_conditions, snapshot)`; the effective window is "inside" only while time-inside
  AND not exit_now. Drive the existing exit-edge block from that combined signal.
- Persist `exit_conditions` on the entry (portable + validated like `conditions`).
- Editor UI: a second condition builder ("End early when…"), reusing the entry builder component.

## FEAT-DISPATCH-INTERRUPT-POLICY — reconcile scheduled dispatches interrupted by a restart (DONE)

**Status:** DONE 2026-09-22 — **Filed & shipped:** 2026-09-22 (user).

A force dispatch's watchdog (auto-release on duration/target-SoC) and exit-edge release both
live in memory, so an ungraceful bridge restart mid-window could leave the battery pinned with
no owner. Now each scheduled dispatch is **persisted** (`dispatches` table: owning schedule,
gateway/host, direction, signed watts/mode, target SoC, window start/end) and a **boot
reconcile** applies a user-chosen policy:

- **none** — record only; no alert, no battery action.
- **notify** (default) — alert the enabled notify devices; never touch the battery (two-masters safe).
- **release** — if the window has ended and the battery is still forced, RELEASE; if still inside,
  re-arm the watchdog to release at window end (never kills a valid dispatch, never re-forces).
- **resume** — like release, plus re-force for the remaining window if the battery dropped it.

Setting `dispatch_interrupt_policy` (Settings → Battery dispatch). Reconcile runs in the VPP
loop's boot pass BEFORE the generic orphan check and suppresses the duplicate orphan alert when
it handled our own dispatch. Every interruption is logged to the schedule activity log
(battery-dispatch filter) and notified per policy. Verified: 7 policy unit tests (monkeypatched
Modbus, full matrix) + live notify path against the container DB (row → interrupted, notified,
battery untouched); settings API persists + 422s bad values; UI selector loads/saves.

**Follow-up (DONE 2026-09-22):** widget-initiated (dashboard) force dispatches are now persisted
too (schedule_id="_widget", window_end = start+duration, or None for an indefinite hold) and
closed on release — so an interrupted widget force is covered by the same boot-reconcile policy
instead of falling to the orphan CRITICAL alert. Full parity between scheduled and widget dispatches.

## FEAT-SCHEDULER-RECURRENCE — trigger types beyond daily (DONE)

**Status:** DONE 2026-09-22 — Phase A (calendar recurrence) + Phase B (full trigger engine + UI). All 8 Modbus trigger types now supported: window (multiple time windows), once, daily, weekly, interval, monthly, cron (croniter), always. Trigger-type selector + quick presets + multiple time windows in the editor; per-occurrence firing engine; backward compatible with legacy daily schedules. — **Filed:** 2026-09-22 (user, from the Scheduler Gap Analysis)
**Depends on:** FEAT-SCHEDULER-FULL-PARITY (done).

Biggest structural gap vs the Modbus bridge: the local scheduler is **daily-only** — one `fire_at` +
`duration_min`, once per day. Modbus has 8 trigger types (window/once/daily/weekly/interval/monthly/
cron/always). Close it in two phases:

### Phase A — CALENDAR recurrence (DONE 2026-09-22)
Layers "which calendar days does this daily window apply to" onto the current tick logic without
reworking it. Delivers weekly + monthly + seasonal + one-off/date-bounded patterns.
- **days** `list[int]` (0=Mon…6=Sun); empty = every day.
- **months** `list[int]` (1–12); empty = every month.
- **day_of_month** `int|None` (1–31, clamped to month length); None = any.
- **start_date / end_date** `YYYY-MM-DD|None` (inclusive); one-off = start==end.
- Engine: a `_calendar_ok(entry, now)` gate folded into `due()` ("outside its recurrence" reason);
  also gates `todays_windows` / `timeline_segments` so a non-matching day shows no planned window.
- Persist on `ScheduleReq` + `_PORTABLE_KEYS`; validate. UI: a "Repeat" row (7 Mon–Sun toggles) +
  an "Advanced" disclosure (months, day-of-month, date range). List card shows the recurrence label.

### Phase B — SUB-DAILY / continuous triggers (needs a tick-model change)
- **interval** (every N min + optional anchor), **cron** (croniter), **always** (sensor-driven, no
  discrete fire). These fire more than once per day or continuously, so the once-per-day
  `last_fired_day` guard + `window_state` need generalising to a per-trigger "next fire" + de-dupe.
  Larger; do after Phase A ships.

## FEAT-SCHEDULER-ORCHESTRATION — priority, conflict policy, release policy, missed-window catch-up, site/service targets (Phase 1 DONE)

**Status:** Phase 1 DONE 2026-09-22 (priority resolution); Phase 2 queued.

**Phase 1 (done):** `priority` (int, default 0) on each schedule. When several schedules fire the
same tick for the same gateway target and carry a battery/gateway action, the highest priority wins
the target for the day; the rest are marked fired="deferred" + logged `deferred`. Notify-only
schedules never contend. Verified with unit tests (winner runs / only winner touches the battery /
loser deferred; solo entry unchanged). Editor has a Priority field; log shows a `deferred` chip.

**Phase 2a (DONE 2026-09-22): conflict-with-active-dispatch policy.** `conflict` (override | defer |
wait, default override) on each schedule. When a force-action schedule becomes due while the battery
is already under ANOTHER schedule's dispatch (persisted, from a prior tick): override takes control,
defer skips for the day (logged `deferred`), wait skips this tick and retries (logged `waiting`,
not marked fired). Editor has an "If busy" selector. Verified with 3 unit tests.

**Phase 2b (queued):**
- **on-exit release policy**: restore-prior-mode (snapshot the mode at dispatch, re-assert on exit)
  vs the current always-release→native.
- **missed-window / catch-up policy** (late-fire-remaining / skip / late-fire-always) on outage or
  restart recovery — window catch-up complementing the dispatch reconcile.
- **Target = Site (all gateways)** fan-out, and **Target = Service** (an HA service call as the whole
  action). — **Filed:** 2026-09-22 (user, from the Gap Analysis)

The "pro automation" layer. Individually small, collectively the difference between last-set-wins and
deterministic multi-schedule behaviour.
- **priority** (0–1000) + a `winner()` per target so overlapping entries resolve deterministically.
- **conflict policy** (defer / override / wait) when the target is already under manual/foreign control.
- **on-exit release policy**: restore-prior-mode (snapshot the mode at dispatch, re-assert on exit) vs
  the current always-release→native.
- **missed-window / catch-up policy** (late-fire-remaining / skip / late-fire-always) on outage or
  restart recovery — complements the existing dispatch reconcile with *window* catch-up.
- **Target = Site (all gateways)** fan-out, and **Target = Service** (an HA service call as the whole
  action, not only via the HA-actions block).

## FEAT-SCHEDULER-LIST-UX — status filter, next-fire, active-now badge, per-entry Stop, CRUD audit (DONE)

**Status:** DONE 2026-09-22 — status filter (All/Enabled/Disabled) + hidden count, per-card Next-fire label (recurrence-aware), Active-now badge + "N active now" count, per-entry Stop (releases just that schedule's dispatch), CRUD audit rows (created/updated/enabled/disabled/deleted/stopped) in the log, and an edit-while-running confirm. — **Filed:** 2026-09-22 (user, from the Gap Analysis)

High-visibility quality-of-life on the schedule list + log:
- **Status filter** on the list (Enabled / Disabled / All) + hidden count.
- **Next-fire** column/label per entry (depends on FEAT-SCHEDULER-RECURRENCE for accurate math).
- **Active-now** badge (pulsing) + a live "N active now" count.
- **Per-entry Stop** — release just this entry's running dispatch (keep it enabled), vs the global
  topbar Release.
- **CRUD audit rows** in the activity log (created / updated / enabled / disabled / deleted).
- **Edit-while-running** prompt ("apply to the live run?").

## FEAT-SCHEDULER-EDITOR-UX — searchable sensor combobox, guided HA-entity picker, exit-condition groups (queued)

**Status:** queued — **Filed:** 2026-09-22 (user, from the Gap Analysis)

Editor polish (nice-to-have once the above land):
- **Searchable sensor combobox** (type-to-filter) replacing the grouped `<select>` — matters once the
  sensor catalogue grows (FEAT-UTILITY-BILLING).
- ~~Guided HA-entity picker~~ **DONE 2026-09-22** — the "+ entity" HA action picks an exposed HA
  entity (grouped by instance) and shows a domain-aware widget: toggle (switch/light/input_boolean →
  Turn On/Off/Toggle), option dropdown (select/input_select → the entity's own options), number
  (number/input_number), press (button), run (scene/script). Free-text domain/service/JSON kept as an
  "Advanced (raw service)" fallback. Matches the Modbus bridge; executes as POST /api/services/
  {domain}/{service} with {entity_id, **data}.
- ~~Nested groups in exit conditions~~ **DONE 2026-09-22** — exit conditions now use the exact same nestable ALL/ANY builder as entry conditions, plus a Test Verify button ("exit WOULD/would NOT fire now"). The two editors are identical.
- **Per-entry export** (currently export-all only).

> **Sensor-catalogue gap** (tariff/demand/energy/fixed/service/const/time/dispatch sensors — the "60+"
> Modbus exposes) is tracked under the existing **FEAT-UTILITY-BILLING**, not duplicated here.

## FEAT-SITES — promote Site to a first-class multi-row entity (DONE 2026-09-23)

**Status:** DONE 2026-09-23 — `sites`+`meters` tables + CRUD + default Home/Meter-1 boot migration + `gateway.meter_id`; /api/sites + /api/meters with guards; Settings "Sites & Meters" card + gateway meter picker (shown only when >1 meter). Single-gateway installs unchanged. Was: queued — **Filed:** 2026-09-23 (user) — **Design:** Sites/Services/Billing architecture doc.

**Grounding (Modbus bridge source read):** the Modbus bridge's Site is a HARD SINGLETON
(`site_config CHECK(id=1)`) — it cannot have two. The real multi-instance entity there is the
**Service**. This item is a deliberate step BEYOND Modbus: a real `sites` table so a fleet/installer
can run several installations. Single-site users never notice (default-site migration).

- `sites` table: `id, name, timezone, latitude, longitude, postcode, currency, region, is_default`.
- Add `site_id` to the new `meters` table (FEAT-METERS); a gateway's site is DERIVED via its meter.
- First-boot migration: create a default "Home" site + a default meter, assign every gateway to it.
- Settings → Sites card (name/location/timezone/currency/region); per-gateway/service site picker.
- Rides on the existing Gateways-in-Settings roster plan (adds one column + a picker).
- Topbar/scheduler gain a Site scope (aggregate = sum across the site's gateways; the local bridge
  already has `/api/site/status` — make it site-scoped).

**Open decision:** full multi-site vs keeping Modbus's singleton and treating "multiple meters" purely
as multiple Services. Multi-site is the thing the user called out wanting beyond Modbus.

## FEAT-METERS — Meter as a first-class entity (DONE 2026-09-23)

**Status:** queued — **Filed:** 2026-09-23 (user, rev-2 normalized model) — **Design:** Sites/Meters/Billing doc.

The user's model normalizes what Modbus denormalizes: **Meter is a real entity** (Modbus never makes it
one — it's a string on the Service). Constraints set by the user (locked):
- A gateway connects to a SINGLE meter → `gateways.meter_id` (a gateway's site is DERIVED via the meter).
- A meter has an AC type (single | split/dual | three-phase) + a fixed rated amperage.
- A site can have MORE THAN ONE meter → Site 1─N Meter.

- `meters` table: `id, site_id, utility_id, tariff_id (nullable), name, meter_number (NMI/MPAN),
  ac_type, rated_amps, pto_status, pto_date, pto_reference, timezone`.
- Gateway editor: a Meter picker + `phase` (which leg of a multi-phase meter) + `device_type` (agate|mac1).
- Settings → Meters card. Default-meter migration (existing gateways attach to one default meter).
- Billing + sensors key on the Meter (FEAT-BILLING-SERVICE).

## FEAT-UTILITY-TARIFF — Utility + Tariff as separate entities + tariff editor (DONE)

**Status:** queued — **Filed:** 2026-09-23 (user, rev-2 normalized model) — **Design:** Sites/Meters/Billing doc.
**Supersedes:** the old FEAT-UTILITY-SERVICE (Modbus Service blob).
**Progress:** stage A (rate_model.py port + utilities/tariffs DB + CRUD + /api + validate) DONE;
stage B (tariff.*/service.* sensors + tariff_snapshot wired into the tick + evaluate/test) DONE.
**Stage C DONE:** Utilities & Tariffs settings card + utility editor (permissions) + tariff editor —
flat/base rate (C1) AND the seasonal Time-of-Use editor (C2: seasons → months → the 4 period rates →
windows, live Validate) + meter → utility/tariff pickers. Nested season/window x-for verified clean.
**Not in this feature (later):** demand/bonus/export-charge/fixed-charge sub-editors ride on
FEAT-BILLING-SERVICE (the fields exist in the tariff JSON; the billing engine + their editors come next).

Modbus bundles supplier + rates + permissions into one `services` row. The user's model splits them:
- **Meter N─1 Utility** ("a utility is associated with each meter").
- **Meter N─0..1 Tariff**, **Utility 1─N Tariff** ("a utility tariff can be associated to a meter").

- `utilities` table: `id, name (retailer), network_dnsp, country, plan_type`. The export/import
  PERMISSIONS + LIMITS + PTO are NOT flat flags here — they are the 4-layer governance model
  (FEAT-GRID-GOVERNANCE): PTO per device on the meter's interconnection, network limits on the meter,
  programme restrictions (FEAT-GRID-PROGRAMME), tariff economics on the tariff.
- `tariffs` table: `id, utility_id, name, pricing (JSON rate model: seasons/blocks/time_periods/tiers/
  default_rate), demand_window, bonus_window, charge_window, fixed_charges, billing_cycle_day,
  plan_version, plan_started_at`.
- Port `rate_model.py` (pure resolver → season/period/buy/sell/tier/billable/reason).
- Tariff editor UI (clone Modbus Settings form): sub-tabs import(seasonal TOU)/demand/bonus/charge/fixed,
  retailer presets, live rate validation, derived plan-type label.
- Meter editor picks a Utility + one of its Tariffs. Emits `tariff.*` + `service.*` sensors.

## FEAT-GRID-GOVERNANCE — layered export/import permission + limit model (queued)

**Status:** queued — **Filed:** 2026-09-23 (user) — **Design:** Sites/Meters/Billing doc §2.
**Depends on:** FEAT-METERS + FEAT-UTILITY-TARIFF.

The user established that "can I export/import" is NOT one flag — it resolves across FOUR
distinct-but-related layers, modelled separately and combined by a resolver:
1. **Interconnection / PTO** — granted by the Utility PER INVERTER DEVICE (solar PV, battery) behind
   the meter → may the device operate/export at all (approved|pending|none). Table `interconnections`
   (meter_id, device_type ∈ solar|battery, pto_status, pto_ref, pto_date, export_allowed, export_limit_kw,
   `source ∈ manual|cloud`, `cloud_ref`, `synced_at`). **Cloud-as-reference:** the FranklinWH Cloud API
   returns a PTO date PER GATEWAY — store it as provenance (`gateway.cloud_pto_date`+synced_at) and let
   it SEED the gateway's meter's (battery) interconnection when unset. MANUAL WINS; sync fills gaps +
   flags conflicts, never overwrites. The model is authoritative + fully functional without the cloud.
2. **Network capacity** — the utility/network's localised transmission limit → hard export/import kW caps
   or a full ban, on the meter. Columns on `meters`: export_limit_kw, import_limit_kw, export_banned,
   import_banned.
3. **Authority / programme** — see FEAT-GRID-PROGRAMME (layer 3, deferred).
4. **Tariff economics** — penalise / zero-rate / NEGATIVE feed-in / export charges → already the Tariff
   rate model (sell rate can be ≤ 0; export-charge windows).

- **PermissionResolver(meter, device, now)** → `export_allowed = PTO(device) approved AND not
  network.export_banned AND not any(programme.bans_export)`; `export_limit_kw = min(network, PTO-device,
  programme)`; rate from the tariff (may be negative). Battery-export vs solar-export resolve independently.
- **INFORMATIONAL — express, don't enforce.** Feeds the `service.*` sensors that the USER references in
  their own conditions/guards (e.g. "only export if service.battery_export_allowed"). The user determines
  usage; the bridge NEVER hard-blocks the battery or auto-rejects a dispatch. Enforcement of grid/scheme
  rules (and its liability) is not the bridge's role. The bridge adds SELF-COMPLIANCE support: the sensors
  to write compliant rules + a track/audit trail (record actions against the governance state so the user
  can demonstrate compliance).
- Phase-1 scope = layers 1, 2, 4 (layer 3 = FEAT-GRID-PROGRAMME).

## FEAT-GRID-PROGRAMME — authority / subsidy / incentive scheme restrictions (governance layer 3) (queued, later)

**Status:** queued (later) — **Filed:** 2026-09-23 (user) — **Depends on:** FEAT-GRID-GOVERNANCE.

State/local authority or subsidy/incentive/loan schemes that ban or restrict export/import or connecting
certain devices (e.g. a subsidy that bans battery export while allowing solar). Distinct from the
network limit and the tariff.
- `programmes` table (name, authority, bans_export/import, device-specific bans, export/import limits,
  source ∈ manual|cloud_entrance_flag) + `meter_programmes` enrolment (meter N─N programme).
- **Cloud API entrance-programme flags** as a REFERENCE source (undocumented codes). Always store the
  raw `cloud_code`+synced_at as provenance; an editable code→scheme guess map creates/enrolls our OWN
  Programme (source=cloud); unknown codes enroll a visible "unclassified" placeholder, never dropped —
  so a code can be re-interpreted later when docs surface. Wire via the existing cloud provider.
- Every record carries `source ∈ manual|cloud` + `cloud_ref` + `synced_at`; manual is source of truth.
- Folds into the PermissionResolver as layer 3. Cloud-agnostic: works fully without the cloud.

## FEAT-BILLING-SERVICE — provider-shaped local billing engine
Status: DONE 2026-09-26 — engine already emitted live sensors; ADDED: billing_periods table + rollover snapshot (closes on cycle/tariff change, stamped retailer/network/plan/tariff), /api/billing/overview (net cost + projection + cycle progress) + /api/billing/history (+CSV), and a dedicated Energy Costs TAB (live card + breakdown + closed-period history). Tests in test_billing_history.py.

**Status:** queued — **Filed:** 2026-09-23 (user, chose "local engine, provider-shaped").
**Design:** Sites/Meters/Billing doc. **Depends on:** FEAT-METERS + FEAT-UTILITY-TARIFF.

Modbus computes billing entirely locally but HARD-WIRES it (no provider seam; its `pricing_api`
column is an unused placeholder). Port the same computation behind a **BillingProvider** interface —
mirroring the existing `providers.py` (dispatch/reserve) pattern — so a wholesale/cloud source can
slot in later untouched.

- `BillingProvider` protocol: `price_now(service, now, used_kwh)`, `integrate(service, sample)`,
  `period_summary(service, now)`. Default `LocalBilling` = the ported Modbus logic:
  - DemandTracker: per-sample integration of import_cost/export_credit against the rate IN FORCE at
    that instant; peak demand via interval-bucketed grid-import counter; state persisted ~60s;
    period rollover on `billing_cycle_day` → snapshot into `billing_periods`.
  - FixedChargesStore: per-day-equivalent standing charges.
  - net_total = demand + export_charge + fixed + import_cost − bonus − export_credit (history reuses
    the sensor formulas so live and history agree).
- `billing_periods` table (closed-period history stamped with retailer/network/plan_version).
- Emits `demand.* / energy.* / bonus.* / fixed.*` sensors (computed on-read from raw accumulators).
- **Per-meter billing** (Modbus v1 uses "first enabled service"): each Meter has one accumulator,
  billing its Tariff against the energy of ITS gateways. Sensor scoping: resolve against the schedule's
  target meter, else the site's default meter (open decision to confirm).

## FEAT-ENERGY-COSTS-TAB — read-only Energy & Costs tab (queued)

**Status:** queued — **Filed:** 2026-09-23 — **Depends on:** FEAT-BILLING-SERVICE.

Clone the Modbus Energy-Costs tab (read-only): Setup (resolved windows/rates), This period (live
cost/credit/demand/fixed + billing-cycle progress bar + linear end-of-period projection), Linked
automations (schedules referencing tariff sensors), and History-by-supplier + CSV export.

## FEAT-SCHEDULER-TARGETS — gateway | meter | site scheduler targets (queued)

**Status:** queued — **Filed:** 2026-09-23 — **Depends on:** FEAT-SITES + FEAT-METERS.
**Converges with:** FEAT-SCHEDULER-ORCHESTRATION Phase 2b (Site/Service targets).

Add `target_type` (gateway|meter|site) to schedules + a resolver: gateway → that gateway; meter →
the gateways connected to that meter; site → all the site's gateways (fan-out). Target dropdown in the
scheduler editor. This is the Target=Site/Service item deferred from orchestration Phase 2b.

## FEAT-BILLING-WHOLESALE — dynamic / wholesale tariffs: AusNEM built-in OR HA price entity (queued)

**Status:** queued — **Filed:** 2026-09-23; expanded 2026-09-27 (user). **Depends on:** FEAT-BILLING-SERVICE.
> **Done 2026-09-29 (AusNEM slice):** the built-in AEMO NEM spot-price feed is shipped — `aemo_nem.py` (regional $/MWh -> c/kWh, cached, never raises), `GET /api/tariff/spot`, the `tariff.spot_price` scheduler sensor (via `nem_snapshot`), and a **NEM Region** selector + live spot display in Settings. Live-verified NSW1 6.72c/kWh. **Done 2026-09-29 (HA price-entity provider):** the SECOND provider is shipped — `scheduler.ha_price_snapshot` maps a chosen exposed HA entity onto `tariff.spot_price` (buy) + `tariff.feed_in_price` (sell), c/kWh, with $/kWh auto-scaled to cents; wired into the engine tick + both eval sites (HA wins over NEM); `/api/tariff/spot` now reports both providers + the active source + exposed-entity options; Settings has a **Dynamic price (wholesale)** card with buy/feed-in entity pickers. Live-verified against **Amber Express** (buy 12.83 / sell 5.89 c/kWh). **Done 2026-09-30 (per-tariff dynamic billing):** wholesale pricing is now a PER-TARIFF property with its OWN provider — a tariff's rate type = **Wholesale (live)** + provider (AusNEM region OR HA buy/feed-in entity). billing prices import/export at that tariff's live rate (negative = not billable); the active dynamic tariff overrides tariff.spot_price/feed_in_price/buy_rate/sell_rate sensors (option B: static tariff -> global sensor source stands). Effective dates switch billing mode automatically. Global toggle retired; the Settings card is now the scheduler-sensor source. Remaining: buy/sell FORECAST sensors.
**Context:** user was on **Amber Electric** before 2026-09-09 (then switched to AGL TOU, already imported).
FWHAI implements Amber; Energipay used the NEM wholesale API. Our rate_model is STATIC today (seasons /
blocks / time_periods + tiers) — a dynamic tariff needs a live price feed, not a schedule.

### A new tariff kind: `dynamic` (wholesale), with a pluggable price provider
Add a "dynamic/wholesale" plan type whose buy/sell is the LIVE price at billing time, not a static
window. `rate_model.resolve` gets a hook: when the tariff is dynamic, return `provider.current(now)`
(c/kWh buy + sell) instead of resolving seasons. Billing already prices per-tick on `used_kwh`, so it
just prices against the live rate. Expose a **`tariff.spot_price`** (+ buy/sell/forecast) sensor for the
scheduler — the whole point is "force charge when the spot price is cheap/negative".

### Two pricing inputs ONLY (user correction 2026-09-27 — no hardcoded vendor APIs)
Pricing/tariff comes from exactly two sources — nothing vendor-hardcoded:
1. **AusNEM built-in sensor** — a bridge-native provider that fetches the AEMO National Electricity
   Market regional spot price by **NEM region** (NSW1/VIC1/QLD1/SA1/TAS1), **$/MWh -> /10 = c/kWh**,
   no key. This is the one built-in wholesale feed. Reuse the Open-Meteo fetch pattern
   ([[FEAT-WEATHER-SOLAR-OPENMETEO]]) + the providers.py breaker.
2. **HA Entity sensor** — link a dynamic tariff to an **HA price/tariff entity** and read its state
   as the live c/kWh (buy, and a sell entity if exposed). **Amber Electric and every other retailer
   come in THIS way** — via their existing HA integration's sensors. Confirmed scope (user 2026-09-29):
   **Amber, Amber Express, ConEd, Localvolts, and any other dynamic retailer** are all just an HA
   price entity we read (e.g. Amber's `sensor.*_price`, the Modbus Bridge's Amber-Express sensor).
   Do NOT hardcode Amber/vendor APIs or manage keys —
   the user already has these as HA entities. Reuse the HA-instance token/read path (ha_instances.py)
   + the guided HA-entity picker (FEAT-SCHEDULER-EDITOR-UX).

### Notes / build order
- Provider interface mirrors providers.py (dispatch/reserve): `current(now)->{buy,sell}`, `forecast()`,
  cached + breaker-guarded; a bad feed falls back to the tariff's static rate (or last-good).
- Config on the Utility/Tariff editor: plan type `dynamic` → provider select (**AusNEM region** /
  **HA price entity**) + units. AU-only fields (NEM region) shown only for AU.
- Ties to [[FEAT-STORM-HEDGE-LOCAL]] + scheduler: `tariff.spot_price` gates force-charge/-discharge.
- Smaller parity follow-up (separate): the Modbus Energy-Costs page also shows a **"Linked automations"**
  list (schedules conditioning on `tariff.*`/`demand.*`/export sensors) + a **top setup-summary strip**
  (active tariff windows). We imported the tariff PROFILE + closed-period HISTORY, but not those two
  presentation views — add them to our Energy Costs tab for parity.

## FEAT-SCHEDULER-PORTABILITY — portable schedules (logic travels, bindings remap) + system of record (queued)

**Status:** queued — **Filed:** 2026-09-23 (user) — **Design:** Sites/Meters/Billing doc §5.
**Builds on:** the existing schedule export/import (`portable()` / `validate_import` / disabled-for-review).

Two principles the user set:
- **System of record (optional):** the Site/Meter/Utility/Tariff/governance tables are the user's
  authoritative record IF they choose to keep one (cloud-seeded, manually correctable, + the audit
  trail). Never forced; an unconfigured tariff/service sensor reads "not configured" and a condition
  fails closed with a clear reason.
- **Portable schedules:** a schedule's LOGIC (trigger/windows/recurrence, conditions, thresholds,
  actions) must migrate between installs; only its SITE-SPECIFIC BINDINGS don't. Conditions reference
  sensors by a STABLE id vocabulary (`battery.soc_pct`, `tariff.buy_rate`, `service.battery_export_allowed`)
  → portable. "Barring the HA-specific wiring, a bundle migrates in theory."

### Work
- Export bundle: carries logic + stable sensor-id references; the system-of-record data (site/meter/
  utility/tariff) is NOT embedded — schedules reference it by sensor id only.
- Import remap/flag for install-specific bindings (extend `validate_import`): HA instance/entity ids
  (guided-entity + condition `ha:*` sensors), notify device ids, gateway/meter/site targets. Unknown →
  reset to a default; imported disabled-for-review; optional a "map to local equivalent" step.
- Capability-gap warnings on import: if a schedule references `tariff.*`/`service.*` but the target has
  no utility/meter configured, warn (condition will fail-closed) rather than silently import.
- Keep it robust as the sensor vocabulary + action types grow (governance sensors, entity actions,
  meter/site targets).

## FEAT-SCHEDULER-TZ — per-site timezone-aware schedule evaluation + defaults (queued, low priority)

**Status:** queued (low priority — ~99.9% single-gateway) — **Filed:** 2026-09-23 (user).
**Design:** Sites/Meters/Billing doc §1 (Defaults & location/timezone resolution).

Local-bridge advantage over Modbus: Modbus evaluates schedules on the CONTAINER clock and only
warns about tz mismatch (time.tz_ok/service.tz_matches_clock) — it has no per-device timezone. The
local API cmd 1201 returns timezone + DST, so we can evaluate each schedule in ITS site's local time.

**Scope proportionately:** the common case (one gateway) is just "local time" — zero config, already
correct (container inherits the host /etc/localtime). This item is the OPT-IN OVERRIDE for the rare
multi-gateway/multi-timezone fleet; cheap to have, never imposed.

- Site.timezone as an **IANA name** (e.g. Australia/Sydney) — derived from the coordinates
  (Open-Meteo returns `timezone`) or seeded from the gateway; the gateway's numeric timezone+DST is
  a reference/fallback (its DST flag = "zone observes DST", not "active now" → not enough for a
  date-correct offset on its own).
- Scheduler: evaluate a schedule's `now` in its target's site timezone (resolve schedule → target →
  meter → site) via `zoneinfo` (DST-correct); container clock is the last-resort fallback. Input
  times (fire_at, windows) are always LOCAL to the gateway; the timeline renders in that local day.
- Defaults (auto-assigned, overridable, never required): default gateway per site (seeds the site
  location/tz; target for site-unbound ops), default site (is_default). Single site → the default
  gateway dictates it automatically.
- Also: a "sync location + timezone from gateway" action (extends the existing coordinate sync), and
  an optional cross-check warning if the gateway's tz disagrees with the coordinate-derived one.

## FEAT-CONSTANTS — Automation Constants (const.* sensors) — PARITY GAP
Status: DONE (3 SoC constants). TODO: default_operating_mode constant (see FEAT-DEFAULT-MODE).
Modbus bridge has user-defined SoC constants surfaced as `const.*` condition sensors and used as
targets in the schedule builder; local bridge has none. Port for parity:
- **db.py**: `_migrate_constants` (single-row store) or reuse settings store — keys min_discharge_soc,
  max_charge_soc, demand_charge_min_soc (each 0–100, clamped) + [min,max] bounds for the form.
- **scheduler.py**: `CONST_SENSORS` (const.min_discharge_soc / const.max_charge_soc /
  const.demand_charge_min_soc) merged into the tick snapshot; add "Automation Constants" sensor group.
- **app.py**: GET/PUT `/api/constants` (mirror Modbus scheduler_api constants model, clamp 0–100).
- **settings.html + settings_tab.js**: "Automation Constants" card (3 number inputs + Save), matching
  the Modbus card the user cited as the saner reference.
- Optionally: schedule-builder presets that reference const.* (Modbus schedule_tab _tleaf pattern).
Ref: franklinwh-modbus-bridge scheduler_api.py:82-99, settings.html:389+, settings_tab.js:690+.

## FEAT-DEFAULT-MODE — Default operating mode constant — DONE (constant + sensor + derived picker)
Stores default_operating_mode (self|tou|backup) in automation_constants; exposed as
const.default_operating_mode sensor; picker options DERIVED from /api/cloud/reserves (the aGate's
mode_list). No device write. TODO (deferred, user chose "constant only"): opt-in restore-on-exit —
return the aGate to this mode when a schedule ends (per-schedule toggle, real set_mode write).

## FEAT-SCHED-HA-NAMES — HA entity friendly names in schedule Actions — DONE (condition picker enriched client-side)
Modbus bridge shows HA entities by friendly name in the schedule action pickers; local shows raw
entity_ids. Surface friendly names (from the HA instance registry) in the schedule Action HA-entity
picker + the action summary. Ref: Modbus schedule_tab HA action rendering.

## FEAT-SCHED-EXPLAIN — Schedule explainability (min/medium/full) — DONE (explain() + card panel)
Plain-language "what this schedule does" at three verbosity levels, like the FWHAI automations dialog:
trigger + conditions + action + exit, rendered readably. min = one line; medium = trigger/action/exit;
full = every condition + sensor + value spelled out.

## FEAT-CLOUD-TOU-IMPORT — Import cloud TOU → editable tariff + supervised override/restore
Status: TODO (design)
User: "Cloud API integration to view current TOU schedule, Prices, seasons, etc. Import & create a
schedule based on it ready for editing (temp name, 'TOU ' prefix). Edit presets & validate. Allow
setting TOU mode to backup and use preset. Post-execution restore prior schedule and mode."

Ties together the cloud reads, the Site/Meter/Utility/Tariff model (FEAT-UTILITY-TARIFF), rate_model,
the scheduler, and the mode-revert work. The local 1727 can't set TOU prices/seasons or timed backup —
so authoritative TOU config is READ/WRITTEN via cloud; local applies what it can (mode switch) and the
bridge supervises the temporary override + restore.

### 1. Read (cloud) — already have the endpoints
- `/api/cloud/tou` (get_gateway_tou_list) returns: `result.timers` (TOU windows), `result.list`
  (modes + soc/minSoc/maxSoc/editSocFlag), `gridChargeEn`, `touStrategy`, `workdayFlag`/`workdayTime`
  (season/weekday split), `currendId` (active). `/api/cloud/reserves` (per-mode reserve SoC),
  `/api/cloud/mode` (active). Surface a read-only "Cloud TOU" viewer: prices/periods, seasons
  (workday vs non-workday), grid-charge flag, per-mode min/max SoC.

### 2. Import → editable tariff (+ optional schedule)
- Map the cloud TOU (timers + prices + workday seasons) into our normalized Tariff `pricing`
  (seasons → months/days, blocks → time_periods, buy/sell) so it lands in the Utilities & Tariffs
  editor as a real editable plan. Name it with a **"TOU " prefix** as a template/temp (e.g.
  "TOU (imported 2026-09-23)"), unassigned until the user reviews — mirrors the schedule-import
  temp-name pattern. Attach to a utility (create/select).
- `rate_model.validate()` runs on import; surface gaps/overlaps before the user assigns it to a meter.

### 3. Edit presets + validate
- Reuse the seasonal-TOU editor (FEAT-UTILITY-TARIFF C2) + validate. "Presets" = named schemes the
  user builds from the imported plan (see FEAT-SCHED-PRESETS below): grid charge/discharge windows,
  min/max SoC, inverter power (W). Editable + validated locally; the ones local can't actuate are
  flagged "cloud-only".

### 4. Supervised override + restore (the core)
- A schedule/preset can temporarily switch **TOU → Emergency Backup** (or apply a preset scheme) for a
  window, then **restore the prior schedule AND mode** at window end.
- Restore target: **snapshot prior mode (mode_list.current_id) at fire; restore on exit; allow an
  explicit override** (Default Operating Mode constant / picked mode) — user chose "default to
  previous, allow override".
- Local path = bridge-emulated (window watchdog + dispatch-reconcile, like force dispatch), since 1727
  can't do timed backup. Cloud path = native `set_mode(reqdurationMinutes, reqnextWorkMode,
  reqbackupForeverFlag)` + TOU write when creds exist (survives bridge restart). Prefer cloud when
  available, else emulate; ALWAYS restore on exit/interruption (reconcile on boot).
- Backup durations (cloud): EMERGENCY_BACKUP_PERIODS {1d=1440, 2d=2880, 3d=4320, indefinite, custom};
  min 30 min. TOU/Self have no duration (mode-only).

### 5. Cloud writes (customise)
- For what local can't do (TOU prices/seasons, timed backup, reserve-SoC ranges, inverter power caps),
  write via cloud `set_mode`/TOU-write; the bridge's `/api/cloud/set-mode` already reports cloud-only
  params as `not_applied_locally` — extend to actually POST them when creds are configured.

Depends on: FEAT-DEFAULT-MODE (done, resume target), the mode-revert primitive (set_mode window
auto-revert — TODO), FEAT-UTILITY-TARIFF (done), rate_model (done).

## FEAT-SCHED-PRESETS — dispatch/grid-programme schedule templates
Status: DONE 2026-09-26 — added 4 force-dispatch presets ported from the Modbus bridge (peak_shave, export_bonus, solar_sponge, offpeak_charge), each requires:modbus + a target-SoC guard + SoC condition; Templates modal shows a Modbus badge. Tests in test_scheduler.py.
Named, reusable "schemes" a (TOU) schedule applies temporarily then reverts — the FWHAI preset concept:
Grid charge / Grid discharge, set min/max SoC, inverter power (W), mode switch. Built on the existing
primitives: force dispatch (power/SoC, auto-release) + set_mode (mode, auto-revert) + reserve SoC.
A preset bundles these; "return the schedule back" = the supervised restore in FEAT-CLOUD-TOU-IMPORT §4.
Local-actuatable schemes run direct; cloud-only knobs (inverter W caps, reserve ranges) via cloud API.

## FEAT-MODE-REVERT — set_mode window auto-revert (enabling primitive)
Status: TODO (near-term)
Today the scheduler `set_mode` action sets a mode and leaves it; `force` auto-releases at window end.
Give `set_mode` the same window lifecycle: snapshot prior mode (mode_list.current_id) at fire, restore
at window end (previous default; explicit override via Default Mode constant / per-action). Reconcile
on boot (persist like dispatches). This is the primitive FEAT-CLOUD-TOU-IMPORT §4 + FEAT-SCHED-PRESETS
build on. Write-block: superseded by FEAT-WRITE-CONFIRM.

## FEAT-WRITE-CONFIRM — replace global write-gate with confirm-on-consequential
Status: DONE. Follow-up: the allow_writes toggle in Settings is now inert (writes always open) — remove or relabel it as 'legacy'.
Drop the global ALLOW_WRITES 403 block. Reversible writes (circuits, constants, reserve SoC, force)
just work. Consequential writes (mode change, off-grid, timed backup) require an explicit `confirm`
flag (server-enforced) that a FWHAI-style confirm dialog provides — real, not cosmetic. Update the ~11
write-gate tests to the new contract. Rationale: the coarse gate is pure friction for the owner (it's
been on for ages) and causes the benign test failures; the real risk (mock/exposed install writing to
a physical aGate) is covered by confirming only the scary actions.

## FEAT-SCHED-ENTRY-PARITY — Entry-conditions editor parity with Modbus (styled search + derived sensors)
Status: DONE — derived sensors (§2) + styled searchable dropdown (§1). Deferred: 'at max rate' ETAs (need a Modbus rate round-trip, not in the tick).
User showed the Modbus/FWHAI Entry-conditions dropdown as the reference; the local editor is a plain
native <select>. Gaps:
1. **Styled searchable dropdown** — replace the native <select> (sensor picker in conditions AND
   exit-conditions, and the value=sensor lookup) with a custom styled dropdown that has a
   "Filter sensors…" text box filtering the grouped options live. Keep optgroup grouping
   (Gateway / Weather & Solar / Tariff & Utility / Automation Constants / HA Live).
2. **Derived "built-in function" sensors** — the local SENSORS list is only raw gateway points; add
   the computed ones the Modbus bridge exposes (several visible in the screenshot):
   - battery.capacity_kwh (Battery Capacity), battery.stored_kwh (Battery Stored Energy),
     battery.remaining_kwh (Battery Headroom to Full)
   - ETA to Max-Charge SoC (min) + ETA to Min-Discharge SoC (min) — and the "at current rate"
     variants — computed from battery power + capacity + **const.max_charge_soc / const.min_discharge_soc**
     (the const.* constants just added are exactly these ETA targets — closes the loop with FEAT-CONSTANTS).
   - battery.status (Charging/Discharging/Standby), grid.status, net.power_w, etc. as applicable.
   Port from Modbus gateway/scheduler_sensors.py (derived-from-live-points pattern); wire into the
   tick snapshot so they're gate-able and testable.

## FEAT-MQTT-ENTITIES — publish more (opt-in) + clone Energipays MQTT Entities UI
Status: DONE (v1: grouped catalogue + opt-in groups + filterable UI + multi-gateway/mock-correct endpoint incl controls). TODO: per-aPower + BMS-cell heavy groups (need expanded poll state); the 42-entity target needs those.
User: "We only publish a fraction of the data available via MQTT. Add more, and let the user turn on
optional data — it can get excessive/slow (e.g. aPower battery cell info every 2s forever). Energipays
Bridge has a great filter UI (but no optional publish/unpublish of fields/groups). Clone that
functionality." (+ a reported defect: MQTT display broken with Mock GW).

### 1. Publish more (the coverage gap)
- Today the local bridge publishes ~15 MQTT entities (verified via /api/mqtt/entities); Energipays
  shows 42+. Add the missing sensors: per-phase power, more energy/mode/SoC fields, per-aPower stats,
  and (opt-in) per-aPower battery cell voltages/temps. Source is publish/entities.py (discovery_configs).

### 2. Opt-in optional groups (the differentiator — Energipays lacks this)
- Group entities (Core / Power / Energy / Mode / per-aPower / Battery-cells / Diagnostic). Heavy or
  high-frequency groups (battery cells @2s, per-cell arrays) default **OFF**; user toggles a group (or
  individual entity) ON. Persist the selection (app_config KV) and have the publisher honour it — so
  we don't flood MQTT/HA long-term stats. Publish cadence per group where it matters (cells slower).

### 3. Clone the Energipays MQTT Entities UI
- Filter tabs: All / Writable / Sensors / Binary / Diagnostic + live entity count + Search box +
  Republish + Clear HA (the local mqtt.html has a basic version — bring to parity). Per-entity card:
  type badge, friendly name, unit, object_id, key, current value, expandable "topics".
- ADD (beyond Energipays): a per-entity / per-group **publish toggle** (on/off) wired to §2, so the
  same screen both views AND controls what is published.

### 4. Defect — MQTT display with Mock GW (investigate)
- User reports the MQTT display broken after the in-app Mock GW changes. Headless check: /api/mqtt/
  entities returns 15 rows without JS error on BOTH the real and a mock gateway — but the mock returns
  the SAME static 15 despite publish_ha OFF, i.e. the list is not per-gateway / not reflecting actual
  published state. Reproduce the specific breakage (value updates? republish targeting the mock?),
  and make the entities list reflect the selected gateway's real published set (empty for a mock
  that isn't publishing). Ties into FEAT-DOCKER Mock GW work.

## FEAT-DEVICE-CAPABILITIES — per-aPower model table (rate + capacity), replaces the manual capacity constant
Status: FOUNDATION DONE 2026-09-30 — bundled `devicedb.APOWER_SPECS` (per-model usable/rated kWh + charge/discharge kW), `GET /api/apower-specs`, and a Settings 'Derive from aPower model × count → Fill' helper on the Battery capacity field (seeds the max-power fallback too). REMAINING: (1) CLOUD auto-resolve of total capacity via `totalCap`/`compile_capabilities` when creds present (exact, zero input); (2) does the aPower serial prefix encode the model (local detection)?; (3) direction-correct (charge≠discharge) at-max-rate ETAs.
User: "Look at the individual batteries — 5 kW fixed per aPower, except aPower S which is 10 kW variable.
Do we have the model id? FWHAI has a device table of capabilities." Correct — and the model is NOT in
the local direct API.

Facts (verified in franklinwh_cloud/const/device_catalog.json + discovery.compile_capabilities):
- `apower_models` maps model→{name, sku, type, has_mppt}. SKU encodes power: APR-05K…=aPower X (5 kW,
  has_mppt false), APR-10K…=aPower 2 (10 kW, high_capacity), APRS-10K/11K…=aPower S (10 kW, stackable,
  has_mppt TRUE — the DC-solar MPPT variant). Cloud resolves per-APowerUnit rated_power_kw +
  rated_capacity_kwh + totals.
- LOCAL direct API gives per-aPower COUNT + serials + firmware (device_firmware 1833: fhp_sn, bms_ver,
  pe_ver) but NO model/SKU/mpptEnFlag → can't distinguish aPower X (5 kW) from aPower S (10 kW).
- Modbus SunSpec 702 gives the total max rate (5 kW confirmed) but not per-model or capacity.

Plan — resolve rate + capacity per aPower, in priority order, feeding the derived ETA/energy sensors:
1. CLOUD capabilities when creds set — port compile_capabilities → per-unit rated_power_kw /
   rated_capacity_kwh + totals. Most accurate, zero user input. Store as reference (system-of-record
   pattern), refresh on demand.
2. LOCAL + ported model table — bundle the apower_models catalog (or a trimmed model→{rate_kw,
   capacity_kwh, has_mppt} map); user picks their aPower model once, × the local aPower count. Offline.
3. Modbus 702 for total max rate as a fallback.
Replaces the manual battery_capacity_kwh constant with a resolved device capability (keep the constant
as a manual override). Also UNBLOCKS the deferred "at max rate" ETAs (FEAT-SCHED-ENTRY-PARITY) — the
max rate becomes count×per-model rate. Research lead: does the aPower serial prefix encode the model
(would give it locally)? — inconclusive so far.

### FEAT-DEVICE-CAPABILITIES — correction: real continuous ratings (charge ≠ discharge), from datasheets
The device_catalog SKU number is NOT the continuous power. Use per-model datasheet values, and store
SEPARATE charge / discharge rates (aPower S discharge also has a with-PV variant):
- **aPower S** (APRS-10K15V1-US, datasheet https://www.franklinwh.com/document/apower-s-datasheet,
  V1.9 2026-02-12): usable **15 kWh**/unit (≤15 units = 225 kWh); **charge 8 kW continuous**;
  **discharge 10 kW battery-only / 11.5 kW with PV input** continuous; peak 15 kW@10s (off-grid
  25 kW@1s); 4 MPPTs, 5 kW/MPPT, 20 kW STC; RTE 90.5%. has_mppt = true.
- **aPower X** (original): ~13.6 kWh, 5 kW charge/discharge (matches the Modbus 702 WChaRte/WDisChaRte
  = 5000 W). has_mppt = false. (Confirm exact usable kWh from its datasheet.)
- **aPower 2** (high_capacity, APR-10K15V2): capture from its datasheet (likely 15 kWh / 10 kW) — TODO.
Implications: the derived "at max rate" ETAs must use the DIRECTION-correct rate (charge vs discharge)
× aPower count, and the with-PV discharge boost only when PV is producing. Capacity per unit is
per-model (13.6 vs 15 kWh), so the capacity constant should default from model×count, not a global
13.6. Keep a bundled model→specs table sourced from datasheets; refresh from cloud capabilities when
creds exist.

### FEAT-DEVICE-CAPABILITIES — capacity cross-checks (user 2026-09-29)
The FWHAI **device table** (`franklinwh_cloud/const/device_catalog.json`, per-aPower
name/sku/model/type/has_mppt) is the source for model→specs; supplement it with these capacity facts:
- **Cell-level derivation (offline cross-check):** an aPower pack is **CATL 314 Ah LFP cells × 16 in
  series** → ~51.2 V nominal × 314 Ah ≈ **16.1 kWh rated** per pack. Useful as a sanity check on the
  datasheet kWh and as a last-resort estimate; chemistry/cell count can change by model, so never
  hardcode — treat as a default, overridable.
- **Original aPower (aPower X):** **13.6 kWh usable**, **15 kWh rated**.
- **aPower 2:** user reports **16 kWh** — reconcile with the SKU (`APR-10K15V2`, the "15" hinting
  15 kWh) and the datasheet before trusting either; capture usable vs rated separately (TODO: pull the
  aPower 2 datasheet).
- Keep usable-vs-rated distinct throughout (the derived SoC→kWh math needs USABLE; nameplate is rated).

### FEAT-DEVICE-CAPABILITIES / at-max-rate ETA — DECISION: use Modbus 702 ratings when Modbus is enabled
User: "if we have modbus enabled we should call that — we do, so just call that." Correct — Modbus
SunSpec 702 (WChaRteMaxRtg / WDisChaRteMaxRtg) reports the ACTUAL installed hardware's max charge/
discharge, so it is inherently model-correct (aPower X→5 kW, aPower S→8 kW charge/10 kW discharge) and
self-updating — no manual model table needed for the RATE. We already read it via
battery_control._ratings() (discover_ratings()).
Build the deferred "at max rate" ETAs on this:
- Add a TTL-cached ratings accessor (e.g. battery_control.cached_ratings(host), ~1 h TTL — ratings are
  static; one Modbus 702 read, not per-tick). Returns (max_charge_w, max_discharge_w) or (None, None)
  when Modbus is disabled/unreachable → the at-max-rate ETA then reads None (graceful).
- derived_snapshot: battery.time_to_charge_min / time_to_discharge_min = _eta_min(cap, stored, const
  SoC target, cached charge/discharge rate). Direction-correct rate.
- Capacity (kWh) is still separate: Modbus SunSpec WHRtg (802/713) could supply it too — check the
  franklinwh-modbus lib exposes it; else keep the battery_capacity_kwh constant / model-table default.
The bundled model→specs table (datasheet values) stays only as a FALLBACK for capacity and for the
no-Modbus case; Modbus-live is the primary source when enabled.

## FEAT-SCHED-SENSOR-PARITY — close the entry-condition sensor gap vs Modbus (61 missing → 2 buckets)
Status: TODO — §A is a single sweep; §B waits on FEAT-BILLING-SERVICE.
Full diff (Modbus scheduler_sensors.py = 89 sensors; local = 40 exposed): 61 missing. NOT a capability
gap for most — the data already exists in the bridge, it just isn't wired into the tick snapshot.

### §A — FEASIBLE NOW (42): expose data the bridge already has. Do in one sweep.
- time.* (5): hour/dow/month/utc_offset_h/tz_ok — local clock + gateway tz (1201 time_location).
- dispatch.* (6): active/source/entry/action/since_min/expires_min — the bridge's own dispatch tracker
  (active_dispatches + reconcile). "Bridge is overriding the gateway" — high value.
- gateway.* (7): serial/model/device_type/manufacturer/version/options/battery_capable — login
  manifest (1101) + gateway roster + battery_control.available().
- inverter.* (4): status/power_rating_w/utilised_w/unutilised_w — power_rating_w = cached Modbus 702
  ratings (DONE); utilised=|battery_power_w|; unutilised=rating−utilised; status from 1703/1704.
- battery.reserve_pct/self/tou (3): mode_list + mode_soc (/api/cloud/reserves).
- service.pto_status/pto_approved/country/timezone/tz_matches_clock (5): from the Utility/Meter/Site
  model (pto_status on meter, country on utility, tz on site/tariff) — extend tariff_snapshot.
- tariff.demand_window_active/bonus_window_active/export_charge_window_active/import_window_active (4):
  from the tariff demand_window/bonus_window/charge_window config via rate_model.
- energy.{grid_import,grid_export,solar,battery_charge,battery_discharge}.total_kwh (5): metrics store.
- grid.status (label), mode.raw (workMode code), pv.is_generating (solar>threshold) (3): trivial.

### §B — BLOCKED on FEAT-BILLING-SERVICE (19): money + period-to-date accounting.
- demand.* (3), fixed.* (5), bonus.* (2), energy.period_import_kwh/import_cost/export_credit/
  unpriced_import_kwh/unpriced_export_kwh (5), tariff.export_charge_kwh/free_remaining/net_kwh/cost (4).
These need DemandTracker + FixedChargesStore + period cost accumulators (the billing engine) — no
shortcut; they accumulate over a billing period, not a point-in-time read.

## FEAT-SYSTEM-SETUP — per-gateway install profile (System Setup card + schedule sensors)
Status: DONE (v1: solar+generator derived, others default+override, card + system.* sensors). TODO: grid_forming/whole_home from 1701 when reliable; solar_type=dc from aPower-S capabilities (FEAT-DEVICE-CAPABILITIES).
User: "Modbus bridge has System Setup settings used in Schedule too. We need these. Some may be
derived." Modbus stores a per-gateway SiteConfig (gateways_api): whole_home_backup, grid_forming,
generator_input, load_shedding, non_backup_loads(_panel), solar_type (none/ac/dc), solar_kwp,
battery_label — shown as a "System Setup" card and used to gate what's relevant in the schedule.

Follow the cloud/device-as-reference pattern (derive but store independently, manual override wins):
DERIVE from the local API where possible, let the user override, expose the useful ones as sensors.
- solar_type + solar_kwp ← solar_pv (1903): installPV1/2port (aGate AC solar inputs) + PV1/PV2RatedPower
  (units of 100 W → 6.6 kW), remoteSolarEn/solarRatedPower; aPower S = DC MPPTs (device capabilities,
  FEAT-DEVICE-CAPABILITIES). NB local already stores pv_kwp (6.6) for the Solar Forecast — unify.
- generator_input ← generator (1901): genEn.
- grid_forming / phases ← install_profile (1701): isThreePhaseInstall, electricSys, solarInstallState.
- battery_label ← aGate model/serial (device_firmware/agate_serial) or user.
- whole_home_backup / load_shedding / non_backup_loads_panel ← install-specific: partial derive + user.
Deliver:
- A per-gateway system_setup store (or fold into the gateways/site row) + derive-on-read with manual
  override; a "System Setup" card in Settings mirroring the Modbus one (derived shown, editable).
- Scheduler: a `system.*` sensor group (system.solar_type, system.solar_kwp, system.grid_forming,
  system.generator_input, system.whole_home_backup, system.load_shedding, system.non_backup_loads) so
  a schedule can gate on install characteristics (e.g. only run a generator action if generator_input;
  gate solar logic on solar_type). Also use to hide irrelevant schedule actions.

## FEAT-SCHED-SCOPE — schedule target scope (all sites / all-or-specific gateways)
Status: TODO
User: "Add scope to parameters so a schedule has context for all sites, specific or all gateways, or
specific gateways. Purely for granular control for complex sites or setups."
Today a schedule targets one gateway (gateway_id) or the default. Add a `scope` on the schedule:
- all sites, a specific site (→ all its meters' gateways), all gateways, or a specific set of gateways.
- The tick fans the schedule's action out to every gateway in scope (each with its own snapshot +
  dispatch reconcile). Sensor conditions evaluate per-gateway (a schedule "if any/all gateways …"?
  — decide per-gateway vs aggregate). UI: a scope picker in the editor (Target: gateway → scope).
For complex multi-site / multi-gateway installs; 99.9% single-gateway users keep the default.

## FEAT-TARIFF-DATES — tariff/service effective start & end dates (never delete, supersede)
Status: DONE (v1: dates + supersede flow + status badges + billing close-on-tariff-change). TODO: per-date historical re-pricing / period splitting across a mid-period change (v1 closes+reopens the period).
User: "Utility tariff setup needs start and end date. Don't delete/remove the old service — add a new
one. Billing with start/end dates is more accurate."
- Add effective_start / effective_end (dates) to a tariff (or a service-assignment on the meter).
- Assigning a new tariff SUPERSEDES the old (sets the old's effective_end) rather than deleting it —
  history stays intact. A meter can have a timeline of tariffs.
- Billing prices each period by the tariff IN FORCE at that time (resolve tariff-for-date), and a
  period that spans a tariff change is split/attributed correctly (mirror the Modbus close-period-on-
  plan-switch). Closed billing_periods snapshot the tariff that priced them.
- Ties into FEAT-BILLING-SERVICE (period snapshots) + the Utilities & Tariffs editor.

## FIX-TOGGLE-SWITCHES — flat button/checkbox toggles → styled toggle switch (Settings first)
Status: DONE for Settings (13 toggles). Other tabs: TODO if any remain.
User: "UI has flat buttons, change to toggle switch like most are. Prioritise settings."
Replace checkbox / flat on-off controls with the app's styled toggle-switch component (as used for the
gateway enable toggle + dashboard cards) for consistency. Start with Settings: the Billing-extras
enable checkboxes (peak-demand / bonus / export-charge), and any other flat toggle controls there.

## FEAT-NAV-LAYOUT — sidebar/bottom-bar breakpoint + override + DYNAMIC bottom bar — DONE
User: iPads should default to the sidebar (not the bottom bar), overridable; a wide bottom bar
shouldn't have wide gaps from a fixed button count. Delivered: auto breakpoint lowered 1024→768 (all
iPads default to the sidebar); a 3-state Navigation override (Auto/Sidebar/Bottom bar, localStorage,
Settings → Display); the bottom-nav button row capped at max-w-md + centred so a fixed set of tabs
clusters centrally instead of spreading. Discrete media-query/boolean only — no dynamic per-pixel math.

## FEAT-DASHBOARD-CUSTOMIZE — clone Energipays "Customize Dashboard" (reorder + default-tab star)
Status: DONE 2026-09-25 (reorder) — dashboard cards merged into ONE responsive grid (layout preserved via lg:col-span) so CSS `order` reorders them; Cards modal is now "Show & reorder" with up/down arrows + styled toggles, persisted (fwh-local-dash-order). Verified: move-down reflows + persists. (Metric-tab default-star still optional/queued.)
User: clone the sleek Energipays dashboard-customisation modal. Local ALREADY has show/hide
(app.js dashCards / dashCardsOpen / toggleDashCard). Add the missing pieces:
- REORDER cards (up/down arrows per row) — persist an order array (localStorage), render cards in order.
- A "Metrics tabs" section: reorder the dashboard metric tabs (Grid/Solar/Battery/… on the power-flow
  card) + a STAR to set the default tab shown on open.
- Polish the modal to the Energipays styling (icon + label + toggle rows, "changes saved automatically",
  Done). Reuse the styled toggle switches already added.

## FEAT-SETTINGS-TABS — collapsible sections / sub-tabs for the long Settings page
Status: DONE 2026-09-26 — 16 sections grouped into 6 sub-tabs (General / Gateways / Automation / Sites & Billing / Integrations / Admin) via per-section x-show wrappers + a tab bar; active tab persisted (fwh-settings-sub). No section leakage; div-balanced; 587 passed.
User: "so much stuff crammed in there… lots of scrolling." Settings has ~14 ══ sections. Options:
- Sub-tabs within Settings (e.g. General / Gateways / Tariffs & Billing / System / MQTT / Admin), OR
- Collapsible accordions per section (remember open/closed in localStorage).
Recommend sub-tabs for the big groups + keep the most-used (Constants, Sites/Meters) prominent. Reduces
scroll; each sub-tab loads its own cards. Ties into FEAT-DASHBOARD-CUSTOMIZE's modal polish.

## FEAT-GAP-3BRIDGE — feature gap analysis: Energipays + Modbus bridge vs local bridge
Status: DONE 2026-09-25 — artifact matrix published (11 areas, Have/Partial/Missing per bridge + feasible/cloud-only/N-A verdict + ranked roadmap). Top gaps: admin backup+storage, Analytics tab+CSV, dashboard reorder.
User: "do a gap to compare energipays n modbus bridge." A whole-app feature comparison (like the
89-sensor scheduler gap, but app-wide): dashboard customisation, settings organisation, admin/backup,
metrics/storage insight, entities UI, charts, rules/scheduler, billing, notifications — across
Energipays bridge + Modbus bridge → what local is missing + why (feasible / cloud-only / N/A). Feeds
the roadmap. Explore the two sibling repos + Energipays screenshots.

# ── ADMIN (separate backlog) ──────────────────────────────────────────────

## OPS-ADMIN-BACKUP — full admin control: config + data backup / restore
Status: DONE 2026-09-25 — SQLite online-backup snapshot (create/list/download/delete, newest 10 kept), in-place restore (confirm-gated 428, audited), metrics CSV/JSON export. Settings → Storage & Admin. Tests in test_admin.py.
Full admin backup/restore from the UI: export/import the metrics DB (SQLite) + app_config (gateways,
sites/meters/utilities/tariffs, constants, system-setup, mqtt groups, schedules, notify devices) as a
single archive; scheduled/auto backups; restore with confirm. Ties into OPS-BACKUP (repo backups) but
this is the RUNTIME data. Consequential → confirm-gated writes.

## OPS-ADMIN-STORAGE — storage-usage metrics by file / tab / table
Status: DONE 2026-09-25 — GET /api/admin/storage: total DB size + SQLite page/freelist + per-table rows & time-span; Vacuum action. UI table in Settings → Storage & Admin. Tests in test_admin.py.
Admin insight into disk/storage use: metrics.db size + per-table row counts (metrics samples, bms
sessions, schedule_log, dispatches, billing_periods, app_config), retention/prune status, growth rate,
and a per-tab/feature attribution ("Battery history is 60% of the DB"). A "Storage" admin card with a
Prune/Vacuum action. Helps the user manage the ~1h@5s sample rings + long-term growth.

# ── CONTROL TAB (filed 2026-09-25, from iPad review) ──────────────────────

## FEAT-CONTROL-HARDENING — audit trail, Modbus toggle, off-grid safety, on/off-grid button
Status: DONE 2026-09-25 — control_log audit trail (+ viewer card); Modbus 502 master switch (gates ratings+dispatch, persisted); off-grid single red/green state button + settable/displayed restore-SoC floor + enriched warning; audit on offgrid/reconnect/reboot/mode/modbus. Remaining: per-gateway off-grid badge is live (via roster). Tests in test_control_hardening.py
Filed: 2026-09-25 (user review of the Control tab on iPad)
Consequential controls need safety + accountability. Items:
- **Audit trail** for every control invoked — off-grid / reconnect / reboot / reserve-SOC
  Save / go-on-grid: who (source: UI/MQTT/schedule), what, old→new value, timestamp, result.
  Persist (app_config or a control_log table) + a small viewer (reuse Logs styling). Highest value.
- **Modbus TCP 502 enable/disable toggle** belongs on the Control tab (currently only implied
  elsewhere). Live on/off of the SunSpec listener; reflects current state.
- **Off-grid warning + restore SOC.** "Go off-grid" currently has no confirm — add a warning
  dialog (consequences: runs off battery, grid disconnected). Add an OPTIONAL restore-SOC that is
  settable AND displayed — the SOC to return to / floor to hold while islanded.
- **Single-colour state button** — one button that is RED "Go off-grid" when on-grid and GREEN
  "Go on-grid" when off-grid (state-reflecting), instead of the two separate off-grid/Reconnect
  buttons. Clone the FranklinWH-AI (fwhai) pattern for this control.
- **Off-grid indicated PROMINENTLY in the top nav bar, per gateway** (see FEAT-TOPNAV-RUNSTATUS) —
  lazy polling is fine for the state, but the badge must be unmissable when islanded.

## FEAT-TOPNAV-RUNSTATUS — top-nav status pill from run_status enum (VPP + off-grid), not the power heuristic
Status: DONE 2026-09-25 (+ correction). Pill reads run_status_desc (catalog enum) for direction; OFF-GRID from 1301 (5/6/7). CORRECTION: VPP is NOT in 1301 run_status (it stays Discharging) — the truth is the Modbus M704 WSet force state (vpp_monitor). Now: monitor writes gw.vpp_active; summary+roster carry it; top-nav shows a purple VPP badge + amber Discharging chip; dashboard "Run status" shows "VPP mode" — matches the official app. Chip made sm:-visible (was md-only, vanished on portrait iPads). Verified live vs a real VPP dispatch. Tests in test_control_hardening.py
Filed: 2026-09-25
Today the top-nav charge-state pill (app.js `chargeState`) is a POWER-SIGN HEURISTIC: battery_w<0
Charging / >0 Discharging / 0 Idle. It ignores the actual `run_status` enum, so VPP mode and the
off-grid states never show in the bar (the bar said "Discharging" while run_status could be VPP or
Off-Grid Discharging).
- Drive the pill from the run_status enum (`franklinwh_local.catalog.RUN_STATUS`, mirrored in
  fieldschema.py): 0 Standby, 1 Charging, 2 Discharging, 5 Off-Grid Standby, 6 Off-Grid Charging,
  7 Off-Grid Discharging, 8 Debug, **9 VPP mode** — the same vocabulary the cloud app uses.
- **VPP detection already works** (backend): `cloud_compat.effective_mode` = "VPP mode" when
  run_status==9; `vpp_monitor.py` watches WSet/VPP force state and raised the startup CRITICAL
  ("battery is in VPP (force) mode… WSetPct=100.0%"). Just surface it in the top nav.
- Show VPP + OFF-GRID prominently and PER-GATEWAY (distinct colour/badge). Lazy-poll the state.

## BUG-MQTT-PUBENTITIES — poller.py NameError `_pub_entities` breaks ALL MQTT publishing
Status: FIXED 2026-09-25 — renamed the two stray refs to `entities` (poller.py:67,108); MQTT publisher now starts (verified live: "MQTT publisher started"). Regression test added (test_mqtt_entities.py).
poller.py line 20 imports `from .publish import entities` (bound as `entities`), but lines 67 & 108
reference `_pub_entities` → `NameError: name '_pub_entities' is not defined`, logged as
"MQTT connect failed (…:1884): name '_pub_entities' is not defined — will retry every 60s".
MQTT/HA discovery is fully down until fixed. Fix: alias the import (`from .publish import entities as
_pub_entities`) or rename the two references to `entities`. Add a test that the poller's MQTT-start
path resolves the groups symbol.

# ── VPP / CLOUD / INTEROP (filed 2026-09-25, from iPad review) ─────────────

## FEAT-VPP-CLOUD-RUNSTATUS — authoritative VPP/run-status from the Cloud API (Modbus = fallback)
Status: DONE 2026-09-25 — cloud_status.poll (get_stats effective_mode + run_status/tou_mode==9, get_programme_info partner), slow loop reusing the providers auth breaker (never locks the account; short retry on the flaky HTTP/2 link). Overlaid via _dispatch_kind: cloud VPP ('vpp' + programme) wins over Modbus FORCE ('force'); stale cloud (>15min) falls back to FORCE. UI: separate VPP (Cloud) vs FORCE (Modbus) badges + 'VPP mode · partner' run-status. PLUS capability markers: summary.capabilities (modbus_enabled/reachable, cloud_configured/available) + guarded 'needs Modbus'/'needs Cloud' pills on Control + dashboard, so features degrade honestly when a subsystem isn't configured. Verified live (cloud_state valid, effective_mode from cloud). Tests in test_control_hardening.py.
Filed: 2026-09-25
User: "calling cloud api is more reliable for run status. if this vpp mode is from outside gateway
or a true third party true vpp it will be wrong." Correct. Cloud docs confirm the truth source:
- **VPP active NOW** = `getDeviceCompositeInfo` → `runtimeData.mode` (tou_mode) **== 9**. NOT
  `run_status` (that stays the hardware action, e.g. 2=Discharging). `run_status==9` never fires
  locally. Library derives `effective_mode` = "VPP mode" when tou_mode==9 and tou_mode_desc empty.
- **Enrollment / programme** = `get_programme_info()` → `flag`, `programName`, `partnerName`
  (e.g. "Virtual Peakers (Ausgrid)"). **Dispatch today** = `get_tou_dispatch_detail()` →
  `todayVppVo.vppFlag`; SoC targets `vppSocVo` (vppSoc / vppMinSoc / vppMaxSoc).
- **Caveat (documented):** the API does NOT distinguish FranklinWH-onboarded VPP from external
  third-party — both report tou_mode==9 and come via get_programme_info. So we can show "VPP
  (partnerName)" but cannot classify onboarded-vs-third-party.
Plan: when a cloud provider is configured, source run-status/VPP from the cloud (tou_mode==9 +
programme name for the badge tooltip); keep the current Modbus M704 WSet detection (gw.vpp_active)
as the offline/no-cloud FALLBACK. Today's Modbus badge is broadly right (it saw the real cloud VPP)
but mislabels a LOCAL force (our own / Modbus-bridge dispatch) as "VPP" — cloud tou_mode fixes that.
Docs: API_COOKBOOK #vpp-mode ; CLI_SUPPORT_INFO #vpp-programme. See [[vpp-not-in-local-run-status]].

## FEAT-SCHED-IMPORT-INTEROP — accept the Modbus bridge's `franklinwh-automations` bundle
Status: DONE 2026-09-26 — scheduler.import_entries maps the Modbus bundle to our schema (force_* → {kind:force,direction,unit,power}; trigger_kind/spec → trigger_type/fire_at/interval/cron; duration_s → duration_min; conditions {match,conditions[nested]} → conditions+match; ha_actions pass through; target "default" → default gateway). Import dialog shows a "mapped from Modbus — review" note. Real uploaded file imports 3/3. Tests in test_scheduler.py.
Filed: 2026-09-25
User exported schedules from the Modbus bridge and importing into local failed with a cryptic
"undefined of undefined can be imported" dialog. TWO parts:
- **FIXED 2026-09-25:** the dialog swallowed the backend's 400. `onImportFile` now checks `r.ok`
  and toasts the real reason; the backend message names the wrong + expected type. Test added
  (test_scheduler.py::test_import_rejects_foreign_bundle_with_actionable_message).
- **TODO:** actually ACCEPT `franklinwh-automations` (v1) and MAP it to local
  `franklinwh-local-schedules`. Field mapping (from a real sample):
    action(str)+params{power_pct} → action{kind, power_pct} · trigger_kind+trigger_spec{time_of_day}
    → trigger_type+fire_at · duration_s → duration_min · entry_conditions/exit_conditions{match,
    conditions[nested]} → conditions/exit_conditions+match · ha_actions{instance_id,entity_id,
    service,data,when} → local ha_actions shape · release/priority/conflict/*_policy/entry_hold_s.
  Do it as a normaliser in validate_import/portable keyed on bundle `type`. Ideally BIDIRECTIONAL
  so the two bridges interchange freely.

## FEAT-MODBUS-SITE-TARIFF — port Site + Tariff details + templates from the Modbus bridge
Status: DONE 2026-09-26 (service fields) — added meter pto_reference + surfaced pto_status/timezone in the editor (PTO status/reference/timezone selects+inputs, PTO badge on the meter row) and a utility export-restriction note; idempotent column migration onto old DBs; models/CRUD threaded through. Local already had export limits/permissions + rated_amps/ac_type/meter_number. REMAINING (smaller): utility/tariff QUICK-START templates (Ausgrid/Amber presets) — separate follow-up.
Filed: 2026-09-25
User: "add site n tariff details from modbus bridge plus import its templates." Bring the Modbus
bridge's richer Utility Service / Site + Tariff editor fields into local (PTO status/ref, export
limits, retailer/network/country/tz, min monthly bill, plan switching) and IMPORT its service/tariff
templates + schedule TEMPLATES (peak_shave, export_bonus, ausgrid_evening, ausgrid_sponge). Ties into
FEAT-SCHED-IMPORT-INTEROP (shared bundle format) + the existing local Site/Meter/Utility/Tariff model.

## FEAT-ANALYTICS — dedicated Analytics tab + CSV/JSON export
Status: DONE 2026-09-25 — new Analytics tab (sidebar + bottom-nav): range presets
(24h/3d/7d/30d) + custom date range, per-metric toggles (SoC/Grid/Solar/Battery/Home/Gen),
line/area, dual-axis Chart.js (W + SoC%), a stats strip (avg SoC, peak solar/home/grid),
and CSV/JSON export (reuses /api/admin/metrics/export). Data from /api/metrics (gateway-scoped).

## FEAT-NOTIFY — Energipays-style push-trigger engine + delivery log
Status: DONE 2026-09-26 — notify_engine: configurable triggers (offline/online, off-grid,
dispatch, SoC thresholds) → companion devices + notify_log + stats; wired into poller +
vpp_monitor; API /api/notify/triggers|log|test; UI in the Notifications center. Tests in
test_notify_engine.py.

## FEAT-UTILITY-DATES — provider (retailer) switch dates + billing-period tagging
Status: DONE 2026-09-26 — utilities gained effective_start/effective_end (migration + models + editor "Provider from/until"); closed billing_periods stamp retailer/network/plan. Tests in test_sites_meters.py.
User: in AU/NZ you switch electricity PROVIDERS (retailers) freely; the bill has a start/end
per provider (uncommon in US/CA). Today only TARIFFS carry effective_start/effective_end
(FEAT-TARIFF-DATES done). Add the same at the UTILITY (retailer) level — effective_start/
effective_end on the utility, "supersede don't delete" on a provider switch — and stamp each
closed billing period with the active retailer/network/plan (see FEAT-BILLING-SERVICE
billing_periods). So a year's history reads correctly across a mid-year provider change.
Depends on / folds into FEAT-BILLING-SERVICE (billing_periods) + the utilities table gaining
date columns (mirror _migrate_tariff_dates). Small schema + editor add on top of what exists.

## FEAT-IMPORT-AGL-SETUP — tariff-profile import/export interchange with the Modbus bridge
Status: DONE 2026-09-26 — tariff_io maps franklinwh-bridge/tariff-profile BOTH ways (flatten/re-nest export_charge + fixed_charges; seasons already match rate_model). POST /api/tariffs/import (dry-run preview + attach to default meter + optional retailer effective_start) + GET /api/tariffs/{id}/export. UI: per-tariff Export + section Import buttons (like the Modbus service card). Ported the real AGL Energy Ausgrid NSW live: billing now configured (net $41.03/period, AGL supply charge accruing). Tests in test_tariff_io.py.
Port the actual Site + AGL energy tariff/plan configuration the user set up in the Modbus bridge
into the Local Bridge (utilities/tariffs/meter). The AGL provider tenure STARTED 2026-09-09 — use
that as the utility effective_start (FEAT-UTILITY-DATES). Likely a one-off importer or a documented
copy of the Modbus bridge's service/tariff JSON → local create_utility/create_tariff. Depends on
FEAT-UTILITY-DATES (done) + the tariff editor (done).

## FEAT-SETUP-WIZARD — first-run / re-runnable setup wizard incl. MQTT-collision detection
Status: Phase 1 (broker conflict detection) DONE 2026-09-27 — `mqtt_scan.analyze` + `GET
/api/mqtt/conflicts` + a "Scan conflicts" panel on the MQTT tab. Surfaces every FranklinWH
producer on the shared broker, tags "this bridge", warns about DUPLICATE HA devices (the real
shared-broker effect — same aGate under N bridges, not a topic clash) and flags a TRUE identifier
collision when a foreign producer overwrote our identifier's retained metadata. Re-runnable.
Remaining: a proper multi-step wizard shell + optional config steps (a "clean stale retained
configs" action would also help — the live dev broker held 20 stale producers). — Filed: 2026-09-26 (user)
User will test all three bridges on ONE HA Live instance → MQTT entities WILL collide (all use the
franklinwh_<id>_<key> namespace + homeassistant/ discovery + colliding device identifiers). Build a
setup wizard that: (1) is re-runnable anytime (not just first-run) for optional config steps;
(2) DETECTS an MQTT-entity/discovery collision against what's already on the broker (scan
homeassistant/*/franklinwh_* retained configs) and warns; (3) offers the fix — an opt-in
mqtt_node_prefix / distinct discovery namespace (e.g. franklinwh_local_) so the Local Bridge's
entities never collide with the Modbus bridge / FWHAI on a shared broker. Ties into the earlier
"opt-in mqtt_node_prefix" note. NB: changing unique_ids orphans existing HA entities — the wizard
must warn + make it a deliberate choice.

---

## DEF-SOC-SET-INHIBITED — can we set Min/Max SoC for Self-Consumption & TOU? (investigate)

**Status:** queued (investigate) — **Filed:** 2026-09-27 (user, Device tab screenshots)

User observation on the Device tab: `battery_inhibit` (1801) reads back as the sequential
integers 0,1,2,…,14 — i.e. field POSITIONS, not values (the tab already flags this: CAUTION,
unpopulated on observed firmware). Separately, `mode_config` (1403) shows `modeChoose: 14`
while runingMode=85232, name=Self-Consumption. User asks: is selecting the key from the left
list vs the "14" on the right confusing, and could that be why SoC-setting seems inhibited?

**Investigate:**
- Confirm whether SoC (reserve / Min + Max) can actually be SET locally for **Self-Consumption**
  AND **TOU** — we appear inhibited, and there seem to be Min and Max SoC for both modes.
- `modeChoose=14` meaning — is 14 a real programme id or another field-position artifact like
  1801? Cross-check against 1403 write semantics + the Cloud/Modbus reserve path.
- Tie to [[FEAT-RESERVE-SOC-NATIVE]] (native local reserve write, currently blocked) and the
  Cloud reserve path (HYBRID Phase 3). Decide if local SoC write is truly unsupported or just
  mis-mapped in the UI.
- Test plan: try setting Min/Max SoC in each mode against a real gateway (guarded) + the mock;
  capture the 1403/1801 read-back before/after.

---

## FEAT-GRID-PROFILE-TAB — dedicated "Grid & Inverter" sidebar tab (profile + import/export + inverter limits)



**PROVEN 2026-09-28 — the local 1701 write is SILENTLY IGNORED (does not work).** On-hardware
test: drove a real ~4 kW grid charge via a LOCAL switch to Emergency Backup (1727 set_mode,
reserved_soc 100 — the cloud-free way to force a 1701-respecting charge), then wrote
`kwRatePower`+`gridSoftLimit`=2000 W. Read-back: `ok:False`, values stayed `-1` (never stored);
grid draw held ~4 kW for 80 s (no clamp). So the aGate ACKs `result:0` but neither stores nor
enforces — the reserved-SoC (1405) failure mode. The modal now labels this a DIAGNOSTIC and states
the confirmed result. NEXT: the working path is the cloud REST `setPowerControl`
(globalGridChargeMax/DischargeMax, a separate GLOBAL plane) — wire it as the real "set grid caps"
action (rate-limit aware: FranklinWH 429s `getDeviceCompositeInfo` per account). See
[[FEAT-CLOUD-CROSSCHECK]] and the memory grid-1701-write-unverified.

**Phase 2 DONE 2026-09-28:** PCS write modal shipped. `POST /api/grid/limits` +
`client.set_grid_limits` — full-block read-modify-write of 1701 with a self-verifying read-back
(`ok` only when every changed field reads back as asked; catches the silent-discard case).
Confirm-gated (428), audited, 1701 added to DANGEROUS_WRITES. Modal: per-field Keep/Unlimited/
Custom/Off, dry-run frame preview, read-back verify table (before→after, OK/MISMATCH per field),
Restore-previous, and an optional cloud witness (global caps) — see [[FEAT-CLOUD-CROSSCHECK]].
Still an UNVERIFIED write path (owner is first to prove on-hardware; booleans tested last).

**Status:** queued — **Filed:** 2026-09-27 (user, install_profile/1701 screenshot)

Surface the install/electrical + grid power-plane profile on its OWN sidebar tab, together
with grid import/export limits and the inverter's real charge/discharge limits — today this
data is buried in the Device tab's raw `install_profile` (1701) card.

### Sections (grounded in the real sources — do NOT trust 1701 for the kW ratings)
1. **Grid connection**
   - `isThreePhaseInstall`, `gridPhaseConSet`/`gridPhaseSeqSet`, `ratedGridVolt`, `ratedGridHz`
   - **Supply/service amps** = `electricSupply` (=63 on this site — the OWNER confirmed a 63 A main; 63 A is a standard AU single-phase breaker). `airSwitchCur` (=100) is the aGate air-switch RATING (hardware max), which this bridge AND FWHAI previously mislabeled as "service_amps". Show both; the supply (electricSupply) is the real figure. Corrected 2026-09-27 (owner).
2. **Grid import/export limits (power plane)** — from 1701:
   - `gridExportEnable` (1), `isPcsDischgEn` (1)
   - `kwRatePower`, `gridSoftLimit`, `gridHardLimit` (all -1 = **unlimited**, same convention as
     cloud `globalGridChargeMax`/`globalGridDischargeMax`). Render -1 as "unlimited".
   - Cross-reference the Cloud global charge/discharge caps + the Utility `export_limit_kw`
     (Sites & Billing) so the user sees device-limit vs utility-permission side by side
     (ties to [[FEAT-GRID-GOVERNANCE]] — the layered permission model).
   - **PCS control modal (write) — the marquee action.** FWHAI exposes this as a **"Grid Import &
     Export"** quick-access card on its Control tab (showing the current state, e.g. "Unlimited")
     that opens a modal:
       - **Grid Import** dropdown: *Unlimited import* / *Custom Limit* (kW) / *Charge from grid not
         allowed* → `gridSoftLimit`/`kwRatePower` + the charge-enable flag.
       - **Grid Export** dropdown: *Unlimited export* / *Custom Limit* (kW) / *Export not allowed*
         → `gridExportEnable` + `gridHardLimit`.
       - Confirm / Cancel. -1 ⇒ the "Unlimited" option; a number ⇒ "Custom Limit".
     Surface it on the Grid & Inverter tab AND consider a Control-tab quick-access card to match
     FWHAI. **CAUTION:** this is a real grid-compliance WRITE — confirm the LOCAL write path
     (which cmdType writes 1701 power-plane) and gate behind ALLOW_WRITES + a confirm; read-only
     until the write is proven (cross-check DER-COMMS / the cloud `set_grid_*` equivalents).
3. **Inverter limits** — **from Modbus SunSpec 702**, NOT 1701:
   - max charge/discharge kW = `WChaRteMaxRtg`/`WDisChaRteMaxRtg` (=5000W confirmed).
   - 1701 `fhpRatePower`/`genRatePower`/`solarInvRatePower` read **0** on aGate X V10R01B04D00 —
     unreliable; show the Modbus-702 value and mark 1701 as "reads 0 on this firmware".
     See [[inverter-max-kw-from-modbus-702]].

### Notes
- Read-only surface first (it's install/config). A later phase could expose the writable bits
  (export enable, soft/hard limits) once the write path is confirmed — cross-check DER-COMMS.
- Reuse the Modbus 702 read the Battery Control widget already uses for the force Power(%) max.

---

## FEAT-BILLING-IMPORT-AUTOFETCH — one-click "Import history from Modbus bridge" (DONE 2026-09-27)

**Status:** DONE 2026-09-27 — server-side login + fetch (POST /api/billing/import-modbus) + Energy Costs modal (URL/creds, Preview/Import). Was: queued — **Filed:** 2026-09-27 (user). **Core done:** the payload import
(`POST /api/billing/import` + `billing.import_modbus_periods`, mapping the Modbus
`/api/tariff/history` schema → our `billing_periods`, dedup by (gateway, period_start)) shipped
and backfilled the real Aug/Sep periods. This item is the repeatable UI.

Remaining: an Energy Costs button that FETCHES from the Modbus bridge itself (no manual
payload). Friction = the Modbus bridge needs a login session (`POST /api/auth/login`, admin
creds), so the local bridge must authenticate server-side. Plan:
- `POST /api/billing/import-modbus {source_url, username, password, gateway, dry_run}` → login
  (cookie jar via urllib, same pattern as providers.py) → GET `/api/tariff/history?limit=240` →
  `import_modbus_periods`. Default `source_url` from `MODBUS_BRIDGE_URL` when set.
- UI: "Import from Modbus" button + small modal (URL prefilled, user/pass, dry-run preview
  showing N periods to import). Reuse the tariff-import modal styling.
- Note: Modbus rows carry empty retailer/network + no import_kwh — imported rows show
  "Imported (Modbus Bridge)" as the plan label and "–" for retailer/kWh. Consider stamping the
  current utility/tariff meta onto imported periods that fall in its effective range.

---

## FEAT-DIAG-CLI-PARITY — Local-API JSON diagnostics parity with the Cloud CLI (networking first)

**Status:** queued — **Filed:** 2026-09-27 (user). **Priority:** networking diagnostics first.

FWHAI's new setup wizard presents gateway + setup + accessories as JSON, modelled on the
FranklinWH **Cloud API CLI**'s `--json` output. Bring the Local API/CLI to parity for the useful
subset — the value is that the local path can answer the same questions **on-LAN, no cloud**.

### The good news: the data already exists locally
The library already decodes every network cmdType — this is a SURFACING gap, not a capability gap:
- **1113 connectivity** → routerStatus, netStatus, **awsStatus** (cloud `get_connectivity`)
- **1117 network_interfaces** → wifi/eth DHCP, **MAC, IP, DNS, gateway** (cloud `get_network_info`;
  already mapped in the bridge's `/api/cloud/network` via `cloud_compat.network_from_interfaces`)
- **1119 network_switches** → eth0/eth1/wifi/**4G** on-off
- **1109 wifi_scan** / **1111 wifi_config** → SSID scan / AP config
- Reachability already covered by `franklinwh-local health --json` (ping, :9000/:502, latency, sunsMdEn).

The Cloud API's networking is RICHER than a status read — it runs **diagnostic checks**. Locally
the equivalent already exists: 1113 is the aGate's self-assessed **connectivity chain**
(routerStatus → netStatus → awsStatus = LAN → internet → cloud), and the bridge can ADD LAN-side
reachability the cloud can't see. So the local Network view can match AND exceed the cloud.

### Build
1. **Network TAB in the bridge UI (headline deliverable).** A dedicated sidebar tab presenting:
   - **Connectivity diagnostic** — router / internet / **AWS-cloud** as pass-fail traffic-lights
     (from 1113 routerStatus/netStatus/awsStatus), with a **"Run diagnostics"** button that
     re-reads live.
   - **Interfaces** — WiFi (SSID, IP, MAC, DHCP, **signal/RSSI**), Ethernet eth0/eth1 (IP/MAC),
     4G/cellular (operator, **operatorRSSI**, mobile_signal) — from 1117/1118 + cloud_compat
     `network_from_interfaces` (already built).
   - **Interface switches** — eth0/eth1/wifi/4G enabled state (1119).
   - **Reachability (bridge-side, cloud CAN'T do this)** — ping, :9000 sendMqtt round-trip +
     latency, :502 Modbus, sunsMdEn config-vs-actual — reuse `health`.
   - **Active TCP connections** — the aGate's live sockets / who it's talking to. *Investigate:*
     is there a connections/netstat cmdType (sweep 110x–112x for a sockets block)? If none,
     fall back to bridge-OBSERVED connections (our own :9000 session state + port probes to
     :9000/:502, and the MQTT broker link from the MQTT tab).
   - **AWS IoT connection details** — the on-LAN answer to "is my aGate talking to the FranklinWH
     cloud, and to where". Source is concrete: **1121 `cloud_config`** = serverAddr (**AWS IoT
     endpoint**), region, MQTT credentials; **1113 awsStatus** = connected/not. Surface endpoint +
     region + connected-state + last-connect. **REDACT the MQTT credentials** (never render the
     secret — show "credentials present", like we do for HA tokens). Investigate 1833/1115 for a
     thing-name / client-id if present.
   - **AWS CloudFront edge / PoP** (like the Cloud API CLI exposes) — IMPORTANT NUANCE: a
     CloudFront PoP (`x-amz-cf-pop`, `x-amz-cf-id`, `via`) is an HTTP RESPONSE HEADER you only get
     from a CloudFront-fronted endpoint (the FranklinWH cloud REST). The aGate's own uplink is
     AWS **IoT Core** (1121 serverAddr), NOT CloudFront — so there is no PoP on the aGate→cloud
     link to read locally. BUT when the BRIDGE uses its own cloud path (FWH_CLOUD creds →
     franklinwh-cloud library → the CloudFront-fronted REST), we CAN capture x-amz-cf-pop /
     x-amz-cf-id / via from those responses and surface them — identical to what the cloud CLI
     sees, because it is the same client→edge relationship. Label it clearly as **the BRIDGE's
     edge PoP** (its network path to AWS), distinct from the aGate's IoT endpoint, and show it
     only when cloud creds are configured. Feasibility: needs the franklinwh-cloud library to
     expose response headers, else a tiny HEAD/GET header-probe to the REST base.
2. **CLI `franklinwh-local net --json`** — the same data as one JSON (1113 + 1117 + 1119 + wifi +
   reachability + connections + aws-iot); human table by default. Powers the tab + scripting.
3. **CLI `franklinwh-local setup --json`** — a consolidated **setup snapshot** matching the Cloud
   CLI / FWHAI wizard shape: gateway identity (serial/fw/model from 1101/firmware), install
   profile (1701, kW from Modbus 702 — see [[inverter-max-kw-from-modbus-702]]), accessories
   (aPowers, Smart Circuits 1409, Generator, V2L), and the networking block.
4. **Bridge endpoints** — `GET /api/network` (connectivity + interfaces + switches + reachability
   + tcp-connections + aws-iot) powering the tab, and `GET /api/setup/snapshot` (the consolidated
   JSON). These also feed the **setup wizard** ([[FEAT-SETUP-WIZARD]]) and the Grid & Inverter tab
   ([[FEAT-GRID-PROFILE-TAB]]).

### Notes / guardrails
- Document each field's Cloud-CLI equivalent inline (like catalog.py already does) so parity is
  auditable, not guessed — per "check the docs, never guess".
- Read-only diagnostics first. WiFi/AP *config writes* (1111) are a separate, later, guarded step.
- Never emit the real serial/MAC/SSID into any committed artifact or public output.

---

## FEAT-NETWORK-WATCH — live "watch" monitoring on the Network tab (phase 2)

**Status:** queued — **Filed:** 2026-09-27 (user). **Phase 1 DONE** (topology diagram + ping test
+ bridge uptime + active-link, shipped with the Network tab).

Add a **Watch** toggle that polls every ~3–5s and streams real-time stats onto the topology:
- **Live latency sparkline** (bridge↔aGate round-trip over time; reuse /api/network/ping).
- **Connection uptime** counters (bridge process; per-edge "up since").
- **Active-link tracking** (WiFi ↔ Ethernet ↔ 4G) + **signal** trend (WifiSignalStrength /
  4GSignalStrength over time).
- **AWS IoT connectivity** over time (awsStatus), and **MQTT throughput** (publish counter).
- **CloudFront PoP edge** for the account/FleetView path — capture `x-amz-cf-pop`/`x-amz-cf-id`
  from the bridge's own cloud REST responses (needs FWH_CLOUD creds; the bridge's edge, not the
  aGate's — see [[mqtt-shared-broker-coexist]] note style). Fills the "Cloud API" node's PoP.

### Notes
- aGate **uptime is NOT exposed** — 1827 `ibg_state` documents an uptime field but the real
  payload (opt/result/reason/infiNum/ibgDspState/ibgMainState/peState/bmsState) omits it. Bridge
  uptime is tracked (process start). Investigate 1708/1835 for an aGate uptime before promising it.
- Keep the poll light (a `power_flow` round-trip, not a full network_bundle) and pause when the
  tab isn't visible.

---

## FEAT-BMS-CAPTURE-SCHEDULE — Recorder tab + scheduled BMS capture, retention + max-duration caps (queued, DO NOT START)

**Status:** queued — **Filed:** 2026-09-27 (user). Do not start yet.

Let Automations/Scheduler capture BMS metrics on a schedule, with disk-safe retention.

### Capture
- **Trigger basis** options for a recording: at an interval, on **ambient temp** (threshold/change),
  and **aligned with charging / discharging schedules** (start/stop with a dispatch window).
- **Schedule types, built-in to the scheduler:** built-in presets, **user-defined**, and **one-time**.
  Reuse the existing trigger engine (window/once/daily/weekly/interval/monthly/cron) + a new
  "BMS capture" action type.

### Retention (disk-safe, all user-definable)
- BMS metrics have a **fixed max store size** (user-definable) so they can't fill the disk.
- **Auto-purge oldest** when over size, OR **time-based archive** (default **30 days**).
- **Disk-max overrides the 30-day limit** — whichever comes first wins (size cap is the hard stop).

### UI
- **BMS tab**: a config panel — capture interval/basis, max store size, retention (days), archive policy.
- **Scheduler**: BMS-capture schedules listed with a **filter by schedule type** (built-in / user / one-time).

### Owner update 2026-09-29 — Recorder as a first-class tab + hard duration cap
- **Rename the Battery "Charts" sub-tab → "Recorder"** (or add a Recorder sub-tab) — surface the
  server-side recorder as first-class, not buried under charts. It runs on the bridge (survives
  tab-close), so it's the proper background-log path (the live charts pause on tab-away by design).
- **STRICT time period:** a scheduled recording defines a bounded start→stop window (one-time or
  recurring), optionally condition-gated (start when charging/temp threshold, stop at window end).
- **Hard MAX-DURATION cap (auto-stop):** every recording must have a max duration (user default +
  a global ceiling) so it **can never run forever / too long** — auto-stops even if the browser
  is closed. This is SEPARATE from the size cap: EITHER the size cap OR the duration cap stops it,
  whichever hits first. No unbounded recording is allowed.

### Notes
- BMS recording engine already exists (`bms_record.py` `Recorder` + `/api/battery/record`) — this
  adds the SCHEDULE + RETENTION + DURATION governance. Ties to [[FEAT-SCHEDULER-RECURRENCE]] (trigger
  types) and the metrics store retention already in db.py (METRICS_RETENTION_DAYS) — reuse that
  pattern with a size cap AND a max-duration auto-stop. See [[FEAT-BMS-SESSIONS-SCHEDULED]].

---

## FEAT-CLOUD-POP-METRICS — CloudFront PoP edge metrics + drill-down (background capture)

**Status:** queued — **Filed:** 2026-09-27 (user, FWHAI API-Metrics + PoP-map screenshots).
**Prereq:** cloud creds (FWH_CLOUD_EMAIL/PASSWORD) configured — cannot verify without them.

FWHAI has a full API-Metrics page (internal call counts, verbs, rate limiter, raw traces). We do
NOT need all that — we want the **CloudFront PoP EDGE** slice for troubleshooting the account →
FleetView/Cloud API path (the "Cloud API" node on the Network tab, currently a placeholder).

### The poller already exists — piggyback, don't add one
`app.py::_cloud_status_loop` already polls the cloud every ~300s (configurable **FWH_CLOUD_STATUS_S**,
min 120s), gated on cloud creds, via `cloud_status.poll` → `franklinwh_cloud.wrapper.FranklinWHCloud`.
Capture the CloudFront response headers off THOSE calls (no new network cost):
- **x-amz-cf-pop** → PoP code (e.g. SYD62-P1) · **x-cache** → Hit/Miss · **x-amz-cf-id** → edge id
- \+ latency, http_status, error_type (timeout/auth_401/server_5xx/network/parse), endpoint, ts.
Blocker to check: does the `FranklinWHCloud` wrapper expose response headers? If not, either patch
it to surface them, or add a tiny separate HEAD/GET header-probe to the REST base.

### Background metrics (disk-safe, like the local metrics store)
- Table `cloud_api_metrics(ts, pop, cache, http_status, error_type, latency_ms, endpoint)`.
- Retention: **30 days default** + a **max-rows / max-size cap** (user-definable) with auto-purge of
  oldest — size cap overrides the day limit, whichever first. Reuse METRICS_RETENTION_DAYS + the
  size-cap pattern from [[FEAT-BMS-CAPTURE-SCHEDULE]].
- Config (Settings or the tab): capture on/off, poll interval, retention days, size cap.

### Drill-down UI (Cloud API section of the Network tab)
- **Current PoP** + region · **PoP distribution** (bar list: SYD62-P1 44.5k, SYD62-P2 1.1k, …).
- **Edge detail**: CF requests, cache-hit %, transitions count.
- **PoP transitions** log (A→B with timestamp + dwell) — the aGate/account re-homes across edges.
- **Errors & retries**: timeout / auth_401 / server_5xx / network / parse + token-refresh count.
- Optional **world map** of PoPs (phase 2 — heavier; the list + transitions carry most of the value).
- Fills the Network diagram's FleetView node PoP (ties to [[FEAT-NETWORK-WATCH]]).

---

## FEAT-SCHEDULER-BUILDER-UX — FWHAI-style Automation Builder polish (queued, DO NOT START)

**Status:** queued — **Filed:** 2026-09-27 (user, FWHAI Automation Builder screenshot). Do not start yet.
Clone the FWHAI Automation Builder UX onto our Scheduler editor. Related: [[FEAT-SCHEDULER-EDITOR-UX]]
(searchable sensor combobox / guided HA-entity picker) — this extends it.

1. **Actionable notifications** as a schedule ACTION type — Title, Message, **Response Type**
   (e.g. Yes/No buttons), **Timeout (minutes)**, and **"If user doesn't respond"** →
   abort-pipeline (skip remaining actions) OR continue. The user's response is saved as
   `notification.response_value` and usable by SUBSEQUENT actions in the pipeline (gating).
   Builds on FEAT-SCHEDULER-HA-SERVICE-ACTIONS (HA actions carry a type) + the HA actionable-
   notification path in FEAT-HA-ADDON-PARITY.
2. **Resizable editor modal** — Min / Mid / Max size buttons (top-right), like FWHAI. Default = Mid.
3. **HA Actions dropdown filterable + styled**, plus an option to pick from an **HA Entities
   drop-down** (guided entity picker) rather than typing entity ids. Ties to FEAT-SCHEDULER-EDITOR-UX.
4. **Reorderable + enable/disable action steps** — per-step up/down arrows + an enable toggle +
   remove (×) in the Action Execution Pipeline, like FWHAI. (The engine already runs actions in
   order; this adds the reorder/disable UI + persistence.) Mirrors FWHAI Automations reordering.

Note: also carry FWHAI's Value/Lookup toggle on SD params (resolve a Smart-Dispatch parameter's
value at execution time) if not already present.

---

## FEAT-STORM-HEDGE-LOCAL — local Storm Hedge (Open-Meteo warnings → Emergency Backup) + Emergency-Backup mode switch (queued)

**Status:** queued — **Filed:** 2026-09-27 (user, Storm Hedge + Confirm-Mode-Change screenshots).
Extends [[FEAT-CLOUD-STORM-HEDGE]] with a LOCAL, no-cloud path, using the existing
[[FEAT-WEATHER-SOLAR-OPENMETEO]] integration.

1. **Local Storm Hedge** — a local equivalent of FWHAI's cloud-only Storm Hedge modal:
   - System protection on/off; **"enable backup before a storm"** lead-time slider (1–5.5 h);
     **decision strategy** Auto-Active (charge immediately on alert) vs Ask Each Time (actionable
     notification → confirm). Apply Settings.
   - **Trigger source = weather, not cloud:** watch **Open-Meteo** for storm/severe-weather
     warnings (or high wind/precip thresholds), OR read the **Cloud API weather** warnings if
     cloud is configured. On a warning within the lead-time window → pre-charge the battery to a
     backup reserve (force charge / raise reserve) and optionally switch to Emergency Backup.
   - Implement as a Scheduler trigger type + action (reuse the trigger engine + weather sensors),
     so it's inspectable and re-runnable — not a hidden cloud toggle.
2. **Emergency Backup mode switch** (the "Confirm Mode Change" modal) — switch **→ Emergency
   Backup** with a **Duration** (Indefinite / Fixed D:H:M) and **Resume Mode After** (TOU /
   Self-Consumption), Confirm/Cancel. Decision: do it LOCALLY (mode switch via local 1727 /
   Modbus force + a timed auto-resume the bridge schedules) rather than the Cloud API where
   possible — the local/Modbus mode switch already exists; the timed-resume is the new bit. Fall
   back to Cloud API only if a local Emergency-Backup mode set isn't reliable. Ties to the
   dispatch-interrupt reconciliation ([[FEAT-DISPATCH-INTERRUPT-POLICY]]) so a restart doesn't
   strand a timed backup.

## FEAT-TERMINAL-CONSOLE — interactive CLI console in the web UI (FWHAI-terminal-style, but proper)

**Ask (owner, 2026-09-27):** the Raw command console + `catalog` CLI output are verbose.
Wants a proper *terminal mode* in the browser: type commands with real line editing,
arrow-key **history**, **tab-completion**, and a **prefix applied automatically** so you don't
retype `franklinwh-local --host 192.168.0.110` every time — "like FWHAI terminal mode but with
proper CLI, editing, arrows, history, etc."

**Design (proposed):**
- A REPL strip (own Device sub-tab or a bottom drawer): monospace output log above, single-line
  input below. The selected gateway from the topbar IS the implicit `--host` prefix — commands
  are just `power_flow`, `call 1405`, `mode <id>`, `1409 --data {…}`, `catalog`, `clear`, `help`.
- **History**: ↑/↓ walk previous commands (persisted to localStorage per gateway, capped ~200).
- **Editing**: standard input caret editing; Ctrl-A/E/U/K/W readline bindings; Ctrl-L clears.
- **Tab-completion**: complete cmdType aliases + subcommands from the catalog; second Tab lists.
- **Output**: labelled+grouped reply by default (reuse the Device label/group renderer), with a
  per-line toggle to raw JSON; latency + sent-frame shown like the Raw console. `catalog` renders
  the grouped table compactly (collapsible sections) instead of the wall-of-text CLI dump.
- **Safety**: writes go through the SAME `_guard_writes` gate as the Raw console; a writable verb
  requires an explicit confirm token (e.g. `--yes`), never fires on Enter alone. `?`/`!` catalog
  flags surfaced as coloured badges in completion.
- **CSP**: no xterm.js/CDN — a lightweight custom input handler (keydown + a history ring) is
  enough and keeps the artifact self-contained. Reuse `/api/device/catalog` + the raw-send endpoint.

**Owner decisions (2026-09-27):** (a) **global bottom drawer** — toggle with ` / Ctrl-`, Esc
closes; (b) **full readline** — ↑/↓ history, Tab (double-Tab lists), Ctrl-A/E/U/K/W/L, Ctrl-C.

**Status:** v1 DONE 2026-09-27 — `static/js/terminal.js` + `partials/terminal.html`, wired in
index.html; reuses GET /api/raw/catalog + POST /api/raw (428 write-guard honoured, --yes to
confirm). Renders `# <cmd> <alias>  <elapsed_ms> ms` + pretty response; `catalog [filter]`, `help`,
`history`, `clear`, `close` builtins; history persisted to localStorage (cap 200). Verified on the
demo (:8102): read 1301 OK, write 1727 → 428 without --yes.

**Follow-up DONE 2026-09-27:** launched from BOTH navs (sidebar item + pinned bottom-nav button,
highlight on open, shared `$store.app.terminalOpen`); floating pill removed (overlapped bottom
nav). One-tap PRESET chips above the input (power/run status/relays/modes/bms/install/solar/
generator/network/catalog/help — all id-free safe reads, verified 200 on the live aGate) for
fast entry on iPhone/iPad.

**Polish DONE 2026-09-28:** drag-resize drawer height (top grip, persisted `fwh-term-height`);
per-gateway command history (keyed by selected gateway, swaps on topbar change); rich `bms [N|all]`
verb — reads battery_modules (1831) then per-module cell telemetry (1705), printing
`SoC/SoH/totV/current/alarm` + `cells lo–hiV (Δ mV)  temp lo–hi°C · N cells` (verified on the live
aGate). NEXT (backlog): run offline `catalog` fully client-side, ANSI colour if wanted.

## FEAT-CLOUD-CROSSCHECK — optional cloud-API witness for local writes/reads (when creds present)

**Ask (owner, 2026-09-28):** when cloud credentials are configured, optionally cross-check a
local action against the cloud API as an independent witness — "optional double-check
functionality… could be implemented throughout." First use landed in the Grid PCS write.

**Pattern:** a best-effort, creds-gated, never-fatal helper that reads the cloud's view of the
same quantity and returns `{available, …, note}`. Skip cleanly if no creds or the optional
franklinwh-cloud lib is absent. Always label WHICH plane the cloud value is (it may be a
different storage plane that doesn't sync — e.g. cloud global caps vs local 1701).

**Done (first instance):** `/api/grid/limits` returns `cloud` = `cloud_status.read_power_control(...)`
(global grid caps) as a witness after a 1701 write.

**Backlog (roll out throughout):** SoC/reserve (cloud getSoc vs local), operating mode (cloud
get_mode vs 1725), offgrid state, generator config, tariff/TOU — each a cloud witness beside the
local read/write, same helper shape. Keep it opt-in per call (`cloud_crosscheck` flag) and cached
where a fresh login per call is too costly.

## FEAT-SOLAR-FORECAST-HOURLY-OVERLAY — actual solar bars + SoC line overlaid on the forecast chart (queued)

**Status:** queued — **Filed:** 2026-09-29 (user). **Builds on:** [[FEAT-SOLAR-FORECAST-ACTUALS]] (the
summary "actual so far" + charge/discharge band are DONE; this is the finer per-hour visualization).

**Ask:** on the Solar Forecast chart, overlay **actual** data on the **forecast** bars, per corresponding
hour — not just the summary total:
1. **Actual solar generation per hour**, drawn ON the today forecast bars for the matching period (e.g. a
   solid/darker actual bar in front of the lighter forecast bar, or a second series), so you see hour-by-hour
   where actual ran ahead/behind forecast (the card already shows "32% behind" in aggregate — this makes it
   visual per hour). Only up to `now`; future hours stay forecast-only.
2. **Actual SoC as a % line** overlaid across the chart (right-hand % axis, like Power History's SoC line),
   so battery state reads against the solar curve.

**Data (already available):** per-hour actual solar + SoC from `GET /api/metrics?bucket=3600` (the card
already loads a charge band from it — reuse the same fetch: hourly `solar_w`→kWh and `soc`). Forecast bars
come from `GET /api/solar/forecast`. Align both to the PV-location-local hour axis already in the card.

**Where:** `static/js/solar_forecast_card.js` (add an actual-solar series + SoC line to the existing bar
chart; it already has `_loadChargeBand`/`_loadSolarSplit` via api/metrics) + the chart render in the card.
Keep it mobile-safe and only for TODAY (tomorrow has no actuals). Ties to the remaining Energipays styling.

## FEAT-SOLAR-FORECAST-ACTUALS — forecast vs actual, charge overlay, Energipays styling (DONE 2026-09-29)

Enhance the Solar Forecast card (owner requests):
- **Forecast vs actual (today) — SLICE DONE 2026-09-29:** actual solar so far (summary kwh_sun) vs
  forecast shown INSIDE the Today card — kWh + % of day + progress bar + ahead/behind-vs-forecast-
  to-now (sums today's hourly bars up to now). In-card (mobile-safe, no new column). Backend added
  the daily kWh totals (kwh_sun/load/uti_in/uti_out/fhp_chg/fhp_di/gen) to the summary power block.
  **Solar split SLICE DONE 2026-09-29:** where today's solar went (→home/→battery/→grid, from
  api/energy/flow) + actual SoC, wrap-friendly, in the Today card. REMAINING: a card to the RIGHT of the forecast — "Actual Solar (as of now)":
  actual PV generated today, the solar→grid / →home / →battery breakdown (if the breakdown is
  available), and actual SoC. So forecast-today sits beside actual-today.
- **Operating-mode + charge/discharge overlay:** show the mode and whether the battery was
  charging/discharging across the day (like the Scheduler timeline strip).
- **Energipays colour scheme:** match Energipays' solar-forecast look (see owner screenshot,
  bottom half) — softer fills, axis gridlines, hour ticks.
- **Hour axis — DONE 2026-09-28:** per-bar hover tooltip (HH:MM · kW) + a 12AM/6AM/12PM/6PM
  tick row + caption (PV-location local). Forecast-vs-actual + solar split + charge/discharge overlay DONE. REMAINING: finer Energipays
  styling (gridlines/softer fills) only.

- **Solar-tracker scheduler sensor — DONE 2026-09-29** (`solar.today_kwh` + `solar_forecast.day_pct`
  + `solar_forecast.vs_expected_pct`; verified live vs_expected 115.6). Was: a built-in **`solar_forecast.*` percent
  sensor** for the scheduler — expose the actual-vs-forecast metrics as schedule CONDITION sensors:
  `solar_forecast.day_pct` (actual today ÷ full-day forecast) and `solar_forecast.vs_expected_pct`
  (actual ÷ forecast-to-now, ahead/behind — the number the card shows). e.g. "if solar >20% behind
  expected, top up battery from cheap grid." NB currently computed CLIENT-side (solar card getters);
  a scheduler sensor must be SERVER-side: join `summary.kwh_sun` + solar_forecast.py, register under
  the existing `solar_forecast.*` family (scheduler.py already exposes weather.*/solar_forecast.*).
  Ties to [[FEAT-SCHEDULER]].

## FEAT-GATEWAY-TZ-COLUMN — show each gateway's timezone in the Gateways table (queued 2026-09-28)

Settings → Gateways table: add a **TZ** column showing each gateway's site timezone (per-gateway;
gateways can differ). Source: the existing gateway-scoped `GET /api/site/timezone?gateway=<id>`
(from the aGate 1201). Simplest: after loadGateways, lazily fetch tz per row; or add a cached
`timezone` field to `_roster_entry`. See docs/TIMEZONES.md (gateway zone).

## FEAT-LOADSHED-DERIVED — "Load shedding" derived from Smart Circuits (queued 2026-09-28)

System Setup → "Load shedding" is a manual toggle; it should be **DERIVED** (badge, like "Generator
input") from Smart-Circuits presence: **Smart Circuits enabled ⇒ Load shedding present.** This is a
LOCAL-only derivation — the owner notes it came from the Modbus path, which has NO Smart-Circuits
register extensions, so Modbus can't derive it; the local bridge CAN (1409/1411). Wire the derived
value from the smart_circuits read; keep an override.

## FEAT-SMARTCIRCUIT-SCHEDULE-VIEW — show Smart-Circuit schedules (view-only) — DONE 2026-09-28

Owner: "why is the schedule info missing for Smart Circuits — even if just viewable? Generator
displays its schedules." Surface the per-circuit schedule read-only (like the Generator windows).
Technical note: the REAL schedule lives in **1409** (`swXTimeEn[]` / `swXTimeSet[]` / `swXTime[]` /
`swXFreq`, X=1..3) — **1401 reads back zeros on this firmware** (see catalog note), so read 1409.
Writes are refused (result:1 reason:-2), so keep it VIEW-ONLY. Render as a small per-circuit
timeline/list on the Smart Circuits tab.

## DEF-HA-NODE-LIGHT-MODE — Home Assistant topology node renders black/unreadable in light mode — FIXED 2026-09-28 (6181134: :style clobbered fill; use :stroke attr)

The Network topology's Home Assistant node is a black box with invisible text in light mode.
**Cause:** the rect has `style="fill:var(--surface-2)"` AND an Alpine string `:style="… stroke …"` —
the string `:style` bind REPLACES the inline style, dropping `fill`, which then defaults to SVG
black (same class as the terminal-drawer transparency bug fixed in 20bd8ef). **Fix (one line,
network.html ~L126):** drop the `:style`, keep `style="fill:var(--surface-2)"`, and set the dynamic
stroke via a `:stroke` ATTRIBUTE instead:
`:stroke="(topo.home_assistant && topo.home_assistant.configured) ? 'var(--accent)' : 'var(--border)'"`
(the `:stroke-dasharray` attribute already coexists fine). Quick fix; queued per owner.


## FEAT-HA-WEBSOCKET-STATUS — HA WebSocket + richer topology labels (queued 2026-09-28)

Owner idea (from the Network topology HA node): beyond the exposed-entity count (DONE — the HA
node now shows "N entities via MQTT discovery"), surface the HA connection modes distinctly:
**WebSocket** (the bridge does NOT currently use HA's WebSocket API — it uses REST for notify +
service calls; a WS connection would give live HA state/events and a real connected/disconnected
signal), **Notify** (REST, current), and **HA Entities** (exposed via MQTT + the per-instance count
of HA's OWN entities the bridge can read, from /api/ha/entities). Next: (a) probe each HA instance
for reachability and show connected/disconnected on the REST edge; (b) optional WS client for live
state; (c) show the read-side HA entity count per instance.

## FEAT-PRESET-THEMES — full custom bg/text preset palettes (queued 2026-09-28)

Accent theming DONE (FEAT-ACCENT: swatch + custom accent picker, recolours the whole UI via
--accent). REMAINING: full preset palettes that change BACKGROUND + TEXT + surfaces (e.g. Nord,
Carbon, Solarized). Blocker/scope: the app hardcodes ~hundreds of Tailwind `slate-*` bg/text
classes that only `[data-theme="light"]` remaps to tokens; a new palette needs the same
slate→var remap (mirror the light block for each theme) OR refactor the remap to apply to
`[data-theme]:not([data-theme="dark"])` shared. This is a global CSS change that MUST be visually
verified across every tab (headless render can't catch per-tab inconsistency) — do it WITH the
owner checking each theme. Then add a theme picker beside the accent picker. Optional: a guarded
full bg/text colour picker with a live contrast check (reject/warn on unreadable combos).

## FEAT-DASHBOARD-MODE-CARD — redesign operating-mode switch UI (dashboard card + Control tab) (DONE 2026-09-30)

**Filed:** 2026-09-29 (owner, mobile screenshot); **2026-09-30: owner flags this as higher priority than recent polish, and that the Control tab's mode switch has the SAME problem.**

The dashboard "Operating Mode & Reserves" card needs a rework:
- **Mobile wrap:** the table wraps badly on a phone (mode names break, columns cramped) — must lay
  out cleanly narrow.
- **Remove the STATUS column** — redundant with the "Active now" pill.
- **Active-mode LED:** a green LED/dot on the mode that is currently active.
- **Switch by clicking the mode name** (link style) — not a separate button.
- **Setting in a MODAL only:** switching mode + setting Reserve SoC happen in a modal, not inline
  table inputs. Show the CURRENT reserve value for each mode (read-only in the row; edit in modal).
- **Card style:** match the other dashboard cards (currently mis-aligned / different style).
- **Control tab too (owner 2026-09-30):** the Control tab's operating-mode switch shows **too much info
  for mobile** — get rid of the status (and other redundant detail), declutter to the essentials (mode +
  active LED + switch action; reserve in the modal). Apply the SAME mobile-first treatment to both the
  dashboard card and the Control-tab surface so they're consistent.
- **Cloud-gated reserve:** Reserve SoC is written via the cloud (updateSocV2). If there's **no valid
  Cloud API connection**, HIGHLIGHT or DISABLE the reserve-set control with a clear reason (ties to
  [[DEF-CLOUD-CREDS-OPAQUE]] / the cloud provider check the app already has). Mode SWITCH is local
  (1727) so it can stay enabled.

Reuse the existing `setReserve`/`setMode` store methods + the cloud-provider capability check
(`caps.cloud_*`). Local mode switch (1727) is proven; reserve write is cloud-only.
