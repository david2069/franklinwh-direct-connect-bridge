/**
 * Analytics tab — power & state history from the bridge's SQLite store (/api/metrics).
 * The Cloud view's periods (one picker for both, owner 2026-11-09) stepped by site day,
 * week, month or year; multi-metric selection, line/area/bars, a stats strip, and CSV/JSON
 * export (via /api/admin/metrics/export). Chart.js is bundled globally.
 *
 * Time handling (#144, #145): every time on this tab is in the SELECTED gateway's site
 * zone ($store.app.siteTzOffsetMin, read from the aGate), falling back to the browser's
 * zone only when the gateway cannot say. The x axis is a real time axis (linear, in epoch
 * seconds), so spacing is proportional to time and a stretch with no samples shows as a
 * gap; lines are straight between samples, never smoothed.
 */

/** Tick steps the time axis may use, in seconds (all divide a day, or are whole days). */
const ANALYTICS_STEPS = [900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800];

/** The Cloud view's periods, used for Local too (the shared panel's own list once loaded). */
const ANALYTICS_PERIODS =
  [['day5', 'Day (5-min)'], ['dayhour', 'Day (hourly)'], ['week', 'Week'], ['month', 'Month'],
   ['year', 'Year'], ['lifetime', 'Lifetime']];

/** The window a period covers on the site's calendar, as the Cloud view reads it: the day
 *  of `day` ('YYYY-MM-DD'), its Monday-to-Monday week, its month or its year; lifetime is
 *  the oldest stored sample to now. Epoch seconds, plus how finely to read it. */
function analyticsPeriodWindow(period, day, offMin, now, firstTs) {
  if (period === 'lifetime') return { start: Math.min(firstTs || now - 86400, now - 3600), end: now, points: 400 };
  let [y, mo, d] = day.split('-').map(Number);
  mo -= 1;
  if (period === 'week') d -= (new Date(Date.UTC(y, mo, d)).getUTCDay() + 6) % 7;
  if (period === 'month' || period === 'year') d = 1;
  if (period === 'year') mo = 0;
  const at = (yy, mm, dd) => Date.UTC(yy, mm, dd) / 1000 - offMin * 60;     // site midnight
  const start = at(y, mo, d);
  const end = period === 'year' ? at(y + 1, 0, 1) : period === 'month' ? at(y, mo + 1, 1)
    : at(y, mo, d + (period === 'week' ? 7 : 1));
  const read = period === 'day5' ? { bucket: 300 }
    : period === 'year' ? { points: 400 } : { bucket: 3600 };
  return Object.assign({ start, end }, read);
}

/** The same period one step earlier (dir -1) or later (+1), as a site day. */
function analyticsStepDay(period, day, dir) {
  const [y, mo, d] = day.split('-').map(Number);
  const t = period === 'year' ? Date.UTC(y + dir, 0, 1)
    : period === 'month' ? Date.UTC(y, mo - 1 + dir, 1)
    : Date.UTC(y, mo - 1, d + dir * (period === 'week' ? 7 : 1));
  return new Date(t).toISOString().slice(0, 10);
}

function analyticsTab() {
  return {
    periods: (window.FWHCloudAnalytics && FWHCloudAnalytics.PERIODS) || ANALYTICS_PERIODS,
    metricDefs: [
      { key: 'soc', label: 'SoC', color: '#34d399', pct: true },
      { key: 'grid_w', label: 'Grid', color: '#f87171' },
      { key: 'solar_w', label: 'Solar', color: '#fbbf24' },
      { key: 'battery_w', label: 'Battery', color: '#22d3ee' },
      { key: 'load_w', label: 'Home', color: '#a78bfa' },
      { key: 'generator_w', label: 'Generator', color: '#94a3b8' },
    ],
    metrics: { soc: true, grid_w: true, solar_w: true, battery_w: true, load_w: true, generator_w: false },
    // the period, one for Local and Cloud, remembered in this browser
    period: (() => { try { const p = localStorage.getItem('fwh-analytics-period'); return ANALYTICS_PERIODS.some(x => x[0] === p) ? p : 'day5'; } catch (e) { return 'day5'; } })(),
    day: null,            // the site day the shown period holds ('YYYY-MM-DD'); null = today
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
      // A zone that arrives (or changes with the gateway) after the first draw moves the
      // site's midnights: read the period again.
      this.$watch('$store.app.siteTzOffsetMin', () => { if (this.win && this.source === 'local') this.load(); });
      this.$watch('$store.app.selectedGateway', () => {
        if (this.$store.app.activeTab !== 'analytics') return;
        if (this.source === 'cloud') { if (this._cloud) this._cloud.reload(); } else this.load();
      });
      lazyTab(this, 'analytics', () => (this.source === 'cloud' ? this.mountCloud() : this.load()));
    },

    setSource(src) {
      this.source = src;
      try { localStorage.setItem('fwh-analytics-source', src); } catch (e) { /* private mode */ }
      if (src === 'cloud') { this.mountCloud(); if (this._cloud) this._cloud.setPeriod(this.period); } else this.load();
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
        periodPicker: false, period: this.period,        // the picker at the top serves both
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
    monthLabel(ts, year) {
      return new Intl.DateTimeFormat(undefined, Object.assign({ month: 'short', timeZone: 'UTC' },
        year ? { year: '2-digit' } : {})).format(this.siteDate(ts));
    },

    get today() { return this.toSiteLocal(Math.floor(Date.now() / 1000)).slice(0, 10); },
    get window() {
      return analyticsPeriodWindow(this.period, this.day || this.today, this.offMin,
        Math.floor(Date.now() / 1000), this.firstTs);
    },
    /** The first day of the shown period, for the day picker (as the Cloud view shows it). */
    get startDay() { return this.toSiteLocal(this.window.start).slice(0, 10); },

    /** The time span picker: one for both views. */
    setPeriod(v) {
      this.period = v;
      try { localStorage.setItem('fwh-analytics-period', v); } catch (e) { /* private mode */ }
      if (this.source === 'cloud') { if (this._cloud) this._cloud.setPeriod(v); } else this.load();
    },
    /** The day picker: the period that holds that day. */
    jumpTo(day) {
      if (!day) return;
      this.day = day > this.today ? null : day;
      this.load();
    },
    refresh() { if (this.source === 'cloud') { if (this._cloud) this._cloud.reload(); } else this.load(); },
    /** ‹ / ›: the day, week, month or year before or after this one. */
    stepWindow(dir) {
      const d = analyticsStepDay(this.period, this.startDay, dir);
      this.day = d > this.today ? null : d;
      this.load();
    },
    /** Back to the period that holds today. */
    goToday() { this.day = null; this.load(); },
    get atToday() { return this.window.end > Math.floor(Date.now() / 1000); },
    get atOldest() {
      return this.firstTs != null && this.window.start <= this.firstTs;
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
        const url = `api/metrics?start=${w.start}&end=${w.end}`
          + (w.bucket ? `&bucket=${w.bucket}` : `&points=${w.points}`) + this.$store.app.gwQuery('&');
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

    /** Tick positions aligned to the site's clock (00:00, 06:00, …), at most `max` (fewer
     *  on a phone, so the labels don't run together). */
    ticksFor(start, end, max = 8) {
      const span = Math.max(1, end - start);
      const off = this.offMin * 60;
      const out = [];
      if (span > 62 * 86400) {
        // a year or more: ticks on the 1st of every one, two, three … months
        const s = this.siteDate(start), e = this.siteDate(end);
        const months = (e.getUTCFullYear() - s.getUTCFullYear()) * 12 + e.getUTCMonth() - s.getUTCMonth() + 1;
        const k = Math.max(1, Math.ceil(months / max));
        for (let i = 0; i <= months; i += k) {
          const t = Date.UTC(s.getUTCFullYear(), s.getUTCMonth() + i, 1) / 1000 - off;
          if (t >= start && t <= end) out.push(t);
        }
        return { step: 2592000, ticks: out };
      }
      const step = ANALYTICS_STEPS.find(s => span / s <= max) || ANALYTICS_STEPS[ANALYTICS_STEPS.length - 1];
      for (let t = Math.ceil((start + off) / step) * step - off; t <= end; t += step) out.push(t);
      return { step, ticks: out };
    },

    render() {
      this.$nextTick(() => {
        const el = this.$refs.canvas;
        if (!el || !window.Chart) return;
        const w = this.win || this.window;
        const max = Math.max(3, Math.min(8, Math.floor((el.parentElement.clientWidth || 800) / 80)));
        const { step, ticks } = this.ticksFor(w.start, w.end, max);
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
                    if (step >= 2592000) return self.monthLabel(v, w.end - w.start > 400 * 86400);
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
