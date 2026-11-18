# HEMS troubleshooting

[HEMS overview](index.md)

**The solar forecast is empty.** The site has no location or array size: set them in
Settings → Location & Prices → Location & Solar (**Sync from gateway** reads the location).

**The solar forecast says stale.** Open-Meteo couldn't be reached; the last forecast is kept
until the next fetch works. The log shows `solar forecast fetch failed`.

**The solar forecast is too high or too low.** It calibrates itself after 5 days with real
sun. Check the array size, tilt and direction first: changing any of them starts the
calibration afresh.

**The Load Forecast `method` says `cold_start`.** There are fewer than 4 weeks of history;
it moves to the model by itself.

**Health says the load forecast "needs 4 weeks of history".** The backtest predicts each day
from the days before it, so it needs four weeks first.

**Load Forecast is missing in Home Assistant.** It is published once there is something to
predict, every 30 minutes; check that Home Assistant publishing is on for the gateway (mock
gateways are never published).

**The wear figures are blank.** Wear cost needs the replacement value and the warranted
throughput; throughput used needs the install date and the first daily snapshot (taken after
midnight); pace needs the warranty end.

**The warranty end and throughput weren't filled in.** The cloud pre-fill needs the
FranklinWH cloud signed in; it is read at most once a day. Type them from your warranty.

**Round-trip efficiency says "no full cycle yet".** It needs a full cycle: at least 3 kWh
each way, back to the same SoC within 1 point.

**A load shows a problem.** Its control needs something this bridge can't do here, such as a
smart-circuit switch on a gateway with no smart circuits, or battery power without the Modbus
client (this bridge) on. See [Loads and controllability](loads.md#what-this-bridge-can-control).

**The always-on load or usage periods are empty.** They come from the last 28 days of home
load; a new install fills them in as history builds up.
