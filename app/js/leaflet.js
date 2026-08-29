/* Shared Leaflet loading and Arizona site geometry. */

const ARIZONA_OUTER = [
  [-114.82, 31.33], [-114.47, 32.49], [-114.48, 34.72], [-114.12, 35.0],
  [-114.13, 37.0], [-109.04, 37.0], [-109.04, 31.33],
];
const LEAFLET_CSS_INTEGRITY = 'sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=';
const LEAFLET_JS_INTEGRITY = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';

let leafletPromise = null;

export function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (leafletPromise) return leafletPromise;
  leafletPromise = new Promise((resolve, reject) => {
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    stylesheet.integrity = LEAFLET_CSS_INTEGRITY;
    stylesheet.crossOrigin = 'anonymous';
    stylesheet.referrerPolicy = 'no-referrer';
    document.head.appendChild(stylesheet);
    const script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.integrity = LEAFLET_JS_INTEGRITY;
    script.crossOrigin = 'anonymous';
    script.referrerPolicy = 'no-referrer';
    script.onload = () => resolve(window.L);
    script.onerror = () => reject(new Error('The map library could not be loaded.'));
    document.head.appendChild(script);
  });
  return leafletPromise;
}

export function isWithinArizona(point) {
  const x = point.lng;
  const y = point.lat;
  let inside = false;
  for (let i = 0, j = ARIZONA_OUTER.length - 1; i < ARIZONA_OUTER.length; j = i, i += 1) {
    const [xi, yi] = ARIZONA_OUTER[i];
    const [xj, yj] = ARIZONA_OUTER[j];
    const crosses = ((yi > y) !== (yj > y))
      && (x < ((xj - xi) * (y - yi) / (yj - yi)) + xi);
    if (crosses) inside = !inside;
  }
  return inside;
}

export function sitePoint(site) {
  if (site && site.location) return site.location;
  const meta = window.SUNUP_WEATHER && window.SUNUP_WEATHER.siteMeta;
  return (site && meta && meta[site.seriesKey]) || null;
}

export function pointFeature(point) {
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[
      [point.lng - 0.002, point.lat - 0.002], [point.lng + 0.002, point.lat - 0.002],
      [point.lng + 0.002, point.lat + 0.002], [point.lng - 0.002, point.lat + 0.002],
      [point.lng - 0.002, point.lat - 0.002],
    ]] } }],
  };
}

export function polygonCentre(polygon) {
  const coordinates = polygon && polygon.features && polygon.features[0]
    && polygon.features[0].geometry && polygon.features[0].geometry.coordinates[0];
  if (!coordinates || !coordinates.length) return null;
  const points = coordinates.slice(0, -1);
  const totals = points.reduce((acc, point) => ({ lng: acc.lng + point[0], lat: acc.lat + point[1] }),
    { lng: 0, lat: 0 });
  return { lng: totals.lng / points.length, lat: totals.lat / points.length };
}
