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
import { exceptionLedger } from './exceptions.js';
import { hasConfiguredKey } from './liveweather.js';
import { startSiteBackfill } from './siteweather.js';
import { sitePoint } from './leaflet.js';
import {
  evaluateIntervention, optimizeCrewShift, recommendationFor, suggestIntervention,
  workCapOptions,
} from './interventions.js';
import {
  el, icon, chip, tag, detailsList, breadcrumb, commandBar, panel,
  dismissPanel, toast, confirmDialog, pageHeader, field, select,
} from './ui.js';

const STATUS_TEXT = {
  cleared: 'Full heat-work shift',
  reduced: 'Modified heat-work plan',
  restricted: 'Limited heat work',
  stop: 'Move heat work',
  absent: 'Absent',
};

/* --- Sparkline ---------------------------------------------------------------
   Compact roster history: 14 days in 86px. Bar height is peak WBGT on a fixed
   22-36 degC scale so two workers are comparable; fill is the prescription band.
   Worker detail carries the larger, fully labelled decision charts. */

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

/* Work capacity and thermal load use separate panels and axes. Mixing minutes,
   temperature, and readiness on one scale makes comparison needlessly hard. */
function svgNode(name, attrs = {}, text = null) {
  const ns = 'http://www.w3.org/2000/svg';
  const node = document.createElementNS(ns, name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (text !== null) node.textContent = text;
  return node;
}

function pointsFor(records, start, xAt, yAt, read) {
  return records.map((record, index) => `${xAt(start + index)},${yAt(read(record))}`).join(' ');
}

function chartKey(className, label) {
  const item = el('span', 'chart-legend-item');
  item.append(el('span', `chart-key ${className}`), el('span', null, label));
  return item;
}

function historyChart(records, recalculation = null) {
  const WIDTH = 1000;
  const HEIGHT = 354;
  const LEFT = 62;
  const RIGHT = 24;
  const PLOT_WIDTH = WIDTH - LEFT - RIGHT;
  const CAP_TOP = 40;
  const CAP_HEIGHT = 112;
  const HEAT_TOP = 218;
  const HEAT_HEIGHT = 94;
  const seam = records.filter((record) => !record.projected).length;
  const xAt = (index) => LEFT + (records.length === 1
    ? PLOT_WIDTH / 2 : (index / (records.length - 1)) * PLOT_WIDTH);
  const capY = (value) => CAP_TOP + CAP_HEIGHT
    - (Math.max(0, Math.min(480, value)) / 480) * CAP_HEIGHT;
  const heatY = (value) => HEAT_TOP + HEAT_HEIGHT
    - ((Math.max(SPARK_FLOOR, Math.min(SPARK_CEIL, value)) - SPARK_FLOOR)
      / (SPARK_CEIL - SPARK_FLOOR)) * HEAT_HEIGHT;

  const svg = svgNode('svg', {
    viewBox: `0 0 ${WIDTH} ${HEIGHT}`, preserveAspectRatio: 'xMidYMid meet',
    class: 'worker-trend', role: 'img',
    'aria-label': `Work capacity and heat exposure across ${records.length} days.`,
  });

  svg.append(
    svgNode('text', { class: 'chart-panel-title', x: LEFT, y: 20 }, 'Work capacity'),
    svgNode('text', { class: 'chart-panel-title', x: LEFT, y: 198 }, 'Thermal load'));

  [[0, 0], [240, 0.5], [480, 1]].forEach(([value, ratio]) => {
    const y = CAP_TOP + CAP_HEIGHT - ratio * CAP_HEIGHT;
    svg.append(
      svgNode('line', { class: 'chart-grid', x1: LEFT, y1: y, x2: WIDTH - RIGHT, y2: y }),
      svgNode('text', {
        class: 'axis-label', x: LEFT - 10, y: y + 4, 'text-anchor': 'end',
      }, `${value}`));
  });
  svg.appendChild(svgNode('text', {
    class: 'axis-unit', x: LEFT - 10, y: CAP_TOP - 10, 'text-anchor': 'end',
  }, 'min'));

  [22, 29, 36].forEach((value) => {
    const y = heatY(value);
    svg.append(
      svgNode('line', { class: 'chart-grid', x1: LEFT, y1: y, x2: WIDTH - RIGHT, y2: y }),
      svgNode('text', {
        class: 'axis-label', x: LEFT - 10, y: y + 4, 'text-anchor': 'end',
      }, `${value}°`));
  });
  svg.appendChild(svgNode('text', {
    class: 'axis-unit', x: LEFT - 10, y: HEAT_TOP - 10, 'text-anchor': 'end',
  }, 'WBGT'));

  if (seam < records.length) {
    const seamX = (xAt(Math.max(0, seam - 1)) + xAt(seam)) / 2;
    svg.append(
      svgNode('rect', {
        class: 'forecast-region', x: seamX, y: CAP_TOP,
        width: WIDTH - RIGHT - seamX, height: HEAT_TOP + HEAT_HEIGHT - CAP_TOP,
      }),
      svgNode('line', {
        class: 'forecast-seam', x1: seamX, y1: CAP_TOP,
        x2: seamX, y2: HEAT_TOP + HEAT_HEIGHT,
      }),
      svgNode('text', {
        class: 'forecast-label', x: seamX + 10, y: CAP_TOP + 16,
      }, 'Forecast'));
  }

  const addSeries = (read, yAt, className) => {
    if (seam) {
      svg.appendChild(svgNode('polyline', {
        class: className,
        points: pointsFor(records.slice(0, seam), 0, xAt, yAt, read),
      }));
    }
    if (seam < records.length) {
      const from = Math.max(0, seam - 1);
      svg.appendChild(svgNode('polyline', {
        class: `${className} projected-line`,
        points: pointsFor(records.slice(from), from, xAt, yAt, read),
      }));
    }
  };

  addSeries((record) => record.prescribedMinutes, capY, 'capacity-line');
  addSeries((record) => record.peakWbgt ?? SPARK_FLOOR, heatY, 'heat-line');
  addSeries((record) => record.limit, heatY, 'limit-line');

  records.forEach((record, index) => {
    const x = xAt(index);
    const capacityChanged = recalculationField(recalculation, record.date, 'prescribedMinutes');
    const capacity = svgNode('circle', {
      class: [
        'capacity-point', record.projected ? 'projected-point' : '',
        capacityChanged ? 'calculated-point' : '',
      ].filter(Boolean).join(' '),
      cx: x, cy: capY(record.prescribedMinutes), r: 4,
    });
    capacity.appendChild(svgNode('title', {},
      `${record.date}: ${record.prescribedMinutes} prescribed minutes`));
    svg.appendChild(capacity);

    if (!record.projected && !record.assumed) {
      const actual = svgNode('circle', {
        class: recalculationField(recalculation, record.date, 'actualMinutes')
          ? 'actual-point calculated-point' : 'actual-point',
        cx: x, cy: capY(record.actualMinutes), r: 4,
      });
      actual.appendChild(svgNode('title', {},
        `${record.date}: ${record.actualMinutes} actual minutes`));
      svg.appendChild(actual);
    }

    if (record.peakWbgt !== null && record.peakWbgt !== undefined) {
      const peak = svgNode('circle', {
        class: record.projected ? 'heat-point projected-point' : 'heat-point',
        cx: x, cy: heatY(record.peakWbgt), r: 3.5,
      });
      peak.appendChild(svgNode('title', {},
        `${record.date}: peak ${record.peakWbgt.toFixed(1)} °C, limit ${record.limit.toFixed(1)} °C`));
      svg.appendChild(peak);
    }

    const interval = Math.max(1, Math.ceil(records.length / 7));
    if (index % interval === 0 || index === records.length - 1) {
      svg.appendChild(svgNode('text', {
        class: 'tick', x, y: HEIGHT - 8, 'text-anchor': 'middle',
      }, record.date.slice(5)));
    }
  });

  const legend = el('div', 'chart-legend');
  legend.append(
    chartKey('chart-key-capacity', 'Prescribed minutes'),
    chartKey('chart-key-actual', 'Actual minutes'),
    chartKey('chart-key-heat', 'Peak WBGT'),
    chartKey('chart-key-limit', 'Personal limit'),
    chartKey('chart-key-forecast', 'Forecast'));

  const wrap = el('div', recalculation ? 'history-chart is-updated' : 'history-chart');
  wrap.append(legend, svg);
  return wrap;
}

function hourlyChart(hours, recalculation = null, date = null) {
  const WIDTH = 1000;
  const HEIGHT = 300;
  const LEFT = 62;
  const RIGHT = 24;
  const TOP = 38;
  const TEMP_HEIGHT = 132;
  const WORK_TOP = 218;
  const WORK_HEIGHT = 42;
  const PLOT_WIDTH = WIDTH - LEFT - RIGHT;
  const values = hours.flatMap((hour) => [hour.wbgt, hour.limit]);
  const low = Math.floor(Math.min(...values) - 1);
  const high = Math.ceil(Math.max(...values) + 1);
  const span = Math.max(1, high - low);
  const cell = PLOT_WIDTH / Math.max(1, hours.length);
  const xAt = (index) => LEFT + cell * index + cell / 2;
  const tempY = (value) => TOP + TEMP_HEIGHT - ((value - low) / span) * TEMP_HEIGHT;
  const fewest = Math.min(...hours.map((hour) => hour.minutes));
  const bindingIndex = hours.findIndex((hour) => hour.minutes === fewest);

  const svg = svgNode('svg', {
    viewBox: `0 0 ${WIDTH} ${HEIGHT}`, preserveAspectRatio: 'xMidYMid meet',
    class: 'shift-chart', role: 'img',
    'aria-label': 'Hourly WBGT, personal limit, and recommended work minutes.',
  });

  for (let index = 0; index < 3; index += 1) {
    const value = low + (span * index) / 2;
    const y = tempY(value);
    svg.append(
      svgNode('line', { class: 'chart-grid', x1: LEFT, y1: y, x2: WIDTH - RIGHT, y2: y }),
      svgNode('text', {
        class: 'axis-label', x: LEFT - 10, y: y + 4, 'text-anchor': 'end',
      }, `${value.toFixed(0)}°`));
  }
  svg.append(
    svgNode('text', { class: 'chart-panel-title', x: LEFT, y: 20 }, 'WBGT and personal limit'),
    svgNode('text', { class: 'chart-panel-title', x: LEFT, y: WORK_TOP - 12 },
      'Recommended work each hour'));

  hours.forEach((hour, index) => {
    const x = LEFT + index * cell;
    if (hour.stop) {
      svg.appendChild(svgNode('rect', {
        class: 'shift-risk', x: x + 2, y: TOP, width: Math.max(1, cell - 4), height: TEMP_HEIGHT,
      }));
    }
    const barHeight = (hour.minutes / 60) * WORK_HEIGHT;
    const barChanged = recalculationHour(recalculation, date, hour.hour, 'minutes');
    svg.appendChild(svgNode('rect', {
      class: [
        'work-bar', hour.minutes ? '' : 'no-work-bar',
        barChanged ? 'calculated-bar' : '',
      ].filter(Boolean).join(' '),
      x: x + Math.max(5, cell * 0.18), y: WORK_TOP + WORK_HEIGHT - barHeight,
      width: Math.max(8, cell * 0.64), height: Math.max(2, barHeight), rx: 2,
    }));
    svg.append(
      svgNode('text', {
        class: 'work-label', x: xAt(index), y: WORK_TOP + WORK_HEIGHT + 15,
        'text-anchor': 'middle',
      }, `${hour.minutes}`),
      svgNode('text', {
        class: 'tick', x: xAt(index), y: HEIGHT - 8, 'text-anchor': 'middle',
      }, `${pad(hour.hour)}:00`));
  });

  svg.append(
    svgNode('polyline', {
      class: 'heat-line', points: pointsFor(hours, 0, xAt, tempY, (hour) => hour.wbgt),
    }),
    svgNode('polyline', {
      class: 'limit-line', points: pointsFor(hours, 0, xAt, tempY, (hour) => hour.limit),
    }));

  hours.forEach((hour, index) => {
    const point = svgNode('circle', {
      class: index === bindingIndex ? 'heat-point binding-point' : 'heat-point',
      cx: xAt(index), cy: tempY(hour.wbgt), r: index === bindingIndex ? 5 : 3.5,
    });
    point.appendChild(svgNode('title', {},
      `${pad(hour.hour)}:00: ${hour.wbgt.toFixed(1)} °C WBGT, ${hour.minutes} work minutes`));
    svg.appendChild(point);
  });

  const legend = el('div', 'chart-legend');
  legend.append(
    chartKey('chart-key-heat', 'WBGT'),
    chartKey('chart-key-limit', 'Personal limit'),
    chartKey('chart-key-work', 'Work minutes'),
    chartKey('chart-key-stop', 'No heat work'));
  const wrap = el('div', recalculationField(recalculation, date, 'hours')
    ? 'shift-chart-wrap is-updated' : 'shift-chart-wrap');
  wrap.append(legend, svg);
  return wrap;
}

function workWindow(hours) {
  const planned = hours.filter((hour) => hour.minutes > 0);
  if (!planned.length) return 'No heat work planned';
  const first = planned[0];
  const last = planned[planned.length - 1];
  return `${pad(first.hour)}:00 to ${pad(last.hour + 1)}:00`;
}

function supervisorPlan(result, recalculation = null) {
  const current = result.current;
  const hours = current.hours;
  const hottest = hours.reduce((best, hour) => (!best || hour.wbgt > best.wbgt ? hour : best), null);
  const recovery = hours.reduce((total, hour) => total + (60 - hour.minutes), 0);
  const card = el('section', 'decision-card supervisor-card');
  card.appendChild(el('h3', 'decision-title', 'Supervisor plan'));

  const metrics = el('div', 'decision-metrics');
  const hoursChanged = recalculationField(recalculation, current.date, 'hours');
  [
    [workWindow(hours), 'planned work window', hoursChanged],
    [`${recovery} min`, 'recovery time', hoursChanged],
    [hottest ? `${hottest.wbgt.toFixed(1)} °C` : 'Not available',
      hottest ? `highest WBGT at ${pad(hottest.hour)}:00` : 'highest WBGT', false],
  ].forEach(([value, label, changed]) => {
    const metric = el('div', 'decision-metric');
    metric.append(calculatedValue(value, changed, 'num', 'strong'), el('span', null, label));
    metrics.appendChild(metric);
  });
  card.appendChild(metrics);

  const recommendation = recommendationFor(result);
  if (recommendation) {
    const explanation = el('div', 'decision-explanation');
    const binding = el('div', 'decision-explanation-row');
    binding.append(
      el('span', 'decision-explanation-label', 'Binding condition'),
      el('strong', null, recommendation.diagnosis));
    const readiness = el('div', 'decision-explanation-row');
    readiness.append(
      el('span', 'decision-explanation-label', 'Exposure history'),
      el('span', null, `${recommendation.readiness}% ready at shift start, `
        + `${recommendation.limit.toFixed(2)} °C personal limit.`));
    explanation.append(binding, readiness);
    card.appendChild(explanation);
  }

  const list = el('ul', 'action-list');
  [
    recommendation ? recommendation.action : 'Confirm the work plan before the shift.',
    'Keep drinking water and a shaded or cooled recovery area close to the work.',
    'Log actual minutes after the shift so the next plan reflects the completed work.',
  ].forEach((text) => list.appendChild(el('li', null, text)));
  card.appendChild(list);
  return card;
}

function seriesForSite(site, date) {
  const registry = window.SUNUP_WEATHER && window.SUNUP_WEATHER.series;
  const series = registry && site && site.seriesKey && registry[site.seriesKey];
  const hourly = series && series[date];
  return Array.isArray(hourly) && hourly.length === 24 ? hourly : null;
}

function interventionMetric(label, current, scenario, format) {
  const row = el('div', 'intervention-row');
  const currentText = format(current);
  const scenarioText = format(scenario);
  row.append(
    el('span', 'intervention-label', label),
    el('span', 'intervention-value num', currentText),
    calculatedValue(scenarioText, current !== scenario, 'intervention-value num'));
  return row;
}

function interventionSimulator(result) {
  const current = result.current;
  const worker = result.worker;
  const sites = store.sites().map((site) => ({
    site, hourly: seriesForSite(site, current.date),
  })).filter((entry) => entry.hourly);
  if (!result.currentHourly || !sites.length) return null;

  const suggestion = suggestIntervention({
    sites,
    currentSiteId: result.site.id,
    worker,
    adaptation: current.adaptationStart,
  });
  const initialSiteId = suggestion ? suggestion.siteId : result.site.id;
  const initialStart = suggestion ? suggestion.shiftStart : worker.shiftStart;
  const initialEnd = suggestion ? suggestion.shiftEnd : worker.shiftEnd;

  const card = el('section', 'decision-card intervention-card');
  const heading = el('div', 'intervention-heading');
  const headingCopy = el('div', 'intervention-heading-copy');
  headingCopy.append(
    el('h3', 'decision-title', 'Compare an intervention'),
    el('p', 'muted', suggestion
      ? 'A practical alternative is selected. Adjust any input to compare another plan.'
      : 'Adjust the site, shift, or hourly heat-work cap.'));
  const presetActions = el('div', 'intervention-actions');
  const suggestedButton = suggestion ? el('button', 'btn', 'Use suggested plan') : null;
  const assignedButton = el('button', 'btn', 'Use assigned plan');
  [suggestedButton, assignedButton].filter(Boolean).forEach((button) => {
    button.type = 'button';
    presetActions.appendChild(button);
  });
  heading.append(headingCopy, presetActions);
  card.appendChild(heading);

  const siteControl = select(initialSiteId, sites.map((entry) => ({
    value: entry.site.id, label: entry.site.name,
  })));
  const starts = Array.from({ length: result.currentHourly.length }, (_, hour) => ({
    value: hour, label: `${pad(hour)}:00`,
  }));
  const ends = Array.from({ length: result.currentHourly.length }, (_, index) => ({
    value: index + 1, label: `${pad(index + 1)}:00`,
  }));
  const startControl = select(initialStart, starts);
  const endControl = select(initialEnd, ends);
  const capControl = select('', [{ value: '', label: 'No extra hourly cap' }]
    .concat(workCapOptions().map((minutes) => ({
      value: minutes, label: `At most ${minutes} heat-work min/hour`,
    }))));
  const controls = el('div', 'intervention-controls');
  controls.append(
    field('Site', siteControl),
    field('Shift start', startControl),
    field('Shift end', endControl),
    field('Hourly heat-work cap', capControl));
  card.appendChild(controls);

  const output = el('div', 'intervention-output');
  output.setAttribute('aria-live', 'polite');
  card.appendChild(output);
  let timer = null;

  function showResult() {
    const selected = sites.find((entry) => entry.site.id === siteControl.value);
    const start = Number(startControl.value);
    const end = Number(endControl.value);
    if (!selected || end <= start) {
      output.replaceChildren(el('p', 'callout-text danger',
        'Shift end must be later than shift start.'));
      return;
    }
    const baseline = evaluateIntervention({
      hourly: result.currentHourly,
      worker,
      adaptation: current.adaptationStart,
    });
    const scenario = evaluateIntervention({
      hourly: selected.hourly,
      worker,
      adaptation: current.adaptationStart,
      shiftStart: start,
      shiftEnd: end,
      capMinutes: capControl.value === '' ? null : Number(capControl.value),
    });
    if (!baseline || !scenario) return;

    calculationOrder = 0;
    const summary = el('div', 'intervention-summary');
    const gain = scenario.plannedMinutes - baseline.plannedMinutes;
    const assignedPlan = selected.site.id === result.site.id
      && start === worker.shiftStart && end === worker.shiftEnd && capControl.value === '';
    summary.append(
      el('strong', null,
        assignedPlan ? 'Assigned plan'
          : (gain === 0 ? 'No gain in heat-work time'
            : (gain > 0 ? `+${gain} heat-work minutes`
              : `${Math.abs(gain)} fewer heat-work minutes`))),
      el('span', 'muted', `${selected.site.name}, ${pad(start)}:00 to ${pad(end)}:00`));

    const comparison = el('div', 'intervention-comparison');
    const header = el('div', 'intervention-row intervention-header');
    header.append(el('span', null, ''), el('span', null, 'Assigned'), el('span', null, 'Compared'));
    comparison.append(
      header,
      interventionMetric('Heat work', baseline.plannedMinutes, scenario.plannedMinutes,
        (value) => `${value} min`),
      interventionMetric('Recovery or non-heat work', baseline.recoveryMinutes, scenario.recoveryMinutes,
        (value) => `${value} min`),
      interventionMetric('Peak WBGT', baseline.peakWbgt, scenario.peakWbgt,
        (value) => `${value.toFixed(1)} °C`),
      interventionMetric('Readiness after', baseline.readinessAfter, scenario.readinessAfter,
        (value) => `${Math.round(value * 100)}%`));
    let explanation = 'The compared plan changes the timing or location without increasing heat-work time.';
    if (assignedPlan) {
      explanation = baseline.plannedMinutes === 0
        ? 'The assigned shift permits no heat work. Use a cooler site, an earlier shift, or non-heat duties.'
        : 'This is the assigned plan. Choose an alternative above to compare it.';
    } else if (scenario.plannedMinutes === 0) {
      explanation = 'This plan still permits no heat work. The remaining shift is for recovery or non-heat duties.';
    } else if (baseline.plannedMinutes === 0 && scenario.plannedMinutes > 0) {
      explanation = `The assigned shift permits no heat work. This plan restores ${scenario.plannedMinutes} minutes; `
        + 'the remaining time is recovery or non-heat work.';
    } else if (gain > 0) {
      explanation = `This plan restores ${gain} heat-work minutes without changing readiness at shift start.`;
    } else if (gain < 0) {
      explanation = 'The lower heat-work total creates additional recovery or non-heat time.';
    }
    output.replaceChildren(summary, comparison,
      el('p', 'intervention-explanation', explanation),
      el('p', 'intervention-footnote',
        `Both plans use ${current.date} and the same readiness at shift start.`));
    if (suggestedButton) {
      suggestedButton.disabled = selected.site.id === suggestion.siteId
        && start === suggestion.shiftStart && end === suggestion.shiftEnd
        && capControl.value === '';
    }
    assignedButton.disabled = assignedPlan;
  }

  function recalculate() {
    if (timer) window.clearTimeout(timer);
    const loader = el('span', 'calculation-loader intervention-loader');
    loader.setAttribute('aria-hidden', 'true');
    loader.append(el('span'), el('span'), el('span'));
    output.replaceChildren(el('div', 'intervention-pending', ''), loader);
    output.firstChild.textContent = 'Calculating the scenario';
    timer = window.setTimeout(showResult, 240);
  }
  [siteControl, startControl, endControl, capControl]
    .forEach((control) => control.addEventListener('change', recalculate));
  function applyPlan(siteId, start, end) {
    siteControl.value = siteId;
    startControl.value = String(start);
    endControl.value = String(end);
    capControl.value = '';
    recalculate();
  }
  if (suggestedButton) {
    suggestedButton.addEventListener('click', () => applyPlan(
      suggestion.siteId, suggestion.shiftStart, suggestion.shiftEnd));
  }
  assignedButton.addEventListener('click', () => applyPlan(
    result.site.id, worker.shiftStart, worker.shiftEnd));
  recalculate();
  return card;
}

const ARIZONA_OUTLINE = [
  [-114.82, 31.33], [-114.47, 32.49], [-114.48, 34.72], [-114.12, 35.0],
  [-114.13, 37.0], [-109.04, 37.0], [-109.04, 31.33],
];

function workerLocationCard(site, ctx) {
  const card = el('section', 'decision-card location-card');
  card.appendChild(el('h3', 'decision-title', 'Work location'));
  const point = sitePoint(site);
  const map = svgNode('svg', {
    viewBox: '0 0 320 174', class: 'worker-location-map', role: 'img',
    'aria-label': point ? `${site.name} location in Arizona` : 'Site location is not set',
  });
  map.appendChild(svgNode('rect', { class: 'locator-bg', x: 0, y: 0, width: 320, height: 174 }));

  const project = ([lng, lat]) => [
    24 + ((lng + 115.2) / (115.2 - 108.65)) * 272,
    154 - ((lat - 30.8) / (37.25 - 30.8)) * 134,
  ];
  const outline = ARIZONA_OUTLINE.map((pair, index) => {
    const [x, y] = project(pair);
    return `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  map.appendChild(svgNode('path', { class: 'locator-state', d: `${outline} Z` }));
  [0.33, 0.66].forEach((ratio) => {
    map.append(
      svgNode('line', {
        class: 'locator-grid', x1: 24, y1: 20 + ratio * 134, x2: 296, y2: 20 + ratio * 134,
      }),
      svgNode('line', {
        class: 'locator-grid', x1: 24 + ratio * 272, y1: 20, x2: 24 + ratio * 272, y2: 154,
      }));
  });

  if (point) {
    const [x, y] = project([point.lng ?? point.lon, point.lat]);
    map.append(
      svgNode('circle', { class: 'locator-halo', cx: x, cy: y, r: 10 }),
      svgNode('circle', { class: 'locator-pin', cx: x, cy: y, r: 5 }));
  } else {
    map.appendChild(svgNode('text', {
      class: 'locator-empty', x: 160, y: 90, 'text-anchor': 'middle',
    }, 'Location not set'));
  }
  card.appendChild(map);

  const footer = el('div', 'location-footer');
  const copy = el('div', 'location-copy');
  copy.append(
    el('strong', null, site ? site.name : 'No site'),
    el('span', 'muted', point
      ? `${point.lat.toFixed(3)}, ${(point.lng ?? point.lon).toFixed(3)}`
      : 'Add a location from the site editor'));
  const open = el('button', 'btn btn-link', 'Open site map');
  open.type = 'button';
  open.addEventListener('click', () => ctx.go('#/map'));
  footer.append(copy, open);
  card.appendChild(footer);
  return card;
}

function recentRecalculation(workerId) {
  try {
    const raw = sessionStorage.getItem('sunup:last-recalculation');
    if (!raw) return null;
    const value = JSON.parse(raw);
    sessionStorage.removeItem('sunup:last-recalculation');
    if (value.workerId === workerId && Date.now() - value.at < 10000) return value;
  } catch (_) {
    return null;
  }
  return null;
}

let calculationOrder = 0;

function recalculationField(recalculation, date, field) {
  const record = recalculation && recalculation.changes
    && recalculation.changes.records && recalculation.changes.records[date];
  return Boolean(record && record.fields && record.fields.includes(field));
}

function recalculationHour(recalculation, date, hour, field) {
  const record = recalculation && recalculation.changes
    && recalculation.changes.records && recalculation.changes.records[date];
  const changed = record && record.hours && record.hours[hour];
  return Boolean(changed && changed.includes(field));
}

function recalculationSummary(recalculation, field) {
  const summary = recalculation && recalculation.changes && recalculation.changes.summary;
  return Boolean(summary && summary.includes(field));
}

function recalculationHasChanges(recalculation) {
  if (!recalculation || !recalculation.changes) return false;
  if ((recalculation.changes.summary || []).length) return true;
  return Object.values(recalculation.changes.records || {})
    .some((record) => (record.fields || []).length > 0);
}

function calculatedValue(value, changed, className = null, tagName = 'span') {
  const node = el(tagName, className);
  if (!changed) {
    node.textContent = value;
    return node;
  }

  node.classList.add('calculated-value');
  node.setAttribute('data-calculation-order', String(calculationOrder % 6));
  calculationOrder += 1;
  const loader = el('span', 'calculation-loader');
  loader.setAttribute('aria-hidden', 'true');
  loader.append(el('span'), el('span'), el('span'));
  node.append(loader, el('span', 'calculated-result', value));
  return node;
}

/* --- Shared cells --------------------------------------------------------------- */

function workerNameCell(result) {
  const wrap = el('div', 'cellstack');
  const line = el('div', 'cellline');
  line.appendChild(el('span', 'nm', result.worker.name));
  if (result.worker.workClassOverride) line.appendChild(tag('override', 'warn'));
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
  const prior = result.observed.filter((record) => record.date < result.current.date);
  return prior.length ? prior[prior.length - 1] : null;
}

function todayMetric(value, label) {
  const wrap = el('div', 'fc-metric');
  wrap.append(el('div', 'fc-value num', value), el('div', 'fc-label', label));
  return wrap;
}

function todayAttention(row) {
  const wrap = el('div', 'attention-cell');
  let action = 'No immediate action';
  if (row.result.unavailable) {
    action = `Add weather for ${row.site ? row.site.name : 'this site'}`;
  } else if (row.recommendation && row.recommendation.earlier) {
    action = `${pad(row.recommendation.earlier.shiftStart)}:00 start, `
      + `+${row.recommendation.gain} min`;
  } else if (row.result.current.status === 'stop') {
    action = 'Move heat work';
  } else if (row.missingCloseout) {
    action = `Close out ${row.previous.date.slice(5)}`;
  } else if (row.result.current.status === 'restricted') {
    action = `Use the ${row.result.current.prescribedMinutes} min plan`;
  } else if (row.result.current.status === 'reduced') {
    action = 'Protect recovery';
  }
  wrap.appendChild(el('span', 'attention-action', action));
  return wrap;
}

function todayChange(row) {
  if (row.result.unavailable) return '';
  if (!row.previous) {
    const first = el('span', 'change-indicator', 'First day');
    first.setAttribute('data-direction', 'new');
    return first;
  }
  const change = row.result.current.prescribedMinutes - row.previous.prescribedMinutes;
  if (!change) {
    const same = el('span', 'change-indicator', 'No change');
    same.setAttribute('data-direction', 'same');
    same.title = `No change compared with ${row.previous.date}`;
    return same;
  }
  const direction = change > 0 ? 'up' : 'down';
  const label = `${Math.abs(change)} min`;
  const spoken = `${change > 0 ? 'Up' : 'Down'} ${label}`;
  const value = el('span', 'change-indicator num');
  value.setAttribute('data-direction', direction);
  value.setAttribute('aria-label', `${spoken} compared with ${row.previous.date}`);
  value.title = `${spoken} compared with ${row.previous.date}`;
  value.append(icon(change > 0 ? 'arrowUp' : 'arrowDown', 12), el('span', null, label));
  return value;
}

function exceptionState(event) {
  if (!event.active) return el('span', 'review-state muted', 'Resolved, reviewed');
  if (event.acknowledgedAt) return el('span', 'review-state', 'Reviewed');
  return el('span', 'review-state review-needed', 'Needs review');
}

function exceptionAction(ctx, event) {
  if (!event.active) return '';
  const reviewed = Boolean(event.acknowledgedAt);
  const action = el('button', 'btn review-action', reviewed ? 'Reopen' : 'Acknowledge');
  action.type = 'button';
  action.addEventListener('click', (clickEvent) => {
    clickEvent.stopPropagation();
    if (reviewed) store.reopenException(event.id);
    else store.acknowledgeException(event);
    toast(reviewed ? 'Exception reopened' : 'Exception acknowledged');
    ctx.refresh();
  });
  return action;
}

function exceptionLedgerSection(ctx, events) {
  const wrap = el('section', 'sect exception-ledger');
  const heading = el('div', 'exception-heading');
  const copy = el('div', 'exception-heading-copy');
  const open = events.filter((event) => event.active && !event.acknowledgedAt).length;
  copy.append(
    el('h2', 'sect-h', 'Exceptions and review'),
    el('p', 'section-description',
      'Current plan, closeout, and work-over-plan events with supervisor acknowledgement.'));
  heading.append(copy, el('span', 'num exception-count', `${open} need review`));
  wrap.appendChild(heading);
  wrap.appendChild(detailsList({
    columns: [
      { label: 'Event', width: '2fr', render: (event) => {
        const node = el('span', 'nm', event.title);
        node.title = event.detail;
        return node;
      } },
      { label: 'Site / crew', width: '1.2fr', render: (event) => event.scope },
      { label: 'Date', width: '96px', render: (event) => event.date },
      { label: 'State', width: '132px', render: exceptionState },
      { label: 'Review', width: '124px', render: (event) => exceptionAction(ctx, event) },
    ],
    rows: events,
    sort: null,
    onSort: () => {},
    selection: new Set(),
    onSelectionChange: () => {},
    rowKey: (event) => event.id,
    onInvoke: (event) => { if (event.href) ctx.go(event.href); },
    selectable: false,
    empty: 'No plan, closeout, or work-over-plan exceptions need review.',
  }));
  return wrap;
}

export function todayView(ctx) {
  const root = el('div', 'view');
  const date = new Date(`${compute.today()}T00:00:00Z`).toLocaleDateString([], {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  });
  root.appendChild(pageHeader('Today', `${date}. Each row shows its active weather date.`));

  const rows = store.workers()
    .filter((worker) => worker.active !== false)
    .map((worker) => {
      const result = compute.forWorker(worker.id);
      const crew = store.crew(worker.crewId);
      const site = result && result.site ? result.site : (crew ? store.site(crew.siteId) : null);
      const previous = previousObserved(result);
      const missingCloseout = Boolean(previous && previous.assumed);
      const recommendation = recommendationFor(result);
      const priority = result.unavailable ? 0
        : (result.current.status === 'stop' ? 1
          : (missingCloseout ? 2
            : (result.current.status === 'restricted' ? 3
              : (result.current.status === 'reduced' ? 4 : 5))));
      return {
        worker, result, crew, site, previous, recommendation, missingCloseout, priority,
      };
    })
    .sort((a, b) => a.priority - b.priority || a.worker.name.localeCompare(b.worker.name));

  const usable = rows.filter((row) => !row.result.unavailable);
  const stopped = usable.filter((row) => row.result.current.status === 'stop').length;
  const restricted = usable.filter(
    (row) => row.result.current.status === 'restricted').length;
  const missing = rows.filter((row) => row.missingCloseout).length;
  const unavailable = rows.length - usable.length;
  const minutes = usable.reduce((sum, row) => sum + row.result.current.prescribedMinutes, 0);
  const ledger = exceptionLedger();
  const needsReview = ledger.filter(
    (event) => event.active && !event.acknowledgedAt).length;

  const summary = el('div', 'fc-summary');
  summary.append(
    todayMetric(String(rows.length), 'active workers'),
    todayMetric(`${(minutes / 60).toFixed(1)} h`, 'prescribed for active date'),
    todayMetric(String(stopped + unavailable), 'urgent actions'),
    todayMetric(String(restricted), 'restricted plans'),
    todayMetric(String(missing), 'need closeout'),
    todayMetric(String(unavailable), 'weather unavailable'),
    todayMetric(String(needsReview), 'exceptions to review'));
  root.appendChild(summary);

  root.appendChild(detailsList({
    columns: [
      { label: 'Worker', width: '1.2fr', render: (row) => workerNameCell(row.result) },
      { label: 'Site / crew', width: '1.2fr',
        render: (row) => `${row.site ? row.site.name : 'No site'} / ${row.crew ? row.crew.name : 'No crew'}` },
      { label: 'Date', width: '88px',
        render: (row) => row.result.unavailable
          ? compute.currentDateForSite(row.site) : row.result.current.date },
      { label: 'Shift', width: '94px', numeric: true,
        render: (row) => `${pad(row.worker.shiftStart)}:00-${pad(row.worker.shiftEnd)}:00` },
      { label: 'Plan (min)', width: '80px', numeric: true,
        render: (row) => row.result.unavailable
          ? '' : String(row.result.current.prescribedMinutes) },
      { label: 'Calendar', width: '76px', numeric: true,
        render: (row) => row.result.unavailable
          ? '' : String(row.result.current.calendarMinutes) },
      { label: 'Change', width: '92px', numeric: true, render: todayChange },
      { label: 'Plan level', width: '174px',
        render: (row) => row.result.unavailable
          ? el('span', 'muted', 'Unavailable')
          : chip(row.result.current.status, STATUS_TEXT[row.result.current.status]) },
      { label: 'Next action', width: '2fr', render: todayAttention },
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
  root.appendChild(exceptionLedgerSection(ctx, ledger));
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
          if (r.site.weatherSource === 'none') wrap.appendChild(tag('no weather', 'danger'));
          return wrap;
        } },
      { label: 'Crews', width: '70px', numeric: true, sortKey: 'crews',
        render: (r) => String(r.crews.length) },
      { label: 'Workers', width: '80px', numeric: true, sortKey: 'workers',
        render: (r) => String(r.workers) },
      { label: 'Model (min)', width: '104px', numeric: true, sortKey: 'model',
        render: (r) => r.site.weatherSource === 'none' ? '' : `${r.modelMinutes}` },
      { label: 'Calendar (min)', width: '112px', numeric: true,
        render: (r) => r.site.weatherSource === 'none' ? '' : `${r.calendarMinutes}` },
      { label: 'Action', width: '92px', numeric: true,
        render: (r) => r.actionRequired
          ? el('span', 'num danger', String(r.actionRequired)) : '' },
      { label: 'Status', width: '174px',
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
  const crewCount = store.crews(siteId).length;
  root.appendChild(pageHeader(site.name,
    `${crewCount} ${crewCount === 1 ? 'crew' : 'crews'} at this site`));
  const freshness = weatherFreshness(site);
  if (freshness) root.appendChild(freshness);

  if (site.weatherSource === 'none') {
    root.appendChild(noWeatherBanner(ctx, site));
  } else if (site.weatherStatus === 'error' || site.weatherStatus === 'partial') {
    root.appendChild(weatherFailureBanner(ctx, site));
  } else if (site.weatherStatus === 'backfill') {
    root.appendChild(backfillBanner(site));
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
        render: (r) => r.unavailable || !r.workers ? '' : String(r.modelMinutes) },
      { label: 'Calendar', width: '90px', numeric: true,
        render: (r) => r.unavailable || !r.workers ? '' : String(r.calendarMinutes) },
      { label: 'Action', width: '80px', numeric: true,
        render: (r) => r.actionRequired
          ? el('span', 'num danger', String(r.actionRequired)) : '' },
      { label: 'Flags', width: '220px',
        render: (r) => {
          const wrap = el('span', 'loggedcell');
          if (r.overexposed) wrap.appendChild(tag(`${r.overexposed} overexposed`, 'danger'));
          if (r.unprescribed) wrap.appendChild(tag(`${r.unprescribed} unprescribed`, 'danger'));
          return wrap;
        } },
      { label: 'Status', width: '174px',
        render: (r) => !r.workers
          ? el('span', 'muted', 'No workers')
          : (r.unavailable
            ? el('span', 'muted', 'Unavailable')
            : chip(r.worstStatus, STATUS_TEXT[r.worstStatus])) },
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

function formatHour(hour) {
  return `${String(hour).padStart(2, '0')}:00`;
}

function optimizerMetric(label, value, detail) {
  const metric = el('div', 'crew-plan-metric');
  metric.append(
    el('span', 'crew-plan-label', label),
    el('strong', 'num', value),
    el('span', 'muted', detail));
  return metric;
}

function crewOptimizerCard(ctx, crew, rows) {
  const optimization = optimizeCrewShift(rows);
  const card = el('section', 'decision-card crew-optimizer');
  const heading = el('div', 'crew-plan-heading');
  const copy = el('div', 'crew-plan-heading-copy');
  copy.append(
    el('h3', 'decision-title', 'Crew shift optimizer'),
    el('p', 'muted', 'Tests one shared start while preserving each worker\'s shift length.'));
  heading.appendChild(copy);
  card.appendChild(heading);

  if (!optimization.available) {
    const message = optimization.reason === 'no-workers'
      ? 'Add an active worker before comparing crew schedules.'
      : (optimization.reason === 'weather-unavailable'
        ? `Weather is unavailable for ${optimization.unavailableCount} active `
          + `${optimization.unavailableCount === 1 ? 'worker' : 'workers'}.`
        : 'One or more assigned shifts cannot be evaluated.');
    card.appendChild(el('p', 'crew-plan-empty muted', message));
    return card;
  }

  const proposed = optimization.recommendation;
  if (!proposed) {
    card.appendChild(el('p', 'crew-plan-empty',
      'The assigned shifts are already the strongest no-loss plan in the available window.'));
    return card;
  }

  const durationSet = new Set(proposed.workers.map(
    (entry) => entry.shiftEnd - entry.shiftStart));
  const shiftValue = durationSet.size === 1
    ? `${formatHour(proposed.shiftStart)}-${formatHour(proposed.workers[0].shiftEnd)}`
    : `${formatHour(proposed.shiftStart)} shared start`;
  const action = el('button', 'btn btn-primary', 'Apply recommended shift');
  action.type = 'button';
  action.addEventListener('click', () => {
    confirmDialog({
      title: 'Apply the crew shift?',
      message: `Move ${proposed.workers.length} active workers to a `
        + `${formatHour(proposed.shiftStart)} shared start. Each worker keeps their `
        + 'assigned shift length.',
      confirmLabel: 'Apply shift',
      onConfirm: () => {
        proposed.workers.forEach((entry) => {
          store.updateWorker(entry.worker.id, {
            shiftStart: entry.shiftStart,
            shiftEnd: entry.shiftEnd,
          });
        });
        compute.invalidate();
        toast(`Updated ${crew.name} to a ${formatHour(proposed.shiftStart)} start`);
        ctx.refresh();
      },
    });
  });
  heading.appendChild(action);

  const metrics = el('div', 'crew-plan-metrics');
  metrics.append(
    optimizerMetric('Recommended shift', shiftValue, 'shared crew start'),
    optimizerMetric('Heat work recovered', `+${proposed.gain} min`,
      `${proposed.baselineMinutes} to ${proposed.plannedMinutes} min`),
    optimizerMetric('Workers helped', `${proposed.helped}/${optimization.workers}`,
      'no worker loses time'),
    optimizerMetric('Readiness floor', `${Math.round(proposed.readinessFloor * 100)}%`,
      `${Math.round(proposed.baselineReadinessFloor * 100)}% assigned`));
  card.appendChild(metrics);

  const helped = proposed.workers.filter((entry) => entry.gain > 0)
    .map((entry) => `${entry.worker.name} +${entry.gain} min`);
  card.appendChild(el('p', 'crew-plan-explanation',
    `Improves ${helped.join(', ')}. No active worker receives fewer prescribed minutes.`));
  return card;
}

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
  const crewWorkers = store.workers(crewId).length;
  root.appendChild(pageHeader(crew.name,
    `${site.name}. ${crewWorkers} ${crewWorkers === 1 ? 'worker' : 'workers'}`));
  const freshness = weatherFreshness(site);
  if (freshness) root.appendChild(freshness);

  if (site.weatherSource === 'none') root.appendChild(noWeatherBanner(ctx, site));
  else if (site.weatherStatus === 'error' || site.weatherStatus === 'partial') {
    root.appendChild(weatherFailureBanner(ctx, site));
  } else if (site.weatherStatus === 'backfill') root.appendChild(backfillBanner(site));

  const rows = store.workers(crewId).map((w) => compute.forWorker(w.id)).filter(Boolean);

  root.appendChild(crewOptimizerCard(ctx, crew, rows));

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
      { label: 'Status', width: '174px', sortKey: 'status',
        render: (r) => r.unavailable ? el('span', 'muted', 'Unavailable')
          : chip(r.current.status, STATUS_TEXT[r.current.status]) },
      { label: 'Plan (min)', width: '88px', numeric: true, sortKey: 'minutes',
        render: (r) => r.unavailable ? '' : String(r.current.prescribedMinutes) },
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

/* --- Crew field briefing ------------------------------------------------------- */

function briefingStatus(result) {
  if (result.unavailable) return 'Weather unavailable';
  if (result.current.status === 'stop') return 'Move heat work outside this shift';
  if (result.current.status === 'restricted') {
    return `Restricted to ${result.current.prescribedMinutes} heat-work minutes`;
  }
  if (result.current.status === 'reduced') return 'Protect every recovery period';
  return 'Normal controls and planned closeout';
}

function briefingCloseout(result) {
  if (result.unavailable) return 'Cannot calculate';
  return result.current.assumed ? 'Closeout pending' : 'Actual minutes recorded';
}

function briefingHour(hour) {
  const cell = el('span', 'briefing-hour');
  cell.append(
    el('strong', 'num', formatHour(hour.hour)),
    el('span', 'num', `${hour.minutes} work`),
    el('span', 'num muted', `${60 - hour.minutes} recovery`));
  return cell;
}

function reviewBox(label) {
  const wrap = el('span', 'briefing-review');
  wrap.append(el('span', 'briefing-check'), el('span', null, label));
  return wrap;
}

function briefingWorker(result) {
  const item = el('section', 'briefing-worker');
  const head = el('div', 'briefing-worker-head');
  const identity = el('div', 'briefing-identity');
  identity.append(
    el('strong', null, result.worker.name),
    el('span', 'muted', result.worker.trade));
  head.appendChild(identity);
  if (!result.unavailable) {
    head.appendChild(chip(result.current.status, STATUS_TEXT[result.current.status]));
  }
  item.appendChild(head);

  if (result.unavailable) {
    item.appendChild(el('p', 'briefing-unavailable muted',
      'No weather history is available for this worker\'s assigned site.'));
  } else {
    const summary = el('div', 'briefing-worker-summary');
    summary.append(
      el('span', 'num', `${formatHour(result.worker.shiftStart)}-${formatHour(result.worker.shiftEnd)}`),
      el('span', 'num', `${result.current.prescribedMinutes} min heat work`),
      el('span', 'num', `${result.shiftHours * 60 - result.current.prescribedMinutes} min recovery`),
      el('span', null, briefingStatus(result)));
    item.appendChild(summary);
    const hourly = el('div', 'briefing-hours');
    result.current.hours.forEach((hour) => hourly.appendChild(briefingHour(hour)));
    item.appendChild(hourly);
  }

  const review = el('div', 'briefing-worker-review');
  review.append(
    reviewBox('Plan reviewed'),
    el('span', 'briefing-closeout', briefingCloseout(result)));
  item.appendChild(review);
  return item;
}

export function crewBriefingView(ctx, siteId, crewId) {
  const crew = store.crew(crewId);
  const site = store.site(siteId);
  if (!crew || !site) return missing(ctx, 'That crew no longer exists.');

  const root = el('div', 'view view-briefing');
  root.appendChild(breadcrumb([
    { label: 'Sites', href: '#/sites' },
    { label: site.name, href: `#/site/${siteId}` },
    { label: crew.name, href: `#/site/${siteId}/crew/${crewId}` },
    { label: 'Daily briefing' },
  ]));
  const date = compute.currentDateForCrew(crewId);
  root.appendChild(pageHeader('Daily crew briefing',
    `${site.name} / ${crew.name} / ${date}`));

  const facts = el('div', 'briefing-facts');
  facts.append(
    optimizerMetric('Site', site.name, site.weatherSource === 'live' ? 'live weather' : 'cached weather'),
    optimizerMetric('Crew', crew.name,
      `${store.workers(crewId).filter((worker) => worker.active !== false).length} active workers`),
    optimizerMetric('Plan date', date, 'active weather date'),
    optimizerMetric('Supervisor', '', 'review before heat work begins'));
  root.appendChild(facts);

  const controls = el('section', 'briefing-controls');
  controls.appendChild(el('h2', 'sect-h', 'Field controls'));
  const controlGrid = el('div', 'briefing-control-grid');
  [
    'Stage potable water for the full shift',
    'Confirm a shaded or cooled recovery area',
    'Assign buddy checks before heat work begins',
    'Review the emergency response and contact path',
  ].forEach((text) => controlGrid.appendChild(reviewBox(text)));
  controls.appendChild(controlGrid);
  root.appendChild(controls);

  const workerList = el('div', 'briefing-workers');
  store.workers(crewId)
    .filter((worker) => worker.active !== false)
    .map((worker) => compute.forWorker(worker.id))
    .filter(Boolean)
    .forEach((result) => workerList.appendChild(briefingWorker(result)));
  if (!workerList.children.length) {
    workerList.appendChild(el('p', 'briefing-unavailable muted',
      'This crew has no active workers.'));
  }
  root.appendChild(workerList);

  const signoff = el('section', 'briefing-signoff');
  signoff.append(
    reviewBox('All workers briefed'),
    el('span', 'briefing-signature', 'Supervisor initials'),
    el('span', 'briefing-signature', 'Time'));
  root.appendChild(signoff);
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
    { label: site ? site.name : 'Missing site', href: `#/site/${siteId}` },
    { label: crew ? crew.name : 'Missing crew', href: `#/site/${siteId}/crew/${crewId}` },
    { label: worker.name },
  ]));
  root.appendChild(pageHeader(worker.name,
    `${crew ? crew.name : 'Worker'} crew at ${site ? site.name : 'this site'}`));

  if (result.unavailable) {
    root.appendChild(noWeatherBanner(ctx, site));
    return root;
  }

  const current = result.current;
  const recalculation = recentRecalculation(workerId);
  calculationOrder = 0;
  if (recalculation) root.classList.add('is-recalculated');

  const head = el('div', 'wk-head');
  const metric = el('div', 'wk-metric');
  metric.append(calculatedValue(
    String(current.prescribedMinutes),
    recalculationField(recalculation, current.date, 'prescribedMinutes'),
    'wk-minutes num', 'div'),
                el('div', 'wk-unit', `minutes prescribed for ${current.date}`));
  const facts = el('div', 'wk-facts');
  facts.append(
    fact('Trade', worker.trade),
    fact('Intensity', result.workClass
      + (worker.workClassOverride ? ' (override)' : '')),
    fact('Shift', `${pad(worker.shiftStart)}:00 to ${pad(worker.shiftEnd)}:00`),
    fact('Clothing', worker.clothing.replace(/_/g, ' ')),
    fact('Ramp', worker.rampType === 'returning' ? 'returning worker' : 'new worker'),
    fact('Day on job', String(current.dayOnJob)),
    fact('Calendar', `${current.calendarMinutes} min`));
  head.append(metric, facts, chip(current.status, STATUS_TEXT[current.status]));
  root.appendChild(head);

  if (recalculation) {
    const hasChanges = recalculationHasChanges(recalculation);
    const feedback = el('div', 'calculation-feedback');
    feedback.setAttribute('role', 'status');
    const check = el('span', 'calculation-check');
    check.appendChild(icon('check'));
    feedback.append(
      check,
      el('strong', null, 'Plan recalculated'),
      el('span', null, hasChanges
        ? `Changed values after logging ${recalculation.date} are highlighted below.`
        : `The log for ${recalculation.date} was saved. No calculated values changed.`));
    root.appendChild(feedback);
  }

  if (result.assumedRun > 0) {
    const missingTitle = result.assumedRun === 1
      ? '1 recent day has no logged actual.'
      : `${result.assumedRun} recent days have no logged actual.`;
    root.appendChild(banner('assumed',
      missingTitle, 'Add actual minutes for these days.'));
  }
  if (result.historyLimited) {
    root.appendChild(banner('assumed',
      'Readiness history begins with the available weather window.',
      'The calendar day reflects the hire date. Readiness starts conservatively at 0% because earlier heat exposure is unavailable.'));
  }
  if (result.cumulativeOverexposure > 0) {
    root.appendChild(banner('danger',
      `Overexposure ${result.cumulativeOverexposure.toFixed(2)} °C·h`,
      'Review the flagged days in the log.'));
  }

  const briefing = el('div', 'worker-briefing');
  briefing.append(supervisorPlan(result, recalculation), workerLocationCard(site, ctx));
  root.appendChild(briefing);

  const simulator = interventionSimulator(result);
  if (simulator) root.appendChild(simulator);

  const historyLabel = result.projected.length
    ? `${result.observed.length} observed days and ${result.projected.length} forecast days`
    : `${result.observed.length} observed days`;
  const history = section('Work capacity history', historyChart(result.records, recalculation));
  history.classList.add('worker-history');
  history.insertBefore(el('p', 'section-description', historyLabel), history.children[1]);
  root.appendChild(history);

  /* Day log ------------------------------------------------------------------ */
  const logRows = result.observed.slice().reverse();
  root.appendChild(section('Day log', detailsList({
    columns: [
      { label: 'Date', width: '1.3fr', render: (r) => r.date },
      { label: 'Job day', width: '80px', numeric: true, render: (r) => String(r.dayOnJob) },
      { label: 'Prescribed (min)', width: '130px', numeric: true,
        render: (r) => calculatedValue(String(r.prescribedMinutes),
          recalculationField(recalculation, r.date, 'prescribedMinutes')) },
      { label: 'Actual (min)', width: '120px', numeric: true,
        render: (r) => {
          if (r.assumed) {
            const node = calculatedValue('not logged',
              recalculationField(recalculation, r.date, 'actualMinutes'), 'muted');
            node.title = 'No actual minutes recorded.';
            return node;
          }
          if (r.absent) return tag('Absent', 'neutral');
          const node = calculatedValue(String(r.actualMinutes),
            recalculationField(recalculation, r.date, 'actualMinutes'), 'num');
          if (r.actualMinutes > r.prescribedMinutes) node.classList.add('danger');
          return node;
        } },
      { label: 'Flags', width: '1.3fr',
        render: (r) => {
          const wrap = el('span', 'loggedcell');
          if (r.unprescribedWork) {
            const t = tag('unprescribed', 'danger');
            t.title = 'Work was logged on a day with no prescribed minutes.';
            wrap.appendChild(t);
          }
          if (r.overexposure > 0) {
            const exposure = tag('', 'danger');
            exposure.appendChild(calculatedValue(`+${r.overexposure.toFixed(1)} °C·h`,
              recalculationField(recalculation, r.date, 'overexposure')));
            wrap.appendChild(exposure);
          }
          return wrap;
        } },
      { label: 'Peak WBGT', width: '110px', numeric: true,
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
    ['Hour', 'WBGT', 'Limit', 'Difference', 'Work (min)'].forEach((label, i) => {
      const th = el('th', i ? 'num' : null, label);
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    const tbody = el('tbody');
    for (const hour of current.hours) {
      const tr = el('tr');
      tr.setAttribute('data-stop', String(hour.stop));
      tr.setAttribute('data-binding', String(hour === binding));
      const difference = hour.overLimit > 0
        ? `${hour.overLimit.toFixed(1)} above`
        : (hour.overLimit < 0 ? `${Math.abs(hour.overLimit).toFixed(1)} below` : 'At limit');
      [[`${pad(hour.hour)}:00`, '', false], [hour.wbgt.toFixed(1), 'num', false],
       [hour.limit.toFixed(1), 'num',
         recalculationHour(recalculation, current.date, hour.hour, 'limit')],
       [difference, 'num',
         recalculationHour(recalculation, current.date, hour.hour, 'overLimit')],
       [String(hour.minutes), 'num',
         recalculationHour(recalculation, current.date, hour.hour, 'minutes')]]
        .forEach(([text, cls, changed]) => {
          const cell = el('td', cls || null);
          cell.appendChild(calculatedValue(text, changed));
          tr.appendChild(cell);
      });
      tbody.appendChild(tr);
    }
    table.append(thead, tbody);
    const why = binding ? el('p', 'binding-note',
      `Most restrictive hour ${pad(binding.hour)}:00. `
      + (binding.overLimit > 0
        ? `WBGT is ${binding.overLimit.toFixed(1)} °C above this worker's limit.`
        : 'WBGT remains within this worker\'s limit.')) : null;
    const exact = el('details', 'hourly-values');
    exact.append(el('summary', null, 'View hourly values'), table);
    const wrap = el('div', 'shift-plan');
    if (why) wrap.appendChild(why);
    wrap.append(hourlyChart(current.hours, recalculation, current.date), exact);
    const shiftSection = section(`Shift plan for ${current.date}`, wrap);
    shiftSection.classList.add('shift-section');
    root.appendChild(shiftSection);
  }

  /* State --------------------------------------------------------------------- */
  const state = el('dl', 'readiness-grid');
  const weatherLabel = site.seeded
    ? `Cached through ${current.date}`
    : `${site.weatherSource}${site.seriesKey ? `, ${site.seriesKey}` : ''}`;
  state.append(
    definition('Readiness at shift start', calculatedValue(
      `${Math.round(current.adaptationStart * 100)}%`,
      recalculationField(recalculation, current.date, 'adaptationStart')), true),
    definition(current.assumed ? 'After planned work' : 'After logged work',
      calculatedValue(`${Math.round(current.adaptationEnd * 100)}%`,
        recalculationField(recalculation, current.date, 'adaptationEnd')), true),
    definition('Personal limit', calculatedValue(`${current.limit.toFixed(2)} °C WBGT`,
      recalculationField(recalculation, current.date, 'limit')), true),
    definition('Overexposure', calculatedValue(
      `${result.cumulativeOverexposure.toFixed(2)} °C·h`,
      recalculationSummary(recalculation, 'cumulativeOverexposure')), true),
    definition('Weather', weatherLabel));
  const readiness = section(`Heat readiness for ${current.date}`, state);
  readiness.classList.add('readiness-section');
  root.appendChild(readiness);

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

function definition(label, value, numeric = false) {
  const item = el('div', 'readiness-item');
  const detail = el('dd', numeric ? 'num' : null);
  if (value instanceof Node) detail.appendChild(value);
  else detail.textContent = value;
  item.append(el('dt', null, label), detail);
  return item;
}

function weatherFreshness(site) {
  if (site.weatherSource !== 'live' || !site.weatherUpdatedAt) return null;
  const progress = site.weatherProgress || { completed: 0, total: 14 };
  const value = new Date(site.weatherUpdatedAt);
  const updated = Number.isNaN(value.getTime())
    ? site.weatherUpdatedAt
    : value.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  return el('p', 'muted',
    `Live weather: ${progress.completed} of ${progress.total} days ready`
    + `${progress.pending ? `, ${progress.pending} processing` : ''}. Updated ${updated}.`);
}

function noWeatherBanner(ctx, site) {
  if (site.weatherStatus === 'loading' || site.weatherStatus === 'backfill') {
    const progress = site.weatherProgress || { completed: 0, total: 14 };
    return banner('info', 'Retrieving live weather',
      `${progress.completed} of ${progress.total} days ready`
      + `${progress.pending ? `, ${progress.pending} processing` : ''}. `
      + 'The first completed day becomes usable immediately.');
  }
  if (site.weatherStatus === 'error' || site.weatherStatus === 'partial') {
    return weatherFailureBanner(ctx, site);
  }
  const node = banner('danger', 'No weather history, prescriptions unavailable',
    'This site has no hourly WBGT series, so nothing can be prescribed for the '
    + 'crews under it.');
  const actions = el('div', 'callout-actions');

  actions.appendChild(liveFetchButton(ctx, site, 'Fetch live'));
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
    site.weatherError || (partial
      ? 'Some days are available. Retry to complete this site’s history.'
      : 'No live days are available. Check the API key, then retry.'));
  const actions = el('div', 'callout-actions');
  actions.appendChild(liveFetchButton(ctx, site, 'Retry live fetch'));
  node.appendChild(actions);
  return node;
}

function backfillBanner(site) {
  const progress = site.weatherProgress || { completed: 5, total: 14 };
  return banner('info', 'Live weather is still backfilling',
    `${progress.completed} of ${progress.total} days ready`
    + `${progress.pending ? `, ${progress.pending} processing` : ''}. `
    + 'Prescriptions update as history arrives.');
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

export { STATUS_TEXT, banner, section, fact };
