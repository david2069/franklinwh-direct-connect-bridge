/**
 * FranklinWH Local Bridge — MQTT tab
 * Lists the HA MQTT-discovery entities, shows broker connection state, and lets you
 * re-publish or clear the discovery config. Uses the shared $store.app.toast().
 */
function mqttTab() {
  return {
    entities: [],
    loading: false,
    connected: false,
    detecting: false,
    detectMsg: '',
    detectFound: false,
    publishing: false, node: '', enabledGroups: [], groupCatalogue: {},
    filter: 'all', search: '', groupSaving: false,
    conflicts: null, scanning: false,

    init() {
      // Loads on first SHOW, not on page load — see lazyTab().
      const t = lazyTab(this, 'mqtt', () => this.load());
      // Re-fetch when the topbar gateway selection changes, so the entity list + values
      // follow the selected gateway (mocks included) instead of showing the first one.
      this.$watch('$store.app.selectedGateway', () => t.reload());
    },

    get filteredEntities() {
      const q = (this.search || '').trim().toLowerCase();
      return (this.entities || []).filter(e => {
        if (this.filter === 'writable' && !e.writable) return false;
        if (this.filter === 'sensors' && (e.writable || e.diagnostic)) return false;
        if (this.filter === 'diagnostic' && !e.diagnostic) return false;
        if (q && !((e.name || '').toLowerCase().includes(q) || (e.slug || '').toLowerCase().includes(q))) return false;
        return true;
      });
    },
    groupEnabled(g) { return this.enabledGroups.includes(g); },
    async toggleGroup(g) {
      const set = new Set(this.enabledGroups);
      set.has(g) ? set.delete(g) : set.add(g);
      this.groupSaving = true;
      try {
        const r = await fetch('api/mqtt/groups', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ groups: [...set] }) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
        this.enabledGroups = (await r.json()).enabled || [...set];
        await this.load();
        Alpine.store('app').toast('MQTT groups updated — re-publishing', 'success');
      } catch (e) { Alpine.store('app').toast('Update failed: ' + e.message, 'error'); }
      finally { this.groupSaving = false; }
    },

    async detect() {
      this.detecting = true;
      this.detectMsg = '';
      try {
        const r = await fetch('api/mqtt/discover');
        const d = await r.json();
        this.detectFound = !!d.found;
        if (d.found) {
          this.detectMsg = `Broker found: ${d.host}:${d.port} (${d.source || 'supervisor'})`
            + '. Credentials are auto-applied at startup in add-on mode.';
        } else {
          this.detectMsg = d.error || 'No broker found.';
        }
      } catch (e) {
        this.detectFound = false;
        this.detectMsg = 'Detect failed: ' + e.message;
      } finally {
        this.detecting = false;
      }
    },

    // Sniff the shared broker for OTHER FranklinWH producers — the same aGate under a Modbus
    // bridge / FWHAI / second Local bridge shows as duplicate HA devices (not a topic clash).
    async scanConflicts() {
      this.scanning = true;
      try {
        const r = await fetch('api/mqtt/conflicts' + Alpine.store('app').gwQuery('?'));
        this.conflicts = await r.json();
        if (!this.conflicts.ok) Alpine.store('app').toast(this.conflicts.error || 'Scan failed', 'info');
      } catch (e) {
        this.conflicts = { ok: false, error: 'Scan failed: ' + e.message };
      } finally { this.scanning = false; }
    },

    async load() {
      this.loading = true;
      try {
        // Scope to the selected gateway (multi-gateway); '' when single-gateway.
        const gwq = Alpine.store('app').gwQuery('?');
        const [entR, cfgR] = await Promise.all([
          fetch('api/mqtt/entities' + gwq),
          fetch('api/mqtt/config' + gwq),
        ]);
        if (entR.ok) { const d = await entR.json(); this.entities = d.entities || d; this.publishing = !!d.publishing; this.node = d.node || ''; this.enabledGroups = d.enabled_groups || []; this.groupCatalogue = d.groups || {}; }
        if (cfgR.ok) {
          const cfg = await cfgR.json();
          this.connected = !!cfg.connected;
        }
      } catch (e) {
        console.warn('[Bridge] mqtt load failed:', e.message);
      } finally {
        this.loading = false;
      }
    },

    fmtValue(v) {
      if (v === null || v === undefined || v === '') return '—';
      if (typeof v === 'number') return Math.round(v * 100) / 100;
      return v;
    },

    async republish() {
      try {
        const r = await fetch('api/mqtt/republish' + Alpine.store('app').gwQuery('?'),
                              { method: 'POST' });
        const d = await r.json();
        Alpine.store('app').toast(d.detail, d.ok ? 'info' : 'error');
      } catch (e) {
        Alpine.store('app').toast('Republish failed: ' + e.message, 'error');
      }
    },

    async unpublish() {
      if (!confirm('Remove all FranklinWH entities from Home Assistant?')) return;
      try {
        const r = await fetch('api/mqtt/unpublish' + Alpine.store('app').gwQuery('?'),
                              { method: 'POST' });
        const d = await r.json();
        Alpine.store('app').toast(d.detail, d.ok ? 'info' : 'error');
      } catch (e) {
        Alpine.store('app').toast('Clear failed: ' + e.message, 'error');
      }
    },
  };
}
