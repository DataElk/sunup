import { readFileSync } from 'node:fs';

globalThis.window = globalThis;
(0, eval)(readFileSync('app/data/constants.js', 'utf8'));

const environment = await import('../app/js/environment.js');

function resultOf(payload) {
  return payload?.data?.result || payload?.result || payload?.data || payload;
}

const fortyGuard = resultOf(JSON.parse(readFileSync(
  'fixtures/heatmap/phoenix_singleday_filter3_raw.json', 'utf8')));
const openMeteo = JSON.parse(readFileSync(
  'fixtures/openmeteo/33.4484_-112.0740_2024-07-15.json', 'utf8'));
const site = {
  location: { lng: -112.0740, lat: 33.4484 },
  polygon: null,
  geometryMode: 'point',
};
const queryAoi = environment.bufferedAoi(site);
const cell = environment.selectSiteCell(fortyGuard, site, queryAoi);
const driver = environment.parseOpenMeteoDays(openMeteo)['2024-07-15'];
const series = environment.buildWbgtSeries(cell, driver, site.location);

function square(lng, lat, value) {
  const d = 0.0002;
  return { type: 'Feature', properties: {
    min_temperature: value - 5,
    average_temperature: value,
    max_temperature: value + 5,
  }, geometry: { type: 'Polygon', coordinates: [[
    [lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d],
    [lng - d, lat + d], [lng - d, lat - d],
  ]] } };
}

const boundarySite = {
  location: { lng: 0.015, lat: 0.015 },
  geometryMode: 'boundary',
  polygon: { type: 'FeatureCollection', features: [{
    type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[
      [0, 0], [0.03, 0], [0.03, 0.03], [0, 0.03], [0, 0],
    ]] },
  }] },
};
const boundaryResult = { map_data: { features: [
  square(0.002, 0.002, 1000), square(0.01, 0.01, 15), square(0.02, 0.02, 25),
] } };
const outerAoi = { type: 'FeatureCollection', features: [{
  type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[
    [0, 0], [0.04, 0], [0.04, 0.04], [0, 0.04], [0, 0],
  ]] },
}] };
const boundaryCell = environment.selectSiteCell(boundaryResult, boundarySite, outerAoi);

const edgeOnlyAoi = { type: 'FeatureCollection', features: [{
  type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[
    [0, 0], [0.003, 0], [0.003, 0.003], [0, 0.003], [0, 0],
  ]] },
}] };
let noInteriorError = '';
try {
  environment.selectSiteCell({ map_data: { features: [square(0.0015, 0.0015, 20)] } },
    { location: { lng: 0.0015, lat: 0.0015 }, geometryMode: 'point' }, edgeOnlyAoi);
} catch (error) {
  noInteriorError = error.message;
}

const emptyBoundarySite = {
  location: { lng: 0.035, lat: 0.035 },
  geometryMode: 'boundary',
  polygon: { type: 'FeatureCollection', features: [{
    type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[
      [0.032, 0.032], [0.038, 0.032], [0.038, 0.038], [0.032, 0.038], [0.032, 0.032],
    ]] },
  }] },
};
let noBoundaryCellError = '';
try {
  environment.selectSiteCell(boundaryResult, emptyBoundarySite, outerAoi);
} catch (error) {
  noBoundaryCellError = error.message;
}

process.stdout.write(JSON.stringify({
  cell, series, boundaryCell, noInteriorError, noBoundaryCellError,
}));
