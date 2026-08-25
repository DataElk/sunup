/* ============================================================================
   Shell wiring: rail routing, drawer open/close, density, status bar.

   A new view is a rail entry plus a content component. Nothing else moves.
   ========================================================================== */

import { renderRoster, crewSummary } from './roster.js';
import { renderDetail } from './detail.js';
import { renderCompliance, recordText } from './compliance.js';
import { renderMap } from './map.js';
import { renderOverlay } from './overlay.js';

const data = window.ROSTER_DATA;
const mapData = window.MAP_DATA;
const baseData = window.BASEMAP;
const overlayData = window.OVERLAY_DATA;

const app = document.getElementById('app');
const content = document.getElementById('content');
const drawerBody = document.getElementById('drawer-body');
const drawerTitle = document.getElementById('drawer-title');
const barTitle = document.getElementById('bar-title');
const barSub = document.getElementById('bar-sub');
const commands = document.getElementById('commands');

let view = 'roster';
let selected = null;
let drawer = null;   // 'detail' | 'compliance' | null

/* --- Drawer --------------------------------------------------------------- */

function openDrawer(kind) {
  drawer = kind;
  app.setAttribute('data-drawer', 'open');
  if (kind === 'compliance') {
    drawerTitle.textContent = 'Compliance record';
    renderCompliance(drawerBody, data);
  } else {
    drawerTitle.textContent = selected ? selected.name : 'Worker';
    renderDetail(drawerBody, selected, data);
  }
}

function closeDrawer() {
  drawer = null;
  app.removeAttribute('data-drawer');
  drawerBody.replaceChildren();
}

document.getElementById('drawer-close').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && drawer) closeDrawer();
});

/* --- Views ---------------------------------------------------------------- */

function button(id, label, onClick) {
  const btn = document.createElement('button');
  btn.className = 'btn';
  btn.id = id;
  btn.textContent = label;
  btn.addEventListener('click', onClick);
  return btn;
}

function renderRosterView() {
  const summary = crewSummary(data);
  barTitle.textContent = 'Crew roster';
  barSub.textContent =
    `${summary.crew} on crew · ${summary.model} worker-min today · `
    + `calendar ${summary.calendar} · ${summary.over} under-protected by the calendar`;

  commands.replaceChildren(
    button('cmd-compliance', 'Compliance record', () => openDrawer('compliance')));

  selected = renderRoster(content, data, (worker) => {
    selected = worker;
    openDrawer('detail');
  });
}

function renderMapView() {
  barTitle.textContent = 'Exposure map';
  barSub.textContent =
    `${mapData.sourceCells.toLocaleString()} cells · threshold `
    + `${mapData.thresholdC} degC · ${data.today}`;
  commands.replaceChildren();
  closeDrawer();
  renderMap(content, mapData, data, baseData);
}

function renderOverlayView() {
  barTitle.textContent = 'Forecast vs actual';
  barSub.textContent =
    `projected ${overlayData.asOf} · ${overlayData.horizon} days forward · `
    + `backtest, not a live forecast`;
  commands.replaceChildren();
  closeDrawer();
  renderOverlay(content, overlayData);
}

const VIEWS = {
  roster: renderRosterView,
  map: renderMapView,
  overlay: renderOverlayView,
};

/* The view lives in the hash so a view is linkable and a reload keeps you
   where you were. Nothing else is routed: the drawer is a transient thing you
   open, not a place you can be. */
function go(next) {
  if (!VIEWS[next]) next = 'roster';
  view = next;
  if (location.hash.slice(1) !== next) location.hash = next;
  for (const btn of document.querySelectorAll('.rail-btn[data-view]')) {
    btn.setAttribute('aria-selected', String(btn.dataset.view === next));
  }
  VIEWS[next]();
}

window.addEventListener('hashchange', () => {
  const next = location.hash.slice(1);
  if (VIEWS[next] && next !== view) go(next);
});

for (const btn of document.querySelectorAll('.rail-btn[data-view]')) {
  btn.addEventListener('click', () => go(btn.dataset.view));
}

/* --- Density -------------------------------------------------------------- */

const densityBtn = document.getElementById('cmd-density');
densityBtn.addEventListener('click', () => {
  const root = document.documentElement;
  const touch = root.getAttribute('data-density') === 'touch';
  if (touch) root.removeAttribute('data-density');
  else root.setAttribute('data-density', 'touch');
  densityBtn.setAttribute('aria-pressed', String(!touch));
  /* Both views are density-dependent now: the roster switches between a table
     and cards, and the map redraws its canvas at the new type scale. */
  closeDrawer();
  VIEWS[view]();
});

/* --- Copy ----------------------------------------------------------------- */

document.getElementById('cmd-copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(recordText(data));
    flash('Compliance record copied');
  } catch {
    openDrawer('compliance');
    flash('Clipboard blocked — record opened');
  }
});

let flashTimer = null;
function flash(message) {
  const el = document.getElementById('sb-message');
  el.textContent = message;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { el.textContent = ''; }, 2400);
}

/* --- Status bar ----------------------------------------------------------- */

document.getElementById('sb-source').textContent =
  'FortyGuard tiles + Open-Meteo hourly';
document.getElementById('sb-date').textContent = data.today;
document.getElementById('sb-cache').textContent = `cached · ${data.generated}`;
/* NAME the assumption, do not count it. "1 assumed input(s)" told a reader
   there was an assumption but not which one, so it got read as whichever input
   looked least trustworthy -- wind, usually, even though wind is measured
   (Open-Meteo 10 m, log-profile-adjusted to 2 m). The single assumption is the
   natural wet bulb substitution, constants.py 5b. */
const assumed = data.provenance.assumed;
const modelCell = document.getElementById('sb-model');
if (!assumed.length) {
  modelCell.textContent = 'no assumed inputs';
} else {
  const first = assumed[0].replace(/\s*\(constants\.py[^)]*\)/, '');
  modelCell.textContent = assumed.length === 1
    ? `assumes ${first}`
    : `assumes ${first} +${assumed.length - 1} more`;
  modelCell.title = assumed.join('\n');
}

go(location.hash.slice(1) || 'roster');
