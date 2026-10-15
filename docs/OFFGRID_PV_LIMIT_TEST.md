# Test plan — does the gateway curtail PV during an island, and how?

**Status:** planned, not run. Written 2026-10-15 after the first observed island.
**Not before ~2026-11-15** — the owner is away from site for a month or more. See
`BACKLOG.md` → `TEST-OFFGRID-BREAKER`, which has the same constraint and should be run in the
same visit if the weather allows: the two tests need opposite conditions (this one needs a
clear sky at solar noon, that one needs nothing but the owner at the switchboard), so they
are separate runs, not one.

## The question

This site has **6.6 kWp of AC-coupled PV** behind a **5 kW** aGate. On grid that is
unremarkable — surplus exports. **Islanded, there is nowhere for surplus to go.** PV output
must equal house load plus battery charge, and the battery cannot absorb more than the
inverter's rating. So above roughly `load + 5 kW` the gateway must do something to PV, or
overload itself.

The owner's expectation is that the gateway shuts PV down. The hypothesis below is narrower
and testable: it **curtails** rather than disconnects, and does so by frequency shift.

### Why frequency shift is the hypothesis

AC-coupled PV has its own inverter, which the aGate does not command directly.

**Frequency shift is a guess, and it is written here only because it is cheap to falsify.**
We have not read a FranklinWH document describing how this gateway curtails AC-coupled PV,
and nothing in our captures shows it doing so. Raising island frequency to throttle PV is a
mechanism used in this class of equipment generally, which is not evidence about this device.
If the guess is wrong the test still answers the real question — what the gateway actually
does — because `gridFreq`, `p_sun` and the relay states are recorded either way.

What is measured and not a guess: the island ran at `gridFreq` 49.96–50.02 Hz throughout
2026-10-15. That is the baseline any frequency movement would be measured against.

Supporting observation, not proof: the Modbus channel logged `DERMeasureAC.DERMode = "PV
Clipped"` for ~51 s at **06:50:49** on 2026-10-15 — the moment of cutover into the island.
So a PV-clipping state exists and the gateway enters it. What is unknown is the threshold
and the mechanism.

## Predictions, stated before the run

| # | If the hypothesis holds | If it does not |
| :-- | :--- | :--- |
| 1 | `gridFreq` rises above 50.0 Hz as PV approaches the limit | frequency stays at 50.0 and something else gives |
| 2 | `p_sun` plateaus below its clear-sky potential; the plateau ≈ `p_load + battery charge limit` | `p_sun` tracks irradiance and the battery charge rate is what clips |
| 3 | `solarRelayStatus` stays **1** (closed) throughout | it goes to 0 — the owner's "PV shuts down" reading, which would make the curtailment hypothesis wrong |
| 4 | Modbus `DERMode` reports `PV Clipped` while curtailing | it reports something else, or nothing |
| 5 | Recovery is smooth when load rises or SoC falls | PV trips off and needs a reconnect delay (typically 60 s) to return |

Prediction 3 is the one that decides between "curtails" and "shuts down". It is written down
first so the result cannot be read either way afterwards.

## Cross-channel corroboration already in hand (2026-10-15)

Three independent channels captured the same island, and they agree on the two things this
test depends on:

- **PV runs while islanded.** Direct Connect `p_sun` 811 W with `solarRelayStatus` 1;
  Modbus 300–500 W with the battery charging; Cloud `p_sun` 1.649 kW at 07:34 with
  `p_fhp` −1.434 kW. So the starting point for this test — that PV produces during an
  island and must therefore be curtailed somehow — is established on three channels, not
  assumed.
- **`run_status` is not the signal, on EITHER channel.** Cloud `runtimeData.run_status`
  showed 1 ×53, 2 ×14, 0 ×4 and never 5/6/7 — matching local `1301`. The "5/6/7 = off-grid"
  mapping is therefore unconfirmed for a real island on both channels, not a local quirk.

Also settled, and it matters for reading the results: **`ibgRunStatus` is a programme id,
not a run status.** Local `1707 ibgRunStatus` read **7** throughout, and Cloud
`runtimeData.mode` read **7** in 71/71 polls — the same value on both channels, where the
normal value is the mode id 85232 "Self-Consumption" and a Modbus dispatch showed 9. So
during this test, `ibgRunStatus`/`mode` identifies the *programme*, and `dspRunstatus` is
the run state to watch.

### The premise does not rest on the solar sensor

The `franklinwh-modbus-bridge` session, at the owner's direction, withdrew its corroboration
on the grounds that these are values the aGate *reports*, not ground truth — if the PV relays
are open, the reported solar figures are measuring something else. That is a fair objection to
a power reading, and it is why this plan does not rest on one.

State of charge, with the grid relay open and `p_uti` 0 throughout:

| time | SoC | `p_sun` | `p_fhp` | `p_load` |
| :--- | ---: | ---: | ---: | ---: |
| 07:53 | 14.11% | 250 W | −36 W | — |
| 08:23 | 15.16% | 823 W | −628 W | ~220 W |
| 08:54 | 17.79% | 1385 W | −1187 W | ~230 W |
| 08:59 | 18.74% | 1372 W | −1141 W | 231 W |

**The battery gained ~4.6% of its capacity in an hour while the house drew 200–500 W, with
the grid relay open.** SoC is a different measurement from solar power, and energy has to
come from somewhere. Either PV was generating, or SoC *and* grid power are wrong as well.

This is recorded as a conflict, not as a verdict. The owner states PV relays shut down during
an off-grid event; `fwhai` has since found that its dialog's "Solar PV will be disconnected
immediately" is **static text keyed on `has_solar`**, with nothing reading a relay — so the
statement and the readings may not be independent sources. `pvRelay2` reading 0 while
`solarRelayStatus` reads 1 is the best candidate for a PV relay that genuinely does open.

**This test is how it gets settled** — by a run with a prediction written down first, rather
than by either side conceding.

## Conditions required

- **Forecast.** Open-Meteo GHI for the site predicting clear-sky PV **above `load + 5 kW`**
  across the window. With 6.6 kWp that needs a genuinely clear day near solar noon; a hazy
  day will not reach the threshold and the test proves nothing.
- **Battery headroom.** SoC low enough to absorb at the full charge rate for the whole hour
  — **below ~70%**. A full battery curtails PV for a completely different reason and would
  confound the result.
- **Load.** Normal. Do not add load to "help" — the point is to reach the limit.

`FEAT-WEATHER-SOLAR-OPENMETEO` is queued and unimplemented, so for a first run the window is
chosen by hand from Open-Meteo's public forecast. Automating the trigger is a *later* step
and must not gate the measurement.

## Procedure

1. **T−24 h** — check the Open-Meteo forecast; pick the hour bracketing peak GHI. Confirm
   SoC will be below ~70% at that time.
2. **T−30 min** — notify `fwh-modbus`, `fwh-modbus-bridge`, `fwh-cloud`, `fwhai`,
   `fwh-modbus-async` with the fixed start and end time, as for the 2026-10-15 island.
3. **T−10 min** — start recording on every channel. Direct Connect at 5 s:
   `p_sun`, `p_load`, `p_fhp`, `soc`, `gridFreq`, `gridLineVol`, `solarRelayStatus`,
   `pvRelay2`, `mainRelay1/2Status`, `offgridState`, `run_status`, `dspRunstatus`.
   **Start before the transition** — the 2026-10-15 capture began ~53 s after cutover and
   therefore has no on-grid baseline. That is the single most important lesson from it.
4. **T+0** — go off-grid: `POST /api/offgrid {"on": true, "soc": <floor>, "confirm": true}`.
5. **T+0 to T+60 min** — observe. Do not intervene unless an abort condition fires.
6. **T+60 min** — return to grid: `POST /api/offgrid {"on": false, "confirm": true}`.
   **One hour is a cap, not a target.** End earlier the moment the question is answered.
7. **T+70 min** — confirm on-grid on all channels, and post the write-ack times so the
   others can align their captures.

## Abort conditions — any one ends the test immediately

- SoC falls below the off-grid floor and keeps falling.
- `p_load` exceeds what PV plus battery can carry, i.e. the battery discharges hard with no
  solar — cloud cover during the window.
- Any relay state the plan did not predict, especially `mainRelay1/2Status` changing while
  `offgridState` stays 1.
- The bridge loses the gateway for more than two consecutive polls.
- Anything the owner does not like. The owner's call ends it, no justification needed.

## Safety notes

- This is a **write to hardware that changes dispatch** — critical under `CLAUDE.md`. It
  needs the owner's confirmation in the session that performs it, every time.
- The grid stays physically live. Islanding is not isolation and is not a reason to treat
  any circuit as dead.
- The aGate is not a UPS. Anything that must not reboot needs its own UPS, including the
  machine running this bridge.

## What the run should produce

A written result that states which predictions held, with the measurements, and **what it did
not establish**. One site, one firmware, one day — a single clear run makes a hypothesis
credible, not a mapping. In particular it will not establish the exact curtailment threshold
unless PV genuinely exceeds it, which is why the forecast condition is a requirement and not
a preference.
