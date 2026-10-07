/**
 * FranklinWH Local Bridge — Grid & Inverter tab (read-only).
 * Grid connection + import/export power-plane limits (install_profile / 1701) and the inverter's
 * real max charge/discharge kW (Modbus SunSpec 702). The PCS write modal (set import/export
 * limits) is a guarded phase 2 — see FEAT-GRID-PROFILE-TAB.
 */
function gridTab() {
  return {
    grid: null,
    loading: false,

    async init() {
      await this.load();
      this.$watch('$store.app.selectedGateway', () => this.load());
    },
    async load() {
      this.loading = true;
      try {
        this.grid = await (await fetch('api/grid' + this.$store.app.gwQuery('?'))).json();
      } catch (e) {
        this.$store.app.toast('Grid load failed: ' + e.message, 'error');
      } finally { this.loading = false; }
    },

    // True when the read actually returned profile data (aGate reachable). When the aGate is
    // offline the endpoint returns empties — show an unreachable state, not a wall of "–".
    get hasData() {
      const g = this.grid;
      return !!(g && (g.grid_connection.service_amps != null || g.inverter.max_charge_kw != null));
    },

    // -1 = unlimited (the FranklinWH power-plane convention); a number = a custom kW cap.
    limit(v) {
      if (v == null || v === '') return '–';
      return Number(v) < 0 ? 'Unlimited' : (v + ' kW');
    },
    // ── PCS write modal (1701 grid import/export limits) — UNVERIFIED write path ──
    modal: false,
    busy: false,
    preview: null,   // dry-run frame result
    result: null,    // write result: {ok, before, after, mismatched, cloud, ...}
    f: { imp: 'keep', impKw: 2, chg: 'keep', chgKw: 2, exp: 'keep', expKw: 3, pcs: 'keep' },

    openModal() {
      const gl = (this.grid && this.grid.grid_limits) || {};
      // Seed the kW inputs from the live values, but leave every MODE on "keep" so
      // opening the modal changes nothing until the user opts a field in.
      this.f = {
        imp: 'keep', impKw: (gl.grid_soft_limit > 0 ? gl.grid_soft_limit : 2),
        chg: 'keep', chgKw: (gl.kw_rate_power > 0 ? gl.kw_rate_power : 2),
        exp: 'keep', expKw: (gl.grid_hard_limit > 0 ? gl.grid_hard_limit : 3),
        pcs: 'keep',
      };
      this.preview = null; this.result = null; this.modal = true;
    },
    _payload() {
      const p = {}, f = this.f;
      if (f.imp === 'unlimited') p.grid_soft_limit = -1;
      else if (f.imp === 'custom') p.grid_soft_limit = Number(f.impKw);
      if (f.chg === 'unlimited') p.kw_rate_power = -1;
      else if (f.chg === 'custom') p.kw_rate_power = Number(f.chgKw);
      if (f.exp === 'off') p.export_enable = false;
      else if (f.exp === 'on_unlim') { p.export_enable = true; p.grid_hard_limit = -1; }
      else if (f.exp === 'on_custom') { p.export_enable = true; p.grid_hard_limit = Number(f.expKw); }
      if (f.pcs === 'on') p.pcs_discharge = true;
      else if (f.pcs === 'off') p.pcs_discharge = false;
      return p;
    },
    get hasChanges() { return Object.keys(this._payload()).length > 0; },
    get touchesBooleans() { const p = this._payload(); return ('export_enable' in p) || ('pcs_discharge' in p); },

    async _post(body) {
      const r = await fetch('api/grid/limits' + this.$store.app.gwQuery('?'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || r.statusText);
      return out;
    },
    async doPreview() {
      const p = this._payload();
      if (!Object.keys(p).length) return;
      this.busy = true; this.result = null;
      try { this.preview = await this._post({ ...p, dry_run: true }); }
      catch (e) { this.$store.app.toast('Preview failed: ' + e.message, 'error'); }
      finally { this.busy = false; }
    },
    async doWrite() {
      const p = this._payload();
      if (!Object.keys(p).length) return;
      const ok = await this.$store.app.confirmDialog(
        'UNVERIFIED write to cmdType 1701. On this firmware it may be silently ignored, OR it may STOP grid export/discharge. A read-back re-reads 1701 to show what actually changed.\n\nProceed?',
        { title: 'Write grid limits?', danger: true });
      if (!ok) return;
      this.busy = true; this.preview = null;
      try {
        this.result = await this._post({ ...p, confirm: true });
        await this.load();
      } catch (e) { this.$store.app.toast('Write failed: ' + e.message, 'error'); }
      finally { this.busy = false; }
    },
    async restore() {
      const b = this.result && this.result.before;
      if (!b) return;
      const p = {};
      if ('gridSoftLimit' in b) p.grid_soft_limit = b.gridSoftLimit;
      if ('gridHardLimit' in b) p.grid_hard_limit = b.gridHardLimit;
      if ('kwRatePower' in b) p.kw_rate_power = b.kwRatePower;
      if ('gridExportEnable' in b) p.export_enable = !!b.gridExportEnable;
      if ('isPcsDischgEn' in b) p.pcs_discharge = !!b.isPcsDischgEn;
      const ok = await this.$store.app.confirmDialog('Restore the previous grid-limit values?',
        { title: 'Restore previous?', danger: false });
      if (!ok) return;
      this.busy = true;
      try { this.result = await this._post({ ...p, confirm: true, cloud_crosscheck: false }); await this.load(); }
      catch (e) { this.$store.app.toast('Restore failed: ' + e.message, 'error'); }
      finally { this.busy = false; }
    },
    // Pretty label for a limit value in the verify table.
    limLabel(v) { return v === -1 ? 'Unlimited' : (v === 0 ? '0 (off)' : (v + ' kW')); },

    val(v, unit) { return (v == null || v === '') ? '–' : (v + (unit || '')); },
  };
}
