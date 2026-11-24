# FranklinWH Direct Connect Bridge

Reads your FranklinWH aGate over its **local** interface — TCP 9000 on your own LAN, no
cloud account required — and publishes it to Home Assistant over MQTT.

> **Unofficial.** Not endorsed by or affiliated with FranklinWH. It speaks an undocumented
> local protocol that may change without notice. **Do not contact FranklinWH support about
> this add-on** — raise issues on
> [GitHub](https://github.com/david2069/franklinwh-direct-connect-bridge/issues).

---

## Getting started

1. Set **`fwh_host`** to your aGate's IP address, or leave it empty and the setup wizard
   finds your aGate (or adds a mock). Give the aGate a DHCP reservation or a static
   address — if it moves, the bridge loses the gateway until you update this.
2. MQTT is on by default (`mqtt_enabled: true`); the Supervisor supplies the broker.
3. **Save**, then **Start**, then **Open Web UI**. Turn on **Show in sidebar** for a
   **Direct Connect** entry in the sidebar; it may be off after installing.

Nothing needs enabling on the gateway for reads.

---

## Configuration

| Option | Default | What it does |
| :--- | :--- | :--- |
| `fwh_host` | — | The aGate's IP address. Leave it empty and the setup wizard finds your aGate, or adds a mock. |
| `fwh_port` | `9000` | The Direct Connect port. Leave it. |
| `modbus_port` | `502` | The aGate's Modbus TCP Server port, for battery ratings and force dispatch. Leave it; Control → Modbus can override it per install. |
| `poll_interval` | `30` | Seconds between reads. A schedule cannot react faster than this. |
| `mqtt_enabled` | `true` | Publish the battery as Home Assistant entities. |
| `mqtt_host` / `mqtt_port` / `mqtt_username` / `mqtt_password` | auto | **Leave blank.** Filled from the Mosquitto add-on via the Supervisor. Set them only for a broker the Supervisor does not know about. |
| `log_level` | `info` | `debug` when reporting a problem. |
| `read_only` | `true` | Kept for older setups; it does not block writes. Mode and off-grid changes ask you to confirm. |
| `allow_writes` | `false` | Kept for older setups; it no longer blocks writes (since 0.5.2). Mode and off-grid changes ask you to confirm instead. |
| `ha_notify` | `true` | Send Home Assistant notifications for the events you enable. |
| `metrics_enabled` | on | Local SQLite history, used by the bridge's own charts. **On unless set to `false`.** |
| `metrics_retention_days` | — | How long to keep that local history. |
| `modbus_host` | — | Not used for force control: each gateway's force goes to that gateway's own host. Override it under **Control → Modbus client**. |
| `modbus_bridge_url` / `fwhai_url` | — | Optional links to the sibling FranklinWH projects. |

---

## What it handles for you

- **MQTT needs no setup.** The Supervisor supplies the broker and credentials. Mosquitto does
  **not** have to be installed first — the bridge re-asks on each reconnect, so a broker
  installed later is picked up without a restart.
- **Timezone** comes from the Supervisor, so logs and displayed times match your host.
  Schedules do not depend on it: they follow the **aGate's own clock**, which matters if your
  gateway and your Home Assistant are in different zones.
- **The watchdog** restarts the add-on if the web app stops serving. It probes `/api/live`,
  which does no gateway I/O, so an unreachable aGate never causes a restart loop.
  **Watchdog** is off after a fresh install: turn on **Watchdog** on the add-on's **Info**
  page for it to act.
- **Mode and off-grid changes ask you to confirm first.** Other writes (a force, a smart
  circuit) go through.

---

## Troubleshooting

**"Gateway unreachable."** Check `fwh_host`, and that TCP 9000 answers **from the Home
Assistant host** — which may not be the machine you tested from. The **Network** tab shows
what the bridge measured.

**No entities appear in Home Assistant.** Open **Home Assistant → Published by bridge** in
the panel. If entities are listed there but missing in HA, the broker the bridge publishes to
is not the one Home Assistant subscribes to. That page's **Dashboard card** builder names the
prefix it used.

**Controls do nothing.** Mode and off-grid changes ask you to confirm first; `allow_writes`
no longer blocks writes. The reason for any refusal is in the add-on's log.

**"MODBUS :502 — Not probed."** Expected when the bridge's own Modbus client is off. It
describes *this add-on*, not your gateway — the gateway's own setting is the separate
**SunSpec Modbus** card.

**Times look wrong on a schedule.** Schedules use the aGate's clock. The **Health** tab and
`/api/site/timezone` report what was derived from the gateway.

---

## More

- [**User Guide**](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/docs/guide/README.md)
  — the tabs, the Scheduler, Home Assistant entities, and which gate stops a write
- [Installation, including Docker and development](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/INSTALL.md)
- [Changelog](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/CHANGELOG.md)
- The **Guide** tab in the panel documents the underlying **Direct Connect protocol library**,
  not this add-on. It is the reference for what the gateway exposes; this page is the add-on.
