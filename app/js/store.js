/* ============================================================================
   The store: sites, crews, workers, day logs.

   localStorage, no backend, so the whole thing runs from a static Pages URL.
   On first load the store is empty and data/seed.json is written into it, which
   makes the demo crew ORDINARY EDITABLE DATA rather than hardcoded content --
   every seeded row can be renamed, re-traded or deleted like any other, and
   Settings can put it all back.

   THE FORBIDDEN-INPUT RULE IS ENFORCED HERE, not just documented. Every write
   passes through `reject()`, which throws if a record carries a field whose
   name looks like age, sex, BMI, fitness, medical history, hydration or
   residence. constants.py owns that list; scripts/build_js_constants.py ships
   it to the browser. It is a legal constraint, not a preference, so it belongs
   at the boundary where data enters rather than in a review checklist.
   ========================================================================== */

import { CONSTANTS } from './engine.js';

const STORE_KEY = 'sunup.store.v1';
const SEED_KEY = 'sunup.seedVersion';

const listeners = new Set();

/* --- Safety: what may never be stored --------------------------------------- */

const FORBIDDEN = CONSTANTS.forbiddenInputs.map((f) => f.toLowerCase());

function reject(record, where) {
  for (const key of Object.keys(record)) {
    const flat = key.toLowerCase().replace(/[^a-z]/g, '');
    for (const banned of FORBIDDEN) {
      const bannedFlat = banned.replace(/[^a-z]/g, '');
      if (flat === bannedFlat || flat.includes(bannedFlat)) {
        throw new Error(
          `${where}: refusing to store "${key}". The model is not permitted `
          + `personal attributes (${banned}); every input must be `
          + 'environmental or job-assigned.');
      }
    }
  }
  return record;
}

/* --- Identity ---------------------------------------------------------------- */

export function newId(prefix) {
  const rand = (globalThis.crypto && globalThis.crypto.randomUUID)
    ? globalThis.crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10);
  return `${prefix}_${rand}`;
}

/* --- Raw persistence --------------------------------------------------------- */

function readRaw(key, fallback) {
  try {
    const text = localStorage.getItem(key);
    return text ? JSON.parse(text) : fallback;
  } catch {
    return fallback;
  }
}

function writeRaw(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch (error) {
    console.warn('sunup: could not persist', key, error);
    return false;
  }
}

const EMPTY = {
  sites: [], crews: [], workers: [], dayLogs: {}, weatherSeries: {},
  exceptionAcknowledgements: {}, seeded: null,
};

let state = null;

function migrateWorkerDefaults(current) {
  let changed = false;
  for (const worker of current.workers || []) {
    if (!worker.rampType) {
      worker.rampType = 'new';
      changed = true;
    }
  }
  return changed;
}

function removeUnsafeDerivedWeather(current) {
  let changed = false;
  for (const site of current.sites || []) {
    if (site.weatherSource !== 'derived') continue;
    if (site.seriesKey && current.weatherSeries) delete current.weatherSeries[site.seriesKey];
    site.seriesKey = null;
    site.weatherSource = 'none';
    site.weatherStatus = 'error';
    site.weatherProgress = null;
    site.weatherUpdatedAt = null;
    site.weatherDates = null;
    site.weatherForecastDates = null;
    site.weatherAsOfDate = null;
    site.weatherError = 'The previous temperature estimate was removed because it was not a site measurement. Fetch live weather to continue.';
    delete site.derivedNote;
    changed = true;
  }
  return changed;
}

/* --- Seeding ----------------------------------------------------------------- */

export async function initStore() {
  state = readRaw(STORE_KEY, null);
  if (state && Array.isArray(state.sites)) {
    let migrated = false;
    if (!state.weatherSeries || typeof state.weatherSeries !== 'object') {
      state.weatherSeries = {};
      migrated = true;
    }
    if (!state.exceptionAcknowledgements
        || typeof state.exceptionAcknowledgements !== 'object') {
      state.exceptionAcknowledgements = {};
      migrated = true;
    }
    if (migrateWorkerDefaults(state)) migrated = true;
    if (removeUnsafeDerivedWeather(state)) migrated = true;
    if (migrateDemoV2(state, window.SUNUP_SEED)) migrated = true;
    if (migrated) writeRaw(STORE_KEY, state);
    hydrateWeatherSeries();
    return state;
  }

  const seed = window.SUNUP_SEED;
  if (!seed) {
    state = { ...EMPTY };
    writeRaw(STORE_KEY, state);
    return state;
  }
  state = applySeed(seed);
  return state;
}

function applySeed(seed) {
  const next = {
    sites: seed.sites.map((s) => reject({ ...s, seeded: true }, 'seed site')),
    crews: seed.crews.map((c) => reject({ ...c, seeded: true }, 'seed crew')),
    workers: seed.workers.map((w) => reject({ rampType: 'new', ...w, seeded: true },
      'seed worker')),
    dayLogs: JSON.parse(JSON.stringify(seed.dayLogs || {})),
    weatherSeries: {},
    exceptionAcknowledgements: {},
    seeded: seed.version,
  };
  writeRaw(STORE_KEY, next);
  writeRaw(SEED_KEY, seed.version);
  return next;
}

/** Settings action. Discards day logs, so the caller must confirm first. */
export function resetToSeed() {
  const seed = window.SUNUP_SEED;
  if (!seed) throw new Error('seed data not loaded');
  for (const key of Object.keys(state.weatherSeries || {})) {
    delete window.SUNUP_WEATHER.series[key];
  }
  state = applySeed(seed);
  emit();
  return state;
}

export function seedVersion() {
  return (state && state.seeded) || null;
}

/* --- Change notification ----------------------------------------------------- */

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit() {
  writeRaw(STORE_KEY, state);
  for (const fn of listeners) fn(state);
}

/* --- Reads ------------------------------------------------------------------- */

export function getState() { return state; }
export function sites() { return state.sites; }
export function site(id) { return state.sites.find((s) => s.id === id) || null; }
export function crews(siteId) {
  return state.crews.filter((c) => !siteId || c.siteId === siteId);
}
export function crew(id) { return state.crews.find((c) => c.id === id) || null; }
export function workers(crewId) {
  return state.workers.filter((w) => !crewId || w.crewId === crewId);
}
export function worker(id) { return state.workers.find((w) => w.id === id) || null; }

export function workersAtSite(siteId) {
  const ids = new Set(crews(siteId).map((c) => c.id));
  return state.workers.filter((w) => ids.has(w.crewId));
}

export function logsFor(workerId) {
  return state.dayLogs[workerId] || {};
}

function migrateDemoV2(current, seed) {
  if (!seed || seed.version < 2 || !current.seeded || current.seeded >= 2) return false;
  const worker = current.workers.find((item) => item.id === 'wkr_whitfield');
  const replacement = seed.workers.find((item) => item.id === 'wkr_whitfield');
  const untouched = worker && worker.seeded
    && worker.name === 'D. Whitfield'
    && worker.crewId === 'crew_elec'
    && worker.trade === 'electrical'
    && worker.clothing === 'work_clothes'
    && worker.shiftStart === 5
    && worker.shiftEnd === 13
    && worker.hireDate === '2026-08-08';
  if (untouched && replacement) {
    worker.shiftStart = replacement.shiftStart;
    worker.shiftEnd = replacement.shiftEnd;
  }
  current.seeded = 2;
  writeRaw(SEED_KEY, 2);
  return true;
}

export function exceptionAcknowledgements() {
  return state.exceptionAcknowledgements || {};
}

function hydrateWeatherSeries() {
  const registry = window.SUNUP_WEATHER && window.SUNUP_WEATHER.series;
  if (!registry) return;
  for (const [key, series] of Object.entries(state.weatherSeries || {})) {
    registry[key] = series;
  }
}

function dropWeatherSeries(key) {
  if (!key || !state.weatherSeries || !state.weatherSeries[key]) return;
  delete state.weatherSeries[key];
  if (window.SUNUP_WEATHER && window.SUNUP_WEATHER.series) {
    delete window.SUNUP_WEATHER.series[key];
  }
}

export function saveWeatherSeries(key, series) {
  const saved = JSON.parse(JSON.stringify(series || {}));
  state.weatherSeries[key] = saved;
  window.SUNUP_WEATHER.series[key] = saved;
  emit();
  return saved;
}

export function removeWeatherSeries(key) {
  dropWeatherSeries(key);
  emit();
}

/* --- Writes ------------------------------------------------------------------ */

export function addSite(fields) {
  const record = reject({
    id: newId('site'),
    name: 'New site',
    polygon: null,
    location: null,
    geometryMode: 'point',
    seriesKey: null,
    weatherSource: 'none',
    weatherStatus: null,
    weatherProgress: null,
    weatherUpdatedAt: null,
    weatherDates: null,
    weatherForecastDates: null,
    weatherAsOfDate: null,
    weatherError: null,
    liveActivities: {},
    liveActivityId: null,
    liveActivityDate: null,
    seeded: false,
    ...fields,
  }, 'addSite');
  state.sites.push(record);
  emit();
  return record;
}

export function addCrew(fields) {
  const record = reject({
    id: newId('crew'), name: 'New crew', siteId: null, seeded: false, ...fields,
  }, 'addCrew');
  state.crews.push(record);
  emit();
  return record;
}

export function addWorker(fields) {
  const record = reject({
    id: newId('wkr'),
    name: 'New worker',
    crewId: null,
    trade: 'concrete',
    workClassOverride: null,
    clothing: 'work_clothes',
    shiftStart: CONSTANTS.defaultShiftStartHour,
    shiftEnd: CONSTANTS.defaultShiftEndHour,
    hireDate: null,
    rampType: 'new',
    active: true,
    seeded: false,
    ...fields,
  }, 'addWorker');
  state.workers.push(record);
  emit();
  return record;
}

function patch(collection, id, changes, where) {
  const item = collection.find((x) => x.id === id);
  if (!item) throw new Error(`${where}: no such id ${id}`);
  reject(changes, where);
  Object.assign(item, changes);
  emit();
  return item;
}

export function updateSite(id, changes) { return patch(state.sites, id, changes, 'updateSite'); }
export function updateCrew(id, changes) { return patch(state.crews, id, changes, 'updateCrew'); }
export function updateWorker(id, changes) { return patch(state.workers, id, changes, 'updateWorker'); }

function dropExceptionAcknowledgements(matches) {
  Object.entries(state.exceptionAcknowledgements || {}).forEach(([id, event]) => {
    if (matches(event)) delete state.exceptionAcknowledgements[id];
  });
}

/* Deletes cascade. A crew whose site is gone, or a worker whose crew is gone,
   would otherwise sit in the store unreachable and still be counted. */

export function removeSite(id) {
  const removed = site(id);
  const doomed = new Set(crews(id).map((c) => c.id));
  state.workers = state.workers.filter((w) => {
    if (!doomed.has(w.crewId)) return true;
    delete state.dayLogs[w.id];
    return false;
  });
  state.crews = state.crews.filter((c) => c.siteId !== id);
  state.sites = state.sites.filter((s) => s.id !== id);
  dropExceptionAcknowledgements((event) => event.siteId === id);
  if (removed) dropWeatherSeries(removed.seriesKey);
  emit();
}

export function removeCrew(id) {
  state.workers = state.workers.filter((w) => {
    if (w.crewId !== id) return true;
    delete state.dayLogs[w.id];
    return false;
  });
  state.crews = state.crews.filter((c) => c.id !== id);
  dropExceptionAcknowledgements((event) => event.crewId === id);
  emit();
}

export function removeWorker(id) {
  state.workers = state.workers.filter((w) => w.id !== id);
  delete state.dayLogs[id];
  dropExceptionAcknowledgements((event) => event.workerId === id
    || (Array.isArray(event.memberWorkerIds) && event.memberWorkerIds.includes(id)));
  emit();
}

/* --- The day log -------------------------------------------------------------
   `null` minutes means "no entry" and the day falls back to the prescription,
   marked assumed. Zero is a MEASUREMENT: he was here and worked nothing --
   and must not be confused with the absence of one.
   ---------------------------------------------------------------------------- */

export function setDayLog(workerId, date, minutes, note) {
  const assignedWorker = worker(workerId);
  if (!assignedWorker) throw new Error('Worker not found.');
  if (!state.dayLogs[workerId]) state.dayLogs[workerId] = {};
  if (minutes === null || minutes === undefined || minutes === '') {
    delete state.dayLogs[workerId][date];
  } else {
    const value = Number(minutes);
    if (!Number.isFinite(value) || value < 0) {
      throw new Error('Actual minutes must be a non-negative number.');
    }
    const shiftMinutes = Math.max(0,
      (assignedWorker.shiftEnd - assignedWorker.shiftStart) * 60);
    if (value > shiftMinutes) {
      throw new Error(`Actual minutes cannot exceed this worker's ${shiftMinutes}-minute shift.`);
    }
    state.dayLogs[workerId][date] = {
      minutes: Math.round(value),
      note: note || '',
    };
  }
  emit();
}

/** Shape the engine wants: { 'YYYY-MM-DD': minutes }. */
export function loggedMinutes(workerId) {
  const out = {};
  for (const [date, entry] of Object.entries(logsFor(workerId))) {
    out[date] = entry.minutes;
  }
  return out;
}

/* --- Exception review -------------------------------------------------------- */

export function acknowledgeException(event) {
  if (!event || !event.id) throw new Error('acknowledgeException: event id required');
  const saved = {
    id: event.id,
    type: event.type,
    date: event.date,
    title: event.title,
    detail: event.detail,
    severity: event.severity,
    workerId: event.workerId || null,
    memberWorkerIds: Array.isArray(event.memberWorkerIds)
      ? event.memberWorkerIds.slice() : [],
    crewId: event.crewId || null,
    siteId: event.siteId || null,
    scope: event.scope || '',
    href: event.href || null,
    acknowledgedAt: new Date().toISOString(),
  };
  state.exceptionAcknowledgements[event.id] = saved;
  emit();
  return saved;
}

export function reopenException(id) {
  delete state.exceptionAcknowledgements[id];
  emit();
}

/* --- Export / import ---------------------------------------------------------- */

export function exportJson() {
  return JSON.stringify(state, null, 1);
}
