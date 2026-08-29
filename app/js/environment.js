/* Live environmental composition for one site-day. */

import { CONSTANTS } from './engine.js';

const K = CONSTANTS.environment;
const ZERO_C_K = 273.15;
const EDGE_DISCARD_M = 500;
const AOI_BUFFER_M = 1000;

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function median(values) {
  const ordered = values.slice().sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2
    ? ordered[middle]
    : (ordered[middle - 1] + ordered[middle]) / 2;
}

function normalise(values) {
  const low = Math.min(...values);
  const high = Math.max(...values);
  if (high <= low) return values.map(() => 0.5);
  return values.map((value) => (value - low) / (high - low));
}

function warpedMean(values, gamma) {
  return values.reduce((sum, value) => sum + (value > 0 ? value ** gamma : 0), 0)
    / values.length;
}

function solveWarp(values, target) {
  let [low, high] = K.diurnalWarpGammaBounds;
  if (warpedMean(values, low) < target) return low;
  if (warpedMean(values, high) > target) return high;
  for (let index = 0; index < 200 && high - low >= 1e-9; index += 1) {
    const middle = (low + high) / 2;
    if (warpedMean(values, middle) > target) low = middle;
    else high = middle;
  }
  return (low + high) / 2;
}

export function reconstructDryBulb(shape, dailyMin, dailyMean, dailyMax) {
  if (!Array.isArray(shape) || shape.length !== 24) {
    throw new Error('Hourly temperature shape must contain 24 values.');
  }
  if (!(dailyMin <= dailyMean && dailyMean <= dailyMax)) {
    throw new Error('The live temperature tile returned unordered daily values.');
  }
  const amplitude = dailyMax - dailyMin;
  if (amplitude === 0) return shape.map(() => dailyMean);
  const scaled = normalise(shape);
  const target = (dailyMean - dailyMin) / amplitude;
  const gamma = solveWarp(scaled, target);
  return scaled.map((value) => dailyMin + (value > 0 ? value ** gamma : 0) * amplitude);
}

function complete(values) {
  return Array.isArray(values) && values.length === 24
    && values.every((value) => Number.isFinite(value));
}

export function parseOpenMeteoDays(payload) {
  const hourly = payload && payload.hourly;
  const times = hourly && hourly.time;
  const fields = {
    temperature: hourly && hourly.temperature_2m,
    humidity: hourly && hourly.relative_humidity_2m,
    wetBulb: hourly && hourly.wet_bulb_temperature_2m,
    ghi: hourly && hourly.shortwave_radiation,
    wind10m: hourly && hourly.wind_speed_10m,
    cloud: hourly && hourly.cloud_cover,
  };
  if (!Array.isArray(times) || !times.length) {
    throw new Error('Regional hourly weather returned no timestamps.');
  }
  const days = {};
  times.forEach((time, index) => {
    const date = String(time).slice(0, 10);
    if (!days[date]) {
      days[date] = {
        date, temperature: [], humidity: [], wetBulb: [], ghi: [],
        wind10m: [], cloud: [], elevationM: Number(payload.elevation) || 0,
        utcOffsetHours: Number(payload.utc_offset_seconds) / 3600 || 0,
      };
    }
    for (const [name, values] of Object.entries(fields)) {
      days[date][name].push(Number(values && values[index]));
    }
  });
  for (const [date, day] of Object.entries(days)) {
    for (const name of Object.keys(fields)) {
      if (!complete(day[name])) {
        throw new Error(`Regional hourly weather is incomplete for ${date} (${name}).`);
      }
    }
    day.cloud = day.cloud.map((value) => clamp(value / 100, 0, 1));
  }
  return days;
}

function ringOf(feature) {
  const geometry = feature && feature.geometry;
  if (!geometry || geometry.type !== 'Polygon') return null;
  return geometry.coordinates && geometry.coordinates[0];
}

function centreOf(feature) {
  const ring = ringOf(feature);
  if (!ring || !ring.length) return null;
  const points = ring.length > 1
    && ring[0][0] === ring[ring.length - 1][0]
    && ring[0][1] === ring[ring.length - 1][1]
    ? ring.slice(0, -1) : ring;
  const sum = points.reduce((acc, point) => ({
    lng: acc.lng + point[0], lat: acc.lat + point[1],
  }), { lng: 0, lat: 0 });
  return { lng: sum.lng / points.length, lat: sum.lat / points.length };
}

function boundsOf(featureCollection, fallback) {
  const points = [];
  for (const feature of (featureCollection && featureCollection.features) || []) {
    const ring = ringOf(feature);
    if (ring) points.push(...ring);
  }
  if (!points.length) {
    return { minLng: fallback.lng, maxLng: fallback.lng,
      minLat: fallback.lat, maxLat: fallback.lat };
  }
  return {
    minLng: Math.min(...points.map((point) => point[0])),
    maxLng: Math.max(...points.map((point) => point[0])),
    minLat: Math.min(...points.map((point) => point[1])),
    maxLat: Math.max(...points.map((point) => point[1])),
  };
}

function pointInRing(point, ring) {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length;
       previous = index, index += 1) {
    const [xi, yi] = ring[index];
    const [xj, yj] = ring[previous];
    const crosses = ((yi > point.lat) !== (yj > point.lat))
      && (point.lng < ((xj - xi) * (point.lat - yi) / (yj - yi)) + xi);
    if (crosses) inside = !inside;
  }
  return inside;
}

function distanceM(a, b) {
  const latitude = ((a.lat + b.lat) / 2) * Math.PI / 180;
  const x = (a.lng - b.lng) * Math.cos(latitude) * 111320;
  const y = (a.lat - b.lat) * 110540;
  return Math.hypot(x, y);
}

function distanceToBoundsM(point, bounds) {
  const latitude = point.lat * Math.PI / 180;
  const longitudeScale = Math.cos(latitude) * 111320;
  return Math.min(
    (point.lng - bounds.minLng) * longitudeScale,
    (bounds.maxLng - point.lng) * longitudeScale,
    (point.lat - bounds.minLat) * 110540,
    (bounds.maxLat - point.lat) * 110540,
  );
}

export function bufferedAoi(site) {
  const location = site.location;
  const bounds = boundsOf(site.polygon, location);
  const centreLat = (bounds.minLat + bounds.maxLat) / 2;
  const latPad = AOI_BUFFER_M / 110540;
  const lngPad = AOI_BUFFER_M / (111320 * Math.cos(centreLat * Math.PI / 180));
  const minLng = bounds.minLng - lngPad;
  const maxLng = bounds.maxLng + lngPad;
  const minLat = bounds.minLat - latPad;
  const maxLat = bounds.maxLat + latPad;
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: {}, geometry: {
      type: 'Polygon', coordinates: [[
        [minLng, minLat], [maxLng, minLat], [maxLng, maxLat], [minLng, maxLat],
        [minLng, minLat],
      ]],
    } }],
  };
}

function readableCell(feature) {
  const properties = feature && feature.properties;
  if (!properties) return null;
  const cell = {
    min: Number(properties.min_temperature),
    mean: Number(properties.average_temperature),
    max: Number(properties.max_temperature),
    centre: centreOf(feature),
  };
  return Number.isFinite(cell.min) && Number.isFinite(cell.mean)
    && Number.isFinite(cell.max) && cell.centre ? cell : null;
}

export function selectSiteCell(result, site, queryAoi = bufferedAoi(site)) {
  const features = result && result.map_data && result.map_data.features;
  const cells = (features || []).map(readableCell).filter(Boolean);
  if (!cells.length) throw new Error('The live weather task returned no usable temperature tile.');

  const queryBounds = boundsOf(queryAoi, site.location);
  const interior = cells.filter((cell) => distanceToBoundsM(cell.centre, queryBounds)
    >= EDGE_DISCARD_M);
  if (!interior.length) {
    throw new Error('No weather cell remains after the request-edge safety filter. Use a larger site area and retry.');
  }

  if (site.geometryMode === 'boundary') {
    const ring = site.polygon && site.polygon.features
      && ringOf(site.polygon.features[0]);
    const within = ring ? interior.filter((cell) => pointInRing(cell.centre, ring)) : [];
    if (within.length) {
      return {
        min: median(within.map((cell) => cell.min)),
        mean: median(within.map((cell) => cell.mean)),
        max: median(within.map((cell) => cell.max)),
        cellsUsed: within.length,
      };
    }
    throw new Error('No safe weather cell falls inside this boundary. Draw a larger boundary or use a point.');
  }

  const nearest = interior.reduce((best, cell) => (
    !best || distanceM(cell.centre, site.location) < distanceM(best.centre, site.location)
      ? cell : best
  ), null);
  return { min: nearest.min, mean: nearest.mean, max: nearest.max, cellsUsed: 1 };
}

function stationPressure(elevationM) {
  const factor = 1 - K.isaLapseCoeff * elevationM;
  return K.isaSeaLevelPressurePa * factor ** K.isaLapseExponent;
}

function saturationVapourPressure(temperatureC) {
  return K.magnusAKpa * Math.exp(K.magnusB * temperatureC
    / (temperatureC + K.magnusC));
}

function skyEmissivity(temperatureC, humidityPct, cloudFraction) {
  const vapourHpa = clamp(humidityPct, 0, 100) / 100
    * saturationVapourPressure(temperatureC) * 10;
  const clear = clamp(K.brutsaertA
    * (vapourHpa / (temperatureC + ZERO_C_K)) ** K.brutsaertExponent, 0, 1);
  return clear + (1 - clear) * clamp(cloudFraction, 0, 1);
}

function windAtGlobe(speed) {
  const ratio = Math.log(K.globeHeightM / K.surfaceRoughnessLengthM)
    / Math.log(K.windMeasurementHeightM / K.surfaceRoughnessLengthM);
  return Math.max(speed * ratio, 0);
}

function convectiveCoefficient(temperatureC, speed, pressurePa) {
  const temperatureK = temperatureC + ZERO_C_K;
  const density = pressurePa / (K.airGasConstantJKgK * temperatureK);
  const viscosity = K.airSutherlandMu0PaS
    * ((K.airSutherlandT0K + K.airSutherlandSK) / (temperatureK + K.airSutherlandSK))
    * (temperatureK / K.airSutherlandT0K) ** 1.5;
  const kinematic = viscosity / density;
  const conductivity = K.airConductivityRefWMK
    * (temperatureK / K.airConductivityRefTK) ** K.airConductivityExponent;
  const reynolds = Math.max(speed, K.minAirSpeedMS) * K.globeDiameterM / kinematic;
  const nusselt = K.ranzMarshallA + K.ranzMarshallB * Math.sqrt(reynolds)
    * K.airPrandtl ** (1 / 3);
  return nusselt * conductivity / K.globeDiameterM;
}

function globeTemperature(airC, humidityPct, speed, dni, dhi, ghi, cloud, elevationM) {
  const pressure = stationPressure(elevationM);
  const sphereShortwave = Math.max(dni, 0) / 4 + Math.max(dhi, 0) / 2
    + K.groundAlbedo * Math.max(ghi, 0) / 2;
  const convection = convectiveCoefficient(airC, speed, pressure);
  const sky = skyEmissivity(airC, humidityPct, cloud);
  const airK = airC + ZERO_C_K;
  const environment = 0.5
    * (sky + K.groundEmissivity + (1 - K.groundEmissivity) * sky) * airK ** 4;
  const absorbed = K.globeSolarAbsorptivity * sphereShortwave;
  const emission = K.globeEmissivity * K.stefanBoltzmann;
  const residual = (globeK) => absorbed + emission * (environment - globeK ** 4)
    - convection * (globeK - airK);
  let low = airK - 40;
  let high = airK + 120;
  for (let index = 0; index < 200 && high - low > 1e-6; index += 1) {
    const middle = (low + high) / 2;
    if (residual(middle) > 0) low = middle;
    else high = middle;
  }
  return (low + high) / 2 - ZERO_C_K;
}

function dayOfYear(date) {
  const [year, month, day] = date.split('-').map(Number);
  return Math.floor((Date.UTC(year, month - 1, day) - Date.UTC(year, 0, 1)) / 86400000) + 1;
}

function solarCosZenith(date, hour, location, utcOffsetHours) {
  const gamma = (2 * Math.PI / 365) * (dayOfYear(date) - 1 + (hour - 12) / 24);
  const equation = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma)
    - 0.032077 * Math.sin(gamma) - 0.014615 * Math.cos(2 * gamma)
    - 0.040849 * Math.sin(2 * gamma));
  const declination = 0.006918 - 0.399912 * Math.cos(gamma)
    + 0.070257 * Math.sin(gamma) - 0.006758 * Math.cos(2 * gamma)
    + 0.000907 * Math.sin(2 * gamma) - 0.002697 * Math.cos(3 * gamma)
    + 0.00148 * Math.sin(3 * gamma);
  const timeOffset = equation + 4 * location.lng - 60 * utcOffsetHours;
  const hourAngle = (hour * 60 + timeOffset) / 4 - 180;
  const latitude = location.lat * Math.PI / 180;
  const angle = hourAngle * Math.PI / 180;
  return Math.max(Math.sin(latitude) * Math.sin(declination)
    + Math.cos(latitude) * Math.cos(declination) * Math.cos(angle), 0);
}

function diffuseFraction(cosZenith) {
  if (cosZenith <= 0) return 1;
  const ghi = K.haurwitzA * cosZenith * Math.exp(-K.haurwitzB / cosZenith);
  const airMass = 1 / cosZenith;
  const dni = K.solarConstantWM2 * K.meinelTau ** (airMass ** K.meinelAmExponent);
  return clamp((ghi - dni * cosZenith) / ghi, 0, 1);
}

function splitSolar(driver, location, hour) {
  const ghi = driver.ghi[hour];
  const cosZenith = solarCosZenith(
    driver.date, hour, location, driver.utcOffsetHours,
  );
  let dhi = ghi * diffuseFraction(cosZenith);
  const dni = cosZenith > 0
    ? Math.min((ghi - dhi) / cosZenith, K.solarConstantWM2) : 0;
  dhi = Math.max(ghi - dni * cosZenith, 0);
  return { ghi, dni, dhi };
}

export function buildWbgtSeries(cell, driver, location) {
  const dryBulb = cell
    ? reconstructDryBulb(driver.temperature, cell.min, cell.mean, cell.max)
    : driver.temperature.slice();
  return dryBulb.map((airC, hour) => {
    const wind = windAtGlobe(driver.wind10m[hour]);
    const solar = splitSolar(driver, location, hour);
    const globe = globeTemperature(
      airC, driver.humidity[hour], wind, solar.dni, solar.dhi,
      solar.ghi, driver.cloud[hour], driver.elevationM,
    );
    const weights = solar.ghi > 0
      ? K.wbgtOutdoorWeights : K.wbgtIndoorWeights;
    const value = weights[0] * driver.wetBulb[hour]
      + weights[1] * globe + weights[2] * airC;
    return Math.round(value * 1e6) / 1e6;
  });
}
