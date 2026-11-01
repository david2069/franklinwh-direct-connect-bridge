# Plan: Home Assistant controls over MQTT

Status: **agreed** (owner decisions in §4, 2026-10-16). Written 2026-10-16 after 0.4.4.

> **Update 2026-10-31 (owner): decision 1 is overridden.** Controls may run unconfirmed from Home
> Assistant: "If users can't see it in HA, they cannot test it." C2 (reserve SoC) is built.
> Off-grid and other controls can now be planned as HA entities; a write still has to take
> effect to become a control, so grid limits wait until their local write is proven.

## 1. Where it stands (0.4.4)

21 entities per gateway:
- **18 sensors**, all with values since 0.4.3 (#96).
- **Controls:**
  - an *Operating Mode* select (works);
  - three *Smart Circuit* switches. They accept on/off, but their **state is always unknown**: the poll never reads circuit state (1409).

There are no number entities (sliders), no buttons, and no limits.

The comparison of HA diagnostics from a live install (Direct 0.4.1 vs FWHAI 0.6.80 and Modbus Bridge 0.2.6
on the same aGate, 2026-10-16) shows what the other two bridges offer:

| Control | Modbus Bridge | FWHAI | Direct today | How the bridge could do it |
|---|---|---|---|---|
| Smart circuit on/off with state | — | switch, state works | switch, state **unknown** | read 1409 each poll, or after each command |
| Reserve SoC (per mode) | number 0–100 % | number 0–100 % | none | **local write is discarded by the aGate** (1405, see API_COMPARISON.md), so only via the cloud provider (`POST /api/cloud/reserve`) when credentials exist |
| Grid export/import limit | — | number 0–100 kW plus "unlimited" switches | none | `POST /api/grid/limits` exists. It is an **unverified** local write, so it needs `confirm` |
| Battery command / dispatch | select plus power, duration and target SoC | dispatch action/power/duration/target | none | `POST /api/dispatch` and `/api/battery/command` exist |
| Off-grid | — | select | none | `POST /api/offgrid` (consequential, needs `confirm`) |
| Run status text | — | — | raw number (`1`) | publish `run_status_desc`, which the poll already has |

## 2. Principles

- **Only writes verified on hardware become HA controls.** An HA control that silently does nothing
  is worse than no control (the existing rule in `publish/entities.py`).
- **A control's state must come from a read, not from the last command.** No control is published
  without a state source.
- An HA control has no confirm dialog. So **a consequential action (off-grid, dispatch, grid limits)
  is only exposed if the owner decides HA automations may do it unconfirmed.**
- New entities are additions, not identity changes. They can ship without the #92 migration, but
  **each release covers one functional area** (TEST_POLICY §1).

## 3. Releases, one area each, every one through G0–G3

| Release | Contents | Gates beyond G0/G1 |
|---|---|---|
| **C1** | Smart-circuit switch **state**: read 1409 in the poll's own session and publish `circuit_N_on`. Run status as text. | G2 read-only: show the switch state follows the app; measure the poll time added |
| **C2** | Reserve SoC numbers (one per mode), published **only when the cloud provider is configured**. State from the provider's read. | G2 write: plan, read back **and** the app showing the new value, restore the original |
| ~~C3~~ | Grid export/import limits: **not exposed to HA** (owner, 2026-10-16: no unconfirmed writes). They stay in the bridge UI. | — |
| **C4** | **Battery command, the same pattern as the Modbus Bridge and FWHAI** (owner, 2026-10-16). See §3.1. | G2 write: **measured** battery W against the command, revert timer, restore the mode; every status state seen on hardware |
| — | Off-grid: **not exposed to HA** (owner, 2026-10-16) | — |

All of them: Modbus off on the real aGate, read-only by default, real hardware only on the owner's
go-ahead in the session.

### 3.1 C4 battery command: the shape

- **`select` Battery Command**: Not Active / Force Charge / Force Discharge / Force Standby / Release.
  **Choosing a command is the action.** It is the deliberate step that stands in for a confirm dialog.
- **`number` parameters, staged only.** Changing one sends nothing to the aGate; it is used by the next
  command.
  - Power W, with Max Charge / Max Discharge sized from the **measured** inverter rating, not an assumed 5 kW;
  - Power %;
  - Duration (0 = no limit, which uses the bridge's revert timer);
  - Target SoC (0 = disabled).
- **Feedback** (`sensor`s), so the outcome is visible at once and an automation can act on it:
  - *Command status*: `accepted` → `in progress` → `completed`, or `rejected` (with the reason) or
    `ended abnormally` (with the reason: reverted by timer, overridden by the aGate or app, connection lost);
  - *Active command*, with the time it started and its remaining duration;
  - *Last result*: the measured battery W against the commanded W.
- State comes from reads (the aGate's own state plus measured power), never from "the command was sent".

## 4. Decisions for the owner

1. **No control runs unconfirmed (owner, 2026-10-16).** Grid limits and off-grid stay in the bridge UI.
   The C4 battery command is allowed because choosing the command *is* the explicit action (§3.1).
2. **C4 alongside the Modbus Bridge: last command wins** (owner, 2026-10-16). The status sensor
   reports *ended abnormally: overridden* when another controller replaces this bridge's command.
3. **Off-grid** as an HA control: no (from 1).
4. **Order: C1 → C2 → C4** (owner, 2026-10-16).
