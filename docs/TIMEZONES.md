# Timezones — policy & purpose

There are **three distinct clocks** in this system, and they must never be conflated.
Every timestamp is **stored in UTC**; the timezone is a **display concern** chosen by *what the
timestamp is about*, applied at render time. This document is the contract.

## The storage invariant

- All timestamps persist as **UTC epoch seconds** in the DB and on the wire. No local time is
  ever stored.
- Timezone is applied **only at render**, per the category rules below.
- CSV / data exports emit **UTC ISO-8601** with an explicit `UTC` note — unambiguous for
  downstream tools; never a localized string.
- Offsets are derived **live** (never cached across a DST boundary).

## The three clocks

### 1. Gateway timezone — the *site* clock
Everything **measured by, or recorded against, the gateway** (the aGate's own metrics and
events). These are facts about a physical site: "2 PM" must mean 2 PM at the panel, no matter who
is looking or from where.

- **Applies to:** Power History, battery / BMS telemetry charts, analytics series, energy-flow
  (Sankey), energy-cost / billing period boundaries (the site's day), gateway event log,
  per-reading times, schedule *definitions* (a "charge at 2 PM" rule is authored in site time).
- **Source:** the aGate's own clock via cmdType **1201** (`time_location`) — the offset is the
  aGate wall-clock minus UTC (DST-correct; `timezoneStr` is usually empty so we do **not** rely on
  an IANA name). Exposed by **`GET /api/site/timezone`** → `{offset_minutes, label, agate_time}`.
- **Per-gateway:** each gateway may sit in a different zone — always use the *selected* gateway's.

### 2. Integration-host timezone — the *bridge* clock
The bridge's **system of record** — records the integration itself authors as the record-keeper.
If you're reading the bridge's own operational history, you want the bridge's own time.

- **Applies to:** the control **audit trail**, **application logs**, **notification delivery
  log**, the **scheduler activity log** (what fired, when), connection **up/down** observations,
  and bridge **file mtimes**.
- **Source:** the bridge process's local zone (`TZ` env / host `/etc/localtime`) via Python
  `datetime.now().astimezone()`. Exposed by **`GET /api/host/timezone`** →
  `{offset_minutes, label, tz_name}`. **Defaults to UTC** unless `TZ` is set on the container
  (compose: `TZ=${TZ:-UTC}`) — set it to the host's real zone for readable audit trails.

### 3. Client timezone — the *viewer* clock (presentation only)
The web/app viewer's local zone. It may be **anywhere** — a browser in Auckland reading a Sydney
site, a phone in transit, or a future mobile client in a third zone. It is **presentational,
never authoritative.**

- **Applies to:** relative times ("3 min ago"), the live "now" marker, and date-range **input
  pickers** the user sets in their own local time.
- **Source:** the browser (`Intl` / `Date` local). Nothing to expose.
- **Hard rule:** a client-tz rendering is **never** persisted, and never presented as the
  canonical timestamp of a gateway metric or a host record.

## Category → zone (the mapping)

| Category                                   | Zone    | Source                 |
|--------------------------------------------|---------|------------------------|
| Gateway metrics & events                   | Gateway | 1201 · `/api/site/timezone` |
| — Power History, battery/BMS, analytics, energy Sankey, energy-cost periods, gateway events, schedule *definitions* | | |
| Bridge system-of-record                    | Host    | `/api/host/timezone`   |
| — Audit trail, app logs, notification log, scheduler *activity* log, offline-since, file mtimes | | |
| Viewer presentation                        | Client  | browser (`Intl`)       |
| — "X ago", now-marker, date-range pickers  | | |

## Rendering technique

Timestamps arrive as epoch-UTC. To render in a target zone, **shift the epoch by that zone's
offset and format as UTC** (so the wall-clock is correct regardless of the browser's zone):

```js
_fmtSiteTime(ts)  // gateway zone  — uses $store.app.siteTzOffsetMin
_fmtHostTime(ts)  // host zone     — uses $store.app.hostTzOffsetMin
// (client zone = plain new Date(ts*1000).toLocaleString())
```

Each surface shows a small **zone label** so the reader always knows which clock they're reading
— e.g. Power History: *"times shown in aGate-local time (UTC+10)"*; audit trail: *"host time
(UTC)"*. When the three zones happen to coincide the labels are still shown (cheap, and correct
when a traveller's browser drifts).

## Edge cases

- **Schedules:** the *rule* ("charge at 2 PM") is gateway-zone (site wall-clock); the scheduler's
  *activity log* (a bridge record of what fired) is host-zone. Two different clocks on one page —
  label both.
- **DST:** derive offsets on each load (gateway from its live clock, host from `astimezone()`).
  Never cache an offset across a possible DST change.
- **Multi-gateway:** gateway-zone surfaces re-resolve when the selected gateway changes.
- **Absent source:** if the aGate 1201 read fails, gateway surfaces fall back to the client zone
  *and say so*; if `TZ` is unset the host zone is UTC (correct, if terse).

## Why this split

A metric is a fact about a place (gateway). A log entry is an act by the record-keeper (host). A
rendering is a courtesy to whoever is looking (client). Collapsing any two of these produces the
exact bug that started this: a Sydney site's chart read two hours wrong because it borrowed an
Auckland browser's clock.
