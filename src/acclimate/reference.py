"""The M1 reference case: downtown Phoenix, 2024-07-15.

constants.py section 5 records what a correct pipeline must produce for this
site-day, from live API values: WBGT about 31 degC at 14:00 and about 24.8 degC
at 06:00, with the day crossing both the NIOSH RAL and REL curves for moderate
work. fixtures/MANIFEST.md names the payloads those numbers came from.

Keeping the wiring here means the exit test and the report agree on which
fixtures constitute the reference, and neither hardcodes a path.

Sites are user input everywhere else (SPEC.md, hard constraint 7). This module
is the one exception, and it exists only to pin a regression.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from acclimate import constants as C
from acclimate import wbgt
from acclimate.sources import openmeteo
from acclimate.sources.fixtures import FixtureStore
from acclimate.sources.fortyguard import (
    EnvParamsDay,
    TemperatureGrid,
    parse_env_params,
    parse_temperature_grid,
)


@dataclass(frozen=True)
class ReferenceCase:
    site_id: str
    date: dt.date
    latitude: float
    longitude: float
    # filter_type=3, carries the per-cell diurnal min/mean/max the
    # reconstruction needs.
    heatmap_filter3_fixture: str
    env_params_fixture: str
    # filter_type=1 at 14:00, an INDEPENDENT snapshot used only to check the
    # reconstruction, never as an input to it.
    heatmap_snapshot_fixture: str
    snapshot_hour: int


M1_REFERENCE = ReferenceCase(
    site_id="phoenix-downtown-parcel",
    date=dt.date.fromisoformat(C.WBGT_REFERENCE_DATE),
    latitude=C.WBGT_REFERENCE_SITE["latitude"],
    longitude=C.WBGT_REFERENCE_SITE["longitude"],
    heatmap_filter3_fixture="heatmap/filter3_properties_2024-07-15.json",
    env_params_fixture="env_params/phoenix_env_params_raw.json",
    heatmap_snapshot_fixture="heatmap/phoenix_heatmap_raw.json",
    snapshot_hour=14,
)


def load_inputs(
    case: ReferenceCase = M1_REFERENCE, store: Optional[FixtureStore] = None
):
    """(grid, env_params) for the reference case, straight off disk."""
    store = store or FixtureStore()
    grid = parse_temperature_grid(store.load(case.heatmap_filter3_fixture))
    env = parse_env_params(store.load(case.env_params_fixture))
    return grid, env


def load_snapshot(
    case: ReferenceCase = M1_REFERENCE, store: Optional[FixtureStore] = None
) -> TemperatureGrid:
    """The filter_type=1 grid, for cross-checking the reconstruction."""
    store = store or FixtureStore()
    return parse_temperature_grid(store.load(case.heatmap_snapshot_fixture))


def build(
    case: ReferenceCase = M1_REFERENCE,
    store: Optional[FixtureStore] = None,
    wind_speed_m_s: Optional[float] = None,
    ground_albedo: float = C.GROUND_ALBEDO,
    use: Optional[wbgt.SourceSelection] = None,
    natural_wet_bulb_model: str = wbgt.NWB_PSYCHROMETRIC,
) -> wbgt.WBGTDay:
    """Run the M1 pipeline on the reference case.

    Uses an Open-Meteo fixture if one has been cached for this site-day, and the
    tagged offline assumptions otherwise. Which of the two happened is readable
    off ``day.provenance.assumed_inputs``.

    ``use`` selects which inputs Open-Meteo supplies, so a single input can be
    swapped in isolation. That is how the M1 report attributes the change to
    measured wind rather than to four changes at once.
    """
    store = store or FixtureStore()
    grid, env = load_inputs(case, store)
    om = openmeteo.try_load_day(case.latitude, case.longitude, case.date, store)
    return wbgt.build_wbgt_day(
        site_id=case.site_id,
        grid=grid,
        env=env,
        site_longitude=case.longitude,
        site_latitude=case.latitude,
        open_meteo=om,
        use=use,
        wind_speed_m_s=wind_speed_m_s,
        ground_albedo=ground_albedo,
        natural_wet_bulb_model=natural_wet_bulb_model,
    )


def snapshot_cross_check(
    day: wbgt.WBGTDay,
    case: ReferenceCase = M1_REFERENCE,
    store: Optional[FixtureStore] = None,
) -> dict:
    """Reconstructed dry bulb at 14:00 vs the independent filter_type=1 snapshot.

    The reconstruction is fitted to a filter_type=3 daily min/mean/max. The
    snapshot is a different call on a different day-part axis, so agreement here
    is real evidence that the shape is landing in the right place, not a
    tautology.
    """
    snapshot = load_snapshot(case, store)
    cell = snapshot.cell_at(case.longitude, case.latitude)
    reconstructed = day.at(case.snapshot_hour).dry_bulb_c
    return {
        "hour": case.snapshot_hour,
        "reconstructed_dry_bulb_c": reconstructed,
        "snapshot_cell_c": cell.mean_c,
        "snapshot_spatial_mean_c": snapshot.spatial_mean_c,
        "residual_c": reconstructed - cell.mean_c,
    }
