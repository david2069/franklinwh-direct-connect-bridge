/**
 * FranklinWH Local Bridge — Network tab.
 * On-LAN network diagnostics for the selected aGate (GET /api/network): the
 * router→internet→cloud connectivity chain (1113), bridge-side reachability the cloud can't
 * see (ping/:9000/:502), interfaces + signal (1118), interface switches (1119), and the
 * AWS-IoT endpoint/region (1121, credentials redacted server-side).
 */
function networkTab() {
  // The Leaflet map stays out of the reactive data: Alpine's proxy breaks Leaflet objects.
  let leafletP = null, map = null, layer = null;
  return {
    net: null,
    loading: false,
    pingResult: null,
    pinging: false,
    pop: null,
    // CloudFront edge period (Today / 7 days / 30 days / All kept) — the tables and the map.
    popPeriod: '30d',
    // PoP map dialog (Leaflet, vendored; online tiles). Offline = the tiles or Leaflet
    // couldn't load: the dialog says so and the tables still work.
    mapOpen: false,
    mapOffline: false,
    mapTransOpen: true,
    // Watch: one ping every ~6s into a rolling latency sparkline (toggleWatch).
    watching: false,
    latHistory: [],
    watchTick: 0,

    init() {
      // Loads on first SHOW, not on page load — see lazyTab(). load() pulls the link
      // history in too, so the card arrives with the probes rather than separately.
      const t = lazyTab(this, 'network', () => this.load());
      this.$watch('$store.app.selectedGateway', () => t.reload());
      // The history is a local DB read, not a device probe, so it can refresh on a
      // timer — but only while the tab is on screen.
      setInterval(() => { if (this.$store.app.activeTab === 'network') this.loadLink(); }, 15000);
    },

    // When the probes last actually ran. A panel of numbers with nothing saying when
    // they were read cannot be told apart from the same panel five minutes stale —
    // which is why pressing the button looked like it did nothing.
    ranAt: null,
    ranMs: null,

    error: '',

    async loadPop() {
      try {
        const pr = await this.$store.app.fetchTimeout('api/cloud/pop?period=' + this.popPeriod, 10000);
        this.pop = await pr.json();
        if (this.mapOpen) this.drawMap();
      } catch (e) { /* optional */ }
    },

    setPopPeriod(p) { this.popPeriod = p; this.loadPop(); },

    // "1.5m", "3.2h", "2.1d": how long the edge stayed on a PoP.
    stayText(s) {
      if (s == null) return '—';
      if (s < 3600) return (s / 60).toFixed(1) + 'm';
      if (s < 86400) return (s / 3600).toFixed(1) + 'h';
      return (s / 86400).toFixed(1) + 'd';
    },

    // Errors & retries rows: each library error category, then refreshes / retries / logins.
    errorRows() {
      const a = (this.pop && this.pop.api) || null;
      if (!a) return [];
      const rows = Object.entries(a.errors_by_type || {}).map(([k, v]) => ({ k, label: k, n: v, err: true }));
      rows.push({ k: 'refresh', label: 'Token refreshes', n: a.token_refresh_count, err: false });
      rows.push({ k: 'retry', label: 'Retries (401 → refresh)', n: a.retry_count, err: false });
      rows.push({ k: 'login', label: 'Logins', n: a.login_count, err: false });
      return rows;
    },

    homePop() {
      const d = (this.pop && this.pop.distribution) || {};
      return Object.keys(d)[0] || null;        // distribution is sorted, most requests first
    },

    // Leaflet is loaded on first use only (it's ~150 kB), from the bridge itself.
    _ensureLeaflet() {
      if (window.L) return Promise.resolve(window.L);
      if (leafletP) return leafletP;
      leafletP = new Promise((resolve, reject) => {
        const css = document.createElement('link');
        css.rel = 'stylesheet'; css.href = 'static/css/leaflet-1.9.4.css';
        document.head.appendChild(css);
        const s = document.createElement('script');
        s.src = 'static/js/leaflet-1.9.4.min.js';
        s.onload = () => resolve(window.L);
        s.onerror = () => { leafletP = null; reject(new Error('Leaflet did not load')); };
        document.head.appendChild(s);
      });
      return leafletP;
    },

    async openMap() {
      this.mapOpen = true;
      this.mapTransOpen = window.innerWidth >= 640;     // folded on a phone: the map first
      this.mapOffline = false;
      await this.$nextTick();
      try {
        const L = await this._ensureLeaflet();
        const el = document.getElementById('pop-map');
        if (!map) {
          map = L.map(el, { worldCopyJump: true }).setView([0, 150], 2);
          const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 8,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          });
          let bad = 0;
          tiles.on('tileerror', () => { if (++bad >= 4) this.mapOffline = true; });
          tiles.on('tileload', () => { bad = 0; this.mapOffline = false; });
          tiles.addTo(map);
        }
        setTimeout(() => map && map.invalidateSize(), 50);
        this.drawMap();
      } catch (e) {
        this.mapOffline = true;
      }
    },

    closeMap() { this.mapOpen = false; },

    drawMap() {
      const L = window.L;
      if (!L || !map || !this.pop) return;
      if (layer) layer.remove();
      layer = L.layerGroup().addTo(map);
      const dist = this.pop.distribution || {};
      const locs = this.pop.locations || {};
      const max = Math.max(1, ...Object.values(dist));
      const home = this.homePop();
      const pts = [];
      for (const [pp, n] of Object.entries(dist)) {
        const g = locs[pp];
        if (!g) continue;                       // unknown code: in the table, not on the map
        const isHome = pp === home;
        L.circleMarker([g.lat, g.lon], {
          radius: 6 + 22 * Math.sqrt(n / max),
          color: isHome ? '#f59e0b' : '#3b82f6', weight: 2,
          fillColor: isHome ? '#f59e0b' : '#3b82f6', fillOpacity: isHome ? 0.45 : 0.35,
        }).bindTooltip(pp + ' · ' + g.city + ' · ' + n + ' requests' + (isHome ? ' · home' : ''))
          .addTo(layer);
        pts.push([g.lat, g.lon]);
      }
      if (pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 5 });
    },

    async load() {
      this.loading = true;
      this.error = '';
      const t0 = Date.now();
      try {
        // Generous, because this probe is genuinely slow — an aGate session plus
        // ping, :502 and four reads. But BOUNDED: with no timeout the button sat on
        // "Probing…" indefinitely, and the tab gave no way to tell slow from hung.
        const r = await this.$store.app.fetchTimeout(
          'api/network' + this.$store.app.gwQuery('?'), 45000);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        this.net = await r.json();
        await this.loadPop();
        this.ranAt = Date.now();
        this.ranMs = this.ranAt - t0;
      } catch (e) {
        // fetchErrorText arrived on main with #19; use it rather than keeping a
        // second copy of the same browser-error translation.
        this.error = fetchErrorText(e, 'api/network');
        this.$store.app.toast('Network probe failed: ' + this.error, 'error');
      } finally { this.loading = false; }
      this.loadLink();                   // the probes just ran, pass or fail
    },

    // ── link history (RUNTIME_DESIGN §6.9) ────────────────────────────────
    // The topology above draws the links; this says how each has BEHAVED. Only the
    // legs the poll cycle actually measures are here — the rest are named as gaps by
    // the endpoint rather than quietly omitted.
    link: null,
    linkError: '',
    openLeg: null,

    async loadLink() {
      try {
        const url = 'api/health/link' + this.$store.app.gwQuery();
        const r = await fetch(url);
        if (!r.ok) throw new Error(r.statusText);
        this.link = await r.json();
        this.linkError = '';
      } catch (e) {
        const m = (e && e.message) || String(e);
        this.linkError = /load failed|failed to fetch|networkerror/i.test(m)
          ? 'could not reach api/health/link — the request never completed'
          : 'api/health/link: ' + m;
      }
    },

    /** A duration in words. '4920 s' is a number; '1h 22m' is an answer. */
    dur(s) {
      if (s == null) return '--';
      s = Math.max(0, Math.round(s));
      if (s < 60) return s + 's';
      if (s < 3600) return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
      if (s < 86400) return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
      return Math.floor(s / 86400) + 'd ' + Math.floor((s % 86400) / 3600) + 'h';
    },
    when(ts) { return ts ? new Date(ts * 1000).toLocaleString() : 'never'; },

    ranText() {
      if (!this.ranAt) return '';
      const age = Math.round((Date.now() - this.ranAt) / 1000);
      const when = age < 60 ? (age < 5 ? 'just now' : age + 's ago')
                            : new Date(this.ranAt).toLocaleTimeString();
      return `probed ${when} · took ${(this.ranMs / 1000).toFixed(1)}s`;
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
      // A field the aGate didn't send is not evidence that a link is off (#302).
      const mk = (name, connKey, swKeys, sigKey) => {
        const conn = this.tri([this.dig(c, connKey)]);
        const avail = this.tri(swKeys.map((k) => sw[k]));
        return { name, state: conn ? 'active' : (avail ? 'available'
                 : (conn === null && avail === null ? 'not reported' : 'off')),
                 signal: sigKey ? this.dig(c, sigKey) : null };
      };
      return [
        mk('WiFi', 'wifiConnectRouterStatus', ['wifiNetSwitch'], 'WifiSignalStrength'),
        mk('Ethernet', 'EthConnectRouterStatus', ['ethernet0NetSwitch', 'ethernet1NetSwitch'], null),
        mk('4G', '4GConnectBSStatus', ['4GNetSwitch'], '4GSignalStrength'),
      ];
    },
    linkColor(state) { return state === 'active' ? '#34d399' : (state === 'available' ? '#60a5fa' : '#64748b'); },
    yesNo(v, yes, no) { return v === null ? 'not reported' : (v ? yes : no); },

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
      // enabled / link are true, false, or null = not reported (#302).
      const rows = specs.map((r) => {
        const enabled = this.tri(r.en.map((k) => sw[k]));
        const link = this.tri([g(r.link)]);
        const ip = r.o && r.o.ip;
        const hasAddr = !!(ip && ip !== '0.0.0.0');
        // 4G holds no IP while idle + SIM status isn't exposed locally → enabled ≈ available.
        const available = r.name === '4G' ? enabled === true : (enabled === true && (link === true || hasAddr));
        return { name: r.name, enabled, link, active: link === true, available,
                 reported: enabled !== null || link !== null || hasAddr,
                 ip: hasAddr ? ip : null, mac: (r.o && r.o.mac) || null,
                 dhcp: r.o ? r.o.dhcp : null, signal: r.sig, unit: r.unit };
      });
      const carrying = rows.filter((x) => x.active).map((x) => x.name);
      const available = rows.filter((x) => x.available).map((x) => x.name);
      return {
        rows, carrying, available, redundant: available.length > 1,
        reported: rows.some((x) => x.reported),
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
    // :502 from the last REAL result, judged by the server against the link's uptime (#617):
    // 'up' green, 'down' red, 'unknown' grey + dashed, null not probed. Never probed (#221).
    mb502Color(p) {
      const s = p && p.modbus_502_state;
      return this.edgeColor(s === 'up' ? true : (s === 'down' ? false : null));
    },
    mb502Dash(p) { return (p && p.modbus_502_state === 'unknown') ? '4 3' : ''; },
    mb502Label(p) {
      const s = p && p.modbus_502_state;
      if (s === 'up') return 'open';
      if (s === 'down') return 'closed';
      if (s !== 'unknown') return 'not probed';
      if (!p.modbus_502_at) return 'unknown';
      const hm = new Date(p.modbus_502_at * 1000)
        .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
      return 'unknown · last ' + (p.modbus_502 ? 'OK ' : 'failed ') + hm;
    },
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
            if (++this.watchTick % 5 === 0) { await this.loadPop(); }
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
