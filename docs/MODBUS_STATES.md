# The four Modbus states, and why the dashboard showed two of them side by side

Four different things are called "Modbus" in this project. Three are the **gateway's**,
one is **ours**, and a dashboard that shows two of them without saying whose is which
reads as a contradiction. It did: `MODBUS :502 — Not probed` sat next to
`SUNSPEC MODBUS — Enabled`, and both were correct.

## The two enable flags in `1205/1206 der_comms`

One read returns both, and they are not the same subject.

| field | subject | observed | meaning |
| :--- | :--- | :---: | :--- |
| `sunsMdEn` | **the aGate** | `1` | SunSpec **Modbus TCP** server on/off, served on `ip`:`port` (502). `1` = the gateway accepts Modbus connections. |
| `enable` | **the aGate** | `0` | **IEEE 2030.5 / SEP2** on/off — a different protocol entirely. The rest of the payload belongs to it: `uri`, `dcap2030_5`, `lfdi`, `sfdi`, `pin`, `status2030_5`. |

The bridge surfaces them as `summary.der_comms = {"sunsMdEn": …, "sep2": …}`, where `sep2`
**is** `enable` (`client.py`). The UI labels them "SunSpec Modbus" and "IEEE 2030.5/CSIP",
which is right — the trap is that `enable`, the more general-sounding name, is the *2030.5*
flag and not the Modbus one.

`sunsMdEn` enables the Modbus **interface** (reads). It is not the write plane: the
`franklinwh-modbus` write-lock is a separate gate, and `1251 SUNSPEC_MODBUS_*_EVAL` are
certification flags, different again.

### Verification

Measured 2026-10-15, aGate X-01-AU, firmware V12R02B30D06:

```
1206 der_comms → sunsMdEn: 1   enable: 0   port: 502   status2030_5: 0
                 dcap2030_5: "/sep2/dcap"   lfdi: ""   sfdi: ""
```

`sunsMdEn: 1` is corroborated independently: the Modbus Bridge held 2–3 established
connections to the gateway's `:502` that morning and polled it successfully, which is only
possible if that listener is on.

## The other two

| state | subject | where it comes from |
| :--- | :--- | :--- |
| **Bridge Modbus client enabled/disabled** | **ours** | `battery_control.is_enabled()` — the Control-tab switch. Governs whether *this bridge* opens Modbus connections at all. |
| **`:502` reachability** | **ours, about the aGate** | `_probe_modbus()` — a TCP probe. Tri-state: reachable / refused / **not probed**, the last when our client is switched off (#30, #32). |

## The rule

**State whose setting it is.** "Enabled" on its own is ambiguous across four subjects. A
card showing a gateway setting must say so; a card showing our own switch must say that.

**Do not infer one from another.** Our client being disabled says nothing about `sunsMdEn`.
`sunsMdEn: 1` says nothing about whether we are connected. The gateway serving Modbus says
nothing about whether writes are permitted.
