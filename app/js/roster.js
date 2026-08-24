/* ============================================================================
   Roster — the supervisor's first screen.

   THE ONE REQUIREMENT THAT SHAPES EVERYTHING: answer "who works today and for
   how long" in under ten seconds, at 6 a.m., outdoors, in glare, one-handed.
   So rows are sorted by severity, the minutes figure is the largest thing in
   the row, and the status chip is readable before the text is.

   DESIGN_SYSTEM.md non-negotiable 10: the adaptation state NEVER appears on a
   collapsed row. The foreman gets minutes. `A` is in the payload because the
   detail view needs it, and this file deliberately never reads that field.

   DESIGN_SYSTEM.md non-negotiable 9: every worker view shows the
   counterfactual — what the OSHA calendar ramp would have prescribed. Without
   it this is just another heat dashboard.
   ========================================================================== */

import { rampStrip } from './rampstrip.js';

/* Worst first. A supervisor scanning for who to intervene on should not have
   to read past the top of the list. */
const SEVERITY = { stop: 0, restricted: 1, reduced: 2, cleared: 3, absent: 4 };

const STATUS_TEXT = {
  cleared: 'Full shift',
  reduced: 'Reduced',
  restricted: 'Restricted',
  stop: 'No work',
  absent: 'Absent',
};

function td(className, ...children) {
  const cell = document.createElement('td');
  if (className) cell.className = className;
  for (const child of children) {
    cell.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return cell;
}

function stack(primary, secondary) {
  const wrap = document.createElement('div');
  const a = document.createElement('div');
  a.className = 'cell-primary';
  a.textContent = primary;
  const b = document.createElement('div');
  b.className = 'cell-sub';
  b.textContent = secondary;
  wrap.append(a, b);
  return wrap;
}

function statusChip(status) {
  const chip = document.createElement('span');
  chip.className = 'chip';
  chip.setAttribute('data-status', status);
  chip.textContent = STATUS_TEXT[status] || status;
  return chip;
}

/* The counterfactual, in the compact form a grid cell can carry: what the
   calendar would have said, struck through, and the delta. */
function counterfactualCell(day) {
  const wrap = document.createElement('div');
  wrap.className = 'cf-inline num';
  const was = document.createElement('span');
  was.className = 'was';
  was.textContent = `${day.calendarMinutes}`;
  const delta = document.createElement('span');
  delta.className = 'delta';
  const sign = day.divergence > 0 ? '+' : '';
  delta.textContent = `${sign}${day.divergence}`;
  wrap.append(was, delta);
  wrap.title = `OSHA calendar ramp would prescribe ${day.calendarMinutes} min `
    + `(day ${day.dayOnJob}); the model prescribes ${day.minutes} min.`;
  return wrap;
}

export function renderRoster(root, data, onSelect) {
  const workers = [...data.workers].sort((a, b) => {
    const bySeverity = SEVERITY[a.today.status] - SEVERITY[b.today.status];
    return bySeverity !== 0 ? bySeverity : a.today.minutes - b.today.minutes;
  });

  const table = document.createElement('table');
  table.className = 'grid';

  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  const columns = [
    ['Worker', ''], ['Status', ''], ['Today', 'num'],
    ['Calendar / diff', 'num'], ['Day', 'num'], ['Site', ''],
    [`${data.daysBehind}d back → ${data.daysAhead}d ahead`, ''],
  ];
  for (const [label, cls] of columns) {
    const th = document.createElement('th');
    if (cls) th.className = cls;
    th.textContent = label;
    headRow.appendChild(th);
  }
  head.appendChild(headRow);

  const body = document.createElement('tbody');
  for (const worker of workers) {
    const day = worker.today;
    const row = document.createElement('tr');
    row.tabIndex = 0;
    row.setAttribute('data-worker', worker.id);
    row.setAttribute('aria-selected', 'false');

    const minutes = document.createElement('span');
    minutes.className = 'cell-primary num';
    minutes.textContent = `${day.minutes}`;

    row.append(
      td('', stack(worker.name, `${worker.trade} · ${worker.shift}`)),
      td('', statusChip(day.status)),
      td('num', minutes, ' min'),
      td('num', counterfactualCell(day)),
      td('num', `${day.dayOnJob}`),
      td('', worker.site === 'hot_site' ? 'p95' : 'p5'),
      td('', rampStrip(worker.strip, data.today, { mini: true })),
    );

    const select = () => {
      for (const other of body.querySelectorAll('tr')) {
        other.setAttribute('aria-selected', 'false');
      }
      row.setAttribute('aria-selected', 'true');
      onSelect(worker);
    };
    row.addEventListener('click', select);
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        select();
      }
    });
    body.appendChild(row);
  }

  table.append(head, body);
  root.replaceChildren(table);
  return workers[0];
}

/** Crew totals for the toolbar — the "how long" half of the ten-second test. */
export function crewSummary(data) {
  const model = data.workers.reduce((sum, w) => sum + w.today.minutes, 0);
  const calendar = data.workers.reduce((sum, w) => sum + w.today.calendarMinutes, 0);
  const stopped = data.workers.filter((w) => w.today.status === 'stop').length;
  return { model, calendar, stopped, delta: model - calendar, crew: data.workers.length };
}
