/**
 * Energy Costs tab — live period-to-date billing (/api/billing/overview) + closed-period
 * history (/api/billing/history). Data is priced by the gateway's meter's tariff; the tab
 * shows "not configured" when no tariff is attached.
 */
function energyCostsTab() {
  return {
    ov: null,
    history: [],
    loading: false,
    closing: false,
    expanded: {},
    modbusImport: { open: false, url: 'http://host.docker.internal:8100', user: 'admin', pass: 'admin', busy: false, preview: null },

    init() {
      // Loads on first SHOW, not on page load — see lazyTab().
      const t = lazyTab(this, 'energy_costs', () => this.load());
      this.$watch('$store.app.selectedGateway', () => t.reload());
    },

    async load() {
      this.loading = true;
      try {
        const q = this.$store.app.gwQuery('?');
        this.ov = await (await fetch('api/billing/overview' + q)).json();
        const hq = this.$store.app.gwQuery('&');
        this.history = (await (await fetch('api/billing/history?limit=60' + hq)).json()).periods || [];
      } catch (e) {
        this.$store.app.toast('Billing load failed: ' + e.message, 'error');
      } finally { this.loading = false; }
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
    exportCsv() { window.location = 'api/billing/history?fmt=csv' + this.$store.app.gwQuery('&'); },

    // One-click import of closed periods from a Modbus bridge (login → fetch → map → store).
    openModbusImport() { this.modbusImport.open = true; this.modbusImport.preview = null; },
    async doModbusFetch(dry) {
      const m = this.modbusImport;
      m.busy = true;
      try {
        const r = await (await fetch('api/billing/import-modbus' + this.$store.app.gwQuery('?'), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source_url: m.url, username: m.user, password: m.pass, dry_run: dry }),
        })).json();
        if (!r.ok) { this.$store.app.toast(r.reason || 'Import failed', 'error'); return; }
        if (dry) {
          m.preview = r;
        } else {
          this.$store.app.toast(`Imported ${r.imported} period(s)` + (r.skipped ? `, skipped ${r.skipped}` : ''), 'success');
          m.open = false;
          await this.load();
        }
      } catch (e) { this.$store.app.toast('Import failed: ' + e.message, 'error'); }
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
        const r = await (await fetch('api/billing/close' + this.$store.app.gwQuery('?'), { method: 'POST' })).json();
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
