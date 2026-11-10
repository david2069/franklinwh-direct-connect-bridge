/**
 * Integration Mapping — Integration → Mapping.
 *
 * A mapping is a NAME this bridge uses paired with WHERE the value comes from, and a
 * PROBE that reads it live. It exists because "which frame carries this field" kept
 * being inferred from field names and neighbouring code rather than looked up, and
 * three of those inferences were wrong in a single week: VPP was declared absent from
 * the local API (wrong frame), gridLineVol was cited from 1708 (it is 1707), and
 * isThreePhaseInstall was used as grid topology (it is a solar field).
 *
 * Every one would have been a two-second probe.
 */
function integrationsTab() {
  return {
    protocols: [],
    reads: [],
    mappings: [],
    loading: false,
    saving: false,
    error: '',

    async init() {
      this.$watch('$store.app.activeTab', (t) => { if (t === 'integrations' && !this.protocols.length) this.load(); });
      if (this.$store.app.activeTab === 'integrations') this.load();
    },

    async load() {
      this.loading = true; this.error = '';
      try {
        const r = await this.$store.app.fetchTimeout('api/integrations', 15000);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const d = await r.json();
        this.protocols = d.protocols || [];
        this.reads = d.reads || [];
        this.mappings = d.mappings || [];
      } catch (e) {
        this.error = fetchErrorText(e, 'api/integrations');
      } finally { this.loading = false; }
    },

    proto(id) { return this.protocols.find(p => p.id === id) || null; },
    implemented(id) { const p = this.proto(id); return !p || p.implemented; },

    addRow() {
      this.mappings.push({ name: '', protocol: 'direct_9000', read: '', field: '',
                           unit: '', enabled: true, _probe: null, _probing: false });
    },
    removeRow(i) { this.mappings.splice(i, 1); },

    /** Read one field from the device NOW and show what came back, with the request
     *  that fetched it — so a claim can be checked instead of trusted. */
    async probe(row) {
      row._probing = true; row._probe = null;
      try {
        const r = await this.$store.app.fetchTimeout('api/probe', 45000, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ field: row.field, read: row.read || '',
                                 gateway: this.$store.app.selectedGateway || null }),
        });
        const d = await r.json();
        row._probe = r.ok
          ? { ok: true, ...d }
          : { ok: false, detail: (d.detail && d.detail.detail) || d.detail || 'not found',
              tried: (d.detail && d.detail.tried) || [] };
        // A probe that found the field tells us where it lives — fill it in rather
        // than making the user copy it across.
        if (r.ok && d.read && !row.read) row.read = d.read;
      } catch (e) {
        row._probe = { ok: false, detail: fetchErrorText(e, 'api/probe') };
      } finally { row._probing = false; }
    },

    async save() {
      this.saving = true; this.error = '';
      try {
        const clean = this.mappings.map(({ _probe, _probing, ...keep }) => keep);
        const r = await this.$store.app.fetchTimeout('api/integrations', 15000, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mappings: clean }),
        });
        // A non-JSON reply (a plain-text 500) must show as its status, not as the browser's
        // JSON parse error, which Safari words as "The string did not match…" (#247).
        const d = await r.json().catch(() => ({ detail: 'HTTP ' + r.status }));
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
        this.$store.app.toast(`Saved ${d.count} mapping(s)`, 'success');
      } catch (e) {
        this.error = (e && e.message) || String(e);
        this.$store.app.toast('Save failed: ' + this.error, 'error');
      } finally { this.saving = false; }
    },
  };
}
