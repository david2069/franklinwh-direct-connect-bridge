# Multi-gateway & HA entities — state of play and phased plan

**Filed:** 2026-09-14 · Scope: `franklinwh-local-bridge` only.

---

## 1. What is already built

**Multi-gateway is ~70% done and working**, not a greenfield feature:

| layer | state | detail |
| :--- | :--- | :--- |
| Config | ✅ | `FWH_HOSTS` — CSV of `host` or `host=Label` (`10.0.0.5=Home,10.0.0.6=Shed`), wins over `FWH_HOST` |
| Registry | ✅ | `state.GatewayState`, `gateways()`, `get_gateway(id)` |
| Poller | ✅ | **one `run_gateway` task per gateway**, each with its own caches and connectivity |
| MQTT / HA | ✅ | per-node topics `prefix/{node}/state`, per-node discovery, per-node `client_id`; **distinct serial → distinct HA device**, collision-free |
| Metrics DB | ✅ | samples tagged with the gateway serial |
| REST | 🟡 | `/api/gateways`, `/api/gateways/{id}/summary`; **47 of 67** endpoints accept `?gateway=` |
| UI | 🟡 | topbar picker + `gwq` helper wired into the original tabs |

**HA entities are minimal**: **8 read-only sensors** — `soc`, `grid_w`, `solar_w`,
`battery_w`, `load_w`, `generator_w`, `mode`, `latency_ms`. No switches, selects or
numbers, and **nothing from any surface added since**: no circuits, no BMS cells, no solar
detail, no generator.

## 2. Defect found while surveying — the newest tabs ignore the picker

`circuits_tab.js`, `generator_tab.js`, `solar_tab.js` and `battery_tab.js` call
`fetch('api/circuits')`, `fetch('api/solar')` … **without `?gateway=`**. The endpoints all
accept it; the tabs never send it. On a multi-gateway site those four tabs silently show
the **default** gateway while the topbar says otherwise — the worst kind of wrong, because
it looks right.

Latent on a single-gateway site (this one), which is why tests and live checks never caught
it. **This is mine** — the pattern existed in `app.js` (`gwq`) and I did not follow it in
four consecutive tabs.

## 3. Phased plan

Phases are ordered so each ships something usable and nothing depends on a later phase.

### Phase 0 — fix the picker regression · **S** (~half a day)
*Component: `static/js/*_tab.js`*

Route the four tabs through the existing `gwq` helper; add a lint test in the shape of the
existing `*_tab.js` scanner that **fails when a tab calls `api/…` without a gateway
parameter**, so the next tab cannot regress it. Do this first — it is a correctness bug,
not a feature.

### Phase 1 — finish REST gateway coverage · **S–M** (~1 day)
*Component: `app.py`*

Add `?gateway=` to the remaining ~20 endpoints and assert coverage with a test that walks
`app.routes` and requires the parameter on every `/api/` route that reaches a device. That
test is the deliverable as much as the parameter is — it converts "we added it everywhere"
from a claim into a check.

### Phase 2 — HA entities from existing reads · **M** (~2–3 days)
*Component: `publish/entities.py` + poller state*

Additive sensors only, no new device interaction — the poller already reads most of this:

- **Solar** — PV total W, energy today, per-input rated kW, relay states
- **Circuits** — per-circuit on/off, power, lifetime energy (only for `present` circuits)
- **Battery** — pack SoH, min/max cell mV, cell spread, temperature spread
- **Generator** — state, enabled, output W
- **System** — grid/solar/generator relays, off-grid flag, standby

Two design rules: **never publish an entity for absent hardware** (the presence work
already decides this), and keep the state topic one JSON document per gateway so entity
count does not multiply MQTT traffic.

### Phase 3 — writable HA entities · **M–L** (~3–5 days)
*Component: `publish/` (new command-topic subscriber) + `client.py`*

Switches and numbers for the writes that are **hardware-verified**: circuit on/off
(`switch`), operating mode (`select`), generator enable and config (`switch`/`number`).
Deliberately excluded: smart-circuit schedules (silently discarded — see
`DISCARDED_WRITES`) and reserve SoC (unproven — `RESEARCH-RESERVE-SOC`). Every command
must go through the existing read-back verification and republish the *verified* state,
never the requested one.

### Phase 4 — gateway lifecycle & mock gateways · **L** (~1 week)
*Component: `state.py`, `config.py`, new `/api/gateways` CRUD, Settings UI*

Mirror the Modbus Bridge's gateway record: add/edit/remove without a restart, **mock
gateways** for development, per-gateway `poll_interval`, and the `service_id` → Utility
service link. This is the largest piece and the only one needing persistence changes, which
is why it is last despite being requested early — everything above is useful without it.

### Phase 5 — per-gateway UI polish · **S–M**
Gateway switcher in the sidebar as well as the topbar, per-gateway health badges, and a
combined "all gateways" dashboard view.

## 4. Recommendation

**Do Phase 0 now** regardless of what else is chosen — it is a live correctness bug with a
cheap permanent guard.

Then **Phase 2 before Phase 1**: HA entities are what actually gets used day to day, and
the remaining `?gateway=` endpoints are mostly diagnostic surfaces that a second gateway
would rarely need first. Phase 1 is cheap enough to fold in whenever.

**Phase 4 only when a second real gateway exists.** Building gateway CRUD against a
single-gateway site risks exactly the class of bug found in §2 — untestable paths that look
finished. Mock gateways would help, which is an argument for doing them *first within*
Phase 4.
