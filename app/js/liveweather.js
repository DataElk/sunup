/* ============================================================================
   Protected live-weather access.

   The browser calls Sunup's narrow weather gateway. The upstream credential is
   held by the gateway and is never stored in, sent by, or returned to the app.
   ========================================================================== */

const REQUEST_TIMEOUT_MS = 60000;
const ACTIVITY_TIMEOUT_MS = 12 * 60 * 1000;
const POLL_INTERVAL_MS = 3000;
const LEGACY_KEY_STORAGE = 'sunup.weather.access.v1';

// Earlier builds stored a personal credential in this browser. It is obsolete
// once all live requests use the protected gateway, so remove it on upgrade.
try {
  localStorage.removeItem(LEGACY_KEY_STORAGE);
} catch {
  // Storage can be blocked without affecting public gateway access.
}

export function gatewayUrl() {
  const configured = String(
    window.SUNUP_CONFIG && window.SUNUP_CONFIG.weatherGateway || '',
  ).trim().replace(/\/+$/, '');
  if (!configured) return '';
  try {
    const url = new URL(configured);
    const local = ['localhost', '127.0.0.1'].includes(url.hostname);
    return url.protocol === 'https:' || (local && url.protocol === 'http:')
      ? url.toString().replace(/\/+$/, '') : '';
  } catch {
    return '';
  }
}

function endpoint(path) {
  const base = gatewayUrl();
  if (!base) throw new Error('Public live weather is not configured.');
  return new URL(path, `${base}/`).toString();
}

async function request(path, options = {}) {
  let response;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    response = await fetch(endpoint(path), {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new Error('The live weather request timed out. Try again to resume it.');
    }
    throw new Error('The live weather service could not be reached.');
  } finally {
    window.clearTimeout(timeout);
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error('The live weather service returned an unreadable response.');
  }

  if (!response.ok) {
    const message = payload && typeof payload.message === 'string'
      ? payload.message : `Live weather request failed (${response.status}).`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload;
}

export function hasLiveAccess() {
  return Boolean(gatewayUrl());
}

export async function testLiveAccess() {
  const response = await request('/health');
  if (!response || response.ok !== true || response.configured !== true) {
    throw new Error('Public live weather is not ready.');
  }
  return true;
}

export async function submitHeatmap(payload) {
  return request('/v1/heatmap', { method: 'POST', body: JSON.stringify(payload) });
}

export async function activityStatus(activityId) {
  return request(`/v1/status/${encodeURIComponent(activityId)}`);
}

export async function waitForActivity(activityId, onPoll, options = {}) {
  const timeoutMs = options.timeoutMs || ACTIVITY_TIMEOUT_MS;
  const startedAt = Date.now();
  let errors = 0;
  for (;;) {
    if (Date.now() - startedAt >= timeoutMs) {
      const error = new Error(
        'The live weather task is still processing. Retry later to resume the same task.');
      error.code = 'activity_timeout';
      error.activityId = activityId;
      throw error;
    }
    try {
      const response = await activityStatus(activityId);
      errors = 0;
      const data = response && response.data;
      const status = String(data && data.status || '').toLowerCase();
      if (onPoll) onPoll(status);
      if (status === 'completed' || status === 'succeeded') return data.result;
      if (status === 'failed') {
        const error = new Error('The live weather task failed.');
        error.code = 'activity_failed';
        throw error;
      }
    } catch (error) {
      if (error && error.code === 'activity_failed') throw error;
      errors += 1;
      if (errors > 3) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

export async function fetchRegionalWeather(location, startDate, endDate) {
  if (!hasLiveAccess()) throw new Error('Live weather is not configured.');
  const url = new URL('https://api.open-meteo.com/v1/forecast');
  url.searchParams.set('latitude', String(location.lat));
  url.searchParams.set('longitude', String(location.lng));
  url.searchParams.set('start_date', startDate);
  url.searchParams.set('end_date', endDate);
  url.searchParams.set('timezone', 'America/Phoenix');
  url.searchParams.set('wind_speed_unit', 'ms');
  url.searchParams.set('hourly', [
    'temperature_2m', 'relative_humidity_2m', 'wet_bulb_temperature_2m',
    'shortwave_radiation', 'wind_speed_10m', 'cloud_cover',
  ].join(','));
  let response;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    response = await fetch(url, { signal: controller.signal });
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new Error('Regional hourly weather timed out. Try again shortly.');
    }
    throw new Error('Regional hourly weather could not be reached.');
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    throw new Error(`Regional hourly weather failed (${response.status}).`);
  }
  const payload = await response.json();
  const units = payload && payload.hourly_units;
  if (!units || units.wind_speed_10m !== 'm/s'
      || units.temperature_2m !== '°C'
      || units.shortwave_radiation !== 'W/m²') {
    throw new Error('Regional hourly weather returned unexpected units.');
  }
  return payload;
}
