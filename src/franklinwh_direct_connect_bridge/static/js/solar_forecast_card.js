/**
 * Dashboard Solar Forecast card — weather + PV production forecast (Open-Meteo).
 * Today/Tomorrow totals + peak, an hourly kW bar chart with a NOW marker, and the
 * current weather. Data from GET /api/solar/forecast (cached server-side ~15min).
 */
function solarForecastCard() {
  return {
    data: null, loading: false, error: '', _t: null,
    solarSplit: null,   // today: {home, battery, grid} kWh (where actual solar went)
    chargeBand: [],     // per-bar (aligned to bars): 'charge'|'discharge'|'idle'|null — what the battery did

    async init() {
      await this.load();
      this._loadSolarSplit();
      this._loadChargeBand();
      this._t = setInterval(() => { if (this.$store.app.activeTab === 'dashboard') { this.load(); this._loadSolarSplit(); this._loadChargeBand(); } }, 15 * 60 * 1000);
      this._ts = setInterval(() => { if (this.$store.app.activeTab === 'dashboard') { this._loadSolarSplit(); this._loadChargeBand(); } }, 120000);
    },
    // Where today's actual solar went (solar->home/battery/grid), from the flow reconstruction.
    async _loadSolarSplit() {
      try {
        const now = Math.floor(Date.now() / 1000);
        const off = (this.data && this.data.utc_offset_seconds) || 0;   // PV-location local
        const localNow = now + off;
        const start = (localNow - (localNow % 86400)) - off;            // site-local midnight -> UTC
        const r = await (await fetch(`api/energy/flow?start=${start}&end=${now}` + this.$store.app.gwQuery('&'))).json();
        const f = (r && r.flows) || {};
        this.solarSplit = { home: f.solar_to_home || 0, battery: f.solar_to_battery || 0, grid: f.solar_to_grid || 0 };
      } catch (e) { /* optional */ }
    },
    // What the battery did today, per hour (battery_w = p_fhp: <0 charging, >0 discharging),
    // aligned to the forecast bars (today bars coloured; tomorrow bars null).
    async _loadChargeBand() {
      try {
        const now = Math.floor(Date.now() / 1000);
        const off = (this.data && this.data.utc_offset_seconds) || 0;
        const start = ((now + off) - ((now + off) % 86400)) - off;
        const r = await (await fetch(`api/metrics?start=${start}&end=${now}&bucket=3600` + this.$store.app.gwQuery('&'))).json();
        const byHour = {};
        for (const p of (r.series || [])) {
          if (p.ts == null) continue;
          const hr = Math.floor(((p.ts + off) % 86400) / 3600);
          const bw = p.battery_w;
          byHour[hr] = (bw == null) ? 'idle' : (bw < -50 ? 'charge' : bw > 50 ? 'discharge' : 'idle');
        }
        this.chargeBand = this.bars.map(b => {
          if (!b.isToday) return null;
          const hr = parseInt((b.time || '').slice(11, 13) || '-1', 10);
          return byHour[hr] != null ? byHour[hr] : null;
        });
      } catch (e) { this.chargeBand = []; }
    },

    async load(force) {
      this.loading = true; this.error = '';
      try {
        const r = await fetch('api/solar/forecast' + (force ? '?force=1' : ''));
        this.data = await r.json();
      } catch (e) { this.error = e.message; }
      finally { this.loading = false; }
    },

    get configured() { return !!(this.data && this.data.configured); },
    get current() { return (this.data && this.data.current) || {}; },
    get today() { return ((this.data && this.data.days) || [])[0] || null; },
    get tomorrow() { return ((this.data && this.data.days) || [])[1] || null; },

    /** Hourly bars for the chart, height as % of the peak; tagged today/tomorrow/now. */
    get bars() {
      const h = (this.data && this.data.hourly) || [];
      if (!h.length) return [];
      const max = Math.max(0.05, ...h.map(x => x.kw || 0));
      const todayDate = this.today ? this.today.date : (h[0].time || '').slice(0, 10);
      // Open-Meteo hourly times are LOCATION-LOCAL. Align "now" to the same clock via
      // the forecast's utc_offset (works regardless of the viewer's own timezone).
      const off = ((this.data && this.data.utc_offset_seconds) || 0) * 1000;
      const nowHr = new Date(Date.now() + off).toISOString().slice(0, 13);
      const TICKS = { 0: '12AM', 6: '6AM', 12: '12PM', 18: '6PM' };
      return h.map(x => {
        const hh = parseInt(x.time.slice(11, 13) || '0', 10);
        return {
          kw: x.kw, time: x.time,
          hm: x.time.slice(11, 16),            // "13:00" — PV-location local
          tick: TICKS[hh] || '',               // hour-axis label at 0/6/12/18
          h: Math.max(1, (x.kw / max) * 100),
          isToday: x.time.slice(0, 10) === todayDate,
          isNow: x.time.slice(0, 13) === nowHr,
        };
      });
    },
    /** Index where tomorrow begins (for the midnight divider), -1 if none. */
    get splitIndex() {
      const b = this.bars;
      return b.findIndex(x => !x.isToday);
    },

    // Actual PV generated today (aGate daily counter kwh_sun) from the live summary, vs forecast.
    get actualSolarKwh() {
      const p = this.$store.app.summary && this.$store.app.summary.power;
      return (p && p.kwh_sun != null) ? Number(p.kwh_sun) : null;
    },
    get actualPct() {
      const a = this.actualSolarKwh, f = this.today && this.today.total_kwh;
      if (a == null || !f) return null;
      return Math.round((a / f) * 100);
    },
    // Expected-so-far = sum of today's forecast hours up to & incl. "now" → ahead/behind vs actual.
    get expectedSoFarKwh() {
      let sum = 0;
      for (const x of this.bars) { if (!x.isToday) break; sum += (x.kw || 0); if (x.isNow) break; }
      return sum;
    },
    get vsExpected() {
      const a = this.actualSolarKwh, e = this.expectedSoFarKwh;
      if (a == null || e <= 0) return null;
      const pct = Math.round(((a - e) / e) * 100);
      return { pct, ahead: a >= e, label: Math.abs(pct) < 8 ? 'on track' : (a >= e ? pct + '% ahead' : Math.abs(pct) + '% behind') };
    },
    fmt(v, dp = 1) { return (v == null) ? '–' : Number(v).toFixed(dp); },
  };
}
