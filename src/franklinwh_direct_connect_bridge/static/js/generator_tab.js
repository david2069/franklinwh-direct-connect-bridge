/**
 * Generator tab — reads cmdType 1901.
 *
 * Presence is evidence-based for the same reason as smart circuits: the gateway
 * returns the 1901 block whether or not a generator module is fitted.
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('generatorTab', () => ({
    data: null, raw: null, loading: false, error: '', busy: false, showRaw: false,

    init() {
      this.$watch('$store.app.activeTab', (t) => { if (t === 'generator' && !this.data) this.load(); });
      if (this.$store.app.activeTab === 'generator') this.load();
    },

    async load() {
      this.loading = true; this.error = '';
      try {
        const r = await fetch('api/generator' + this.$store.app.gwQuery());
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.data = await r.json();
      } catch (e) { this.error = e.message; this.data = null; }
      finally { this.loading = false; }
    },

    async loadRaw() {
      this.showRaw = !this.showRaw;
      if (this.showRaw && !this.raw) {
        try { this.raw = await (await fetch('api/generator/raw' + this.$store.app.gwQuery())).json(); }
        catch (e) { this.error = e.message; }
      }
    },

    async setMode(mode) {
      if (this.busy) return;
      this.busy = true;
      try {
        const r = await fetch('api/generator/mode' + this.$store.app.gwQuery(), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode }),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        this.$store.app.toast(out.confirmed ? `Mode set to ${mode}`
          : 'Write sent but read-back did not confirm', out.confirmed ? 'success' : 'warning');
        await this.load();
      } catch (e) {
        this.$store.app.toast(`Mode change failed: ${e.message}`, 'error');
      } finally { this.busy = false; }
    },

    // ── editable config (1901 writes — hardware-verified 2026-09-14) ─────────
    editWin: null,        // {index, enabled, start, end}
    editEx: null,
    editSoc: null,

    openWindow(w) {
      this.editWin = { index: w.index, enabled: w.enabled,
                       start: w.start || '00:00', end: w.end || '00:00' };
    },
    openExercise() {
      const m = this.data.maintenance;
      this.editEx = { enabled: m.enabled, every_days: m.every_days ?? 7,
                      day: m.day ?? 0, start: m.start || '00:00',
                      minutes: m.run_minutes ?? 5 };
    },
    openSoc() {
      this.editSoc = { start_below: this.data.soc_start_pct ?? 20,
                       stop_above: this.data.soc_stop_pct ?? 80 };
    },
    closeEdit() { this.editWin = this.editEx = this.editSoc = null; },

    /** All three writes share one verdict shape: ok only when the re-read agrees. */
    async save(url, body) {
      if (this.busy) return;
      this.busy = true;
      try {
        const r = await fetch(url + this.$store.app.gwQuery(), {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        if (out.ok) this.$store.app.toast('Saved', 'success');
        else this.$store.app.toast(
          'Device accepted the write but the read-back disagreed', 'warning');
        this.closeEdit();
        await this.load();
      } catch (e) {
        this.$store.app.toast(`Save failed: ${e.message}`, 'error');
      } finally { this.busy = false; }
    },

    saveWindow() {
      const w = this.editWin;
      return this.save(`api/generator/window/${w.index}`,
        { enabled: w.enabled, start: w.start, end: w.end });
    },
    saveExercise() { return this.save('api/generator/exercise', this.editEx); },
    saveSoc() {
      const s = this.editSoc;
      if (s.stop_above <= s.start_below) {
        this.$store.app.toast('Stop SoC must be above start SoC', 'error');
        return;
      }
      return this.save('api/generator/soc', s);
    },

    /** Writes allowed AND the feature switched on — editing a disabled generator
     *  would look like it did something, and the gateway accepts it either way. */
    get canWrite() {
      return !!this.$store.app.summary.writes_enabled
        && !!(this.data && this.data.editable);
    },
    get canToggleFeature() { return !!this.$store.app.summary.writes_enabled; },

    editBlockedReason() {
      if (!this.$store.app.summary.writes_enabled) return 'Writes are disabled (ALLOW_WRITES=true)';
      if (this.data && !this.data.enabled) return 'Generator is not enabled';
      return '';
    },

    /** Mirrors the official app: you may enable it with no module wired up, so warn. */
    async setEnabled(on) {
      if (this.busy) return;
      if (on) {
        const lines = [];
        if (this.data && !this.data.configured) {
          lines.push('This gateway reports no generator hardware — no model, no rated '
            + 'power, no run state. The setting will save, but nothing will happen '
            + 'unless a module is physically installed.');
        }
        // The generator only supplies power off-grid; FranklinWH documents its SoC
        // start/stop as an off-grid behaviour. Whether enabling while ON grid takes
        // effect is untested here — say so rather than imply it works.
        lines.push('The generator is only available off-grid. You can configure it '
          + 'while on grid, but it will not run until the gateway islands.');
        lines.push('Enable it anyway?');
        const ok = await this.$store.app.confirmDialog(lines.join('\n\n'),
          { title: 'Enable generator?', danger: false });
        if (!ok) return;
      }
      this.busy = true;
      try {
        const r = await fetch('api/generator/enable' + this.$store.app.gwQuery(), {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: on }),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        this.$store.app.toast(
          out.ok ? (on ? 'Generator enabled' : 'Generator disabled')
                 : 'Write accepted but the read-back disagreed',
          out.ok ? 'success' : 'warning');
        await this.load();
      } catch (e) {
        this.$store.app.toast(`Failed: ${e.message}`, 'error');
      } finally { this.busy = false; }
    },

    fmt(v, unit, dp = 0) {
      return (v === null || v === undefined) ? '—' : `${Number(v).toFixed(dp)} ${unit}`;
    },
    get windows() { return (this.data && this.data.charge_windows) || []; },
    get rawJson() { return JSON.stringify(this.raw, null, 2); },
  }));
});
