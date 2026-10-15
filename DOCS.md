# FranklinWH Direct Connect Bridge

Reads your FranklinWH aGate over its **local** interface — TCP 9000 on your own LAN, no
cloud account required — and publishes it to Home Assistant over MQTT.

> **Unofficial.** Not endorsed by or affiliated with FranklinWH. It speaks an undocumented
> local protocol that may change without notice. **Do not contact FranklinWH support about
> this add-on** — raise issues on
> [GitHub](https://github.com/david2069/franklinwh-direct-connect-bridge/issues).

---

## Getting started

1. Set **`fwh_host`** to your aGate's IP address. Give it a DHCP reservation or a static
   address — if it moves, the bridge loses the gateway until you update this.
2. Set **`mqtt_enabled: true`** to publish entities to Home Assistant.
3. **Save**, then **Start**, then open the sidebar panel.

Nothing needs enabling on the gateway for reads.

---

## Configuration

| Option | Default | What it does |
| :--- | :--- | :--- |
| `fwh_host` | — | **Required.** The aGate's IP address. |
| `fwh_port` | `9000` | The Direct Connect port. Leave it. |
| `poll_interval` | `30` | Seconds between reads. A schedule cannot react faster than this. |
| `mqtt_enabled` | `false` | Publish the battery as Home Assistant entities. |
| `mqtt_host` / `mqtt_port` / `mqtt_username` / `mqtt_password` | auto | **Leave blank.** Filled from the Mosquitto add-on via the Supervisor. Set them only for a broker the Supervisor does not know about. |
| `log_level` | `info` | `debug` when reporting a problem. |
| `read_only` | `true` | Blocks every write, including from the UI. |
| `allow_writes` | `false` | Permits mode and off-grid changes. Also switchable live from the **Settings** tab. |
| `ha_notify` | `true` | Send Home Assistant notifications for the events you enable. |
| `metrics_enabled` | auto | Local SQLite history. **Off by default when MQTT is on** — the HA recorder already stores the published entities, so a second copy is redundant. Set `true` to force it. |
| `metrics_retention_days` | — | How long to keep that local history. |
| `modbus_host` | — | Optional. The aGate's Modbus/SunSpec address, for battery force control. |
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
- **Writes stay off** until you allow them.

---

## Troubleshooting

**"Gateway unreachable."** Check `fwh_host`, and that TCP 9000 answers **from the Home
Assistant host** — which may not be the machine you tested from. The **Network** tab shows
what the bridge measured.

**No entities appear in Home Assistant.** Open **Home Assistant → Published by bridge** in
the panel. If entities are listed there but missing in HA, the broker the bridge publishes to
is not the one Home Assistant subscribes to. That page's **Dashboard card** builder names the
prefix it used.

**Controls do nothing.** Writes are disabled. Set `allow_writes`, or use the Settings tab.

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
