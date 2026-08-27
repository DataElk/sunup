/* ============================================================================
   The views.

   Three levels of master/detail. Sites -> crews -> the worker grid, then one
   worker. Everything above the engine is a view of the store; nothing here
   holds state of its own beyond selection and sort.
   ========================================================================== */

import { CONSTANTS } from './engine.js';
import * as store from './store.js';
import * as compute from './compute.js';
import * as forms from './forms.js';
import { hasConfiguredKey } from './liveweather.js';
import { startSiteBackfill } from './siteweather.js';
import {
  el, icon, chip, tag, detailsList, breadcrumb, commandBar, panel,
  dismissPanel, toast, confirmDialog, pageHeader,
} from './ui.js';

const STATUS_TEXT = {
  cleared: 'Full shift', reduced: 'Reduced', restricted: 'Restricted',
  stop: 'No work', absent: 'Absent',
};

/* --- Sparkline ---------------------------------------------------------------
   The compact form of the ramp strip: 14 days in 86px. Bar height is peak WBGT
   on a fixed 22-36 degC scale so two workers are comparable; fill is the
   prescription band. The large strip lives in worker detail, where there is
   room for it to mean something. */

const SPARK_FLOOR = 22;
const SPARK_CEIL = 36;

export function sparkline(records, { width = 86, height = 18 } = {}) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  const shown = records.slice(-14);
  const cell = width / Math.max(1, shown.length);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.setAttribute('class', 'spark');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', describeSpark(shown));

  shown.forEach((record, index) => {
    const peak = record.peakWbgt;
    if (peak === null || peak === undefined) return;
    const clamped = Math.max(SPARK_FLOOR, Math.min(SPARK_CEIL, peak));
    const h = Math.max(2,
      ((clamped - SPARK_FLOOR) / (SPARK_CEIL - SPARK_FLOOR)) * (height - 2));
    const rect = document.createElementNS(ns, 'rect');
    rect.setAttribute('x', (index * cell + 0.6).toFixed(2));
    rect.setAttribute('y', (height - h).toFixed(2));
    rect.setAttribute('width', Math.max(1.5, cell - 1.2).toFixed(2));
    rect.setAttribute('height', h.toFixed(2));
    rect.setAttribute('class', record.projected ? 'sbar sbar-proj' : 'sbar');
    rect.setAttribute('data-status', record.status);
    svg.appendChild(rect);
  });
  return svg;
}

function describeSpark(records) {
  const observed = records.filter((r) => !r.projected);
  const last = observed[observed.length - 1];
  return last
    ? `Fourteen days to ${last.date}; today ${last.prescribedMinutes} minutes.`
    : 'No history.';
}

/* --- Full ramp strip (worker detail only) ------------------------------------- */

function rampStrip(records) {
  const ns = 'http://www.w3.org/2000/svg';
  const CELL = 30;
  const HEAT = 78;
  const TOP = 4;
  const HEIGHT = TOP + HEAT + 16;
  const width = records.length * CELL;

  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${HEIGHT}`);
  svg.setAttribute('preserveAspectRatio', 'xMinYMid meet');
  svg.setAttribute('class', 'ramp');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label',
    `Work schedule across ${records.length} days.`);

  const make = (name, attrs) => {
    const node = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, String(v)));
    return node;
  };

  records.forEach((record, index) => {
    const x = index * CELL;
    svg.appendChild(make('rect', {
      class: record.projected ? 'cell cell-proj' : 'cell',
      x: x + 0.5, y: TOP, width: CELL - 1, height: HEAT,
    }));
    const peak = record.peakWbgt;
    if (peak !== null && peak !== undefined) {
      const clamped = Math.max(SPARK_FLOOR, Math.min(SPARK_CEIL, peak));
      const h = Math.max(2,
        ((clamped - SPARK_FLOOR) / (SPARK_CEIL - SPARK_FLOOR)) * HEAT);
      const bar = make('rect', {
        class: record.projected ? 'bar bar-proj' : 'bar',
        x: x + 3, y: TOP + HEAT - h, width: CELL - 6, height: h,
      });
      bar.setAttribute('data-status', record.status);
      const title = document.createElementNS(ns, 'title');
      title.textContent = `${record.date}, ${record.prescribedMinutes} min prescribed`
        + `${record.assumed ? ' (not logged)' : `, ${record.actualMinutes} logged`}`
        + `, peak ${peak.toFixed(1)} °C`;
      bar.appendChild(title);
      svg.appendChild(bar);
    }
    if (record.unprescribedWork) {
      svg.appendChild(make('circle', {
        class: 'flag-unprescribed', cx: x + CELL / 2, cy: TOP + 6, r: 3.2,
      }));
    }
    const tick = make('text', {
      class: 'tick', x: x + CELL / 2, y: HEIGHT - 4, 'text-anchor': 'middle',
    });
    tick.textContent = record.date.slice(8);
    svg.appendChild(tick);
  });

  const seam = records.filter((r) => !r.projected).length;
  const point = (r, i) => `${i * CELL + CELL / 2},${TOP + HEAT - 2 - r.adaptationStart * (HEAT - 6)}`;
  if (seam > 1) {
    svg.appendChild(make('polyline', {
      class: 'adapt', points: records.slice(0, seam).map(point).join(' '),
    }));
  }
  if (seam < records.length) {
    const from = Math.max(seam - 1, 0);
    svg.appendChild(make('polyline', {
      class: 'adapt adapt-proj',
      points: records.slice(from).map((r, i) => point(r, from + i)).join(' '),
    }));
  }
  return svg;
}

/* --- Shared cells --------------------------------------------------------------- */

function workerNameCell(result) {
  const wrap = el('div', 'cellstack');
  const line = el('div', 'cellline');
  line.appendChild(el('span', 'nm', result.worker.name));
  if (result.worker.workClassOverride) line.appendChild(tag('override', 'warn'));
  if (result.site && result.site.weatherSource === 'derived') {
    line.appendChild(tag('derived', 'warn'));
  }
  wrap.appendChild(line);
  return wrap;
}

function divergenceCell(record) {
  if (!record) return '';
  const node = el('span', 'num diverge',
    `${record.divergence > 0 ? '+' : ''}${record.divergence}`);
  node.setAttribute('data-dir',
    record.divergence < 0 ? 'over' : (record.divergence > 0 ? 'under' : 'none'));
  node.title = record.divergence < 0
    ? 'The calendar allows more than the model, under-protection'
    : (record.divergence > 0
      ? 'The calendar allows less than the model, hours it discards'
      : 'The calendar and the model agree');
  return node;
}

function loggedCell(result) {
  const wrap = el('span', 'loggedcell');
  if (result.assumedRun > 0) {
    const t = tag(`${result.assumedRun}d unlogged`, 'assumed');
    t.title = 'Recent days are missing actual minutes.';
    wrap.appendChild(t);
  } else {
    wrap.appendChild(el('span', 'num ok', 'logged'));
  }
  if (result.unprescribedDays > 0) {
    const t = tag(`${result.unprescribedDays}× unprescribed`, 'danger');
    t.title = 'Work was logged on a day the model prescribed none.';
    wrap.appendChild(t);
  }
  return wrap;
}

/* --- Today: start-of-shift decisions ------------------------------------------ */

function previousObserved(result) {
  if (!result || result.unavailable) return null;
  const prior = result.observed.filter((record) => record.date < compute.today());
  return prior.length ? prior[prior.length - 1] : null;
}

function todayMetric(value, label) {
  const wrap = el('div', 'fc-metric');
  wrap.append(el('div', 'fc-value num', value), el('div', 'fc-label', label));
  return wrap;
}

function todayAttention(row) {
  const wrap = el('span', 'loggedcell');
  if (row.result.unavailable) wrap.appendChild(tag('Weather needed', 'danger'));
  if (!row.result.unavailable && row.result.current.status === 'stop') {
    wrap.appendChild(tag('Move from heat work', 'danger'));
  }
  if (row.missingCloseout) wrap.appendChild(tag('Log previous day', 'assumed'));
  if (!wrap.childElementCount) wrap.appendChild(el('span', 'muted', 'Ready'));
  return wrap;
}

export function todayView(ctx) {
  const root = el('div', 'view');
  const date = new Date(`${compute.today()}T00:00:00Z`).toLocaleDateString([], {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  });
  root.appendChild(pageHeader('Today', date));

  const rows = store.workers()
    .filter((worker) => worker.active !== false)
    .map((worker) => {
      const result = compute.forWorker(worker.id);
      const crew = store.crew(worker.crewId);
      const site = result && result.site ? result.site : (crew ? store.site(crew.siteId) : null);
      const previous = previousObserved(result);
      const missingCloseout = Boolean(previous && previous.assumed);
      const priority = result.unavailable ? 0
        : (result.current.status === 'stop' ? 1 : (missingCloseout ? 2 : 3));
      return { worker, result, crew, site, missingCloseout, priority };
    })
    .sort((a, b) => a.priority - b.priority || a.worker.name.localeCompare(b.worker.name));

  const usable = rows.filter((row) => !row.result.unavailable);
  const stopped = usable.filter((row) => row.result.current.status === 'stop').length;
  const missing = rows.filter((row) => row.missingCloseout).length;
  const unavailable = rows.length - usable.length;
  const minutes = usable.reduce((sum, row) => sum + row.result.current.prescribedMinutes, 0);

  const summary = el('div', 'fc-summary');
  summary.append(
    todayMetric(String(rows.length), 'active workers'),
    todayMetric(`${(minutes / 60).toFixed(1)} h`, 'prescribed today'),
    todayMetric(String(stopped), 'stop work'),
    todayMetric(String(missing), 'need closeout'),
    todayMetric(String(unavailable), 'weather unavailable'));
  root.appendChild(summary);

  root.appendChild(detailsList({
    columns: [
      { label: 'Worker', width: '1.4fr', render: (row) => workerNameCell(row.result) },
      { label: 'Site / crew', width: '1.3fr',
        render: (row) => `${row.site ? row.site.name : 'No site'} / ${row.crew ? row.crew.name : 'No crew'}` },
      { label: 'Shift', width: '96px', numeric: true,
        render: (row) => `${pad(row.worker.shiftStart)}:00-${pad(row.worker.shiftEnd)}:00` },
      { label: 'Prescribed (min)', width: '136px', numeric: true,
        render: (row) => row.result.unavailable
          ? '—' : String(row.result.current.prescribedMinutes) },
      { label: 'Calendar (min)', width: '104px', numeric: true,
        render: (row) => row.result.unavailable
          ? '—' : String(row.result.current.calendarMinutes) },
      { label: 'Status', width: '110px',
        render: (row) => row.result.unavailable
          ? el('span', 'muted', 'Unavailable')
          : chip(row.result.current.status, STATUS_TEXT[row.result.current.status]) },
      { label: 'Attention', width: '1.4fr', render: todayAttention },
    ],
    rows,
    sort: null,
    onSort: () => {},
    selection: new Set(),
    onSelectionChange: () => {},
    rowKey: (row) => row.worker.id,
    onInvoke: (row) => {
      if (row.site && row.crew) {
        ctx.go(`#/site/${row.site.id}/crew/${row.crew.id}/worker/${row.worker.id}`);
      }
    },
    selectable: false,
    empty: 'No active workers. Add workers under Sites and crews.',
  }));
  return root;
}

/* --- Level 1: all sites --------------------------------------------------------- */

export function sitesView(ctx) {
  const root = el('div', 'view');
  const rows = store.sites().map((s) => compute.forSite(s.id));
  const workers = rows.reduce((sum, row) => sum + row.workers, 0);
  root.appendChild(pageHeader('Sites and crews',
    `${rows.length} sites, ${workers} active workers`));
  const list = detailsList({
    columns: [
      { label: 'Site', width: '2fr', sortKey: 'name',
        render: (r) => {
          const wrap = el('div', 'cellline');
          wrap.appendChild(el('span', 'nm', r.site.name));
          if (r.site.weatherSource === 'derived') wrap.appendChild(tag('derived', 'warn'));
          if (r.site.weatherSource === 'none') wrap.appendChild(tag('no weather', 'danger'));
          return wrap;
        } },
      { label: 'Crews', width: '70px', numeric: true, sortKey: 'crews',
        render: (r) => String(r.crews.length) },
      { label: 'Workers', width: '80px', numeric: true, sortKey: 'workers',
        render: (r) => String(r.workers) },
      { label: 'Model (min)', width: '104px', numeric: true, sortKey: 'model',
        render: (r) => r.site.weatherSource === 'none' ? '—' : `${r.modelMinutes}` },
      { label: 'Calendar (min)', width: '112px', numeric: true,
        render: (r) => r.site.weatherSource === 'none' ? '—' : `${r.calendarMinutes}` },
      { label: 'Status', width: '110px',
        render: (r) => r.site.weatherSource === 'none'
          ? el('span', 'muted', 'unavailable')
          : chip(r.worstStatus, STATUS_TEXT[r.worstStatus]) },
    ],
    rows: sortRows(rows, ctx.sort, {
      name: (r) => r.site.name, crews: (r) => r.crews.length,
      workers: (r) => r.workers, model: (r) => r.modelMinutes,
    }),
    sort: ctx.sort,
    onSort: ctx.onSort,
    selection: ctx.selection,
    onSelectionChange: ctx.onSelectionChange,
    rowKey: (r) => r.site.id,
    onInvoke: (r) => ctx.go(`#/site/${r.site.id}`),
    empty: 'No sites. Use New site to add one.',
  });
  root.appendChild(list);
  return root;
}

/* --- Level 2: one site ----------------------------------------------------------- */

export function siteView(ctx, siteId) {
  const site = store.site(siteId);
  if (!site) return missing(ctx, 'That site no longer exists.');
  const root = el('div', 'view');
  root.appendChild(breadcrumb([
    { label: 'Sites', href: '#/sites' }, { label: site.name },
  ]));
  const freshness = weatherFreshness(site);
  if (freshness) root.appendChild(freshness);

  if (site.weatherSource === 'none') {
    root.appendChild(noWeatherBanner(ctx, site));
  } else if (site.weatherStatus === 'error' || site.weatherStatus === 'partial') {
    root.appendChild(weatherFailureBanner(ctx, site));
  } else if (site.weatherStatus === 'backfill') {
    root.appendChild(backfillBanner(site));
  } else if (site.weatherSource === 'derived') {
    root.appendChild(derivedBanner(site));
  }

  const rows = store.crews(siteId).map((c) => compute.forCrew(c.id));
  root.appendChild(detailsList({
    columns: [
      { label: 'Crew', width: '2fr', sortKey: 'name',
        render: (r) => {
          const wrap = el('div', 'cellline');
          wrap.appendChild(el('span', 'nm', r.crew.name));
          return wrap;
        } },
      { label: 'Workers', width: '80px', numeric: true, sortKey: 'workers',
        render: (r) => String(r.workers) },
      { label: 'Model', width: '90px', numeric: true, sortKey: 'model',
        render: (r) => String(r.modelMinutes) },
      { label: 'Calendar', width: '90px', numeric: true,
        render: (r) => String(r.calendarMinutes) },
      { label: 'Stopped', width: '80px', numeric: true,
        render: (r) => r.stopped ? String(r.stopped) : '' },
      { label: 'Flags', width: '220px',
        render: (r) => {
          const wrap = el('span', 'loggedcell');
          if (r.overexposed) wrap.appendChild(tag(`${r.overexposed} overexposed`, 'danger'));
          if (r.unprescribed) wrap.appendChild(tag(`${r.unprescribed} unprescribed`, 'danger'));
          return wrap;
        } },
      { label: 'Status', width: '110px',
        render: (r) => chip(r.worstStatus, STATUS_TEXT[r.worstStatus]) },
    ],
    rows: sortRows(rows, ctx.sort, {
      name: (r) => r.crew.name, workers: (r) => r.workers,
      model: (r) => r.modelMinutes,
    }),
    sort: ctx.sort,
    onSort: ctx.onSort,
    selection: ctx.selection,
    onSelectionChange: ctx.onSelectionChange,
    rowKey: (r) => r.crew.id,
    onInvoke: (r) => ctx.go(`#/site/${siteId}/crew/${r.crew.id}`),
    empty: 'No crews at this site yet.',
  }));
  return root;
}

/* --- Level 3: the worker grid ----------------------------------------------------- */

export function crewView(ctx, siteId, crewId) {
  const crew = store.crew(crewId);
  const site = store.site(siteId);
  if (!crew || !site) return missing(ctx, 'That crew no longer exists.');

  const root = el('div', 'view');
  root.appendChild(breadcrumb([
    { label: 'Sites', href: '#/sites' },
    { label: site.name, href: `#/site/${siteId}` },
    { label: crew.name },
  ]));
  const freshness = weatherFreshness(site);
  if (freshness) root.appendChild(freshness);

  if (site.weatherSource === 'none') root.appendChild(noWeatherBanner(ctx, site));
  else if (site.weatherStatus === 'error' || site.weatherStatus === 'partial') {
    root.appendChild(weatherFailureBanner(ctx, site));
  } else if (site.weatherStatus === 'backfill') root.appendChild(backfillBanner(site));
  else if (site.weatherSource === 'derived') root.appendChild(derivedBanner(site));

  const rows = store.workers(crewId).map((w) => compute.forWorker(w.id)).filter(Boolean);

  root.appendChild(detailsList({
    columns: [
      { label: 'Worker', width: '1.7fr', sortKey: 'name', render: workerNameCell },
      { label: 'Trade', width: '110px', sortKey: 'trade',
        render: (r) => r.worker.trade },
      { label: 'Start', width: '64px', sortKey: 'shift',
        render: (r) => {
          const node = el('span', 'num',
            `${String(r.worker.shiftStart).padStart(2, '0')}:00`);
          if (r.worker.shiftStart > CONSTANTS.defaultShiftStartHour) {
            node.classList.add('late');
          }
          return node;
        } },
      { label: 'Status', width: '104px', sortKey: 'status',
        render: (r) => r.unavailable ? el('span', 'muted', '—')
          : chip(r.current.status, STATUS_TEXT[r.current.status]) },
      { label: 'Today (min)', width: '88px', numeric: true, sortKey: 'minutes',
        render: (r) => r.unavailable ? '—' : String(r.current.prescribedMinutes) },
      { label: 'vs cal.', width: '70px', numeric: true, sortKey: 'divergence',
        render: (r) => r.unavailable ? '' : divergenceCell(r.current) },
      { label: 'Overexp.', width: '80px', numeric: true, sortKey: 'over',
        render: (r) => {
          if (r.unavailable || r.cumulativeOverexposure <= 0) return '';
          const node = el('span', 'num danger',
            r.cumulativeOverexposure.toFixed(1));
          node.title = 'Cumulative °C·h worked above this worker’s own limit '
            + 'beyond what was prescribed.';
          return node;
        } },
      { label: 'Log', width: '186px',
        render: (r) => r.unavailable ? '' : loggedCell(r) },
      { label: '14 days', width: '96px',
        render: (r) => r.unavailable ? '' : sparkline(r.records) },
    ],
    rows: sortRows(rows, ctx.sort, {
      name: (r) => r.worker.name,
      trade: (r) => r.worker.trade,
      shift: (r) => r.worker.shiftStart,
      status: (r) => r.unavailable ? 9 : ['stop', 'restricted', 'reduced', 'cleared']
        .indexOf(r.current.status),
      minutes: (r) => r.unavailable ? -1 : r.current.prescribedMinutes,
      divergence: (r) => r.unavailable ? 0 : r.current.divergence,
      over: (r) => r.unavailable ? 0 : r.cumulativeOverexposure,
    }),
    sort: ctx.sort,
    onSort: ctx.onSort,
    selection: ctx.selection,
    onSelectionChange: ctx.onSelectionChange,
    rowKey: (r) => r.worker.id,
    onInvoke: (r) => ctx.go(`#/site/${siteId}/crew/${crewId}/worker/${r.worker.id}`),
    empty: 'No workers in this crew yet.',
  }));
  return root;
}

/* --- Level 4: one worker ----------------------------------------------------------- */

export function workerView(ctx, siteId, crewId, workerId) {
  const result = compute.forWorker(workerId);
  if (!result) return missing(ctx, 'That worker no longer exists.');
  const { worker, site } = result;
  const crew = store.crew(crewId);

  const root = el('div', 'view view-worker');
  root.appendChild(breadcrumb([
    { label: 'Sites', href: '#/sites' },
    { label: site ? site.name : '—', href: `#/site/${siteId}` },
    { label: crew ? crew.name : '—', href: `#/site/${siteId}/crew/${crewId}` },
    { label: worker.name },
  ]));

  if (result.unavailable) {
    root.appendChild(noWeatherBanner(ctx, site));
    return root;
  }

  const current = result.current;

  const head = el('div', 'wk-head');
  const metric = el('div', 'wk-metric');
  metric.append(el('div', 'wk-minutes num', String(current.prescribedMinutes)),
                el('div', 'wk-unit', 'minutes prescribed today'));
  const facts = el('div', 'wk-facts');
  facts.append(
    fact('Trade', worker.trade),
    fact('Intensity', result.workClass
      + (worker.workClassOverride ? ' (override)' : '')),
    fact('Shift', `${pad(worker.shiftStart)}:00, ${pad(worker.shiftEnd)}:00`),
    fact('Clothing', worker.clothing.replace(/_/g, ' ')),
    fact('Day on job', String(current.dayOnJob)),
    fact('Calendar', `${current.calendarMinutes} min`));
  head.append(metric, facts, chip(current.status, STATUS_TEXT[current.status]));
  root.appendChild(head);

  if (result.assumedRun > 0) {
    const missingTitle = result.assumedRun === 1
      ? '1 recent day has no logged actual.'
      : `${result.assumedRun} recent days have no logged actual.`;
    root.appendChild(banner('assumed',
      missingTitle, 'Add actual minutes for these days.'));
  }
  if (result.cumulativeOverexposure > 0) {
    root.appendChild(banner('danger',
      `Overexposure ${result.cumulativeOverexposure.toFixed(2)} °C·h`,
      'Review the flagged days in the log.'));
  }

  root.appendChild(section('Fourteen days and six upcoming',
    rampStrip(result.records)));

  /* Day log ------------------------------------------------------------------ */
  const logRows = result.observed.slice().reverse();
  root.appendChild(section('Day log', detailsList({
    columns: [
      { label: 'Date', width: '108px', render: (r) => r.date },
      { label: 'Day', width: '54px', numeric: true, render: (r) => String(r.dayOnJob) },
      { label: 'Prescribed', width: '92px', numeric: true,
        render: (r) => String(r.prescribedMinutes) },
      { label: 'Actual', width: '92px', numeric: true,
        render: (r) => {
          if (r.assumed) {
            const node = el('span', 'muted', 'not logged');
            node.title = 'No actual minutes recorded.';
            return node;
          }
          const node = el('span', 'num', String(r.actualMinutes));
          if (r.actualMinutes > r.prescribedMinutes) node.classList.add('danger');
          return node;
        } },
      { label: 'Rule', width: '96px',
        render: (r) => r.assumed ? el('span', 'muted', '—')
          : el('span', 'muted', r.allocationRule) },
      { label: 'Flags', width: '150px',
        render: (r) => {
          const wrap = el('span', 'loggedcell');
          if (r.unprescribedWork) {
            const t = tag('unprescribed', 'danger');
            t.title = 'Work was logged on a day with no prescribed minutes.';
            wrap.appendChild(t);
          }
          if (r.overexposure > 0) {
            wrap.appendChild(tag(`+${r.overexposure.toFixed(1)} °C·h`, 'danger'));
          }
          return wrap;
        } },
      { label: 'Peak', width: '76px', numeric: true,
        render: (r) => r.peakWbgt === null ? '' : r.peakWbgt.toFixed(1) },
    ],
    rows: logRows,
    sort: null,
    onSort: () => {},
    selection: new Set(),
    onSelectionChange: () => {},
    rowKey: (r) => r.date,
    selectable: false,
    onInvoke: (r) => forms.editDayLog(workerId, r.date, ctx.refresh),
    empty: 'No days yet.',
  })));

  /* Hour by hour -------------------------------------------------------------- */
  if (current.hours.length) {
    const fewest = Math.min(...current.hours.map((h) => h.minutes));
    const binding = current.hours.find((h) => h.minutes === fewest);
    const table = el('table', 'hours');
    const thead = el('thead');
    const hr = el('tr');
    ['Hour', 'WBGT', 'Limit', 'Over', 'Work'].forEach((label, i) => {
      const th = el('th', i ? 'num' : null, label);
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    const tbody = el('tbody');
    for (const hour of current.hours) {
      const tr = el('tr');
      tr.setAttribute('data-stop', String(hour.stop));
      tr.setAttribute('data-binding', String(hour === binding));
      [[`${pad(hour.hour)}:00`, ''], [hour.wbgt.toFixed(1), 'num'],
       [hour.limit.toFixed(1), 'num'],
       [`${hour.overLimit > 0 ? '+' : ''}${hour.overLimit.toFixed(1)}`, 'num'],
       [String(hour.minutes), 'num']].forEach(([text, cls]) => {
        tr.appendChild(el('td', cls || null, text));
      });
      tbody.appendChild(tr);
    }
    table.append(thead, tbody);
    const why = binding ? el('p', 'muted',
      `Binding hour ${pad(binding.hour)}:00, `
      + (binding.overLimit > 0
        ? `${binding.overLimit.toFixed(1)} °C above this worker’s limit.`
        : 'within limit.')) : null;
    const wrap = el('div', 'stack');
    if (why) wrap.appendChild(why);
    wrap.appendChild(table);
    root.appendChild(section('Hour by hour, today', wrap));
  }

  /* State --------------------------------------------------------------------- */
  const state = el('dl', 'kv');
  state.append(
    el('dt', null, 'Adaptation'), el('dd', 'num', current.adaptationStart.toFixed(3)),
    el('dt', null, 'Personal limit'), el('dd', 'num', `${current.limit.toFixed(2)} °C-WBGT`),
    el('dt', null, 'Overexposure'), el('dd', 'num',
      `${result.cumulativeOverexposure.toFixed(2)} °C·h`),
    el('dt', null, 'Weather'), el('dd', null,
      `${site.weatherSource}${site.seriesKey ? `, ${site.seriesKey}` : ''}`));
  root.appendChild(section('Acclimatization state', state));

  return root;
}

function fact(label, value) {
  const wrap = el('div', 'fact');
  wrap.append(el('span', 'fact-l', label), el('span', 'fact-v', value));
  return wrap;
}

function pad(n) { return String(n).padStart(2, '0'); }

function section(title, content) {
  const wrap = el('section', 'sect');
  wrap.appendChild(el('h3', 'sect-h', title));
  wrap.appendChild(content);
  return wrap;
}

function banner(kind, title, detail) {
  const node = el('div', 'callout');
  node.setAttribute('data-kind', kind);
  node.append(el('strong', null, title));
  if (detail) node.appendChild(el('p', null, detail));
  return node;
}

function derivedBanner(site) {
  return banner('warn', 'Derived weather',
    site.derivedNote || 'A measured source site was used.');
}

function weatherFreshness(site) {
  if (site.weatherSource !== 'live' || !site.weatherUpdatedAt) return null;
  const progress = site.weatherProgress || { completed: 0, total: 14 };
  const value = new Date(site.weatherUpdatedAt);
  const updated = Number.isNaN(value.getTime())
    ? site.weatherUpdatedAt
    : value.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  return el('p', 'muted',
    `Live weather: ${progress.completed} of ${progress.total} days. Updated ${updated}.`);
}

function noWeatherBanner(ctx, site) {
  if (site.weatherStatus === 'loading' || site.weatherStatus === 'backfill') {
    const progress = site.weatherProgress || { completed: 0, total: 14 };
    return banner('info', 'Retrieving live weather',
      `${progress.completed} of ${progress.total} days ready. Prescriptions appear after the first five days.`);
  }
  if (site.weatherStatus === 'error' || site.weatherStatus === 'partial') {
    return weatherFailureBanner(ctx, site);
  }
  const node = banner('danger', 'No weather history, prescriptions unavailable',
    'This site has no hourly WBGT series, so nothing can be prescribed for the '
    + 'crews under it.');
  const actions = el('div', 'callout-actions');

  const fetchBtn = liveFetchButton(ctx, site, 'Fetch live');
  const est = el('button', 'btn btn-primary', 'Estimate from nearest measured site');
  est.type = 'button';
  est.addEventListener('click', () => forms.estimateWeather(site.id, ctx.refresh));

  actions.append(fetchBtn, est);
  node.appendChild(actions);
  return node;
}

function liveFetchButton(ctx, site, label) {
  const button = el('button', 'btn', hasConfiguredKey() ? label : 'Add API key');
  button.type = 'button';
  if (!hasConfiguredKey()) {
    button.addEventListener('click', () => ctx.go('#/settings'));
    return button;
  }
  button.addEventListener('click', async () => {
    button.disabled = true;
    const task = startSiteBackfill(site.id);
    ctx.refresh();
    const started = await task;
    if (!started) toast('Live weather fetch failed. Check the key and try again.');
    ctx.refresh();
  });
  return button;
}

function weatherFailureBanner(ctx, site) {
  const partial = site.weatherStatus === 'partial';
  const node = banner(partial ? 'warn' : 'danger',
    partial ? 'Live weather history is incomplete' : 'Live weather fetch failed',
    partial
      ? 'Some days are available. Retry to complete this site’s history.'
      : 'No live days are available. Check the API key, then retry.');
  const actions = el('div', 'callout-actions');
  actions.appendChild(liveFetchButton(ctx, site, 'Retry live fetch'));
  node.appendChild(actions);
  return node;
}

function backfillBanner(site) {
  const progress = site.weatherProgress || { completed: 5, total: 14 };
  return banner('info', 'Live weather is still backfilling',
    `${progress.completed} of ${progress.total} days ready. Prescriptions update as history arrives.`);
}

function missing(ctx, message) {
  const root = el('div', 'view');
  root.appendChild(banner('warn', message, 'It may have been removed.'));
  const back = el('button', 'btn', 'Back to sites');
  back.type = 'button';
  back.addEventListener('click', () => ctx.go('#/sites'));
  root.appendChild(back);
  return root;
}

/* --- Sorting -------------------------------------------------------------------- */

function sortRows(rows, sort, accessors) {
  if (!sort || !accessors[sort.key]) return rows;
  const get = accessors[sort.key];
  const dir = sort.dir === 'asc' ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const x = get(a);
    const y = get(b);
    if (x === y) return 0;
    return (x > y ? 1 : -1) * dir;
  });
}

export { STATUS_TEXT, rampStrip, banner, section, fact };
