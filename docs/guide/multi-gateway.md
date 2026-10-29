# Multi-gateway and sites

[Back to the guide index](index.md)

A single aGate needs none of this: with one gateway registered, the gateway selector does
not even appear and everything behaves as though it were the only thing the bridge knows
about. Read this when you have two, or when you want to model a property properly.

---

## Registering gateways

![Settings → Gateways with two mock gateways](../images/multi-gateway/01-registering-gateways.png)

Three ways, and they coexist:

1. **Configuration** — `FWH_HOSTS`, a comma-separated list where each entry is either
   `host` or `host=Label`, for example
   `FWH_HOSTS=192.0.2.10=Home,192.0.2.11=Shed`. When set, it wins over the
   single-gateway `FWH_HOST`.
2. **Settings → Gateways → Add** — host and a label, from the UI.
3. **Settings → Gateways → Scan** — probe a subnet for aGates. The subnet comes from
   `FWH_SUBNET`, or is derived as the host's `/24` when that is blank.

Each gateway can be enabled or disabled, edited, given a description, and removed, all
from its **Edit** dialog. All of those are writes. Two rules protect the default gateway
(below):

- **The default gateway can't be disabled.** Make another gateway the default first.
- **A gateway is removed only once it is disabled.** Remove Gateway is greyed out while it
  is enabled.

**Disabling a gateway releases a force** this bridge holds on it first, because once its
poller stops nothing else would. The dialog shows the release result. If the release fails,
the gateway stays enabled and the dialog says why. As of 0.5.2, `allow_writes` no longer blocks them (see
[Control](control.md#1-allow_writes-no-longer-blocks-writes)).

### Gateway identity

The bridge gives each gateway its own ID when the gateway is added. You never type it, and it never changes. The name is only a label.

The first time a gateway's aGate reports its serial number, that serial is locked to the gateway. A serial belongs to one gateway only (#381). If a gateway later reports a different serial, or a serial another gateway already has, the bridge stops that gateway. It logs the reason and sends a **FranklinWH gateway stopped** notice. The gateway's readings are not recorded or published, and the API refuses requests for it with 409. Settings → Gateways shows the reason. Restarting the gateway checks it again.

If an aGate is replaced, remove its gateway and add it again. A locked serial is never changed in place.

### The default gateway

![The gateway selector in the top bar](../images/multi-gateway/03-default-gateway.png)

**One gateway is marked as the default**, shown with a **default** badge in Settings →
Gateways. The first gateway you add becomes the default. The only way to change it is
**Make default** in another gateway's Edit dialog. Editing, restarting or republishing a
gateway never moves it. (Before 0.5.18 the default was whichever gateway had been
registered first, and editing the default gateway quietly made another one the default;
#182.) On update, the gateway that was the default at start-up is marked, so nothing
changes.

The default is a designation and nothing more (#383). It is always listed first, and the
page opens with it on screen. Any gateway can be removed; if the default is removed, the
next gateway becomes the default straight away.

Schedules left on **Default gateway** still run on the default.

**Every API call that acts on an aGate must name it** (#379): `?gateway=<id>` (or
`gateway` in the request body, `gateway_id` for `/api/dispatch`), where the value is the
gateway's ID or its locked aGate serial (#381). Nothing falls back to the default gateway,
even with only one gateway. Each refusal comes before any device I/O:

| Request | Answer |
|---|---|
| No gateway | **400** "gateway is required" |
| Not a valid ID or serial | **422** |
| No gateway with that ID or locked serial | **404** |
| The gateway is stopped for its identity (#381) | **409**, with the reason |

A few routes treat "no gateway" as *every* gateway rather than an error: the setup
status and Home Assistant checks, link diagnostics, the control log and the metrics
export. A schedule's **Run now** and **Test** use the schedule's own gateway when you
name none.

### What is scoped per gateway

![The Dashboard scoped to Mock aGate 2](../images/multi-gateway/04-scoped-per-gateway.png)

The selector at the top of the screen scopes **every tab**: dashboard, battery, solar,
circuits, generator, control, grid, health, network, MQTT. Also per gateway:

- its own poll loop, last state and health;
- `publish_ha` — whether *this* gateway is published to MQTT/HA. The UI defaults a mock
  gateway to **not** publishing (verified live: both mock gateways reported
  `publish_ha: false`, the real one `true`); you can turn it on;
- its MQTT node id, which is that gateway's serial, lower-cased — so two gateways are two
  HA devices, as they should be;
- `POST /api/gateways/{id}/restart` restarts just that gateway's workers.

When you switch gateway, each tab drops what it showed and reads the new gateway, so a
form or toggle read from one gateway is never saved to another.

The page always shows and controls **one gateway**, the one named in the top bar.
**All gateways…** in the gateway selector opens a read-only view of every gateway (#383):
counts (Registered, Polling active, Unavailable, Stopped), one row per gateway (name and
serial, model, health, grid, mode or command, SoC, poll status, last poll, and battery,
grid, solar and load power) and a site total. Click a row to show that gateway. It has no
controls. (It replaces Site view, *Site · All Gateways*.)

The **reserve SoC** is set through the FranklinWH cloud on the serial of the gateway on
screen. It's refused for a mock gateway, and for a gateway other than the one in the
cloud settings. The grid-limit cloud check reads the same way: that gateway's own serial,
or nothing.

The **aGate serial in the cloud settings** must be one of this bridge's gateways, locked
when it first connected (#381). An unknown serial is refused with 404 and a malformed one
with 422, before any sign-in. If the account has one aGate and no serial is typed, that
aGate must also be one of this bridge's gateways, or nothing is saved (#379).

---

## Mock gateways

![Settings → Gateways → Add a mock gateway](../images/multi-gateway/02-add-mock-gateway.png)

**Settings → Gateways → Add mock.** A mock runs the Direct Connect library's threaded
`Emulator` inside the bridge process on `127.0.0.1` at an ephemeral port, with a seed
and an aPower count you choose. The seed is stable — derived from the gateway id when you
do not set one — so the synthetic site and its serial are reproducible.

This is the right way to explore the UI with no hardware, and to try a schedule you would
not want to run against a real battery.

**What a mock actually serves — and a documented conflict.** The source comment in
`mockgw.py` says `energy_history` and `smart_circuits` "are not synthesised, so those
views stay empty for a mock". A read-only check against the running bridge on
**2026-10-15** disagrees:

- `GET /api/circuits?gateway=<mock>` returned three named smart circuits with state,
  mode, SoC-cutoff and detection evidence. **Not empty.**
- `GET /api/energy/flow?gateway=<mock>` returned a full directional flow set with
  `coverage: 0.999` over 729 samples. This one is not really a contradiction: the
  energy-flow Sankey is *reconstructed from the bridge's own power samples*, not read
  from the gateway's energy history, so it fills in for a mock simply because the bridge
  has been polling it.
- `GET /api/generator?gateway=<mock>` returned `installed: false`, so the **Generator tab
  stays hidden** for a mock.

Recording the conflict rather than picking a side: the comment is at least stale about
smart circuits. The earlier `docs/USER_GUIDE.md` repeated the comment's claim, which is
how a stale comment becomes stale documentation.

---

## Sites, meters, utilities and tariffs

![Settings → Sites & Billing](../images/multi-gateway/05-sites-meters-tariffs.png)

Above the gateway there is a small normalised model, managed from
**Settings → Sites & Billing**:

```
Site  →  Meter  →  (Utility  →  Tariff)
            ↑
         Gateway
```

- A **site** is a property.
- A **meter** is a billing point at that site. A gateway is attached to a meter
  (`meter_id`), and more than one gateway can share one.
- A **utility** is the retailer; a **tariff** is the plan, which belongs to a utility and
  is assigned to a meter.

This is what makes costs meaningful on a site with two gateways behind one meter: the
tariff is a property of the meter, not of the gateway, so the cost is computed once for
the billing point rather than twice. Tariffs can be exported, imported and validated
individually.

The model is enforced rather than advisory: deleting a meter that gateways are still
attached to is refused with **409** and a count — *"N gateway(s) connect to this meter —
reassign them first"* — instead of leaving them orphaned.

See [History, costs and tariffs](energy-and-costs.md) for what the tariff actually drives.

---

## Schedules across gateways

![A schedule's gateway binding](../images/multi-gateway/06-schedules-across-gateways.png)

The rule is worth stating precisely, because the wrong guess is expensive:

| Rule's gateway setting | When it runs |
|---|---|
| **Bound** to a gateway | Only on **that** gateway's tick. |
| **Unbound** (no gateway) | On the **default** gateway's tick only — so it does not fire once per gateway. |
| **Scope "all"** | Every gateway evaluates it on its own tick, producing one run **and one resource claim** per gateway. |

That last row is the subtle one. An "all"-scope rule claims the resource on *the gateway
whose tick it is running on*, not the gateway it is nominally bound to. Without that,
every gateway would contend for a single resource and all but one would be deferred
against a battery they were never driving. Each gateway also fires an "all"-scope rule once
per occurrence on its own (#270).

### Battery forces on several gateways

Each gateway's force is supervised on its own: its time limit, target SoC and SoC reading
never affect another gateway's (#194). **Stop**, **Pause**, the window-end release, a
graceful shutdown and the start-up reconcile all act on the gateway the force was sent to
(#192). **Run now** on a schedule bound to a gateway runs there, whatever the top bar shows
(#193).

**Battery Control** (Control tab) and the top bar's **Release** act on the gateway shown
in the top bar (#349); `/api/battery/command` takes `?gateway=` (the default gateway
when omitted).

The Modbus client's **host override** (Control → Modbus client) and `FWH_MODBUS_HOST`
apply only to the **default gateway**. Every other gateway connects to its own IP (#354).

Not yet per gateway (part of the multi-gateway audit, #220):

- The VPP monitor reads only the default gateway (#357).

If you import a schedule that names a gateway this bridge does not have, validation
raises a **warning** (not an error) and the rule falls back to the default gateway, so a
bundle from another install still loads and you can fix the binding afterwards.
