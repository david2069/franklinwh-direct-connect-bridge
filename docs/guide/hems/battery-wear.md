# Battery warranty and wear

[HEMS overview](index.md)

**Settings → Gateways → Battery warranty & wear**, per gateway (#713). The figures come from
hems, the shared energy engine; nothing here writes to the aGate.

| Field | Where it comes from |
|---|---|
| Warranty end, Warranted throughput (MWh) | Your warranty. When the FranklinWH cloud is signed in, the bridge reads them from it once a day and fills them in, marked **Please confirm**: check them against your warranty and save. Only these figures are kept from the cloud. |
| Guaranteed SoH at the end (%) | Your warranty document (no API has it). |
| Install date | The day the battery was installed; throughput is counted from it. |
| Replacement value ($) | What replacing the battery would cost. |
| Value at the end of warranty ($) | Optional. Left blank, it is replacement value × the guaranteed end SoH, and says so. |

| Figure | How it is worked out |
|---|---|
| Wear cost | (replacement value − value at the end) ÷ warranted throughput, per kWh discharged, with the sum shown. |
| Throughput used / left | Discharged since the install date, from the daily snapshot; left is warranted − used (or the cloud's own figure while the throughput is the cloud's). |
| Pace | Throughput left ÷ days to the warranty end: the kWh a day the battery can discharge and still last the warranty. |
| State of health | The aPowers' SoH, as read for the alarms. |
| Round-trip efficiency | The median, over 30 days, of full cycles: back to the same SoC (within 1 point) with at least 3 kWh each way, measured on the aGate's own charged and discharged counters. |

Each charge and discharge block is also recorded (energy in and out, SoC at the start and the
end, mean power, temperature, and whether it was a VPP event).

## Where it is kept

The fields are per gateway. The bridge samples the battery's power, SoC, counters and
temperature every 5 minutes for the efficiency figure and keeps 45 days of samples. The card
shows the last 10 charge and discharge blocks.

## What to do with it

Compare **Pace** with how much the battery discharges on a typical day (Analytics). Below the
pace, the warranty's throughput outlasts its years; above it, throughput runs out first. The
**wear cost** is what each kWh discharged costs in battery life: worth knowing when a
discharge saves less than that.

Nothing here writes to the aGate, and nothing is scheduled from it yet.
