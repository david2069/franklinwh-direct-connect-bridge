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
    autoBusy: false,
    autoMsg: null,
    _chart: null,
    // Owner 2026-11-25: Actuals from the site's midnight to now beside the plan; the tariff
    // shaded on the chart (each kind a filter) or as bands (the Tariff view). Remembered here.
    stepsOpen: false,        // the half-hour table, folded by default (owner 2026-11-25)
    showActuals: (() => { try { return localStorage.getItem('fwh-sd-actuals') === '1'; } catch (e) { return false; } })(),
    actuals: null,
    sdView: (() => { try { return localStorage.getItem('fwh-sd-view') || 'chart'; } catch (e) { return 'chart'; } })(),
    shade: (() => { try { return Object.assign({ tou: true, demand: true, bonus: true, penalty: true }, JSON.parse(localStorage.getItem('fwh-sd-shade') || '{}')); } catch (e) { return { tou: true, demand: true, bonus: true, penalty: true }; } })(),

    init() {
      const t = lazyTab(this, 'smart_dispatch', () => this.load());
      this.$watch('$store.app.selectedGateway', () => t.reload());
    },

    _take(v) {
      this.v = v;
      if (this.showActuals) this.loadActuals();
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
      this.createMsg = null;
      // #831: a click always answers here, even when there is nothing to create.
      if (!(this.v && this.v.drafts && this.v.drafts.tasks.length)) {
        this.createMsg = { ok: false, text: 'Nothing to create: the plan has no forced battery action (it is self-consumption, or solar charging the battery by itself), so the Scheduler needs no tasks. Re-evaluate after changing your target or limits.' };
        return;
      }
      this.creating = true;
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

    async setAuto(mode) {
      // Off | Shadow | On; a refusal (On before a week of Shadow) stays in the card.
      this.autoBusy = true;
      this.autoMsg = null;
      try {
        const r = await fetch('api/schedules/smart-dispatch/auto' + this.$store.app.gwQuery('?'), {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { this.autoMsg = { ok: false, text: j.detail || ('Failed (' + r.status + ')') }; return; }
        this._take(j);
        this.autoMsg = { ok: true, text: { off: 'Auto is off.', shadow: 'Shadow: each hour the log below says what it would create.', on: 'On: each hour it creates and updates its Scheduler tasks.' }[mode] };
      } catch (e) {
        this.autoMsg = { ok: false, text: e.message };
      } finally {
        this.autoBusy = false;
        // A refused change puts the select back on the saved mode.
        this.$nextTick(() => { const el = this.$root.querySelector('[data-testid=sd-auto]'); if (el && this.v && this.v.auto) el.value = this.v.auto.mode; });
      }
    },

    autoText(e) {
      if (e.error) return e.error;
      const verb = e.mode === 'on' ? 'Created' : 'Would create';
      const parts = [];
      parts.push(e.create.length ? verb + ': ' + e.create.join(', ') : (e.mode === 'on' ? 'Nothing new' : 'Nothing new to create'));
      if (e.replace.length) parts.push((e.mode === 'on' ? 'Replaced: ' : 'Would replace: ') + e.replace.join(', '));
      if (e.kept) parts.push('kept ' + e.kept);
      if (e.skipped.length) parts.push('skipped: ' + e.skipped.map(k => k.name + ' (' + k.why + ')').join(', '));
      return parts.join(' · ');
    },

    dayTime(ts) {
      return new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
        timeZone: (this.v && this.v.timezone) || undefined }).format(new Date(ts * 1000));
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
    kwh(x) { return x == null ? '—' : x.toFixed(1) + ' kWh'; },
    money(x) { return x == null ? '—' : (x < 0 ? '−' : '') + Math.abs(x).toFixed(2) + (this.currency ? ' ' + this.currency : ''); },
    /** The plan's zone, short ("AEDT"), for the chart's time axis (#50). */
    get zoneShort() {
      try {
        return new Intl.DateTimeFormat('en-AU', { timeZoneName: 'short',
          timeZone: (this.v && this.v.timezone) || undefined }).formatToParts(new Date())
          .find(p => p.type === 'timeZoneName').value;
      } catch (e) { return (this.v && this.v.timezone) || ''; }
    },
    // A Plan inputs row's button: Re-run HEMS setup opens the wizard at its step; the others
    // open the tab where the input is set.
    openInput(i) {
      const a = i.action || {};
      if (a.wizard) {
        window.dispatchEvent(new CustomEvent('fwh:open-setup-task',
          { detail: { id: a.wizard, inline: a.wizard, step: a.step } }));
        return;
      }
      if (a.tab) this.$store.app.activeTab = a.tab;
    },

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

    async toggleActuals() {
      this.showActuals = !this.showActuals;
      try { localStorage.setItem('fwh-sd-actuals', this.showActuals ? '1' : '0'); } catch (e) { /* per browser only */ }
      if (this.showActuals) await this.loadActuals(); else this.$nextTick(() => this.draw());
    },
    async loadActuals() {
      try {
        const r = await fetch('api/smart-dispatch/actuals' + this.$store.app.gwQuery('?'));
        this.actuals = r.ok ? await r.json() : null;
      } catch (e) { this.actuals = null; }
      this.$nextTick(() => this.draw());
    },
    setView(v) {
      this.sdView = v;
      try { localStorage.setItem('fwh-sd-view', v); } catch (e) { /* per browser only */ }
      if (v === 'chart') this.$nextTick(() => this.draw());
    },
    toggleShade(k) {
      this.shade[k] = !this.shade[k];
      try { localStorage.setItem('fwh-sd-shade', JSON.stringify(this.shade)); } catch (e) { /* per browser only */ }
      if (this._chart) Alpine.raw(this._chart).update('none');
    },

    /** The rows: with Actuals on, the half hours since midnight first (actuals only), then
     *  the plan; a plan step with an actual (the one under way) carries it. */
    get rows() {
      const plan = this.steps.map(s => ({ ...s, past: false, actual: null }));
      if (!this.showActuals || !this.actuals) return plan;
      const by = Object.fromEntries((this.actuals.steps || []).map(a => [a.start, a]));
      const first = plan.length ? plan[0].start : Infinity;
      const past = (this.actuals.steps || []).filter(a => a.start < first)
        .map(a => ({ start: a.start, past: true, actual: a }));
      for (const p of plan) p.actual = by[p.start] || null;
      return past.concat(plan);
    },
    /** What the plan's tariff has, so only those filters show. */
    get tariffKinds() {
      const s = this.steps;
      const bands = new Set(s.map(x => x.band).filter(Boolean));
      const exp = s.map(x => x.export_price);
      const low = exp.length ? Math.min(...exp) : 0;
      return { tou: bands.size > 1, demand: s.some(x => x.demand_rate > 0),
        bonus: exp.some(e => e > Math.max(low, 0) + 1e-6), penalty: exp.some(e => e < 0) };
    },
    bandColor(b) {
      const n = String(b || '').toLowerCase();
      if (!n) return 'rgba(148,163,184,.25)';
      if (n.includes('off')) return 'rgba(74,222,128,.55)';
      if (n.includes('shoulder')) return 'rgba(251,191,36,.55)';
      if (n.includes('peak')) return 'rgba(248,113,113,.6)';
      return 'rgba(148,163,184,.4)';
    },
    bandLabel(b) { return String(b || '—').replace(/_/g, '-').replace(/\b\w/g, c => c.toUpperCase()); },
    /** The shade for one plan step (chart background), from the filters that are on. */
    _shadeOf(s) {
      if (!s || s.past) return null;
      const k = this.tariffKinds;
      const low = Math.max(Math.min(...this.steps.map(x => x.export_price)), 0);
      if (k.penalty && this.shade.penalty && s.export_price < 0) return 'rgba(239,68,68,.16)';
      if (k.demand && this.shade.demand && s.demand_rate > 0) return 'rgba(167,139,250,.18)';
      if (k.bonus && this.shade.bonus && s.export_price > low + 1e-6) return 'rgba(250,204,21,.14)';
      if (k.tou && this.shade.tou && s.band) return this.bandColor(s.band).replace(/[\d.]+\)$/, '0.12)');
      return null;
    },
    /** The Tariff view's bands: runs of the same value, as the emulator's TOU schedule. */
    get bands() {
      const s = this.steps;
      if (!s.length) return [];
      const t0 = s[0].start, t1 = s[s.length - 1].start + (s[s.length - 1].duration_s || 1800);
      const runs = (val, col, lab) => {
        const out = [];
        for (const x of s) {
          const v = val(x), last = out[out.length - 1];
          if (last && last.v === v) { last.end = x.start + (x.duration_s || 1800); continue; }
          out.push({ v, start: x.start, end: x.start + (x.duration_s || 1800) });
        }
        return out.map(o => ({ ...o, left: (o.start - t0) / (t1 - t0) * 100, width: (o.end - o.start) / (t1 - t0) * 100,
          color: col(o.v), label: lab(o.v) }));
      };
      const k = this.tariffKinds, rows = [];
      rows.push({ name: 'Plan', segs: runs(x => x.action, a => ({ charge: 'rgba(56,189,248,.55)', discharge: 'rgba(251,191,36,.6)', hold: 'rgba(167,139,250,.55)' }[a] || 'rgba(148,163,184,.3)'), a => ({ self: 'Self', charge: 'Charge', discharge: 'Export', hold: 'Hold' }[a] || a)) });   // short, as the emulator's bands
      rows.push({ name: 'Tariff', segs: runs(x => x.band || '', b => this.bandColor(b), b => this.bandLabel(b)) });
      if (k.demand) rows.push({ name: 'Demand', segs: runs(x => x.demand_rate > 0, d => d ? 'rgba(167,139,250,.6)' : 'transparent', d => d ? 'Demand charge' : '') });
      if (k.bonus || k.penalty) {
        const low = Math.max(Math.min(...s.map(x => x.export_price)), 0);
        rows.push({ name: 'Export', segs: runs(x => x.export_price < 0 ? 'penalty' : (x.export_price > low + 1e-6 ? 'bonus' : ''),
          e => ({ penalty: 'rgba(239,68,68,.55)', bonus: 'rgba(250,204,21,.6)' }[e] || 'transparent'),
          e => ({ penalty: 'Export penalty', bonus: 'Export bonus' }[e] || '')) });
      }
      return rows;
    },
    bandPx: 0,
    /** A band's label only where it fits (about 6.5 px a character at 10 px). */
    fits(g) { return !!g.label && g.width / 100 * this.bandPx > g.label.length * 6.5 + 6; },
    get bandTicks() {
      const s = this.steps;
      if (!s.length) return [];
      const t0 = s[0].start, t1 = s[s.length - 1].start + (s[s.length - 1].duration_s || 1800);
      return s.filter((x, i) => i % 6 === 0).map(x => ({ left: (x.start - t0) / (t1 - t0) * 100, label: this.hhmm(x.start) }));
    },

    draw() {
      const el = this.$refs.sdChart;
      if (!el || !this.steps.length || typeof Chart === 'undefined') return;
      const s = this.rows;
      const labels = s.map(x => this.hhmm(x.start));
      const plan = (f) => s.map(x => x.past ? null : f(x));
      const act = (f) => s.map(x => x.actual ? f(x.actual) : null);
      const self = this;
      const tariffShade = {
        id: 'tariffShade',
        beforeDatasetsDraw(chart) {
          const { ctx, chartArea: a, scales: { x } } = chart;
          const w = s.length > 1 ? x.getPixelForValue(1) - x.getPixelForValue(0) : a.right - a.left;
          ctx.save();
          s.forEach((row, i) => {
            const c = self._shadeOf(row);
            if (!c) return;
            ctx.fillStyle = c;
            ctx.fillRect(x.getPixelForValue(i), a.top, w, a.bottom - a.top);
          });
          ctx.restore();
        },
      };
      const sets = [
        { label: 'Planned SoC %', data: plan(x => x.soc_pct), yAxisID: 'y1', borderColor: '#34d399', tension: 0.2, pointRadius: 0 },
        { label: 'Battery kW (+ charge)', data: plan(x => x.battery_kw), yAxisID: 'y', borderColor: '#60a5fa', stepped: true, pointRadius: 0 },
        { label: 'Import price', data: plan(x => x.import_price), yAxisID: 'y2', borderColor: '#f87171', stepped: true, pointRadius: 0, borderDash: [4, 3] },
        { label: 'Export price', data: plan(x => x.export_price), yAxisID: 'y2', borderColor: '#fbbf24', stepped: true, pointRadius: 0, borderDash: [2, 3] },
      ];
      if (this.showActuals && this.actuals) sets.push(
        { label: 'Actual SoC %', data: act(a => a.soc_pct), yAxisID: 'y1', borderColor: '#059669', borderWidth: 3, pointRadius: 0 },
        { label: 'Actual battery kW', data: act(a => a.battery_kw), yAxisID: 'y', borderColor: '#1d4ed8', borderWidth: 3, stepped: true, pointRadius: 0 });
      const cfg = {
        type: 'line',
        plugins: [tariffShade],
        data: { labels, datasets: sets },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { labels: { color: '#94a3b8', font: { size: 10 } } } },
          scales: {
            x: { title: { display: true, text: 'Time (' + this.zoneShort + ')', color: '#64748b' }, ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 12 }, grid: { color: 'rgba(148,163,184,.08)' } },
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
