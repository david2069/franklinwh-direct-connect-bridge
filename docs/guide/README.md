# FranklinWH Direct Connect Bridge — User Guide

This is the guide to **the bridge**: its web UI, its scheduler, what it publishes to
Home Assistant, and which controls can actually write to your gateway.

It is deliberately *not* the in-app **Guide** button. That opens the bundled
[Direct Connect API](https://github.com/david2069/franklinwh-direct-connect-api)
documentation — the wire protocol, the `cmdType` catalogue, the frame formats. Useful if
you are writing code against the aGate; not useful if you want to know what the
Scheduler's "Only if" box does. This guide covers the second question.

| If you want to… | Read |
|---|---|
| Install, upgrade or configure the bridge | [`INSTALL.md`](../../INSTALL.md) |
| Know what each tab is for, and how to get around | [Tour of the UI](tour.md) |
| Change something on the gateway, and know what gates it | [Control and write safety](control.md) |
| Automate charge/discharge windows, modes, circuits, alerts | [Scheduler](scheduler.md) |
| Get the aGate into Home Assistant | [Home Assistant and MQTT](home-assistant.md) |
| Run more than one aGate, or model a site | [Multi-gateway and sites](multi-gateway.md) |
| See history, costs and tariffs | [History, costs and tariffs](energy-and-costs.md) |
| Understand how the protocol works | the in-app **Guide** button |

Open the UI at `http://<bridge-host>:8101`. As a Home Assistant add-on, use the add-on's
**Open Web UI** button or the sidebar panel.

---

## The one thing to understand first

The bridge reaches your system over **three different paths**, and they do not have the
same powers. Most of the surprises in this UI come from this split, so it is worth
reading once:

| Path | Transport | What it owns |
|---|---|---|
| **Local** (Direct Connect) | `sendMqtt` over TCP `:9000` to the aGate | Almost all reads; operating mode; smart-circuit on/off; off-grid; generator config; reboot |
| **Modbus** | SunSpec, either direct TCP `:502` or an installed **Modbus Bridge** over REST | Battery **force** charge / discharge / standby, and the inverter's max charge/discharge ratings |
| **Cloud** | FranklinWH cloud API (needs your FranklinWH account) | **Reserve SoC**, the TOU schedule, and some authoritative status |

The bridge records, in code and in the UI, a short list of things that **cannot** be done
over the local path — not as an assumption but as a probe result. `GET /api/capabilities`
returns them; measured on the running bridge on 2026-10-15:

| Wanted | Why not locally |
|---|---|
| Reserve SoC | "1405/1725/1727 accept the write and discard it" |
| TOU schedule | "1407 accepts the write and discards it" |
| Smart-circuit schedule | "1409 accepts the schedule write and discards it" |
| Force charge/discharge | "no dispatchId/gridChargeMax field exists locally" |

Where a path is missing, the UI is meant to say so and disable the control rather than
offer one that silently does nothing. If you find a control that fails without
explaining itself, that is a defect worth reporting.

If you ever need to know *where* a number on screen actually came from, the bridge has a
tool for exactly that: **Settings → Integrations → Mapping** has a read-only **Probe**
that takes a field name, finds the frame itself, and shows you the live value and the
exact request it sent. See [Tour of the UI](tour.md#integration--mapping-and-the-probe).

---

## How this guide was checked

Every statement here was taken either from the bridge's source in this repository or from
a read-only `GET` against a running bridge. Live reads were taken on **2026-10-15**
against a bridge reporting `version 0.2.0`, `source_sha bc847f5` (from `/api/version`).

Two caveats, stated rather than hidden:

- That container was **two commits behind** this repository's `main` at the time
  (`bc847f5` vs `e9bc99d`). One of the two is documentation only; the other changed how
  the bridge authenticates to an installed Modbus Bridge. Anything about *Modbus Bridge
  REST* below therefore comes from the source, not from a live read, and is marked.
- Where a behaviour depends on hardware this guide could not exercise (a generator, a
  three-aPower stack, an actual grid outage), it says **unverified**. One site on one
  firmware is a hypothesis, not a mapping.

Counts quoted below (21 published entities, 196 scheduler sensors, 8 trigger types,
13 operators) are from that live bridge and will differ with your configuration — they
are there to tell you the shape of the thing, not to be exact on your install.

**Integration → Mapping and its Probe** landed in `main` while this guide was being
written and were read from the source only; they were not exercised against the running
bridge, which predates them.
