/* ============================================================================
   Forecast vs actual — M5's validation view.

   The ramp strip draws six projected days and marks them dashed. That is an
   honesty gesture, not evidence. This view answers the question the gesture
   raises: standing a week earlier, WAS THE PROJECTION RIGHT?

   The chart is one paired series per subject — predicted minutes against actual
   minutes, day by day, with the error called out beneath. Predicted keeps the
   projected treatment it has everywhere else in the product (dashed,
   --projected-alpha) so a reader does not have to learn a second visual
   language for the same idea.

   WHAT IT REFUSES TO DO. It does not print an accuracy percentage as a headline.
   One of the two subjects is prescribed zero minutes on every day of the
   horizon, predicted and actual, and so scores a perfect band match while
   demonstrating no skill at all; the builder flags that case and this view says
   so on the card rather than banking the number. A metric that cannot be wrong
   is not a metric.
   ========================================================================== */

const CELL_W = 120;
const CHART_H = 150;
const TOP = 8;
const SVG_NS = 'http://www.w3.org/2000/svg';

function el(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
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

/* --- The paired chart ------------------------------------------------------ */

function chart(subject) {
  const pairs = subject.pairs;
  const full = subject.shiftHours * 60;
  const width = pairs.length * CELL_W;
  const height = CHART_H;
  const scale = (minutes) => TOP + (1 - minutes / full) * (height - TOP - 26);

  const svg = el('svg', {
    class: 'overlay-chart',
    viewBox: `0 0 ${width} ${height}`,
    preserveAspectRatio: 'xMinYMid meet',
    role: 'img',
  });
  svg.setAttribute('aria-label', describe(subject));

  // Full-shift reference.
  svg.appendChild(el('line', {
    class: 'overlay-baseline',
    x1: 0, y1: scale(full), x2: width, y2: scale(full),
  }));
  svg.appendChild(el('line', {
    class: 'overlay-baseline',
    x1: 0, y1: scale(0), x2: width, y2: scale(0),
  }));

  pairs.forEach((pair, index) => {
    const x = index * CELL_W + CELL_W / 2;
    const py = scale(pair.predicted.minutes);
    const ay = scale(pair.actual.minutes);

    // The error, drawn as the gap it is.
    if (pair.predicted.minutes !== pair.actual.minutes) {
      svg.appendChild(el('line', {
        class: 'overlay-error', x1: x, y1: py, x2: x, y2: ay,
      }));
    }

    const predicted = el('circle', {
      class: 'overlay-dot overlay-predicted', cx: x, cy: py, r: 5,
    });
    predicted.appendChild(titleFor('projected', pair.predicted));
    svg.appendChild(predicted);

    const actual = el('circle', {
      class: 'overlay-dot overlay-actual', cx: x, cy: ay, r: 5,
    });
    actual.setAttribute('data-status', pair.actual.status);
    actual.appendChild(titleFor('actual', pair.actual));
    svg.appendChild(actual);

    const tick = el('text', {
      class: 'overlay-tick', x, y: height - 12, 'text-anchor': 'middle',
    });
    tick.textContent = pair.actual.date.slice(8);
    svg.appendChild(tick);

    if (pair.minutesError !== 0) {
      const err = el('text', {
        class: 'overlay-errlabel', x, y: height - 1, 'text-anchor': 'middle',
      });
      err.textContent = `${pair.minutesError > 0 ? '+' : ''}${pair.minutesError}`;
      svg.appendChild(err);
    }
  });

  // Connect each series so the shape is readable.
  for (const [cls, key] of [['overlay-line overlay-predicted-line', 'predicted'],
                            ['overlay-line overlay-actual-line', 'actual']]) {
    svg.appendChild(el('polyline', {
      class: cls,
      points: pairs.map((p, i) =>
        `${i * CELL_W + CELL_W / 2},${scale(p[key].minutes)}`).join(' '),
    }));
  }

  return svg;
}

function titleFor(kind, day) {
  const node = el('title');
  node.textContent = `${day.date} — ${kind} ${day.minutes} min, `
    + `peak ${day.peakWbgt} degC`;
  return node;
}

export function describe(subject) {
  return `${subject.name}, ${subject.shiftFull}: projected against actual `
    + `prescribed minutes over ${subject.pairs.length} days. Mean absolute error `
    + `${subject.meanAbsMinutesError} minutes, prescription band matched on `
    + `${subject.bandsMatched} of ${subject.bandsTotal} days.`;
}

/* --- Cards ----------------------------------------------------------------- */

function metric(value, label, className) {
  const wrap = div('overlay-metric');
  wrap.append(div(`overlay-value num ${className || ''}`.trim(), value),
              div('overlay-label', label));
  return wrap;
}

function card(subject, data) {
  const wrap = document.createElement('article');
  wrap.className = 'overlay-card';
  if (subject.pair) wrap.setAttribute('data-pair', subject.pair);

  const head = div('overlay-head');
  const identity = document.createElement('div');
  const line = document.createElement('div');
  if (subject.pair) {
    line.appendChild(span('pair-flag',
      subject.pair === 'a' ? 'PAIR A' : 'PAIR B'));
  }
  line.appendChild(span('name', subject.name));
  identity.append(line, div('sub',
    `${subject.trade} · ${subject.shiftFull} · ${subject.siteLabel}`));
  head.append(identity);

  /* Band first. A supervisor does not experience "34 minutes of error" -- he
     experiences being told Reduced when the day turned out Restricted. The
     minute figures are the diagnosis behind that, not the headline. */
  const figures = div('overlay-figures');
  const bias = subject.meanSignedMinutesError;
  figures.append(
    metric(`${subject.bandsMatched}/${subject.bandsTotal}`,
           'prescription band correct',
           subject.degenerate ? 'overlay-value-void' : ''),
    metric(`${bias > 0 ? '+' : ''}${bias}`,
           `bias, min — ${subject.biasDirection}`,
           bias > 0 ? 'overlay-value-permissive' : 'overlay-value-safe'),
    metric(`${subject.meanAbsMinutesError}`, 'mean error, min'),
    metric(`${subject.maxAbsMinutesError}`, 'worst day, min'),
    metric(`${subject.adaptationErrorAtHorizon > 0 ? '+' : ''}`
           + `${subject.adaptationErrorAtHorizon.toFixed(3)}`,
           'state error at day 7'));

  wrap.append(head, figures, chart(subject));

  if (subject.degenerate) {
    const warn = div('overlay-void', subject.degenerateNote);
    wrap.appendChild(warn);
  }
  return wrap;
}

/* --- Entry ----------------------------------------------------------------- */

export function renderOverlay(root, data) {
  const wrap = div('overlay-wrap');

  const intro = div('overlay-intro');
  intro.append(
    div('overlay-asof', `Projected on ${data.asOf}, ${data.horizon} days forward`),
    div('overlay-method', `Method — ${data.method}.`),
    div('overlay-caveat', data.caveat));
  wrap.appendChild(intro);

  /* The mechanism, not just the direction. "Systematically conservative" with
     no cause invites "what else is systematically wrong?" */
  const mech = data.biasMechanism;
  const why = div('overlay-mechanism');
  why.append(div('overlay-mechanism-head', 'Why every miss is low'));
  const bands = div('overlay-bands');
  for (const [label, delta, note] of [
    ['peak hour', mech.peakDelta, 'decides nothing — already zero minutes'],
    [`${String(mech.decisionHours[0]).padStart(2, '0')}:00–`
     + `${String(mech.decisionHours[1]).padStart(2, '0')}:00`,
     mech.decisionBandDelta, 'where the ladder is actually read'],
  ]) {
    const row = div('overlay-band');
    row.append(
      span('overlay-band-label', label),
      span(`overlay-band-delta num ${delta > 0 ? 'overlay-value-permissive' : 'overlay-value-safe'}`,
           `${delta > 0 ? '+' : ''}${delta.toFixed(2)} °C`),
      span('overlay-band-note', note));
    bands.appendChild(row);
  }
  why.append(bands, div('overlay-mechanism-note', mech.note),
             div('overlay-mechanism-fix', `The fix — ${mech.fix}`));
  wrap.appendChild(why);

  const legend = div('overlay-key');
  legend.append(
    span('overlay-swatch overlay-swatch-predicted'), span('', 'projected'),
    span('overlay-swatch overlay-swatch-actual'), span('', 'actual'),
    span('overlay-swatch overlay-swatch-error'), span('', 'error'));
  wrap.appendChild(legend);

  const list = div('overlay-cards');
  for (const subject of data.subjects) list.appendChild(card(subject, data));
  wrap.appendChild(list);

  root.replaceChildren(wrap);
}
