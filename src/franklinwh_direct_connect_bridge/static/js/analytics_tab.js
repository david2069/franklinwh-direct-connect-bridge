/**
 * Analytics tab — power & state history from the bridge's SQLite store (/api/metrics).
 * Range presets + a custom date-and-time range, multi-metric selection, line/area, a stats
 * strip, and CSV/JSON export (via /api/admin/metrics/export). Chart.js is bundled globally.
 *
 * Time handling (#144, #145): every time on this tab is in the SELECTED gateway's site
 * zone ($store.app.siteTzOffsetMin, read from the aGate), falling back to the browser's
 * zone only when the gateway cannot say. The x axis is a real time axis (linear, in epoch
 * seconds), so spacing is proportional to time and a stretch with no samples shows as a
 * gap; lines are straight between samples, never smoothed.
 */

/** Tick steps the time axis may use, in seconds (all divide a day, or are whole days). */
const ANALYTICS_STEPS = [900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800];

function analyticsTab() {
  return {
    ranges: [
      { key: '24h', label: '24h', hours: 24 },
      { key: '3d', label: '3d', hours: 72 },
      { key: '7d', label: '7d', hours: 168 },
      { key: '30d', label: '30d', hours: 720 },
    ],
    metricDefs: [
      { key: 'soc', label: 'SoC', color: '#34d399', pct: true },
      { key: 'grid_w', label: 'Grid', color: '#f87171' },
      { key: 'solar_w', label: 'Solar', color: '#fbbf24' },
      { key: 'battery_w', label: 'Battery', color: '#22d3ee' },
      { key: 'load_w', label: 'Home', color: '#a78bfa' },
      { key: 'generator_w', label: 'Generator', color: '#94a3b8' },
    ],
    metrics: { soc: true, grid_w: true, solar_w: true, battery_w: true, load_w: true, generator_w: false },
    // the period, remembered in this browser like the Cloud view's
    range: (() => { try { const r = localStorage.getItem('fwh-analytics-range'); return ['24h', '3d', '7d', '30d'].includes(r) ? r : '24h'; } catch (e) { return '24h'; } })(),
    custom: false,
    customStart: '',      // 'YYYY-MM-DDTHH:MM', site wall-clock
    customEnd: '',
    shiftS: 0,            // a preset window moved back from now by ‹ (seconds)
    firstTs: null,        // the oldest stored sample for this gateway (epoch s)
    // line | area | bars, remembered in this browser like the Cloud view's style
    chartType: (() => { try { const t = localStorage.getItem('fwh-analytics-style'); return ['line', 'area', 'bars'].includes(t) ? t : 'area'; } catch (e) { return 'area'; } })(),
    series: [],
    bucketS: null,        // the server's bucket size for the loaded series
    win: null,            // the {start, end} the loaded series was asked for
    loading: false,
    _chart: null,
    // Local (this bridge's samples) or Cloud (the FranklinWH cloud's history, #215).
    source: (() => { try { return localStorage.getItem('fwh-analytics-source') === 'cloud' ? 'cloud' : 'local'; } catch (e) { return 'local'; } })(),
    _cloud: null,

    init() {
      this.resetCustom();
      // A zone that arrives (or changes with the gateway) after the first draw re-labels it.
      this.$watch('$store.app.siteTzOffsetMin', () => {
        // Defaults set before the zone arrived were in the browser's zone: redo them,
        // unless a custom range is in use.
        if (!this.custom) this.resetCustom();
        this.render();
      });
      this.$watch('$store.app.selectedGateway', () => {
        if (this.$store.app.activeTab !== 'analytics') return;
        if (this.source === 'cloud') { if (this._cloud) this._cloud.reload(); } else this.load();
      });
      lazyTab(this, 'analytics', () => (this.source === 'cloud' ? this.mountCloud() : this.load()));
    },

    setSource(src) {
      this.source = src;
      try { localStorage.setItem('fwh-analytics-source', src); } catch (e) { /* private mode */ }
      if (src === 'cloud') this.mountCloud(); else this.load();
    },

    /** Settings → Integrations, scrolled to the FranklinWH Cloud API card. */
    openCloudSettings() {
      Alpine.store('app').setActiveTab('settings');
      window.dispatchEvent(new CustomEvent('fwh-open-settings', { detail: { sub: 'integrations', card: 'settings-cloud-api' } }));
    },

    /** The shared cloud panel, mounted once; it reads the gateway picked in the top bar. */
    mountCloud() {
      if (this._cloud || !window.FWHCloudAnalytics) return;
      this._cloud = FWHCloudAnalytics.mount(this.$refs.cloud, {
        endpoint: 'api/analytics/cloud',
        params: () => ({ gateway: this.$store.app.selectedGateway || '' }),
      });
    },

    // ---- site-zone helpers ------------------------------------------------------------
    /** Site UTC offset in minutes; the browser's own offset when the gateway can't say. */
    get offMin() {
      const o = this.$store.app.siteTzOffsetMin;
      return o == null ? -new Date().getTimezoneOffset() : o;
    },
    get zoneLabel() {
      return this.$store.app.siteTzLabel || 'browser time';
    },
    /** Site wall-clock fields of an epoch-seconds ts (read with getUTC*). */
    siteDate(ts) { return new Date((ts + this.offMin * 60) * 1000); },
    /** 'YYYY-MM-DDTHH:MM' in site wall-clock → epoch seconds, or NaN. */
    fromSiteLocal(str) {
      const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(str || '');
      if (!m) return NaN;
      return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 1000 - this.offMin * 60;
    },
    /** Epoch seconds → 'YYYY-MM-DDTHH:MM' in site wall-clock (for the inputs). */
    toSiteLocal(ts) { return this.siteDate(ts).toISOString().slice(0, 16); },
    hhmm(ts) { return this.siteDate(ts).toISOString().slice(11, 16); },
    // In the browser's own date format (5 Nov, Nov 5); siteDate's UTC fields are the site's
    // wall clock, so it is formatted as UTC.
    dayLabel(ts, year) {
      return new Intl.DateTimeFormat(undefined, Object.assign({ day: 'numeric', month: 'short', timeZone: 'UTC' },
        year ? { year: 'numeric' } : {})).format(this.siteDate(ts));
    },
    stamp(ts) { return this.dayLabel(ts) + ' ' + this.hhmm(ts); },

    /** Custom range defaults: today 00:00 → now, in the site zone. */
    resetCustom() {
      const now = Math.floor(Date.now() / 1000);
      const today = this.toSiteLocal(now).slice(0, 10);
      this.customStart = today + 'T00:00';
      this.customEnd = this.toSiteLocal(now);
    },

    get rangeHours() {
      const w = this.window;
      return Math.max(1, Math.round((w.end - w.start) / 3600));
    },
    get rangeLabel() {
      if (this.custom) {
        const w = this.window;
        return this.stamp(w.start) + ' → ' + this.stamp(w.end);
      }
      return (this.ranges.find(r => r.key === this.range) || this.ranges[0]).label;
    },
    get customValid() {
      const s = this.fromSiteLocal(this.customStart), e = this.fromSiteLocal(this.customEnd);
      return isFinite(s) && isFinite(e) && e > s;
    },
    get window() {
      const now = Math.floor(Date.now() / 1000);
      if (this.custom && this.customValid) {
        return { start: this.fromSiteLocal(this.customStart), end: this.fromSiteLocal(this.customEnd) };
      }
      const h = (this.ranges.find(r => r.key === this.range) || this.ranges[0]).hours;
      return { start: now - this.shiftS - h * 3600, end: now - this.shiftS };
    },

    setRange(k) {
      this.range = k; this.custom = false; this.shiftS = 0;
      try { localStorage.setItem('fwh-analytics-range', k); } catch (e) { /* private mode */ }
      this.load();
    },
    /** The period dropdown: a preset, or Custom (which starts from the window shown). */
    setPeriod(v) {
      if (v !== 'custom') { this.setRange(v); return; }
      const w = this.window;
      this.customStart = this.toSiteLocal(w.start);
      this.customEnd = this.toSiteLocal(w.end);
      this.custom = true;
    },
    /** The site day the shown window ends on, for the day picker. */
    get endDay() { return this.toSiteLocal(this.window.end - 1).slice(0, 10); },
    get today() { return this.toSiteLocal(Math.floor(Date.now() / 1000)).slice(0, 10); },
    /** The day picker: the same-length window, ending at the end of that day (or now). */
    jumpTo(day) {
      if (!day) return;
      const now = Math.floor(Date.now() / 1000), w = this.window, span = w.end - w.start;
      const end = Math.min(now, this.fromSiteLocal(day + 'T00:00') + 86400);
      if (this.custom) {
        this.customStart = this.toSiteLocal(end - span);
        this.customEnd = this.toSiteLocal(end);
      } else {
        this.shiftS = Math.max(0, now - end);
      }
      this.load();
    },
    refresh() { if (this.source === 'cloud') { if (this._cloud) this._cloud.reload(); } else this.load(); },
    /** ‹ / ›: the window before or after this one, the same length. */
    stepWindow(dir) {
      const w = this.window, span = w.end - w.start;
      if (this.custom) {
        const now = Math.floor(Date.now() / 1000);
        const end = Math.min(now, w.end + dir * span);
        this.customStart = this.toSiteLocal(end - span);
        this.customEnd = this.toSiteLocal(end);
      } else {
        this.shiftS = Math.max(0, this.shiftS - dir * span);
      }
      this.load();
    },
    /** Back to the window that ends now. */
    goToday() { this.custom = false; this.shiftS = 0; this.load(); },
    get atToday() {
      return this.custom ? this.window.end >= Math.floor(Date.now() / 1000) - 120 : this.shiftS === 0;
    },
    get atOldest() {
      return this.firstTs != null && this.window.start <= this.firstTs;
    },
    applyCustom() {
      if (!this.customValid) {
        this.$store.app.toast('"To" must be after "From"', 'error');
        return;
      }
      this.custom = true;
      this.load();
    },
    setChartType(t) {
      this.chartType = t;
      try { localStorage.setItem('fwh-analytics-style', t); } catch (e) { /* private mode */ }
      this.render();
    },
    toggleMetric(k) { this.metrics[k] = !this.metrics[k]; this.render(); },

    async load() {
      this.loading = true;
      try {
        const w = this.window;
        const url = `api/metrics?start=${w.start}&end=${w.end}&points=400`
          + this.$store.app.gwQuery('&');
        const d = await (await fetch(url)).json();
        this.series = (d && d.series) || [];
        this.bucketS = (d && d.bucket_s) || null;
        this.firstTs = (d && d.first_ts) || null;
        this.win = w;
        this.render();
      } catch (e) {
        this.series = [];
        this.$store.app.toast('History load failed: ' + e.message, 'error');
      } finally { this.loading = false; }
    },

    /** Points for one metric, with a null wherever samples are missing, so the line breaks
     *  instead of being drawn straight across the gap. */
    pointsFor(key) {
      const out = [];
      const gap = (this.bucketS || 60) * 2.5;
      let prev = null;
      for (const p of this.series) {
        if (prev != null && p.ts - prev > gap) out.push({ x: prev + (this.bucketS || 60), y: null });
        out.push({ x: p.ts, y: p[key] == null ? null : p[key] });
        prev = p.ts;
      }
      return out;
    },

    /** Tick positions aligned to the site's clock (00:00, 06:00, …), at most ~8. */
    ticksFor(start, end) {
      const span = Math.max(1, end - start);
      const step = ANALYTICS_STEPS.find(s => span / s <= 8) || ANALYTICS_STEPS[ANALYTICS_STEPS.length - 1];
      const off = this.offMin * 60;
      const out = [];
      for (let t = Math.ceil((start + off) / step) * step - off; t <= end; t += step) out.push(t);
      return { step, ticks: out };
    },

    render() {
      this.$nextTick(() => {
        const el = this.$refs.canvas;
        if (!el || !window.Chart) return;
        const w = this.win || this.window;
        const { step, ticks } = this.ticksFor(w.start, w.end);
        const self = this;
        // Bars draw each bucket's power as a bar; SoC (its own % axis) stays a line.
        const bars = this.chartType === 'bars';
        const datasets = this.metricDefs.filter(m => this.metrics[m.key]).map(m => ({
          type: bars && !m.pct ? 'bar' : 'line',
          order: m.pct ? 0 : 1,
          label: m.label,
          data: this.pointsFor(m.key),
          borderColor: m.color,
          backgroundColor: this.chartType === 'area' ? m.color + '26' : m.color,
          fill: this.chartType === 'area' && !m.pct,
          yAxisID: m.pct ? 'y1' : 'y',
          borderWidth: 1.5, pointRadius: 0,
          tension: 0,          // straight between samples: smoothing invented shapes (#145)
          spanGaps: false,     // a missing stretch stays a gap
        }));
        const cfg = {
          type: 'line',
          data: { datasets },
          options: {
            responsive: true, maintainAspectRatio: false, animation: false, parsing: true,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            plugins: {
              legend: { display: false },
              tooltip: {
                enabled: true,
                callbacks: { title: (items) => items.length ? self.stamp(items[0].parsed.x) : '' },
              },
            },
            scales: {
              x: {
                type: 'linear', min: w.start, max: w.end,
                afterBuildTicks: (axis) => { axis.ticks = ticks.map(v => ({ value: v })); },
                ticks: {
                  color: '#64748b', font: { size: 10 }, maxRotation: 0, autoSkip: false,
                  // HH:MM, with the short date on a second line where the day changes;
                  // whole-day steps show the date only.
                  callback: (v, i) => {
                    if (step >= 86400) return self.dayLabel(v);
                    const newDay = i === 0 || self.dayLabel(ticks[i - 1]) !== self.dayLabel(v);
                    return newDay ? [self.hhmm(v), self.dayLabel(v)] : self.hhmm(v);
                  },
                },
                grid: { color: 'rgba(148,163,184,.08)' },
              },
              y: { position: 'left', title: { display: true, text: 'W', color: '#64748b' },
                   ticks: { color: '#64748b', font: { size: 10 } },
                   grid: { color: 'rgba(148,163,184,.08)' } },
              y1: { position: 'right', min: 0, max: 100,
                    title: { display: true, text: 'SoC %', color: '#34d399' },
                    ticks: { color: '#34d399', font: { size: 10 } }, grid: { drawOnChartArea: false } },
            },
          },
        };
        if (this._chart) this._chart.destroy();
        this._chart = new Chart(el, cfg);
      });
    },

    /** What the chart actually shows: samples, bucket, first → last, and the zone. */
    get caption() {
      const s = this.series;
      if (!s.length) return '';
      const b = this.bucketS;
      const bucket = !b ? '' : b < 3600 ? ` · ${Math.round(b / 60)}-min buckets` : ` · ${+(b / 3600).toFixed(1)}-h buckets`;
      let txt = `${s.length} points${bucket} · data ${this.stamp(s[0].ts)} → ${this.stamp(s[s.length - 1].ts)}`
        + ` · ${this.zoneLabel}`;
      const w = this.win;
      if (w && b && s[0].ts - w.start > 2 * b) txt += ` · no data before ${this.stamp(s[0].ts)}`;
      if (this.firstTs) txt += ` · history from ${this.dayLabel(this.firstTs, true)}`;
      return txt;
    },

    get stats() {
      const s = this.series;
      if (!s.length) return [];
      const nums = (k) => s.map(p => p[k]).filter(v => typeof v === 'number');
      const avg = (a) => a.length ? Math.round(a.reduce((x, y) => x + y, 0) / a.length) : null;
      const socs = nums('soc');
      const grid = nums('grid_w');
      const fmtW = (v) => v == null ? '–' : (Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + ' kW' : v + ' W');
      return [
        { label: 'Avg SoC', value: socs.length ? Math.round(avg(socs)) + '%' : '–' },
        { label: 'Peak solar', value: fmtW(Math.max(0, ...nums('solar_w'))) },
        { label: 'Peak home', value: fmtW(Math.max(0, ...nums('load_w'))) },
        { label: 'Peak grid import', value: fmtW(Math.max(0, ...grid)) },
      ];
    },

    exportData(fmt) {
      // Cloud: the shared panel downloads the period it shows.
      if (this.source === 'cloud') { if (this._cloud) this._cloud.exportData(fmt); return; }
      // The same window the chart shows, not "the last N hours" (#145).
      const w = this.win || this.window;
      window.location = `api/admin/metrics/export?fmt=${fmt}&start=${w.start}&end=${w.end}`
        + this.$store.app.gwQuery('&');
    },
  };
}
