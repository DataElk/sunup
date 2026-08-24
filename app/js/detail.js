/* ============================================================================
   Worker detail — the "why" panel.

   This is the ONLY place the adaptation state is allowed to appear
   (DESIGN_SYSTEM.md non-negotiable 10). The foreman opens this asking why a man
   he thinks is fine has been cut to 135 minutes, and the answer has to be here
   in full: the state, the personal limit it implies, and the hour that binds.

   The hour table is what the engine's HourPrescription made possible. Before
   that fix the interface could state a prescription but not explain it.
   ========================================================================== */

import { rampStrip } from './rampstrip.js';

function section(label, ...children) {
  const wrap = document.createElement('section');
  wrap.className = 'section';
  if (label) {
    const head = document.createElement('div');
    head.className = 'section-label';
    head.textContent = label;
    wrap.appendChild(head);
  }
  wrap.append(...children);
  return wrap;
}

function metric(label, value, sub) {
  const wrap = document.createElement('div');
  wrap.className = 'metric';
  const l = document.createElement('div');
  l.className = 'metric-label';
  l.textContent = label;
  const v = document.createElement('div');
  v.className = 'metric-value';
  v.textContent = value;
  wrap.append(l, v);
  if (sub) {
    const s = document.createElement('div');
    s.className = 'metric-sub';
    s.textContent = sub;
    wrap.appendChild(s);
  }
  return wrap;
}

/* The full-width counterfactual. Non-negotiable 9: this appears on every worker
   view, because the model's output without the calendar's is just a number. */
function counterfactual(day, shiftHours) {
  const wrap = document.createElement('div');
  wrap.className = 'counterfactual';

  const left = document.createElement('div');
  left.className = 'side';
  const ll = document.createElement('div');
  ll.className = 'cf-label';
  ll.textContent = `OSHA calendar · day ${day.dayOnJob}`;
  const lv = document.createElement('div');
  lv.className = 'cf-value num';
  lv.textContent = `${day.calendarMinutes} min`;
  left.append(ll, lv);

  const delta = document.createElement('div');
  delta.className = 'delta num';
  delta.textContent = `${day.divergence > 0 ? '+' : ''}${day.divergence}`;

  const right = document.createElement('div');
  right.className = 'side model';
  const rl = document.createElement('div');
  rl.className = 'cf-label';
  rl.textContent = 'Acclimate · measured';
  const rv = document.createElement('div');
  rv.className = 'cf-value num';
  rv.textContent = `${day.minutes} min`;
  right.append(rl, rv);

  wrap.append(left, delta, right);
  wrap.title = `The calendar assigns ${day.calendarMinutes} minutes from the day `
    + `count alone. The model measures this worker's exposure and prescribes `
    + `${day.minutes}.`;
  return wrap;
}

function hourTable(day) {
  const table = document.createElement('table');
  table.className = 'hours';
  const head = document.createElement('thead');
  head.innerHTML = '';
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
  const bindingHour = day.hours.find((h) => h.minutes === fewest);

  const body = document.createElement('tbody');
  for (const hour of day.hours) {
    const tr = document.createElement('tr');
    tr.setAttribute('data-stop', String(hour.stop));
    tr.setAttribute('data-binding', String(hour === bindingHour));
    const cells = [
      [`${String(hour.hour).padStart(2, '0')}:00`, ''],
      [hour.wbgt.toFixed(1), 'num'],
      [hour.limit.toFixed(1), 'num'],
      [`${hour.overLimit > 0 ? '+' : ''}${hour.overLimit.toFixed(1)}`, 'num'],
      [`${hour.minutes} min`, 'num'],
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
  return { table, bindingHour };
}

export function renderDetail(root, worker, data) {
  if (!worker) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'Select a worker.';
    root.replaceChildren(empty);
    return;
  }

  const day = worker.today;
  const parts = [];

  parts.push(section(null,
    metric('Prescribed today', `${day.minutes} min`,
           `${worker.shift} · ${worker.trade} · ${worker.workClass} work`)));

  parts.push(section('Counterfactual', counterfactual(day, worker.shiftHours)));

  parts.push(section(`${data.daysBehind} days behind · today · ${data.daysAhead} ahead`,
                     rampStrip(worker.strip, data.today)));

  if (day.hours.length) {
    const { table, bindingHour } = hourTable(day);
    const why = document.createElement('p');
    why.style.margin = '0 0 var(--space-2)';
    why.textContent = bindingHour
      ? `Binding hour ${String(bindingHour.hour).padStart(2, '0')}:00 — `
        + `${bindingHour.overLimit > 0
            ? `${bindingHour.overLimit.toFixed(1)} degC above this worker's limit`
            : 'within limit'}.`
      : '';
    parts.push(section('Why — hour by hour', why, table));
  }

  /* The adaptation state. Permitted HERE and nowhere else. */
  const state = document.createElement('dl');
  state.className = 'kv';
  const rows = [
    ['Adaptation state', day.adaptation.toFixed(3)],
    ['Personal limit', `${day.limit.toFixed(2)} degC-WBGT`],
    ['Day on job', `${day.dayOnJob}`],
    ['Site', worker.site === 'hot_site' ? 'p95 (hotter)' : 'p5 (cooler)'],
  ];
  for (const [key, value] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = key;
    const dd = document.createElement('dd');
    dd.className = 'num';
    dd.textContent = value;
    state.append(dt, dd);
  }
  parts.push(section('State — detail view only', state));

  root.replaceChildren(...parts);
}
