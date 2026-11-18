# Battery warranty and wear

[HEMS overview](index.md)

**Settings → Gateways → Battery warranty & wear**, per gateway (#713). The figures come from
hems, the shared energy engine; nothing here writes to the aGate.

| Field | Where it comes from |
|---|---|
| Warranty end, Warranted throughput (MWh) | Your warranty. When the FranklinWH cloud is signed in, the bridge reads them from it once a day and fills them in, marked **Please confirm**: check them against your warranty and save. Only these figures are kept from the cloud. |
| Guaranteed SoH at the end (%) | Your warranty document (no API has it). |
| Install date | The day the battery was installed; throughput is counted from it. Left blank, it is **estimated** from the FranklinWH cloud (below), marked **Please confirm**. |
| Replacement value ($) | What replacing the battery would cost. |
| Value at the end of warranty ($) | Optional. Left blank, it is replacement value × the guaranteed end SoH, and says so. |

| Figure | How it is worked out |
|---|---|
| Wear cost | (replacement value − value at the end) ÷ warranted throughput, per kWh discharged, with the sum shown. |
| Throughput used / left | Discharged since the install date, from the daily snapshot; left is warranted − used (or the cloud's own figure while the throughput is the cloud's). |
| Used, by source | Each source that has it, with its name: the FranklinWH warranty's own figures (warranted − remaining), the cloud's discharge total since its first day with data (**estimated**), and this bridge's daily snapshots. |
| Pace | Throughput left ÷ days to the warranty end: the kWh a day the battery can discharge and still last the warranty. This is the allowance, not what the battery uses. |
| Your use vs the allowance | Throughput used (the first source above) ÷ days since the install date, beside the pace: "using 8.3 kWh a day since 2024-03-12; allowance 9.9 kWh a day (0.84×)". It says **estimated** when the install date or the figure is. |
| SoH vs the warranty | The SoH now against the guaranteed SoH at the end, once you enter it. |
| Warranty end, each unit | Each aGate's and aPower's own end date from the FranklinWH cloud (and its modules', when the cloud gives one), named by the last four characters of its serial. |
| State of health | The aPowers' SoH, as read for the alarms. |
| Round-trip efficiency | The median, over 30 days, of full cycles: back to the same SoC (within 1 point) with at least 3 kWh each way, measured on the aGate's own charged and discharged counters. |

Each charge and discharge block is also recorded (energy in and out, SoC at the start and the
end, mean power, temperature, and whether it was a VPP event).

## What is estimated, and why

The FranklinWH cloud has no install date. On the owner's aGate, the cloud's energy reports
start at the manufacturing date with zeros, and real figures start on the commissioning day.
So when you haven't entered an install date, the bridge uses the **first day with data** in
the cloud's history, and says "estimated: first day with data in the FranklinWH cloud
(observed on one site)", with the cloud's activation date beside it for comparison. This has
been seen on one site only: check it against your installation paperwork and save. A date you
enter always wins.

The cloud's **discharge total since that day** is estimated for the same reason. The
warranty's own "warranted − remaining" comes straight from the cloud's warranty figures and is
not an estimate.

The bridge reads the cloud's history at most once a day while the cloud is signed in, through
the same cached reads as Analytics → Cloud: the lifetime report, then once the first year's
and first month's reports to find the day.

## Where it is kept

The fields are per gateway. The bridge samples the battery's power, SoC, counters and
temperature every 5 minutes for the efficiency figure and keeps 45 days of samples. The card
shows the last 10 charge and discharge blocks.

## What to do with it

**Your use vs the allowance** compares them for you: below 1×, the warranty's throughput
outlasts its years; above it, throughput runs out first. The
**wear cost** is what each kWh discharged costs in battery life: worth knowing when a
discharge saves less than that.

Nothing here writes to the aGate, and nothing is scheduled from it yet.
