"""M3, site selection, with the boundary-artifact mitigation that makes it valid.

FORTYGUARD_API_CONTRACT.md section 5 is blunt about why this module exists. On
the 14-day 40 degC Phoenix run, all five highest cells sat within 460 m of the
west edge and all five lowest within 80 m of the north edge, each a contiguous
scanline at a single latitude. The extremes of an exceedance grid are an
artifact of where the AOI was drawn. Picking a site from `max(value)` is picking
noise and calling it a hot site.

The four-part mitigation, all enforced here:

  1. BUFFER   request an AOI at least AOI_BUFFER_KM larger than the region you
              actually care about, so the artifact ring falls outside it
  2. DISCARD  drop every cell within EDGE_DISCARD_M of the AOI boundary before
              ranking anything
  3. PERCENTILE  rank by 5th/95th percentile, never absolute min/max
  4. CROSS-CHECK  confirm a selected hot cell against satellite segmentation, 
              a genuine hot cell has high impervious share. If land cover does
              not explain the ranking, it is an artifact.

Geometry note: distances use a local equirectangular projection about the AOI
centroid. Over a metro-scale AOI (~25 km) the error against a proper geodesic is
well under a metre, and the alternative is a dependency for no accuracy that
matters at a 500 m threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from sunup import constants as C
from sunup.errors import ImplausibleValue
from sunup.sources.fortyguard import AnalysisCell, AnalysisGrid

LonLat = Tuple[float, float]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def metres_per_degree(latitude_deg: float) -> Tuple[float, float]:
    """(metres per degree of longitude, metres per degree of latitude)."""
    lat_m = math.pi * C.EARTH_MEAN_RADIUS_M / 180.0
    lon_m = lat_m * math.cos(math.radians(latitude_deg))
    return lon_m, lat_m


def ring_of(polygon_geojson: Mapping) -> Tuple[LonLat, ...]:
    """The outer ring of a GeoJSON FeatureCollection / Feature / Polygon."""
    node = polygon_geojson
    if node.get("type") == "FeatureCollection":
        features = node.get("features") or []
        if not features:
            raise ValueError("FeatureCollection has no features")
        node = features[0]
    if node.get("type") == "Feature":
        node = node.get("geometry") or {}
    if node.get("type") != "Polygon":
        raise ValueError("expected a Polygon, got %r" % node.get("type"))
    ring = [(float(p[0]), float(p[1])) for p in node["coordinates"][0]]
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        raise ValueError("polygon ring needs at least 3 distinct vertices")
    return tuple(ring)


def bbox_of(ring: Sequence[LonLat]) -> Tuple[float, float, float, float]:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return min(lons), min(lats), max(lons), max(lats)


def centroid_of(ring: Sequence[LonLat]) -> LonLat:
    return (sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring))


def buffer_polygon(polygon_geojson: Mapping, km: float = C.AOI_BUFFER_KM) -> Dict:
    """Expand an AOI outward by ``km``, as a GeoJSON FeatureCollection.

    Mitigation step 1. The buffer is what pushes the artifact ring outside the
    region you actually intend to select from, you request the larger polygon,
    then discard its edge (step 2), and what survives is the region you wanted.
    """
    if km < 0:
        raise ValueError("buffer must not be negative")
    ring = ring_of(polygon_geojson)
    west, south, east, north = bbox_of(ring)
    lon_m, lat_m = metres_per_degree(0.5 * (south + north))
    dlon = km * 1000.0 / lon_m
    dlat = km * 1000.0 / lat_m
    west, east = west - dlon, east + dlon
    south, north = south - dlat, north + dlat
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"buffer_km": km},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south], [east, south], [east, north],
                    [west, north], [west, south],
                ]],
            },
        }],
    }


def _point_to_segment_m(
    point: LonLat, a: LonLat, b: LonLat, lon_m: float, lat_m: float
) -> float:
    px, py = (point[0] - a[0]) * lon_m, (point[1] - a[1]) * lat_m
    bx, by = (b[0] - a[0]) * lon_m, (b[1] - a[1]) * lat_m
    length_sq = bx * bx + by * by
    if length_sq == 0.0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, (px * bx + py * by) / length_sq))
    return math.hypot(px - t * bx, py - t * by)


def distance_to_boundary_m(point: LonLat, ring: Sequence[LonLat]) -> float:
    """Shortest distance from a point to the polygon's boundary, in metres.

    Unsigned: a point just inside and a point just outside both read small.
    That is what we want, a cell straddling the edge is suspect either way.
    """
    lon_m, lat_m = metres_per_degree(centroid_of(ring)[1])
    return min(
        _point_to_segment_m(point, ring[i], ring[(i + 1) % len(ring)], lon_m, lat_m)
        for i in range(len(ring))
    )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteCandidate:
    cell: AnalysisCell
    distance_to_edge_m: float
    percentile: float

    @property
    def centroid(self) -> LonLat:
        return self.cell.centroid

    @property
    def value_hours(self) -> float:
        return self.cell.value


@dataclass(frozen=True)
class SelectionReport:
    """Everything needed to defend a site choice, not just the choice."""

    total_cells: int
    discarded_edge_cells: int
    surviving_cells: int
    edge_discard_m: float
    percentile_low: float
    percentile_high: float
    value_at_low: float
    value_at_high: float
    cool_site: SiteCandidate
    hot_site: SiteCandidate
    raw_min: float
    raw_max: float

    @property
    def discarded_fraction(self) -> float:
        return self.discarded_edge_cells / self.total_cells if self.total_cells else 0.0

    @property
    def dose_ratio(self) -> float:
        """Hot/cool exposure ratio, AFTER the mitigation.

        Compare against the raw ratio: the difference is how much of the
        headline number was boundary artifact.
        """
        return self.hot_site.value_hours / self.cool_site.value_hours

    @property
    def raw_dose_ratio(self) -> float:
        return self.raw_max / self.raw_min if self.raw_min else float("inf")


def discard_edge_cells(
    cells: Iterable[AnalysisCell],
    ring: Sequence[LonLat],
    min_distance_m: float = C.EDGE_DISCARD_M,
) -> List[Tuple[AnalysisCell, float]]:
    """Mitigation step 2. Returns [(cell, distance_to_edge_m)] for survivors."""
    kept = []
    for cell in cells:
        distance = distance_to_boundary_m(cell.centroid, ring)
        if distance >= min_distance_m:
            kept.append((cell, distance))
    return kept


def percentile_value(values: Sequence[float], q: float) -> float:
    """Mitigation step 3. Linear interpolation between order statistics."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(max(q, 0.0), 100.0) / 100.0
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def select_sites(
    grid: AnalysisGrid,
    aoi: Mapping,
    edge_discard_m: float = C.EDGE_DISCARD_M,
    percentile_low: float = C.RANK_PERCENTILE_LOW,
    percentile_high: float = C.RANK_PERCENTILE_HIGH,
) -> SelectionReport:
    """Pick a cool and a hot site from an exceedance grid, defensibly.

    The returned sites are the cells whose values sit CLOSEST to the 5th and
    95th percentiles of the edge-discarded population, not the extremes, and
    not synthetic points at the percentile value.
    """
    ring = ring_of(aoi)
    survivors = discard_edge_cells(grid.cells, ring, edge_discard_m)
    if len(survivors) < 2:
        raise ImplausibleValue(
            "only %d cells survived the %.0f m edge discard out of %d. Either the "
            "AOI is too small for this buffer or the grid is degenerate."
            % (len(survivors), edge_discard_m, len(grid.cells))
        )

    values = [cell.value for cell, _ in survivors]
    low_value = percentile_value(values, percentile_low)
    high_value = percentile_value(values, percentile_high)

    def nearest(target: float) -> Tuple[AnalysisCell, float]:
        return min(survivors, key=lambda pair: abs(pair[0].value - target))

    cool_cell, cool_distance = nearest(low_value)
    hot_cell, hot_distance = nearest(high_value)
    if cool_cell.tile_id == hot_cell.tile_id:
        raise ImplausibleValue(
            "the 5th and 95th percentile resolve to the same cell. The grid has "
            "no usable spatial spread after edge discard"
        )

    ordered = sorted(values)

    def rank_of(value: float) -> float:
        below = sum(1 for v in ordered if v < value)
        return 100.0 * below / len(ordered)

    return SelectionReport(
        total_cells=len(grid.cells),
        discarded_edge_cells=len(grid.cells) - len(survivors),
        surviving_cells=len(survivors),
        edge_discard_m=edge_discard_m,
        percentile_low=percentile_low,
        percentile_high=percentile_high,
        value_at_low=low_value,
        value_at_high=high_value,
        cool_site=SiteCandidate(cool_cell, cool_distance, rank_of(cool_cell.value)),
        hot_site=SiteCandidate(hot_cell, hot_distance, rank_of(hot_cell.value)),
        raw_min=min(c.value for c in grid.cells),
        raw_max=max(c.value for c in grid.cells),
    )


# ---------------------------------------------------------------------------
# Mitigation step 4: satellite segmentation cross-check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentationCheck:
    impervious_share: float
    recognised_share: float
    unrecognised_classes: Tuple[str, ...]
    passes: bool
    note: str


def impervious_share(segments: Mapping[str, float]) -> Tuple[float, float, Tuple[str, ...]]:
    """(impervious share, recognised share, unrecognised class names).

    Contract section 7: class labels are ADE20K-style and open-ended, a
    landlocked downtown Phoenix tile returned "ship": 2.74. We SUM the classes
    we recognise rather than subtracting from 100, because the unrecognised
    remainder is not necessarily pervious and may not even be land cover
    ("sky" appears as a class).
    """
    total = sum(float(v) for v in segments.values()) or 1.0
    impervious = 0.0
    recognised = 0.0
    unknown = []
    for name, value in segments.items():
        key = name.strip().lower()
        if key in C.IMPERVIOUS_CLASSES:
            impervious += float(value)
            recognised += float(value)
        elif key in ("sky", "tree", "grass", "plant", "earth, ground", "water",
                     "field", "sand", "dirt track", "others", "mountain, mount",
                     "rock, stone", "hill", "palm, palm tree", "bush, shrub"):
            recognised += float(value)
        else:
            unknown.append(name)
    return impervious / total, recognised / total, tuple(sorted(unknown))


def cross_check_site(
    segments: Mapping[str, float],
    expect: str = "hot",
    minimum: float = C.MIN_IMPERVIOUS_SHARE_FOR_HOT_SITE,
) -> SegmentationCheck:
    """Does land cover explain why this cell ranks where it does?

    Mitigation step 4, and it is DIRECTIONAL. Contract section 5 states it for
    hot cells, "a genuine hot cell has high impervious share; if land cover
    does not explain it, it is an artifact", and the same logic run backwards
    validates a cool cell: a genuinely cool cell in a desert city should be
    vegetated or bare, not paved.

    Applying the hot test to a cool site is a category error that would report a
    correct selection as a failure, so `expect` is required to mean anything.
    """
    if expect not in ("hot", "cool"):
        raise ValueError("expect must be 'hot' or 'cool'; got %r" % expect)
    share, recognised, unknown = impervious_share(segments)

    if expect == "hot":
        passes = share >= minimum
        note = (
            "land cover explains the hot ranking: %.1f%% impervious" % (100 * share)
            if passes else
            "impervious share %.1f%% is below the %.0f%% floor, the HOT ranking is "
            "not explained by land cover and may be a boundary or interpolation "
            "artifact. Do not use this site without review."
            % (100 * share, 100 * minimum)
        )
    else:
        passes = share < minimum
        note = (
            "land cover corroborates the cool ranking: only %.1f%% impervious"
            % (100 * share)
            if passes else
            "impervious share %.1f%% is at or above the %.0f%% floor, yet this cell "
            "ranked COOL. Land cover does not corroborate the ranking, treat it "
            "as suspect." % (100 * share, 100 * minimum)
        )
    return SegmentationCheck(
        impervious_share=share,
        recognised_share=recognised,
        unrecognised_classes=unknown,
        passes=passes,
        note=note,
    )


def cross_check_hot_site(
    segments: Mapping[str, float],
    minimum: float = C.MIN_IMPERVIOUS_SHARE_FOR_HOT_SITE,
) -> SegmentationCheck:
    """Backwards-compatible alias for cross_check_site(..., expect="hot")."""
    return cross_check_site(segments, "hot", minimum)


def parcel_around(
    centre: LonLat, half_width_m: float = 500.0
) -> Dict:
    """A square AOI centred on a point, for the per-site filter_type=3 backfill.

    Site selection returns a single cell; the backfill needs a small polygon
    around it. 500 m half-width gives roughly the 1 km parcel the existing
    fixtures use, so cell counts and credit costs stay comparable.
    """
    lon_m, lat_m = metres_per_degree(centre[1])
    dlon = half_width_m / lon_m
    dlat = half_width_m / lat_m
    west, east = centre[0] - dlon, centre[0] + dlon
    south, north = centre[1] - dlat, centre[1] + dlat
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"centre_lon": centre[0], "centre_lat": centre[1]},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south], [east, south], [east, north],
                    [west, north], [west, south],
                ]],
            },
        }],
    }
