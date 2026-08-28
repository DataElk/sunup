/* ============================================================================
   Derivation: store + weather + engine -> what the screen shows.

   Nothing here is persisted. Every prescription is recomputed from the worker,
   the site's weather and the day log, which is what makes changing a trade or
   logging a day update the answer immediately rather than at the next build.

   Results are memoised on a cheap signature so a grid of forty workers does not
   re-simulate on every keystroke; any store change clears the cache.
   ========================================================================== */

import { simulate, shiftHours, workClassOf, statusFor } from './engine.js';
import * as store from './store.js';

const W = () => window.SUNUP_WEATHER;

let cache = new Map();
export function invalidate() { cache = new Map(); }

export function today() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Phoenix', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

export function observedDatesForSite(site) {
  if (site && Array.isArray(site.weatherDates) && site.weatherDates.length) {
    return site.weatherDates.slice().sort();
  }
  return W().dates.slice();
}

export function forecastDatesForSite(site) {
  return site && Array.isArray(site.weatherForecastDates)
    ? site.weatherForecastDates.slice().sort() : [];
}

export function allDates(site = null) { return observedDatesForSite(site); }

export function currentDateForSite(site) {
  const dates = observedDatesForSite(site);
  return (site && site.weatherAsOfDate) || dates[dates.length - 1] || today();
}

export function currentDateForWorker(workerId) {
  const worker = store.worker(workerId);
  return worker ? currentDateForSite(siteOf(worker)) : today();
}

export function currentDateForCrew(crewId) {
  const crew = store.crew(crewId);
  return crew ? currentDateForSite(store.site(crew.siteId)) : today();
}

/** Maximum number of real forecast days shown after the observed history. */
export const PROJECTION_DAYS = 6;

function signature(worker, logs) {
  return [
    worker.id, worker.trade, worker.workClassOverride, worker.clothing,
    worker.shiftStart, worker.shiftEnd, worker.hireDate, worker.active,
    JSON.stringify(logs),
  ].join('|');
}

/** The site a worker's weather comes from, via their crew. */
export function siteOf(worker) {
  const crew = store.crew(worker.crewId);
  return crew ? store.site(crew.siteId) : null;
}

/**
 * Full history for one worker: observed days from hire date to today, plus a
 * projection. Returns null when the site has no weather series, a real state
 * the interface must show rather than paper over.
 */
export function forWorker(workerId) {
  const worker = store.worker(workerId);
  if (!worker) return null;

  const site = siteOf(worker);
  if (!site || !site.seriesKey || !W().series[site.seriesKey]) {
    return { worker, site, unavailable: true, reason: 'no-weather' };
  }

  const logs = store.loggedMinutes(worker.id);
  const key = signature(worker, logs);
  if (cache.has(key)) return cache.get(key);

  const series = W().series[site.seriesKey];
  const dates = observedDatesForSite(site)
    .filter((d) => series[d] && (!worker.hireDate || d >= worker.hireDate));
  if (!dates.length) {
    return { worker, site, unavailable: true, reason: 'not-started' };
  }

  const observed = dates.map((date) => ({ date, hourly: series[date] }));
  const projected = forecastDatesForSite(site)
    .filter((date) => series[date])
    .slice(0, PROJECTION_DAYS)
    .map((date) => ({ date, hourly: series[date], projected: true }));

  const run = simulate({
    worker, days: observed.concat(projected), logs, initialAdaptation: 0,
  });

  const records = run.records;
  const currentDate = currentDateForSite(site);
  const todayIndex = records.findIndex((r) => r.date === currentDate && !r.projected);
  const current = todayIndex >= 0 ? records[todayIndex] : records[dates.length - 1];

  const result = {
    worker,
    site,
    unavailable: false,
    records,
    observed: records.filter((r) => !r.projected),
    projected: records.filter((r) => r.projected),
    current,
    currentHourly: series[current.date] || null,
    finalAdaptation: run.finalAdaptation,
    cumulativeOverexposure: run.cumulativeOverexposure,
    assumedRun: trailingAssumed(records.filter((r) => !r.projected)),
    unprescribedDays: records.filter((r) => r.unprescribedWork && !r.projected).length,
    workClass: workClassOf(worker),
    shiftHours: shiftHours(worker),
  };
  cache.set(key, result);
  return result;
}

/** How many of the most recent observed days had no logged actual. */
function trailingAssumed(observed) {
  let n = 0;
  for (let i = observed.length - 1; i >= 0; i -= 1) {
    if (!observed[i].assumed) break;
    n += 1;
  }
  return n;
}

/* --- Roll-ups ---------------------------------------------------------------- */

const SEVERITY = { stop: 0, restricted: 1, reduced: 2, cleared: 3 };

export function forCrew(crewId) {
  const rows = store.workers(crewId)
    .filter((w) => w.active !== false)
    .map((w) => forWorker(w.id))
    .filter(Boolean);

  const usable = rows.filter((r) => !r.unavailable);
  const worst = usable.reduce((acc, r) => {
    const s = SEVERITY[r.current.status];
    return s < acc ? s : acc;
  }, 3);

  return {
    crew: store.crew(crewId),
    rows,
    workers: rows.length,
    unavailable: rows.length > 0 && usable.length === 0,
    modelMinutes: usable.reduce((s, r) => s + r.current.prescribedMinutes, 0),
    calendarMinutes: usable.reduce((s, r) => s + r.current.calendarMinutes, 0),
    stopped: usable.filter((r) => r.current.status === 'stop').length,
    overexposed: usable.filter((r) => r.cumulativeOverexposure > 0).length,
    unprescribed: usable.filter((r) => r.unprescribedDays > 0).length,
    worstStatus: Object.keys(SEVERITY).find((k) => SEVERITY[k] === worst) || 'cleared',
  };
}

export function forSite(siteId) {
  const crews = store.crews(siteId).map((c) => forCrew(c.id));
  const worst = crews.reduce((acc, c) => {
    const s = SEVERITY[c.worstStatus];
    return s < acc ? s : acc;
  }, 3);
  return {
    site: store.site(siteId),
    crews,
    workers: crews.reduce((s, c) => s + c.workers, 0),
    modelMinutes: crews.reduce((s, c) => s + c.modelMinutes, 0),
    calendarMinutes: crews.reduce((s, c) => s + c.calendarMinutes, 0),
    stopped: crews.reduce((s, c) => s + c.stopped, 0),
    worstStatus: Object.keys(SEVERITY).find((k) => SEVERITY[k] === worst) || 'cleared',
  };
}

/* --- Weather estimation for a site that has none -----------------------------
   The honest default is that a new site has no weather and says so. This is the
   opt-in alternative: scale the nearest measured series by the ratio of the two
   sites' exceedance hours. It is a DERIVED series, tagged as such everywhere it
   surfaces, including the compliance record.
   ---------------------------------------------------------------------------- */

export function estimateSeriesFrom(measuredKey, ratio) {
  const source = W().series[measuredKey];
  const out = {};
  for (const [date, hourly] of Object.entries(source)) {
    out[date] = hourly.map((v) => Math.round(v * ratio * 1000) / 1000);
  }
  return out;
}

export function measuredSeriesKeys() {
  return Object.keys(W().series);
}

export function statusOf(minutes, worker) { return statusFor(minutes, worker); }
