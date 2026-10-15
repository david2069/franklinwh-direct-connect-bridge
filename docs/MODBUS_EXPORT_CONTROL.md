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
