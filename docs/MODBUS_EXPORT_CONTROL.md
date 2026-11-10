# Voltello LinkPro — CSIP-AUS export control via the aGate's Modbus server

**Source:** *FranklinWH Commissioning Guide – AU & NZ*, page 25, "Step 3. Add Voltello LinkPro
and bind it to the system." Read 2026-10-15. AU/NZ only.

## What the page states

- **Voltello LinkPro is a compliance gateway from Village Energy** that "receives DNSP
  dispatch instructions and controls this system's energy export". The owner identifies this
  as **CSIP-AUS control of the grid-connected inverter**, which is what the function is.
- It is **bound to the system by serial number** — scanned or typed into the FranklinWH app.
- It is configured in the **Voltello app**, using details the FranklinWH app displays under
  **"aGate Modbus TCP Server"**: IP address, **Port 502**, **Slave ID 1**, Interface
  **Ethernet**, with a live Connection Status.
- **If the LinkPro goes offline, the system caps export power at a fallback limit of 1.5 kW.**

That is the whole of it. The page is a commissioning procedure, not a protocol description.

## What it does not state

- Which registers LinkPro reads or writes.
- Whether anything other than export can be controlled this way. It says **energy export**.
  It does not mention operating modes.
- Whether the serial-number binding gates anything at the aGate, or is bookkeeping in the app.
- Whether the 1.5 kW fallback is readable or configurable.

## What Voltello says about it

The FranklinWH knowledge base was searched and does not explain how Voltello interacts with
Amber Electric or LocalVolts in respect of the aGate. **The device maker's own announcement
does**, at the commercial level.

**Source:** company post by *Voltello by Village Energy* on LinkedIn, ~September 2026,
announcing the FranklinWH Australia integration. Read 2026-10-15. **This is marketing
material, not technical documentation** — it states what the product offers, not what it
writes.

Quoted from that post:

- "**FranklinWH Australia batteries can now be added to the Voltello platform via our LinkPro
  gateway** giving eligible households in **WA access to Synergy's VPP**."
- "Customers in south-eastern states are eligible for **VPP1 and BESS2 rebate programs with
  access to live Amber Electric and LocalVolts pricing**."
- "with **full CSIP-AUS compliance built in**, once connected, customers are **VPP Ready**."
- "one gateway, one app, and the same automations work across the battery your customer
  already chose."
- Voltello "now integrates with over a dozen inverters, batteries and retailers".

### What that settles, and what it does not

**Settled at the commercial level:** the Amber / LocalVolts connection is real and is a stated
product feature, as is VPP participation. The earlier reading that the device supports solar
PV only is not what the maker says — the post is explicit that **batteries** are added to the
platform via LinkPro.

**Not settled, and the post does not touch it:** how any of this reaches the aGate. Nothing
states which registers LinkPro reads or writes, whether battery control goes over the Modbus
link documented on page 25, or whether "the same automations" means commanding the battery or
only responding to it. A marketing claim that automations work is not a description of the
mechanism.

### VPP participation requires battery dispatch

The owner's reading, 2026-10-15, and it follows from what the post claims rather than from
anything about the device: **a VPP dispatches the battery.** Synergy's VPP, VPP1 and BESS2 are
programmes that charge and discharge stored energy on command. A device that makes a battery
"VPP Ready" must therefore reach a charge/discharge control somewhere. Export curtailment
alone cannot deliver that.

**And on this hardware, battery dispatch over Modbus is already proven — by us.** The
`franklinwh-modbus` **M704 `WSet`** path forces charge and discharge, and
`battery_control.py` in this repo uses it for our own force dispatch. It is a standard
SunSpec register, not a vendor extension, and it needs nothing unlocked. So "a third-party
Modbus client dispatches a FranklinWH battery" describes something we already do.

The post says nothing about the route. Dispatch could equally have reached the battery
through FranklinWH's cloud, with the local Modbus link used only for reading SoC and state
and for CSIP-AUS export limiting — which fits page 25's "controls this system's energy
export" exactly as written.

### The route, per a FranklinWH AU employee

**Synergy's VPP uses Modbus TCP.** Stated by a FranklinWH Australia employee and relayed by
the owner, 2026-10-15. A verbal statement from the vendor, not documentation — but it is the
only thing we have that chooses between the two routes, and it chooses the local one.

Taken with the commissioning guide, it is coherent: LinkPro is the Modbus client, bound to
the aGate's Modbus TCP server, and Synergy VPP dispatch runs over that link.

**It also converges with our own record.** `franklinwh-modbus` M704 `WSet` is observed to be
set by a cloud VPP dispatch, by the Modbus bridge, by the app's manual force, and by our own
`force_charge` — four origins, one register. If VPP dispatch arrives over Modbus TCP, it is
most likely arriving at the same place our own force dispatch does. **Likely, not shown**: no
capture of a Synergy VPP dispatch exists, and this site is not enrolled in one.

What would settle it: a Modbus capture on a site running a Synergy VPP through LinkPro.
Neither we nor any peer session has access to one.

## Relevance to this project

Narrow, and worth keeping narrow:

- `docs/MODBUS_STATES.md` records `sunsMdEn` as the aGate's SunSpec Modbus TCP server toggle.
  This page shows a device being commissioned against that server. On an AU site with a
  LinkPro bound, turning `sunsMdEn` off would therefore affect more than our own reads. We
  have no such site and have not tested it.
- Nothing here changes what we read or write today.

## If it is worth pursuing

Documentation first, no hardware: the FranklinWH guide points to the Village Energy website
for LinkPro configuration. If that documentation names registers, it answers the questions
above directly.

## Related

- `docs/MODBUS_STATES.md` — the four Modbus states and what `sunsMdEn` gates
- `BACKLOG.md` → `FEAT-EXPORT-CURTAIL-NEGATIVE-PRICE` — the owner's own export use case,
  which is a separate matter from this device
