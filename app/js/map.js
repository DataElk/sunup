/* ============================================================================
   MapCanvas — exceedance choropleth with an offline locator basemap.

   Canvas, no library, NO TILE SERVER. The road/river/park geometry is a
   build-time fetch from OpenStreetMap cached into app/data/basemap.js by
   scripts/build_basemap.py, so nothing is requested at render time and
   SPEC.md hard constraint 6 still holds. The previous version had no basemap
   at all and was two dots twenty kilometres apart on a field of red: correct,
   and impossible for anyone to place or audit.

   CLASSING IS QUANTILE, NOT EQUAL-INTERVAL.
   The exceedance distribution is strongly left-skewed — p5 79.3 h, p50 96.7 h,
   max 106.9 h — so equal steps in value were nothing like equal steps in area:
   81% of cells landed in the top two classes and the metro read as one flat
   smear. scripts/build_map_data.py now ships `breaks` holding a sixth of the
   cells per class. The legend prints the break values, because a quantile
   scale whose thresholds are hidden is not readable.

   WHAT THIS LAYER CANNOT SHOW, AND SAYS SO.
   The tiles are 101 m but the exceedance field they carry is far smoother: a
   500 m box blur destroys only 1.1% of its variance, and neighbouring tiles
   differ by 0.40% of the range on average. Drawing that at tile resolution
   implies a precision it does not have, so the effective resolution is printed
   on the map rather than left for a reader to discover by squinting.

   AND IT IS NOT THE AGGREGATION. The obvious objection is that exceedance
   counts hours across 336 of them, so of course it is smooth. That was tested
   rather than assumed: a metro-extent single-hour retrieval over the identical
   250x186 lattice scores 0.42% against exceedance's 0.40%, and keeps 98.6% of
   its variance through a 500 m blur against 98.9%. One instant is exactly as
   smooth as the fortnight-long count built from it.

   In absolute terms, at 14:00 on a day above 40 degC the whole Phoenix metro
   spans 1.02 degC and neighbouring 100 m tiles differ by 0.004 degC. Published
   land-surface temperature for this city at this hour separates an irrigated
   park from an asphalt lot by something on the order of 10 degC. Whatever these
   tiles carry, it does not resolve roads, parks, or the river corridor — which
   is why the basemap above is drawn from OpenStreetMap rather than inferred
   from the data. See scripts/audit_resolution.py.

   The 500 m edge-discard band is DRAWN, hatched, rather than hidden. The
   project's original 1.84x headline came from cells inside that band, and the
   honest ratio after discarding it is 1.28x. A map that quietly cropped the
   band would be hiding the finding.
   ========================================================================== */

const HEAT_STEPS = ['--heat-0', '--heat-1', '--heat-2', '--heat-3', '--heat-4', '--heat-5'];

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Index of the quantile class a value falls in. */
function classify(value, breaks) {
  let k = 0;
  while (k < breaks.length && value >= breaks[k]) k += 1;
  return k;
}

/* --- Basemap -------------------------------------------------------------- */

/* Coordinates arrive normalised 0..1 within the AOI bounds, so there is no
   projection maths here at all — the build script did it once. */
function polyline(ctx, flat, from, w, h) {
  ctx.beginPath();
  for (let i = from; i < flat.length; i += 2) {
    const x = flat[i] * w;
    const y = flat[i + 1] * h;
    if (i === from) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
}

function drawBasemap(ctx, base, w, h) {
  if (!base) return;

  ctx.save();

  ctx.globalAlpha = 0.28;
  ctx.fillStyle = token('--map-park');
  for (const park of base.parks) {
    polyline(ctx, park, 0, w, h);
    ctx.closePath();
    ctx.fill();
  }

  ctx.globalAlpha = 0.55;
  ctx.strokeStyle = token('--map-river');
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  for (const way of base.river) {
    polyline(ctx, way, 0, w, h);
    ctx.stroke();
  }

  /* Minor first, then major on top, so the arterial grid reads as a hierarchy
     rather than a mesh of equal lines. */
  for (const [klass, colour, width, alpha] of [
    [2, '--map-road-minor', 0.7, 0.5],
    [1, '--map-road-major', 1.6, 0.65],
  ]) {
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = token(colour);
    ctx.lineWidth = width;
    for (const road of base.roads) {
      if (road[0] !== klass) continue;
      polyline(ctx, road, 1, w, h);
      ctx.stroke();
    }
  }

  ctx.restore();
}

/* --- Scale bar ------------------------------------------------------------ */

function drawScaleBar(ctx, data, w, h) {
  const { west, east, south, north } = data.bounds;
  const midLat = (south + north) / 2;
  const kmPerDegLon = 111.320 * Math.cos((midLat * Math.PI) / 180);
  const kmAcross = (east - west) * kmPerDegLon;

  const target = kmAcross / 5;
  const nice = [1, 2, 5, 10, 20, 50].reduce(
    (best, n) => (Math.abs(n - target) < Math.abs(best - target) ? n : best), 1);
  const barPx = (nice / kmAcross) * w;

  const x = 12;
  const y = h - 14;
  ctx.save();
  ctx.lineWidth = 3;
  ctx.strokeStyle = token('--surface-panel');
  ctx.beginPath();
  ctx.moveTo(x, y); ctx.lineTo(x + barPx, y);
  ctx.stroke();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = token('--ink-primary');
  ctx.beginPath();
  ctx.moveTo(x, y - 3); ctx.lineTo(x, y + 3);
  ctx.moveTo(x, y); ctx.lineTo(x + barPx, y);
  ctx.moveTo(x + barPx, y - 3); ctx.lineTo(x + barPx, y + 3);
  ctx.stroke();

  const label = `${nice} km`;
  ctx.font = `600 11px ${token('--font-ui') || 'sans-serif'}`;
  const tw = ctx.measureText(label).width;
  ctx.fillStyle = token('--surface-panel');
  ctx.fillRect(x + barPx + 4, y - 8, tw + 4, 13);
  ctx.fillStyle = token('--ink-primary');
  ctx.fillText(label, x + barPx + 6, y + 2);
  ctx.restore();
}

/* --- Sites ---------------------------------------------------------------- */

function drawSites(ctx, data, w, h) {
  const { west, south, east, north } = data.bounds;
  const entries = Object.entries(data.sites)
    .sort((a, b) => b[1].valueHours - a[1].valueHours);

  for (const [name, site] of entries) {
    const px = ((site.lon - west) / (east - west)) * w;
    const py = ((north - site.lat) / (north - south)) * h;

    ctx.beginPath();
    ctx.arc(px, py, 8, 0, Math.PI * 2);
    ctx.fillStyle = token('--map-site-ring');
    ctx.fill();
    ctx.beginPath();
    ctx.arc(px, py, 5, 0, Math.PI * 2);
    ctx.fillStyle = token('--map-site');
    ctx.fill();

    const title = name === 'hot_site' ? 'p95 site' : 'p5 site';
    const detail = `${(site.valueHours / 14).toFixed(1)} h/day above threshold`;
    ctx.font = `600 12px ${token('--font-ui') || 'sans-serif'}`;
    const titleW = ctx.measureText(title).width;
    ctx.font = `11px ${token('--font-ui') || 'sans-serif'}`;
    const detailW = ctx.measureText(detail).width;
    const boxW = Math.max(titleW, detailW) + 12;
    const boxH = 32;

    let bx = px + 12;
    let by = py - boxH / 2;
    if (bx + boxW > w - 4) bx = px - 12 - boxW;
    by = Math.min(Math.max(by, 4), h - boxH - 4);

    ctx.fillStyle = token('--surface-panel');
    ctx.strokeStyle = token('--line-strong');
    ctx.lineWidth = 1;
    ctx.fillRect(bx, by, boxW, boxH);
    ctx.strokeRect(bx + 0.5, by + 0.5, boxW - 1, boxH - 1);

    ctx.fillStyle = token('--ink-primary');
    ctx.font = `600 12px ${token('--font-ui') || 'sans-serif'}`;
    ctx.fillText(title, bx + 6, by + 14);
    ctx.fillStyle = token('--ink-secondary');
    ctx.font = `11px ${token('--font-ui') || 'sans-serif'}`;
    ctx.fillText(detail, bx + 6, by + 26);
  }
}

/* --- Draw ----------------------------------------------------------------- */

function draw(canvas, data, base) {
  const holder = canvas.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const cssW = holder.clientWidth - 24;
  const cssH = holder.clientHeight - 24;
  if (cssW <= 0 || cssH <= 0) return;

  const aspect = data.width / data.height;
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
  const cw = w / data.width;
  const ch = h / data.height;

  for (let y = 0; y < data.height; y += 1) {
    for (let x = 0; x < data.width; x += 1) {
      const index = y * data.width + x;
      const value = data.values[index];
      if (value === null) continue;
      ctx.fillStyle = colours[classify(value, data.breaks)];
      ctx.fillRect(x * cw, y * ch, Math.ceil(cw), Math.ceil(ch));
    }
  }

  // The discarded edge band, drawn as a translucent wash so it reads as
  // "excluded" rather than "missing".
  ctx.save();
  ctx.globalAlpha = 0.6;
  ctx.fillStyle = token('--surface-panel');
  for (let y = 0; y < data.height; y += 1) {
    for (let x = 0; x < data.width; x += 1) {
      const index = y * data.width + x;
      if (data.values[index] === null || !data.discarded[index]) continue;
      ctx.fillRect(x * cw, y * ch, Math.ceil(cw), Math.ceil(ch));
    }
  }
  ctx.restore();

  drawBasemap(ctx, base, w, h);

  ctx.strokeStyle = token('--map-outline');
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1);

  drawSites(ctx, data, w, h);
  drawScaleBar(ctx, data, w, h);
}

/* --- Legend --------------------------------------------------------------- */

function legendFor(data, base) {
  const legend = document.createElement('div');
  legend.className = 'legend';

  const label = document.createElement('span');
  label.className = 'legend-label';
  label.textContent = `Hours above ${data.thresholdC} °C in 14 days`;

  /* Quantile scale: the break values ARE the legend. A gradient bar with only
     the endpoints labelled would hide where the classes actually fall. */
  const scale = document.createElement('div');
  scale.className = 'legend-scale';
  const edges = [data.min, ...data.breaks, data.max];
  HEAT_STEPS.forEach((step, index) => {
    const cell = document.createElement('div');
    cell.className = 'legend-cell';
    const swatch = document.createElement('div');
    swatch.className = 'legend-swatch';
    swatch.style.background = `var(${step})`;
    const tick = document.createElement('span');
    tick.className = 'legend-tick num';
    tick.textContent = edges[index].toFixed(0);
    cell.append(swatch, tick);
    scale.appendChild(cell);
  });
  const last = document.createElement('span');
  last.className = 'legend-tick legend-tick-end num';
  last.textContent = data.max.toFixed(0);
  scale.appendChild(last);

  const quantile = document.createElement('span');
  quantile.className = 'legend-note';
  quantile.textContent =
    `Quantile classes — each holds ${data.classOccupancyPct}% of cells.`;

  const audit = data.resolutionAudit;
  const resolution = document.createElement('span');
  resolution.className = 'legend-note';
  resolution.textContent =
    `${data.tileResolutionM} m tiles, but a 500 m blur keeps `
    + `${audit.blur500VarianceKeptPct}% of this layer's variance, so its effective `
    + `resolution is about ${(data.effectiveResolutionM / 1000).toFixed(0)} km. Not `
    + `an artifact of the 14-day count: a single-hour retrieval over the same grid `
    + `scores ${audit.snapshotLag1PctOfRange}% against ${audit.lag1PctOfRange}%, and `
    + `spans just ${audit.snapshotSpanC} °C across the whole metro. See ${audit.script}.`;

  const band = document.createElement('span');
  band.className = 'legend-note';
  band.textContent = `Pale band = within ${data.edgeDiscardM} m of the AOI edge, `
    + 'discarded before ranking.';

  const offline = document.createElement('span');
  offline.className = 'legend-note';
  offline.textContent = base
    ? `Basemap ${base.attribution}, cached at build time — no tiles, no network.`
    : 'No basemap available.';

  legend.append(label, scale, quantile, resolution, band, offline);
  return legend;
}

export function renderMap(root, mapData, rosterData, baseData) {
  const wrap = document.createElement('div');
  wrap.className = 'map-wrap';

  const holder = document.createElement('div');
  holder.className = 'map-canvas-holder';
  const canvas = document.createElement('canvas');
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label',
    `Exceedance choropleth of ${mapData.sourceCells} cells, `
    + `${mapData.min} to ${mapData.max} hours above ${mapData.thresholdC} degC `
    + `over ${mapData.windowHours} hours, in ${HEAT_STEPS.length} quantile classes. `
    + 'Both selected sites are marked over an OpenStreetMap locator layer.');
  holder.appendChild(canvas);

  wrap.append(holder, legendFor(mapData, baseData));
  root.replaceChildren(wrap);

  const redraw = () => draw(canvas, mapData, baseData);
  requestAnimationFrame(redraw);
  if (renderMap._listener) window.removeEventListener('resize', renderMap._listener);
  renderMap._listener = redraw;
  window.addEventListener('resize', redraw);
}
