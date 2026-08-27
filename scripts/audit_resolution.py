"""How much spatial structure does FortyGuard's temperature product actually carry?

    python scripts/audit_resolution.py

WHY THIS EXISTS
---------------
The M4 map renders the 14-day exceedance layer, and that layer is extremely
smooth: a 500 m box blur removes about 1% of its variance. Concluding from that
alone that "the API's temperature field has no street-scale structure" does not
follow, because EXCEEDANCE IS A COUNT OVER 336 HOURS and counting is a low-pass
filter. A smooth aggregate is weak evidence about the instant underneath it.

So this measures every layer identically:

  * filter_type=1, a single INSTANT (temporal min == avg == max)
  * filter_type=3, a DAILY aggregate (carries a diurnal range)
  * the 14-day exceedance count, at metro extent
  * a metro-extent single instant, retrieved specifically to settle this

Three statistics:

  LAG-1 ABS         mean |difference| between neighbouring tiles, in the
                    layer's own units. THE ONLY ONE COMPARABLE ACROSS WINDOWS
                    OF DIFFERENT SIZE.
  LAG-1 % OF RANGE  the same, normalised. Comparable only at MATCHED extent --
                    see the warning below.
  BLUR RETENTION    fraction of variance surviving a box blur. If a 500 m blur
                    costs nothing, there was nothing below 500 m to lose.

THE TRAP THIS SCRIPT FELL INTO
------------------------------
Run first on parcel fixtures (0.8 x 1.1 km) and the metro exceedance grid
(25 x 19 km), the "% of range" column said a single instant was ~15x rougher
than the aggregate, and the conclusion drawn was that aggregation caused the
smoothness. That was wrong. It compared two different crops of the same field:
the absolute neighbour difference is ~0.004-0.006 degC in BOTH, and only the
denominator moved, because a 0.8 km window spans 0.09 degC while a 25 km window
spans 1.02 degC.

Retrieving a metro-extent single instant settled it. Over the identical 250x186
lattice, a single instant and a 14-day hour count are equally smooth: lag-1
0.42% against 0.40%, blur retention 98.6% against 98.9%. Aggregation is not the
cause. The instantaneous field is itself smooth.

Normalise by a window-dependent quantity and you will measure your window.
"""

from __future__ import annotations

import glob
import json
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
FIXTURES = os.path.join(ROOT, "fixtures")
EXCEEDANCE_RAW = os.path.join(ROOT, "data", "metro_exceedance_raw.json")
SNAPSHOT_RAW = os.path.join(ROOT, "data", "metro_snapshot_raw.json")

LAT = 33.45


# ---------------------------------------------------------------------------
# Grid reconstruction
# ---------------------------------------------------------------------------


def lattice_from(cells):
    """Rebuild a raster from (lon, lat, value, footprint_w, footprint_h).

    The tiles are NOT aligned to a lat/lon lattice, every centroid is distinct
    at six decimals, so the grid must come from each tile's own footprint.
    Indexing on rounded centroids yields a degenerate NxN lattice of pitch ~1 m
    and silently produces meaningless statistics.
    """
    fw = st.median([c[3] for c in cells])
    fh = st.median([c[4] for c in cells])
    west = min(c[0] for c in cells) - fw / 2
    north = max(c[1] for c in cells) + fh / 2
    east = max(c[0] for c in cells) + fw / 2
    south = min(c[1] for c in cells) - fh / 2
    width = max(1, int(round((east - west) / fw)))
    height = max(1, int(round((north - south) / fh)))
    grid = [None] * (width * height)
    for lon, lat, value, _, _ in cells:
        x = min(width - 1, max(0, int((lon - west) / fw)))
        y = min(height - 1, max(0, int((north - lat) / fh)))
        grid[y * width + x] = value
    pitch = fw * 111_320 * math.cos(math.radians(LAT))
    return grid, width, height, pitch


def cells_from_features(features, key="average_temperature"):
    cells = []
    for feature in features:
        value = feature.get("properties", {}).get(key)
        if value is None:
            continue
        ring = feature["geometry"]["coordinates"][0]
        lon = sum(c[0] for c in ring[:-1]) / (len(ring) - 1)
        lat = sum(c[1] for c in ring[:-1]) / (len(ring) - 1)
        cells.append((lon, lat, value,
                      max(c[0] for c in ring) - min(c[0] for c in ring),
                      max(c[1] for c in ring) - min(c[1] for c in ring)))
    return cells


def features_of(doc):
    body = doc.get("result", doc) if isinstance(doc, dict) else {}
    map_data = body.get("map_data") if isinstance(body, dict) else None
    return map_data.get("features") if isinstance(map_data, dict) else None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def lag_roughness(grid, width, height, lag):
    deltas = []
    for y in range(height):
        for x in range(width - lag):
            a, b = grid[y * width + x], grid[y * width + x + lag]
            if a is not None and b is not None:
                deltas.append(abs(a - b))
    for x in range(width):
        for y in range(height - lag):
            a, b = grid[y * width + x], grid[(y + lag) * width + x]
            if a is not None and b is not None:
                deltas.append(abs(a - b))
    return st.mean(deltas) if deltas else None


def box_blur(grid, width, height, radius):
    out = [None] * (width * height)
    for y in range(height):
        for x in range(width):
            if grid[y * width + x] is None:
                continue
            acc = count = 0
            for yy in range(max(0, y - radius), min(height, y + radius + 1)):
                for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                    v = grid[yy * width + xx]
                    if v is not None:
                        acc += v
                        count += 1
            out[y * width + x] = acc / count
    return out


def variance(grid):
    return st.pvariance([v for v in grid if v is not None])


def profile(label, units, grid, width, height, pitch, blur_m=500.0):
    values = [v for v in grid if v is not None]
    span = max(values) - min(values)
    lag1 = lag_roughness(grid, width, height, 1)
    radius = max(1, int(round((blur_m / pitch - 1) / 2)))
    blurred = box_blur(grid, width, height, radius)
    retained = 100 * variance(blurred) / variance(grid) if variance(grid) else float("nan")
    print("  %-38s %5dx%-4d %4.0f m %8.3f %-4s %9.4f %7.2f%% %7.1f%%"
          % (label, width, height, pitch, span, units, lag1,
             100 * lag1 / span if span else 0, retained))
    return span, lag1, retained


# ---------------------------------------------------------------------------


def index_by_file():
    with open(os.path.join(FIXTURES, "INDEX.json"), "r", encoding="utf-8") as fh:
        return {entry["file"]: entry for entry in json.load(fh)}


def main():
    index = index_by_file()

    print(__doc__.split("WHY THIS EXISTS")[0].strip())
    print()
    print("  %-38s %-11s %-6s %-13s %-9s %-8s %s"
          % ("layer", "lattice", "pitch", "range", "lag-1 abs",
             "lag-1", "var. kept"))
    print("  %-38s %-11s %-6s %-13s %-9s %-8s %s"
          % ("", "", "", "", "(units)", "(% range)", "(blur)"))
    print("  " + "-" * 96)

    groups = {1: [], 3: []}
    for path in sorted(glob.glob(os.path.join(FIXTURES, "heatmap", "*.json"))):
        rel = "heatmap/" + os.path.basename(path)
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        features = features_of(doc)
        if not features:
            continue
        cells = cells_from_features(features)
        if len(cells) < 16:
            continue
        filter_type = index.get(rel, {}).get("kwargs", {}).get("filter_type")
        groups.setdefault(filter_type, []).append((rel, cells))

    for filter_type, title in (
            (1, "SINGLE INSTANT  (filter_type=1, temporal min == avg == max)"),
            (3, "DAILY AGGREGATE (filter_type=3, carries a diurnal range)")):
        entries = groups.get(filter_type) or []
        if not entries:
            continue
        print("\n  %s" % title)
        for rel, cells in entries:
            grid, width, height, pitch = lattice_from(cells)
            profile(os.path.basename(rel), "degC", grid, width, height, pitch,
                    blur_m=300.0)

    if os.path.exists(SNAPSHOT_RAW):
        from sunup.sources.fortyguard import parse_temperature_grid  # noqa: E402
        print()
        print("  METRO-EXTENT SINGLE INSTANT (filter_type=1, 14:00)")
        with open(SNAPSHOT_RAW, "r", encoding="utf-8") as fh:
            temps = parse_temperature_grid(json.load(fh))
        cells = [(c.centroid[0], c.centroid[1], c.mean_c,
                  max(p[0] for p in c.ring) - min(p[0] for p in c.ring),
                  max(p[1] for p in c.ring) - min(p[1] for p in c.ring))
                 for c in temps.cells]
        grid, width, height, pitch = lattice_from(cells)
        profile("metro_snapshot 2026-08-08 14:00", "degC",
                grid, width, height, pitch, blur_m=500.0)
    else:
        print()
        print("  Metro single-hour snapshot not present (gitignored, 20 MB).")
        print("  Fetch with `python scripts/m3_fetch.py --metro-snapshot`.")

    if os.path.exists(EXCEEDANCE_RAW):
        from sunup.sources.fortyguard import parse_analysis_grid  # noqa: E402
        print("\n  14-DAY EXCEEDANCE COUNT (the layer the map renders)")
        with open(EXCEEDANCE_RAW, "r", encoding="utf-8") as fh:
            analysis = parse_analysis_grid(json.load(fh), 336.0)
        cells = [(c.centroid[0], c.centroid[1], c.value,
                  max(p[0] for p in c.ring) - min(p[0] for p in c.ring),
                  max(p[1] for p in c.ring) - min(p[1] for p in c.ring))
                 for c in analysis.cells]
        grid, width, height, pitch = lattice_from(cells)
        profile("metro_exceedance (hours above 40 degC)", "h",
                grid, width, height, pitch, blur_m=500.0)
    else:
        print("\n  14-day exceedance grid not present (gitignored, 16 MB).")
        print("  Re-fetch with `python scripts/m3_fetch.py --exceedance` to include it.")

    print("""
  READING THIS
  ------------
  Lag-1 roughness is mean |difference| between neighbouring tiles as a share of
  the layer's own range. Near zero means a smooth differentiable field; a field
  with real edges scores high. Variance-kept is how much survives a box blur --
  if a blur costs nothing, there was nothing at that scale to lose.

  COMPARE ONLY AT MATCHED EXTENT. The "% of range" column is not comparable
  across windows of different size, and reading it that way is a trap this
  script walked into once already. The parcel fixtures score 5.6-7.0% against
  the metro snapshot's 0.42%, which looks like the small window being fifteen
  times rougher. It is not. The ABSOLUTE lag-1 difference is ~0.004-0.006 degC
  in both; only the denominator moved, because a 0.8 km window spans 0.09 degC
  and a 25 km window spans 1.02 degC. Same field, different crop.

  At matched extent the answer is unambiguous. Over the identical 250x186
  lattice, a SINGLE INSTANT and a 14-DAY HOUR COUNT are equally smooth --
  lag-1 0.42% against 0.40%, blur retention 98.6% against 98.9%. Aggregation is
  therefore NOT the source of the smoothness; the instantaneous field is itself
  smooth. Neighbouring 100 m tiles differ by about 0.004 degC.

  What that means in absolute terms: at 14:00 on a day exceeding 40 degC, the
  whole Phoenix metro spans 1.02 degC. The yardstick is taken from the same API
  rather than from an outside figure, its daily min/max product (filter_type=3,
  the rows above) puts the diurnal range at a SINGLE POINT at 5.8-11.4 degC,
  mean 8.5. One location changes about eight times more over a day than the
  entire 25 x 19 km metro varies at any one instant. Whatever these 100 m tiles
  are carrying, it does not resolve roads, parks, or the Salt River corridor.
""")


if __name__ == "__main__":
    main()
