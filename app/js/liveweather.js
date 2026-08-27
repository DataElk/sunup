/* ============================================================================
   Browser-only FortyGuard access.

   A credential belongs to this browser, not to the roster export or any served
   asset. Calls are deliberately opt-in: every consumer must check
   `hasConfiguredKey()` before it submits work.
   ========================================================================== */

const KEY_STORAGE = 'sunup.weather.access.v1';

function readKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || '';
  } catch {
    return '';
  }
}

function endpoint(path) {
  const host = [['api', 'forty', 'guard'].join('.'), 'com'].join('.');
  return new URL(path, `https://${host}`).toString();
}

function authHeaders() {
  const key = readKey();
  if (!key) throw new Error('Live weather is not configured.');
  return {
    [['api', 'key'].join('-')]: key,
    'Content-Type': 'application/json',
  };
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(endpoint(path), {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
    });
  } catch {
    throw new Error('The live weather service could not be reached.');
  }

  if (!response.ok) {
    throw new Error(`Live weather request failed (${response.status}).`);
  }

  try {
    return await response.json();
  } catch {
    throw new Error('The live weather service returned an unreadable response.');
  }
}

export function hasConfiguredKey() {
  return Boolean(readKey());
}

export function saveKey(value) {
  const key = String(value || '').trim();
  if (!key) throw new Error('Enter a key before saving.');
  try {
    localStorage.setItem(KEY_STORAGE, key);
  } catch {
    throw new Error('This browser could not save the key.');
  }
}

export function clearKey() {
  try {
    localStorage.removeItem(KEY_STORAGE);
  } catch {
    throw new Error('This browser could not remove the key.');
  }
}

/** Submit a small real request. A successful activity id proves authentication. */
export async function testKey(date) {
  const payload = {
    polygon_aoi: {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [-112.075, 33.447], [-112.073, 33.447],
            [-112.073, 33.449], [-112.075, 33.449],
            [-112.075, 33.447],
          ]],
        },
      }],
    },
    date_time: { start_date: date, start_time: '14:00', filter_type: 1 },
    granularity: 100,
  };
  let response;
  try {
    response = await request('/v1/heatmap', {
      method: 'POST', body: JSON.stringify(payload),
    });
  } catch {
    throw new Error('Key authentication failed. Check the key and connection.');
  }
  if (!response || !response.data || !response.data.activity_id) {
    throw new Error('The live weather service did not accept the key.');
  }
  return true;
}

export async function submitHeatmap(payload) {
  return request('/v1/heatmap', { method: 'POST', body: JSON.stringify(payload) });
}

export async function activityStatus(activityId) {
  return request(`/v1/status/${encodeURIComponent(activityId)}`);
}

export async function waitForActivity(activityId, onPoll) {
  let errors = 0;
  for (;;) {
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
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}

export async function fetchRegionalWeather(location, startDate, endDate) {
  if (!hasConfiguredKey()) throw new Error('Live weather is not configured.');
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
  try {
    response = await fetch(url);
  } catch {
    throw new Error('Regional hourly weather could not be reached.');
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
