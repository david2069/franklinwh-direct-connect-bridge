/**
 * Billing & Utilities (#613, #629): Summary, Bill detail, History, Plans & meters, for one
 * meter. /api/billing/page gives the meters and what is still to set up (from hems);
 * the period and history come from /api/billing/overview and /history for the meter's
 * gateway. Plans & meters is Settings' own editors (settingsTab, embedded).
 */
function energyCostsTab() {
  return {
    ov: null,
    history: [],
    loading: false,
    closing: false,
    expanded: {},
    page: { meters: [], meter: null, steps: [], complete: false },
    meterId: '',
    subTabs: [
      { key: 'summary', label: 'Summary' },
      { key: 'detail', label: 'Bill detail' },
      { key: 'history', label: 'History' },
      { key: 'plans', label: 'Plans & meters' },
    ],
    sub: (function () { try { return localStorage.getItem('fwh-billing-sub') || 'summary'; } catch (e) { return 'summary'; } })(),
    setSub(k) {
      this.sub = k;
      try { localStorage.setItem('fwh-billing-sub', k); } catch (e) { /* per-viewer only */ }
      if (k !== 'plans') this.load();
    },
    modbusImport: { open: false, url: 'http://host.docker.internal:8100', user: 'admin', pass: 'admin', busy: false, preview: null, msg: null },

    init() {
      // Loads on first SHOW, not on page load — see lazyTab().
      const t = lazyTab(this, 'energy_costs', () => this.load());
      this.$watch('$store.app.selectedGateway', () => t.reload());
    },

    // The chosen meter's gateway: billing is per meter, read through any of its gateways.
    meterGwQuery(sep) {
      const g = this.page.meter && this.page.meter.gateway_ids[0];
      return g ? `${sep}gateway=${encodeURIComponent(g)}` : this.$store.app.gwQuery(sep);
    },

    async load() {
      this.loading = true;
      try {
        const pr = await fetch('api/billing/page' + (this.meterId ? '?meter=' + encodeURIComponent(this.meterId) : ''));
        if (pr.ok) { this.page = await pr.json(); this.meterId = (this.page.meter && this.page.meter.id) || ''; }
        this.ov = await (await fetch('api/billing/overview' + this.meterGwQuery('?'))).json();
        this.history = (await (await fetch('api/billing/history?limit=60' + this.meterGwQuery('&'))).json()).periods || [];
      } catch (e) {
        this.$store.app.toast('Billing load failed: ' + e.message, 'error');
      } finally { this.loading = false; }
    },

    // A setup step's button: the editor that does it, on Plans & meters.
    doStep(st) {
      this.setSub('plans');
      const m = this.page.meter;
      setTimeout(() => window.dispatchEvent(new CustomEvent('fwh-plans-action', { detail: {
        action: st.key === 'tariffs' ? 'plan' : st.key, meter_id: m && m.id,
        site_id: m && m.site_id } })), 50);
    },

    // The last closed period, for comparison on the Summary.
    get lastPeriod() { return this.history.find(p => !this.inProgress(p)) || null; },

    // What drives the open period's lines now.
    get liveInputs() {
      const o = this.ov || {}, out = [];
      if (o['demand.peak_kw'] != null) out.push({ label: 'Demand peak so far', value: this.fmt(o['demand.peak_kw'], 2) + ' kW' });
      if (o['demand.interval_kw'] != null) out.push({ label: 'This demand interval', value: this.fmt(o['demand.interval_kw'], 2) + ' kW' });
      if (o['tariff.export_charge_free_remaining'] != null) out.push({ label: 'Free export left this period', value: this.fmt(o['tariff.export_charge_free_remaining'], 1) + ' kWh' });
      if (Number(o['energy.unpriced_import_kwh']) > 0) out.push({ label: 'Import with no rate', value: this.fmt(o['energy.unpriced_import_kwh'], 2) + ' kWh' });
      if (Number(o['energy.unpriced_export_kwh']) > 0) out.push({ label: 'Export with no rate', value: this.fmt(o['energy.unpriced_export_kwh'], 2) + ' kWh' });
      return out;
    },

    get progressPct() {
      const d = this.ov && this.ov.days_elapsed, t = this.ov && this.ov.period_days;
      if (!d || !t) return 0;
      return Math.max(0, Math.min(100, Math.round((d / t) * 100)));
    },

    //: The cost-component tiles. Each shows only when its charge type is configured.
    get breakdown() {
      const o = this.ov || {};
      const has = (k) => o[k] != null;
      return [
        { label: 'Energy import', value: this.money(o['energy.import_cost']),
          sub: this.fmt(o['energy.period_import_kwh'], 1) + ' kWh', show: has('energy.import_cost') },
        { label: 'Export credit', value: this.money(o['energy.export_credit']),
          color: '#34d399', show: has('energy.export_credit') },
        { label: 'Demand charge', value: this.money(o['demand.period_charge']),
          sub: 'peak ' + this.fmt(o['demand.peak_kw'], 1) + ' kW', show: has('demand.period_charge') },
        { label: 'Bonus credit', value: this.money(o['bonus.period_credit']),
          color: '#34d399', sub: this.fmt(o['bonus.export_kwh'], 1) + ' kWh', show: has('bonus.period_credit') },
        { label: 'Export charge', value: this.money(o['tariff.export_charge_cost']),
          sub: this.fmt(o['tariff.export_charge_net_kwh'], 1) + ' kWh billable', show: has('tariff.export_charge_cost') },
        { label: 'Fixed charges', value: this.money(o['fixed.accrued_period']),
          sub: 'of ' + this.money(o['fixed.period_total']) + ' / period', show: has('fixed.accrued_period') },
      ];
    },

    periodLabel(p) {
      const f = (ts) => { try { return new Date(ts * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' }); } catch (e) { return '?'; } };
      return f(p.period_start) + ' – ' + f(p.period_end);
    },
    exportCsv() { window.location = 'api/billing/history?fmt=csv' + this.meterGwQuery('&'); },

    // One-click import of closed periods from a Modbus bridge (login → fetch → map → store).
    openModbusImport() { this.modbusImport.open = true; this.modbusImport.preview = null; this.modbusImport.msg = null; },
    async doModbusFetch(dry) {
      const m = this.modbusImport;
      m.busy = true; m.msg = null;      // results show inside the dialog (#293)
      try {
        const r = await (await fetch('api/billing/import-modbus' + this.meterGwQuery('?'), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source_url: m.url, username: m.user, password: m.pass, dry_run: dry }),
        })).json();
        if (!r.ok) { m.msg = { kind: 'danger', text: r.reason || 'Import failed' }; return; }
        if (dry) {
          m.preview = r;
        } else {
          m.open = false;
          this.$store.app.toast(`Imported ${r.imported} period(s)` + (r.skipped ? `, skipped ${r.skipped}` : ''), 'success');
          await this.load();
        }
      } catch (e) { m.msg = { kind: 'danger', text: 'Import failed: ' + e.message }; }
      finally { m.busy = false; }
    },

    toggle(i) { this.expanded[i] = !this.expanded[i]; },
    // A snapshot whose period hasn't ended yet is a manual early close — still accruing,
    // finalised automatically at rollover.
    inProgress(p) { return !!(p && p.period_end && p.period_end * 1000 > Date.now()); },

    // Manual "close now" — snapshots the current period so its breakdown shows immediately.
    async closePeriod() {
      if (!await this.$store.app.confirmDialog(
        'Close the current billing period now? Its itemised breakdown appears in history immediately and finalises automatically at the normal rollover.', {}))
        return;
      this.closing = true;
      try {
        const r = await (await fetch('api/billing/close' + this.meterGwQuery('?'), { method: 'POST' })).json();
        if (r.ok && r.closed) { this.$store.app.toast('Current period snapshotted to history', 'success'); await this.load(); }
        else { this.$store.app.toast(r.reason || 'Nothing to close yet', 'info'); }
      } catch (e) { this.$store.app.toast('Close failed: ' + e.message, 'error'); }
      finally { this.closing = false; }
    },

    // The itemised breakdown for ONE closed period (only the components that carry a value).
    rowBreakdown(p) {
      const n = (v) => (v == null ? null : Number(v));
      const nz = (v) => n(v) != null && n(v) !== 0;
      return [
        { label: 'Energy import', value: this.money(p.import_cost), sub: p.import_kwh != null ? this.fmt(p.import_kwh, 1) + ' kWh' : null, show: n(p.import_cost) != null },
        { label: 'Export credit', value: this.money(p.export_credit), color: '#34d399', show: nz(p.export_credit) },
        { label: 'Demand charge', value: this.money(p.demand_charge), sub: p.demand_peak_kw ? 'peak ' + this.fmt(p.demand_peak_kw, 1) + ' kW' : null, show: nz(p.demand_charge) },
        { label: 'Bonus credit', value: this.money(p.bonus_credit), color: '#34d399', show: nz(p.bonus_credit) },
        { label: 'Export charge', value: this.money(p.export_charge), show: nz(p.export_charge) },
        { label: 'Fixed / standing', value: this.money(p.fixed_total), show: nz(p.fixed_total) },
      ].filter((x) => x.show);
    },

    money(v) { return (v == null) ? '–' : '$' + Number(v).toFixed(2); },
    fmt(v, dp = 1) { return (v == null) ? '–' : Number(v).toFixed(dp); },
  };
}
