/* ============================================================================
   The prescription engine, in the browser.

   WHY THIS EXISTS AT ALL. Until now every prescription was computed in Python at
   build time and frozen into a data file. Once trades are editable and day logs
   feed back into the state, the inputs change at runtime, so the per-worker
   maths has to run here. There is no version of an editable roster that avoids
   it.

   WHAT THIS IS NOT. It is not a second source of truth. Every constant comes
   from window.SUNUP_CONSTANTS, generated from src/sunup/constants.py by
   scripts/build_js_constants.py. Nothing numeric is typed into this file.

   HOW IT IS KEPT HONEST. tests/test_js_engine.py runs this module under Node
   over golden vectors emitted by the Python engine and asserts agreement to
   1e-9. Two implementations of the thing that decides whether a worker is told
   to stop will drift; the gate is what stops that being discovered in the field.

   The mirrored functions are, in Python terms:
     effective_wbgt_c, personal_limit_c, work_minutes_per_hour,
     prescribe_hours, daily_stimulus, advance_adaptation, simulate
   ========================================================================== */

const K = (typeof window !== 'undefined' && window.SUNUP_CONSTANTS)
  || (typeof globalThis !== 'undefined' && globalThis.SUNUP_CONSTANTS);

if (!K) {
  throw new Error(
    'SUNUP_CONSTANTS missing. Run scripts/build_js_constants.py and load '
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

   RULE A: PROPORTIONAL. When actual work is at or below the prescription, scale
   every prescribed hour by actual/prescribed. It preserves the planned shape.

   RULE B: BOUNDED CONSERVATIVE. When actual work exceeds the prescription,
   retain every prescribed minute and place the extra work into the hottest
   shift hours first. No hour can exceed 60 minutes. This avoids the old failure
   mode where proportional scaling could invent more than one hour of exposure
   inside a clock hour. Work logged against a zero-minute plan is flagged.
   -------------------------------------------------------------------------- */

export function allocateActual(hours, actualMinutes, worker) {
  const prescribed = hours.reduce((sum, h) => sum + h.minutes, 0);
  const capacity = Math.min(shiftHours(worker), hours.length) * 60;

  if (actualMinutes === null || actualMinutes === undefined) {
    return { duties: hours.map((h) => h.minutes / 60), rule: 'prescribed',
             prescribed, actual: prescribed, unprescribedWork: false };
  }
  const requested = Number(actualMinutes);
  if (!Number.isFinite(requested) || requested < 0) {
    throw new Error('Actual minutes must be a non-negative number.');
  }
  const actual = Math.min(requested, capacity);
  if (prescribed > 0 && actual <= prescribed) {
    const factor = actual / prescribed;
    return { duties: hours.map((h) => (h.minutes * factor) / 60), rule: 'proportional',
             prescribed, actual, requestedActual: requested, unprescribedWork: false };
  }

  const allocated = hours.map((h) => Math.min(60, Math.max(0, h.minutes)));
  let remaining = Math.max(0, actual - allocated.reduce((sum, value) => sum + value, 0));
  const hottestFirst = hours.map((h, index) => ({ h, index })).sort((a, b) =>
    (Number(b.h.overLimit || 0) - Number(a.h.overLimit || 0))
    || (Number(b.h.wbgt || 0) - Number(a.h.wbgt || 0))
    || (Number(a.h.hour || 0) - Number(b.h.hour || 0)));
  for (const { index } of hottestFirst) {
    if (remaining <= 0) break;
    const added = Math.min(60 - allocated[index], remaining);
    allocated[index] += added;
    remaining -= added;
  }
  return {
    duties: allocated.map((minutes) => minutes / 60),
    rule: 'bounded_conservative',
    prescribed,
    actual,
    requestedActual: requested,
    unprescribedWork: prescribed === 0 && actual > 0,
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

export function calendarPct(dayOnJob, worker = null) {
  const table = worker && worker.rampType === 'returning'
    ? K.returningCalendarRampPctByDay : K.calendarRampPctByDay;
  const hit = table[String(dayOnJob)];
  return hit === undefined ? 100 : hit;
}

export function calendarMinutes(dayOnJob, worker) {
  return Math.round((calendarPct(dayOnJob, worker) / 100) * shiftHours(worker) * 60);
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
  let dayOnJob = firstDayOnJob;
  const records = [];

  days.forEach((day) => {
    const hours = prescribeHours(day.hourly, worker, adaptation);
    const prescribed = hours.reduce((sum, h) => sum + h.minutes, 0);

    const hasLog = Object.prototype.hasOwnProperty.call(logs, day.date);
    const entry = hasLog ? logs[day.date] : null;
    const richEntry = entry && typeof entry === 'object' ? entry : null;
    const absent = Boolean(richEntry && (richEntry.absent === true
      || String(richEntry.note || '').trim().toLowerCase() === 'absent'));
    const logged = hasLog
      ? (absent ? 0 : Number(richEntry ? richEntry.minutes : entry)) : null;
    const allocation = allocateActual(hours, logged, worker);
    const stimulus = absent
      ? { degreeHours: 0, value: 0, saturated: false,
        hoursAboveRal: 0, workedHoursEquivalent: 0 }
      : dailyStimulus(hours, worker, allocation);
    const dayOverexposure = overexposure(hours, allocation);
    const adaptationEnd = advanceAdaptation(adaptation, stimulus.value, tau);
    cumulativeOverexposure += dayOverexposure;

    const peak = hours.length
      ? Math.max(...hours.map((h) => h.wbgt)) : null;

    records.push({
      date: day.date,
      dayOnJob,
      projected: Boolean(day.projected),
      hours,
      prescribedMinutes: prescribed,
      actualMinutes: logged === null ? prescribed : allocation.actual,
      actualMinutesLogged: logged,
      allocationClamped: logged !== null && allocation.actual !== logged,
      assumed: logged === null,
      absent,
      absenceReason: absent ? String(richEntry.note || 'Absent') : null,
      allocationRule: absent ? 'absent' : allocation.rule,
      unprescribedWork: allocation.unprescribedWork,
      adaptationStart: adaptation,
      adaptationEnd,
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

    adaptation = adaptationEnd;
    if (!absent) dayOnJob += 1;
  });

  return {
    records,
    finalAdaptation: adaptation,
    cumulativeOverexposure,
    nextDayOnJob: dayOnJob,
  };
}
