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

function humanize(value) {
  const text = String(value).replace(/_/g, ' ');
  return text.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

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
  let geometryMode = existing ? existing.geometryMode || 'point' : 'point';
  let changedLocation = Boolean(initialPoint);

  const body = el('div', 'panel-stack');
  const fields = form(save);
  fields.append(
    field('Name', name),
    field('Location', picker,
      'Click a point or draw a boundary in Arizona. Live weather is fetched after creation.'));
  body.appendChild(fields);

  function save() {
    if (!chosen) {
      toast('Choose a site location in Arizona first');
      return;
    }
    const changes = {
      name: name.value.trim() || 'Untitled site',
      location: chosen,
      polygon: polygon || pointFeature(chosen),
      geometryMode,
    };
    if (!existing || changedLocation) {
      if (existing && existing.seriesKey) store.removeWeatherSeries(existing.seriesKey);
      changes.seriesKey = null;
      changes.weatherSource = 'none';
      changes.weatherStatus = null;
      changes.weatherProgress = null;
      changes.weatherUpdatedAt = null;
      changes.weatherDates = null;
      changes.weatherForecastDates = null;
      changes.weatherAsOfDate = null;
      changes.weatherError = null;
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
    subtitle: existing ? existing.name : 'Choose a job location in Arizona',
    body,
    footer: footer(existing ? 'Save' : 'Create', save),
  });
  mountSitePicker(picker, initial, polygon, geometryMode, (next) => {
    chosen = next.location;
    polygon = next.polygon;
    geometryMode = next.mode;
    changedLocation = true;
  });
  return surface;
}

async function mountSitePicker(host, initial, initialPolygon, initialMode, onChange) {
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
  let boundary;
  let vertices = [];
  let mode = 'point';
  const center = initial ? [initial.lat, initial.lon ?? initial.lng] : [33.45, -112.07];

  function showPoint(L, location) {
    if (marker) marker.remove();
    marker = L.marker([location.lat, location.lng]).addTo(map);
  }

  function showBoundary(L, featureCollection) {
    if (boundary) boundary.remove();
    boundary = L.geoJSON(featureCollection).addTo(map);
    if (marker) {
      marker.remove();
      marker = null;
    }
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
    if (initialMode === 'boundary' && initialPolygon && initialPolygon.features) {
      showBoundary(L, initialPolygon);
      mode = 'area';
      point.setAttribute('aria-pressed', 'false');
      area.setAttribute('aria-pressed', 'true');
    } else if (initial) {
      showPoint(L, { lat: initial.lat, lng: initial.lon ?? initial.lng });
    }
    note.textContent = 'Arizona coverage only. Choose a point or trace a work boundary.';

    point.addEventListener('click', () => {
      mode = 'point';
      point.setAttribute('aria-pressed', 'true');
      area.setAttribute('aria-pressed', 'false');
      finish.disabled = true;
    });
    area.addEventListener('click', () => {
      mode = 'area';
      vertices = [];
      redrawLine(L);
      point.setAttribute('aria-pressed', 'false');
      area.setAttribute('aria-pressed', 'true');
      finish.disabled = true;
      note.textContent = 'Click at least three corners, then finish the boundary.';
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
        showBoundary(L, picked);
        onChange({ location, polygon: picked, mode: 'boundary' });
      }
      mode = 'area';
      point.setAttribute('aria-pressed', 'false');
      area.setAttribute('aria-pressed', 'true');
      vertices = [];
      redrawLine(L);
      finish.disabled = true;
      note.textContent = 'Boundary set. Create the site or draw a replacement boundary.';
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
        if (boundary) {
          boundary.remove();
          boundary = null;
        }
        showPoint(L, event.latlng);
        onChange({ location: { lng: event.latlng.lng, lat: event.latlng.lat },
          polygon: pointFeature(event.latlng), mode: 'point' });
      }
    });
  } catch {
    note.textContent = 'The map could not load. Check your connection and try again.';
    point.disabled = true;
    area.disabled = true;
  }
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
    subtitle: existing ? existing.name : 'Crews belong to a site',
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
      value: t, label: `${humanize(t)}, ${humanize(CONSTANTS.tradeToWorkClass[t])} work`,
    })));
  const override = select(existing ? existing.workClassOverride || '' : '',
    [{ value: '', label: 'Use trade default' }]
      .concat(CLASSES.map((c) => ({ value: c, label: humanize(c) }))));
  const clothing = select(existing ? existing.clothing : 'work_clothes',
    CLOTHING.map((c) => ({
      value: c,
      label: `${humanize(c)} (${CONSTANTS.clothingAdjustmentC[c] >= 0 ? '+' : ''}${CONSTANTS.clothingAdjustmentC[c]} °C)`,
    })));
  const start = select(existing ? existing.shiftStart : CONSTANTS.defaultShiftStartHour, HOURS);
  const end = select(existing ? existing.shiftEnd : CONSTANTS.defaultShiftEndHour, HOURS);
  const hire = input(existing ? existing.hireDate || ''
    : compute.currentDateForCrew(defaultCrewId), { type: 'date' });
  const rampType = select(existing ? existing.rampType || 'new' : 'new', [
    { value: 'new', label: 'New to this work in heat' },
    { value: 'returning', label: 'Returning with recent similar experience' },
  ]);

  const fields = form(save);
  fields.classList.add('worker-form');
  fields.append(
    field('Name', name),
    field('Crew', crew),
    field('Trade', trade),
    field('Work intensity', override,
      'Override only when the task differs from the trade default.'),
    field('Clothing adjustment', clothing),
    field('Ramp schedule', rampType,
      'This changes only the published calendar comparison. Readiness still comes from logged exposure.'),
    field('First day on job', hire),
    field('Shift start', start),
    field('Shift end', end));

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
      rampType: rampType.value,
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

function recalculationSnapshot(result) {
  if (!result || result.unavailable) return null;
  return {
    cumulativeOverexposure: result.cumulativeOverexposure,
    records: Object.fromEntries(result.records.map((record) => [record.date, {
      prescribedMinutes: record.prescribedMinutes,
      actualMinutes: record.actualMinutes,
      assumed: record.assumed,
      adaptationStart: record.adaptationStart,
      adaptationEnd: record.adaptationEnd,
      limit: record.limit,
      overexposure: record.overexposure,
      cumulativeOverexposure: record.cumulativeOverexposure,
      hours: record.hours.map((hour) => ({
        hour: hour.hour,
        limit: hour.limit,
        overLimit: hour.overLimit,
        minutes: hour.minutes,
      })),
    }])),
  };
}

function recalculationChanges(beforeResult, afterResult) {
  const before = recalculationSnapshot(beforeResult);
  const after = recalculationSnapshot(afterResult);
  const changes = { records: {}, summary: [] };
  if (!before || !after) return changes;

  if (before.cumulativeOverexposure !== after.cumulativeOverexposure) {
    changes.summary.push('cumulativeOverexposure');
  }

  const fields = [
    'prescribedMinutes', 'actualMinutes', 'adaptationStart', 'adaptationEnd',
    'limit', 'overexposure', 'cumulativeOverexposure',
  ];
  for (const [date, current] of Object.entries(after.records)) {
    const previous = before.records[date];
    if (!previous) continue;
    const recordChanges = fields.filter((field) => previous[field] !== current[field]);
    if (previous.assumed !== current.assumed && !recordChanges.includes('actualMinutes')) {
      recordChanges.push('actualMinutes');
    }

    const hourChanges = {};
    current.hours.forEach((hour, index) => {
      const oldHour = previous.hours[index];
      if (!oldHour) return;
      const changed = ['limit', 'overLimit', 'minutes']
        .filter((field) => oldHour[field] !== hour[field]);
      if (changed.length) hourChanges[hour.hour] = changed;
    });
    if (Object.keys(hourChanges).length) recordChanges.push('hours');
    if (recordChanges.length) {
      changes.records[date] = { fields: recordChanges, hours: hourChanges };
    }
  }
  return changes;
}

function markRecalculation(workerId, date, beforeResult) {
  const changes = recalculationChanges(beforeResult, compute.forWorker(workerId));
  try {
    sessionStorage.setItem('sunup:last-recalculation', JSON.stringify({
      workerId, date, changes, at: Date.now(),
    }));
  } catch (_) {
    /* The recalculation still works when browser storage is unavailable. */
  }
}

export function editDayLog(workerId, date, after) {
  const worker = store.worker(workerId);
  const logs = store.logsFor(workerId);
  const entry = logs[date];
  const result = compute.forWorker(workerId);
  const record = result && !result.unavailable
    ? result.records.find((r) => r.date === date) : null;

  const shiftMinutes = Math.max(0, (worker.shiftEnd - worker.shiftStart) * 60);
  const minutes = input(entry ? entry.minutes : '', {
    type: 'number', min: '0', max: String(shiftMinutes), step: '5',
    placeholder: 'Not recorded',
  });
  const note = input(entry ? entry.note : '', { placeholder: 'Optional' });

  const body = el('div', 'panel-stack');
  if (record) {
    const facts = el('dl', 'kv');
    facts.append(
      el('dt', null, 'Prescribed'), el('dd', 'num', `${record.prescribedMinutes} min`),
      el('dt', null, 'Peak WBGT'), el('dd', 'num',
        record.peakWbgt === null ? 'Not available' : `${record.peakWbgt.toFixed(1)} °C`),
      el('dt', null, 'Personal limit'), el('dd', 'num', `${record.limit.toFixed(2)} °C`));
    body.appendChild(facts);
  }

  body.appendChild(el('p', 'muted',
    'Saving an actual updates future prescriptions. The prescription already issued for this date stays unchanged.'));

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
      markRecalculation(workerId, date, result);
      toast('Actual removed. Later prescriptions recalculated.');
      if (after) after();
    });
  }

  function save() {
    if (!minutes.reportValidity()) return;
    const raw = minutes.value.trim();
    try {
      store.setDayLog(workerId, date, raw === '' ? null : Number(raw), note.value);
    } catch (error) {
      toast(error.message);
      return;
    }
    dismissPanel();
    compute.invalidate();
    markRecalculation(workerId, date, result);
    toast('Actual saved. Later prescriptions recalculated.');
    if (after) after();
  }

  panel({
    title: `Log ${date}`,
    subtitle: worker.name,
    body,
    footer: footer('Save', save, clear),
  });
}

/* --- Crew day log -------------------------------------------------------------
   A shift closeout is one crew action. Blank remains unrecorded; Absent stores
   zero actual minutes and an attendance note without changing model inputs.
   ------------------------------------------------------------------------------ */

export function editCrewDayLog(crewId, date, after) {
  const crew = store.crew(crewId);
  if (!crew) return null;
  const workers = store.workers(crewId).filter((worker) => worker.active !== false);
  const body = el('div', 'panel-stack');
  const help = el('p', 'muted',
    'Enter actual heat-exposed minutes. Leave blank if the day is not recorded.');
  body.appendChild(help);

  const list = el('div', 'bulk-log');
  const controls = workers.map((worker) => {
    const entry = store.logsFor(worker.id)[date];
    const result = compute.forWorker(worker.id);
    const record = result && !result.unavailable
      ? result.records.find((item) => item.date === date) : null;
    const isAbsent = Boolean(entry && entry.minutes === 0 && entry.note === 'Absent');
    const shiftMinutes = Math.max(0, (worker.shiftEnd - worker.shiftStart) * 60);
    const minutes = input(isAbsent ? '0' : (entry ? entry.minutes : ''), {
      type: 'number', min: '0', max: String(shiftMinutes), step: '5',
      placeholder: 'Not recorded',
      'aria-label': `Actual minutes for ${worker.name}`,
    });
    const absent = input('', { type: 'checkbox', 'aria-label': `${worker.name} absent` });
    absent.checked = isAbsent;
    minutes.disabled = isAbsent;
    let remembered = isAbsent ? '' : minutes.value;

    const row = el('div', 'bulk-log-row');
    const heading = el('div', 'bulk-log-head');
    heading.append(
      el('strong', null, worker.name),
      el('span', 'muted num', record ? `${record.prescribedMinutes} min prescribed` : 'No prescription'));
    const rowControls = el('div', 'bulk-log-controls');
    const absentLabel = el('label', 'bulk-log-absent');
    absentLabel.append(absent, el('span', null, 'Absent'));
    rowControls.append(field('Actual minutes', minutes), absentLabel);
    row.append(heading, rowControls);
    list.appendChild(row);

    absent.addEventListener('change', () => {
      if (absent.checked) {
        remembered = minutes.value;
        minutes.value = '0';
        minutes.disabled = true;
      } else {
        minutes.disabled = false;
        minutes.value = remembered;
        minutes.focus();
      }
    });
    return { worker, entry, minutes, absent };
  });

  if (workers.length) body.appendChild(list);
  else body.appendChild(el('p', 'muted', 'This crew has no active workers.'));

  function save() {
    const entries = [];
    for (const control of controls) {
      const raw = control.minutes.value.trim();
      if (!control.absent.checked && !control.minutes.reportValidity()) return;
      const note = control.absent.checked
        ? 'Absent' : (control.entry && control.entry.note !== 'Absent' ? control.entry.note : '');
      entries.push({ workerId: control.worker.id,
        minutes: control.absent.checked ? 0 : (raw === '' ? null : Number(raw)), note });
    }
    try {
      for (const entry of entries) {
        store.setDayLog(entry.workerId, date, entry.minutes, entry.note);
      }
    } catch (error) {
      toast(error.message);
      return;
    }
    dismissPanel();
    compute.invalidate();
    toast(`Saved ${workers.length} crew logs`);
    if (after) after();
  }

  return panel({
    title: 'Log crew',
    subtitle: `${crew.name}, ${date}`,
    body,
    footer: workers.length
      ? footer('Save crew', save)
      : footer('Close', () => dismissPanel()),
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
