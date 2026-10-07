/**
 * Shared real-time cap for component tabs (battery, solar, circuits, logs).
 *
 * Continuous live polling holds a device session open and (on charty tabs)
 * accumulates browser samples — leaving it on for hours is the main memory /
 * resource risk (DEF-BROWSER-MEMORY). Each surface auto-pauses after the user's
 * per-surface limit (Settings → Real-time limits, stored on $store.app.liveCaps)
 * and offers an explicit resume. The dashboard has its own copy of this in the
 * store, because its poll lives there too.
 *
 * Spread into a component:  return { ...liveCapMixin('solar'), ... }
 * Contract the component fulfils:
 *   - call _capMark() (or _capStart()) when a live session begins
 *   - in the poll tick, if _capExpired(): _capTrip() then tear down its timer
 *   - define _capRestart() so resumeLive() can restart polling
 */
window.liveCapMixin = function (surface) {
  return {
    liveCapped: false,
    _liveStartedAt: null,
    _capMinutes() { return this.$store.app.liveCapMinutes(surface); },
    // Reset the clock at the start of each continuous polling run, so time spent
    // paused (tab hidden/away) never counts toward the cap. The cap measures
    // continuous ATTENDED foreground polling, not wall-clock since first-ever-live.
    _capMark() { this._liveStartedAt = Date.now(); },
    // Explicit (re)start of the clock — a fresh, deliberate live action.
    _capStart() { this.liveCapped = false; this._liveStartedAt = Date.now(); },
    _capExpired() {
      // Real-time capping is DISABLED (2026-09-21) — it caused live charts to freeze
      // unexpectedly and provided little value. Never auto-pause. The Settings →
      // Real-time limits UI is inert until this is deliberately re-enabled.
      return false;
    },
    // Trip the cap: mark paused + clear the clock. Caller tears down its timer.
    _capTrip() { this.liveCapped = true; this._liveStartedAt = null; },
    resumeLive() { this._capStart(); if (this._capRestart) this._capRestart(); },
  };
};
