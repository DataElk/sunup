/* ============================================================================
   Editors. Every one opens in a Panel, saves on submit, and closes.

   Editing a trade, an intensity override, a shift or clothing changes the
   prescription for that worker immediately. There is no build step between
   the form and the answer, because compute.js re-derives from the store on
   every change.

   D4, decided: no justification string on an intensity override. Trade and
   intensity are job facts, and the audit trail is the change record, not prose.
   The override is still MARKED wherever the worker appears, so a hand-set
   intensity can never be mistaken for the trade's own.
   ========================================================================== */

import { CONSTANTS } from './engine.js';
import * as store from './store.js';
import * as compute from './compute.js';
import { isWithinArizona, loadLeaflet, pointFeature, polygonCentre, sitePoint } from './leaflet.js';
import { hasConfiguredKey } from './liveweather.js';
import { startSiteBackfill } from './siteweather.js';
import {
  el, panel, dismissPanel, field, input, select, toast, confirmDialog,
} from './ui.js';

const TRADES = Object.keys(CONSTANTS.tradeToWorkClass).sort();
const CLOTHING = Object.keys(CONSTANTS.clothingAdjustmentC).sort();
const CLASSES = Object.keys(CONSTANTS.ralByClass);

const HOURS = Array.from({ length: 25 }, (_, h) => ({
  value: h, label: `${String(h).padStart(2, '0')}:00`,
}));

function form(onSubmit) {
  const node = el('form', 'form');
  node.addEventListener('submit', (event) => { event.preventDefault(); onSubmit(); });
  return node;
}

function footer(submitLabel, onSubmit, extra) {
  const foot = el('div', 'panel-foot');
  if (extra) foot.appendChild(extra);
  const cancel = el('button', 'btn', 'Cancel');
  cancel.type = 'button';
  cancel.addEventListener('click', () => dismissPanel());
  const save = el('button', 'btn btn-primary', submitLabel);
  save.type = 'button';
  save.addEventListener('click', onSubmit);
  foot.append(cancel, save);
  return foot;
}

/* --- Site --------------------------------------------------------------------- */

export function editSite(siteId, after, initialPoint = null) {
  const existing = siteId ? store.site(siteId) : null;
  const name = input(existing ? existing.name : '', { placeholder: 'Site name' });
  const picker = el('div', 'site-picker');
  const initial = initialPoint || sitePoint(existing);
  let chosen = initial ? { lng: initial.lon ?? initial.lng, lat: initial.lat } : null;
  let polygon = existing ? existing.polygon : null;
  let changedLocation = Boolean(initialPoint);

  const body = el('div', 'panel-stack');
  const fields = form(save);
  fields.append(
    field('Name', name),
    field('Location', picker,
      'Click a point or draw a boundary in Arizona. Live weather is fetched after creation.'));
  body.appendChild(fields);

  if (existing && existing.weatherSource === 'derived') {
    const note = el('div', 'callout callout-warn');
    note.append(
      el('strong', null, 'Derived weather'),
      el('p', null, existing.derivedNote
        || 'This site’s hourly series was estimated, not measured.'));
    body.appendChild(note);
  }

  function save() {
    if (!chosen) {
      toast('Choose a site location in Arizona first');
      return;
    }
    const changes = {
      name: name.value.trim() || 'Untitled site',
      location: chosen,
      polygon: polygon || pointFeature(chosen),
    };
    if (!existing || changedLocation) {
      if (existing && existing.seriesKey) store.removeWeatherSeries(existing.seriesKey);
      changes.seriesKey = null;
      changes.weatherSource = 'none';
      changes.weatherStatus = null;
      changes.weatherProgress = null;
      changes.weatherUpdatedAt = null;
      changes.liveActivityId = null;
      changes.liveActivityDate = null;
      delete changes.derivedNote;
    }
    const saved = existing ? store.updateSite(existing.id, changes) : store.addSite(changes);
    dismissPanel();
    compute.invalidate();
    if (after) after();
    if ((!existing || changedLocation) && hasConfiguredKey()) {
      startSiteBackfill(saved.id).then((started) => {
        if (!started) toast('Live weather could not start for this site');
      });
    } else if (!existing || changedLocation) {
      toast('Site saved with cached weather unavailable. Add a key to fetch its history.');
    }
  }

  const surface = panel({
    title: existing ? 'Edit site' : 'New site',
    subtitle: existing ? existing.id : 'Choose a job location in Arizona',
    body,
    footer: footer(existing ? 'Save' : 'Create', save),
  });
  mountSitePicker(picker, initial, polygon, (next) => {
    chosen = next.location;
    polygon = next.polygon;
    changedLocation = true;
  });
  return surface;
}

async function mountSitePicker(host, initial, initialPolygon, onChange) {
  const note = el('p', 'field-hint', 'Loading map…');
  const canvas = el('div', 'site-picker-map');
  const controls = el('div', 'site-picker-actions');
  const point = el('button', 'btn', 'Set point');
  const area = el('button', 'btn', 'Draw boundary');
  const finish = el('button', 'btn', 'Finish boundary');
  [point, area, finish].forEach((button) => { button.type = 'button'; });
  point.setAttribute('aria-pressed', 'true');
  area.setAttribute('aria-pressed', 'false');
  finish.disabled = true;
  controls.append(point, area, finish);
  host.append(note, canvas, controls);

  let map;
  let marker;
  let line;
  let vertices = [];
  let mode = 'point';
  const center = initial ? [initial.lat, initial.lon ?? initial.lng] : [33.45, -112.07];

  function showPoint(L, location) {
    if (marker) marker.remove();
    marker = L.marker([location.lat, location.lng]).addTo(map);
  }

  function redrawLine(L) {
    if (line) line.remove();
    if (vertices.length) line = L.polyline(vertices.map((v) => [v.lat, v.lng])).addTo(map);
  }

  try {
    const L = await loadLeaflet();
    map = L.map(canvas, { maxBounds: [[30.8, -115.2], [37.25, -108.65]], maxBoundsViscosity: 1 })
      .setView(center, initial ? 13 : 7);
    L.DomEvent.disableClickPropagation(canvas);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    requestAnimationFrame(() => {
      if (canvas.isConnected) map.invalidateSize({ pan: false });
    });
    if (initial) showPoint(L, { lat: initial.lat, lng: initial.lon ?? initial.lng });
    if (initialPolygon && initialPolygon.features) L.geoJSON(initialPolygon).addTo(map);
    note.textContent = 'Arizona coverage only. Choose a point or trace a work boundary.';

    point.addEventListener('click', () => {
      mode = 'point';
      point.setAttribute('aria-pressed', 'true');
      area.setAttribute('aria-pressed', 'false');
      finish.disabled = true;
    });
    area.addEventListener('click', () => {
      mode = 'area';
      point.setAttribute('aria-pressed', 'false');
      area.setAttribute('aria-pressed', 'true');
      finish.disabled = vertices.length < 3;
    });
    finish.addEventListener('click', () => {
      if (vertices.length < 3) return;
      const ring = vertices.map((v) => [v.lng, v.lat]);
      ring.push(ring[0]);
      const picked = { type: 'FeatureCollection', features: [{
        type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] },
      }] };
      const location = polygonCentre(picked);
      if (location) {
        showPoint(L, location);
        onChange({ location, polygon: picked });
      }
      mode = 'point';
      point.setAttribute('aria-pressed', 'true');
      area.setAttribute('aria-pressed', 'false');
      vertices = [];
      redrawLine(L);
      finish.disabled = true;
    });
    map.on('click', (event) => {
      if (!isWithinArizona(event.latlng)) {
        note.textContent = 'FortyGuard weather for this workspace is limited to Arizona.';
        return;
      }
      if (mode === 'area') {
        vertices.push(event.latlng);
        redrawLine(L);
        finish.disabled = vertices.length < 3;
      } else {
        vertices = [];
        redrawLine(L);
        showPoint(L, event.latlng);
        onChange({ location: { lng: event.latlng.lng, lat: event.latlng.lat },
          polygon: pointFeature(event.latlng) });
      }
    });
  } catch {
    note.textContent = 'The map could not load. Check your connection and try again.';
    point.disabled = true;
    area.disabled = true;
  }
}

/* --- Estimate weather for a site that has none -------------------------------
   D2, decided: honest by default, derived as an explicit opt-in. The user has
   to come here and choose it, and the result is tagged everywhere afterwards.
   ---------------------------------------------------------------------------- */

export function estimateWeather(siteId, after) {
  const site = store.site(siteId);
  const measured = compute.measuredSeriesKeys();
  const meta = window.ACCLIMATE_WEATHER.siteMeta;

  const source = select(measured[0], measured.map((k) => ({
    value: k,
    label: `${k}, ${meta[k] ? `${(meta[k].exceedanceHours / 14).toFixed(1)} h/day above threshold` : 'measured'}`,
  })));
  const ratio = input('1.00', { type: 'number', step: '0.01', min: '0.5', max: '1.5' });

  const body = el('div', 'panel-stack');
  const warn = el('div', 'callout callout-warn');
  warn.append(
    el('strong', null, 'This site will use derived weather.'),
    el('p', null, 'Choose a source site and adjustment.'));
  body.appendChild(warn);

  const fields = form(save);
  fields.append(
    field('Source site', source),
    field('Adjustment', ratio, 'Allowed range: 0.50 to 1.50.'));
  body.appendChild(fields);

  function save() {
    const factor = Math.max(0.5, Math.min(1.5, Number(ratio.value) || 1));
    const key = `derived_${site.id}`;
    store.saveWeatherSeries(key, compute.estimateSeriesFrom(source.value, factor));
    store.updateSite(site.id, {
      seriesKey: key,
      weatherSource: 'derived',
      weatherStatus: null,
      weatherProgress: null,
      weatherUpdatedAt: null,
      liveActivityId: null,
      liveActivityDate: null,
      derivedNote: `Source: ${source.value}. Adjustment: ${factor.toFixed(2)}.`,
    });
    dismissPanel();
    compute.invalidate();
    toast('Weather estimate saved');
    if (after) after();
  }

  panel({
    title: 'Estimate weather',
    subtitle: site.name,
    body,
    footer: footer('Estimate', save),
  });
}

/* --- Crew --------------------------------------------------------------------- */

export function editCrew(crewId, defaultSiteId, after) {
  const existing = crewId ? store.crew(crewId) : null;
  const name = input(existing ? existing.name : '', { placeholder: 'Crew name' });
  const site = select(existing ? existing.siteId : defaultSiteId,
    store.sites().map((s) => ({ value: s.id, label: s.name })));

  const fields = form(save);
  fields.append(field('Name', name), field('Site', site));

  function save() {
    const changes = { name: name.value.trim() || 'Untitled crew', siteId: site.value };
    if (existing) store.updateCrew(existing.id, changes);
    else store.addCrew(changes);
    dismissPanel();
    compute.invalidate();
    if (after) after();
  }

  panel({
    title: existing ? 'Edit crew' : 'New crew',
    subtitle: existing ? existing.id : 'Crews belong to a site',
    body: fields,
    footer: footer(existing ? 'Save' : 'Create', save),
  });
}

/* --- Worker -------------------------------------------------------------------- */

export function editWorker(workerId, defaultCrewId, after) {
  const existing = workerId ? store.worker(workerId) : null;

  const name = input(existing ? existing.name : '', { placeholder: 'Worker name' });
  const crew = select(existing ? existing.crewId : defaultCrewId,
    store.crews().map((c) => {
      const site = store.site(c.siteId);
      return { value: c.id, label: `${c.name}${site ? `, ${site.name}` : ''}` };
    }));
  const trade = select(existing ? existing.trade : 'concrete',
    TRADES.map((t) => ({
      value: t, label: `${t} (${CONSTANTS.tradeToWorkClass[t]})`,
    })));
  const override = select(existing ? existing.workClassOverride || '' : '',
    [{ value: '', label: 'From trade' }]
      .concat(CLASSES.map((c) => ({ value: c, label: `Override: ${c}` }))));
  const clothing = select(existing ? existing.clothing : 'work_clothes',
    CLOTHING.map((c) => ({
      value: c,
      label: `${c.replace(/_/g, ' ')} (${CONSTANTS.clothingAdjustmentC[c] >= 0 ? '+' : ''}${CONSTANTS.clothingAdjustmentC[c]} °C)`,
    })));
  const start = select(existing ? existing.shiftStart : CONSTANTS.defaultShiftStartHour, HOURS);
  const end = select(existing ? existing.shiftEnd : CONSTANTS.defaultShiftEndHour, HOURS);
  const hire = input(existing ? existing.hireDate || '' : compute.today(), { type: 'date' });

  const fields = form(save);
  fields.append(
    field('Name', name),
    field('Crew', crew),
    field('Trade', trade),
    field('Work intensity', override),
    field('Clothing', clothing),
    field('Shift start', start),
    field('Shift end', end),
    field('First day on job', hire));

  function save() {
    const s = Number(start.value);
    const e = Number(end.value);
    if (e <= s) { toast('Shift end must be after shift start'); return; }
    const changes = {
      name: name.value.trim() || 'Unnamed worker',
      crewId: crew.value,
      trade: trade.value,
      workClassOverride: override.value || null,
      clothing: clothing.value,
      shiftStart: s,
      shiftEnd: e,
      hireDate: hire.value || null,
    };
    if (existing) store.updateWorker(existing.id, changes);
    else store.addWorker(changes);
    dismissPanel();
    compute.invalidate();
    if (after) after();
  }

  panel({
    title: existing ? 'Edit worker' : 'New worker',
    subtitle: existing ? existing.name : 'New crew member',
    body: fields,
    footer: footer(existing ? 'Save' : 'Create', save),
  });
}

/* --- Day log -------------------------------------------------------------------
   The feedback loop's entry point. Blank means "no entry" and the day falls back
   to the prescription, marked assumed. Zero is a measurement.
   ------------------------------------------------------------------------------ */

export function editDayLog(workerId, date, after) {
  const worker = store.worker(workerId);
  const logs = store.logsFor(workerId);
  const entry = logs[date];
  const result = compute.forWorker(workerId);
  const record = result && !result.unavailable
    ? result.records.find((r) => r.date === date) : null;

  const minutes = input(entry ? entry.minutes : '', {
    type: 'number', min: '0', max: '1440', step: '5',
    placeholder: 'blank = no entry',
  });
  const note = input(entry ? entry.note : '', { placeholder: 'Optional' });

  const body = el('div', 'panel-stack');
  if (record) {
    const facts = el('dl', 'kv');
    facts.append(
      el('dt', null, 'Prescribed'), el('dd', 'num', `${record.prescribedMinutes} min`),
      el('dt', null, 'Peak WBGT'), el('dd', 'num',
        record.peakWbgt === null ? '—' : `${record.peakWbgt.toFixed(1)} °C`),
      el('dt', null, 'Personal limit'), el('dd', 'num', `${record.limit.toFixed(2)} °C`));
    body.appendChild(facts);
  }

  const fields = form(save);
  fields.append(
    field('Minutes actually worked', minutes,
      'Leave blank if not recorded. Enter 0 if no work occurred.'),
    field('Note', note));
  body.appendChild(fields);

  let clear = null;
  if (entry) {
    clear = el('button', 'btn btn-danger', 'Clear entry');
    clear.type = 'button';
    clear.addEventListener('click', () => {
      store.setDayLog(workerId, date, null);
      dismissPanel();
      compute.invalidate();
      if (after) after();
    });
  }

  function save() {
    const raw = minutes.value.trim();
    store.setDayLog(workerId, date, raw === '' ? null : Number(raw), note.value);
    dismissPanel();
    compute.invalidate();
    if (after) after();
  }

  panel({
    title: `Log ${date}`,
    subtitle: worker.name,
    body,
    footer: footer('Save', save, clear),
  });
}

/* --- Deletes -------------------------------------------------------------------- */

export function confirmRemove(kind, items, after) {
  const names = items.map((i) => i.name).join(', ');
  const detail = kind === 'site'
    ? 'Its crews, workers and day logs go with it.'
    : (kind === 'crew' ? 'Its workers and their day logs go with it.'
                       : 'Their day logs go with them.');
  confirmDialog({
    title: `Remove ${items.length} ${kind}${items.length > 1 ? 's' : ''}`,
    message: `${names}. ${detail} This cannot be undone.`,
    confirmLabel: 'Remove',
    danger: true,
    onConfirm: () => {
      for (const item of items) {
        if (kind === 'site') store.removeSite(item.id);
        else if (kind === 'crew') store.removeCrew(item.id);
        else store.removeWorker(item.id);
      }
      compute.invalidate();
      toast(`Removed ${items.length} ${kind}${items.length > 1 ? 's' : ''}`);
      if (after) after();
    },
  });
}
