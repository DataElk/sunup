/* Live site history, fetched five days first and backfilled in the background. */

import * as store from './store.js';
import * as compute from './compute.js';
import { activityStatus, hasConfiguredKey, submitHeatmap, waitForActivity } from './liveweather.js';

const FIRST_DAYS = 5;

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

async function fetchDates(siteId, dates, completed, total) {
  const site = store.site(siteId);
  if (!site) return completed;
  const key = site.seriesKey || `live_${site.id}`;
  const series = weather().series[key] || {};
  for (const date of dates) {
    const current = store.site(siteId);
    if (!current) return completed;
    const daily = await fetchDay(current, date, (activityId) => updateProgress(siteId, {
      liveActivityId: activityId,
    }));
    series[date] = daily;
    weather().series[key] = series;
    completed += 1;
    updateProgress(siteId, {
      seriesKey: key,
      weatherSource: completed >= FIRST_DAYS ? 'live' : 'none',
      weatherStatus: completed >= FIRST_DAYS
        ? (completed === total ? 'complete' : 'backfill') : 'loading',
      weatherProgress: { completed, total },
      liveActivityId: null,
    });
    compute.invalidate();
  }
  return completed;
}

export async function startSiteBackfill(siteId) {
  if (!hasConfiguredKey()) return false;
  const site = store.site(siteId);
  if (!site || !site.polygon || !site.location) return false;
  const dates = weather().dates.slice();
  const first = dates.slice(-FIRST_DAYS);
  const remaining = dates.slice(0, -FIRST_DAYS);
  updateProgress(siteId, {
    weatherStatus: 'loading', weatherProgress: { completed: 0, total: dates.length },
  });
  try {
    const completed = await fetchDates(siteId, first, 0, dates.length);
    window.setTimeout(async () => {
      try {
        await fetchDates(siteId, remaining, completed, dates.length);
      } catch {
        updateProgress(siteId, { weatherStatus: 'partial' });
      }
    }, 0);
    return true;
  } catch {
    updateProgress(siteId, { weatherStatus: 'error', liveActivityId: null });
    return false;
  }
}

export async function resumeSiteActivity(siteId) {
  const site = store.site(siteId);
  if (!site || !site.liveActivityId) return false;
  const response = await activityStatus(site.liveActivityId);
  return Boolean(response && response.data);
}
