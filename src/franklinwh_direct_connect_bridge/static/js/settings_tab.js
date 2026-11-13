/**
 * FranklinWH Local Bridge — Settings tab.
 * Fetches the effective (masked) config from GET /api/settings and displays it. Most
 * settings come from env / add-on options and take effect on restart (read-only here).
 * A small whitelist — allow_writes / log_level / ha_notify — is live-editable and PUT
 * back to /api/settings, where it applies immediately and persists to DATA_DIR (P7).
 */
function settingsTab() {
  return {
    support: null, supportText: '', supportBusy: false, supportCopied: '',
    apowerSpecs: [], apowerModel: '', apowerCount: 1,
    haPriceOpts: [],   // {id:'ha:<inst>:<eid>', label:friendly, group:instance}
    haEventOpts: [],   // on/off HA entities for the price events (#582)
    priceSrc: 'off',   // the price signal's source: off | nem | ha (#582)
    cfg: { connection: {}, mqtt: {}, control: {}, notifications: {},
           metrics: {}, environment: {} },
    // Live-editable mirror of the whitelisted fields (bound to the inputs).
    // What the gateway says the PV array is (1903 solar_pv). Null when it could not be
    // read — which is NOT the same as "no solar", so the hint simply does not appear.
    derivedPvKwp: null,

    form: { allow_writes: false, log_level: 'info', ha_notify: true, ha_url: '', ha_token: '',
            fwh_cloud_email: '', fwh_cloud_password: '', fwh_cloud_gateway: '',
            pv_latitude: '', pv_longitude: '', pv_kwp: '', pv_tilt: '', pv_azimuth: '',
            nem_region: '', tariff_price_entity: '', tariff_feedin_entity: '',
            price_spike_c: '', price_spike_entity: '', demand_window_entity: '' },
    nemSpot: null,   // {region, spot:{price_c_kwh,...}, regions[]} — AEMO NEM wholesale
    cloudTesting: false,
    cloudResult: null,
    logLevels: ['trace', 'debug', 'info', 'notice', 'warning', 'error', 'fatal'],
    testing: false,
    saving: false,

    // ── Gateways (DB-backed roster) ──
    gateways: [],
    // ── Sites + Meters ──
    sites: [], meters: [], siteEdit: null, meterEdit: null,
    utilities: [], tariffs: [], utilEdit: null, tariffEdit: null,
    tariffImp: { open: false, text: '', preview: null, msg: null, busy: false, done: false },
    // ── Automation constants (const.* sensors) ──
    constants: {}, constSpec: {}, constModes: [], constSaving: false,
    systemSetup: {}, systemSpec: {}, systemSaving: false, systemLoaded: {},
    systemFor: null,   // the gwQuery() the System Setup form was read for (#352)
    gwBusy: {},          // id -> true while a toggle/test is in flight
    gwAdd: null,         // add-form object when open, else null
    gwErr: '',

    // ── Notifications center (Energipay-style: instances + companion devices + broadcast) ──
    notif: {
      loaded: false, master: false, busy: false,
      instances: [], devices: [],
      addDev: null, addDevMsg: null,   // {kind: danger|warn|ok, text}: shown in the dialog
      instMsg: null,                   // the add-instance panel's result (#293)
      targets: null, discovered: [], pickerOpen: false, pickerSearch: '',
      addInst: null,
      testDlg: null,                   // the Send test target picker (#281)
      bc: null,
      rt: {},                          // device id -> {kind, text}: the test-with-buttons round trip
      checks: null, checksBusy: false, checksErr: '',   // the Notifications check (#464)
      ta: null,                        // the Test critical alert dialog: {steps, running, msg, run}
    },

    // ── Support info bundle (redacted; for GitHub issues) ────────────────────
    async loadApowerSpecs() {
      if (!this.$store.app.selectedGateway) return;   // no gateway yet: nothing to ask (#379)
      try {
        const d = await (await fetch('api/apower-specs' + this.$store.app.gwQuery())).json();
        this.apowerSpecs = d.models || [];
        if (d.apower_count) this.apowerCount = d.apower_count;
        if (d.apower_model && !this.apowerModel) this.apowerModel = d.apower_model;   // read (#496)
      } catch (e) { /* optional */ }
    },
    fillCapacityFromModel() {
      const m = this.apowerSpecs.find(x => x.model === this.apowerModel);
      if (!m || !this.apowerCount) return;
      this.constants.battery_capacity_kwh = Math.round(m.usable_kwh * this.apowerCount * 100) / 100;
      // also seed the max-power fallback from the model (discharge kW × count is the pack rate)
      if (m.discharge_kw) this.constants.battery_max_power_kw = Math.round(m.discharge_kw * this.apowerCount * 10) / 10;
      this.toast && this.toast(`Capacity set to ${this.constants.battery_capacity_kwh} kWh (${this.apowerModel} × ${this.apowerCount})`, 'info');
    },
    async loadSupportInfo() {
      this.supportBusy = true; this.supportCopied = '';
      try {
        this.support = await (await fetch('api/support-info')).json();
        this.supportText = this._fmtSupport(this.support);
      } catch (e) { this.supportText = 'Failed to load support info: ' + (e.message || e); }
      finally { this.supportBusy = false; }
    },
    _fmtSupport(d) {
      if (!d) return '';
      const L = [];
      const m = d.meta || {};
      L.push('FranklinWH Direct Connect Bridge — support info (redacted)');
      L.push(`generated: ${new Date((m.generated_at||0)*1000).toISOString()}`);
      L.push(`version: ${m.software_version}  build: ${m.build}  platform: ${m.platform}`);
      const i = m.install || {};   // which installation this is (owner, 2026-11-11)
      if (i.install_id) L.push(`install: ${i.install_id} · ${i.install_type} · ${i.os} ${i.arch} · Python ${i.python}${i.home_assistant ? ' · HA ' + i.home_assistant : ''} · since ${i.install_date || '?'} (${i.first_version || '?'}) · now ${i.bridge_version}`);
      L.push(`installed: ${m.install_date||'?'}  last update: ${m.last_updated?new Date(m.last_updated*1000).toISOString().slice(0,10):'?'}  uptime: ${m.bridge_uptime_s!=null?Math.round(m.bridge_uptime_s)+'s':'?'}`);
      if ((m.updates||[]).length) L.push('updates: ' + m.updates.map(u => u.version+'@'+new Date(u.ts*1000).toISOString().slice(0,10)).join(', '));
      L.push('');
      (d.gateways||[]).forEach(g => {
        L.push(`gateway #${g.index}: ${g.model||'?'}${g.vendor_model?(' ('+g.vendor_model+')'):''}${g.is_mock?' [mock]':''}`);
        if (g.country||g.hardware_model_id!=null) L.push(`  hw_id ${g.hardware_model_id} · ${g.country||'?'} · aPowers ${g.apower_count??'?'}${(g.apower_models||[]).length?' ('+g.apower_models.join(', ')+')':''}`);
        if (g.grid) { const gr=g.grid; L.push(`  grid: service ${gr.service_amps??'?'}A · air-switch ${gr.air_switch_amps??'?'}A · import ${gr.import_limit_w===-1?'unlimited':gr.import_limit_w} · export ${gr.grid_export_enabled?'enabled':'disabled'} (${gr.export_limit_w===-1?'unlimited':gr.export_limit_w}) · pcs-discharge ${gr.pcs_discharge_enabled?'on':'off'} · inverter ${gr.inverter_max_charge_kw??'?'}/${gr.inverter_max_discharge_kw??'?'} kW`); }
        (g.install||[]).forEach(line => L.push('  ' + line));   // the install-profile card (#496)
        if (g.firmware) L.push('  firmware: ' + Object.entries(g.firmware).map(([k,v])=>k+'='+v).join(' '));
        if (g.smart_circuits!=null) L.push(`  smart circuits: ${g.smart_circuits}`);
        if (g.generator) L.push(`  generator: feature ${g.generator.enabled?'on':'off'} · ${g.generator.state||'?'} · reported model ${(g.generator.evidence&&g.generator.evidence.model)||'none'}`);
        if (g.operating_mode||g.soc_pct!=null) L.push(`  mode ${g.operating_mode||'?'} · SoC ${g.soc_pct!=null?Math.round(g.soc_pct)+'%':'?'} · run ${g.run_status||'?'} · vpp ${g.cloud_vpp}`);
        if (g.contacted_at) L.push(`  last contact: ${new Date(g.contacted_at*1000).toISOString()}`);
      });
      L.push('');
      const so = d.solar||{}; if (Object.keys(so).length) L.push('solar: ' + Object.entries(so).map(([k,v])=>k+'='+v).join(' '));
      const ss = d.system_setup||{}; if (Object.keys(ss).length) L.push('system setup: ' + Object.entries(ss).map(([k,v])=>k+'='+v).join(' '));
      const it = d.integration||{}; L.push('integration: ' + Object.entries(it).map(([k,v])=>k+'='+v).join(' '));
      const b = d.billing||{}; L.push('billing: ' + Object.entries(b).map(([k,v])=>k+'='+v).join(' '));
      if ((d.notifications||[]).length) {
        L.push('notifications check:');
        d.notifications.forEach(c => L.push(`  ${c.check}: ${c.status}${c.source?' · '+c.source:''}${c.detail?' · '+c.detail:''}`));
      }
      L.push('');
      L.push(m.note||'');
      return L.join('\n');
    },
    async copySupport() {
      if (!this.supportText) await this.loadSupportInfo();
      // The result shows next to the button (#327): 'Copied', or why it could not.
      this.supportCopied = await Alpine.store('app').copyText(this.supportText)
        ? 'Copied' : 'Copying is blocked here — select the text below and press Ctrl/Cmd+C';
      if (this.supportCopied === 'Copied') setTimeout(() => this.supportCopied = '', 2000);
    },
    _dl(name, text, type) {
      try {
        const blob = new Blob([text], { type }); const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = name; a.click();
        setTimeout(()=>URL.revokeObjectURL(url), 1000);
      } catch (e) { this.toast && this.toast('Download failed', 'error'); }
    },
    async downloadSupportJson() { if (!this.support) await this.loadSupportInfo(); this._dl('support-info.json', JSON.stringify(this.support, null, 2), 'application/json'); },
    async downloadSupportCsv() {
      if (!this.support) await this.loadSupportInfo();
      const rows = [['section','key','value']];
      const walk = (sec, obj) => { for (const [k,v] of Object.entries(obj||{})) {
        if (v && typeof v === 'object' && !Array.isArray(v)) walk(sec+'.'+k, v);
        else rows.push([sec, k, Array.isArray(v)?JSON.stringify(v):(v==null?'':String(v))]); } };
      walk('meta', this.support.meta); (this.support.gateways||[]).forEach((g,i)=>walk('gateway'+(i+1), g));
      walk('system_setup', this.support.system_setup); walk('integration', this.support.integration); walk('billing', this.support.billing);
      const csv = rows.map(r => r.map(c => '"'+String(c).replace(/"/g,'""')+'"').join(',')).join('\n');
      this._dl('support-info.csv', csv, 'text/csv');
    },

    init() {
      // System Setup is per gateway (#352): a switch drops the form until it's re-read,
      // now if Settings is on screen, else when it's next shown.
      // init() runs twice here (Alpine's own call and the template's x-init): watch once.
      let stale = false;
      if (!this._systemWatched) this.$watch('$store.app.selectedGateway', () => {
        this.systemFor = null;
        stale = this.$store.app.activeTab !== 'settings';
        if (!stale) this.loadSystemSetup();
      });
      if (!this._systemWatched) this.$watch('$store.app.activeTab', (tab) => {
        if (tab === 'settings' && stale) { stale = false; this.loadSystemSetup(); }
      });
      this._systemWatched = true;
      lazyTab(this, 'settings', async () => {
        await this.reload();
        await this.loadGateways();
        await this.loadSitesMeters();
        await this.loadUtilitiesTariffs();
        await this.loadConstants();
        await this.loadSystemSetup();
        await this.loadNotify();
      });
      // Refresh roster status periodically so "last poll"/ok stay live — but only while
      // the tab is on screen. This ticked every 15s forever, on every page, invisibly.
      setInterval(() => {
        if (this.$store.app.activeTab !== 'settings') return;
        this.loadGateways(); this.loadSitesMeters(); this.loadUtilitiesTariffs();
      }, 15000);
    },

    _gwTz: {},   // gateway id -> tz label (cached; each gateway may sit in a different zone)
    async loadGateways() {
      try {
        const r = await fetch('api/gateways');
        if (r.ok) { this.gateways = await r.json(); this._enrichGatewayTz(); }
      } catch (e) { /* leave last-known */ }
    },
    async _enrichGatewayTz() {
      for (const gw of this.gateways) {
        if (this._gwTz[gw.id] !== undefined) continue;   // cached (incl. null = unavailable)
        this._gwTz[gw.id] = null;                          // reserve so we fetch once
        try {
          const t = await (await fetch('api/site/timezone?gateway=' + encodeURIComponent(gw.id))).json();
          this._gwTz[gw.id] = (t && t.available) ? t.label : null;
        } catch (e) { /* leave null */ }
      }
    },

    // ── Settings sub-tabs (FEAT-SETTINGS-TABS) ──────────────────────────────
    subTabs: [
      { key: 'setup', label: 'Setup' },
      { key: 'general', label: 'General' },
      { key: 'gateways', label: 'Gateways' },
      { key: 'automation', label: 'Automation' },
      { key: 'billing', label: 'Sites & Billing' },
      { key: 'integrations', label: 'Integrations' },
      { key: 'admin', label: 'Admin' },
    ],
    sub: (function () { try { return localStorage.getItem('fwh-settings-sub') || 'general'; } catch (e) { return 'general'; } })(),
    setSub(k) {
      this.sub = k;
      try { localStorage.setItem('fwh-settings-sub', k); } catch (e) { /**/ }
    },

    // ── Storage & Admin (OPS-ADMIN) ─────────────────────────────────────────
    admin: { storage: {}, busy: false, exportHours: 24 },
    // Trusted networks (#457 phase 1). The result of Save stays in the section (no toast).
    security: { loaded: false, install: '', any: true, text: '', you: '', ingress: false,
                canSave: true, saving: false, msg: null, https: {},
                // phase 3: the switch, accounts and sign-in activity
                enabled: false, hasAdmin: false, onAddon: false, principal: null,
                switchMsg: null, users: [], events: [], acctMsg: null,
                add: { username: '', password: '', role: 'user' }, resetFor: null, resetPw: '',
                myPw: { current: '', new: '', msg: null },
                // phase 4: API tokens; a new token is shown once, in newToken
                tokens: [], tokenDays: [30, 90, 365], tok: { user_id: '', name: '', days: 365 },
                newToken: '', tokMsg: null },
    async loadSecurity() {
      try {
        const d = await (await fetch('api/security')).json();
        const nets = d.trusted_networks || ['any'];
        Object.assign(this.security, { loaded: true, install: d.install, you: d.your_address || '',
          ingress: !!d.via_ingress, canSave: d.can_save !== false, any: nets.includes('any'),
          https: d.https || {}, enabled: !!d.enabled, hasAdmin: !!d.has_admin,
          onAddon: !!d.on_addon, principal: d.principal || null,
          text: nets.includes('any') ? (d.private_ranges || []).join('\n') : nets.join('\n') });
      } catch (e) { /* leave last-known */ }
    },
    // An admin (or, while Security is off, anyone not in HA's sidebar) sees the accounts.
    securityAdmin() {
      const p = this.security.principal;
      if (p) return p.role === 'admin';     // HA sidebar users have their HA group's role
      return !this.security.enabled;
    },
    async loadAccounts() {
      if (!this.securityAdmin()) return;
      try {
        this.security.users = (await (await fetch('api/security/users')).json()).users || [];
        this.security.events = (await (await fetch('api/security/signins?limit=20')).json()).events || [];
        const tk = await (await fetch('api/security/tokens')).json();
        this.security.tokens = tk.tokens || []; this.security.tokenDays = tk.days || [30, 90, 365];
      } catch (e) { /* leave last-known */ }
    },
    async _securityCall(url, method, body, msgKey) {
      const s = this.security;
      s[msgKey] = null;
      try {
        const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' },
          body: body === undefined ? undefined : JSON.stringify(body) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || ('failed (' + r.status + ')'));
        return d;
      } catch (e) { s[msgKey] = { kind: 'danger', text: 'Not done: ' + e.message }; return null; }
    },
    async setSecurity(on) {
      const d = await this._securityCall('api/security/enabled', 'PUT', { enabled: on }, 'switchMsg');
      if (d) {
        this.security.switchMsg = { kind: 'ok', text: d.enabled
          ? 'Security is on. Port 8101 now sends browsers to the HTTPS port, where they sign in.'
          : 'Security is off. Both ports answer without signing in.' };
      }
      await this.loadSecurity(); await this.loadAccounts();
    },
    async addAccount() {
      const a = this.security.add;
      const d = await this._securityCall('api/security/users', 'POST',
        { username: a.username.trim(), password: a.role === 'api' ? null : a.password, role: a.role }, 'acctMsg');
      if (d) {
        this.security.acctMsg = { kind: 'ok', text: 'Added ' + d.username + ' (' + d.role + ').' };
        this.security.add = { username: '', password: '', role: 'user' };
      }
      await this.loadSecurity(); await this.loadAccounts();
    },
    async editAccount(u, change, done) {
      const d = await this._securityCall('api/security/users/' + u.id, 'PATCH', change, 'acctMsg');
      if (d) this.security.acctMsg = { kind: 'ok', text: done || ('Saved ' + d.username + '.') };
      await this.loadSecurity(); await this.loadAccounts();
    },
    async resetAccountPassword(u) {
      await this.editAccount(u, { password: this.security.resetPw }, 'New password set for ' + u.username + '.');
      if (this.security.acctMsg && this.security.acctMsg.kind === 'ok') { this.security.resetFor = null; this.security.resetPw = ''; }
    },
    async deleteAccount(u) {
      const d = await this._securityCall('api/security/users/' + u.id, 'DELETE', undefined, 'acctMsg');
      if (d) this.security.acctMsg = { kind: 'ok', text: 'Deleted ' + u.username + '.' };
      await this.loadSecurity(); await this.loadAccounts();
    },
    async createToken() {
      const k = this.security.tok;
      this.security.newToken = '';
      const d = await this._securityCall('api/security/tokens', 'POST',
        { user_id: Number(k.user_id), name: k.name.trim(), days: Number(k.days) }, 'tokMsg');
      if (d) {
        this.security.newToken = d.token;
        this.security.tokMsg = { kind: 'ok', text: 'Token "' + d.name + '" for ' + d.username
          + ' made. Copy it now: it is not shown again.' };
        k.name = '';
      }
      await this.loadAccounts();
    },
    async revokeToken(t) {
      const d = await this._securityCall('api/security/tokens/' + t.id, 'DELETE', undefined, 'tokMsg');
      if (d) this.security.tokMsg = { kind: 'ok', text: 'Revoked "' + t.name + '".' };
      this.security.newToken = '';
      await this.loadAccounts();
    },
    async changeMyPassword() {
      const m = this.security.myPw;
      const d = await this._securityCall('api/auth/password', 'POST', { current: m.current, new: m.new }, 'acctMsg');
      m.msg = d ? { kind: 'ok', text: 'Your password is changed.' } : this.security.acctMsg;
      this.security.acctMsg = null;
      if (d) { m.current = ''; m.new = ''; }
    },
    async signOut() {
      await fetch('api/auth/logout', { method: 'POST' });
      location.href = 'signin';
    },
    async saveTrustedNetworks() {
      const s = this.security;
      s.saving = true; s.msg = null;
      try {
        const networks = s.any ? ['any'] : s.text.split(/[\s,]+/).filter(Boolean);
        const r = await fetch('api/security/trusted-networks', { method: 'PUT',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ networks }) });
        const d = await r.json(); if (!r.ok) throw new Error(d.detail || 'save failed');
        const saved = d.trusted_networks || [];
        s.any = saved.includes('any');
        if (!s.any) s.text = saved.join('\n');
        s.msg = { kind: 'ok', text: s.any ? 'Saved: every network is trusted.'
                                          : 'Saved: ' + saved.length + ' trusted network(s).' };
      } catch (e) { s.msg = { kind: 'danger', text: 'Not saved: ' + e.message }; }
      finally { s.saving = false; }
    },
    async loadAdmin() {
      try { this.admin.storage = await (await fetch('api/admin/storage')).json() || {}; }
      catch (e) { /* leave last-known */ }
    },
    async vacuumDb() {
      this.admin.busy = true;
      try {
        const d = await (await fetch('api/admin/vacuum', { method: 'POST' })).json();
        this.$store.app.toast('Database compacted → ' + (d.db_human || ''), 'success');
        await this.loadAdmin();
      } catch (e) { this.$store.app.toast('Vacuum failed: ' + e.message, 'error'); }
      finally { this.admin.busy = false; }
    },
    async createBackup() {
      this.admin.busy = true;
      try {
        const d = await (await fetch('api/admin/backup', { method: 'POST' })).json();
        if (d.ok) this.$store.app.toast('Backup created (' + d.human + ')', 'success');
        await this.loadAdmin();
      } catch (e) { this.$store.app.toast('Backup failed: ' + e.message, 'error'); }
      finally { this.admin.busy = false; }
    },
    async restoreBackup(name) {
      if (!await this.$store.app.confirmDialog(
        'Restore this backup?\n\nIt OVERWRITES the current database — schedules, sites/tariffs, '
        + 'constants and all history are replaced with the snapshot. This cannot be undone.',
        { title: 'Restore database', danger: true })) return;
      try {
        const r = await fetch('api/admin/backup/' + encodeURIComponent(name) + '/restore', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirm: true }),
        });
        const d = await r.json();
        if (r.ok && d.ok) {
          this.$store.app.toast('Database restored — reloading…', 'success');
          setTimeout(() => window.location.reload(), 1200);
        } else {
          this.$store.app.toast('Restore failed: ' + (d.detail || 'error'), 'error');
        }
      } catch (e) { this.$store.app.toast('Restore failed: ' + e.message, 'error'); }
    },
    async deleteBackup(name) {
      if (!await this.$store.app.confirmDialog('Delete this backup?', { danger: true })) return;
      try {
        await fetch('api/admin/backup/' + encodeURIComponent(name), { method: 'DELETE' });
        await this.loadAdmin();
      } catch (e) { this.$store.app.toast('Delete failed: ' + e.message, 'error'); }
    },
    exportMetrics(fmt) {
      window.location = 'api/admin/metrics/export?fmt=' + fmt + '&hours=' + (this.admin.exportHours || 24);
    },
    fmtBackupTime(mtime) {
      if (!mtime) return '';
      try { return this.$store.app._fmtHostTime(mtime); } catch (e) { return ''; }
    },

    canWrite() { return !!(this.cfg.control && this.cfg.control.allow_writes); },

    // ── Discover (scan TCP 9000 + Local-API login) ──
    scanning: false,
    scanCands: null,      // null = not scanned; [] = scanned, none found
    scanSubnet: '',

    async discoverGateways() {
      if (!this.canWrite()) { this.gwErr = 'Enable writes (ALLOW_WRITES) to scan/add.'; return; }
      this.scanning = true; this.gwErr = ''; this.scanCands = null;
      try {
        const body = this.scanSubnet.trim() ? { subnet: this.scanSubnet.trim() } : {};
        const r = await fetch('api/gateways/scan', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        const d = await r.json();
        this.scanSubnet = d.subnet;
        this.scanCands = d.candidates || [];
      } catch (e) { this.gwErr = e.message; this.scanCands = []; }
      finally { this.scanning = false; }
    },

    confirmedCands() { return (this.scanCands || []).filter((c) => c.confirmed); },
    unconfirmedCount() { return (this.scanCands || []).filter((c) => !c.confirmed).length; },

    async addFromScan(c) {
      try {
        const label = c.serial ? ('aGate ' + String(c.serial).slice(-4)) : c.host;
        const r = await fetch('api/gateways', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, host: c.host, port: window.FWH_BOOT.ports.dc, enabled: true }) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        c.already_added = true;
        await this.loadGateways();
      } catch (e) { this.gwErr = e.message; }
    },

    // ── Mock gateway (in-process emulator, testing) ──
    mockForm: { label: 'Mock', units: 3, seed: '', publish_ha: false },
    async saveMockGateway() {
      if (!this.canWrite()) { this.gwErr = 'Enable writes (ALLOW_WRITES) to add a gateway.'; return; }
      try {
        const body = { label: this.mockForm.label || 'Mock', is_mock: true,
          mock_units: Math.max(1, Math.min(8, this.mockForm.units || 1)),
          publish_ha: this.mockForm.publish_ha, enabled: true };
        const seed = parseInt(this.mockForm.seed, 10);
        if (Number.isFinite(seed)) body.mock_seed = seed;   // reproducible profile
        const r = await fetch('api/gateways', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        await this.loadGateways();
      } catch (e) { this.gwErr = e.message; }
    },

    openAddGateway() { this.gwErr = ''; this.scanCands = null; this.gwAdd = { label: '', host: '', port: window.FWH_BOOT.ports.dc, enabled: true }; },
    cancelAddGateway() { this.gwAdd = null; },
    async saveAddGateway() {
      if (!this.canWrite()) { this.gwErr = 'Enable writes (ALLOW_WRITES) to add a gateway.'; return; }
      try {
        const r = await fetch('api/gateways', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.gwAdd) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.gwAdd = null;
        await this.loadGateways();
      } catch (e) { this.gwErr = e.message; }
    },

    // ── Edit Gateway modal ──
    gwEdit: { open: false, id: '', label: '', host: '', port: window.FWH_BOOT.ports.dc, description: '', publish_ha: true, is_mock: false, mock_units: 1, is_default: false, enabled: true, was_enabled: true, meter_id: '' },
    gwTest: null, gwTesting: false, gwNote: '',
    openEditGateway(gw) {
      this.gwErr = ''; this.gwNote = ''; this.gwTest = null;
      this.gwEdit = { open: true, id: gw.id, label: gw.label, host: gw.host || '', port: gw.port || window.FWH_BOOT.ports.dc,
        description: gw.description || '', publish_ha: !!gw.publish_ha, is_mock: !!gw.is_mock,
        mock_units: gw.mock_units || 1, is_default: !!gw.is_default, enabled: !!gw.enabled,
        was_enabled: !!gw.enabled, meter_id: gw.meter_id || '' };
    },
    // The default moves only here, never as a side effect of an edit (#182).
    async makeDefaultGateway() {
      if (!this.canWrite()) { this.gwErr = 'Enable writes (ALLOW_WRITES) to edit gateways.'; return; }
      this.gwErr = ''; this.gwNote = '';
      try {
        const r = await fetch('api/gateways/' + encodeURIComponent(this.gwEdit.id) + '/default', { method: 'POST' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.gwEdit.is_default = true;
        this.gwNote = `"${this.gwEdit.label}" is now the default gateway.`;
        await this.loadGateways();
      } catch (e) { this.gwErr = e.message; }
    },
    closeEditGateway() { this.gwEdit.open = false; this.gwTest = null; },

    // ── Sites + Meters ──
    async loadSitesMeters() {
      try { this.sites = (await (await fetch('api/sites')).json()).sites || []; } catch { this.sites = []; }
      try { this.meters = (await (await fetch('api/meters')).json()).meters || []; } catch { this.meters = []; }
    },
    metersForSite(sid) { return this.meters.filter(m => m.site_id === sid); },
    meterName(id) { const m = this.meters.find(x => x.id === id); return m ? m.name : '—'; },
    acLabel(t) { return ({ single: 'Single phase', split: 'Split / dual', three: 'Three phase' })[t] || t; },

    newSite() { this.siteEdit = { id: '', name: '', timezone: '', postcode: '', region: '', currency: '' }; },
    editSite(s) { this.siteEdit = { ...s }; },
    async saveSite() {
      if (!this.canWrite()) { this.$store.app.toast('Enable writes to change sites', 'error'); return; }
      const s = this.siteEdit;
      const body = { name: s.name, timezone: s.timezone || '', postcode: s.postcode || '', region: s.region || '', currency: s.currency || '' };
      try {
        const r = await fetch(s.id ? 'api/sites/' + s.id : 'api/sites',
          { method: s.id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.siteEdit = null; await this.loadSitesMeters();
      } catch (e) { this.$store.app.toast('Site save failed: ' + e.message, 'error'); }
    },
    async deleteSite(s) {
      if (!await this.$store.app.confirmDialog(`Delete site "${s.name}"?`, { danger: true })) return;
      try {
        const r = await fetch('api/sites/' + s.id, { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        await this.loadSitesMeters();
      } catch (e) { this.$store.app.toast('Delete failed: ' + e.message, 'error'); }
    },
    newMeter(sid) { this.meterEdit = { id: '', site_id: sid, name: 'Meter ' + (this.metersForSite(sid).length + 1), meter_number: '', ac_type: 'single', rated_amps: '', pto_status: 'unknown', pto_reference: '', timezone: '', utility_id: '', tariff_id: '' }; },
    editMeter(m) { this.meterEdit = { ...m, rated_amps: m.rated_amps ?? '', pto_status: m.pto_status || 'unknown', pto_reference: m.pto_reference || '', timezone: m.timezone || '', utility_id: m.utility_id || '', tariff_id: m.tariff_id || '' }; },
    ptoLabel(s) { return ({ unknown: 'Unknown', pending: 'Pending', approved: 'Approved', exempt: 'Exempt' })[s] || 'Unknown'; },
    async saveMeter() {
      if (!this.canWrite()) { this.$store.app.toast('Enable writes to change meters', 'error'); return; }
      const m = this.meterEdit;
      const body = { site_id: m.site_id, name: m.name, meter_number: m.meter_number || '',
                     ac_type: m.ac_type, rated_amps: (m.rated_amps === '' || m.rated_amps == null) ? null : Number(m.rated_amps),
                     utility_id: m.utility_id || '', tariff_id: m.tariff_id || '' };
      try {
        const r = await fetch(m.id ? 'api/meters/' + m.id : 'api/meters',
          { method: m.id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.meterEdit = null; await this.loadSitesMeters();
      } catch (e) { this.$store.app.toast('Meter save failed: ' + e.message, 'error'); }
    },
    async deleteMeter(m) {
      if (!await this.$store.app.confirmDialog(`Delete meter "${m.name}"?`, { danger: true })) return;
      try {
        const r = await fetch('api/meters/' + m.id, { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        await this.loadSitesMeters();
      } catch (e) { this.$store.app.toast('Delete failed: ' + e.message, 'error'); }
    },

    // ── Utilities + Tariffs ──
    async loadUtilitiesTariffs() {
      try { this.utilities = (await (await fetch('api/utilities')).json()).utilities || []; } catch { this.utilities = []; }
      try { this.tariffs = (await (await fetch('api/tariffs')).json()).tariffs || []; } catch { this.tariffs = []; }
    },

    async loadConstants() {
      try { const d = await (await fetch('api/constants')).json();
            this.constants = d.values || {}; this.constSpec = d.spec || {}; }
      catch { this.constants = {}; }
      try { this.constModes = (await (await fetch('api/constants/modes' + this.$store.app.gwQuery())).json()).options || []; }
      catch { this.constModes = []; }
    },
    modeAvail(v) { return !this.constModes.length || this.constModes.some(o => o.value === v); },
    async saveConstants() {
      if (!this.canWrite()) { this.$store.app.toast('Enable writes to save constants', 'error'); return; }
      this.constSaving = true;
      try {
        const r = await fetch('api/constants', { method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            min_discharge_soc: Number(this.constants.min_discharge_soc),
            max_charge_soc: Number(this.constants.max_charge_soc),
            demand_charge_min_soc: Number(this.constants.demand_charge_min_soc),
            battery_capacity_kwh: Number(this.constants.battery_capacity_kwh),
            battery_max_power_kw: Number(this.constants.battery_max_power_kw),
            default_operating_mode: this.constants.default_operating_mode,
          }) });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'save failed');
        this.constants = d.values || this.constants;
        this.$store.app.toast('Constants saved', 'success');
      } catch (e) { this.$store.app.toast('Constants save failed: ' + e.message, 'error'); }
      finally { this.constSaving = false; }
    },

    async loadSystemSetup() {
      const gwq = this.$store.app.gwQuery();
      try { const d = await (await fetch('api/system-setup' + gwq)).json();
            if (gwq !== this.$store.app.gwQuery()) return;     // a late reply for another gateway
            this.systemSetup = d.values || {}; this.systemSpec = d.spec || {}; this.systemFor = gwq;
            this.systemLoaded = this.sysFields(); }
      catch { this.systemSetup = {}; }
    },
    //: The form shows the gateway on screen, so Save can't write one gateway's form to another.
    get systemCurrent() { return this.systemFor === this.$store.app.gwQuery(); },
    sysDerived(k) { return !!(this.systemSetup._overridden && this.systemSetup._overridden[k] === false && this.systemSpec[k] && this.systemSpec[k].derived); },
    /** The form's fields, normalised the way they are stored. */
    sysFields() {
      const s = this.systemSetup || {};
      return { solar_type: s.solar_type, solar_kwp: Number(s.solar_kwp) || 0,
        generator_input: !!s.generator_input, grid_forming: !!s.grid_forming,
        whole_home_backup: !!s.whole_home_backup, load_shedding: !!s.load_shedding,
        non_backup_loads: !!s.non_backup_loads, battery_label: s.battery_label || '' };
    },
    /** Only what was changed here (#496): saving every field would turn each one into an
     *  override, and the gateway's later readings would be ignored. */
    sysChanged() {
      const now = this.sysFields(), was = this.systemLoaded || {};
      return Object.fromEntries(Object.entries(now).filter(([k, v]) => was[k] !== v));
    },
    async saveSystemSetup() {
      if (!this.canWrite()) { this.$store.app.toast('Enable writes to save', 'error'); return; }
      if (!this.systemCurrent) return;
      this.systemSaving = true;
      try {
        const changed = this.sysChanged();
        if (!Object.keys(changed).length) { this.$store.app.toast('Nothing changed', 'info'); return; }
        const r = await fetch('api/system-setup' + this.$store.app.gwQuery(), { method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(changed) });
        const d = await r.json(); if (!r.ok) throw new Error(d.detail || 'save failed');
        this.systemSetup = d.values || this.systemSetup;
        this.systemLoaded = this.sysFields();
        this.$store.app._loadSolarInstalled();    // the Solar tab follows the solar type
        this.$store.app.toast('System Setup saved', 'success');
      } catch (e) { this.$store.app.toast('System Setup save failed: ' + e.message, 'error'); }
      finally { this.systemSaving = false; }
    },
    tariffsForUtility(uid) { return this.tariffs.filter(t => t.utility_id === uid); },
    utilityName(id) { const u = this.utilities.find(x => x.id === id); return u ? u.name : '—'; },
    tariffName(id) { const t = this.tariffs.find(x => x.id === id); return t ? t.name : '—'; },
    tariffStatus(t) {
      const today = new Date().toISOString().slice(0, 10);
      if (t.effective_end && t.effective_end < today) return 'past';
      if (t.effective_start && t.effective_start > today) return 'future';
      return 'active';
    },
    tariffDateLabel(t) {
      if (!t.effective_start && !t.effective_end) return '';
      return (t.effective_start || '…') + ' → ' + (t.effective_end || 'now');
    },
    async supersedeTariff(t) {
      if (!this.canWrite()) { this.$store.app.toast('Enable writes to supersede', 'error'); return; }
      const today = new Date().toISOString().slice(0, 10);
      try { await fetch('api/tariffs/' + t.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ effective_end: today }) }); } catch (e) {}
      await this.loadUtilitiesTariffs();
      const fresh = this.tariffs.find(x => x.id === t.id) || t;
      this.editTariff(fresh);            // pre-fill from the old plan…
      this.tariffEdit.id = '';           // …but save as a NEW tariff (the old is kept, end-dated)
      this.tariffEdit.name = (t.name || 'Tariff') + ' v2';
      this.tariffEdit.effective_start = today;
      this.tariffEdit.effective_end = '';
      this.$store.app.toast('Old tariff end-dated ' + today + ' — edit + save the new one', 'info');
    },

    newUtility() { this.utilEdit = { id: '', name: '', network_dnsp: '', country: '', plan_type: 'unknown', export_allowed: true, solar_export_allowed: true, battery_export_allowed: true, charging_allowed: true, discharging_allowed: true, export_limit_kw: '', export_note: '', effective_start: '', effective_end: '' }; },

    // ── tariff-profile interchange with the Modbus bridge (FEAT-IMPORT-AGL-SETUP) ──
    async exportTariffProfile(t) {
      try {
        const bundle = await (await fetch('api/tariffs/' + encodeURIComponent(t.id) + '/export')).json();
        const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = ((t.name || 'tariff').replace(/[^\w.-]+/g, '_')) + '-tariff.json';
        a.click(); URL.revokeObjectURL(a.href);
      } catch (e) { this.$store.app.toast('Export failed: ' + e.message, 'error'); }
    },
    // Import tariff (owner 2026-11-13): paste the JSON or choose a file — a phone often has
    // no file to hand. Check is the dry-run preview; results stay in the dialog.
    openTariffImport() {
      this.tariffImp = { open: true, text: '', preview: null, msg: null, busy: false, done: false };
    },
    async tariffImportFile(ev) {
      const file = ev.target.files[0]; ev.target.value = '';
      if (!file) return;
      this.tariffImp.text = await file.text();
      await this.tariffImportCheck();
    },
    _tariffBundle() {
      try { return JSON.parse(this.tariffImp.text); }
      catch (e) { this.tariffImp.msg = { kind: 'err', text: 'Not valid JSON: ' + e.message }; return null; }
    },
    async tariffImportCheck() {
      const t = this.tariffImp;
      Object.assign(t, { preview: null, msg: null, done: false });
      const bundle = this._tariffBundle();
      if (!bundle) return;
      t.busy = true;
      try {
        const r = await fetch('api/tariffs/import?dry_run=true', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundle) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) t.msg = { kind: 'err', text: 'Not accepted: ' + (d.detail || r.statusText) };
        else t.preview = d.preview || {};
      } catch (e) { t.msg = { kind: 'err', text: 'Check failed: ' + e.message }; }
      t.busy = false;
    },
    tariffImportSummary() {
      const p = this.tariffImp.preview || {};
      return `"${p.tariff_name}"\nRetailer: ${p.retailer} · Network: ${p.network}\n`
        + `Plan: ${p.plan_type} · ${p.seasons} season(s) · ${p.fixed_charges} fixed charge(s)`
        + (p.timezone ? `\nTimezone: ${p.timezone}` : '')
        + '\nImport creates the utility + tariff and attaches them to the default meter.';
    },
    async tariffImportApply() {
      const t = this.tariffImp;
      const bundle = this._tariffBundle();
      if (!bundle) return;
      t.busy = true;
      try {
        const r = await fetch('api/tariffs/import', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundle) });
        const d = await r.json().catch(() => ({}));
        if (r.ok && d.ok) {
          t.msg = { kind: 'ok', text: `Imported ${t.preview.retailer} — ${t.preview.tariff_name}.` };
          t.done = true;
          await this.loadUtilitiesTariffs(); await this.loadSitesMeters();
        } else t.msg = { kind: 'err', text: 'Import failed: ' + (d.detail || r.statusText) };
      } catch (e) { t.msg = { kind: 'err', text: 'Import failed: ' + e.message }; }
      t.busy = false;
    },
    editUtility(u) { this.utilEdit = { ...u, export_limit_kw: u.export_limit_kw ?? '',
      export_allowed: !!u.export_allowed, solar_export_allowed: !!u.solar_export_allowed, battery_export_allowed: !!u.battery_export_allowed,
      charging_allowed: !!u.charging_allowed, discharging_allowed: !!u.discharging_allowed,
      effective_start: u.effective_start || '', effective_end: u.effective_end || '' }; },
    async saveUtility() {
      if (!this.canWrite()) { this.$store.app.toast('Enable writes to change utilities', 'error'); return; }
      const u = this.utilEdit;
      const body = { name: u.name, network_dnsp: u.network_dnsp || '', country: u.country || '', plan_type: u.plan_type || 'unknown',
        export_allowed: u.export_allowed, solar_export_allowed: u.solar_export_allowed, battery_export_allowed: u.battery_export_allowed,
        charging_allowed: u.charging_allowed, discharging_allowed: u.discharging_allowed,
        export_limit_kw: (u.export_limit_kw === '' || u.export_limit_kw == null) ? null : Number(u.export_limit_kw) };
      try {
        const r = await fetch(u.id ? 'api/utilities/' + u.id : 'api/utilities',
          { method: u.id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.utilEdit = null; await this.loadUtilitiesTariffs();
      } catch (e) { this.$store.app.toast('Utility save failed: ' + e.message, 'error'); }
    },
    async deleteUtility(u) {
      if (!await this.$store.app.confirmDialog(`Delete utility "${u.name}"?`, { danger: true })) return;
      try {
        const r = await fetch('api/utilities/' + u.id, { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        await this.loadUtilitiesTariffs();
      } catch (e) { this.$store.app.toast('Delete failed: ' + e.message, 'error'); }
    },

    newTariff(uid) { this.tariffEdit = { id: '', utility_id: uid, name: '', billing_cycle_day: 1, effective_start: '', effective_end: '',
      pricing: { default_rate: { buy: '', sell: '' }, seasons: [], kind: 'static', dynamic: { source: 'nem', region: '', buy_entity: '', feedin_entity: '' } },
      demand: { on: false, start: '15:00', end: '21:00', rate: '', interval_min: 30, basis: 'per_kw_day', months: [], days: [] },
      bonus: { on: false, start: '17:00', end: '21:00', rate: '', months: [], days: [] },
      charge: { on: false, start: '10:00', end: '15:00', rate: '', free_kwh_per_day: '', months: [], days: [] },
      fixed: [] }; this.tariffProblems = []; this.seasonIdx = 0; this.rateProblems = []; },
    editTariff(t) {
      const pr = JSON.parse(JSON.stringify(t.pricing || {}));
      if (!pr.default_rate) pr.default_rate = { buy: '', sell: '' };
      if (!pr.seasons) pr.seasons = [];
      if (!pr.kind) pr.kind = 'static';
      if (!pr.dynamic) pr.dynamic = { source: 'nem', region: '', buy_entity: '', feedin_entity: '' };
      pr.seasons.forEach(x => this._ensureSeason(x));
      if (!this.nemSpot) this.loadNemSpot();   // populate region options for the wholesale picker
      this.loadHaPriceOpts();   // friendly HA price-entity names for the combobox
      const dw = t.demand_window || {}, bw = t.bonus_window || {}, cw = t.charge_window || {};
      this.tariffEdit = { id: t.id, utility_id: t.utility_id, name: t.name, billing_cycle_day: t.billing_cycle_day || 1, effective_start: t.effective_start || '', effective_end: t.effective_end || '', pricing: pr,
        demand: { on: !!dw.start, start: dw.start || '15:00', end: dw.end || '21:00', rate: pr.demand_rate ?? '', interval_min: pr.demand_interval_min || 30, basis: pr.demand_charge_basis || 'per_kw_day', months: dw.months || [], days: dw.days || [] },
        bonus: { on: !!bw.start, start: bw.start || '17:00', end: bw.end || '21:00', rate: pr.export_bonus_rate ?? '', months: bw.months || [], days: bw.days || [] },
        charge: { on: !!cw.start, start: cw.start || '10:00', end: cw.end || '15:00', rate: pr.export_charge_rate ?? '', free_kwh_per_day: pr.export_charge_free_kwh_per_day ?? '', months: cw.months || [], days: cw.days || [] },
        fixed: (Array.isArray(t.fixed_charges) ? t.fixed_charges : []).map(c => ({ type: c.type || 'supply', levied_by: c.levied_by || 'utility', description: c.description || '', frequency: c.frequency || 'daily', rate: c.rate ?? '', tax_rate: c.tax_rate ?? '' })) };
      this.tariffProblems = [];
      this.seasonIdx = 0; this.rateProblems = [];
      this.checkRates();
    },
    tariffProblems: [],
    periodLabel(p) { return ({ super_off_peak: 'Super off-peak', off_peak: 'Off-peak', mid_peak: 'Mid-peak', on_peak: 'On-peak' })[p] || p; },
    _ensureSeason(sea) {
      sea.months = sea.months || []; sea.blocks = sea.blocks || []; sea.time_periods = sea.time_periods || {};
      for (const p of ['super_off_peak', 'off_peak', 'mid_peak', 'on_peak']) {
        const r = sea.time_periods[p] || {};
        sea.time_periods[p] = { buy: r.buy ?? '', sell: r.sell ?? '' };
      }
      return sea;
    },
    // ── Energy-rates editor (cloned from the Modbus bridge) ────────────────
    monthLabels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    PERIOD_IDS: ['super_off_peak', 'off_peak', 'mid_peak', 'on_peak'],
    PERIOD_LABELS: { super_off_peak: 'Super Off-Peak', off_peak: 'Off-Peak', mid_peak: 'Mid-Peak', on_peak: 'On-Peak' },
    PERIOD_DOTS: { super_off_peak: '#3b82f6', off_peak: '#64748b', mid_peak: '#f59e0b', on_peak: '#ef4444' },
    seasonIdx: 0,
    rateProblems: [],

    get seasons() { return (this.tariffEdit && this.tariffEdit.pricing && this.tariffEdit.pricing.seasons) || []; },
    get nemRegions() { return (this.nemSpot && this.nemSpot.regions) || ['NSW1','QLD1','SA1','TAS1','VIC1']; },
    get haPriceOptions() { return (this.nemSpot && this.nemSpot.ha_options) || []; },
    // Friendly-name HA price entities for the styled combobox (buy/feed-in), like the scheduler.
    async loadHaPriceOpts() {
      try {
        const d = await (await fetch('api/ha/entities?exposed=true&limit=1000')).json();
        const opt = e => ({ id: `ha:${e.instance_id}:${e.entity_id}`, label: e.name || e.entity_id, group: e.instance || 'HA' });
        this.haPriceOpts = (d.entities || [])
          .filter(e => ['sensor', 'number', 'input_number'].includes(e.domain)).map(opt);
        // On/off entities for the price events (#582): a spike sensor, a peak window.
        this.haEventOpts = (d.entities || [])
          .filter(e => ['binary_sensor', 'calendar', 'input_boolean', 'switch'].includes(e.domain)).map(opt);
      } catch (e) { this.haPriceOpts = []; this.haEventOpts = []; }
    },
    // The price signal's source (#582): off, AEMO NEM (the site's region) or HA entities.
    async setPriceSignal(v) {
      this.priceSrc = v;
      if (v === 'nem') {
        const rg = (this.nemSpot && this.nemSpot.site_region) || '';
        await this.saveOne({ nem_region: rg, tariff_price_entity: '', tariff_feedin_entity: '' });
      } else if (v === 'ha') {
        await this.saveOne({ nem_region: '' });
      } else {
        await this.saveOne({ nem_region: '', tariff_price_entity: '', tariff_feedin_entity: '' });
      }
      await this.loadNemSpot();
    },
    haPriceLabel(id) {
      if (!id) return '';
      const o = this.haPriceOpts.find(x => x.id === id);
      return o ? o.label : (id.split(':').slice(2).join(':') || id);
    },
    haPriceItems(q) {
      const t = (q || '').toLowerCase().trim();
      const groups = {};
      for (const o of this.haPriceOpts) {
        if (t && !(o.label.toLowerCase().includes(t) || o.id.toLowerCase().includes(t))) continue;
        (groups[o.group] ||= []).push(o);
      }
      const out = [];
      for (const [g, items] of Object.entries(groups)) {
        out.push({ kind: 'group', name: g, key: 'g:' + g });
        for (const o of items) out.push({ kind: 'item', id: o.id, label: o.label, key: o.id });
      }
      return out;
    },
    get defaultRate() {
      const pr = this.tariffEdit && this.tariffEdit.pricing;
      if (!pr) return null;
      if (!pr.default_rate) pr.default_rate = { buy: 0, sell: 0 };
      return pr.default_rate;
    },
    get season() { return this.seasons[this.seasonIdx] || null; },

    // Tariff-wide (default) rate — flat or tiered. Overridden by any time period.
    isDefaultTiered(side) { return Array.isArray(this.defaultRate && this.defaultRate[side]); },
    makeDefaultTiered(side) {
      const flat = Number(this.defaultRate[side]) || 0;
      this.defaultRate[side] = [{ up_to_kwh: 1000, rate: flat }, { rate: flat }];
      this.checkRates();
    },
    makeDefaultFlat(side) {
      const l = this.defaultRate[side];
      this.defaultRate[side] = Number(l && l[0] && l[0].rate) || 0;
      this.checkRates();
    },
    addDefaultTier(side) {
      const l = this.defaultRate[side];
      const bounded = l.filter(t => typeof t.up_to_kwh === 'number');
      const next = bounded.length ? Math.max(...bounded.map(t => t.up_to_kwh)) * 2 : 1000;
      l.splice(l.length - 1, 0, { up_to_kwh: next, rate: (l[l.length - 1] && l[l.length - 1].rate) ?? 0 });
      this.checkRates();
    },
    removeDefaultTier(side, i) {
      const l = this.defaultRate[side];
      if (l.length <= 2) { this.makeDefaultFlat(side); return; }
      l.splice(i, 1);
      this.checkRates();
    },
    applyDefaultToAllPeriods() {
      const src = JSON.parse(JSON.stringify(this.defaultRate));
      let n = 0;
      for (const s of this.seasons) for (const k of Object.keys(s.time_periods || {})) { s.time_periods[k] = JSON.parse(JSON.stringify(src)); n += 1; }
      this.checkRates();
      this.$store.app.toast(`Reset ${n} time period(s) to the tariff rate`, 'info');
    },

    _blankSeason(name) {
      const periods = {};
      for (const w of this.PERIOD_IDS) periods[w] = { buy: 0, sell: 0 };
      return { id: 'season_' + Date.now().toString(36), name: name || `Season ${this.seasons.length + 1}`,
        months: [], time_periods: periods,
        blocks: [{ start: '00:00', end: '24:00', time_period: 'off_peak', days: [] }] };
    },
    addFlatSeason() {
      const season = this._blankSeason('Flat rate');
      if (!this.tariffEdit.pricing.seasons) this.tariffEdit.pricing.seasons = [];
      this.tariffEdit.pricing.seasons.push(season);
      this.seasonIdx = this.seasons.length - 1;
      this.checkRates();
      this.$store.app.toast('Flat rate season added — set buy and sell on Off-Peak', 'info');
    },
    addSeason() {
      if (!this.tariffEdit.pricing.seasons) this.tariffEdit.pricing.seasons = [];
      this.tariffEdit.pricing.seasons.push(this._blankSeason());
      this.seasonIdx = this.seasons.length - 1;
      this.checkRates();
    },
    removeSeason(i) {
      this.tariffEdit.pricing.seasons.splice(i, 1);
      this.seasonIdx = Math.max(0, Math.min(this.seasonIdx, this.seasons.length - 1));
      this.checkRates();
    },
    monthOwner(m) { const s = this.seasons.find(x => (x.months || []).includes(m)); return s ? s.name : null; },
    // Months are exclusive across seasons — clicking one owned elsewhere MOVES it here.
    toggleMonth(m) {
      if (!this.season) return;
      const mine = (this.season.months || []).includes(m);
      for (const s of this.seasons) s.months = (s.months || []).filter(x => x !== m);
      if (!mine) this.season.months.push(m);
      this.season.months.sort((a, b) => a - b);
      this.checkRates();
    },
    addBlock() { this.season.blocks.push({ start: '00:00', end: '06:00', time_period: 'off_peak', days: [] }); this.checkRates(); },
    removeBlock(i) { this.season.blocks.splice(i, 1); this.checkRates(); },
    setBlockDays(block, preset) { block.days = preset === 'weekdays' ? [0, 1, 2, 3, 4] : preset === 'weekend' ? [5, 6] : []; this.checkRates(); },
    blockDayPreset(block) { const d = (block.days || []).join(','); if (d === '0,1,2,3,4') return 'weekdays'; if (d === '5,6') return 'weekend'; return 'all'; },
    periodUsed(w) { return ((this.season && this.season.blocks) || []).some(b => b.time_period === w); },

    // Tier ladders on a time period's price (a tiered TOU band = a hybrid plan).
    isTiered(period, side) { return Array.isArray(this.season && this.season.time_periods && this.season.time_periods[period] && this.season.time_periods[period][side]); },
    makeTiered(period, side) {
      const flat = Number(this.season.time_periods[period][side]) || 0;
      this.season.time_periods[period][side] = [{ up_to_kwh: 1000, rate: flat }, { rate: flat }];
      this.checkRates();
    },
    makeFlat(period, side) {
      const ladder = this.season.time_periods[period][side];
      this.season.time_periods[period][side] = Number(ladder && ladder[0] && ladder[0].rate) || 0;
      this.checkRates();
    },
    addTier(period, side) {
      const ladder = this.season.time_periods[period][side];
      const last = ladder[ladder.length - 1];
      const bounded = ladder.filter(t => typeof t.up_to_kwh === 'number');
      const nextLimit = bounded.length ? Math.max(...bounded.map(t => t.up_to_kwh)) * 2 : 1000;
      ladder.splice(ladder.length - 1, 0, { up_to_kwh: nextLimit, rate: (last && last.rate) ?? 0 });
      this.checkRates();
    },
    removeTier(period, side, i) {
      const ladder = this.season.time_periods[period][side];
      if (ladder.length <= 2) { this.makeFlat(period, side); return; }
      ladder.splice(i, 1);
      this.checkRates();
    },
    copyRatesToAllSeasons() {
      if (!this.season) return;
      const src = JSON.parse(JSON.stringify(this.season.time_periods));
      for (const s of this.seasons) if (s !== this.season) s.time_periods = JSON.parse(JSON.stringify(src));
      this.$store.app.toast('Rates copied to every season', 'info');
    },
    async checkRates() {
      try {
        const r = await fetch('api/tariffs/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pricing: this._tariffPricing() }) });
        const d = await r.json();
        this.rateProblems = (d && d.problems) || [];
      } catch (e) { /* live check is best-effort */ }
    },

    addFixed() { this.tariffEdit.fixed.push({ type: 'supply', levied_by: 'utility', description: '', frequency: 'daily', rate: '', tax_rate: '' }); },
    removeFixed(i) { this.tariffEdit.fixed.splice(i, 1); },
    // Standing charges normalised to $/day (× tax) for the tab's Total footer.
    fixedPerDay(f) {
      const r = Number(f.rate) || 0, tax = 1 + (Number(f.tax_rate) || 0);
      const per = { daily: 1, weekly: 1 / 7, monthly: 12 / 365, quarterly: 4 / 365, annual: 1 / 365 }[f.frequency || 'daily'] || 1;
      return r * per * tax;
    },
    get fixedTotalPerDay() { return ((this.tariffEdit && this.tariffEdit.fixed) || []).reduce((a, f) => a + this.fixedPerDay(f), 0); },
    // Month / day-of-week pills shared by the demand / bonus / charge windows (0=Mon … 6=Sun).
    toggleWinMonth(o, m) { o.months = o.months || []; const k = o.months.indexOf(m); if (k >= 0) o.months.splice(k, 1); else { o.months.push(m); o.months.sort((a, b) => a - b); } },
    toggleWinDay(o, d) { o.days = o.days || []; const k = o.days.indexOf(d); if (k >= 0) o.days.splice(k, 1); else { o.days.push(d); o.days.sort((a, b) => a - b); } },
    // Export is already priced by the time periods when any sell rate is set — an
    // export-bonus window would then double-count the same kWh.
    get exportPricedByPeriod() {
      const priced = v => Array.isArray(v) ? v.length > 0 : (v !== '' && v != null && Number(v) !== 0);
      return this.seasons.some(s => Object.values(s.time_periods || {}).some(tp => priced(tp && tp.sell)))
        || (this.defaultRate && priced(this.defaultRate.sell));
    },
    _tariffPricing() {
      const t = this.tariffEdit, dr = t.pricing.default_rate || {};
      const num = v => (v === '' || v == null) ? null : Number(v);
      // A rate is a scalar OR a tier ladder [{up_to_kwh?, rate}]; preserve arrays intact.
      const rate = v => Array.isArray(v)
        ? v.map(tr => (typeof tr.up_to_kwh === 'number'
            ? { up_to_kwh: Number(tr.up_to_kwh), rate: Number(tr.rate) || 0 }
            : { rate: Number(tr.rate) || 0 }))
        : num(v);
      const seasons = (t.pricing.seasons || []).map(sea => {
        const tp = {};
        for (const p in (sea.time_periods || {})) {
          const r = sea.time_periods[p] || {}, buy = rate(r.buy), sell = rate(r.sell);
          if (buy != null || sell != null) tp[p] = { ...(buy != null ? { buy } : {}), ...(sell != null ? { sell } : {}) };
        }
        return { ...(sea.id ? { id: sea.id } : {}), name: sea.name || '', months: (sea.months || []).map(Number), time_periods: tp,
          blocks: (sea.blocks || []).map(b => ({ start: b.start, end: b.end, time_period: b.time_period,
            ...(b.days && b.days.length ? { days: b.days.map(Number) } : {}) })) };
      });
      const p = { ...t.pricing, default_rate: { buy: rate(dr.buy), sell: rate(dr.sell) }, seasons };
      const d = t.demand || {}, b = t.bonus || {}, c = t.charge || {};
      if (d.on) { p.demand_rate = num(d.rate); p.demand_interval_min = Number(d.interval_min) || 30; p.demand_charge_basis = d.basis || 'per_kw_day'; }
      if (b.on) { p.export_bonus_rate = num(b.rate); }
      if (c.on) { p.export_charge_rate = num(c.rate); p.export_charge_free_kwh_per_day = num(c.free_kwh_per_day); }
      return p;
    },
    async validateTariff() {
      try {
        const r = await fetch('api/tariffs/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pricing: this._tariffPricing() }) });
        const d = await r.json(); this.tariffProblems = d.problems || [];
        this.$store.app.toast(d.ok ? 'Tariff is valid' : `${this.tariffProblems.length} issue(s)`, d.ok ? 'success' : 'info');
      } catch (e) { this.$store.app.toast('Validate failed: ' + e.message, 'error'); }
    },
    async saveTariff() {
      if (!this.canWrite()) { this.$store.app.toast('Enable writes to change tariffs', 'error'); return; }
      const t = this.tariffEdit;
      const win = o => (o && o.on ? { start: o.start, end: o.end,
        ...(o.months && o.months.length ? { months: o.months.map(Number) } : {}),
        ...(o.days && o.days.length ? { days: o.days.map(Number) } : {}) } : {});
      const body = { utility_id: t.utility_id, name: t.name, billing_cycle_day: Number(t.billing_cycle_day) || 1,
        effective_start: t.effective_start || null, effective_end: t.effective_end || null,
        pricing: this._tariffPricing(),
        demand_window: win(t.demand), bonus_window: win(t.bonus), charge_window: win(t.charge),
        fixed_charges: (t.fixed || []).filter(f => f.rate !== '' && f.rate != null)
          .map(f => ({ type: f.type || 'supply', levied_by: f.levied_by || 'utility', description: f.description || '', frequency: f.frequency || 'daily', rate: Number(f.rate) || 0, tax_rate: Number(f.tax_rate) || 0 })) };
      try {
        const r = await fetch(t.id ? 'api/tariffs/' + t.id : 'api/tariffs',
          { method: t.id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.tariffEdit = null; await this.loadUtilitiesTariffs();
      } catch (e) { this.$store.app.toast('Tariff save failed: ' + e.message, 'error'); }
    },
    async deleteTariff(t) {
      if (!await this.$store.app.confirmDialog(`Delete tariff "${t.name}"?`, { danger: true })) return;
      try {
        const r = await fetch('api/tariffs/' + t.id, { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        await this.loadUtilitiesTariffs();
      } catch (e) { this.$store.app.toast('Delete failed: ' + e.message, 'error'); }
    },
    async saveEditGateway() {
      if (!this.canWrite()) { this.gwErr = 'Enable writes (ALLOW_WRITES) to edit gateways.'; return; }
      const e = this.gwEdit;
      const body = e.is_mock
        ? { label: e.label, description: e.description, publish_ha: e.publish_ha,
            mock_units: Math.max(1, Math.min(8, e.mock_units || 1)) }
        : { label: e.label, host: e.host, port: e.port, description: e.description, publish_ha: e.publish_ha };
      if (e.enabled !== e.was_enabled) body.enabled = e.enabled;
      if (e.meter_id) body.meter_id = e.meter_id;
      this.gwErr = ''; this.gwNote = '';
      try {
        const r = await fetch('api/gateways/' + encodeURIComponent(e.id), {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || r.statusText);
        await this.loadGateways();
        // A disable that released a force says so here, in the dialog (#353).
        if (d.released) {
          e.was_enabled = e.enabled;
          this.gwNote = `Saved. The force this bridge held on "${e.label}" was released: ${d.released}`;
        } else {
          this.gwEdit.open = false;
        }
      } catch (err) { this.gwErr = err.message; }
    },
    async testEditGateway() {
      this.gwTesting = true; this.gwTest = null;
      try {
        const r = await fetch('api/gateways/' + encodeURIComponent(this.gwEdit.id) + '/summary');
        const d = await r.json();
        this.gwTest = { ok: !!d.ok, latency: d.latency_ms,
          serial: d.serial || (d.firmware && d.firmware.IBG_SN) || null,
          mode: d.mode && d.mode.name, soc: d.power && d.power.soc };
      } catch (e) { this.gwTest = { ok: false, error: e.message }; }
      finally { this.gwTesting = false; }
    },
    async restartEditGateway() {
      if (!this.canWrite()) { this.gwErr = 'Enable writes to restart.'; return; }
      try {
        const r = await fetch('api/gateways/' + encodeURIComponent(this.gwEdit.id) + '/restart', { method: 'POST' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.gwTest = { restarted: true }; await this.loadGateways();
      } catch (e) { this.gwErr = e.message; }
    },
    async removeEditGateway() {
      if (!this.canWrite()) { this.gwErr = 'Enable writes to remove.'; return; }
      if (!await this.$store.app.confirmDialog(`Remove gateway "${this.gwEdit.label}"?`, { danger: true })) return;
      try {
        const r = await fetch('api/gateways/' + encodeURIComponent(this.gwEdit.id), { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.gwEdit.open = false; await this.loadGateways();
      } catch (e) { this.gwErr = e.message; }
    },

    async deleteGateway(gw) {
      if (!this.canWrite()) { this.gwErr = 'Enable writes (ALLOW_WRITES) to remove a gateway.'; return; }
      if (!await this.$store.app.confirmDialog(`Remove gateway "${gw.label}"?`, { danger: true })) return;
      try {
        const r = await fetch('api/gateways/' + encodeURIComponent(gw.id), { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        await this.loadGateways();
      } catch (e) { this.gwErr = e.message; }
    },

    async reload() {
      try {
        const r = await fetch('api/settings' + this.$store.app.gwQuery());
        if (r.ok) {
          this.cfg = await r.json();
          this.syncForm();
        }
      } catch (e) {
        console.warn('[Bridge] settings load failed:', e.message);
      }
    },

    // Copy the current effective values into the editable form.
    syncForm() {
      this.form.allow_writes = !!(this.cfg.control && this.cfg.control.allow_writes);
      this.form.log_level = (this.cfg.control && this.cfg.control.log_level) || 'info';
      this.form.ha_notify = !!(this.cfg.notifications && this.cfg.notifications.ha_notify);
      this.form.ha_url = (this.cfg.notifications && this.cfg.notifications.ha_url) || '';
      const pr = this.cfg.prices || {};                 // price events (#582)
      this.form.price_spike_c = pr.price_spike_c || '';
      this.form.price_spike_entity = pr.price_spike_entity || '';
      this.form.demand_window_entity = pr.demand_window_entity || '';
      const loc = this.cfg.location || {};
      this.form.pv_latitude = loc.latitude ?? '';
      this.form.pv_longitude = loc.longitude ?? '';
      this.form.pv_kwp = loc.pv_kwp ?? '';
      this.form.pv_tilt = loc.pv_tilt ?? '';
      this.form.pv_azimuth = loc.pv_azimuth ?? '';
      this.derivedPvKwp = (typeof loc.derived_pv_kwp === 'number' && loc.derived_pv_kwp > 0)
        ? loc.derived_pv_kwp : null;
      this.loadNemSpot();
      this.form.dispatch_interrupt_policy =
        (this.cfg.scheduler && this.cfg.scheduler.dispatch_interrupt_policy) || 'release';
      this.form.ha_token = '';   // write-only: never populated from the API; blank = keep
    },

    /** Check the stored credentials with one real login. The result IS the answer —
     *  a wrong password must read differently from an unreachable cloud. */
    async testCloud() {
      this.cloudTesting = true; this.cloudResult = null;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 30000);   // never spin forever on a hung cloud
      try {
        const r = await fetch('api/cloud/validate', { method: 'POST', signal: ctrl.signal });
        this.cloudResult = await r.json();
      } catch (e) {
        this.cloudResult = (e.name === 'AbortError')
          ? { state: 'error', error: 'Timed out after 30s waiting for the FranklinWH cloud — try again.' }
          : { state: 'error', error: e.message };
      } finally { clearTimeout(timer); this.cloudTesting = false; }
    },

    cloudShowPw: false,
    //: The account hold (server-side, persisted): FranklinWH rejected a sign-in, so none is
    //  sent until the owner clears it. Editing the fields does not lift it (2026-10-21).
    get cloudBlocked() { return !!this.cfg?.cloud?.hold?.active; },

    async clearCloudHold() {
      const ok = await this.$store.app.confirmDialog(
        'Clear the cloud sign-in hold?\n\nFranklinWH said: "' + (this.cfg?.cloud?.hold?.message || '')
        + '"\n\nOnly clear it after you have signed in to the FranklinWH app with the same email and '
        + 'password. Another wrong password may lock the account, the FranklinWH app included.',
        { title: 'Clear cloud sign-in hold', danger: true });
      if (!ok) return;
      try {
        await fetch('api/cloud/hold/clear', { method: 'POST' });
        this.$store.app.toast('Hold cleared — one sign-in is allowed', 'info');
      } finally { await this.reload(); }
    },

    /** Sign in with the typed credentials and store them only if that works (#248). */
    async saveCloud() {
      if (this.cloudBlocked) return;
      this.cloudTesting = true; this.cloudResult = null;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 45000);
      try {
        const r = await fetch('api/setup/cloud', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal,
          body: JSON.stringify({ email: this.form.fwh_cloud_email.trim(),
                                 password: this.form.fwh_cloud_password,
                                 gateway: (this.form.fwh_cloud_gateway || '').trim() || null,
                                 save: true }),
        });
        const d = await r.json().catch(() => ({ ok: false, detail: 'HTTP ' + r.status }));
        if (!r.ok && !('ok' in d)) d.detail = d.detail || ('HTTP ' + r.status);
        this.cloudResult = d.ok ? { state: 'valid' } : { state: 'error', error: d.detail };
        if (!d.ok) await this.reload();   // pick up a hold the server just set
        this.$store.app.toast(d.detail || (d.ok ? 'Saved' : 'Not saved'), d.ok ? 'success' : 'error');
        if (d.ok) {
          this.form.fwh_cloud_password = '';
          if (d.gateway) this.form.fwh_cloud_gateway = d.gateway;
          await this.reload();
        }
      } catch (e) {
        this.cloudResult = { state: 'error', error: e.name === 'AbortError'
          ? 'Timed out waiting for the FranklinWH cloud — try again.' : e.message };
      } finally { clearTimeout(timer); this.cloudTesting = false; }
    },

    get cloudOk() { return (this.cloudResult || this.cfg.cloud?.auth || {}).state === 'valid'; },

    cloudMessage() {
      const a = this.cloudResult || this.cfg.cloud?.auth || {};
      return {
        valid: 'Connected — cloud features are enabled.',
        unconfigured: 'Not configured — cloud features are disabled.',
        locked: 'Locked after repeated failures. Re-enter the password to clear it.',
        invalid: `Rejected: ${a.error || 'check the email and password'}`,
        unknown: 'Not checked yet — press Test.',
      }[a.state] || (a.error || 'Unknown state.');
    },

    async save() {
      this.saving = true;
      try {
        const body = {
          allow_writes: this.form.allow_writes,
          log_level: this.form.log_level,
          ha_notify: this.form.ha_notify,
          ha_url: this.form.ha_url,
        };
        // Only send the token if the user typed one — blank means "keep the existing".
        if (this.form.ha_token) body.ha_token = this.form.ha_token;
        const r = await fetch('api/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const d = await r.json();
        if (r.ok) {
          this.cfg = d;
          this.syncForm();
          Alpine.store('app').toast('Settings saved', 'info');
        } else {
          Alpine.store('app').toast(d.detail || 'Save failed', 'error');
        }
      } catch (e) {
        Alpine.store('app').toast('Save failed: ' + e.message, 'error');
      } finally {
        this.saving = false;
      }
    },

    runtimeLabel(rt) {
      return { ha_addon: 'Home Assistant add-on', docker: 'Docker (standalone)',
               dev: 'Development' }[rt] || (rt || '—');
    },

    // ── Local history (#540): on/off and how long it is kept ────────────────
    history: { info: {}, busy: false, confirmOff: false, msg: null },
    async loadHistory() {
      try { this.history.info = await (await fetch('api/metrics/info')).json(); } catch (e) { /* leave last-known */ }
    },
    async setHistory(change) {
      this.history.busy = true;
      this.history.msg = null;
      try {
        const r = await fetch('api/metrics/settings', { method: 'PUT',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(change) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || 'HTTP ' + r.status);
        this.history.info = d;
        this.history.confirmOff = false;
        const days = d.retention_days;
        this.history.msg = { kind: 'ok', text: ('bms_keep_days' in change || 'bms_max_mb' in change)
          ? `Battery recordings: kept ${d.bms_keep_days} days, up to ${d.bms_max_mb} MB.`
          : 'enabled' in change
          ? (d.enabled ? 'Local history is on.' : 'Local history is off. What is stored is kept.')
          : 'Kept for ' + (days ? (days % 365 ? days + ' days' : (days / 365) + (days === 365 ? ' year' : ' years')) : 'ever') + '.' };
      } catch (e) {
        this.history.msg = { kind: 'danger', text: 'Not changed: ' + e.message };
      } finally { this.history.busy = false; }
    },
    /** The database size now and how fast it grows, so the choice is an informed one. */
    historySize() {
      const i = this.history.info;
      if (i.db_bytes == null) return '';
      const mb = (i.db_bytes / 1048576).toFixed(1);
      const g = i.growth || {};
      if (!g.measured) return `Database ${mb} MB now. How fast it grows shows once it has recorded for a while.`;
      // measured here: full resolution for the first days, then 5-minute rows
      const days = i.retention_days, full = i.full_resolution_days || 10;
      const whenFull = Math.round(g.recent_mb_day * Math.min(days || full, full)
                                  + g.older_mb_day * Math.max(0, days - full));
      const total = days ? ` About ${whenFull} MB per gateway when full.` : ' With Forever it keeps growing at the older-day rate.';
      return `Database ${mb} MB now. Per gateway, the last ${full} days take about ${g.recent_mb_day} MB a day and older days about ${g.older_mb_day} MB a day (measured here).${total}`;
    },

    /** Persist ONE whitelisted setting immediately (auto-save). Everything the
     *  user can change here now applies on change — no separate Save step. */
    async syncLocation() {
      try {
        const r = await fetch('api/solar/sync-location' + this.$store.app.gwQuery(), { method: 'POST' });
        const d = await r.json();
        if (r.ok) {
          this.form.pv_latitude = d.latitude; this.form.pv_longitude = d.longitude;
          Alpine.store('app').toast('Location synced from gateway' + (d.postcode ? ' (postcode ' + d.postcode + ')' : ''), 'success');
        } else Alpine.store('app').toast('Sync failed: ' + (d.detail || r.status), 'error');
      } catch (e) { Alpine.store('app').toast('Sync failed: ' + e.message, 'error'); }
    },
    async loadNemSpot() {
      this.loadHaPriceOpts();   // friendly HA price-entity names for the global card pickers
      try {
        const r = await (await fetch('api/tariff/spot')).json();
        this.nemSpot = r;
        this.form.nem_region = r.configured_region || '';
        if (r.ha) { this.form.tariff_price_entity = r.ha.price_entity || ''; this.form.tariff_feedin_entity = r.ha.feedin_entity || ''; }
        if (this.priceSrc !== 'ha' || this.form.tariff_price_entity)
          this.priceSrc = this.form.tariff_price_entity ? 'ha' : (this.form.nem_region ? 'nem' : 'off');
      } catch (e) { /* optional */ }
    },
    async saveOne(patch) {
      try {
        const r = await fetch('api/settings', { method: 'PUT',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        Alpine.store('app').toast('Saved', 'success');
      } catch (e) { Alpine.store('app').toast('Save failed: ' + e.message, 'error'); }
    },
    async testNotify() {
      this.testing = true;
      try {
        const r = await fetch('api/notify/test', { method: 'POST' });
        const d = await r.json();
        Alpine.store('app').toast(d.detail, d.ok ? 'info' : 'error');
      } catch (e) {
        Alpine.store('app').toast('Test notification failed: ' + e.message, 'error');
      } finally {
        this.testing = false;
      }
    },

    // ── Auto-notify triggers (FEAT-NOTIFY) ─────────────────────────────────
    triggers: { config: { triggers: {}, asks: {} }, stats: [], log: [], err: '' },
    trgPick: {},   // trigger key -> "Chosen devices" picked, before any device is ticked
    async loadTriggers() {
      try {
        const d = await (await fetch('api/notify/triggers')).json();
        this.triggers.config = d.config || { triggers: {} };
        this.triggers.stats = d.stats || [];
        this.triggers.log = (await (await fetch('api/notify/log?limit=20')).json()).events || [];
      } catch (e) { /* leave last-known */ }
    },
    // A failed save says so on the page, under the rows (no toast).
    async _saveTriggers(patch) {
      try {
        const r = await fetch('api/notify/triggers', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || r.statusText);
        this.triggers.config = d.config || this.triggers.config;
        this.triggers.err = '';
      } catch (e) { this.triggers.err = 'Save failed: ' + e.message; }
    },
    toggleTrigger(key) {
      const t = this.triggers.config.triggers[key];
      this._saveTriggers({ triggers: { [key]: { enabled: !t.enabled } } });
    },
    setThreshold(key, val) {
      const n = Math.max(0, Math.min(100, parseInt(val, 10) || 0));
      this._saveTriggers({ triggers: { [key]: { threshold: n } } });
    },
    // The group heading (#581, Scheduler) before the first trigger of its group.
    triggerGroupStart(key) {
      const all = Object.entries(this.triggers.config.triggers || {});
      const i = all.findIndex(([k]) => k === key);
      const g = (all[i] || [])[1]?.group;
      return g && (i === 0 || all[i - 1][1].group !== g) ? g : '';
    },
    triggerStat(key) {
      const s = (this.triggers.stats || []).find(x => x.event === key);
      return s ? `${s.count}× · last ${this.fmtNotifyTime(s.last_ts)}` : '';
    },
    // A trigger's target (#281): all devices, or the devices chosen. Roles come later.
    triggerTargetValue(key, t) {
      return (t.target && t.target.type === 'device') || this.trgPick[key] ? 'device' : 'all';
    },
    triggerTargetIds(t) {
      return (t.target && t.target.type === 'device' && t.target.ids) || [];
    },
    setTriggerTarget(key, value) {
      this.trgPick[key] = value === 'device';
      if (value === 'all') this._saveTriggers({ triggers: { [key]: { target: { type: 'all' } } } });
    },
    // Ticking a device saves the target; the last one ticked stays (choose All instead).
    toggleTriggerDevice(key, t, id, on) {
      const ids = this.triggerTargetIds(t).filter(x => x !== id);
      if (on) ids.push(id);
      if (ids.length) this._saveTriggers({ triggers: { [key]: { target: { type: 'device', ids } } } });
    },
    // Critical alerts and Release / Keep: the same Send to, saved under asks (#281).
    setAskTarget(key, value) {
      this.trgPick['ask:' + key] = value === 'device';
      if (value === 'all') this._saveTriggers({ asks: { [key]: { target: { type: 'all' } } } });
    },
    toggleAskDevice(key, a, id, on) {
      const ids = this.triggerTargetIds(a).filter(x => x !== id);
      if (on) ids.push(id);
      if (ids.length) this._saveTriggers({ asks: { [key]: { target: { type: 'device', ids } } } });
    },
    // Send test opens a target picker; with no devices it says so and offers + Add device,
    // never a "sent to 0 devices". The result stays in the dialog (#281, #293).
    openTestDialog() {
      if (!this.notif.loaded) this.loadNotify();
      this.notif.testDlg = { to: 'all', ids: [], sending: false, msg: null };
    },
    testDialogAddDevice() { this.notif.testDlg = null; this.openAddDevice(); },
    async testTrigger() {
      const t = this.notif.testDlg; t.msg = null;
      if (t.to === 'device' && !t.ids.length) { t.msg = { kind: 'warn', text: 'Choose at least one device' }; return; }
      t.sending = true;
      try {
        const r = await fetch('api/notify/triggers/test', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(t.to === 'all' ? {} : { device_ids: t.ids }) });
        const d = await r.json();
        if (!r.ok) t.msg = { kind: 'danger', text: 'Test failed: ' + (d.detail || 'HTTP ' + r.status) };
        else if (d.sent) t.msg = { kind: 'ok', text: `Test sent to ${d.sent} of ${d.total} device(s)` };
        else t.msg = { kind: 'warn', text: d.detail || `Not delivered to any of ${d.total} device(s)` };
        await this.loadTriggers();
      } catch (e) { t.msg = { kind: 'danger', text: 'Test failed: ' + e.message }; }
      finally { t.sending = false; }
    },
    fmtNotifyTime(ts) {
      if (!ts) return '';
      try { return this.$store.app._fmtHostTime(ts, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; }
    },

    // ── Notifications check and Test critical alert (#464) ─────────────────
    async loadChecks() {
      this.notif.checksBusy = true; this.notif.checksErr = '';
      try {
        const r = await fetch('api/notify/checks');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        this.notif.checks = (await r.json()).checks || [];
      } catch (e) { this.notif.checksErr = 'Could not run the check: ' + e.message; }
      finally { this.notif.checksBusy = false; }
    },
    openTestAlert() { this.notif.ta = { steps: [], running: false, msg: null, run: 0 }; },
    closeTestAlert() { if (this.notif.ta) this.notif.ta.run++; this.notif.ta = null; this.loadChecks(); },
    async runTestAlert() {
      const ta = this.notif.ta; if (!ta) return;
      const run = ++ta.run;
      ta.running = true; ta.msg = null; ta.steps = [];
      const live = () => this.notif.ta === ta && ta.run === run;
      try {
        const r = await fetch('api/notify/test-alert', { method: 'POST' });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { ta.msg = { kind: 'danger', text: 'Test failed: ' + (d.detail || 'HTTP ' + r.status) }; return; }
        ta.steps = d.steps || []; ta.running = false;
        if (!d.request_id) return;
        const ack = ta.steps.find(s => s.id === 'ack');
        const until = Date.now() + (d.ttl_s || 300) * 1000 + 5000;
        while (Date.now() < until && live()) {
          await new Promise(res => setTimeout(res, 2000));
          if (!live()) return;
          const a = await (await fetch('api/notify/test-alert/' + d.request_id)).json().catch(() => ({}));
          if (a.answer) { ack.status = 'pass'; ack.detail = 'Acknowledged on a phone: the full path works'; return; }
          if (a.expired) break;
        }
        if (live()) { ack.status = 'fail'; ack.detail = 'No tap within ' + Math.round((d.ttl_s || 300) / 60) + ' min. Check the Button taps listener line.'; }
      } catch (e) { ta.msg = { kind: 'danger', text: 'Test failed: ' + e.message }; }
      finally { if (this.notif.ta === ta) ta.running = false; }
    },

    // ── Notifications center ───────────────────────────────────────────────
    async loadNotify() {
      try {
        const d = await (await fetch('api/ha/notify-devices')).json();
        this.notif.master = !!d.master_enabled;
        this.notif.devices = d.devices || [];
        const i = await (await fetch('api/ha/instances')).json();
        this.notif.instances = i.instances || [];
        this.notif.loaded = true;
      } catch (e) { Alpine.store('app').toast('Load notifications failed: ' + e.message, 'error'); }
    },
    async toggleMaster() {
      const next = !this.notif.master;
      this.notif.master = next; this.form.ha_notify = next;
      try {
        const r = await fetch('api/settings', { method: 'PUT',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ha_notify: next }) });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        Alpine.store('app').toast('Push notifications ' + (next ? 'enabled' : 'disabled'), 'success');
      } catch (e) { this.notif.master = !next; this.form.ha_notify = !next; Alpine.store('app').toast('Failed: ' + e.message, 'error'); }
    },
    async toggleDevice(dev) {
      try {
        const r = await fetch('api/ha/notify-devices/' + dev.id, { method: 'PATCH',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !dev.enabled }) });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        await this.loadNotify();
      } catch (e) { Alpine.store('app').toast('Failed: ' + e.message, 'error'); }
    },
    async deleteDevice(dev) {
      if (!await this.$store.app.confirmDialog(
            'Remove "' + dev.alias + '"? It will stop receiving notifications.',
            { title: 'Remove this device?', danger: true })) return;
      await fetch('api/ha/notify-devices/' + dev.id, { method: 'DELETE' });
      await this.loadNotify();
    },
    async testDevice(dev) {
      this.notif.busy = true;
      try {
        const r = await fetch('api/ha/notify-devices/test', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: dev.id }) });
        const j = await r.json();
        Alpine.store('app').toast(j.ok ? ('Sent to ' + dev.alias) : ('Failed: ' + (j.error || j.detail || 'error')), j.ok ? 'success' : 'error');
      } finally { this.notif.busy = false; }
    },
    // Yes / No test (#374): the tapped answer shows on the device's row and stays there.
    async testButtons(dev) {
      const say = (kind, text) => { this.notif.rt = { ...this.notif.rt, [dev.id]: { kind, text } }; };
      say('info', 'Sending…');
      try {
        const r = await fetch('api/ha/notify-devices/test-buttons', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: dev.id }) });
        const j = await r.json().catch(() => ({}));
        if (!j.ok) { say('danger', 'Not sent: ' + (j.error || j.detail || 'HTTP ' + r.status)); this.loadChecks(); return; }
        say('info', 'Sent — tap Yes or No on ' + dev.alias + '…');
        const until = Date.now() + (j.ttl_s || 120) * 1000 + 5000;
        while (Date.now() < until) {
          await new Promise(res => setTimeout(res, 2000));
          const a = await (await fetch('api/ha/notify-devices/test-buttons/' + j.request_id)).json().catch(() => ({}));
          if (a.answer) { say('ok', 'Round trip works: you tapped ' + (a.answer === 'YES' ? 'Yes' : 'No')); this.loadChecks(); return; }
          if (a.expired) break;
        }
        say('warn', 'No reply within ' + (j.ttl_s || 120) + ' s'); this.loadChecks();
      } catch (e) { say('danger', 'Test failed: ' + e.message); }
    },
    openAddDevice() {
      this.notif.addDev = { alias: '', instance_id: (this.notif.instances[0] || {}).id || '', service: '', kind: 'other' };
      this.notif.discovered = []; this.notif.pickerOpen = false; this.notif.addDevMsg = null;
    },
    editDevice(dev) {   // rename / re-target an existing device
      this.notif.addDev = { id: dev.id, alias: dev.alias, instance_id: dev.instance_id, service: dev.service, kind: dev.kind || 'other' };
      this.notif.discovered = []; this.notif.pickerOpen = false; this.notif.addDevMsg = null;
    },
    // Ask the CHOSEN instance, not every instance. A bridge can read several Home
    // Assistants and a notification goes to exactly one — mixing their targets in one
    // list is how a message ends up on the wrong house's phone.
    async discover() {
      this.notif.busy = true; this.notif.addDevMsg = null;
      const inst = this.notif.addDev.instance_id;
      try {
        const url = 'api/ha/notify-targets' + (inst ? '?instance=' + encodeURIComponent(inst) : '');
        const d = await (await fetch(url)).json();
        this.notif.discovered = d.targets || [];
        const err = (d.errors || {})[inst];
        if (err) { this.addDevSay('danger', 'Could not read that instance: ' + err); return; }
        if (!this.notif.discovered.length) { this.addDevSay('warn', 'No notify services found on that instance'); return; }
        this.notif.pickerSearch = ''; this.notif.pickerOpen = true;
      } catch (e) { this.addDevSay('danger', 'Discover failed: ' + e.message); }
      finally { this.notif.busy = false; }
    },
    get notifyPicker() {
      const q = this.notif.pickerSearch.trim().toLowerCase();
      return this.notif.discovered
        .map(t => ({
          service: t.service,
          label: t.friendly_name || t.name || this.friendlyService(t.service),
          kind: t.kind || 'other',
          // Home Assistant re-registers a companion app as `_2` beside the original and
          // gives no hint which is live. Last-seen IS the hint — show it, rather than
          // leaving the user to find it in a 3800-entity browser.
          seen: this.fmtSeen(t.last_updated),
          shadows: t.duplicate_of || '',
        }))
        .filter(x => !q || x.service.toLowerCase().includes(q) || x.label.toLowerCase().includes(q));
    },

    //: "2 hours ago" / "just now" / '' when Home Assistant does not report it.
    fmtSeen(iso) {
      if (!iso) return '';
      const then = Date.parse(iso);
      if (!then) return '';
      const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
      if (mins < 2) return 'seen just now';
      if (mins < 60) return `seen ${mins} min ago`;
      const hrs = Math.round(mins / 60);
      if (hrs < 48) return `seen ${hrs} h ago`;
      return `seen ${Math.round(hrs / 24)} d ago`;
    },
    friendlyService(x) { return x.replace(/^notify\./, '').replace(/mobile_app_/, '').replace(/_/g, ' '); },
    // Take Home Assistant's own friendly name across. Typing "David's iPhone 15 Pro" by
    // hand, next to a list that already says it, is work the picker should have done.
    chooseService(x, label, kind) {
      this.notif.addDev.service = x;
      if (kind) this.notif.addDev.kind = kind;
      if (!this.notif.addDev.alias && label) this.notif.addDev.alias = label;
      this.notif.pickerOpen = false;
    },

    //: Turn an instance off WITHOUT deleting it. Its devices stop being offered and stop
    //: receiving — suppression, not removal, so the aliases and the history survive a
    //: holiday, a moved server, or a token that needs replacing.
    async toggleInstance(inst) {
      try {
        const r = await fetch('api/ha/instances/' + inst.id, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !inst.enabled }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        await this.loadNotify();
        Alpine.store('app').toast(
          `${inst.name} ${inst.enabled ? 'disabled — its devices are suppressed' : 'enabled'}`,
          'success');
      } catch (e) { Alpine.store('app').toast('Could not change it: ' + e.message, 'error'); }
    },
    addDevSay(kind, text) { this.notif.addDevMsg = { kind, text }; },
    async testNewDevice() {
      const f = this.notif.addDev;
      if (!f.instance_id || !f.service) { this.addDevSay('warn', 'Pick an instance and a notify service first'); return; }
      this.notif.busy = true; this.notif.addDevMsg = null;
      try {
        const r = await fetch('api/ha/notify-devices/test', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instance_id: f.instance_id, service: f.service }) });
        const j = await r.json().catch(() => ({}));
        if (j.ok) this.addDevSay('ok', 'Test sent to ' + f.service + ' — check your device');
        else this.addDevSay('danger', 'Test failed: ' + (j.error || j.detail || 'HTTP ' + r.status));
      } catch (e) { this.addDevSay('danger', 'Test failed: ' + e.message); }
      finally { this.notif.busy = false; }
    },
    async saveDevice() {
      const f = this.notif.addDev;
      if (!f.alias || !f.instance_id || !f.service) { this.addDevSay('warn', 'Alias, HA instance and notify service are all required'); return; }
      this.notif.addDevMsg = null;
      const editing = !!f.id;
      const url = editing ? 'api/ha/notify-devices/' + f.id : 'api/ha/notify-devices';
      const body = { alias: f.alias, instance_id: f.instance_id, service: f.service, kind: f.kind || 'other' };
      const r = await fetch(url, { method: editing ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (r.ok) { this.notif.addDev = null; await this.loadNotify(); Alpine.store('app').toast(editing ? 'Device updated' : 'Device added', 'success'); }
      else { const j = await r.json().catch(() => ({})); this.addDevSay('danger', 'Not saved: ' + (j.detail || 'HTTP ' + r.status)); }
    },
    openAddInstance() { this.notif.instMsg = null; this.notif.addInst = { name: '', base_url: '', token: '', is_default: this.notif.instances.length === 0 }; },
    async saveInstance() {
      const f = this.notif.addInst;
      // Results show in the panel, not a toast behind it (#293).
      this.notif.instMsg = null;
      if (!f.name || !f.base_url) { this.notif.instMsg = { kind: 'warn', text: 'Name and URL are required' }; return; }
      const r = await fetch('api/ha/instances', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(f) });
      if (r.ok) { this.notif.addInst = null; await this.loadNotify(); Alpine.store('app').toast('Instance added', 'success'); }
      else { const j = await r.json().catch(() => ({})); this.notif.instMsg = { kind: 'danger', text: 'Failed: ' + (j.detail || r.status) }; }
    },
    async deleteInstance(inst) {
      if (!await this.$store.app.confirmDialog(
            'Remove instance "' + inst.name + '"? Devices using it will stop working.',
            { title: 'Remove this Home Assistant?', danger: true })) return;
      await fetch('api/ha/instances/' + inst.id, { method: 'DELETE' });
      await this.loadNotify();
    },
    openBroadcast() { this.notif.bc = { title: 'FranklinWH', message: '', sending: false, msg: null }; },
    async sendBroadcast() {
      // Results show inside the dialog (#293); a toast only once it has closed.
      const b = this.notif.bc; b.msg = null;
      if (!b.message) { b.msg = { kind: 'warn', text: 'Enter a message' }; return; }
      b.sending = true;
      try {
        const r = await fetch('api/ha/notify-devices/broadcast', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: b.title, message: b.message }) });
        const j = await r.json();
        if (r.ok && j.sent) { this.notif.bc = null; Alpine.store('app').toast('Broadcast sent to ' + j.sent + ' of ' + j.total + ' device(s)', 'success'); }
        else if (r.ok) { b.msg = { kind: 'warn', text: j.detail || ('Sent to 0 of ' + j.total + ' device(s)') }; }
        else { b.msg = { kind: 'danger', text: 'Failed: ' + (j.detail || r.status) }; }
      } finally { if (this.notif.bc) b.sending = false; }
    },
  };
}
