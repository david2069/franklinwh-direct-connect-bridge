/**
 * The styled calendar (owner, 2026-11-10) shared by Analytics and the Dashboard's Energy
 * Flow card: days, months or years to pick from, drawn by partials/calendar.html. Dates are
 * 'YYYY-MM-DD' on the calendar the host uses (the site's for Analytics, the browser's for
 * the card); these helpers only do the date arithmetic, each host keeps its own state.
 */
(function () {
  'use strict';

  const iso = (t) => new Date(t).toISOString().slice(0, 10);
  const parts = (d) => d.split('-').map(Number);

  window.FWHCalendar = {
    /** What the calendar lists for a period: days, months (Month) or years (Year). */
    mode(period) { return period === 'year' ? 'years' : period === 'month' ? 'months' : 'days'; },

    /** The heading: the month shown, the year shown, or the twelve years shown. */
    title(cursor, mode) {
      const [y, m] = parts(cursor);
      if (mode === 'years') return `${y - 8} – ${y + 3}`;
      if (mode === 'months') return String(y);
      return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' })
        .format(new Date(Date.UTC(y, m - 1, 1)));
    },

    /** ‹ › inside the calendar: a month, a year, or twelve years. */
    step(cursor, mode, dir) {
      const [y, m] = parts(cursor);
      return iso(mode === 'days' ? Date.UTC(y, m - 1 + dir, 1)
        : Date.UTC(y + dir * (mode === 'years' ? 12 : 1), 0, 1));
    },

    /** Nothing later to show. */
    atEnd(cursor, mode, today) {
      return mode === 'days' ? cursor.slice(0, 7) >= today.slice(0, 7)
        : mode === 'months' ? cursor.slice(0, 4) >= today.slice(0, 4) : +cursor.slice(0, 4) + 3 >= +today.slice(0, 4);
    },

    /** Six Monday-to-Sunday weeks around the cursor's month. `sel` is marked (with the six
     *  days after it when `week`); days after `maxDay` or before `minDay` are off. */
    days(cursor, { sel, week, today, maxDay, minDay }) {
      const [y, m] = parts(cursor);
      const first = Date.UTC(y, m - 1, 1), lead = (new Date(first).getUTCDay() + 6) % 7;
      const [sy, sm, sd] = parts(sel), weekEnd = iso(Date.UTC(sy, sm - 1, sd + 7));
      const max = maxDay || today;
      return Array.from({ length: 42 }, (_, i) => {
        const d = iso(first + (i - lead) * 86400000);
        return { iso: d, d: +d.slice(8), inMonth: +d.slice(5, 7) === m, today: d === today,
                 off: d > max || (minDay != null && d < minDay),
                 sel: week ? d >= sel && d < weekEnd : d === sel };
      });
    },

    /** The cursor's twelve months. */
    months(cursor, { sel, today, minDay }) {
      const y = +cursor.slice(0, 4);
      return Array.from({ length: 12 }, (_, i) => {
        const d = `${y}-${String(i + 1).padStart(2, '0')}-01`;
        return { iso: d, label: new Intl.DateTimeFormat(undefined, { month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(y, i, 1))),
                 off: d > today || (minDay != null && d.slice(0, 7) < minDay.slice(0, 7)), sel: d === sel };
      });
    },

    /** Twelve years, the cursor's ninth. */
    years(cursor, { sel, today, minDay }) {
      const y = +cursor.slice(0, 4);
      return Array.from({ length: 12 }, (_, i) => {
        const yy = y - 8 + i, d = `${yy}-01-01`;
        return { iso: d, label: String(yy), off: d > today || (minDay != null && String(yy) < minDay.slice(0, 4)),
                 sel: d === sel };
      });
    },
  };
})();
