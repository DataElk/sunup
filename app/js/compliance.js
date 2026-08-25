/* ============================================================================
   Compliance record — drawer content.

   The document an employer keeps to show a decision was defensible. Its job is
   not to look confident; it is to be auditable, which means stating its
   assumptions and provenance next to the numbers.

   constants.py section 6: the OSHA heat standard is PROPOSED, not law.
   Enforcement is nevertheless active under the General Duty Clause and the Heat
   National Emphasis Program. The record says exactly that — a document that
   overstates the regulatory position is worse than none.

   There is deliberately no "filed text" block. The previous version rendered
   the whole record twice, once as structure and once as a monospace dump of the
   same content. Copy produces the text; the panel does not need to preview it.
   ========================================================================== */

function section(label, ...children) {
  const wrap = document.createElement('section');
  wrap.className = 'section';
  if (label) {
    const head = document.createElement('div');
    head.className = 'section-label';
    head.textContent = label;
    wrap.appendChild(head);
  }
  wrap.append(...children);
  return wrap;
}

function paragraph(text) {
  const p = document.createElement('p');
  p.style.margin = '0';
  p.style.fontSize = 'var(--text-caption)';
  p.textContent = text;
  return p;
}

function keyValues(rows) {
  const dl = document.createElement('dl');
  dl.className = 'kv';
  for (const [key, value] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = key;
    const dd = document.createElement('dd');
    dd.textContent = value;
    dl.append(dt, dd);
  }
  return dl;
}

/** Plain text — what gets filed or pasted into a report. Copy only. */
export function recordText(data) {
  const out = [];
  out.push('ACCLIMATE - HEAT EXPOSURE COMPLIANCE RECORD');
  out.push(`Date of record: ${data.today}`);
  out.push(`Generated: ${data.generated}`);
  out.push('');
  out.push('REGULATORY POSITION');
  out.push('  The federal OSHA heat standard is PROPOSED and not finalised.');
  out.push('  Enforcement is active under the General Duty Clause and the Heat');
  out.push('  National Emphasis Program (CPL 03-00-024, renewed 2026-04-10).');
  out.push('  Prescriptions below use NIOSH RAL/REL exposure limits.');
  out.push('');
  out.push('METHOD');
  out.push(`  Wet bulb model: ${data.model.wetBulb}`);
  out.push(`  Stimulus norm:  ${data.model.normalisation} degC-h`);
  out.push(`  tau gain/decay: ${data.model.tauGain} / ${data.model.tauDecay} days`);
  out.push('');
  out.push('DATA PROVENANCE');
  out.push(`  Dry bulb: ${data.provenance.dryBulb}`);
  out.push(`  Shape:    ${data.provenance.shape}`);
  out.push(`  Wet bulb: ${data.provenance.wetBulb}`);
  out.push(`  Wind:     ${data.provenance.wind}`);
  out.push(`  ASSUMED:  ${data.provenance.assumed.join('; ') || 'none'}`);
  out.push('');
  out.push('PRESCRIPTIONS');
  out.push('  worker         trade       start  day  model  calendar   diff  reason');
  for (const w of data.workers) {
    const t = w.today;
    out.push(`  ${w.name.padEnd(14)} ${w.trade.padEnd(11)} ${w.shift}  `
      + `${String(t.dayOnJob).padStart(3)}  ${String(t.minutes).padStart(5)}  `
      + `${String(t.calendarMinutes).padStart(8)}  ${String(t.divergence).padStart(5)}  `
      + `${w.levers.reason}`);
  }
  out.push('');
  out.push('EXCLUDED INPUTS');
  out.push('  No age, sex, BMI, fitness, medical history, hydration or residence');
  out.push('  data was used. Every input is environmental or job-assigned.');
  return out.join('\n');
}

export function renderCompliance(root, data) {
  const parts = [];

  parts.push(section('Record', keyValues([
    ['Date of record', data.today],
    ['Generated', data.generated],
    ['Crew size', String(data.workers.length)],
  ])));

  parts.push(section('Regulatory position',
    paragraph('The federal OSHA heat standard is PROPOSED and not finalised.'),
    paragraph('Enforcement is active under the General Duty Clause and the Heat '
      + 'National Emphasis Program (CPL 03-00-024, renewed 2026-04-10).'),
    paragraph('Prescriptions use NIOSH RAL/REL exposure limits.')));

  parts.push(section('Method', keyValues([
    ['Wet bulb', data.model.wetBulb],
    ['Stimulus normalisation', `${data.model.normalisation} degC-h`],
    ['tau gain / decay', `${data.model.tauGain} / ${data.model.tauDecay} d`],
  ])));

  parts.push(section('Provenance', keyValues([
    ['Dry bulb', data.provenance.dryBulb],
    ['Diurnal shape', data.provenance.shape],
    ['Wet bulb', data.provenance.wetBulb],
    ['Wind', data.provenance.wind],
    ['Assumed', data.provenance.assumed.join('; ') || 'none'],
  ])));

  parts.push(section('Prescriptions today', keyValues(
    data.workers.map((w) => [
      `${w.name} · ${w.shift}`,
      `${w.today.minutes} min (calendar ${w.today.calendarMinutes})`,
    ]))));

  parts.push(section('Excluded inputs',
    paragraph('No age, sex, BMI, fitness, medical history, hydration or '
      + 'residence data was used. Every input is environmental or job-assigned.')));

  root.replaceChildren(...parts);
}
