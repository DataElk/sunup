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

async function fetchDay(site, date, driver, onActivity) {
  const queryAoi = bufferedAoi(site);
  const submitted = await submitHeatmap(payload(site, date, queryAoi));
  const activityId = submitted && submitted.data && submitted.data.activity_id;
  if (!activityId) throw new Error('The live weather task was not accepted.');
  if (onActivity) onActivity(activityId);
  const result = await waitForActivity(activityId);
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
    weatherProgress: { completed, total },
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
  updateProgress(siteId, {
    seriesKey: key,
    weatherSource: completed >= FIRST_DAYS ? 'live' : 'none',
    weatherStatus: stageFor(completed, total),
    weatherProgress: { completed, total },
    weatherUpdatedAt: new Date().toISOString(),
    liveActivityId: null,
    liveActivityDate: null,
  });
  compute.invalidate();
  return completed;
}

async function fetchDates(siteId, dates, drivers) {
  const site = store.site(siteId);
  if (!site) return 0;
  for (const date of dates) {
    const current = store.site(siteId);
    if (!current) return 0;
    if (dayReady(current, date)) continue;
    const daily = await fetchDay(current, date, drivers[date], (activityId) => (
      updateProgress(siteId, { liveActivityId: activityId, liveActivityDate: date })
    ));
    saveDailySeries(siteId, date, daily);
  }
  const latest = store.site(siteId);
  return latest ? completedDays(latest) : 0;
}

async function resumePending(siteId, drivers) {
  const site = store.site(siteId);
  if (!site || !site.liveActivityId) return false;
  const date = site.liveActivityDate
    || orderedDates(site).find((item) => !dayReady(site, item));
  if (!date) {
    updateProgress(siteId, { liveActivityId: null, liveActivityDate: null });
    return false;
  }
  if (dayReady(site, date)) {
    updateProgress(siteId, { liveActivityId: null, liveActivityDate: null });
    return true;
  }
  updateProgress(siteId, { liveActivityDate: date });
  const result = await waitForActivity(site.liveActivityId);
  const current = store.site(siteId);
  if (!current) return false;
  const queryAoi = bufferedAoi(current);
  saveDailySeries(siteId, date, readDailySeries(result, current, drivers[date], queryAoi));
  return true;
}

function markFailure(siteId, error) {
  const site = store.site(siteId);
  if (!site) return;
  const completed = completedDays(site);
  const changes = {
    weatherStatus: completed ? 'partial' : 'error',
    weatherProgress: { completed, total: siteDates(site).length },
    weatherError: error && error.message ? error.message : 'Live weather failed.',
  };
  if (error && error.code === 'activity_failed') {
    changes.liveActivityId = null;
    changes.liveActivityDate = null;
  }
  updateProgress(siteId, changes);
}

async function finishBackfill(siteId, drivers) {
  try {
    const site = store.site(siteId);
    if (site) await fetchDates(siteId, orderedDates(site), drivers);
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
    await fetchDates(siteId, siteDates(latest).slice(-FIRST_DAYS), drivers);
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
  if (!site || !site.liveActivityId) return false;
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
  const resumable = store.sites().filter((site) => site.liveActivityId
    || ['loading', 'backfill', 'partial'].includes(site.weatherStatus));
  return Promise.allSettled(resumable.map((site) => startSiteBackfill(site.id)));
}
