/* ============================================================================
   Browser-only FortyGuard access.

   A credential belongs to this browser, not to the roster export or any served
   asset. Calls are deliberately opt-in: every consumer must check
   `hasConfiguredKey()` before it submits work.
   ========================================================================== */

const KEY_STORAGE = 'acclimate.weather.access.v1';

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
  const response = await request('/v1/heatmap', {
    method: 'POST', body: JSON.stringify(payload),
  });
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
