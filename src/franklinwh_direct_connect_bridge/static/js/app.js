/**
 * FranklinWH Local Bridge — Frontend App State
 * Alpine.js global store. Polls GET /api/summary and drives the shell.
 */

// ── Utilities ────────────────────────────────────────────────
const fmt = {
  w:   (v) => (v != null ? `${Math.round(v)}` : '--'),
  pct: (v) => (v != null ? `${Math.round(v)}%` : '--'),
  soc: (v) => (v != null ? `${Math.round(v)}` : '--'),
  socPct: (v) => (v != null ? `${Math.round(v)}%` : '--'),   // whole number + unit
  ms:  (v) => (v != null ? `${Math.round(v)}` : '--'),
};

// SoC ring stroke colour by level.
/**
 * Defer a tab's first fetch until the tab is actually shown.
 *
 * Every tab is mounted with `x-show`, not `x-if`, so its component is alive from
 * page load whether or not you are looking at it. Six tabs fetched in `init()`,
 * which meant opening ANY page fired an aGate session for the Network scan, the
 * MQTT entity list, the grid read and more — and over a slow link those failed and
 * toasted errors for tabs the user was not on.
 *
 * Returns `{ reload }`: a no-op until the first real load has happened, so a
 * gateway-change watcher cannot resurrect the eager behaviour it was meant to fix.
 */
function lazyTab(cmp, key, loader) {
  let loaded = false;
  const run = () => { if (loaded) return; loaded = true; return loader(); };
  if (cmp.$store.app.activeTab === key) run();
  cmp.$watch('$store.app.activeTab', (t) => { if (t === key) run(); });
  return {
    get loaded() { return loaded; },
    reload: () => (loaded ? loader() : undefined),
  };
}

/**
 * A fetch failure in words. Browsers throw a bare "Load failed" (Safari) or
 * "Failed to fetch" (Chrome) with no URL, status or cause — which tells the user
 * nothing and tells a bug report less.
 */
function fetchErrorText(e, url) {
  const m = (e && e.message) || String(e);
  if (/load failed|failed to fetch|networkerror/i.test(m)) {
    return `could not reach ${url} — the request never completed `
         + `(bridge unreachable, request blocked, or the link timed out)`;
  }
  return `${url}: ${m}`;
}

function socColour(soc) {
  if (soc == null) return 'var(--text-muted)';
  if (soc >= 80) return 'var(--ok)';
  if (soc >= 30) return 'var(--accent)';
  if (soc >= 15) return 'var(--warn)';
  return 'var(--danger)';
}

// Power value colour: battery charge/discharge, grid import/export, solar.
function powerColour(watts, type) {
  if (watts == null) return 'var(--text-muted)';
  if (type === 'battery') return watts < 0 ? 'var(--ok)' : watts > 0 ? 'var(--warn)' : 'var(--text-muted)';
  if (type === 'grid')    return watts > 0 ? 'var(--danger)' : watts < 0 ? 'var(--ok)' : 'var(--text-muted)';
  if (type === 'solar')   return watts > 0 ? 'var(--solar)' : 'var(--text-muted)';
  return 'var(--text-primary)';
}

// ── Main Alpine App ──────────────────────────────────────────
document.addEventListener('alpine:init', () => {

  Alpine.store('app', {
    // ── State ──────────────────────────────────────────────
    summary: {},
    // ── Build freshness ────────────────────────────────────
    // A dashboard tab stays open for days. Poll the asset token and offer a
    // reload when the bridge has been rebuilt, rather than letting someone stare
    // at a fixed bug that is already fixed on disk.
    buildAsset: '',
    newBuild: false,

    dismissedAsset: '',

    async checkBuild() {
      try {
        const v = await (await fetch('api/version', { cache: 'no-store' })).json();
        if (!this.buildAsset) { this.buildAsset = v.asset; return; }
        // Show the modal for a genuinely newer build, unless the user already
        // said "Later" for this exact build (don't nag every 30s).
        if (v.asset && v.asset !== this.buildAsset && v.asset !== this.dismissedAsset) {
          this.pendingAsset = v.asset;
          this.newBuild = true;
        }
      } catch { /* offline or restarting — try again next tick */ }
    },

    pendingAsset: '',
    dismissBuild() { this.dismissedAsset = this.pendingAsset; this.newBuild = false; },
    reloadForBuild() { location.reload(true); },

    // ── Multi-gateway (reads/monitoring) ───────────────────
    gateways: [],
    // Multi-gateway = single view at a time. ALWAYS defaults to the first defined
    // gateway on load (not a persisted selection); the topbar/in-card switcher changes
    // it for the session.
    selectedGateway: '',
    activeTab: localStorage.getItem('fwh-tab') || 'dashboard',

    // Title shown in the topbar. A map, not a ternary chain — the chain it
    // replaced had no arm for battery/device/logs and fell through to a
    // literal 'Health', so three tabs displayed the wrong name.
    // ── mobile bottom nav ── dynamic: as many tabs as fit the width, rest under More.
    // Ordered tab registry (icon = sidebar SVG inner markup) for the DYNAMIC bottom bar.
    _navTabsAll: [
      { key: 'dashboard', title: 'Home', icon: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/> <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>' },
      { key: 'battery', title: 'Battery', icon: '<rect x="2" y="7" width="18" height="10" rx="2"/><path d="M22 11v2"/><path d="M6 11v2"/>' },
      { key: 'analytics', title: 'Analytics', icon: '<path d="M3 3v18h18"/><path d="M7 14l3-4 3 3 4-6"/>' },
      { key: 'energy_costs', title: 'Costs', icon: '<circle cx="12" cy="12" r="9"/><path d="M14.8 9.5a2.5 2.5 0 0 0-2.3-1.5c-1.4 0-2.5.9-2.5 2s1.1 2 2.5 2 2.5.9 2.5 2-1.1 2-2.5 2a2.5 2.5 0 0 1-2.3-1.5M12 6.5v11"/>' },
      { key: 'solar', title: 'Solar', icon: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>' },
      { key: 'scheduler', title: 'Schedule', icon: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>' },
      { key: 'circuits', title: 'Circuits', icon: '<path d="M9 2v6"/><path d="M15 2v6"/><path d="M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>' },
      { key: 'generator', title: 'Generator', icon: '<rect x="3" y="9" width="18" height="11" rx="2"/><path d="M7 9V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v3"/><path d="M11 13l-2 3h4l-2 3"/>' },
      { key: 'health', title: 'Health', icon: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>' },
      { key: 'ha', title: 'HA', icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M3 11l9-8 9 8"/> <path stroke-linecap="round" stroke-linejoin="round" d="M5 10v10h14V10"/>' },
      { key: 'mqtt', title: 'MQTT', icon: '<circle cx="12" cy="12" r="2"/> <path stroke-linecap="round" d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.24a6 6 0 0 1 0-8.49"/> <path stroke-linecap="round" d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/>' },
      { key: 'network', title: 'Network', icon: '<circle cx="12" cy="12" r="9"/><path stroke-linecap="round" d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/>' },
      { key: 'grid', title: 'Grid', icon: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>' },
      { key: 'device', title: 'Device', icon: '<rect x="4" y="4" width="16" height="16" rx="2"/> <rect x="9" y="9" width="6" height="6"/> <path stroke-linecap="round" d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>' },
      { key: 'control', title: 'Control', icon: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/> <line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/> <line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/> <line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>' },
      { key: 'logs', title: 'Logs', icon: '<path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h10"/>' },
      { key: 'settings', title: 'Settings', icon: '<circle cx="12" cy="12" r="3"/> <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>' },
    ],
    //: Whether this gateway has a generator (1901 genEn OR configured). Device-metric
    //  tabs/columns for absent hardware are hidden rather than showing a permanent 0 W.
    generatorInstalled: false,
    //: The registry filtered to what this gateway actually has — feeds barMax/barTabs/
    //  overflowTabs and the bottom nav. Generator drops out when no genset is present.
    //: One ordering drives BOTH navs. The sidebar and the bottom bar used to be two
    //  hand-maintained lists that had drifted apart in order AND in naming; they now
    //  read the same registry, differing only in label width (tabTitles = long form
    //  for the sidebar, tab.title = short form for the 64px bar slots).
    //  Pinning: 'dashboard' is locked first and always on, everywhere. 'settings' is
    //  locked on and always second in the SIDEBAR, but floats in the bar order — bar
    //  slots are scarce (~5 on a phone) and Settings is always reachable under More.
    NAV_PIN: { dashboard: 'both', settings: 'sidebar' },
    navPinned(key) { return this.NAV_PIN[key] || ''; },
    navLabel(key) { return this.tabTitles[key] || key; },

    //: The registry filtered to hardware this gateway actually has.
    get navAvailable() { return this._navTabsAll.filter(t => t.key !== 'generator' || this.generatorInstalled); },

    navPrefs: [],
    _navDefaults() {
      return this._navTabsAll.map(t => ({ id: t.key, on: true }));
    },
    _loadNavPrefs() {
      let p = null;
      try { p = JSON.parse(localStorage.getItem('fwh-local-nav') || 'null'); } catch (e) { /**/ }
      const def = this._navDefaults();
      const byId = Object.fromEntries(def.map(d => [d.id, d]));
      const out = [];
      (Array.isArray(p) ? p : []).forEach(s => {
        if (byId[s.id]) { out.push({ id: s.id, on: !!s.on }); delete byId[s.id]; }
      });
      // Tabs added in an upgrade append rather than vanish for anyone with saved prefs.
      Object.values(byId).forEach(d => out.push({ ...d }));
      this.navPrefs = out;
    },
    _saveNavPrefs() {
      try { localStorage.setItem('fwh-local-nav', JSON.stringify(this.navPrefs)); } catch (e) { /**/ }
    },
    toggleNavItem(id) {
      if (this.navPinned(id)) return;              // pinned tabs cannot be hidden
      this.navPrefs = this.navPrefs.map(x => x.id === id ? { ...x, on: !x.on } : x);
      this._saveNavPrefs();
    },
    moveNavItem(id, dir) {
      if (this.navPinned(id) === 'both') return;   // dashboard is locked first
      const arr = this.navPrefs;
      const i = arr.findIndex(x => x.id === id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= arr.length) return;
      if (this.navPinned(arr[j].id) === 'both') return;
      const next = [...arr];
      [next[i], next[j]] = [next[j], next[i]];
      this.navPrefs = next;
      this._saveNavPrefs();
    },
    resetNavPrefs() { this.navPrefs = this._navDefaults(); this._saveNavPrefs(); },

    //: Every available tab in the user's order, pinned-first — the list the cog edits.
    get navOrdered() {
      const by = Object.fromEntries(this.navAvailable.map(t => [t.key, t]));
      const seen = new Set();
      const out = [];
      this.navPrefs.forEach(p => { if (by[p.id] && !seen.has(p.id)) { seen.add(p.id); out.push({ ...by[p.id], on: !!p.on }); } });
      this.navAvailable.forEach(t => { if (!seen.has(t.key)) out.push({ ...t, on: true }); });
      const pin = out.filter(t => this.navPinned(t.key) === 'both');
      return [...pin, ...out.filter(t => this.navPinned(t.key) !== 'both')];
    },

    //: Bottom bar — visible tabs only, in that order.
    get navTabs() { return this.navOrdered.filter(t => t.on || this.navPinned(t.key)); },

    //: Sidebar — same list, but Settings is hoisted to second.
    get sidebarTabs() {
      const v = this.navTabs;
      const st = v.find(t => t.key === 'settings');
      if (!st) return v;
      const rest = v.filter(t => t.key !== 'settings');
      return [rest[0], st, ...rest.slice(1)].filter(Boolean);
    },
    bottomTabKeys: ['dashboard', 'battery', 'solar', 'scheduler'],
    // Live viewport width (horizontal only — stable on iOS URL-bar scroll, so no thrash).
    winW: (typeof window !== 'undefined' ? window.innerWidth : 1024),
    // How many bar slots fit: ~64px per button, min 4, max the whole registry.
    get barMax() { return Math.max(4, Math.min(this.navTabs.length, Math.floor((this.winW || 375) / 64))); },
    // Tabs shown on the bar; if not everything fits, the last slot is "More".
    get barTabs() { const m = this.barMax; return m >= this.navTabs.length ? this.navTabs : this.navTabs.slice(0, m - 1); },
    get overflowTabs() { const m = this.barMax; return m >= this.navTabs.length ? [] : this.navTabs.slice(m - 1); },
    get showMore() { return this.overflowTabs.length > 0; },
    moreOpen: false,
    tabTitles: {
      dashboard: 'Dashboard', control: 'Control', mqtt: 'MQTT',
      settings: 'Settings', health: 'Health', battery: 'Battery',
      circuits: 'Smart Circuits', generator: 'Generator', solar: 'Solar',
      ha: 'Home Assistant', scheduler: 'Scheduler',
      device: 'Device', logs: 'Logs', analytics: 'Analytics', energy_costs: 'Energy Costs',
      network: 'Network', grid: 'Grid & Inverter',
    },
    get tabTitle() {
      return this.tabTitles[this.activeTab]
        || (this.activeTab || '').replace(/^./, c => c.toUpperCase());
    },
    get moreTabList() { return this.overflowTabs.map(t => [t.key, t.title]); },  // legacy shape

    sidebarCollapsed: false,   // set in init(): collapsed on mobile, saved pref on desktop
    // ── sidebar ────────────────────────────────────────────
    // The nav rail is cramped on a phone, so start it collapsed on narrow screens
    // (the icon rail + hover labels still navigate). On desktop honour a saved
    // preference. A manual toggle persists on desktop only, so a phone session
    // never overwrites the desktop layout choice.
    _mqNarrow: null,
    narrow: false,   // drives sidebar vs bottom-nav (matchMedia + navLayout override)
    terminalOpen: false,   // global terminal drawer (launched from either nav; the drawer syncs)
    toggleTerminal() { if (!this.advancedTools) return; this.terminalOpen = !this.terminalOpen; },

    //: Advanced / admin tools, OFF by default. Gates a CATEGORY, not one button, so
    //  anything later judged admin-only joins this gate rather than inventing its own.
    //  Browser-local for now; when user profiles arrive this becomes a server-side
    //  role and the controls stop depending on which device you happen to be on.
    advancedTools: false,
    setAdvancedTools(on) {
      this.advancedTools = !!on;
      if (!this.advancedTools) this.terminalOpen = false;   // never leave it open behind the gate
      try { localStorage.setItem('fwh-local-advanced', this.advancedTools ? '1' : '0'); } catch (e) { /**/ }
    },
    _loadAdvancedTools() {
      try { this.advancedTools = localStorage.getItem('fwh-local-advanced') === '1'; } catch (e) { /**/ }
    },
    // Nav layout override: 'auto' = by width (< 768 = bottom bar; tablets/desktop = sidebar),
    // 'sidebar' / 'bottom' force one regardless of width. Persisted per-browser.
    navLayout: localStorage.getItem('fwh-nav-layout') || 'auto',
    _computeNarrow() {
      if (this.navLayout === 'sidebar') return false;
      if (this.navLayout === 'bottom') return true;
      return this._mqNarrow ? this._mqNarrow.matches
                            : window.matchMedia('(max-width: 699px)').matches;
    },
    initSidebar() {
      // 768 px cutover: phones (< 768) get the bottom bar; all iPads/desktop get the sidebar
      // by default. The navLayout override wins over this.
      this._mqNarrow = window.matchMedia('(max-width: 699px)');
      const saved = localStorage.getItem('fwh-sidebar-collapsed');
      this.narrow = this._computeNarrow();
      this.sidebarCollapsed = this._mqNarrow.matches ? true : (saved === '1');
      // On a real rotate/resize across the phone boundary (only when Auto), tuck the rail away.
      this._mqNarrow.addEventListener('change', (e) => {
        this.narrow = this._computeNarrow();
        if (e.matches && this.navLayout === 'auto') this.sidebarCollapsed = true;
      });
      // Track width for the dynamic bottom bar (innerWidth doesn't change on vertical scroll).
      window.addEventListener('resize', () => { this.winW = window.innerWidth; });
    },
    setNavLayout(v) {
      this.navLayout = (v === 'sidebar' || v === 'bottom') ? v : 'auto';
      localStorage.setItem('fwh-nav-layout', this.navLayout);
      this.narrow = this._computeNarrow();
    },

    // ── First-connection legal disclaimer (unofficial app) ──────────────────
    showDisclaimer: false,

    // Guide (bundled mkdocs site). Opened as an in-app panel, never as a plain
    // navigation: in a home-screen/PWA window there is no browser chrome, so a
    // link to guide/ strands the user in the docs with no way back to the app.
    guideOpen: false,
    openGuide() { this.guideOpen = true },
    closeGuide() { this.guideOpen = false },
    disclaimer: null,      // { title, lines[], issues_url, docs_url, version, agreed }
    agreedChecked: false,  // the "I have read and agree" checkbox
    _clientId() {
      let id = null;
      try { id = localStorage.getItem('fwh-client-id'); } catch (e) { /* private mode */ }
      if (!id) {
        id = (self.crypto && crypto.randomUUID) ? crypto.randomUUID()
             : 'c-' + Math.abs((Date.now() ^ (this.winW || 0)) >>> 0).toString(36);
        try { localStorage.setItem('fwh-client-id', id); } catch (e) { /* ignore */ }
      }
      return id;
    },
    async _loadDisclaimer() {
      // The DB is the source of truth for don't-show-again (survives a localStorage clear),
      // keyed by a stable per-browser client id.
      try {
        const cid = encodeURIComponent(this._clientId());
        this.disclaimer = await (await fetch('api/disclaimer?client_id=' + cid)).json();
        if (this.disclaimer && !this.disclaimer.agreed) this.showDisclaimer = true;
      } catch (e) { /* if it can't load, don't block the app */ }
    },
    async ackDisclaimer() {
      this.showDisclaimer = false;
      // Only persist "don't show again" when the user ticked "I agree"; otherwise it
      // reappears next load. When agreed: record in the DB + write the agreement to the log.
      if (this.agreedChecked) {
        try {
          fetch('api/disclaimer/ack', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: this._clientId() }),
          });
        } catch (e) { /* best-effort */ }
      }
    },
    setSidebar(v) {
      this.sidebarCollapsed = v;
      if (window.matchMedia('(min-width: 700px)').matches) {
        localStorage.setItem('fwh-sidebar-collapsed', v ? '1' : '0');
      }
    },
    toggleSidebar() { this.setSidebar(!this.sidebarCollapsed); },

    theme: localStorage.getItem('fwh-theme') || 'dark',
    accent: localStorage.getItem('fwh-accent') || '',   // '' = default green (#22c55e)
    accents: [
      { name: 'Emerald', color: '#22c55e' },
      { name: 'Ocean',   color: '#06b6d4' },
      { name: 'Sky',     color: '#3b82f6' },
      { name: 'Violet',  color: '#8b5cf6' },
      { name: 'Amber',   color: '#f59e0b' },
      { name: 'Rose',    color: '#f43f5e' },
    ],
    setAccent(color) {
      this.accent = color || '';
      const r = document.documentElement.style;
      const props = ['--accent','--primary-color','--primary-dark','--primary-light','--accent-glow','--border-accent'];
      if (!color) { props.forEach(p => r.removeProperty(p)); localStorage.removeItem('fwh-accent'); return; }
      r.setProperty('--accent', color);
      r.setProperty('--primary-color', color);
      r.setProperty('--primary-dark',  `color-mix(in srgb, ${color} 82%, black)`);
      r.setProperty('--primary-light', `color-mix(in srgb, ${color} 72%, white)`);
      r.setProperty('--accent-glow',   `color-mix(in srgb, ${color} 15%, transparent)`);
      r.setProperty('--border-accent', `color-mix(in srgb, ${color} 32%, transparent)`);
      localStorage.setItem('fwh-accent', color);
    },
    version: '--',
    batteryActive: 'Not Active',   // active WSet force dispatch (topbar Release)
    batteryRemaining: null,
    toasts: [],
    _toastId: 0,
    _interval: null,

    // ── real-time caps (global, per-surface; minutes, 0 = no limit) ──
    // Configurable in Settings → Real-time limits; persisted per browser. Reads
    // fall back to liveCapDefaults for any surface the user has not set.
    liveCaps: {},
    // ── dashboard card customisation (show/hide; per browser) ──
    dashCardsOpen: false,
    dashCardDefaults: {
      socRing: true, powerFlow: true, battery: true, energyToday: true, energyFlow: true,
      operatingMode: true, diagnostics: true, solarForecast: true, powerHistory: true, livePoints: true,
    },
    dashCardList: [
      ['socRing', 'State of Charge'], ['powerFlow', 'Power Flow'], ['battery', 'Battery'],
      ['energyToday', 'Energy'], ['energyFlow', 'Energy Flow'], ['operatingMode', 'Operating Mode'],
      ['diagnostics', 'Diagnostics'], ['solarForecast', 'Solar Forecast'], ['powerHistory', 'Power History'], ['livePoints', 'Live Points'],
    ],
    dashCards: {},
    //: User-chosen card order (array of keys). Defaults to the dashCardList order; any new
    //  cards not yet in a saved order are appended so an upgrade never drops one.
    dashOrder: [],
    get _dashKeys() { return this.dashCardList.map(c => c[0]); },
    _loadDashCards() {
      try {
        const saved = JSON.parse(localStorage.getItem('fwh-local-dash-cards') || '{}');
        this.dashCards = { ...this.dashCardDefaults, ...(saved && typeof saved === 'object' ? saved : {}) };
      } catch (e) { this.dashCards = { ...this.dashCardDefaults }; }
      try {
        const ord = JSON.parse(localStorage.getItem('fwh-local-dash-order') || '[]');
        const valid = Array.isArray(ord) ? ord.filter(k => this._dashKeys.includes(k)) : [];
        this.dashOrder = [...valid, ...this._dashKeys.filter(k => !valid.includes(k))];
      } catch (e) { this.dashOrder = [...this._dashKeys]; }
    },
    //: CSS `order` for a card so the flat dashboard grid renders in the chosen sequence.
    dashCardStyle(key) {
      // Return an OBJECT, not a string. Alpine merges an object :style property-by-property,
      // so it preserves the `display:none` that x-show sets when the card is hidden. A STRING
      // :style rewrites cssText and wipes that display, so a hidden card kept rendering — most
      // visibly the Diagnostics card (a .metrics-grid, display:grid, not a .card). Same class of
      // bug as the terminal-drawer :style-string clobber.
      const i = this.dashOrder.indexOf(key);
      return { order: String(i < 0 ? 99 : i) };
    },
    //: Ordered [key,label] rows for the customise modal.
    get dashOrderedList() {
      const by = Object.fromEntries(this.dashCardList);
      return this.dashOrder.map(k => [k, by[k]]).filter(r => r[1]);
    },
    _saveDashOrder() {
      try { localStorage.setItem('fwh-local-dash-order', JSON.stringify(this.dashOrder)); } catch (e) { /**/ }
    },
    moveDashCard(key, dir) {
      const i = this.dashOrder.indexOf(key);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= this.dashOrder.length) return;
      const next = [...this.dashOrder];
      [next[i], next[j]] = [next[j], next[i]];
      this.dashOrder = next;
      this._saveDashOrder();
    },
    toggleDashCard(key) {
      this.dashCards = { ...this.dashCards, [key]: !this.dashCards[key] };
      try { localStorage.setItem('fwh-local-dash-cards', JSON.stringify(this.dashCards)); } catch (e) { /**/ }
    },
    resetDashCards() {
      this.dashCards = { ...this.dashCardDefaults };
      this.dashOrder = [...this._dashKeys];
      try {
        localStorage.removeItem('fwh-local-dash-cards');
        localStorage.removeItem('fwh-local-dash-order');
      } catch (e) { /**/ }
    },

    // ── topbar customisation (show/hide + reorder; per browser) ──
    //  Mirrors the Modbus Bridge "Topbar Preferences". The gateway selector and the
    //  connection status are LOCKED (always shown) and intentionally NOT in these lists.
    topbarPrefsOpen: false,
    prefsTab: 'appearance',   // which cog view: appearance | nav | topbar
    topbarPrefs: { centre: [], right: [] },
    _topbarDefaults() {
      return {
        centre: [
          { id: 'mode', label: 'Operating mode', on: true },
          { id: 'status', label: 'VPP / Force / Off-grid', on: true },
          { id: 'charge', label: 'Charge state', on: true },
          { id: 'soc', label: 'State of charge', on: true },
          { id: 'latency', label: 'Round-trip latency', on: true },
        ],
        right: [
          { id: 'cards', label: 'Cards (dashboard)', on: true },
          { id: 'rawkeys', label: 'Raw keys </>', on: true },
          { id: 'refresh', label: 'Refresh', on: true },
          { id: 'theme', label: 'Theme', on: true },
          { id: 'release', label: 'Release', on: true },
        ],
      };
    },
    _loadTopbarPrefs() {
      let p = null;
      try { p = JSON.parse(localStorage.getItem('fwh-local-topbar') || 'null'); } catch (e) { /**/ }
      const def = this._topbarDefaults();
      // Merge saved on/off + order onto defaults so a new item added in an upgrade still shows.
      const merge = (group) => {
        const saved = (p && Array.isArray(p[group])) ? p[group] : [];
        const byId = Object.fromEntries(def[group].map(d => [d.id, d]));
        const out = [];
        saved.forEach(s => { if (byId[s.id]) { out.push({ ...byId[s.id], on: !!s.on }); delete byId[s.id]; } });
        Object.values(byId).forEach(d => out.push({ ...d }));
        return out;
      };
      this.topbarPrefs = { centre: merge('centre'), right: merge('right') };
    },
    _saveTopbarPrefs() {
      try { localStorage.setItem('fwh-local-topbar', JSON.stringify(this.topbarPrefs)); } catch (e) { /**/ }
    },
    _tbItem(id) {
      const p = this.topbarPrefs;
      return (p.centre || []).concat(p.right || []).find(x => x.id === id);
    },
    topbarShow(id) { const it = this._tbItem(id); return it ? it.on : true; },
    topbarOrder(id) {
      let i = (this.topbarPrefs.centre || []).findIndex(x => x.id === id);
      if (i >= 0) return i;                         // centre indicators: 0..n
      i = (this.topbarPrefs.right || []).findIndex(x => x.id === id);
      return i >= 0 ? 100 + i : 999;                // right buttons: always after centre
    },
    toggleTopbarItem(group, id) {
      const arr = this.topbarPrefs[group] || [];
      const next = arr.map(x => x.id === id ? { ...x, on: !x.on } : x);
      this.topbarPrefs = { ...this.topbarPrefs, [group]: next };
      this._saveTopbarPrefs();
    },
    moveTopbarItem(group, id, dir) {
      const arr = this.topbarPrefs[group] || [];
      const i = arr.findIndex(x => x.id === id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= arr.length) return;
      const next = [...arr];
      [next[i], next[j]] = [next[j], next[i]];
      this.topbarPrefs = { ...this.topbarPrefs, [group]: next };
      this._saveTopbarPrefs();
    },
    resetTopbarPrefs() { this.topbarPrefs = this._topbarDefaults(); this._saveTopbarPrefs(); },
    liveCapDefaults: { dashboard: 60, battery: 30, solar: 30, circuits: 30, logs: 30 },
    liveCapOptions: [5, 15, 30, 60, 0],
    liveCapSurfaces: [
      { key: 'dashboard', label: 'Dashboard', note: 'live power poll (every 5s)' },
      { key: 'battery',   label: 'Battery',   note: 'Auto / Chart / Watch-live' },
      { key: 'solar',     label: 'Solar',     note: 'Auto-refresh' },
      { key: 'circuits',  label: 'Smart Circuits', note: 'Monitoring Auto-refresh' },
      { key: 'logs',      label: 'Logs',      note: 'live tail (every 10s)' },
    ],
    liveCapLabel(m) { return m > 0 ? m + ' min' : 'no limit'; },
    liveCapMinutes(surface) {
      const c = this.liveCaps[surface];
      return Number.isFinite(c) ? c : (this.liveCapDefaults[surface] || 0);
    },
    setLiveCap(surface, minutes) {
      this.liveCaps = { ...this.liveCaps, [surface]: Number(minutes) };
      try { localStorage.setItem('fwh-live-caps', JSON.stringify(this.liveCaps)); } catch (e) { /* private mode */ }
    },
    _loadLiveCaps() {
      try {
        const raw = JSON.parse(localStorage.getItem('fwh-live-caps') || '{}');
        if (raw && typeof raw === 'object') this.liveCaps = raw;
      } catch (e) { /* corrupt / unavailable — keep defaults */ }
    },
    // Dashboard cap runtime (its poll lives in this store, not a component).
    dashCapped: false,
    _dashStartedAt: null,
    _dashExpired() {
      // Real-time capping DISABLED (2026-09-21) — see live_cap.js. Never auto-pause.
      return false;
    },
    _dashTick() {
      if (this._dashExpired()) { this.dashCapped = true; this._dashStartedAt = null; this._pausePoll(); return; }
      this.poll();
    },
    resumeDashboard() {
      this.dashCapped = false; this._dashStartedAt = Date.now();
      this._resumePoll(); this.poll();
    },

    // ── Connection state (banner + details modal) ──────────
    // poll() used to swallow failures with a console.warn, so if the bridge went
    // away the UI silently served stale data. Track it explicitly instead and
    // surface a banner, mirroring the FWHAI reconnect UX.
    conn: {
      online: true,          // last poll succeeded
      offlineSince: null,    // epoch ms of the first consecutive failure
      attempt: 0,            // consecutive failed attempts
      nextRetryIn: null,     // seconds until the next automatic attempt
      lastError: '',
      detailsOpen: false,
      dismissed: false,      // banner hidden by the user until reconnect
      checks: {              // per-component probe results for the modal
        web:    { label: 'Bridge API',   state: 'ok', detail: '' },
        poller: { label: 'Device poller', state: 'ok', detail: '' },
        agate:  { label: 'aGate :9000',  state: 'ok', detail: '' },
      },
    },
    _retryTimer: null,
    //: Backoff schedule in seconds; the last value repeats. Short at first so a
    //: container restart recovers quickly, then backs off to stay quiet.
    _retryBackoff: [2, 2, 5, 5, 10, 15, 30],

    // ── Power History (Chart.js) ───────────────────────────
    // Range menu aligned with the FranklinWH Modbus Bridge (Live … 30d).
    histRanges: ['live', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '18h', '24h', '3d', '5d', '7d', '30d'],
    histRange: '6h',
    // Aggregation resolution (matches the Modbus Bridge "Auto" dropdown). Auto = the backend
    // picks a per-span default; else an explicit bucket (raw = no aggregation).
    histBuckets: ['auto', 'raw', '1m', '5m', '15m', '30m', '1h'],
    histBucket: 'auto',
    _bucketSeconds: { auto: null, raw: 0, '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600 },
    histExpanded: false,
    histLoading: false,
    histCustomOpen: false,          // custom "Range…" picker (matches the Modbus Bridge)
    histCustomStart: '',
    histCustomEnd: '',
    _chart: null,

    histRangeLabel(r) {
      if (r === 'live') return 'Live';
      if (r === 'custom') return 'Custom';
      return r;
    },

    histBucketLabel(b) { return b === 'auto' ? 'Auto' : b === 'raw' ? 'Raw' : b; },

    // `&bucket=` query fragment for the current resolution ('' when Auto → backend default).
    _bucketQuery() {
      const s = this._bucketSeconds[this.histBucket];
      return (s === null || s === undefined) ? '' : '&bucket=' + s;
    },

    // Change resolution and re-load the current range (or custom window).
    setBucket(b) {
      this.histBucket = b;
      if (this.histRange === 'custom') this.applyCustomRange();
      else this.loadHistory(this.histRange);
    },

    _dtLocal(d) {
      const p = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
    },

    // Open the custom-range form, seeding sensible defaults (last 24h) if empty.
    openCustomRange() {
      if (!this.histCustomStart || !this.histCustomEnd) {
        const now = new Date();
        this.histCustomStart = this._dtLocal(new Date(now.getTime() - 86400000));
        this.histCustomEnd = this._dtLocal(now);
      }
      this.histCustomOpen = true;
    },

    // Apply an explicit start/end window (bucketed to ~300 points by the backend).
    async applyCustomRange() {
      if (!this.histCustomStart || !this.histCustomEnd) return;
      const start = Math.floor(new Date(this.histCustomStart).getTime() / 1000);
      const end = Math.floor(new Date(this.histCustomEnd).getTime() / 1000);
      if (!(end > start)) { this.toast('End must be after start', 'error'); return; }
      this.histRange = 'custom';
      this.histCustomOpen = false;
      this.histLoading = true;
      try {
        const serial = this.gwSerial();
        const gwq = serial ? '&gateway=' + encodeURIComponent(serial) : '';
        // Explicit bucket if chosen; else ~300 points across the custom window.
        const bq = this.histBucket === 'auto' ? '&points=300' : this._bucketQuery();
        const r = await fetch(`api/metrics?start=${start}&end=${end}${bq}${gwq}`);
        const d = await r.json();
        this.renderChart(d.series || []);
      } catch (e) {
        console.warn('[Bridge] custom range load failed:', e.message);
      } finally {
        this.histLoading = false;
      }
    },
    _histInterval: null,
    _hidden: false,   // browser tab backgrounded (visibilitychange) — pause heavy work
    _gwInterval: null,
    _lastSeries: [],                 // last-loaded series (for client-side CSV export)

    // ── Display units (client-side only; localStorage, no server round-trip) ─
    powerUnit: localStorage.getItem('fwh-power-unit') || 'W',   // 'W' | 'kW'
    tempUnit: localStorage.getItem('fwh-temp-unit') || 'C',     // 'C' | 'F' | 'both'
    showRawKeys: localStorage.getItem('fwh-show-keys') === '1', // show raw key/cmdType by labels
    siteTzOffsetMin: null,   // aGate-local UTC offset (min) for time axes; null = fall back to browser tz
    siteTzLabel: '',
    hostTzOffsetMin: null,   // integration-host UTC offset (min) for system-of-record times
    hostTzLabel: '',

    // ── Live Points (on-demand raw power_flow; NOT auto-polled) ─────────────
    livePoints: null,
    livePointsOpen: false,
    livePointsLoading: false,

    // ── Field-schema + command catalog (loaded once; label/group raw fields) ─
    // Shared by the Device tab and Live Points so their labelling can't drift.
    fieldSchema: {},   // raw_key -> { label, group, unit }
    catalog: {},       // cmd name -> { description, cmd, write }

    // ── Lifecycle ──────────────────────────────────────────
    init() {
      document.documentElement.setAttribute('data-theme', this.theme);
      this._loadDisclaimer();   // first-connection legal-disclaimer modal (once per browser)
      if (this.accent) this.setAccent(this.accent);   // restore custom accent
      // A live polling UI WILL hit transient network failures (a bridge restart, flaky aGate
      // wifi). Those reject background fetches; without a handler each becomes a red
      // "Unhandled Promise Rejection: [object Object]" flood in the console. De-noise
      // NETWORK rejections only (log once, concisely) — real programming errors fall through
      // and still surface. See DEF-BROWSER-MEMORY / console-noise.
      if (!window._fwhRejHandler) {
        window._fwhRejHandler = true;
        window.addEventListener('unhandledrejection', (ev) => {
          const r = ev.reason;
          const msg = String((r && (r.message || r)) || '');
          if (/load failed|failed to fetch|networkerror|could not connect|network connection was lost|the request timed out/i.test(msg)) {
            console.warn('[Bridge] background request failed (transient network):', msg);
            ev.preventDefault();   // expected blip — don't treat as a fatal unhandled error
          }
        });
      }
      this._loadLiveCaps();
      this._loadDashCards();
      this._loadAdvancedTools();
      this._loadTopbarPrefs();
      this._loadNavPrefs();
      this.initSidebar();
      // Static labelling metadata — fetch once (no device I/O, cheap, cached).
      this.loadFieldSchema();
      this.loadCatalog();
      this.loadReserveProvider();   // is reserve editable? (cloud provider present)
      // Roster is on the same slow cadence as history — load once, then refresh slowly.
      this.loadGateways();
      this._loadGeneratorInstalled();
      this.poll();
      this._dashStartedAt = Date.now();
      this._interval = setInterval(() => this._dashTick(), 10000);
      // History is heavier than the 5s poll — load once, then refresh slowly.
      this.loadSiteTz();
      this.loadHostTz();
      this.loadHistory(this.histRange);
      // Only refresh the Power History chart while the dashboard is visible — recreating it
      // on a hidden canvas every 60s is pure churn (DEF-BROWSER-MEMORY).
      this._histInterval = setInterval(() => { if (this.activeTab === 'dashboard' && !this._hidden) this.loadHistory(this.histRange); }, 90000);
      this._gwInterval = setInterval(() => { if (!this._hidden) this.loadGateways(); }, 120000);
      this.pollBattery();
      this._batInterval = setInterval(() => { if (!this._hidden) this.pollBattery(); }, 15000);
      // Pause polling + free the Power History canvas while the browser tab is BACKGROUNDED —
      // Safari reloads hidden tabs holding 'significant memory' (DEF-BROWSER-MEMORY). Resume +
      // refresh on return. Respects the dashboard idle-cap (don't auto-resume a capped session).
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
          this._hidden = true;
          this._pausePoll();
          if (this._chart) { this._chart.destroy(); this._chart = null; }
        } else {
          this._hidden = false;
          if (!this.dashCapped) { this._resumePoll(); this.poll(); }
          if (this.activeTab === 'dashboard') this.loadHistory(this.histRange);
          if (this.activeTab === 'battery') this.pollBattery();
        }
      });
      this.checkBuild();                                   // record the token now
      this._buildInterval = setInterval(() => this.checkBuild(), 60000);
    },

    // ── Multi-gateway ──────────────────────────────────────
    async loadGateways() {
      try {
        const r = await fetch('api/gateways');
        if (!r.ok) return;
        const list = await r.json();
        this.gateways = Array.isArray(list) ? list : [];
        // '__site__' (the aggregate) is a valid selection alongside the real gateway ids.
        const ids = this.gateways.map(g => g.id).concat(this.gateways.length > 1 ? ['__site__'] : []);
        // Restore the last-picked gateway across reloads; else the first.
        if (!this.selectedGateway || !ids.includes(this.selectedGateway)) {
          const saved = localStorage.getItem('fwh-gateway');
          this.selectedGateway = ids.includes(saved) ? saved : (this.gateways.length ? this.gateways[0].id : '');
        }
      } catch (e) {
        console.warn('[Bridge] gateways load failed:', e.message);
      }
    },

    //: Detect whether the selected gateway has a generator (per-gateway). Cheap 1901 read.
    async _loadGeneratorInstalled() {
      try {
        const r = await (await fetch('api/generator' + this.gwQuery())).json();
        this.generatorInstalled = !!(r && r.installed);
      } catch (e) { this.generatorInstalled = false; }
      // If we're sitting on a now-hidden Generator tab (no genset), fall back to the dashboard.
      if (!this.generatorInstalled && this.activeTab === 'generator') this.setActiveTab('dashboard');
    },
    selectGateway(id) {
      this.selectedGateway = id;
      try { localStorage.setItem('fwh-gateway', id); } catch { /* private mode */ }
      this.poll();
      this._loadGeneratorInstalled();   // generator presence is per-gateway
      this.loadHistory(this.histRange);   // history is scoped per-gateway (by serial)
    },

    // Query-string fragment that scopes a device call to the SELECTED gateway — only
    // when there's more than one gateway and one is selected. Single-gateway returns ''
    // so no ?gateway is sent and behaviour is identical to today. ``sep`` is '?' when it
    // starts the query string, '&' when appended after an existing param.
    gwQuery(sep = '?') {
      // Site-aggregate mode is not a single gateway — don't scope per-gateway calls to it.
      return (this.gateways.length > 1 && this.selectedGateway && this.selectedGateway !== '__site__')
        ? `${sep}gateway=${encodeURIComponent(this.selectedGateway)}`
        : '';
    },
    get siteMode() { return this.selectedGateway === '__site__'; },

    // The selected gateway's serial (metrics are tagged by serial, not id). '' when
    // single-gateway or unknown → no history filter (includes legacy untagged rows).
    gwSerial() {
      if (this.gateways.length <= 1) return '';
      const g = this.gateways.find(x => x.id === this.selectedGateway);
      return (g && g.serial) || '';
    },
    // Selected gateway's model (e.g. "aGate X-01-AU" from devicedb / SyHdVersion) + country.
    get gwModel() {
      const g = this.gateways.find(x => x.id === this.selectedGateway) || this.gateways[0];
      if (!g) return '';
      return (g.model && g.model !== 'aGate') ? g.model : (g.model || '');
    },
    get gwModelCountry() {
      const g = this.gateways.find(x => x.id === this.selectedGateway) || this.gateways[0];
      return (g && g.model_country) || '';
    },

    /** Poll the battery force state so the topbar can show a global Release. Cheap
     *  (in-memory active + cached availability). */
    async pollBattery() {
      try {
        const d = await (await fetch('api/battery/command')).json();
        this.batteryActive = d.active || 'Not Active';
        this.batteryRemaining = d.remaining_s ?? null;
      } catch (e) { /* leave last value */ }
    },
    /** Global emergency release of any active force dispatch. */
    async releaseBattery() {
      if (!await this.confirmDialog(
            `Release the active battery force (${this.batteryActive}) and return to normal operation?`,
            { title: 'Release force dispatch', danger: true })) return;
      try {
        const r = await fetch('api/battery/command', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ slug: 'battery_command', value: 'Release' }) });
        const d = await r.json();
        if (r.ok && d.ok) { this.batteryActive = 'Not Active'; this.batteryRemaining = null; this.toast('Battery released', 'success'); }
        else this.toast('Release failed: ' + (d.result || d.detail || r.status), 'error');
      } catch (e) { this.toast('Release failed: ' + e.message, 'error'); }
      this.pollBattery();
    },

    async poll() {
      try {
        if (this.siteMode) { await this._pollSite(); return; }
        // Multi-gateway: fetch the selected gateway's summary. Single-gateway keeps the
        // exact existing /api/summary path (unchanged behaviour).
        const url = (this.gateways.length > 1 && this.selectedGateway)
          ? `api/gateways/${encodeURIComponent(this.selectedGateway)}/summary`
          : 'api/summary';
        const r = await fetch(url);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        // Keep last-good mode/power if a (transient) response lacks them, so the
        // operating-mode section + cards never blank between polls (no flicker).
        const prev = this.summary || {};
        if (!(d.mode && d.mode.modes && d.mode.modes.length) && prev.mode) d.mode = prev.mode;
        if (!(d.power && Object.keys(d.power).length) && prev.power) d.power = prev.power;
        this.summary = d;
        this._noteConnOk(d);
      } catch (e) {
        // Keep the last known summary on error — don't blank the UI — but do say so.
        console.warn('[Bridge] poll failed:', e.message);
        this._noteConnFail(e);
      }
    },

    //: Site-aggregate summary — sums power across all OK gateways (/api/site/status) and
    //  averages SoC, mapped into the same summary/power shape the shell reads. Per-unit
    //  cards (battery modules, energy today) are left empty since they don't aggregate.
    async _pollSite() {
      try {
        const r = await fetch('api/site/status');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        const okGws = (d.gateways || []).filter(g => g.ok);
        const socs = okGws.map(g => g.soc).filter(v => typeof v === 'number');
        const avgSoc = socs.length ? Math.round(socs.reduce((a, b) => a + b, 0) / socs.length) : null;
        const anyVpp = okGws.some(g => g.vpp_kind === 'vpp');
        const anyForce = okGws.some(g => g.vpp);
        this.summary = {
          ok: (d.ok_count || 0) > 0, site: true, count: d.count, ok_count: d.ok_count,
          power: {
            ...(d.totals || {}), soc: avgSoc, mode: 'Site',
            off_grid: okGws.some(g => g.off_grid),
            vpp: anyVpp || anyForce, vpp_kind: anyVpp ? 'vpp' : (anyForce ? 'force' : null),
          },
          battery: {}, energy_today: {},
          capabilities: (this.summary && this.summary.capabilities) || {},
        };
        this._noteConnOk(this.summary);
      } catch (e) {
        console.warn('[Bridge] site poll failed:', e.message);
        this._noteConnFail(e);
      }
    },

    // ── Connection tracking ────────────────────────────────
    _noteConnOk(summary) {
      const wasOffline = !this.conn.online;
      this.conn.online = true;
      this.conn.attempt = 0;
      this.conn.offlineSince = null;
      this.conn.nextRetryIn = null;
      this.conn.lastError = '';
      this.conn.dismissed = false;     // a fresh outage should show again
      this.conn.checks.web = { label: 'Bridge API', state: 'ok', detail: 'responding' };
      // The bridge answered, so distinguish "bridge up, device down" from a full outage.
      const deviceOk = summary && summary.ok === true;
      this.conn.checks.agate = {
        label: 'aGate :9000',
        state: deviceOk ? 'ok' : 'fail',
        detail: deviceOk ? `${summary.latency_ms ?? '?'} ms`
                         : (summary && summary.error) || 'not responding',
      };
      this.conn.checks.poller = {
        label: 'Device poller',
        state: summary && summary.stale ? 'warn' : 'ok',
        detail: summary && summary.stale ? 'serving stale data' : 'fresh',
      };
      if (wasOffline) {
        this._clearRetry();
        this._resumePoll();
        this.toast('Reconnected to the bridge', 'success');
      }
    },

    _pausePoll() {
      if (this._interval) { clearInterval(this._interval); this._interval = null; }
    },

    _resumePoll() {
      if (!this._interval) this._interval = setInterval(() => this._dashTick(), 10000);
    },

    _noteConnFail(err) {
      if (this.conn.online) {
        this.conn.online = false;
        this.conn.offlineSince = Date.now();
        this.conn.attempt = 0;
        // Hand pacing to the backoff timer. Leaving the 5s loop running would
        // double-poll alongside it, inflate the attempt count, and make the
        // "next retry in Ns" countdown a lie.
        this._pausePoll();
      }
      this.conn.attempt += 1;
      this.conn.lastError = (err && err.message) || String(err);
      // The bridge itself is unreachable, so nothing behind it can be assessed.
      this.conn.checks.web = { label: 'Bridge API', state: 'fail', detail: this.conn.lastError };
      this.conn.checks.poller = { label: 'Device poller', state: 'unknown', detail: 'waiting…' };
      this.conn.checks.agate = { label: 'aGate :9000', state: 'unknown', detail: 'waiting…' };
      this._scheduleRetry();
    },

    _retryDelay() {
      const b = this._retryBackoff;
      return b[Math.min(this.conn.attempt - 1, b.length - 1)] ?? b[b.length - 1];
    },

    _scheduleRetry() {
      this._clearRetry();
      this.conn.nextRetryIn = this._retryDelay();
      // Tick the countdown every second so the modal shows real progress rather
      // than a static number.
      this._retryTimer = setInterval(() => {
        if (this.conn.nextRetryIn > 0) this.conn.nextRetryIn -= 1;
        if (this.conn.nextRetryIn <= 0) { this._clearRetry(); this.poll(); }
      }, 1000);
    },

    _clearRetry() {
      if (this._retryTimer) { clearInterval(this._retryTimer); this._retryTimer = null; }
    },

    retryNow() {
      this._clearRetry();
      this.conn.nextRetryIn = 0;
      this.poll();
    },

    dismissConnBanner() {
      this.conn.dismissed = true;
      this.conn.detailsOpen = false;
    },

    get connOfflineFor() {
      if (!this.conn.offlineSince) return '';
      const s = Math.max(0, Math.round((Date.now() - this.conn.offlineSince) / 1000));
      if (s < 60) return `${s}s`;
      const m = Math.floor(s / 60);
      return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
    },

    get connOfflineSinceLabel() {
      if (!this.conn.offlineSince) return '';       // bridge observation — HOST zone
      return this._fmtHostTime(this.conn.offlineSince / 1000, { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true });
    },

    // ── Getters ────────────────────────────────────────────
    get isOnline() {
      return this.summary && this.summary.ok === true;
    },
    get power() {
      return this.summary.power || {};
    },
    get socPct() {
      // Round at the source: the gateway reports SoC to six decimals
      // (e.g. 99.789474), which is noise on a percentage.
      const v = this.power.soc;
      return (v === null || v === undefined) ? null : Math.round(v * 10) / 10;
    },
    get ringOffset() {
      const soc = this.socPct;
      if (soc == null) return 251.3;
      const pct = Math.min(100, Math.max(0, soc)) / 100;
      return 251.3 * (1 - pct);
    },
    get chargeState() {
      // The battery DIRECTION (Charging / Discharging / Standby) from the run_status enum;
      // falls back to the battery_w power-sign heuristic when no run_status is reported.
      // VPP is shown separately (its own badge + the run-status line) so both read together,
      // exactly like the official app: "Discharging" + "VPP Mode".
      const d = this.power.run_status_desc;
      if (d) return d;
      const w = this.power.battery_w;
      if (w == null) return 'Unknown';
      if (w < 0) return 'Charging';
      if (w > 0) return 'Discharging';
      return 'Idle';
    },
    //: Operating-status label for the dashboard SoC card's "Run status". A dispatch wins over
    //  the plain direction: cloud VPP shows its mode label (+ programme), an unattributed force
    //  shows "Force dispatch". The backend sets vpp_label from the authoritative source.
    get runStatusLabel() {
      if (this.power.vpp_label) {
        return this.isVpp && this.vppProgramme
          ? `${this.power.vpp_label} · ${this.vppProgramme}` : this.power.vpp_label;
      }
      return this.battery.run_status_desc || this.power.run_status_desc
             || (this.power.run_status ?? '--');
    },
    //: run_status 5/6/7 — the aGate has islanded (disconnected from the grid, running on
    //  battery). Surfaced as a prominent top-nav badge and drives the on/off-grid button.
    get isOffGrid() {
      return this.power.off_grid === true || [5, 6, 7].includes(this.power.run_status);
    },
    //: A dispatch is holding the battery — either a cloud-confirmed VPP or an unattributed
    //  FORCE (Modbus M704 WSet: cloud VPP / Modbus bridge / app / our own force_charge).
    get isForced() {
      return this.power.vpp === true || this.power.run_status === 9;
    },
    //: Cloud-CONFIRMED VPP (getDeviceCompositeInfo run_status/tou_mode==9). Only the Cloud API
    //  can tell a genuine VPP from a local force; without it we only claim FORCE.
    get isVpp() {
      return this.power.vpp_kind === 'vpp';
    },
    //: Enrolled VPP programme / partner name (e.g. "Virtual Peakers (Ausgrid)"), when known.
    get vppProgramme() {
      return this.power.vpp_programme || '';
    },

    // ── Subsystem capabilities (which controls need Modbus vs Cloud, and are they usable) ──
    get caps() { return this.summary.capabilities || {}; },
    get modbusEnabled() { return !!this.caps.modbus_enabled; },
    get modbusReachable() { return !!this.caps.modbus_reachable; },
    get cloudConfigured() { return !!this.caps.cloud_configured; },
    get cloudAvailable() { return !!this.caps.cloud_available; },
    //: Marker state for a "needs Modbus / needs Cloud" pill. Returns {ok, hint} — ok=true when
    //  the subsystem is configured/enabled/reachable, else a hint on how to enable it.
    capState(kind) {
      if (kind === 'modbus') {
        if (!this.modbusEnabled) return { ok: false, hint: 'Enable the Modbus path on the Control tab' };
        if (!this.modbusReachable) return { ok: false, hint: 'Modbus port 502 is not reachable on this gateway' };
        return { ok: true, hint: 'Uses the Modbus (SunSpec 502) path' };
      }
      if (!this.cloudConfigured) return { ok: false, hint: 'Add FranklinWH Cloud credentials in Settings' };
      if (!this.cloudAvailable) return { ok: false, hint: 'FranklinWH Cloud sign-in is unavailable (check credentials)' };
      return { ok: true, hint: 'Uses the FranklinWH Cloud API' };
    },
    //: Semantic class for the charge-direction chip. Off-grid / VPP have their own
    //  dedicated badges, so this stays a simple charge/discharge colour.
    get chargeStateClass() {
      const s = this.chargeState;
      if (s === 'Charging') return 'ok';
      if (s === 'Discharging') return 'warn';
      return 'muted';
    },
    get activeMode() {
      return this.power.mode || '--';
    },
    get modes() {
      return (this.summary.mode && this.summary.mode.modes) || [];
    },
    //: Mode display-name -> set_mode alias (self/tou/backup).
    //: Radial tick on the SoC ring at the ACTIVE mode's reserved SoC (SVG is CSS-rotated -90deg,
    //  so 0deg here = 3 o'clock and the fill/tick share the same origin). Null when unknown.
    //: The reserved arc, 0 -> reserve, drawn under the fill. A 5% reserve as a bare
    //: tick sits within a few degrees of where the track meets the fill and reads as a
    //: rendering seam; as a shaded band it reads as the floor the charge sits above.
    get socReserveArc() {
      const m = this.modes.find(x => x.active);
      const r = (m && m.reserved_soc != null) ? Number(m.reserved_soc) : null;
      if (r == null || isNaN(r) || r <= 0) return null;
      const C = 251.3;                                  // 2*pi*40, matches the fill
      const pct = Math.max(0, Math.min(100, r));
      return { dash: (pct / 100) * C, gap: C, pct };
    },
    get socReserveTick() {
      const m = this.modes.find(x => x.active);
      const r = (m && m.reserved_soc != null) ? Number(m.reserved_soc) : null;
      if (r == null || isNaN(r)) return null;
      const t = Math.max(0, Math.min(100, r)) / 100 * 2 * Math.PI;
      const c = Math.cos(t), s = Math.sin(t);
      return { x1: 50 + 33 * c, y1: 50 + 33 * s, x2: 50 + 47 * c, y2: 50 + 47 * s, pct: r };
    },
    modeAlias(name) {
      const n = (name || '').toLowerCase();
      if (n.includes('time') || n.includes('tou')) return 'tou';
      if (n.includes('backup') || n.includes('emergency')) return 'backup';
      return 'self';
    },
    get battery() {
      return this.summary.battery || {};
    },
    get energyToday() {
      return this.summary.energy_today || {};
    },

    // ── Unit formatters (display-only) ─────────────────────
    // Power in raw watts → 'W' or 'kW' per the user's preference.
    fmtPower(watts) {
      if (watts == null) return '--';
      if (this.powerUnit === 'kW') return `${(watts / 1000).toFixed(2)} kW`;
      return `${Math.round(watts).toLocaleString()} W`;
    },
    // Module power arrives already in kW (fhpPower) — render consistently with powerUnit.
    fmtPowerKw(kw) {
      if (kw == null) return '--';
      if (this.powerUnit === 'W') return `${Math.round(kw * 1000).toLocaleString()} W`;
      return `${Number(kw).toFixed(2)} kW`;
    },
    // Ambient temp in °C → °C / °F / both.
    fmtTemp(c) {
      if (c == null) return '--';
      const cs = `${Number(c).toFixed(1)} °C`;
      const fs = `${(Number(c) * 9 / 5 + 32).toFixed(1)} °F`;
      if (this.tempUnit === 'F') return fs;
      if (this.tempUnit === 'both') return `${cs} / ${fs}`;
      return cs;
    },
    fmtKwh(v) {
      return v == null ? '--' : `${Number(v).toFixed(2)}`;
    },

    // ── Field-schema helpers (ONE place — Device tab + Live Points share these) ─
    async loadFieldSchema() {
      try {
        const r = await fetch('api/schema');
        if (r.ok) this.fieldSchema = await r.json();
      } catch (e) { console.warn('[Bridge] schema load failed:', e.message); }
    },
    async loadCatalog() {
      try {
        const r = await fetch('api/catalog');
        if (r.ok) this.catalog = await r.json();
      } catch (e) { console.warn('[Bridge] catalog load failed:', e.message); }
    },
    // Base key = raw key with a trailing array index stripped (pro_load_pwr[0] → pro_load_pwr).
    _baseKey(key) { return String(key).replace(/\[[^\]]*\]$/, ''); },
    // Human label for a raw field key — schema label, else the raw key itself.
    fieldLabel(key) {
      const e = this.fieldSchema[this._baseKey(key)];
      return (e && e.label) || key;
    },
    // Display group for a raw field key — schema group, else 'Other'.
    fieldGroup(key) {
      const e = this.fieldSchema[this._baseKey(key)];
      return (e && e.group) || 'Other';
    },
    // Unit-aware value formatting. The schema `unit` is the CLOUD scale; LOCAL power_flow
    // (1301) values differ (watts vs kW), so we classify by field TYPE, not by schema unit:
    //   p_uti/p_sun/p_gen/p_fhp/p_load → watts → fmtPower (respects W/kW pref)
    //   fhpPower → already kW → fmtPowerKw ·  kwh* → fmtKwh ·  t_amb → fmtTemp
    //   soc/fhpSoc/signal → %  ·  main_sw/pro_load/*Relay* → 0/1 state  ·  else → raw
    fmtField(key, value) {
      if (value === null || value === undefined) return '--';
      const base = this._baseKey(key);
      const low = base.toLowerCase();
      // Enum decode: "1 · Charging" when the schema entry carries an enum map and the
      // (scalar) value is a known code. Keeps the raw field consistent with the topbar.
      const entry = this.fieldSchema[base];
      if (entry && entry.enum && !Array.isArray(value)) {
        const desc = entry.enum[value];
        if (desc != null) return `${value} · ${desc}`;
      }
      const arr = (v, f) => Array.isArray(v) ? v.map(f).join(', ') : f(v);
      const WATTS = ['p_uti', 'p_sun', 'p_gen', 'p_fhp', 'p_load'];
      if (WATTS.includes(base))                       return this.fmtPower(value);
      if (base === 'fhpPower')                         return arr(value, (v) => this.fmtPowerKw(v));
      if (low.startsWith('kwh'))                       return arr(value, (v) => this.fmtKwh(v));
      if (base === 't_amb')                            return this.fmtTemp(value);
      if (['soc', 'fhpSoc', 'signal', 'wifiSignal'].includes(base))
        return arr(value, (v) => (v == null ? '--' : `${Math.round(v)}%`));
      if (base === 'main_sw' || base === 'pro_load' || /relay/i.test(base))
        return arr(value, (v) => String(v));   // 0/1 relay / state — raw with no scaling
      if (Array.isArray(value)) return `[${value.join(', ')}]`;
      if (typeof value === 'object') return JSON.stringify(value);
      return String(value);
    },

    // Per-index schema metadata: the specific entry for `base[i]` (main_sw[0] →
    // "Grid relay1"), else a generic "<base label> [i]" derived from the base key.
    describeIndexed(base, i) {
      const hit = this.fieldSchema[`${base}[${i}]`];
      if (hit) return hit;
      const b = this.fieldSchema[base] || {};
      return { label: `${b.label || base} [${i}]`, group: b.group || 'Other', unit: b.unit || '' };
    },

    // Break-out arrays: relays / smart-circuit switches / per-pack values render as ONE
    // ROW PER ELEMENT (main_sw → Grid relay1 / Generator relay / Solar relay1). Other
    // arrays (TOU buckets sharp/peak/flat/valley) stay a single labelled row.
    _PER_INDEX: ['main_sw', 'pro_load', 'pro_load_pwr', 'fhpSn', 'fhpSoc', 'fhpPower', 'bms_work',
                 'doStatus', 'diStatus'],

    // Expand one raw {key: value} into render rows: [{ key, label, group, value }].
    // Shared by BOTH Live Points and the Device tab so labelling can't drift.
    expandRows(key, value) {
      const base = this._baseKey(key);
      if (Array.isArray(value) && this._PER_INDEX.includes(base)) {
        return value.map((el, i) => {
          const d = this.describeIndexed(base, i);
          return { key: `${base}[${i}]`, label: d.label, group: d.group,
                   value: this.fmtField(`${base}[${i}]`, el) };
        });
      }
      return [{ key, label: this.fieldLabel(key), group: this.fieldGroup(key),
                value: this.fmtField(key, value) }];
    },

    setPowerUnit(u) {
      this.powerUnit = u;
      localStorage.setItem('fwh-power-unit', u);
      this.renderChart(this._lastSeries);   // re-scale the Y-axis + tooltips live
    },
    setTempUnit(u) {
      this.tempUnit = u;
      localStorage.setItem('fwh-temp-unit', u);
    },
    // Show the raw API key / cmdType next to field labels (Modbus-Bridge '</>' style).
    toggleRawKeys() {
      this.showRawKeys = !this.showRawKeys;
      localStorage.setItem('fwh-show-keys', this.showRawKeys ? '1' : '0');
    },
    // Source annotation shown next to a dashboard value when </> is on: "rawkey · cmdType".
    // Most dashboard values come from power_flow (1301); modes from mode_list (1726).
    srcTag(key, cmd) { return cmd ? `${key} · ${cmd}` : key; },
    // Run-status colour for the Battery card (0 Standby / 1 Charging / 2 Discharging).
    runStatusColour() {
      const rs = this.battery.run_status;
      if (rs === 1) return 'var(--ok)';
      if (rs === 2) return 'var(--warn)';
      return 'var(--text-muted)';
    },

    // ── Live Points (on-demand raw power_flow) ─────────────
    async toggleLivePoints() {
      this.livePointsOpen = !this.livePointsOpen;
      if (this.livePointsOpen && !this.livePoints) await this.loadLivePoints();
    },
    // On-demand ONLY (Live Points expand + Refresh). Merges THREE gateway-scoped reads —
    // power_flow (1301) + solar_pv (1903) + relay_status (1709) — so the panel shows all
    // relays and both PV ports even at 0. Merge order: power_flow first, then solar_pv,
    // then relay_status (never overwrite a present key). solar_pv/relay_status are
    // best-effort — if they fail (flaky) the panel still renders power_flow. Never added
    // to the cached /api/summary poll.
    async loadLivePoints() {
      this.livePointsLoading = true;
      const skip = new Set(['opt', 'result', 'reason']);
      const merged = {};
      const mergeIn = (obj) => {
        if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return;
        for (const [k, v] of Object.entries(obj)) {
          if (skip.has(k) || (k in merged)) continue;
          merged[k] = v;
        }
      };
      try {
        const r = await fetch('api/cmd/power_flow' + this.gwQuery('?'));
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        mergeIn(await r.json());
      } catch (e) {
        this.toast(`Live Points load failed: ${e.message}`, 'error');
        this.livePointsLoading = false;
        return;   // no power_flow → nothing to show
      }
      // Extended relays + PV ports live in other cmdTypes — best-effort, graceful degrade.
      for (const extra of ['solar_pv', 'relay_status']) {
        try {
          const r = await fetch('api/cmd/' + extra + this.gwQuery('?'));
          if (r.ok) mergeIn(await r.json());
        } catch (e) {
          console.warn(`[Bridge] Live Points ${extra} read failed:`, e.message);
        }
      }
      this.livePoints = merged;
      this.livePointsLoading = false;
    },
    get livePointRows() {
      const d = this.livePoints || {};
      const skip = new Set(['opt', 'result', 'reason']);
      // Same labelling/formatting as the Device tab (shared expandRows/fmtField). Array
      // fields (relays/switches/packs) break out into one row per element.
      const rows = [];
      for (const [k, v] of Object.entries(d)) {
        if (skip.has(k)) continue;
        for (const r of this.expandRows(k, v)) rows.push({ k: r.key, label: r.label, group: r.group, v: r.value });
      }
      return rows;
    },
    // Live Points grouped by schema group (mirrors the Device tab render). 'Other' last.
    get livePointGroups() {
      const groups = {};
      for (const row of this.livePointRows) (groups[row.group] ||= []).push(row);
      return Object.keys(groups)
        .sort((a, b) => (a === 'Other') - (b === 'Other') || a.localeCompare(b))
        .map((title) => ({ title, rows: groups[title] }));
    },
    get livePointCount() {
      return this.livePointRows.length;
    },

    // ── UI actions ─────────────────────────────────────────
    setTheme(mode) {
      this.theme = mode === 'light' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', this.theme);
      localStorage.setItem('fwh-theme', this.theme);
    },

    // The topbar icon and the terminal chip are shortcuts for the same preference
    // that Settings -> Display owns; all three go through setTheme.
    toggleTheme() { this.setTheme(this.theme === 'dark' ? 'light' : 'dark') },

    setActiveTab(name) {
      const leaving = this.activeTab === 'dashboard' && name !== 'dashboard';
      const entering = this.activeTab !== 'dashboard' && name === 'dashboard';
      this.activeTab = name;
      this.moreOpen = false;
      localStorage.setItem('fwh-tab', name);
      // Free the Power History canvas while the dashboard is hidden; rebuild on return.
      if (leaving && this._chart) { this._chart.destroy(); this._chart = null; }
      if (entering) setTimeout(() => this.loadHistory(this.histRange), 0);
    },

    // ── Control writes ─────────────────────────────────────
    modeMenuOpen: false,
    gwMenuOpen: false,  // styled gateway selector dropdown
    get selectedGatewayLabel() { if (this.siteMode) return 'Site · All Gateways'; const g = (this.gateways || []).find(x => x.id === this.selectedGateway); return g ? (g.label || g.host) : 'Gateway'; },
    get modeChoices() {
      const active = this.activeMode;
      return [
        { alias: 'self',   label: 'Self-Consumption' },
        { alias: 'tou',    label: 'Time-of-Use' },
        { alias: 'backup', label: 'Emergency Backup' },
      ].map(m => ({ ...m, active: m.label === active }));
    },

    async setMode(alias) {
      const labels = { self: 'Self-Consumption', tou: 'Time-of-Use', backup: 'Emergency Backup' };
      if (!await this.confirmDialog(`Switch operating mode to ${labels[alias] || alias}?`,
                                    { title: 'Switch mode' })) return;
      try {
        const r = await fetch('api/mode' + this.gwQuery('?'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: alias, confirm: true }),  // dialog above IS the confirm
        });
        if (r.status === 428) { this.toast('Confirmation required for this action', 'error'); return; }
        const d = await r.json();
        if (r.ok && d.ok) {
          this.toast(`Mode set to ${labels[alias] || alias}`, 'info');
        } else {
          this.toast(`Mode change failed: ${d.detail || d.result || 'error'}`, 'error');
        }
      } catch (e) {
        this.toast(`Mode change error: ${e.message}`, 'error');
      }
      this.poll();
    },

    //: Restore/reserve SoC floor to hold while islanded (settable on the Control tab).
    offgridSoc: 5,

    async setOffgrid(on) {
      const soc = Math.max(0, Math.min(100, Number(this.offgridSoc) || 0));
      // Explicit consequences — off-grid is destructive; be unambiguous about what happens.
      const warn = on
        ? `Disconnect from the grid and run the home entirely on battery.\n\n`
          + `• Grid power is cut until you reconnect.\n`
          + `• The battery drains under load and will hold no lower than the ${soc}% restore floor.\n`
          + `• If the battery reaches the floor while off-grid, backed-up loads lose power.\n\n`
          + `Go off-grid now?`
        : `Reconnect to the grid and resume normal operation?`;
      if (!await this.confirmDialog(warn,
            { title: on ? 'Go off-grid' : 'Reconnect to grid', danger: on })) return;
      try {
        const r = await fetch('api/offgrid' + this.gwQuery('?'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ on, soc, confirm: true }),  // dialog above IS the confirm
        });
        if (r.status === 403) { this.toast('Control writes are disabled (read-only)', 'error'); return; }
        const d = await r.json();
        if (r.ok && d.ok) {
          this.toast(on ? `Going off-grid (restore floor ${soc}%)` : 'Reconnecting to grid', 'info');
        } else {
          this.toast(`Off-grid change failed: ${d.detail || d.result || 'error'}`, 'error');
        }
      } catch (e) {
        this.toast(`Off-grid error: ${e.message}`, 'error');
      }
      this.loadControlLog();
      this.poll();
    },

    // ── Modbus (SunSpec 502) master switch ──────────────────────────────────
    modbus: { enabled: true, available: true, reason: '', resolved_host: null, resolved_port: 502,
             unit_id: null, host_override: '', port_override: null, auto: true },
    modbusTest: null, modbusTesting: false,
    async loadModbus() {
      try {
        const d = await (await fetch('api/modbus')).json();
        this.modbus = { enabled: !!d.enabled, available: !!d.available, reason: d.reason || '',
                        resolved_host: d.resolved_host || null, resolved_port: d.resolved_port || 502,
                        unit_id: d.unit_id, host_override: d.host_override || '',
                        port_override: d.port_override || null, auto: !!d.auto };
      } catch (e) { /* leave defaults */ }
    },
    async toggleModbus() {
      const next = !this.modbus.enabled;
      try {
        const r = await fetch('api/modbus', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: next }),
        });
        const d = await r.json();
        this.modbus.enabled = !!d.enabled;
        this.toast(`Modbus ${d.enabled ? 'enabled' : 'disabled'}`, 'info');
        this.loadModbus();
        this.loadControlLog();
      } catch (e) { this.toast(`Modbus toggle failed: ${e.message}`, 'error'); }
    },

    async saveModbusOverride() {
      try {
        const r = await fetch('api/modbus', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ host_override: this.modbus.host_override || '',
                                 port_override: Number(this.modbus.port_override) || 0 }),
        });
        const d = await r.json();
        Object.assign(this.modbus, {
          resolved_host: d.resolved_host || null, resolved_port: d.resolved_port || 502,
          host_override: d.host_override || '', port_override: d.port_override || null,
          auto: !!d.auto });
        this.modbusTest = null;
        this.toast(d.auto ? 'Modbus host: auto (from gateway)' : `Modbus host set: ${d.resolved_host}:${d.resolved_port}`, 'info');
        this.loadControlLog();
      } catch (e) { this.toast(`Modbus host save failed: ${e.message}`, 'error'); }
    },
    async testModbus() {
      this.modbusTesting = true; this.modbusTest = null;
      try {
        this.modbusTest = await (await fetch('api/modbus/test', { method: 'POST' })).json();
      } catch (e) { this.modbusTest = { ok: false, reason: 'request failed' }; }
      finally { this.modbusTesting = false; }
    },

    // ── Control audit trail ─────────────────────────────────────────────────
    controlLog: [],
    async loadControlLog() {
      try {
        const d = await (await fetch('api/control-log?limit=50')).json();
        this.controlLog = (d && d.events) || [];
      } catch (e) { this.controlLog = []; }
    },
    controlActionLabel(a) {
      return ({
        go_off_grid: 'Go off-grid', reconnect_grid: 'Reconnect to grid',
        reboot_gateway: 'Reboot gateway', set_mode: 'Set operating mode',
        modbus_toggle: 'Modbus toggle', set_reserve: 'Set reserve SoC',
      })[a] || a;
    },
    fmtTime(ts) {                                   // control audit trail — HOST zone (system of record)
      if (!ts) return '';
      try { return this._fmtHostTime(ts); } catch (e) { return ''; }
    },

    //: Set by a link elsewhere in the UI; the Device tab picks it up and opens that
    //  reading. Keeps firmware (and anything else) documented in ONE place.
    deviceReadRequest: '',

    openDeviceRead(name) {
      this.deviceReadRequest = name;
      this.setActiveTab('device');
    },

    async rebootGateway() {
      const ok = await this.confirmDialog(
        'The gateway will restart and drop its connection for a minute or two. '
        + 'Battery control and monitoring stop until it comes back, and on some sites '
        + 'the restart triggers a switch to 4G.\n\nReboot the gateway?',
        { title: 'Reboot gateway', danger: true });
      if (!ok) return;
      try {
        const r = await fetch('api/reboot' + this.gwQuery('?'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirm: true }),
        });
        if (r.status === 403) { this.toast('Control writes are disabled (read-only)', 'error'); return; }
        const d = await r.json();
        // The gateway drops the link as it restarts, so a transport error here is the
        // expected outcome, not a failure — report the request, not a guessed result.
        this.toast(r.ok ? 'Reboot sent — the gateway will be offline for a minute or two'
                        : `Reboot failed: ${d.detail || 'error'}`,
                   r.ok ? 'info' : 'error');
      } catch (e) {
        this.toast('Reboot sent — the connection dropped, which is expected', 'info');
      }
    },

    // Reserve SoC is CLOUD-OWNED — the local API silently discards the write. Editable only
    // when a cloud reserve provider is configured (fetched from /api/providers).
    reserveEditable: false,
    async loadReserveProvider() {
      try {
        const r = await fetch('api/providers');
        const d = await r.json();
        this.reserveEditable = !!(d && d.reserve && d.reserve.available);
      } catch (e) { this.reserveEditable = false; }
    },
    // Structured reserve write for the modal lifecycle — NO confirm/toast. Returns
    // {ok, status, detail} so the caller can keep its modal open and render the
    // outcome (success / failure / timeout / retry). Bounded by a hard timeout so a
    // hung cloud never leaves the modal spinning forever.
    async applyReserve(mode, soc, timeoutMs = 30000) {
      const pct = parseInt(soc, 10);
      if (isNaN(pct) || pct < 0 || pct > 100) return { ok: false, status: 422, detail: 'Reserve must be 0–100%.' };
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      try {
        const r = await fetch('api/cloud/reserve' + this.gwQuery('?'), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode, soc: pct }), signal: ctrl.signal,
        });
        let d = {}; try { d = await r.json(); } catch (e) { /* non-JSON error body */ }
        if (r.status === 403) return { ok: false, status: 403, detail: 'Control writes are disabled (read-only).' };
        if (r.status === 503) return { ok: false, status: 503, detail: 'No cloud provider configured — set cloud credentials in Settings → Cloud.' };
        if (r.ok && d.ok) return { ok: true, status: r.status, detail: d.note || 'Applied via the FranklinWH cloud.', data: d };
        return { ok: false, status: r.status, detail: d.detail || d.error || `Cloud returned HTTP ${r.status}.` };
      } catch (e) {
        if (e.name === 'AbortError') return { ok: false, status: 0, detail: `Timed out after ${Math.round(timeoutMs / 1000)}s waiting for the cloud — it may still have applied; re-check in ~8s.` };
        return { ok: false, status: 0, detail: `Network error: ${e.message}` };
      } finally { clearTimeout(timer); }
    },
    // (setReserve removed — all reserve writes now go through applyReserve(), which the
    //  dashboard modal and the Control-tab editor both drive with a full saving/ok/error
    //  lifecycle + timeout. No fire-and-forget toast path remains.)

    // ── Power History ──────────────────────────────────────
    async loadHistory(range) {
      this.histRange = range;
      this.histLoading = true;               // show the "Loading…" pill until the chart repaints
      try {
        // Metrics rows are tagged by SERIAL — scope to the selected gateway's serial when
        // multi-gateway; single-gateway sends no filter (includes legacy untagged rows).
        const serial = this.gwSerial();
        const gwq = serial ? '&gateway=' + encodeURIComponent(serial) : '';
        const r = await fetch('api/metrics?range=' + range + gwq + this._bucketQuery());
        const d = await r.json();
        this.renderChart(d.series || []);
      } catch (e) {
        console.warn('[Bridge] history load failed:', e.message);
      } finally {
        this.histLoading = false;
      }
    },

    // Site timezone (from the aGate) so charts read in aGate-local time, not the browser's.
    async loadSiteTz() {
      try {
        const r = await (await fetch('api/site/timezone' + this.gwQuery('?'))).json();
        if (r && r.available && r.offset_minutes != null) {
          this.siteTzOffsetMin = r.offset_minutes;
          this.siteTzLabel = r.label + (r.tz_str ? ' \u00b7 ' + r.tz_str : '');
          if (this._lastSeries) this.renderChart(this._lastSeries);   // re-render with correct tz
        }
      } catch (e) { /* falls back to browser tz */ }
    },
    // Integration-host timezone (the bridge's own zone) for the SYSTEM OF RECORD — audit trail,
    // app logs, notification log, scheduler activity, offline-since. See docs/TIMEZONES.md.
    async loadHostTz() {
      try {
        const r = await (await fetch('api/host/timezone')).json();
        if (r && r.available && r.offset_minutes != null) {
          this.hostTzOffsetMin = r.offset_minutes;
          this.hostTzLabel = r.label + (r.tz_name ? ' \u00b7 ' + r.tz_name : '');
        }
      } catch (e) { /* falls back to browser tz */ }
    },
    // Format epoch-seconds ts in the HOST zone (shift epoch, render as UTC). opts = Intl options.
    _fmtHostTime(ts, opts) {
      if (ts == null || ts === '') return '';
      const o = opts || { year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true };
      if (this.hostTzOffsetMin == null) return new Date(ts * 1000).toLocaleString([], o);
      return new Date((ts + this.hostTzOffsetMin * 60) * 1000).toLocaleString('en-US', { ...o, timeZone: 'UTC' });
    },
    // Format an epoch-seconds ts as HH:MM:SS in the SITE tz (shift epoch, render as UTC).
    _fmtSiteTime(ts, opts) {
      if (ts == null || ts === '') return '';
      if (opts) {   // caller wants a full date/time (e.g. analytics axis) in the SITE zone
        if (this.siteTzOffsetMin == null) return new Date(ts * 1000).toLocaleString([], opts);
        return new Date((ts + this.siteTzOffsetMin * 60) * 1000).toLocaleString('en-US', { ...opts, timeZone: 'UTC' });
      }
      if (this.siteTzOffsetMin == null) return new Date(ts * 1000).toLocaleTimeString();
      const d = new Date((ts + this.siteTzOffsetMin * 60) * 1000);
      return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true, timeZone: 'UTC' });
    },
    renderChart(series) {
      series = series || [];
      this._lastSeries = series;                 // retain for CSV export / unit re-render
      const el = document.getElementById('histChart');
      if (!el || typeof Chart === 'undefined') return;
      // Category x-axis with formatted labels — no time scale / date adapter needed.
      const labels = series.map(p => this._fmtSiteTime(p.ts));
      // Power axis respects the display unit: W series ÷1000 → kW when selected.
      const kw = this.powerUnit === 'kW';
      const scale = kw ? 0.001 : 1;
      const yLabel = kw ? 'kW' : 'W';
      // Friendly labels + DISTINCT colours per series, aligned to the Modbus Bridge /
      // FWHAI palette (Battery cyan · Grid red · Solar amber · Home violet · SoC green).
      const dsPower = (label, key, color) => ({
        label, data: series.map(p => (p[key] == null ? null : p[key] * scale)),
        borderColor: color, backgroundColor: color + '22',
        yAxisID: 'y', pointRadius: 0, borderWidth: 1.5, tension: 0.25,
      });
      const cfg = {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'SoC %', data: series.map(p => p.soc),
              borderColor: '#22c55e', backgroundColor: '#22c55e22',
              yAxisID: 'y1', pointRadius: 0, borderWidth: 1.5, tension: 0.25,
            },
            dsPower('Grid', 'grid_w', '#ef4444'),      // red — import/export
            dsPower('Solar', 'solar_w', '#f59e0b'),    // amber
            dsPower('Battery', 'battery_w', '#06b6d4'), // cyan (was green — clashed with SoC)
            dsPower('Home', 'load_w', '#a78bfa'),      // violet (was grey — clashed w/ grid)
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          // No animation: we destroy()+recreate on every range switch, and an animated
          // redraw schedules a requestAnimationFrame that fires AFTER the next destroy —
          // drawing on a nulled canvas ctx ("null is not an object (evaluating 't.save')").
          // Disabling it also makes range switches repaint instantly.
          animation: false,
          interaction: { mode: 'index', intersect: false },
          scales: {
            x: { ticks: { maxTicksLimit: 8, autoSkip: true } },
            y: {
              position: 'left', title: { display: true, text: yLabel },
              ticks: { callback: (v) => (kw ? v : Math.round(v)) },
            },
            y1: {
              position: 'right', min: 0, max: 100,
              grid: { drawOnChartArea: false },
              title: { display: true, text: 'SoC %' },
            },
          },
          plugins: {
            legend: { labels: { boxWidth: 10 } },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const v = ctx.parsed.y;
                  if (v == null) return `${ctx.dataset.label}: --`;
                  if (ctx.dataset.yAxisID === 'y1') return `${ctx.dataset.label}: ${v.toFixed(0)}%`;
                  return `${ctx.dataset.label}: ${kw ? v.toFixed(2) : Math.round(v)} ${yLabel}`;
                },
              },
            },
          },
        },
      };
      // Destroy + recreate on each render. This is safe ONLY because `animation: false` (above)
      // makes the draw synchronous — so there is never a pending requestAnimationFrame that would
      // fire after destroy() nulls the canvas ctx (the "null is not an object (evaluating
      // 't.save')" crash). We avoid the two alternatives that DON'T work with this build:
      // reassigning `options` (drops the normalised events array -> hover crash) and reassigning
      // `data` in place (corrupts scale/layout state -> "fullSize"/"y" undefined, stack overflow).
      if (this._chart) {
        this._chart.destroy();
        this._chart = null;
      }
      this._chart = new Chart(el, cfg);
    },

    // Grow / shrink the chart height (near-fullscreen for detail inspection).
    toggleExpand() {
      this.histExpanded = !this.histExpanded;
      setTimeout(() => { if (this._chart) this._chart.resize(); }, 60);
    },

    // Download the currently-loaded series as CSV (client-side; no backend).
    exportHistoryCsv() {
      const series = this._lastSeries || [];
      const header = 'ts,soc,grid_w,solar_w,battery_w,load_w';
      const rows = series.map(p => [p.ts, p.soc, p.grid_w, p.solar_w, p.battery_w, p.load_w]
        .map(x => (x == null ? '' : x)).join(','));
      const csv = [header, ...rows].join('\n');
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `fwh-history-${this.histRange}-${Date.now()}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    },

    // ── Toasts ─────────────────────────────────────────────
    toast(message, level = 'info') {
      const id = ++this._toastId;
      this.toasts.push({ id, message, level });
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
      }, 4000);
    },

    // ── Styled confirm dialog (replaces native confirm()) ──────────────────
    confirmState: { open: false, title: '', message: '', danger: false },
    _confirmResolve: null,
    // Await a themed yes/no modal; resolves true (OK) / false (Cancel).
    confirmDialog(message, { title = 'Please confirm', danger = false } = {}) {
      this.confirmState = { open: true, title, message, danger };
      return new Promise((resolve) => { this._confirmResolve = resolve; });
    },
    confirmResolve(ok) {
      this.confirmState.open = false;
      const r = this._confirmResolve; this._confirmResolve = null;
      if (r) r(ok);
    },
  });

});
