import assert from 'node:assert/strict';
import test from 'node:test';
import { handleRequest, validateHeatmapPayload } from '../src/index.mjs';

const ORIGIN = 'https://dataelk.github.io';
const SECRET = 'unit-test-only-secret';
const env = {
  ALLOWED_ORIGINS: ORIGIN,
  FORTYGUARD_API_KEY: SECRET,
};

function payload(overrides = {}) {
  return {
    polygon_aoi: {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature', properties: {}, geometry: {
          type: 'Polygon', coordinates: [[
            [-112.085, 33.44], [-112.065, 33.44], [-112.065, 33.46],
            [-112.085, 33.46], [-112.085, 33.44],
          ]],
        },
      }],
    },
    date_time: { start_date: '2024-07-15', filter_type: 3 },
    granularity: 100,
    ...overrides,
  };
}

function browserRequest(path, options = {}) {
  return new Request(`https://gateway.example${path}`, {
    ...options,
    headers: {
      Origin: ORIGIN,
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
}

test('health reports configuration without exposing the credential', async () => {
  const response = await handleRequest(browserRequest('/health'), env);
  assert.equal(response.status, 200);
  const text = await response.text();
  assert.deepEqual(JSON.parse(text), { ok: true, configured: true });
  assert.equal(text.includes(SECRET), false);
});

test('a valid request is constrained and authenticated upstream', async () => {
  let forwarded;
  const fetcher = async (url, options) => {
    forwarded = { url: String(url), options };
    return Response.json({ data: { activity_id: 'activity-123' } });
  };
  const response = await handleRequest(browserRequest('/v1/heatmap', {
    method: 'POST', body: JSON.stringify(payload()),
  }), env, fetcher);
  assert.equal(response.status, 200);
  assert.equal(forwarded.url, 'https://api.fortyguard.com/v1/heatmap');
  assert.equal(forwarded.options.headers['api-key'], SECRET);
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), ORIGIN);
  assert.equal((await response.text()).includes(SECRET), false);
});

test('status polling accepts only a bounded activity id', async () => {
  let path = '';
  const fetcher = async (url, options) => {
    path = `${new URL(url).pathname}:${options.method}`;
    return Response.json({ data: { status: 'Processing' } });
  };
  const response = await handleRequest(browserRequest('/v1/status/abc-123'), env, fetcher);
  assert.equal(response.status, 200);
  assert.equal(path, '/v1/status/abc-123:GET');
  const rejected = await handleRequest(browserRequest('/v1/status/a%2Fb'), env, fetcher);
  assert.equal(rejected.status, 404);
});

test('untrusted origins and unknown routes never reach upstream', async () => {
  let calls = 0;
  const fetcher = async () => { calls += 1; return Response.json({}); };
  const request = new Request('https://gateway.example/v1/heatmap', {
    method: 'POST',
    headers: { Origin: 'https://attacker.example', 'Content-Type': 'application/json' },
    body: JSON.stringify(payload()),
  });
  assert.equal((await handleRequest(request, env, fetcher)).status, 403);
  assert.equal((await handleRequest(browserRequest('/v1/anything'), env, fetcher)).status, 404);
  assert.equal(calls, 0);
});

test('payload validation rejects expanded, future, and non-Arizona work', () => {
  assert.equal(validateHeatmapPayload(payload()), '');
  assert.match(validateHeatmapPayload(payload({ granularity: 60 })), /100 metre/);
  assert.match(validateHeatmapPayload(payload({
    date_time: { start_date: '2999-01-01', filter_type: 3 },
  })), /no later than today/);
  assert.match(validateHeatmapPayload(payload({
    date_time: { start_date: '2024-07-15', filter_type: 1 },
  })), /filter type 3/);
  const outside = payload();
  outside.polygon_aoi.features[0].geometry.coordinates[0] = [
    [-118.3, 34.0], [-118.2, 34.0], [-118.2, 34.1],
    [-118.3, 34.1], [-118.3, 34.0],
  ];
  assert.match(validateHeatmapPayload(outside), /inside Arizona/);
});

test('rate limits are enforced without contacting FortyGuard', async () => {
  let calls = 0;
  const limited = {
    ...env,
    SUBMIT_LIMITER: { limit: async () => ({ success: false }) },
  };
  const response = await handleRequest(browserRequest('/v1/heatmap', {
    method: 'POST', body: JSON.stringify(payload()),
  }), limited, async () => { calls += 1; return Response.json({}); });
  assert.equal(response.status, 429);
  assert.equal(calls, 0);
});
