# Restarts and the clock

Direct Connect Bridge. Mirrors the Modbus Bridge page
[Restarts and the clock](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/restarts-and-clock/)
section for section.

What a bridge restart does to running force commands and open windows, and which clock every
schedule runs on.

## Bridge restart

| Step | What happens |
|---|---|
| Graceful shutdown | The scheduler worker is told to stop. If the bridge holds a force it started (in memory), it sends a **Release** to each aGate it holds a force on. Exit HA actions do not run and History gets no *exit* row. |
| Crash or power loss | Nothing is released. The force stays on the aGate. |
| Start-up: interrupted dispatches | A force a schedule (or the Battery Control widget) started is recorded until it is released. At start-up, if the Modbus client (this bridge) is on, rows still marked active are handled by **the interrupted-dispatch policy** (default **release**: release it if its window has ended, re-arm the auto-release if not). |
| Start-up: paused runs | A run that was paused when the bridge stopped is closed as *stopped*. |
| First ticks | The engine's in-memory state is empty. A schedule that **already fired** in the current occurrence does **not** fire again (that is stored). One that has not fired is evaluated afresh; its hold starts from zero. |
| Catch-up | **Not in this bridge.** Windows that opened and closed while the bridge was down are not run late, and leave no *missed* row. |

<!-- @b RST-01 ;; src: app.py:1253, battery_control.py:304-310 ;; tested: tests/test_multigw_force.py::test_shutdown_releases_every_held_gateway ;; write: yes ;; b: Graceful shutdown releases every force this bridge holds, each on the host it was sent to (#192) -->
<!-- @b RST-02 ;; src: app.py:1044-1063, battery_control.py:148-264, config.py:84-88 ;; tested: tests/test_dispatch_reconcile.py::test_notify_never_touches_battery ;; write: yes ;; b: At start-up active dispatch rows are reconciled by dispatch_interrupt_policy (none, notify, release default, resume); notify never touches the battery (default: tests/test_force_ownership.py::test_restart_policy_defaults_to_release_and_release_stale_is_gone) ;; test: -->
<!-- @b RST-03 ;; src: scheduler.py:538-541, db.py:920-931 ;; tested: tests/test_scheduler.py::test_fires_once_per_day ;; write: yes ;; b: last_fired_day is stored, so after a restart an entry that already fired this occurrence does not fire again; one that has not fires on the first tick that passes ;; test: -->
<!-- @b RST-05 ;; src: scheduler_worker.py:190-200, db.py:2080-2100 ;; tested: tests/test_occurrences.py::test_a_restart_while_paused_resolves_to_terminal ;; write: no ;; b: At worker start every paused run is resolved to stopped with a reason ;; test: -->

The interrupted-dispatch policy (**Settings**, `dispatch_interrupt_policy`) decides what
start-up does with a force a restart cut short:

| Policy | Window ended | Window still open |
|---|---|---|
| `none` | recorded, nothing else | recorded, nothing else |
| `notify` | alert your notification devices; the battery is not touched | the same |
| `release` (default) | if the battery is still forced: **Release** | if still forced: re-arm the bridge's timer to release at the window end |
| `resume` | as `release` | as `release`; and if no longer forced: **force again** for the rest of the window |

See also [After a bridge restart mid-dispatch](../control.md#after-a-bridge-restart-mid-dispatch).
<!-- @b RST-06 ;; src: battery_control.py:154-270 ;; tested: tests/test_dispatch_reconcile.py::test_resume_reforces_when_battery_dropped_inside_window ;; write: yes ;; b: resume re-forces for the remaining window when the battery is no longer forced; release only releases or re-arms ;; test: -->

Only a force this bridge recorded is acted on. A force on the aGate with no record here
(another Modbus client's) is never released at start-up; it is only alerted as an orphan.
A saved policy is kept: if you chose `notify` before `release` became the default (#199),
you keep `notify`.

!!! warning "With notify a force can outlive a restart"
    The aGate does not end a force by itself; the bridge's own timer does, and that timer is
    in memory. With **notify**, a force that was running when the bridge restarted keeps
    running until something releases it. The schedule's window end still sends a Release if
    the bridge is back up before the window closes (the first tick marks the window open, so
    its closing edge is seen). If the window closed while the bridge was down, no Release
    comes from the scheduler. Release from **Control**, or choose `release`.
<!-- @b RST-07 ;; src: battery_control.py:20-27, scheduler.py:1995-2039, battery_control.py:207-212 ;; untested ;; write: yes ;; b: After a restart the duration and target-SoC timer is gone; with policy notify only a later window-end edge (if the bridge is up for it) releases ;; test: unit: restart mid-window (clear module state, record_dispatch active); tick to window end; assert Release; tick a window that ended during downtime; assert none -->

On a site with several gateways, the start-up reconcile runs for every aGate that has a
force recorded as active, each with its own gateway's SoC, and a graceful shutdown releases
every gateway this bridge holds a force on (#192).
<!-- @b RST-08 ;; src: app.py:1054-1057, battery_control.py:304-338 ;; tested: tests/test_multigw_force.py::test_boot_reconcile_covers_every_gateway_with_its_own_soc ;; write: yes ;; b: Boot reconcile runs per host with an open dispatch row, with that gateway's SoC reader; shutdown releases every held host (see also test_shutdown_releases_every_held_gateway) -->

**Not in this bridge:** releasing any force found on the aGate at start-up, whoever set it.
Start-up acts only on forces this bridge recorded, through the policy above (#199).
<!-- @b RST-04 ;; src: battery_control.py:148-264, app.py:1044-1063 ;; tested: tests/test_force_ownership.py::test_restart_policy_defaults_to_release_and_release_stale_is_gone ;; write: yes ;; b: There is no release_stale; start-up releases only through reconcile_interrupted on recorded active rows; pollers, the reconcile thread and the scheduler worker start independently -->

So a restart during an open window usually means **no second write** for a schedule that had
already fired, and a fresh attempt for one that had not.

## The clock

![Settings → Setup → Where is this site? The site timezone schedules run on](../../images/scheduler/04-which-clock-site-timezone.png)

Schedules run on **each gateway's own clock**: the scheduler asks the aGate for its time
(`time_location`), works out the UTC offset (rounded to 15 minutes), and evaluates that
gateway's schedules in that wall-clock time. The offset is cached for 10 minutes per gateway.
If the gateway cannot be read, the bridge falls back to the container's clock for that tick.
<!-- @b CLK-01 ;; src: site_time.py:39-107, scheduler.py:1947-1948 ;; tested: tests/test_site_clock_scheduler.py::test_tick_derives_the_site_clock_and_fires_on_it ;; write: yes ;; b: The tick evaluates each gateway in that aGate's wall-clock offset (cached 10 min), falling back to the container clock when unreadable ;; test: -->

- An unreadable gateway is not treated as UTC: the container's clock is used.
  <!-- @b CLK-05 ;; src: site_time.py:72-107 ;; tested: tests/test_site_clock_scheduler.py::test_unreadable_gateway_is_not_reported_as_utc ;; write: yes ;; b: An unreadable gateway gives offset None and the container-local clock, never UTC ;; test: -->
- A gateway clock that is impossible (an offset outside UTC−12 to UTC+14) is ignored; the
  base offset it reports is used instead, or the container's clock.
  <!-- @b CLK-06 ;; src: site_time.py:27-69 ;; tested: tests/test_site_clock_scheduler.py::test_an_impossible_offset_is_refused_outright ;; write: yes ;; b: An implausible aGate clock is not used as an offset; the base offset or the container clock is used ;; test: -->
- **Where is this site?** in Setup sets the site timezone. It sets the clock of **mock**
  gateways, and clears the cached offsets; a real gateway's clock comes from the aGate.
  <!-- @b CLK-03 ;; src: site_time.py:110-113 ;; tested: tests/test_setup_timezone_api.py::test_setting_the_zone_drops_the_cached_offsets ;; write: no ;; b: Setting the site timezone drops the cached clock offsets ;; test: -->

!!! warning "The pages and previews use the container's clock"
    Only the tick uses the site clock. **Next:**, **● active**, the **Timeline** (its "now"
    line and today's windows) and **Test against live** use the bridge container's clock, and
    **History** shows times in the bridge host's zone. When the container's zone differs from
    the site's, these are off by the difference. Issue #161. See
    [docs/TIMEZONES.md](../../TIMEZONES.md).
<!-- @b CLK-02 ;; src: app.py:3033-3038, app.py:3334, app.py:3386, static/js/scheduler_tab.js:81 ;; unclear ;; write: no ;; b: next_fire, active_now, the timeline and /test use the container's naive clock; History uses the host zone ;; test: unit (API): container and site zones apart; assert the timeline and next_fire follow the site -->

**Not in this bridge:** `time.*` sensors (`time.hour`, `time.dow`, `time.utc_offset_h`,
`time.tz_ok`) and a recorded-timezone check at start-up.

!!! note "Several gateways, several clocks"
    Each gateway's schedules run on that gateway's clock. An unbound schedule runs on the
    default gateway's clock (#182). The Modbus Bridge uses one clock for all gateways.

### Daylight saving

The tick works in a fixed UTC offset per gateway, re-read at most every 10 minutes. Around a
daylight-saving change:

- for up to 10 minutes after the change the old offset can still be in use, so windows can
  open up to an hour early or late in that time;
- when clocks go forward, a window inside the missing hour may not open that day; when they go
  back, the repeated hour is seen twice, but the occurrence key is the date, so a Daily-type
  schedule that already fired does not fire again (Every N minutes and cron slots may).

This is from the code; it has not been observed on a gateway. Keep schedules out of the
change hour, or check **History** afterwards.
<!-- @b CLK-04 ;; src: site_time.py:22-25, site_time.py:97-107, scheduler.py:385-391, scheduler.py:332-366 ;; unclear ;; write: yes ;; b: The offset is fixed per read and cached up to 10 min, so a DST change applies late; date keys stop a daily re-fire in the repeated hour, slot keys may not ;; test: unit: simulate offset change across a cached read; assert window timing; VM: observe on a change day -->
