# History, costs and tariffs

[Back to the guide index](index.md)

The bridge keeps its own history in a local SQLite database, and prices it against a
tariff you describe. This page covers what is stored, what the numbers mean, and how much
to trust them.

---

## What is stored, and for how long

![Settings → Admin → Database storage](../images/energy-and-costs/01-what-is-stored.png)

| Store | Retention |
|---|---|
| Power / metrics samples | **1 year** by default; Settings → Admin → Local history → **Keep for** (90 days, 1 year, 2 years or Forever) |
| Application log | the newest **50,000** rows |
| Hourly link-health buckets | 90 days |

**Full resolution for the last 10 days, then 5-minute rows.** Every poll is kept as it was
read for 10 days (Home Assistant's recorder keeps 10 by default too). After that, each
gateway's samples become one row per 5 minutes: each value's average, with its min and max
and the sample count, the last mode and the last tariff-tier counters. Energy over those 5
minutes is unchanged, so the charts and Energy Costs read the same totals. Once an hour the
bridge deletes what is past **Keep for**, then makes the 5-minute rows, and logs both, for
example: `Local history: 2880 samples older than 10 days kept as 288 five-minute rows (full
resolution for the last 10 days)`.

**How much disk it takes is measured, not assumed.** The Local history card shows, per
gateway, what the last 10 days take a day and what older days take a day, from this
database. On a test install polling every 30 seconds that was about 8 MB a day for the
last 10 days (each poll keeps every number it read) and about 0.4 MB a day older, so two
years come to roughly 350 MB per gateway. Keeping a year or more locally is deliberate: it
removes the only reason the gateway's own history (about 105 days) looked like the longer
record.

Settings → Admin → **Database storage** shows the space on disk with the WAL and SHM files
counted, and each table's rows, size and time span.

### Choosing how long it is kept, or turning it off

![Settings → Admin → Local history](../images/energy-and-costs/02-history-auto-off.png)

Settings → Admin → **Local history** has the switch and **Keep for**: 90 days, 1 year
(the default), 2 years or **Forever**. The card shows the database size now and how fast
it grows (about 0.35–0.7 MB a day per gateway); with Forever it keeps growing. A change
applies at once and is kept across restarts.

Local history is **on by default everywhere**, the Home Assistant add-on included: the
Dashboard's power history, Analytics and Energy Costs read only this store. On the add-on
with MQTT on, Home Assistant's recorder also keeps the values the bridge publishes, so this
is a second copy of them; the card says so. Turning it off asks first, because those
charts stop getting new data; what is already stored is kept.

`METRICS_ENABLED` and `METRICS_RETENTION_DAYS` (environment variables, or the add-on's
options) still decide when they are set: the card then shows them as set for this install,
and they are changed there.

If the store is disabled, the features built on it degrade honestly rather than
pretending: the Logs tab falls back to an in-memory ring, and the endpoints that need the
store answer **503 "metrics store is disabled"**.

---

## Analytics

![The Analytics tab](../images/energy-and-costs/03-analytics.png)

Longer-horizon charts over the stored samples — power, battery, energy — with a
selectable range. This is the bridge's own record, so it survives a gateway reboot and
goes back further than the aGate's.

Local and Cloud share one layout. The top row has the time span (Day (5-min), Day (hourly),
Week, Month, Year or Lifetime; one choice for both sources, remembered in this browser),
then **Local | Cloud**, **Export ▾** and **Refresh**. In the chart card, step with **‹ ›**,
pick a day, or press **Today**: **‹ ›** move by the period (a day, a Monday-to-Sunday week, a
month or a year on the site's calendar), the day picker shows the period that holds that
day, and **Today** comes back to the current one. **‹** stops at the oldest stored sample;
the caption under the chart says where the history starts ("history from …"). Local reads
Day (5-min) in 5-minute buckets, Day (hourly), Week and Month hourly, and Year and Lifetime
in about 400 buckets; a period older than the stored history is shown empty. The chips
(SoC, Grid, Solar, Battery, Home, Generator) under the chart show or hide each series;
**Line | Area | Bars** beside them picks the style (SoC, on its own % axis, stays a line).
Dates are in your browser's own format.

### Local or Cloud

The **Local | Cloud** switch in the top row picks the source, and the page says which one
it is showing. **Export ▾** (CSV or JSON) and **Refresh** beside it work on whichever source
is shown. For Cloud, the export is the shown period (`fwh-cloud-<period>-<date>.csv`) with
every series the cloud returned, including any hidden with its chip.

Cloud needs the FranklinWH cloud account: while it is missing or
refused, a **Cloud account** link at the top of the Cloud view opens Settings → Integrations →
**FranklinWH Cloud API**. **Local** is the bridge's own record, above. **Cloud** shows the
FranklinWH cloud's energy history for the gateway picked in the top bar:

| Period | Chart |
|---|---|
| Day (5-min) | home, solar, battery and grid power in kW, as lines |
| Day (hourly) | each hour's kWh, as bars |
| Week, Month | each day's kWh, as bars |
| Year | each month's kWh |
| Lifetime | each year's kWh |

Pick the period from the time span in the top row, then step with **‹ ›**, choose a date, or press
**Today** to come back to the current period; Week starts on
its Monday, and Month and Year on the 1st. Battery discharge and grid import are drawn
above zero, battery charge and grid export below. A period with no data is left empty,
never drawn as 0. Values marked **≈** are added up from the cloud's 5-minute flows rather
than read as a total. **(inferred)** marks a value the cloud's field is only named for,
never checked. A generator that never ran is left out.

Under the chart, a chip per series shows or hides it, and the chart rescales to what is
shown. **Line | Area | Bars** picks the style for any period (a day starts as lines, the
longer periods as bars). Hover, or tap on a phone, anywhere on the chart for every shown
value at that time. Dates are shown in your browser's own format (5 Nov in
Australia, Nov 5 in the US); times are 24-hour, on the site's clock. With Bars, the
**stacked** button (at the end of the chips) draws one column per bar instead of one per
value: where the energy came from (solar, battery, grid import) above zero, and where it
went (home, battery charge, grid export) below. Refresh **↻** is at
the end of the line that says what is shown.

Cloud needs your FranklinWH cloud account in **Settings**; without one, or for a mock
gateway, the panel says why it's empty. The bridge asks the cloud as little as it can: the
current period is kept for 5 minutes and a finished one for 6 hours (**↻** asks again).
The choice of Local or Cloud and the period are remembered in this browser.

## The energy-flow Sankey

![The Energy Flow card on the Dashboard](../images/energy-and-costs/04-energy-flow-sankey.png)

On the Dashboard. It shows directional flows for a local day: solar to home, solar to
battery, solar to grid, battery to home, battery to grid, grid to home, grid to battery.

**Be clear about what this is.** The gateway reports *node* totals — how much solar, how
much import — and never the arcs between them. The bridge reconstructs the arcs from its
own power samples by a merit-order split. It is a well-founded estimate, not a meter
reading. The response carries a `quality.coverage` figure saying how much of the span
actually had samples, and the UI surfaces it; a low coverage means a gap in polling, and
the numbers should be read accordingly.

---

## Energy Costs

![The Energy Costs tab before a tariff is assigned](../images/energy-and-costs/05-energy-costs.png)

The **Energy Costs** tab shows live period-to-date billing and closed-period history:
net cost this period, peak kW, retailer and plan, and a table of closed periods. You can
export the history as CSV, import history, or **import from a Modbus Bridge** if you have
one with a longer record.

The cost is computed by integrating your grid import and export against the rate in force
at the time, plus demand charges, export charges, battery-export bonuses and standing
charges where your tariff defines them. It is an estimate for your own use — not a
revenue-grade meter, and not a substitute for your bill.

---

## Tariffs

![Settings → Sites & Billing → Utilities & Tariffs: a new utility](../images/energy-and-costs/06-tariffs.png)

Set up under **Settings → Sites & Billing → Utilities & Tariffs**. A tariff belongs to a
utility and is assigned to a meter; the meter is what a gateway connects to. (See
[Multi-gateway and sites](multi-gateway.md) for why the tariff hangs off the meter rather
than the gateway.)

### Static or dynamic

![The tariff editor's Rate type set to Dynamic (live)](../images/energy-and-costs/07b-dynamic.png)

The editor's **Rate type** toggle offers two, and only two, options:

- **Static** — your plan as written. A default buy and sell rate, which may itself be a
  **tier ladder** rather than a single number, plus optional **seasons** and **time
  periods**. Time periods are defined as periods rather than as prices, so import and
  export boundaries can differ, and a tiered price *inside* a time-of-use band needs no
  extra concept — a time period with a tiered price *is* the hybrid plan. A plain flat or
  tiered tariff is complete with no seasons and no periods at all.
- **Dynamic (live)** — priced at the live wholesale rate while this tariff is active. Two
  providers:
  - **AusNEM (AEMO spot)** — set your NEM region (`NEM_REGION`: NSW1, QLD1, SA1, TAS1,
    VIC1).
  - **Home Assistant price entity** — point at an HA entity for the buy price and
    optionally another for the feed-in price. Values in dollars are auto-detected and
    scaled to c/kWh.

  When both are configured, **the HA price entity wins over NEM.**

A dynamic tariff drives two things at once: the billing figures on the Energy Costs tab,
and the `tariff.spot_price` / `tariff.feed_in_price` sensors available to the
[Scheduler](scheduler/conditions.md) — so a rule can charge when the price is negative without you
wiring the price in twice. `GET /api/tariff/spot` shows both providers side by side.

Tariffs can be **exported, imported and validated** one at a time, so a plan can be moved
between installs or shared.

---

## Solar forecast

![Settings → Integrations → Location & Solar](../images/energy-and-costs/08-solar-forecast.png)

Optional, and off until the bridge has a location. The forecast comes from Open-Meteo.

Under **Settings → Integrations → Location & Solar**, press **Sync from gateway**. The
bridge reads the location your installer configured on the aGate, over the local API
(`cmdType 1201`), and saves it as the latitude and longitude. No cloud account is needed,
and nothing needs typing. If the aGate has no location configured, the sync says so and
leaves the fields as they were. Only then type the coordinates in yourself.

Then set the array: size in kWp, tilt, and azimuth.

**Azimuth uses Open-Meteo's convention**, which is not the one most people assume:
`0` is south, `-90` is east, `90` is west.

With a location set you get the **Solar Forecast card on the Dashboard** (not on the
Solar tab): hourly forecast bars for today and tomorrow, the current weather, actual PV
generated today against the forecast, and an ahead/behind figure versus the forecast to
now. Hours are shown in the PV location's local time, aligned to now by the forecast's own
offset, so it reads correctly from any timezone. The server caches the forecast for about
15 minutes.

The same data becomes scheduler sensors: today's forecast kWh, today's peak kW, remaining
kWh today, tomorrow's kWh, and two solar-*tracker* sensors comparing actual generation
against the forecast (percentage of today's forecast reached, and percentage versus
forecast-to-now, where above 100 means ahead of schedule).

---

## Storage and backups

![Settings → Admin: storage, export and backups](../images/energy-and-costs/09-storage-and-backups.png)

**Settings → Admin.**

- **Storage** — how much the database is using.
- **Vacuum** — reclaim space after a retention prune.
- **Back up** — write a backup, list them, download one, delete one.
- **Restore** — replace the live database from a backup. It needs an explicit
  confirmation, because it is destructive. (`allow_writes` no longer blocks it; see
  [Control](control.md#1-allow_writes-no-longer-blocks-writes).)
- **Export metrics** — a windowed export of raw samples.

One caution from this project's own history: in a container deployment the data directory
is a mount, and the database in it is the real one. Treat a restore as the destructive
operation it is.
