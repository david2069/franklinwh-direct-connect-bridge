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
   ['year', 'Year'], ['lifetime', 'Lifetime'], ['custom', 'Custom']];

/** A custom From-To range (owner, 2026-11-10) draws as the period its length matches, the
 *  same slots as Cloud (franklinwh-ha-cloud-analytics fetch_range): 5-minute power to 2 days,
 *  hourly kWh to 31 days, daily to a year, monthly beyond. Epoch seconds. */
function analyticsRangeKind(start, end) {
  const span = end - start;
  if (span <= 2 * 86400) return 'day5';
  if (span <= 31 * 86400) return 'dayhour';
  if (span <= 366 * 86400) return 'month';
  return 'year';
}

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

/** Where each kWh slot starts and ends: hours for Day (hourly), days for Week and Month,
 *  months for Year, years for Lifetime; epoch seconds on the site's calendar. */
function analyticsSlotEdges(period, win, offMin, now) {
  const at = (y, m, d, h) => Date.UTC(y, m, d, h || 0) / 1000 - offMin * 60;
  const f = new Date((win.start + offMin * 60) * 1000);
  const y = f.getUTCFullYear(), m = f.getUTCMonth(), d = f.getUTCDate();
  const out = [];
  if (period === 'lifetime') {
    for (let yy = y; !out.length || out[out.length - 1] <= now; yy++) out.push(at(yy, 0, 1));
    return out;
  }
  for (let i = 0; ; i++) {
    const t = period === 'dayhour' ? at(y, m, d, i) : period === 'year' ? at(y, m + i, 1) : at(y, m, d + i);
    out.push(t);
    if (t >= win.end) return out;
  }
}

/** The power/energy axis as the Cloud view draws it: zero always shown, four nice steps
 *  (1, 2, 5 × 10ⁿ) from min(0, data) to max(0, data), so both charts get the same scale. */
function analyticsYRange(values) {
  const nice = (x) => { const p = Math.pow(10, Math.floor(Math.log10(x))); const m = x / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p; };
  const v = values.filter(x => x != null && isFinite(x));
  let hi = Math.max(0, ...v), lo = Math.min(0, ...v);
  if (hi === lo) hi = lo + 1;
  const step = nice((hi - lo) / 4);
  return { min: Math.floor(lo / step) * step, max: Math.ceil(hi / step) * step, step };
}

/** Cloud's series for the kWh periods; charge and export below zero. */
const ANALYTICS_ENERGY = [
  { key: 'home', label: 'Home' },
  { key: 'solar', label: 'Solar' },
  { key: 'battery_discharge', label: 'Battery discharged' },
  { key: 'battery_charge', label: 'Battery charged', below: true },
  { key: 'grid_import', label: 'Grid imported' },
  { key: 'grid_export', label: 'Grid exported', below: true },
  { key: 'soc', label: 'SoC', pct: true },
];

/** One colour per series for Local and Cloud (owner, 2026-11-10): the defaults (Cloud's,
 * with SoC apart from the battery's greens) and presets for a dark or light background. */
const ANALYTICS_COLOURS = {
  defaults: { home: '#5b8def', solar: '#e8b100', battery_discharge: '#2fae6b', battery_charge: '#7fd1a3',
              grid_import: '#d1453b', grid_export: '#8a94a3', soc: '#d946ef', generator: '#9b6bd6' },
  dark: { home: '#60a5fa', solar: '#facc15', battery_discharge: '#22c55e', battery_charge: '#86efac',
          grid_import: '#f87171', grid_export: '#94a3b8', soc: '#e879f9', generator: '#c4b5fd' },
  light: { home: '#2563eb', solar: '#ca8a04', battery_discharge: '#15803d', battery_charge: '#4ade80',
           grid_import: '#dc2626', grid_export: '#64748b', soc: '#c026d3', generator: '#7c3aed' },
};
/** The colours dialog's rows; Local's power series share Cloud's. */
const ANALYTICS_COLOUR_ROWS = [
  ['home', 'Home'], ['solar', 'Solar'], ['battery_discharge', 'Battery discharged (Local: Battery)'],
  ['battery_charge', 'Battery charged'], ['grid_import', 'Grid imported'],
  ['grid_export', 'Grid exported (Local: Grid)'], ['soc', 'SoC'], ['generator', 'Generator'],
];
const ANALYTICS_COLOUR_OF = { load_w: 'home', solar_w: 'solar', battery_w: 'battery_discharge',
                              grid_w: 'grid_export', generator_w: 'generator' };
/** The shared panel's tokens for each colour. */
const ANALYTICS_CLOUD_VARS = {
  home: ['--ca-home'], solar: ['--ca-solar'], battery_discharge: ['--ca-battery', '--ca-battery_discharge'],
  battery_charge: ['--ca-battery_charge'], grid_import: ['--ca-grid_import'],
  grid_export: ['--ca-grid', '--ca-grid_export'], soc: ['--ca-soc'], generator: ['--ca-generator'],
};

function analyticsTab() {
  return {
    // the shared panel's periods, then Custom (a From-To range, the bridge's own picker)
    periods: ((window.FWHCloudAnalytics && FWHCloudAnalytics.PERIODS) || ANALYTICS_PERIODS)
      .filter(p => p[0] !== 'custom').concat([['custom', 'Custom']]),
    metricDefs: [
      { key: 'soc', label: 'SoC', pct: true },
      // Cloud's colours (colourOf), so a day looks the same from either source (owner, 2026-11-10)
      { key: 'grid_w', label: 'Grid' },
      { key: 'solar_w', label: 'Solar' },
      { key: 'battery_w', label: 'Battery' },
      { key: 'load_w', label: 'Home' },
      { key: 'generator_w', label: 'Generator' },
    ],
    metrics: { soc: true, grid_w: true, solar_w: true, battery_w: true, load_w: true, generator_w: false,
               home: true, solar: true, battery_discharge: true, battery_charge: true, grid_import: true, grid_export: true },
    // the period, one for Local and Cloud, remembered in this browser
    period: (() => { try { const p = localStorage.getItem('fwh-analytics-period'); return ANALYTICS_PERIODS.some(x => x[0] === p) ? p : 'day5'; } catch (e) { return 'day5'; } })(),
    day: null,            // the site day the shown period holds ('YYYY-MM-DD'); null = today
    firstTs: null,        // the oldest stored sample for this gateway (epoch s)
    // line | area | bars | flow, remembered in this browser like the Cloud view's style
    // unset: lines for Day (5-min), bars for the kWh periods, as the Cloud view does
    style: (() => { try { const t = localStorage.getItem('fwh-analytics-style'); return ['line', 'area', 'bars', 'flow'].includes(t) ? t : null; } catch (e) { return null; } })(),
    // Stacked bars (owner, 2026-11-10): sources above zero, uses below; Local and Cloud
    stacked: (() => { try { return localStorage.getItem('fwh-analytics-stacked') === '1'; } catch (e) { return false; } })(),
    // the styled date picker: open, and the day its calendar shows
    pickerOpen: false,
    pickerCursor: null,
    pickerFor: 'period',  // what the calendar picks: the period's day, or the range's From or To
    // Custom: From and To in site wall-clock ('YYYY-MM-DDTHH:MM', To not included), remembered
    range: (() => { try { const r = JSON.parse(localStorage.getItem('fwh-analytics-range') || 'null');
      return r && /^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(r.from) && /^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(r.to) ? r : null; } catch (e) { return null; } })(),
    draft: { date: null, h: '00', m: '00' },   // the From or To being picked
    rangeErr: '',
    // the series colours, remembered in this browser; the dialog that picks them
    colours: (() => {
      try { return Object.assign({}, ANALYTICS_COLOURS.defaults, JSON.parse(localStorage.getItem('fwh-analytics-colours') || '{}')); }
      catch (e) { return Object.assign({}, ANALYTICS_COLOURS.defaults); }
    })(),
    colourRows: ANALYTICS_COLOUR_ROWS,
    coloursOpen: false,
    atTime: null,         // Day views: the picker's time ('HH:MM'); the readout opens there
    // Flow (#543): the period's arcs in kWh, where they came from, and what went wrong
    flow: null,
    flowNote: '',
    flowWarn: false,
    flowErr: '',
    series: [],
    bucketS: null,        // the server's bucket size for the loaded series (power only)
    coverage: null,       // kWh periods: the share of the period with samples
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
        if (this.chartType === 'flow') this.loadFlow();
        else if (this.source === 'cloud') { if (this._cloud) this._cloud.reload(); } else this.load();
      });
      lazyTab(this, 'analytics', () => this.load());

      // The Dashboard's Energy Flow card opens its period here (#543).
      window.addEventListener('fwh-analytics-flow', (e) => {
        const d = e.detail || {};
        if (ANALYTICS_PERIODS.some(x => x[0] === d.period)) this.period = d.period;
        this.source = d.source === 'cloud' ? 'cloud' : 'local';
        this.style = 'flow';
        this.day = !d.day || d.day >= this.today ? null : d.day;
        this.loadFlow();
      });
      // the Sankey is laid out from its width: draw it again when that changes
      if (window.ResizeObserver && this.$refs.flow) {
        let last = 0;
        new ResizeObserver((e) => {
          const w = Math.round(e[0].contentRect.width);
          if (w && Math.abs(w - last) > 12) { last = w; this.drawFlow(); }
        }).observe(this.$refs.flow);
      }
    },

    setSource(src) {
      this.source = src;
      try { localStorage.setItem('fwh-analytics-source', src); } catch (e) { /* private mode */ }
      this.load();
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
        range: this.period === 'custom' ? this.rangeOrDefault : null,   // and Custom's From-To
        height: 380,                                      // as tall as the Local chart
        styleControl: false, style: this.style,           // Line | Area | Bars at the top serves both
        stackControl: false, stacked: this.stacked,       // and Stack
        navControl: false, date: this.startDay,           // and the date picker
        refreshControl: false, statusBelow: true,         // Refresh at the top; the note under the chart, as Local's
        socAxis: 'always',                                // the SoC axis every period, so the plots line up
      });
      this.applyCloudColours();
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
      if (this.period === 'custom') {
        const r = this.rangeOrDefault, end = this.fromSiteLocal(r.to);
        let start = this.fromSiteLocal(r.from);
        // the first slot starts on its own hour, midnight or 1st, as Cloud's does
        const f = this.siteDate(start), off = this.offMin * 60, k = this.kind;
        if (k === 'dayhour') start = Date.UTC(f.getUTCFullYear(), f.getUTCMonth(), f.getUTCDate(), f.getUTCHours()) / 1000 - off;
        if (k === 'month') start = Date.UTC(f.getUTCFullYear(), f.getUTCMonth(), f.getUTCDate()) / 1000 - off;
        if (k === 'year') start = Date.UTC(f.getUTCFullYear(), f.getUTCMonth(), 1) / 1000 - off;
        return { start, end, bucket: 300 };
      }
      return analyticsPeriodWindow(this.period, this.day || this.today, this.offMin,
        Math.floor(Date.now() / 1000), this.firstTs);
    },
    /** The slots drawn: the period's own, or for Custom the period its length matches. */
    get kind() {
      if (this.period !== 'custom') return this.period;
      const r = this.rangeOrDefault;
      return analyticsRangeKind(this.fromSiteLocal(r.from), this.fromSiteLocal(r.to));
    },
    /** Custom's range; until one is picked, yesterday and today. */
    get rangeOrDefault() {
      if (this.range) return this.range;
      const y = new Date(Date.parse(this.today + 'T00:00:00Z') - 86400000).toISOString().slice(0, 10);
      const t = new Date(Date.parse(this.today + 'T00:00:00Z') + 86400000).toISOString().slice(0, 10);
      return { from: y + 'T00:00', to: t + 'T00:00' };
    },
    /** How a From or To reads on its button: 5 Nov 2026 22:00. */
    rangeLabel(v) {
      const [y, m, d] = v.slice(0, 10).split('-').map(Number);
      return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
        .format(new Date(Date.UTC(y, m - 1, d))) + ' ' + v.slice(11, 16);
    },
    /** From or To: the calendar opens on its day, the time grid on its time. */
    openRange(which) {
      const v = this.rangeOrDefault[which];
      this.draft = { date: v.slice(0, 10), h: v.slice(11, 13), m: v.slice(14, 16) };
      this.rangeErr = '';
      if (this.pickerOpen && this.pickerFor === which) { this.pickerOpen = false; return; }
      this.pickerFor = which; this.pickerCursor = this.draft.date; this.pickerOpen = true;
    },
    /** Apply: the range picked, shown at once on Local and Cloud; To must be after From. */
    applyRange() {
      const v = `${this.draft.date}T${this.draft.h}:${this.draft.m}`;
      const r = Object.assign({}, this.rangeOrDefault, { [this.pickerFor]: v });
      if (r.to <= r.from) { this.rangeErr = 'To must be after From.'; return; }
      this.range = r; this.rangeErr = ''; this.pickerOpen = false;
      try { localStorage.setItem('fwh-analytics-range', JSON.stringify(r)); } catch (e) { /* private mode */ }
      this.load();
    },
    /** The first day of the shown period, for the day picker (as the Cloud view shows it). */
    get startDay() { return this.toSiteLocal(this.window.start).slice(0, 10); },

    /** The time span picker: one for both views. */
    setPeriod(v) {
      this.period = v;
      try { localStorage.setItem('fwh-analytics-period', v); } catch (e) { /* private mode */ }
      this.load();
    },
    /** The day picker: the period that holds that day. */
    jumpTo(day) {
      if (!day) return;
      this.day = day > this.today ? null : day;
      this.load();
    },
    refresh() {
      if (this.chartType === 'flow') this.loadFlow(true);
      else if (this.source === 'cloud') { if (this._cloud) this._cloud.reload(); } else this.load();
    },
    /** ‹ / ›: the day, week, month or year before or after this one. */
    stepWindow(dir) {
      const d = analyticsStepDay(this.period, this.startDay, dir);
      this.day = d > this.today ? null : d;
      this.load();
    },
    /** Back to the period that holds today. */
    goToday() { this.day = null; this.load(); },
    get atToday() { return this.window.end > Math.floor(Date.now() / 1000); },
    get atOldest() {     // this bridge's history; the cloud's goes further back
      return this.source === 'local' && this.firstTs != null && this.window.start <= this.firstTs;
    },
    setChartType(t) {
      const wasFlow = this.chartType === 'flow';
      this.style = t;
      try { localStorage.setItem('fwh-analytics-style', t); } catch (e) { /* private mode */ }
      if (this._cloud && t !== 'flow') this._cloud.setStyle(t);
      if (t === 'flow') this.loadFlow();
      else if (wasFlow) this.load();
      else this.render();
    },
    toggleMetric(k) { this.metrics[k] = !this.metrics[k]; this.render(); },
    /** Day (5-min) is power in kW; the other periods are kWh per hour, day, month or year,
     *  with Cloud's series, as the Cloud view shows them (owner, 2026-11-09). */
    get energyMode() { return this.kind !== 'day5'; },
    colourOf(key) { return this.colours[ANALYTICS_COLOUR_OF[key] || key] || '#8a94a3'; },
    setColour(key, v) { this.colours[key] = v; this.saveColours(); },
    /** Dark or Light background: the preset's colours, remembered as the viewer's own. */
    useColourPreset(name) { this.colours = Object.assign({}, ANALYTICS_COLOURS[name]); this.saveColours(); },
    resetColours() {
      this.colours = Object.assign({}, ANALYTICS_COLOURS.defaults);
      try { localStorage.removeItem('fwh-analytics-colours'); } catch (e) { /* private mode */ }
      this.applyColours();
    },
    saveColours() {
      try { localStorage.setItem('fwh-analytics-colours', JSON.stringify(this.colours)); } catch (e) { /* private mode */ }
      this.applyColours();
    },
    applyColours() {
      this.applyCloudColours();
      if (this.source === 'local' && this.chartType !== 'flow' && this.series.length) this.render();
    },
    /** Cloud: the shared panel reads its series colours from --ca-* tokens. */
    applyCloudColours() {
      const el = this.$refs.cloud;
      if (!el) return;
      for (const k in ANALYTICS_CLOUD_VARS) {
        for (const v of ANALYTICS_CLOUD_VARS[k]) el.style.setProperty(v, this.colours[k]);
      }
    },
    get chips() { return this.energyMode ? ANALYTICS_ENERGY : this.metricDefs; },
    get chartType() { return this.style || (this.energyMode ? 'bars' : 'line'); },
    get unit() { return this.energyMode ? 'kWh' : 'kW'; },

    /** What the Chart button says: the type shown (Line until one is picked for a day). */
    get chartLabel() {
      const t = this.chartType;
      return t === 'flow' ? 'Flow' : t === 'area' ? 'Area' : t === 'bars' ? (this.stacked ? 'Bars stacked' : 'Bars') : 'Line';
    },
    /** Bars or Bars stacked. */
    setBars(on) { this.setStacked(on); this.setChartType('bars'); },
    setStacked(on) {
      this.stacked = on;
      try { localStorage.setItem('fwh-analytics-stacked', on ? '1' : '0'); } catch (e) { /* private mode */ }
      if (this._cloud) this._cloud.setStacked(on);
      this.render();
    },

    // ---- the date picker ------------------------------------------------------------
    /** The shown period, as the button says it: 9 Nov 2026, Week of 2 Nov 2026, October
     *  2026, 2026 (in the browser's own format). */
    get periodLabel() {
      const [y, m, d] = this.startDay.split('-').map(Number), at = new Date(Date.UTC(y, m - 1, d));
      const f = (o) => new Intl.DateTimeFormat(undefined, Object.assign({ timeZone: 'UTC' }, o)).format(at);
      if (this.period === 'year') return String(y);
      if (this.period === 'month') return f({ month: 'long', year: 'numeric' });
      const day = f({ day: 'numeric', month: 'short', year: 'numeric' });
      return this.period === 'week' ? 'Week of ' + day : day;
    },
    /** The picker takes a time on the Day views (owner, 2026-11-10), not on Flow. */
    get timeMode() { return (this.period === 'day5' || this.period === 'dayhour') && this.chartType !== 'flow'; },
    get pickerHours() { return Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0')); },
    /** Day (5-min): the minute snaps to the 5-minute slots. */
    get pickerMinutes() { return Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0')); },
    get atHour() { return this.atTime ? this.atTime.slice(0, 2) : ''; },
    get atMinute() { return this.atTime && this.period === 'day5' ? this.atTime.slice(3) : '00'; },
    /** A time picked: Day (hourly) snaps to the hour; '' clears it. */
    setAtTime(h, m) {
      this.atTime = h === '' ? null : `${h}:${this.period === 'day5' ? m || '00' : '00'}`;
      this.showAtTime();
    },
    /** The readout at the picked time, on whichever chart is shown. */
    showAtTime() {
      const t = this.timeMode ? this.atTime : null;
      if (this.source === 'cloud') { if (this._cloud && this._cloud.showAt) this._cloud.showAt(t); }
      else this.showLocalAt();
    },
    /** Local: Chart.js's own readout at the slot holding the picked time. */
    showLocalAt() {
      const c = this._chart && Alpine.raw(this._chart);   // Chart.js breaks behind Alpine's proxy
      if (!c) return;
      if (!this.timeMode || !this.atTime) { c.setActiveElements([]); c.tooltip.setActiveElements([], { x: 0, y: 0 }); c.update(); return; }
      const [h, m] = this.atTime.split(':').map(Number);
      const ts = this.window.start + h * 3600 + m * 60;
      const active = [];
      const series = Alpine.raw(this.series);
      c.data.datasets.forEach((d, di) => {
        let best = -1, gap = Infinity;
        d.data.forEach((p, i) => {
          if (p.y == null) return;
          const g = this.energyMode ? (series[i] && series[i].ts <= ts && ts < series[i].end ? 0 : Infinity) : Math.abs(p.x - ts);
          if (g < gap) { gap = g; best = i; }
        });
        if (best >= 0 && gap <= (this.energyMode ? 0 : 300)) active.push({ datasetIndex: di, index: best });
      });
      const a = c.chartArea;
      c.setActiveElements(active);
      c.tooltip.setActiveElements(active, { x: c.scales.x.getPixelForValue(ts), y: a.top + (a.bottom - a.top) / 3 });
      c.update();
    },
    get pickerMode() { return this.period === 'year' ? 'years' : this.period === 'month' ? 'months' : 'days'; },
    openPicker() { this.pickerFor = 'period'; this.pickerCursor = this.startDay; this.pickerOpen = !this.pickerOpen; },
    /** The oldest day there is: this bridge's first sample; the cloud's history is its own. */
    get minDay() { return this.source === 'local' && this.firstTs ? this.toSiteLocal(this.firstTs).slice(0, 10) : null; },
    get pickerTitle() {
      const [y, m] = (this.pickerCursor || this.startDay).split('-').map(Number);
      if (this.pickerMode === 'years') return `${y - 8} – ${y + 3}`;
      if (this.pickerMode === 'months') return String(y);
      return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(y, m - 1, 1)));
    },
    /** ‹ › inside the calendar: a month, a year, or twelve years. */
    pickerStep(dir) {
      const [y, m] = (this.pickerCursor || this.startDay).split('-').map(Number);
      const t = this.pickerMode === 'days' ? Date.UTC(y, m - 1 + dir, 1)
        : Date.UTC(y + dir * (this.pickerMode === 'years' ? 12 : 1), 0, 1);
      this.pickerCursor = new Date(t).toISOString().slice(0, 10);
    },
    get pickerAtEnd() {
      const c = this.pickerCursor || this.startDay;
      return this.pickerMode === 'days' ? c.slice(0, 7) >= this.today.slice(0, 7)
        : this.pickerMode === 'months' ? c.slice(0, 4) >= this.today.slice(0, 4) : +c.slice(0, 4) + 3 >= +this.today.slice(0, 4);
    },
    /** Six Monday-to-Sunday weeks around the cursor's month; a week period marks its week. */
    get pickerDays() {
      const [y, m] = (this.pickerCursor || this.startDay).split('-').map(Number);
      const first = Date.UTC(y, m - 1, 1), lead = (new Date(first).getUTCDay() + 6) % 7;
      const minDay = this.minDay, range = this.pickerFor !== 'period', sel = range ? this.draft.date : this.startDay;
      // To is where the range stops (not included), so it may be tomorrow's midnight
      const maxDay = this.pickerFor === 'to' ? new Date(Date.parse(this.today + 'T00:00:00Z') + 86400000).toISOString().slice(0, 10) : this.today;
      const weekEnd = analyticsStepDay('week', sel, 1);
      return Array.from({ length: 42 }, (_, i) => {
        const iso = new Date(first + (i - lead) * 86400000).toISOString().slice(0, 10);
        return { iso, d: +iso.slice(8), inMonth: +iso.slice(5, 7) === m, today: iso === this.today,
                 off: iso > maxDay || (minDay != null && iso < minDay),
                 sel: this.period === 'week' && !range ? iso >= sel && iso < weekEnd : iso === sel };
      });
    },
    get pickerMonths() {
      const y = +(this.pickerCursor || this.startDay).slice(0, 4), minDay = this.minDay;
      return Array.from({ length: 12 }, (_, i) => {
        const iso = `${y}-${String(i + 1).padStart(2, '0')}-01`;
        return { iso, label: new Intl.DateTimeFormat(undefined, { month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(y, i, 1))),
                 off: iso > this.today || (minDay != null && iso.slice(0, 7) < minDay.slice(0, 7)), sel: iso === this.startDay };
      });
    },
    get pickerYears() {
      const y = +(this.pickerCursor || this.startDay).slice(0, 4), minDay = this.minDay;
      return Array.from({ length: 12 }, (_, i) => {
        const yy = y - 8 + i, iso = `${yy}-01-01`;
        return { iso, label: String(yy), off: iso > this.today || (minDay != null && String(yy) < minDay.slice(0, 4)),
                 sel: iso === this.startDay };
      });
    },
    pick(iso) {
      if (this.pickerFor !== 'period') { this.draft.date = iso; this.rangeErr = ''; return; }   // then a time, then Apply
      this.pickerOpen = false; this.jumpTo(iso);
    },
    /** The styled time grid (owner, 2026-11-10): the Day views' time, or From / To's. */
    get gridHour() { return this.pickerFor === 'period' ? this.atHour : this.draft.h; },
    get gridMinute() { return this.pickerFor === 'period' ? this.atMinute : this.draft.m; },
    get gridMinutes() { return this.pickerFor !== 'period' || this.period === 'day5'; },
    pickHour(h) { if (this.pickerFor === 'period') this.setAtTime(h, this.atMinute); else this.draft.h = h; },
    pickMinute(m) { if (this.pickerFor === 'period') this.setAtTime(this.atHour || '00', m); else this.draft.m = m; },

    async load() {
      if (this.chartType === 'flow') return this.loadFlow();
      // Cloud: the shared panel reads the period and day picked here, in one read
      if (this.source === 'cloud') {
        if (!this._cloud) this.mountCloud();
        else if (this.period === 'custom') { this.range = this.rangeOrDefault; this._cloud.setRange(this.range.from, this.range.to); }
        else this._cloud.setPeriod(this.period, this.startDay);
        this.showAtTime();      // the package opens it again once the period has loaded
        return;
      }
      this.loading = true;
      try {
        const w = this.window;
        if (this.energyMode) {
          const edges = analyticsSlotEdges(this.kind, w, this.offMin, Math.floor(Date.now() / 1000));
          const d = await (await fetch(`api/metrics/energy?edges=${edges.join(',')}`
            + this.$store.app.gwQuery('&'))).json();
          // one row per slot that has samples: its start and end, each series' kWh, avg SoC
          this.series = ((d && d.starts) || []).map((t, i) => {
            const p = { ts: t, end: edges[i + 1], soc: d.soc[i] };
            for (const k in d.series) p[k] = d.series[k][i];
            return p;
          }).filter(p => p.solar != null);
          this.coverage = d ? d.coverage : null;
          this.bucketS = null;
          this.firstTs = (d && d.first_ts) || null;
          this.win = { start: edges[0], end: edges[edges.length - 1] };
          this.edges = edges;
          // Lifetime starts at the oldest sample, known only after the first read
          if (this.period === 'lifetime' && this.firstTs && this.firstTs < edges[0]) { this.load(); return; }
        } else {
          const url = `api/metrics?start=${w.start}&end=${w.end}`
            + (w.bucket ? `&bucket=${w.bucket}` : `&points=${w.points}`) + this.$store.app.gwQuery('&');
          const d = await (await fetch(url)).json();
          this.series = (d && d.series) || [];
          this.bucketS = (d && d.bucket_s) || null;
          this.firstTs = (d && d.first_ts) || null;
          this.win = w;
        }
        this.render();
      } catch (e) {
        this.series = [];
        this.$store.app.toast('History load failed: ' + e.message, 'error');
      } finally { this.loading = false; }
    },

    /** Points for one metric, with a null wherever samples are missing, so the line breaks
     *  instead of being drawn straight across the gap. */
    pointsFor(key) {
      const def = this.chips.find(m => m.key === key) || {};
      // Stacked bars are a balance, as Cloud draws them: home is a use, so below zero
      const below = def.below || (this.stacked && this.chartType === 'bars' && (key === 'home' || key === 'load_w'));
      // kWh: one point mid-slot; power: kW (SoC stays %)
      if (this.energyMode) {
        return this.series.map(p => ({ x: (p.ts + p.end) / 2,
          y: p[key] == null ? null : below ? -p[key] : p[key] }));
      }
      const scale = def.pct ? 1 : 1000;
      const out = [];
      const gap = (this.bucketS || 60) * 2.5;
      let prev = null;
      for (const p of this.series) {
        if (prev != null && p.ts - prev > gap) out.push({ x: prev + (this.bucketS || 60), y: null });
        out.push({ x: p.ts, y: p[key] == null ? null : (below ? -p[key] : p[key]) / scale });
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
        let { step, ticks } = this.ticksFor(w.start, w.end, max);
        // kWh slots: labelled as the Cloud view labels its bars (owner, 2026-11-10), every
        // n-th slot from the first, under the bar's middle, at most 8 (4 on a phone)
        let slotTick = null;
        if (this.energyMode && this.edges && this.edges.length > 1) {
          const e = this.edges, n = e.length - 1, every = Math.ceil(n / ((el.parentElement.clientWidth || 800) < 520 ? 4 : 8));
          slotTick = {};
          ticks = [];
          for (let i = 0; i < n; i += every) { const mid = (e[i] + e[i + 1]) / 2; ticks.push(mid); slotTick[mid] = e[i]; }
        }
        const self = this;
        // Bars draw each bucket's power as a bar; SoC (its own % axis) stays a line.
        const bars = this.chartType === 'bars', stack = bars && this.stacked;
        const datasets = this.chips.filter(m => this.metrics[m.key]).map(m => ({
          type: bars && !m.pct ? 'bar' : 'line',
          order: m.pct ? 0 : 1,
          label: m.label,
          data: this.pointsFor(m.key),
          borderColor: this.colourOf(m.key),
          backgroundColor: this.chartType === 'area' ? this.colourOf(m.key) + '26' : this.colourOf(m.key),
          fill: this.chartType === 'area' && !m.pct,
          yAxisID: m.pct ? 'y1' : 'y',
          borderWidth: 1.5, pointRadius: 0,
          tension: 0,          // straight between samples: smoothing invented shapes (#145)
          spanGaps: false,     // a missing stretch stays a gap
        }));
        const onY = datasets.filter(d => d.yAxisID === 'y');
        // stacked: the range is each slot's pile above zero and below it
        const sums = {};
        if (stack) onY.forEach(d => d.data.forEach(p => {
          if (p.y == null) return;
          const s = sums[p.x] || (sums[p.x] = [0, 0]);
          s[p.y > 0 ? 0 : 1] += p.y;
        }));
        const yr = analyticsYRange(stack ? Object.values(sums).flat() : onY.flatMap(d => d.data.map(p => p.y)));
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
                callbacks: {
                  title: (items) => !items.length ? ''
                    : self.energyMode ? self.slotLabel(self.series[items[0].dataIndex]) : self.stamp(items[0].parsed.x),
                  label: (it) => it.parsed.y == null ? null : `${it.dataset.label}: `
                    + (it.dataset.yAxisID === 'y1' ? it.parsed.y + ' %'
                      : Math.abs(it.parsed.y).toFixed(Math.abs(it.parsed.y) >= 100 ? 0 : 2) + ' ' + self.unit),
                },
              },
            },
            scales: {
              x: {
                type: 'linear', min: w.start, max: w.end, stacked: stack,
                offset: false,     // bars inside the period's edges, as the Cloud view draws them
                afterBuildTicks: (axis) => { axis.ticks = ticks.map(v => ({ value: v })); },
                ticks: {
                  color: '#64748b', font: { size: 10 }, maxRotation: 0, autoSkip: false,
                  // HH:MM, with the short date on a second line where the day changes;
                  // whole-day steps show the date only.
                  callback: (v, i) => {
                    if (slotTick && slotTick[v] != null) {
                      // a custom range in hours: the date under the time where the day changes
                      if (self.period === 'custom' && self.kind === 'dayhour'
                          && (i === 0 || self.dayLabel(slotTick[ticks[i - 1]]) !== self.dayLabel(slotTick[v]))) {
                        return [self.hhmm(slotTick[v]), self.dayLabel(slotTick[v])];
                      }
                      return self.slotTickLabel(slotTick[v]);
                    }
                    if (step >= 2592000) return self.monthLabel(v, w.end - w.start > 400 * 86400);
                    if (step >= 86400) return self.dayLabel(v);
                    const newDay = i === 0 || self.dayLabel(ticks[i - 1]) !== self.dayLabel(v);
                    return newDay ? [self.hhmm(v), self.dayLabel(v)] : self.hhmm(v);
                  },
                },
                grid: { color: 'rgba(148,163,184,.08)' },
              },
              y: { position: 'left', title: { display: true, text: self.unit, color: '#64748b' },
                   min: yr.min, max: yr.max, stacked: stack,
                   ticks: { color: '#64748b', font: { size: 10 }, stepSize: yr.step },
                   grid: { color: 'rgba(148,163,184,.08)' } },
              y1: { position: 'right', min: 0, max: 100,
                    title: { display: true, text: 'SoC %', color: self.colourOf('soc') },
                    ticks: { color: self.colourOf('soc'), font: { size: 10 } }, grid: { drawOnChartArea: false } },
            },
          },
        };
        if (this._chart) this._chart.destroy();
        this._chart = new Chart(el, cfg);
        if (this.timeMode && this.atTime) this.showLocalAt();
      });
    },

    /** A kWh slot's name in the readout: the hour, the day, the month or the year. */
    /** A kWh slot's tick, as the Cloud view writes it: 03:00, 5 Nov, Jan, 2025. */
    slotTickLabel(start) {
      if (this.kind === 'dayhour') return this.hhmm(start);
      if (this.kind === 'year') return this.monthLabel(start, this.period === 'custom');
      if (this.kind === 'lifetime') return String(this.siteDate(start).getUTCFullYear());
      return this.dayLabel(start);
    },
    slotLabel(p) {
      if (!p) return '';
      if (this.kind === 'dayhour') return this.stamp(p.ts) + '–' + this.hhmm(p.end);
      if (this.kind === 'week' || this.kind === 'month') {
        return new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
          .format(this.siteDate(p.ts));
      }
      if (this.kind === 'year') {
        return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(this.siteDate(p.ts));
      }
      return String(this.siteDate(p.ts).getUTCFullYear());
    },

    /** What the chart actually shows: samples, bucket, first → last, and the zone. */
    get caption() {
      const s = this.series;
      if (!s.length) return '';
      if (this.energyMode) {
        const noun = { dayhour: 'hour', week: 'day', month: 'day', year: 'month', lifetime: 'year' }[this.kind];
        let txt = `kWh per ${noun}, summed from this bridge's power samples (an estimate, not a meter)`
          + (this.coverage != null ? ` · samples for ${Math.round(this.coverage * 100)}% of the period` : '')
          + ` · ${this.zoneLabel}`;
        if (this.firstTs) txt += ` · history from ${this.dayLabel(this.firstTs, true)}`;
        return txt;
      }
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
      if (this.energyMode) {
        const sum = (k) => s.reduce((t, p) => t + (p[k] || 0), 0);
        const kwh = (v) => (v >= 100 ? v.toFixed(0) : v.toFixed(1)) + ' kWh';
        return [
          { label: 'Solar', value: kwh(sum('solar')) },
          { label: 'Home', value: kwh(sum('home')) },
          { label: 'Grid imported', value: kwh(sum('grid_import')) },
          { label: 'Grid exported', value: kwh(sum('grid_export')) },
        ];
      }
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

    /** Flow (#543): the period's arcs, from this bridge's samples (an estimate) or from the
     *  cloud's own breakdown (metered). */
    async loadFlow(refresh) {
      this.loading = true; this.flowErr = '';
      try {
        const w = this.window;
        if (this.source === 'cloud') {
          const r = this.rangeOrDefault;
          const what = this.period === 'custom' ? `period=custom&from=${r.from}&to=${r.to}` : `period=${this.period}&date=${this.startDay}`;
          const d = await (await fetch(`api/analytics/cloud?${what}`
            + (refresh ? '&refresh=1' : '') + this.$store.app.gwQuery('&'))).json();
          this.flowWarn = false;
          if (d.error) { this.flow = null; this.flowErr = d.error; }
          else if (!d.flows) { this.flow = null; this.flowErr = 'The cloud has no flow breakdown for this period.'; }
          else { this.flow = d.flows; this.flowNote = 'Metered by the FranklinWH cloud.'; }
        } else {
          const d = await (await fetch(`api/energy/flow?start=${w.start}&end=${w.end}`
            + this.$store.app.gwQuery('&'))).json();
          this.firstTs = d.first_ts || null;
          // Lifetime starts at the oldest sample, known only after the first read
          if (this.period === 'lifetime' && this.firstTs && this.firstTs < w.start) { await this.loadFlow(); return; }
          const q = d.quality || {}, pct = Math.round((q.coverage || 0) * 100);
          this.flow = q.samples ? d.flows : null;
          this.flowWarn = !!q.samples && pct < 95;
          if (!q.samples) this.flowErr = 'No samples recorded by this bridge for this period.';
          this.flowNote = this.flowWarn ? `Partial data: this bridge recorded ${pct}% of this period. An estimate from its power samples, not a meter.`
            : 'Estimated from this bridge\'s power samples, not a meter.';
        }
      } catch (e) {
        this.flow = null; this.flowErr = 'Energy flow unavailable: ' + e.message;
      } finally { this.loading = false; }
      this.$nextTick(() => this.drawFlow());
    },
    drawFlow() {
      const el = this.$refs.flow;
      if (!el || this.chartType !== 'flow') return;
      if (!this.flow || !window.FWHSankey) { el.innerHTML = ''; return; }
      window.FWHSankey.render(el, this.flow, { height: 380 });     // as tall as the charts
    },
    /** The node totals under the Sankey, from its arcs. */
    get flowNodes() {
      const f = this.flow || {}, g = (k) => Number(f[k]) || 0;
      return {
        solar: g('solar_to_home') + g('solar_to_battery') + g('solar_to_grid'),
        home: g('solar_to_home') + g('battery_to_home') + g('grid_to_home'),
        battery_charge: g('solar_to_battery') + g('grid_to_battery'),
        battery_discharge: g('battery_to_home') + g('battery_to_grid'),
        grid_import: g('grid_to_home') + g('grid_to_battery'),
        grid_export: g('solar_to_grid') + g('battery_to_grid'),
      };
    },
    kwh(v) { const n = Number(v) || 0; return `${n.toFixed(n >= 10 ? 1 : 2)} kWh`; },

    /** Flow: the period's totals, each arc and node in kWh. */
    exportFlow(fmt) {
      {
        if (!this.flow) return;
        const r = this.rangeOrDefault;
        const name = `fwh-flow-${this.source}-${this.period}` + (this.period === 'lifetime' ? ''
          : this.period === 'custom' ? `-${r.from.replace(':', '')}-${r.to.replace(':', '')}` : `-${this.startDay}`) + `.${fmt}`;
        const body = fmt === 'json'
          ? JSON.stringify({ source: this.source, period: this.period, start: this.startDay, unit: 'kWh',
                             flows: this.flow, nodes: this.flowNodes, note: this.flowNote }, null, 2)
          : 'item,kWh\n' + Object.entries(this.flow).concat(Object.entries(this.flowNodes))
              .map(([k, v]) => `${k},${v}`).join('\n') + '\n';
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([body], { type: (fmt === 'json' ? 'application/json' : 'text/csv') + ';charset=utf-8' }));
        a.download = name; document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      }
    },

    exportData(fmt) {
      if (this.chartType === 'flow') return this.exportFlow(fmt);
      // Cloud: the shared panel downloads the period it shows.
      if (this.source === 'cloud') { if (this._cloud) this._cloud.exportData(fmt); return; }
      // The same window the chart shows, not "the last N hours" (#145).
      const w = this.win || this.window;
      window.location = `api/admin/metrics/export?fmt=${fmt}&start=${w.start}&end=${w.end}`
        + this.$store.app.gwQuery('&');
    },
  };
}
