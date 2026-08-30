/* Background weather advances without replacing the displayed plan. */

import { el } from './ui.js';

const RUNNING = new Set(['loading', 'backfill']);
const FAILED = new Set(['error', 'partial']);

export function weatherProgressState(sites, dirty = false) {
  const tasks = sites.filter((site) => site.weatherStatus);
  const running = tasks.filter((site) => RUNNING.has(site.weatherStatus));
  const failed = tasks.filter((site) => FAILED.has(site.weatherStatus));
  const active = tasks.filter((site) => RUNNING.has(site.weatherStatus)
    || FAILED.has(site.weatherStatus));
  const shown = tasks;
  const sum = (key) => shown.reduce((total, site) => (
    total + Number((site.weatherProgress || {})[key] || 0)), 0);
  const total = sum('total');
  const completed = Math.min(total, sum('completed'));
  const pending = shown.reduce((count, site) => (
    count + Object.keys(site.liveActivities || {}).length), 0);
  const first = running[0] || failed[0] || shown[0];
  const phase = first && first.weatherPhase;
  let title = 'Weather history ready';
  let detail = dirty ? 'New weather is ready. Update the plan when you are ready to review it.'
    : 'Your displayed plan uses the available weather history.';
  if (running.length) {
    title = completed ? 'Building schedule history' : 'Preparing the first schedule';
    const step = phase === 'regional' ? 'Getting hourly weather and forecasts.'
      : (phase === 'site-check' ? 'Checking the site and processing the first day.'
        : (phase === 'backfill' ? 'Adding earlier weather days.' : 'Processing recent weather days.'));
    detail = `${step} This can take several minutes. You can keep working.`;
  } else if (failed.length) {
    title = completed ? 'Weather history paused' : 'Weather could not be loaded';
    detail = `${first.weatherError || 'The weather service did not finish.'} `
      + (completed ? 'Completed days are saved.' : 'Retry when the service is available.');
  }
  const started = shown.map((site) => Date.parse(site.weatherStartedAt)).filter(Number.isFinite);
  const finished = shown.map((site) => Date.parse(site.weatherFinishedAt)).filter(Number.isFinite);
  return {
    visible: active.length > 0 || dirty,
    title, detail, completed, total, pending,
    scope: shown.length === 1 ? shown[0].name : `${shown.length} sites`,
    running: running.length > 0,
    canApply: dirty && tasks.some((site) => Number((site.weatherProgress || {}).completed) > 0),
    retryIds: failed.map((site) => site.id),
    startedAt: started.length ? Math.min(...started) : null,
    finishedAt: !running.length && finished.length ? Math.max(...finished) : null,
  };
}

export function createWeatherProgress(host, { onApply, onRetry }) {
  const card = el('section', 'weather-task');
  card.setAttribute('aria-label', 'Schedule preparation progress');
  const copy = el('div', 'weather-task-copy');
  const heading = el('div', 'weather-task-heading');
  const title = el('strong');
  title.setAttribute('role', 'status');
  const scope = el('span', 'weather-task-scope');
  const detail = el('p', 'weather-task-detail');
  const progress = el('progress', 'weather-task-progress');
  progress.setAttribute('aria-label', 'Weather history days ready');
  const meta = el('div', 'weather-task-meta');
  const count = el('span', 'num');
  const elapsed = el('span', 'num');
  heading.append(title, scope);
  meta.append(count, elapsed);
  copy.append(heading, detail, progress, meta);
  const actions = el('div', 'weather-task-actions');
  const apply = el('button', 'btn', 'Update plan');
  const retry = el('button', 'btn', 'Retry missing days');
  apply.type = retry.type = 'button';
  const note = el('span', 'weather-task-note');
  actions.append(apply, retry, note);
  card.append(copy, actions);
  host.replaceChildren(card);
  let current = null;
  let retained = false;
  let clock = null;
  const setText = (node, text) => { if (node.textContent !== text) node.textContent = text; };
  apply.addEventListener('click', () => onApply());
  retry.addEventListener('click', () => {
    if (current) onRetry(current.retryIds);
  });

  function tick() {
    if (!current || !current.startedAt) { setText(elapsed, ''); return; }
    const seconds = Math.max(0, Math.floor(
      ((current.finishedAt || Date.now()) - current.startedAt) / 1000));
    setText(elapsed, `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s elapsed`);
  }

  return {
    update(sites, { dirty = false, reset = false } = {}) {
      if (reset) retained = false;
      current = weatherProgressState(sites, dirty);
      retained = retained || current.visible;
      host.hidden = !retained || sites.length === 0;
      setText(title, current.title);
      setText(scope, current.scope);
      setText(detail, current.detail);
      detail.title = current.detail;
      progress.max = current.total || 1;
      progress.value = current.completed;
      progress.setAttribute('aria-valuetext', `${current.completed} of ${current.total} weather days ready`);
      setText(count, `${current.completed} of ${current.total} days ready`
        + (current.pending ? ` / ${current.pending} ${current.running ? 'processing' : 'pending'}` : ''));
      apply.disabled = !current.canApply;
      apply.classList.toggle('btn-primary', current.canApply);
      setText(apply, current.running ? 'Show available plan' : 'Update plan');
      retry.hidden = current.retryIds.length === 0;
      setText(note, dirty ? 'Displayed plan has not changed.'
        : (current.running ? 'Your view stays in place.'
          : (current.retryIds.length ? 'Retry to finish loading.' : 'Plan is up to date.')));
      if (clock) { window.clearInterval(clock); clock = null; }
      if (current.running && !host.hidden) clock = window.setInterval(tick, 1000);
      tick();
    },
  };
}
