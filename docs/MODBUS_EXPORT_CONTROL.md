# The aGate as a Modbus TCP server for third-party export control

FranklinWH documents a third-party device writing to the aGate over Modbus TCP to control
export. This is the first vendor-documented Modbus **control** path we have found, and it is
AU/NZ-specific.

**Source:** *FranklinWH Commissioning Guide – AU & NZ*, page 25, "Step 3. Add Voltello LinkPro
and bind it to the system." Read 2026-10-15.

## What the guide states

Quoted and paraphrased from that page only. Nothing below is inferred.

- **Voltello LinkPro is a compliance gateway from Village Energy** that "receives DNSP
  dispatch instructions and controls this system's energy export".
- It is **bound to the FranklinWH system by serial number** — scanned or typed into the
  FranklinWH app, then Confirm.
- It is configured from the **Voltello app**, separately; the FranklinWH app's role is the
  binding and a **Verify Connection** check.
- The FranklinWH app displays an **"aGate Modbus TCP Server"** panel giving the details to
  enter into the Voltello app: **IP address, Port 502, Slave ID 1, Interface: Ethernet**,
  plus a live **Connection Status** (Not connected / Connected).
- **If the LinkPro goes offline, the system automatically caps export power at a fallback
  limit of 1.5 kW.**

## What this establishes for us

1. **The aGate's Modbus TCP server is a vendor-sanctioned control surface**, not only a
   read surface. A third-party box is documented as connecting to it, at `:502`, unit 1,
   and controlling export.
2. **`sunsMdEn` matters more than its name suggests.** `docs/MODBUS_STATES.md` records it as
   the gateway's SunSpec Modbus TCP server toggle. Turning it off would, on this reading,
   also sever a compliance device — which is a far larger consequence than losing our reads.
   The existing confirm-gate on disabling it is justified; this is why.
3. **There is an export cap mechanism with a documented default.** 1.5 kW on LinkPro loss.
   That is a concrete behaviour, stated by the vendor, that nothing of ours currently
   reads or exposes.

## What this does NOT establish

Recorded because the temptation to read more into it is strong, and the page does not
support it.

| question | status |
| :--- | :--- |
| Which registers LinkPro writes | **not stated anywhere on that page** |
| Whether export control is done via the extension registers we already know | unknown |
| Whether operating MODES can be switched this way | unknown — the page says "controls energy export", nothing about modes |
| Whether the binding is a Cloud API call | unknown — the guide shows an app flow, not an API |
| Whether the 1.5 kW fallback is readable or writable | unknown |
| Whether the aGate accepts writes from any Modbus client or only a bound SN | **unknown, and the most important of these** |

The last row matters most: the binding is by serial number, and the guide does not say
whether that binding gates writes at the aGate or is only bookkeeping in the app. Our own
`franklinwh-modbus` write-lock work is adjacent to this and may be the same mechanism seen
from the other side.

## Owner's hypotheses, recorded as hypotheses

Stated by the owner on 2026-10-15, from reading the LinkPro device's own user guide (which
we have not read):

- That this path likely allows **writing extension registers to switch operating modes**.
- That the LinkPro device guide claims connectivity to **Amber Electric** and **Localvolts**,
  both dynamic-tariff retailers.
- That the use case is **curtailing solar export when the feed-in price is negative**, where
  exporting costs money rather than earning it.

None of these is supported by page 25, which is the only source read. They are listed so the
next person knows what to look for, not as findings.

## The SPAN / Lumin write-unlock, and a conflict worth resolving

The owner's hypothesis, labelled as the owner's (2026-10-15): SPAN and Lumin enrolment may do
something similar to the LinkPro binding — enabling a control path — but not through the
installer app; perhaps FranklinWH Support does it in the FleetView portal.

That is speculation and the owner said so. What is **not** speculation is that
`franklinwh-modbus`'s documentation already asserts such an unlock exists, repeatedly, and
**disagrees with itself about who performs it**:

- `docs/FRANKLINWH_SUNSPEC_QUIRKS.md:153` — "Write access to 15507–15509 requires **SPAN
  Modbus** unlock **in FranklinWH installer app**."
- `docs/FRANKLINWH_SUNSPEC_QUIRKS.md:235` — "Extension write access requires **SPAN Modbus**
  unlock — **enabled by FranklinWH Support** for SPAN panel owners."

Installer app, or vendor support? The same document says both. Also in that repo:
`DER_CONTROL_REFERENCE.md:192` ("Need SPAN Modbus unlock") and `:295`, `backlog.md:30`
("write access still require SPAN/Lumin provisioning"), and
`CLI_COMMAND_REFERENCE.md:58`, which tells users these writes will not function unless
FranklinWH Support unlocks them.

And pulling the other way: on **2026-10-14 the owner confirmed there is no evidence a
`span_unlock` state exists**, which is why the `franklinwh-gateway-emulator` session withdrew
it from the emulator's scope.

Those two may be reconcilable — "no readable state flag exists" and "support can provision
write access" are different claims — but nothing currently says so, and a reader meeting both
cannot tell which they are looking at. **It is a documentation conflict in a repo that is not
ours**, so it is recorded here and raised, not edited.

### Why the LinkPro page is relevant to it

LinkPro is a documented case of the same shape: a third-party device, **bound by serial
number**, granted a control path to the aGate over Modbus. If extension writes are gated by a
binding rather than by a global flag, that would fit both the LinkPro flow and the absence of
a `span_unlock` state. **That sentence is a hypothesis and nothing in the guide supports it** —
page 25 does not say whether the binding gates writes at the aGate at all.

## What would settle it

In rough order of cost:

0. **Ask `fwh-modbus` to resolve its own conflict** — installer app or vendor support — and
   to reconcile it with the 2026-10-14 `span_unlock` withdrawal. Costs nothing and no
   hardware; it is their documentation and their call.
1. **Read the Voltello LinkPro installer guide and the Village Energy documentation.** The
   FranklinWH guide links to the Village Energy website for configuration. If LinkPro's own
   documentation names the registers it writes, that answers most of the table above without
   touching hardware.
2. **Check whether the FranklinWH app's "aGate Modbus TCP Server" panel is backed by a Cloud
   API field.** `franklinwh-cloud` has the corpus to answer whether Connection Status and the
   LinkPro binding appear in any captured response.
3. **Observe `sunsMdEn` and the export limit** on a site with a LinkPro bound. We have no
   such site.

## Related

- `docs/MODBUS_STATES.md` — the four Modbus states, and what `sunsMdEn` actually gates
- `BACKLOG.md` → `FEAT-EXPORT-CURTAIL-NEGATIVE-PRICE` — the owner's use case
- PR #26 — the design to retire direct Modbus TCP and delegate to the Modbus Bridge REST API.
  **This finding is relevant to that decision** and should be read before it merges: the
  Modbus server is not only a convenience for us, it is a vendor-sanctioned control plane.
