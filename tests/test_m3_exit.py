"""M3 exit test — site selection and the boundary-artifact mitigation.

SPEC.md, milestone M3:

    Exit: the boundary-artifact mitigation is in place — buffered AOI, 500 m
    edge discard, percentile ranking — and selected cells are cross-checked
    against satellite segmentation. No selected site sits within 500 m of an
    AOI edge.

All four parts are asserted against the REAL 46 931-cell exceedance grid
retrieved on 2026-08-24, via the committed selection record.
"""

from __future__ import annotations

import json

import pytest

from acclimate import constants as C
from acclimate import siteselection as ss
from acclimate.errors import ImplausibleValue
from acclimate.sources.fixtures import FixtureStore
from acclimate.sources.fortyguard import AnalysisCell, AnalysisGrid

SELECTION = "site_selection/phoenix_40c_selection.json"

METRO_AOI = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-112.20, 33.40], [-111.95, 33.40],
            [-111.95, 33.55], [-112.20, 33.55], [-112.20, 33.40]]]},
    }],
}


@pytest.fixture(scope="module")
def store():
    return FixtureStore()


@pytest.fixture(scope="module")
def selection(store):
    return store.load(SELECTION)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_metres_per_degree_is_sane_at_phoenix_latitude():
    lon_m, lat_m = ss.metres_per_degree(33.5)
    assert 110_000 < lat_m < 112_000
    assert 92_000 < lon_m < 94_000       # shrinks with cos(latitude)
    assert lon_m < lat_m


def test_ring_extraction_accepts_the_three_geojson_shapes():
    ring = ss.ring_of(METRO_AOI)
    assert len(ring) == 4                # closing vertex dropped
    feature = METRO_AOI["features"][0]
    assert ss.ring_of(feature) == ring
    assert ss.ring_of(feature["geometry"]) == ring
    with pytest.raises(ValueError):
        ss.ring_of({"type": "Point", "coordinates": [0, 0]})


def test_distance_to_boundary_is_zero_on_the_edge_and_large_at_the_centre():
    ring = ss.ring_of(METRO_AOI)
    assert ss.distance_to_boundary_m((-112.20, 33.475), ring) == pytest.approx(0.0, abs=1.0)
    centre = ss.centroid_of(ring)
    assert ss.distance_to_boundary_m(centre, ring) > 8000


# ---------------------------------------------------------------------------
# Mitigation step 1 — buffered AOI
# ---------------------------------------------------------------------------


def test_buffer_expands_the_aoi_by_the_requested_distance():
    buffered = ss.buffer_polygon(METRO_AOI, C.AOI_BUFFER_KM)
    original = ss.bbox_of(ss.ring_of(METRO_AOI))
    widened = ss.bbox_of(ss.ring_of(buffered))
    assert widened[0] < original[0] and widened[1] < original[1]
    assert widened[2] > original[2] and widened[3] > original[3]
    # Every original corner now sits at least the buffer distance inside.
    ring = ss.ring_of(buffered)
    for corner in ss.ring_of(METRO_AOI):
        assert ss.distance_to_boundary_m(corner, ring) >= C.AOI_BUFFER_KM * 1000 - 50


def test_the_committed_selection_used_a_buffered_aoi(selection):
    assert selection["buffer_km"] == C.AOI_BUFFER_KM
    buffered = ss.bbox_of(ss.ring_of(selection["aoi_buffered"]))
    original = ss.bbox_of(ss.ring_of(METRO_AOI))
    assert buffered[0] < original[0] and buffered[2] > original[2]


def test_buffer_rejects_a_negative_distance():
    with pytest.raises(ValueError):
        ss.buffer_polygon(METRO_AOI, -1.0)


# ---------------------------------------------------------------------------
# Mitigation step 2 — 500 m edge discard.  THE EXIT CRITERION.
# ---------------------------------------------------------------------------


def test_no_selected_site_sits_within_500_m_of_an_aoi_edge(selection):
    """THE M3 EXIT CRITERION, against the real retrieved grid."""
    ring = ss.ring_of(selection["aoi_buffered"])
    for name in ("cool_site", "hot_site"):
        site = selection[name]
        measured = ss.distance_to_boundary_m(tuple(site["centroid_lon_lat"]), ring)
        assert measured == pytest.approx(site["distance_to_edge_m"], abs=1.0)
        assert measured >= C.EDGE_DISCARD_M, (name, measured)
        # Both landed far clear of the threshold, not scraping past it.
        assert measured > 2000, (name, measured)


def test_the_edge_discard_actually_removed_cells(selection):
    assert selection["edge_discard_m"] == C.EDGE_DISCARD_M
    assert selection["discarded_edge_cells"] > 0
    assert selection["surviving_cells"] < selection["total_cells"]
    assert (selection["surviving_cells"] + selection["discarded_edge_cells"]
            == selection["total_cells"])
    fraction = selection["discarded_edge_cells"] / selection["total_cells"]
    assert 0.05 < fraction < 0.25, fraction


def test_discard_keeps_interior_cells_and_drops_edge_cells():
    ring = ss.ring_of(METRO_AOI)
    r = 0.0005
    def cell(i, lon, lat):
        return AnalysisCell(i, 1.0, 1.0,
                            ((lon - r, lat - r), (lon + r, lat - r),
                             (lon + r, lat + r), (lon - r, lat + r)))
    edge = cell(0, -112.1990, 33.4750)      # ~90 m from the west edge
    interior = cell(1, -112.0750, 33.4750)  # mid-AOI
    kept = ss.discard_edge_cells([edge, interior], ring, C.EDGE_DISCARD_M)
    assert [c.tile_id for c, _ in kept] == [1]


def test_the_documented_artifact_cells_would_have_been_discarded(store):
    """FORTYGUARD_API_CONTRACT.md section 5 records the top/bottom 5 cells of the
    original run as boundary artifacts. Confirm the mitigation catches them —
    that is the whole reason it exists."""
    fixture = json.load(open(store.path("heatmap/phoenix_40c_exceedance_sites.json")))
    ring = ss.ring_of(METRO_AOI)
    for group in ("top_5_highest_cells", "bottom_5_lowest_cells"):
        for entry in fixture[group]:
            distance = ss.distance_to_boundary_m(tuple(entry["centroid_lon_lat"]), ring)
            assert distance < C.EDGE_DISCARD_M, (group, entry["centroid_lon_lat"], distance)


# ---------------------------------------------------------------------------
# Mitigation step 3 — percentile ranking
# ---------------------------------------------------------------------------


def test_percentile_interpolates_between_order_statistics():
    values = [float(v) for v in range(101)]
    assert ss.percentile_value(values, 0) == 0.0
    assert ss.percentile_value(values, 100) == 100.0
    assert ss.percentile_value(values, 50) == pytest.approx(50.0)
    assert ss.percentile_value(values, 5) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        ss.percentile_value([], 50)


def test_selection_used_percentiles_not_extremes(selection):
    assert selection["cool_site"]["percentile"] == pytest.approx(
        C.RANK_PERCENTILE_LOW, abs=0.5)
    assert selection["hot_site"]["percentile"] == pytest.approx(
        C.RANK_PERCENTILE_HIGH, abs=0.5)
    # The chosen sites are strictly inside the raw range.
    assert selection["raw_min"] < selection["cool_site"]["value_hours"]
    assert selection["hot_site"]["value_hours"] < selection["raw_max"]


def test_percentile_ranking_shrinks_the_headline_dose_ratio(selection):
    """The number the writeup must correct.

    The project's headline 1.84x is a RAW min/max ratio — precisely the
    boundary-artifact statistic the contract warns against. After the mitigation
    the defensible ratio is materially smaller, and that is what may be claimed.
    """
    raw = selection["raw_max"] / selection["raw_min"]
    mitigated = (selection["hot_site"]["value_hours"]
                 / selection["cool_site"]["value_hours"])
    assert raw > mitigated
    assert 1.8 < raw < 2.0
    assert 1.15 < mitigated < 1.45


def test_select_sites_refuses_a_grid_with_no_interior():
    """A tiny AOI relative to the discard distance has nothing left to rank."""
    tiny = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-112.001, 33.001], [-112.000, 33.001],
            [-112.000, 33.002], [-112.001, 33.002], [-112.001, 33.001]]]}}]}
    r = 0.0001
    cells = tuple(
        AnalysisCell(i, float(i), float(i),
                     ((-112.0005 - r, 33.0015 - r), (-112.0005 + r, 33.0015 - r),
                      (-112.0005 + r, 33.0015 + r), (-112.0005 - r, 33.0015 + r)))
        for i in range(4)
    )
    grid = AnalysisGrid(cells, "exceedance", "hour", 336.0, 0, 0, None, None, None)
    with pytest.raises(ImplausibleValue):
        ss.select_sites(grid, tiny)


# ---------------------------------------------------------------------------
# Mitigation step 4 — satellite segmentation cross-check
# ---------------------------------------------------------------------------


def test_impervious_share_sums_recognised_classes_not_100_minus_other():
    """Contract section 7: labels are ADE20K-style and open-ended. A landlocked
    downtown Phoenix tile returned "ship": 2.74."""
    downtown = {"building": 72.7, "sky": 1.04, "road, route": 12.47,
                "sidewalk, pavement": 8.9, "skyscraper": 2.04,
                "ship": 2.74, "others": 0.11}
    share, recognised, unknown = ss.impervious_share(downtown)
    assert share == pytest.approx(0.961, abs=0.002)
    assert unknown == ("ship",)          # flagged, never a KeyError
    assert recognised < 1.0


def test_cross_check_is_directional():
    """Applying the hot test to a cool site would report a correct selection as
    a failure, so the direction has to be stated."""
    paved = {"road, route": 60.0, "building": 20.0, "tree": 20.0}
    green = {"tree": 60.0, "grass": 25.0, "building": 15.0}
    assert ss.cross_check_site(paved, "hot").passes
    assert not ss.cross_check_site(paved, "cool").passes
    assert ss.cross_check_site(green, "cool").passes
    assert not ss.cross_check_site(green, "hot").passes
    with pytest.raises(ValueError):
        ss.cross_check_site(paved, "sideways")


def test_selected_sites_are_corroborated_by_real_segmentation(store):
    """THE EXIT CRITERION's cross-check, against two live /v1/satellite calls.

    The hot site should be paved and the cool site vegetated. If land cover did
    not explain the ranking, the selection would be an artifact.
    """
    for name, expect in (("hot_site", "hot"), ("cool_site", "cool")):
        payload = store.load("satellite/%s_segmentation.json" % name)
        segments = ((payload.get("data") or {}).get("result") or {}) \
            .get("segmentation", {}).get("segments", {})
        assert segments, name
        check = ss.cross_check_site(segments, expect)
        assert check.passes, (name, check.note)
        assert check.recognised_share > 0.95, (name, check.unrecognised_classes)
    hot = store.load("satellite/hot_site_segmentation.json")
    hot_segments = ((hot.get("data") or {}).get("result") or {}) \
        .get("segmentation", {}).get("segments", {})
    cool = store.load("satellite/cool_site_segmentation.json")
    cool_segments = ((cool.get("data") or {}).get("result") or {}) \
        .get("segmentation", {}).get("segments", {})
    hot_share = ss.impervious_share(hot_segments)[0]
    cool_share = ss.impervious_share(cool_segments)[0]
    assert hot_share > cool_share, (hot_share, cool_share)


def test_unknown_classes_never_raise():
    weird = {"ship": 40.0, "unicorn": 30.0, "road, route": 30.0}
    check = ss.cross_check_site(weird, "hot")
    assert check.unrecognised_classes == ("ship", "unicorn")
    assert check.impervious_share == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Parcel construction for the per-site backfill
# ---------------------------------------------------------------------------


def test_parcel_is_square_and_centred():
    centre = (-112.0740, 33.4484)
    parcel = ss.parcel_around(centre, 500.0)
    ring = ss.ring_of(parcel)
    west, south, east, north = ss.bbox_of(ring)
    assert west < centre[0] < east
    assert south < centre[1] < north
    lon_m, lat_m = ss.metres_per_degree(centre[1])
    assert (east - west) * lon_m == pytest.approx(1000.0, abs=1.0)
    assert (north - south) * lat_m == pytest.approx(1000.0, abs=1.0)
