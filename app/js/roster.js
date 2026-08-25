/* ============================================================================
   Roster — the primary view, full width.

   The crew is a DESIGNED COMPARISON, not a sample. A matched pair sits at the
   top, adjacent and marked: same site, same trade, same day count, differing
   only in start time. M3 measured shift timing as the strongest available
   lever, so shift is a primary column here, not 9px grey metadata.

   Rule 12: every row carries a signed mismatch indicator from the --mismatch-*
   scale — magenta where the calendar allows MORE than the model
   (under-protection), teal where it allows less. It encodes MAGNITUDE, not
   existence: the stripe's width and opacity scale with the gap as a fraction of
   the shift. Flagging five of six rows identically was the same as flagging
   none of them. Status chips stay severity-coloured; mismatch is a separate
   channel.

   Rule 13: a restricted worker says WHY — read off the binding hour, so no two
   rows say the same thing — and names the lever that recovers the hours,
   priced in minutes.

   Rule 10: the adaptation state never appears here. This file never reads it.

   DENSITY: `desktop` renders a table, `touch` renders cards. Not a table with
   bigger padding — the row-height token never bound, because the ramp strip
   already makes rows ~100px tall, so "touch mode" was desktop with larger type
   and nothing else. A field tablet gets one worker per card, no columns.
   ========================================================================== */

import { rampStrip } from './rampstrip.js';
import { pretty } from './format.js';

const SEVERITY = { stop: 0, restricted: 1, reduced: 2, cleared: 3, absent: 4 };

/* Enough height to show an expanded card and still see the next worker. */
const ROOMY = window.matchMedia('(min-height: 900px) and (min-width: 600px)');

const STATUS_TEXT = {
  cleared: 'Full shift',
  reduced: 'Reduced',
  restricted: 'Restricted',
  stop: 'No work',
  absent: 'Absent',
};

const COLUMNS = [
  ['Worker', 'col-worker'],
  ['Start', 'col-shift'],
  ['Status', 'col-status'],
  ['Today', 'col-today num'],
  ['Calendar vs model', 'col-cf'],
  ['Why', 'col-reason'],
  ['7 days behind · today · 6 ahead', 'col-strip'],
];

function td(className, ...children) {
  const cell = document.createElement('td');
  if (className) cell.className = className;
  for (const child of children) {
    if (child === null || child === undefined) continue;
    cell.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return cell;
}

function div(className, text) {
  const node = document.createElement('div');
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function span(className, text) {
  const node = document.createElement('span');
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* --- Cell parts, shared by both densities --------------------------------- */

function pairFlag(worker) {
  if (!worker.pair) return null;
  return span('pair-flag', worker.pair === 'a' ? 'PAIR A' : 'PAIR B');
}

function workerCell(worker) {
  const wrap = document.createElement('div');
  const line = document.createElement('div');
  const flag = pairFlag(worker);
  if (flag) line.appendChild(flag);
  line.appendChild(span('name', worker.name));
  wrap.append(line, div('sub',
    `${worker.trade} · ${worker.workClass} · ${worker.siteLabel} · day ${worker.today.dayOnJob}`));
  return wrap;
}

/* The shift-hours line that used to sit under the time is gone: it read "8 h"
   on all six rows, and the drawer already gives the full window. */
function shiftCell(worker, earlyStart) {
  const time = div('shift', worker.shift);
  if (worker.shiftStart > earlyStart) time.classList.add('shift-late');
  return time;
}

function statusChip(status) {
  const chip = span('chip', STATUS_TEXT[status] || status);
  chip.setAttribute('data-status', status);
  return chip;
}

function todayCell(day) {
  const wrap = document.createElement('div');
  wrap.append(div('minutes', String(day.minutes)),
              div('minutes-unit', 'min'));   // the column header says TODAY
  return wrap;
}

function mismatchBadge(day) {
  const badge = span('mismatch', day.mismatch === 'none'
    ? 'agree'
    : `${day.divergence > 0 ? '+' : ''}${day.divergence} min`);
  badge.setAttribute('data-mismatch', day.mismatch);
  badge.title = day.mismatch === 'over'
    ? 'The calendar allows MORE than the model — under-protection.'
    : (day.mismatch === 'under'
      ? 'The calendar allows LESS than the model — hours the blanket rule discards.'
      : 'The calendar and the model agree.');
  return badge;
}

/* The counterfactual as a RELATIONSHIP: one track, the calendar's allowance as
   the reference span, the model's inside it, and the gap between them tinted by
   sign. Two adjacent numbers with a strikethrough was a puzzle, not a
   comparison. */
function counterfactual(day, shiftHours) {
  const full = Math.max(shiftHours * 60, day.calendarMinutes, day.minutes, 1);
  const wrap = div('cf');

  const track = div('cf-track');
  const calendar = div('cf-calendar');
  calendar.style.width = `${(day.calendarMinutes / full) * 100}%`;

  const gap = div('cf-gap');
  gap.setAttribute('data-mismatch', day.mismatch);
  const low = Math.min(day.minutes, day.calendarMinutes);
  const high = Math.max(day.minutes, day.calendarMinutes);
  gap.style.left = `${(low / full) * 100}%`;
  gap.style.width = `${((high - low) / full) * 100}%`;

  const model = div('cf-model');
  model.setAttribute('data-status', day.status);
  model.style.width = `${(day.minutes / full) * 100}%`;

  track.append(calendar, gap, model);

  /* One phrase, one element. As four flex children it broke wherever the
     column got tight -- "calendar 480 →" on one line and "model 135" on the
     next, which strands the arrow and reads as two facts instead of one
     comparison. */
  const read = div('cf-read');
  const phrase = span('cf-phrase num',
    `calendar ${day.calendarMinutes} → model ${day.minutes}`);
  read.append(phrase, mismatchBadge(day));

  wrap.append(track, read);
  return wrap;
}

/* Rule 13: the diagnosis, then the lever priced in minutes. */
function reasonCell(worker) {
  const wrap = div('reason');
  wrap.append(div('reason-what', pretty(worker.levers.reason)));
  /* The short form, not the sentence: the column is narrow and the sentence
     belongs in the drawer. Still priced in minutes. */
  const lever = div('reason-lever', pretty(worker.levers.short));
  lever.title = worker.levers.detail;
  wrap.append(lever);
  return wrap;
}

/* --- Rule 12: magnitude, not existence ------------------------------------ */

/** The gap as a fraction of the full shift, 0..1. Drives width and opacity. */
function mismatchWeight(worker) {
  const full = Math.max(worker.shiftHours * 60, 1);
  return Math.min(1, Math.abs(worker.today.divergence) / full);
}

function applyMismatch(element, worker) {
  const day = worker.today;
  element.setAttribute('data-mismatch', day.mismatch);
  element.style.setProperty('--mismatch-weight', mismatchWeight(worker).toFixed(3));
}

/* --- Sorting -------------------------------------------------------------- */

function ordered(data) {
  return [...data.workers].sort((a, b) => {
    if (a.pair && b.pair) return a.pair < b.pair ? -1 : 1;
    if (a.pair) return -1;
    if (b.pair) return 1;
    const bySeverity = SEVERITY[a.today.status] - SEVERITY[b.today.status];
    return bySeverity !== 0 ? bySeverity : a.today.minutes - b.today.minutes;
  });
}

function selectable(element, worker, group, onSelect) {
  const select = () => {
    for (const other of group) other.setAttribute('aria-selected', 'false');
    element.setAttribute('aria-selected', 'true');
    onSelect(worker);
  };
  element.tabIndex = 0;
  element.setAttribute('aria-selected', 'false');
  element.addEventListener('click', select);
  element.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      select();
    }
  });
}

/* --- Desktop: a table ------------------------------------------------------ */

function renderTable(data, onSelect) {
  const table = document.createElement('table');
  table.className = 'grid';

  const colgroup = document.createElement('colgroup');
  /* The strip gets the widest column. It is the signature element and the
     only one whose job is comparison across fourteen days. */
  for (const width of ['18%', '6%', '8%', '6%', '16%', '14%', '32%']) {
    const col = document.createElement('col');
    col.style.width = width;
    colgroup.appendChild(col);
  }

  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  for (const [label, cls] of COLUMNS) {
    const th = document.createElement('th');
    th.className = cls;
    th.textContent = label;
    headRow.appendChild(th);
  }
  head.appendChild(headRow);

  const body = document.createElement('tbody');
  const rows = [];
  const workers = ordered(data);
  for (const worker of workers) {
    const day = worker.today;
    const row = document.createElement('tr');
    row.setAttribute('data-worker', worker.id);
    applyMismatch(row, worker);
    if (worker.pair) row.setAttribute('data-pair', worker.pair);

    row.append(
      td('', workerCell(worker)),
      td('', shiftCell(worker, data.earlyStart)),
      td('', statusChip(day.status)),
      td('num', todayCell(day)),
      td('', counterfactual(day, worker.shiftHours)),
      td('', reasonCell(worker)),
      td('', rampStrip(worker.strip, data.today)),
    );
    rows.push(row);
    body.appendChild(row);
  }
  rows.forEach((row, index) => selectable(row, workers[index], rows, onSelect));

  table.append(colgroup, head, body);
  return table;
}

/* --- Touch: cards ---------------------------------------------------------- */

function renderCards(data, onSelect) {
  const list = document.createElement('div');
  list.className = 'cards';
  const cards = [];
  const workers = ordered(data);

  for (const worker of workers) {
    const day = worker.today;
    const card = document.createElement('article');
    card.className = 'card';
    card.setAttribute('data-worker', worker.id);
    applyMismatch(card, worker);
    if (worker.pair) card.setAttribute('data-pair', worker.pair);

    const head = div('card-head');
    const identity = document.createElement('div');
    const line = document.createElement('div');
    const flag = pairFlag(worker);
    if (flag) line.appendChild(flag);
    line.appendChild(span('name', worker.name));
    identity.append(line, div('sub',
      `${worker.trade} · ${worker.workClass} · ${worker.siteLabel} · day ${worker.today.dayOnJob}`));
    head.append(identity, span('spacer'), statusChip(day.status));

    const figures = div('card-figures');
    const minutes = div('card-metric');
    minutes.append(div('minutes', String(day.minutes)), div('minutes-unit', 'min today'));
    const start = div('card-start');
    const time = div('shift', worker.shift);
    if (worker.shiftStart > data.earlyStart) time.classList.add('shift-late');
    start.append(div('card-label', 'Start'), time);
    figures.append(minutes, start, mismatchBadge(day));

    /* Everything below the summary collapses. On a phone the expanded card is
       ~380px tall and you get two and a half workers per screen, which is not a
       roster -- it is a slideshow. On a tablet there is room, so the default
       flips with the viewport rather than being hardcoded. */
    const detail = div('card-detail');
    detail.append(counterfactual(day, worker.shiftHours),
                  reasonCell(worker),
                  rampStrip(worker.strip, data.today, { labels: true }));

    const more = document.createElement('button');
    more.className = 'btn btn-quiet card-more';
    more.textContent = 'Full detail';
    more.addEventListener('click', (event) => {
      event.stopPropagation();
      onSelect(worker);
    });
    detail.appendChild(more);

    card.append(head, figures, detail);
    card.setAttribute('data-expanded', String(ROOMY.matches));
    card.setAttribute('aria-expanded', String(ROOMY.matches));
    cards.push(card);
    list.appendChild(card);
  }

  /* A tap toggles the card open; the drawer is reached from the button inside
     it. Tapping a collapsed card to open a drawer over the top of it would hide
     the list you were reading. */
  cards.forEach((card) => {
    card.tabIndex = 0;
    const toggle = () => {
      const open = card.getAttribute('data-expanded') !== 'true';
      card.setAttribute('data-expanded', String(open));
      card.setAttribute('aria-expanded', String(open));
    };
    card.addEventListener('click', toggle);
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggle();
      }
    });
  });
  return list;
}

/* --- The crew strip -------------------------------------------------------- */

/* What the table cannot say, and the two stories the roster buries.

   The pair is the product's argument and it sat in two rows a reader had to
   diff by eye. The teal case -- a worker the calendar holds BACK -- is the
   second-strongest thing here and severity sorting pushes it to the bottom,
   because "cleared for more hours than the rule allows" is the least severe
   thing on the screen. Both get stated in words. */
function crewStrip(data) {
  const summary = crewSummary(data);
  const strip = div('crewbar');

  const totals = div('crewpanel');
  totals.append(div('crewpanel-label', 'Crew today'));
  const figures = div('crew-figures');
  const modelFig = div('crew-figure');
  modelFig.append(div('crew-value num', String(summary.model)),
                  div('crew-unit', 'worker-min, model'));
  const calFig = div('crew-figure');
  calFig.append(div('crew-value num crew-value-muted', String(summary.calendar)),
                div('crew-unit', 'worker-min, OSHA calendar'));
  figures.append(modelFig, calFig);
  totals.append(figures, div('crewpanel-note',
    `${summary.over} of ${summary.crew} under-protected by the calendar, `
    + `${summary.under} held back by it.`));

  const pairPanel = div('crewpanel');
  pairPanel.append(div('crewpanel-label', 'The matched pair'));
  const [a, b] = data.workers.filter((w) => w.pair)
    .sort((x, y) => (x.pair < y.pair ? -1 : 1));
  if (a && b) {
    const compare = div('pair-compare');
    for (const worker of [a, b]) {
      const cell = div('pair-cell');
      cell.append(div('pair-when', worker.shift),
                  div('crew-value num', String(worker.today.minutes)),
                  div('crew-unit', 'min'));
      compare.appendChild(cell);
    }
    pairPanel.append(compare, div('crewpanel-note',
      `Same site, same trade, day ${a.today.dayOnJob} for both. `
      + `The only difference is the start time, and it is worth `
      + `${a.today.minutes - b.today.minutes} min today.`));
  }

  const discarded = div('crewpanel');
  discarded.append(div('crewpanel-label', 'Hours the calendar discards'));
  const held = data.workers.filter((w) => w.today.mismatch === 'under')
    .sort((x, y) => y.today.divergence - x.today.divergence);
  if (held.length) {
    const worst = held[0];
    const value = div('crew-value num crew-value-under', `+${worst.today.divergence}`);
    discarded.append(value, div('crew-unit', 'min, this worker alone'),
      div('crewpanel-note',
        `${worst.name} is cleared for ${worst.today.minutes} min. The `
        + `day-${worst.today.dayOnJob} calendar step allows `
        + `${worst.today.calendarMinutes}. The model is not only more `
        + `protective than the rule — here it is less, and correctly.`));
  } else {
    discarded.append(div('crewpanel-note',
      'No worker is cleared for more than the calendar allows today.'));
  }

  strip.append(totals, pairPanel, discarded);
  return strip;
}

/* --- Entry ----------------------------------------------------------------- */

export function renderRoster(root, data, onSelect) {
  const touch = document.documentElement.getAttribute('data-density') === 'touch';
  const view = touch ? renderCards(data, onSelect) : renderTable(data, onSelect);
  root.replaceChildren(view, crewStrip(data));
  return ordered(data)[0];
}

export function crewSummary(data) {
  const model = data.workers.reduce((s, w) => s + w.today.minutes, 0);
  const calendar = data.workers.reduce((s, w) => s + w.today.calendarMinutes, 0);
  const stopped = data.workers.filter((w) => w.today.status === 'stop').length;
  const over = data.workers.filter((w) => w.today.mismatch === 'over').length;
  const under = data.workers.filter((w) => w.today.mismatch === 'under').length;
  return { model, calendar, stopped, over, under, delta: model - calendar,
           crew: data.workers.length };
}
