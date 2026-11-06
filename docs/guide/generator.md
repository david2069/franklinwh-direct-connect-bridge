# Generator

The **Generator** tab shows and edits the aGate's generator settings over Direct Connect
(cmdType 1901). Like the FranklinWH app, the tab is **always there**: you can switch the
generator feature on here, whether or not a generator is connected.

!!! warning "No generator hardware has been tested"
    Every write on this tab has been checked against a reference aGate **without a
    generator**: the aGate stores the value and reads it back. What a connected generator
    then *does* with those settings has not been observed by this project.

## What the bridge can and cannot know

The aGate returns the full generator block whether or not a generator is wired up, so the
bridge **cannot tell** whether a generator is installed. It shows what the aGate reports:

| Shown as | From | Meaning |
|---|---|---|
| Feature on / off | `genEn` | The generator feature switch, the same one the FranklinWH app has. A user setting, not a hardware fact. |
| Model, rated power | `genModel`, `genRatedPower` | Reported by the aGate. Empty or 0 when it reports nothing. |
| Run state | `genStat` | Standby / OFF, Running / ON, Cooldown, Fault. |
| Generator power | `genpowerGen` | Generator output. The block's other `power` / `curr` / `volt` / `freq` fields are gateway-level values shared with the smart-circuit meter, so they are not shown as generator output. |

FranklinWH's field names don't reliably describe what a field does. Where a field's meaning
is not confirmed, the tab shows it under its raw key rather than guessing a label.

## Switching the feature on and off

**Enable generator** / **Disable** writes `genEn` and reads it back (`PUT /api/generator/enable`).
While the feature is off, the settings are shown read-only, and the dashboard's Power Flow
leaves out the Generator row (it would only ever read 0 W). Turn it on, and the row
appears, even while the generator is idle.

The generator only supplies power **off-grid**: you can configure it on grid, but it will not
run until the aGate islands.

## Settings

| Setting | Fields | Endpoint |
|---|---|---|
| Auto start / stop SoC | `genStartElec` (start below), `genCloseElec` (stop at or above) | `PUT /api/generator/soc` |
| Operating windows (3) | `charge1..3En`, `StartTime`, `EndTime` | `PUT /api/generator/window/{1-3}` |
| Exercise (maintenance) run | `oilmanoEn`, `manoFre` (every N days), `manoStartTime`, `manoTime` (minutes) | `PUT /api/generator/exercise` |

FranklinWH's Generator support page describes *"up to 3 non-overlapping operating periods
(00:00-23:59) with minimum 1-minute intervals"*, which matches the three windows. On a
gateway with no generator, window 1 may still show as enabled (11:00–23:59): a stored value
does not mean an active schedule.

Writes need **Allow writes** on (Settings → Admin).

## Mode: not available yet

The tab shows the generator's **mode** fields raw (`mode` and `manuSw`) and does not let you
change them (#237):

- Until 0.5.11 the Auto / Manual buttons wrote `manuSw`. Captures of the FranklinWH cloud app
  (franklinwh-cloud, DEF-GEN-MODE-WRITES-MANUSW) show `manuSw` acts as a **manual start/stop**
  command; one write stopped a running generator.
- The same captures show `mode` is the field the app uses to set the mode, but what its
  values mean is not confirmed.

Change the mode in the FranklinWH app. `POST /api/generator/mode` answers 409 and writes
nothing.

## Raw data

**Raw JSON** shows the complete 1901 block (`GET /api/generator/raw`), including fields the
tab leaves out.
