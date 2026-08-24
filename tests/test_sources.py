"""Tests for the fixture-reading layer.

These double as regression tests on FORTYGUARD_API_CONTRACT.md: each one pins a
claim that document makes, so a fixture refresh that changes the API's behaviour
fails here rather than silently changing the model's answers.
"""

from __future__ import annotations

import datetime as dt

import pytest

from acclimate import constants as C
from acclimate import wbgt
from acclimate.errors import FixtureNotFound, ImplausibleValue, OfflineDataUnavailable
from acclimate.reference import M1_REFERENCE
from acclimate.sources import openmeteo
from acclimate.sources.fixtures import FixtureStore, unwrap_result
from acclimate.sources.fortyguard import parse_env_params, parse_temperature_grid


# ---------------------------------------------------------------------------
# envelopes
# ---------------------------------------------------------------------------


def test_unwrap_handles_all_three_envelope_shapes():
    """FORTYGUARD_API_CONTRACT.md section 1: the shape depends on access path."""
    body = {"map_data": {"features": []}}
    assert unwrap_result({"activity_id": "x", "result": body}) is body
    assert unwrap_result({"data": {"activity_id": "x", "result": body}}) is body
    assert unwrap_result(body) is body


def test_unwrap_refuses_an_unrecognised_payload():
    with pytest.raises(KeyError):
        unwrap_result({"something": "else"})


def test_missing_fixture_names_itself(store):
    with pytest.raises(FixtureNotFound) as excinfo:
        store.load("heatmap/does_not_exist.json")
    assert "does_not_exist.json" in str(excinfo.value)


# ---------------------------------------------------------------------------
# /v1/heatmap
# ---------------------------------------------------------------------------


def test_filter3_carries_per_cell_temporal_range(store):
    """The claim fixtures/MANIFEST.md calls the CONTROL for 2024-07-15."""
    grid = parse_temperature_grid(store.load(M1_REFERENCE.heatmap_filter3_fixture))
    assert len(grid.cells) == 81
    tile0 = grid.cells[0]
    assert tile0.mean_c == pytest.approx(36.1482)
    assert tile0.min_c == pytest.approx(29.5985)
    assert tile0.max_c == pytest.approx(40.4686)
    assert max(c.diurnal_range_c for c in grid.cells) == pytest.approx(11.3837, abs=1e-3)


def test_temporal_and_spatial_axes_are_not_confused(store):
    """The trap in FORTYGUARD_API_CONTRACT.md section 4, pinned.

    Spatial spread across the parcel is 0.36 degC; the temporal range within a
    single cell is 11 degC. Reading one where the other is meant is a 30x error.
    """
    grid = parse_temperature_grid(store.load(M1_REFERENCE.heatmap_filter3_fixture))
    assert grid.spatial_spread_c == pytest.approx(0.3574, abs=1e-3)
    assert grid.cells[0].diurnal_range_c > 10.0
    assert grid.spatial_spread_c < 0.5


def test_filter1_snapshot_has_no_diurnal_range(store):
    """Section 4: with one timestep, temporal min == avg == max."""
    grid = parse_temperature_grid(store.load(M1_REFERENCE.heatmap_snapshot_fixture))
    assert all(cell.diurnal_range_c == 0.0 for cell in grid.cells)
    assert grid.spatial_mean_c == pytest.approx(39.7142, abs=1e-3)


def test_pipeline_refuses_a_filter1_grid(store):
    """A snapshot grid would silently reconstruct a flat day."""
    grid = parse_temperature_grid(store.load(M1_REFERENCE.heatmap_snapshot_fixture))
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    with pytest.raises(ImplausibleValue) as excinfo:
        wbgt.build_wbgt_day(
            site_id="x",
            grid=grid,
            env=env,
            site_longitude=M1_REFERENCE.longitude,
            site_latitude=M1_REFERENCE.latitude,
        )
    assert "filter_type=3" in str(excinfo.value)


def test_analysis_heatmap_properties_are_rejected_with_an_explanation():
    """Section 5: an exceedance grid uses properties.value, not
    average_temperature. Code that reads the wrong one finds nothing."""
    payload = {
        "result": {
            "map_data": {
                "features": [
                    {
                        "properties": {"tile_id": 0, "value": 6.03},
                        "geometry": {"type": "Polygon", "coordinates": [[]]},
                    }
                ]
            }
        }
    }
    with pytest.raises(ValueError) as excinfo:
        parse_temperature_grid(payload)
    assert "properties.value" in str(excinfo.value)


def test_site_lookup_picks_the_containing_cell(store):
    grid = parse_temperature_grid(store.load(M1_REFERENCE.heatmap_filter3_fixture))
    cell = grid.cell_at(M1_REFERENCE.longitude, M1_REFERENCE.latitude)
    assert cell.contains(M1_REFERENCE.longitude, M1_REFERENCE.latitude)
    # Deterministic: the same point must always resolve to the same cell.
    assert grid.cell_at(M1_REFERENCE.longitude, M1_REFERENCE.latitude) is cell


def test_site_lookup_falls_back_to_the_nearest_cell_outside_the_aoi(store):
    grid = parse_temperature_grid(store.load(M1_REFERENCE.heatmap_filter3_fixture))
    far = grid.cell_at(-115.0, 36.0)
    assert far in grid.cells
    assert not far.contains(-115.0, 36.0)


# ---------------------------------------------------------------------------
# /v1/env_params
# ---------------------------------------------------------------------------


def test_env_params_returns_the_values_constants_section_5_quotes(store):
    """constants.py section 5 records T_wb 23.7 at 14:00, 22.0 at 06:00,
    RH 22.9% at 14:00. If a fixture refresh moves these, the WBGT reference
    moves with them and the exit test is no longer meaningful."""
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    wet_bulb = env.hourly("wet_bulb_temperature_celsius")
    assert wet_bulb[14] == pytest.approx(23.7)
    assert wet_bulb[6] == pytest.approx(22.0)
    assert env.hourly("relative_humidity_percent")[14] == pytest.approx(22.9)
    assert env.date == dt.date(2024, 7, 15)
    assert env.utc_offset_hours == -7.0
    assert env.elevation_m == pytest.approx(333.0)


def test_temperature_field_is_the_anchor_we_supplied_not_an_output(store):
    """Section 6: `temperature` echoes the input anchor. Reading it as a
    measurement would put 39.5 degC on every hour of the day."""
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    assert env.temperature_anchor_c == pytest.approx(39.5)


def test_solar_irradiance_is_one_daily_mean_not_a_24_element_array(store):
    """Section 6, trap 1."""
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    assert env.clear_sky_ghi_w_m2 == pytest.approx(576.92)
    assert env.clear_sky_dni_w_m2 == pytest.approx(691.43)
    assert env.clear_sky_dhi_w_m2 == pytest.approx(85.61)
    assert "solar_irradiance" not in env.parameters


def test_all_null_parameters_raise_rather_than_read_as_zero(store):
    """Section 6: methane_ppb and co2_ppm came back all-null."""
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    for name in ("methane_ppb", "co2_ppm"):
        assert name in env.parameters
        with pytest.raises(ImplausibleValue):
            env.hourly(name)


def test_unknown_parameter_lists_what_is_available(store):
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    with pytest.raises(KeyError) as excinfo:
        env.hourly("wind_speed_10m")
    assert "wet_bulb_temperature_celsius" in str(excinfo.value)


def test_cloud_cover_is_percent_despite_the_octas_field_name(store):
    """Undocumented behaviour, established from the committed payload: the field
    is named cloud_cover_octas but runs 0-100."""
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    raw = env.hourly("cloud_cover_octas")
    assert max(raw) == 100.0
    assert not env.cloud_scale_ambiguous
    fractions = env.cloud_fraction()
    assert len(fractions) == 24
    assert max(fractions) == pytest.approx(1.0)
    assert min(fractions) >= 0.0


def test_m1_depends_on_parameters_a_three_param_request_would_not_return(store):
    """fixtures/MANIFEST.md records this call as analysis=[wet_bulb,
    solar_irradiance, relative_humidity], yet the payload carries 15 parameters.

    M1 needs apparent_temperature_celsius and cloud_cover_octas as well, so the
    backfill in M3 must either request them explicitly or confirm that
    `analysis` is not applied. Pinned here so the dependency is visible.
    """
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    for required in (
        "wet_bulb_temperature_celsius",
        "relative_humidity_percent",
        "apparent_temperature_celsius",
        "cloud_cover_octas",
    ):
        assert required in env.parameters, required


def test_heat_index_is_the_artifact_the_contract_warns_about(store):
    """Section 6, trap 2: heat_index_celsius peaks in the small hours because
    the endpoint holds the temperature anchor fixed and varies only humidity.
    Pinned so nobody 'fixes' the pipeline by reaching for it."""
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    heat_index = env.hourly("heat_index_celsius")
    assert heat_index[6] > heat_index[16], "the artifact has gone; re-read trap 2"
    apparent = env.hourly("apparent_temperature_celsius")
    assert apparent[16] > apparent[6], "apparent temperature must peak in daylight"


# ---------------------------------------------------------------------------
# Open-Meteo — not cached, and honest about it
# ---------------------------------------------------------------------------


def test_open_meteo_absence_raises_with_the_exact_call_needed(tmp_path):
    """Tested against an EMPTY store — the real fixture now exists."""
    empty = FixtureStore(str(tmp_path))
    with pytest.raises(OfflineDataUnavailable) as excinfo:
        openmeteo.load_day(33.4484, -112.0740, dt.date(2024, 7, 15), empty)
    message = str(excinfo.value)
    assert "archive-api.open-meteo.com" in message
    assert "wind_speed_10m" in message
    assert "2024-07-15" in message


def test_try_load_day_is_none_rather_than_a_guess(tmp_path):
    empty = FixtureStore(str(tmp_path))
    assert openmeteo.try_load_day(33.4484, -112.0740, dt.date(2024, 7, 15), empty) is None


def test_cached_open_meteo_day_is_present_and_in_the_right_units(store):
    """The fixture fetched 2026-08-24. Wind is the trap: Open-Meteo defaults to
    km/h, and 4.32 km/h vs 4.32 m/s would silently over-ventilate the globe."""
    day = openmeteo.load_day(33.4484, -112.0740, dt.date(2024, 7, 15), store)
    assert len(day.temperature_2m_c) == 24
    winds = day.wind_speed_10m_m_s
    # A Phoenix July day in m/s sits in single digits; in km/h it would be ~4x.
    assert 0.5 < min(winds) < 3.0, winds
    assert 3.0 < max(winds) < 15.0, winds
    assert max(day.shortwave_radiation_w_m2) == pytest.approx(933.0)
    assert 0.0 <= min(day.cloud_cover_fraction) <= max(day.cloud_cover_fraction) <= 1.0


def test_fortyguard_cloud_is_byte_identical_to_open_meteo(store):
    """Discovered 2026-08-24, and now recorded in FORTYGUARD_API_CONTRACT.md 6.

    FortyGuard's cloud_cover_octas equals Open-Meteo's cloud_cover PERCENT
    field, value for value. That settles the units question beyond argument and
    indicates env_params is served from the same reanalysis backend. If a
    fixture refresh ever breaks this, the shared-backend claim in the contract
    needs revisiting.
    """
    env = parse_env_params(store.load(M1_REFERENCE.env_params_fixture))
    om = openmeteo.load_day(33.4484, -112.0740, dt.date(2024, 7, 15), store)
    fortyguard = [int(v) for v in env.hourly("cloud_cover_octas")]
    open_meteo = [round(v * 100) for v in om.cloud_cover_fraction]
    assert fortyguard == open_meteo
    assert max(fortyguard) == 100  # impossible on an 0-8 octas scale


def test_fixture_key_is_stable():
    key = openmeteo.fixture_key(33.4484, -112.0740, dt.date(2024, 7, 15))
    assert key == "openmeteo/33.4484_-112.0740_2024-07-15.json"


def test_default_wind_is_inside_the_declared_sensitivity_band():
    low, high = C.WIND_SENSITIVITY_BAND_M_S
    assert low <= C.DEFAULT_WIND_SPEED_M_S <= high
    assert C.MIN_AIR_SPEED_M_S < low
