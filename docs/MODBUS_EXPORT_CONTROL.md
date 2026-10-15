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
