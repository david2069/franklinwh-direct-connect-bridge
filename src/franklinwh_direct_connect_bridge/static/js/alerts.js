/**
 * Alerts (#271) — the shared alert spec v1 (franklinwh-modbus-bridge#324 §5).
 *
 * The bridge stores every alert; this only shows them. On every page load it fetches the
 * open set, so a fault raised while no browser was open is shown on the next visit. After
 * that it polls the small /api/status summary on the dashboard's 10 s cycle and refetches
 * the list only when `open`, `latest_id` or `changed_ts` changes. No SSE or WebSocket.
 *
 *  - critical + unacknowledged  → the modal, which stays until acknowledged;
 *  - an active condition that has been acknowledged → the red bar under the top bar;
 *  - the summary → the top-bar badge, which opens the list (time first, then what
 *    happened, then where it was delivered).
 * Routine results stay as toasts.
 */
document.addEventListener('alpine:init', () => {
  Alpine.store('alerts', {
    summary: { level: 'ok', open: 0, latest_id: null, changed_ts: null },
    list: [],            // GET /api/alerts?open=1, newest first
    understood: {},      // alert id -> "I understand" ticked (per alert)
    listOpen: false,     // the badge's panel
    busy: false,
    _sig: '',
    _timer: null,

    init() {
      this.poll();                 // every page load fetches the open set (spec §5)
      this._timer = setInterval(() => {
        const app = Alpine.store('app');
        if (!(app && app._hidden)) this.poll();
      }, 10000);
    },

    async poll(force = false) {
      try {
        const r = await fetch('api/status', { cache: 'no-store' });
        if (!r.ok) return;
        const s = (await r.json()).alerts || {};
        this.summary = s;
        const sig = `${s.open}|${s.latest_id}|${s.changed_ts}`;
        if ((force || sig !== this._sig) && await this.load()) this._sig = sig;
      } catch (e) { /* bridge restarting — the connection banner covers it */ }
    },

    /** The open set. True when it was read, so a failed read is retried next poll. */
    async load() {
      try {
        const r = await fetch('api/alerts?open=1', { cache: 'no-store' });
        if (!r.ok) return false;
        this.list = (await r.json()).alerts || [];
        return true;
      } catch (e) { return false; }
    },

    // ── what each part of the UI shows ──────────────────────────────────────
    /** The modal's queue: critical, not yet acknowledged, newest first. */
    get pending() {
      return this.list.filter(a => a.severity === 'critical' && !a.acked_ts);
    },
    /** The red bar: conditions still active that someone has already acknowledged. */
    get activeAcked() {
      return this.list.filter(a => a.kind === 'condition' && !a.resolved_ts && a.acked_ts);
    },
    get allUnderstood() {
      return this.pending.length > 0 && this.pending.every(a => this.understood[a.id]);
    },

    async ackPending() {
      if (!this.allUnderstood || this.busy) return;
      await this._ack(this.pending.map(a => a.id));
    },
    async ackOne(id) { await this._ack([id]); },

    async _ack(ids) {
      this.busy = true;
      try {
        for (const id of ids) {
          const r = await fetch(`api/alerts/${id}/ack`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: 'ui' }),
          });
          if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            Alpine.store('app').toast(`Could not acknowledge alert ${id}: ${d.detail || r.statusText}`, 'error');
          }
          delete this.understood[id];
        }
      } finally {
        this.busy = false;
        // Re-read now rather than on the next 10 s poll.
        await this.poll(true);
      }
    },

    // ── formatting (SITE time, spec §5/§8) ──────────────────────────────────
    _opts: { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true },
    at(ts) { return ts ? Alpine.store('app')._fmtSiteTime(ts, this._opts) : ''; },
    hm(ts) {
      return ts ? Alpine.store('app')._fmtSiteTime(ts, { hour: 'numeric', minute: '2-digit', hour12: true }) : '';
    },
    /** "since 09:54", or "09:54–13:27, resolved" for a condition that came and went. */
    when(a) {
      if (a.kind === 'condition') {
        return a.resolved_ts ? `${this.at(a.opened_ts)}–${this.hm(a.resolved_ts)}, resolved`
                             : `since ${this.at(a.opened_ts)}`;
      }
      return this.at(a.opened_ts) + (a.count > 1 ? ` · ${a.count}×, last ${this.hm(a.last_ts)}` : '');
    },
    /** Where it went. Every alert is in the bridge's log; critical ones also go to HA. */
    delivery(a) {
      const d = (a.deliveries || []).find(x => x.channel === 'ha_persistent');
      if (!d) return 'Bridge log';
      if (d.delivered_ts) return 'Bridge log · HA notification';
      if ((d.last_error || '').startsWith('skipped:')) return 'Bridge log · HA ' + d.last_error;
      if (d.attempts) return `Bridge log · HA not reached (${d.attempts} tries)`;
      return 'Bridge log · HA pending';
    },
    barText(a) {
      return `${a.title} since ${this.hm(a.opened_ts)}` + (a.gateway_id ? ` (${a.gateway_id})` : '');
    },

    // ── what it means and what to do, per code ──────────────────────────────
    HELP: {
      GATEWAY_UNREACHABLE: {
        means: 'The bridge cannot reach the aGate on your network. Live readings, schedules and controls sent through the bridge cannot run until it is back.',
        todo: 'Check the aGate has power and its network connection. The Logs show each failed connection.',
        tab: 'logs', link: 'Open Logs' },
      LIVE_DATA_MISSING: {
        means: 'No live readings have arrived from the aGate. Values on the Dashboard and in Home Assistant are stale.',
        todo: 'The Logs show why each read failed. The bridge keeps retrying.',
        tab: 'logs', link: 'Open Logs' },
      DATA_MISSING_PARTIAL: {
        means: 'Some live readings are missing; the rest are arriving.',
        todo: 'The Logs show which read failed.', tab: 'logs', link: 'Open Logs' },
      MQTT_DOWN: {
        means: 'The bridge is not connected to the MQTT broker, so Home Assistant entities are not updating.',
        todo: 'Check the broker is running, and the MQTT settings.', tab: 'mqtt', link: 'Open MQTT' },
      HA_UNREACHABLE: {
        means: 'Home Assistant did not answer, so its notifications are waiting. They are retried.',
        todo: 'Check Home Assistant is running and reachable from the bridge.',
        tab: 'settings', link: 'Open Settings' },
      WORKER_STALLED: {
        means: 'A background part of the bridge stopped responding or crashed. Whatever it does (polling, scheduling, publishing) may have stopped.',
        todo: 'Health lists each worker and whether it can be restarted; otherwise restart the bridge.',
        tab: 'health', link: 'Open Health' },
      COMMAND_REFUSED: {
        means: 'The bridge recorded this command as refused or failed. Check the current state before trying again.',
        todo: 'The Audit Trail on the Control tab has the detail.', tab: 'control', link: 'Open Control' },
      COMMAND_UNCONFIRMED: {
        means: 'The command was sent but its result could not be confirmed.',
        todo: 'Check the current state before trying again.', tab: 'control', link: 'Open Control' },
      WRITE_IGNORED: {
        means: 'The aGate accepted the write but the value did not change.',
        todo: 'Check the current state before trying again.', tab: 'control', link: 'Open Control' },
      SCHEDULE_FAILED: {
        means: 'A scheduled action did not complete. A failure is retried while its window is open; a missed window is not.',
        todo: 'The schedule\'s activity shows each attempt.', tab: 'scheduler', link: 'Open Scheduler' },
      RESTART_DURING_COMMAND: {
        means: 'The bridge restarted while a command was in progress.',
        todo: 'Check the current state.', tab: 'control', link: 'Open Control' },
      EXTERNAL_SETPOINT: {
        means: 'A setting was changed outside this bridge (the app, the cloud or another tool).',
        todo: 'Check the current state.', tab: 'control', link: 'Open Control' },
      INTERNAL_ERROR: {
        means: 'The bridge hit an unexpected error.', todo: 'The Logs have the detail.',
        tab: 'logs', link: 'Open Logs' },
    },
    help(a) { return this.HELP[a.code] || { means: '', todo: '', tab: 'logs', link: 'Open Logs' }; },
    go(a) {
      this.listOpen = false;
      Alpine.store('app').setActiveTab(this.help(a).tab);
    },
  });
});
