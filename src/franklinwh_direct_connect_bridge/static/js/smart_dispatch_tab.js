/**
 * Smart Dispatch, plan only (#612 §7 phase 1, hems.dispatch). /api/smart-dispatch gives the
 * target and limit questions (pre-filled answers to confirm), what is missing, the 24-hour
 * plan, the action now and the plan as draft schedules. Check plans unsaved answers; Save
 * keeps them; Create schedules adds the drafts to the Scheduler. Nothing here writes to the
 * gateway: the Scheduler runs the tasks.
 */
function smartDispatchTab() {
  return {
    v: null,
    form: {},
    loading: false,
    saving: false,
    msg: null,
    creating: false,
    createMsg: null,
    _chart: null,

    init() {
      const t = lazyTab(this, 'smart_dispatch', () => this.load());
      this.$watch('$store.app.selectedGateway', () => t.reload());
    },

    _take(v) {
      this.v = v;
      const f = {};
      for (const q of v.questions || []) if (q.kind !== 'info' && !q.readonly) f[q.key] = q.value;
      this.form = f;
      this.$nextTick(() => this.draw());
    },

    async load(refresh) {
      this.loading = true;
      try {
        const r = await fetch('api/smart-dispatch' + this.$store.app.gwQuery('?') + (refresh ? '&refresh=1' : ''));
        if (r.ok) this._take(await r.json());
        else this.msg = { ok: false, text: 'Could not load Smart Dispatch (' + r.status + ')' };
      } catch (e) {
        this.msg = { ok: false, text: 'Could not load Smart Dispatch: ' + e.message };
      } finally { this.loading = false; }
    },

    _body() {
      const b = {};
      for (const [k, x] of Object.entries(this.form)) {
        if (x === '' || x === undefined) continue;
        const q = (this.v.questions || []).find(q => q.key === k);
        b[k] = q && q.kind === 'number' && x !== null ? Number(x) : x;
      }
      return b;
    },

    async send(method) {
      this.saving = true;
      this.msg = null;
      try {
        const url = method === 'PUT' ? 'api/smart-dispatch' : 'api/smart-dispatch/check';
        const r = await fetch(url + this.$store.app.gwQuery('?'), {
          method: method === 'PUT' ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(this._body()) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { this.msg = { ok: false, text: j.detail || ('Failed (' + r.status + ')') }; return; }
        this._take(j);
        this.msg = { ok: !j.issues.length, text: j.issues.length ? 'Check these: ' + j.issues.join('; ')
          : (method === 'PUT' ? 'Saved. The plan below uses your answers.' : 'Checked. The plan below uses these answers (not saved).') };
      } catch (e) {
        this.msg = { ok: false, text: e.message };
      } finally { this.saving = false; }
    },

    async createSchedules() {
      // Adds the drafts to the Scheduler (writes allowed only); the result stays in the card.
      this.creating = true;
      this.createMsg = null;
      try {
        const r = await fetch('api/schedules/smart-dispatch' + this.$store.app.gwQuery('?'), { method: 'POST' });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { this.createMsg = { ok: false, text: j.detail || ('Failed (' + r.status + ')') }; return; }
        const n = j.created.length, m = j.replaced.length;
        this.createMsg = { ok: n > 0, skipped: j.skipped,
          text: 'Created ' + n + ' task(s) in the Scheduler' + (m ? '; replaced ' + m + ' not yet started' : '') + '.' };
        await this.load();
      } catch (e) {
        this.createMsg = { ok: false, text: e.message };
      } finally { this.creating = false; }
    },

    shown(q) {
      // Limited sizes only while their choice is "limited"; battery export only while export is allowed.
      if (q.key === 'grid_charge_kw') return this.form.grid_charge === 'limited';
      if (q.key === 'export_kw') return this.form.export === 'limited';
      if (q.key === 'battery_export') return this.form.export !== 'prohibited';
      return true;
    },

    get steps() { return (this.v && this.v.result && this.v.result.steps) || []; },
    get currency() { return (this.v && this.v.currency) || ''; },
    money(x) { return x == null ? '—' : (x < 0 ? '−' : '') + Math.abs(x).toFixed(2) + (this.currency ? ' ' + this.currency : ''); },
    hhmm(ts) {
      return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: false,
        timeZone: (this.v && this.v.timezone) || undefined }).format(new Date(ts * 1000));
    },
    dayWord(ts) {
      // "Tomorrow " for a task that starts after today (site time); today's need no word.
      const day = t => new Intl.DateTimeFormat('en-CA', { timeZone: (this.v && this.v.timezone) || undefined }).format(t);
      return day(new Date(ts * 1000)) !== day(new Date()) ? 'Tomorrow ' : '';
    },
    actionLabel(a) {
      return { self: 'Self-consumption', charge: 'Charge from grid', discharge: 'Export from battery', hold: 'Hold' }[a] || a;
    },
    forceText(a) {
      if (a.direction === 'standby') return 'Standby';
      return (a.direction === 'charge' ? 'Charge ' : 'Discharge ') + a.power + ' kW to ' + a.target_soc + '%';
    },
    actionClass(a) {
      return { charge: 'text-sky-300', discharge: 'text-amber-300', hold: 'text-violet-300' }[a] || 'text-slate-300';
    },

    draw() {
      const el = this.$refs.sdChart;
      if (!el || !this.steps.length || typeof Chart === 'undefined') return;
      const s = this.steps;
      const labels = s.map(x => this.hhmm(x.start));
      const cfg = {
        type: 'line',
        data: { labels, datasets: [
          { label: 'Planned SoC %', data: s.map(x => x.soc_pct), yAxisID: 'y1', borderColor: '#34d399', tension: 0.2, pointRadius: 0 },
          { label: 'Battery kW (+ charge)', data: s.map(x => x.battery_kw), yAxisID: 'y', borderColor: '#60a5fa', stepped: true, pointRadius: 0 },
          { label: 'Import price', data: s.map(x => x.import_price), yAxisID: 'y2', borderColor: '#f87171', stepped: true, pointRadius: 0, borderDash: [4, 3] },
          { label: 'Export price', data: s.map(x => x.export_price), yAxisID: 'y2', borderColor: '#fbbf24', stepped: true, pointRadius: 0, borderDash: [2, 3] },
        ] },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { labels: { color: '#94a3b8', font: { size: 10 } } } },
          scales: {
            x: { ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 12 }, grid: { color: 'rgba(148,163,184,.08)' } },
            y: { position: 'left', title: { display: true, text: 'kW', color: '#64748b' }, ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(148,163,184,.08)' } },
            y1: { position: 'right', min: 0, max: 100, title: { display: true, text: 'SoC %', color: '#34d399' }, ticks: { color: '#34d399', font: { size: 10 } }, grid: { drawOnChartArea: false } },
            y2: { position: 'right', title: { display: true, text: 'price', color: '#f87171' }, ticks: { color: '#f87171', font: { size: 10 } }, grid: { drawOnChartArea: false } },
          },
        },
      };
      if (this._chart) Alpine.raw(this._chart).destroy();
      this._chart = new Chart(el, cfg);
    },
  };
}
