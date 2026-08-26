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

const STORE_KEY = 'acclimate.store.v1';
const SEED_KEY = 'acclimate.seedVersion';

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
    console.warn('acclimate: could not persist', key, error);
    return false;
  }
}

const EMPTY = { sites: [], crews: [], workers: [], dayLogs: {}, seeded: null };

let state = null;

/* --- Seeding ----------------------------------------------------------------- */

export async function initStore() {
  state = readRaw(STORE_KEY, null);
  if (state && Array.isArray(state.sites)) return state;

  const seed = window.ACCLIMATE_SEED;
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
    workers: seed.workers.map((w) => reject({ ...w, seeded: true }, 'seed worker')),
    dayLogs: JSON.parse(JSON.stringify(seed.dayLogs || {})),
    seeded: seed.version,
  };
  writeRaw(STORE_KEY, next);
  writeRaw(SEED_KEY, seed.version);
  return next;
}

/** Settings action. Discards day logs, so the caller must confirm first. */
export function resetToSeed() {
  const seed = window.ACCLIMATE_SEED;
  if (!seed) throw new Error('seed data not loaded');
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

/* --- Writes ------------------------------------------------------------------ */

export function addSite(fields) {
  const record = reject({
    id: newId('site'),
    name: 'New site',
    polygon: null,
    location: null,
    seriesKey: null,
    weatherSource: 'none',
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

/* Deletes cascade. A crew whose site is gone, or a worker whose crew is gone,
   would otherwise sit in the store unreachable and still be counted. */

export function removeSite(id) {
  const doomed = new Set(crews(id).map((c) => c.id));
  state.workers = state.workers.filter((w) => {
    if (!doomed.has(w.crewId)) return true;
    delete state.dayLogs[w.id];
    return false;
  });
  state.crews = state.crews.filter((c) => c.siteId !== id);
  state.sites = state.sites.filter((s) => s.id !== id);
  emit();
}

export function removeCrew(id) {
  state.workers = state.workers.filter((w) => {
    if (w.crewId !== id) return true;
    delete state.dayLogs[w.id];
    return false;
  });
  state.crews = state.crews.filter((c) => c.id !== id);
  emit();
}

export function removeWorker(id) {
  state.workers = state.workers.filter((w) => w.id !== id);
  delete state.dayLogs[id];
  emit();
}

/* --- The day log -------------------------------------------------------------
   `null` minutes means "no entry" and the day falls back to the prescription,
   marked assumed. Zero is a MEASUREMENT: he was here and worked nothing --
   and must not be confused with the absence of one.
   ---------------------------------------------------------------------------- */

export function setDayLog(workerId, date, minutes, note) {
  if (!state.dayLogs[workerId]) state.dayLogs[workerId] = {};
  if (minutes === null || minutes === undefined || minutes === '') {
    delete state.dayLogs[workerId][date];
  } else {
    state.dayLogs[workerId][date] = {
      minutes: Math.max(0, Math.round(Number(minutes))),
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

/* --- Export / import ---------------------------------------------------------- */

export function exportJson() {
  return JSON.stringify(state, null, 1);
}
