/**
 * FranklinWH Local Bridge — Terminal console (global bottom drawer).
 *
 * A REPL over the same two endpoints the Raw command console uses:
 *   GET  /api/raw/catalog   — cmdType aliases (completion + read payloads)
 *   POST /api/raw           — send one cmdType; 428 = write needs --yes
 * The selected gateway (topbar) is the implicit --host prefix, so you type
 * `power_flow`, `call 1405`, `1409 --data {…} --yes`, `catalog`, `help`.
 *
 * Full readline on a native <input> (so Left/Right/Home/End/selection are the
 * browser's): ↑/↓ history, Tab-completion (double-Tab lists), Ctrl-A/E/U/K/W/L,
 * Ctrl-C cancel. Toggle with ` (backtick) or Ctrl-`; Escape closes.
 */
function terminalConsole() {
  const HIST_KEY = 'fwh-term-history';
  const BUILTINS = ['help', 'catalog', 'bms', 'theme', 'accent', 'clear', 'history', 'close'];
  // Curated one-tap commands for touch (iPhone/iPad) — all id-free reads + builtins,
  // so a tap never errors or writes. Rendered as chips above the input.
  const PRESETS = [
    { label: 'power', cmd: 'power_flow' },
    { label: 'run status', cmd: 'ibg_run_status' },
    { label: 'relays', cmd: 'relay_status' },
    { label: 'modes', cmd: 'mode_list' },
    { label: 'bms', cmd: 'bms' },
    { label: 'install', cmd: 'install_profile' },
    { label: 'solar', cmd: 'solar_pv' },
    { label: 'generator', cmd: 'generator' },
    { label: 'network', cmd: 'network_interfaces' },
    { label: 'catalog', cmd: 'catalog' },
    { label: 'help', cmd: 'help' },
  ];
  // Friendly words (incl. the preset chip labels) -> the real cmdType alias, so typing
  // "modes" works the same as clicking the "modes" chip (whose command is mode_list).
  const ALIASES = {
    power: 'power_flow',
    modes: 'mode_list', mode: 'mode_list',
    status: 'ibg_run_status', 'run-status': 'ibg_run_status',
    relays: 'relay_status',
    install: 'install_profile',
    solar: 'solar_pv',
    network: 'network_interfaces',
    grid: 'install_profile',
  };
  return {
    presets: PRESETS,
    cfgOpen: false,   // inline theme/accent panel (the header cog)
    height: 440,               // drawer height (px), drag-resized + persisted
    lines: [],                 // {kind:'in'|'out'|'err'|'info', text}
    input: '',
    busy: false,
    catalog: [],
    writesInfo: {},
    history: [],
    histIdx: -1,               // -1 = editing a fresh line
    histStash: '',
    _lastTab: '',              // for double-Tab "list" behaviour

    // `open` is the shared store flag, so either nav's Terminal button drives the drawer.
    get open() { return this.$store.app.terminalOpen; },
    set open(v) { this.$store.app.terminalOpen = v; },

    // History is per-gateway, so switching gateways in the topbar swaps its recall.
    get _histKey() { return HIST_KEY + ':' + (this.$store.app.selectedGateway || 'default'); },
    _loadHistory() {
      try { this.history = JSON.parse(localStorage.getItem(this._histKey) || '[]'); } catch { this.history = []; }
      this.histIdx = -1;
    },
    init() {
      const h = parseInt(localStorage.getItem('fwh-term-height'), 10);
      if (h) this.height = Math.max(160, Math.min(window.innerHeight * 0.92, h));
      this._loadHistory();
      this._loadCatalog();
      // Greet + focus whenever the drawer opens, however it was opened.
      this.$watch('$store.app.terminalOpen', (v) => { if (v) this._onOpen(); });
      // Swap history when the active gateway changes.
      this.$watch('$store.app.selectedGateway', () => this._loadHistory());
    },
    // Drag the top grip to resize; persists across sessions.
    startResize(e) {
      const sy = e.clientY, sh = this.height;
      const move = (ev) => { this.height = Math.max(160, Math.min(window.innerHeight * 0.92, sh + (sy - ev.clientY))); };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        try { localStorage.setItem('fwh-term-height', String(Math.round(this.height))); } catch { /* private mode */ }
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      e.preventDefault();
    },
    async _loadCatalog() {
      try {
        const r = await (await fetch('api/raw/catalog')).json();
        this.catalog = r.commands || [];
        this.writesInfo = r.writes || {};
      } catch { /* completion is a nicety; the console still sends */ }
    },

    // ── open / close ──────────────────────────────────────────────────────
    toggle() { this.open = !this.open; },
    _onOpen() {
      if (!this.lines.length) this._greet();
      // Focus AFTER the open transition settles — $nextTick fires mid-transition in Safari
      // and the focus is dropped.
      setTimeout(() => { if (this.$refs.input) this.$refs.input.focus(); }, 80);
    },
    // One-tap preset: drop the command in and run it (curated safe reads only).
    quick(cmd) { this.input = cmd; this.run(); this.$nextTick(() => this.$refs.input && this.$refs.input.focus()); },
    _isEditable(el) {
      if (!el) return false;
      if (el === this.$refs.input) return false;   // our own input never blocks the toggle key
      const t = (el.tagName || '').toUpperCase();
      return t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || el.isContentEditable;
    },
    onGlobalKey(e) {
      if (e.key === '`' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.toggle(); return; }
      if (e.key === '`' && !this.open && !this._isEditable(e.target)) { e.preventDefault(); this.toggle(); }
    },

    // ── output helpers ────────────────────────────────────────────────────
    _push(kind, text) {
      this.lines.push({ kind, text });
      if (this.lines.length > 500) this.lines.splice(0, this.lines.length - 500);
      this.$nextTick(() => { const b = this.$refs.log; if (b) b.scrollTop = b.scrollHeight; });
    },
    _greet() {
      this._push('info', 'FranklinWH local terminal — `help` for commands, Tab to complete, ↑/↓ history.');
    },
    get promptHost() {
      const g = this.$store.app.selectedGateway;
      return g ? String(g).split(':')[0] : 'aGate';
    },

    // ── key handling on the input ─────────────────────────────────────────
    onKey(e) {
      const el = e.target;
      if (e.key === 'Enter') { e.preventDefault(); return this.run(); }
      if (e.key === 'Escape') { e.preventDefault(); this.open = false; return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); return this._histPrev(); }
      if (e.key === 'ArrowDown') { e.preventDefault(); return this._histNext(); }
      if (e.key === 'Tab') { e.preventDefault(); return this._complete(); }
      if (e.ctrlKey && !e.altKey && !e.metaKey) {
        const k = e.key.toLowerCase();
        if (k === 'a') { e.preventDefault(); el.setSelectionRange(0, 0); return; }
        if (k === 'e') { e.preventDefault(); const n = this.input.length; el.setSelectionRange(n, n); return; }
        if (k === 'u') { e.preventDefault(); this.input = this.input.slice(el.selectionStart); this.$nextTick(() => el.setSelectionRange(0, 0)); return; }
        if (k === 'k') { e.preventDefault(); this.input = this.input.slice(0, el.selectionStart); return; }
        if (k === 'w') { e.preventDefault(); return this._killWord(el); }
        if (k === 'l') { e.preventDefault(); this.lines = []; return; }
        if (k === 'c') { e.preventDefault(); this._push('in', this._prompt(this.input) + ' ^C'); this.input = ''; this.histIdx = -1; return; }
      }
      if (e.key !== 'Tab') this._lastTab = '';   // any other key resets the double-Tab list
    },
    _killWord(el) {
      const c = el.selectionStart;
      const left = this.input.slice(0, c).replace(/\s*\S+\s*$/, '');
      const right = this.input.slice(c);
      this.input = left + right;
      this.$nextTick(() => el.setSelectionRange(left.length, left.length));
    },

    // ── history ───────────────────────────────────────────────────────────
    _histPrev() {
      if (!this.history.length) return;
      if (this.histIdx === -1) { this.histStash = this.input; this.histIdx = this.history.length; }
      this.histIdx = Math.max(0, this.histIdx - 1);
      this.input = this.history[this.histIdx];
      this._caretEnd();
    },
    _histNext() {
      if (this.histIdx === -1) return;
      this.histIdx += 1;
      if (this.histIdx >= this.history.length) { this.histIdx = -1; this.input = this.histStash; }
      else this.input = this.history[this.histIdx];
      this._caretEnd();
    },
    _caretEnd() { this.$nextTick(() => { const el = this.$refs.input; if (el) { const n = this.input.length; el.setSelectionRange(n, n); } }); },
    _remember(cmd) {
      if (!cmd || this.history[this.history.length - 1] === cmd) return;
      this.history.push(cmd);
      if (this.history.length > 200) this.history.shift();
      try { localStorage.setItem(this._histKey, JSON.stringify(this.history)); } catch { /* private mode */ }
    },

    // ── tab completion ────────────────────────────────────────────────────
    _candidates(prefix) {
      const names = this.catalog.map(c => c.name).concat(BUILTINS).concat(Object.keys(ALIASES));
      return [...new Set(names)].filter(n => n.startsWith(prefix)).sort();
    },
    _complete() {
      const m = this.input.match(/(\S*)$/);
      const frag = m ? m[1] : '';
      // Only complete the FIRST word (the verb); after that leave args alone.
      if (/\s/.test(this.input.trimStart()) && this.input.trimEnd() !== frag) return;
      const cands = this._candidates(frag);
      if (!cands.length) return;
      if (cands.length === 1) { this.input = cands[0] + ' '; this._lastTab = ''; this._caretEnd(); return; }
      const common = this._commonPrefix(cands);
      if (common.length > frag.length) { this.input = common; this._caretEnd(); }
      if (this._lastTab === frag) { this._push('info', cands.join('   ')); this._lastTab = ''; }
      else this._lastTab = frag;
    },
    _commonPrefix(arr) {
      if (!arr.length) return '';
      let p = arr[0];
      for (const s of arr) { while (!s.startsWith(p)) p = p.slice(0, -1); }
      return p;
    },

    // ── run a line ────────────────────────────────────────────────────────
    _prompt(cmd) { return this.promptHost + ' ›'; },
    _resolve(token) {
      if (/^\d+$/.test(token)) return Number(token);
      const name = ALIASES[token.toLowerCase()] || token;
      const hit = this.catalog.find(c => c.name === name);
      return hit ? hit.cmd : null;
    },
    async run() {
      if (this.busy) return;                 // a command is in flight — ignore Enter (input stays typeable)
      const raw = this.input.trim();
      this._push('in', this._prompt(raw) + ' ' + raw);
      this.input = ''; this.histIdx = -1; this._lastTab = '';
      if (!raw) return;
      this._remember(raw);

      // builtins
      const verb = raw.split(/\s+/)[0].toLowerCase();
      if (verb === 'help') return this._help();
      if (verb === 'clear' || verb === 'cls') { this.lines = []; return; }
      if (verb === 'history') { this.history.forEach((h, i) => this._push('info', String(i + 1).padStart(3) + '  ' + h)); return; }
      if (verb === 'close' || verb === 'exit' || verb === 'quit') { this.open = false; return; }
      if (verb === 'catalog') return this._catalogDump(raw.split(/\s+/)[1]);
      if (verb === 'bms') { this.busy = true; try { await this._bms(raw.split(/\s+/)[1]); } finally { this.busy = false; } return; }
      if (verb === 'theme') { this._theme(raw.split(/\s+/)[1]); return; }
      if (verb === 'accent') { this._accent(raw.split(/\s+/)[1]); return; }

      // parse: [call] <alias|cmd> [--data {json}] [--yes]
      let body = raw;
      let confirm = false;
      if (/(^|\s)--yes(\s|$)/.test(body)) { confirm = true; body = body.replace(/(^|\s)--yes(\s|$)/, ' ').trim(); }
      let dataStr = null;
      const di = body.indexOf('--data');
      if (di >= 0) { dataStr = body.slice(di + 6).trim(); body = body.slice(0, di).trim(); }
      let token = body.replace(/^call\s+/i, '').trim().split(/\s+/)[0];
      const cmd = this._resolve(token);
      if (cmd == null) { this._push('err', `unknown command: ${token} — try \`help\` or Tab-complete`); return; }

      let data = null;
      if (dataStr) {
        try { data = JSON.parse(dataStr); }
        catch (e) { this._push('err', `--data is not valid JSON: ${e.message}`); return; }
      }
      await this._send(cmd, data, confirm, token);
    },
    async _send(cmd, data, confirm, token) {
      this.busy = true;
      try {
        const r = await fetch('api/raw' + this.$store.app.gwQuery(), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cmd, data, confirm }),
        });
        const out = await r.json();
        if (r.status === 428) {
          this._push('err', out.detail || 'write needs confirmation');
          this._push('info', `→ re-run with --yes to send this WRITE to cmdType ${cmd}.`);
          return;
        }
        if (!r.ok) { this._push('err', out.detail || r.statusText); return; }
        const name = (this.catalog.find(c => c.cmd === cmd) || {}).name || token || cmd;
        const rc = out.request && out.request.cmdType;
        const ms = out.elapsed_ms != null ? `  ${out.elapsed_ms} ms` : '';
        this._push('out', `# ${cmd} ${name}` + (rc ? `  (sent ${rc})` : '') + ms);
        if (out.warning) this._push('info', 'warning: ' + out.warning);
        this._push('out', JSON.stringify(out.response, null, 2));
      } catch (e) {
        this._push('err', e.message);
      } finally { this.busy = false; }
    },

    // ── informational verbs ───────────────────────────────────────────────
    // Low-level single read used by convenience verbs; returns the response object or null.
    async _raw(cmd, data) {
      try {
        const r = await fetch('api/raw' + this.$store.app.gwQuery(), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cmd, data, confirm: false }),
        });
        const out = await r.json();
        if (!r.ok) { this._push('err', out.detail || r.statusText); return null; }
        return out.response || {};
      } catch (e) { this._push('err', e.message); return null; }
    },
    _n(v, d = 1) { return (v == null || isNaN(v)) ? '?' : (Math.round(v * 10 ** d) / 10 ** d); },

    // `bms` — module list (1831) then per-module cell telemetry (1705). `bms N` = one module.
    async _bms(which) {
      const mod = await this._raw(1831, null);
      if (!mod) return;
      let devs = mod.devMap || [];
      if (!devs.length) { this._push('info', 'no battery modules reported'); return; }
      if (which && which !== 'all') {
        const idx = parseInt(which, 10);
        const pick = devs.find(d => d.id === idx) || devs[idx - 1];
        if (pick) devs = [pick]; else { this._push('err', `no module ${which} (have ${devs.map(d => d.id).join(', ')})`); return; }
      }
      this._push('out', `# bms — ${mod.devNum || devs.length} module${(mod.devNum || devs.length) === 1 ? '' : 's'}`);
      for (const d of devs) {
        const c = await this._raw(1705, { opt: 0, id: d.id });
        if (!c) { this._push('err', `[${d.id}] cell read failed`); continue; }
        const hi = c.singleHighestVolt, lo = c.singleLowestVolt;
        const dv = (hi != null && lo != null) ? (hi - lo) : null;
        this._push('out',
          `[${d.id}] ${d.devSN || '?'}  SoC ${this._n(c.batSoc)}%  SoH ${this._n(c.batSoh)}%  `
          + `${this._n(c.batTotalVolt, 2)}V  ${this._n(c.currGrp, 1)}A  alarm ${c.alarmLevel != null ? c.alarmLevel : '?'}`);
        this._push('info',
          `    cells ${lo != null ? (lo / 1000).toFixed(3) : '?'}\u2013${hi != null ? (hi / 1000).toFixed(3) : '?'}V`
          + (dv != null ? ` (\u0394${dv}mV)` : '')
          + `  temp ${this._n(c.singleLowestTemp)}\u2013${this._n(c.singleHighestTemp)}\u00b0C`
          + (Array.isArray(c.batVolt) ? `  \u00b7 ${c.batVolt.length} cells` : ''));
      }
    },
    // Configure the UI from the terminal (a CLI should configure itself).
    _theme(arg) {
      const app = this.$store.app;
      arg = (arg || '').toLowerCase();
      if (!arg) { this._push('info', 'theme: ' + app.theme + '  (usage: theme dark|light)'); return; }
      if (arg !== 'dark' && arg !== 'light') { this._push('err', 'theme must be dark or light'); return; }
      if (app.theme !== arg) app.toggleTheme();
      this._push('info', 'theme \u2192 ' + arg);
    },
    _accent(arg) {
      const app = this.$store.app;
      arg = (arg || '').toLowerCase();
      if (!arg || arg === 'list') {
        this._push('info', 'accents: ' + app.accents.map(a => a.name.toLowerCase()).join(', ') + ', <#hex>, reset');
        this._push('info', 'current: ' + (app.accent || 'default (#22c55e)'));
        return;
      }
      if (arg === 'reset' || arg === 'default') { app.setAccent(''); this._push('info', 'accent \u2192 default'); return; }
      if (/^#?[0-9a-f]{6}$/i.test(arg)) { const hex = arg[0] === '#' ? arg : '#' + arg; app.setAccent(hex); this._push('info', 'accent \u2192 ' + hex); return; }
      const hit = app.accents.find(a => a.name.toLowerCase() === arg);
      if (hit) { app.setAccent(hit.color); this._push('info', 'accent \u2192 ' + hit.name + ' ' + hit.color); return; }
      this._push('err', 'unknown accent: ' + arg + ' \u2014 try `accent list`');
    },
    _help() {
      [
        'Commands:',
        '  <alias>|<cmd>            read a cmdType     e.g.  power_flow   |   1301',
        '  call <alias|cmd>         same, explicit',
        '  <alias|cmd> --data {…}   write (needs --yes)  e.g.  1727 --data {"opt":3,"current_id":"…"} --yes',
        '  bms [N|all]              battery summary: modules + per-cell SoC/SoH/spread/temp',
        '  catalog [group]          list cmdTypes (optionally filter by group name)',
        '  theme dark|light         switch the UI theme',
        '  accent <name|#hex|reset> recolour the UI (accent list to see names)',
        '  history · clear · close  session history · wipe screen · hide drawer',
        '',
        'Editing:  ↑/↓ history · Tab complete (Tab Tab lists) · Ctrl-A/E move · Ctrl-U/K/W kill · Ctrl-L clear · Ctrl-C cancel',
        'The topbar gateway is the implicit --host; writes go through the same confirm gate as the Raw console.',
      ].forEach(t => this._push('info', t));
    },
    _catalogDump(filter) {
      const f = (filter || '').toLowerCase();
      let rows = this.catalog;
      if (f) rows = rows.filter(c => (c.name + ' ' + (c.description || '')).toLowerCase().includes(f));
      if (!rows.length) { this._push('info', 'no cmdTypes match ' + filter); return; }
      rows.forEach(c => this._push('info',
        String(c.cmd).padEnd(6) + (c.name || '').padEnd(24) + (c.dangerous_write ? '! ' : '  ')
        + (c.description || '').split('\n')[0].slice(0, 60)));
      this._push('info', `${rows.length} cmdTypes` + (f ? ` matching “${filter}”` : ''));
    },
  };
}
