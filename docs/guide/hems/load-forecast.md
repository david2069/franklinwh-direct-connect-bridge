# Load forecast

[HEMS overview](index.md)

**Load Forecast** (#713) is the home load the bridge expects this hour, in kW, with the next
48 hours in its `forecast` attribute as `[{time, value}]` every 30 minutes: the format HAEO
and similar optimisers read. It is learnt from this gateway's own home load (hour of the day,
weekday or weekend, season, and the outside temperature when the load follows it) by hems,
the shared energy engine, and published every half hour on its own topic. In its first four
weeks it is the median of the same weekday and hour so far (the `method` attribute says
`cold_start`). The attribute changes every half hour; to keep it out of Home Assistant's
history database, add the entity to the recorder's `exclude`. The weekly battery report on
the Health tab shows how far off it was over the last 90 days.

## The model

| Part | What it does |
|---|---|
| Profile | The load per hour of the day, by weekday or weekend and by season, from up to 365 days of this gateway's home load |
| Temperature | Heating and cooling terms around a comfort band learnt from your own history, using Open-Meteo's past temperatures for the site (fetched once a day). Without a site location there are no temperatures and the profile alone is used. |
| Cold start | Until there are 4 weeks of history, the median of the same weekday and hour over the last 11 weeks |
| Refit | Once a site day; while it is still on the cold start, once an hour |

The next 48 hours use the solar forecast's temperatures when the site has a solar forecast.

## In Home Assistant

| | |
|---|---|
| Entity | **Load Forecast** (`load_forecast`), on the gateway's device |
| State | This hour's expected load, kW |
| `forecast` attribute | The next 48 hours as `[{time, value}]` every 30 minutes, the format HAEO reads |
| `method` attribute | `cold_start` or the model |
| Published | Every 30 minutes, on its own topic |

**HAEO:** point HAEO's load forecast at the entity's `forecast` attribute.

## How accurate it is

The weekly battery report on **Health** runs a backtest over the last 90 days: each day is
predicted only from the days before it, and its daily error is shown next to "same as the day
before" for comparison. It needs four weeks of history.
