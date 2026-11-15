/**
 * Health tab — firmware detail.
 *
 * Health is the firmware DETAIL page: it already spelled the tags out in plain
 * words while the Device tab showed raw four-letter codes, so the full data was
 * moved here rather than the reader being sent to the worse of the two.
 *
 * Loaded on demand: /api/firmware/all opens an aGate session and reads 1833 per
 * battery, so it is not something to poll.
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('healthTab', () => ({
    fw: null,
    loading: false,
    error: '',

    init() {
      this.$watch('$store.app.activeTab', (t) => { if (t === 'health' && !this.fw) this.load(); });
      if (this.$store.app.activeTab === 'health') this.load();
      clearOnGatewaySwitch(this, 'health', () => { this.fw = null; });
    },

    async load() {
      this.loading = true; this.error = '';
      const gwq = this.$store.app.gwQuery();
      try {
        const r = await fetch('api/firmware/all' + gwq);
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        const d = await r.json();
        if (gwq === this.$store.app.gwQuery()) this.fw = d;
      } catch (e) { this.error = e.message; }
      finally { this.loading = false; }
    },

    /** Plain-word labels. Raw tags stay visible so a value can still be matched
     *  back to the protocol field it came from. */
    LABELS: {
      protocolVer: 'Protocol version', IBG_VER: 'Gateway firmware',
      APP_VER: 'Local service', AWS_VER: 'Cloud (IoT) service',
      SL_VER: 'SL_VER (undecoded)', METER_VER: 'Meter firmware',
      FPGA_VER: 'FPGA', DCDC_VER: 'DC-DC converter', INV_VER: 'Inverter',
      BMS_VER: 'BMS', BL_VER: 'Bootloader', TH_VER: 'Thermal board',
      SyHdVersion: 'Hardware model id', IBG_SN: 'Gateway serial',
      FHP_SN: 'aPower serial', BMS_SN: 'BMS serial', PE_SN: 'Power-electronics serial',
      fhp_sn: 'aPower serial', ibg_sn: 'Gateway serial', bms_sn: 'BMS serial',
      pe_sn: 'Power-electronics serial', ibg_ver: 'Gateway firmware',
      ibg_iot: 'Cloud (IoT) service', ibg_local: 'Local service',
      bms_ver: 'BMS', pe_ver: 'Power electronics',
    },

    label(key) { return this.LABELS[key] || key; },

    /** An array field carries one entry per aPower; show it as such. */
    value(v) { return Array.isArray(v) ? v.join(', ') : (v ?? '—'); },

    get gatewayRows() {
      const g = (this.fw && this.fw.gateway) || {};
      return Object.keys(g).filter(k => !k.endsWith('_SN')).map(k => [k, g[k]]);
    },
    get serialRows() {
      const g = (this.fw && this.fw.gateway) || {};
      return Object.keys(g).filter(k => k.endsWith('_SN')).map(k => [k, g[k]]);
    },
    get batteries() { return (this.fw && this.fw.devices) || []; },

    deviceRows(dev) {
      return Object.keys(dev)
        .filter(k => !['id', 'opt', 'result', 'reason', 'error'].includes(k))
        .map(k => [k, dev[k]]);
    },
  }));

  // The daily bridge-health report and the weekly battery report (owner 2026-11-15).
  // Bridge-wide: no gateway. ``kind`` is 'daily' or 'weekly'.
  Alpine.data('healthReport', (kind = 'daily') => ({
    kind, cur: null, past: [], on: true, busy: false, err: '',

    init() {
      this.$watch('$store.app.activeTab', (t) => { if (t === 'health') this.load(); });
      if (this.$store.app.activeTab === 'health') this.load();
    },

    get r() { return (this.cur && this.cur.report) || {}; },

    async load(id) {
      this.err = '';
      try {
        const q = id ? `?id=${encodeURIComponent(id)}` : `?kind=${this.kind}`;
        const d = await (await fetch('api/health/report' + q)).json();
        this.cur = d.report; this.on = d[this.kind];
        this.past = (await (await fetch(`api/health/reports?kind=${this.kind}`)).json()).reports || [];
      } catch (e) { this.err = String(e); }
    },

    open(id) { this.load(id); },

    async runNow() {
      this.busy = true; this.err = '';
      try {
        const r = await fetch(`api/health/report/run?kind=${this.kind}`, { method: 'POST' });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        await this.load((await r.json()).id);
      } catch (e) { this.err = e.message; }
      finally { this.busy = false; }
    },

    async setOn(on) {
      this.err = '';
      try {
        const r = await fetch('api/health/report/settings', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [this.kind]: on }) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.on = (await r.json())[this.kind];
      } catch (e) { this.err = e.message; }
    },

    num(v, unit = '') { return v == null ? '–' : `${Math.round(v * 100) / 100}${unit}`; },
    chipClass(level) { return level === 'red' ? 'error' : level === 'amber' ? 'warn' : 'ok'; },
    when(ts) { return ts ? new Date(ts * 1000).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''; },
    size(b) { return b == null ? '–' : b < 1048576 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1048576).toFixed(1)} MB`; },
  }));
});
