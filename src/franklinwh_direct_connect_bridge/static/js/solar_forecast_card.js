/**
 * Dashboard Solar Forecast card — weather + PV production forecast (Open-Meteo).
 * Today/Tomorrow totals + peak, an hourly kW bar chart with a NOW marker, and the
 * current weather. Data from GET /api/solar/forecast (cached server-side ~15min).
 */
function solarForecastCard(tab = 'dashboard') {   // the tab it refreshes on
  return {
    data: null, loading: false, error: '', _t: null,
    solarSplit: null,   // today: {home, battery, grid} kWh (where actual solar went)
    chargeBand: [],     // per-bar (aligned to bars): 'charge'|'discharge'|'idle'|null — what the battery did
    // #676, as the Energipays Bridge's card: today's actual solar and the temperature
    // drawn over the bars, each with its toggle (remembered in this browser).
    actualByHour: {},   // site-local hour -> actual solar kW (hourly mean of solar_w)
    showActual: (() => { try { return localStorage.getItem('fwh-solar-actual') !== '0'; } catch (e) { return true; } })(),
    showTemp: (() => { try { return localStorage.getItem('fwh-solar-temp') !== '0'; } catch (e) { return true; } })(),
    tip: null,          // the bar under the pointer: {time, kw, actual, temp, x}

    async init() {
      this.$watch('$store.app.selectedGateway', () => this.load());   // its site's forecast (#675)
      await this.load();
      this._loadSolarSplit();
      this._loadChargeBand();
      this._t = setInterval(() => { if (this.$store.app.activeTab === tab) { this.load(); this._loadSolarSplit(); this._loadChargeBand(); } }, 15 * 60 * 1000);
      this._ts = setInterval(() => { if (this.$store.app.activeTab === tab) { this._loadSolarSplit(); this._loadChargeBand(); } }, 120000);
    },
    // Where today's actual solar went (solar->home/battery/grid), from the flow reconstruction.
    async _loadSolarSplit() {
      if (!this.$store.app.selectedGateway) return;   // no gateway yet: nothing to ask (#379)
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
      if (!this.$store.app.selectedGateway) return;   // no gateway yet: nothing to ask (#379)
      try {
        const now = Math.floor(Date.now() / 1000);
        const off = (this.data && this.data.utc_offset_seconds) || 0;
        const start = ((now + off) - ((now + off) % 86400)) - off;
        const r = await (await fetch(`api/metrics?start=${start}&end=${now}&bucket=3600` + this.$store.app.gwQuery('&'))).json();
        const byHour = {}, solar = {};
        for (const p of (r.series || [])) {
          if (p.ts == null) continue;
          const hr = Math.floor(((p.ts + off) % 86400) / 3600);
          const bw = p.battery_w;
          byHour[hr] = (bw == null) ? 'idle' : (bw < -50 ? 'charge' : bw > 50 ? 'discharge' : 'idle');
          if (p.solar_w != null) solar[hr] = Math.max(0, p.solar_w) / 1000;   // actual solar, kW
        }
        this.actualByHour = solar;
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
        // the picked gateway's site's location and array (#675)
        const r = await fetch('api/solar/forecast' + (force ? '?force=1' : '') + this.$store.app.gwQuery(force ? '&' : '?'));
        this.data = await r.json();
      } catch (e) { this.error = e.message; }
      finally { this.loading = false; }
    },

    toggleActual() { this.showActual = !this.showActual; try { localStorage.setItem('fwh-solar-actual', this.showActual ? '1' : '0'); } catch (e) { /**/ } },
    toggleTemp() { this.showTemp = !this.showTemp; try { localStorage.setItem('fwh-solar-temp', this.showTemp ? '1' : '0'); } catch (e) { /**/ } },
    /** Will the solar left today fill the battery? From the server (solar_fill). */
    get fill() { return (this.data && this.data.fill) || null; },

    get configured() { return !!(this.data && this.data.configured); },
    get current() { return (this.data && this.data.current) || {}; },
    get today() { return ((this.data && this.data.days) || [])[0] || null; },
    get tomorrow() { return ((this.data && this.data.days) || [])[1] || null; },

    /** Hourly bars for the chart, height as % of the peak; tagged today/tomorrow/now. */
    get bars() {
      const h = (this.data && this.data.hourly) || [];
      if (!h.length) return [];
      const max = this.maxKw;
      const todayDate = this.today ? this.today.date : (h[0].time || '').slice(0, 10);
      // Open-Meteo hourly times are LOCATION-LOCAL. Align "now" to the same clock via
      // the forecast's utc_offset (works regardless of the viewer's own timezone).
      const off = ((this.data && this.data.utc_offset_seconds) || 0) * 1000;
      const nowHr = new Date(Date.now() + off).toISOString().slice(0, 13);
      const TICKS = { 0: '12AM', 6: '6AM', 12: '12PM', 18: '6PM' };
      return h.map(x => {
        const hh = parseInt(x.time.slice(11, 13) || '0', 10);
        return {
          kw: x.kw, time: x.time, temp: x.temp_c,
          hm: x.time.slice(11, 16),            // "13:00" — PV-location local
          tick: TICKS[hh] || '',               // hour-axis label at 0/6/12/18
          h: Math.max(1, (x.kw / max) * 100),
          isToday: x.time.slice(0, 10) === todayDate,
          isNow: x.time.slice(0, 13) === nowHr,
        };
      });
    },
    /** The kW axis' top: the forecast's peak, or today's actual when that is higher. */
    get maxKw() {
      const h = (this.data && this.data.hourly) || [];
      return Math.max(0.05, ...h.map(x => x.kw || 0), ...Object.values(this.actualByHour || {}));
    },
    /** Actual solar today, as SVG points (x = bar centre %, y = % from the top). */
    get actualPoints() {
      const b = this.bars, n = b.length, max = this.maxKw, pts = [];
      b.forEach((x, i) => {
        if (!x.isToday) return;
        const hr = parseInt(x.time.slice(11, 13), 10), kw = this.actualByHour[hr];
        if (kw != null) pts.push(((i + 0.5) / n * 100).toFixed(2) + ',' + (100 - kw / max * 100).toFixed(2));
      });
      return pts.length > 1 ? pts.join(' ') : '';
    },
    /** The temperature axis: whole degrees around the 48 hours' range, or null. */
    get tempRange() {
      const t = this.bars.map(x => x.temp).filter(v => v != null);
      if (!t.length) return null;
      const lo = Math.floor(Math.min(...t)), hi = Math.ceil(Math.max(...t));
      return { lo, hi: hi > lo ? hi : lo + 1 };
    },
    get tempPoints() {
      const r = this.tempRange, b = this.bars, n = b.length;
      if (!r) return '';
      return b.map((x, i) => x.temp == null ? null
        : ((i + 0.5) / n * 100).toFixed(2) + ',' + (100 - (x.temp - r.lo) / (r.hi - r.lo) * 100).toFixed(2))
        .filter(Boolean).join(' ');
    },
    /** Now, as % across the chart: its bar plus the minutes into the hour. */
    get nowPct() {
      const b = this.bars, i = b.findIndex(x => x.isNow);
      if (i < 0) return null;
      const off = ((this.data && this.data.utc_offset_seconds) || 0) * 1000;
      const min = new Date(Date.now() + off).getUTCMinutes();
      return (i + min / 60) / b.length * 100;
    },
    hover(bar, i) {
      const hr = parseInt(bar.time.slice(11, 13), 10);
      this.tip = { time: bar.hm, kw: bar.kw, temp: bar.temp,
                   actual: bar.isToday ? this.actualByHour[hr] : null,
                   x: (i + 0.5) / this.bars.length * 100 };
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
