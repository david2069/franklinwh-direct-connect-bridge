# Targets

Direct Connect Bridge. Mirrors the Modbus Bridge page
[Targets](https://david2069.github.io/franklinwh-modbus-bridge/user/scheduler/targets/)
section for section.

The target says which gateway a schedule acts on. Here a schedule is bound to one gateway,
left on the default gateway, or (API only) set to run on every gateway. See also
[Multi-gateway and sites](../multi-gateway.md).

![Binding a rule to a gateway](../../images/scheduler/19-multi-gateway-binding.png)

## Pick a target

1. In **Add schedule** or **Edit**, find the gateway list next to **Priority** and **If busy**
   in the **Battery action** box. It is shown only when the bridge has more than one gateway.
2. Pick a gateway, or leave **Default gateway**.

<!-- @b TGT-21 ;; src: templates/tabs/scheduler.html:542-549, static/js/scheduler_tab.js:244-249 ;; untested ;; write: no ;; b: The gateway select appears only with more than one gateway; Default gateway stores gateway_id "" ;; test: browser: with one gateway the select is hidden; with two it lists both plus Default gateway -->

| Target | API | Acts on |
|---|---|---|
| a gateway | `gateway_id`: the gateway id | that gateway only, on its own tick |
| **Default gateway** | `gateway_id`: `""` | the default gateway (below) |
| every gateway (API only) | `gateway_scope`: `"all"` | each gateway on its own tick |

A schedule bound to a gateway is evaluated only on that gateway's tick, so its action goes to
that aGate. <!-- @b TGT-01 ;; src: scheduler.py:1978-1988 ;; tested: tests/test_scheduler.py::test_bound_schedule_fires_only_on_its_gateway ;; write: yes ;; b: A bound schedule is skipped on every other gateway's tick ;; test: — -->
A gateway's schedules are evaluated only while that gateway is enabled and its last poll is
fresh (three poll intervals, at least 90 s). A bound gateway that is offline or stale is
skipped with a debug log line only; nothing is sent and History shows nothing.
<!-- @b TGT-08 ;; src: scheduler_worker.py:94-104, scheduler_worker.py:156-160 ;; tested: tests/test_scheduler_worker.py::test_stale_gateways_are_not_passed_to_tick_at_all ;; write: yes ;; b: A disabled, never-polled or stale gateway is not evaluated at all, silently ;; test: — -->
A schedule bound to a gateway id that does not exist (deleted, renamed) never runs, and
nothing says so. <!-- @b TGT-22 ;; src: scheduler.py:1984-1986 ;; untested ;; write: yes ;; b: A gateway_id matching no registered gateway is skipped on every tick with no log ;; test: unit: schedule bound to "ghost"; tick two real gateways; assert no fire and decide on a warning -->

**Not in this bridge: Site and Service targets.** There is no utility-service target and no
"Site (all gateways)" choice in the form (#162). The closest is gateway scope *all*.

**Gateway scope "all" (API only).** With `"gateway_scope": "all"` the schedule is
evaluated by every gateway on its own tick. The form has no control for it. Since 0.5.2
(#157) saving from the form keeps it; before 0.5.2 the form turned it off. Any value other
than exactly `all` means one gateway. <!-- @b TGT-02 ;; src: scheduler.py:2093-2107, scheduler.py:2323, app.py:640-644, scheduler_worker.py:156-163 ;; tested: tests/test_multigw_force.py::test_scope_all_fires_once_on_each_gateway_per_occurrence ;; write: yes ;; b: gateway_scope all makes every eligible gateway (mocks included) evaluate the schedule on its own tick, and each settles its own occurrence, so each fires once (#270) -->
<!-- @b TGT-23 ;; src: app.py:3111-3127 ;; tested: tests/test_schedule_update_merge.py::test_a_form_save_keeps_api_only_fields ;; write: yes ;; b: A form save (which never sends gateway_scope) keeps gateway_scope all ;; test: — -->

## How a fan-out works

For gateway scope *all*, each gateway is handled on its own:

| Per gateway | Detail |
|---|---|
| Conditions | that gateway's own snapshot (see [Conditions → Scope](conditions.md#scope-which-gateways-values)) |
| Run | one run (occurrence) per gateway, with its own status and retries. Each gateway fires once per occurrence; before #270 the first gateway to fire stopped the others |
| Priority | one resource claim per gateway (`<gateway>/battery`), so gateways do not compete |
| Window end | each gateway's tick sends its own release when the window closes |
| History | one row per gateway, but the row does **not** name the gateway |

<!-- @b TGT-04 ;; src: scheduler.py:2084-2094, scheduler.py:2317-2329, db.py:1935-1962 ;; tested: tests/test_occurrences.py::test_the_same_rule_on_two_gateways_is_two_runs ;; write: yes ;; b: Each gateway gets its own occurrence row and its own resource claim for an all-scope rule ;; test: — -->
<!-- @b TGT-05 ;; src: scheduler.py:1989, scheduler.py:2014-2033 ;; untested ;; write: yes ;; b: The window-end release runs per gateway:entry key, to that gateway's host ;; test: unit: all-scope force on two gateways; close the window; assert a Release to each host -->
<!-- @b TGT-06 ;; src: db.py:1004-1023, scheduler.py:2458 ;; untested ;; write: no ;; b: History rows carry schedule id and name but no gateway ;; test: unit: all-scope fire on two gateways gives two identical fired rows; decide to add the gateway -->

Each gateway's force is supervised on its own: a force on one gateway never ends or changes
another gateway's time limit and target SoC (#194). **Stop** and **Pause** release on the
gateway the force was sent to, a graceful shutdown releases every gateway this bridge holds
a force on, and the start-up check for an interrupted dispatch covers every gateway (#192).
<!-- @b TGT-20 ;; src: app.py:3261-3290, app.py:3291-3320, app.py:1253, app.py:1054-1057, battery_control.py:304-338 ;; tested: tests/test_multigw_force.py::test_stop_releases_the_gateway_the_force_was_sent_to ;; write: yes ;; b: Stop and Pause release on the dispatch row's host; shutdown releases every held host; boot reconcile covers every host with an open row (see also test_shutdown_releases_every_held_gateway, test_boot_reconcile_covers_every_gateway_with_its_own_soc) -->

A gateway that leaves (disabled, or its poll goes stale) while its force runs is no longer
evaluated, so its window-end release is not sent. The force keeps running until the
watchdog's time limit or target SoC ends it (each gateway's force keeps its own watchdog,
#194), or until you release it. <!-- @b TGT-07 ;; src: scheduler_worker.py:156-160, scheduler.py:2014-2033, battery_control.py:118-145 ;; unclear ;; write: yes ;; b: A gateway skipped as stale gets no exit edge; only the in-memory watchdog can still end its force ;; test: unit: force running, then gateway stale past window end; assert a release is still sent (fails today) -->

**Run now** runs once, on one gateway, even for scope *all* (see below).

## Entries with no target id

A schedule left on **Default gateway** (`gateway_id` empty) runs on the default gateway's
tick only, so it does not run once per gateway. The default gateway is the
**first-registered** gateway in the bridge's memory. Nothing is stored or shown; deleting or
re-ordering gateways moves it (#182). <!-- @b TGT-10 ;; src: scheduler.py:1858-1866, scheduler.py:1987-1988, state.py:84-94 ;; untested ;; write: yes ;; b: An unbound schedule runs only when the tick's gateway is state.gateways()[0] ;; test: unit: two registered gateways, unbound schedule; assert it fires only on the first -->
In the same tick an unbound schedule claims that gateway's id, so it competes on priority with
schedules bound to that gateway. <!-- @b TGT-11 ;; src: scheduler.py:2088-2089 ;; untested ;; write: yes ;; b: An unbound schedule claims <tick gateway>/battery, the same resource as one bound to that gateway ;; test: unit: unbound and bound force entries on gw1 in one tick; assert one deferred -->

!!! warning "A disabled first gateway stops every unbound schedule"
    The default is the first-registered gateway whether or not it is enabled. A disabled
    gateway is not evaluated, and every other gateway refuses unbound schedules, so they run
    nowhere and History shows nothing. Bind them to a gateway (#182). <!-- @b TGT-17 ;; src: scheduler.py:1858-1866, scheduler_worker.py:96-97 ;; unclear ;; write: yes ;; b: The default-gateway test ignores enabled, so a disabled first gateway leaves unbound schedules unevaluated ;; test: unit: first gateway disabled, second enabled; unbound schedule never fires (fails today) -->

## In the form

- The gateway list shows the gateway's label (else its serial or id).
- **Not in this bridge: a mock warning.** The form does not warn when the picked gateway is a
  mock. For a mock, the scheduler skips the ratings read through the Modbus client (this
  bridge). <!-- @b TGT-18 ;; src: scheduler_worker.py:107-116, scheduler.py:1967-1969 ;; tested: tests/test_scheduler_worker.py::test_mock_gateways_skip_the_modbus_read ;; write: no ;; b: A mock gateway's tick passes an empty Modbus host, so no 702 ratings read ;; test: — -->
  Whether a force to a mock reaches anything depends on the mock's address answering SunSpec
  (**unverified**).
- **Test** under a condition block evaluates against the gateway selected in the top bar (with
  one gateway, that gateway). **⋮ → Test against live** on a card
  always uses the default gateway's values, whatever gateway the schedule is bound to
  (see [Conditions → Test Verification](conditions.md#test-verification)). <!-- @b TGT-19 ;; src: static/js/scheduler_tab.js:606-613, static/js/scheduler_tab.js:921-931, app.py:3360-3369, app.py:3397-3402 ;; untested ;; write: no ;; b: Editor Test uses the top-bar gateway; Test against live reads get_state(), the default gateway ;; test: unit (API): /test on a schedule bound to gw2 uses gw2's state (fails today) -->
- **Import** points an entry whose gateway does not exist here at **Default gateway**, warns
  "gateway '…' not found — will use the default gateway", and creates it disabled. A Modbus
  Bridge entry with target `default` maps to **Default gateway**. <!-- @b TGT-14 ;; src: scheduler.py:852-854, scheduler.py:728-729, app.py:3294-3309 ;; tested: tests/test_scheduler.py::test_import_maps_modbus_automations_bundle ;; write: no ;; b: Import maps a default/unknown gateway to "" and creates the entry disabled ;; test: — -->

**Run now** on a schedule bound to a gateway runs on that gateway, whatever gateway the top
bar shows. For a schedule on **Default gateway** or with scope *all*, it runs on the gateway
selected in the top bar, else the default (#193).
<!-- @b TGT-09 ;; src: static/js/scheduler_tab.js:632-640, app.py:3553-3566 ;; tested: tests/test_multigw_force.py::test_run_now_uses_the_schedules_gateway_not_the_viewed_one ;; write: yes ;; b: Run now uses the schedule's bound gateway; the ?gateway= query is used only for an unbound or scope-all schedule -->

## On the timeline

The **Timeline** view draws every enabled schedule's planned windows, for all gateways, in
one list. It does not split by gateway, and the fire markers come from every gateway's
History. The tab asks for the timeline without a gateway, so the mode band and SoC line are the default gateway's. <!-- @b TGT-15 ;; src: app.py:3327-3358, scheduler.py:864-885, static/js/scheduler_tab.js:71-74 ;; untested ;; write: no ;; b: Timeline segments ignore the gateway; markers come from the whole log; the tab sends no gateway ;; test: unit (API): timeline?gateway=gw2 still lists a schedule bound to gw1 -->

Related pages: [Multi-gateway and sites](../multi-gateway.md),
[Priorities and conflicts](priorities.md), [Actions](actions.md).
