/* Replays the Python engine's golden vectors through app/js/engine.js.
 *
 * Invoked by tests/test_js_engine.py. Prints one JSON object on stdout:
 *   { ok, checked, failures: [{ what, expected, actual, delta }] }
 *
 * Exits non-zero only on a harness error, a vector mismatch is reported as
 * data so the Python test can print something readable. */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

/* engine.js reads its constants off a global, exactly as the browser does. */
const constantsSource = readFileSync(
  join(root, 'app', 'data', 'constants.js'), 'utf8');
globalThis.window = globalThis;
// eslint-disable-next-line no-eval
(0, eval)(constantsSource);

const engine = await import(
  new URL('../app/js/engine.js', import.meta.url).href);

const vectors = JSON.parse(
  readFileSync(join(root, 'tests', 'fixtures', 'golden_vectors.json'), 'utf8'));

const tol = vectors.tolerance;
const failures = [];
let checked = 0;

function close(actual, expected) {
  if (typeof expected === 'number' && typeof actual === 'number') {
    return Math.abs(actual - expected) <= tol;
  }
  return actual === expected;
}

function check(what, actual, expected) {
  checked += 1;
  if (!close(actual, expected)) {
    failures.push({
      what,
      expected,
      actual,
      delta: (typeof expected === 'number' && typeof actual === 'number')
        ? actual - expected : null,
    });
  }
}

/* --- scalars --------------------------------------------------------------- */

for (const v of vectors.scalars) {
  const a = v.args;
  let actual;
  switch (v.fn) {
    case 'personalLimit':
      actual = engine.personalLimit(a.adaptation, a.workClass); break;
    case 'effectiveWbgt':
      actual = engine.effectiveWbgt(a.wbgtC, a.clothing); break;
    case 'workMinutesPerHour':
      actual = engine.workMinutesPerHour(a.effective, a.limitC); break;
    case 'advanceAdaptation':
      actual = engine.advanceAdaptation(a.adaptation, a.stimulus, vectors.tau); break;
    default:
      throw new Error(`unknown fn ${v.fn}`);
  }
  check(`${v.fn}(${JSON.stringify(a)})`, actual, v.expected);
}

/* --- simulations ----------------------------------------------------------- */

for (const sim of vectors.simulations) {
  const result = engine.simulate({
    worker: sim.worker,
    days: sim.days,
    logs: {},                       // golden path is prescribed-only, as Python
    initialAdaptation: sim.initialAdaptation,
    tau: vectors.tau,
  });

  sim.expected.forEach((want, index) => {
    const got = result.records[index];
    const tag = `${sim.label} day ${index + 1}`;
    if (!got) {
      failures.push({ what: `${tag} MISSING`, expected: want.date, actual: null });
      return;
    }
    check(`${tag} date`, got.date, want.date);
    check(`${tag} dayOnJob`, got.dayOnJob, want.dayOnJob);
    check(`${tag} prescribedMinutes`, got.prescribedMinutes, want.prescribedMinutes);
    check(`${tag} adaptationStart`, got.adaptationStart, want.adaptationStart);
    check(`${tag} limit`, got.limit, want.limit);
    if (want.degreeHours !== undefined) {
      check(`${tag} degreeHours`, got.degreeHours, want.degreeHours);
      check(`${tag} stimulus`, got.stimulus, want.stimulus);
    }
    const mins = got.hours.map((h) => h.minutes);
    check(`${tag} minutesPerHour length`, mins.length, want.minutesPerHour.length);
    want.minutesPerHour.forEach((m, h) => {
      check(`${tag} minutesPerHour[${h}]`, mins[h], m);
    });
  });

  if (sim.expectedFinalAdaptation !== undefined) {
    check(`${sim.label} finalAdaptation`,
          result.finalAdaptation, sim.expectedFinalAdaptation);
  }
}

process.stdout.write(JSON.stringify({
  ok: failures.length === 0,
  checked,
  sourceHash: globalThis.SUNUP_CONSTANTS.sourceHash,
  failures: failures.slice(0, 25),
  totalFailures: failures.length,
}));
