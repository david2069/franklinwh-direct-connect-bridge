/**
 * FranklinWH Local Bridge — Settings tab.
 * Fetches the effective (masked) config from GET /api/settings and displays it. Most
 * settings come from env / add-on options and take effect on restart (read-only here).
 * A small whitelist — allow_writes / log_level / ha_notify — is live-editable and PUT
 * back to /api/settings, where it applies immediately and persists to DATA_DIR (P7).
 */
function settingsTab() {
  return {
    support: null, supportText: '', supportBusy: false, supportCopied: false,
    apowerSpecs: [], apowerModel: '', apowerCount: 1,
    haPriceOpts: [],   // {id:'ha:<inst>:<eid>', label:friendly, group:instance}
    cfg: { connection: {}, mqtt: {}, control: {}, notifications: {},
           metrics: {}, environment: {} },
    // Live-editable mirror of the whitelisted fields (bound to the inputs).
    form: { allow_writes: false, log_level: 'info', ha_notify: true, ha_url: '', ha_token: '',
            fwh_cloud_email: '', fwh_cloud_password: '', fwh_cloud_gateway: '',
            pv_latitude: '', pv_longitude: '', pv_kwp: '', pv_tilt: '', pv_azimuth: '',
            nem_region: '', tariff_price_entity: '', tariff_feedin_entity: '' },
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
    // ── Automation constants (const.* sensors) ──
    constants: {}, constSpec: {}, constModes: [], constSaving: false,
    systemSetup: {}, systemSpec: {}, systemSaving: false,
    gwBusy: {},          // id -> true while a toggle/test is in flight
    gwAdd: null,         // add-form object when open, else null
    gwErr: '',

    // ── Notifications center (Energipay-style: instances + companion devices + broadcast) ──
    notif: {
      loaded: false, master: false, busy: false,
      instances: [], devices: [],
      addDev: null,
      targets: null, discovered: [], pickerOpen: false, pickerSearch: '',
      addInst: null,
      bc: null,
    },

    // ── Support info bundle (redacted; for GitHub issues) ────────────────────
    async loadApowerSpecs() {
      try {
        const d = await (await fetch('api/apower-specs' + this.$store.app.gwQuery())).json();
        this.apowerSpecs = d.models || [];
        if (d.apower_count) this.apowerCount = d.apower_count;
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
      this.supportBusy = true; this.supportCopied = false;
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
      L.push('FranklinWH Local Bridge — support info (redacted)');
      L.push(`generated: ${new Date((m.generated_at||0)*1000).toISOString()}`);
      L.push(`version: ${m.software_version}  build: ${m.build}  platform: ${m.platform}`);
      L.push(`installed: ${m.install_date||'?'}  last update: ${m.last_updated?new Date(m.last_updated*1000).toISOString().slice(0,10):'?'}  uptime: ${m.bridge_uptime_s!=null?Math.round(m.bridge_uptime_s)+'s':'?'}`);
      if ((m.updates||[]).length) L.push('updates: ' + m.updates.map(u => u.version+'@'+new Date(u.ts*1000).toISOString().slice(0,10)).join(', '));
      L.push('');
      (d.gateways||[]).forEach(g => {
        L.push(`gateway #${g.index}: ${g.model||'?'}${g.vendor_model?(' ('+g.vendor_model+')'):''}${g.is_mock?' [mock]':''}`);
        if (g.country||g.hardware_model_id!=null) L.push(`  hw_id ${g.hardware_model_id} · ${g.country||'?'} · aPowers ${g.apower_count??'?'}`);
        if (g.grid) { const gr=g.grid; L.push(`  grid: service ${gr.service_amps??'?'}A · air-switch ${gr.air_switch_amps??'?'}A · import ${gr.import_limit_w===-1?'unlimited':gr.import_limit_w} · export ${gr.grid_export_enabled?'enabled':'disabled'} (${gr.export_limit_w===-1?'unlimited':gr.export_limit_w}) · pcs-discharge ${gr.pcs_discharge_enabled?'on':'off'} · inverter ${gr.inverter_max_charge_kw??'?'}/${gr.inverter_max_discharge_kw??'?'} kW`); }
        if (g.firmware) L.push('  firmware: ' + Object.entries(g.firmware).map(([k,v])=>k+'='+v).join(' '));
        if (g.smart_circuits!=null) L.push(`  smart circuits: ${g.smart_circuits}`);
        if (g.generator) L.push(`  generator: ${g.generator.installed?('installed · '+(g.generator.mode||'?')+' · '+(g.generator.state||'?')):'not installed'}`);
        if (g.operating_mode||g.soc_pct!=null) L.push(`  mode ${g.operating_mode||'?'} · SoC ${g.soc_pct!=null?Math.round(g.soc_pct)+'%':'?'} · run ${g.run_status||'?'} · vpp ${g.cloud_vpp}`);
        if (g.contacted_at) L.push(`  last contact: ${new Date(g.contacted_at*1000).toISOString()}`);
      });
      L.push('');
      const so = d.solar||{}; if (Object.keys(so).length) L.push('solar: ' + Object.entries(so).map(([k,v])=>k+'='+v).join(' '));
      const ss = d.system_setup||{}; if (Object.keys(ss).length) L.push('system setup: ' + Object.entries(ss).map(([k,v])=>k+'='+v).join(' '));
      const it = d.integration||{}; L.push('integration: ' + Object.entries(it).map(([k,v])=>k+'='+v).join(' '));
      const b = d.billing||{}; L.push('billing: ' + Object.entries(b).map(([k,v])=>k+'='+v).join(' '));
      L.push('');
      L.push(m.note||'');
      return L.join('\n');
    },
    async copySupport() {
      if (!this.supportText) await this.loadSupportInfo();
      try { await navigator.clipboard.writeText(this.supportText); this.supportCopied = true; setTimeout(()=>this.supportCopied=false, 2000); }
      catch (e) { this.toast && this.toast('Copy failed — select the text manually', 'error'); }
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

    async init() {
      await this.reload();
      await this.loadGateways();
      await this.loadSitesMeters();
      await this.loadUtilitiesTariffs();
      await this.loadConstants();
      await this.loadSystemSetup();
      await this.loadNotify();
      // Refresh roster status periodically so "last poll"/ok stay live.
      setInterval(() => { this.loadGateways(); this.loadSitesMeters(); this.loadUtilitiesTariffs(); }, 15000);
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

    async toggleGateway(gw) {
      if (!this.canWrite()) { this.gwErr = 'Enable writes (ALLOW_WRITES) to change gateways.'; return; }
      this.gwBusy = { ...this.gwBusy, [gw.id]: true };
      try {
        const r = await fetch('api/gateways/' + encodeURIComponent(gw.id), {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !gw.enabled }) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        await this.loadGateways();
      } catch (e) { this.gwErr = e.message; }
      finally { this.gwBusy = { ...this.gwBusy, [gw.id]: false }; }
    },

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
          body: JSON.stringify({ label, host: c.host, port: 9000, enabled: true }) });
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

    openAddGateway() { this.gwErr = ''; this.scanCands = null; this.gwAdd = { label: '', host: '', port: 9000, enabled: true }; },
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
    gwEdit: { open: false, id: '', label: '', host: '', port: 9000, description: '', publish_ha: true, is_mock: false, mock_units: 1, is_default: false, meter_id: '' },
    gwTest: null, gwTesting: false,
    openEditGateway(gw) {
      this.gwErr = ''; this.gwTest = null;
      this.gwEdit = { open: true, id: gw.id, label: gw.label, host: gw.host || '', port: gw.port || 9000,
        description: gw.description || '', publish_ha: !!gw.publish_ha, is_mock: !!gw.is_mock,
        mock_units: gw.mock_units || 1, is_default: !!gw.is_default, meter_id: gw.meter_id || '' };
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
      try { const d = await (await fetch('api/system-setup' + this.$store.app.gwQuery())).json();
            this.systemSetup = d.values || {}; this.systemSpec = d.spec || {}; }
      catch { this.systemSetup = {}; }
    },
    sysDerived(k) { return !!(this.systemSetup._overridden && this.systemSetup._overridden[k] === false && this.systemSpec[k] && this.systemSpec[k].derived); },
    async saveSystemSetup() {
      if (!this.canWrite()) { this.$store.app.toast('Enable writes to save', 'error'); return; }
      this.systemSaving = true;
      try {
        const s = this.systemSetup;
        const r = await fetch('api/system-setup' + this.$store.app.gwQuery(), { method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ solar_type: s.solar_type, solar_kwp: Number(s.solar_kwp) || 0,
            generator_input: !!s.generator_input, grid_forming: !!s.grid_forming,
            whole_home_backup: !!s.whole_home_backup, load_shedding: !!s.load_shedding,
            non_backup_loads: !!s.non_backup_loads, battery_label: s.battery_label || '' }) });
        const d = await r.json(); if (!r.ok) throw new Error(d.detail || 'save failed');
        this.systemSetup = d.values || this.systemSetup;
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
    async importTariffProfile(ev) {
      const file = ev.target.files[0]; ev.target.value = '';
      if (!file) return;
      let bundle;
      try { bundle = JSON.parse(await file.text()); }
      catch (e) { this.$store.app.toast('Import failed: not valid JSON — ' + e.message, 'error'); return; }
      try {
        // preview
        const pr = await fetch('api/tariffs/import?dry_run=true', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundle) });
        const pd = await pr.json();
        if (!pr.ok) { this.$store.app.toast('Import rejected: ' + (pd.detail || pr.statusText), 'error'); return; }
        const p = pd.preview || {};
        const ok = await this.$store.app.confirmDialog(
          `Import "${p.tariff_name}"?\n\nRetailer: ${p.retailer} · Network: ${p.network}\n`
          + `Plan: ${p.plan_type} · ${p.seasons} season(s) · ${p.fixed_charges} fixed charge(s)\n`
          + `${p.timezone ? 'Timezone: ' + p.timezone + '\n' : ''}`
          + `\nCreates the utility + tariff and attaches them to the default meter.`,
          { title: 'Import tariff' });
        if (!ok) return;
        const r = await fetch('api/tariffs/import', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundle) });
        const d = await r.json();
        if (r.ok && d.ok) {
          this.$store.app.toast('Imported ' + p.retailer + ' — ' + p.tariff_name, 'success');
          await this.loadUtilitiesTariffs(); await this.loadSitesMeters();
        } else { this.$store.app.toast('Import failed: ' + (d.detail || 'error'), 'error'); }
      } catch (e) { this.$store.app.toast('Import failed: ' + e.message, 'error'); }
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
        this.haPriceOpts = (d.entities || [])
          .filter(e => ['sensor', 'number', 'input_number'].includes(e.domain))
          .map(e => ({ id: `ha:${e.instance_id}:${e.entity_id}`, label: e.name || e.entity_id, group: e.instance || 'HA' }));
      } catch (e) { this.haPriceOpts = []; }
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
      if (e.is_default) body.is_default = true;
      if (e.meter_id) body.meter_id = e.meter_id;
      try {
        const r = await fetch('api/gateways/' + encodeURIComponent(e.id), {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.gwEdit.open = false; await this.loadGateways();
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
        const r = await fetch('api/settings');
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
      const loc = this.cfg.location || {};
      this.form.pv_latitude = loc.latitude ?? '';
      this.form.pv_longitude = loc.longitude ?? '';
      this.form.pv_kwp = loc.pv_kwp ?? '';
      this.form.pv_tilt = loc.pv_tilt ?? '';
      this.form.pv_azimuth = loc.pv_azimuth ?? '';
      this.loadNemSpot();
      this.form.dispatch_interrupt_policy =
        (this.cfg.scheduler && this.cfg.scheduler.dispatch_interrupt_policy) || 'notify';
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

    metricsCaption() {
      const m = this.cfg.metrics || {};
      if (m.mode !== 'auto') return '';
      if (m.runtime === 'ha_addon' && !m.enabled)
        return 'Auto: off in the add-on because Home Assistant stores history via MQTT.';
      return 'Auto: local history is on (no Home Assistant recorder covers it).';
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
        if (r.configured_region != null) this.form.nem_region = r.configured_region;
        if (r.ha) { this.form.tariff_price_entity = r.ha.price_entity || ''; this.form.tariff_feedin_entity = r.ha.feedin_entity || ''; }
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
    triggers: { config: { triggers: {} }, stats: [], log: [] },
    async loadTriggers() {
      try {
        const d = await (await fetch('api/notify/triggers')).json();
        this.triggers.config = d.config || { triggers: {} };
        this.triggers.stats = d.stats || [];
        this.triggers.log = (await (await fetch('api/notify/log?limit=20')).json()).events || [];
      } catch (e) { /* leave last-known */ }
    },
    async _saveTriggers(patch) {
      try {
        const d = await (await fetch('api/notify/triggers', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        })).json();
        this.triggers.config = d.config || this.triggers.config;
      } catch (e) { Alpine.store('app').toast('Save failed: ' + e.message, 'error'); }
    },
    toggleTrigger(key) {
      const t = this.triggers.config.triggers[key];
      this._saveTriggers({ triggers: { [key]: { enabled: !t.enabled } } });
    },
    setThreshold(key, val) {
      const n = Math.max(0, Math.min(100, parseInt(val, 10) || 0));
      this._saveTriggers({ triggers: { [key]: { threshold: n } } });
    },
    triggerStat(key) {
      const s = (this.triggers.stats || []).find(x => x.event === key);
      return s ? `${s.count}× · last ${this.fmtNotifyTime(s.last_ts)}` : '';
    },
    async testTrigger() {
      try {
        const d = await (await fetch('api/notify/triggers/test', { method: 'POST' })).json();
        Alpine.store('app').toast(`Test sent to ${d.sent} device(s)`, d.sent ? 'success' : 'info');
        await this.loadTriggers();
      } catch (e) { Alpine.store('app').toast('Test failed: ' + e.message, 'error'); }
    },
    fmtNotifyTime(ts) {
      if (!ts) return '';
      try { return this.$store.app._fmtHostTime(ts, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; }
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
      if (!confirm('Remove "' + dev.alias + '"?')) return;
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
    openAddDevice() {
      this.notif.addDev = { alias: '', instance_id: (this.notif.instances[0] || {}).id || '', service: '' };
      this.notif.discovered = []; this.notif.pickerOpen = false;
    },
    editDevice(dev) {   // rename / re-target an existing device
      this.notif.addDev = { id: dev.id, alias: dev.alias, instance_id: dev.instance_id, service: dev.service };
      this.notif.discovered = []; this.notif.pickerOpen = false;
    },
    async discover() {
      this.notif.busy = true;
      try {
        if (!this.notif.targets) this.notif.targets = await (await fetch('api/ha/notify-targets')).json();
        this.notif.discovered = (this.notif.targets.targets || [])
          .filter(t => !this.notif.addDev.instance_id || t.instance_id === this.notif.addDev.instance_id)
          .map(t => t.service);
        if (!this.notif.discovered.length) { Alpine.store('app').toast('No notify services found on that instance', 'warning'); return; }
        this.notif.pickerSearch = ''; this.notif.pickerOpen = true;
      } catch (e) { Alpine.store('app').toast('Discover failed: ' + e.message, 'error'); }
      finally { this.notif.busy = false; }
    },
    get notifyPicker() {
      const q = this.notif.pickerSearch.trim().toLowerCase();
      return this.notif.discovered.map(x => ({ service: x, label: this.friendlyService(x) }))
        .filter(x => !q || x.service.toLowerCase().includes(q) || x.label.toLowerCase().includes(q));
    },
    friendlyService(x) { return x.replace(/^notify\./, '').replace(/mobile_app_/, '').replace(/_/g, ' '); },
    chooseService(x) { this.notif.addDev.service = x; this.notif.pickerOpen = false; },
    async testNewDevice() {
      const f = this.notif.addDev;
      if (!f.instance_id || !f.service) { Alpine.store('app').toast('Pick an instance and service first', 'warning'); return; }
      this.notif.busy = true;
      try {
        const r = await fetch('api/ha/notify-devices/test', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instance_id: f.instance_id, service: f.service }) });
        const j = await r.json();
        Alpine.store('app').toast(j.ok ? 'Test sent — check your device' : ('Failed: ' + (j.error || j.detail || 'error')), j.ok ? 'success' : 'error');
      } finally { this.notif.busy = false; }
    },
    async saveDevice() {
      const f = this.notif.addDev;
      if (!f.alias || !f.instance_id || !f.service) { Alpine.store('app').toast('Alias, instance and service are required', 'warning'); return; }
      const editing = !!f.id;
      const url = editing ? 'api/ha/notify-devices/' + f.id : 'api/ha/notify-devices';
      const body = { alias: f.alias, instance_id: f.instance_id, service: f.service };
      const r = await fetch(url, { method: editing ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (r.ok) { this.notif.addDev = null; await this.loadNotify(); Alpine.store('app').toast(editing ? 'Device updated' : 'Device added', 'success'); }
      else { const j = await r.json().catch(() => ({})); Alpine.store('app').toast('Failed: ' + (j.detail || r.status), 'error'); }
    },
    openAddInstance() { this.notif.addInst = { name: '', base_url: '', token: '', is_default: this.notif.instances.length === 0 }; },
    async saveInstance() {
      const f = this.notif.addInst;
      if (!f.name || !f.base_url) { Alpine.store('app').toast('Name and URL are required', 'warning'); return; }
      const r = await fetch('api/ha/instances', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(f) });
      if (r.ok) { this.notif.addInst = null; await this.loadNotify(); Alpine.store('app').toast('Instance added', 'success'); }
      else { const j = await r.json().catch(() => ({})); Alpine.store('app').toast('Failed: ' + (j.detail || r.status), 'error'); }
    },
    async deleteInstance(inst) {
      if (!confirm('Remove instance "' + inst.name + '"? Devices using it will stop working.')) return;
      await fetch('api/ha/instances/' + inst.id, { method: 'DELETE' });
      await this.loadNotify();
    },
    openBroadcast() { this.notif.bc = { title: 'FranklinWH', message: '', sending: false }; },
    async sendBroadcast() {
      const b = this.notif.bc; if (!b.message) { Alpine.store('app').toast('Enter a message', 'warning'); return; }
      b.sending = true;
      try {
        const r = await fetch('api/ha/notify-devices/broadcast', { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: b.title, message: b.message }) });
        const j = await r.json();
        if (r.ok) { Alpine.store('app').toast('Broadcast sent to ' + j.sent + ' of ' + j.total + ' device(s)', j.sent ? 'success' : 'warning'); this.notif.bc = null; }
        else { Alpine.store('app').toast('Failed: ' + (j.detail || r.status), 'error'); }
      } finally { if (this.notif.bc) b.sending = false; }
    },
  };
}
