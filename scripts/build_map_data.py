"""Derive a compact exceedance raster for the Map view.

    python scripts/build_map_data.py

The cached exceedance response is 46 931 cells / 16 MB and gitignored. Shipping
it to the browser as GeoJSON polygons would be absurd for a choropleth that is
ultimately a grid of coloured rectangles, so this bins it into a raster: bounds,
width, height, and a flat array of mean exceedance hours per bin.

Canvas draws that directly with no library and no basemap tiles, which is what
keeps the demo offline (SPEC.md hard constraint 6).

Cells inside the 500 m edge-discard band are marked null rather than dropped, so
the map can SHOW the discarded band instead of quietly hiding it, the boundary
artifact is part of the story, not an embarrassment.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sunup import constants as C  # noqa: E402
from sunup import siteselection as ss  # noqa: E402
from sunup.sources.fixtures import FixtureStore  # noqa: E402
from sunup.sources.fortyguard import parse_analysis_grid  # noqa: E402

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "data", "metro_exceedance_raw.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "app", "data", "map.js")

BINS_X = 132
BINS_Y = 92
WINDOW_HOURS = 24.0 * 14

# One class per --heat-* stop in web/tokens.css. Named here only to fix the
# COUNT; the colours themselves stay in the stylesheet.
HEAT_STOPS = ("--heat-0", "--heat-1", "--heat-2", "--heat-3", "--heat-4", "--heat-5")

# Measured: not assumed, by scripts/audit_resolution.py, which runs the
# identical statistic on every layer over the identical lattice.
#
# Settled by a metro-extent filter_type=1 retrieval. A single INSTANT and the
# 14-day hour count are equally smooth over the same 250x186 grid, so the
# smoothness is NOT an artifact of aggregating 336 hours, the instantaneous
# field is itself smooth. At 14:00 on a day above 40 degC the entire Phoenix
# metro spans 1.02 degC.
TILE_RESOLUTION_M = 101
EFFECTIVE_RESOLUTION_M = 2000

# Lag-1 roughness: mean |difference| between neighbouring tiles, both as an
# absolute value and as a percentage of the layer's own range. Compare the
# percentage ONLY at matched extent; normalised by a window-dependent range it
# measures the window rather than the field.
LAG1_PCT_OF_RANGE = 0.40            # 14-day exceedance count, metro extent
SNAPSHOT_LAG1_PCT_OF_RANGE = 0.42   # single instant, SAME metro lattice
SNAPSHOT_SPAN_C = 1.02              # whole metro, one instant, degC
BLUR_500M_VARIANCE_KEPT_PCT = 98.9      # exceedance
SNAPSHOT_BLUR_500M_VARIANCE_KEPT_PCT = 98.6  # single instant


def main():
    if not os.path.exists(RAW):
        raise SystemExit(
            "No raw exceedance grid at %s.\n"
            "It is gitignored (16 MB). Re-fetch with "
            "`python scripts/m3_fetch.py --exceedance`." % os.path.relpath(RAW))

    store = FixtureStore()
    selection = store.load("site_selection/phoenix_40c_selection.json")
    aoi = selection["aoi_buffered"]
    ring = ss.ring_of(aoi)
    west, south, east, north = ss.bbox_of(ring)

    with open(RAW, "r", encoding="utf-8") as fh:
        grid = parse_analysis_grid(json.load(fh), WINDOW_HOURS)

    sums = [0.0] * (BINS_X * BINS_Y)
    counts = [0] * (BINS_X * BINS_Y)
    edge = [0] * (BINS_X * BINS_Y)

    for cell in grid.cells:
        lon, lat = cell.centroid
        bx = int((lon - west) / (east - west) * BINS_X)
        by = int((north - lat) / (north - south) * BINS_Y)   # row 0 = north
        if not (0 <= bx < BINS_X and 0 <= by < BINS_Y):
            continue
        index = by * BINS_X + bx
        sums[index] += cell.value
        counts[index] += 1
        if ss.distance_to_boundary_m((lon, lat), ring) < C.EDGE_DISCARD_M:
            edge[index] += 1

    values = []
    discarded = []
    for index in range(BINS_X * BINS_Y):
        if counts[index] == 0:
            values.append(None)
            discarded.append(0)
        else:
            values.append(round(sums[index] / counts[index], 2))
            # A bin is "in the discard band" when most of its cells are.
            discarded.append(1 if edge[index] * 2 > counts[index] else 0)

    present = [v for v in values if v is not None]

    # QUANTILE BREAKS, computed on the SOURCE cells rather than the raster, so
    # the classing describes the data and not the binning.
    #
    # Equal-interval classing put 81% of cells in the top two classes and made
    # the whole metro one flat smear: the distribution is strongly left-skewed
    # (p5 79.3 h, p50 96.7 h, max 106.9 h), so equal steps in value are nothing
    # like equal steps in area. Six classes, one per --heat-* stop, each holding
    # about a sixth of the cells.
    ordered = sorted(c.value for c in grid.cells)
    classes = len(HEAT_STOPS)
    breaks = [round(ordered[int(k / classes * (len(ordered) - 1))], 2)
              for k in range(1, classes)]

    # EFFECTIVE RESOLUTION OF THIS LAYER. The tiles are 101 m, but the
    # exceedance field is far smoother: a 500 m box blur destroys 1.1% of its
    # variance and neighbouring tiles differ by 0.40% of the range on average.
    # Rendering it as if it resolved streets would be a lie told with pixels, so
    # the number travels with the data and is printed on the map.
    #
    # AND IT IS NOT THE AGGREGATION. A metro-extent single-hour retrieval scores
    # 0.42% on the same lattice against exceedance's 0.40%, and keeps 98.6% of
    # its variance through a 500 m blur against 98.9%. The instantaneous field
    # is just as smooth as the 14-day count built from it.
    payload = {
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "width": BINS_X,
        "height": BINS_Y,
        "values": values,
        "discarded": discarded,
        "min": min(present),
        "max": max(present),
        "breaks": breaks,
        "classOccupancyPct": round(100.0 / len(HEAT_STOPS), 1),
        "effectiveResolutionM": EFFECTIVE_RESOLUTION_M,
        "tileResolutionM": TILE_RESOLUTION_M,
        "resolutionAudit": {
            "lag1PctOfRange": LAG1_PCT_OF_RANGE,
            "blur500VarianceKeptPct": BLUR_500M_VARIANCE_KEPT_PCT,
            "snapshotLag1PctOfRange": SNAPSHOT_LAG1_PCT_OF_RANGE,
            "snapshotBlur500VarianceKeptPct": SNAPSHOT_BLUR_500M_VARIANCE_KEPT_PCT,
            "snapshotSpanC": SNAPSHOT_SPAN_C,
            "script": "scripts/audit_resolution.py",
        },
        "windowHours": WINDOW_HOURS,
        "thresholdC": selection["threshold_c"],
        "sourceCells": len(grid.cells),
        "edgeDiscardM": C.EDGE_DISCARD_M,
        "sites": {
            name: {
                "lon": selection[name]["centroid_lon_lat"][0],
                "lat": selection[name]["centroid_lon_lat"][1],
                "valueHours": selection[name]["value_hours"],
                "percentile": selection[name]["percentile"],
                "distanceToEdgeM": selection[name]["distance_to_edge_m"],
            }
            for name in ("cool_site", "hot_site")
        },
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("/* GENERATED by scripts/build_map_data.py - do not edit. */\n")
        fh.write("window.MAP_DATA = ")
        json.dump(payload, fh, separators=(",", ":"))
        fh.write(";\n")

    size = os.path.getsize(OUT)
    print("wrote %s (%.0f KB)" % (os.path.relpath(OUT), size / 1024))
    print("  %d source cells -> %dx%d raster, %d populated bins"
          % (len(grid.cells), BINS_X, BINS_Y, len(present)))
    print("  exceedance %.2f .. %.2f h of %.0f  (%d bins in the discard band)"
          % (payload["min"], payload["max"], WINDOW_HOURS, sum(discarded)))
    edges = [round(min(ordered), 2)] + breaks + [round(max(ordered), 2)]
    print("  quantile breaks (%d classes, %.1f%% each): %s"
          % (len(HEAT_STOPS), payload["classOccupancyPct"],
             " | ".join("%.1f" % e for e in edges)))
    counts_per_class = [0] * len(HEAT_STOPS)
    for value in ordered:
        k = 0
        while k < len(breaks) and value >= breaks[k]:
            k += 1
        counts_per_class[k] += 1
    print("  realised occupancy: %s"
          % [round(100.0 * c / len(ordered), 1) for c in counts_per_class])


if __name__ == "__main__":
    main()
