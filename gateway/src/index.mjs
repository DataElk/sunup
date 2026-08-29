const DEFAULT_ORIGINS = [
  'https://dataelk.github.io',
  'http://127.0.0.1:8777',
  'http://localhost:8777',
];
const UPSTREAM_ORIGIN = 'https://api.fortyguard.com';
const MAX_BODY_BYTES = 32 * 1024;
const MAX_RING_POINTS = 24;
const MAX_AOI_AREA_KM2 = 25;

// The same state outline used by the browser map. A small tolerance permits the
// one-kilometre request buffer around a site selected beside the state line.
const ARIZONA_OUTER = [
  [-114.82, 31.33], [-114.47, 32.49], [-114.48, 34.72], [-114.12, 35.0],
  [-114.13, 37.0], [-109.04, 37.0], [-109.04, 31.33],
];
const ARIZONA_TOLERANCE_DEGREES = 0.02;

function allowedOrigins(env) {
  const configured = String(env.ALLOWED_ORIGINS || '').split(',')
    .map((item) => item.trim()).filter(Boolean);
  return new Set(configured.length ? configured : DEFAULT_ORIGINS);
}

function requestOrigin(request, env) {
  const origin = request.headers.get('Origin') || '';
  return allowedOrigins(env).has(origin) ? origin : '';
}

function responseHeaders(origin, extra = {}) {
  const headers = {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    ...extra,
  };
  if (origin) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers.Vary = 'Origin';
  }
  return headers;
}

function jsonResponse(payload, status, origin, extra = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: responseHeaders(origin, extra),
  });
}

function errorResponse(message, status, origin) {
  return jsonResponse({ error: true, message }, status, origin);
}

function corsPreflight(origin) {
  return new Response(null, {
    status: 204,
    headers: responseHeaders(origin, {
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '600',
    }),
  });
}

function pointInPolygon(point, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const crosses = (yi > point[1]) !== (yj > point[1])
      && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi;
    if (crosses) inside = !inside;
  }
  return inside;
}

function distanceToSegment(point, start, end) {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  if (dx === 0 && dy === 0) return Math.hypot(point[0] - start[0], point[1] - start[1]);
  const position = Math.max(0, Math.min(1,
    ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(
    point[0] - (start[0] + position * dx),
    point[1] - (start[1] + position * dy),
  );
}

function inArizonaOrBuffer([lng, lat]) {
  if (pointInPolygon([lng, lat], ARIZONA_OUTER)) return true;
  return ARIZONA_OUTER.some((start, index) => {
    const end = ARIZONA_OUTER[(index + 1) % ARIZONA_OUTER.length];
    return distanceToSegment([lng, lat], start, end) <= ARIZONA_TOLERANCE_DEGREES;
  });
}

function samePoint(left, right) {
  return left[0] === right[0] && left[1] === right[1];
}

function aoiAreaKm2(ring) {
  const lngs = ring.map((point) => point[0]);
  const lats = ring.map((point) => point[1]);
  const middleLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const width = (Math.max(...lngs) - Math.min(...lngs))
    * 111.32 * Math.cos(middleLat * Math.PI / 180);
  const height = (Math.max(...lats) - Math.min(...lats)) * 110.54;
  return width * height;
}

function phoenixDate() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Phoenix', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function validIsoDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

export function validateHeatmapPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return 'The request body must be a JSON object.';
  }
  const keys = Object.keys(payload).sort().join(',');
  if (keys !== 'date_time,granularity,polygon_aoi') {
    return 'Only Sunup heatmap fields are accepted.';
  }
  if (payload.granularity !== 100) {
    return 'Sunup live weather requires 100 metre granularity.';
  }
  const dateTime = payload.date_time;
  if (!dateTime || typeof dateTime !== 'object' || Array.isArray(dateTime)
      || Object.keys(dateTime).sort().join(',') !== 'filter_type,start_date'
      || dateTime.filter_type !== 3) {
    return 'Sunup live weather requires one daily filter type 3 request.';
  }
  if (!validIsoDate(dateTime.start_date) || dateTime.start_date > phoenixDate()) {
    return 'The weather date must be a valid Arizona date no later than today.';
  }

  const collection = payload.polygon_aoi;
  if (!collection || collection.type !== 'FeatureCollection'
      || !Array.isArray(collection.features) || collection.features.length !== 1) {
    return 'The request must contain exactly one GeoJSON feature.';
  }
  const geometry = collection.features[0] && collection.features[0].geometry;
  if (!geometry || geometry.type !== 'Polygon' || !Array.isArray(geometry.coordinates)
      || geometry.coordinates.length !== 1) {
    return 'The request must contain one polygon without holes.';
  }
  const ring = geometry.coordinates[0];
  if (!Array.isArray(ring) || ring.length < 4 || ring.length > MAX_RING_POINTS) {
    return `The polygon must contain 4 to ${MAX_RING_POINTS} points.`;
  }
  if (!ring.every((point) => Array.isArray(point) && point.length === 2
      && point.every(Number.isFinite))) {
    return 'Every polygon coordinate must be a finite longitude and latitude pair.';
  }
  if (!samePoint(ring[0], ring[ring.length - 1])) {
    return 'The polygon ring must be closed.';
  }
  if (!ring.every(inArizonaOrBuffer)) {
    return 'The requested area must be inside Arizona.';
  }
  if (aoiAreaKm2(ring) > MAX_AOI_AREA_KM2) {
    return `The requested area must not exceed ${MAX_AOI_AREA_KM2} square kilometres.`;
  }
  return '';
}

async function parseBody(request) {
  const length = Number(request.headers.get('Content-Length') || 0);
  if (length > MAX_BODY_BYTES) throw new Error('body_too_large');
  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) {
    throw new Error('body_too_large');
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error('invalid_json');
  }
}

async function withinLimit(binding, key) {
  if (!binding || typeof binding.limit !== 'function') return true;
  const result = await binding.limit({ key });
  return Boolean(result && result.success);
}

async function forward(path, options, env, origin, fetcher) {
  if (!env.FORTYGUARD_API_KEY) {
    return errorResponse('Live weather is not configured.', 503, origin);
  }
  let upstream;
  try {
    upstream = await fetcher(new URL(path, UPSTREAM_ORIGIN), {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'api-key': env.FORTYGUARD_API_KEY,
      },
    });
  } catch {
    return errorResponse('The live weather service could not be reached.', 502, origin);
  }
  const body = await upstream.text();
  const contentType = upstream.headers.get('Content-Type') || '';
  if (!contentType.toLowerCase().includes('application/json')) {
    return errorResponse('The live weather service returned an unreadable response.', 502, origin);
  }
  return new Response(body, {
    status: upstream.status,
    headers: responseHeaders(origin),
  });
}

function limiterKey(request, route) {
  const client = request.headers.get('CF-Connecting-IP') || 'unknown';
  return `${route}:${client}`;
}

export async function handleRequest(request, env, fetcher = fetch) {
  const url = new URL(request.url);
  const origin = requestOrigin(request, env);

  if (url.pathname === '/health' && request.method === 'GET') {
    return jsonResponse({ ok: true, configured: Boolean(env.FORTYGUARD_API_KEY) }, 200, origin);
  }
  if (!origin) return errorResponse('This origin is not allowed.', 403, '');
  if (request.method === 'OPTIONS') return corsPreflight(origin);

  if (url.pathname === '/v1/heatmap' && request.method === 'POST') {
    const contentType = request.headers.get('Content-Type') || '';
    if (!contentType.toLowerCase().startsWith('application/json')) {
      return errorResponse('Content-Type must be application/json.', 415, origin);
    }
    if (!await withinLimit(env.SUBMIT_LIMITER, limiterKey(request, 'submit'))) {
      return errorResponse('Too many weather submissions. Try again in one minute.', 429, origin);
    }
    let payload;
    try {
      payload = await parseBody(request);
    } catch (error) {
      const tooLarge = error && error.message === 'body_too_large';
      return errorResponse(tooLarge ? 'The request body is too large.' : 'The request body is not valid JSON.',
        tooLarge ? 413 : 400, origin);
    }
    const invalid = validateHeatmapPayload(payload);
    if (invalid) return errorResponse(invalid, 422, origin);
    return forward('/v1/heatmap', {
      method: 'POST', body: JSON.stringify(payload),
    }, env, origin, fetcher);
  }

  const status = url.pathname.match(/^\/v1\/status\/([A-Za-z0-9-]{3,80})$/);
  if (status && request.method === 'GET') {
    if (!await withinLimit(env.STATUS_LIMITER, limiterKey(request, 'status'))) {
      return errorResponse('Too many status checks. Try again in one minute.', 429, origin);
    }
    return forward(`/v1/status/${encodeURIComponent(status[1])}`, {
      method: 'GET',
    }, env, origin, fetcher);
  }

  return errorResponse('Route not found.', 404, origin);
}

export default {
  fetch(request, env) {
    return handleRequest(request, env);
  },
};
