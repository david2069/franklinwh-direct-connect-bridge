/* What's installed, in plain words (#496). See templates/partials/install_profile.html.
 *
 * One card per gateway, shared by the setup wizard's Confirm step and Settings → Setup.
 * Facts the gateway reports say where they came from and wait for Confirm; only what the
 * gateway can't tell is asked. Results show on the card itself, never as a toast.
 */
window.installProfile = function installProfile() {
  return {
    cards: [],
    loading: false,
    error: '',
    msg: {},                 // gateway id -> last result on that card
    open: {},                // gateway id -> the one fact row shown open, or none

    isOpen(card, key) { return this.open[card.gateway_id] === key; },
    toggle(card, key) {
      this.open[card.gateway_id] = this.isOpen(card, key) ? null : key;
    },

    async load() {
      this.loading = true;
      this.error = '';
      try {
        const r = await fetch('api/install-profile');
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || r.statusText);
        this.cards = d.gateways || [];
      } catch (e) {
        this.error = `Couldn't read the gateways: ${e.message}`;
      } finally {
        this.loading = false;
      }
    },

    async _post(path, gid, body, done) {
      this.msg[gid] = '';
      try {
        const r = await fetch(`${path}?gateway=${encodeURIComponent(gid)}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || r.statusText);
        this.cards = d.gateways || this.cards;
        this.msg[gid] = done;
      } catch (e) {
        this.msg[gid] = `Not saved: ${e.message}`;
      }
    },

    confirm(card, keys) {
      return this._post('api/install-profile/confirm', card.gateway_id, { keys }, 'Confirmed.');
    },
    confirmAll(card) {
      const keys = card.facts.filter(f => !f.confirmed && f.value !== "Couldn't be read")
        .map(f => f.key);
      return keys.length ? this.confirm(card, keys) : null;
    },
    answer(card, q, value) {
      return this._post('api/install-profile/answer', card.gateway_id, { key: q.key, value },
        'Saved.');
    },
    unconfirmed(card) {
      // The battery name is optional, so it never counts as waiting.
      return card.facts.filter(f => !f.confirmed).length
        + card.questions.filter(q => !q.answered && q.key !== 'battery_label').length;
    },
  };
};
