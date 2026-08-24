"""M2 exit test — the acclimatization engine and the two-worker divergence.

SPEC.md, milestone M2:

    Exit: the two-worker divergence reproduces from real retrieved data — same
    trade, same day-on-job, mild vs hot first three days, materially different
    prescriptions. Sensitivity report across tau_gain in [3,6] and tau_decay in
    [10,21] showing the divergence survives the whole range.
    And it must survive BOTH wet-bulb methods.

THE EXIT TEST DOES NOT PASS AS SPECIFIED, and these tests say so rather than
being written around it. At DEGREE_HOURS_FULL_STIMULUS = 6.0 the stimulus term
saturates on every real Phoenix shift, s is pinned at 1, and the divergence is
exactly zero for both wet-bulb methods across all 84 tau pairs.

Each failing property is pinned deliberately. If someone later "fixes" the
saturation by accident, these tests fail and force the finding back into view
instead of letting it disappear.
"""

from __future__ import annotations

import pytest

from acclimate import acclimatization as ac
from acclimate import constants as C
from acclimate import scenarios, wbgt
from acclimate.errors import ForbiddenInput, ImplausibleValue

SPEC_NORM = C.DEGREE_HOURS_FULL_STIMULUS      # 6.0, as written
ALT_NORM = C.DEGREE_HOURS_ALT_STIMULUS        # 40.0, proposed
MODELS = (wbgt.NWB_PSYCHROMETRIC, wbgt.NWB_ISO_ANNEX_D)


@pytest.fixture(scope="module")
def cache():
    return scenarios.SiteDayCache()


def diverge(cache, scenario, model, norm, tau=None):
    mild, hot = scenarios.build_ramps(
        scenario, cache, model, tau or ac.Tau(), norm)
    return ac.compare(scenario.label, mild, hot, scenario.day_on_job)


# ---------------------------------------------------------------------------
# The model's four steps
# ---------------------------------------------------------------------------


def test_personal_limit_interpolates_between_the_two_niosh_curves():
    """SPEC step 4 — the intellectual core. A=0 is RAL, A=1 is REL."""
    moderate = C.WorkClass.MODERATE
    assert ac.personal_limit_c(0.0, moderate) == C.WBGT_LIMIT_UNACCLIMATIZED[moderate]
    assert ac.personal_limit_c(1.0, moderate) == C.WBGT_LIMIT_ACCLIMATIZED[moderate]
    assert ac.personal_limit_c(0.5, moderate) == pytest.approx(26.5)
    # Monotone, so more adaptation never lowers a worker's limit.
    limits = [ac.personal_limit_c(a / 10.0, moderate) for a in range(11)]
    assert limits == sorted(limits)


def test_personal_limit_rejects_an_impossible_state():
    with pytest.raises(ImplausibleValue):
        ac.personal_limit_c(1.5, C.WorkClass.MODERATE)


def test_work_rest_ladder_matches_the_constants_table():
    limit = 25.0
    assert ac.work_minutes_per_hour(limit - 5, limit) == 60
    assert ac.work_minutes_per_hour(limit + 0.0, limit) == 60
    assert ac.work_minutes_per_hour(limit + 0.5, limit) == 45
    assert ac.work_minutes_per_hour(limit + 1.5, limit) == 30
    assert ac.work_minutes_per_hour(limit + 2.5, limit) == 15
    assert ac.work_minutes_per_hour(limit + 3.5, limit) == C.WORK_REST_STOP


def test_clothing_adjustment_is_added_to_wbgt_not_subtracted_from_the_limit():
    """ISO 7243:2017 Clause 7, Formula (3): WBGTeff = WBGT + CAV."""
    assert ac.effective_wbgt_c(30.0, "work_clothes") == 30.0
    assert ac.effective_wbgt_c(30.0, "double_layer_woven") == 33.0
    assert ac.effective_wbgt_c(30.0, "vapor_barrier_limited") == 41.0


def test_state_update_gains_with_stimulus_and_decays_without():
    tau = ac.Tau(gain_days=4.0, decay_days=13.0)
    assert ac.advance_adaptation(0.0, 1.0, tau) == pytest.approx(0.25)
    assert ac.advance_adaptation(0.5, 0.0, tau) == pytest.approx(0.5 - 0.5 / 13.0)
    # Bounded.
    assert 0.0 <= ac.advance_adaptation(0.99, 1.0, tau) <= 1.0
    assert ac.advance_adaptation(0.0, 0.0, tau) == 0.0


def test_gain_is_faster_than_decay():
    """constants.py section 3: earned in days, lost over weeks. If a re-tune
    ever inverts this, the model stops being physiological."""
    tau = ac.Tau()
    assert tau.asymmetry > 2.0
    gained = ac.advance_adaptation(0.5, 1.0, tau) - 0.5
    lost = 0.5 - ac.advance_adaptation(0.5, 0.0, tau)
    assert gained > lost


def test_full_stimulus_every_day_reaches_high_adaptation_in_about_two_weeks():
    tau = ac.Tau()
    a = 0.0
    for _ in range(14):
        a = ac.advance_adaptation(a, 1.0, tau)
    assert a > 0.95


def test_calendar_ramp_is_the_osha_rule_of_20_percent():
    assert [ac.calendar_ramp_pct(d) for d in range(1, 7)] == [20, 40, 60, 80, 100, 100]
    with pytest.raises(ValueError):
        ac.calendar_ramp_pct(0)


# ---------------------------------------------------------------------------
# Forbidden inputs — a legal constraint, not a preference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", sorted(C.FORBIDDEN_INPUTS))
def test_every_forbidden_input_is_rejected(field):
    with pytest.raises(ForbiddenInput):
        ac.Worker.from_mapping(
            {"worker_id": "w", "trade": "concrete", field: "anything"})


def test_worker_accepts_only_job_assigned_fields():
    worker = ac.Worker.from_mapping(
        {"worker_id": "w1", "trade": "rebar", "clothing": "work_clothes"})
    assert worker.work_class is C.WorkClass.HEAVY
    with pytest.raises(ValueError):
        ac.Worker.from_mapping({"worker_id": "w", "trade": "concrete", "nickname": "x"})
    with pytest.raises(ValueError):
        ac.Worker(worker_id="w", trade="astronaut")


# ---------------------------------------------------------------------------
# THE EXIT TEST
# ---------------------------------------------------------------------------


def test_the_specified_normalisation_saturates_on_every_real_site_day(cache):
    """The finding that decides whether the central claim is true."""
    worker = ac.Worker(worker_id="probe", trade="concrete")
    for site in cache.all_days(wbgt.NWB_PSYCHROMETRIC):
        s = ac.daily_stimulus(site.day, worker, 0.0, SPEC_NORM)
        assert s.saturated, site.iso
        assert s.value == 1.0, site.iso
        assert s.degree_hours > 3 * SPEC_NORM, site.iso


@pytest.mark.parametrize("model", MODELS)
def test_at_the_specified_normalisation_the_divergence_is_exactly_zero(cache, model):
    """PINNED FAILURE. s is pinned at 1, so the state model is a day-counter and
    the two workers are indistinguishable. Both wet-bulb methods, both scenarios."""
    for build in (scenarios.shift_assignment_scenario,
                  scenarios.mild_vs_hot_days_scenario):
        scenario = build(cache, model)
        d = diverge(cache, scenario, model, SPEC_NORM)
        assert d.both_degenerate, scenario.label
        assert d.adaptation_gap == 0.0, scenario.label
        assert d.max_minutes_per_hour_gap == 0, scenario.label
        assert d.shift_minutes_gap == 0, scenario.label
        assert not d.is_material, scenario.label


def test_headline_divergence_is_material_at_the_proposed_normalisation(cache):
    """The one configuration that does what the exit test asks for."""
    scenario = scenarios.shift_assignment_scenario(cache, wbgt.NWB_PSYCHROMETRIC)
    d = diverge(cache, scenario, wbgt.NWB_PSYCHROMETRIC, ALT_NORM)
    assert d.is_material
    assert d.max_minutes_per_hour_gap == 15
    assert d.shift_minutes_gap == 30
    assert d.hours_with_different_prescription == 2
    assert d.limit_gap_c == pytest.approx(0.49, abs=0.02)
    # The calendar cannot tell them apart; that is the whole point.
    assert d.calendar_pct == 80
    assert d.mild.at_day(4).calendar_pct == d.hot.at_day(4).calendar_pct


@pytest.mark.parametrize("model", MODELS)
def test_headline_divergence_survives_both_wet_bulb_methods_at_default_tau(cache, model):
    scenario = scenarios.shift_assignment_scenario(cache, model)
    d = diverge(cache, scenario, model, ALT_NORM)
    assert d.is_material, MODELS
    assert d.max_minutes_per_hour_gap == 15
    assert d.adaptation_gap > 0.0


def test_headline_divergence_survives_the_entire_tau_sweep(cache):
    """SPEC.md M2: tau_gain in [3,6], tau_decay in [10,21], all 84 pairs."""
    scenario = scenarios.shift_assignment_scenario(cache, wbgt.NWB_PSYCHROMETRIC)
    sweep = ac.default_tau_sweep()
    assert len(sweep) == 84
    gaps = [
        diverge(cache, scenario, wbgt.NWB_PSYCHROMETRIC, ALT_NORM, tau)
        .max_minutes_per_hour_gap
        for tau in sweep
    ]
    assert all(abs(g) >= C.MATERIAL_DIVERGENCE_MIN_PER_HOUR for g in gaps), gaps
    # And the hot worker is always the one with more allowance, never inverted.
    assert all(g > 0 for g in gaps)


def test_iso_annex_d_does_NOT_survive_the_entire_tau_sweep(cache):
    """PINNED PARTIAL FAILURE — the honest answer to "both wet-bulb methods?".

    Under ISO Annex D the divergence is material for most of the tau range but
    not all of it, because the NIOSH ladder is quantised in 15-minute rungs and
    the effect is roughly one rung wide. The underlying adaptation gap never
    vanishes; only its expression through the ladder does.
    """
    scenario = scenarios.shift_assignment_scenario(cache, wbgt.NWB_ISO_ANNEX_D)
    results = [
        diverge(cache, scenario, wbgt.NWB_ISO_ANNEX_D, ALT_NORM, tau)
        for tau in ac.default_tau_sweep()
    ]
    material = [d for d in results if d.is_material]
    assert 0 < len(material) < len(results), (
        "ISO Annex D now behaves differently across tau; re-measure the report"
    )
    assert 0.7 < len(material) / len(results) < 1.0
    # The continuous gap survives even where the quantised one does not.
    assert all(d.adaptation_gap > 0 for d in results)


def test_the_comparison_day_is_shared_so_the_gap_is_purely_history(cache):
    """If the two workers faced different weather on the comparison day, the
    result would mix accumulated adaptation with that day's own exposure."""
    for build in (scenarios.shift_assignment_scenario,
                  scenarios.mild_vs_hot_days_scenario):
        scenario = build(cache, wbgt.NWB_PSYCHROMETRIC)
        assert scenarios.histories_differ(scenario), scenario.label
        mild, hot = scenarios.build_ramps(
            scenario, cache, wbgt.NWB_PSYCHROMETRIC, ac.Tau(), ALT_NORM)
        m, h = mild.at_day(scenario.day_on_job), hot.at_day(scenario.day_on_job)
        assert m.date == h.date
        assert m.peak_effective_wbgt_c == pytest.approx(h.peak_effective_wbgt_c)
        assert len(m.minutes_per_hour) == len(h.minutes_per_hour)


def test_more_exposure_always_produces_more_adaptation(cache):
    """Monotonicity. If this ever inverts the model is not a heat model."""
    worker = ac.Worker(worker_id="w", trade="concrete")
    ranked = cache.ranked_by_dose(wbgt.NWB_PSYCHROMETRIC)
    stimuli = [
        ac.daily_stimulus(s.day, worker, 0.0, ALT_NORM).value for s in ranked
    ]
    assert stimuli == sorted(stimuli), stimuli
    tau = ac.Tau()
    states = [ac.advance_adaptation(0.0, s, tau) for s in stimuli]
    assert states == sorted(states)


def test_splice_refuses_a_discontinuous_continuation(cache):
    scenario = scenarios.shift_assignment_scenario(cache, wbgt.NWB_PSYCHROMETRIC)
    worker = ac.Worker(worker_id="w", trade="concrete")
    days = [cache.get(d, wbgt.NWB_PSYCHROMETRIC) for d in scenario.mild_dates]
    head = ac.simulate(worker, days, full_stimulus_degree_hours=ALT_NORM)
    bad = ac.simulate(worker, days[:1], initial_adaptation=0.9,
                      full_stimulus_degree_hours=ALT_NORM, first_day_on_job=4)
    with pytest.raises(ImplausibleValue):
        ac.splice(head, bad)


def test_ramp_reports_its_own_degeneracy(cache):
    worker = ac.Worker(worker_id="w", trade="concrete")
    days = [cache.get(d, wbgt.NWB_PSYCHROMETRIC) for d in sorted(scenarios.TILE_FIXTURES)]
    saturated = ac.simulate(worker, days, full_stimulus_degree_hours=SPEC_NORM)
    informative = ac.simulate(worker, days, full_stimulus_degree_hours=ALT_NORM)
    assert saturated.is_degenerate
    assert saturated.saturated_days == len(days)
    assert not informative.is_degenerate


def test_every_wbgt_day_used_by_m2_is_real_retrieved_data(cache):
    """SPEC.md M2 requires the divergence to come from real retrieved data.

    Each site-day must be FortyGuard tile data plus Open-Meteo hourly — nothing
    modelled end to end, nothing hand-authored.
    """
    for site in cache.all_days(wbgt.NWB_PSYCHROMETRIC):
        provenance = site.day.provenance
        assert "fortyguard.heatmap filter_type=3" in provenance.dry_bulb
        assert "openmeteo" in provenance.dry_bulb_shape
        assert "openmeteo" in provenance.wind
        assert "wind" not in provenance.assumed_inputs
