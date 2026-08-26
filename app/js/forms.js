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

export function editSite(siteId, after) {
  const existing = siteId ? store.site(siteId) : null;
  const name = input(existing ? existing.name : '', { placeholder: 'Site name' });

  const measured = compute.measuredSeriesKeys();
  const seriesOptions = [{ value: '', label: 'No weather history' }]
    .concat(measured.map((k) => ({
      value: k, label: `${k}, measured, 14 days hourly`,
    })));
  const series = select(existing ? existing.seriesKey || '' : '', seriesOptions);

  const body = el('div', 'panel-stack');
  const fields = form(save);
  fields.append(
    field('Name', name),
    field('Weather series', series,
      'A site with no series cannot be prescribed for. Measured series come '
      + 'from the 14-day backfill; there are two.'));
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
    const changes = {
      name: name.value.trim() || 'Untitled site',
      seriesKey: series.value || null,
      weatherSource: series.value
        ? (existing && existing.weatherSource === 'derived' ? 'derived' : 'measured')
        : 'none',
    };
    if (existing) store.updateSite(existing.id, changes);
    else store.addSite(changes);
    dismissPanel();
    compute.invalidate();
    if (after) after();
  }

  panel({
    title: existing ? 'Edit site' : 'New site',
    subtitle: existing ? existing.id : 'Sites group crews and carry the weather',
    body,
    footer: footer(existing ? 'Save' : 'Create', save),
  });
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
    el('strong', null, 'This produces derived data, not a measurement.'),
    el('p', null,
      'There is no hourly weather for this site. Estimating scales a measured '
      + 'site’s hourly curve by a fixed ratio. The site, every worker row '
      + 'under it, and the compliance record will all be tagged "derived", and '
      + 'the record will state the method.'));
  body.appendChild(warn);

  const fields = form(save);
  fields.append(
    field('Scale from', source),
    field('Ratio', ratio, 'Multiplies every hourly WBGT value. 1.00 copies the '
      + 'source site exactly.'));
  body.appendChild(fields);

  function save() {
    const factor = Math.max(0.5, Math.min(1.5, Number(ratio.value) || 1));
    const key = `derived_${site.id}`;
    window.ACCLIMATE_WEATHER.series[key] =
      compute.estimateSeriesFrom(source.value, factor);
    store.updateSite(site.id, {
      seriesKey: key,
      weatherSource: 'derived',
      derivedNote: `Scaled from ${source.value} by ${factor.toFixed(2)}x. `
        + 'Estimated, not measured.',
    });
    dismissPanel();
    compute.invalidate();
    toast('Weather estimated, this site is now marked derived');
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
    field('Trade', trade, 'Sets the work intensity unless overridden below.'),
    field('Work intensity', override,
      'An override is marked wherever this worker appears, so it can never be '
      + 'mistaken for the trade’s own intensity.'),
    field('Clothing', clothing, 'ISO 7243 Clause 7 adjustment, added to WBGT.'),
    field('Shift start', start),
    field('Shift end', end),
    field('First day on job', hire, 'Only ever used as "day N". No other '
      + 'personal detail is stored, by design.'));

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
    subtitle: existing ? existing.name : 'Job facts only',
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
      'Leave blank if not recorded, the day then falls back to the '
      + 'prescription and is marked assumed. Zero means present but not working.'),
    field('Note', note));
  body.appendChild(fields);

  const hint = el('div', 'callout');
  hint.append(el('p', null,
    'The state update uses what you enter here, not what was prescribed. A '
    + 'worker who went over adapted faster and took more strain; both show on '
    + 'his record.'));
  body.appendChild(hint);

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
