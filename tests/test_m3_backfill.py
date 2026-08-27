"""M3 part 2: the 14-day two-site backfill and what it settled.

These pin the measured answers to the two questions M2 left open:
does mild-vs-hot survive once the histories are genuinely disjoint, and does
site assignment, the scenario the exceedance ratio was supposed to support, 
survive at all.

The answers are not the ones the project expected, so they are pinned tightly.
"""

from __future__ import annotations

import pytest

from sunup import acclimatization as ac
from sunup import backfill as bf
from sunup import constants as C
from sunup import scenarios, wbgt

NORM = C.DEGREE_HOURS_FULL_STIMULUS
MODELS = (wbgt.NWB_PSYCHROMETRIC, wbgt.NWB_ISO_ANNEX_D)


@pytest.fixture(scope="module")
def cache():
    return bf.BackfillCache()


@pytest.fixture(scope="module")
def shared(cache):
    return cache.shared_dates(wbgt.NWB_PSYCHROMETRIC)


def peak(day):
    return max(h.wbgt_c for h in day.window(5, 13))


def dose(day, worker=None):
    worker = worker or ac.Worker(worker_id="p", trade="concrete")
    return ac.daily_stimulus(day, worker, 0.0, NORM).degree_hours


def ramp_from(cache, site, dates, comparison, model, tau, shift=(5, 13)):
    worker = ac.Worker(worker_id="w", trade="concrete",
                       shift_start_hour=shift[0], shift_end_hour=shift[1])
    head = ac.simulate(worker, [cache.get(site, d, model) for d in dates],
                       tau=tau, full_stimulus_degree_hours=NORM)
    compare_worker = ac.Worker(worker_id="w", trade="concrete")
    tail = ac.simulate(compare_worker, [cache.get(site, comparison, model)],
                       tau=tau, initial_adaptation=head.final_adaptation,
                       full_stimulus_degree_hours=NORM,
                       first_day_on_job=len(dates) + 1)
    return ac.splice(head, tail)


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_the_backfill_covers_the_full_demo_window(cache, shared):
    window = bf.backfill_dates()
    assert len(window) == 14
    assert len(cache.available_dates("cool_site")) == 14
    assert len(shared) == 14


def test_every_backfilled_day_is_real_retrieved_data(cache, shared):
    for site in bf.SITE_NAMES:
        day = cache.get(site, shared[0], wbgt.NWB_PSYCHROMETRIC)
        assert "fortyguard.heatmap filter_type=3" in day.provenance.dry_bulb
        assert "openmeteo" in day.provenance.wind
        assert "wind" not in day.provenance.assumed_inputs


def test_the_backfill_reads_back_with_the_network_disconnected(cache, shared):
    """The client is constructed with an OfflineTransport, so a day that was
    never fetched raises rather than silently going live during a demo."""
    from sunup.sources.transport import OfflineTransport

    assert isinstance(cache.client.transport, OfflineTransport)
    assert cache.client.live_calls == 0


# ---------------------------------------------------------------------------
# Peak temperature is nearly useless as a predictor of dose
# ---------------------------------------------------------------------------


def test_peak_wbgt_barely_predicts_worked_dose(cache, shared):
    """THE FINDING that reconciles the two halves of the inversion.

    Real days do not differ by a uniform temperature offset, so they do not
    slide along the synthetic sweep curve. What drives adaptation is hours
    actually worked above the RAL, which peak temperature hardly constrains.
    """
    days = [cache.get("hot_site", d, wbgt.NWB_PSYCHROMETRIC) for d in shared]
    peaks = [peak(d) for d in days]
    doses = [dose(d) for d in days]
    mean_p = sum(peaks) / len(peaks)
    mean_d = sum(doses) / len(doses)
    cov = sum((p - mean_p) * (x - mean_d) for p, x in zip(peaks, doses))
    denominator = (sum((p - mean_p) ** 2 for p in peaks)
                   * sum((x - mean_d) ** 2 for x in doses)) ** 0.5
    correlation = cov / denominator
    assert -0.2 < correlation < 0.45, correlation


# ---------------------------------------------------------------------------
# Mild vs hot, with genuinely disjoint histories
# ---------------------------------------------------------------------------


def _survival(cache, shared, key, model):
    days = [(d, cache.get("hot_site", d, wbgt.NWB_PSYCHROMETRIC)) for d in shared]
    ranked = sorted(days, key=key)
    mild = [d for d, _ in ranked[:3]]
    hot = [d for d, _ in reversed(ranked[-3:])]
    assert not set(mild) & set(hot)
    comparison = ranked[len(ranked) // 2][0]
    sweep = ac.default_tau_sweep()
    gaps = [
        ac.compare("x", ramp_from(cache, "hot_site", mild, comparison, model, tau),
                   ramp_from(cache, "hot_site", hot, comparison, model, tau), 4)
        .limit_gap_c
        for tau in sweep
    ]
    material = sum(1 for g in gaps if abs(g) >= C.MATERIAL_LIMIT_GAP_C)
    return material, len(sweep), min(gaps), max(gaps)


@pytest.mark.parametrize("model", MODELS)
def test_mild_vs_hot_by_worked_dose_survives_every_tau_pair(cache, shared, model):
    """M2 got 0/84 and 36/84 with four overlapping days. With fourteen disjoint
    ones it is 84/84 under both wet-bulb methods."""
    material, total, low, high = _survival(cache, shared, lambda p: dose(p[1]), model)
    assert material == total, (model, material, low, high)
    assert low > 0.0


@pytest.mark.parametrize("model,expected", [
    (wbgt.NWB_PSYCHROMETRIC, 36),
    (wbgt.NWB_ISO_ANNEX_D, 54),
])
def test_mild_vs_hot_by_peak_temperature_is_much_weaker(cache, shared, model, expected):
    """The LITERAL reading of "mild vs hot". It survives only about half the tau
    range, because peak temperature is not what drives adaptation."""
    material, total, _low, _high = _survival(
        cache, shared, lambda p: peak(p[1]), model)
    assert material == expected, (model, material)
    assert 0 < material < total


# ---------------------------------------------------------------------------
# Site assignment: the scenario the exceedance ratio was meant to support
# ---------------------------------------------------------------------------


def test_the_exceedance_ratio_does_not_survive_duty_cycle_weighting(cache, shared):
    """1.284x of exceedance hours becomes 1.118x of WORKED dose.

    The extra hot hours at the p95 site are exactly the hours the work/rest rule
    prescribes at or near zero, so more than half the site difference is removed
    before it can reach the state model.
    """
    worker = ac.Worker(worker_id="p", trade="concrete")
    totals = {
        site: sum(dose(cache.get(site, d, wbgt.NWB_PSYCHROMETRIC), worker)
                  for d in shared)
        for site in bf.SITE_NAMES
    }
    ratio = totals["hot_site"] / totals["cool_site"]
    assert 1.05 < ratio < 1.20, ratio
    assert ratio < 1.284


@pytest.mark.parametrize("model", MODELS)
def test_site_assignment_does_not_reach_materiality(cache, model):
    """PINNED NEGATIVE RESULT. The scenario the 1.28x ratio was supposed to
    support is the weakest of the three levers measured."""
    scenario = scenarios.site_assignment_scenario(cache, model)
    sweep = ac.default_tau_sweep()
    gaps = []
    for tau in sweep:
        cool, hot = scenarios.build_site_ramps(scenario, cache, model, tau, NORM)
        gaps.append(ac.compare(scenario.label, cool, hot,
                               scenario.day_on_job).limit_gap_c)
    material = sum(1 for g in gaps if abs(g) >= C.MATERIAL_LIMIT_GAP_C)
    assert material == 0, (model, material, max(gaps))
    assert max(gaps) < C.MATERIAL_LIMIT_GAP_C + 0.01


# ---------------------------------------------------------------------------
# Shift assignment: the strongest lever, and the surviving half of the inversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("late", [(8, 16), (10, 18)])
def test_shift_assignment_survives_every_tau_pair_and_is_inverted(
        cache, shared, model, late):
    """The later shift adapts LESS, in all 84 pairs, under both methods.

    This is the half of the M2 inversion finding that the full backfill
    confirms: the protective schedule removes the exposure that would have
    adapted the worker.
    """
    history = shared[:3]
    comparison = shared[3]
    sweep = ac.default_tau_sweep()
    gaps = []
    for tau in sweep:
        early_ramp = ramp_from(cache, "hot_site", history, comparison, model,
                               tau, shift=(5, 13))
        late_ramp = ramp_from(cache, "hot_site", history, comparison, model,
                              tau, shift=late)
        divergence = ac.compare("shift", late_ramp, early_ramp, 4)
        gaps.append(divergence.limit_gap_c)
        assert divergence.more_adapted.worker.shift_start_hour == 5
    material = sum(1 for g in gaps if abs(g) >= C.MATERIAL_LIMIT_GAP_C)
    assert material == len(sweep), (model, late, material, min(gaps))
    assert min(gaps) > C.MATERIAL_LIMIT_GAP_C


def test_shift_assignment_is_the_strongest_lever(cache, shared):
    """Ranking the three levers, so the writeup quotes the right one."""
    model = wbgt.NWB_PSYCHROMETRIC
    history, comparison = shared[:3], shared[3]
    shift_gap = ac.compare(
        "shift",
        ramp_from(cache, "hot_site", history, comparison, model, ac.Tau(), (10, 18)),
        ramp_from(cache, "hot_site", history, comparison, model, ac.Tau(), (5, 13)),
        4).limit_gap_c
    scenario = scenarios.site_assignment_scenario(cache, model)
    cool, hot = scenarios.build_site_ramps(scenario, cache, model, ac.Tau(), NORM)
    site_gap = abs(ac.compare(scenario.label, cool, hot,
                              scenario.day_on_job).limit_gap_c)
    material, _t, _lo, _hi = _survival(cache, shared, lambda p: dose(p[1]), model)
    assert shift_gap > site_gap, (shift_gap, site_gap)
    assert shift_gap > 0.9
    assert site_gap < C.MATERIAL_LIMIT_GAP_C
    assert material == 84
