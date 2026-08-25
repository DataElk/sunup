/* ============================================================================
   RampStrip — the signature component.

   The previous version rendered at ~13px per cell with pale fills and an
   adaptation line nobody could see. A signature element you cannot read is not
   a signature. This one is sized to be the largest thing on a roster row.

   Encodings, kept deliberately separate:

     BAR HEIGHT  peak WBGT. A position encoding, so it costs no colour.
     BAR FILL    the prescription band. Colour is for FIT, never temperature.
     INK LINE    adaptation, drawn across the cells in --adapt-line. Not a third
                 colour scale — deliberately monochrome so it reads on top of
                 the bars without competing with them.
     DASHED      everything after today, at --projected-alpha. Honesty
                 requirement, not decoration.
   ========================================================================== */

const SVG_NS = 'http://www.w3.org/2000/svg';

/* Bar height is scaled against a fixed WBGT window, not each strip's own range,
   so two workers are directly comparable. Autoscaling would make a mild crew
   look identical to a brutal one. */
const WBGT_FLOOR = 22;
const WBGT_CEIL = 36;

/* Sized so that at the roster's strip column width the SVG renders at roughly
   1:1 and stands ~80px tall — taller than any text block on the row. The
   adaptation line gets the same 67px of travel, which is what makes it a curve
   you can read rather than a smudge. */
const CELL_W = 28;
const GAP = 2;
const TOP = 4;
const HEAT_H = 72;
const BASE = TOP + HEAT_H;
const HEIGHT = BASE + 9;

function el(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

function heatHeight(peak) {
  if (peak === null || peak === undefined) return 0;
  const clamped = Math.max(WBGT_FLOOR, Math.min(WBGT_CEIL, peak));
  return Math.max(2, ((clamped - WBGT_FLOOR) / (WBGT_CEIL - WBGT_FLOOR)) * HEAT_H);
}

/**
 * @param {Array}  strip  day payloads, oldest first
 * @param {string} today  ISO date of the current day
 * @param {object} opts   {labels: boolean}
 */
export function rampStrip(strip, today, opts = {}) {
  const width = strip.length * CELL_W;
  const svg = el('svg', {
    class: 'ramp',
    viewBox: `0 0 ${width} ${HEIGHT}`,
    /* Left-aligned when the box is a different aspect to the content, which
       happens in the card layout where the strip is sized by height. The
       default xMidYMid centres it and leaves a ragged left edge against the
       text above it. */
    preserveAspectRatio: 'xMinYMid meet',
    role: 'img',
  });
  svg.setAttribute('aria-label', describe(strip, today));

  strip.forEach((day, index) => {
    const x = index * CELL_W;
    const cellClass = day.absent ? 'cell-absent'
      : (day.projected ? 'cell-projected' : 'cell-observed');
    svg.appendChild(el('rect', {
      class: cellClass,
      x: x + 0.5, y: TOP, width: CELL_W - 1, height: HEAT_H,
    }));

    if (!day.absent) {
      const h = heatHeight(day.peakWbgt);
      const bar = el('rect', {
        class: day.projected ? 'bar bar-projected' : 'bar',
        x: x + GAP + 1, y: BASE - h, width: CELL_W - 2 * GAP - 2, height: h,
      });
      bar.setAttribute('data-status', day.status);
      const title = el('title');
      title.textContent = `${day.date} — ${day.minutes} min`
        + `, calendar ${day.calendarMinutes}`
        + (day.peakWbgt === null ? '' : `, peak ${day.peakWbgt} degC`);
      bar.appendChild(title);
      svg.appendChild(bar);
    }

    if (day.date === today) {
      svg.appendChild(el('line', {
        class: 'today-mark', x1: x + 0.5, y1: 0, x2: x + 0.5, y2: BASE + 3,
      }));
      svg.appendChild(el('line', {
        class: 'today-mark',
        x1: x + CELL_W - 0.5, y1: 0, x2: x + CELL_W - 0.5, y2: BASE + 3,
      }));
    }

    if (opts.labels) {
      const tick = el('text', {
        class: 'tick', x: x + CELL_W / 2, y: HEIGHT - 1, 'text-anchor': 'middle',
      });
      tick.textContent = day.date.slice(8);
      svg.appendChild(tick);
    }
  });

  /* Adaptation, drawn across the cells rather than beneath them, so the strip
     stays compact enough to be a row element. Split at the observed/projected
     seam so the dash can change without a gap. */
  const point = (day, index) => {
    const x = index * CELL_W + CELL_W / 2;
    const y = BASE - 2 - day.adaptation * (HEAT_H - 5);
    return `${x},${y}`;
  };
  const seam = strip.filter((d) => !d.projected).length;
  if (seam > 1) {
    svg.appendChild(el('polyline', {
      class: 'adapt-line',
      points: strip.slice(0, seam).map((d, i) => point(d, i)).join(' '),
    }));
  }
  if (seam < strip.length) {
    const from = Math.max(seam - 1, 0);
    svg.appendChild(el('polyline', {
      class: 'adapt-line-projected',
      points: strip.slice(from).map((d, i) => point(d, from + i)).join(' '),
    }));
  }

  return svg;
}

/** Text alternative. The strip must be readable without seeing it. */
export function describe(strip, today) {
  const current = strip.find((d) => d.date === today);
  const ahead = strip.filter((d) => d.projected);
  const parts = [];
  if (current) {
    parts.push(`today ${current.minutes} minutes against a calendar allowance of `
      + `${current.calendarMinutes}`);
  }
  if (ahead.length) {
    parts.push(`projected ${ahead[ahead.length - 1].minutes} minutes by `
      + `${ahead[ahead.length - 1].date}`);
  }
  return `Exposure and adaptation strip: ${parts.join('; ')}.`;
}

export const STRIP_METRICS = { CELL_W, HEIGHT, WBGT_FLOOR, WBGT_CEIL };
