/* ============================================================================
   The prescription engine, in the browser.

   WHY THIS EXISTS AT ALL. Until now every prescription was computed in Python at
   build time and frozen into a data file. Once trades are editable and day logs
   feed back into the state, the inputs change at runtime, so the per-worker
   maths has to run here. There is no version of an editable roster that avoids
   it.

   WHAT THIS IS NOT. It is not a second source of truth. Every constant comes
   from window.ACCLIMATE_CONSTANTS, generated from src/acclimate/constants.py by
   scripts/build_js_constants.py. Nothing numeric is typed into this file.

   HOW IT IS KEPT HONEST. tests/test_js_engine.py runs this module under Node
   over golden vectors emitted by the Python engine and asserts agreement to
   1e-9. Two implementations of the thing that decides whether a worker is told
   to stop will drift; the gate is what stops that being discovered in the field.

   The mirrored functions are, in Python terms:
     effective_wbgt_c, personal_limit_c, work_minutes_per_hour,
     prescribe_hours, daily_stimulus, advance_adaptation, simulate
   ========================================================================== */

const K = (typeof window !== 'undefined' && window.ACCLIMATE_CONSTANTS)
  || (typeof globalThis !== 'undefined' && globalThis.ACCLIMATE_CONSTANTS);

if (!K) {
  throw new Error(
    'ACCLIMATE_CONSTANTS missing. Run scripts/build_js_constants.py and load '
    + 'app/data/constants.js before this module.');
}

export const CONSTANTS = K;

/* --- Worker facts ---------------------------------------------------------- */

/** Work class from the trade, unless the roster overrides it explicitly. */
export function workClassOf(worker) {
  return worker.workClassOverride || K.tradeToWorkClass[worker.trade] || 'moderate';
}

export function shiftHours(worker) {
  return Math.max(0, worker.shiftEnd - worker.shiftStart);
}

/* --- ISO 7243 Clause 7, Formula (3): WBGTeff = WBGT + CAV ------------------ */

export function effectiveWbgt(wbgtC, clothing) {
  const adjustment = K.clothingAdjustmentC[clothing];
  if (adjustment === undefined) {
    throw new Error(`unknown clothing ${clothing}`);
  }
  return wbgtC + adjustment;
}

/* --- SPEC step 4: WBGT_limit(A) = RAL + A * (REL - RAL) -------------------- */

export function personalLimit(adaptation, workClass) {
  const ral = K.ralByClass[workClass];
  const rel = K.relByClass[workClass];
  if (ral === undefined || rel === undefined) {
    throw new Error(`unknown work class ${workClass}`);
  }
  const a = Math.min(1, Math.max(0, adaptation));
  return ral + a * (rel - ral);
}

/* --- SPEC step 5: read the work/rest ladder at the personal limit ---------- */

export function workMinutesPerHour(effective, limitC) {
  const excess = effective - limitC;
  for (const [maxExcess, minutes] of K.workRestLadder) {
    if (excess <= maxExcess) return minutes;
  }
  return K.workRestStop;
}

/* --- The prescription, hour by hour ---------------------------------------- */

/**
 * @param {number[]} hourly  24 raw WBGT values for the site-day, index = hour
 * @param {object}   worker
 * @param {number}   adaptation
 */
export function prescribeHours(hourly, worker, adaptation) {
  const workClass = workClassOf(worker);
  const limit = personalLimit(adaptation, workClass);
  const ral = K.ralByClass[workClass];
  const out = [];
  for (let hour = worker.shiftStart; hour < worker.shiftEnd; hour += 1) {
    const raw = hourly[hour];
    if (raw === undefined || raw === null) continue;
    const effective = effectiveWbgt(raw, worker.clothing);
    const minutes = workMinutesPerHour(effective, limit);
    out.push({
      hour,
      wbgt: effective,
      limit,
      overLimit: effective - limit,
      overRal: effective - ral,
      minutes,
      stop: minutes === K.workRestStop,
    });
  }
  return out;
}

/* --- The feedback loop -----------------------------------------------------
   A supervisor logs ONE number for the day; the stimulus integral needs
   per-hour duty. Bridging the two is a modelling decision, so it is named here
   rather than buried.

   RULE A -- PROPORTIONAL. Scale every prescribed hour by actual/prescribed. It
   preserves the shape of the day: the hottest hours were prescribed least and
   still contribute least.

   RULE C -- UNIFORM, the fallback. When the prescription totalled zero and the
   worker worked anyway, rule A divides by zero. There is no shape to preserve
   because the schedule said "no work at all", so the minutes are spread evenly
   across the shift and the day is flagged `unprescribedWork` -- a supervisor
   who logged work on a stop-work day must see that, not have it averaged away.
   -------------------------------------------------------------------------- */

export function allocateActual(hours, actualMinutes, worker) {
  const prescribed = hours.reduce((sum, h) => sum + h.minutes, 0);
  const span = Math.max(1, shiftHours(worker));

  if (actualMinutes === null || actualMinutes === undefined) {
    return { duties: hours.map((h) => h.minutes / 60), rule: 'prescribed',
             prescribed, actual: prescribed, unprescribedWork: false };
  }
  if (prescribed > 0) {
    const factor = actualMinutes / prescribed;
    return { duties: hours.map((h) => (h.minutes * factor) / 60), rule: 'proportional',
             prescribed, actual: actualMinutes, unprescribedWork: false };
  }
  const perHour = actualMinutes / span;
  return {
    duties: hours.map(() => perHour / 60),
    rule: 'uniform',
    prescribed,
    actual: actualMinutes,
    unprescribedWork: actualMinutes > 0,
  };
}

/* --- SPEC step 2, constants.py section 3a ---------------------------------- */

export function dailyStimulus(hours, worker, allocation) {
  const workClass = workClassOf(worker);
  const ral = K.ralByClass[workClass];
  let degreeHours = 0;
  let hoursAbove = 0;
  let worked = 0;

  hours.forEach((h, index) => {
    const duty = allocation.duties[index];
    worked += duty;
    const excess = h.wbgt - ral - K.stimulusFloorDeg;
    if (excess > 0) {
      hoursAbove += 1;
      degreeHours += excess * duty;
    }
  });

  const value = Math.min(degreeHours / K.degreeHoursFullStimulus, 1);
  return {
    degreeHours,
    value,
    saturated: degreeHours >= K.degreeHoursFullStimulus,
    hoursAboveRal: hoursAbove,
    workedHoursEquivalent: worked,
  };
}

/* --- Overexposure ----------------------------------------------------------
   The counterweight to "he adapted faster". Exposure above THIS worker's own
   limit that the schedule never authorised. Reporting only the adaptation gain
   from overwork would be reporting the flattering half.
   -------------------------------------------------------------------------- */

export function overexposure(hours, allocation) {
  let degreeHours = 0;
  hours.forEach((h, index) => {
    const extraDuty = allocation.duties[index] - h.minutes / 60;
    if (extraDuty > 0 && h.overLimit > 0) {
      degreeHours += h.overLimit * extraDuty;
    }
  });
  return degreeHours;
}

/* --- SPEC step 3: A(t+1) = A + s(1-A)/tau_gain - (1-s)A/tau_decay ---------- */

export function advanceAdaptation(adaptation, stimulus, tau) {
  const gain = (tau && tau.gain) || K.tauGainDays;
  const decay = (tau && tau.decay) || K.tauDecayDays;
  const next = adaptation
    + (stimulus * (1 - adaptation)) / gain
    - ((1 - stimulus) * adaptation) / decay;
  return Math.min(1, Math.max(0, next));
}

/* --- The calendar the product argues with ---------------------------------- */

export function calendarPct(dayOnJob) {
  const table = K.calendarRampPctByDay;
  const hit = table[String(dayOnJob)];
  return hit === undefined ? 100 : hit;
}

export function calendarMinutes(dayOnJob, worker) {
  return Math.round((calendarPct(dayOnJob) / 100) * shiftHours(worker) * 60);
}

/* --- Status band ----------------------------------------------------------- */

export function statusFor(minutes, worker) {
  const full = shiftHours(worker) * 60;
  if (minutes <= 0) return 'stop';
  if (minutes >= full) return 'cleared';
  return minutes < full * 0.5 ? 'restricted' : 'reduced';
}

/* --- simulate --------------------------------------------------------------
   Walks a worker forward over dated site-days. `logs` maps ISO date -> actual
   minutes; a date with no entry falls back to the prescription and the day is
   marked `assumed`, never silently treated as measurement.
   -------------------------------------------------------------------------- */

export function simulate({ worker, days, logs = {}, initialAdaptation = 0,
                           firstDayOnJob = 1, tau = null }) {
  let adaptation = initialAdaptation;
  let cumulativeOverexposure = 0;
  const records = [];

  days.forEach((day, index) => {
    const dayOnJob = firstDayOnJob + index;
    const hours = prescribeHours(day.hourly, worker, adaptation);
    const prescribed = hours.reduce((sum, h) => sum + h.minutes, 0);

    const logged = Object.prototype.hasOwnProperty.call(logs, day.date)
      ? logs[day.date] : null;
    const allocation = allocateActual(hours, logged, worker);
    const stimulus = dailyStimulus(hours, worker, allocation);
    const dayOverexposure = overexposure(hours, allocation);
    cumulativeOverexposure += dayOverexposure;

    const peak = hours.length
      ? Math.max(...hours.map((h) => h.wbgt)) : null;

    records.push({
      date: day.date,
      dayOnJob,
      projected: Boolean(day.projected),
      hours,
      prescribedMinutes: prescribed,
      actualMinutes: logged === null ? prescribed : logged,
      assumed: logged === null,
      allocationRule: allocation.rule,
      unprescribedWork: allocation.unprescribedWork,
      adaptationStart: adaptation,
      limit: personalLimit(adaptation, workClassOf(worker)),
      peakWbgt: peak,
      stimulus: stimulus.value,
      degreeHours: stimulus.degreeHours,
      overexposure: dayOverexposure,
      cumulativeOverexposure,
      calendarMinutes: calendarMinutes(dayOnJob, worker),
      divergence: prescribed - calendarMinutes(dayOnJob, worker),
      status: statusFor(prescribed, worker),
    });

    adaptation = advanceAdaptation(adaptation, stimulus.value, tau);
  });

  return { records, finalAdaptation: adaptation, cumulativeOverexposure };
}
