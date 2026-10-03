/**
 * FranklinWH Local Bridge — Network tab.
 * On-LAN network diagnostics for the selected aGate (GET /api/network): the
 * router→internet→cloud connectivity chain (1113), bridge-side reachability the cloud can't
 * see (ping/:9000/:502), interfaces + signal (1118), interface switches (1119), and the
 * AWS-IoT endpoint/region (1121, credentials redacted server-side).
 */
function networkTab() {
  return {
    net: null,
    loading: false,
    pingResult: null,
    pinging: false,
    pop: null,

    async init() {
      await this.load();
      this.$watch('$store.app.selectedGateway', () => this.load());
    },

    async load() {
      this.loading = true;
      try {
        this.net = await (await fetch('api/network' + this.$store.app.gwQuery('?'))).json();
        try { this.pop = await (await fetch('api/cloud/pop')).json(); } catch (e) { /* optional */ }
      } catch (e) {
        this.$store.app.toast('Network scan failed: ' + e.message, 'error');
      } finally { this.loading = false; }
    },

    // aGate payloads nest under result / commSetPara — dig for a key wherever it lives.
    dig(o, key) {
      if (!o || typeof o !== 'object') return undefined;
      if (key in o) return o[key];
      for (const w of ['result', 'commSetPara']) {
        if (o[w] && typeof o[w] === 'object') { const v = this.dig(o[w], key); if (v !== undefined) return v; }
      }
      return undefined;
    },
    statusOk(v) { return v === 1 || v === true || v === '1' || v === 'online' || v === 'connected' || v === 'ok'; },

    // The connectivity chain: LAN router → internet → FranklinWH cloud (AWS).
    // NB: the 1113 top-level routerStatus/netStatus/awsStatus read 0 on observed firmware
    // (a field-position quirk, like 1801) — derive from the RELIABLE per-link fields + 1118.
    tri(vals) {  // true if any is ok; null if none reported; else false
      if (vals.some(v => this.statusOk(v))) return true;
      return vals.every(v => v == null) ? null : false;
    },
    get chain() {
      const c = this.net && this.net.connectivity;
      const g = (k) => this.dig(c, k);
      const ifAws = this.net && this.net.interfaces && this.net.interfaces.awsStatus;
      const router = this.tri([g('wifiConnectRouterStatus'), g('EthConnectRouterStatus'), g('4GConnectBSStatus')]);
      const cloud = this.tri([ifAws, g('awsStatus')]);
      // No dedicated reliable "internet" flag — cloud-reachable implies internet, else netStatus.
      const inet = cloud === true ? true : this.tri([g('netStatus')]);
      return [
        { label: 'Router / LAN', v: router },
        { label: 'Internet', v: inet },
        { label: 'FranklinWH cloud (AWS IoT)', v: cloud },
      ];
    },
    get reach() { return (this.net && this.net.reachability) || {}; },
    get ifaces() {
      const n = (this.net && this.net.interfaces) || {};
      const c = this.net && this.net.connectivity;
      const wifiSig = this.dig(c, 'WifiSignalStrength');
      const cellSig = this.dig(c, '4GSignalStrength');
      return [
        { name: 'WiFi', d: n.wifi, extra: wifiSig != null ? ('signal ' + wifiSig) : null },
        { name: 'Ethernet 0', d: n.eth0, extra: null },
        { name: 'Ethernet 1', d: n.eth1, extra: null },
        { name: 'Cellular / 4G', d: n.operator, extra: (cellSig != null ? ('signal ' + cellSig)
            : ((n.operator && n.operator.rssi != null) ? ('RSSI ' + n.operator.rssi) : null)) },
      ].filter(x => x.d && Object.values(x.d).some(v => v !== null && v !== undefined && v !== ''));
    },
    get cloudRows() {
      const c = (this.net && this.net.cloud) || null;
      if (!c) return null;
      const noise = new Set(['opt', 'result', 'reason', 'code', 'message', 'sno', 'pointId', 'pointMax']);
      return Object.entries(c).filter(([k, v]) => typeof v !== 'object' && v !== null && v !== '' && !noise.has(k));
    },
    get switchRows() {
      const s = (this.net && this.net.switches) || {};
      const src = (s.result && typeof s.result === 'object') ? (s.result.commSetPara || s.result) : s;
      const noise = new Set(['opt', 'result', 'reason', 'code', 'message']);
      return Object.entries(src || {}).filter(([k, v]) => typeof v !== 'object' && !noise.has(k));
    },

    val(v) { return (v === null || v === undefined || v === '') ? '–' : v; },
    onoff(v) { return this.statusOk(v) ? 'on' : (v === 0 || v === '0' || v === false ? 'off' : this.val(v)); },

    // ── Topology diagram + ping ──────────────────────────────────────────
    get topo() { return (this.net && this.net.topology) || {}; },

    // Uplinks to the FranklinWH cloud — which physical link is ACTIVE (carrying traffic),
    // which are merely available (switch on), which are off. + signal where reported.
    get links() {
      const c = this.net && this.net.connectivity;
      const s = (this.net && this.net.switches) || {};
      const sw = (s.result && typeof s.result === 'object') ? (s.result.commSetPara || s.result) : s;
      const mk = (name, connKey, swKeys, sigKey) => {
        const conn = this.statusOk(this.dig(c, connKey));
        const avail = swKeys.some((k) => this.statusOk(sw[k]));
        return { name, state: conn ? 'active' : (avail ? 'available' : 'off'),
                 signal: sigKey ? this.dig(c, sigKey) : null };
      };
      return [
        mk('WiFi', 'wifiConnectRouterStatus', ['wifiNetSwitch'], 'WifiSignalStrength'),
        mk('Ethernet', 'EthConnectRouterStatus', ['ethernet0NetSwitch', 'ethernet1NetSwitch'], null),
        mk('4G', '4GConnectBSStatus', ['4GNetSwitch'], '4GSignalStrength'),
      ];
    },
    linkColor(state) { return state === 'active' ? '#34d399' : (state === 'available' ? '#60a5fa' : '#64748b'); },

    // Cloud-CLI-parity interface model: enabled / link / active (carrying) / available
    // (would carry if the active one stopped) / signal — with the reliable-vs-self-report
    // cloud distinction (317 authoritative, 339 self-report has been seen contradicting reality).
    get diag() {
      const c = (this.net && this.net.connectivity) || {};
      const ifc = (this.net && this.net.interfaces) || {};
      const s = (this.net && this.net.switches) || {};
      const sw = (s.result && typeof s.result === 'object') ? (s.result.commSetPara || s.result) : (s || {});
      const g = (k) => this.dig(c, k);
      const ok = (v) => this.statusOk(v);
      const specs = [
        { name: 'eth0', en: ['ethernet0NetSwitch'], link: 'EthConnectRouterStatus', o: ifc.eth0, sig: null, unit: '' },
        { name: 'eth1', en: ['ethernet1NetSwitch'], link: 'EthConnectRouterStatus', o: ifc.eth1, sig: null, unit: '' },
        { name: 'WiFi', en: ['wifiNetSwitch'], link: 'wifiConnectRouterStatus', o: ifc.wifi, sig: g('WifiSignalStrength'), unit: '%' },
        { name: '4G', en: ['4GNetSwitch'], link: '4GConnectBSStatus', o: ifc.operator, sig: g('4GSignalStrength'), unit: '/52' },
      ];
      const rows = specs.map((r) => {
        const enabled = r.en.some((k) => ok(sw[k]));
        const link = ok(g(r.link));
        const ip = r.o && r.o.ip;
        const hasAddr = !!(ip && ip !== '0.0.0.0');
        // 4G holds no IP while idle + SIM status isn't exposed locally → enabled ≈ available.
        const available = r.name === '4G' ? enabled : (enabled && (link || hasAddr));
        return { name: r.name, enabled, link, active: link, available,
                 ip: hasAddr ? ip : null, mac: (r.o && r.o.mac) || null,
                 dhcp: r.o ? r.o.dhcp : null, signal: r.sig, unit: r.unit };
      });
      const carrying = rows.filter((x) => x.active).map((x) => x.name);
      const available = rows.filter((x) => x.available).map((x) => x.name);
      return {
        rows, carrying, available, redundant: available.length > 1,
        fallback: available.filter((n) => !carrying.includes(n)),
        awsReliable: ok(ifc.awsStatus),        // 317 — authoritative
        awsSelfReport: ok(g('awsStatus')),     // 339 — self-report, unreliable
        routerRaw: g('routerStatus'),
      };
    },
    sigText(r) { return r.signal == null ? '–' : (r.signal + r.unit); },
    exportJson() {
      try {
        const blob = new Blob([JSON.stringify(this.net, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'fwh-network.json'; a.click();
        URL.revokeObjectURL(url);
      } catch (e) { this.$store.app.toast('Export failed: ' + e.message, 'error'); }
    },
    edgeColor(ok) { return ok === true ? '#34d399' : (ok === false ? '#ef4444' : '#475569'); },
    linkLabel(l) { return { wifi: 'WiFi', eth: 'Ethernet', '4g': '4G' }[l] || '—'; },

    // Home Assistant node in the topology diagram. HA gets aGate entities via MQTT discovery
    // (broker → HA) and receives notifications/service calls over REST (bridge → HA).
    haTitle() {
      const h = this.topo && this.topo.home_assistant;
      if (!h || !h.configured) return "Home Assistant — not linked (add an HA instance in Settings)";
      const names = (h.instances || []).map((i) => i.name || i.host).filter(Boolean).join(", ");
      const ent = (h.published_entities != null) ? (h.published_entities + " published") : "discovery";
      return "Home Assistant · " + h.count + " instance" + (h.count === 1 ? "" : "s")
        + (names ? " · " + names : "")
        + " · " + ent + " " + (h.via_mqtt ? "via MQTT discovery" : "(MQTT publishing off)") + " + REST notify/actions";
    },
    haSub() {
      const h = this.topo && this.topo.home_assistant;
      if (!h || !h.configured) return "not linked";
      const first = (h.instances && h.instances[0]) || {};
      const host = (first.host || "linked") + (h.count > 1 ? (" +" + (h.count - 1)) : "");
      return (h.exposed_entities != null ? (h.exposed_entities + " entities \u00b7 ") : "") + host;
    },
    fmtUptime(s) {
      if (s == null) return '–';
      s = Math.floor(s);
      const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
      if (d) return `${d}d ${h}h`;
      if (h) return `${h}h ${m}m`;
      return `${m}m ${s % 60}s`;
    },
    async runPing() {
      this.pinging = true;
      try {
        this.pingResult = await (await fetch('api/network/ping?count=5' + this.$store.app.gwQuery('&'))).json();
      } catch (e) {
        this.$store.app.toast('Ping failed: ' + e.message, 'error');
      } finally { this.pinging = false; }
    },

    // Live "watch": one round-trip every ~6s → rolling latency sparkline; refresh PoP every 5th.
    toggleWatch() {
      this.watching = !this.watching;
      if (this.watching) { this.latHistory = []; this.watchTick = 0; this._watchLoop(); }
    },
    async _watchLoop() {
      while (this.watching) {
        // Pause polling while the tab isn't visible, but keep the watch armed.
        if (this.$store.app.activeTab === 'network' && !document.hidden) {
          try {
            const r = await (await fetch('api/network/ping?count=1' + this.$store.app.gwQuery('&'))).json();
            this.latHistory.push(r.samples ? r.samples[0] : null);
            if (this.latHistory.length > 60) this.latHistory.shift();
            if (++this.watchTick % 5 === 0) { try { this.pop = await (await fetch('api/cloud/pop')).json(); } catch (e) { /* opt */ } }
          } catch (e) { this.latHistory.push(null); }
        }
        for (let i = 0; i < 12 && this.watching; i++) await new Promise((res) => setTimeout(res, 500));
      }
    },
    get watchMax() { const v = this.latHistory.filter((x) => x != null); return v.length ? Math.max(...v) : 1; },
    get watchLast() { for (let i = this.latHistory.length - 1; i >= 0; i--) if (this.latHistory[i] != null) return this.latHistory[i]; return null; },
    get watchAvg() { const v = this.latHistory.filter((x) => x != null); return v.length ? Math.round(v.reduce((a, b) => a + b, 0) / v.length) : null; },
  };
}
