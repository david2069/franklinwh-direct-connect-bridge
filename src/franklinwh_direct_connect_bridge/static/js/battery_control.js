/**
 * Battery Control widget — cloned from the Modbus bridge's Controls tab.
 *
 * Force Charge / Discharge / Standby via the aGate's WSet setpoint. The local
 * bridge drives this by speaking Modbus DIRECTLY to the aGate (the proven
 * franklinwh-modbus library), independent of the modbus-bridge service. Each
 * control POSTs a {slug, value} to /api/battery/command, mirroring the Modbus
 * bridge's per-slug command model.
 *
 * SAFETY: force writes actually move the battery. The endpoint refuses unless
 * the Modbus path is configured + reachable AND writes are enabled, and reports
 * that plainly rather than pretending — never a fake button.
 */
function batteryControl() {
  return {
    command: 'Not Active',
    powerW: 0,
    powerPct: 100,
    duration: 0,
    targetSoc: 0,
    powerMode: 'pct',       // 'w' or 'pct' — which power control the backend will use
    maxChargeW: 5000,
    maxDischargeW: 5000,
    available: false,       // is the Modbus force path usable?
    reason: '',             // why not, if unavailable
    active: 'Not Active',   // the currently-running dispatch, from the backend
    sending: false,
    commandLog: [],

    async init() {
      await this.refresh();
    },

    async refresh() {
      try {
        const r = await fetch('api/battery/command');
        const d = await r.json();
        this.available = !!d.available;
        this.reason = d.reason || '';
        this.active = d.active || 'Not Active';
        if (d.power_mode) this.powerMode = d.power_mode;
        if (d.max_charge_w) this.maxChargeW = d.max_charge_w;
        if (d.max_discharge_w) this.maxDischargeW = d.max_discharge_w;
      } catch (e) { this.available = false; this.reason = e.message; }
    },

    get canWrite() { return !!this.$store.app.summary.writes_enabled; },

    // ── Duration as hh:mm:ss (two-way with the raw `duration` seconds) ──
    get durH() { return Math.floor(this.duration / 3600); },
    get durM() { return Math.floor((this.duration % 3600) / 60); },
    get durS() { return this.duration % 60; },
    setDurPart(part, v) {
      v = Math.max(0, parseInt(v) || 0);
      let h = this.durH, m = this.durM, s = this.durS;
      if (part === 'h') h = v;
      else if (part === 'm') { m = Math.min(59, v); }
      else { s = Math.min(59, v); }
      this.duration = h * 3600 + m * 60 + s;
      this.sendCommand('battery_command_duration', this.duration);
    },
    fmtHMS(sec) {
      sec = Math.max(0, parseInt(sec) || 0);
      const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
      const pad = (n) => String(n).padStart(2, '0');
      return `${pad(h)}:${pad(m)}:${pad(s)}`;
    },

    // ── Tick presets — tap/click a tick to set a slider value directly ──
    get powerWTicks() {
      const mx = Math.max(this.maxChargeW, this.maxDischargeW) || 5000;
      const q = (f) => Math.round(mx * f / 100) * 100;
      return [{ label: '0', v: 0 }, { label: '25%', v: q(0.25) },
              { label: '50%', v: q(0.5) }, { label: '75%', v: q(0.75) },
              { label: 'Max', v: mx }];
    },
    get pctTicks() { return [0, 25, 50, 75, 100].map(v => ({ label: v + '%', v })); },
    get durationTicks() {
      return [{ label: '∞', v: 0 }, { label: '30m', v: 1800 }, { label: '1h', v: 3600 },
              { label: '2h', v: 7200 }, { label: '4h', v: 14400 }, { label: '6h', v: 21600 }];
    },
    get socTicks() { return [0, 50, 80, 90, 100].map(v => ({ label: v === 0 ? 'Off' : v + '%', v })); },
    // The inverter nameplate (max of charge/discharge) that the W slider and the
    // % anchor use — read live from SunSpec M702, so it tracks the real hardware.
    get nameplateW() { return Math.max(this.maxChargeW, this.maxDischargeW) || 5000; },
    setTick(field, value, slug) {
      this[field] = value;
      this.sendCommand(slug, value);
    },

    _log(slug, value, ok, message) {
      const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
      const label = slug.replace(/^battery_command_?/, '').replace(/_/g, ' ') || 'command';
      this.commandLog.push({ ts, slug: label, value, ok, message });
      if (this.commandLog.length > 50) this.commandLog.splice(0, this.commandLog.length - 50);
      this.$nextTick(() => { const el = this.$refs?.logScroll; if (el) el.scrollTop = el.scrollHeight; });
    },

    // Pick the active power unit (W or %) — they are mutually exclusive. Staging the
    // selected unit's value keeps the backend's power_mode in sync with what's shown.
    setPowerUnit(mode) {
      if (mode === this.powerMode) return;
      this.powerMode = mode;
      if (mode === 'w') this.sendCommand('battery_command_power', this.powerW);
      else this.sendCommand('battery_command_power_pct', this.powerPct);
    },

    setMaxCharge() { this.powerW = this.maxChargeW; this.sendCommand('battery_command_power', this.powerW); },
    setMaxDischarge() { this.powerW = this.maxDischargeW; this.sendCommand('battery_command_power', this.powerW); },

    async sendCommand(slug, value) {
      if (this.sending) return;
      // Parameter slugs carry a number — coerce to a clean finite integer so a
      // momentarily-empty/NaN field can never be POSTed (which left the value
      // unstaged) or logged blank. The `battery_command` slug keeps its string.
      if (slug !== 'battery_command') {
        const n = Number(value);
        value = Number.isFinite(n) ? Math.round(n) : 0;
        if (slug === 'battery_command_power') this.powerMode = 'w';
        if (slug === 'battery_command_power_pct') this.powerMode = 'pct';
      }

      // A Force command moves the real battery over Modbus — confirm first with a
      // styled modal. Release / Not Active (the safe direction) stay instant.
      if (slug === 'battery_command' && /^Force /.test(value)) {
        const pwr = this.powerMode === 'w' ? `${this.powerW} W` : `${this.powerPct}%`;
        const dur = this.duration > 0 ? this.fmtHMS(this.duration) + ' (hh:mm:ss)' : 'no limit (until released)';
        const tgt = this.targetSoc > 0 ? `${this.targetSoc}%` : 'none';
        const ok = await this.$store.app.confirmDialog(
          `${value} the battery now — this drives it directly over Modbus.\n\n` +
          `Power: ${pwr}\nDuration: ${dur}\nTarget SoC: ${tgt}`,
          { title: value, danger: true });
        if (!ok) { this.command = this.active; return; }  // revert the select to reality
      }

      this.sending = true;
      try {
        const r = await fetch('api/battery/command', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ slug, value: String(value) }),
        });
        const d = await r.json();
        if (r.ok && d.ok) {
          this._log(slug, value, true, d.result || 'Sent');
          if (d.active) this.active = d.active;
          this.$store.app.toast(`${slug.replace(/^battery_command_?/, '') || 'command'}: ${d.result || 'ok'}`, 'success');
        } else {
          const msg = d.result || d.detail || d.error || 'Failed';
          this._log(slug, value, false, msg);
          this.$store.app.toast(`Command failed: ${msg}`, 'error');
        }
      } catch (e) {
        this._log(slug, value, false, e.message);
        this.$store.app.toast(`Command failed: ${e.message}`, 'error');
      } finally {
        this.sending = false;
      }
    },
  };
}
