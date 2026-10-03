/**
 * Analytics tab — power & state history from the bridge's SQLite store (/api/metrics).
 * Range presets + custom dates, multi-metric selection, line/area, a stats strip, and
 * CSV/JSON export (via /api/admin/metrics/export). Chart.js is bundled globally.
 */
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
    range: '24h',
    custom: false,
    customStart: '',
    customEnd: '',
    chartType: 'area',
    series: [],
    loading: false,
    _chart: null,

    async init() {
      const today = new Date();
      this.customEnd = today.toISOString().slice(0, 10);
      this.customStart = new Date(today.getTime() - 7 * 86400000).toISOString().slice(0, 10);
      await this.load();
    },

    get rangeHours() {
      if (this.custom) {
        const s = Date.parse(this.customStart), e = Date.parse(this.customEnd);
        if (isFinite(s) && isFinite(e) && e > s) return Math.round((e - s) / 3600000) + 24;
      }
      return (this.ranges.find(r => r.key === this.range) || this.ranges[0]).hours;
    },
    get rangeLabel() {
      if (this.custom) return this.customStart + ' → ' + this.customEnd;
      return (this.ranges.find(r => r.key === this.range) || this.ranges[0]).label;
    },
    get window() {
      const now = Math.floor(Date.now() / 1000);
      if (this.custom) {
        const s = Date.parse(this.customStart), e = Date.parse(this.customEnd);
        if (isFinite(s) && isFinite(e) && e > s) {
          return { start: Math.floor(s / 1000), end: Math.floor(e / 1000) + 86400 };
        }
      }
      return { start: now - this.rangeHours * 3600, end: now };
    },

    setRange(k) { this.range = k; this.custom = false; this.load(); },
    applyCustom() { this.custom = true; this.load(); },
    toggleMetric(k) { this.metrics[k] = !this.metrics[k]; this.render(); },

    async load() {
      this.loading = true;
      try {
        const w = this.window;
        const url = `api/metrics?start=${w.start}&end=${w.end}&points=400`
          + this.$store.app.gwQuery('&');
        const d = await (await fetch(url)).json();
        this.series = (d && d.series) || [];
        this.render();
      } catch (e) {
        this.series = [];
        this.$store.app.toast('History load failed: ' + e.message, 'error');
      } finally { this.loading = false; }
    },

    render() {
      this.$nextTick(() => {
        const el = this.$refs.canvas;
        if (!el || !window.Chart) return;
        const labels = this.series.map(p => this.$store.app._fmtSiteTime(p.ts, {   // gateway metrics — SITE zone
          month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
        }));
        const datasets = this.metricDefs.filter(m => this.metrics[m.key]).map(m => ({
          label: m.label,
          data: this.series.map(p => p[m.key]),
          borderColor: m.color,
          backgroundColor: this.chartType === 'area' ? m.color + '26' : m.color,
          fill: this.chartType === 'area' && !m.pct,
          yAxisID: m.pct ? 'y1' : 'y',
          borderWidth: 1.5, pointRadius: 0, tension: 0.25,
        }));
        const cfg = {
          type: 'line',
          data: { labels, datasets },
          options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { display: false }, tooltip: { enabled: true } },
            scales: {
              x: { ticks: { maxTicksLimit: 8, color: '#64748b', font: { size: 10 } },
                   grid: { color: 'rgba(148,163,184,.08)' } },
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
      window.location = `api/admin/metrics/export?fmt=${fmt}&hours=${this.rangeHours}`
        + this.$store.app.gwQuery('&');
    },
  };
}
