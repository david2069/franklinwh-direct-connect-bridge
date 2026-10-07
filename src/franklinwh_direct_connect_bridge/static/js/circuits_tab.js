/**
 * Smart Circuits tab — FEAT-SMART-CIRCUITS phase 1 (read-only + power toggle).
 *
 * Presence is decided server-side (circuits.py) and a circuit is never hidden:
 * an undetected one renders as a muted card explaining why, because "AU has two
 * circuits" and "no enclosure is installed" are different facts that look
 * identical in the 1409 payload.
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('circuitsTab', () => ({
    ...window.liveCapMixin('circuits'),
    data: null,
    loading: false,
    error: '',
    busy: {},              // circuit id -> toggle in flight
    view: 'circuits',      // 'circuits' | 'monitor'
    meter: null,           // raw 1411 for the Monitoring sub-view
    auto: false,
    intervalS: 5,
    _timer: null,

    init() {
      this.$watch('$store.app.activeTab', (t) => {
        if (t === 'circuits' && !this.data) this.load();
        if (t !== 'circuits') this.stopAuto();     // don't poll a hidden tab
      });
      if (this.$store.app.activeTab === 'circuits') this.load();
    },

    setView(v) {
      this.view = v;
      if (v === 'monitor') { if (!this.meter) this.loadMeter(); }
      else this.stopAuto();
    },

    async loadMeter() {
      try {
        const r = await fetch('api/circuits/meter' + this.$store.app.gwQuery());
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.meter = await r.json();
        this.error = '';
      } catch (e) { this.error = e.message; }
    },

    toggleAuto() {
      this.auto = !this.auto;
      if (this.auto) {
        this._capStart();
        this.loadMeter();
        this._timer = setInterval(() => this._tick(), this.intervalS * 1000);
      } else this.stopAuto();
    },
    // Auto-pause once the live session runs past the user's cap (Settings → Real-time limits).
    _tick() {
      if (this._capExpired()) { this._capTrip(); this.stopAuto(); return; }
      this.loadMeter();
    },
    _capRestart() { this.auto = true; this.loadMeter(); this._timer = setInterval(() => this._tick(), this.intervalS * 1000); },

    stopAuto() {
      clearInterval(this._timer); this._timer = null; this.auto = false;
    },

    /**
     * Rows for the Monitoring view. CarSW is labelled V2L to match the Device tab
     * and fieldschema, and the shared power/curr/volt/freq keys are grouped as
     * gateway-level — they are byte-identical in 1411 and 1901, so presenting them
     * as circuit metrics would be wrong.
     */
    get monitorGroups() {
      const m = this.meter || {}, n = (k) => (k in m ? m[k] : null);
      return [
        { title: 'Switch 1', rows: [
          ['Voltage', n('Sw1Volt'), 'V', 10], ['Current', n('SW1Curr'), 'A', 1],
          ['Power', n('SW1ExpPower'), 'W', 1], ['Energy', n('SW1ExpEnergy'), 'kWh', 100]] },
        { title: 'Switch 2', rows: [
          ['Voltage', n('Sw2Volt'), 'V', 10], ['Current', n('SW2Curr'), 'A', 1],
          ['Power', n('SW2ExpPower'), 'W', 1], ['Energy', n('SW2ExpEnergy'), 'kWh', 100]] },
        { title: 'V2L / CarSW', rows: [
          ['Current', n('CarSWCurr'), 'A', 1], ['Power', n('CarSWPower'), 'W', 1],
          ['Export', n('CarSWExpEnergy'), 'kWh', 100],
          ['Import', n('CarSWImpEnergy'), 'kWh', 100],
          ['Consumption supply', n('CarSwConsSupExpEnerge'), 'kWh', 100]] },
        { title: 'Gateway (shared, not per-circuit)', rows: [
          ['Power', n('power'), 'W', 1], ['Current', n('curr'), 'A', 1],
          ['Voltage', n('volt'), 'V', 10], ['Frequency', n('freq'), 'Hz', 10],
          ['Generator power', n('genpowerGen'), 'W', 1]] },
      ];
    },

    scaled(v, scale) {
      if (v === null || v === undefined) return '—';
      return scale === 1 ? String(v) : (v / scale).toFixed(scale === 100 ? 2 : 1);
    },

    get circuits() { return (this.data && this.data.circuits) || []; },
    get present() { return this.circuits.filter(c => c.present); },
    get absent() { return this.circuits.filter(c => !c.present); },

    raw: null,
    showRaw: false,

    async loadRaw() {
      this.showRaw = !this.showRaw;
      if (this.showRaw && !this.raw) {
        try { this.raw = await (await fetch('api/circuits/raw' + this.$store.app.gwQuery())).json(); }
        catch (e) { this.error = e.message; }
      }
    },
    get rawJson() { return JSON.stringify(this.raw, null, 2); },

    async load() {
      this.loading = true; this.error = '';
      try {
        const r = await fetch('api/circuits' + this.$store.app.gwQuery());
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.data = await r.json();
      } catch (e) { this.error = e.message; this.data = null; }
      finally { this.loading = false; }
    },

    async toggle(c) {
      if (this.busy[c.id]) return;
      this.busy = { ...this.busy, [c.id]: true };
      try {
        const r = await fetch(`api/circuits/${c.id}/power` + this.$store.app.gwQuery(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ on: !c.on }),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        // `ok` is the device's own read-back, not the HTTP status — a 200 with
        // ok:false means the write was accepted but the mode did not flip.
        if (out.ok) {
          this.$store.app.toast(`${c.name} ${!c.on ? 'on' : 'off'}`, 'success');
        } else {
          this.$store.app.toast(
            `${c.name}: write sent but read-back did not confirm`, 'warning');
        }
        await this.load();
      } catch (e) {
        this.$store.app.toast(`Toggle failed: ${e.message}`, 'error');
      } finally {
        const b = { ...this.busy }; delete b[c.id]; this.busy = b;
      }
    },

    // ── schedule editor ──────────────────────────────────────────────────────
    edit: null,            // { id, name, windows: [{enabled, start, end}, ...] }
    saving: false,

    /** Slots come back as 4 datetimes; the editor works in two HH:MM windows. */
    openEditor(c) {
      const at = (i) => {
        const s = (c.schedule[i] || {}).at;
        return s && s.includes(' ') ? s.split(' ')[1] : '';
      };
      const win = (a, b) => ({
        enabled: !!((c.schedule[a] || {}).enabled),
        start: at(a) || '00:00',
        end: at(b) || '00:00',
      });
      this.edit = { id: c.id, name: c.name, windows: [win(0, 1), win(2, 3)] };
    },

    closeEditor() { this.edit = null; },

    async saveSchedule() {
      if (this.saving) return;
      this.saving = true;
      try {
        const r = await fetch(`api/circuits/${this.edit.id}/schedule` + this.$store.app.gwQuery(), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ windows: this.edit.windows }),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        this.$store.app.toast(
          out.confirmed ? 'Schedule saved' : 'Write sent but read-back did not confirm',
          out.confirmed ? 'success' : 'warning');
        this.closeEditor();
        await this.load();
      } catch (e) {
        this.$store.app.toast(`Save failed: ${e.message}`, 'error');
      } finally { this.saving = false; }
    },

    _hm(dt) { return (dt || '').slice(11, 16) || '—'; },   // "2026-09-18 12:00" -> "12:00"
    // Pair the 4 schedule slots into on->off windows (TimeSet [1,0,1,0]); return configured
    // windows even when DISABLED so the schedule is viewable. Date is a daily-recurring
    // artifact — HH:MM only. See docs/SMART_CIRCUITS_DESIGN.md.
    schedWindows(c) {
      const s = (c && c.schedule) || [];
      const out = [];
      for (let i = 0; i + 1 < s.length; i += 2) {
        const open = s[i], close = s[i + 1];
        if (!open || !open.at || !close || !close.at) continue;
        out.push({ open: this._hm(open.at), close: this._hm(close.at), enabled: !!(open.enabled || close.enabled) });
      }
      return out;
    },
    fmtW(w)   { return w === null || w === undefined ? '—' : `${Math.round(w)} W`; },
    fmtKwh(k) { return k === null || k === undefined ? '—' : `${k.toFixed(2)} kWh`; },
    fmtV(v)   { return v === null || v === undefined ? '—' : `${v.toFixed(1)} V`; },

    reason(c) {
      const a = c.evidence_against || [];
      if (c.source === 'setting') return 'Excluded by the Smart circuits setting.';
      if (!a.length) return 'Not detected.';
      return `Not detected — ${a.join('; ')}.`;
    },
  }));
});
