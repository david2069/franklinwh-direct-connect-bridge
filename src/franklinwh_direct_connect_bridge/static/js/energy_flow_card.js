/**
 * Energy Flow card — the Sankey plus its period + date selector. Ported from
 * the FranklinWH Modbus Bridge. The drawing lives in sankey.js (shared
 * verbatim); this is the thin Alpine wrapper that fetches a span and hands the
 * arcs over.
 *
 * Periods (day/week/month/year) are ANCHORED on the chosen date, so ‹/› and the
 * date picker still move a single reference day and the span is derived from it
 * (week = the anchor's Mon–Sun, month = its calendar month, year = its year).
 *
 * Flows are RECONSTRUCTED from the bridge's power samples by a merit-order
 * split — an estimate, not a meter — so the caption says so, and a partial
 * span (bridge offline) is flagged rather than shown as a quiet one.
 */
function energyFlowCard() {
  return {
    day: '',
    today: '',
    period: 'day',   // day | week | month | year
    quality: '',
    spanLabel: '',
    warn: false,
    nodes: null,
    _flows: null,
    _ro: null,

    init() {
      this.today = this._localToday();
      this.day = this.today;
      this.load();

      // Redraw on width change (sidebar collapse, rotate) — layout is computed
      // from clientWidth.
      if (window.ResizeObserver && this.$refs.sankey) {
        let last = 0;
        this._ro = new ResizeObserver((entries) => {
          const w = Math.round(entries[0].contentRect.width);
          if (w && Math.abs(w - last) > 12) { last = w; this._draw(); }
        });
        this._ro.observe(this.$refs.sankey);
      }

      // Only a live span moves; a settled past one doesn't. Whole-span integral,
      // so 2 minutes, not the 5s power tick.
      // Cease the Sankey rebuild when the dashboard isn't shown (DEF-BROWSER-MEMORY).
      setInterval(() => { if (this._spansToday() && this.$store.app.activeTab === 'dashboard') this.load(); }, 120000);
      this.$watch('$store.app.selectedGateway', () => this.load());
    },

    // Local calendar date. toISOString() converts to UTC first, which east of
    // Greenwich hands back yesterday for most of the working day.
    _localToday() {
      const d = new Date(); const p = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    },

    // True when the current period's span includes today (so it's still moving).
    _spansToday() {
      const [, e] = this._span();
      return Date.now() / 1000 < e;
    },

    prettyDay() {
      if (this.period !== 'day') return this.spanLabel;
      if (this.day === this.today) return 'Today';
      const [y, m, d] = this.day.split('-').map(Number);
      return new Date(y, m - 1, d).toLocaleDateString(undefined,
        { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
    },

    atToday() { return this.day >= this.today; },

    setPeriod(p) { this.period = p; this.load(); },

    // Step by one period (day/week/month/year), keeping the anchor within range.
    shiftDay(dir) {
      const [y, m, d] = this.day.split('-').map(Number);
      const dt = new Date(y, m - 1, d);
      if (this.period === 'week') dt.setDate(dt.getDate() + 7 * dir);
      else if (this.period === 'month') dt.setMonth(dt.getMonth() + dir);
      else if (this.period === 'year') dt.setFullYear(dt.getFullYear() + dir);
      else dt.setDate(dt.getDate() + dir);
      const p = (n) => String(n).padStart(2, '0');
      const next = `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
      if (next > this.today) return;
      this.day = next; this.load();
    },

    goToday() { this.today = this._localToday(); this.day = this.today; this.load(); },

    // The selected period's [start,end) as BROWSER-LOCAL epoch seconds. We send
    // explicit start/end, never day=<string> — the server would resolve midnight
    // in the CONTAINER's timezone, which breaks when the viewer's zone differs.
    // Local (not UTC) because the aGate's own daily totals reset at local midnight.
    _span() {
      const [y, m, d] = this.day.split('-').map(Number);
      const start = new Date(y, m - 1, d);
      const end = new Date(y, m - 1, d);
      if (this.period === 'week') {
        // Monday-start.
        start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
        end.setTime(start.getTime()); end.setDate(end.getDate() + 7);
      } else if (this.period === 'month') {
        start.setDate(1);
        end.setTime(start.getTime()); end.setMonth(end.getMonth() + 1);
      } else if (this.period === 'year') {
        start.setMonth(0, 1);
        end.setTime(start.getTime()); end.setFullYear(end.getFullYear() + 1);
      } else {
        end.setDate(end.getDate() + 1);
      }
      return [Math.floor(start.getTime() / 1000), Math.floor(end.getTime() / 1000)];
    },

    // What the span actually covers — a week anchored midweek still starts Monday,
    // so showing only the anchor date would mislead.
    _describeSpan(s, e) {
      const f = (secs) => new Date(secs * 1000).toLocaleDateString(undefined,
        { day: '2-digit', month: 'short' });
      if (this.period === 'year') return String(new Date(s * 1000).getFullYear());
      if (this.period === 'month') return new Date(s * 1000).toLocaleDateString(undefined,
        { month: 'long', year: 'numeric' });
      if (this.period === 'week') return `${f(s)} – ${f(e - 1)}`;
      return '';
    },

    async load() {
      const [s0, e0] = this._span();
      this.spanLabel = this._describeSpan(s0, e0);
      let url = `api/energy/flow?start=${s0}&end=${e0}`;
      const gw = this.$store.app.selectedGateway;
      if (gw && this.$store.app.gateways.length > 1) url += `&gateway=${encodeURIComponent(gw)}`;
      try {
        const r = await fetch(url, { headers: { Accept: 'application/json' } });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        this._flows = data.flows; this.nodes = data.nodes;
        this._draw(); this._setQuality(data.quality);
      } catch (e) {
        this._flows = null; this.nodes = null;
        if (this.$refs.sankey) this.$refs.sankey.innerHTML =
          '<p class="sankey-empty">Energy flow unavailable.</p>';
        this.quality = ''; this.warn = false;
      }
    },

    _draw() {
      if (!this._flows || !this.$refs.sankey || !window.FWHSankey) return;
      window.FWHSankey.render(this.$refs.sankey, this._flows, { height: 260 });
    },

    kwh(v) { const n = Number(v) || 0; return `${n.toFixed(n >= 10 ? 1 : 2)} kWh`; },

    _setQuality(q) {
      const noun = { day: 'day', week: 'week', month: 'month', year: 'year' }[this.period];
      if (!q || !q.samples) {
        this.warn = false;
        this.quality = q
          ? (this._spansToday() && this.period === 'day'
              ? 'Today is just starting — the flow builds as power samples come in.'
              : `No samples recorded for this ${noun}.`)
          : '';
        return;
      }
      const pct = Math.round((q.coverage || 0) * 100);
      this.warn = pct < 95;
      this.quality = this.warn
        ? `Partial data — the bridge recorded ${pct}% of this ${noun}.`
        : 'Derived from power samples — an estimate, not a meter.';
    },
  };
}
