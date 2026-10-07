/**
 * Scheduler tab — time windows that run a local action and optional HA actions.
 *
 * The action list comes from the server, including which actions are UNAVAILABLE
 * and why. Force charge / discharge / standby are Modbus-only; showing them here
 * greyed with the reason is more honest than hiding them, because someone coming
 * from the Modbus Bridge will look for them.
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('schedulerTab', () => ({
    schedules: [], actions: {}, unavailable: {}, force_available: false, force_reason: '',
    sensors: [], ops: [], gateways: [],
    haNames: {},   // exposed HA entity_id -> friendly name (condition-label enrichment)
    explainId: null, explainLevel: 'medium',   // per-schedule plain-language explanation
    devices: [],
    instances: [],
    haEntities: [],   // controllable exposed HA entities for the guided picker
    advRepeat: false,
    exitTestResult: null,
    listFilter: 'all',   // all | enabled | disabled
    trigger_types: [], cron_available: false, presetSel: '',
    loading: false, error: '', busy: false,
    form: null,
    testResult: null,
    traceByCid: {},
    _cidSeq: 0,
    text_rhs_ops: [],
    presets: [],
    presetOpen: false,
    importReport: null,
    view: 'schedules',       // schedules | timeline | history
    timeline: null,
    logEvents: null,
    logFilter: '',

    init() {
      this.$watch('$store.app.activeTab', (t) => { if (t === 'scheduler' && !this.schedules.length) this.load(); });
      if (this.$store.app.activeTab === 'scheduler') this.load();
    },

    get canWrite() { return !!this.$store.app.summary.writes_enabled; },

    async load() {
      this.loading = true; this.error = '';
      try {
        const r = await fetch('api/schedules');
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        const d = await r.json();
        this.schedules = d.schedules || [];
        this.actions = d.actions || {};
        this.unavailable = d.unavailable || {};
        this.force_available = !!d.force_available;
        this.force_reason = d.force_reason || '';
        this.trigger_types = d.trigger_types || [];
        this.cron_available = !!d.cron_available;
        this.sensors = d.sensors || [];
        this.gateways = d.gateways || [];
        this.ops = d.ops || [];
        this.text_rhs_ops = d.text_rhs_ops || [];
        try {
          this.devices = (await (await fetch('api/ha/notify-devices')).json()).devices || [];
        } catch { this.devices = []; }
        try {
          this.instances = (await (await fetch('api/ha/instances')).json()).instances || [];
        } catch { this.instances = []; }
        this.loadHaEntities();
      } catch (e) { this.error = e.message; }
      finally { this.loading = false; }
    },

    async setView(v) {
      this.view = v;
      if (v === 'timeline') this.timeline = await (await fetch('api/schedules/timeline')).json();
      if (v === 'history') this.logEvents = (await (await fetch('api/schedules/log?limit=200')).json()).events;
    },

    hhmm(min) {
      const m = ((min % 1440) + 1440) % 1440;
      return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
    },
    when(ts) { return this.$store.app._fmtHostTime(ts); },   // scheduler activity log — HOST zone

    // ─── Activity log filtering + status colours ───
    get logStatuses() {
      const counts = {};
      for (const e of (this.logEvents || [])) counts[e.status] = (counts[e.status] || 0) + 1;
      const order = ['fired', 'executed', 'exit', 'waiting', 'gated', 'missed', 'error', 'manual', 'created', 'updated', 'enabled', 'disabled', 'stopped', 'deferred', 'deleted', 'dispatch-start', 'dispatch-end', 'vpp-start', 'vpp-stop', 'orphan'];
      return Object.entries(counts)
        .sort((a, b) => (order.indexOf(a[0]) + 1 || 99) - (order.indexOf(b[0]) + 1 || 99))
        .map(([status, n]) => ({ status, n }));
    },
    _isBatteryEvent(e) { return e.schedule_id === '_batt' || e.schedule_id === '_vpp'; },
    get batteryLogCount() { return (this.logEvents || []).filter(e => this._isBatteryEvent(e)).length; },
    get filteredLog() {
      const evs = this.logEvents || [];
      if (!this.logFilter) return evs;
      if (this.logFilter === '_battery_') return evs.filter(e => this._isBatteryEvent(e));
      return evs.filter(e => e.status === this.logFilter);
    },
    setLogFilter(s) { this.logFilter = (this.logFilter === s ? '' : s); },

    // ─── Timeline chart helpers ───
    modeColor(m) {
      const s = (m || '').toLowerCase();
      if (s.includes('self')) return '#34d399';
      if (s.includes('time') || s.includes('tou')) return '#38bdf8';
      if (s.includes('backup')) return '#c4b5fd';
      return '#94a3b8';
    },
    get modeLegend() {
      const seen = {}, out = [];
      for (const m of (this.timeline?.modes || [])) {
        if (!seen[m.mode]) { seen[m.mode] = 1; out.push({ mode: m.mode, color: this.modeColor(m.mode) }); }
      }
      return out;
    },
    /** SoC polyline points in the SVG's 0..1440 x / 0..100 y space (band = top 12). */
    get socPoints() {
      return (this.timeline?.soc || [])
        .map(p => `${p.min},${(98 - (Math.max(0, Math.min(100, p.soc)) / 100) * 82).toFixed(1)}`)
        .join(' ');
    },
    fireColor(status) {
      return { fired: '#34d399', exit: '#38bdf8', gated: '#94a3b8', error: '#fb7185' }[status] || '#fbbf24';
    },

    /** The chart interior as an SVG string — <template x-for> does not work inside
     *  an <svg> (SVG namespace), so build the children and inject via x-html. */
    get svgInner() {
      const t = this.timeline;
      if (!t) return '';
      const L = (x1,y1,x2,y2,stroke,w,dash='') =>
        `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${w}"${dash?` stroke-dasharray="${dash}"`:''} vector-effect="non-scaling-stroke"/>`;
      let o = '';
      for (const h of [6,12,18]) o += L(h*60,0,h*60,100,'rgba(148,163,184,0.22)',1);
      for (const m of (t.modes||[]))
        o += `<rect x="${m.start_min}" y="0" width="${Math.max(0.5,m.end_min-m.start_min)}" height="12" fill="${this.modeColor(m.mode)}" opacity="0.55"/>`;
      if (this.socPoints)
        o += `<polyline points="${this.socPoints}" fill="none" stroke="#38bdf8" stroke-width="1.5" vector-effect="non-scaling-stroke"/>`;
      for (const f of (t.fires||[])) o += L(f.min,14,f.min,100,this.fireColor(f.status),1,'2 2');
      o += L(t.now_min,0,t.now_min,100,'#fbbf24',1.5);
      return o;
    },
    statusStyle(s) {
      const m = { fired: '#34d399', executed: '#34d399', exit: '#38bdf8', waiting: '#fbbf24',
                  gated: '#94a3b8', missed: '#fb923c', error: '#fb7185', manual: '#c4b5fd',
                  'dispatch-start': '#22d3ee', 'dispatch-end': '#94a3b8',
                  'vpp-start': '#fbbf24', 'vpp-stop': '#94a3b8', orphan: '#fb7185',
                  created: '#2dd4bf', updated: '#94a3b8', enabled: '#34d399',
                  disabled: '#94a3b8', deleted: '#fb7185', stopped: '#fb923c',
                  deferred: '#fbbf24' };
      const c = m[s] || '#94a3b8';
      return `background:${c}22;color:${c}`;
    },

    // ─── Actions ─────────────────────────────────
    async openPresets() {
      if (!this.presets.length) {
        this.presets = (await (await fetch('api/schedules/presets')).json()).presets || [];
      }
      this.presetOpen = true;
    },

    /** Load a preset INTO the editor (disabled), not fire it — you review first. */
    loadPreset(p) {
      const b = this.blank();
      this.form = { ...b, ...(p.spec || {}), name: p.name, enabled: false,
                    action: { ...(p.spec?.action || { kind: '' }) },
                    conditions: JSON.parse(JSON.stringify(p.spec?.conditions || [])),
                    entry_hold_s: p.spec?.entry_hold_s ?? 0,
                    ha_actions: this._haToForm(p.spec?.ha_actions) };
      this.presetOpen = false;
      this.testResult = null;
      this.traceByCid = {};
      this._ensureCids();
      // Reveal the advanced repeat controls if any are in use.
      this.advRepeat = !!(this.form.months.length || this.form.day_of_month
                          || this.form.start_date || this.form.end_date);
    },

    /** Download all schedules as a portable bundle. */
    exportOpen: false,
    async exportAll(fmt) {
      try {
        const q = fmt === 'automations' ? '?fmt=automations' : '';
        const bundle = await (await fetch('api/schedules/export' + q)).json();
        const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = fmt === 'automations' ? 'franklinwh-automations.json' : 'franklinwh-schedules.json';
        a.click();
        URL.revokeObjectURL(a.href);
        this.exportOpen = false;
      } catch (e) { this.$store.app.toast(`Export failed: ${e.message}`, 'error'); }
    },

    /** Pick a file, dry-run validate it, show the report before committing. */
    triggerImport() { this.$refs.importFile.click(); },
    async onImportFile(ev) {
      const file = ev.target.files[0];
      ev.target.value = '';
      if (!file) return;
      let bundle;
      try {
        bundle = JSON.parse(await file.text());
      } catch (e) {
        this.$store.app.toast(`Import failed: not valid JSON — ${e.message}`, 'error');
        return;
      }
      this._importBundle = bundle;
      try {
        const r = await fetch('api/schedules/import?dry_run=true', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(bundle),
        });
        const data = await r.json();
        // A rejected bundle (wrong type / bad shape) returns an error object with no
        // count/importable — show WHY instead of an "undefined of undefined" dialog.
        if (!r.ok) {
          const why = data.detail || r.statusText || 'unrecognised bundle';
          this.$store.app.toast(`Import rejected: ${why}`, 'error');
          this.importReport = null;
          return;
        }
        this.importReport = data;
      } catch (e) { this.$store.app.toast(`Import failed to read: ${e.message}`, 'error'); }
    },
    async confirmImport() {
      try {
        const r = await fetch('api/schedules/import?dry_run=false', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this._importBundle),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        this.$store.app.toast(
          `Imported ${(out.created || []).length} (disabled for review)`, 'success');
        this.importReport = null;
        await this.load();
      } catch (e) { this.$store.app.toast(`Import failed: ${e.message}`, 'error'); }
    },

    blank() {
      return { id: '', name: '', enabled: true, fire_at: '18:00', duration_min: 90,
               match: 'all', gateway_id: '', conditions: [], exit_conditions: [],
               exit_match: 'all', entry_hold_s: 0, action: { kind: '' }, ha_actions: [],
               days: [], months: [], day_of_month: null, start_date: null, end_date: null,
               priority: 0, conflict: 'override',
               trigger_type: 'daily', windows: [], interval_min: 30, anchor: '', cron: '0 3 * * *' };
    },
    newEntry() { this.testResult = null; this.traceByCid = {}; this.advRepeat = false; this.form = this.blank(); },
    editEntry(s) {
      this.testResult = null;
      this.form = {
        id: s.id, name: s.name, enabled: s.enabled,
        fire_at: s.fire_at || '18:00', duration_min: s.duration_min ?? 0,
        match: s.match || 'all', gateway_id: s.gateway_id || '',
        conditions: JSON.parse(JSON.stringify(s.conditions || [])),
        exit_conditions: JSON.parse(JSON.stringify(s.exit_conditions || [])),
        exit_match: s.exit_match || 'all',
        days: [...(s.days || [])], months: [...(s.months || [])],
        day_of_month: s.day_of_month ?? null,
        start_date: s.start_date || null, end_date: s.end_date || null,
        priority: s.priority ?? 0, conflict: s.conflict || 'override',
        trigger_type: s.trigger_type || 'daily',
        windows: (s.windows || []).map(w => ({ ...w })),
        interval_min: s.interval_min ?? 30, anchor: s.anchor || '', cron: s.cron || '0 3 * * *',
        entry_hold_s: s.entry_hold_s ?? 0,
        action: JSON.parse(JSON.stringify(s.action || { kind: '' })),
        ha_actions: this._haToForm(s.ha_actions),
        // (advRepeat toggled below once form is built)
      };
      this.traceByCid = {};
      this._ensureCids();
    },
    closeForm() { this.form = null; this.testResult = null; },
    /** Duplicate an existing schedule into the editor as a NEW (unsaved) entry —
     *  the original is untouched until you save the copy. */
    duplicate(s) {
      this.editEntry(s);              // rehydrates conditions + ha_action guards
      this.form.id = '';             // no id -> saves as a new schedule
      this.form.name = 'Copy of ' + (s.name || 'schedule');
      this.form.enabled = false;
      this.testResult = null; this.traceByCid = {};
    },

    newHaGuard() {
      return { enabled: false, sensor: this.sensors[0]?.id || '', op: '<', value: 0,
               value2: 0, value_kind: 'value', value_sensor: '' };
    },
    addHa() {
      this.form.ha_actions.push({ ha_kind: 'notify', device_id: this.devices[0]?.id || '',
        when: 'fire', title: '', message: '', guard: this.newHaGuard() });
    },
    addHaService() {
      this.form.ha_actions.push({ ha_kind: 'service', raw: false, instance_id: '',
        when: 'fire', entity_id: '', domain: '', service: 'turn_on', data: {}, guard: this.newHaGuard() });
    },

    // ─── guided HA-entity picker (parity with the Modbus bridge) ───
    async loadHaEntities() {
      try {
        const CTRL = ['switch', 'input_boolean', 'light', 'select', 'input_select',
                      'number', 'input_number', 'button', 'scene', 'script'];
        const d = await (await fetch('api/ha/entities?exposed=true&limit=1000')).json();
        const all = d.entities || [];
        // Friendly-name map for ALL exposed entities — condition sensors include
        // non-controllable domains (binary_sensor, sensor, …), so this is broader
        // than the controllable action list below.
        const names = {};
        for (const e of all) if (e.name && e.name !== e.entity_id) names[e.entity_id] = e.name;
        this.haNames = names;
        this._enrichHaSensorLabels();
        this.haEntities = all
          .filter(e => CTRL.includes(e.domain))
          .map(e => ({ instance_id: e.instance_id, instance: e.instance, entity_id: e.entity_id,
                       domain: e.domain, options: e.options || null, min: e.min, max: e.max, step: e.step,
                       label: `${e.name || e.entity_id} (${e.entity_id})` }));
      } catch { this.haEntities = []; }
    },
    /** Rewrite HA-live condition sensor labels (id "ha:<inst>:<entity>") to the
     *  entity's friendly name — the instance is already the optgroup, so the label
     *  just needs the human name (Modbus-bridge parity). Falls back to entity_id. */
    _enrichHaSensorLabels() {
      let changed = false;
      for (const s of this.sensors) {
        if (!s.id || !s.id.startsWith('ha:')) continue;
        const eid = s.id.split(':').slice(2).join(':');
        const fn = this.haNames[eid];
        if (fn && s.label !== fn) { s.label = fn; changed = true; }
      }
      if (changed) this.sensors = [...this.sensors];
    },
    /** Controllable entities grouped by HA instance, for <optgroup>s. */
    get haEntityGroups() {
      const g = {};
      for (const e of this.haEntities) (g[e.instance || 'HA'] ||= []).push(e);
      return Object.entries(g).map(([instance, entities]) => ({ instance, entities }));
    },
    haEntityMeta(a) {
      return this.haEntities.find(e => e.instance_id === a.instance_id && e.entity_id === a.entity_id) || null;
    },
    /** Domain -> widget kind. */
    haControlKind(a) {
      const d = a.domain || (this.haEntityMeta(a) || {}).domain;
      if (['switch', 'input_boolean', 'light'].includes(d)) return 'toggle';
      if (['select', 'input_select'].includes(d)) return 'select';
      if (['number', 'input_number'].includes(d)) return 'number';
      if (d === 'button') return 'press';
      if (['scene', 'script'].includes(d)) return 'run';
      return 'toggle';
    },
    _defaultServiceFor(domain) {
      if (['select', 'input_select'].includes(domain)) return 'select_option';
      if (['number', 'input_number'].includes(domain)) return 'set_value';
      if (domain === 'button') return 'press';
      if (['scene', 'script'].includes(domain)) return 'turn_on';
      return 'turn_on';
    },
    /** Composite "instance_id::entity_id" -> set the action's instance/entity/domain/service. */
    onHaEntityPick(a, composite) {
      const [iid, ...rest] = (composite || '').split('::');
      const eid = rest.join('::');
      a.instance_id = iid || ''; a.entity_id = eid || '';
      const meta = this.haEntities.find(e => e.instance_id === a.instance_id && e.entity_id === a.entity_id);
      a.domain = meta ? meta.domain : '';
      a.service = this._defaultServiceFor(a.domain);
      a.data = {};
    },
    removeHa(i) { this.form.ha_actions.splice(i, 1); },
    /** Stored ha_action -> editor form (guard leaf|null -> {enabled,...}). */
    _guardToForm(g) {
      return { enabled: !!g, sensor: g?.sensor || (this.sensors[0]?.id || ''), op: g?.op || '<',
               value: g?.value ?? 0, value2: g?.value2 ?? 0, value_kind: g?.value_kind || 'value',
               value_sensor: g?.value_sensor || '' };
    },
    _haToForm(list) {
      return (list || []).map(h => ({
        ha_kind: h.ha_kind || 'notify', when: h.when || 'fire',
        device_id: h.device_id || '', title: h.title || '', message: h.message || '',
        instance_id: h.instance_id || '', domain: h.domain || '', service: h.service || '',
        entity_id: h.entity_id || '',
        // guided data is an object; raw data is a JSON string. Keep whatever was saved.
        data: (h.data && typeof h.data === 'object') ? JSON.parse(JSON.stringify(h.data)) : (h.data || (h.entity_id ? {} : '')),
        raw: !!h.raw,
        guard: this._guardToForm(h.guard) }));
    },
    /** Editor form -> stored ha_action (guard {enabled,...} -> leaf|omitted). */
    _haFromForm(list) {
      return (list || []).map(h => {
        let out;
        if (h.ha_kind === 'service') {
          out = { ha_kind: 'service', raw: !!h.raw, when: h.when || 'fire',
                  instance_id: h.instance_id || '', domain: h.domain || '', service: h.service || '',
                  entity_id: h.entity_id || '',
                  data: (h.data && typeof h.data === 'object') ? h.data : (h.data || '') };
        } else {
          out = { ha_kind: 'notify', device_id: h.device_id, when: h.when || 'fire',
                  title: h.title || '', message: h.message || '' };
        }
        const g = h.guard;
        if (g && g.enabled) {
          const leaf = { sensor: g.sensor, op: g.op };
          if (this.isTextRhs(g.op)) leaf.value = g.value ?? '';
          else if ((g.value_kind || 'value') === 'sensor') { leaf.value_kind = 'sensor'; leaf.value_sensor = g.value_sensor || ''; }
          else { leaf.value = this._coerceVal(g.value); if (g.op === 'between') leaf.value2 = this._coerceVal(g.value2); }
          out.guard = leaf;
        }
        return out;
      });
    },

    /** Params differ per action, so the editor asks only for what applies. */
    actionParams(kind) { return (this.actions[kind] || {}).params || []; },

    /** The three operating work modes, read from the gateway itself.
     *  `workmode` (1 TOU / 2 Self / 3 Backup) is the stable alias — the id is a
     *  site-specific GUID and the name can be a tariff ("Solar & Battery Plan"),
     *  so neither travels. Offering a free-text box here was the bug: it let a
     *  meaningless value like 0 be typed in. */
    get modeOptions() {
      const alias = { 1: 'tou', 2: 'self', 3: 'backup' };
      const modes = (this.$store.app.summary.mode || {}).modes || [];
      if (modes.length) {
        return modes
          .filter(m => alias[m.workmode])
          .map(m => ({ value: alias[m.workmode], label: m.name }));
      }
      return [{ value: 'tou', label: 'Time-of-Use' },
              { value: 'self', label: 'Self-Consumption' },
              { value: 'backup', label: 'Emergency Backup' }];
    },

    /** Params that get a picker rather than a text box. */
    paramChoices(param) {
      if (param === 'mode') return this.modeOptions;
      if (param === 'on') return [{ value: 'true', label: 'On' },
                                  { value: 'false', label: 'Off' }];
      if (param === 'circuit') return [1, 2, 3].map(n => ({ value: n, label: `Circuit ${n}` }));
      if (param === 'direction') return [
        { value: 'charge', label: 'Force charge' },
        { value: 'discharge', label: 'Force discharge' },
        { value: 'standby', label: 'Force standby (hold)' }];
      if (param === 'unit') return [
        { value: 'pct', label: '% of inverter power' },
        { value: 'kw', label: 'kW' }];
      return null;
    },

    /** Friendly labels for the force action's params (the generic editor shows the
     *  raw key otherwise). */
    paramLabel(param) {
      return ({ mode: 'Operating mode', direction: 'Direction', unit: 'Power unit',
                power: 'Power', target_soc: 'Target SoC (%, optional)',
                soc: 'SoC (%)' })[param] || param;
    },

    /** Seed sensible defaults when the force action is first chosen, so an empty
     *  form does not silently dispatch 0 W. */
    onActionKind() {
      if (this.form.action.kind !== 'force') return;
      const a = this.form.action;
      if (!a.direction) a.direction = 'discharge';
      if (!a.unit) a.unit = 'pct';
      if (a.power === undefined || a.power === '' || a.power === null) a.power = 100;
      if (a.target_soc === undefined || a.target_soc === null) a.target_soc = '';
    },

    // ─── list: status filter, active-now, next-fire, per-entry stop ───
    get filteredSchedules() {
      const all = this.schedules || [];
      if (this.listFilter === 'enabled') return all.filter(s => s.enabled);
      if (this.listFilter === 'disabled') return all.filter(s => !s.enabled);
      return all;
    },
    get hiddenCount() { return (this.schedules || []).length - this.filteredSchedules.length; },
    get activeCount() { return (this.schedules || []).filter(s => s.active_now).length; },

    /** Human "next fire" from the server-computed epoch. */
    nextFireLabel(s) {
      if (!s.enabled) return 'disabled';
      const ts = s.next_fire;
      if (!ts) return '—';
      const d = new Date(ts * 1000), now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      const tmr = new Date(now); tmr.setDate(tmr.getDate() + 1);
      const isTmr = d.toDateString() === tmr.toDateString();
      const hm = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
      if (sameDay) {
        const mins = Math.round((d - now) / 60000);
        if (mins <= 0) return 'in its window';
        if (mins < 60) return `in ${mins} min`;
        return `today ${hm}`;
      }
      if (isTmr) return `tomorrow ${hm}`;
      const within = (d - now) / 86400000 < 6.5;
      return within ? `${d.toLocaleDateString(undefined, { weekday: 'short' })} ${hm}`
                    : `${d.toLocaleDateString(undefined, { day: '2-digit', month: 'short' })} ${hm}`;
    },

    async stopEntry(s) {
      if (!confirm(`Stop "${s.name}" now? Its running battery dispatch will be released (the schedule stays enabled).`)) return;
      try {
        const r = await fetch(`api/schedules/${s.id}/stop`, { method: 'POST' });
        const d = await r.json();
        this.$store.app.toast(d.stopped ? `Stopped "${s.name}"` : (d.result || 'nothing to stop'),
                              d.stopped ? 'success' : 'info');
        await this.load();
      } catch (e) { this.$store.app.toast(`Stop failed: ${e.message}`, 'error'); }
    },

    async save() {
      if (this.form.trigger_type === 'once') this.form.end_date = this.form.start_date;
      if (this.form.id) {
        const live = (this.schedules || []).find(x => x.id === this.form.id);
        if (live && live.active_now &&
            !confirm('This schedule is running now — save the changes anyway?')) return;
      }
      this.busy = true;
      try {
        const body = { ...this.form,
          conditions: this._buildTree(this.form.conditions, false),
          exit_conditions: this._buildTree(this.form.exit_conditions, false),
          exit_match: this.form.exit_match || 'all',
          entry_hold_s: Number(this.form.entry_hold_s) || 0,
          ha_actions: this._haFromForm(this.form.ha_actions) };
        delete body.id;
        const url = this.form.id ? `api/schedules/${this.form.id}` : 'api/schedules';
        const r = await fetch(url, {
          method: this.form.id ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        this.$store.app.toast('Schedule saved', 'success');
        this.closeForm();
        await this.load();
      } catch (e) { this.$store.app.toast(`Save failed: ${e.message}`, 'error'); }
      finally { this.busy = false; }
    },

    async toggle(s) {
      try {
        const body = { name: s.name, enabled: !s.enabled, fire_at: s.fire_at,
                       duration_min: s.duration_min, match: s.match,
                       gateway_id: s.gateway_id || '',
                       conditions: s.conditions || [], action: s.action || {},
                       ha_actions: s.ha_actions || [] };
        const r = await fetch(`api/schedules/${s.id}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        await this.load();
      } catch (e) { this.$store.app.toast(`Failed: ${e.message}`, 'error'); }
    },

    async remove(s) {
      const ok = await this.$store.app.confirmDialog(
        `Delete "${s.name}"? To pause it instead, switch it off.`,
        { title: 'Delete schedule', danger: true });
      if (!ok) return;
      try {
        await fetch(`api/schedules/${s.id}`, { method: 'DELETE' });
        await this.load();
      } catch (e) { this.$store.app.toast(`Failed: ${e.message}`, 'error'); }
    },

    /** Evaluate against live values WITHOUT firing — shows each row's actual. */
    async verify(s) {
      this.busy = true;
      try {
        const r = await fetch(`api/schedules/${s.id}/test`, { method: 'POST' });
        this.testResult = { id: s.id, ...(await r.json()) };
      } catch (e) { this.$store.app.toast(`Test failed: ${e.message}`, 'error'); }
      finally { this.busy = false; }
    },

    /** Run the actions now, ignoring the window. This performs REAL actions. */
    async runNow(s) {
      const ok = await this.$store.app.confirmDialog(
        `Run "${s.name}" now? Its actions will execute immediately, ignoring the window.`,
        { title: 'Run schedule now', danger: true });
      if (!ok) return;
      this.busy = true;
      try {
        const r = await fetch(`api/schedules/${s.id}/run` + this.$store.app.gwQuery(),
                              { method: 'POST' });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        this.$store.app.toast((out.results || []).join(' · ') || 'nothing to do', 'info');
        await this.load();
      } catch (e) { this.$store.app.toast(`Run failed: ${e.message}`, 'error'); }
      finally { this.busy = false; }
    },

    // ─── Condition tree (nestable ALL/ANY groups + Value|Lookup) ───
    isGroup(c) { return !!(c && c.conditions); },
    isTextRhs(op) { return this.text_rhs_ops.includes(op); },
    _newLeaf() {
      return { sensor: this.sensors[0]?.id || '', op: '<', value: 0, value2: 0,
               value_kind: 'value', value_sensor: '', _cid: ++this._cidSeq };
    },
    addRow() { this.form.conditions.push(this._newLeaf()); },
    addGroup() { this.form.conditions.push({ match: 'all', conditions: [this._newLeaf()], _cid: ++this._cidSeq }); },
    removeCond(i) { this.form.conditions.splice(i, 1); },
    addToGroup(g) { (g.conditions ||= []).push(this._newLeaf()); },
    removeFromGroup(g, j) { g.conditions.splice(j, 1); },

    // Exit conditions use the SAME nestable ALL/ANY builder as entry conditions.
    addExitRow() { (this.form.exit_conditions ||= []).push(this._newLeaf()); },
    addExitGroup() { (this.form.exit_conditions ||= []).push({ match: 'all', conditions: [this._newLeaf()], _cid: ++this._cidSeq }); },
    removeExitCond(i) { this.form.exit_conditions.splice(i, 1); },

    triggerLabel(t) {
      return ({ window: 'Recurring windows', once: 'One-off date', daily: 'Daily at time',
                weekly: 'Weekly at time', interval: 'Every N minutes', monthly: 'Monthly / calendar',
                cron: 'Custom cron', always: 'Always (sensor-driven)' })[t] || t;
    },
    get showFireAt() { return ['daily', 'weekly', 'monthly', 'once'].includes(this.form.trigger_type); },
    get showDays() { return ['window', 'weekly'].includes(this.form.trigger_type); },
    get showWindows() { return ['window', 'once'].includes(this.form.trigger_type); },
    get showDate() { return this.form.trigger_type === 'once'; },
    get showMonthly() { return this.form.trigger_type === 'monthly'; },
    get showInterval() { return this.form.trigger_type === 'interval'; },
    get showCron() { return this.form.trigger_type === 'cron'; },
    get showAlways() { return this.form.trigger_type === 'always'; },

    addWindow() { (this.form.windows ||= []).push({ start: '06:00', end: '09:00' }); },
    removeWindow(i) { this.form.windows.splice(i, 1); },

    /** Seed sensible defaults when the trigger type changes so no field is left empty. */
    onTriggerType() {
      const t = this.form.trigger_type;
      if (t === 'window' && !(this.form.windows || []).length) this.addWindow();
      if (t === 'interval' && !this.form.interval_min) this.form.interval_min = 30;
      if (t === 'cron' && !this.form.cron) this.form.cron = '0 3 * * *';
    },

    get triggerPresets() {
      return [
        { id: '', label: '— choose a preset —' },
        { id: 'every15', label: 'Every 15 minutes', spec: { trigger_type: 'interval', interval_min: 15 } },
        { id: 'every30', label: 'Every 30 minutes', spec: { trigger_type: 'interval', interval_min: 30 } },
        { id: 'hourly', label: 'Hourly', spec: { trigger_type: 'interval', interval_min: 60 } },
        { id: 'daily8', label: 'Every day 08:00', spec: { trigger_type: 'daily', fire_at: '08:00' } },
        { id: 'weekdays', label: 'Weekdays 18:00', spec: { trigger_type: 'weekly', days: [0, 1, 2, 3, 4], fire_at: '18:00' } },
        { id: 'weekly_sun', label: 'Weekly (Sun) 00:00', spec: { trigger_type: 'weekly', days: [6], fire_at: '00:00' } },
        { id: 'monthly1', label: 'Monthly (1st)', spec: { trigger_type: 'monthly', day_of_month: 1, fire_at: '00:00' } },
        { id: 'quarterly', label: 'Quarterly (1st)', spec: { trigger_type: 'monthly', day_of_month: 1, months: [1, 4, 7, 10], fire_at: '00:00' } },
        { id: 'annually', label: 'Annually (Jan 1)', spec: { trigger_type: 'monthly', day_of_month: 1, months: [1], fire_at: '00:00' } },
        { id: 'nightly3', label: 'Nightly 03:00 (cron)', spec: { trigger_type: 'cron', cron: '0 3 * * *' } },
      ];
    },
    applyPreset() {
      const p = this.triggerPresets.find(x => x.id === this.presetSel);
      this.presetSel = '';
      if (!p || !p.spec) return;
      Object.assign(this.form, { days: [], months: [], day_of_month: null, windows: [] }, p.spec);
      this.onTriggerType();
    },

    toggleDay(i) {
      const a = (this.form.days ||= []);
      const k = a.indexOf(i);
      if (k >= 0) a.splice(k, 1); else { a.push(i); a.sort((x, y) => x - y); }
    },
    toggleMonth(m) {
      const a = (this.form.months ||= []);
      const k = a.indexOf(m);
      if (k >= 0) a.splice(k, 1); else { a.push(m); a.sort((x, y) => x - y); }
    },
    /** Short human recurrence label for the editor + list cards. */
    recurrenceLabel(e) {
      const tt = e.trigger_type || 'daily';
      if (tt === 'always') return 'Always (sensor-driven)';
      if (tt === 'interval') return `Every ${e.interval_min || '?'} min`;
      if (tt === 'cron') return `Cron: ${e.cron || '?'}`;
      if (tt === 'once') return e.start_date ? ('Once on ' + e.start_date) : 'One-off';
      if (tt === 'window' && (e.windows || []).length)
        return e.windows.map(w => `${w.start}–${w.end}`).join(', ');
      const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      const parts = [];
      const days = e.days || [];
      if (days.length) {
        const set = [...days].sort((a, b) => a - b);
        if (set.length === 7) parts.push('Daily');
        else if (set.join(',') === '0,1,2,3,4') parts.push('Weekdays');
        else if (set.join(',') === '5,6') parts.push('Weekends');
        else parts.push(set.map(d => DOW[d]).join(' '));
      }
      if (e.day_of_month) parts.push('day ' + e.day_of_month);
      const months = e.months || [];
      if (months.length && months.length < 12) parts.push(months.map(m => MON[m - 1]).join(' '));
      if (e.start_date && e.start_date === e.end_date) return 'once on ' + e.start_date;
      if (e.start_date) parts.push('from ' + e.start_date);
      if (e.end_date) parts.push('until ' + e.end_date);
      return parts.length ? parts.join(' · ') : 'Every day';
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Plain-language explainability (min / medium / full) — the "what will this
    // automation actually do?" panel, in the spirit of the FWHAI automations dialog.
    // Built from the same labels the picker uses, so HA entities read as their
    // friendly names and sensors/ops/values read as written.
    // ─────────────────────────────────────────────────────────────────────────
    _opPhrase(op) {
      return ({ '<': 'is below', '<=': 'is at most', '==': 'is', '!=': 'is not',
        '>=': 'is at least', '>': 'is above', 'between': 'is between', 'in': 'is one of',
        'not_in': 'is not one of', 'matchlist': 'matches one of', 'not_matchlist': 'matches none of',
        'like': 'is like', 'not_like': 'is not like' })[op] || op;
    },
    _leafPhrase(leaf) {
      const name = this.sensorLabel(leaf.sensor);
      const op = this._opPhrase(leaf.op);
      let rhs;
      if (leaf.value_kind === 'sensor') rhs = '“' + this.sensorLabel(leaf.value_sensor) + '”';
      else if (leaf.op === 'between') rhs = `${leaf.value} and ${leaf.value2}`;
      else rhs = String(leaf.value);
      return `${name} ${op} ${rhs}`;
    },
    _condPhrase(nodes, match, depth) {
      if (!nodes || !nodes.length) return '';
      const join = (match === 'any') ? ' OR ' : ' AND ';
      const parts = nodes.map(n => {
        if (this.isGroup(n)) {
          const inner = this._condPhrase(n.conditions, n.match || 'all', (depth || 0) + 1);
          return `(${inner})`;
        }
        return this._leafPhrase(n);
      });
      return parts.join(join);
    },
    _triggerPhrase(s) {
      const rec = this.recurrenceLabel(s);
      const tt = s.trigger_type || 'daily';
      let at = '';
      if (tt !== 'window' && tt !== 'interval' && tt !== 'cron' && tt !== 'always' && s.fire_at)
        at = ` at ${s.fire_at}`;
      const dur = s.duration_min ? ` for ${s.duration_min} min` : '';
      return `${rec}${at}${dur}`;
    },
    _actionPhrase(s) {
      const a = s.action || {}; const out = [];
      if (a.kind === 'force') {
        const dir = a.direction || 'discharge';
        const pw = (a.power === '' || a.power == null) ? null
          : (a.unit === 'pct' ? `${a.power}% power` : `${(Number(a.power) / 1000)} kW`);
        let t = `force ${dir}` + (pw ? ` at ${pw}` : '');
        if (a.target_soc !== '' && a.target_soc != null) t += ` until SoC reaches ${a.target_soc}%`;
        out.push(t);
      } else if (a.kind === 'set_mode') {
        const m = (this.modeOptions.find(o => o.value === a.mode) || {}).label || a.mode;
        out.push(`set the operating mode to ${m}`);
      } else if (a.kind === 'smart_circuit') {
        out.push(`turn ${String(a.on) === 'true' || a.on === true ? 'ON' : 'OFF'} smart circuit ${a.circuit}`);
      } else if (a.kind === 'offgrid') {
        out.push(String(a.on) === 'true' || a.on === true ? 'go off-grid' : 'reconnect to the grid');
      } else if (a.kind === 'reserve_soc') {
        out.push(`set the reserve SoC to ${a.soc}%`);
      } else if (a.kind === 'notify') {
        out.push('send a Home Assistant notification');
      } else if (a.kind) {
        out.push((this.actions[a.kind] || {}).label || a.kind);
      }
      for (const h of (s.ha_actions || [])) {
        if (h.ha_kind === 'service') {
          const ent = this.haNames[h.entity_id] || h.entity_id || 'an entity';
          const svc = (h.service || 'call').replace(/_/g, ' ');
          out.push(`${svc} “${ent}”`);
        } else {
          out.push('notify a companion device');
        }
      }
      return out.length ? out.join(', then ') : 'take no gateway action';
    },
    /** Compose the explanation at a verbosity level: 'min' | 'medium' | 'full'. */
    explain(s, level) {
      const trig = this._triggerPhrase(s);
      const act = this._actionPhrase(s);
      const conds = this._condPhrase(s.conditions, s.match || 'all', 0);
      const exits = this._condPhrase(s.exit_conditions, s.exit_match || 'all', 0);
      if (level === 'min') {
        return `${trig} → ${act}.`;
      }
      if (level === 'medium') {
        let t = `When ${trig}`;
        if (conds) t += `, and only if ${conds}`;
        t += `, ${act}.`;
        if (exits) t += ` End early when ${exits}.`;
        return t;
      }
      // full — labelled, multi-line
      const lines = [];
      lines.push(`WHEN   ${trig}.`);
      lines.push(conds ? `IF     ${conds} (${(s.match || 'all') === 'any' ? 'any' : 'all'} must hold).`
                       : `IF     no extra conditions — fires whenever the schedule is due.`);
      lines.push(`DO     ${act}.`);
      if (exits) lines.push(`UNTIL  it ends early when ${exits} (${(s.exit_match || 'all') === 'any' ? 'any' : 'all'}).`);
      const gw = (this.gateways.find(g => g.id === s.gateway_id) || {});
      if (s.gateway_id) lines.push(`ON     ${gw.name || s.gateway_id}.`);
      if (s.entry_hold_s) lines.push(`HOLD   conditions must stay true for ${s.entry_hold_s}s before firing.`);
      return lines.join('\n');
    },
    toggleExplain(s) { this.explainId = (this.explainId === s.id) ? null : s.id; },

    /** Give every leaf a stable _cid so a Test Verification result maps back to
     *  its row even inside a group. */
    _ensureCids(nodes = this.form?.conditions || []) {
      for (const n of nodes) {
        if (!n._cid) n._cid = ++this._cidSeq;
        if (this.isGroup(n)) this._ensureCids(n.conditions || []);
      }
    },
    /** Flatten the tree to a single list for rendering — Alpine dislikes a
     *  dynamic <template x-for> nested inside another. Each item references the
     *  real node object so x-model still mutates the tree. */
    _flatten(list) {
      const out = [];
      (list || []).forEach((c, i) => {
        if (this.isGroup(c)) {
          out.push({ kind: 'group', node: c, i });
          (c.conditions || []).forEach((cc, j) =>
            out.push({ kind: 'grouprow', node: cc, group: c, i, j }));
          if (!(c.conditions || []).length) out.push({ kind: 'groupempty', node: c, i });
        } else {
          out.push({ kind: 'row', node: c, i });
        }
      });
      return out;
    },
    get flatConds() { this._ensureCids(this.form?.conditions || []); return this._flatten(this.form?.conditions || []); },
    get flatExit() { this._ensureCids(this.form?.exit_conditions || []); return this._flatten(this.form?.exit_conditions || []); },
    _coerceVal(v) {
      if (v === '' || v === null || v === undefined) return v;
      const n = Number(v);
      return (typeof v === 'string' && v.trim() !== '' && !isNaN(n)) ? n : v;
    },
    /** Serialise the editor tree for the API. withCid=true for Test Verify (so
     *  results map to rows); false for save. Prunes empty nested groups. */
    _buildTree(nodes, withCid) {
      const out = [];
      for (const c of nodes || []) {
        if (this.isGroup(c)) {
          const kids = this._buildTree(c.conditions || [], withCid);
          if (kids.length) out.push({ match: c.match || 'all', conditions: kids });
          continue;
        }
        const row = { sensor: c.sensor, op: c.op };
        if (this.isTextRhs(c.op)) {
          row.value = c.value ?? '';                       // raw string (list/pattern)
        } else if ((c.value_kind || 'value') === 'sensor') {
          row.value_kind = 'sensor'; row.value_sensor = c.value_sensor || '';
        } else {
          row.value = this._coerceVal(c.value);
          if (c.op === 'between') row.value2 = this._coerceVal(c.value2);
        }
        if (withCid) row.cid = c._cid;
        out.push(row);
      }
      return out;
    },

    /** Test Verification — evaluate the UNSAVED tree against live values. */
    async testExit() {
      this.busy = true;
      try {
        this._ensureCids(this.form.exit_conditions);
        const body = { match: this.form.exit_match || 'all',
                       conditions: this._buildTree(this.form.exit_conditions, true) };
        const r = await fetch('api/schedules/evaluate' + this.$store.app.gwQuery(), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        const by = { ...this.traceByCid };
        for (const row of out.per_condition || []) if (row.cid != null) by[row.cid] = row;
        this.traceByCid = by;                          // shared: exit cids are distinct from entry
        this.exitTestResult = { result: out.result };
      } catch (e) { this.$store.app.toast(`Test failed: ${e.message}`, 'error'); }
      finally { this.busy = false; }
    },
    async testVerify() {
      this.busy = true;
      try {
        this._ensureCids();
        const body = { match: this.form.match || 'all',
                       conditions: this._buildTree(this.form.conditions, true) };
        const r = await fetch('api/schedules/evaluate' + this.$store.app.gwQuery(), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        const by = {};
        for (const row of out.per_condition || []) if (row.cid != null) by[row.cid] = row;
        this.traceByCid = by;
        this.testResult = { result: out.result };
      } catch (e) { this.$store.app.toast(`Test failed: ${e.message}`, 'error'); }
      finally { this.busy = false; }
    },

    // per-row verdict, from the last Test Verification
    condTested(c) { return c._cid != null && this.traceByCid[c._cid] !== undefined; },
    condLive(c) { const t = this.traceByCid[c._cid]; return t ? t.live_value : undefined; },
    condPassed(c) { return this.condTested(c) && this.traceByCid[c._cid].result === true; },
    condFailed(c) { return this.condTested(c) && this.traceByCid[c._cid].result === false; },
    _condNoValue(c) { return this.condTested(c) && (this.condLive(c) === null || this.condLive(c) === undefined); },
    condVerdict(c) {
      if (!this.condTested(c)) return '';
      if (this._condNoValue(c)) return `no value`;
      return this.condPassed(c) ? `live ${this.condLive(c)} (pass)` : `live ${this.condLive(c)} (fail)`;
    },
    condVerdictClass(c) {
      if (this._condNoValue(c)) return 'text-amber-400';
      return this.condPassed(c) ? 'text-emerald-400' : 'text-rose-400';
    },
    condRingClass(c) {
      if (!this.condTested(c)) return '';
      if (this._condNoValue(c)) return 'ring-1 ring-amber-400/60 rounded';
      return this.condPassed(c) ? 'ring-1 ring-emerald-400/60 rounded' : 'ring-1 ring-rose-400/60 rounded';
    },

    // Duration hold (entry_hold_s) <-> HH:MM:SS
    secToHms(s) {
      s = Math.max(0, Number(s) || 0);
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
      return [h, m, sec].map(n => String(n).padStart(2, '0')).join(':');
    },
    hmsToSec(str) {
      const p = String(str || '').split(':').map(n => parseInt(n, 10) || 0);
      while (p.length < 3) p.unshift(0);
      return p[0] * 3600 + p[1] * 60 + p[2];
    },

    deviceName(id) {
      const d = this.devices.find(x => x.id === id);
      return d ? d.alias : '(device missing)';
    },
    sensorLabel(id) {
      const s = this.sensors.find(x => x.id === id);
      return s ? s.label : id;
    },
    /** Flat, filtered list for the styled sensor dropdown: interleaved group headers
     *  and sensors, matched against the filter text on label OR id. One x-for, so no
     *  nested-x-for fragility. */
    pickerItems(q) {
      const t = (q || '').trim().toLowerCase();
      const out = [];
      for (const g of this.sensorGroups) {
        const ss = g.sensors.filter(x => !t
          || (x.label || '').toLowerCase().includes(t) || (x.id || '').toLowerCase().includes(t));
        if (!ss.length) continue;
        out.push({ kind: 'group', name: g.name, key: 'g:' + g.name });
        for (const x of ss) out.push({ kind: 'sensor', id: x.id, label: x.label, key: 's:' + x.id });
      }
      return out;
    },

    /** Sensors grouped for the <optgroup> picker: Gateway, then each HA instance —
     *  the "HA Live: …" grouping the Modbus Bridge shows. */
    get sensorGroups() {
      const groups = {};
      for (const s of this.sensors) {
        const g = s.group || 'Gateway';
        (groups[g] = groups[g] || []).push(s);
      }
      // Gateway first, HA instances after, alphabetical.
      const order = Object.keys(groups).sort((a, b) =>
        (a === 'Gateway' ? -1 : b === 'Gateway' ? 1 : a.localeCompare(b)));
      return order.map(name => ({ name, sensors: groups[name] }));
    },
  }));
});
