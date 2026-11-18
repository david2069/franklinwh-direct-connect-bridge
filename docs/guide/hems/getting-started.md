# Getting started with HEMS

[HEMS overview](index.md)

## The Set up HEMS wizard

The quickest way is the wizard: open the setup list (**Settings → Setup**, or the setup
wizard), and under **Advanced** choose **Energy planning (HEMS)**. Both cards also have a
**Set up HEMS** link. It goes through the steps below in order:

| Step | What it does |
|---|---|
| 1. Opt in | Switches the HEMS setup on or leaves it off, with the notice. Off goes straight to Check. |
| 2. Site & solar | Shows whether the site's location and array are set, and today's forecast. It doesn't ask for them: **Open Location & Solar** opens that card (and closes the wizard). No panels? Press Next. |
| 3. Warranty | The battery warranty fields, with the cloud's pre-fill marked **Please confirm**. **Skip for now** leaves the wear figures blank. |
| 4. Usage | The always-on load and the usage periods from the last four weeks, to confirm. Without enough history it says so, and they fill in later on the card. |
| 5. Heavy loads | Each heavy load, or **None**. A control's details (deadline, off and on times, soak triggers, EV fields) are on the HEMS setup card. |
| 6. Check | What will be saved, and each load checked against what this bridge can control. **Save** writes the two cards' settings and says so in the dialog. |

It writes this bridge's settings only, never the aGate or the FranklinWH cloud. Run it again
any time: it starts from what is saved. The setup list shows it **Done** once HEMS setup is
on for a gateway.

The steps by hand:

## 1. Location and solar

The solar forecast needs the site's location, and your array's size, tilt and direction.
Set them in **Settings → Location & Prices → Location & Solar**; **Sync from gateway** reads
the location your installer set on the aGate. See
[History, costs and tariffs → Solar forecast](../energy-and-costs.md#solar-forecast). With no
solar panels, leave the array size empty; the load forecast and the wear figures still work.

## 2. Battery warranty

Open **Settings → Gateways → Battery warranty & wear** and fill in your warranty: end date,
warranted throughput, guaranteed SoH at the end, install date and replacement value. If the
FranklinWH cloud is signed in, the end date and throughput are filled in for you, marked
**Please confirm**. See [Battery warranty and wear](battery-wear.md).

## 3. Your home (optional)

Open **Settings → Gateways → HEMS setup**, switch it on, and check the pre-filled always-on
load and usage periods. Add each heavy load you want planned around. See
[Loads and controllability](loads.md).

## What is ready when

| What | Ready |
|---|---|
| Solar forecast | As soon as the location and array size are set |
| Solar calibration | After 5 days with real sun (it learns from the last 30) |
| Load forecast | From the first day; the full model after 4 weeks of history (until then the `method` attribute says `cold_start`) |
| Load forecast accuracy (Health) | After 4 weeks of history |
| Always-on load and usage periods | From the history; the last 28 days are used |
| Throughput used | From the first daily snapshot after midnight |
| Round-trip efficiency | After the first full cycle (3 kWh each way, back to the same SoC) |

## Change it later

Every field stays editable on its card; saving replaces the pre-fill. Changing the location,
tilt, direction or array size starts the solar calibration afresh.
