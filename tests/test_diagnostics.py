"""Tests for the structural-limit diagnostic.

The claim this supports is strong and needs to be hard to fake: that the ceiling
on weather-driven divergence is a property of the MODEL, not a shortage of
fixtures. If the sweep were buggy the whole M3 conclusion would be wrong, so the
mechanics are tested separately from the finding.
"""

from __future__ import annotations

import pytest

from acclimate import acclimatization as ac
from acclimate import constants as C
from acclimate import diagnostics as dg
from acclimate import scenarios, wbgt


@pytest.fixture(scope="module")
def cache():
    return scenarios.SiteDayCache()


@pytest.fixture(scope="module")
def base_day(cache):
    return cache.get("2026-08-05", wbgt.NWB_PSYCHROMETRIC)


# ---------------------------------------------------------------------------
# offset_day — a controlled perturbation, not an invented day
# ---------------------------------------------------------------------------


def test_offset_shifts_every_hour_by_exactly_the_delta(base_day):
    shifted = dg.offset_day(base_day, 2.5)
    for original, moved in zip(base_day.hours, shifted.hours):
        assert moved.wbgt_c == pytest.approx(original.wbgt_c + 2.5)
        assert moved.dry_bulb_c == pytest.approx(original.dry_bulb_c + 2.5)
        assert moved.globe_c == pytest.approx(original.globe_c + 2.5)


def test_offset_preserves_shape_timing_and_provenance(base_day):
    shifted = dg.offset_day(base_day, -3.0)
    assert shifted.date == base_day.date
    assert shifted.provenance == base_day.provenance
    assert [h.hour for h in shifted.hours] == [h.hour for h in base_day.hours]
    # The diurnal shape is untouched: hour-to-hour differences are identical.
    original = [b.wbgt_c - a.wbgt_c for a, b in zip(base_day.hours, base_day.hours[1:])]
    moved = [b.wbgt_c - a.wbgt_c for a, b in zip(shifted.hours, shifted.hours[1:])]
    assert original == pytest.approx(moved)


def test_zero_offset_is_the_identity(base_day):
    same = dg.offset_day(base_day, 0.0)
    assert [h.wbgt_c for h in same.hours] == [h.wbgt_c for h in base_day.hours]


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_sweep_holds_everything_except_the_weather_constant(base_day):
    sweep = dg.weather_history_sweep(base_day, [-2.0, 0.0, 2.0])
    assert len(sweep.points) == 3
    assert [p.delta_c for p in sweep.points] == [-2.0, 0.0, 2.0]
    assert sweep.history_days == 3
    assert sweep.trade == "concrete"


def test_cold_extreme_produces_no_adaptation(base_day):
    """Below the RAL there is no dose, however long the shift."""
    sweep = dg.weather_history_sweep(base_day, [-20.0])
    point = sweep.points[0]
    assert point.total_dose == 0.0
    assert point.final_adaptation == 0.0
    assert point.personal_limit_c == C.WBGT_LIMIT_UNACCLIMATIZED[C.WorkClass.MODERATE]


def test_hot_extreme_also_produces_no_adaptation(base_day):
    """THE FINDING. Far above the ladder the schedule prescribes zero minutes,
    so the worker accumulates nothing despite extreme heat."""
    sweep = dg.weather_history_sweep(base_day, [+20.0])
    point = sweep.points[0]
    assert point.total_worked_hours == 0.0
    assert point.total_dose == 0.0
    assert point.final_adaptation == 0.0


def test_adaptation_is_non_monotone_in_weather(base_day):
    """Duty-cycle feedback structurally caps the model. If this ever becomes
    monotone the cap has gone and section 4 of the M3 report is wrong."""
    deltas = [d / 2.0 for d in range(-24, 25)]
    sweep = dg.weather_history_sweep(base_day, deltas)
    assert sweep.is_non_monotone
    assert sweep.points[0].delta_c < sweep.peak_delta_c < sweep.points[-1].delta_c
    limits = [p.personal_limit_c for p in sweep.points]
    assert limits[0] < max(limits) > limits[-1]


def test_the_peak_sits_below_the_real_phoenix_day(base_day):
    """Which is why every real day in the demo is on the descending limb, and
    why hotter means less adapted."""
    deltas = [d / 2.0 for d in range(-24, 25)]
    sweep = dg.weather_history_sweep(base_day, deltas)
    assert sweep.peak_delta_c < 0.0


def test_maximum_weather_driven_gap_is_a_fraction_of_the_available_range(base_day):
    """THE HEADLINE DIAGNOSTIC NUMBER."""
    deltas = [d / 2.0 for d in range(-24, 25)]
    sweep = dg.weather_history_sweep(base_day, deltas)
    assert sweep.theoretical_max_gap_c == pytest.approx(3.0)
    assert 0.8 < sweep.max_limit_gap_c < 1.3
    assert 0.25 < sweep.fraction_of_theoretical < 0.45


@pytest.mark.parametrize("trade", ["electrical", "concrete", "rebar"])
def test_the_cap_holds_across_every_trade(base_day, trade):
    deltas = [d / 2.0 for d in range(-24, 25)]
    sweep = dg.weather_history_sweep(base_day, deltas, trade=trade)
    assert sweep.is_non_monotone
    assert 0.25 < sweep.fraction_of_theoretical < 0.45, trade


@pytest.mark.parametrize("shift", [(4, 12), (5, 13), (6, 14)])
def test_the_cap_holds_across_shift_timing(base_day, shift):
    deltas = [d / 2.0 for d in range(-24, 25)]
    sweep = dg.weather_history_sweep(base_day, deltas, shift=shift)
    assert sweep.is_non_monotone
    assert 0.25 < sweep.fraction_of_theoretical < 0.45, shift


def test_the_cap_holds_across_the_whole_tau_sweep(base_day):
    """A ceiling that only existed at one tau would be a tuning artefact."""
    deltas = [float(d) for d in range(-12, 13)]
    gaps = [
        dg.weather_history_sweep(base_day, deltas, tau=tau).max_limit_gap_c
        for tau in ac.default_tau_sweep()
    ]
    assert max(gaps) < 1.6, max(gaps)
    assert min(gaps) > 0.3, min(gaps)


def test_best_and_worst_bracket_every_point(base_day):
    sweep = dg.weather_history_sweep(base_day, [-6.0, -3.0, 0.0, 3.0])
    limits = [p.personal_limit_c for p in sweep.points]
    assert sweep.best.personal_limit_c == max(limits)
    assert sweep.worst.personal_limit_c == min(limits)
    assert sweep.max_limit_gap_c == pytest.approx(max(limits) - min(limits))
