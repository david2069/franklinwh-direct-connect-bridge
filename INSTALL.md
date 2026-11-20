# Installing the FranklinWH Direct Connect Bridge

Three ways to run it. Most people want the **Home Assistant add-on**.

Nothing here needs a checkout of any other FranklinWH repository — the Direct Connect API
library installs from PyPI like any other dependency.

---

## Prerequisites

- A **FranklinWH aGate** reachable on your LAN, with a **static IP or a DHCP reservation**.
  The bridge connects to TCP **9000** (the Direct Connect local API). If the address moves,
  the bridge loses the gateway until you update it.
- **Nothing to enable on the gateway** for reads over port 9000.
- Optional: the **Mosquitto** broker add-on, if you want the battery published as Home
  Assistant entities. It does not have to be installed first — see *MQTT* below.

---

## 1. Home Assistant add-on


[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdavid2069%2Ffranklinwh-direct-connect-bridge)

Click the button above, or add the repository by hand:
1. In Home Assistant: **Settings → Add-ons → Add-on Store**.
2. **⋮** (top right) → **Repositories**, add
   `https://github.com/david2069/franklinwh-direct-connect-bridge`, then close.
3. Find **FranklinWH Direct Connect Bridge** and click **Install**.
4. On **Configuration**, set `fwh_host` to the aGate's IP. Set `mqtt_enabled: true` to
   publish the battery as Home Assistant entities. **Save.**
5. **Start**, then **Open Web UI** (served over HA ingress). For a **Direct Connect** entry in
   the sidebar, turn on **Show in sidebar** on the same page: it was off after a fresh install
   on Home Assistant OS 18.4 (#784).

### What the add-on does for you

- **MQTT auto-configures** from the Mosquitto add-on — no host or credentials to type. The
  Supervisor supplies them. Mosquitto does **not** need to be installed first: the bridge
  re-asks the Supervisor on each reconnect attempt, so a broker installed later is picked up
  without a restart.
- **Timezone** comes from the Supervisor, so logs and rendered times match the host.
  (Schedules do not depend on this — they follow the aGate's own clock.)
- **Local history** is **on by default**. The bridge's own charts (Power History, Analytics,
  costs) read it. `metrics_enabled: false` turns recording off.
- A **watchdog** restarts the add-on if the web app stops serving. It probes `/api/live`,
  which does no gateway I/O, so an unreachable aGate never triggers a restart.
- **A prebuilt image** is downloaded from GitHub's container registry
  (`ghcr.io/david2069/{arch}-franklinwh-direct-connect-bridge`); nothing is compiled on your
  machine. Supported: **aarch64** (Raspberry Pi 4/5, most ARM boards) and **amd64** (Intel/AMD).
- **Control writes stay off** until you set `allow_writes`. You can flip it live from the
  **Settings** tab.

> **Not verified by the maintainers on a live Supervisor.** The add-on build and the
> Supervisor integration are exercised by tests against a faked Supervisor API, not on a real
> Home Assistant OS install. If something here does not match what you see, that is worth
> reporting — it is a gap in our testing, not your mistake.

---

## 2. Docker (standalone)

```bash
git clone https://github.com/david2069/franklinwh-direct-connect-bridge
cd franklinwh-direct-connect-bridge
docker build -t franklinwh-direct-connect-bridge:dev .
FWH_HOST=<your aGate IP> docker compose up -d
```

Then open <http://localhost:8101>. Leave out `FWH_HOST` and the setup wizard opens instead:
it finds your aGate, or adds a mock gateway to try the bridge without one. MQTT to Home
Assistant is off until you set `MQTT_ENABLED=true` and `MQTT_HOST` (and `MQTT_PORT`,
`MQTT_USERNAME`, `MQTT_PASSWORD` if your broker needs them).

A plain `docker build` resolves every dependency from PyPI, including
[`franklinwh-direct-connect-api`](https://pypi.org/project/franklinwh-direct-connect-api/).
**This path is verified**: the image is built from a clean export of the repository with no
sibling checkouts present, and the library, cloud and Modbus dependencies are confirmed
importable inside it.

> **Do not use `docker compose up --build`.** `docker-compose.yml` has no `build:` section
> (the image needs its wheels staged first), so the `--build` flag is **silently ignored** and
> any existing container keeps running. Build the image first, as above.

### Without Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install ".[cloud]"
franklinwh-direct-connect-bridge setup    # answer the questions once
franklinwh-direct-connect-bridge          # start it
```

Or skip `setup` and set the variables yourself:
`FWH_HOST=<your aGate IP> franklinwh-direct-connect-bridge run` (see [First sign-in](#first-sign-in-docker-and-pip)).

### From PyPI

> **Not published yet.** This route works from the first release published to PyPI
> ([#782](https://github.com/david2069/franklinwh-direct-connect-bridge/issues/782)). Until
> [the PyPI page](https://pypi.org/project/franklinwh-direct-connect-bridge/) shows a release, use *Without Docker* above.

No clone needed:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "franklinwh-direct-connect-bridge[cloud]"
franklinwh-direct-connect-bridge setup    # or set the variables yourself, as above
franklinwh-direct-connect-bridge
```

To upgrade, `pip install --upgrade "franklinwh-direct-connect-bridge[cloud]"` in the same venv.

`[cloud]` is optional. Without it everything runs, but cloud-backed capabilities report
`available: false` (see `GET /api/providers`).

### First sign-in (Docker and pip)

A new install starts with **Security on**: port 8101 sends the browser to the HTTPS port
(8102), which asks you to sign in. The bridge's certificate is its own, so the browser
warns once. Set it up either way:

**The setup command (less typing).** Run `franklinwh-direct-connect-bridge setup` with the
bridge stopped (for Docker: `docker compose run --rm franklinwh-direct-connect-bridge
franklinwh-direct-connect-bridge setup`). Run it from the folder that holds `data`, not
from inside `data`. It first shows the version, this folder, the data folder (new or
existing install), where it saves the settings, and its checks: Python 3.11 or newer, the
cloud features, and whether ports 8101 and 8102 are free (if the bridge is running, stop it
first). Each question has a default in [brackets]: press Enter to accept it, or type your
own. Four steps:

1. the aGate's address, and checks that its Direct Connect port (TCP 9000) answers. If it
   doesn't, it asks again, or keeps the address if you say so (the aGate may be off).
   Optional: leave it blank and add it later in the web UI;
2. the web port (8101) and the HTTPS port (8102). In Docker keep them: `docker-compose.yml`
   publishes those two;
3. whether to ask for a sign-in (Security on or off; on by default);
4. with Security on and no admin yet: whether to choose the admin's username and password
   now. Optional (default no): the first start then makes `admin` with a generated password
   and shows it once. Choose now and press Enter for the password, and it makes one up and
   shows it once.

It ends with a summary and, for pip, **Start the bridge now?** (Enter = yes). In Docker,
start it with `docker compose up -d`.

It saves the address and ports to `data/bridge.env` (`/data/bridge.env` in Docker), so
starting the bridge needs nothing typed. The password goes into the bridge's own accounts,
never into that file. Run `setup` again any time to change the address or ports, or to turn
Security on or off.

**Manual (environment variables).** Set them yourself instead; they win over
`bridge.env` when both are set.

- `FWH_HOST`, `HTTP_PORT`, `HTTPS_PORT`: the aGate's address and the ports.
- **Choose the admin:** set `ADMIN_USERNAME` and `ADMIN_PASSWORD` before the first start.
  They're read only while no admin exists; change the password in the bridge after that.
- **Generated admin:** set neither, and the first start makes `admin` with a random
  password, shown once in the startup banner (`docker logs <container>`, or the terminal
  you ran it in). It is never kept in the bridge's own Logs tab or a support bundle.
- **Quick start, no sign-in:** set `SECURITY=off` on the first start, e.g.
  `SECURITY=off FWH_HOST=<your aGate IP> docker compose up -d`. The bridge opens on
  <http://localhost:8101> without signing in; only the private networks can reach it.
  Anyone on them can use it, battery control included. `SECURITY` is read only on the
  first start, so it never turns Security off on an existing install.

**Turning Security on or off later:** under **Settings → Admin → Security**, or run
`setup` again with the bridge stopped. Turned off, accounts and tokens are kept, so turning
it back on restores them ([guide](docs/guide/security.md#the-first-admin)).

**The startup banner.** Before the web server starts, the bridge prints where to open it,
for example `https://localhost:8102` and this computer's address on your network, whether
Security is on, and the generated admin password on the one start that makes it. With
Security off it lists both addresses: `http://…:8101` and `https://…:8102`. If either port is
already in use (often the bridge already running in another terminal), it doesn't start,
and says which port and how to change it. Uvicorn's
own `Uvicorn running on http://0.0.0.0:8101` line is the address it listens on (every
network interface), not one to open in a browser.

**Lost the password:** `franklinwh-direct-connect-bridge reset-password admin` where the
bridge runs (inside the container for Docker).

---

## 3. Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test,cloud]"
pip install -e ../franklinwh-direct-connect-api   # optional: the library, editable
tools/dev.sh                             # build, restart, and VERIFY
```

`tools/dev.sh` rebuilds the image, recreates the container, and then **proves the container
is running your working tree**, exiting non-zero if it is not. `GET /api/version` reports the
same stamp as `source_sha`. Use it before trusting any measurement taken against the running
bridge.

---

## Upgrading

- **Add-on:** Home Assistant offers the update in the Add-on Store. Settings are preserved.
- **Docker:** `git pull`, rebuild the image, `docker compose up -d --force-recreate`.
- **Data** lives in `./data` (standalone) or the add-on's `/data`. The SQLite store migrates
  itself forward on start; there is no manual step.

### Reinstalling: read this before you remove anything

> **An upgrade keeps your Home Assistant entities. A remove-and-reinstall is the case that
> costs you history.**

Home Assistant identifies an entity by the id it was discovered with. The bridge builds
that id from the gateway's node id, so reinstalling onto the same gateway usually restores
the same entities — but if Home Assistant has an old entity still registered under that id,
it keeps the old one and gives the new one a suffix (`_2`). The new sensor then starts its
history from zero and the old series stops, which is what people notice weeks later in the
Energy dashboard.

**Keep the entity id and Home Assistant carries the history with it.** No data is copied
and nothing is exported:

1. Remove the old entity, or rename it out of the way first, so its id is free.
2. **Settings → Devices & Services → Entities**, open the new entity, and set its entity id
   to the old one.
3. Home Assistant moves history and long-term statistics across an entity-id rename, so the
   new entity continues the old series.

This works when the two mean the same thing in the same units — kWh to kWh, with the same
`state_class: total_increasing` behaviour. If the new sensor's running total starts from a
different number you will see a step in the Energy dashboard; correct it in **Developer
Tools → Statistics**, which can adjust a single sum.

If you need more than this — merging an old series into a new one — read
[docs/HA_HISTORY.md](docs/HA_HISTORY.md) first. It is possible, it is **discouraged**, and
that page says why and what the alternatives are.

Two things worth knowing before you start:

- **Check your Home Assistant version's behaviour on a single sensor first.** Carrying
  statistics across a rename is current Home Assistant behaviour, not a guarantee this
  project can make for every version — try one entity and look at its history before doing
  the rest.
- **The bridge cannot do this for you.** It publishes discovery; the entity registry is
  Home Assistant's. An integration that tries to repurpose old entities on the way in has
  to guess which old one matches which new one, and guessing wrong is worse than the step
  in the graph.

---

## Troubleshooting

**The gateway is unreachable.** Check `fwh_host` and that TCP 9000 answers from wherever the
bridge runs — on the add-on that is the Home Assistant host, which may not be the machine
you tested from. The **Network** tab shows the reachability it measured.

**No entities in Home Assistant.** Open **Home Assistant → Published by bridge**. If entities
are listed there but absent in HA, the broker the bridge publishes to is not the one Home
Assistant subscribes to — that is the usual cause, and the dashboard-card builder on that
page names the prefix it used.

**Mode or off-grid controls do nothing.** Writes are off unless `allow_writes` is set. The
UI says so on the Settings tab rather than failing quietly.

**"MODBUS :502 — Not probed".** Expected when the bridge's own Modbus client is switched off.
It is a statement about this bridge, not about the gateway; the gateway's own SunSpec Modbus
setting is the separate **SunSpec Modbus** card.

**Times look wrong.** Schedules and tariff windows follow the **aGate's** clock, not the
container's. `GET /api/site/timezone` reports what the bridge derived.

---

## Where things are

| | |
| :--- | :--- |
| Web UI | `http://<host>:8101`, or the HA sidebar panel |
| REST API | `/api/…` — see [`docs/`](docs/) |
| Add-on manifest | `config.yaml`, `build.yaml`, `repository.json` |
| Data | `./data` standalone, `/data` in the add-on |
