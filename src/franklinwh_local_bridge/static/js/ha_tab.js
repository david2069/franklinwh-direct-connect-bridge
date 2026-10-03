/**
 * HA Entities tab.
 *
 * Two directions, deliberately kept apart on the page because conflating them is
 * the usual confusion:
 *   - PUBLISHED  — what this bridge sends INTO Home Assistant over MQTT.
 *   - INSTANCES  — Home Assistants the bridge can READ entities from.
 */
document.addEventListener('alpine:init', () => {
  Alpine.data('haTab', () => ({
    view: 'instances',
    instances: [],
    published: null,
    ents: null,
    loading: false,
    error: '',
    busy: false,

    // add / edit form
    form: null,
    testResult: null,

    // entity browser filters
    fInstance: '',
    fDomain: '',
    fSearch: '',
    fTopic: '',
    fExposedOnly: false,

    init() {
      this.$watch('$store.app.activeTab', (t) => { if (t === 'ha' && !this.instances.length) this.load(); });
      if (this.$store.app.activeTab === 'ha') this.load();
    },

    get canWrite() { return !!this.$store.app.summary.writes_enabled; },

    async load() {
      this.loading = true; this.error = '';
      try {
        const r = await fetch('api/ha/instances');
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.instances = (await r.json()).instances || [];
      } catch (e) { this.error = e.message; }
      finally { this.loading = false; }
    },

    async setView(v) {
      this.view = v;
      if (v === 'published' && !this.published) {
        this.published = await (await fetch('api/ha/published')).json();
      }
      if (v === 'entities' && !this.ents) await this.loadEntities();
    },

    async loadEntities() {
      this.loading = true; this.error = '';
      try {
        const q = new URLSearchParams();
        if (this.fInstance) q.set('instance', this.fInstance);
        if (this.fDomain) q.set('domain', this.fDomain);
        if (this.fSearch) q.set('search', this.fSearch);
        if (this.fTopic) q.set('topic', this.fTopic);
        if (this.fExposedOnly) q.set('exposed', 'true');
        const r = await fetch('api/ha/entities?' + q.toString());
        this.ents = await r.json();
      } catch (e) { this.error = e.message; }
      finally { this.loading = false; }
    },

    /** Toggle a topic chip — clicking the active one clears it. */
    setTopic(t) { this.fTopic = this.fTopic === t ? '' : t; this.loadEntities(); },

    /** Mark an entity exposed/visible. Optimistic, reverted on failure. */
    async toggleExposed(e) {
      const want = !e.exposed;
      e.exposed = want;                                  // optimistic
      try {
        const r = await fetch('api/ha/entities/expose', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instance_id: e.instance_id, entity_id: e.entity_id, exposed: want }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        if (this.ents) this.ents.exposed_count += want ? 1 : -1;
      } catch (err) {
        e.exposed = !want;                               // revert
        this.$store.app.toast(`Failed: ${err.message}`, 'error');
      }
    },

    newInstance() {
      this.testResult = null;
      this.form = { id: '', name: '', base_url: '', token: '', is_default: !this.instances.length, enabled: true };
    },
    editInstance(i) {
      this.testResult = null;
      // Token intentionally blank: it is never sent to the client. Leaving it blank
      // on save keeps the stored one.
      this.form = { id: i.id, name: i.name, base_url: i.base_url, token: '',
                    is_default: i.is_default, enabled: i.enabled };
    },
    closeForm() { this.form = null; this.testResult = null; },

    async testConnection() {
      this.busy = true;
      try {
        const r = await fetch('api/ha/test', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ base_url: this.form.base_url,
                                 token: this.form.token || null,
                                 ha_id: this.form.id || null }),
        });
        this.testResult = await r.json();
      } catch (e) { this.testResult = { ok: false, error: e.message }; }
      finally { this.busy = false; }
    },

    async saveInstance() {
      this.busy = true;
      try {
        const body = { name: this.form.name, base_url: this.form.base_url,
                       is_default: this.form.is_default, enabled: this.form.enabled };
        if (this.form.token) body.token = this.form.token;   // blank = keep existing
        const url = this.form.id ? `api/ha/instances/${this.form.id}` : 'api/ha/instances';
        const r = await fetch(url, {
          method: this.form.id ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const out = await r.json();
        if (!r.ok) throw new Error(out.detail || r.statusText);
        this.$store.app.toast(this.form.id ? 'Instance updated' : 'Instance added', 'success');
        this.closeForm();
        await this.load();
      } catch (e) {
        this.$store.app.toast(`Save failed: ${e.message}`, 'error');
      } finally { this.busy = false; }
    },

    async removeInstance(i) {
      const ok = await this.$store.app.confirmDialog(
        `Remove "${i.name}"? The bridge will stop reading entities from it.`,
        { title: 'Remove HA instance', danger: true });
      if (!ok) return;
      try {
        const r = await fetch(`api/ha/instances/${i.id}`, { method: 'DELETE' });
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        this.$store.app.toast('Instance removed', 'success');
        await this.load();
      } catch (e) { this.$store.app.toast(`Remove failed: ${e.message}`, 'error'); }
    },
  }));
});
