/* ============================================================================
   Worker detail — drawer content.

   Opens on demand and closes. It is a thing you ASK for, not a permanent
   half-screen panel over eight rows.

   This is the ONLY place the adaptation state may appear (rule 10). The foreman
   opens this asking why a man he thinks is fine has been cut, and the answer has
   to be here in full: the state, the limit it implies, and the hour that binds.
   ========================================================================== */

import { rampStrip } from './rampstrip.js';
import { pretty } from './format.js';

function section(label, ...children) {
  const wrap = document.createElement('section');
  wrap.className = 'section';
  if (label) {
    const head = document.createElement('div');
    head.className = 'section-label';
    head.textContent = label;
    wrap.appendChild(head);
  }
  wrap.append(...children.filter(Boolean));
  return wrap;
}

function div(className, text) {
  const node = document.createElement('div');
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function keyValues(rows) {
  const dl = document.createElement('dl');
  dl.className = 'kv';
  for (const [key, value] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = key;
    const dd = document.createElement('dd');
    dd.className = 'num';
    dd.textContent = value;
    dl.append(dt, dd);
  }
  return dl;
}

function counterfactual(day) {
  const wrap = div('cf');
  const read = div('cf-read');
  const cal = document.createElement('span');
  cal.className = 'num';
  cal.textContent = `OSHA calendar, day ${day.dayOnJob}: ${day.calendarMinutes} min`;
  const badge = document.createElement('span');
  badge.className = 'mismatch';
  badge.setAttribute('data-mismatch', day.mismatch);
  badge.textContent = day.mismatch === 'none'
    ? 'agree' : `${day.divergence > 0 ? '+' : ''}${day.divergence} min`;
  read.append(cal, badge);
  wrap.append(read);
  return wrap;
}

function hourTable(day) {
  const table = document.createElement('table');
  table.className = 'hours';

  const head = document.createElement('thead');
  const hr = document.createElement('tr');
  for (const [label, cls] of [['Hour', ''], ['WBGT', 'num'], ['Limit', 'num'],
                              ['Over', 'num'], ['Work', 'num']]) {
    const th = document.createElement('th');
    if (cls) th.className = cls;
    th.textContent = label;
    hr.appendChild(th);
  }
  head.appendChild(hr);

  const fewest = Math.min(...day.hours.map((h) => h.minutes));
  const binding = day.hours.find((h) => h.minutes === fewest);

  const body = document.createElement('tbody');
  for (const hour of day.hours) {
    const tr = document.createElement('tr');
    tr.setAttribute('data-stop', String(hour.stop));
    tr.setAttribute('data-binding', String(hour === binding));
    const cells = [
      [`${String(hour.hour).padStart(2, '0')}:00`, ''],
      [hour.wbgt.toFixed(1), 'num'],
      [hour.limit.toFixed(1), 'num'],
      [`${hour.overLimit > 0 ? '+' : ''}${hour.overLimit.toFixed(1)}`, 'num'],
      [`${hour.minutes}`, 'num'],
    ];
    for (const [text, cls] of cells) {
      const cell = document.createElement('td');
      if (cls) cell.className = cls;
      cell.textContent = text;
      tr.appendChild(cell);
    }
    body.appendChild(tr);
  }
  table.append(head, body);
  return { table, binding };
}

export function renderDetail(root, worker, data) {
  if (!worker) {
    root.replaceChildren(div('empty', 'Select a worker.'));
    return;
  }
  const day = worker.today;
  const parts = [];

  const headline = section(null,
    div('metric-value', `${day.minutes} min`),
    div('metric-sub',
      `${worker.shiftFull} · ${worker.trade} · ${worker.workClass} work · ${worker.siteLabel}`));
  parts.push(headline);

  if (worker.pair) {
    const note = document.createElement('p');
    note.className = 'note';
    note.textContent = worker.note;
    parts.push(note);
  }

  parts.push(section('Counterfactual', counterfactual(day)));

  parts.push(section('Why', div('reason-what', pretty(worker.levers.reason)),
                     div('reason-lever', pretty(worker.levers.detail)),
                     keyValues([
                       ['If started 05:00', `${worker.levers.ifEarlyShift} min`],
                       ['If fully adapted', `${worker.levers.ifFullyAdapted} min`],
                     ])));

  parts.push(section(
    `${data.daysBehind} days behind · today · ${data.daysAhead} ahead`,
    rampStrip(worker.strip, data.today, { labels: true })));

  if (day.hours.length) {
    const { table, binding } = hourTable(day);
    const why = binding
      ? div('reason-lever',
        `Binding hour ${String(binding.hour).padStart(2, '0')}:00 — `
        + (binding.overLimit > 0
          ? `${binding.overLimit.toFixed(1)} degC above this worker's limit.`
          : 'within limit.'))
      : null;
    parts.push(section('Hour by hour', why, table));
  }

  /* Rule 10: permitted HERE and nowhere else. The heading used to read
     "State — detail only", which is a note to whoever maintains the rule, not
     something a foreman needs to read. The rule is enforced in the roster
     component and in tests; the label should just say what the numbers are. */
  parts.push(section('Acclimatization state', keyValues([
    ['Adaptation state', day.adaptation.toFixed(3)],
    ['Personal limit', pretty(`${day.limit.toFixed(2)} degC`) + '-WBGT'],
    ['Day on job', String(day.dayOnJob)],
  ])));

  root.replaceChildren(...parts);
}
