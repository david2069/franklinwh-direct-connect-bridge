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
5. **Start**, then open the sidebar panel (served over HA ingress).

### What the add-on does for you

- **MQTT auto-configures** from the Mosquitto add-on — no host or credentials to type. The
  Supervisor supplies them. Mosquitto does **not** need to be installed first: the bridge
  re-asks the Supervisor on each reconnect attempt, so a broker installed later is picked up
  without a restart.
- **Timezone** comes from the Supervisor, so logs and rendered times match the host.
  (Schedules do not depend on this — they follow the aGate's own clock.)
- **Local history** is **off by default** when MQTT is on: Home Assistant's recorder already
  stores the published entities, so a second copy is redundant. `metrics_enabled: true`
  forces it on.
- A **watchdog** restarts the add-on if the web app stops serving. It probes `/api/live`,
  which does no gateway I/O, so an unreachable aGate never triggers a restart.
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

Then open <http://localhost:8101>.

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
FWH_HOST=<your aGate IP> franklinwh-direct-connect-bridge run
```

`[cloud]` is optional. Without it everything runs, but cloud-backed capabilities report
`available: false` (see `GET /api/providers`).

---

## 3. Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test,cloud]"
pip install -e ../franklinwh-local      # optional: the library, editable
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
