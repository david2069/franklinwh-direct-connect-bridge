# HEMS in the Scheduler

[HEMS overview](index.md) · [Scheduler conditions](../scheduler/conditions.md#solar-forecast)

The solar forecast and the weather are scheduler sensors, under **Weather & Solar** and
**Derived Battery** in a condition's picker. They are worked out for the gateway's site.

| Sensor | Meaning |
|---|---|
| `weather.temp_c` | The site's air temperature now (°C) |
| `weather.condition` | The weather now, in words |
| `solar_forecast.today_kwh` | Today's forecast solar (kWh) |
| `solar_forecast.today_peak_kw` | Today's forecast peak (kW) |
| `solar_forecast.remaining_kwh` | Solar still to come today, from this hour on (kWh) |
| `solar_forecast.tomorrow_kwh` | Tomorrow's forecast solar (kWh) |
| `solar_forecast.day_pct` | How much of today's forecast has been made so far (%) |
| `solar_forecast.vs_expected_pct` | Made so far against what the forecast expected by now (%; above 100 ahead, below 100 behind) |

A sensor with no value (no forecast yet, or no location) never satisfies a condition, so a
schedule waits rather than acting on a missing forecast.

## Examples

- **Charge from the grid tonight only when tomorrow is dull:** a 23:00 trigger with the
  condition `solar_forecast.tomorrow_kwh < 10`, then the **Force charge** action (it needs
  the Modbus client (this bridge) on).
- **Save the battery for the evening on a sunny day:** at 10:00, if
  `solar_forecast.remaining_kwh > 15`, the **Operating Mode** action to Self-Consumption.
- **Tell me when the panels are behind:** at 13:00, if
  `solar_forecast.vs_expected_pct < 60`, a Home Assistant notify action (shading, a fault,
  or a dirty array).

The load forecast and the wear figures are not scheduler sensors yet; the load forecast is in
Home Assistant (see [Load forecast](load-forecast.md)).
