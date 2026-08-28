/* ============================================================================
   The shell: rail, nav tree, command bar, content, status bar.

   Routing is hash-based and three levels deep, so every screen survives a hard
   refresh and can be linked:

     #/today  #/sites
     #/site/:siteId
     #/site/:siteId/crew/:crewId
     #/site/:siteId/crew/:crewId/briefing
     #/site/:siteId/crew/:crewId/worker/:workerId
     #/map  #/performance  #/settings
     #/forecast (legacy alias for model performance)

   Commands live in ONE bar at the top and enable on selection rather than
   appearing and disappearing, which is what keeps an Office toolbar stable
   under the cursor.
   ========================================================================== */

import * as store from './store.js';
import * as compute from './compute.js';
import * as forms from './forms.js';
import * as views from './views.js';
import { hasConfiguredKey } from './liveweather.js';
import { resumeSiteBackfills } from './siteweather.js';
import { mapView } from './mapview.js';
import { performanceView, settingsView } from './extraviews.js';
import { el, icon, commandBar, navTree, toast, dismissPanel } from './ui.js';

const rail = document.getElementById('rail');
const treeHost = document.getElementById('tree');
const treeTitle = document.getElementById('tree-title');
const barHost = document.getElementById('commandbar');
const content = document.getElementById('content');
const statusHost = document.getElementById('statusbar');

const RAIL = [
  { id: 'today', icon: 'log', label: 'Today', href: '#/today' },
  { id: 'roster', icon: 'grid', label: 'Sites and crews', href: '#/sites' },
  { id: 'map', icon: 'map', label: 'Site map', href: '#/map' },
  { id: 'performance', icon: 'chart', label: 'Model performance', href: '#/performance' },
  { id: 'settings', icon: 'gear', label: 'Settings', href: '#/settings' },
];

let route = { view: 'today' };
let selection = new Set();
let sort = { key: 'name', dir: 'asc' };
let expanded = new Set();

/* --- Routing ------------------------------------------------------------------- */

function parse() {
  const hash = location.hash.replace(/^#\/?/, '');
  const parts = hash.split('/').filter(Boolean);
  if (!parts.length) return { view: 'today' };
  if (parts[0] === 'today') return { view: 'today' };
  if (parts[0] === 'map') return { view: 'map' };
  if (parts[0] === 'performance' || parts[0] === 'forecast') {
    return { view: 'performance' };
  }
  if (parts[0] === 'settings') return { view: 'settings' };
  if (parts[0] === 'sites') return { view: 'sites' };
  if (parts[0] === 'site' && parts[1]) {
    if (parts[2] === 'crew' && parts[3]) {
      if (parts[4] === 'briefing') {
        return { view: 'briefing', siteId: parts[1], crewId: parts[3] };
      }
      if (parts[4] === 'worker' && parts[5]) {
        return { view: 'worker', siteId: parts[1], crewId: parts[3], workerId: parts[5] };
      }
      return { view: 'crew', siteId: parts[1], crewId: parts[3] };
    }
    return { view: 'site', siteId: parts[1] };
  }
  return { view: 'sites' };
}

function go(href) {
  if (location.hash === href) render();
  else location.hash = href;
}

const ctx = {
  go,
  refresh: () => render(),
  get selection() { return selection; },
  get sort() { return sort; },
  onSort: (key) => {
    sort = (sort && sort.key === key)
      ? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: 'asc' };
    render();
  },
  onSelectionChange: (next) => { selection = next; render(); },
};

/* --- Commands ------------------------------------------------------------------- */

function selectedSites() {
  return [...selection].map((id) => store.site(id)).filter(Boolean);
}
function selectedCrews() {
  return [...selection].map((id) => store.crew(id)).filter(Boolean);
}
function selectedWorkers() {
  return [...selection].map((id) => store.worker(id)).filter(Boolean);
}

function commandsFor(current) {
  const one = selection.size === 1;
  const any = selection.size > 0;

  if (current.view === 'sites') {
    return [
      { icon: 'add', label: 'New site', run: () => forms.editSite(null, after) },
      { icon: 'edit', label: 'Edit', enabled: () => one,
        run: () => forms.editSite([...selection][0], after) },
      { divider: true },
      { icon: 'remove', label: 'Remove', danger: true, enabled: () => any,
        run: () => forms.confirmRemove('site', selectedSites(), after) },
      { icon: 'crew', label: 'New crew here', overflow: true, enabled: () => one,
        run: () => forms.editCrew(null, [...selection][0], after) },
    ];
  }
  if (current.view === 'site') {
    return [
      { icon: 'add', label: 'New crew',
        run: () => forms.editCrew(null, current.siteId, after) },
      { icon: 'edit', label: 'Edit crew', enabled: () => one,
        run: () => forms.editCrew([...selection][0], current.siteId, after) },
      { divider: true },
      { icon: 'remove', label: 'Remove', danger: true, enabled: () => any,
        run: () => forms.confirmRemove('crew', selectedCrews(), after) },
      { icon: 'log', label: 'Log selected crew', overflow: true, enabled: () => one,
        run: () => forms.editCrewDayLog([...selection][0],
          compute.currentDateForCrew([...selection][0]), after) },
      { icon: 'site', label: 'Edit site', overflow: true,
        run: () => forms.editSite(current.siteId, after) },
    ];
  }
  if (current.view === 'crew') {
    return [
      { icon: 'add', label: 'New worker',
        run: () => forms.editWorker(null, current.crewId, after) },
      { icon: 'edit', label: 'Edit', enabled: () => one,
        run: () => forms.editWorker([...selection][0], current.crewId, after) },
      { icon: 'log', label: 'Log crew',
        run: () => forms.editCrewDayLog(current.crewId,
          compute.currentDateForCrew(current.crewId), after) },
      { icon: 'print', label: 'Crew briefing',
        run: () => go(`#/site/${current.siteId}/crew/${current.crewId}/briefing`) },
      { divider: true },
      { icon: 'remove', label: 'Remove', danger: true, enabled: () => any,
        run: () => forms.confirmRemove('worker', selectedWorkers(), after) },
      { icon: 'copy', label: 'Copy compliance record', overflow: true,
        run: () => copyRecord(current.crewId) },
      { icon: 'log', label: 'Log selected worker', overflow: true, enabled: () => one,
        run: () => forms.editDayLog([...selection][0],
          compute.currentDateForWorker([...selection][0]), after) },
      { icon: 'crew', label: 'Edit crew', overflow: true,
        run: () => forms.editCrew(current.crewId, current.siteId, after) },
    ];
  }
  if (current.view === 'worker') {
    return [
      { icon: 'log', label: 'Log today',
        run: () => forms.editDayLog(current.workerId,
          compute.currentDateForWorker(current.workerId), after) },
      { icon: 'edit', label: 'Edit worker',
        run: () => forms.editWorker(current.workerId, current.crewId, after) },
      { divider: true },
      { icon: 'remove', label: 'Remove', danger: true,
        run: () => forms.confirmRemove('worker',
          [store.worker(current.workerId)],
          () => go(`#/site/${current.siteId}/crew/${current.crewId}`)) },
    ];
  }
  if (current.view === 'briefing') {
    return [
      { icon: 'print', label: 'Print briefing', run: () => window.print() },
      { icon: 'crew', label: 'Back to crew',
        run: () => go(`#/site/${current.siteId}/crew/${current.crewId}`) },
    ];
  }
  if (current.view === 'today' || current.view === 'settings' || current.view === 'map'
      || current.view === 'performance') {
    return [];
  }
  return [];
}

function after() { compute.invalidate(); render(); }

function copyRecord(crewId) {
  const summary = compute.forCrew(crewId);
  const crew = store.crew(crewId);
  const site = store.site(crew.siteId);
  const lines = [];
  lines.push('SUNUP - HEAT EXPOSURE COMPLIANCE RECORD');
  lines.push(`Date: ${compute.currentDateForCrew(crewId)}`);
  lines.push(`Site: ${site.name}   Crew: ${crew.name}`);
  lines.push(`Weather source: ${site.weatherSource}`);
  lines.push('');
  lines.push('PRESCRIPTIONS');
  lines.push('  worker           trade       start  day  model  cal.  logged');
  for (const row of summary.rows) {
    if (row.unavailable) {
      lines.push(`  ${row.worker.name.padEnd(16)} ${row.worker.trade.padEnd(11)} `
        + 'NO WEATHER HISTORY');
      continue;
    }
    const c = row.current;
    lines.push(`  ${row.worker.name.padEnd(16)} ${row.worker.trade.padEnd(11)} `
      + `${String(row.worker.shiftStart).padStart(2, '0')}:00 `
      + `${String(c.dayOnJob).padStart(4)} `
      + `${String(c.prescribedMinutes).padStart(6)} `
      + `${String(c.calendarMinutes).padStart(5)}  `
      + (c.assumed ? 'not logged' : String(c.actualMinutes))
      + (row.cumulativeOverexposure > 0
        ? `  OVEREXPOSURE ${row.cumulativeOverexposure.toFixed(2)} °C·h` : ''));
  }
  const text = lines.join('\n');
  navigator.clipboard.writeText(text)
    .then(() => toast('Compliance record copied'))
    .catch(() => toast('Clipboard blocked by the browser'));
}

/* --- Chrome --------------------------------------------------------------------- */

function railFor(current) {
  const key = ['today', 'map', 'performance', 'settings'].includes(current.view)
    ? current.view : 'roster';
  rail.replaceChildren();
  for (const item of RAIL) {
    const button = el('a', 'rail-btn');
    button.href = item.href;
    button.title = item.label;
    button.setAttribute('aria-label', item.label);
    if (item.id === key) button.setAttribute('aria-current', 'page');
    button.append(icon(item.icon, 18), el('span', 'rail-label', item.label));
    rail.appendChild(button);
  }
}

function treeFor(current) {
  const showing = ['sites', 'site', 'crew', 'briefing', 'worker'].includes(current.view);
  document.getElementById('shell').setAttribute('data-tree', String(showing));
  if (!showing) { treeHost.replaceChildren(); return; }

  treeTitle.textContent = 'Sites and crews';
  const nodes = store.sites().map((site) => {
    const summary = compute.forSite(site.id);
    return {
      id: site.id,
      label: site.name,
      badge: site.weatherSource === 'none' ? null : summary.worstStatus,
      href: `#/site/${site.id}`,
      children: store.crews(site.id).map((crew) => {
        const cs = compute.forCrew(crew.id);
        return {
          id: crew.id,
          label: crew.name,
          count: cs.workers,
          badge: cs.unavailable ? null : cs.worstStatus,
          href: `#/site/${site.id}/crew/${crew.id}`,
        };
      }),
    };
  });

  const selected = current.crewId || current.siteId || null;

  treeHost.replaceChildren(navTree({
    nodes,
    selectedId: selected,
    expanded,
    onSelect: (node) => go(node.href),
    onToggle: (id) => {
      if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
      render();
    },
  }));
}

function statusFor(current) {
  const weather = window.SUNUP_WEATHER;
  const state = store.getState();
  statusHost.replaceChildren();
  const add = (label, value, title) => {
    const wrap = el('span', 'sb');
    wrap.append(el('span', 'sb-l', label), el('span', 'sb-v', value));
    if (title) wrap.title = title;
    statusHost.appendChild(wrap);
  };
  add('Date', compute.today());
  add('Source', hasConfiguredKey() ? 'Live weather' : 'Cached weather');
  add('Store', `${state.workers.length} workers, browser storage`);
}

/* --- Render ---------------------------------------------------------------------- */

function render() {
  const current = parse();
  if (current.view !== route.view
      || current.siteId !== route.siteId
      || current.crewId !== route.crewId) {
    selection = new Set();
  }
  route = current;

  railFor(current);
  treeFor(current);

  const commands = commandsFor(current);
  barHost.replaceChildren();
  if (commands.length) barHost.appendChild(commandBar(commands, ctx));
  barHost.style.display = commands.length ? '' : 'none';

  let view;
  switch (current.view) {
    case 'today': view = views.todayView(ctx); break;
    case 'map': view = mapView(ctx); break;
    case 'performance': view = performanceView(ctx); break;
    case 'settings': view = settingsView(ctx); break;
    case 'site': view = views.siteView(ctx, current.siteId); break;
    case 'crew': view = views.crewView(ctx, current.siteId, current.crewId); break;
    case 'briefing':
      view = views.crewBriefingView(ctx, current.siteId, current.crewId);
      break;
    case 'worker':
      view = views.workerView(ctx, current.siteId, current.crewId, current.workerId);
      break;
    default: view = views.sitesView(ctx);
  }
  content.replaceChildren(view);
  statusFor(current);
}

/* --- Boot ------------------------------------------------------------------------ */

window.addEventListener('hashchange', () => { dismissPanel(); render(); });

(async function boot() {
  await store.initStore();
  store.subscribe(() => {
    compute.invalidate();
    if (!document.querySelector('.panel')) render();
  });

  for (const site of store.sites()) expanded.add(site.id);
  resumeSiteBackfills();

  if (!location.hash) location.hash = '#/today';
  render();
})();
