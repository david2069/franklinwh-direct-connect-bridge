# REST API and OpenAPI

[Developers Guide](index.md) · [Endpoint reference](api-endpoints.md)

The bridge is a [FastAPI](https://fastapi.tiangolo.com/) application. Everything the web
UI does is a call to its REST API, so anything the UI can do, your code can do too.

---

## Where the API is served

The app is built by `create_app()` in `app.py`. Its `FastAPI(...)` call sets a title, a
version and a description, and leaves `openapi_url` at its default. It sets
`docs_url=None, redoc_url=None` because `create_app()` serves `/docs` and `/redoc` itself,
so they work under ingress (see below). The paths are FastAPI's usual ones:

| Path | What it is |
|---|---|
| `/openapi.json` | The OpenAPI schema: every path, parameter and request-body model. |
| `/docs` | Swagger UI. You can try requests from it. |
| `/redoc` | ReDoc, a read-only rendering of the same schema. |
| `/guide/` | **Not** this API. It is the bundled Direct Connect API documentation, mounted at `/guide` because FastAPI owns `/docs` (comment in `create_app`). |

The port is **8101** in every install:

- **Home Assistant add-on:** `config.yaml` publishes `8101/tcp` ("Web UI + REST API")
  and uses it as `ingress_port`.
- **Docker:** `docker-compose.yml` maps `8101:8101`.
- **Python:** `franklinwh-direct-connect-bridge run` serves on `:8101` (README).

Fetch the schema with:

```bash
curl -s http://<bridge-host>:8101/openapi.json -o openapi.json
```

**Verified live**, 2026-10-17, read-only `GET`s on the add-on in the test VM (version
0.5.3): `/docs` and `/redoc` returned 200, and `/openapi.json` returned 200 with 233
operations. The schema generated from `main` (0.5.2) has 232. The extra one is
`GET /api/diagnostics/link`, added in 0.5.3 (PR #164). The endpoint table is regenerated
from 0.5.5.

### Under Home Assistant ingress

The web UI works under ingress. `_base_path()` in `app.py` reads the `X-Ingress-Path`
header on every request, and `templates/index.html` puts it in `<base href>`, so every
relative URL the UI uses resolves inside the ingress path.

Swagger UI and ReDoc follow the same header. FastAPI's built-in pages load the schema
from `root_path + "/openapi.json"`, and the app never sets `root_path`, so under ingress
that pointed at Home Assistant's root rather than at the bridge (#177). `create_app()`
now serves `/docs` and `/redoc` itself, with the schema URL taken from `_base_path()`.

!!! tip "Use port 8101 for API work"
    For scripts and for Swagger, use `http://<ha-host>:8101/...`. Ingress also needs a
    Home Assistant login session, which a script does not have. From inside Home
    Assistant, for example a `rest_command`, use the add-on's internal hostname on port
    8101, as described in
    [Scheduler → Using schedules from Home Assistant](../guide/scheduler/index.md#using-schedules-from-home-assistant-direct-connect-only).

---

## Authentication

From 0.5.32 (#457) one middleware in `app.py` (`_security`) decides every request; see
the User Guide's [Security](../guide/security.md) page.

- **Trusted networks** apply always: another address gets **403**.
- **Security off** (an upgraded install keeps it off): no sign-in, on 8101 or the HTTPS
  port, as before.
- **Security on** (a new install): 8101 answers `/api/live` and Home Assistant ingress,
  and redirects everything else (**307**) to the HTTPS port (8102). There, send
  `Authorization: Bearer <token>` (an API token, **Settings → Admin → Security → API
  tokens**) or a session cookie from `POST /api/auth/login`. No credentials: **401**. A
  role that may not make the call: **403** "Your role (viewer) can't do this."
- Roles per route are in `security.required()`: reads for every role (no web pages for
  `api`); battery commands (`/api/battery/command`, `/api/dispatch`, `/api/mode`,
  `/api/offgrid`, `/api/cloud/reserve`, `/api/cloud/set-mode`, `/api/cloud/hold/clear`,
  `/api/alerts/…`) for admin, user and api; schedules for admin and user; everything else
  admin only.
- Home Assistant ingress requests get the role of the HA user's group, Security on or off.

Tokens and passwords the bridge holds are **write-only** over the API. Home Assistant
instance tokens are removed by `ha_instances.redact()` and replaced by `has_token`.
`GET /api/settings` reports `ha_token_set` and never the token.

---

## Endpoint groups

The [endpoint reference](api-endpoints.md) lists every operation. In outline, with the
number of operations on `main` (0.5.2):

| Group | Prefix | Ops | Use it for |
|---|---|---|---|
| Live data | `/api/summary`, `/api/gateways/{id}/summary`, `/api/power`, `/api/battery`, `/api/solar`, `/api/grid`, `/api/live` | — | The current reading. `/api/summary` returns the poller's cached copy, so it costs the aGate nothing. `/api/live` is liveness only, with no device I/O (the add-on watchdog uses it). |
| Gateways | `/api/gateways` | 9 | List, add, edit, enable and remove gateways, make one the default (`POST /api/gateways/{id}/default`), and per-gateway summaries. Setting `is_default` through add or edit, disabling the default, and removing an enabled gateway each return 409 with the reason. |
| Schedules | `/api/schedules` | 17 | Create, update, delete, run, stop, pause and resume schedules, plus the timeline, log, runs, presets, import/export, and a condition evaluator. See [the Scheduler use case](scheduler-integration.md). |
| Battery and control | `/api/battery/command`, `/api/dispatch`, `/api/mode`, `/api/offgrid`, `/api/circuits`, `/api/grid/limits`, `/api/reboot` | — | Writes. See [write safety](#write-safety) below. |
| Modbus client (this bridge) | `/api/modbus` | 3 | Settings and test for the bridge's optional connection to the Modbus TCP Server (aGate :502). |
| Home Assistant | `/api/ha` | 16 | HA instances, entity browsing and exposure, notification devices, what the bridge publishes, dashboard YAML. See [Reading Home Assistant](reading-home-assistant.md). |
| MQTT publishing | `/api/mqtt` | 12 | Broker status, entity groups, republish, unpublish, broker scan and orphan clean-up. See [MQTT](mqtt.md). |
| Notifications | `/api/notify` | 5 | Notification triggers, their log, and tests. |
| Setup | `/api/setup` | 8 | The setup wizard, including the Home Assistant checks. |
| Health and network | `/api/health`, `/api/network` | 7 | Reachability, link history, ping. |
| Cloud | `/api/cloud` | 16 | The FranklinWH cloud path: reserve SoC, TOU, cloud mode. Needs cloud credentials. |
| Raw commands | `/api/cmd`, `/api/raw`, `/api/call` | 39 | Named reads of Direct Connect commands, and a raw console. |
| Tariffs and billing | `/api/tariffs`, `/api/tariff`, `/api/billing`, `/api/meters`, `/api/utilities`, `/api/sites` | 25 | Sites, utility services, meters, tariffs and costs. |
| Admin | `/api/admin`, `/api/settings`, `/api/logs`, `/api/version` | 12 | Backups, storage, live settings, the log, and version. |

`GET /api/version` returns `version`, `asset` and `source_sha`. Quote `source_sha` when
you report a result: it says which source the running build came from.

---

## Choosing a gateway

Most read and control endpoints take an optional `gateway` query parameter, a gateway
id from `GET /api/gateways`. A request that acts on an aGate must name one; none goes to
the default gateway (#379).
`_gw_or_404()` in `app.py` returns **404** for an unknown id, before any device I/O.

```bash
curl -s "http://<bridge-host>:8101/api/health?gateway=<gateway-id>"
```

The web UI adds the parameter only when more than one gateway is registered
(`gwQuery()` in `static/js/app.js`).

---

## Errors

Errors use FastAPI's standard shape. A handler that refuses raises `HTTPException`, so
the body is:

```json
{"detail": "'set operating mode' changes the physical gateway — re-send with confirm=true."}
```

A body that fails validation against the request model returns **422**, with `detail` as
a list of objects, one per field. That is FastAPI's default. `app.py` does not install a
custom handler for it.

The status codes the bridge raises on purpose. The provider codes (501, 502, 503) are
described in
[Control → Provider availability](../guide/control.md#3-provider-availability-can-the-path-be-reached-at-all).

| Code | Meaning |
|---|---|
| 404 | Unknown gateway, schedule or other id. |
| 422 | The body did not match the model, or a value was out of range. |
| 428 | A consequential action was sent without `confirm=true`. |
| 501 | The path exists but is deliberately not wired (for example `/api/dispatch` through the `franklinwh-modbus` library). |
| 502 | The provider (aGate, cloud, Modbus Bridge) did not answer. |
| 503 | No provider is configured for this action, or the local store the endpoint needs is disabled ("metrics store is disabled"). |

---

## Write safety

Read this before you automate a write. The current state is described for users in
[Control and write safety](../guide/control.md#the-three-gates). In code:

**`allow_writes` does not block anything.** `client.writes_enabled()` returns `True`
unconditionally. Its docstring says: "Global write-gate dropped (FEAT-WRITE-CONFIRM):
reversible writes just work." `_guard_writes()` in `app.py` is still called by many
write endpoints, including schedules, HA instances and constants, but it raises only
when `writes_enabled()` is false, so it never does.

**`confirm` is the gate that acts.** `_guard_consequential(confirm, action)` in `app.py`
raises **428** unless `confirm` is true. The endpoints that take a `confirm` field or
query parameter are marked in the [endpoint reference](api-endpoints.md). On `main` they
are:

- `POST /api/mode`
- `POST /api/offgrid`
- `POST /api/grid/limits`
- `POST /api/cloud/set-mode`
- `POST /api/cloud/grid-status`
- `POST /api/der-comms`
- `POST /api/reboot`
- `POST /api/raw`
- `POST /api/mqtt/orphans/purge`
- `POST /api/admin/backup/{name}/restore`

For how each one handles `confirm`, see the
[gate table in the User Guide](../guide/control.md#which-gate-applies-to-what).

**Not confirm-gated:** battery force and release (`POST /api/battery/command`; the UI
asks, the API does not), `POST /api/dispatch`, smart circuits, reserve SoC, and every
create, edit or delete of gateways, sites, tariffs, schedules and HA instances.

!!! warning "Creating a schedule is a write to your battery, later"
    `POST /api/schedules` is not confirm-gated. A schedule with a `force` action that you
    create over the API will move the battery when its window opens, with no prompt.

**MQTT controls bypass `confirm`.** Home Assistant's **Operating Mode** select and
**Smart Circuit** switches arrive on MQTT command topics. `_on_control()` in `poller.py`
checks only `client.writes_enabled()`, which is always true, then calls
`publish.handle_command()`. A mode change from Home Assistant is therefore not
confirm-gated, although the same change over REST is. See [MQTT](mqtt.md#command-topics).
