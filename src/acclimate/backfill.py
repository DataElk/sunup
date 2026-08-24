"""M3 — the 14-day, two-site backfill, read back offline.

`scripts/m3_fetch.py --backfill` does the retrieval; this module reads it back.
Everything goes through the M0 client with an OFFLINE transport, so a site-day
that was never fetched fails loudly instead of silently going to the network
during a demo.

Each site-day is FortyGuard `filter_type=3` tile data (per-cell diurnal
min/mean/max) reconstructed against Open-Meteo hourly shape, solar, wind, cloud,
wet bulb and humidity — the same pipeline M1 validated, on a site chosen by M3's
percentile ranking rather than by hand.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from acclimate import constants as C
from acclimate import siteselection as ss
from acclimate import wbgt
from acclimate.errors import CacheMiss, LiveCallBlocked
from acclimate.sources import openmeteo
from acclimate.sources.cache import DiskCache
from acclimate.sources.client import FortyGuardClient
from acclimate.sources.fixtures import FixtureStore
from acclimate.sources.fortyguard import parse_temperature_grid
from acclimate.sources.transport import OfflineTransport

SELECTION_FILE = "site_selection/phoenix_40c_selection.json"
SITE_NAMES = ("cool_site", "hot_site")


def backfill_dates() -> List[dt.date]:
    start = dt.date.fromisoformat(C.DEMO_BACKFILL_START)
    end = dt.date.fromisoformat(C.DEMO_BACKFILL_END)
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


@dataclass(frozen=True)
class Site:
    name: str
    longitude: float
    latitude: float
    exceedance_hours: float
    distance_to_edge_m: float
    percentile: float

    @property
    def centroid(self) -> Tuple[float, float]:
        return (self.longitude, self.latitude)

    @property
    def hours_per_day_above_threshold(self) -> float:
        return self.exceedance_hours / len(backfill_dates())


def load_sites(store: Optional[FixtureStore] = None) -> Dict[str, Site]:
    store = store or FixtureStore()
    selection = store.load(SELECTION_FILE)
    sites = {}
    for name in SITE_NAMES:
        entry = selection[name]
        lon, lat = entry["centroid_lon_lat"]
        sites[name] = Site(
            name=name, longitude=lon, latitude=lat,
            exceedance_hours=entry["value_hours"],
            distance_to_edge_m=entry["distance_to_edge_m"],
            percentile=entry["percentile"],
        )
    return sites


class BackfillCache:
    """WBGT days for the two selected sites across the 14-day window.

    Built once per (site, date, wet-bulb model) and reused, because the tau
    sweep runs 84 parameter pairs and the WBGT does not depend on tau.
    """

    def __init__(self, store: Optional[FixtureStore] = None) -> None:
        self.store = store or FixtureStore()
        self.sites = load_sites(self.store)
        self.client = FortyGuardClient(
            cache=DiskCache(), transport=OfflineTransport(), refresh=False)
        self._built: Dict[Tuple[str, str, str], wbgt.WBGTDay] = {}

    def available_dates(self, site_name: str) -> List[dt.date]:
        """Dates where BOTH the tile grid and the Open-Meteo day are cached."""
        site = self.sites[site_name]
        aoi = ss.parcel_around(site.centroid)
        found = []
        for date in backfill_dates():
            if not self.store.exists(
                openmeteo.fixture_key(site.latitude, site.longitude, date)
            ):
                continue
            try:
                self.client.create_heatmap(
                    polygon_aoi=aoi, start_date=date.isoformat(),
                    filter_type=3, granularity=100)
            except (CacheMiss, LiveCallBlocked):
                continue
            found.append(date)
        return found

    def get(self, site_name: str, date: dt.date, model: str) -> wbgt.WBGTDay:
        key = (site_name, date.isoformat(), model)
        if key not in self._built:
            site = self.sites[site_name]
            aoi = ss.parcel_around(site.centroid)
            response = self.client.create_heatmap(
                polygon_aoi=aoi, start_date=date.isoformat(),
                filter_type=3, granularity=100)
            grid = parse_temperature_grid(response)
            om = openmeteo.load_day(site.latitude, site.longitude, date, self.store)
            self._built[key] = wbgt.build_wbgt_day(
                site_id=site_name, grid=grid, env=None,
                site_longitude=site.longitude, site_latitude=site.latitude,
                open_meteo=om, natural_wet_bulb_model=model,
            )
        return self._built[key]

    def series(
        self, site_name: str, model: str, dates: Optional[Sequence[dt.date]] = None
    ) -> List[wbgt.WBGTDay]:
        dates = dates if dates is not None else self.available_dates(site_name)
        return [self.get(site_name, d, model) for d in dates]

    def shared_dates(self, model: str) -> List[dt.date]:
        """Dates available at BOTH sites — the only ones a fair comparison can use."""
        cool = set(self.available_dates("cool_site"))
        hot = set(self.available_dates("hot_site"))
        return sorted(cool & hot)
