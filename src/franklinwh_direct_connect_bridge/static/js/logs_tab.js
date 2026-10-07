/**
 * FranklinWH Local Bridge — Logs tab (P6).
 * Fetches the bridge's ring buffer from GET /api/logs (newest-first) on view + a 10s
 * auto-refresh. All filtering (level bucket / source / text) is client-side over the
 * fetched entries, to match the FranklinWH Modbus Bridge Logs page: level-count tiles,
 * a Source filter, and a TIME/LEVEL/SOURCE/MESSAGE table.
 */
function logsTab() {
  return {
    ...window.liveCapMixin('logs'),
    entries: [],
    total: null,           // server-reported total rows matching the range (for the footer)
    levelFilter: '',           // '' = all; else one of the 5 buckets (DEBUG..CRITICAL)
    source: '',                // '' = all sources; else exact logger name
    query: '',                 // free-text filter (message / logger / level)
    loading: false,
    paused: false,             // pause the 10s auto-refresh (freeze the view)
    _interval: null,

    // Time range over the persisted history (the server keeps up to 5000 lines). A
    // longer range loads more; because this bridge logs sparsely (startup / state /
    // errors, never routine polls) even "All" is cheap here.
    range: '24h',
    ranges: [
      { v: '1h',  label: 'Last 1h',  secs: 3600 },
      { v: '6h',  label: 'Last 6h',  secs: 21600 },
      { v: '24h', label: 'Last 24h', secs: 86400 },
      { v: '7d',  label: 'Last 7 days', secs: 604800 },
      { v: 'all', label: 'All time', secs: null },
    ],

    // The 5 display buckets (matches the Modbus Bridge tiles), each mapping from the
    // python/HA level names our buffer emits.
    buckets: ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],

    init() {
      this.load();
      this._capMark();
      this._interval = setInterval(() => this._tick(), 10000);
    },
    // Auto-pause the live tail once it runs past the user's cap (Settings → Real-time limits).
    _tick() {
      if (this.paused) return;
      if (this._capExpired()) { this._capTrip(); clearInterval(this._interval); this._interval = null; return; }
      this.load();
    },
    _capRestart() { this._interval = setInterval(() => this._tick(), 10000); this.load(); },

    async load() {
      this.loading = true;
      try {
        // Server-side time-range over the persisted history, then filter the rest
        // (level / source / text) client-side.
        const params = new URLSearchParams({ limit: '5000' });
        const rr = this.ranges.find((x) => x.v === this.range);
        if (rr && rr.secs) params.set('since', String(Math.floor(Date.now() / 1000) - rr.secs));
        const r = await fetch('api/logs?' + params.toString());
        if (r.ok) {
          const d = await r.json();
          this.entries = (d && Array.isArray(d.entries)) ? d.entries : [];
          this.total = (d && typeof d.total === 'number') ? d.total : null;
        }
      } catch (e) {
        console.warn('[Bridge] logs load failed:', e.message);
      } finally {
        this.loading = false;
      }
    },

    // Map a raw level name to one of the 5 display buckets.
    bucketOf(lvl) {
      const l = String(lvl || '').toLowerCase();
      if (l === 'trace' || l === 'debug') return 'DEBUG';
      if (l === 'info' || l === 'notice') return 'INFO';
      if (l === 'warning' || l === 'warn') return 'WARNING';
      if (l === 'error') return 'ERROR';
      if (l === 'fatal' || l === 'critical') return 'CRITICAL';
      return 'INFO';
    },

    // Total count per bucket over ALL entries (the tiles show totals, not the filtered view).
    levelCounts() {
      const c = { DEBUG: 0, INFO: 0, WARNING: 0, ERROR: 0, CRITICAL: 0 };
      for (const e of this.entries) c[this.bucketOf(e.level)]++;
      return c;
    },

    // Unique logger names present, sorted — for the Source dropdown.
    sources() {
      return [...new Set(this.entries.map((e) => e.name))].sort();
    },

    // Click a level tile: filter to that bucket, or clear if it's already active.
    setLevel(bucket) { this.levelFilter = (this.levelFilter === bucket) ? '' : bucket; },

    // The visible rows after level + source + text filters.
    filtered() {
      const q = this.query.trim().toLowerCase();
      return this.entries.filter((e) => {
        if (this.levelFilter && this.bucketOf(e.level) !== this.levelFilter) return false;
        if (this.source && e.name !== this.source) return false;
        if (q && !`${e.message} ${e.name} ${e.level}`.toLowerCase().includes(q)) return false;
        return true;
      });
    },

    // Download the currently-shown lines as a plain .log (respects all filters).
    exportLogs() {
      const lines = this.filtered().slice().reverse().map((e) => {  // oldest-first in the file
        const t = e.ts != null ? new Date(e.ts * 1000).toISOString() : '';
        return `${t} ${String(e.level).padEnd(7)} ${e.name}  ${e.message}`;
      });
      const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `fwh-bridge-${Date.now()}.log`;
      a.click();
      URL.revokeObjectURL(url);
    },

    // Level → chip colour class (matches the design-system chip palette).
    levelClass(lvl) {
      const b = this.bucketOf(lvl);
      if (b === 'ERROR' || b === 'CRITICAL') return 'error';
      if (b === 'WARNING') return 'warn';
      if (b === 'INFO') return 'ok';
      return 'muted';
    },

    fmtTime(ts) {                                   // app logs — HOST zone (system of record)
      if (ts == null) return '--';
      try { return this.$store.app._fmtHostTime(ts, { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true }); }
      catch (e) { return String(ts); }
    },
  };
}
