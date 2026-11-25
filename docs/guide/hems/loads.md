# Loads and controllability

[HEMS overview](index.md)

## HEMS setup

**Settings → Gateways → HEMS setup** (#713) describes your home for energy planning. It is
optional and off until you switch it on. *Planning is only as accurate as your answers.*

- **Always-on load** (kW): filled in from the quietest overnight hours of your own history
  (00:00–06:00), marked **Please confirm**. Change it if it is wrong; saving confirms it.
  Smart Dispatch uses it for hours with no history at all, so a typical figure is fine. The
  wizard's Usage step shows how many days of local history there are.
- **Usage periods:** your high, medium and low hours on a weekday and on a weekend day, from
  the last four weeks of history. Tick **These look right** when they do.
- **Heavy loads:** each large appliance you want planned around: what it is (**Device
  type**, picked from a list: EV charger, hot water, heat pump, air conditioning, pool
  pump, spa, well pump, clothes dryer, washing machine, dishwasher, oven, or Other; a type
  typed in before 0.5.57 shows as *Other (…)* and is flagged until you pick one), how it is
  measured (a Home Assistant power entity, an energy entity, or its nameplate kW), its power
  and/or how long it runs, when it runs (times, or that it follows the weather), its circuit,
  and how it may be controlled:
  - *deferrable*: the energy it needs and the time it needs it by;
  - *sheddable*: how long it may be off, how long it must stay on, and its priority;
  - *soak*: soaks up energy when the export price is at or below a level, export is limited,
    or the battery is full and exporting, up to a kWh quota.

  An EV charger also asks for its kW, phases, how it is controlled, arrival and departure
  times, and the energy needed.

Each load is checked against what this bridge can control (shown on the card): the operating
mode always; battery power and target SoC while the Modbus client is on; smart circuits when
the gateway has them. A problem is listed under the load, such as a smart-circuit switch on a
gateway with none. The checks and pre-fills come from hems, the shared energy engine. The
answers are only recorded: nothing is switched or scheduled from them yet.

## What this bridge can control

| Capability | When |
|---|---|
| Operating mode | Always (local API) |
| Battery power and target SoC | While the Modbus client (this bridge) is on (Battery Command) |
| Smart circuits | When the gateway has smart circuits, or their count isn't known yet |

A load whose control needs something the bridge can't do here is shown with a problem under
it; nothing is taken away on a guess.
