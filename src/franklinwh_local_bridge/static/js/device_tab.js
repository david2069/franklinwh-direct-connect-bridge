/**
 * FranklinWH Local Bridge — Device tab
 * A labelled + grouped + exportable field viewer over the full /api/cmd/<name> read
 * surface (FWHAI `schema --live` style). Each endpoint is self-describing BEFORE you
 * click (name + catalog description from /api/catalog). On click it GETs one live read
 * and renders the reply grouped by the ported field schema (/api/schema): each row is
 *   label · unit-aware value · raw key (mono)
 * with a Raw-JSON toggle and per-endpoint JSON/CSV export. Nothing is polled — reads
 * fire on click only (grid_profile / wifi_scan are slow). Labelling/formatting live in
 * $store.app (fieldLabel / fieldGroup / fmtField) so this tab and Live Points can't drift.
 */
function deviceTab() {
  return {
    // ── Raw cmdType console ────────────────────────────────────────────────
    // Sends one arbitrary cmdType and shows the request and the RAW reply
    // side by side. Deliberately unprocessed: a decoded view hides exactly the
    // detail you open a console to look at.
    conOpen: false,
    conCmd: 1405,
    conJson: '{\n  "opt": 0\n}',
    conBusy: false,
    conResult: null,
    conError: '',
    conCatalog: [],

    async conInit() {
      if (this.conCatalog.length) return;
      try {
        const r = await fetch('api/raw/catalog');
        this.conCatalog = (await r.json()).commands || [];
      } catch { /* autocomplete is a nicety; the console works without it */ }
    },

    toggleConsole() {
      this.conOpen = !this.conOpen;
      if (this.conOpen) this.conInit();
    },

    get conInfo() {
      return this.conCatalog.find(c => c.cmd === Number(this.conCmd)) || null;
    },

    /** Called when the cmdType changes: load its real read payload, so a command
     *  with an unusual read (1725 opt:1, 1705 needs an id) works first time. */
    conSync() {
      this.conResult = null;
      const p = this.conInfo && this.conInfo.read_payload;
      if (p) this.conJson = JSON.stringify(p, null, 2);
    },

    /** Read vs write is PER COMMAND, not "opt === 0".
     *
     *  `opt` is an operation SELECTOR, not a global read/write flag. The
     *  0=read / 1=write convention holds for most commands but is not a rule:
     *  1725 reads with opt:1, and 1727 acts on opt:3. So compare against the
     *  command's own read opt, which is what the server-side gate does too. */
    get conIsWrite() {
      let sent;
      try { sent = JSON.parse(this.conJson) || {}; } catch { return false; }
      const info = this.conInfo;
      const readOpt = info && info.read_payload ? info.read_payload.opt : 0;
      return sent.opt !== readOpt;
    },

    /** Label for the badge: says READ when this payload matches the read opt. */
    get conKind() {
      return this.conIsWrite ? 'write' : 'read';
    },

    /** 'read' uses the catalog's real read payload — 1725 answers ONLY opt:1, and
     *  opt:0 draws no reply at all, which is what made the console appear to hang. */
    /** Any edit to the payload or cmdType invalidates the displayed result.
     *  Otherwise the "Request sent" panel keeps showing an EARLIER frame while the
     *  editor shows something else — which is precisely the kind of false
     *  provenance this console exists to eliminate. */
    conInvalidate() { this.conResult = null; this.conError = ''; },

    conPreset(kind) {
      this.conInvalidate();
      if (kind === 'read') {
        const p = (this.conInfo && this.conInfo.read_payload) || { opt: 0 };
        this.conJson = JSON.stringify(p, null, 2);
      }
      if (kind === 'write') this.conJson = '{\n  "opt": 1\n}';
      if (kind === 'id') this.conJson = '{\n  "opt": 0,\n  "id": 1\n}';
      if (kind === 'noopt') this.conJson = '{}';
    },

    /** Warn when the payload's opt is not the one this command answers to. */
    get conOptMismatch() {
      const info = this.conInfo;
      if (!info || !info.read_payload) return '';
      let sent;
      try { sent = JSON.parse(this.conJson); } catch { return ''; }
      const want = info.read_payload.opt;
      if (sent.opt === undefined) return `${this.conCmd} requires an opt field.`;
      if (sent.opt === want) return '';
      if (sent.opt === 1 && want === 0) return '';      // an ordinary write
      return `${this.conCmd} reads with opt:${want}. opt:${sent.opt} may draw no reply.`;
    },

    async conSend(confirm = false) {
      let data;
      try { data = JSON.parse(this.conJson); }
      catch (e) { this.conError = `dataArea is not valid JSON: ${e.message}`; return; }
      this.conBusy = true; this.conError = ''; this.conResult = null;
      try {
        const r = await fetch('api/raw' + this.$store.app.gwQuery(), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cmd: Number(this.conCmd), data, confirm }),
        });
        const out = await r.json();
        if (r.status === 428) {                       // write needs confirmation
          const ok = await this.$store.app.confirmDialog(
            out.detail + '\n\nSend it?',
            { title: `Write to cmdType ${this.conCmd}?`, danger: true });
          this.conBusy = false;
          if (ok) return this.conSend(true);
          return;
        }
        if (!r.ok) throw new Error(out.detail || r.statusText);
        this.conResult = out;
      } catch (e) {
        this.conError = e.message;
      } finally { this.conBusy = false; }
    },

    get conRequestJson() {
      return this.conResult ? JSON.stringify(this.conResult.request, null, 2) : '';
    },
    get conResponseJson() {
      return this.conResult ? JSON.stringify(this.conResult.response, null, 2) : '';
    },
    conCopy() {
      navigator.clipboard?.writeText(
        JSON.stringify({ request: this.conResult.request,
                         response: this.conResult.response }, null, 2));
      this.$store.app.toast('Copied request + response', 'success');
    },

    results: {},   // name -> parsed JSON (or {error})
    loading: {},   // name -> bool
    rawOpen: {},   // name -> bool (Raw JSON toggle)
    selected: '',  // master-detail: the endpoint shown in the right-hand panel
    //: name -> the frame the bridge ACTUALLY sent, from the X-FWH-Request header.
    //  Shown beside each reading so the request never has to be taken on trust.
    sentFrames: {},
    navCollapsed: {},   // left-nav group title -> collapsed?

    toggleNav(title) { this.navCollapsed[title] = !this.navCollapsed[title]; },
    collapseAllNav() { const c = {}; for (const g of this.endpointGroups) c[g.title] = true; this.navCollapsed = c; },
    expandAllNav() { this.navCollapsed = {}; },
    get allNavCollapsed() { return this.endpointGroups.every(g => this.navCollapsed[g.title]); },

    // Endpoint groups (each item name maps to GET /api/cmd/<name>). Descriptions come
    // from the catalog at render time, so the list is self-explanatory before clicking.
    endpointGroups: [
      { title: 'Live & Status',
        items: ['power_flow', 'relay_status', 'ibg_run_status', 'ibg_state'] },
      { title: 'Battery',
        items: ['battery_modules', 'battery_inhibit', 'mode_soc'] },
      { title: 'Energy & Circuits',
        items: ['solar_pv', 'generator', 'smart_circuits', 'smart_circuit_meter'] },
      { title: 'Modes & TOU',
        items: ['mode_config', 'mode_list', 'tou_schedule', 'offgrid'] },
      { title: 'Grid compliance',
        items: ['grid_policy', 'der_comms',
                { name: 'grid_profile', slow: true }] },
      { title: 'Device & Network',
        items: ['device_info', 'install_profile', 'time_location',
                { name: 'connectivity', slow: true },   // router/net/AWS probe — ~6s
                'network_interfaces', 'network_switches', 'wifi_config', 'cloud_config',
                'event_block', 'firmware'] },
    ],

    // Curated set pulled by "Export snapshot" (at least power_flow).
    snapshotSet: ['power_flow', 'relay_status', 'ibg_run_status', 'mode_config',
                  'mode_list', 'battery_modules'],

    get app() { return Alpine.store('app'); },

    // Normalise an item (string or {name, ...}) to a plain name.
    itemName(it) { return typeof it === 'string' ? it : it.name; },
    isSlow(it)   { return typeof it === 'object' && it.slow; },

    // Catalog description for an endpoint (empty string if unknown / not loaded yet).
    desc(name) {
      const c = this.app.catalog[name];
      return c ? c.description : '';
    },
    isWrite(name) {
      const c = this.app.catalog[name];
      return !!(c && c.write);
    },

    // Master-detail: show an endpoint in the right panel, fetching it on first view.
    select(name) {
      this.selected = name;
      if (!this.hasResult(name)) this.fetchCmd(name);
      this.conFromSelection(name);
    },

    /** Honour a request from elsewhere in the UI (e.g. Health's firmware card). */
    watchDeviceReadRequest() {
      this.$watch('$store.app.deviceReadRequest', (name) => {
        if (!name) return;
        this.select(name);
        this.$store.app.deviceReadRequest = '';
      });
    },

    /** The literal frame sent for a reading: {cmdType, dataArea}. */
    sentFrame(name) { return this.sentFrames[name] || null; },
    sentFrameText(name) {
      const f = this.sentFrame(name);
      return f ? `${f.cmdType} · ${JSON.stringify(f.dataArea)}` : '';
    },

    /** Point the console at whatever is selected below, pre-filled with the payload
     *  that command actually reads with — so 1725 arrives as opt:1, not opt:0. */
    async conFromSelection(name) {
      await this.conInit();
      const entry = this.conCatalog.find(c => c.name === name);
      if (!entry) return;
      this.conCmd = entry.cmd;
      this.conJson = JSON.stringify(entry.read_payload || { opt: 0 }, null, 2);
      this.conResult = null;
      this.conError = '';
    },

    async fetchCmd(name) {
      this.loading[name] = true;
      // Abort a hung read after 35s (grid_profile/connectivity are slow but bounded).
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 35000);
      // The bridge returns the frame it actually sent in X-FWH-Request; show it
      // rather than asking anyone to trust a reconstruction.
      try {
        // Scope the read to the selected gateway (multi-gateway); '' when single-gateway.
        const r = await fetch('api/cmd/' + name + this.app.gwQuery('?'), { signal: ctrl.signal });
        const sent = r.headers.get('X-FWH-Request');
        if (sent) { try { this.sentFrames[name] = JSON.parse(sent); } catch { /* ignore */ } }
        this.results[name] = r.ok
          ? await r.json()
          : { error: `HTTP ${r.status} — ${(await r.text()) || 'request rejected'}` };
      } catch (e) {
        // Network-level failure (bridge restarting, device slow/offline) surfaces in Safari
        // as "TypeError: Load failed" — translate to something actionable + a Retry button.
        this.results[name] = {
          error: e && e.name === 'AbortError'
            ? 'Timed out after 35s — the device did not respond. Retry.'
            : 'Request failed — the bridge may be restarting or the device is slow/offline. Retry.',
        };
      } finally {
        clearTimeout(timer);
        this.loading[name] = false;
      }
    },

    // Group + label a response for rendering. Envelope fields (opt/result/reason) are
    // dropped. Returns [{ title, rows: [{ label, value, raw }] }], 'Other' group last.
    // Recursively flatten a reply into readable sections. Nested objects (grid_profile ->
    // grid_policy / compliance_sections -> grid_ov_trip ...) become their own breadcrumb
    // section instead of a squished, truncated JSON string — so NOTHING is hidden. Top-level
    // scalar leaves are grouped by the field schema; nested leaves sit under their path.
    grouped(name) {
      const d = this.results[name];
      if (!d || typeof d !== 'object' || Array.isArray(d)) return [];
      const skip = new Set(['opt', 'result', 'reason']);
      const nice = { list: 'Modes', devMap: 'Battery modules' };
      const out = [];
      const isPlainObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
      const isObjArray = (v) => Array.isArray(v) && v.length && v.every(isPlainObj);

      const walk = (obj, path, topLevel) => {
        const rows = [];        // leaf rows at this level
        const deferred = [];    // [{title, obj}] nested sections, rendered after this level
        for (const [k, v] of Object.entries(obj)) {
          if (skip.has(k)) continue;
          const label = nice[k] || this.app.fieldLabel(k);
          const crumb = path ? `${path} › ${label}` : label;
          if (isPlainObj(v)) {
            deferred.push({ title: crumb, obj: v });
          } else if (isObjArray(v)) {
            v.forEach((el, i) => deferred.push({ title: `${crumb} [${i}]`, obj: el }));
          } else {
            for (const r of this.app.expandRows(k, v)) rows.push(r);
          }
        }
        if (topLevel) {
          // Group top-level scalar leaves by their schema group (Battery, Grid, ...).
          const byGroup = {};
          rows.forEach((r) => (byGroup[r.group] ||= []).push(r));
          Object.keys(byGroup)
            .sort((a, b) => (a === 'Other') - (b === 'Other') || a.localeCompare(b))
            .forEach((g) => out.push({ title: g, rows: byGroup[g].map(this._toRow) }));
        } else if (rows.length) {
          out.push({ title: path, rows: rows.map(this._toRow), nested: true });
        }
        deferred.forEach((dd) => walk(dd.obj, dd.title, false));
      };
      walk(d, '', true);
      return out;
    },

    _toRow(r) { return { label: r.label, value: r.value, raw: r.key }; },

    hasResult(name) { return this.results[name] !== undefined; },
    isError(name)   { const d = this.results[name]; return !!(d && d.error); },
    // A successful read that produced no renderable rows (rare) — so the panel can say so
    // instead of showing blank. Carries result/reason for the "why" the user asked about.
    isEmpty(name) {
      return this.hasResult(name) && !this.isError(name) && this.grouped(name).length === 0;
    },
    envelope(name) {
      const d = this.results[name] || {};
      return `result=${d.result}${d.reason !== undefined ? ' reason=' + d.reason : ''}`;
    },

    toggleRaw(name) { this.rawOpen[name] = !this.rawOpen[name]; },

    pretty(v) {
      try { return JSON.stringify(v, null, 2); }
      catch (e) { return String(v); }
    },

    // ── Client-side export (Blob; no backend) ──────────────────────────────
    _download(filename, text, mime) {
      const blob = new Blob([text], { type: mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },

    exportJson(name) {
      this._download(`fwh-${name}-${Date.now()}.json`,
                     this.pretty(this.results[name]), 'application/json');
    },

    // CSV of the labelled table (group,label,raw_key,value) — tabular for any response.
    exportCsv(name) {
      const esc = (s) => `"${String(s).replace(/"/g, '""')}"`;
      const rows = ['group,label,raw_key,value'];
      for (const g of this.grouped(name)) {
        for (const r of g.rows) {
          rows.push([g.title, r.label, r.raw, r.value].map(esc).join(','));
        }
      }
      this._download(`fwh-${name}-${Date.now()}.csv`, rows.join('\n'), 'text/csv');
    },

    // Fetch a curated set (incl. power_flow) and download a combined JSON snapshot.
    async exportSnapshot() {
      const snap = {};
      for (const n of this.snapshotSet) {
        try {
          const r = await fetch('api/cmd/' + n + this.app.gwQuery('?'));
          snap[n] = r.ok ? await r.json() : { error: r.status };
        } catch (e) {
          snap[n] = { error: String(e) };
        }
      }
      this._download(`fwh-snapshot-${Date.now()}.json`, this.pretty(snap),
                     'application/json');
    },
  };
}
