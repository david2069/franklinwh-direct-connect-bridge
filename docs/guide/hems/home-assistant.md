# HEMS in Home Assistant

[HEMS overview](index.md) · [Home Assistant](../home-assistant.md)

| Entity | Key | Unit | What it is |
|---|---|---|---|
| **Load Forecast** | `load_forecast` | kW | This hour's expected home load; `forecast` attribute: the next 48 hours for HAEO; `method`: `cold_start` or the model. See [Load forecast](load-forecast.md). |

It is on the gateway's device, worked out on the bridge (source `local`), and published every
30 minutes on its own topic. Its attribute changes every half hour: add the entity to the
recorder's `exclude` to keep it out of Home Assistant's history database.

The solar forecast, the wear figures and the HEMS setup are not published to Home Assistant;
they are on the bridge's Solar tab, Settings cards and scheduler sensors.
