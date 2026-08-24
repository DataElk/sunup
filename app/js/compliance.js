/* ============================================================================
   Compliance record.

   The document an employer keeps to show a decision was defensible. Its job is
   NOT to look confident — it is to be auditable, which means it states its own
   assumptions and provenance next to the numbers.

   constants.py section 6: the OSHA heat standard is PROPOSED, not law.
   Enforcement is nevertheless active under the General Duty Clause and the Heat
   National Emphasis Program. The record says exactly that, because a document
   that overstates the regulatory position is worse than none.
   ========================================================================== */

function line(text, cls) {
  const p = document.createElement('p');
  if (cls) p.className = cls;
  p.style.margin = '0';
  p.textContent = text;
  return p;
}

function block(label, rows) {
  const wrap = document.createElement('section');
  wrap.className = 'section';
  const head = document.createElement('div');
  head.className = 'section-label';
  head.textContent = label;
  const dl = document.createElement('dl');
  dl.className = 'kv';
  for (const [key, value] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = key;
    const dd = document.createElement('dd');
    dd.textContent = value;
    dl.append(dt, dd);
  }
  wrap.append(head, dl);
  return wrap;
}

/** Plain-text record — what actually gets filed or pasted into a report. */
export function recordText(data) {
  const out = [];
  out.push('ACCLIMATE — HEAT EXPOSURE COMPLIANCE RECORD');
  out.push(`Date of record: ${data.today}`);
  out.push(`Generated: ${data.generated}`);
  out.push('');
  out.push('REGULATORY POSITION');
  out.push('  The federal OSHA heat standard is PROPOSED and not finalised.');
  out.push('  Enforcement is active under the General Duty Clause and the Heat');
  out.push('  National Emphasis Program (CPL 03-00-024, renewed 2026-04-10).');
  out.push('  Prescriptions below are based on NIOSH RAL/REL exposure limits.');
  out.push('');
  out.push('METHOD');
  out.push(`  Wet bulb model:   ${data.model.wetBulb}`);
  out.push(`  Stimulus norm:    ${data.model.normalisation} degC-h`);
  out.push(`  tau gain/decay:   ${data.model.tauGain} / ${data.model.tauDecay} days`);
  out.push('');
  out.push('DATA PROVENANCE');
  out.push(`  Dry bulb:   ${data.provenance.dryBulb}`);
  out.push(`  Shape:      ${data.provenance.shape}`);
  out.push(`  Wet bulb:   ${data.provenance.wetBulb}`);
  out.push(`  Wind:       ${data.provenance.wind}`);
  out.push(`  ASSUMED:    ${data.provenance.assumed.join('; ') || 'none'}`);
  out.push('');
  out.push('PRESCRIPTIONS');
  out.push('  worker           trade       shift        day  model  calendar  diff');
  for (const w of data.workers) {
    const t = w.today;
    out.push(`  ${w.name.padEnd(16)} ${w.trade.padEnd(11)} ${w.shift}  `
      + `${String(t.dayOnJob).padStart(3)}  ${String(t.minutes).padStart(5)}  `
      + `${String(t.calendarMinutes).padStart(8)}  ${String(t.divergence).padStart(4)}`);
  }
  out.push('');
  out.push('EXCLUDED INPUTS');
  out.push('  No age, sex, BMI, fitness, medical history, hydration or residence');
  out.push('  data was used. Every input is environmental or job-assigned.');
  return out.join('\n');
}

export function renderCompliance(root, data) {
  const parts = [];

  parts.push(block('Record', [
    ['Date of record', data.today],
    ['Generated', data.generated],
    ['Crew size', String(data.workers.length)],
  ]));

  const reg = document.createElement('section');
  reg.className = 'section';
  const regHead = document.createElement('div');
  regHead.className = 'section-label';
  regHead.textContent = 'Regulatory position';
  reg.append(regHead,
    line('The federal OSHA heat standard is PROPOSED and not finalised.'),
    line('Enforcement is active under the General Duty Clause and the Heat '
       + 'National Emphasis Program (CPL 03-00-024, renewed 2026-04-10).'),
    line('Prescriptions use NIOSH RAL/REL exposure limits.'));
  parts.push(reg);

  parts.push(block('Method', [
    ['Wet bulb', data.model.wetBulb],
    ['Stimulus normalisation', `${data.model.normalisation} degC-h`],
    ['tau gain / decay', `${data.model.tauGain} / ${data.model.tauDecay} d`],
  ]));

  parts.push(block('Provenance', [
    ['Dry bulb', data.provenance.dryBulb],
    ['Diurnal shape', data.provenance.shape],
    ['Wet bulb', data.provenance.wetBulb],
    ['Wind', data.provenance.wind],
    ['Assumed', data.provenance.assumed.join('; ') || 'none'],
  ]));

  const excluded = document.createElement('section');
  excluded.className = 'section';
  const exHead = document.createElement('div');
  exHead.className = 'section-label';
  exHead.textContent = 'Excluded inputs';
  excluded.append(exHead,
    line('No age, sex, BMI, fitness, medical history, hydration or residence '
       + 'data was used. Every input is environmental or job-assigned.'));
  parts.push(excluded);

  const pre = document.createElement('pre');
  pre.className = 'num';
  pre.style.margin = '0';
  pre.style.overflow = 'auto';
  pre.textContent = recordText(data);
  const filed = document.createElement('section');
  filed.className = 'section';
  const filedHead = document.createElement('div');
  filedHead.className = 'section-label';
  filedHead.textContent = 'Filed text';
  filed.append(filedHead, pre);
  parts.push(filed);

  root.replaceChildren(...parts);
}
