"""M2 demo scenarios, built from real retrieved site-days.

SPEC.md hard constraint 7 says sites are user input and must never be hardcoded
into logic. This module is demo WIRING, the same exception `reference.py` takes:
it pins which cached site-days the M2 report runs on. No engine code imports it.

WHAT IS REAL AND WHAT IS SCENARIO, stated once so the report does not have to
keep hedging:

  REAL      every WBGT value. Each site-day is FortyGuard `filter_type=3` tile
            data (per-cell diurnal min/mean/max) reconstructed against Open-Meteo
            hourly shape, solar, wind, cloud, wet bulb and humidity.
  SCENARIO  which worker is assigned to which days and which shift. That is a
            roster decision, and rostering is exactly what the product advises.

THE DATA CEILING. Only four site-days have cached FortyGuard tiles —
2024-07-15, 2026-07-26, 2026-08-05 and 2026-08-09. A full 14-day backfill is
M3's job and needs FortyGuard credits. Four days is enough to drive a day-4
comparison, which is what the exit test asks for, but it is NOT enough to build
two disjoint three-day histories. The mild-vs-hot scenario therefore overlaps,
and says so.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from acclimate import constants as C
from acclimate import wbgt
from acclimate.sources import openmeteo
from acclimate.sources.fixtures import FixtureStore
from acclimate.sources.fortyguard import parse_temperature_grid

SITE_ID = "phoenix-downtown-parcel"
LATITUDE = C.WBGT_REFERENCE_SITE["latitude"]
LONGITUDE = C.WBGT_REFERENCE_SITE["longitude"]

# date -> the committed filter_type=3 fixture for that day
TILE_FIXTURES: Dict[str, str] = {
    "2024-07-15": "heatmap/filter3_properties_2024-07-15.json",
    "2026-07-26": "heatmap/filter3_properties_2026-07-26.json",
    "2026-08-05": "heatmap/filter3_properties_2026-08-05.json",
    "2026-08-09": "heatmap/filter3_properties_2026-08-09.json",
}

EARLY_SHIFT = (C.DEMO_SHIFT_START_HOUR, C.DEMO_SHIFT_END_HOUR)   # 05:00-13:00
LATE_SHIFT = (10, 18)


@dataclass(frozen=True)
class SiteDay:
    date: dt.date
    day: wbgt.WBGTDay
    shift_degree_hours_above_ral: float

    @property
    def iso(self) -> str:
        return self.date.isoformat()


class SiteDayCache:
    """Builds each site-day once per wet-bulb model, then hands out the result.

    The tau sweep runs 84 parameter pairs; rebuilding 4 WBGT days for each would
    be 336 globe solves per worker for no reason. The WBGT does not depend on
    tau at all.
    """

    def __init__(self, store: Optional[FixtureStore] = None) -> None:
        self.store = store or FixtureStore()
        self._built: Dict[Tuple[str, str], wbgt.WBGTDay] = {}

    def get(self, iso_date: str, natural_wet_bulb_model: str) -> wbgt.WBGTDay:
        key = (iso_date, natural_wet_bulb_model)
        if key not in self._built:
            date = dt.date.fromisoformat(iso_date)
            grid = parse_temperature_grid(self.store.load(TILE_FIXTURES[iso_date]))
            om = openmeteo.load_day(LATITUDE, LONGITUDE, date, self.store)
            self._built[key] = wbgt.build_wbgt_day(
                site_id=SITE_ID,
                grid=grid,
                env=None,          # env_params exists for one day only
                site_longitude=LONGITUDE,
                site_latitude=LATITUDE,
                open_meteo=om,
                natural_wet_bulb_model=natural_wet_bulb_model,
            )
        return self._built[key]

    def all_days(self, natural_wet_bulb_model: str) -> List[SiteDay]:
        ral = C.WBGT_LIMIT_UNACCLIMATIZED[C.WorkClass.MODERATE]
        out = []
        for iso in sorted(TILE_FIXTURES):
            day = self.get(iso, natural_wet_bulb_model)
            out.append(
                SiteDay(
                    date=day.date,
                    day=day,
                    shift_degree_hours_above_ral=day.degree_hours_above(
                        ral, *EARLY_SHIFT
                    ),
                )
            )
        return out

    def ranked_by_dose(self, natural_wet_bulb_model: str) -> List[SiteDay]:
        """Mildest first. Ranking is by measured dose, not by date."""
        return sorted(
            self.all_days(natural_wet_bulb_model),
            key=lambda s: s.shift_degree_hours_above_ral,
        )


@dataclass(frozen=True)
class Scenario:
    """One two-worker comparison: who works which days, on which shift."""

    label: str
    rationale: str
    mild_dates: Tuple[str, ...]
    hot_dates: Tuple[str, ...]
    mild_shift: Tuple[int, int]
    hot_shift: Tuple[int, int]
    comparison_date: str
    comparison_shift: Tuple[int, int] = EARLY_SHIFT
    caveat: str = ""

    @property
    def day_on_job(self) -> int:
        """Both workers are compared on the day AFTER their histories."""
        return len(self.mild_dates) + 1


def shift_assignment_scenario(cache: SiteDayCache, model: str) -> Scenario:
    """Same crew, same site, same days — different assigned shift.

    This is the strongest version available from cached data, because nothing is
    cherry-picked: both workers get the SAME three site-days, and the only
    difference is the roster decision. It is also the scenario the product most
    directly advises on, since shift timing is the lever a supervisor actually
    controls at 6 a.m.
    """
    days = sorted(TILE_FIXTURES)[:3]
    return Scenario(
        label="Shift assignment (same days, same site)",
        rationale=(
            "Two workers, same crew, same trade, both starting the same day. One "
            "is rostered 05:00-13:00, the other 10:00-18:00. Identical weather, "
            "identical calendar position, different measured dose."
        ),
        mild_dates=tuple(days),
        hot_dates=tuple(days),
        mild_shift=EARLY_SHIFT,
        hot_shift=LATE_SHIFT,
        comparison_date=days[-1],
    )


def mild_vs_hot_days_scenario(cache: SiteDayCache, model: str) -> Scenario:
    """SPEC.md's literal scenario: mild vs brutal first three days.

    Only four tile-anchored site-days are cached, so the two histories cannot be
    disjoint — they share whichever days sit in the middle of the ranking. The
    caveat is carried on the Scenario and printed by the report.
    """
    ranked = cache.ranked_by_dose(model)
    mild = tuple(s.iso for s in ranked[:3])
    hot = tuple(s.iso for s in reversed(ranked[-3:]))
    overlap = sorted(set(mild) & set(hot))
    return Scenario(
        label="Mild vs hot first three days (same shift)",
        rationale=(
            "Two workers, same trade, both on day 4, both on the 05:00-13:00 "
            "shift, but staggered starts: one ramped through the mildest cached "
            "site-days, the other through the hottest."
        ),
        mild_dates=mild,
        hot_dates=hot,
        mild_shift=EARLY_SHIFT,
        hot_shift=EARLY_SHIFT,
        comparison_date=ranked[-1].iso,
        caveat=(
            "Only 4 tile-anchored site-days are cached, so the histories overlap "
            "on %s. A 14-day backfill (M3) is what makes this scenario clean."
            % (", ".join(overlap) if overlap else "nothing")
        ),
    )


def build_ramps(
    scenario: Scenario,
    cache: SiteDayCache,
    model: str,
    tau,
    full_stimulus_degree_hours: float,
    trade: str = "concrete",
):
    """(mild ramp, hot ramp). Histories differ; the comparison day is shared.

    Both workers face the SAME site, SAME weather and SAME shift on the day they
    are compared. Every difference in their prescription therefore comes from
    what they accumulated beforehand — which is the model's entire claim, and the
    only way to demonstrate it without contaminating the result.
    """
    from acclimate import acclimatization as ac

    def ramp(worker_id, dates, shift):
        history_worker = ac.Worker(
            worker_id=worker_id, trade=trade,
            shift_start_hour=shift[0], shift_end_hour=shift[1],
        )
        history = ac.simulate(
            worker=history_worker,
            wbgt_days=[cache.get(d, model) for d in dates],
            tau=tau,
            full_stimulus_degree_hours=full_stimulus_degree_hours,
            natural_wet_bulb_model=model,
        )
        comparison_worker = ac.Worker(
            worker_id=worker_id, trade=trade,
            shift_start_hour=scenario.comparison_shift[0],
            shift_end_hour=scenario.comparison_shift[1],
        )
        tail = ac.simulate(
            worker=comparison_worker,
            wbgt_days=[cache.get(scenario.comparison_date, model)],
            tau=tau,
            initial_adaptation=history.final_adaptation,
            full_stimulus_degree_hours=full_stimulus_degree_hours,
            natural_wet_bulb_model=model,
            first_day_on_job=len(dates) + 1,
        )
        return ac.splice(history, tail)

    return (
        ramp("mild", scenario.mild_dates, scenario.mild_shift),
        ramp("hot", scenario.hot_dates, scenario.hot_shift),
    )


def histories_differ(scenario: Scenario) -> bool:
    """True when the two workers actually had different exposure histories."""
    return (scenario.mild_dates != scenario.hot_dates
            or scenario.mild_shift != scenario.hot_shift)
