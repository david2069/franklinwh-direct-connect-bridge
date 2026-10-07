/**
 * Solar tab — everything solar in one place.
 *
 * Exists because the firmware's naming defeats the generic Live Points view:
 * installPV1port vs PV1RatedPower, solarRelayStat (unindexed) vs loadRelay1Stat,
 * loadSolar1RatedPower vs a bare mainsSolarRatedPower. Grouping is the feature.
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('solarTab', () => ({
    ...window.liveCapMixin('solar'),
    data: null, raw: null, loading: false, error: '', showRaw: false,
    auto: false, intervalS: 10, _timer: null,

    init() {
      this.$watch('$store.app.activeTab', (t) => {
        if (t === 'solar' && !this.data) this.load();
        if (t !== 'solar') this.stopAuto();
      });
      if (this.$store.app.activeTab === 'solar') this.load();
    },

    async load() {
      this.loading = true; this.error = '';
      try {
        const r = await fetch('api/solar' + this.$store.app.gwQuery());
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.data = await r.json();
      } catch (e) { this.error = e.message; this.data = null; }
      finally { this.loading = false; }
    },

    async loadRaw() {
      this.showRaw = !this.showRaw;
      if (this.showRaw && !this.raw) {
        try { this.raw = await (await fetch('api/solar/raw' + this.$store.app.gwQuery())).json(); }
        catch (e) { this.error = e.message; }
      }
    },
    get rawJson() { return JSON.stringify(this.raw, null, 2); },

    toggleAuto() {
      this.auto = !this.auto;
      if (this.auto) { this._capStart(); this._timer = setInterval(() => this._tick(), this.intervalS * 1000); }
      else this.stopAuto();
    },
    // Auto-pause once the live session runs past the user's cap (Settings → Real-time limits).
    _tick() {
      if (this._capExpired()) { this._capTrip(); this.stopAuto(); return; }
      this.load();
    },
    _capRestart() { this.auto = true; this._timer = setInterval(() => this._tick(), this.intervalS * 1000); this.load(); },
    stopAuto() { clearInterval(this._timer); this._timer = null; this.auto = false; },

    fmtW(v)  { return (v === null || v === undefined) ? '—' : `${Math.round(v)} W`; },
    fmtKw(v) { return (v === null || v === undefined) ? '—' : `${v} kW`; },
    io(arr)  { return Array.isArray(arr) ? arr : null; },
  }));
});
