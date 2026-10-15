/* First-run setup modal. See templates/partials/setup_wizard.html.
 *
 * Opens ONCE, when the bridge has nothing configured, and only if setup has never been
 * completed or declined. Closing records `skipped` — that stops the prompt and disables
 * nothing; Settings → Setup is the same content and stays reachable.
 *
 * The flow is linear and short on purpose: intent, how much hardware, where the site is,
 * find it, confirm. Everything optional is deferred, and says so.
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
    manual: { host: '' },
    demo: { label: 'Mock aGate' },
    profile: null,

    async init() {
      // Ask the server, never guess from local state: a second browser must not re-prompt
      // for a bridge that is already set up.
      try {
        const r = await fetch('api/setup');
        if (!r.ok) return;
        const s = await r.json();
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
      return this.step === 'done' ? 'Ready' : 'Set up the bridge';
    },

    get canBack() { return this.history.length > 0 && this.step !== 'done'; },

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
      if (this.step === 'intent') return '';
      if (this.step === 'hardware') return 'Continue';
      if (this.step === 'timezone') return 'Continue';
      if (this.step === 'find') return 'Continue';
      if (this.step === 'demo') return '';
      if (this.step === 'confirm') return 'Finish';
      if (this.step === 'done') return 'Close';
      return '';
    },

    go(step) {
      this.error = '';
      this.history.push(this.step);
      this.step = step;
      if (step === 'hardware') this.intent = this.intent || 'hardware';
      if (step === 'find') this.scan();
      if (step === 'confirm') this.loadProfile();
    },

    back() {
      this.error = '';
      this.step = this.history.pop() || 'intent';
    },

    async next() {
      if (this.step === 'hardware') { await this.saveCounts(); return; }
      if (this.step === 'timezone') { await this.saveTimezone(); return; }
      if (this.step === 'find') { this.go('confirm'); return; }
      if (this.step === 'confirm') { await this.finish('done'); return; }
      if (this.step === 'done') { this.hide(); return; }
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

    async scan() {
      this.busy = true; this.error = ''; this.found = null;
      try {
        const r = await fetch('api/gateways/scan', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
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
        label: 'aGate', host: this.manual.host.trim(), port: 9000, enabled: true });
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
        this.go('confirm');
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
        }
        this.go('confirm');
      } catch (e) { this.error = String(e); } finally { this.busy = false; }
    },

    async loadProfile() {
      try {
        const r = await fetch('api/setup');
        if (!r.ok) return;
        const s = await r.json();
        const step = (s.steps || []).find(x => x.id === 'profile');
        this.profile = (step && step.values) || {};
      } catch (e) { /* the step explains an empty profile itself */ }
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
      this.step = 'done';
    },

    // Land on a REAL gateway, not the "Site · All Gateways" roll-up. Site mode has no host
    // of its own, so the per-gateway views (Battery, Device, Grid & Inverter) report a
    // connection failure against an empty address — the first thing the user would see
    // after finishing setup.
    async _selectFirstGateway(a) {
      try {
        if (typeof a.loadGateways === 'function') await a.loadGateways();
        const gws = a.gateways || [];
        const first = gws.find(g => g && g.id && g.id !== '__site__');
        if (first && (!a.selectedGateway || a.selectedGateway === '__site__')) {
          a.selectGateway(first.id);
        }
      } catch (e) { /* a missed selection is cosmetic; never fail the finish */ }
    },

    async skip() { await this.finish('skipped'); this.hide(); },

    async close() { await this.skip(); },
  };
};
