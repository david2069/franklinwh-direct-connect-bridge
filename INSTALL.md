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
