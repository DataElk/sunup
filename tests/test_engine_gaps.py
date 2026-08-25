"""The three engine gaps the roster prototype exposed, and their fixes.

Gaps 14, 13 and 5/9 from the 2026-08-24 prototype gap report. The others were
view concerns and are deliberately not addressed.
"""

from __future__ import annotations

import datetime as dt

import pytest

from acclimate import acclimatization as ac
from acclimate import backfill as bf
from acclimate import constants as C
from acclimate import wbgt

NORM = C.DEGREE_HOURS_FULL_STIMULUS


@pytest.fixture(scope="module")
def cache():
    return bf.BackfillCache()


@pytest.fixture(scope="module")
def days(cache):
    dates = cache.shared_dates(wbgt.NWB_PSYCHROMETRIC)
    return [cache.get("hot_site", d, wbgt.NWB_PSYCHROMETRIC) for d in dates]


@pytest.fixture(scope="module")
def worker():
    return ac.Worker(worker_id="w", trade="concrete")


# ---------------------------------------------------------------------------
# GAP 14 — a worker on leave must DECAY, never reset
# ---------------------------------------------------------------------------


def test_an_empty_ramp_returns_the_state_carried_in(worker):
    """THE CORRECTNESS BUG. The old `else 0.0` reported a fully adapted worker
    as fully unadapted the moment he was simulated over an empty window."""
    empty = ac.simulate(worker, [], initial_adaptation=0.62,
                        full_stimulus_degree_hours=NORM)
    assert empty.final_adaptation == 0.62
    assert empty.days == ()
    assert ac.simulate(worker, [], full_stimulus_degree_hours=NORM).final_adaptation == 0.0


def test_leave_decays_the_state_rather_than_resetting_it(worker, days):
    earned = ac.simulate(worker, days[:5], full_stimulus_degree_hours=NORM)
    start = earned.final_adaptation
    assert start > 0.4

    leave = [ac.Absence(dt.date(2026, 9, 1) + dt.timedelta(days=i)) for i in range(7)]
    after = ac.simulate(worker, leave, initial_adaptation=start,
                        full_stimulus_degree_hours=NORM)
    assert 0.0 < after.final_adaptation < start
    assert after.final_adaptation / start > 0.5      # a week is not a reset
    assert after.absent_days == 7
    assert after.worked_days == 0


def test_fourteen_days_absence_matches_the_constant_it_was_tuned_for(worker, days):
    """constants.py section 3 justifies TAU_DECAY = 13 by "A ~ 0.34 retained
    after 14 days of zero stimulus". This is that claim, measured."""
    earned = ac.simulate(worker, days[:5], full_stimulus_degree_hours=NORM)
    start = earned.final_adaptation
    leave = [ac.Absence(dt.date(2026, 9, 1) + dt.timedelta(days=i)) for i in range(14)]
    after = ac.simulate(worker, leave, initial_adaptation=start,
                        full_stimulus_degree_hours=NORM)
    assert after.final_adaptation / start == pytest.approx(0.34, abs=0.04)


def test_absence_does_not_advance_the_osha_ramp_position(worker, days):
    """A man on leave does not progress his calendar ramp. If absence advanced
    day_on_job the counterfactual would silently flatter the calendar."""
    sequence = [days[0], ac.Absence(dt.date(2026, 9, 1)), days[1]]
    ramp = ac.simulate(worker, sequence, full_stimulus_degree_hours=NORM)
    assert [d.day_on_job for d in ramp.days] == [1, 1, 2]
    assert [d.absent for d in ramp.days] == [False, True, False]


def test_an_absent_day_carries_no_prescription(worker):
    ramp = ac.simulate(worker, [ac.Absence(dt.date(2026, 9, 1), "sick")],
                       initial_adaptation=0.5, full_stimulus_degree_hours=NORM)
    record = ramp.days[0]
    assert record.absent
    assert record.absence_reason == "sick"
    assert record.hours == ()
    assert record.minutes_per_hour == ()
    assert record.shift_work_minutes == 0
    assert record.binding_hour is None
    assert record.stimulus.value == 0.0


def test_absence_is_distinguishable_from_a_worked_day_of_zero_minutes(cache, worker):
    """Gap 14's other half: a 10:00-18:00 worker is prescribed zero minutes but
    is NOT absent, and the two must not look the same."""
    dates = cache.shared_dates(wbgt.NWB_PSYCHROMETRIC)
    idle = ac.Worker(worker_id="idle", trade="concrete",
                     shift_start_hour=10, shift_end_hour=18)
    worked = ac.simulate(
        idle, [cache.get("hot_site", dates[0], wbgt.NWB_PSYCHROMETRIC)],
        full_stimulus_degree_hours=NORM).days[0]
    absent = ac.simulate(worker, [ac.Absence(dates[0])],
                         full_stimulus_degree_hours=NORM).days[0]
    assert worked.shift_work_minutes == absent.shift_work_minutes == 0
    assert not worked.absent and absent.absent
    assert len(worked.hours) == 8 and absent.hours == ()


# ---------------------------------------------------------------------------
# GAP 13 — forward projection
# ---------------------------------------------------------------------------


def test_projection_continues_from_where_the_history_ended(worker, days):
    observed = ac.simulate(worker, days[:7], full_stimulus_degree_hours=NORM)
    full = ac.project(observed, ac.repeat_day(days[6], 7))
    assert len(full.days) == 14
    assert full.days[7].adaptation_start == pytest.approx(observed.final_adaptation)
    # Continuous across the seam.
    for previous, following in zip(full.days, full.days[1:]):
        assert following.adaptation_start == pytest.approx(previous.adaptation_end)


def test_projected_records_are_flagged_and_separable(worker, days):
    observed = ac.simulate(worker, days[:7], full_stimulus_degree_hours=NORM)
    full = ac.project(observed, ac.repeat_day(days[6], 7))
    assert len(full.observed) == 7
    assert len(full.projected) == 7
    assert all(not d.projected for d in full.observed)
    assert all(d.projected for d in full.projected)
    # "Past is solid, future is dashed" is now expressible.
    assert full.observed + full.projected == full.days


def test_projection_keeps_counting_days_on_job(worker, days):
    observed = ac.simulate(worker, days[:5], full_stimulus_degree_hours=NORM)
    full = ac.project(observed, ac.repeat_day(days[4], 5))
    assert [d.day_on_job for d in full.days] == list(range(1, 11))
    assert full.days[-1].calendar_pct == 100


def test_projection_can_include_planned_absence(worker, days):
    observed = ac.simulate(worker, days[:5], full_stimulus_degree_hours=NORM)
    plan = [days[4], ac.Absence(dt.date(2026, 9, 5), "rest day"), days[4]]
    full = ac.project(observed, plan)
    assert full.projected[1].absent
    assert full.projected[1].adaptation_end < full.projected[1].adaptation_start


def test_projection_preserves_the_workers_configuration(worker, days):
    observed = ac.simulate(worker, days[:3], full_stimulus_degree_hours=NORM)
    full = ac.project(observed, ac.repeat_day(days[2], 3))
    assert full.worker == observed.worker
    assert full.tau == observed.tau
    assert full.full_stimulus_degree_hours == observed.full_stimulus_degree_hours
    assert full.initial_adaptation == observed.initial_adaptation


def test_repeat_day_advances_the_date_and_records_the_substitution(days):
    """A projection has to sit somewhere in time. `[day] * count` handed back
    the same frozen record `count` times, so every projected day shared the
    source date -- which reached M4's ramp strip as a "today" marker drawn on
    all six future cells."""
    source = days[4]
    copies = ac.repeat_day(source, 3)
    assert [d.date for d in copies] == [
        source.date + dt.timedelta(days=n) for n in (1, 2, 3)
    ]
    assert source.date.isoformat() not in [d.date.isoformat() for d in copies]
    for copy in copies:
        assert any("repeated from" in note for note in copy.notes)
        assert copy.series_c == source.series_c


def test_repeat_day_rejects_a_negative_count(days):
    with pytest.raises(ValueError):
        ac.repeat_day(days[0], -1)


def test_a_projected_ramp_reaches_higher_adaptation_than_the_history_alone(worker, days):
    observed = ac.simulate(worker, days[:5], full_stimulus_degree_hours=NORM)
    full = ac.project(observed, ac.repeat_day(days[4], 9))
    assert full.final_adaptation > observed.final_adaptation
    assert full.final_adaptation <= 1.0


# ---------------------------------------------------------------------------
# GAP 5/9 — retain the per-hour excess
# ---------------------------------------------------------------------------


def test_every_hour_carries_the_excess_that_produced_its_rung(worker, days):
    record = ac.simulate(worker, days[:4], full_stimulus_degree_hours=NORM).days[-1]
    assert len(record.hours) == worker.shift_hours
    for hour in record.hours:
        expected = ac.work_minutes_per_hour(hour.effective_wbgt_c, hour.personal_limit_c)
        assert hour.minutes == expected
        assert hour.excess_over_limit_c == pytest.approx(
            hour.effective_wbgt_c - hour.personal_limit_c)
        assert hour.duty_fraction == pytest.approx(hour.minutes / 60.0)


def test_both_thresholds_are_retained_because_they_do_different_jobs(worker, days):
    """The ladder is read at the personal limit; the stimulus integrates above
    the fixed RAL. Showing one while the model uses the other would mislead."""
    record = ac.simulate(worker, days[:4], full_stimulus_degree_hours=NORM).days[-1]
    ral = C.WBGT_LIMIT_UNACCLIMATIZED[worker.work_class]
    for hour in record.hours:
        assert hour.excess_over_ral_c == pytest.approx(hour.effective_wbgt_c - ral)
        assert hour.excess_over_ral_c >= hour.excess_over_limit_c


def test_hours_carry_their_clock_time(worker, days):
    record = ac.simulate(worker, days[:2], full_stimulus_degree_hours=NORM).days[-1]
    assert [h.hour for h in record.hours] == list(
        range(worker.shift_start_hour, worker.shift_end_hour))


def test_the_binding_hour_is_identified_and_explains_itself(worker, days):
    record = ac.simulate(worker, days[:4], full_stimulus_degree_hours=NORM).days[-1]
    binding = record.binding_hour
    assert binding is not None
    assert binding.minutes == record.binding_minutes_per_hour
    # Earliest of any tie: that is when the crew actually has to stop.
    tied = [h for h in record.hours if h.minutes == binding.minutes]
    assert binding.hour == min(h.hour for h in tied)


def test_stop_work_hours_are_labelled(worker, days):
    record = ac.simulate(worker, days[:4], full_stimulus_degree_hours=NORM).days[-1]
    for hour in record.hours:
        assert hour.is_stop_work == (hour.minutes == C.WORK_REST_STOP)


def test_minutes_per_hour_still_works_for_existing_callers(worker, days):
    record = ac.simulate(worker, days[:3], full_stimulus_degree_hours=NORM).days[-1]
    assert record.minutes_per_hour == tuple(h.minutes for h in record.hours)
    assert sum(record.minutes_per_hour) == record.shift_work_minutes


def test_prescribe_hours_is_usable_without_running_a_whole_ramp(worker, days):
    """The interface needs "what would this day look like at adaptation A"
    without simulating anything."""
    hours = ac.prescribe_hours(days[0], worker, 0.5)
    assert len(hours) == worker.shift_hours
    assert all(h.personal_limit_c == ac.personal_limit_c(0.5, worker.work_class)
               for h in hours)
    hotter = ac.prescribe_hours(days[0], worker, 0.0)
    assert sum(h.minutes for h in hours) >= sum(h.minutes for h in hotter)
