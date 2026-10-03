/**
 * FranklinWH Local Bridge — Battery tab
 *
 * Per-cell BMS telemetry from GET /api/battery (one aGate session: cmdTypes
 * 1705 + 1703 + 1835 + 1833 + 1105). Three modes:
 *   snapshot      one read on demand (default — the device is slow, never auto-poll
 *                 a tab the user is not looking at)
 *   auto-refresh  repeat every N seconds while the tab is open
 *   chart         accumulate samples client-side and plot cell spread / pack values
 *
 * Samples are held in memory only. Persisting BMS sessions is a separate job
 * (BACKLOG FEAT-BMS-SESSIONS) — this keeps the tab dependency-free.
 */
function batteryTab() {
  return {
    data: null,
    loading: false,
    error: '',
    lastAt: '',
    // ── card show/hide (declutter; per browser) ──
    bmsCardsOpen: false,
    bmsCardDefaults: { header: true, metrics: true, cells: true, inverter: true },
    bmsCardList: [['header', 'BMS Header'], ['metrics', 'Pack Metrics'], ['cells', 'Cell Telemetry'], ['inverter', 'Inverter & Power']],
    bmsCards: {},
    _loadBmsCards() {
      try {
        const saved = JSON.parse(localStorage.getItem('fwh-battery-cards') || '{}');
        this.bmsCards = { ...this.bmsCardDefaults, ...(saved && typeof saved === 'object' ? saved : {}) };
      } catch (e) { this.bmsCards = { ...this.bmsCardDefaults }; }
    },
    toggleBmsCard(key) {
      this.bmsCards = { ...this.bmsCards, [key]: !this.bmsCards[key] };
      try { localStorage.setItem('fwh-battery-cards', JSON.stringify(this.bmsCards)); } catch (e) { /**/ }
    },
    get anyBmsCard() {
      const c = this.bmsCards || {};
      return !!(c.header || c.metrics || c.cells || c.inverter);
    },
    resetBmsCards() {
      this.bmsCards = { ...this.bmsCardDefaults };
      try { localStorage.removeItem('fwh-battery-cards'); } catch (e) { /**/ }
    },
    unitId: 1,

    // ── refresh control ──
    auto: localStorage.getItem('fwh-bat-auto') === '1',
    intervalS: 5,
    intervals: [2, 5, 10, 30, 60],
    _timer: null,

    // ── chart ──
    showChart: localStorage.getItem('fwh-bat-chart') === '1',
    // Trend chart mode: the originally-displayed aggregate (spread/SoC/temp) can be
    // toggled to per-cell voltage lines, or an average / median of the cells.
    trendMode: 'trend',   // trend | percell | average | median
    trendMetric: 'voltage', // voltage | temp — for the per-cell / avg / median modes
    // Per-unit live sample store — {aPowerId: [{t,soc,spread,vmin,vmax,tmax,current,volts[],temps[]}]}.
    // Keyed by aPower so a multi-battery site can overlay units on one chart.
    samplesByUnit: {},
    chartUnits: [],       // EXTRA aPower ids to also chart (primary unitId is always in)
    unitRows: [],         // per-aPower summary rows for the multi-battery table
    maxSamples: 720,      // ~1h at 5s; bounded so a long watch cannot grow forever
    // `samples` = the primary aPower's series (drawLive / Export CSV / header count read it).
    get samples() { return this.samplesByUnit[this.unitId] || []; },
    // Every aPower to chart, primary first, de-duplicated.
    get selectedUnits() { return [...new Set([this.unitId, ...this.chartUnits])]; },
    // Per-cell + 2+ aPowers → a stack of small per-cell charts (one per unit).
    get showStack() { return this.trendMode === 'percell' && this.selectedUnits.length > 1; },
    _stackCharts: {},
    unitLabel(u) {
      const dm = (this.data && this.data.units && this.data.units.devMap) || [];
      const d = dm.find((x) => x.id === u);
      return d ? ('aPower ' + u + ' · ' + d.devSN) : ('aPower ' + u);
    },
    _chart: null,

    // ── live-watch modal ──
    // A full-screen realtime chart. It shares the same `samples` ring the Trend
    // uses (so Export CSV / Clear work on one dataset) but drives its own poll
    // when the tab's Auto is off, and renders a rolling window into its own canvas.
    liveOpen: false,
    liveWindow: 120,      // last N samples shown (~10 min at 5s) so the line keeps moving
    _liveChart: null,

    init() {
      this._loadBmsCards();
      this.load();
      // Restore a persisted Auto/Chart choice so the live view survives a reload
      // (previously every refresh hid the chart and stopped auto-refresh).
      if (this.$store.app.activeTab === 'battery' && (this.showChart || this.auto)) this._syncPoll();
      if (this.showChart) this.$nextTick(() => this.draw());
      // Stop polling when the tab is hidden — no point holding a device session
      // open for a view nobody is looking at.
      this.$watch('$store.app.activeTab', (t) => {
        // Free retained retina canvas buffers while the tab is away (DEF-BROWSER-MEMORY);
        // rebuild on return from the data still in hand.
        if (t !== 'battery') { this._pausePoll(); this._disposeCharts(); }
        else { this._syncPoll(); this.$nextTick(() => { if (this.showChart) this.draw(); if (this.liveOpen) this.drawLive(); }); }
      });
      // Switching the gateway in the topbar points at a DIFFERENT battery — reset the
      // per-unit selection/samples and re-read (the tab used to keep showing the old
      // gateway's data until a manual refresh).
      this.$watch('$store.app.selectedGateway', () => {
        this.unitId = 1;
        this.chartUnits = [];
        this.samplesByUnit = {};
        this.unitRows = [];
        this.data = null;
        this._destroyStack();
        this.load();
      });
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) this._pausePoll();
        else if (this.$store.app.activeTab === 'battery') this._syncPoll();
      });
    },

    async load() {
      // The aGate is slow and single-connection: never stack overlapping reads, or
      // they queue on the device, one hangs, and `loading` sticks true forever (the
      // "samples stop increasing" bug). A tick that arrives mid-read is simply skipped.
      if (this.loading) return;
      this.loading = true;
      this.error = '';
      const _ctrl = new AbortController();
      const _to = setTimeout(() => _ctrl.abort(), 20000);   // recover from a hung read
      try {
        const q = new URLSearchParams({ id: String(this.unitId) });
        // gateway scoping is appended by gwQuery('&') — don't double it here.
        const r = await fetch('api/battery?' + q.toString() + this.$store.app.gwQuery('&'), { signal: _ctrl.signal });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        if (!d.ok) throw new Error(d.error || 'device did not return cell data');
        this.data = d;
        this.lastAt = new Date().toLocaleTimeString();
        this.record(d);                                  // primary aPower
        // Multi-battery site: gather every aPower once — build the per-aPower table
        // row from each, and record the charted ones for the overlay. Sequential:
        // each is its own (slow) aGate read.
        const devMap = (d.units && d.units.devMap) || [];
        if (devMap.length > 1) {
          const rows = [];
          for (const u of devMap) {
            let ud = d;
            if (u.id !== this.unitId) {
              try { ud = await this._fetchUnit(u.id); } catch { ud = null; }
            }
            if (ud && ud.ok) {
              rows.push(this._unitRow(ud, u));
              if ((this.showChart || this.liveOpen) && this.selectedUnits.includes(u.id)) {
                this.record(ud, u.id);
              }
            } else {
              rows.push({ id: u.id, devSN: u.devSN, offline: true });
            }
          }
          this.unitRows = rows;
        } else {
          this.unitRows = [];
        }
        try {
          if (this.showChart) this.draw();
          if (this.liveOpen) this.drawLive();
        } catch (chartErr) {
          // A transient Chart.js resize (e.g. rendering into a not-yet-laid-out canvas
          // during a tab/gateway switch) must not surface as a device-read failure.
          console.warn('[Bridge] chart render skipped:', chartErr && chartErr.message);
        }
      } catch (e) {
        this.error = e.message;
        // Keep the previous reading on screen — a dropped poll on this link is
        // routine and blanking the view would lose more than it tells you.
      } finally {
        clearTimeout(_to);
        this.loading = false;
      }
    },

    async _fetchUnit(id) {
      const q = new URLSearchParams({ id: String(id) });
      const r = await fetch('api/battery?' + q.toString() + this.$store.app.gwQuery('&'));
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    },

    toggleAuto() { this.auto = !this.auto; localStorage.setItem('fwh-bat-auto', this.auto ? '1' : '0'); this._syncPoll(); },
    startAuto() { this.auto = true; this._syncPoll(); },
    stopAuto() { this.auto = false; this._syncPoll(); },
    changeInterval() { this._restartPoll(); },

    // ── unified polling ────────────────────────────────────
    // ONE timer drives every live view. Poll whenever the user wants Auto, the
    // inline Chart is shown, OR the Watch-live modal is open — so opening a
    // chart actually builds instead of freezing on the samples so far (the bug:
    // Chart used to draw once and never refresh).
    // The Auto button lights up whenever the tab is actually refreshing — Auto
    // toggled on, or a live view (Chart / Watch-live) pulling its own data.
    get polling() { return this.auto || this.showChart || this.liveOpen; },

    _syncPoll() {
      const want = this.auto || this.showChart || this.liveOpen;
      if (want && !this._timer) {
        this._timer = setInterval(() => this.load(), this.intervalS * 1000);
      } else if (!want && this._timer) {
        clearInterval(this._timer); this._timer = null;
      }
    },
    _restartPoll() {
      if (this._timer) { clearInterval(this._timer); this._timer = null; }
      this._syncPoll();
    },
    // Pause the timer while the tab is hidden/away WITHOUT forgetting the user's
    // Auto/Chart/live intent — _syncPoll restores it on return.
    _pausePoll() { if (this._timer) { clearInterval(this._timer); this._timer = null; } },

    // ── derived ──
    get cells() { return (this.data && this.data.cells) || {}; },
    get el() { return (this.data && this.data.electrical) || {}; },
    get states() { return (this.data && this.data.states) || {}; },
    get fw() { return (this.data && this.data.firmware) || {}; },
    get volts() { return this.cells.batVolt || []; },
    get temps() { return this.cells.batTemp || []; },

    get stats() {
      const v = this.volts, t = this.temps;
      if (!v.length) return {};
      const vmax = Math.max(...v), vmin = Math.min(...v);
      const o = { vmax, vmin, spread: vmax - vmin,
                  vmaxCell: v.indexOf(vmax) + 1, vminCell: v.indexOf(vmin) + 1 };
      if (t.length) {
        o.tmax = Math.max(...t); o.tmin = Math.min(...t);
        o.tmaxCell = t.indexOf(o.tmax) + 1; o.tminCell = t.indexOf(o.tmin) + 1;
      }
      return o;
    },

    // Spread is the health signal worth colouring: tight is good, wide means a
    // cell is drifting. Thresholds match the CLI view.
    get spreadClass() {
      const s = this.stats.spread;
      if (s === undefined) return '';
      return s <= 20 ? 'text-emerald-400' : s <= 50 ? 'text-amber-400' : 'text-red-400';
    },

    cellClass(i) {
      const s = this.stats;
      if (i + 1 === s.vmaxCell) return 'border-sky-400/60 bg-sky-500/10';
      if (i + 1 === s.vminCell) return 'border-red-400/60 bg-red-500/10';
      return '';
    },

    get currentLabel() {
      const a = this.cells.currGrp;
      if (a === undefined || a === null) return '—';
      // Direction from the AUTHORITATIVE DCDC/BMS charge-state (what the topbar uses), NOT the
      // currGrp SIGN — on this BMS positive current = charging, so the old `a>0?'Discharging'`
      // was inverted (topbar said Charging while this card said Discharging). Magnitude = |a|.
      const st = (this.el.DCDCStatus_desc || this.states.bmsState_desc || '').toLowerCase();
      let dir;
      if (st.includes('dischar')) dir = 'Discharging';
      else if (st.includes('charg')) dir = 'Charging';
      else if (st.includes('stand') || st.includes('idle')) dir = 'Idle';
      else dir = a > 0 ? 'Charging' : a < 0 ? 'Discharging' : 'Idle';   // fallback: corrected sign
      return `${Math.abs(a).toFixed(1)} A · ${dir}`;
    },

    fmt(v, digits = 1, unit = '') {
      if (v === undefined || v === null) return '—';
      return (typeof v === 'number' ? v.toFixed(digits) : v) + (unit ? ' ' + unit : '');
    },

    // ── chart ──
    record(d, unit) {
      unit = unit ?? this.unitId;
      const c = d.cells || {}, v = c.batVolt || [], t = c.batTemp || [];
      if (!v.length) return;
      const arr = this.samplesByUnit[unit] || (this.samplesByUnit[unit] = []);
      arr.push({
        t: Date.now(),
        soc: c.batSoc, current: c.currGrp,
        vmin: Math.min(...v), vmax: Math.max(...v),
        spread: Math.max(...v) - Math.min(...v),
        tmax: t.length ? Math.max(...t) : null,
        volts: v.slice(),                 // per-cell mV — for the Per-cell / Avg / Median modes
        temps: t.length ? t.slice() : null,
      });
      if (arr.length > this.maxSamples) arr.shift();
    },

    // Multi-select: toggle an EXTRA aPower into/out of the chart (primary stays).
    toggleChartUnit(id) {
      id = Number(id);
      if (id === this.unitId) return;                 // primary is always charted
      const i = this.chartUnits.indexOf(id);
      if (i >= 0) this.chartUnits.splice(i, 1); else this.chartUnits.push(id);
      this.$nextTick(() => { this.draw(); if (this.liveOpen) this.drawLive(); });
    },
    unitColour(id, idx) { return `hsl(${(idx * 67) % 360}, 70%, 55%)`; },

    // One row of the per-aPower table from a full battery read.
    _unitRow(ud, u) {
      const c = ud.cells || {}, st = ud.states || {}, el = ud.electrical || {}, fw = ud.firmware || {};
      return {
        id: u.id, devSN: u.devSN,
        soc: c.batSoc, soh: c.batSoh, current: c.currGrp,
        bms: st.bmsState_desc, inverter: st.peState_desc,
        dcdc: el.DCDCStatus_desc, bmsVer: fw.bms_ver,
        offline: false,
      };
    },

    toggleChart() {
      this.showChart = !this.showChart;
      localStorage.setItem('fwh-bat-chart', this.showChart ? '1' : '0');
      this._syncPoll();            // showing the chart is a live consumer → poll
      if (this.showChart) this.$nextTick(() => this.draw());
    },

    clearSamples() { this.samplesByUnit = {}; if (this.showChart) this.draw(); if (this.liveOpen) this.drawLive(); },

    setTrendMode(m) { this.trendMode = m; this.$nextTick(() => this.draw()); },
    setTrendMetric(m) { this.trendMetric = m; this.$nextTick(() => this.draw()); },

    _hidden: {},   // legend-hidden series, by label — survives the per-tick redraw

    _renderTrend(el, labels, datasets, scales) {
      // The chart is destroyed + recreated every poll, which reset any series the
      // user hid from the legend (they'd click to deselect and it came back on the
      // next refresh). Re-apply the remembered hidden state, and record legend
      // clicks into it so the choice sticks.
      const self = this;
      // In-place update when the dataset shape is unchanged — recreating a Chart every ~2s
      // poll churns canvas backing stores and leaks over long sessions (DEF-BROWSER-MEMORY).
      // drawLive() already does this; mirror it. Only recreate on a real structure change.
      const same = this._chart && this._chart.canvas === el
        && this._chart.data.datasets.length === datasets.length
        && this._chart.data.datasets.every((d, i) => d.label === datasets[i].label);
      if (same) {
        this._chart.data.labels = labels;
        datasets.forEach((d, i) => { this._chart.data.datasets[i].data = d.data; });
        if (scales) this._chart.options.scales = scales;
        this._chart.update('none');
        return;
      }
      datasets.forEach((d) => { if (self._hidden[d.label]) d.hidden = true; });
      const cfg = {
        type: 'line', data: { labels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: 'index', intersect: false },
          scales,
          plugins: { legend: { labels: { boxWidth: 10, filter: (it) => it.text !== '_min' },
            onClick(e, item, legend) {
              const ci = legend.chart, idx = item.datasetIndex;
              const label = ci.data.datasets[idx].label;
              if (ci.isDatasetVisible(idx)) { ci.hide(idx); self._hidden[label] = true; }
              else { ci.show(idx); delete self._hidden[label]; }
            } } },
        },
      };
      if (this._chart) { this._chart.destroy(); }
      this._chart = new Chart(el, cfg);
    },

    _disposeCharts() {
      if (this._chart) { this._chart.destroy(); this._chart = null; }
      if (this._liveChart) { this._liveChart.destroy(); this._liveChart = null; }
      if (this._cellChart) { this._cellChart.destroy(); this._cellChart = null; }
      this._destroyStack();
    },

    _destroyStack() {
      for (const id of Object.keys(this._stackCharts)) {
        this._stackCharts[id].destroy(); delete this._stackCharts[id];
      }
    },

    drawPerCellStack() {
      const temp = this.trendMetric === 'temp';
      const cellArr = (x) => (temp ? x.temps : x.volts);
      const scale = (x) => (temp ? x : x / 1000);
      const yText = temp ? 'Temperature (°C)' : 'Voltage (V)';
      const units = this.selectedUnits;
      for (const id of Object.keys(this._stackCharts)) {
        if (!units.includes(Number(id))) { this._stackCharts[id].destroy(); delete this._stackCharts[id]; }
      }
      for (const u of units) {
        const el = document.getElementById('bmsCellChart-' + u);
        if (!el || typeof Chart === 'undefined' || !el.clientHeight) continue;
        const rows = (this.samplesByUnit[u] || []).filter((s) => Array.isArray(cellArr(s)) && cellArr(s).length);
        const labels = rows.map((s) => this.$store.app._fmtSiteTime(s.t/1000));
        const n = rows.length ? cellArr(rows[rows.length - 1]).length : 0;
        const datasets = Array.from({ length: n }, (_, i) => ({
          label: `Cell ${i + 1}`,
          data: rows.map((s) => (cellArr(s)[i] != null ? scale(cellArr(s)[i]) : null)),
          borderColor: this.cellColour(i, n), backgroundColor: 'transparent',
          tension: 0.2, pointRadius: 0, borderWidth: 1.2,
        }));
        const cfg = {
          type: 'line', data: { labels, datasets },
          options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            interaction: { mode: 'index', intersect: false },
            scales: { y: { title: { display: true, text: yText } } },
            plugins: { legend: { display: false } },   // 16 cells × N units — legend off
          },
        };
        const existing = this._stackCharts[u];
        if (existing && existing.canvas === el && existing.data.datasets.length === datasets.length) {
          existing.data.labels = labels;                       // in-place — no per-poll recreate
          datasets.forEach((d, i) => { existing.data.datasets[i].data = d.data; });
          existing.options.scales = cfg.options.scales;
          existing.update('none');
        } else {
          if (existing) existing.destroy();
          this._stackCharts[u] = new Chart(el, cfg);
        }
      }
    },

    draw() {
      // Per-cell across 2+ aPowers → a stack of per-unit charts, not one canvas.
      if (this.showStack) {
        if (this._chart) { this._chart.destroy(); this._chart = null; }
        this.$nextTick(() => this.drawPerCellStack());
        return;
      }
      this._destroyStack();
      const el = document.getElementById('bmsChart');
      if (!el || typeof Chart === 'undefined' || !el.clientHeight) return;

      // Multi-aPower compare: >1 unit selected → ONE line per unit (per-cell across
      // units would be a hairball). The quantity follows the mode: Trend→SoC,
      // Avg/Median→that aggregate of the unit's cells (Voltage or Temp).
      const units = this.selectedUnits;
      if (units.length > 1) {
        const temp = this.trendMetric === 'temp';
        const soc = this.trendMode === 'trend';
        const median = this.trendMode === 'median';
        const cellArr = (x) => (temp ? x.temps : x.volts);
        const scale = (x) => (temp ? x : x / 1000);
        const val = (s) => {
          if (soc) return s.soc;
          const a = cellArr(s);
          if (!Array.isArray(a) || !a.length) return null;
          const v = [];
          for (let i = 0; i < a.length; i++) { const x = a[i]; if (x != null && !isNaN(x)) v.push(scale(x)); }
          if (!v.length) return null;
          if (median) { const t = [...v].sort((a2, b2) => a2 - b2), m = Math.floor(t.length / 2); return t.length % 2 ? t[m] : (t[m - 1] + t[m]) / 2; }
          return v.reduce((a2, b2) => a2 + b2, 0) / v.length;
        };
        const dm = (this.data && this.data.units && this.data.units.devMap) || [];
        const nameOf = (id) => { const u = dm.find(x => x.id === id); return u ? ('aP' + id + ' ·' + String(u.devSN).slice(-4)) : ('aPower ' + id); };
        const primaryRows = this.samplesByUnit[this.unitId] || [];
        const labels = primaryRows.map(s => this.$store.app._fmtSiteTime(s.t/1000));
        const datasets = units.map((id, idx) => ({
          label: nameOf(id),
          data: (this.samplesByUnit[id] || []).map(val),
          borderColor: this.unitColour(id, idx), backgroundColor: 'transparent',
          tension: 0.2, pointRadius: 0, borderWidth: 2,
        }));
        const yText = soc ? 'SoC (%)' : (temp ? 'Temperature (°C)' : 'Voltage (V)');
        this._renderTrend(el, labels, datasets, { y: { title: { display: true, text: yText } } });
        return;
      }

      // Original aggregate trend: spread / SoC / max-cell-temp on a dual axis.
      if (this.trendMode === 'trend') {
        const labels = this.samples.map(s => this.$store.app._fmtSiteTime(s.t/1000));
        const ds = (label, key, colour, axis) => ({
          label, data: this.samples.map(s => s[key]), borderColor: colour,
          backgroundColor: colour + '22', yAxisID: axis, tension: 0.25,
          pointRadius: 0, borderWidth: 2,
        });
        this._renderTrend(el, labels, [
          ds('Spread (mV)', 'spread', '#f59e0b', 'y'),
          ds('SoC (%)', 'soc', '#10b981', 'y2'),
          ds('Max cell temp (°C)', 'tmax', '#ef4444', 'y2'),
        ], {
          y:  { position: 'left',  title: { display: true, text: 'mV' } },
          y2: { position: 'right', grid: { drawOnChartArea: false },
                title: { display: true, text: '% / °C' } },
        });
        return;
      }

      // Per-cell metric (voltage → V, or temperature → °C) and its average / median —
      // needs the raw cell arrays kept on each sample.
      const temp = this.trendMetric === 'temp';
      const arr = (s) => (temp ? s.temps : s.volts);
      const scale = (x) => (temp ? x : x / 1000);   // temps already °C; volts mV → V
      const rows = this.samples.filter(s => Array.isArray(arr(s)) && arr(s).length);
      const labels = rows.map(s => this.$store.app._fmtSiteTime(s.t/1000));
      const n = rows.length ? arr(rows[rows.length - 1]).length : 0;
      let datasets;
      if (this.trendMode === 'percell') {
        datasets = Array.from({ length: n }, (_, i) => ({
          label: `Cell ${i + 1}`,
          data: rows.map(s => (arr(s)[i] != null ? scale(arr(s)[i]) : null)),
          borderColor: this.cellColour(i, n), backgroundColor: 'transparent',
          tension: 0.2, pointRadius: 0, borderWidth: 1.5,
        }));
      } else {
        const perRow = rows.map(s => {
          const v = [];
          for (let i = 0; i < n; i++) { const x = arr(s)[i]; if (x != null && !isNaN(x)) v.push(scale(x)); }
          return v;
        });
        const mins = perRow.map(v => v.length ? Math.min(...v) : null);
        const maxs = perRow.map(v => v.length ? Math.max(...v) : null);
        const agg = perRow.map(v => {
          if (!v.length) return null;
          if (this.trendMode === 'median') {
            const t = [...v].sort((a, b) => a - b), m = Math.floor(t.length / 2);
            return t.length % 2 ? t[m] : (t[m - 1] + t[m]) / 2;
          }
          return v.reduce((a, b) => a + b, 0) / v.length;   // average
        });
        const label = (this.trendMode === 'median' ? 'Median' : 'Average') + ` of ${n} cells`;
        datasets = [
          { label: '_min', data: mins, borderColor: 'transparent', backgroundColor: 'transparent',
            pointRadius: 0, borderWidth: 0, tension: 0.2 },
          { label: 'Min–max range', data: maxs, borderColor: 'transparent', backgroundColor: '#38bdf822',
            fill: '-1', pointRadius: 0, borderWidth: 0, tension: 0.2 },
          { label, data: agg, borderColor: '#22d3ee', backgroundColor: 'transparent',
            tension: 0.2, pointRadius: 0, borderWidth: 2.5 },
        ];
      }
      this._renderTrend(el, labels, datasets, { y: { title: { display: true, text: temp ? 'Temperature (°C)' : 'Voltage (V)' } } });
    },

    // ── live-watch modal ──────────────────────────────────────
    openLive() {
      this.liveOpen = true;
      this.load();                 // seed a point immediately
      this._syncPoll();            // the modal is a live consumer → ensure polling
      this.$nextTick(() => this.drawLive());
    },

    closeLive() {
      this.liveOpen = false;
      this._syncPoll();            // stop polling if nothing else needs it
      if (this._liveChart) { this._liveChart.destroy(); this._liveChart = null; }
    },

    changeLiveInterval() { this._restartPoll(); },

    get liveLast() { return this.samples.length ? this.samples[this.samples.length - 1] : null; },

    drawLive() {
      const el = document.getElementById('bmsLiveChart');
      if (!el || typeof Chart === 'undefined') return;
      const rows = this.samples.slice(-this.liveWindow);
      const labels = rows.map(s => this.$store.app._fmtSiteTime(s.t/1000));
      const cols = { spread: '#f59e0b', soc: '#10b981', tmax: '#ef4444' };
      if (!this._liveChart) {
        const ds = (label, key, axis) => ({
          label, data: rows.map(s => s[key]), borderColor: cols[key],
          backgroundColor: cols[key] + '22', yAxisID: axis, tension: 0.25,
          pointRadius: 0, borderWidth: 2,
        });
        this._liveChart = new Chart(el, {
          type: 'line',
          data: { labels, datasets: [
            ds('Spread (mV)', 'spread', 'y'),
            ds('SoC (%)', 'soc', 'y2'),
            ds('Max cell temp (°C)', 'tmax', 'y2'),
          ]},
          options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
              y:  { position: 'left',  title: { display: true, text: 'mV' } },
              y2: { position: 'right', grid: { drawOnChartArea: false },
                    title: { display: true, text: '% / °C' } },
            },
            plugins: { legend: { labels: { boxWidth: 10 } } },
          },
        });
      } else {
        // Update in place — smoother than destroy/recreate at the poll cadence.
        this._liveChart.data.labels = labels;
        const keys = ['spread', 'soc', 'tmax'];
        keys.forEach((k, i) => { this._liveChart.data.datasets[i].data = rows.map(s => s[k]); });
        this._liveChart.update('none');
      }
    },

    // ── recorded sessions (persisted) ──────────────────────────
    view: 'telemetry',        // telemetry | charts
    sessions: [],
    sessionId: null,
    session: null,
    chartView: 'voltage',     // voltage | temperature | comparison
    seriesMode: 'all',        // all (per-cell) | average | median — collapses 16 lines
    rec: { active: false, captured: 0, planned: 0, errors: 0 },
    recSamples: 20,
    recIntervalS: 15,
    _recTimer: null,
    _cellChart: null,

    setView(v) {
      this.view = v;
      if (v === 'charts') { this.loadSessions(); this.$nextTick(() => this.drawCells()); }
    },

    async loadSessions() {
      try {
        const r = await fetch('api/battery/sessions?limit=200');
        this.sessions = (await r.json()).sessions || [];
      } catch (e) { this.error = e.message; }
    },

    async openSession(id) {
      this.sessionId = id;
      try {
        const r = await fetch(`api/battery/sessions/${id}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        this.session = await r.json();
        this.$nextTick(() => this.drawCells());
      } catch (e) { this.error = e.message; }
    },

    async deleteSession(id) {
      const ok = await this.$store.app.confirmDialog(
        'Remove this recording and all its snapshots?',
        { title: 'Delete session', danger: true });
      if (!ok) return;
      await fetch(`api/battery/sessions/${id}`, { method: 'DELETE' });
      if (this.sessionId === id) { this.session = null; this.sessionId = null; }
      this.loadSessions();
    },

    async startRecording() {
      try {
        const r = await fetch('api/battery/record' + this.$store.app.gwQuery(), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ samples: this.recSamples,
                                 interval_s: this.recIntervalS, id: this.unitId }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        this.rec = d;
        this.pollRecording();
      } catch (e) { this.$store.app.toast(`Record failed: ${e.message}`, 'error'); }
    },

    async stopRecording() {
      await fetch('api/battery/record/stop', { method: 'POST' });
    },

    pollRecording() {
      // The session runs server-side; poll its progress so the button reflects
      // reality even if the page is reloaded mid-recording.
      clearInterval(this._recTimer);
      this._recTimer = setInterval(async () => {
        try {
          this.rec = await (await fetch('api/battery/record/status')).json();
          if (!this.rec.active) {
            clearInterval(this._recTimer);
            this._recTimer = null;
            this.loadSessions();
            this.$store.app.toast(
              `Recording finished — ${this.rec.captured} sample(s)`, 'success');
          }
        } catch { clearInterval(this._recTimer); this._recTimer = null; }
      }, 2000);
    },

    get sessionCells() {
      const s = this.session;
      if (!s || !s.samples || !s.samples.length) return 0;
      const v = s.samples.find(x => x.volts);
      return v ? v.volts.length : 0;
    },

    //: Per-cell palette. 16 distinct hues so adjacent cells stay distinguishable.
    cellColour(i, n) { return `hsl(${Math.round((i * 360) / (n || 16))}, 70%, 55%)`; },

    drawCells() {
      const el = document.getElementById('cellChart');
      if (!el || typeof Chart === 'undefined' || !this.session) return;
      if (this.chartView === 'comparison') {
        if (this._cellChart) { this._cellChart.destroy(); this._cellChart = null; }
        return;    // comparison is a table, not a chart
      }
      const temp = this.chartView === 'temperature';
      const rows = (this.session.samples || []).filter(s => temp ? s.temps : s.volts);
      const n = this.sessionCells;
      const labels = rows.map(s => this.$store.app._fmtSiteTime(s.ts));
      const valAt = (s, i) => { const a = temp ? s.temps : s.volts; return a ? (temp ? a[i] : a[i] / 1000) : null; };

      let datasets;
      if (this.seriesMode === 'all') {
        datasets = Array.from({ length: n }, (_, i) => ({
          label: `Cell ${i + 1}`,
          data: rows.map(s => valAt(s, i)),
          borderColor: this.cellColour(i, n), backgroundColor: 'transparent',
          tension: 0.2, pointRadius: 2, borderWidth: 1.5,
        }));
      } else {
        // Collapse the cells to one aggregate line + a faint min–max band per row.
        const perRow = rows.map(s => {
          const v = [];
          for (let i = 0; i < n; i++) { const x = valAt(s, i); if (x != null && !isNaN(x)) v.push(x); }
          return v;
        });
        const mins = perRow.map(v => v.length ? Math.min(...v) : null);
        const maxs = perRow.map(v => v.length ? Math.max(...v) : null);
        const agg = perRow.map(v => {
          if (!v.length) return null;
          if (this.seriesMode === 'median') {
            const t = [...v].sort((a, b) => a - b), m = Math.floor(t.length / 2);
            return t.length % 2 ? t[m] : (t[m - 1] + t[m]) / 2;
          }
          return v.reduce((a, b) => a + b, 0) / v.length;   // average
        });
        const band = temp ? '#f59e0b' : '#38bdf8';
        const line = temp ? '#ef4444' : '#22d3ee';
        const label = (this.seriesMode === 'median' ? 'Median' : 'Average') + ` of ${n} cells`;
        datasets = [
          { label: '_min', data: mins, borderColor: 'transparent', backgroundColor: 'transparent',
            pointRadius: 0, borderWidth: 0, tension: 0.2 },
          { label: 'Min–max range', data: maxs, borderColor: 'transparent', backgroundColor: band + '22',
            fill: '-1', pointRadius: 0, borderWidth: 0, tension: 0.2 },
          { label, data: agg, borderColor: line, backgroundColor: 'transparent',
            tension: 0.2, pointRadius: 2, borderWidth: 2.5 },
        ];
      }
      if (this._cellChart) this._cellChart.destroy();
      this._cellChart = new Chart(el, {
        type: 'line', data: { labels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: 'index', intersect: false },
          scales: { y: { title: { display: true,
                                  text: temp ? 'Temperature (°C)' : 'Voltage (V)' } } },
          plugins: { legend: { labels: { boxWidth: 8, font: { size: 10 },
                     filter: (it) => it.text !== '_min' } } },
        },
      });
    },

    setChartView(v) { this.chartView = v; this.$nextTick(() => this.drawCells()); },
    setSeriesMode(m) { this.seriesMode = m; this.$nextTick(() => this.drawCells()); },

    //: Previous vs current snapshot, per cell — the "what moved" view.
    get comparison() {
      const s = this.session;
      if (!s || !s.samples) return [];
      const withV = s.samples.filter(x => x.volts);
      if (withV.length < 2) return [];
      const prev = withV[withV.length - 2].volts, cur = withV[withV.length - 1].volts;
      return cur.map((mv, i) => ({ cell: i + 1, prev: prev[i], cur: mv,
                                   delta: mv - prev[i] }));
    },

    sessionCsv() {
      const s = this.session;
      if (!s || !s.samples) return;
      const n = this.sessionCells;
      const head = ['time', 'soc', 'pack_v', 'current_a',
        ...Array.from({ length: n }, (_, i) => `cell${i + 1}_mv`),
        ...Array.from({ length: n }, (_, i) => `cell${i + 1}_c`)].join(',');
      const rows = s.samples.map(x => [
        new Date(x.ts * 1000).toISOString(), x.soc ?? '', x.pack_v ?? '', x.current_a ?? '',
        ...(x.volts || Array(n).fill('')), ...(x.temps || Array(n).fill('')),
      ].join(','));
      const blob = new Blob([[head, ...rows].join('\n')], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `bms-session-${s.id}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    },

    exportCsv() {
      const head = 'time,soc_pct,current_a,cell_min_mv,cell_max_mv,spread_mv,max_temp_c';
      const rows = this.samples.map(s => [
        new Date(s.t).toISOString(), s.soc ?? '', s.current ?? '',
        s.vmin ?? '', s.vmax ?? '', s.spread ?? '', s.tmax ?? '',
      ].join(','));
      const blob = new Blob([[head, ...rows].join('\n')], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `bms-${new Date().toISOString().slice(0, 19)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    },
  };
}
