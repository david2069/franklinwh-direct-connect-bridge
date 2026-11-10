# Developers Guide

This guide is for people writing code, automations or dashboards that talk to the bridge:
over its REST API, over MQTT, or through Home Assistant. If you want to use the bridge's
own web UI, read the [User Guide](../guide/index.md) instead.

The bridge talks to the aGate on your behalf. You do not need to know the aGate's
protocol to use anything here. If you do want it, that is the
[Direct Connect API](https://github.com/david2069/franklinwh-direct-connect-api)
documentation, which the bridge also bundles behind the in-app **Guide** button.

## Pages in this guide

| Page | What it covers |
|---|---|
| [REST API and OpenAPI](rest-api.md) | Where the OpenAPI schema and the Swagger and ReDoc pages are served, on port 8101 and under Home Assistant ingress. The endpoint groups, gateway selection, errors, and what does and does not guard a write. |
| [REST endpoint reference](api-endpoints.md) | Every operation, generated from the bridge's own schema by `tools/gen_api_reference.py`. |
| [How the web UI uses the API](web-ui.md) | Server-rendered templates, the Alpine.js store and tab components, what the browser polls and how often, and two worked examples. |
| [Sending data to Home Assistant over MQTT](mqtt.md) | Discovery, state, availability and command topics, device identity, entity groups, retained messages and purging, with sample payloads. |
| [Reading Home Assistant](reading-home-assistant.md) | How the bridge reads entity states and calls services in Home Assistant. It uses HA's REST API, not the websocket API. |
| [Use case: integrating with the Scheduler](scheduler-integration.md) | End to end: a Home Assistant price sensor as a schedule condition, the schedule created over REST, what each tick does, a service call as an action, and how the result reaches Home Assistant. |

## How this guide was checked

Each statement names the source file and function it was read from. Paths are relative
to `src/franklinwh_direct_connect_bridge/`. Code was read on `main` at release **0.5.2**,
on 2026-10-17.

Some statements were also checked live, with read-only `GET` requests only, against a
Home Assistant OS test VM running the add-on. The VM's `/api/version` reported
**0.5.3** (then a pre-release build of PR #164), with `source_sha`
`unknown`. Those statements say so. Anything else is from reading the code and is
**not verified live**.

Sample payloads were produced from the code by running it against the bridge's built-in
**mock gateway**, the library's in-process `Emulator`. The values in them are synthetic,
and serials are replaced with `<SERIAL>`.

!!! warning "Unofficial software"
    This bridge is not affiliated with or endorsed by FranklinWH. It sends write
    commands to grid-connected battery hardware. Anything that can reach its HTTP API can
    change your system, within the limits described in
    [REST API: write safety](rest-api.md#write-safety).
