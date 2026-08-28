/* Operational exceptions derived from the current store and decision results. */

import * as compute from './compute.js';
import * as store from './store.js';

function workerScope(worker, result) {
  const crew = store.crew(worker.crewId);
  const site = result && result.site ? result.site : (crew ? store.site(crew.siteId) : null);
  return { crew, site };
}

function workerEvent({ id, type, date, title, detail, severity, worker, crew, site }) {
  return {
    id,
    type,
    date,
    title,
    detail,
    severity,
    workerId: worker.id,
    crewId: crew ? crew.id : null,
    siteId: site ? site.id : null,
    scope: [site && site.name, crew && crew.name].filter(Boolean).join(' / '),
    href: crew && site
      ? `#/site/${site.id}/crew/${crew.id}/worker/${worker.id}` : null,
  };
}

function previousObserved(result) {
  const prior = result.observed.filter((record) => record.date < result.current.date);
  return prior.length ? prior[prior.length - 1] : null;
}

function workerExceptions(worker) {
  const result = compute.forWorker(worker.id);
  if (!result) return [];
  const { crew, site } = workerScope(worker, result);
  const events = [];

  if (result.unavailable) {
    events.push(workerEvent({
      id: `weather:${worker.id}:${compute.currentDateForWorker(worker.id)}`,
      type: 'weather-unavailable',
      date: compute.currentDateForWorker(worker.id),
      title: `${worker.name} has no usable weather`,
      detail: 'Add or recover site weather before assigning heat work.',
      severity: 'urgent', worker, crew, site,
    }));
    return events;
  }

  const current = result.current;
  if (current.status === 'stop') {
    events.push(workerEvent({
      id: `plan-stop:${worker.id}:${current.date}`,
      type: 'plan-stop', date: current.date,
      title: `${worker.name} has no prescribed heat-work minutes`,
      detail: 'Move heat work outside the assigned shift or use a non-heat task.',
      severity: 'urgent', worker, crew, site,
    }));
  }

  const previous = previousObserved(result);
  if (previous && previous.assumed) {
    events.push(workerEvent({
      id: `closeout:${worker.id}:${previous.date}`,
      type: 'missing-closeout', date: previous.date,
      title: `${worker.name} is missing a shift closeout`,
      detail: `Record actual heat-work minutes for ${previous.date}.`,
      severity: 'review', worker, crew, site,
    }));
  }

  result.observed.slice(-2)
    .filter((record) => !record.assumed
      && record.actualMinutes > record.prescribedMinutes)
    .forEach((record) => {
      const unprescribed = record.prescribedMinutes === 0;
      events.push(workerEvent({
        id: `over-plan:${worker.id}:${record.date}`,
        type: unprescribed ? 'unprescribed-work' : 'over-plan',
        date: record.date,
        title: unprescribed
          ? `${worker.name} worked on a no-work day`
          : `${worker.name} exceeded the prescribed minutes`,
        detail: `${record.actualMinutes} actual minutes against `
          + `${record.prescribedMinutes} prescribed minutes.`,
        severity: unprescribed ? 'urgent' : 'review', worker, crew, site,
      }));
    });
  return events;
}

function groupOperationalEvents(events) {
  const grouped = new Map();
  const direct = [];
  events.forEach((event) => {
    if (!['missing-closeout', 'weather-unavailable'].includes(event.type)) {
      direct.push(event);
      return;
    }
    const owner = event.type === 'missing-closeout' ? event.crewId : event.siteId;
    const key = `${event.type}:${owner}:${event.date}`;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(event);
  });

  grouped.forEach((members, groupId) => {
    const first = members[0];
    const names = members.map((event) => event.title.split(' is missing')[0]);
    const memberWorkerIds = members.map((event) => event.workerId).filter(Boolean).sort();
    const id = `${groupId}:${memberWorkerIds.join(',')}`;
    if (first.type === 'missing-closeout') {
      const crew = first.crewId ? store.crew(first.crewId) : null;
      direct.push({
        ...first,
        id,
        workerId: null,
        memberWorkerIds,
        href: crew && first.siteId
          ? `#/site/${first.siteId}/crew/${crew.id}` : null,
        title: `${crew ? crew.name : 'Crew'} has ${members.length} missing `
          + `${members.length === 1 ? 'closeout' : 'closeouts'}`,
        detail: `Record actual heat-work minutes for ${names.join(', ')}.`,
      });
    } else {
      const site = first.siteId ? store.site(first.siteId) : null;
      direct.push({
        ...first,
        id,
        workerId: null,
        memberWorkerIds,
        crewId: null,
        href: site ? `#/site/${site.id}` : null,
        scope: site ? site.name : first.scope,
        title: `${site ? site.name : 'Site'} has no usable weather`,
        detail: `${members.length} active ${members.length === 1 ? 'worker is' : 'workers are'} `
          + 'blocked until site weather is available.',
      });
    }
  });
  return direct;
}

function eventOrder(left, right) {
  const priority = { urgent: 0, review: 1, resolved: 2 };
  const severity = priority[left.severity] - priority[right.severity];
  if (severity) return severity;
  const date = String(right.date || '').localeCompare(String(left.date || ''));
  return date || left.title.localeCompare(right.title);
}

export function currentExceptions() {
  const events = store.workers()
    .filter((worker) => worker.active !== false)
    .flatMap((worker) => workerExceptions(worker));
  return groupOperationalEvents(events).sort(eventOrder);
}

export function exceptionLedger() {
  const current = currentExceptions();
  const currentIds = new Set(current.map((event) => event.id));
  const acknowledgements = store.exceptionAcknowledgements();
  const active = current.map((event) => ({
    ...event,
    active: true,
    acknowledgedAt: acknowledgements[event.id]
      ? acknowledgements[event.id].acknowledgedAt : null,
  }));
  const history = Object.values(acknowledgements)
    .filter((event) => !currentIds.has(event.id))
    .map((event) => ({ ...event, active: false, severity: 'resolved' }));
  return active.concat(history).sort(eventOrder);
}
