# Polling inventory: every outbound call this bridge makes

Every periodic or triggered call that the Direct Connect bridge makes to a device or
service: what starts it, what it hits, how often, what it costs, and whether anything
needs it at that rate. Written for issue #221, where the owner found the poller opening up
to three TCP connections to the Modbus TCP Server (aGate :502) every 30 s just to report
"reachable". The Modbus Bridge is producing the same table for its own side.

**Version.** Read from the code at **0.5.7** (`main`, a0b875f).

**Evidence.** Unless a row says **VM**, it comes **only from reading the code**. Nothing
here was measured on a real aGate, and no connection to one was opened. **VM** means
confirmed by read-only GETs against the 0.5.7 add-on on the QEMU test VM, on 2026-10-17.
That add-on has **one mock gateway and no real aGate**, so it confirms cadences, not
device-side cost:

- `/api/health/workers` reported cadences of poller 30 s, scheduler 15 s, supervisor 5 s,
  VPP monitor 60 s, cloud status 300 s (paused: no credentials), dispatch watchdog 30 s
  (paused: no force).
- `/api/health/link/hourly` reported **121** `local_9000` probes and 121 `icmp` probes in
  one full hour, with 121 connects. That is one poll per ~30 s (the wait is 30 s *after*
  each cycle, and a mock cycle takes milliseconds). No `modbus_502` leg was recorded,
  because mocks are never probed.
- `/api/settings` reported `timeout 20`, `retries 2`, `poll_interval 30`.

Counts that come from libraries were read from these sources. The add-on image may carry
different versions, because the bridge requires `franklinwh-modbus>=0.9` without an upper
bound (#219):

- the Direct Connect library (`franklinwh-direct-connect-api` 0.5.0 checkout): one TCP
  socket per `with _client(...)` session, reused by every request in it;
- `franklinwh-modbus` 0.9.5 (`controller.py`), on top of `pysunspec2` 1.3.6.

**Connection counts to the Modbus TCP Server (aGate :502) are estimates from reading the
code. Count the sockets before relying on them.** The estimates depend on this: in
pysunspec2 1.3.6, `scan()` opens a connection, reads the model chain and **closes it**
(`sunspec2/modbus/client.py`, `scan`). Every later `model.read()` finds no socket and
opens and closes one of its own (`sunspec2/modbus/modbus.py`, `ModbusClientTCP.read`,
`local_connect`). So each SunSpec model read made after `connect()` costs its own TCP
connection.

## Defaults used for the per-hour figures

The add-on defaults: one real gateway, `poll_interval` 30 s, `scheduler_tick_s` 15 s,
MQTT on (`config.yaml`), metrics on, and the Modbus client (this bridge) on
(`modbus_enabled` defaults to `1`). There is one Home Assistant instance, seeded from the
add-on's own Supervisor, with **no exposed entities and no price entity**. There are no
cloud credentials, no NEM region and no PV location, and no browser is open. Rows that
depend on an option say so. "Per hour" uses 120 polls per hour. A real aGate's cycle time
lowers that a little, because the 30 s wait starts after the cycle.

## The inventory

Kind: **poll** (periodic data read), **probe** (reachability check that reads no data),
**query** (on demand, for a user or API call), **heartbeat**, **discovery**, **command**
(write or control), **publish** (MQTT out).

### Modbus TCP Server (aGate :502)

| # | Kind | Purpose (consumer) | Trigger | Interval (setting) | Scope | Cost per call | Per hour (defaults) | Needed at that rate? | Source |
|---|---|---|---|---|---|---|---|---|---|
| M1 | probe | Fills `modbus_502` in the summary. Consumers: the "port 502" chips on the Dashboard, Control and Health tabs, the UI's `capState('modbus')` hint, and the `modbus_502` leg of the link history. **Not published to MQTT** (`state_payload` copies `power` only). | poller cycle | every poll: 30 s (`poll_interval`) | per gateway (skipped for mocks and when the Modbus client (this bridge) is off) | TCP connect only, no PDU. **1** connect when it opens, **3** when it does not (`any(...)` over 3 tries, 3 s timeout each, so up to 9 s) | **120** (360 if refused or filtered) | **No consumer at this rate.** The chips matter only while a browser is open, and a dispatch re-checks with a real SunSpec read anyway (M3). Could be on demand, or derived from the last real Modbus client (this bridge) operation (#221). | `client.py:841-856`, called at `client.py:988`; `poller.py:229-232` |
| M2 | probe + query | Availability, active force and ratings for the Battery Control widget and the top-bar Release button (`/api/battery/command` GET). Consumers: the widget's state and hint, its power sliders (`max_charge_w`/`max_discharge_w`) and the top-bar force pill. The pill reads only `active`, which is in memory. | **page visible**: `pollBattery()` every 15 s on **every tab**; the widget's `refresh()` on page open | the server re-runs it when its cache is older than **30 s** (hard-coded `_avail_cache`) | once per process (default gateway host) | `battery_control.status()`: a controller `connect()` = a full SunSpec **model scan** (1 connection) + M702 read + M704 orphan check (1 each), then `read_control_status()` = M704 + M715 (1 each), then `_ratings()` = M702 again (1). **≈6 TCP connections and one full scan** (estimate) | **0** with no browser. **≈120 status calls = ≈720 TCP connections and 120 full scans** while any tab is visible | **No.** The pill needs only the in-memory `active`, ratings are static, and availability is re-confirmed before any dispatch (M3). Check when the Control tab opens, or on a long TTL. **Largest :502 load found.** | `app.py:3491-3509` (`_avail_cache` 3464, `_battery_force_status` 3482); `battery_control.py:405-434`; `static/js/app.js:788-789`, `static/js/battery_control.js:35-41` |
| M3 | command | Force charge, discharge or standby (scheduler action, Control widget, API). | schedule fire / button / `POST /api/battery/command` | on demand | per gateway | `capability()` (≈5 connections: connect + `read_control_status`), then a second `_connect()` (≈3), `_ratings()` (1), `send_command()` writes (≥1). **≈10 TCP connections and 2 full scans per force** (estimate) | 0 at defaults | Yes, on demand. Could use one connection instead of two controller connects. | `battery_control.py:483-563`; `scheduler.py:1527-1599` |
| M4 | command | Release a force (button, window end, watchdog deadline or target SoC, shutdown). | button / window exit / watchdog / shutdown | on demand. The watchdog *checks* every 5 s but touches the Modbus TCP Server (aGate :502) only to release | per force | `_connect()` (≈3) + `reset_control_state()` (≥1) ≈ **4+** | 0 at defaults | Yes. | `battery_control.py:50-62, 92-110, 515-522`; `app.py:1196-1206`; `scheduler.py:2030-2033` |
| M5 | discovery | Battery charge and discharge ratings (SunSpec M702) for the scheduler's `ratings.*` sensors and the at-max-rate ETA. Also used by the Grid tab and Support info, which share the cache. | scheduler tick, via `ratings_snapshot` | cached **1 h** (`_RATINGS_TTL`, failures cached too) | per host (skipped for mocks) | `connect()` (≈3 connections, 1 scan) + `_ratings()` (M702 again, 1) ≈ **4** | **≈4** (1 refresh) | Could be slower: ratings are nameplate values. Cache for the process lifetime, or persist them and refresh on demand. | `scheduler.py:1054-1068`, `scheduler.py:1969`; `battery_control.py:458-480` |
| M6 | probe | `modbus_502` in the Network tab's reachability block and diagram, and in `/api/health`. | Network tab first shown / Refresh button; `/api/health` (no UI caller found) | on demand | per gateway | as M1: 1 or 3 connects (≤9 s) | 0 at defaults | On demand is fine. One try would do. | `client.py:234-267` (`network_bundle`), `client.py:202-231` (`health`); `app.py:3852-3858`, `app.py:1364-1366` |
| M7 | query | "Test connection" on Control → Modbus client (this bridge). | button (`POST /api/modbus/test`) | on demand | once | as M2: ≈6 connections, 1 scan | 0 | Yes. | `app.py:4399-4412` |
| M8 | query | Boot reconcile of a dispatch a restart interrupted. | startup, only if the database holds an active dispatch | once | first gateway | `status()` ≈6, plus a release or re-force depending on policy | 0 | Yes. NB the reconcile targets the first gateway (#192). | `app.py:1000-1022`; `battery_control.py:154-270` |
| M9 | probe | `/api/summary` on a **cold cache**. When no poller runs (MQTT and metrics both off) or before the first poll, every browser poll runs a full `client.summary()`, which includes M1. | page visible: `poll()` every 10 s | per browser poll | per gateway | M1 + the whole of D1 | 0 at defaults; **360** connect probes/h per open browser with MQTT and metrics off | No. On demand it should not probe the Modbus TCP Server (aGate :502) at all. | `app.py:1295-1300`; `app.py:963-968` |

`release_stale()` would also open a connection at startup, but nothing calls it (#199).
The VPP monitor no longer touches the Modbus TCP Server (aGate :502): it reads the poller's
cached 1707 programme id (`vpp_monitor.py:58-79`).

### Direct Connect :9000

Every session is one TCP connection, a 1101 login, then the listed cmdTypes on the same
socket. A failed connect is retried up to `fwh_retries` (2) times with `fwh_timeout` (20 s)
each.

| # | Kind | Purpose (consumer) | Trigger | Interval (setting) | Scope | Cost per call | Per hour (defaults) | Needed at that rate? | Source |
|---|---|---|---|---|---|---|---|---|---|
| D1 | poll | The summary. Consumers: MQTT state (HA sensors and switches), metrics history, the cached `/api/summary` and roster, scheduler conditions, notifications, the VPP monitor. cmdTypes **1301** power flow, **1726** mode list, **1205** DER comms, **1409** smart circuits, **1707** run status (programme id, grid V/Hz, relays), **1723** off-grid. | poller cycle | 30 s (`poll_interval`) + cycle time | per gateway | **1 connection, 7 requests** (login + 6) | **120 connections, 840 requests** (**VM**: 121 connects/h on a mock) | Mostly yes: it is the bridge's main data. But **1205** (`sunsMdEn`, feeding the Dashboard's SunSpec chip) changes only when someone toggles it, so every 10 min would do. A held session would cut 120 connects/h to about 0 (CONNECTION_DESIGN). | `client.py:958-1141`; `poller.py:227-234` |
| D2 | poll | aGate network state for HA's `net_*` entities (#134). cmdTypes 1113, 1118, 1119, 1121. | poller cycle, after a successful poll | 600 s (`NET_EVERY_S`, hard-coded) | per real gateway | 1 connection, 5 requests | 6 / 30 | Yes with MQTT on. **No consumer with MQTT off or `publish_ha` off**: it still runs, and the result reaches only `gw.last_state`, which nothing else reads for `net_*`. | `poller.py:236-252`; `client.py:270-286` |
| D3 | poll | Site UTC offset (1201) for the scheduler's site clock. | scheduler tick | cached 600 s (`site_time.TTL_SECONDS`). **Failures are not cached**, so a failing read retries every tick | per host | 1 connection, 2 requests | 6 / 12 | Yes; the zone rarely changes. | `site_time.py:72-94`; `scheduler.py:1947-1948` |
| D4 | poll | System profile derivation (1903 solar, 1901 generator, 1409 circuits) for the scheduler's `system.*` sensors and the setup wizard. | scheduler tick; `/api/setup` | cached 1 h (`_DERIVE_TTL`). Failures not cached | per host | 1 connection, 4 requests | 1 / 4 | Yes. | `system_setup.py:51-98` |
| D5 | discovery | Identity (serial, firmware) from the login manifest. | poller start; with MQTT on, every 60 s until the serial is known | once (60 s retry) | per gateway | 1 connection, 1 request | 0 steady state | Yes. | `poller.py:60-79, 194-197` |
| D6 | probe | "Still at its address?" before a sweep: ping, then a TCP connect to :9000. | after **3** failed polls in a row (`REDISCOVER_AFTER_FAILS`) | each failed poll past the third, until a sweep is due | per gateway | 1 ICMP + 1 connect | 0 while the gateway is up | Yes. | `client.py:152-167`; `poller.py:416-426` |
| D7 | discovery | Re-discovery sweep of the /24 (or `fwh_subnet`): connect to :9000 on every host, log in on the hits, match the serial. **:9000 only**; the Modbus TCP Server (aGate :502) is no longer swept (#123). | after D6 finds nothing | back-off 5 → 10 → 20 → 40 → 60 min (`SWEEP_GAP_MIN_S`/`MAX_S`) | per gateway | ~254 connects (1 s timeout, 128 threads) + 1 login per hit | 0 while up; ≤12 during the first hour of an outage, then 1/h | Yes, with the back-off. #183 records a scheduler heartbeat miss right after a sweep. | `client.py:170-199`; `poller.py:416-436` |
| D8 | command | HA MQTT controls: mode select (1726, 1727, 1726) and smart-circuit switch (1409 read-modify-write). | MQTT command | on demand | per gateway | 1 connection; mode = 4 requests | 0 | Yes. | `poller.py:103-116`; `publish/__init__.py:4-27`; `client.py:392-401` |
| D9 | query | UI and API reads: Battery (1705, 1703, 1835, 1833, 1105), Circuits (1409 + 1411; meter 1411), Solar (1903, 1301, 1707), Generator (1901), Grid (1701 and 1707 in **two** sessions, plus M5), Health firmware, Network bundle (1113, 1118, 1119, 1121 + ping + M6), Network ping (N× 1301), site timezone (1201, **uncached**), `/api/cmd/*`, Device tab. | tab open / button / auto-refresh (see [the UI](#the-web-ui)) | on demand | per gateway | 1 connection each, 2–6 requests; Battery is one session **per aPower** | 0 with no browser | See the UI section. | `app.py:2258-2320, 3675-3720, 3852-3985, 3987-4020, 4186-4207, 4612-4660` |
| D10 | command | Scheduler actions (mode, smart circuit, off-grid) and REST writes. | schedule fire / API | on demand | per gateway | 1 connection, 2–4 requests | 0 | Yes. | `scheduler.py:1786-1798` |

### ICMP

| # | Kind | Purpose (consumer) | Trigger | Interval | Scope | Cost | Per hour | Needed? | Source |
|---|---|---|---|---|---|---|---|---|---|
| I1 | probe | `ping` in the summary. Consumers: the "Ping" line on the Dashboard and Health tabs, and the `icmp` leg of the link history. | poller cycle | 30 s | per gateway (mocks too: they are pinged on 127.0.0.1) | 1 `ping -c 1` subprocess, ≤2 s | **120** (**VM**: 121/h) | Could be slower. D1 succeeding already proves reachability; the ping only adds information when :9000 fails. | `client.py:979`; library `discover.ping` |
| I2 | probe | D6 and the Network tab's reachability. | see D6 / tab | on demand | per gateway | 1 ping | 0 | Yes. | `client.py:160, 242` |

### MQTT broker

| # | Kind | Purpose (consumer) | Trigger | Interval | Scope | Cost | Per hour | Needed? | Source |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | publish | State JSON (retained) for every HA entity. | poller cycle | 30 s | per gateway with `publish_ha` | 1 publish (one JSON object of state keys) | 120 | Yes. #176: a failed poll publishes a state built from the failed summary. | `poller.py:336-338`; `publish/mqtt_publisher.py:96` |
| Q2 | heartbeat | Availability `online`/`offline` (retained), plus an LWT. | poller cycle | 30 s | per gateway | 1 publish | 120 | Could publish only on change; harmless. | `publish/mqtt_publisher.py:99`, LWT `:33` |
| Q3 | publish | HA discovery configs (retained). | publisher start; Republish/Clear buttons | once | per gateway | one publish per entity | 0 steady state | Yes. | `publish/mqtt_publisher.py:62-85`; `poller.py:207-220` |
| Q4 | heartbeat | The broker connection itself (paho keepalive, default 60 s). | persistent | 60 s | per gateway publisher | PINGREQ | ~60 | Yes. | `publish/mqtt_publisher.py:62` |
| Q5 | query | Ownership and orphan scans of retained discovery topics (MQTT tab, setup checks). | button / tab | on demand | once | a short-lived extra client subscribes to `homeassistant/#` configs | 0 | Yes. | `publish/mqtt_scan.py:29-52, 237-253` |

### Home Assistant REST and Supervisor

| # | Kind | Purpose (consumer) | Trigger | Interval | Scope | Cost | Per hour (defaults) | Needed at that rate? | Source |
|---|---|---|---|---|---|---|---|---|---|
| H1 | poll | Exposed HA entities as scheduler conditions. **Full `GET /api/states`**, filtered locally. | scheduler tick | **15 s** (`scheduler_tick_s`), **uncached** | **per gateway × per HA instance** with exposed entities | 1 request; the full state list (the code's own comment cites 3,949 entities on one instance; payload size not measured) | **0** (none exposed). With ≥1 exposed: **240 per gateway** | **Could be far cheaper.** One fetch per tick shared by every gateway, or `GET /api/states/<entity_id>` for each exposed entity, or a websocket subscription. | `scheduler.py:959-985`, called at `scheduler.py:1950` |
| H2 | poll | HA price entities (`tariff_price_entity`, `tariff_feedin_entity`) → `tariff.spot_price`/`feed_in_price`. Another **full `/api/states`**. | scheduler tick | 15 s, uncached | per gateway × instance | 1 full-state request | 0; **240 per gateway** when set | As H1. It also **duplicates H1** on the same tick. | `scheduler.py:1218-1247, 1307-1327`, called at `:1953` |
| H3 | poll | Per-tariff dynamic pricing from an HA entity. A third **full `/api/states`**. | scheduler tick | 15 s, uncached | per gateway | 1 full-state request | 0; **240 per gateway** when the active tariff is `dynamic`/`ha` | As H1. Up to **three** full fetches per gateway per tick. | `scheduler.py:1250-1283, 1285-1304`, called at `:1957` |
| H4 | command | Notifications: `notify.*` service calls (VPP events, notification triggers, schedule actions). | event | on demand | per enabled notify device | 1 POST each | 0 | Yes. | `vpp_monitor.py:30-48`; `notify_engine.py:111`; `ha_instances.py:245-262` |
| H5 | command | Schedule HA service calls. | schedule fire | on demand | per action | 1 POST | 0 | Yes. | `scheduler.py:1842`; `ha_instances.py:214-234` |
| H6 | query | HA tab and Settings: probe, `/api/config`, entity lists (full `/api/states`), notify targets. | tab / button | on demand | per instance | 1 request | 0 | Yes. | `ha_instances.py:36-98` |
| H7 | discovery | Supervisor `GET /services/mqtt` for broker credentials. | startup; then every 60 s while the publisher is not connected | once (60 s retry) | once | 1 request (5 s timeout) | 0 (≤60 while the broker is down) | Yes. | `ha_supervisor.py:40-50, 202`; `app.py:915`; `poller.py:182-193` |

### FranklinWH cloud (only with credentials)

| # | Kind | Purpose (consumer) | Trigger | Interval (setting) | Scope | Cost | Per hour | Needed at that rate? | Source |
|---|---|---|---|---|---|---|---|---|---|
| C1 | poll | VPP truth and operating-mode label for the top-nav badge and dashboard (`cloud_vpp`, `cloud_mode`, programme name); CloudFront PoP samples for the Network tab. | named worker `cloud-status` | **300 s** (`FWH_CLOUD_STATUS_S`, minimum 120); **45 s** after a failure | once (one gateway) | A **new login every poll** (a fresh `FranklinWHCloud` each time), `getDeviceCompositeInfo` with **`refreshFlag=1`**, and `selectProgramFlag`: ≥3 HTTPS requests | 0 at defaults; **≥36** with credentials; **≥240** while the cloud fails (80 polls) | Could be cheaper: reuse the token instead of logging in every 5 min. Whether `refreshFlag=1` makes the cloud ask the aGate for fresh data over its IoT link is **unverified**. | `app.py:1073-1147`; `cloud_status.py:32-57, 147-198` |
| C2 | probe | Credential re-check (keeps the reserve-SoC controls truthful). | poller cycle, rate-limited | 12 h (`REVALIDATE_AFTER_S`), 30 min while unreachable. In practice C1 refreshes `checked_at` every 5 min, so it does not run while C1 succeeds | once | login + 1 read, bounded to 25 s | ~0 | Yes. | `poller.py:357-378`; `providers.py:235-244, 350-367` |
| C3 | query | Reserve writes, the validate button, power-control witness reads. | button / API | on demand | once | login + 1–2 requests | 0 | Yes. | `app.py:4558-4610`; `cloud_status.py:100-117` |

**The breaker.** Only an authentication rejection counts towards the lock (3,
`_MAX_AUTH_FAILS`). A transport failure marks the breaker "unreachable" and never counts.
A locked breaker stops C1 for good (the thread exits) until the credentials are
re-entered. An unreachable cloud is retried every 45 s indefinitely
(`cloud_status.py:159-171`, `app.py:1139-1146`).

### Internet APIs and other services

| # | Kind | Purpose (consumer) | Trigger | Interval (setting) | Scope | Cost | Per hour | Needed at that rate? | Source |
|---|---|---|---|---|---|---|---|---|---|
| N1 | poll | AEMO NEM spot price → `tariff.spot_price` (scheduler conditions, billing). | scheduler tick (`nem_snapshot`, dynamic tariff) | cached **240 s** (`_TTL`). **Failures are not cached** | once per region | 1 HTTPS GET (12 s timeout), the whole NEM summary | 0 at defaults; **15** with `nem_region`; **up to 240** while AEMO fails | Yes when it works. During an outage it retries every tick and can stall the tick by up to 12 s each time; a stale price is then kept for ever (#207). | `aemo_nem.py:23-48`; `scheduler.py:1171-1182, 1270-1272` |
| N2 | poll | Open-Meteo weather and PV forecast (scheduler `weather.*`/`solar_forecast.*`, Dashboard forecast card). | scheduler tick; dashboard card | cached **900 s** (`CACHE_S`). **Failures not cached**; logs WARNING each time | once per location | 1 HTTPS GET (15 s timeout) | 0 at defaults; **4** with a PV location; **up to 240** while it fails | Yes when it works. Back off on failure. | `solar_forecast.py:91-108`; `scheduler.py:1185-1196` |
| N3 | query | Modbus Bridge REST session (`/api/providers`: is the Modbus Bridge an authorised dispatch provider?). An **HTTP** call to the Modbus Bridge app, not to the Modbus TCP Server (aGate :502). | page open (`loadReserveProvider`) | per page load | once | login + session check against the configured `modbus_bridge_url` | 0 unless configured | Could be cached. | `providers.py:82-102`; `modbus_bridge.py:123-145`; `static/js/app.js:766, 1695-1697` |
| N4 | command | Generic webhook notifications (`Notifier`). | event (poll transitions, firmware change, aGate moved) | on demand | once | 1 POST (10 s) | 0 | Yes. | `notify.py:54-68`; `poller.py:339-340` |

### Worker heartbeats (no network)

The supervisor runs every 5 s and the scheduler worker every 15 s. The VPP monitor runs
every 60 s (`FWH_VPP_MONITOR_S`, minimum 15) and makes **no** device call in steady state:
it reads the poller's cached 1707 programme id. The dispatch watchdog checks every 5 s
while a force is active. All of these are in-process; the VPP monitor's boot reconcile is
M8 (`app.py:973-1049`, `workers.py:367-428`, `battery_control.py:92-110`).

## The web UI

Every tab is in the page from the start (`templates/index.html` shows and hides them with
`x-show`), so **every component's `init()` runs at page load**, whatever tab is shown.
Some components defer their first load with `lazyTab()`; others do not. The live caps in
Settings → Real-time limits are switched off in code (`live_cap.js`; `_dashExpired()` in
`app.js:595-598`), so nothing pauses itself on a timer.

Each endpoint below was traced to its server code. **cache** means it is answered from the
poller's cache, the database or an in-process cache, with no device I/O. **device** means
it opens a session to the aGate.

### Polled on every tab while the page is visible

| Poll | Interval | Endpoint | Device? | Hidden page | Source |
|---|---|---|---|---|---|
| Summary | **10 s** (the code comments say 5 s; the timer is 10 s) | `/api/summary` or `/api/gateways/{id}/summary` | **cache** (`gw.last_summary`); **device**, the whole of D1 with M1, only on a cold cache (M9) | paused (`visibilitychange`) | `static/js/app.js:772, 599-602, 955-980`; `app.py:1647-1654, 1295-1300` |
| Battery force state | 15 s | `/api/battery/command` | **Modbus TCP Server (aGate :502)**: `status()` when the 30 s cache has expired (M2) | skipped | `app.js:788-789`; `app.py:3491-3509` |
| Gateway roster | 120 s (10 s with no gateway) | `/api/gateways` | cache | skipped | `app.js:783, 856-862`; `app.py:1692-1710` |
| Build check | 60 s | `/api/version` | none | **keeps polling** | `app.js:85-96, 806` |
| Logs (from the Logs tab's component, on **every** tab) | 10 s | `/api/logs?limit=5000` | cache (database) | **keeps polling** | `logs_tab.js:36-47, 57` |

### Polled only while a given tab or card is shown

| Tab or card | Poll | Interval | Endpoint → device? | Hidden page | Source |
|---|---|---|---|---|---|
| Dashboard: Power History | history | 90 s | `/api/metrics` → cache | skipped | `app.js:781` |
| Dashboard: energy-flow card | today's span | 120 s | `/api/energy/flow` → cache | **keeps polling** (checks the tab only) | `energy_flow_card.js:46` |
| Dashboard: solar-forecast card | forecast; solar split + charge band | 15 min; 120 s | `/api/solar/forecast` → Open-Meteo through the 15 min cache (N2); `/api/energy/flow`, `/api/metrics` → cache | **keeps polling** | `solar_forecast_card.js:12-17` |
| Network | link history | 15 s | `/api/health/link` → cache | **keeps polling** (tab check only) | `network_tab.js:23` |
| Network | probe bundle | first show, Refresh | `/api/network` → **device**: ping, M6, one :9000 session (5 requests) | — | `network_tab.js:19, 33-60` |
| Network | Watch | ~6 s while on | `/api/network/ping?count=1` → **device**: 1 session, login + 1301 | paused | `network_tab.js:274-291` |
| Battery | Auto / Chart / Watch-live | 5 s by default (2–60 s), choice persisted | `/api/battery` → **device**: 1 session × 6 requests **per aPower** | paused | `battery_tab.js:46-52, 116-205` |
| Circuits | Monitor "Auto" | 5 s | `/api/circuits/meter` → **device**: 1 session, login + 1411 | **keeps polling** (stops only on a tab switch) | `circuits_tab.js:19-58` |
| Solar | "Auto" | 10 s | `/api/solar` → **device**: 1 session, login + 1903, 1301, 1707 | **keeps polling** (stops only on a tab switch) | `solar_tab.js:12-51` |
| Settings | roster, sites, tariffs | 15 s | cache | **keeps polling** (tab check only) | `settings_tab.js:143-147` |
| Battery recording | recorder status | while recording | `/api/battery/record/status` → cache. The recorder itself reads the device server-side at its own interval, **5 s minimum** (`bms_record.py:27`) | — | `battery_tab.js:652-668` |

### Read once when the page opens

| Read | Endpoint → device? | Source |
|---|---|---|
| Battery tab first read (from a hidden tab) | `/api/battery` → **device**, 1 session, 6 requests | `battery_tab.js:85-87` |
| Generator presence | `/api/generator` → **device**, 1 session, login + 1901 | `app.js:769, 865-873` |
| Site timezone | `/api/site/timezone` → **device**, 1 session, login + 1201, **not cached** (also called on a gateway switch and from Settings, once per gateway) | `app.js:774, 1762`; `app.py:4186-4207` |
| Setup state | `/api/setup` → D4 and D3 through their caches | `app.js:158-160`; `app.py:2694-2732` |
| Battery Control widget | `/api/battery/command` → may run M2 | `battery_control.js:35-41` |
| Reserve provider | `/api/providers` → N3 when a Modbus Bridge URL is set | `app.js:766, 1695-1697` |
| Field schema, catalog, guide, host timezone, disclaimer | cache | `app.js:760-777` |

**Do browser polls lead to device reads?** The Dashboard's 10 s summary does not, while
the poller's cache is warm. The roster, history, energy-flow, logs and link-history polls
do not either. Three things do:

- the **15 s battery-force poll**, which reaches the **Modbus TCP Server (aGate :502)**
  every 30 s (M2);
- the opt-in live views (Battery, Circuits Monitor, Solar, Network Watch), each a fresh
  :9000 session per tick;
- the page-open reads.

## Per-hour totals at the default setup

One real gateway that is up, MQTT on, the Modbus client (this bridge) on, one HA instance
with nothing exposed, no cloud credentials, no NEM region or PV location.

| Target | No browser open | Add: one browser tab visible on the Dashboard |
|---|---|---|
| **Modbus TCP Server (aGate :502)** | **≈124 TCP connections**: 120 connect-only probes (M1) + ≈4 for the hourly ratings refresh (M5), with 1 SunSpec scan. 360+ if the port refuses. | **+≈720 TCP connections and +120 full SunSpec scans** (M2), so **≈844/h** |
| **Direct Connect :9000** | **≈133 sessions (TCP connections), ≈886 requests**: D1 120/840, D2 6/30, D3 6/12, D4 1/4 | +2–3 sessions at page open (Battery, Generator, site timezone; see the UI section). Dashboard polling adds 0. |
| **ICMP** | 120 pings | 0 |
| **MQTT broker** | 240 retained publishes + ~60 keepalives, 1 persistent connection | 0 |
| **Home Assistant REST** | 0 (events only) | 0. With exposed entities: 240 full `/api/states` per gateway, up to 720 with HA price sources too |
| **FranklinWH cloud** | 0 (no credentials). With credentials: ≥36 HTTPS, including 12 logins | 0 |
| **Internet APIs** | 0. With a NEM region: 15; with a PV location: 4. Each up to 240 while failing | Forecast card: served from the same 15 min cache |
| **This bridge (HTTP from the browser)** | — | ≈1,200 requests: `/api/summary` 360, `/api/logs?limit=5000` 360, `/api/battery/command` 240, `/api/version` 60, history and energy flow ≈130, roster 30 |

## Findings, ranked by risk

Modbus TCP Server (aGate :502) first, then load on the aGate, then Home Assistant, then
the internet. Everything below comes from reading the code unless marked. "No consumer"
means no code was found that uses the result.

### Touching the Modbus TCP Server (aGate :502)

1. **An open browser runs a full SunSpec scan every 30 s (M2).** `pollBattery()` asks
   `/api/battery/command` every 15 s on every tab. Its availability cache expires after
   30 s, and a refresh is `battery_control.status()`: controller `connect()` (a full model
   scan plus M702 and M704 reads), then M704 + M715, then M702 again. By the pysunspec2
   reading that is **≈6 TCP connections per refresh, ≈720 per hour** while a tab is
   visible: about six times the poller's probe in #221. The consumer needs almost none of
   it. The top-bar pill reads only the in-memory `active`, and the ratings are static.
   Availability is re-confirmed by `capability()` before any dispatch. **Change:** serve
   the GET from memory, run `status()` only when the Control tab opens or on a long TTL
   (10 min or more), and reuse M5's cached ratings. Refs #221 (same class of defect).
2. **The poller's connect-only probe has no consumer at its rate (M1).** It costs 1
   connection per poll (3 on refusal, up to 9 s), 120 to 360 an hour, around the clock. Its
   only consumers are UI chips, a UI hint and the link-history leg. MQTT never sees it, and
   a dispatch makes its own real check. **Change:** remove it from the poll. Report
   reachability from the last real Modbus client (this bridge) operation (M2 to M5), or
   probe on demand from the Network tab with a single try. Refs #221.
3. **Each controller connect is several connections, and reads are repeated (M2, M3, M5).**
   `FranklinWHController.connect()` scans, and pysunspec2 closes the socket after the
   scan. Each following model read then opens and closes its own TCP connection.
   `discover_ratings()` runs inside `connect()` and again in `_ratings()`, and
   `_check_orphaned_vpp()` reads M704, which `read_control_status()` reads again. A force
   (M3) does **two** controller connects, `capability()` then `_connect()`, for ≈10
   connections. **Change:** hold one connection per operation (`dev.connect()` before,
   `disconnect()` after), cache the scanned model map, and drop the duplicate reads. The
   connect behaviour belongs to `franklinwh-modbus`; this bridge can avoid the second
   connect and the repeated `_ratings()`. Pin the library first (#219). **Verify by
   counting sockets.** This is the estimate most in need of a measurement.
4. **The ratings refresh hourly for values that do not change (M5).** It costs ≈4
   connections and a scan per hour, per host. **Change:** cache for the process lifetime,
   persist them, and refresh on demand (Control → Test connection already reads them).
5. **A cold summary probes the Modbus TCP Server (aGate :502) from the browser (M9).** With
   MQTT and metrics both off, no poller runs, so every 10 s browser poll does a full
   `client.summary()`: one :9000 session plus M1, per open browser. **Change:** an
   on-demand summary should never probe :502.
6. **The probe retries three times with a 3 s timeout (M1, M6).** A refused port costs 3
   connections and up to 9 s per call. **Change:** one try.

### Load on the aGate (Direct Connect :9000)

7. **A fresh TCP connection and login every poll (D1).** That is 120 connects and logins
   an hour for one gateway, before any UI. A held session would remove nearly all of
   them (CONNECTION_DESIGN). Separately, **1205 `sunsMdEn` is read every poll** for one
   Dashboard chip; it changes only when someone toggles it. **Change:** held session;
   read 1205 every 10 min or on demand.
8. **A timed-out poll leaves its thread running (D1).** `asyncio.wait_for(to_thread(...),
   30)` stops waiting but not the thread. With `fwh_timeout` 20 s and `fwh_retries` 2, a
   session to an unreachable aGate can take about 60 s to fail, plus ping and the M1
   probe. The next cycle can therefore start a second session while the first is still
   connecting, so an outage gets overlapping attempts. **Change:** bound the transport's
   connect timeout and retries below the poll timeout (#183 may be related).
9. **Live views keep polling the aGate while the browser tab is hidden (D9).** Circuits →
   Monitor "Auto" (5 s, `/api/circuits/meter`) and Solar "Auto" (10 s, `/api/solar`, 3
   cmdTypes) stop on a tab switch but check neither `document.hidden` nor the live cap.
   The cap is disabled (`live_cap.js`, `_capExpired()` returns `false`). A backgrounded
   window keeps up **720 or 360 sessions an hour** indefinitely. Battery "Auto"/"Chart"
   (5 s, one session per aPower per tick, 6 requests each) pauses when hidden, but its
   choice persists in `localStorage`, so it resumes on every visit. **Change:** gate on
   visibility, re-enable a cap, or serve these from the poller.
10. **Every page load reads the aGate two or three times (D9).** The Battery tab's
    `init()` calls `load()` whatever tab is shown (tabs are `x-show`, so every component
    initialises at page load): one session, 6 requests. App start calls `/api/generator`
    (1901) and `/api/site/timezone` (1201, **uncached**, although `site_time` holds the
    same value for 10 min). **Change:** load Battery lazily (`lazyTab`), and answer
    generator presence and timezone from cache.
11. **The network read has no consumer without MQTT (D2).** It runs every 10 min even with
    MQTT or `publish_ha` off, and its result feeds only the HA `net_*` entities.
    **Change:** skip it when nothing publishes.
12. **Network watch (D9) is ~600 sessions an hour while it runs.** One session (login +
    1301) every ~6 s. It is on demand and pauses when hidden. Acceptable, but say so in
    the UI.
13. **Some failures are not cached and retry every 15 s tick (D3, D4).** The scheduler
    only ticks a gateway with a fresh snapshot, so this mainly bites when :9000 flaps.
    **Change:** a short negative cache.
14. **The sweep is bounded (D7).** ~254 connects after three failed polls and a failed
    still-at-address check, backing off to 60 min. Kept, with #183 in mind.

### Home Assistant

15. **Up to three full `GET /api/states` per gateway per tick (H1 to H3).** Exposed
    entities, HA price entities and an HA-sourced dynamic tariff each fetch the **whole**
    state list, uncached, every 15 s and once per gateway. At one gateway that is up to
    720 full-state responses an hour from an instance the code itself notes may hold ~4,000
    entities. **Change:** one fetch per tick shared by every snapshot and gateway, or
    per-entity `GET /api/states/<id>`, or a websocket subscription.
16. **MQTT availability is republished every poll (Q2).** Harmless and retained; on
    change would do. #176 covers the failed-poll state payload.

### Internet

17. **AEMO failures are retried every tick (N1).** The 240 s cache stores only successes,
    so during an AEMO outage every 15 s tick makes a 12 s-timeout request. That stalls the
    tick, and the stale value is then kept for ever (#207). **Change:** a negative cache
    with back-off.
18. **Open-Meteo failures are retried every tick (N2),** with a 15 s timeout and a WARNING
    log line each time. **Change:** back-off.
19. **The cloud poll logs in from scratch every 5 min (C1).** That is 12 logins an hour,
    and 80 an hour while the cloud fails (45 s retry, indefinitely, by design of the
    breaker). It also asks with `refreshFlag=1`. **Change:** reuse the token; back off
    transport failures exponentially; find out what `refreshFlag=1` does at the aGate
    before keeping it.

### This bridge (no device cost)

20. **The Logs tab polls even when hidden or off-screen.** Its component initialises at
    page load and fetches `/api/logs?limit=5000` every 10 s, whatever tab is shown and
    whether or not the page is visible: 360 requests an hour of up to 5,000 rows each.
    **Change:** `lazyTab` and a visibility check. `checkBuild()` (`/api/version`, 60 s)
    also ignores visibility, but it is trivial.

## Interference with the Modbus Bridge

What the Modbus Bridge polls is its session's to state. This section lists what **this**
bridge does to the same resource. The owner states (#221) that the Modbus TCP Server
(aGate :502) serves **one client at a time**. That was not re-tested here, so treat it as
the owner's statement, not a measurement.

**Same resource: the Modbus TCP Server (aGate :502).**

| Call | When | What it does to :502 | Collision risk with a polling Modbus Bridge |
|---|---|---|---|
| M1 poller probe | every poll, 24/7 | TCP connect, then close | If the server takes one client, every probe either takes the slot for an instant, delaying or refusing a Modbus Bridge reconnect, or is refused itself. A refusal then shows as "Down" on our chips, so the probe cannot tell "port closed" from "the Modbus Bridge is connected". |
| M2 availability | every 30 s while any browser tab is visible | ≈6 connections, a full SunSpec scan, M702/M704/M715 reads | **Highest.** Many short connections and dozens of register reads interleaved with the Modbus Bridge's polling. A failed scan is reported as `unreachable` or `no_sunspec`. |
| M5 ratings | hourly, per gateway | ≈4 connections, 1 scan, M702 | Low frequency, same mechanism. |
| M3 / M4 force and release | on demand | ≈10 / ≈4 connections, **writes to M704** | Two controllers writing WSet is the two-masters problem. This bridge never auto-releases a force it did not start (`vpp_monitor.py:12-14`), but a Release from this bridge ends the Modbus Bridge's force too. |
| M6 / M7 / M8 | tab, button, boot | as M1 / M2 | On demand; low. |

**Shared aGate, different port.** D1 to D9 use Direct Connect :9000, not :502. They do not
take the Modbus TCP Server's client slot. They do add load to the same gateway, which #123
records as sensitive to load. Whether :9000 sessions slow the Modbus TCP Server (aGate
:502) has **not been measured**.

**Not interference.** The VPP monitor (local 1707), the re-discovery sweep (:9000 only
since #123), D2's network reads, and N3 (an HTTP call to the Modbus Bridge *application*,
not to the Modbus TCP Server (aGate :502)).

**To verify on the reference aGate** (with the owner): with the Modbus Bridge polling,
count this bridge's sockets to :502 (`/api/diagnostics/link` counts existing sockets and
opens none to :502) over an hour, twice: with no browser open, and with one Dashboard tab
visible. Compare them with the ≈124 and ≈844 estimated above.
