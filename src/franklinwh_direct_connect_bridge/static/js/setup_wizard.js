/* First-run setup modal. See templates/partials/setup_wizard.html.
 *
 * Opens ONCE, when the bridge has nothing configured, and only if setup has never been
 * completed or declined. Closing records `skipped` — that stops the prompt and disables
 * nothing; Settings → Setup is the same content and stays reachable.
 *
 * The flow is linear and short on purpose: intent, how much hardware, where the site is,
 * find it, confirm. Everything optional is deferred, and says so.
 *
 * Once that is done the wizard opens on the setup list (`hub`, owner 2026-11-11): every
 * other thing worth setting up, Done or To do. A few are answered here (cloud, publish,
 * default mode); the rest open the Settings card, tab or overlay that already does them.
 */
window.setupWizard = function setupWizard() {
  return {
    open: false,
    step: 'intent',
    busy: false,
    error: '',
    history: [],

    counts: { agates: 1, apowers: 1 },
    intent: 'hardware',        // which door was taken: hardware | demo
    // ONE timezone for the whole site. The browser's is only the default — the person
    // setting this up is not necessarily sitting at the site.
    tz: { name: '', zones: [], detected: '' },
    found: null,                       // null = not scanned yet; [] = scanned, nothing found
    // The subnet Discover will sweep, and WHERE it came from. A prefilled value with no
    // provenance cannot be told apart from a guess — and one of the sources IS a guess.
    scan_subnet: '',
    scan_source: '',
    scan_label: '',
    manual: { host: '' },
    // The four live Home Assistant checks, and whether to publish at all.
    ha: { checks: [], publishing: false, addon: false, busy: false, msg: '' },
    // Gateways added in THIS wizard run. "Publish this gateway to Home Assistant? Yes"
    // applies to them — and only them (#98: their publish flag is what the poller honours).
    createdIds: [],
    demo: { label: 'Mock aGate' },
    // FranklinWH app credentials. Optional, and only stored once a real sign-in proves
    // they work — storing an untested password is how someone finds out months later that
    // a reserve-SoC write has been failing silently.
    cloud: { email: '', password: '', state: '', detail: '' },   // state: '' | ok | failed

    // The setup list (from /api/setup) and where it was opened from.
    tasks: [],
    setupState: 'pending',
    fromHub: false,                    // an inline task was opened from the list
    mode: { value: '', options: [], msg: '', busy: false },
    // A FranklinWH Gateway Emulator, added as a gateway at its address and port.
    emu: { label: 'Gateway Emulator', host: '', port: window.FWH_BOOT.ports.dc, msg: '', ok: false, busy: false },
    // Where the Modbus client connects (the active gateway's, or an override).
    mb: { enabled: true, host: '', port: '', resolved: '', msg: '', ok: false, test: null, busy: false },

    // ONE profile per gateway. Solar, generator and backup wiring are per-gateway facts:
    // a site can have an aGate with 6.6 kW of PV and another with none, and showing a
    // single profile at the end of setup silently claims they are the same.

    async init() {
      // Anything in the app can ask for the wizard — the dashboard banner does. A plain
      // window event keeps the wizard self-contained instead of wiring a second owner for
      // its open/closed state.
      window.addEventListener('fwh:open-setup-wizard', () => this.reopen());

      // Ask the server, never guess from local state: a second browser must not re-prompt
      // for a bridge that is already set up.
      try {
        const r = await fetch('api/setup');
        if (!r.ok) return;
        const s = await r.json();
        this.tasks = s.tasks || [];
        this.setupState = s.state || 'pending';
        const step = (s.steps || []).find(x => x.id === 'expected');
        if (step && step.values) this.counts = { ...step.values };
        const tzStep = (s.steps || []).find(x => x.id === 'timezone');
        this.tz.detected = this._browserZone();
        this.tz.name = (tzStep && tzStep.values && tzStep.values.timezone) || this.tz.detected;
        this.tz.zones = this._zoneChoices(this.tz.detected);
        if (!s.should_prompt) return;

        // Queue behind the legal gate. Both are modals, and stacking setup on an
        // unaccepted disclaimer puts a dialog over the one thing the user has to read.
        const app = () => (window.Alpine && Alpine.store('app')) || null;
        const ready = () => { const a = app(); return a && !a.showDisclaimer; };
        if (ready()) { this.show(); return; }
        const timer = setInterval(() => {
          if (!ready()) return;
          clearInterval(timer);
          this.show();
        }, 300);
      } catch (e) { /* never block the app on the wizard */ }
    },

    // Reopening after it was finished or skipped is always allowed — the state only
    // governs whether it appears UNASKED.
    // A bridge that already has a gateway opens on the setup list; a new one starts at the
    // beginning (the list has "Start again" for re-running the first steps).
    async reopen() {
      this.history = [];
      this.error = '';
      await this.loadTasks();
      const a = (window.Alpine && Alpine.store('app')) || null;
      const hasGateway = !!(a && (a.gateways || []).length);
      if (hasGateway || this.setupState === 'done') {
        this.toHub();
      } else {
        this.step = 'intent';
        await this.loadScanDefault().catch(() => {});
      }
      this.show();
    },

    async loadTasks() {
      try {
        const r = await fetch('api/setup');
        if (!r.ok) return;
        const s = await r.json();
        this.tasks = s.tasks || [];
        this.setupState = s.state || this.setupState;
      } catch (e) { /* the list keeps what it had */ }
    },

    toHub() {
      this.history = [];
      this.fromHub = false;
      this.error = '';
      this.step = 'hub';
      this.loadTasks();
    },

    tasksIn(group) { return this.tasks.filter(t => t.group === group); },

    // Answer it here, or go to what already does it. Leaving the wizard closes it; the list
    // is one click away again from Settings → Setup.
    openTask(t) {
      if (t.inline) {
        this.fromHub = true;
        if (t.inline === 'mode') this.loadModes();
        if (t.inline === 'modbus') this.loadModbus();
        if (t.inline === 'emulator') this.emu.msg = '';
        this.go(t.inline);
        return;
      }
      const o = t.open || {};
      const a = (window.Alpine && Alpine.store('app')) || null;
      this.hide();
      if (o.overlay === 'systemview') { if (window.FWHSystemView) FWHSystemView.open(); return; }
      if (!a) return;
      if (o.tab) { a.setActiveTab(o.tab); return; }
      a.setActiveTab('settings');
      setTimeout(() => window.dispatchEvent(new CustomEvent('fwh-open-settings',
        { detail: { sub: o.sub, card: o.card } })), 50);
    },

    async loadModes() {
      this.mode.msg = '';
      const a = (window.Alpine && Alpine.store('app')) || null;
      try {
        const c = await (await fetch('api/constants')).json();
        this.mode.value = (c.values || {}).default_operating_mode || '';
        this.mode.options = ((c.spec || {}).default_operating_mode || {}).options || [];
        if (a && a.selectedGateway) {
          const m = await (await fetch('api/constants/modes' + a.gwQuery())).json();
          if ((m.options || []).length) this.mode.options = m.options;
        }
      } catch (e) { this.mode.msg = `Could not read the modes: ${e.message || e}`; }
    },

    // The address the emulator listens on and its Direct Connect port. A port other than
    // this bridge's Direct Connect port travels in the host (host:port), the form every
    // read uses.
    async addEmulator() {
      const e = this.emu;
      if (!e.host.trim()) return;
      e.busy = true; e.msg = ''; e.ok = false;
      const port = Number(e.port) || window.FWH_BOOT.ports.dc;
      const host = port === window.FWH_BOOT.ports.dc ? e.host.trim() : `${e.host.trim()}:${port}`;
      try {
        const r = await fetch('api/gateways', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label: e.label || 'Gateway Emulator', host, port, enabled: true }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { e.msg = `Not added: ${d.detail || r.status}`; return; }
        e.ok = true;
        e.msg = `Added as "${d.label || e.label}". Pick it in the gateway list at the top.`;
        const a = (window.Alpine && Alpine.store('app')) || null;
        if (a && typeof a.loadGateways === 'function') a.loadGateways();
      } catch (err) { e.msg = `Not added: ${err.message || err}`; }
      finally { e.busy = false; }
    },

    _gwq() {
      const a = (window.Alpine && Alpine.store('app')) || null;
      return a && a.selectedGateway ? a.gwQuery() : '';
    },

    async loadModbus() {
      const m = this.mb;
      m.msg = ''; m.test = null;
      try {
        const d = await (await fetch('api/modbus' + this._gwq())).json();
        m.enabled = !!d.enabled;
        m.host = d.host_override || '';
        m.port = d.port_override || '';
        m.resolved = d.resolved_host ? `${d.resolved_host}:${d.resolved_port}` : '';
      } catch (e) { m.msg = `Could not read it: ${e.message || e}`; }
    },

    async saveModbus(body) {
      const m = this.mb;
      m.busy = true; m.msg = ''; m.ok = false; m.test = null;
      try {
        const r = await fetch('api/modbus' + this._gwq(), {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || { host_override: m.host.trim(), port_override: Number(m.port) || 0 }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { m.msg = `Not saved: ${d.detail || r.status}`; return; }
        m.enabled = !!d.enabled;
        m.resolved = d.resolved_host ? `${d.resolved_host}:${d.resolved_port}` : '';
        m.ok = true;
        m.msg = body ? (d.enabled ? 'Modbus client on.' : 'Modbus client off.')
                     : (d.auto ? `Saved: the active gateway's address (${m.resolved}).` : `Saved: ${m.resolved}.`);
        const a = (window.Alpine && Alpine.store('app')) || null;
        if (a && typeof a.loadModbus === 'function') a.loadModbus();
      } catch (e) { m.msg = `Not saved: ${e.message || e}`; }
      finally { m.busy = false; }
    },

    async testModbus() {
      const m = this.mb;
      m.busy = true; m.test = null;
      try {
        m.test = await (await fetch('api/modbus/test' + this._gwq(), { method: 'POST' })).json();
      } catch (e) { m.test = { ok: false, reason: String(e) }; }
      finally { m.busy = false; }
    },

    async saveMode(v) {
      this.mode.busy = true; this.mode.msg = '';
      try {
        const r = await fetch('api/constants', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ default_operating_mode: v }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.mode.msg = `Not saved: ${d.detail || r.status}`; return; }
        this.mode.value = (d.values || {}).default_operating_mode || v;
        this.mode.msg = 'Saved.';
      } catch (e) { this.mode.msg = `Not saved: ${e.message || e}`; }
      finally { this.mode.busy = false; }
    },

    show() {
      this.open = true;
      const a = (window.Alpine && Alpine.store('app')) || null;
      if (a) a.setupModalOpen = true;
    },

    hide() {
      this.open = false;
      const a = (window.Alpine && Alpine.store('app')) || null;
      if (a) a.setupModalOpen = false;
    },

    get title() {
      return 'Set up the bridge';
    },

    get canBack() { return this.history.length > 0 && this.step !== 'hub'; },

    // What the browser believes, used as the default only. Returns '' when the browser
    // cannot say, in which case the user picks from the list rather than being given a
    // guess dressed as a detection.
    _browserZone() {
      try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; }
      catch (e) { return ''; }
    },

    // A short list that covers the installed base, with the detected zone first so the
    // common case is one click. Anything else can be typed — the server validates it
    // against the real IANA database and refuses what it does not know.
    _zoneChoices(detected) {
      const base = [
        'Australia/Sydney', 'Australia/Brisbane', 'Australia/Adelaide', 'Australia/Perth',
        'Pacific/Auckland', 'America/Los_Angeles', 'America/Denver', 'America/Chicago',
        'America/New_York', 'Europe/London', 'Europe/Berlin', 'UTC',
      ];
      return detected && !base.includes(detected) ? [detected, ...base] : base;
    },

    get nextLabel() {
      if (this.step === 'hub') return 'Close';
      if (this.fromHub) return 'Done';
      if (this.step === 'intent') return '';
      if (this.step === 'hardware') return 'Continue';
      if (this.step === 'timezone') return 'Continue';
      if (this.step === 'find') return 'Continue';
      if (this.step === 'cloud') return this.cloud.state === 'ok' ? 'Continue' : 'Skip for now';
      if (this.step === 'demo') return '';
      if (this.step === 'confirm') return 'Continue';
      if (this.step === 'publish') return 'Finish';
      return '';
    },

    go(step) {
      this.error = '';
      this.history.push(this.step);
      this.step = step;
      if (step === 'hardware') this.intent = this.intent || 'hardware';
      if (step === 'find') { this.loadScanDefault().then(() => this.scan()); }
      if (step === 'publish') this.loadHaChecks();
    },

    back() {
      this.error = '';
      const prev = this.history.pop() || 'intent';
      if (prev === 'hub') { this.toHub(); return; }
      this.step = prev;
    },

    async next() {
      if (this.step === 'hub') { this.hide(); return; }
      if (this.fromHub) { this.toHub(); return; }
      if (this.step === 'hardware') { await this.saveCounts(); return; }
      if (this.step === 'timezone') { await this.saveTimezone(); return; }
      if (this.step === 'find') { this.go('cloud'); return; }
      if (this.step === 'cloud') { this.go('confirm'); return; }
      if (this.step === 'confirm') { this.go('publish'); return; }
      if (this.step === 'publish') { await this.finish('done'); return; }
    },

    async saveCounts() {
      this.busy = true; this.error = '';
      try {
        const r = await fetch('api/setup/expected', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.counts),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.error = d.detail || `HTTP ${r.status}`; return; }
        this.go('timezone');
      } catch (e) { this.error = String(e); } finally { this.busy = false; }
    },

    // The site's timezone is stored BEFORE any gateway is created, so mock gateways are
    // born on the site's clock instead of being restarted onto it afterwards.
    async saveTimezone() {
      this.busy = true; this.error = '';
      try {
        const r = await fetch('api/setup/timezone', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ timezone: this.tz.name }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.error = d.detail || `HTTP ${r.status}`; return; }
        this.go(this.intent === 'demo' ? 'demo' : 'find');
      } catch (e) { this.error = String(e); } finally { this.busy = false; }
    },

    async loadScanDefault() {
      try {
        const r = await fetch('api/gateways/scan/default');
        if (!r.ok) return;
        const d = await r.json();
        if (!this.scan_subnet) this.scan_subnet = d.subnet || '';
        this.scan_source = d.source || '';
        this.scan_label = d.label || '';
      } catch (e) { /* the box simply starts empty */ }
    },

    async scan() {
      this.busy = true; this.error = ''; this.found = null;
      try {
        const r = await fetch('api/gateways/scan', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          // Several subnets, comma-separated: an aGate on a VPN or a second VLAN is not
          // on the network this container can see.
          body: JSON.stringify(this.scan_subnet ? { subnet: this.scan_subnet } : {}),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.error = d.detail || `Scan failed (HTTP ${r.status}).`; this.found = []; return; }
        // Only CONFIRMED aGates are offered. A host with 9000 open is not an aGate.
        this.found = (d.candidates || d.results || []).filter(c => c.confirmed || c.serial);
      } catch (e) { this.error = String(e); this.found = []; } finally { this.busy = false; }
    },

    async addFound(c) { await this._addGateway({ host: c.host, label: c.label || '' }); },

    async addManual() {
      if (!this.manual.host) return;
      await this._addGateway({
        label: 'aGate', host: this.manual.host.trim(), port: window.FWH_BOOT.ports.dc, enabled: true });
    },

    // NB the roster field is `is_mock`, not `mock`. Sending the wrong key creates a REAL
    // gateway with no host, which then sits Offline for ever and looks like a broken mock.
    async _addGateway(body) {
      this.busy = true; this.error = '';
      try {
        const r = await fetch('api/gateways', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.error = d.detail || `Could not add it (HTTP ${r.status}).`; return; }
        if (d.id) this.createdIds.push(d.id);
        this.go('cloud');
      } catch (e) { this.error = String(e); } finally { this.busy = false; }
    },

    // Build the site that was DESCRIBED: one mock per declared aGate, each with the
    // declared number of aPowers. Creating a single mock when three were asked for leaves
    // the wizard reporting "1 of 3 configured" on the step the user just completed.
    // Labels are numbered, because several gateways all called "Mock aGate" cannot be told
    // apart in the switcher.
    async createMock() {
      this.busy = true; this.error = '';
      const want = Math.max(1, Math.min(16, this.counts.agates || 1));
      const units = Math.max(1, Math.min(16, this.counts.apowers || 1));
      const base = this.demo.label || 'Mock aGate';
      try {
        for (let i = 1; i <= want; i++) {
          const r = await fetch('api/gateways', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              label: want === 1 ? base : `${base} ${i}`,
              is_mock: true, enabled: true, mock_units: units,
            }),
          });
          const d = await r.json().catch(() => ({}));
          if (!r.ok) {
            // Stop at the first failure and say which one: finishing silently with fewer
            // gateways than asked for is the defect this replaced.
            this.error = d.detail || `Could not create mock ${i} of ${want} (HTTP ${r.status}).`;
            return;
          }
          if (d.id) this.createdIds.push(d.id);
        }
        this.go('cloud');
      } catch (e) { this.error = String(e); } finally { this.busy = false; }
    },

    // Sign in for real. Nothing is stored unless it works, and the password never comes
    // back from the server.
    async testCloud() {
      if (!this.cloud.email || !this.cloud.password) return;
      this.busy = true; this.error = ''; this.cloud.state = ''; this.cloud.detail = '';
      try {
        const r = await fetch('api/setup/cloud', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: this.cloud.email, password: this.cloud.password }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.cloud.state = 'failed'; this.cloud.detail = d.detail || `HTTP ${r.status}`; return; }
        this.cloud.state = d.ok ? 'ok' : 'failed';
        this.cloud.detail = d.detail || '';
        if (d.ok) this.cloud.password = '';     // keep it out of the page once it is stored
      } catch (e) { this.cloud.state = 'failed'; this.cloud.detail = String(e); }
      finally { this.busy = false; }
    },

    // The four things that decide whether this bridge shows up in Home Assistant. Each
    // fails independently and each has its own remedy, so they are shown as four lines
    // rather than one verdict.
    async loadHaChecks() {
      this.ha.busy = true;
      try {
        const r = await fetch('api/setup/ha-checks');
        if (r.ok) {
          const d = await r.json();
          this.ha.checks = d.checks || [];
          this.ha.publishing = !!d.publishing;
          this.ha.addon = !!d.addon;
        }
      } catch (e) { /* the step explains an empty list itself */ }
      finally { this.ha.busy = false; }
    },

    // "Yes" is the only thing that turns publishing on. Entities appear in someone's Home
    // Assistant as a result, so it is asked rather than assumed.
    async publishYes() {
      this.ha.busy = true; this.ha.msg = '';
      try {
        // The broker may already be on (the add-on default, #264): then only the
        // per-gateway flags below are needed.
        const r = this.ha.publishing ? { ok: true, status: 200, json: async () => ({}) }
                                     : await fetch('api/mqtt/supervisor/enable', { method: 'POST' });
        const d = await r.json().catch(() => ({}));
        // Enabling the broker is not enough: each gateway publishes only when its own
        // flag says so. Set it for the gateways this wizard added (the user just said Yes).
        // From the setup list, Yes is for every real gateway: none was added in this run.
        const a = (window.Alpine && Alpine.store('app')) || null;
        const ids = this.fromHub
          ? ((a && a.gateways) || []).filter(g => g && g.id && !g.is_mock).map(g => g.id)
          : this.createdIds;
        if (r.ok) {
          for (const id of ids) {
            await fetch(`api/gateways/${encodeURIComponent(id)}`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ publish_ha: true }),
            }).catch(() => {});
          }
        }
        this.ha.msg = r.ok ? (d.note || 'Publishing enabled.')
                           : (d.detail || `Could not enable it (HTTP ${r.status}).`);
      } catch (e) { this.ha.msg = String(e); }
      finally { this.ha.busy = false; await this.loadHaChecks(); }
    },

    publishNo() {
      this.ha.msg = 'Left off. You can turn publishing on later from the MQTT tab.';
    },

    async finish(state) {
      this.busy = true;
      try {
        await fetch('api/setup/state', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ state }),
        });
        const a = (window.Alpine && Alpine.store('app')) || null;
        if (a) {
          a.loadSetup();
          await this._selectFirstGateway(a);
        }
      } catch (e) { /* closing must never fail */ } finally { this.busy = false; }
      this.setupState = state;
      this.toHub();      // finished: on to everything else worth setting up
    },

    // Land on a REAL gateway, not the "Site · All Gateways" roll-up. Site mode has no host
    // of its own, so the per-gateway views (Battery, Device, Grid & Inverter) report a
    // connection failure against an empty address — the first thing the user would see
    // after finishing setup.
    async _selectFirstGateway(a) {
      try {
        if (typeof a.loadGateways === 'function') await a.loadGateways();
        const gws = a.gateways || [];
        const first = gws.find(g => g && g.id);
        if (first && !a.selectedGateway) {
          a.selectGateway(first.id);
        }
      } catch (e) { /* a missed selection is cosmetic; never fail the finish */ }
    },

    async skip() { await this.finish('skipped'); this.hide(); },

    // Closing the list or a task opened from it is not declining setup.
    async close() {
      if (this.step === 'hub' || this.fromHub || this.setupState === 'done') { this.hide(); return; }
      await this.skip();
    },
  };
};
