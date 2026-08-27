"""Unit tests for the physics layer.

Each of these can be checked against a textbook or an almanac without a network,
which is the point: if the WBGT pipeline is wrong, the bug is findable offline.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest

from sunup import constants as C
from sunup.errors import ImplausibleValue
from sunup.physics import diurnal, globe, solar
from sunup.physics import psychrometrics as psy

PHOENIX_LAT = 33.4484
PHOENIX_LON = -112.0740
PHOENIX_TZ = -7.0  # Arizona never observes DST
JULY_15 = dt.date(2024, 7, 15)


# ---------------------------------------------------------------------------
# psychrometrics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "t_c,expected_kpa",
    [(0.0, 0.6113), (20.0, 2.3388), (30.0, 4.2455), (40.0, 7.3814)],
)
def test_saturation_vapour_pressure_matches_steam_tables(t_c, expected_kpa):
    """Magnus is fitted for roughly 0-50 degC; 1% is the honest tolerance."""
    got = psy.saturation_vapour_pressure_kpa(t_c)
    assert got == pytest.approx(expected_kpa, rel=0.01)


def test_vapour_pressure_clamps_impossible_humidity():
    assert psy.vapour_pressure_kpa(25.0, 0.0) == 0.0
    saturated = psy.saturation_vapour_pressure_kpa(25.0)
    assert psy.vapour_pressure_kpa(25.0, 100.0) == pytest.approx(saturated)
    assert psy.vapour_pressure_kpa(25.0, 130.0) == pytest.approx(saturated)


def test_station_pressure_falls_with_elevation():
    assert psy.station_pressure_pa(0.0) == pytest.approx(C.ISA_SEA_LEVEL_PRESSURE_PA)
    phoenix = psy.station_pressure_pa(333.0)
    assert 96000.0 < phoenix < 98500.0
    assert phoenix < psy.station_pressure_pa(0.0)


def test_sky_emissivity_reaches_one_under_overcast():
    clear = psy.sky_emissivity(30.0, 40.0, cloud_fraction=0.0)
    overcast = psy.sky_emissivity(30.0, 40.0, cloud_fraction=1.0)
    assert 0.6 < clear < 0.95, clear
    assert overcast == pytest.approx(1.0)
    half = psy.sky_emissivity(30.0, 40.0, cloud_fraction=0.5)
    assert clear < half < overcast


def test_sky_emissivity_rises_with_humidity():
    dry = psy.sky_emissivity(30.0, 15.0, 0.0)
    humid = psy.sky_emissivity(30.0, 70.0, 0.0)
    assert humid > dry


def test_log_wind_profile_slows_the_wind_at_globe_height():
    at_globe = psy.wind_at_height(10.0)
    assert 5.0 < at_globe < 8.0, at_globe
    expected = 10.0 * math.log(2.0 / 0.1) / math.log(10.0 / 0.1)
    assert at_globe == pytest.approx(expected)
    assert psy.wind_at_height(0.0) == 0.0


# ---------------------------------------------------------------------------
# solar
# ---------------------------------------------------------------------------


def test_phoenix_sunrise_and_sunset_are_almanac_plausible():
    """Geometric sunrise, so no refraction or solar-radius correction.

    The almanac day is a few minutes longer than this at both ends; asserting to
    the minute would be asserting something the model does not claim.
    """
    rise, set_ = solar.sunrise_sunset_local(JULY_15, PHOENIX_LAT, PHOENIX_LON, PHOENIX_TZ)
    assert 5.3 < rise < 5.8, rise
    assert 19.3 < set_ < 19.8, set_
    solar_noon = 0.5 * (rise + set_)
    # Phoenix sits 7 degrees west of the 105 W meridian, so solar noon is late.
    assert 12.4 < solar_noon < 12.7, solar_noon
    assert 13.8 < set_ - rise < 14.3


def test_solar_declination_follows_the_seasons():
    def decl(date):
        gamma = solar._fractional_year_rad(date.timetuple().tm_yday, 12.0)
        return math.degrees(solar.solar_declination_rad(gamma))

    assert decl(dt.date(2024, 6, 21)) == pytest.approx(23.44, abs=0.4)
    assert decl(dt.date(2024, 12, 21)) == pytest.approx(-23.44, abs=0.4)
    assert abs(decl(dt.date(2024, 3, 20))) < 1.0


def test_equation_of_time_stays_in_its_known_envelope():
    for day in range(1, 366):
        gamma = solar._fractional_year_rad(day, 12.0)
        assert -17.0 < solar.equation_of_time_min(gamma) < 17.0


def test_sun_is_below_the_horizon_at_midnight():
    position = solar.solar_position(JULY_15, 0.0, PHOENIX_LAT, PHOENIX_LON, PHOENIX_TZ)
    assert position.elevation_deg < 0.0
    assert position.cos_zenith == 0.0
    assert not position.is_daylight


def test_clear_sky_ghi_is_zero_at_night_and_rises_with_the_sun():
    assert solar.clear_sky_ghi_w_m2(0.0) == 0.0
    assert solar.clear_sky_ghi_w_m2(-0.2) == 0.0
    values = [solar.clear_sky_ghi_w_m2(c) for c in (0.2, 0.5, 0.8, 1.0)]
    assert values == sorted(values)
    assert 950.0 < values[-1] < 1100.0


def test_anchoring_reproduces_the_fortyguard_daily_mean_exactly():
    """The one place FortyGuard sets the LEVEL of the solar curve."""
    anchor = 576.92
    day = solar.solar_day(
        JULY_15, PHOENIX_LAT, PHOENIX_LON, PHOENIX_TZ, anchor_daily_ghi_w_m2=anchor
    )
    daylight = [
        g for g, p in zip(day.ghi_w_m2, day.positions) if p.is_daylight
    ]
    assert sum(daylight) / len(daylight) == pytest.approx(anchor, rel=1e-9)


def test_the_fortyguard_solar_anchor_is_a_daylight_mean_not_a_24h_mean():
    """Established from the committed fixture, not from the endpoint docs.

    /v1/env_params does not say which window its clear-sky mean averages over.
    The modelled 24-hour mean is far below the reported 576.92 while the
    daylight-hours mean is close to it, so it is a daylight mean.
    """
    day = solar.solar_day(JULY_15, PHOENIX_LAT, PHOENIX_LON, PHOENIX_TZ)
    assert day.model_24h_mean_ghi < 400.0
    assert 580.0 < day.model_daylight_mean_ghi < 650.0


def test_irradiance_closure_holds_every_hour():
    """GHI = DNI * cos(z) + DHI, clear and cloudy alike."""
    cloud = tuple((h % 5) / 4.0 for h in range(24))
    for clouds in (None, cloud):
        day = solar.solar_day(
            JULY_15,
            PHOENIX_LAT,
            PHOENIX_LON,
            PHOENIX_TZ,
            anchor_daily_ghi_w_m2=576.92,
            cloud_fraction=clouds,
        )
        for h in range(24):
            reconstructed = (
                day.dni_w_m2[h] * day.positions[h].cos_zenith + day.dhi_w_m2[h]
            )
            assert reconstructed == pytest.approx(day.ghi_w_m2[h], abs=1e-6)


def test_beam_never_exceeds_the_solar_constant():
    """A large anchor meeting a low sun could otherwise return an impossible DNI."""
    day = solar.solar_day(
        JULY_15, PHOENIX_LAT, PHOENIX_LON, PHOENIX_TZ, anchor_daily_ghi_w_m2=1500.0
    )
    assert max(day.dni_w_m2) <= C.SOLAR_CONSTANT_W_M2
    assert min(day.dhi_w_m2) >= 0.0
    for h in range(24):
        closure = day.dni_w_m2[h] * day.positions[h].cos_zenith + day.dhi_w_m2[h]
        assert closure == pytest.approx(day.ghi_w_m2[h], abs=1e-6)


def test_cloud_attenuation_endpoints():
    assert solar.cloud_attenuation_factor(0.0) == pytest.approx(1.0)
    assert solar.cloud_attenuation_factor(1.0) == pytest.approx(
        1.0 - C.KASTEN_CZEPLAK_A
    )
    assert solar.cloud_attenuation_factor(0.5) < 1.0


def test_overcast_kills_the_beam_entirely():
    day = solar.solar_day(
        JULY_15,
        PHOENIX_LAT,
        PHOENIX_LON,
        PHOENIX_TZ,
        anchor_daily_ghi_w_m2=576.92,
        cloud_fraction=tuple(1.0 for _ in range(24)),
    )
    assert max(day.dni_w_m2) == pytest.approx(0.0)
    assert max(day.dhi_w_m2) > 0.0


def test_cloud_series_must_have_24_values():
    with pytest.raises(ValueError):
        solar.solar_day(
            JULY_15, PHOENIX_LAT, PHOENIX_LON, PHOENIX_TZ, cloud_fraction=(0.0, 1.0)
        )


# ---------------------------------------------------------------------------
# globe
# ---------------------------------------------------------------------------


def test_sphere_shortwave_is_geometry_not_a_fit():
    assert globe.sphere_mean_shortwave_w_m2(400.0, 0.0, 0.0, 0.0) == pytest.approx(100.0)
    assert globe.sphere_mean_shortwave_w_m2(0.0, 200.0, 0.0, 0.0) == pytest.approx(100.0)
    assert globe.sphere_mean_shortwave_w_m2(0.0, 0.0, 500.0, 0.2) == pytest.approx(50.0)
    assert globe.sphere_mean_shortwave_w_m2(-5.0, -5.0, -5.0, 0.2) == 0.0


def test_globe_sits_at_air_temperature_under_a_black_sky_with_no_sun():
    """Overcast night: sky emissivity is 1 and the ground is at air temperature,
    so the net longwave vanishes exactly and the globe has nothing to do but
    match the air.

    This is an identity, not an approximation, it holds only because the ground
    REFLECTS the sky's downwelling longwave as well as emitting its own. It is
    the test that caught that term missing.
    """
    result = globe.globe_temperature(
        air_temperature_c=25.0,
        relative_humidity_pct=60.0,
        air_speed_m_s=2.0,
        dni_w_m2=0.0,
        dhi_w_m2=0.0,
        ghi_w_m2=0.0,
        cloud_fraction=1.0,
        elevation_m=333.0,
    )
    assert result.globe_temperature_c == pytest.approx(25.0, abs=1e-4)


def test_globe_cools_below_air_under_a_clear_night_sky():
    result = globe.globe_temperature(
        air_temperature_c=25.0,
        relative_humidity_pct=20.0,
        air_speed_m_s=2.0,
        dni_w_m2=0.0,
        dhi_w_m2=0.0,
        ghi_w_m2=0.0,
        cloud_fraction=0.0,
        elevation_m=333.0,
    )
    assert result.excess_over_air_c < -0.5


def test_globe_runs_hot_in_sun_and_cools_with_wind():
    def run(speed):
        return globe.globe_temperature(
            air_temperature_c=40.0,
            relative_humidity_pct=20.0,
            air_speed_m_s=speed,
            dni_w_m2=900.0,
            dhi_w_m2=90.0,
            ghi_w_m2=900.0,
            cloud_fraction=0.0,
            elevation_m=333.0,
        ).excess_over_air_c

    calm, breezy, windy = run(1.0), run(3.0), run(8.0)
    assert calm > breezy > windy > 0.0
    # A black globe in full desert sun sits well above air temperature.
    assert 5.0 < breezy < 25.0


def test_globe_excess_rises_monotonically_with_irradiance():
    previous = -99.0
    for ghi in (0.0, 200.0, 500.0, 800.0, 1000.0):
        excess = globe.globe_temperature(
            air_temperature_c=35.0,
            relative_humidity_pct=25.0,
            air_speed_m_s=3.0,
            dni_w_m2=ghi,
            dhi_w_m2=0.1 * ghi,
            ghi_w_m2=ghi,
            cloud_fraction=0.0,
            elevation_m=333.0,
        ).excess_over_air_c
        assert excess > previous
        previous = excess


def test_air_speed_is_floored_so_the_correlation_cannot_blow_up():
    still = globe.convective_coefficient_w_m2_k(30.0, 0.0, 97000.0)
    floored = globe.convective_coefficient_w_m2_k(30.0, C.MIN_AIR_SPEED_M_S, 97000.0)
    assert still == pytest.approx(floored)
    assert still > 5.0


# ---------------------------------------------------------------------------
# diurnal reconstruction
# ---------------------------------------------------------------------------


def _bell_shape():
    return tuple(math.sin(math.pi * h / 23.0) for h in range(24))


def test_reconstruction_reproduces_all_three_fortyguard_numbers():
    result = diurnal.reconstruct_dry_bulb(
        shape=_bell_shape(),
        daily_min_c=29.5985,
        daily_mean_c=36.1482,
        daily_max_c=40.4686,
        shape_source="test",
    )
    assert result.achieved_min_c == pytest.approx(29.5985)
    assert result.achieved_max_c == pytest.approx(40.4686)
    assert result.achieved_mean_c == pytest.approx(36.1482, abs=1e-4)
    assert result.warp_converged


def test_warp_is_the_identity_when_the_shape_already_has_the_right_mean():
    shape = _bell_shape()
    normalised = diurnal.normalise_shape(shape)
    natural_mean = sum(normalised) / len(normalised)
    result = diurnal.reconstruct_dry_bulb(
        shape=shape,
        daily_min_c=20.0,
        daily_mean_c=20.0 + natural_mean * 10.0,
        daily_max_c=30.0,
        shape_source="test",
    )
    assert result.warp_gamma == pytest.approx(1.0, abs=1e-3)


def test_warp_preserves_the_ordering_of_the_shape():
    """The warp must be monotone, or it would reorder the day.

    Asserted pairwise rather than by sorting: the bell shape has exact ties
    (sin is symmetric), and sorting would test float tie-breaking instead.
    """
    shape = _bell_shape()
    result = diurnal.reconstruct_dry_bulb(
        shape=shape,
        daily_min_c=20.0,
        daily_mean_c=27.0,
        daily_max_c=30.0,
        shape_source="test",
    )
    out = result.dry_bulb_c
    for i in range(24):
        for j in range(24):
            if shape[i] < shape[j]:
                assert out[i] <= out[j], (i, j, shape[i], shape[j])
            elif shape[i] == shape[j]:
                assert out[i] == pytest.approx(out[j])


def test_reconstruction_rejects_unordered_daily_stats():
    with pytest.raises(ImplausibleValue):
        diurnal.reconstruct_dry_bulb(
            shape=_bell_shape(),
            daily_min_c=30.0,
            daily_mean_c=25.0,
            daily_max_c=40.0,
            shape_source="test",
        )


def test_reconstruction_rejects_a_shape_that_is_not_24_hours():
    with pytest.raises(ValueError):
        diurnal.reconstruct_dry_bulb(
            shape=(1.0, 2.0), daily_min_c=1.0, daily_mean_c=1.5,
            daily_max_c=2.0, shape_source="test",
        )


def test_unreachable_mean_is_flagged_rather_than_faked():
    """A mean pinned right against max cannot be reached by a monotone warp."""
    result = diurnal.reconstruct_dry_bulb(
        shape=_bell_shape(),
        daily_min_c=20.0,
        daily_mean_c=29.999,
        daily_max_c=30.0,
        shape_source="test",
    )
    assert not result.warp_converged
    assert result.warp_gamma in C.DIURNAL_WARP_GAMMA_BOUNDS
    assert abs(result.mean_residual_c) > 0.0


def test_night_limb_reversals_are_zero_on_a_clean_cooling_curve():
    # Falls from an 18:00 peak to a 06:00 minimum, then rises again.
    curve = []
    for h in range(24):
        if h <= 6:
            curve.append(30.0 - h)
        elif h <= 18:
            curve.append(24.0 + (h - 6))
        else:
            curve.append(36.0 - (h - 18))
    reversals, warming = diurnal.night_limb_reversals(curve, sunset_hour=19, sunrise_hour=5)
    assert reversals == 0
    assert warming == pytest.approx(0.0)


def test_night_limb_reversals_catch_a_humidity_bump():
    curve = [30.0 - h * 0.5 for h in range(24)]
    curve[2] += 3.0  # a 02:00 bump of the kind apparent temperature introduces
    reversals, warming = diurnal.night_limb_reversals(curve, sunset_hour=19, sunrise_hour=5)
    assert reversals >= 1
    assert warming > 2.0


def test_amplitude_comparison_reports_a_missing_reference():
    check = diurnal.compare_amplitude(29.6, 40.5, None, "none", False)
    assert check.discrepancy_c is None
    assert check.ratio is None
    assert "Open-Meteo" in check.note


def test_amplitude_comparison_measures_the_smoothing_bias():
    reference_curve = tuple(20.0 + 7.0 * math.sin(math.pi * h / 23.0) for h in range(24))
    check = diurnal.compare_amplitude(
        30.0, 34.0, reference_curve, "openmeteo.temperature_2m", True
    )
    assert check.fortyguard_amplitude_c == pytest.approx(4.0)
    assert check.reference_amplitude_c == pytest.approx(7.0, abs=0.1)
    assert check.discrepancy_c < 0.0
    assert check.is_independent
