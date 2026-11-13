/**
 * Troubleshoot (#614) — opened from the red bar and from an aGate-unreachable or on-4G
 * alert. It shows the verdict (the bridge's LAN link plus what the FranklinWH cloud says the
 * aGate is connected through), a Health check (LAN, :9000, the aGate's cloud link, the last
 * good poll — never the Modbus TCP Server (aGate :502)), a link to Network, the steps, and,
 * when the cloud says 4G, Reconnect to Wi-Fi (admin, typed confirmation). Every result stays
 * inside the panel. The bridge never sends, holds or shows a Wi-Fi password; the library
 * reuses the one the aGate stores.
 */
document.addEventListener('alpine:init', () => {
  Alpine.store('troubleshoot', {
    isOpen: false,
    gw: '',
    data: null,          // GET /api/troubleshoot/connectivity
    loading: false,
    msg: null,           // the verdict read failed: {kind, text}
    health: null,        // GET /api/troubleshoot/health → checks
    healthBusy: false,
    healthMsg: null,
    job: { state: 'idle', result: null },
    reconnectMsg: null,
    platform: 'ios',     // the app steps, one platform at a time
    _timer: null,

    open(gatewayId) {
      this.gw = gatewayId || Alpine.store('app').selectedGateway || '';
      this.isOpen = true;
      this.data = null; this.msg = null; this.health = null; this.healthMsg = null;
      this.reconnectMsg = null;
      this.refresh();
      this._job();          // a reconnect still running from earlier shows here
    },
    close() {
      this.isOpen = false;
      if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    },
    _q() { return this.gw ? `?gateway=${encodeURIComponent(this.gw)}` : ''; },

    async refresh() {
      this.loading = true; this.msg = null;
      try {
        const r = await fetch('api/troubleshoot/connectivity' + this._q(), { cache: 'no-store' });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.msg = { kind: 'danger', text: d.detail || r.statusText }; return; }
        this.data = d;
      } catch (e) {
        this.msg = { kind: 'danger', text: 'The bridge did not answer: ' + e.message };
      } finally { this.loading = false; }
    },

    async runHealth() {
      this.healthBusy = true; this.healthMsg = null;
      try {
        const r = await fetch('api/troubleshoot/health' + this._q(), { cache: 'no-store' });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { this.healthMsg = { kind: 'danger', text: d.detail || r.statusText }; return; }
        this.health = d;
      } catch (e) {
        this.healthMsg = { kind: 'danger', text: 'The bridge did not answer: ' + e.message };
      } finally { this.healthBusy = false; }
    },

    // ── Reconnect to Wi-Fi ──────────────────────────────────────────────────
    async reconnect() {
      const d = this.data || {};
      if (!d.can_reconnect || !d.admin || this.job.state === 'running') return;
      const ok = await Alpine.store('app').confirmTyped(
        `The FranklinWH cloud puts the aGate back on its stored Wi-Fi network "${d.stored_ssid}", `
        + 'with the credentials the aGate already holds. It first checks that 4G stays as a '
        + 'fallback, then waits up to 3 minutes for the Wi-Fi link to come up. It is not retried.'
        + '\n\nType RECONNECT to go ahead.',
        'RECONNECT', { title: 'Reconnect to Wi-Fi', danger: true });
      if (!ok) return;
      this.reconnectMsg = null;
      try {
        const r = await fetch('api/troubleshoot/reconnect-wifi' + this._q(), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ssid: d.stored_ssid, confirm: true }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
          this.reconnectMsg = { kind: 'danger', text: j.detail || r.statusText };
          this.job = { state: 'done', result: { ok: false, use_app: true } };
          return;
        }
        this.job = j;
        this._job();
      } catch (e) {
        this.reconnectMsg = { kind: 'danger', text: 'The bridge did not answer: ' + e.message };
      }
    },
    /** Follow a running reconnect until it is done; its result stays in the panel. */
    async _job() {
      if (this._timer) { clearTimeout(this._timer); this._timer = null; }
      try {
        const r = await fetch('api/troubleshoot/reconnect-wifi' + this._q(), { cache: 'no-store' });
        if (r.ok) this.job = await r.json();
      } catch (e) { /* retried below while running */ }
      if (this.job.state === 'running') {
        if (this.isOpen) this._timer = setTimeout(() => this._job(), 3000);
        return;
      }
      const res = this.job.result;
      if (res && !this.reconnectMsg) {
        this.reconnectMsg = { kind: res.ok ? 'ok' : 'danger',
          text: res.message + ((res.reasons || []).length ? ' ' + res.reasons.join('; ') : '') };
        if (res.ok) this.refresh();
      }
    },
    get running() { return this.job.state === 'running'; },

    // ── what the panel shows ────────────────────────────────────────────────
    get verdictColor() {
      const s = this.data && this.data.verdict && this.data.verdict.severity;
      return s === 'critical' ? 'var(--danger, #dc2626)' : s === 'warning' ? 'var(--warn, #f59e0b)'
        : 'var(--ok, #10b981)';
    },
    get cloudLine() {
      const c = this.data && this.data.cloud;
      if (!c) return '';
      if (!c.available) return 'FranklinWH cloud: not asked — ' + (c.reason || 'not available');
      if (c.reachable === false) return 'FranklinWH cloud: the aGate is offline to the cloud';
      return 'FranklinWH cloud: online via ' + (c.label || 'an unknown link')
        + (c.fallbacks && c.fallbacks.length ? ' · fallback ' + c.fallbacks.join(', ') : '');
    },
    get lanLine() {
      const l = this.data && this.data.lan;
      if (!l) return '';
      const at = ts => Alpine.store('alerts').at(ts);
      if (l.up) return 'LAN: answering on :' + window.FWH_BOOT.ports.dc + (l.last_ok_ts ? ' · last good ' + at(l.last_ok_ts) : '');
      if (l.state === 'down') return 'LAN: not answering since ' + at(l.down_since_ts);
      return 'LAN: not known yet' + (l.last_ok_ts ? ' · last good ' + at(l.last_ok_ts) : '');
    },
    /** "Use the FranklinWH app": without the cloud, or when a reconnect did not work. */
    get showApp() {
      const d = this.data;
      if (!d) return false;
      if (!d.cloud.available) return true;
      const res = this.job.result;
      if (this.job.state === 'done' && res && res.use_app) return true;
      return ['on_4g', 'left_wifi'].includes(d.verdict.code) && !d.can_reconnect;
    },
    appSteps(platform) {
      const device = platform === 'android' ? 'Android phone' : 'iPhone';
      return [
        `Open the FranklinWH app on your ${device}.`,
        'Go to Settings → Network → Wifi and tap Configure.',
        'With your router on, choose your network and enter the password.',
        'Wait up to 5 minutes for the aGate to join. The app then shows Wi-Fi → Internet, Connected.',
      ];
    },
    steps: [
      'Power: check the aGate is powered and its light is on.',
      'Router: if other devices have lost internet too, restart the router. The aGate joins 2.4 GHz Wi-Fi only.',
      'Wi-Fi: if the aGate is on 4G, put it back on Wi-Fi — below, or with the FranklinWH app.',
    ],
    checkColor(ok) {
      return ok === true ? 'var(--ok, #10b981)' : ok === false ? 'var(--danger, #dc2626)'
        : 'var(--text-muted, #64748b)';
    },
    checkText(ok) { return ok === true ? 'pass' : ok === false ? 'fail' : 'unknown'; },
    openNetwork() {
      const app = Alpine.store('app');
      if (this.gw && app.selectedGateway !== this.gw) app.selectGateway(this.gw);
      this.close();
      Alpine.store('alerts').listOpen = false;
      app.setActiveTab('network');
    },
  });
});
