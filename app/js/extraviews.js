/* ============================================================================
   Model performance, and Settings.

   MODEL PERFORMANCE stands at an as-of date, projects
   every active worker forward by carrying that day's weather, and compares
   against what each worker's OWN DAY LOG says happened. Accuracy is therefore
   measured against what crews actually did.

   It keeps two habits from the earlier build, because both were right: it says
   plainly that it is a backtest rather than a live forecast, and it refuses to
   bank a score that cannot be wrong. A worker prescribed zero on every day of
   the horizon matches perfectly while demonstrating nothing, and the row says
   so instead of counting it.
   ========================================================================== */

import { simulate } from './engine.js';
import * as store from './store.js';
import * as compute from './compute.js';
import * as liveWeather from './liveweather.js';
import {
  el, detailsList, chip, tag, toast, confirmDialog, pageHeader,
} from './ui.js';
import { section } from './views.js';

/* --- Model performance ---------------------------------------------------------- */

const HORIZON = 5;

function backtest(worker) {
  const site = compute.siteOf(worker);
  if (!site || !site.seriesKey) return null;
  const series = window.SUNUP_WEATHER.series[site.seriesKey];
  const dates = compute.observedDatesForSite(site)
    .filter((d) => series[d] && (!worker.hireDate || d >= worker.hireDate));
  if (dates.length < HORIZON + 2) return null;

  const cut = dates.length - HORIZON;
  const asOf = dates[cut - 1];
  const before = dates.slice(0, cut).map((d) => ({ date: d, hourly: series[d] }));
  const after = dates.slice(cut).map((d) => ({ date: d, hourly: series[d] }));
  const logs = store.logsFor(worker.id);
  const firstDay = compute.firstDayOnJob(worker, dates[0], logs);

  const history = simulate({
    worker, days: before, logs, initialAdaptation: 0, firstDayOnJob: firstDay,
  });

  /* The projection: carry the as-of day forward, seeing nothing after it. */
  const carried = after.map((d) => ({ date: d.date, hourly: series[asOf] }));
  const predicted = simulate({
    worker, days: carried, logs: {},
    initialAdaptation: history.finalAdaptation,
    firstDayOnJob: history.nextDayOnJob,
  }).records;

  /* The truth: the real days, with the worker's real log. */
  const actual = simulate({
    worker, days: after, logs,
    initialAdaptation: history.finalAdaptation,
    firstDayOnJob: history.nextDayOnJob,
  }).records;

  const pairs = predicted.map((p, i) => ({
    date: p.date,
    predicted: p.prescribedMinutes,
    actual: actual[i].prescribedMinutes,
    logged: actual[i].assumed ? null : actual[i].actualMinutes,
    error: p.prescribedMinutes - actual[i].prescribedMinutes,
    bandMatched: p.status === actual[i].status,
    predictedStatus: p.status,
    actualStatus: actual[i].status,
  }));

  const errors = pairs.map((p) => Math.abs(p.error));
  const signed = pairs.map((p) => p.error);
  const values = new Set(pairs.flatMap((p) => [p.predicted, p.actual]));

  return {
    worker,
    site,
    asOf,
    pairs,
    loggedDays: pairs.filter((p) => p.logged !== null).length,
    bandsMatched: pairs.filter((p) => p.bandMatched).length,
    bandsTotal: pairs.length,
    meanAbs: Math.round((errors.reduce((a, b) => a + b, 0) / errors.length) * 10) / 10,
    bias: Math.round((signed.reduce((a, b) => a + b, 0) / signed.length) * 10) / 10,
    degenerate: values.size === 1,
  };
}

export function performanceView(ctx) {
  const root = el('div', 'view');

  const rows = store.workers()
    .filter((w) => w.active !== false)
    .map(backtest)
    .filter(Boolean);
  root.appendChild(pageHeader('Model performance',
    `${rows.length} active workers with enough history for a ${HORIZON}-day holdout`));

  const usable = rows.filter((r) => !r.degenerate);
  if (usable.length) {
    const bands = usable.reduce((s, r) => s + r.bandsMatched, 0);
    const total = usable.reduce((s, r) => s + r.bandsTotal, 0);
    const bias = usable.reduce((s, r) => s + r.bias, 0) / usable.length;
    const summary = el('div', 'fc-summary');
    summary.append(
      metric(`${bands}/${total}`, 'projected plan level matched'),
      metric(`${bias > 0 ? '+' : ''}${bias.toFixed(1)}`,
        `projection bias, min, ${bias < 0 ? 'conservative' : (bias > 0 ? 'permissive' : 'none')}`,
        bias > 0 ? 'permissive' : 'safe'),
      metric(String(usable.length), 'workers with a usable comparison'),
      metric(String(rows.length - usable.length), 'workers without variation'));
    root.appendChild(summary);
  }

  root.appendChild(detailsList({
    columns: [
      { label: 'Worker', width: '1.6fr',
        render: (r) => {
          const wrap = el('div', 'cellline');
          wrap.appendChild(el('span', 'nm', r.worker.name));
          if (r.degenerate) {
            const t = tag('not counted', 'assumed');
            t.title = 'No variation in the available days.';
            wrap.appendChild(t);
          }
          return wrap;
        } },
      { label: 'Site', width: '1fr', render: (r) => r.site.name },
      { label: 'Logged actuals', width: '108px', numeric: true,
        render: (r) => `${r.loggedDays}/${r.bandsTotal}` },
      { label: 'Plan level', width: '84px', numeric: true,
        render: (r) => {
          const node = el('span', 'num', `${r.bandsMatched}/${r.bandsTotal}`);
          if (r.degenerate) node.classList.add('void');
          return node;
        } },
      { label: 'Bias (min)', width: '88px', numeric: true,
        render: (r) => {
          if (r.degenerate) return '';
          const node = el('span', 'num', `${r.bias > 0 ? '+' : ''}${r.bias}`);
          node.classList.add(r.bias > 0 ? 'danger' : 'ok');
          return node;
        } },
      { label: 'Mean gap (min)', width: '108px', numeric: true,
        render: (r) => r.degenerate ? '' : String(r.meanAbs) },
      { label: `Last ${HORIZON} days: projected / recalculated`, width: '300px',
        render: (r) => {
          const wrap = el('span', 'fc-days');
          for (const pair of r.pairs) {
            const day = el('span', 'fc-day');
            day.setAttribute('data-ok', String(pair.bandMatched));
            day.title = `${pair.date}: projected ${pair.predicted}, `
              + `recalculated ${pair.actual}`;
            day.append(
              el('span', 'fc-day-date', pair.date.slice(5)),
              el('span', 'fc-day-value num', `${pair.predicted}/${pair.actual}`));
            wrap.appendChild(day);
          }
          return wrap;
        } },
    ],
    rows,
    sort: null,
    onSort: () => {},
    selection: new Set(),
    onSelectionChange: () => {},
    rowKey: (r) => r.worker.id,
    selectable: false,
    empty: 'No worker has enough history for comparison yet.',
  }));

  return root;
}

function metric(value, label, kind) {
  const wrap = el('div', 'fc-metric');
  const node = el('div', 'fc-value num', value);
  if (kind) node.setAttribute('data-kind', kind);
  wrap.append(node, el('div', 'fc-label', label));
  return wrap;
}

/* --- Settings -------------------------------------------------------------------- */

export function settingsView(ctx) {
  const root = el('div', 'view');
  const state = store.getState();
  root.appendChild(pageHeader('Settings', 'Weather access and browser data'));
  const settingsGrid = el('div', 'settings-grid');
  root.appendChild(settingsGrid);

  settingsGrid.appendChild(section('Live weather', (() => {
    const wrap = el('div', 'stack');
    const configured = liveWeather.hasLiveAccess();
    const accessStatus = el('p', 'muted', configured
      ? 'Public live weather is ready. No credential is stored in this browser.'
      : 'Public live weather is not configured for this deployment. Cached demo data remains available.');
    accessStatus.setAttribute('role', 'status');
    const actions = el('div', 'callout-actions');
    const test = el('button', 'btn btn-primary', 'Check live access');
    test.type = 'button';
    test.disabled = !configured;
    test.addEventListener('click', async () => {
      test.disabled = true;
      test.textContent = 'Checking...';
      try {
        await liveWeather.testLiveAccess();
        accessStatus.textContent = 'Public live weather is ready.';
        toast('Live weather is available');
      } catch (error) {
        accessStatus.textContent = `Live weather check failed: ${error.message}`;
        toast(error.message);
      } finally {
        test.textContent = 'Check live access';
        test.disabled = false;
      }
    });

    wrap.append(
      el('p', null, 'Live sites can retrieve up to 14 observed days and refresh missing days automatically.'),
      accessStatus,
      actions);
    actions.append(test);
    return wrap;
  })()));

  settingsGrid.appendChild(section('Browser data', (() => {
    const wrap = el('div', 'stack');
    const counts = el('dl', 'kv');
    counts.append(
      el('dt', null, 'Sites'), el('dd', 'num', String(state.sites.length)),
      el('dt', null, 'Crews'), el('dd', 'num', String(state.crews.length)),
      el('dt', null, 'Workers'), el('dd', 'num', String(state.workers.length)),
      el('dt', null, 'Logged days'), el('dd', 'num',
        String(Object.values(state.dayLogs).reduce((s, m) => s + Object.keys(m).length, 0))));
    wrap.appendChild(counts);

    const actions = el('div', 'callout-actions');

    const reset = el('button', 'btn btn-danger', 'Reset to demo data');
    reset.type = 'button';
    reset.addEventListener('click', () => confirmDialog({
      title: 'Reset to demo data',
      message: 'This replaces all current data with the original sites, crews, '
        + 'workers, and logs. It cannot be undone.',
      confirmLabel: 'Reset',
      danger: true,
      onConfirm: () => {
        store.resetToSeed();
        compute.invalidate();
        toast('Reset to demo data');
        ctx.go('#/sites');
      },
    }));

    const clear = el('button', 'btn btn-danger', 'Delete everything');
    clear.type = 'button';
    clear.addEventListener('click', () => confirmDialog({
      title: 'Delete everything',
      message: 'Removes every site, crew, worker and day log, leaving an empty '
        + 'store. Reset to demo data restores the original records.',
      confirmLabel: 'Delete all',
      danger: true,
      onConfirm: () => {
        for (const site of store.sites().slice()) store.removeSite(site.id);
        compute.invalidate();
        toast('Store emptied');
        ctx.go('#/sites');
      },
    }));

    const copy = el('button', 'btn', 'Copy store as JSON');
    copy.type = 'button';
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(store.exportJson());
        toast('Store copied to clipboard');
      } catch {
        toast('Clipboard blocked by the browser');
      }
    });

    actions.append(reset, clear, copy);
    wrap.appendChild(actions);
    return wrap;
  })()));

  return root;
}
