# Solar forecast

[HEMS overview](index.md)

The solar forecast is today's and tomorrow's solar production for the site, hour by hour.
It shows on the **Solar** tab and as scheduler sensors. It needs the site's location and the
array's size, tilt and direction (Settings → Location & Prices → **Location & Solar**; see
[History, costs and tariffs → Solar forecast](../energy-and-costs.md#solar-forecast) for
setting them up, and for one location per site).

## How it is worked out

The bridge asks Open-Meteo for the hourly sunlight on your panels'
tilt and direction and the air temperature. It turns that into kW for your array size, less
about 15 % for the inverter and wiring, and less what hot panels lose (they make less in the
heat). It then **learns from your own system**: each day it compares the forecast with the
solar your gateways measured, and once it has five days with real sun it scales the forecast
by measured ÷ forecast over the last 30 days. A shaded or oversized array is corrected this
way. Changing the location, tilt, direction or solar size starts the learning afresh. The
maths come from hems, the shared energy engine the bridges use.

| Step | Value |
|---|---|
| Inverter, wiring and soiling loss | 15 % (the forecast is × 0.85) |
| Hot-panel loss | −0.35 % per °C of cell temperature above 25 °C, from the air temperature and the sunlight |
| Calibration | measured ÷ forecast over the last 30 days, once there are 5 days with at least 1 kWh forecast; kept between 0.5 and 1.5 |

A site with several gateways adds their solar up for the calibration. A day with less than
1 kWh forecast (heavy cloud) doesn't count.

## How to read it

- **Today / tomorrow (kWh)** and **today's peak (kW)**: the day totals.
- **Remaining today (kWh)**: what is still to come from this hour on.
- **The tracker:** `solar_forecast.day_pct` is how much of today's forecast has been made so
  far; `vs_expected_pct` compares what has been made with what the forecast expected by now
  (above 100 ahead, below 100 behind).

## When Open-Meteo can't be reached

The forecast is fetched at most every 15 minutes and kept. If a fetch fails, the last
forecast is used, marked stale, and the bridge logs `solar forecast fetch failed`. A sensor
with no value (no forecast at all) is "no value", so a schedule condition on it doesn't fire.
