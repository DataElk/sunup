"""M2 — the acclimatization engine.

    Environment  ->  WBGT  ->  daily stimulus s  ->  adaptation state A  ->  work/rest
                              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                              this module

SPEC.md's model, implemented as written:

  2. daily stimulus  s in [0,1] — degree-hours above the worker's personal limit,
     normalised by DEGREE_HOURS_FULL_STIMULUS. Only exposure above the limit
     builds adaptation.
  3. state update    A(t+1) = A + s*(1-A)/tau_gain - (1-s)*A/tau_decay
  4. personal limit  WBGT_limit(A) = RAL + A*(REL - RAL)
  5. work/rest       read off the NIOSH ladder at that limit

THE INTELLECTUAL CORE is step 4. NIOSH already publishes two curves and treats
acclimatization as a binary switch; we place each worker continuously between
them. No threshold is invented.

WHAT THE MODEL IS NOT ALLOWED TO KNOW. Every input here is environmental or
job-assigned. constants.py section 7 lists what is excluded and why — age, sex,
BMI, fitness, medical history, hydration, residence. `Worker` rejects them
structurally rather than by convention, because the reason is legal, not
stylistic: restricting a man's hours on the basis of age is age discrimination.

A CAUTION THE ENGINE REPORTS ON ITSELF. If s saturates at 1 for every worker on
every day, the update degenerates to A(t+1) = A + (1-A)/tau_gain — a function of
DAYS ELAPSED alone, which is exactly the calendar the product exists to replace.
Every result therefore carries `saturated_days`, and `Ramp.is_degenerate` says so
outright. See scripts/m2_report.py for what that does on real Phoenix data.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from acclimate import constants as C
from acclimate.errors import ForbiddenInput, ImplausibleValue
from acclimate.wbgt import WBGTDay


# ---------------------------------------------------------------------------
# Worker — job-assigned attributes only
# ---------------------------------------------------------------------------


def reject_forbidden_inputs(fields: Mapping[str, object]) -> None:
    """Raise if any key names an input constants.py section 7 forbids.

    Called on any mapping that came from outside the system. The check is on the
    KEY, so a caller cannot smuggle age in as `age` and cannot claim it was an
    oversight. constants.py section 7 has the legal reasoning.
    """
    offending = sorted(set(k.lower() for k in fields) & C.FORBIDDEN_INPUTS)
    if offending:
        raise ForbiddenInput(
            "these inputs are forbidden and must never be accepted, not even "
            "optionally: %s. See constants.py section 7 — restricting a worker's "
            "hours on the basis of any of these is a legal exposure, not a "
            "modelling preference." % offending
        )


@dataclass(frozen=True)
class Worker:
    """Everything the model is permitted to know about a person.

    Trade and clothing are job assignments. Shift hours are a roster decision.
    There is deliberately nothing else, and there is deliberately no optional
    field for anything else.
    """

    worker_id: str
    trade: str
    clothing: str = "work_clothes"
    shift_start_hour: int = C.DEMO_SHIFT_START_HOUR
    shift_end_hour: int = C.DEMO_SHIFT_END_HOUR

    def __post_init__(self) -> None:
        if self.trade not in C.TRADE_TO_WORK_CLASS:
            raise ValueError(
                "unknown trade %r; known trades: %s"
                % (self.trade, sorted(C.TRADE_TO_WORK_CLASS))
            )
        if self.clothing not in C.CLOTHING_ADJUSTMENT_C:
            raise ValueError(
                "unknown clothing %r; known: %s"
                % (self.clothing, sorted(C.CLOTHING_ADJUSTMENT_C))
            )
        if not 0 <= self.shift_start_hour < self.shift_end_hour <= 24:
            raise ValueError(
                "shift must satisfy 0 <= start < end <= 24; got %d-%d"
                % (self.shift_start_hour, self.shift_end_hour)
            )

    @property
    def work_class(self) -> C.WorkClass:
        return C.TRADE_TO_WORK_CLASS[self.trade]

    @property
    def shift_hours(self) -> int:
        return self.shift_end_hour - self.shift_start_hour

    @classmethod
    def from_mapping(cls, fields: Mapping[str, object]) -> "Worker":
        """Build from untrusted input, rejecting forbidden fields first."""
        reject_forbidden_inputs(fields)
        allowed = {
            k: v for k, v in fields.items()
            if k in ("worker_id", "trade", "clothing", "shift_start_hour", "shift_end_hour")
        }
        unknown = sorted(set(fields) - set(allowed))
        if unknown:
            raise ValueError("unrecognised worker fields: %s" % unknown)
        return cls(**allowed)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Tau:
    """The two time constants. constants.py section 3 tags both [TUNED]."""

    gain_days: float = C.TAU_GAIN_DAYS
    decay_days: float = C.TAU_DECAY_DAYS

    def __post_init__(self) -> None:
        if self.gain_days <= 0 or self.decay_days <= 0:
            raise ValueError("tau values must be positive")

    @property
    def asymmetry(self) -> float:
        """Decay/gain. The physiologically important property is that this is
        well above 1: adaptation is earned in days and lost over weeks."""
        return self.decay_days / self.gain_days


# ---------------------------------------------------------------------------
# The four model steps
# ---------------------------------------------------------------------------


def personal_limit_c(adaptation: float, work_class: C.WorkClass) -> float:
    """SPEC step 4: WBGT_limit(A) = RAL + A*(REL - RAL).

    A = 0 gives NIOSH's Recommended Alert Limit (unacclimatized); A = 1 gives the
    Recommended Exposure Limit (acclimatized). Everything between is the claim.
    """
    if not C.A_MIN <= adaptation <= C.A_MAX:
        raise ImplausibleValue("adaptation %r outside [0, 1]" % adaptation)
    ral = C.WBGT_LIMIT_UNACCLIMATIZED[work_class]
    rel = C.WBGT_LIMIT_ACCLIMATIZED[work_class]
    return ral + adaptation * (rel - ral)


def effective_wbgt_c(wbgt_c: float, clothing: str) -> float:
    """ISO 7243:2017 Clause 7, Formula (3): WBGTeff = WBGT + CAV.

    [VERIFIED 2026-08-24 against the standard.] The adjustment is ADDED to the
    measured WBGT rather than subtracted from the limit. Arithmetically the same
    for a single comparison, but it is what the standard says, and it keeps the
    limit meaning "the NIOSH limit" rather than "the NIOSH limit, adjusted".
    """
    return wbgt_c + C.CLOTHING_ADJUSTMENT_C[clothing]


def work_minutes_per_hour(effective_wbgt: float, limit_c: float) -> int:
    """SPEC step 5: read the NIOSH work/rest ladder at the personal limit."""
    excess = effective_wbgt - limit_c
    for max_excess, minutes in C.WORK_REST_LADDER:
        if excess <= max_excess:
            return minutes
    return C.WORK_REST_STOP


@dataclass(frozen=True)
class Stimulus:
    degree_hours: float
    value: float          # s in [0, 1]
    saturated: bool       # s hit the ceiling — the day carries no information
    hours_above_ral: int
    worked_hours_equivalent: float   # sum of duty fractions over the shift


def daily_stimulus(
    day: WBGTDay,
    worker: Worker,
    adaptation: float,
    full_stimulus_degree_hours: float = C.DEGREE_HOURS_FULL_STIMULUS,
) -> Stimulus:
    """SPEC step 2, integrated over the RIGHT thing. constants.py section 3a.

        dose = SUM over shift hours of  max(WBGTeff - RAL, 0) * (minutes worked / 60)

    TWO CHOICES THAT ARE THE WHOLE POINT:

    1. The threshold is the FIXED RAL for the workload class, not the worker's
       moving personal limit. Integrating above the moving limit is circular: it
       makes an adapted worker accumulate LESS dose than an unadapted one
       standing beside him in identical weather, which is backwards. The
       environment does not know how adapted anyone is.

    2. Only hours ACTUALLY WORKED count, weighted by the prescribed duty cycle.
       An hour spent resting in shade produces no adaptive stimulus, so an hour
       prescribed at 15 min/h contributes a quarter of its degree-hours.

    The schedule still depends on adaptation, so dose still depends on
    adaptation — but now in the physically correct direction: a more adapted
    worker is cleared for more minutes, so he accumulates MORE dose, not less.
    That is a stabilising feedback, and it is also what makes the hottest hours
    self-limiting: they are exactly the hours prescribed at zero.
    """
    if full_stimulus_degree_hours <= 0:
        raise ValueError("full_stimulus_degree_hours must be positive")

    ral = C.WBGT_LIMIT_UNACCLIMATIZED[worker.work_class]      # fixed threshold
    limit = personal_limit_c(adaptation, worker.work_class)   # sets the schedule only

    degree_hours = 0.0
    hours_above = 0
    worked = 0.0
    for hour in day.window(worker.shift_start_hour, worker.shift_end_hour):
        effective = effective_wbgt_c(hour.wbgt_c, worker.clothing)
        duty = work_minutes_per_hour(effective, limit) / 60.0
        worked += duty
        excess = effective - ral - C.STIMULUS_FLOOR_DEG
        if excess > 0.0:
            hours_above += 1
            degree_hours += excess * duty

    value = min(degree_hours / full_stimulus_degree_hours, 1.0)
    return Stimulus(
        degree_hours=degree_hours,
        value=value,
        saturated=degree_hours >= full_stimulus_degree_hours,
        hours_above_ral=hours_above,
        worked_hours_equivalent=worked,
    )


def advance_adaptation(adaptation: float, stimulus: float, tau: Tau) -> float:
    """SPEC step 3: A(t+1) = A + s*(1-A)/tau_gain - (1-s)*A/tau_decay."""
    nxt = (
        adaptation
        + stimulus * (1.0 - adaptation) / tau.gain_days
        - (1.0 - stimulus) * adaptation / tau.decay_days
    )
    return min(max(nxt, C.A_MIN), C.A_MAX)


def calendar_ramp_pct(day_on_job: int) -> int:
    """OSHA's "Rule of 20 Percent" — the thing the model is measured against.

    Day 1 is 20% of a normal shift, +20% per day, 100% from day 5. It is what a
    supervisor does today, and it is the counterfactual the UI must always show.
    """
    if day_on_job < 1:
        raise ValueError("day_on_job starts at 1; got %r" % day_on_job)
    return C.CALENDAR_RAMP_PCT_BY_DAY.get(day_on_job, 100)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DayRecord:
    date: dt.date
    day_on_job: int
    adaptation_start: float
    adaptation_end: float
    stimulus: Stimulus
    personal_limit_c: float
    peak_effective_wbgt_c: float
    minutes_per_hour: Tuple[int, ...]
    binding_minutes_per_hour: int
    shift_work_minutes: int
    model_pct: float
    calendar_pct: int

    @property
    def model_minus_calendar_pct(self) -> float:
        return self.model_pct - self.calendar_pct

    @property
    def stop_work(self) -> bool:
        """True when at least one shift hour is a full stop.

        NOT a useful discriminator on a Phoenix summer afternoon: the peak hour
        exceeds the ladder for everyone, adapted or not, so `binding_minutes_per_hour`
        is 0 for every worker and carries no information. What separates workers
        is HOW MANY hours they can work and by how much — see
        `Divergence.max_minutes_per_hour_gap` and `shift_work_minutes`.
        """
        return self.binding_minutes_per_hour == C.WORK_REST_STOP

    @property
    def mean_minutes_per_hour(self) -> float:
        return self.shift_work_minutes / len(self.minutes_per_hour)

    @property
    def workable_hours(self) -> int:
        return sum(1 for m in self.minutes_per_hour if m > 0)


@dataclass(frozen=True)
class Ramp:
    worker: Worker
    days: Tuple[DayRecord, ...]
    tau: Tau
    full_stimulus_degree_hours: float
    natural_wet_bulb_model: str

    @property
    def final_adaptation(self) -> float:
        return self.days[-1].adaptation_end if self.days else 0.0

    @property
    def saturated_days(self) -> int:
        return sum(1 for d in self.days if d.stimulus.saturated)

    @property
    def is_degenerate(self) -> bool:
        """Every day saturated, so the state carries no exposure information.

        When this is True the model is a day-counter wearing a physics costume,
        and any "divergence" between two workers is coming from somewhere other
        than their heat exposure. Check it before believing a result.
        """
        return bool(self.days) and self.saturated_days == len(self.days)

    def at_day(self, day_on_job: int) -> DayRecord:
        for record in self.days:
            if record.day_on_job == day_on_job:
                return record
        raise KeyError("no record for day %d" % day_on_job)


def simulate(
    worker: Worker,
    wbgt_days: Sequence[WBGTDay],
    tau: Optional[Tau] = None,
    initial_adaptation: float = 0.0,
    full_stimulus_degree_hours: float = C.DEGREE_HOURS_FULL_STIMULUS,
    natural_wet_bulb_model: str = "psychrometric",
    first_day_on_job: int = 1,
) -> Ramp:
    """Run a worker's ramp over a sequence of site-days.

    The prescription for a day uses the adaptation the worker STARTED that day
    with — you cannot credit a man for adaptation he has not earned yet, and a
    supervisor has to be able to write the schedule at 6 a.m.
    """
    tau = tau or Tau()
    adaptation = initial_adaptation
    records = []

    for index, day in enumerate(wbgt_days):
        limit = personal_limit_c(adaptation, worker.work_class)
        shift = day.window(worker.shift_start_hour, worker.shift_end_hour)
        if not shift:
            raise ImplausibleValue(
                "shift %02d:00-%02d:00 selected no hours from %s"
                % (worker.shift_start_hour, worker.shift_end_hour, day.date)
            )
        per_hour = [
            work_minutes_per_hour(effective_wbgt_c(h.wbgt_c, worker.clothing), limit)
            for h in shift
        ]
        stimulus = daily_stimulus(day, worker, adaptation, full_stimulus_degree_hours)
        next_adaptation = advance_adaptation(adaptation, stimulus.value, tau)

        records.append(
            DayRecord(
                date=day.date,
                day_on_job=first_day_on_job + index,
                adaptation_start=adaptation,
                adaptation_end=next_adaptation,
                stimulus=stimulus,
                personal_limit_c=limit,
                peak_effective_wbgt_c=max(
                    effective_wbgt_c(h.wbgt_c, worker.clothing) for h in shift
                ),
                minutes_per_hour=tuple(per_hour),
                binding_minutes_per_hour=min(per_hour),
                shift_work_minutes=sum(per_hour),
                model_pct=100.0 * sum(per_hour) / (60.0 * len(shift)),
                calendar_pct=calendar_ramp_pct(first_day_on_job + index),
            )
        )
        adaptation = next_adaptation

    return Ramp(
        worker=worker,
        days=tuple(records),
        tau=tau,
        full_stimulus_degree_hours=full_stimulus_degree_hours,
        natural_wet_bulb_model=natural_wet_bulb_model,
    )


# ---------------------------------------------------------------------------
# The two-worker comparison M2's exit test turns on
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Divergence:
    """What separates two workers the calendar treats identically.

    The two slots are assigned BY MEASUREMENT, not by scenario label. Under the
    corrected stimulus definition (constants.py section 3a) the environmentally
    hotter arm can end up LESS adapted, because the protective schedule removes
    the exposure that would have adapted him. Naming the slots after the weather
    would hide exactly the finding worth reporting, so `compare` sorts them.
    """

    label: str
    day_on_job: int
    less_adapted: Ramp
    more_adapted: Ramp
    calendar_pct: int
    inverted: bool           # the hotter-history arm is the LESS adapted one
    less_adapted_arm: str    # which scenario arm each slot turned out to be
    more_adapted_arm: str

    # -- the continuous metric, reported first because it is what survives ----

    @property
    def limit_gap_c(self) -> float:
        """Difference in personal limit, degC-WBGT. THE PRIMARY METRIC.

        Continuous and monotone in accumulated dose, so unlike the prescription
        it does not depend on where a worker happens to fall relative to a
        15-minute rung of the NIOSH ladder. This is the number that survives.
        """
        return (self.more_adapted.at_day(self.day_on_job).personal_limit_c
                - self.less_adapted.at_day(self.day_on_job).personal_limit_c)

    @property
    def adaptation_gap(self) -> float:
        return (self.more_adapted.at_day(self.day_on_job).adaptation_start
                - self.less_adapted.at_day(self.day_on_job).adaptation_start)

    @property
    def limit_gap_is_material(self) -> bool:
        return abs(self.limit_gap_c) >= C.MATERIAL_LIMIT_GAP_C

    # -- the quantised metric, reported second -------------------------------

    @property
    def per_hour_gaps(self) -> Tuple[int, ...]:
        low = self.less_adapted.at_day(self.day_on_job).minutes_per_hour
        high = self.more_adapted.at_day(self.day_on_job).minutes_per_hour
        return tuple(h - l for l, h in zip(low, high))

    @property
    def max_minutes_per_hour_gap(self) -> int:
        """Largest single-hour difference in prescribed working minutes.

        The BINDING (minimum) hour is useless on a Phoenix afternoon: the peak
        hour is a stop-work for everybody, adapted or not.
        """
        gaps = self.per_hour_gaps
        return max(gaps, key=abs) if gaps else 0

    @property
    def hours_with_different_prescription(self) -> int:
        return sum(1 for g in self.per_hour_gaps if g != 0)

    @property
    def shift_minutes_gap(self) -> int:
        return (self.more_adapted.at_day(self.day_on_job).shift_work_minutes
                - self.less_adapted.at_day(self.day_on_job).shift_work_minutes)

    @property
    def is_material(self) -> bool:
        """One rung of the NIOSH ladder is 15 min/h — a different instruction."""
        return abs(self.max_minutes_per_hour_gap) >= C.MATERIAL_DIVERGENCE_MIN_PER_HOUR

    @property
    def both_degenerate(self) -> bool:
        return self.less_adapted.is_degenerate and self.more_adapted.is_degenerate


def splice(head: Ramp, tail: Ramp) -> Ramp:
    """Join a history ramp to a continuation computed on a different shift.

    The two-worker comparison needs each worker's HISTORY to differ while the
    comparison day itself is identical for both — same site, same weather, same
    shift. Otherwise the difference in prescription mixes accumulated adaptation
    with that day's own exposure, and the model's actual claim is not what is
    being demonstrated.
    """
    if head.days and tail.days:
        expected = head.days[-1].adaptation_end
        if abs(tail.days[0].adaptation_start - expected) > 1e-9:
            raise ImplausibleValue(
                "continuation does not start where the history ended: %.6f vs %.6f"
                % (tail.days[0].adaptation_start, expected)
            )
    return Ramp(
        worker=head.worker,
        days=head.days + tail.days,
        tau=head.tau,
        full_stimulus_degree_hours=head.full_stimulus_degree_hours,
        natural_wet_bulb_model=head.natural_wet_bulb_model,
    )


def compare(
    label: str,
    mild: Ramp,
    hot: Ramp,
    day_on_job: int,
) -> Divergence:
    """Compare two ramps. `mild` and `hot` name the ENVIRONMENTAL arms.

    Which of them is actually the more adapted worker is decided by the model,
    not by the argument order — see Divergence.
    """
    if mild.worker.work_class != hot.worker.work_class:
        raise ValueError(
            "the comparison is only meaningful for the same work class; got %s vs %s"
            % (mild.worker.work_class, hot.worker.work_class)
        )
    mild_a = mild.at_day(day_on_job).adaptation_start
    hot_a = hot.at_day(day_on_job).adaptation_start
    hotter_is_more_adapted = hot_a >= mild_a
    return Divergence(
        label=label,
        day_on_job=day_on_job,
        less_adapted=mild if hotter_is_more_adapted else hot,
        more_adapted=hot if hotter_is_more_adapted else mild,
        calendar_pct=calendar_ramp_pct(day_on_job),
        inverted=not hotter_is_more_adapted,
        less_adapted_arm="mild" if hotter_is_more_adapted else "hot",
        more_adapted_arm="hot" if hotter_is_more_adapted else "mild",
    )


def tau_sweep(
    gain_range: Iterable[float],
    decay_range: Iterable[float],
) -> Tuple[Tau, ...]:
    """Every (gain, decay) pair in the ranges SPEC.md requires M2 to report."""
    return tuple(
        Tau(gain_days=g, decay_days=d) for g in gain_range for d in decay_range
    )


def default_tau_sweep() -> Tuple[Tau, ...]:
    """SPEC.md M2: tau_gain in [3,6] and tau_decay in [10,21]."""
    lo_g, hi_g = C.TAU_GAIN_SENSITIVITY_RANGE
    lo_d, hi_d = C.TAU_DECAY_SENSITIVITY_RANGE
    gains = [lo_g + i * 0.5 for i in range(int((hi_g - lo_g) / 0.5) + 1)]
    decays = [float(d) for d in range(int(lo_d), int(hi_d) + 1)]
    return tau_sweep(gains, decays)
