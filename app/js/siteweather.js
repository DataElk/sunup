/* Live site history, fetched five days first and backfilled in the background. */

import * as store from './store.js';
import * as compute from './compute.js';
import { hasConfiguredKey, submitHeatmap, waitForActivity } from './liveweather.js';

const FIRST_DAYS = 5;
const inflight = new Set();

function weather() { return window.ACCLIMATE_WEATHER; }

function nearestFeature(features, location) {
  let best = null;
  let bestDistance = Infinity;
  for (const feature of features || []) {
    const ring = feature.geometry && feature.geometry.coordinates && feature.geometry.coordinates[0];
    if (!ring || !ring.length) continue;
    const point = ring[0];
    const distance = Math.hypot(point[0] - location.lng, point[1] - location.lat);
    if (distance < bestDistance) { bestDistance = distance; best = feature; }
  }
  return best;
}

function baseSeries(date) {
  const all = weather().series;
  return all.hot_site[date] || all.cool_site[date] || Object.values(all)[0][date];
}

function readDailySeries(result, site, date) {
  const mapData = result && result.map_data;
  const feature = mapData && nearestFeature(mapData.features, site.location);
  const cell = feature && feature.properties;
  const mean = result && result.stats_data && result.stats_data.temperature_stats
    && result.stats_data.temperature_stats.mean;
  if (!cell || !Number.isFinite(cell.average_temperature) || !Number.isFinite(mean)) {
    throw new Error('The live weather task returned no usable temperature tile.');
  }
  const offset = cell.average_temperature - mean;
  return baseSeries(date).map((value) => Math.round((value + offset) * 1000) / 1000);
}

function payload(site, date) {
  return {
    polygon_aoi: site.polygon,
    date_time: { start_date: date, filter_type: 3 },
    granularity: 100,
  };
}

async function fetchDay(site, date, onActivity) {
  const submitted = await submitHeatmap(payload(site, date));
  const activityId = submitted && submitted.data && submitted.data.activity_id;
  if (!activityId) throw new Error('The live weather task was not accepted.');
  if (onActivity) onActivity(activityId);
  const result = await waitForActivity(activityId);
  return readDailySeries(result, site, date);
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
  return Array.isArray(series[date]) && series[date].length > 0;
}

function completedDays(site) {
  return weather().dates.filter((date) => dayReady(site, date)).length;
}

function orderedDates() {
  const dates = weather().dates.slice();
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
  const total = weather().dates.length;
  updateProgress(siteId, {
    weatherSource: completed >= FIRST_DAYS ? 'live' : 'none',
    weatherStatus: stageFor(completed, total),
    weatherProgress: { completed, total },
  });
  return completed;
}

function saveDailySeries(siteId, date, daily) {
  const site = store.site(siteId);
  if (!site) return 0;
  const key = liveKey(site);
  const series = { ...(weather().series[key] || {}), [date]: daily };
  store.saveWeatherSeries(key, series);
  const completed = weather().dates.filter((item) => Array.isArray(series[item])).length;
  const total = weather().dates.length;
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

async function fetchDates(siteId, dates) {
  const site = store.site(siteId);
  if (!site) return 0;
  for (const date of dates) {
    const current = store.site(siteId);
    if (!current) return 0;
    if (dayReady(current, date)) continue;
    const daily = await fetchDay(current, date, (activityId) => updateProgress(siteId, {
      liveActivityId: activityId,
      liveActivityDate: date,
    }));
    saveDailySeries(siteId, date, daily);
  }
  const latest = store.site(siteId);
  return latest ? completedDays(latest) : 0;
}

async function resumePending(siteId) {
  const site = store.site(siteId);
  if (!site || !site.liveActivityId) return false;
  const date = site.liveActivityDate
    || orderedDates().find((item) => !dayReady(site, item));
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
  saveDailySeries(siteId, date, readDailySeries(result, current, date));
  return true;
}

function markFailure(siteId, error) {
  const site = store.site(siteId);
  if (!site) return;
  const completed = completedDays(site);
  const changes = {
    weatherStatus: completed ? 'partial' : 'error',
    weatherProgress: { completed, total: weather().dates.length },
  };
  if (error && error.code === 'activity_failed') {
    changes.liveActivityId = null;
    changes.liveActivityDate = null;
  }
  updateProgress(siteId, changes);
}

async function finishBackfill(siteId) {
  try {
    await fetchDates(siteId, orderedDates());
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
  setStage(siteId);
  try {
    await resumePending(siteId);
    await fetchDates(siteId, weather().dates.slice(-FIRST_DAYS));
    window.setTimeout(() => finishBackfill(siteId), 0);
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
    return await resumePending(siteId);
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
