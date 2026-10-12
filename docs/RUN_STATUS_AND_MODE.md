# Run status and operating mode — the field guide

**Written 2026-10-12.** Every mapping below is taken from source or from a live read on
the reference aGate (192.168.0.110), not from recollection. Where something is not yet
observed, it says so.

This exists because the same question was answered wrongly three times in one session:
*does the local API see VPP mode?* The answer is **yes** — but not in the field everyone
reaches for first.

---

## 1. There are TWO fields, and they answer different questions

The single most common mistake is treating "run status" as one thing. It is two.

| Question | Cloud field | Local field | Values |
| --- | --- | --- | --- |
| **What is the battery physically doing?** | `runtimeData.run_status` | **1301** `run_status` | `RUN_STATUS` table (§2) |
| **Which programme is in control?** | `runtimeData.mode` (`tou_mode`) | **1707** `ibg_run_status.ibgRunStatus` | programme id; **9 = VPP** |
| **What is the programme called?** | `runtimeData.name` | `name` (both frames) | e.g. `Self-Consumption`; **empty during VPP** |

The FranklinWH Cloud cookbook states this explicitly: the `RUN_STATUS` value table is
*"keyed by `runtimeData.run_status`, **not** `runtimeData.mode`"*, while the VPP rule in
`effective_mode` is *"`RUN_STATUS[9]` = "VPP mode" **if `tou_mode == 9`** and name is
empty"*.

So **`run_status == 9` is not how you detect VPP**, on either channel. `run_status` stays
at the battery direction. VPP shows up in the *programme* field.

---

## 2. `RUN_STATUS` — what the battery is doing

Identical in both libraries: `franklinwh_cloud.const.modes.RUN_STATUS` and the local
`catalog.run_status_desc()`.

| Value | Label | Note |
| ---: | --- | --- |
| 0 | Standby | inactive / idle |
| 1 | Charging | |
| 2 | Discharging | |
| 3 | *Unknown 3* | reserved, never observed |
| 4 | *Unknown 4* | reserved, never observed |
| 5 | Off-Grid Standby | island mode, battery idle |
| 6 | Off-Grid Charging | island mode, solar charging |
| 7 | Off-Grid Discharging | island mode, battery powering home |
| 8 | Debug Mode | FranklinWH remote support session |
| 9 | VPP mode | **defined in the table, but see §4 — the local 1301 does not emit it** |

Cloud-side distribution over 60 days / 12,962 samples (`docs/cli-energy.md` in
franklinwh-cloud): `0` no flow 100%, `1` charging 95%, `2` discharging 98%. No sighting
of 3, 4 or 9 in that sample.

---

## 3. Operating mode (work mode) — and the three numbering schemes

Three systems number the same three modes differently. This is a standing source of
error; always say which scheme a number belongs to.

| Mode | Cloud `workMode` | Modbus `oldIndex` | Local 1726 |
| --- | ---: | ---: | --- |
| Time-of-Use | 1 | 3 | by `scheduling_type` |
| Self-Consumption | 2 | 2 | by `scheduling_type` |
| Emergency Backup | 3 | 1 | by `scheduling_type` |

Cloud ↔ Modbus is **not** identity: `CLOUD_TO_MODBUS_MODE` maps 1→3, 2→2, 3→1. The local
library carries both in `OPERATING_MODES`
(`{'Emergency Backup': {'modbus': 1, 'cloud': 3}, 'Self-Consumption': {'modbus': 2,
'cloud': 2}, 'Time-of-Use': {'modbus': 3, 'cloud': 1}}`).

**Naming:** the local broker labels TOU with a site-specific tariff name (e.g.
`"Ausgrid EA11 TOU"`). `catalog.mode_label()` maps `scheduling_type` to the generic
`"Time-of-Use"` for display parity with the app. Note the cloud spells it
`"Time-Of-Use"` (capital O) and the local library `"Time-of-Use"` — do not compare these
strings across channels.

---

## 4. VPP mode — measured, 2026-10-12

A Modbus force **is** VPP mode. Per the vendor reference
(`david2069.github.io/franklinwh-modbus/VPP_MODE_REFERENCE/`): *"When **any** remote
client takes direct control of the aGate — whether via Modbus TCP or the FranklinWH
Cloud API — the mobile app displays the operating mode as VPP Mode."*

Live readings, with a Modbus force discharge active and the mobile app showing **VPP
Mode**:

| Field | Not forced | **During VPP** |
| --- | --- | --- |
| 1301 `run_status` | 2 | **2** — unchanged |
| 1301 / 1707 `name` | `Self-Consumption` | **`""`** (empty) |
| 1707 `ibgRunStatus` | 85232 | **9** |
| Modbus M704 `wset_enabled` | false | true |

So, on the **local** channel:

```
VPP active  ⟺  ibg_run_status.ibgRunStatus == 9      (and name is empty)
```

which is the cloud's own rule (`tou_mode == 9`, name empty) applied to the local
equivalent field. **No Modbus is required to detect VPP mode.**

### Why 1301 looked like a dead end

`run_status` reports the battery's direction and keeps doing so under VPP — the battery
is still discharging, so 2 is correct, not a bug. The code in
`cloud_compat.py` that maps a local `run_status == 9` to "VPP mode" is therefore
**unreachable in practice**: the field it reads never carries 9. It is harmless but
misleading, and should be re-pointed at `ibgRunStatus`.

### Not yet established

* **What `ibgRunStatus` is when not in VPP.** One observation: `85232`. The catalogue
  annotates the field *"(programme id)"*, so it is probably a programme identifier
  rather than a small enum — but a single sample is not a mapping. Do **not** write
  `ibgRunStatus != 9 → no programme`; test for `== 9` only.
* **Whether a cloud-originated VPP (a utility/aggregator dispatch) also sets
  `ibgRunStatus` to 9.** Only a Modbus-originated force has been observed. The vendor
  doc says the app shows VPP Mode for both, which makes it likely, but likely is not
  measured.
* **Whether `name` is empty for every VPP source**, or only this one.

---

## 5. Rules of thumb

1. **To show the user what the battery is doing:** `RUN_STATUS[1301.run_status]`.
2. **To detect VPP:** `1707.ibgRunStatus == 9`. Never `run_status == 9`.
3. **To show the dominant mode label**, follow the cloud's `effective_mode` priority:
   programme name if non-empty → `"VPP mode"` if the programme id is 9 and the name is
   empty → the work-mode label.
4. **`vpp_active` in this codebase is not VPP** — it is the Modbus M704 `wset_enabled`
   force bit, set by *any* controller including our own schedules. It is a **force**
   signal. The UI labels it "Force dispatch" for that reason.
5. **Never compare mode strings across channels** (§3, the `Time-Of-Use` / `Time-of-Use`
   difference).

## 6. Sources

* `franklinwh_cloud/const/modes.py` — `RUN_STATUS`, `OPERATING_MODES`, `CLOUD_TO_MODBUS_MODE`
* `franklinwh_direct_connect_api` — `catalog.run_status_desc()`, `OPERATING_MODES`,
  `WORK_MODE_NAMES`, `mode_label()`
* API Cookbook → *Operating Mode & Run Status — Field Guide* (david2069.github.io/franklinwh-cloud)
* *VPP Mode Reference* (david2069.github.io/franklinwh-modbus)
* Live reads on 192.168.0.110, 2026-10-12, recorded in §4
