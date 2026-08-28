/* Counterfactual work plans built from the existing prescription engine. */

import {
  CONSTANTS, advanceAdaptation, allocateActual, dailyStimulus,
  prescribeHours, statusFor,
} from './engine.js';

function mostRestrictive(hours) {
  return hours.reduce((best, hour) => {
    if (!best || hour.minutes < best.minutes) return hour;
    return best;
  }, null);
}

export function workCapOptions() {
  return [...new Set(CONSTANTS.workRestLadder.map((entry) => entry[1]))]
    .filter((minutes) => minutes > CONSTANTS.workRestStop && minutes < 60)
    .sort((a, b) => b - a);
}

export function evaluateIntervention({
  hourly, worker, adaptation, shiftStart = worker.shiftStart,
  shiftEnd = worker.shiftEnd, capMinutes = null,
}) {
  if (!Array.isArray(hourly) || hourly.length !== 24) return null;
  if (shiftEnd <= shiftStart) return null;
  const candidate = { ...worker, shiftStart, shiftEnd };
  let hours = prescribeHours(hourly, candidate, adaptation);
  if (capMinutes !== null && capMinutes !== undefined && capMinutes !== '') {
    const cap = Number(capMinutes);
    hours = hours.map((hour) => ({ ...hour, minutes: Math.min(hour.minutes, cap) }));
  }
  const plannedMinutes = hours.reduce((sum, hour) => sum + hour.minutes, 0);
  const shiftMinutes = (shiftEnd - shiftStart) * 60;
  const allocation = allocateActual(hours, plannedMinutes, candidate);
  const stimulus = dailyStimulus(hours, candidate, allocation);
  const peakWbgt = hours.length ? Math.max(...hours.map((hour) => hour.wbgt)) : null;
  return {
    shiftStart,
    shiftEnd,
    capMinutes: capMinutes === '' ? null : capMinutes,
    hours,
    plannedMinutes,
    recoveryMinutes: Math.max(0, shiftMinutes - plannedMinutes),
    peakWbgt,
    readinessAfter: advanceAdaptation(adaptation, stimulus.value),
    binding: mostRestrictive(hours),
    status: statusFor(plannedMinutes, candidate),
  };
}

function siteIdFor(entry) {
  return entry && (entry.siteId || (entry.site && entry.site.id));
}

export function suggestIntervention({ sites, currentSiteId, worker, adaptation }) {
  if (!Array.isArray(sites) || !worker) return null;
  const currentSite = sites.find((entry) => siteIdFor(entry) === currentSiteId);
  if (!currentSite) return null;

  const baseline = evaluateIntervention({
    hourly: currentSite.hourly, worker, adaptation,
  });
  if (!baseline) return null;

  const duration = worker.shiftEnd - worker.shiftStart;
  const firstStart = Math.min(worker.shiftStart, CONSTANTS.defaultShiftStartHour);
  let best = {
    siteId: currentSiteId,
    shiftStart: worker.shiftStart,
    shiftEnd: worker.shiftEnd,
    result: baseline,
    siteChange: 0,
    shiftChange: 0,
  };

  sites.forEach((entry) => {
    const siteId = siteIdFor(entry);
    if (!siteId || !Array.isArray(entry.hourly)) return;
    for (let start = firstStart; start <= worker.shiftStart; start += 1) {
      const end = start + duration;
      if (end > entry.hourly.length) continue;
      const result = evaluateIntervention({
        hourly: entry.hourly,
        worker,
        adaptation,
        shiftStart: start,
        shiftEnd: end,
      });
      if (!result) continue;
      const siteChange = siteId === currentSiteId ? 0 : 1;
      const shiftChange = Math.abs(start - worker.shiftStart);
      const improvesWork = result.plannedMinutes > best.result.plannedMinutes;
      const sameWork = result.plannedMinutes === best.result.plannedMinutes;
      const lessDisruption = siteChange < best.siteChange
        || (siteChange === best.siteChange && shiftChange < best.shiftChange);
      if (improvesWork || (sameWork && lessDisruption)) {
        best = { siteId, shiftStart: start, shiftEnd: end, result, siteChange, shiftChange };
      }
    }
  });

  const gain = best.result.plannedMinutes - baseline.plannedMinutes;
  return gain > 0 ? { ...best, baseline, gain } : null;
}

export function bestEarlierShift(result) {
  if (!result || result.unavailable || !result.currentHourly) return null;
  const worker = result.worker;
  const current = evaluateIntervention({
    hourly: result.currentHourly, worker, adaptation: result.current.adaptationStart,
  });
  if (!current) return null;
  const duration = worker.shiftEnd - worker.shiftStart;
  let best = current;
  for (let start = CONSTANTS.defaultShiftStartHour;
       start < worker.shiftStart && start + duration <= result.currentHourly.length;
       start += 1) {
    const candidate = evaluateIntervention({
      hourly: result.currentHourly,
      worker,
      adaptation: result.current.adaptationStart,
      shiftStart: start,
      shiftEnd: start + duration,
    });
    if (candidate && candidate.plannedMinutes > best.plannedMinutes) best = candidate;
  }
  return best.plannedMinutes > current.plannedMinutes ? best : null;
}

export function recommendationFor(result) {
  if (!result || result.unavailable) return null;
  const current = result.current;
  const binding = mostRestrictive(current.hours);
  const earlier = bestEarlierShift(result);
  let diagnosis = 'The planned shift remains within this worker\'s current limit.';
  if (binding && binding.overLimit > 0) {
    diagnosis = `At ${String(binding.hour).padStart(2, '0')}:00, WBGT is `
      + `${binding.overLimit.toFixed(1)} °C above this worker's limit.`;
  }

  let action;
  if (earlier) {
    const gain = earlier.plannedMinutes - current.prescribedMinutes;
    action = `Start at ${String(earlier.shiftStart).padStart(2, '0')}:00 to recover `
      + `${gain} workable minutes under the same conditions.`;
  } else if (current.status === 'stop') {
    action = 'Move heat work outside this shift or assign a cooler task before work begins.';
  } else if (current.status === 'restricted') {
    action = 'Keep heat work inside the prescribed minutes and use the coolest hours first.';
  } else if (current.status === 'reduced') {
    action = 'Protect the scheduled recovery periods and reassess if conditions change.';
  } else {
    action = 'Keep the normal heat controls active and close out actual minutes after work.';
  }

  return {
    diagnosis,
    action,
    earlier,
    gain: earlier ? earlier.plannedMinutes - current.prescribedMinutes : 0,
    readiness: Math.round(current.adaptationStart * 100),
    limit: current.limit,
  };
}
