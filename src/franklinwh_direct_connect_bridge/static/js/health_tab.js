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
    },

    async load() {
      this.loading = true; this.error = '';
      try {
        const r = await fetch('api/firmware/all' + this.$store.app.gwQuery());
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.fw = await r.json();
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
});
