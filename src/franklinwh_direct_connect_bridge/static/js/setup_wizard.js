/* First-run setup modal. See templates/partials/setup_wizard.html.
 *
 * Opens ONCE, when the bridge has nothing configured, and only if setup has never been
 * completed or declined. Closing records `skipped` — that stops the prompt and disables
 * nothing; Settings → Setup is the same content and stays reachable.
 *
 * The flow is linear and short on purpose: intent, how much hardware, find it, confirm.
 * Everything optional is deferred, and says so.
 */
window.setupWizard = function setupWizard() {
  return {
    open: false,
    step: 'intent',
    busy: false,
    error: '',
    history: [],

    counts: { agates: 1, apowers: 1 },
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

    get nextLabel() {
      if (this.step === 'intent') return '';
      if (this.step === 'hardware') return 'Continue';
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
      if (step === 'find') this.scan();
      if (step === 'confirm') this.loadProfile();
    },

    back() {
      this.error = '';
      this.step = this.history.pop() || 'intent';
    },

    async next() {
      if (this.step === 'hardware') { await this.saveCounts(); return; }
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
        this.go('find');
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
      await this._addGateway({ host: this.manual.host.trim(), label: '' });
    },

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

    async createMock() {
      this.busy = true; this.error = '';
      try {
        const r = await fetch('api/gateways', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mock: true, label: this.demo.label || 'Mock aGate' }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.error = d.detail || `Could not create it (HTTP ${r.status}).`; return; }
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
        if (window.Alpine && Alpine.store('app')) Alpine.store('app').loadSetup();
      } catch (e) { /* closing must never fail */ } finally { this.busy = false; }
      this.step = 'done';
    },

    async skip() { await this.finish('skipped'); this.hide(); },

    async close() { await this.skip(); },
  };
};
