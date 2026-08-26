"""Diagnostics for the acclimatization model's structural limits.

THE QUESTION THIS ANSWERS. The mild-vs-hot scenario failed to reach materiality
in M2, and the obvious explanation was data coverage, only four cached
site-days, histories overlapping on two of three. But there is a second possible
explanation that no amount of data would fix, and it has to be ruled in or out
before anyone spends credits chasing the first.

Under the corrected stimulus definition (constants.py section 3a) dose is
weighted by the prescribed duty cycle, and the prescription falls as WBGT rises.
So a hotter day pushes dose in two opposite directions at once:

    hotter  ->  larger excess above RAL          ->  MORE dose
    hotter  ->  fewer prescribed working minutes ->  LESS dose

If the second effect wins beyond some temperature, then accumulated adaptation
is a NON-MONOTONE function of how hot the weather was, and there is a ceiling on
the divergence weather history alone can ever produce. That ceiling would be a
property of the model, not of the fixtures.

`weather_history_sweep` measures it: hold the worker, the trade, the shift, the
day count and the comparison day fixed, and vary ONLY the temperature offset
applied to the history days. Whatever spread of personal limits comes out is the
most the model can do from weather alone.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional, Sequence, Tuple

from acclimate import acclimatization as ac
from acclimate import constants as C
from acclimate.wbgt import WBGTDay


def offset_day(day: WBGTDay, delta_c: float) -> WBGTDay:
    """A copy of a real site-day with every hourly WBGT shifted by ``delta_c``.

    Only the WBGT and its components move; the day keeps its real diurnal shape,
    its real timing, and its provenance. This is a controlled perturbation of
    measured data, not a synthetic day invented from nothing, and the report
    labels every number derived from it as synthetic.
    """
    hours = tuple(
        replace(
            hour,
            wbgt_c=hour.wbgt_c + delta_c,
            dry_bulb_c=hour.dry_bulb_c + delta_c,
            natural_wet_bulb_c=hour.natural_wet_bulb_c + delta_c,
            globe_c=hour.globe_c + delta_c,
        )
        for hour in day.hours
    )
    return replace(day, hours=hours)


@dataclass(frozen=True)
class SweepPoint:
    delta_c: float
    final_adaptation: float
    personal_limit_c: float
    total_dose: float
    total_worked_hours: float
    shift_work_minutes_on_comparison_day: int
    saturated_days: int


@dataclass(frozen=True)
class WeatherHistorySweep:
    """What weather history alone can and cannot do to a worker's limit."""

    points: Tuple[SweepPoint, ...]
    history_days: int
    trade: str
    shift: Tuple[int, int]

    @property
    def max_limit_gap_c(self) -> float:
        """THE HEADLINE: the widest personal-limit separation achievable by
        varying nothing but the history weather."""
        limits = [p.personal_limit_c for p in self.points]
        return max(limits) - min(limits)

    @property
    def best(self) -> SweepPoint:
        return max(self.points, key=lambda p: p.personal_limit_c)

    @property
    def worst(self) -> SweepPoint:
        return min(self.points, key=lambda p: p.personal_limit_c)

    @property
    def is_non_monotone(self) -> bool:
        """True when adaptation PEAKS at some offset and falls beyond it.

        If this is True, duty-cycle feedback is structurally capping the model:
        making the weather hotter past the peak makes the worker LESS adapted,
        because the protective schedule removes his exposure.
        """
        limits = [p.personal_limit_c for p in self.points]
        peak = limits.index(max(limits))
        return 0 < peak < len(limits) - 1

    @property
    def peak_delta_c(self) -> float:
        return self.best.delta_c

    @property
    def theoretical_max_gap_c(self) -> float:
        """The full RAL-to-REL span. The model can never exceed this."""
        work_class = C.TRADE_TO_WORK_CLASS[self.trade]
        return (C.WBGT_LIMIT_ACCLIMATIZED[work_class]
                - C.WBGT_LIMIT_UNACCLIMATIZED[work_class])

    @property
    def fraction_of_theoretical(self) -> float:
        return self.max_limit_gap_c / self.theoretical_max_gap_c


def weather_history_sweep(
    base_day: WBGTDay,
    deltas_c: Sequence[float],
    trade: str = "concrete",
    history_days: int = 3,
    shift: Tuple[int, int] = (C.DEMO_SHIFT_START_HOUR, C.DEMO_SHIFT_END_HOUR),
    tau: Optional[ac.Tau] = None,
    full_stimulus_degree_hours: float = C.DEGREE_HOURS_FULL_STIMULUS,
    comparison_day: Optional[WBGTDay] = None,
) -> WeatherHistorySweep:
    """Vary ONLY the history weather; hold everything else fixed.

    Each point runs a worker through ``history_days`` copies of ``base_day``
    offset by delta_c, then reads his personal limit on a shared comparison day
    that is identical for every point.
    """
    tau = tau or ac.Tau()
    worker = ac.Worker(
        worker_id="sweep", trade=trade,
        shift_start_hour=shift[0], shift_end_hour=shift[1],
    )
    comparison = comparison_day if comparison_day is not None else base_day

    points: List[SweepPoint] = []
    for delta in deltas_c:
        history = [offset_day(base_day, delta) for _ in range(history_days)]
        ramp = ac.simulate(
            worker=worker, wbgt_days=history, tau=tau,
            full_stimulus_degree_hours=full_stimulus_degree_hours,
        )
        tail = ac.simulate(
            worker=worker, wbgt_days=[comparison], tau=tau,
            initial_adaptation=ramp.final_adaptation,
            full_stimulus_degree_hours=full_stimulus_degree_hours,
            first_day_on_job=history_days + 1,
        )
        record = tail.days[0]
        points.append(
            SweepPoint(
                delta_c=delta,
                final_adaptation=ramp.final_adaptation,
                personal_limit_c=record.personal_limit_c,
                total_dose=sum(d.stimulus.degree_hours for d in ramp.days),
                total_worked_hours=sum(
                    d.stimulus.worked_hours_equivalent for d in ramp.days),
                shift_work_minutes_on_comparison_day=record.shift_work_minutes,
                saturated_days=ramp.saturated_days,
            )
        )

    return WeatherHistorySweep(
        points=tuple(points), history_days=history_days, trade=trade, shift=shift,
    )
