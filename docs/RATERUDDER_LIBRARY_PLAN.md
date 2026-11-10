# RateRudder client library — plan

**Status:** planning (no code yet). **Filed:** 2026-08-09.
**Coordinate with:** the **franklinwh-modbus-bridge** project — RateRudder is a shared
dependency (both bridges may consume it; the modbus bridge is the one that can *actuate*
battery dispatch). Keep this plan in sync with that repo's agent/owner before building.

Grounds: a real HAR capture of `raterudder.com`
(`~/Downloads/raterudder.com HTTPToolkit_2026-08-09_18-58.har`, 2026-08-09).

## What RateRudder is (recap)
Cloud energy-optimizer (Go/GCP) for FranklinWH / Powerwall that dispatches the battery
against real-time + TOU pricing + weather. It **actuates via the FranklinWH Cloud API** —
it stores the user's FranklinWH cloud credentials (see `list_ess[].credentials`) and drives
the battery itself. Its API is configuration + forecast + history, not per-step dispatch.

## Why a standalone library
Mirror the `franklinwh-cloud` / `franklinwh-local` / `franklinwh-modbus` pattern: a small,
well-tested Python client (`raterudder`) with a CLI, published like the others, so **both**
the local bridge and the modbus bridge can consume it without duplicating auth + API code.
Repo: a new `raterudder` (not inside either bridge).

## API contract (from the HAR)
Base: `https://raterudder.com/api`. **Auth: session cookie** (set by `/api/auth/login`).
All `/api/*` calls below send that cookie.

| Method | Path | Shape |
|---|---|---|
| GET | `/api/auth/status` | `{authRequired, clientIDs, email, loggedIn, sites}` |
| POST | `/api/auth/login` | req `{client, token}` → sets session cookie |
| GET | `/api/list/utilities[?siteID=]` | `[{id, name, rates}]` |
| GET | `/api/list/ess[?siteID=]` | `[{id, name, credentials}]` (ESS = battery systems; **holds FranklinWH creds**) |
| POST | `/api/join` | req `{create, name}` → `{siteID}` (link/create a site) |
| GET | `/api/settings?siteID=` | full optimizer config (below) |
| POST | `/api/settings` | same keys + `siteID`, `credentials` (update config) |
| GET | `/api/utility/periods?siteID=&utilityProvider=&utilityRate=` | `[{name, start, end, hours}]` (tariff periods) |
| GET | `/api/forecast?siteID=&overrideHomeLoadPredictionStrategy=` | `{energyHistory, priceHistory, simulation, solar1hForecast, updated}` |
| GET | `/api/history/actionsAndSavings?start=&end=` | `{actions, savings}` |

`siteID` = the user's site (e.g. `david.hona`). `utilityProvider` (e.g. `globird`) +
`utilityRate` identify the tariff. `settings` keys include: `gridChargeBatteries`,
`gridExportBatteries`, `gridExportSolar`, `minBatterySOC`, `socBufferPercent`, `pause`,
`dryRun`, `release`, `updateGroup`, `alwaysChargeUnderDollarsPerKWH`,
`minArbitrageDifferenceDollarsPerKWH`, `minDeficitPriceDifferenceDollarsPerKWH`,
`ignoreHourUsageFloorKWH`, `ignoreHourUsageOverMultiple`, `peakSurvivalBufferMinutes`,
`solarCapacityBufferMinutes`, `solar{Azimuth,Tilt,BellCurveMultiplier,TrendRatioMax,
FullyChargeHeadroomBatterySOC,NetMeteringCreditsValue}`, `vppChargingBufferMinutes`,
`homeLoadPredictionStrategy`, `countryCode`, `postalCode`, `utilityProvider`,
`utilityRate`, `utilityRateOptions`, `ess`, `essAuthStatus`, `hasCredentials`.

## Why this matters (user, 2026-08-09)
RateRudder's price-optimization is **smarter than the FranklinWH native TOU scheduler**, so
the bridge should:
1. **Query it and expose it** — surface its forecast/plan, actions + $ savings, and settings
   as **HA sensors / metrics** and as inputs to the bridge's own **automations** (read-first,
   high value, zero conflict).
2. **Coordinate dispatch (PAUSE / RESUME)** — the bridge can do things RateRudder can't
   (local mode / off-grid / smart-circuit, and dispatch via HYBRID-CAPABILITIES). So it must
   be able to **pause RateRudder, act, then resume** — smart orchestration, the same way we
   coordinate the native Franklin TOU and **FWHAI Smart Dispatch**. RateRudder already
   exposes this: `settings.pause` (+ `dryRun`, `release`) via `POST /api/settings`. See
   BACKLOG → DISPATCH-ORCHESTRATION.

## Auth / SSO — the hard part (user's question)
**v0 — long-lived API token (IDEAL; requested from the author).** The user has asked the
RateRudder author to add long-lived API tokens. If added, this is the PRIMARY path: a single
token in bridge config, no SSO dance, stable for headless/library use — exactly like the HA
long-lived token or a PyPI token. Everything below becomes fallback. **Strongly prefer this;
it removes the whole problem.** (Design the library so the auth backend is pluggable: token →
cookie → OAuth.)

RateRudder logs in via **Apple / Google SSO** (the HAR shows `appleid.apple.com` +
`accounts.google.com`). The RateRudder step is `POST /api/auth/login {client, token}` where
`client` is `apple`/`google` and `token` is the **OIDC ID token** from that provider; the
response sets a **session cookie**. `/api/auth/status` exposes the provider **`clientIDs`**.
A headless library can't do interactive SSO, so:

- **v1 — user-supplied session (pragmatic, ship first).** The user logs in on
  raterudder.com in a browser and provides EITHER the **session cookie** OR the
  `{client, token}` from the login request (dev-tools/HAR). The library stores it and
  reuses/re-logs-in. Simple; fragile (expiry → re-supply). Mirrors how we take an HA
  long-lived token.
- **v2 — interactive OAuth (proper).** Because `clientIDs` are public, the library can run
  the provider's **Authorization Code + PKCE** flow (open a browser / local redirect, user
  consents), obtain the ID token, `POST /api/auth/login`, then persist the session cookie +
  refresh. Real work per provider (Google + Apple, Apple is fiddly), plus provider ToS /
  app-verification concerns for using RateRudder's client IDs. Do after v1.
- **Not recommended — headless-browser (Playwright)** automating the SSO with stored
  Google/Apple creds: heavy, 2FA-breaking, credential-storage risk.

**Security note:** RateRudder stores the user's **FranklinWH cloud credentials**
(`list_ess[].credentials`, `settings.credentials`) to actuate the battery. Any integration
should treat RateRudder as a trusted party holding those creds, and never log/echo them.

## Library shape (mirror franklinwh-cloud)
`raterudder/`: `client.py` (`Client` with a session + the methods below), `auth.py`
(cookie/token store + optional v2 OAuth), `models.py` (Settings, EssSystem, Utility,
UtilityPeriod, Forecast, ActionsSavings dataclasses), `cli.py` (Typer: `status`, `sites`,
`settings get/set`, `utilities`, `ess`, `periods`, `forecast`, `history`), tests with
recorded fixtures. Methods: `get_auth_status`, `login(client, token)` / `login_with_cookie`,
`list_utilities`, `list_ess`, `join`, `get_settings`, `update_settings`,
`get_utility_periods`, `get_forecast`, `get_history`, plus orchestration convenience:
`pause()` / `resume()` (patch `settings.pause`), `set_dry_run(bool)`, `is_paused()`. Auth
backend pluggable: **API token** (v0) → cookie/`{client,token}` (v1) → OAuth (v2).

## How the bridges use it (coop with the modbus bridge)
- RateRudder already **actuates via the FranklinWH cloud** — so the simplest integration is
  **read-only**: pull `forecast` (its plan / `simulation`), `history/actionsAndSavings`
  (what it did + savings), and `settings` — surface them in a bridge and/or MQTT/HA. No
  actuation needed; no conflict.
- **Execute-locally (advanced, modbus-bridge-owned):** the **modbus bridge** can dispatch
  the battery directly (WSet registers) — so it *could* execute RateRudder's plan locally
  instead of via the cloud (lower latency, no cloud dependency). The **local bridge cannot
  dispatch** (hard wall) — only mode/off-grid. So the actuation side belongs to the modbus
  bridge. This is the key coordination point: decide whether RateRudder stays the actuator
  (cloud) or a bridge executes its plan, and who owns that.
- **Expose (read-first):** publish RateRudder's forecast/plan, actions + $ savings, and
  key settings as **HA sensors / metrics** (MQTT discovery) and as **automation inputs** —
  it's smarter at price-optimization than the native TOU scheduler, so the bridge's
  automations can react to its signals.
- **Orchestrate (PAUSE/RESUME):** the bridge can `pause()`/`resume()` RateRudder
  (`settings.pause`) to take over for events it handles better (off-grid, a manual/
  scheduled dispatch, a smart-circuit event), then hand back. Same arbitration we apply to
  the native Franklin TOU and FWHAI Smart Dispatch — see BACKLOG → DISPATCH-ORCHESTRATION.
- See `BACKLOG.md` → RATERUDDER-INTERFACE for the consumer-side options (A/B/C).

## Open questions (resolve with the modbus-bridge owner before coding)
1. Repo home + package name for the shared `raterudder` lib.
2. Auth v1 shape: session cookie vs `{client, token}` re-login — which is more stable?
3. Does RateRudder expose per-step dispatch anywhere (else "execute locally" only has the
   coarse `forecast.simulation` / `settings` to work from)?
4. Is there any RateRudder personal API token (would remove the SSO problem entirely)? —
   not seen in the HAR; ask RateRudder.
