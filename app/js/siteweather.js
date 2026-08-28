/* Live site history, fetched five days first and backfilled in the background. */

import * as store from './store.js';
import * as compute from './compute.js';
import {
  bufferedAoi, buildWbgtSeries, parseOpenMeteoDays, selectSiteCell,
} from './environment.js';
import {
  fetchRegionalWeather, hasConfiguredKey, submitHeatmap, waitForActivity,
} from './liveweather.js';

const HISTORY_DAYS = 14;
const FIRST_DAYS = 5;
const FORECAST_DAYS = 6;
const INITIAL_CONCURRENCY = 5;
const BACKFILL_CONCURRENCY = 3;
const inflight = new Set();

function weather() { return window.SUNUP_WEATHER; }

function phoenixToday() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Phoenix', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function moveDate(date, days) {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

export function observedDateWindow(asOf = phoenixToday()) {
  return Array.from({ length: HISTORY_DAYS }, (_, index) => (
    moveDate(asOf, index - HISTORY_DAYS + 1)
  ));
}

export function forecastDateWindow(asOf = phoenixToday()) {
  return Array.from({ length: FORECAST_DAYS }, (_, index) => moveDate(asOf, index + 1));
}

function siteDates(site) {
  return Array.isArray(site.weatherDates) && site.weatherDates.length
    ? site.weatherDates : observedDateWindow();
}

function forecastDates(site) {
  return Array.isArray(site.weatherForecastDates) && site.weatherForecastDates.length
    ? site.weatherForecastDates : forecastDateWindow();
}

function payload(site, date, queryAoi) {
  return {
    polygon_aoi: queryAoi,
    date_time: { start_date: date, filter_type: 3 },
    granularity: 100,
  };
}

export function readDailySeries(result, site, driver, queryAoi) {
  const cell = selectSiteCell(result, site, queryAoi);
  return buildWbgtSeries(cell, driver, site.location);
}

async function fetchDay(site, date, driver, onActivity, activityId = null) {
  const queryAoi = bufferedAoi(site);
  let pendingId = activityId;
  if (!pendingId) {
    const submitted = await submitHeatmap(payload(site, date, queryAoi));
    pendingId = submitted && submitted.data && submitted.data.activity_id;
    if (!pendingId) throw new Error('The live weather task was not accepted.');
    if (onActivity) onActivity(pendingId);
  }
  const result = await waitForActivity(pendingId);
  return readDailySeries(result, site, driver, queryAoi);
}

async function loadDrivers(site) {
  const observed = siteDates(site);
  const projected = forecastDates(site);
  const raw = await fetchRegionalWeather(
    site.location, observed[0], projected[projected.length - 1],
  );
  const days = parseOpenMeteoDays(raw);
  for (const date of observed.concat(projected)) {
    if (!days[date]) throw new Error(`Regional hourly weather is missing ${date}.`);
  }
  return days;
}

function updateProgress(siteId, changes) {
  const site = store.site(siteId);
  if (site) store.updateSite(siteId, changes);
}

function liveKey(site) {
  return site.seriesKey || `live_${site.id}`;
}

function dayReady(site, date) {
  const series = weather().series[liveKey(site)] || {};
  return Array.isArray(series[date]) && series[date].length === 24;
}

function completedDays(site) {
  return siteDates(site).filter((date) => dayReady(site, date)).length;
}

function pendingActivities(site) {
  const pending = { ...((site && site.liveActivities) || {}) };
  if (site && site.liveActivityId && site.liveActivityDate
      && !pending[site.liveActivityDate]) {
    pending[site.liveActivityDate] = site.liveActivityId;
  }
  return pending;
}

function setPendingActivity(siteId, date, activityId) {
  const site = store.site(siteId);
  if (!site) return;
  const pending = { ...pendingActivities(site), [date]: activityId };
  updateProgress(siteId, {
    liveActivities: pending,
    liveActivityId: activityId,
    liveActivityDate: date,
  });
}

function clearPendingActivity(siteId, date) {
  const site = store.site(siteId);
  if (!site) return;
  const pending = pendingActivities(site);
  delete pending[date];
  const remaining = Object.entries(pending)[0] || [null, null];
  updateProgress(siteId, {
    liveActivities: pending,
    liveActivityDate: remaining[0],
    liveActivityId: remaining[1],
  });
}

function orderedDates(site) {
  const dates = siteDates(site);
  return dates.slice(-FIRST_DAYS).concat(dates.slice(0, -FIRST_DAYS));
}

function stageFor(completed, total) {
  if (completed >= total) return 'complete';
  return completed >= FIRST_DAYS ? 'backfill' : 'loading';
}

function setStage(siteId) {
  const site = store.site(siteId);
  if (!site) return 0;
  const completed = completedDays(site);
  const total = siteDates(site).length;
  updateProgress(siteId, {
    weatherSource: completed >= FIRST_DAYS ? 'live' : 'none',
    weatherStatus: stageFor(completed, total),
    weatherProgress: {
      completed, total, pending: Object.keys(pendingActivities(site)).length,
    },
  });
  return completed;
}

function saveForecastSeries(siteId, drivers) {
  const site = store.site(siteId);
  if (!site) return;
  const key = liveKey(site);
  const series = { ...(weather().series[key] || {}) };
  for (const date of forecastDates(site)) {
    series[date] = buildWbgtSeries(null, drivers[date], site.location);
  }
  store.saveWeatherSeries(key, series);
  updateProgress(siteId, { seriesKey: key });
  compute.invalidate();
}

function saveDailySeries(siteId, date, daily) {
  const site = store.site(siteId);
  if (!site) return 0;
  const key = liveKey(site);
  const series = { ...(weather().series[key] || {}), [date]: daily };
  store.saveWeatherSeries(key, series);
  const completed = siteDates(site).filter((item) => Array.isArray(series[item])).length;
  const total = siteDates(site).length;
  clearPendingActivity(siteId, date);
  const current = store.site(siteId);
  updateProgress(siteId, {
    seriesKey: key,
    weatherSource: completed >= FIRST_DAYS ? 'live' : 'none',
    weatherStatus: stageFor(completed, total),
    weatherProgress: {
      completed, total, pending: Object.keys(pendingActivities(current)).length,
    },
    weatherUpdatedAt: new Date().toISOString(),
    weatherError: null,
  });
  compute.invalidate();
  return completed;
}

async function runPool(items, limit, work) {
  const queue = items.slice();
  const outcomes = [];
  async function worker() {
    while (queue.length) {
      const item = queue.shift();
      try {
        outcomes.push({ item, value: await work(item) });
      } catch (error) {
        outcomes.push({ item, error });
      }
    }
  }
  await Promise.all(Array.from(
    { length: Math.min(limit, queue.length) }, () => worker()));
  return outcomes;
}

async function fetchDates(siteId, dates, drivers, concurrency) {
  const site = store.site(siteId);
  if (!site) return 0;
  const pending = pendingActivities(site);
  const missing = dates.filter((date) => !dayReady(site, date) && !pending[date]);
  const outcomes = await runPool(missing, concurrency, async (date) => {
    const current = store.site(siteId);
    if (!current) return null;
    try {
      const daily = await fetchDay(current, date, drivers[date], (activityId) => (
        setPendingActivity(siteId, date, activityId)
      ));
      saveDailySeries(siteId, date, daily);
      return daily;
    } catch (error) {
      if (error && error.code === 'activity_failed') clearPendingActivity(siteId, date);
      throw error;
    }
  });
  const failure = outcomes.find((outcome) => outcome.error);
  if (failure) throw failure.error;
  const latest = store.site(siteId);
  return latest ? completedDays(latest) : 0;
}

async function resumePending(siteId, drivers) {
  const site = store.site(siteId);
  if (!site) return false;
  const pending = Object.entries(pendingActivities(site));
  if (!pending.length) return false;
  const outcomes = await runPool(pending, INITIAL_CONCURRENCY, async ([date, activityId]) => {
    const current = store.site(siteId);
    if (!current) return null;
    if (dayReady(current, date)) {
      clearPendingActivity(siteId, date);
      return null;
    }
    try {
      const daily = await fetchDay(current, date, drivers[date], null, activityId);
      saveDailySeries(siteId, date, daily);
      return daily;
    } catch (error) {
      if (error && error.code === 'activity_failed') clearPendingActivity(siteId, date);
      throw error;
    }
  });
  const failure = outcomes.find((outcome) => outcome.error);
  if (failure) throw failure.error;
  return true;
}

function markFailure(siteId, error) {
  const site = store.site(siteId);
  if (!site) return;
  const completed = completedDays(site);
  const changes = {
    weatherStatus: completed ? 'partial' : 'error',
    weatherProgress: {
      completed,
      total: siteDates(site).length,
      pending: Object.keys(pendingActivities(site)).length,
    },
    weatherError: error && error.message ? error.message : 'Live weather failed.',
  };
  updateProgress(siteId, changes);
}

async function finishBackfill(siteId, drivers) {
  try {
    const site = store.site(siteId);
    if (site) await fetchDates(
      siteId, orderedDates(site), drivers, BACKFILL_CONCURRENCY);
  } catch (error) {
    markFailure(siteId, error);
  } finally {
    inflight.delete(siteId);
  }
}

export async function startSiteBackfill(siteId) {
  if (!hasConfiguredKey()) return false;
  const site = store.site(siteId);
  if (!site || !site.polygon || !site.location) return false;
  if (inflight.has(siteId)) return true;
  inflight.add(siteId);

  // FortyGuard heatmaps are historical. End observations on the last complete
  // Arizona day, then begin the Open-Meteo forecast on today.
  const today = phoenixToday();
  const asOf = moveDate(today, -1);
  updateProgress(siteId, {
    weatherDates: observedDateWindow(asOf),
    weatherForecastDates: forecastDateWindow(asOf),
    weatherAsOfDate: asOf,
    weatherError: null,
  });
  setStage(siteId);
  try {
    const current = store.site(siteId);
    const drivers = await loadDrivers(current);
    saveForecastSeries(siteId, drivers);
    await resumePending(siteId, drivers);
    const latest = store.site(siteId);
    await fetchDates(
      siteId, siteDates(latest).slice(-FIRST_DAYS), drivers, INITIAL_CONCURRENCY);
    window.setTimeout(() => finishBackfill(siteId, drivers), 0);
    return true;
  } catch (error) {
    markFailure(siteId, error);
    inflight.delete(siteId);
    return false;
  }
}

export async function resumeSiteActivity(siteId) {
  const site = store.site(siteId);
  if (!site || !Object.keys(pendingActivities(site)).length) return false;
  try {
    const drivers = await loadDrivers(site);
    return await resumePending(siteId, drivers);
  } catch (error) {
    markFailure(siteId, error);
    return false;
  }
}

export function resumeSiteBackfills() {
  if (!hasConfiguredKey()) return Promise.resolve([]);
  const resumable = store.sites().filter((site) => Object.keys(pendingActivities(site)).length
    || ['loading', 'backfill', 'partial'].includes(site.weatherStatus));
  return Promise.allSettled(resumable.map((site) => startSiteBackfill(site.id)));
}
