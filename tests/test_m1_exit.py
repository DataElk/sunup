"""M1 exit test.

SPEC.md, milestone M1:

    Exit: reproduces the verified reference in constants.py section 5 —
    downtown Phoenix 2024-07-15 gives ~31 degC at 14:00 and ~24.8 degC at 06:00,
    both within +/-1 degC. The day crosses both the RAL and REL curves for
    moderate work.

"Done" means these pass, not that the code looks finished.
"""

from __future__ import annotations

import os
import re

import pytest

from acclimate import constants as C
from acclimate import reference, wbgt
from acclimate.physics import diurnal
from acclimate.sources import openmeteo


# ---------------------------------------------------------------------------
# The exit criteria themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hour", sorted(C.WBGT_REFERENCE_HOURS_C))
def test_reference_hour_within_one_degree(reference_day, hour):
    target = C.WBGT_REFERENCE_HOURS_C[hour]
    got = reference_day.at(hour).wbgt_c
    assert abs(got - target) <= C.WBGT_REFERENCE_TOLERANCE_C, (
        "WBGT at %02d:00 was %.3f degC, reference %.1f degC, error %+.3f"
        % (hour, got, target, got - target)
    )


def test_day_crosses_both_niosh_curves_for_moderate_work(reference_day):
    ral = C.WBGT_LIMIT_UNACCLIMATIZED[C.WorkClass.MODERATE]
    rel = C.WBGT_LIMIT_ACCLIMATIZED[C.WorkClass.MODERATE]
    assert ral < rel, "RAL is the unacclimatized (lower) curve; constants are swapped"
    assert reference_day.crosses(ral), (
        "day never crosses RAL %.1f; range was %.2f..%.2f"
        % (ral, min(reference_day.series_c), max(reference_day.series_c))
    )
    assert reference_day.crosses(rel), (
        "day never crosses REL %.1f; range was %.2f..%.2f"
        % (rel, min(reference_day.series_c), max(reference_day.series_c))
    )


# ---------------------------------------------------------------------------
# Guards that stop the exit criteria from passing for the wrong reason
# ---------------------------------------------------------------------------


def _worst_reference_error(reference_inputs, speed):
    grid, env = reference_inputs
    case = reference.M1_REFERENCE
    day = wbgt.build_wbgt_day(
        site_id=case.site_id,
        grid=grid,
        env=env,
        site_longitude=case.longitude,
        site_latitude=case.latitude,
        wind_speed_m_s=speed,
    )
    return max(
        abs(day.at(hour).wbgt_c - target)
        for hour, target in C.WBGT_REFERENCE_HOURS_C.items()
    )


def test_exit_holds_across_the_whole_reproducing_wind_band(reference_inputs):
    """Wind is the one input with no source at all (constants.py 5d).

    If the reference only reproduced at the assumed 3 m/s, the pass would be an
    artifact of the guess rather than evidence the physics is right. It holds
    across 1.5-10 m/s, which is most of the plausible range and contains the
    default with room on both sides.
    """
    lo, hi = C.WIND_BAND_REPRODUCING_REFERENCE_M_S
    assert lo < C.DEFAULT_WIND_SPEED_M_S < hi
    for speed in (lo, 2.0, C.DEFAULT_WIND_SPEED_M_S, 5.0, hi):
        worst = _worst_reference_error(reference_inputs, speed)
        assert worst <= C.WBGT_REFERENCE_TOLERANCE_C, (
            "at %.1f m/s the worst reference error was %+.3f degC" % (speed, worst)
        )


def test_near_calm_over_reads_and_that_limitation_stays_pinned(reference_inputs):
    """Below 1.5 m/s the modelled globe over-heats and 14:00 leaves the gate.

    Pinned deliberately. The reproducing band in constants.py 5d is narrower
    than the plausible wind band, and a test that quietly asserted only the
    passing range would hide exactly the caveat the writeup has to state.
    """
    lo, _hi = C.WIND_BAND_REPRODUCING_REFERENCE_M_S
    below = _worst_reference_error(reference_inputs, C.MIN_AIR_SPEED_M_S)
    assert below > C.WBGT_REFERENCE_TOLERANCE_C, (
        "near-calm no longer over-reads; re-measure the band in constants.py 5d"
    )
    # ...and the error must shrink monotonically as the wind picks up, so the
    # failure is a known bias rather than instability in the solve.
    errors = [_worst_reference_error(reference_inputs, v) for v in (0.5, 1.0, lo)]
    assert errors == sorted(errors, reverse=True), errors


def test_reconstruction_agrees_with_an_independent_snapshot(reference_day):
    """The 14:00 dry bulb is fitted to a filter_type=3 daily min/mean/max.

    The filter_type=1 snapshot is a separate call reading a different axis, so
    agreement is evidence rather than a tautology. FORTYGUARD_API_CONTRACT.md
    section 4 explains why the two are easy to confuse.
    """
    check = reference.snapshot_cross_check(reference_day)
    assert abs(check["residual_c"]) < 1.0, check


def test_reference_day_is_not_accidentally_flat(reference_day):
    """A flat day would satisfy neither crossing test by accident."""
    assert max(reference_day.series_c) - min(reference_day.series_c) > 5.0
    assert reference_day.peak.hour in range(11, 17), reference_day.peak.hour
    assert reference_day.trough.hour in range(3, 8), reference_day.trough.hour


def test_wbgt_stays_below_dry_bulb_at_the_peak(reference_day):
    """Sanity: in a desert, WBGT sits far below air temperature.

    Phoenix at 22% RH should show a WBGT roughly 9 degC under dry bulb at the
    peak. If this ever inverts, the wet bulb and dry bulb terms have been
    swapped.
    """
    peak = reference_day.peak
    assert peak.wbgt_c < peak.dry_bulb_c
    assert 5.0 < peak.dry_bulb_c - peak.wbgt_c < 15.0


def test_every_hour_is_inside_the_sanity_band(reference_day):
    for hour in reference_day.hours:
        assert C.WBGT_PLAUSIBLE_MIN <= hour.wbgt_c <= C.WBGT_PLAUSIBLE_MAX


# ---------------------------------------------------------------------------
# The "work only from fixtures" constraint, enforced rather than trusted
# ---------------------------------------------------------------------------


NETWORK_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+(requests|httpx|urllib|urllib3|http|socket|aiohttp)\b",
    re.MULTILINE,
)


PIPELINE_MODULES = (
    "wbgt.py", "reference.py", "constants.py", "errors.py",
    os.path.join("physics", "solar.py"),
    os.path.join("physics", "globe.py"),
    os.path.join("physics", "diurnal.py"),
    os.path.join("physics", "psychrometrics.py"),
    os.path.join("physics", "natural_wet_bulb.py"),
    os.path.join("sources", "fixtures.py"),
    os.path.join("sources", "fortyguard.py"),
    os.path.join("sources", "openmeteo.py"),
    os.path.join("sources", "cache.py"),
)


def test_no_pipeline_module_can_open_a_socket():
    """SPEC.md hard constraint 6: the demo must run with zero live API calls.

    M0 added a client, so the package as a whole is no longer free of
    networking — it is confined to `sources/transport.py`, and
    `tests/test_m0_client.py::test_networking_is_quarantined_to_exactly_one_module`
    is what enforces that boundary.

    This test makes the narrower claim that still matters for the demo: every
    module the WBGT pipeline actually runs through is offline by construction.
    Grepping imports is cruder than mocking a transport, but it cannot be
    bypassed by a code path the tests happen not to exercise.
    """
    package = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "src", "acclimate"))
    offenders = []
    for relative in PIPELINE_MODULES:
        path = os.path.join(package, relative)
        assert os.path.isfile(path), "pipeline module went missing: %s" % relative
        with open(path, "r", encoding="utf-8") as fh:
            if NETWORK_IMPORTS.search(fh.read()):
                offenders.append(relative)
    assert not offenders, "networking imported by pipeline modules: %s" % offenders


def test_offline_run_tags_every_assumption(reference_inputs):
    """An assumed input must never be indistinguishable from a retrieved one.

    Forced onto the offline path explicitly: an Open-Meteo fixture now exists,
    so the default run no longer assumes wind. The offline path still has to be
    honest about itself, because M3 will backfill site-days that have no
    Open-Meteo coverage.
    """
    grid, env = reference_inputs
    case = reference.M1_REFERENCE
    day = wbgt.build_wbgt_day(
        site_id=case.site_id,
        grid=grid,
        env=env,
        site_longitude=case.longitude,
        site_latitude=case.latitude,
        use=wbgt.SourceSelection.none(),
    )
    provenance = day.provenance
    assert not provenance.fully_retrieved
    assert "wind" in provenance.assumed_inputs
    assert "ASSUMED" in provenance.wind
    assert "%.1f" % C.DEFAULT_WIND_SPEED_M_S in provenance.wind
    assert all(value for _label, value in provenance.as_rows())


def test_default_run_now_uses_measured_wind(reference_day):
    """The Open-Meteo fixture landed 2026-08-24; wind is no longer assumed."""
    provenance = reference_day.provenance
    assert "wind" not in provenance.assumed_inputs
    assert "ASSUMED" not in provenance.wind
    assert "openmeteo.wind_speed_10m" in provenance.wind
    # Measured wind varies across the day; an assumed constant would not.
    speeds = {h.wind_speed_m_s for h in reference_day.hours}
    assert len(speeds) > 5


def test_measured_wind_did_not_rescue_a_broken_model(reference_inputs):
    """The offline assumption and the measurement must agree closely.

    If swapping an assumed 3.0 m/s for the real series had moved 14:00 by more
    than a few tenths, the earlier offline result would have been luck. It moves
    by under 0.2 degC, so the assumption was sound and the physics is carrying
    the result.
    """
    grid, env = reference_inputs
    case = reference.M1_REFERENCE
    common = dict(
        site_id=case.site_id, grid=grid, env=env,
        site_longitude=case.longitude, site_latitude=case.latitude,
    )
    om = openmeteo.load_day(case.latitude, case.longitude, case.date)
    assumed = wbgt.build_wbgt_day(use=wbgt.SourceSelection.none(), **common)
    measured = wbgt.build_wbgt_day(
        open_meteo=om, use=wbgt.SourceSelection.wind_only(), **common
    )
    for hour in C.WBGT_REFERENCE_HOURS_C:
        assert abs(measured.at(hour).wbgt_c - assumed.at(hour).wbgt_c) < 0.2


def test_amplitude_comparison_is_now_independent_and_recorded(reference_day):
    """CLAUDE.md: M1 must compare FortyGuard's amplitude against Open-Meteo's.

    Was blocked with no fixture; now answered. FortyGuard's 2024 archive cell
    reads about 94% of Open-Meteo's amplitude — mild compression, far milder
    than the ~40% narrowing fixtures/MANIFEST.md records for 2026 dates.
    """
    check = reference_day.amplitude_check
    assert check.is_independent
    assert check.reference_amplitude_c is not None
    assert check.discrepancy_c is not None
    assert check.fortyguard_amplitude_c == pytest.approx(11.133, abs=0.01)
    assert check.reference_amplitude_c == pytest.approx(11.800, abs=0.01)
    # FortyGuard reads LOW, which under-estimates stimulus — a safe direction.
    assert check.discrepancy_c < 0.0
    assert 0.90 < check.ratio < 1.0


def test_missing_open_meteo_still_reports_the_gap(reference_inputs, tmp_path):
    """The gap-reporting path must survive the fixture existing."""
    grid, env = reference_inputs
    case = reference.M1_REFERENCE
    day = wbgt.build_wbgt_day(
        site_id=case.site_id, grid=grid, env=env,
        site_longitude=case.longitude, site_latitude=case.latitude,
        use=wbgt.SourceSelection.none(),
    )
    check = day.amplitude_check
    assert check.reference_amplitude_c is None
    assert not check.is_independent
    assert "open-meteo" in check.note.lower()


def test_open_meteo_shape_reduces_the_overnight_humidity_artifact(reference_inputs):
    """FortyGuard apparent temperature carries humidity, so it puts a spurious
    warm bump on the overnight cooling limb. Real dry bulb falls monotonically.
    Open-Meteo temperature_2m should measurably reduce it."""
    grid, env = reference_inputs
    case = reference.M1_REFERENCE
    common = dict(
        site_id=case.site_id, grid=grid, env=env,
        site_longitude=case.longitude, site_latitude=case.latitude,
    )
    om = openmeteo.load_day(case.latitude, case.longitude, case.date)
    offline = wbgt.build_wbgt_day(use=wbgt.SourceSelection.none(), **common)
    online = wbgt.build_wbgt_day(open_meteo=om, use=wbgt.SourceSelection(), **common)

    def reversals(day):
        return diurnal.night_limb_reversals(
            day.reconstruction.dry_bulb_c,
            day.solar_day.sunset_local,
            day.solar_day.sunrise_local,
        )

    off_hours, off_warm = reversals(offline)
    on_hours, on_warm = reversals(online)
    assert on_warm < off_warm
    assert on_hours <= off_hours
