/* ============================================================================
   Wiring. Ribbon commands, panel routing, density toggle, status bar.
   ========================================================================== */

import { renderRoster, crewSummary } from './roster.js';
import { renderDetail } from './detail.js';
import { renderCompliance, recordText } from './compliance.js';

const data = window.ROSTER_DATA;

const rosterBody = document.getElementById('roster-body');
const sideBody = document.getElementById('side-body');
const sideTitle = document.getElementById('side-title');
const sideSub = document.getElementById('side-sub');
const summaryEl = document.getElementById('crew-summary');

let selected = null;
let sideView = 'detail';

function paintSide() {
  if (sideView === 'compliance') {
    sideTitle.textContent = 'Compliance record';
    sideSub.textContent = data.today;
    renderCompliance(sideBody, data);
  } else {
    sideTitle.textContent = selected ? selected.name : 'Worker';
    sideSub.textContent = selected
      ? `${selected.trade} · ${selected.shift}` : 'none selected';
    renderDetail(sideBody, selected, data);
  }
}

function select(worker) {
  selected = worker;
  if (sideView !== 'compliance') paintSide();
}

function paintSummary() {
  const s = crewSummary(data);
  summaryEl.textContent =
    `${s.crew} on crew · ${s.model} worker-min today · `
    + `calendar ${s.calendar} (${s.delta > 0 ? '+' : ''}${s.delta}) · `
    + `${s.stopped} stopped`;
}

/* --- Ribbon commands ------------------------------------------------------ */

document.getElementById('cmd-detail').addEventListener('click', () => {
  sideView = 'detail';
  setPressed();
  paintSide();
});

document.getElementById('cmd-compliance').addEventListener('click', () => {
  sideView = 'compliance';
  setPressed();
  paintSide();
});

document.getElementById('cmd-print').addEventListener('click', () => {
  sideView = 'compliance';
  setPressed();
  paintSide();
  window.print();
});

document.getElementById('cmd-copy').addEventListener('click', async () => {
  const text = recordText(data);
  try {
    await navigator.clipboard.writeText(text);
    flash('Record copied');
  } catch {
    /* Clipboard is unavailable from file:// in some browsers; show it instead
       so the supervisor can still get the text out. */
    sideView = 'compliance';
    setPressed();
    paintSide();
    flash('Clipboard blocked — record shown');
  }
});

const densityBtn = document.getElementById('cmd-density');
densityBtn.addEventListener('click', () => {
  const root = document.documentElement;
  const touch = root.getAttribute('data-density') === 'touch';
  if (touch) root.removeAttribute('data-density');
  else root.setAttribute('data-density', 'touch');
  densityBtn.setAttribute('aria-pressed', String(!touch));
});

function setPressed() {
  document.getElementById('cmd-detail')
    .setAttribute('aria-pressed', String(sideView === 'detail'));
  document.getElementById('cmd-compliance')
    .setAttribute('aria-pressed', String(sideView === 'compliance'));
}

let flashTimer = null;
function flash(message) {
  const el = document.getElementById('sb-message');
  el.textContent = message;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { el.textContent = ''; }, 2400);
}

/* --- Status bar ----------------------------------------------------------- */

document.getElementById('sb-date').textContent = data.today;
document.getElementById('sb-source').textContent =
  'FortyGuard tiles + Open-Meteo hourly';
document.getElementById('sb-cache').textContent =
  `cached · generated ${data.generated}`;
document.getElementById('sb-assumed').textContent =
  data.provenance.assumed.length
    ? `${data.provenance.assumed.length} assumed input(s)` : 'no assumed inputs';

/* --- Go ------------------------------------------------------------------- */

paintSummary();
const first = renderRoster(rosterBody, data, select);
const firstRow = rosterBody.querySelector('tbody tr');
if (firstRow) firstRow.setAttribute('aria-selected', 'true');
select(first);
setPressed();
