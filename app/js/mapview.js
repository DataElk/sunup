/* ============================================================================
   The map, as a selection surface.

   It used to be a picture. Now it is the spatial index into the same tree: site
   polygons and crew markers over the exceedance layer, and clicking a crew
   opens it. A marker carries its crew's WORST current status, so the hot site
   reads as hot before anything is clicked.

   Crews share their site's coordinates, so several crews at one site are fanned
   around the site point rather than stacked on it. The fan is a drawing device,
   not a location claim, and the site dot stays where the site actually is.

   Classing, basemap and the resolution note are unchanged from the earlier
   build: quantile classes from build_map_data.py, an OpenStreetMap locator
   layer cached at build time, and no tiles at render time.
   ========================================================================== */

import * as store from './store.js';
import * as compute from './compute.js';
import { el } from './ui.js';

const HEAT_STEPS = ['--heat-0', '--heat-1', '--heat-2', '--heat-3', '--heat-4', '--heat-5'];

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function classify(value, breaks) {
  let k = 0;
  while (k < breaks.length && value >= breaks[k]) k += 1;
  return k;
}

const STATUS_TOKEN = {
  stop: '--status-stop', restricted: '--status-restricted',
  reduced: '--status-reduced', cleared: '--status-cleared',
};

/** Where each crew marker sits, in canvas pixels. Also the hit-test table. */
function layout(mapData, width, height) {
  const { west, south, east, north } = mapData.bounds;
  const meta = window.ACCLIMATE_WEATHER.siteMeta;
  const spots = [];

  for (const site of store.sites()) {
    const key = site.seriesKey;
    const point = meta[key] || meta[Object.keys(meta)[0]];
    if (!point) continue;
    const px = ((point.lon - west) / (east - west)) * width;
    const py = ((north - point.lat) / (north - south)) * height;

    const crews = store.crews(site.id);
    spots.push({ kind: 'site', site, x: px, y: py });

    crews.forEach((crew, index) => {
      const summary = compute.forCrew(crew.id);
      const angle = (-Math.PI / 2) + (index / Math.max(1, crews.length)) * Math.PI * 2;
      const radius = crews.length > 1 ? 26 : 0;
      spots.push({
        kind: 'crew',
        crew,
        site,
        summary,
        x: px + Math.cos(angle) * radius,
        y: py + Math.sin(angle) * radius,
      });
    });
  }
  return spots;
}

function draw(canvas, mapData, base, spots, hover) {
  const holder = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const cssW = holder.clientWidth - 16;
  const cssH = holder.clientHeight - 16;
  if (cssW <= 0 || cssH <= 0) return null;

  const aspect = mapData.width / mapData.height;
  let w = cssW;
  let h = w / aspect;
  if (h > cssH) { h = cssH; w = h * aspect; }

  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = token('--map-bg');
  ctx.fillRect(0, 0, w, h);

  const colours = HEAT_STEPS.map(token);
  const cw = w / mapData.width;
  const ch = h / mapData.height;
  for (let y = 0; y < mapData.height; y += 1) {
    for (let x = 0; x < mapData.width; x += 1) {
      const index = y * mapData.width + x;
      const value = mapData.values[index];
      if (value === null) continue;
      ctx.fillStyle = colours[classify(value, mapData.breaks)];
      ctx.fillRect(x * cw, y * ch, Math.ceil(cw), Math.ceil(ch));
    }
  }

  ctx.save();
  ctx.globalAlpha = 0.6;
  ctx.fillStyle = token('--surface-panel');
  for (let y = 0; y < mapData.height; y += 1) {
    for (let x = 0; x < mapData.width; x += 1) {
      const index = y * mapData.width + x;
      if (mapData.values[index] === null || !mapData.discarded[index]) continue;
      ctx.fillRect(x * cw, y * ch, Math.ceil(cw), Math.ceil(ch));
    }
  }
  ctx.restore();

  drawBasemap(ctx, base, w, h);

  ctx.strokeStyle = token('--map-outline');
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1);

  return { w, h };
}

function drawBasemap(ctx, base, w, h) {
  if (!base) return;
  ctx.save();
  ctx.globalAlpha = 0.28;
  ctx.fillStyle = token('--map-park');
  for (const park of base.parks) {
    trace(ctx, park, 0, w, h); ctx.closePath(); ctx.fill();
  }
  ctx.globalAlpha = 0.55;
  ctx.strokeStyle = token('--map-river');
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  for (const way of base.river) { trace(ctx, way, 0, w, h); ctx.stroke(); }
  for (const [klass, colour, width, alpha] of [
    [2, '--map-road-minor', 0.7, 0.5], [1, '--map-road-major', 1.6, 0.65]]) {
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = token(colour);
    ctx.lineWidth = width;
    for (const road of base.roads) {
      if (road[0] !== klass) continue;
      trace(ctx, road, 1, w, h); ctx.stroke();
    }
  }
  ctx.restore();
}

function trace(ctx, flat, from, w, h) {
  ctx.beginPath();
  for (let i = from; i < flat.length; i += 2) {
    const x = flat[i] * w;
    const y = flat[i + 1] * h;
    if (i === from) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
}

function drawMarkers(ctx, spots, hover) {
  for (const spot of spots.filter((s) => s.kind === 'site')) {
    ctx.beginPath();
    ctx.arc(spot.x, spot.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = token('--map-site-ring');
    ctx.fill();
    ctx.strokeStyle = token('--ink-primary');
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  for (const spot of spots.filter((s) => s.kind === 'crew')) {
    const status = spot.summary.unavailable ? 'cleared' : spot.summary.worstStatus;
    const isHover = hover && hover.crew && hover.crew.id === spot.crew.id;
    const r = isHover ? 11 : 9;

    ctx.beginPath();
    ctx.arc(spot.x, spot.y, r + 2, 0, Math.PI * 2);
    ctx.fillStyle = token('--surface-panel');
    ctx.fill();

    ctx.beginPath();
    ctx.arc(spot.x, spot.y, r, 0, Math.PI * 2);
    ctx.fillStyle = token(STATUS_TOKEN[status] || '--status-cleared');
    ctx.fill();
    ctx.strokeStyle = isHover ? token('--accent') : token('--surface-panel');
    ctx.lineWidth = isHover ? 2.5 : 1.5;
    ctx.stroke();

    ctx.fillStyle = token('--ink-inverse');
    ctx.font = '700 10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(spot.summary.workers), spot.x, spot.y);
  }

  if (hover) {
    const label = hover.kind === 'crew'
      ? `${hover.crew.name} · ${hover.summary.workers} workers`
      : hover.site.name;
    ctx.font = '600 12px system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    const width = ctx.measureText(label).width;
    const bx = hover.x + 14;
    const by = hover.y - 8;
    ctx.fillStyle = token('--surface-inverse');
    ctx.fillRect(bx, by - 12, width + 12, 20);
    ctx.fillStyle = token('--ink-inverse');
    ctx.fillText(label, bx + 6, by + 2);
  }
}

export function mapView(ctx) {
  const mapData = window.MAP_DATA;
  const base = window.BASEMAP;

  const root = el('div', 'view view-map');
  const holder = el('div', 'map-holder');
  const canvas = el('canvas', 'map-canvas');
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label',
    'Exceedance choropleth with site and crew markers. Click a crew to open it.');
  holder.appendChild(canvas);

  const legend = el('div', 'map-legend');
  const scale = el('div', 'legend-scale');
  const edges = [mapData.min, ...mapData.breaks];
  HEAT_STEPS.forEach((step, index) => {
    const cell = el('div', 'legend-cell');
    const swatch = el('div', 'legend-swatch');
    swatch.style.background = `var(${step})`;
    cell.append(swatch, el('span', 'legend-tick num', edges[index].toFixed(0)));
    scale.appendChild(cell);
  });
  scale.appendChild(el('span', 'legend-tick num', mapData.max.toFixed(0)));

  const audit = mapData.resolutionAudit;
  legend.append(
    el('span', 'legend-label', `Hours above ${mapData.thresholdC} °C in 14 days`),
    scale,
    el('span', 'legend-note',
      `Quantile classes, ${mapData.classOccupancyPct}% of cells each. `
      + `${mapData.tileResolutionM} m tiles but ~${(mapData.effectiveResolutionM / 1000).toFixed(0)} km `
      + `effective resolution, a single-hour retrieval scores `
      + `${audit.snapshotLag1PctOfRange}% against ${audit.lag1PctOfRange}% on the same grid, `
      + `so the smoothness is the field, not the 14-day count.`),
    el('span', 'legend-note',
      `Basemap ${base ? base.attribution : '—'}, cached at build time. No tiles, no network.`));

  root.append(holder, legend);

  let spots = [];
  let hover = null;

  function render() {
    const size = draw(canvas, mapData, base, spots, hover);
    if (!size) return;
    spots = layout(mapData, size.w, size.h);
    const context = canvas.getContext('2d');
    drawMarkers(context, spots, hover);
  }

  function at(event) {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let best = null;
    let bestDistance = 16;
    for (const spot of spots) {
      if (spot.kind !== 'crew') continue;
      const d = Math.hypot(spot.x - x, spot.y - y);
      if (d < bestDistance) { bestDistance = d; best = spot; }
    }
    return best;
  }

  canvas.addEventListener('mousemove', (event) => {
    const found = at(event);
    if (found !== hover) {
      hover = found;
      canvas.style.cursor = found ? 'pointer' : 'default';
      render();
    }
  });
  canvas.addEventListener('mouseleave', () => {
    if (hover) { hover = null; render(); }
  });
  canvas.addEventListener('click', (event) => {
    const found = at(event);
    if (found) ctx.go(`#/site/${found.site.id}/crew/${found.crew.id}`);
  });

  requestAnimationFrame(render);
  if (mapView._listener) window.removeEventListener('resize', mapView._listener);
  mapView._listener = render;
  window.addEventListener('resize', render);

  return root;
}
