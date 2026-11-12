/**
 * Customise dialog (#585, as the Modbus Bridge): one place, opened from the gear and from
 * the Dashboard's Cards button, to show, hide and reorder the top bar's items, the navbar's
 * tabs and the Dashboard's cards. Replaces the gear's Navbar / Top bar lists and the
 * Dashboard's Cards panel; Theme stays in the gear.
 *
 * Each row: a drag handle, finger-sized up/down arrows (the fallback for keyboard, screen
 * readers and a precise one-place move) and an on/off switch. Dragging uses pointer events
 * on the handle, so it works with a finger too: HTML5 drag events never fire from a touch
 * drag. Every change is saved at once under the existing keys; Undo (the store's) steps
 * back through this visit's changes, one step per click, toggle or drag.
 *
 * Lists: 'centre', 'right' (top bar), 'nav' and 'cards'.
 */
function customiseDialog() {
  return {
    _drag: null,   // {list, key} while a handle is held

    get app() { return Alpine.store('app'); },

    items(list) {
      const app = this.app;
      if (list === 'cards') {
        return app.dashOrderedList.map(([key, label]) => ({ key, label, on: !!app.dashCards[key] }));
      }
      if (list === 'nav') {
        return app.navOrdered.map(t => {
          const pin = app.navPinned(t.key);
          return { key: t.key, label: app.navLabel(t.key), on: t.on || !!pin, lockedOn: !!pin,
                   fixed: pin === 'both', note: pin === 'both' ? 'pinned' : (pin ? 'sidebar 2nd' : '') };
        });
      }
      return (app.topbarPrefs[list] || []).map(i => ({ key: i.id, label: i.label, on: i.on }));
    },

    toggle(list, key) {
      const app = this.app;
      if (list === 'nav' && app.navPinned(key)) return;      // pinned tabs stay on
      app.custSnapshot();
      if (list === 'cards') app.toggleDashCard(key);
      else if (list === 'nav') app.toggleNavItem(key);
      else app.toggleTopbarItem(list, key);
    },

    _keys(list) { return this.items(list).map(i => i.key); },

    canMove(list, key, delta) {
      const rows = this.items(list), at = rows.findIndex(r => r.key === key), to = at + delta;
      if (at < 0 || to < 0 || to >= rows.length) return false;
      return !rows[at].fixed && !rows[to].fixed;
    },

    // Put `key` at index `to` in its list; saves. No snapshot: callers take one.
    _place(list, key, to) {
      const app = this.app;
      if (list === 'cards') app.placeDashCard(key, to);
      else if (list === 'nav') app.placeNavItem(key, to);
      else app.placeTopbarItem(list, key, to);
    },

    move(list, key, delta) {
      if (!this.canMove(list, key, delta)) return;
      this.app.custSnapshot();
      this._place(list, key, this._keys(list).indexOf(key) + delta);
    },

    // ── drag by the handle ──
    dragStart(e, list, key) {
      e.preventDefault();
      this.app.custSnapshot();
      this._drag = { list, key };
      e.target.setPointerCapture?.(e.pointerId);
    },

    dragMove(e) {
      if (!this._drag) return;
      const row = document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-cust-row]');
      if (!row || row.dataset.list !== this._drag.list || row.dataset.key === this._drag.key) return;
      this._place(this._drag.list, this._drag.key, this._keys(this._drag.list).indexOf(row.dataset.key));
    },

    dragEnd() { this._drag = null; },

    dragging(list, key) { return !!this._drag && this._drag.list === list && this._drag.key === key; },
  };
}
