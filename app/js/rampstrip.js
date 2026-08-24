/* ============================================================================
   RampStrip — the signature component.

   DESIGN_SYSTEM.md: "the horizontal strip of day cells showing seven days
   behind, today, and six ahead. Heat as bar height, adaptation as a line
   beneath, past solid, future dashed."

   Two encodings, kept deliberately separate:

     BAR HEIGHT  = peak WBGT for that shift. A position encoding, so it reads
                   as magnitude without spending any colour.
     BAR FILL    = the prescription band. Non-negotiable 12: colour encodes
                   MISMATCH — whether the plan fits the person — never
                   temperature. A 40 degC day with an adapted crew is green.
     LINE        = adaptation state, on the --adapt ramp, drawn beneath so the
                   two series can share the cell without being confused.

   Everything after today is drawn dashed at --projected-alpha. That is an
   honesty requirement (non-negotiable 11), not a stylistic one.
   ========================================================================== */

const SVG_NS = 'http://www.w3.org/2000/svg';

/* Bar height is scaled against a fixed WBGT window rather than the data's own
   range, so two workers' strips are directly comparable. Autoscaling per strip
   would make a mild crew look identical to a brutal one. */
const WBGT_FLOOR = 22;
const WBGT_CEIL = 36;

const CELL_W = 20;
const HEAT_TOP = 2;
const HEAT_H = 34;
const ADAPT_TOP = 42;
const ADAPT_H = 16;
const TOTAL_H = 62;

function el(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, String(value));
  }
  return node;
}

function heatHeight(peak) {
  if (peak === null || peak === undefined) return 0;
  const clamped = Math.max(WBGT_FLOOR, Math.min(WBGT_CEIL, peak));
  return ((clamped - WBGT_FLOOR) / (WBGT_CEIL - WBGT_FLOOR)) * HEAT_H;
}

/**
 * @param {Array} strip   day payloads, oldest first
 * @param {string} today  ISO date of the current day
 * @param {object} opts   {mini: boolean}
 */
export function rampStrip(strip, today, opts = {}) {
  const mini = Boolean(opts.mini);
  const width = strip.length * CELL_W;
  const svg = el('svg', {
    class: mini ? 'ramp ramp-mini' : 'ramp',
    viewBox: `0 0 ${width} ${mini ? ADAPT_TOP + ADAPT_H : TOTAL_H}`,
    preserveAspectRatio: 'none',
    role: 'img',
  });
  svg.setAttribute('aria-label', describe(strip, today));

  // Baseline the bars sit on.
  svg.appendChild(el('line', {
    class: 'axis', x1: 0, y1: HEAT_TOP + HEAT_H, x2: width, y2: HEAT_TOP + HEAT_H,
  }));

  strip.forEach((day, index) => {
    const x = index * CELL_W;
    const isProjected = day.projected;

    // Cell frame: solid for observed, dashed for projected.
    svg.appendChild(el('rect', {
      class: isProjected ? 'cell-projected' : 'cell-observed',
      x: x + 0.5, y: HEAT_TOP, width: CELL_W - 1, height: HEAT_H, fill: 'none',
    }));

    if (!day.absent) {
      const h = heatHeight(day.peakWbgt);
      const bar = el('rect', {
        class: 'bar',
        x: x + 3, y: HEAT_TOP + HEAT_H - h, width: CELL_W - 6, height: h,
      });
      bar.setAttribute('data-status', day.status);
      if (isProjected) bar.setAttribute('opacity', 'var(--projected-alpha)');
      svg.appendChild(bar);
    }

    if (day.date === today) {
      svg.appendChild(el('line', {
        class: 'today-mark',
        x1: x + 0.5, y1: 0, x2: x + 0.5, y2: mini ? ADAPT_TOP + ADAPT_H : TOTAL_H,
      }));
    }
  });

  // Adaptation line, split at the observed/projected seam so the dash can
  // change without a gap appearing.
  const point = (day, index) => {
    const x = index * CELL_W + CELL_W / 2;
    const y = ADAPT_TOP + ADAPT_H - day.adaptation * ADAPT_H;
    return `${x},${y}`;
  };
  const observed = strip.filter((d) => !d.projected);
  const seam = observed.length;
  if (seam > 1) {
    svg.appendChild(el('polyline', {
      class: 'adapt-line',
      points: observed.map((d, i) => point(d, i)).join(' '),
    }));
  }
  if (seam < strip.length) {
    const tail = strip.slice(Math.max(seam - 1, 0));
    svg.appendChild(el('polyline', {
      class: 'adapt-line projected',
      points: tail.map((d, i) => point(d, Math.max(seam - 1, 0) + i)).join(' '),
    }));
  }

  return svg;
}

/** Text alternative — the strip must be readable without seeing it. */
export function describe(strip, today) {
  const current = strip.find((d) => d.date === today);
  const ahead = strip.filter((d) => d.projected);
  const parts = [];
  if (current) {
    parts.push(`today ${current.minutes} minutes, calendar would allow ${current.calendarMinutes}`);
  }
  if (ahead.length) {
    const last = ahead[ahead.length - 1];
    parts.push(`projected ${last.minutes} minutes by ${last.date}`);
  }
  return `Exposure and adaptation strip: ${parts.join('; ')}.`;
}

export const STRIP_METRICS = { CELL_W, WBGT_FLOOR, WBGT_CEIL };
